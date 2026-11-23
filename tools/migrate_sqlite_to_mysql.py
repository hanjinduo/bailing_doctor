# -*- coding: utf-8 -*-
"""bailing.db(SQLite) -> MySQL bailing_doctor 结构与数据全量迁移。

用途：把项目现有 SQLite 库原样搬到 MySQL，供默认 MySQL 模式启动使用。
特性：
  - 只操作 MYSQL_DB 指定的库（默认 bailing_doctor），不改同实例其它库；
  - 建表/索引/类型转换全部复用 db.py 的方言层，不另写一套 DDL；
  - 可重复执行：先 DROP 目标库中与本库同名的表再重建，幂等；
  - 迁移后逐表比对行数，并把各表 AUTO_INCREMENT 置为 max(id)+1。

用法（在项目根执行）：
    python tools/migrate_sqlite_to_mysql.py
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pymysql  # noqa: E402

import db  # noqa: E402

SRC = os.environ.get("SQLITE_PATH") or os.path.join(ROOT, "bailing.db")


def main():
    if not os.path.exists(SRC):
        print("ERROR sqlite not found:", SRC)
        return 1
    conf = db._mysql_conf()
    print("target mysql: %s:%s user=%s pwd_from=%s db=%s charset=utf8mb4"
          % (conf["host"], conf["port"], conf["user"], conf["pwd_from"], conf["database"]))

    # 1) 建库（不改其它库）
    raw = pymysql.connect(host=conf["host"], port=conf["port"], user=conf["user"],
                          password=conf["password"], charset="utf8mb4", autocommit=True)
    cur = raw.cursor()
    cur.execute("CREATE DATABASE IF NOT EXISTS `%s` CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_unicode_ci" % conf["database"])
    cur.execute("SHOW CREATE DATABASE `%s`" % conf["database"])
    print("database ready:", cur.fetchone()[1])
    cur.close()
    raw.close()

    # 2) 读 SQLite 结构与数据
    s = sqlite3.connect(SRC)
    s.row_factory = sqlite3.Row
    tabs = [r[0] for r in s.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    ddl_list, idx_list = [], []
    for r in s.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"):
        if r[0] == "table":
            ddl_list.append(r[2].replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
        elif r[0] == "index" and r[2]:
            idx_list.append(r[2].replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1))
    print("source tables: %d" % len(tabs))

    # 3) 清空目标库中同名表（仅本任务自建库，无外部数据）
    c = db.connect()
    cur = c.cursor()
    for t in tabs:
        cur.execute("DROP TABLE IF EXISTS `%s`" % t)
    c.commit()
    c.close()

    # 4) 建表（走方言层：注释保留、类型窄化、引擎/字符集）
    db.init_schema(";\n".join(ddl_list))
    print("schema created: %d tables" % len(tabs))

    # 5) 灌数据
    c = db.connect()
    cur = c.cursor()
    total = 0
    for t in tabs:
        cols = [r[1] for r in s.execute("PRAGMA table_info(%s)" % t)]
        data = [tuple(r) for r in s.execute("SELECT * FROM %s" % t)]
        cur.execute("DELETE FROM `%s`" % t)
        if data:
            ph = ",".join(["%s"] * len(cols))
            q = ("INSERT INTO `" + t + "`(" + ",".join("`" + x + "`" for x in cols) +
                 ") VALUES(" + ph + ")")
            cur.executemany(q, data)
        total += len(data)
        print("  %-12s %5d rows" % (t, len(data)))
    c.commit()
    c.close()
    print("data loaded: %d rows" % total)

    # 6) 建索引（方言层负责去掉 IF NOT EXISTS 并做 1061 幂等）
    before = db.one("SELECT COUNT(DISTINCT index_name) AS n FROM information_schema.statistics "
                    "WHERE table_schema=DATABASE()")["n"]
    fail = 0
    for stmt in idx_list:
        try:
            db.run(stmt)          # db.run 对非 INSERT 返回 None，故以异常与最终计数判定
        except Exception as e:
            fail += 1
            print("  INDEX FAIL %s -> %s" % (stmt[:60], str(e)[:80]))
    after = db.one("SELECT COUNT(DISTINCT index_name) AS n FROM information_schema.statistics "
                   "WHERE table_schema=DATABASE()")["n"]
    print("indexes: source=%d mysql_before=%d mysql_after=%d fail=%d"
          % (len(idx_list), before, after, fail))

    # 7) AUTO_INCREMENT 对齐 max(id)+1，避免演示库自增断层
    c = db.connect()
    cur = c.cursor()
    reset = 0
    for t in tabs:
        has_id = db.one("SELECT COUNT(*) AS n FROM information_schema.columns "
                        "WHERE table_schema=DATABASE() AND table_name=? AND column_name='id'", (t,))["n"]
        if not has_id:
            continue
        mx = db.one("SELECT COALESCE(MAX(id),0) AS m FROM `%s`" % t)["m"]
        cur.execute("ALTER TABLE `%s` AUTO_INCREMENT = %d" % (t, int(mx) + 1))
        reset += 1
    c.commit()
    c.close()
    print("auto_increment reset: %d tables" % reset)

    # 8) 行数核对
    bad = 0
    for t in tabs:
        a = s.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        b = db.one("SELECT COUNT(*) AS n FROM `%s`" % t)["n"]
        if a != b:
            bad += 1
            print("  MISMATCH %-12s sqlite=%d mysql=%d" % (t, a, b))
    s.close()
    print("verify: tables=%d mismatch=%d" % (len(tabs), bad))
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
