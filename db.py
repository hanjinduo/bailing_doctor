"""
数据库访问层：默认 MySQL，可通过 DATABASE_URL / DB_ENGINE 显式切回 SQLite，
并完整保留原有 PostgreSQL 分支。

引擎判定（自上而下，命中即停）：
    1. DATABASE_URL 以 postgres:// 或 postgresql:// 开头   -> PostgreSQL
    2. DATABASE_URL 以 sqlite 开头                          -> SQLite（bailing.db）
    3. DATABASE_URL 以 mysql:// 开头                        -> MySQL（参数取自 URL）
    4. DB_ENGINE=sqlite / mysql / postgresql                -> 指定引擎
    5. 都没设置                                             -> MySQL（默认）

MySQL 默认参数（均可用环境变量覆盖）：
    MYSQL_HOST=127.0.0.1   MYSQL_PORT=3306   MYSQL_DB=bailing_doctor   MYSQL_USER=root
    口令：MYSQL_PWD > MYSQL_PASSWORD > 本机 phpstudy 默认口令（回退时打 WARNING）
    字符集：utf8mb4（表引擎 InnoDB，排序 utf8mb4_unicode_ci）

对上层只暴露 rows / one / run / columns / init_schema / exec_script / tx，
业务代码统一用 ? 占位符，由本层按方言转换，切换数据库不改业务代码。
"""
import contextlib
import logging
import os
import re
import sqlite3
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.environ.get("SQLITE_PATH") or os.path.join(ROOT, "bailing.db")
URL = os.environ.get("DATABASE_URL", "").strip()
DB_ENGINE = os.environ.get("DB_ENGINE", "").strip().lower()
NO_ID_TABLES = {"cart"}   # 复合主键 (user_id, med_id)，没有 id 列

MYSQL_FALLBACK_PWD = "root"   # phpstudy 自带 MySQL 的默认口令
MYSQL_DEFAULTS = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3306") or 3306),
    "user": os.environ.get("MYSQL_USER", "root"),
    "database": os.environ.get("MYSQL_DB", "bailing_doctor"),
    "password": "",
    "pwd_from": "",
}


def _resolve_engine():
    """按上方优先级判定引擎，返回 (engine, sqlite_path)"""
    low = URL.lower()
    if low.startswith(("postgres://", "postgresql://")):
        return "postgresql", SQLITE_PATH
    if low.startswith("sqlite"):
        rest = URL.split(":", 1)[1] if ":" in URL else ""
        if rest.startswith("//"):
            rest = rest[2:]
        rest = rest.lstrip("/")
        p = unquote(rest.split("?")[0])
        if p in ("", ":memory:"):
            return "sqlite", SQLITE_PATH
        if not os.path.isabs(p):
            p = os.path.join(ROOT, p)
        return "sqlite", p
    if low.startswith("mysql"):
        return "mysql", SQLITE_PATH
    if DB_ENGINE in ("sqlite", "sqlite3"):
        return "sqlite", SQLITE_PATH
    if DB_ENGINE in ("postgres", "postgresql", "pg"):
        return "postgresql", SQLITE_PATH
    if DB_ENGINE == "mysql":
        return "mysql", SQLITE_PATH
    return "mysql", SQLITE_PATH          # 默认：MySQL


ENGINE, SQLITE_PATH = _resolve_engine()
MYSQL = ENGINE == "mysql"
PG = ENGINE == "postgresql"
SQLITE = ENGINE == "sqlite"
LABEL = (MYSQL_DEFAULTS["database"] if MYSQL else
         URL if PG else os.path.basename(SQLITE_PATH))

_log = logging.getLogger("bailing.db")
_log.setLevel(logging.INFO)
_warned = set()
_engine_logged = [False]


def _log_engine_once():
    """首次建连时自报一次引擎与目标库，便于运维确认当前实际方言（app.py 的启动日志行未改）"""
    if _engine_logged[0]:
        return
    _engine_logged[0] = True
    try:
        if MYSQL:
            conf = _mysql_conf()
            _log.info("engine=mysql dsn=%s:%s/%s user=%s charset=utf8mb4 pwd_from=%s",
                      conf["host"], conf["port"], conf["database"], conf["user"],
                      conf["pwd_from"] or "-")
        elif PG:
            _log.info("engine=postgresql url=%s", URL)
        else:
            _log.info("engine=sqlite path=%s", SQLITE_PATH)
    except Exception:
        pass


