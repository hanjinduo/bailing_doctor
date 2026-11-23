# 数据库切换 MySQL 实施报告

- 项目：百灵医生（FastAPI + 原生前端，本地服务 127.0.0.1:8010）
- 实施日期：2026-11-19
- 目标：默认数据库引擎由 SQLite 切换为 MySQL（库 `bailing_doctor`），同时保留 SQLite 作为显式可切换选项，PostgreSQL 分支不破坏，业务代码零改动
- 结论：**已完成并全量验收通过**。MySQL 模式下 10 个核心接口全部 200、36 项测试全绿、数据与 SQLite 逐表一致；`DATABASE_URL=sqlite:///bailing.db` 重启后同样 36 项全绿，可随时切回

---

## 1. 背景与改造边界

改造前 `db.py` 是"SQLite 为默认、`DATABASE_URL` 命中 `postgres://`/`postgresql://` 才切 PostgreSQL"的双引擎结构，`app.py` / `rag.py` 通过 `q()` / `x()` / `db.rows` / `db.tx()` 统一访问，全部使用 `?` 占位符。

本次改造的硬边界（全部遵守）：

| 边界 | 落地情况 |
|---|---|
| 默认连本机 MySQL 127.0.0.1:3306 / bailing_doctor / root | 已实现，启动日志自报 `engine=mysql dsn=127.0.0.1:3306/bailing_doctor` |
| 口令优先 `MYSQL_PWD` > `MYSQL_PASSWORD`，缺省回退 phpstudy 默认口令并 WARNING | 已实现，回退时打印 `WARNING mysql password env ... 未设置，回退本机 phpstudy 默认口令` |
| charset=utf8mb4 | 连接级 `charset="utf8mb4"`，表级 `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci` |
| SQLite 可切换（`DATABASE_URL` 以 sqlite 开头 或 `DB_ENGINE=sqlite`） | 已实现并实测 |
| PostgreSQL 分支保留 | 已实现，`postgres://` / `postgresql://` 仍走 psycopg2 + `RETURNING id` |
| `app.py` 业务代码不动 | **未改动**（`app.py` 最后修改时间 2026-11-18 17:39，早于本次实施；121 处 `q(` / 80 处 `x(` 调用、字段名、返回结构、路由全部原样） |
| 禁止碰项目根 `.env` | 全程未读写 `.env` |
| 不重构业务、不动同实例其它库 | 仅操作 `bailing_doctor`，`doctor` 等既有库未被 CREATE/DROP |

改动文件清单：

| 文件 | 变更性质 | 说明 |
|---|---|---|
| `db.py` | 方言层重写（568 行） | 三引擎判定、MySQL 方言转换、类型窄化、索引容错、lastrowid、事务方言 |
| `tools/migrate_sqlite_to_mysql.py` | 新增（109 行） | SQLite→MySQL 结构与数据全量迁移、行数校验、AUTO_INCREMENT 对齐 |
| `tests/test_tier1.py` | 局部改造（168 行） | 索引验证按方言分支：MySQL 走 `information_schema.statistics` + `EXPLAIN key`，SQLite 保持 `EXPLAIN QUERY PLAN` |
| `rag.py` / `app.py` / `core.py` / `schemas.py` | 未改动 | `rag.py` 的 `kb_chunks` DDL 经 `db.exec_script()` 自动走方言层转换 |

---

## 2. 引擎判定与配置

判定顺序（`db._resolve_engine()`，自上而下命中即停）：

| 优先级 | 条件 | 结果 |
|---|---|---|
| 1 | `DATABASE_URL` 以 `postgres://` / `postgresql://` 开头 | PostgreSQL |
| 2 | `DATABASE_URL` 以 `sqlite` 开头 | SQLite（`bailing.db`） |
| 3 | `DATABASE_URL` 以 `mysql` 开头 | MySQL，参数取自 URL |
| 4 | `DB_ENGINE` = sqlite / sqlite3 / mysql / postgresql / pg | 指定引擎 |
| 5 | 全部未设置 | **MySQL（默认）** |

MySQL 默认参数（均可用环境变量覆盖）：`MYSQL_HOST=127.0.0.1`、`MYSQL_PORT=3306`、`MYSQL_DB=bailing_doctor`、`MYSQL_USER=root`，口令 `MYSQL_PWD` > `MYSQL_PASSWORD` > phpstudy 默认，连接 `connect_timeout=10`、`autocommit=False`、`client_flag=CLIENT.FOUND_ROWS`。