def _mysql_conf():
    """MySQL 连接参数：mysql:// URL 优先，其次 MYSQL_* 环境变量，口令按优先级回退"""
    conf = dict(MYSQL_DEFAULTS)
    if URL.lower().startswith("mysql"):
        u = urlparse(URL)
        if u.hostname:
            conf["host"] = u.hostname
        if u.port:
            conf["port"] = int(u.port)
        if u.username:
            conf["user"] = unquote(u.username)
        if u.password:
            conf["password"] = unquote(u.password)
            conf["pwd_from"] = "DATABASE_URL"
        if u.path and len(u.path) > 1:
            conf["database"] = u.path.lstrip("/")
    if not conf["password"]:
        for key in ("MYSQL_PWD", "MYSQL_PASSWORD"):
            v = os.environ.get(key)
            if v:
                conf["password"] = v
                conf["pwd_from"] = key
                break
    if not conf["password"]:
        conf["password"] = MYSQL_FALLBACK_PWD
        conf["pwd_from"] = "phpstudy-default"
        if "fallback" not in _warned:
            _warned.add("fallback")
            _log.warning("WARNING mysql password env MYSQL_PWD/MYSQL_PASSWORD 未设置，"
                         "回退本机 phpstudy 默认口令（生产环境请设置环境变量）")
    return conf


# ==================== 方言适配：标识符 / 类型 / 索引 ====================
# MySQL 8.0 保留字做列名必须反引号（本项目 slots.left、notices.read 两处命中）；
# 该转换在方言层完成，业务 SQL 不需要改。
MYSQL_RESERVED = {"left", "read", "usage"}   # 本库列名与 MySQL 保留字的全部交集

# MySQL 不允许 TEXT/BLOB 参与索引与唯一键，也不允许 TEXT 带默认值。
# 参与索引或唯一键、或带默认值的列按此表窄化为 VARCHAR；其余长文本保持 TEXT 以免截断问诊内容。
MYSQL_TEXT_TYPES = {
    ("users", "phone"): "VARCHAR(32)",        # TEXT UNIQUE -> VARCHAR UNIQUE
    ("users", "avatar"): "VARCHAR(64)",       # TEXT DEFAULT '👤'
    ("users", "sex"): "VARCHAR(16)",
    ("chats", "status"): "VARCHAR(32)",       # idx_chats_user(user_id, status)
    ("orders", "status"): "VARCHAR(32)",      # idx_orders_user(user_id, status)
    ("orders", "kind"): "VARCHAR(32)",
    ("rxs", "status"): "VARCHAR(32)",         # idx_rxs_user(user_id, status)
    ("coupons", "status"): "VARCHAR(32)",     # idx_coupons_user(user_id, status)
    ("appts", "status"): "VARCHAR(32)",       # idx_appts_user(user_id, status)
    ("kb_chunks", "mode"): "VARCHAR(32)",     # idx_kb_dim(dim, mode)
    ("chats", "created"): "VARCHAR(32)",      # idx_chats_created(created)
    ("orders", "created"): "VARCHAR(32)",     # idx_orders_created(created)
    ("appts", "day"): "VARCHAR(16)",          # idx_appts_slot(doctor_id, day)
    ("slots", "day"): "VARCHAR(16)",          # idx_slots_doc(doctor_id, day)
    ("meds", "cat"): "VARCHAR(32)",           # idx_meds_cat(cat, rx)
}


def _scan_quoted(sql, i):
    """从 i 处的引号开始跳过整段字符串 / 反引号标识符，返回结束下标+1"""
    q = sql[i]
    n = len(sql)
    j = i + 1
    while j < n:
        if sql[j] == "\\" and q != "`":
            j += 2
            continue
        if sql[j] == q:
            if j + 1 < n and sql[j + 1] == q:   # 转义写法的重复引号
                j += 2
                continue
            return j + 1
        j += 1
    return n