驱动选型：`mysqlclient` / `MySQLdb` / `aiomysql` 均未安装，`pymysql 2.2.8` 已装且为纯 Python 实现（无需编译），故 MySQL 分支用 `pymysql`；SQLite 分支保持标准库 `sqlite3` 零依赖；PostgreSQL 分支保持 `psycopg2`。

启动自报（实测日志，证明实际生效的方言）：

```
INFO  engine=mysql dsn=127.0.0.1:3306/bailing_doctor user=root charset=utf8mb4 pwd_from=phpstudy-default
INFO  indexes ready ok=18 skip=0 skip_detail=-

INFO  engine=sqlite path=...\output\bailing_doctor\bailing.db
```

---

## 3. MySQL 硬限制处理清单（逐项）

| # | 硬限制 | 处理方式 | 代码位置 |
|---|---|---|---|
| 1 | `users.phone` 为 `TEXT UNIQUE`，MySQL 不允许 TEXT 参与唯一键 | 窄化为 `VARCHAR(32)`，唯一键保留 | `MYSQL_TEXT_TYPES[("users","phone")]` → `_mysql_col()` |
| 2 | 参与索引的 TEXT 列同样不能窄化漏项 | 15 条窄化映射：`users.avatar VARCHAR(64)`、`users.sex VARCHAR(16)`、`chats/orders/rxs/coupons/appts.status VARCHAR(32)`、`orders.kind VARCHAR(32)`、`kb_chunks.mode VARCHAR(32)`、`chats/orders.created VARCHAR(32)`、`appts/slots.day VARCHAR(16)`、`meds.cat VARCHAR(32)`；**其余长文本（msgs.content、records 等）保持 TEXT**，不截断问诊内容 | `MYSQL_TEXT_TYPES`（15 项） |
| 3 | MySQL 无 `RETURNING id` | INSERT 后取 `cursor.lastrowid`（仅 INSERT 返回主键，UPDATE/DELETE 返回 None，与 SQLite 语义一致） | `run()` / `Tx.run()` |
| 4 | MySQL 8.0 不支持 `CREATE INDEX IF NOT EXISTS` | 双保险：① `_sql()` 正则剥掉 `IF NOT EXISTS`；② `_exec()` 捕获 errno 1061（duplicate key name）按幂等忽略 | `_sql()` / `_exec()` / `_errno()` |
| 5 | `db.columns()` 需支持 MySQL，否则启动缺列自动迁移（MIGRATE_COLS）失效 | 新增 `information_schema.columns` 分支（`table_schema=DATABASE()`） | `columns()` |
| 6 | `BEGIN IMMEDIATE` 在 MySQL 不存在 | `tx()` 方言分支：MySQL 用 `START TRANSACTION`；`CLIENT.FOUND_ROWS` 保证 `rowcount` 为"命中行数"而非"变更行数"，条件 UPDATE 的并发语义与 SQLite 一致 | `tx()` / `connect()` |
| 7 | `REAL` / `BLOB` 不适用 | `REAL → DOUBLE`、`BLOB → MEDIUMBLOB`、`TEXT DEFAULT → VARCHAR(255) DEFAULT` | `_mysql_type_fix()` |
| 8 | `INTEGER PRIMARY KEY AUTOINCREMENT` 语法 | `INT PRIMARY KEY AUTO_INCREMENT`（建表由 `_mysql_create_table()` 逐列改写，PG 仍走 `SERIAL PRIMARY KEY`） | `ddl_for()` / `_mysql_col()` |
| 9 | 保留字列名 | `slots.left`、`notices.read`、`usage` 共 3 列加反引号，仅在方言层处理，业务 SQL 不改 | `MYSQL_RESERVED` + `_quote_ident()` |
| 10 | 多语句 DDL 无法一次执行 | `_split_sql()` 按分号安全切分（忽略引号内分号）后逐条 `_exec` | `_split_sql()` / `init_schema()` |

事务与并发语义（双击支付防重的根基）：`Tx.run()` 执行后把 `cursor.rowcount` 留在 `self.rowcount`，业务侧用"条件 UPDATE 是否命中"判断状态迁移是否被别人抢先；MySQL 下靠 InnoDB 行锁 + `FOUND_ROWS` 标志保持与 SQLite 相同的"命中即 1"语义。

---

## 4. 数据迁移

工具：`tools/migrate_sqlite_to_mysql.py`（可重复执行、幂等）

执行流程：读 SQLite `sqlite_master` 取 20 张表 → `CREATE DATABASE IF NOT EXISTS bailing_doctor CHARACTER SET utf8mb4` → 逐表 `DROP TABLE IF EXISTS` + 用方言层转换后的 `CREATE TABLE` 重建 → 分批灌数 → 建 18 条业务索引 → 逐表比对行数 → `ALTER TABLE ... AUTO_INCREMENT = max(id)+1`。

实测输出（本次最终态，源库为迁移前的干净快照）：

```
users           16 rows
data loaded: 788 rows
indexes: source=18 mysql_before=2 mysql_after=20 fail=0
auto_increment reset: 19 tables
verify: tables=20 mismatch=0
```

说明：
- `mysql_before=2` 为重建表时随主键/唯一约束自动生成的索引（`cart` 复合主键、`users.phone` 唯一键），建完 18 条业务索引后合计 20，`fail=0`。
- 只对 `bailing_doctor` 库做 CREATE/DROP；同实例已有 `doctor`、`shop` 等 30+ 库未被触碰。
- `AUTO_INCREMENT` 对齐 `max(id)+1`，避免新插入数据 id 与历史 id 冲突或断层。

---

## 5. 验收结果

### a. 10 个核心接口在 MySQL 模式下全部 200

服务以默认配置（未设 `DATABASE_URL`）启动在 127.0.0.1:8010，用演示账号 `13800000000/123456` 登录后逐个访问：

| 接口 | MySQL 状态码 | SQLite 状态码 |
|---|---|---|
| POST /api/login | 200 | 200 |
| GET /api/me | 200 | 200 |
| GET /api/home | 200 | 200 |
| GET /api/doctors | 200 | 200 |
| GET /api/orders | 200 | 200 |
| GET /api/chats | 200 | 200 |
| GET /api/coupons | 200 | 200 |
| GET /api/addresses | 200 | 200 |
| GET /api/msgs | 200 | 200 |
| GET /api/meds | 200 | 200 |

关键字段逐项对比（同一份数据、两种引擎，实测快照）：

| 字段 | MySQL 模式 | SQLite 模式 | 是否一致 |
|---|---|---|---|
| me.user.id / phone / name | 1 / 13800000000 / 李小百 | 1 / 13800000000 / 李小百 | 一致 |
| me.user.vip / vip_until | true / 2031-06-17 | true / 2031-06-17 | 一致 |
| me.stat.orders / chats | 33 / 27 | 33 / 27 | 一致 |
| me.stat.wait_pay / in_consult | 60 / 15 | 60 / 15 | 一致 |
| home.depts / home.doctors | 9 / 5 | 9 / 5 | 一致 |
| doctors.total / 首条(id,name) | 19 / (1, 张明) | 19 / (1, 张明) | 一致 |
| orders.total / has_more | 33 / true | 33 / true | 一致 |
| orders 首条(id,status,amount) | (41, 已退款, 32.0) | (41, 已退款, 32.0) | 一致 |
| chats.total | 27 | 27 | 一致 |
| coupons.total / addresses.total | 4 / 11 | 4 / 11 | 一致 |
| msgs.total / chats / notices / unread | 104 / 27 / 20 / 3 | 104 / 27 / 20 / 3 | 一致 |
| meds 条数 | 20 | 20 | 一致 |

两模式快照 JSON 全字段 diff 结果：**空**（`DIFF: {}`）。

### b. MySQL 侧 20 张表行数与 SQLite 完全一致

| 表 | MySQL | SQLite | 表 | MySQL | SQLite |
|---|---|---|---|---|---|
| addresses | 19 | 19 | msgs | 113 | 113 |
| appts | 1 | 1 | news | 12 | 12 |
| cart | 11 | 11 | notices | 171 | 171 |
| chats | 46 | 46 | orders | 41 | 41 |
| coupon_tpl | 4 | 4 | pkgs | 3 | 3 |
| coupons | 34 | 34 | records | 0 | 0 |
| depts | 9 | 9 | rx_items | 30 | 30 |
| doctors | 19 | 19 | rxs | 16 | 16 |
| kb_chunks | 48 | 48 | slots | 171 | 171 |
| meds | 24 | 24 | users | 16 | 16 |
| **合计** | **788** | **788** | 差异表数 | **0** | — |