def _quote_ident(sql):
    """给 MySQL 保留字列名补反引号（不进入字符串字面量、不误伤 LEFT( 这类函数调用）"""
    out, i, n = [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"', "`"):
            j = _scan_quoted(sql, i)
            out.append(sql[i:j])
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] in "_$"):
                j += 1
            word = sql[i:j]
            nxt = sql[j] if j < n else ""
            if word.lower() in MYSQL_RESERVED and nxt != "(":
                out.append("`%s`" % word)
            else:
                out.append(word)
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_sql(sql):
    """按分号切语句（跳过引号内的分号）"""
    stmts, buf, i, n = [], [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"', "`"):
            j = _scan_quoted(sql, i)
            buf.append(sql[i:j])
            i = j
            continue
        if ch == ";":
            stmts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    stmts.append("".join(buf))
    return [s.strip() for s in stmts if s.strip()]


def _split_cols(inner):
    """切分 CREATE TABLE 括号内的列定义（跳过括号与引号内的逗号）"""
    items, buf, depth, i, n = [], [], 0, 0, len(inner)
    while i < n:
        ch = inner[i]
        if ch in ("'", '"', "`"):
            j = _scan_quoted(inner, i)
            buf.append(inner[i:j])
            i = j
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if "".join(buf).strip():
        items.append("".join(buf))
    return items


def _quote_paren_idents(item):
    """把 PRIMARY KEY(...) / UNIQUE(...) / KEY xxx(...) 括号内的列名逐个加反引号"""
    m = re.match(r"(.*?\()([^()]*)(\)[\s\S]*)$", item.strip(), re.S)
    if not m:
        return _quote_ident(item)
    cols = ", ".join("`%s`" % c.strip() for c in m.group(2).split(",") if c.strip())
    return _quote_ident(m.group(1) + cols + m.group(3))


def _mysql_col(table, item):
    """单列定义方言转换：TEXT 窄化、REAL->DOUBLE、BLOB->MEDIUMBLOB、AUTOINCREMENT->AUTO_INCREMENT"""
    it = item.strip()
    if not it:
        return it
    up = it.upper()
    if up.startswith(("PRIMARY KEY", "UNIQUE KEY", "UNIQUE(", "KEY ", "INDEX ",
                      "CONSTRAINT", "FOREIGN KEY", "CHECK")):
        return _quote_paren_idents(it)
    m = re.match(r"(`?)([A-Za-z_]\w*)\1(\s+[\s\S]*)$", it)
    if not m:
        return _quote_ident(it)
    name, rest = m.group(2), m.group(3).strip()
    up_rest = rest.upper()
    if up_rest.startswith("INTEGER PRIMARY KEY AUTOINCREMENT"):
        rest = "INT PRIMARY KEY AUTO_INCREMENT"
        return "%s %s" % (name, rest)
    toks = rest.split()
    if not toks:
        return _quote_ident(it)
    first = toks[0].upper()
    tail = rest[len(toks[0]):]
    if first == "TEXT":
        if "UNIQUE" in up_rest:
            newtype = MYSQL_TEXT_TYPES.get((table, name.lower()), "VARCHAR(64)")
        elif "DEFAULT" in up_rest:
            newtype = MYSQL_TEXT_TYPES.get((table, name.lower()), "VARCHAR(255)")
        else:
            newtype = MYSQL_TEXT_TYPES.get((table, name.lower()), "TEXT")
        rest = newtype + tail
    elif first == "BLOB":
        rest = "MEDIUMBLOB" + tail
    elif first == "REAL":
        rest = "DOUBLE" + tail
    elif first == "INTEGER":
        rest = "INT" + tail
    return ("`%s` %s" % (name, rest)).strip()


def _mysql_create_table(stmt):
    """CREATE TABLE 语句方言转换（含引擎/字符集）"""
    m = re.search(r"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?`?([A-Za-z_]\w*)`?", stmt, re.I)
    if not m:
        return _quote_ident(stmt)
    table = m.group(2).lower()
    brace = stmt.find("(", m.end())
    if brace < 0:
        return _quote_ident(stmt)
    close = stmt.rfind(")")
    if close < brace:
        return _quote_ident(stmt)
    inner = stmt[brace + 1:close]
    tail = stmt[close + 1:].strip()
    cols = [_mysql_col(table, it) for it in _split_cols(inner)]
    body = ", ".join(c.strip() for c in cols)
    if not tail:
        tail = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
    return "%s(%s) %s" % (stmt[:brace], body, tail)


def _mysql_type_fix(sql):
    """ALTER TABLE 等非建表语句里的类型修正"""
    sql = re.sub(r"\bTEXT(\s+DEFAULT)", r"VARCHAR(255)\1", sql, flags=re.I)
    sql = re.sub(r"\bREAL\b", "DOUBLE", sql, flags=re.I)
    sql = re.sub(r"\bBLOB\b", "MEDIUMBLOB", sql, flags=re.I)
    return sql


def ddl_for(sql):
    """建表语句方言转换：
    SQLite（原样） / PostgreSQL（AUTOINCREMENT->SERIAL）/ MySQL（类型窄化 + 引擎字符集）
    """
    if PG:
        return sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    if MYSQL:
        out = []
        for s in _split_sql(sql):
            up = s.upper()
            if up.startswith("CREATE TABLE"):
                out.append(_mysql_create_table(s))
            elif up.startswith(("ALTER TABLE", "CREATE ")):
                out.append(_quote_ident(_mysql_type_fix(s)))
            else:
                out.append(s)
        return ";\n".join(out)
    return sql


def _sql(sql):
    """占位符与标识别名方言转换：SQLite 原样；PG/MySQL 的 ? -> %s"""
    if SQLITE:
        return sql
    s = sql.replace("?", "%s")
    if MYSQL:
        up = s.lstrip().upper()
        if up.startswith("CREATE INDEX IF NOT EXISTS") or up.startswith("CREATE UNIQUE INDEX IF NOT EXISTS"):
            s = re.sub(r"(?i)(CREATE\s+(?:UNIQUE\s+)?INDEX)\s+IF\s+NOT\s+EXISTS", r"\1", s, count=1)
            up = s.lstrip().upper()
        if up.startswith("CREATE TABLE"):
            s = _mysql_create_table(s)
        elif up.startswith(("CREATE", "ALTER")):
            s = _mysql_type_fix(s)
        s = _quote_ident(s)
    return s


def _errno(e):
    a = getattr(e, "args", ())
    return a[0] if a and isinstance(a[0], int) else None


def _exec(cur, sql, args=None):
    """执行单条语句；MySQL 重复建索引（errno 1061）按幂等处理"""
    if args is not None and not args:
        args = None
    try:
        if args is None:
            cur.execute(sql)          # sqlite3 不接受 None 作为参数序列
        else:
            cur.execute(sql, args)
    except Exception as e:
        if MYSQL and _errno(e) == 1061 and sql.lstrip().upper().startswith("CREATE"):
            return False
        raise
    return True


# ==================== 连接与基础读写 ====================
def connect():
    """新建连接（调用方负责关闭）"""
    _log_engine_once()
    if PG:
        import psycopg2  # PostgreSQL 模式才需要，SQLite 模式零依赖
        return psycopg2.connect(URL)
    if MYSQL:
        import pymysql
        from pymysql.constants import CLIENT
        conf = _mysql_conf()
        return pymysql.connect(
            host=conf["host"], port=conf["port"], user=conf["user"],
            password=conf["password"], database=conf["database"],
            charset="utf8mb4", autocommit=False, connect_timeout=10,
            client_flag=CLIENT.FOUND_ROWS,   # rowcount 按“命中行”计，与 SQLite 语义一致
        )
    c = sqlite3.connect(SQLITE_PATH, timeout=15, isolation_level=None)  # 关自动事务，由 tx() 显式 BEGIN
    c.row_factory = sqlite3.Row
    return c


def _row(cur, r):
    if SQLITE:
        return dict(r)
    return dict(zip([d[0] for d in cur.description], r))


def rows(sql, args=()):
    c = connect()
    try:
        cur = c.cursor()
        _exec(cur, _sql(sql), args)
        return [_row(cur, r) for r in cur.fetchall()]
    finally:
        c.close()


def one(sql, args=()):
    r = rows(sql, args)
    return r[0] if r else None


def run(sql, args=()):
    """执行写操作，返回自增主键（非 INSERT 或复合主键表返回 None）"""
    c = connect()
    try:
        cur = c.cursor()
        sql = _sql(sql)
        is_ins = sql.lstrip().upper().startswith("INSERT")
        if PG and is_ins:
            table = sql.split("(")[0].split()[-1].strip().lower()
            if table in NO_ID_TABLES:          # 复合主键、无 id 列的表不能 RETURNING id
                cur.execute(sql, args)
                nid = None
            else:
                cur.execute(sql + " RETURNING id", args)   # PG 用 RETURNING 取主键
                nid = cur.fetchone()[0]
        else:
            _exec(cur, sql, args)
            if PG:
                nid = None                     # psycopg2 无 lastrowid
            elif MYSQL:
                nid = cur.lastrowid if is_ins else None
            else:
                nid = cur.lastrowid
        c.commit()
        return nid
    finally:
        c.close()


def columns(table):
    """表已存在的列名集合（用于旧库平滑加列）"""
    if PG:
        rs = rows("SELECT column_name AS n FROM information_schema.columns WHERE table_name=?", (table,))
    elif MYSQL:
        rs = rows("SELECT column_name AS n FROM information_schema.columns "
                  "WHERE table_schema=DATABASE() AND table_name=?", (table,))
    else:
        rs = rows("PRAGMA table_info(%s)" % table)  # PRAGMA 不支持参数，表名为内部常量
    return {r["n"] if "n" in r else r["name"] for r in rs}


def init_schema(ddl):
    c = connect()
    try:
        cur = c.cursor()
        if SQLITE:
            cur.executescript(ddl)
        else:
            for s in _split_sql(ddl_for(ddl)):     # psycopg2/pymysql 一次只能执行一条语句
                _exec(cur, s)
        c.commit()
    finally:
        c.close()


def exec_script(sql, args=()):
    """批量写（无返回值）"""
    c = connect()
    try:
        _exec(c.cursor(), _sql(sql), args)
        c.commit()
    finally:
        c.close()


# ==================== 事务（下单 / 支付等跨表写必须原子） ====================
class Tx:
    """事务句柄：块内所有读写共用同一条连接。

    rows/one 用于读，run 用于写。run 执行后 self.rowcount 即为本次影响行数，
    可用它判断“条件更新”是否真的命中（例如订单状态迁移是否被别人抢先）。
    """

    def __init__(self, c):
        self.c = c
        self.rowcount = -1

    def rows(self, sql, args=()):
        cur = self.c.cursor()
        _exec(cur, _sql(sql), args)
        return [_row(cur, r) for r in cur.fetchall()]

    def one(self, sql, args=()):
        r = self.rows(sql, args)
        return r[0] if r else None

    def run(self, sql, args=()):
        """执行写操作，返回自增主键（INSERT），并把影响行数留在 self.rowcount"""
        cur = self.c.cursor()
        s = _sql(sql)
        is_ins = s.lstrip().upper().startswith("INSERT")
        if PG and is_ins:
            table = s.split("(")[0].split()[-1].strip().lower()
            if table in NO_ID_TABLES:
                cur.execute(s, args)
                nid = None
            else:
                cur.execute(s + " RETURNING id", args)
                nid = cur.fetchone()[0]
        else:
            _exec(cur, s, args)
            if PG:
                nid = None
            elif MYSQL:
                nid = cur.lastrowid if is_ins else None
            else:
                nid = cur.lastrowid
        self.rowcount = cur.rowcount
        return nid


@contextlib.contextmanager
def tx():
    """事务上下文：正常退出提交，异常整体回滚。

    SQLite 用 BEGIN IMMEDIATE 立即取写锁，避免“双击支付/连点下单”并发写互相覆盖；
    MySQL 用 START TRANSACTION，靠 InnoDB 行锁 + 条件 UPDATE 的 rowcount 兜住并发；
    PostgreSQL 走普通事务（默认已开）。
    """
    c = connect()
    try:
        if PG:
            c.autocommit = False
        elif MYSQL:
            c.cursor().execute("START TRANSACTION")   # BEGIN IMMEDIATE 在 MySQL 不存在
        else:
            c.execute("BEGIN IMMEDIATE")
        t = Tx(c)
        yield t
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