演示订单原样核对（MySQL 实查）：`(34, '待发货', deleted=0, 72.0)`、`(35, '待发货', deleted=0, 72.0)`，状态、软删除标记、金额均未变。

### c. MySQL 模式下 36 项测试全绿

| 套件 | 项数 | MySQL 模式 | 说明 |
|---|---|---|---|
| tests/test_api.py | 16 | 16 / 16 通过 | 登录、鉴权、下单、支付、订单、会话、地址、优惠券等主链路 |
| tests/test_tier1.py | 20 | 20 / 20 通过 | 含 RAG/SSE/索引；索引段按方言分支改造，非假通过 |
| 合计 | 36 | **36 / 36** | — |

`test_tier1` 索引验证的方言分支（防假通过的关键）：

- MySQL：索引清单取 `SELECT DISTINCT index_name FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=?`，是否真正走索引用 `EXPLAIN <SQL>` 的 `key` / `possible_keys` 判定（4 条查询：orders 按 user_id+status、msgs 按 chat_id、chats 按 user_id+status、kb_chunks 按 dim+mode）。
- SQLite：保持原逻辑 `EXPLAIN QUERY PLAN`，不加分支即报错，因此不存在"跳过验证也算过"。

### d. 切回 SQLite 后同样 36 项全绿

以 `DATABASE_URL=sqlite:///bailing.db` 重启服务（日志 `engine=sqlite path=...\bailing.db`），复跑同一套件：`test_api 16/16`、`test_tier1 20/20`，合计 **36 / 36**，与改造前基线一致，证明 SQLite 可随时切回。

### e. MySQL 下并发/软删除/分页抽测

| 场景 | 验证方式 | 结果 |
|---|---|---|
| 双击支付防重 | 同一订单发起两次支付，事务内条件 UPDATE 依赖 `rowcount` 判定 | 仅 1 次状态迁移生效，第 2 次 `rowcount=0` 被拦下，未产生重复扣款/重复状态变更 |
| 订单软删除 | 删除后复查列表、`/api/me` 统计、详情接口 | 列表与统计同步排除已删行，详情返回 404，与 SQLite 行为一致 |
| 分页 has_more | `/api/orders` 默认 limit=20，total=33 | `has_more=true`，`limit/offset/total` 字段齐全，与 SQLite 一致（`/api/chats` total=27 同样正确） |

### f. 自测数据清理

- 迁移前将原始 `bailing.db` 备份为快照，验收完成后以该快照重建 SQLite 并**重新执行一次完整迁移**，MySQL 侧恢复为纯净演示数据。
- MySQL 实查残留：`orders` 中 `deleted=1` 计数 **0**，`chats` 中 `deleted=1` 计数 **0**。
- 演示订单 34/35：`待发货`、`deleted=0`、`amount=72.0`，未被动过。
- 最终态表数 20、总行数 788，与迁移基线完全一致。

---

## 6. MySQL / SQLite 双模式对比

| 维度 | MySQL（默认） | SQLite（可切换） |
|---|---|---|
| 连接方式 | pymysql → 127.0.0.1:3306/bailing_doctor | 标准库 sqlite3 → 项目根 bailing.db |
| 启动开关 | 不设变量即默认 | `DATABASE_URL=sqlite:///bailing.db` 或 `DB_ENGINE=sqlite` |
| 起始耗时 | 首次连接约 1~2 秒（握手 + 建连） | 毫秒级，无网络开销 |
| 并发写 | InnoDB 行锁，多连接并行写 | 库级写锁（`BEGIN IMMEDIATE`），写串行 |
| 自增主键 | `AUTO_INCREMENT` + `lastrowid` | `AUTOINCREMENT` + `lastrowid` |
| 建索引幂等 | 剥 `IF NOT EXISTS` + errno 1061 容错 | 原生支持 `CREATE INDEX IF NOT EXISTS` |
| 列类型 | 索引/唯一/默认值列窄化为 VARCHAR，长文本 TEXT，金额 DOUBLE | 原样 TEXT / REAL / BLOB |
| 字符串比较 | `utf8mb4_unicode_ci` 大小写不敏感 | 默认 BINARY，大小写敏感 |
| 缺列自动迁移 | 走 `information_schema.columns` | 走 `PRAGMA table_info` |
| 事务起点 | `START TRANSACTION` | `BEGIN IMMEDIATE` |
| rowcount 语义 | `CLIENT.FOUND_ROWS`，命中行计数 | 命中行计数 |
| 部署依赖 | 需 MySQL 8.0 + pymysql | 零依赖，单文件可拷走 |
| 适用场景 | 默认运行环境、多实例/并发写 | 本地演示、离线调试、快速回滚 |

**接口层表现一致**：两模式下 10 个接口状态码与关键字段完全相同（见 5.a），36 项测试均全绿，说明上层业务代码对引擎无感知。

---

## 7. 遇到的问题与解决

| 问题 | 现象 | 解决 |
|---|---|---|
| TEXT 不能建唯一键/索引 | 建 `users` 表报 `BLOB/TEXT column 'phone' used in key specification without a key length` | 引入 `MYSQL_TEXT_TYPES` 白名单窄化（15 列），其余长文本保留 TEXT |
| `slots.left` / `notices.read` 报语法错 | `You have an error in your SQL syntax ... near 'left'` | 方言层 `_quote_ident()` 对 3 个保留字列加反引号，业务 SQL 与字段名不变 |
| `CREATE INDEX IF NOT EXISTS` 报错 | MySQL 8.0 语法不支持 | `_sql()` 剥掉 `IF NOT EXISTS` + `_exec()` 捕获 errno 1061 幂等；重复启动不再中断 |
| 启动缺列迁移在 MySQL 下静默失效 | `columns()` 走 PRAGMA，MySQL 返回空集，`MIGRATE_COLS` 判定"列已存在"跳过加列 | 补 `information_schema.columns` 分支，实测旧库缺列可自动补齐 |
| `BEGIN IMMEDIATE` 报错 | `You have an error in your SQL syntax ... BEGIN IMMEDIATE` | `tx()` 按引擎分支为 `START TRANSACTION` |
| rowcount 语义差异 | MySQL 默认只统计"实际变更行"，条件 UPDATE 命中但值未变时返回 0，会误判"被抢先" | 连接加 `CLIENT.FOUND_ROWS`，rowcount 回到"命中行"语义，与 SQLite 对齐 |
| 迁移后新数据 id 与历史冲突隐患 | `AUTO_INCREMENT` 从 1 开始 | 迁移末尾按 `max(id)+1` 逐表重置（19 张含 id 列的表） |
| `test_tier1` 索引校验是 SQLite 专用 | 直接指向 `bailing.db` 文件，MySQL 下会假通过/误报 | 按 `db.ENGINE` 分支：MySQL 查 `information_schema.statistics` + `EXPLAIN`，SQLite 保持原逻辑 |
| 迁移脚本重复执行脏数据 | 二次执行出现重复主键/行数翻倍 | 脚本先 `DROP TABLE IF EXISTS` 再重建，幂等可重跑 |
| 调试期端口占用 | 旧 uvicorn 进程占用 8010 导致新配置不生效 | 每次切换引擎前按端口查 PID 并 `taskkill`，确认端口释放后再启动 |

---

## 8. 遗留风险与建议

| 风险 | 等级 | 说明 | 建议 |
|---|---|---|---|
| root 直连 | 高 | 默认用 root 连本机 MySQL，权限过大，误操作可波及同实例 30+ 其它库 | 生产环境新建最小权限账号（仅 `bailing_doctor` 的 SELECT/INSERT/UPDATE/DELETE + 建表权限），通过 `MYSQL_USER/MYSQL_PWD` 注入 |
| 口令回退到默认值 | 中高 | 未设 `MYSQL_PWD` 时回退 phpstudy 默认口令并只打 WARNING，本机演示方便但线上不可接受 | 上线前强制要求环境变量，缺失时启动失败（可加 `STRICT_DB_ENV=1` 开关） |
| 无连接池 | 中 | `connect()` 每次新建物理连接，请求结束即关闭；高并发下握手开销与连接数上限成为瓶颈 | 引入 `DBUtils.PooledDB` 或 `SQLAlchemy` 连接池，保持 `rows/one/run` 接口不变 |
| `REAL → DOUBLE` 精度差异 | 中低 | 金额字段由单精度浮点变双精度，`72.0` 等展示与比较实测一致，但浮点相等比较本身不可靠 | 金额改为 `DECIMAL(10,2)` 或统一按分（整数）存储；业务侧禁止 `==` 比较浮点 |
| TEXT → VARCHAR 窄化截断 | 中低 | `VARCHAR(32)` 类列在超长输入时会被截断或报 1406 | 接口层加长度校验；对昵称等自由文本留足长度 |
| 排序规则差异 | 中低 | `utf8mb4_unicode_ci` 大小写/重音不敏感，SQLite 默认区分大小写；`users.phone` 为纯数字无影响，其它唯一列需评估 | 需严格区分大小写的列改 `utf8mb4_bin` |
| DDL 转换依赖正则 | 低 | `_mysql_create_table()` / `_quote_ident()` 基于正则识别，新增怪写法 DDL 可能漏转 | 新增表/索引时同步补 `MYSQL_TEXT_TYPES` 与保留字集合，并在启动时核对 `indexes ready ok=?` |
| 双库并存一致性 | 低 | SQLite 文件与 MySQL 各自演进后会数据漂移 | 明确 MySQL 为唯一写入源，SQLite 仅作演示/回滚快照；如需并行，用迁移脚本定期单向同步 |

---

## 9. 运维手册

切到 SQLite（临时演示 / 回滚）：

```powershell
$env:DATABASE_URL = "sqlite:///bailing.db"      # 或 $env:DB_ENGINE = "sqlite"
python -m uvicorn app:app --host 127.0.0.1 --port 8010
```

回到默认 MySQL：

```powershell
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:DB_ENGINE -ErrorAction SilentlyContinue
$env:MYSQL_PWD = "<口令>"        # 生产环境务必设置
python -m uvicorn app:app --host 127.0.0.1 --port 8010
```

重新迁移（幂等，会重建 `bailing_doctor` 内同名表）：

```powershell
python tools\migrate_sqlite_to_mysql.py
```

启动自检要点：日志出现 `engine=mysql ... pwd_from=...` 与 `indexes ready ok=18`；若 `pwd_from=phpstudy-default` 说明口令走的是回退值。

---

## 10. 附录：验收环境与复现

- 操作系统：Windows 11（Build 26200）
- Python：3.11（Marvis 运行时）
- 驱动：pymysql 2.2.8、psycopg2 2.9.13；`mysqlclient` / `MySQLdb` / `aiomysql` 未安装
- MySQL：8.0.12（phpstudy，`D:\phpstudy_pro\Extensions\MySQL8.0.12`），监听 3306
- 目标库：`bailing_doctor`（utf8mb4 / InnoDB），20 表 788 行 18 条业务索引
- 服务：`python -m uvicorn app:app --host 127.0.0.1 --port 8010`
- 测试：`python -m unittest discover -s tests -p "test_*.py"`（36 项）

复现顺序：备份 `bailing.db` → 跑迁移脚本 → MySQL 模式起服务并核对接口/行数 → 跑 36 项测试 → 切 SQLite 重启再跑 36 项 → 切回 MySQL 并复核 `deleted=1` 残留与演示订单 34/35。

---

## 11. 主 Agent 独立复验（2026-11-19）

本节由主 Agent 在**不采信实施过程的既有结论**、重新独立执行的前提下逐项复跑并留证。下文只写实测结果，不重复前文推导过程。

### a. 双库 20 张表逐表行数完全一致

对 MySQL `bailing_doctor` 与 SQLite `bailing.db` 逐表计数并两两比对：**20 张表行数全部一致**，合计 **788 行**，与迁移基线相同。逐表清单：

| 表 | 行数 | 表 | 行数 | 表 | 行数 | 表 | 行数 |
|---|---|---|---|---|---|---|---|
| addresses | 19 | appts | 1 | cart | 11 | chats | 46 |
| coupon_tpl | 4 | coupons | 34 | depts | 9 | doctors | 19 |
| kb_chunks | 48 | meds | 24 | msgs | 113 | news | 12 |
| notices | 171 | orders | 41 | pkgs | 3 | records | 0 |
| rx_items | 30 | rxs | 16 | slots | 171 | users | 16 |

（每格两库取值相同；合计 MySQL 788 = SQLite 788，无单表偏移。）

### b. 服务真实读写 MySQL（探针实测）

仅按"配置写了 MySQL"无法排除"实际仍读 SQLite"，因此做写入探针：

1. 直接在 MySQL 侧 `UPDATE doctors SET name=...` 改掉某一位医生的姓名，SQLite 侧同一行保持原值；
2. 随即请求运行中服务（8010）的 `GET /api/doctors`，返回的姓名**随 MySQL 改动同步变化**；
3. 此时 SQLite 侧该行从未改动，若服务实际读的是 SQLite，返回值应保持原姓名——实测并非如此。

结论：8010 服务的数据源确为 MySQL，读写路径真实切到 MySQL，而非只在配置层声明。探针改动**已回滚**，`doctors` 表恢复原值，双库行数仍为 20 表 788 行。

### c. 引擎判定 6 种组合全部正确

以 `db.ENGINE` / `db.LABEL` 输出为判定依据，逐一验证：

| # | 环境变量设置 | 期望引擎 | 实测 |
|---|---|---|---|
| 1 | 不设任何数据库变量 | mysql | mysql ✔ |
| 2 | `DATABASE_URL=sqlite` | sqlite | sqlite ✔ |
| 3 | `DATABASE_URL=sqlite:///bailing.db` | sqlite | sqlite ✔ |
| 4 | `DATABASE_URL=mysql://root:...@127.0.0.1:3306/bailing_doctor` | mysql | mysql ✔ |
| 5 | `DB_ENGINE=sqlite` | sqlite | sqlite ✔ |
| 6 | `DB_ENGINE=mysql` | mysql | mysql ✔ |

6 组全部命中预期，未出现"变量被忽略"或"前缀误判"的情况。

### d. 36 项测试双模式全过

- **MySQL 模式**：`test_api` 16 项 + `test_tier1` 20 项 = **36 项全过**。`test_tier1` 的索引段按方言走 `EXPLAIN` 分支（查 `information_schema.statistics` 取索引清单），4 条业务 SQL 实测命中索引：`idx_orders_user`、`idx_msgs_chat`、`idx_chats_user`、`idx_kb_dim`，非"跳过即通过"。
- **SQLite 模式**：同样 **36 项全过**，索引段走 `EXPLAIN QUERY PLAN` 分支。

两种模式的用例、断言与预期完全一致，仅底层方言分支不同，说明业务层对引擎无感知。

### e. 业务索引与启动自检

- 业务索引 **18 条**全部建成（另有 `users.phone` 唯一索引由唯一约束生成，不计入 18 条业务索引），启动日志 `indexes ready ok=18`，**无 skip**（剥 `IF NOT EXISTS` + errno 1061 容错生效，重复启动不中断）。
- 启动日志自报 `engine=mysql dsn=127.0.0.1:3306/bailing_doctor user=root charset=utf8mb4`，与配置实况一致。

### f. 演示数据未被污染

- 演示订单 **34 / 35 仍为「待发货」**，`deleted=0`，金额与状态未变。
- 软删残留：`orders` 中 `deleted=1` 计数 **0**，`chats` 中 `deleted=1` 计数 **0**。

### g. 测试数据已清理

两种模式测试过程中产生的**问诊单与通知均已清理干净**，复查相关表无残留测试数据，库内容与迁移基线一致。

### h. 已知限制（1 条）

**`app.py` 的 `db` / `driver` 字段仍按 SQLite 口径打印，不反映真实引擎。** 因本次改造边界要求"不改 `app.py`"，其 startup 日志取 `db.URL or db.SQLITE_PATH` 与 `"postgresql" if db.PG else "sqlite"`：MySQL 模式下 `db.URL` 为空，于是 `db=` 打印的是 `...\bailing.db`、`driver=` 打印 `sqlite`；`GET /api/health` 的 `db` 字段取 `os.path.basename(db.SQLITE_PATH)`，同样固定返回 `bailing.db`。在 MySQL 模式下这三处会误导排查者。判断真实引擎请以下列信号为准：

- `db.ENGINE` / `db.LABEL`（代码内判定结果）；
- 启动日志中 `engine=mysql ... dsn=...` 这一行（由 `db.py` 方言层自报）。

如需彻底消除该干扰，后续可单独提一次小改动把两处字段改为读取 `db.LABEL`（不在本次改造范围）。

### i. 文档一致性

`README.md` 的数据库章节已同步为当前实况：默认 MySQL 8.0；SQLite 改为 `DATABASE_URL=sqlite` / `DB_ENGINE=sqlite` 显式切换；补齐 `DATABASE_URL` 三种前缀与 `DB_ENGINE` 取值、引擎判定优先级、口令回退 `WARNING`；新增「本地 MySQL 直接跑」启动方式；Docker / PostgreSQL 方式保留并注明**非默认**（compose 内注入的是 `postgresql://`）。

---

## 12. 最终冒烟自检（MySQL 默认模式）

在**不设任何数据库环境变量**（默认走 MySQL）的前提下，对常驻服务做一次只读冒烟，确认切换后无功能回归。以下为实测记录。

### a. 环境

| 项 | 实测值 |
|---|---|
| 数据库 | phpstudy MySQL **8.0.12**，`mysqld` PID **36348**，监听 **3306**（17:59 前启动） |
| 应用服务 | `python -m uvicorn app:app --host 127.0.0.1 --port 8010`，PID **29056** |
| 引擎来源 | 未设 `DATABASE_URL` / `DB_ENGINE` → 默认 MySQL |

### b. 启动日志

```text
engine=mysql dsn=127.0.0.1:3306/bailing_doctor user=root charset=utf8mb4 pwd_from=phpstudy-default
indexes ready ok=18 skip=0
rag ready chunks=48
```

- `pwd_from=phpstudy-default`：未设 `MYSQL_PWD` / `MYSQL_PASSWORD`，口令走本机 phpstudy 回退值（同时打了 `WARNING`）。
- `indexes ready ok=18 skip=0`：18 条业务索引全部就绪，无跳过。
- `rag ready chunks=48`：知识库 48 个语义块加载正常。

### c. 登录鉴权

| 接口 | 参数 | 状态码 | 结果 |
|---|---|---|---|
| `POST /api/login` | `phone=13800000000`、`pwd=123456` | **200** | 签发 token，长度 **127** |

### d. 核心接口冒烟（18/18 通过）

| 接口 | 状态码 |
|---|---|
| `GET /api/health`（免鉴权） | 200 |
| `GET /api/rag/status`（免鉴权） | 200 |
| `GET /api/home` | 200 |
| `GET /api/me` | 200 |
| `GET /api/addresses` | 200 |
| `GET /api/coupons` | 200 |
| `GET /api/doctors` | 200 |
| `GET /api/appts` | 200 |
| `GET /api/chats` | 200 |
| `GET /api/rxs` | 200 |
| `GET /api/medcats` | 200 |
| `GET /api/meds` | 200 |
| `GET /api/pkgs` | 200 |
| `GET /api/cart` | 200 |
| `GET /api/orders` | 200 |
| `GET /api/msgs` | 200 |
| `GET /api/news` | 200 |
| `GET /api/records` | 200 |
| `GET /api/vip` | 200 |

**合计 ok=18/18**，无 4xx/5xx、无超时；其中 `/api/health` 与 `/api/rag/status` 为免鉴权接口。

### e. 双库逐表行数一致性（diff=0）

| 表 | 行数 | 表 | 行数 | 表 | 行数 | 表 | 行数 |
|---|---|---|---|---|---|---|---|
| addresses | 19 | appts | 1 | cart | 11 | chats | 46 |
| coupon_tpl | 4 | coupons | 34 | depts | 9 | doctors | 19 |
| kb_chunks | 48 | meds | 24 | msgs | 113 | news | 12 |
| notices | 171 | orders | 41 | pkgs | 3 | records | 0 |
| rx_items | 30 | rxs | 16 | slots | 171 | users | 16 |

**20 张表 SQLite 与 MySQL 完全一致，diff=0**（MySQL 合计 788 行 = SQLite 合计 788 行）。

### f. 软删残留核查

| 项 | 实测 |
|---|---|
| 含 `deleted` 列的表 | 仅 `chats`、`orders` 两张 |
| `chats` 中 `deleted=1` | SQLite 0 / MySQL 0 |
| `orders` 中 `deleted=1` | SQLite 0 / MySQL 0 |
| 残留合计 | **residual_total = 0** |

### g. 演示订单 34 / 35

| 项 | 实测 |
|---|---|
| 比对方式 | SQLite 与 MySQL 同行逐字段比对，**42 列** |
| 比对结果 | **identical = True**（无任一列差异） |
| `amount` | 两库均为 **72.0** |
| 支付方式 | 微信支付 |

### h. 已知限制（沿用）

未改 `app.py`，因此其 startup 日志的 `db` 字段与 `GET /api/health` 返回的 `db` 字段仍为 `bailing.db`，**不代表实际引擎**；真实方言以启动日志 `engine=...` 行与 `DB_ENGINE` 配置为准（判定细节见第 11 节 h）。

### i. 说明

本次冒烟**仅调用只读接口**（登录 + 各查询接口），未写入任何数据：未下单、未改病历、未发消息、未触发 RAG 重建，故两库数据在冒烟前后保持一致（20 表 788 行、diff=0）。


