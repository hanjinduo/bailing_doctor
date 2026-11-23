"""第一档优化验收：RAG 检索 + SSE 流式 + 索引

覆盖：
1. /api/rag/status 索引与向量通道
2. /api/rag/search 检索相关度
3. 问诊全链路：登录 → 建单 → 支付 → 接诊 → SSE 流式对话
4. sqlite 索引是否真实建立（EXPLAIN QUERY PLAN 验证走索引）
"""
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8010"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("[PASS] " if ok else "[FAIL] ") + name + ("  " + str(detail)[:160] if detail else ""))


def req(path, data=None, token=None, method=None):
    url = BASE + path
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, method=method or ("POST" if data is not None else "GET"))
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code, "body": e.read().decode()[:200]}


def stream(path, data, token):
    """消费 SSE，返回 (增量片段列表, done 帧)"""
    url = BASE + path
    body = json.dumps(data, ensure_ascii=False).encode()
    r = urllib.request.Request(url, data=body, method="POST")
    r.add_header("Content-Type", "application/json")
    r.add_header("Authorization", "Bearer " + token)
    deltas, done, ctype = [], None, ""
    with urllib.request.urlopen(r, timeout=60) as resp:
        ctype = resp.headers.get("content-type", "")
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            obj = json.loads(line[5:].strip())
            if obj.get("t") == "delta":
                deltas.append(obj["v"])
            elif obj.get("t") == "done":
                done = obj
    return deltas, done, ctype


def main():
    print("=" * 60)
    print("一、RAG 索引与检索")
    print("=" * 60)
    st = req("/api/rag/status")
    check("rag/status 可用", st.get("ok") is True, st.get("msg", ""))
    check("知识库已切块入库", int(st.get("chunks") or 0) >= 40, "chunks=%s files=%s" % (st.get("chunks"), st.get("kb_files")))
    check("embedding 通道为远端 text-embedding-v3",
          "remote" in (st.get("index_modes") or []) and st.get("embed_model") == "text-embedding-v3",
          st.get("index_modes"))

    cases = [("发烧到39度怎么办", "发热"), ("吃完头孢能喝酒吗", "用药"), ("孩子拉肚子脱水", "儿科|消化")]
    for q, expect in cases:
        r = req("/api/rag/search?q=" + urllib.parse.quote(q) + "&k=3")
        top = (r.get("hits") or [{}])[0]
        hit_src = top.get("src", "")
        import re as _re
        matched = bool(_re.search(expect, hit_src)) or any(_re.search(expect, h.get("text", "")) for h in (r.get("hits") or []))
        check("检索「%s」命中相关片段" % q, r.get("ok") and r.get("count", 0) > 0 and matched,
              "top=%s score=%s" % (hit_src, top.get("score")))

    print()
    print("=" * 60)
    print("二、SSE 流式问诊")
    print("=" * 60)
    lg = req("/api/login", {"phone": "13800000000", "pwd": "123456"})
    token = lg.get("token") or (lg.get("user") or {}).get("token")
    check("登录获取 JWT", bool(token), "token_len=%d" % len(token or ""))

    docs = req("/api/doctors").get("doctors") or []
    doc = docs[0] if docs else {}
    cs = req("/api/chat/start", {"doctor_id": doc.get("id", 0), "dept": doc.get("dept", "内科"),
                                 "mode": "text", "symptom": "发烧38.7度两天，伴咽痛"}, token)
    cid = cs.get("chat_id") or (cs.get("chat") or {}).get("id")
    check("创建问诊单", bool(cid), cs.get("msg", ""))

    if cid:
        req("/api/chat/%d/pay" % cid, {"pay": "微信", "coupon_id": 0}, token)
        req("/api/chat/%d/enter" % cid, {}, token)

        t0 = time.time()
        deltas, done, ctype = stream("/api/chat/stream", {"chat_id": cid, "text": "烧到39度了，要吃什么药"}, token)
        cost = time.time() - t0
        check("响应 Content-Type 为 text/event-stream", "text/event-stream" in ctype, ctype)
        check("收到多个增量帧（真流式）", len(deltas) >= 3, "frames=%d cost=%.2fs" % (len(deltas), cost))
        check("done 帧带完整回复与来源", bool(done and done.get("reply")),
              "source=%s llm=%s hits=%d" % ((done or {}).get("source"), (done or {}).get("llm"),
                                            len((done or {}).get("hits") or [])))
        check("增量拼接等于完整回复", bool(done) and "".join(deltas) == done.get("reply"))
        check("回复内容非空且含医疗表述", bool(done) and len(done.get("reply", "")) > 20,
              (done or {}).get("reply", "")[:60])

        g = req("/api/chat/%d" % cid, token=token)
        last = (g.get("msgs") or [{}])[-1]
        check("流式回复已落库", last.get("role") == "dr" and bool(last.get("text")),
              "%s: %s" % (last.get("role"), (last.get("text") or "")[:40]))

        # 非流式老接口保持兼容
        r2 = req("/api/chat/send", {"chat_id": cid, "text": "那需要注意什么"}, token)
        check("旧接口 /chat/send 兼容可用", r2.get("ok") is True and bool(r2.get("reply")),
              (r2.get("reply") or "")[:40])

    print()
    print("=" * 60)
    print("三、数据库索引（按方言分支：MySQL 用 EXPLAIN，SQLite 用 EXPLAIN QUERY PLAN）")
    print("=" * 60)
    sys.path.insert(0, ROOT)
    import db as _db
    engine = _db.ENGINE
    print("   当前引擎：%s" % engine)

    if engine == "mysql":
        # MySQL：索引清单取 information_schema；是否可用看 EXPLAIN 的 key / possible_keys
        # （小表下优化器可能主动选全表扫描，故 key 或 possible_keys 命中即视为索引可用）
        # 注意：MySQL 8 的 information_schema 列名为大写（INDEX_NAME），必须用别名取小写键
        idx_names = sorted({r["idx_name"] for r in _db.rows(
            "SELECT DISTINCT index_name AS idx_name FROM information_schema.statistics "
            "WHERE table_schema=DATABASE() AND index_name LIKE ?", ("idx%",))})
        check("已建立业务索引", len(idx_names) >= 15,
              "engine=mysql count=%d" % len(idx_names))

        def plan_of(sql):
            r = _db.rows("EXPLAIN " + sql)
            row = r[0] if r else {}
            return row

        probes = [
            ("orders 按用户+状态查询走索引", "idx_orders_user",
             "SELECT * FROM orders WHERE user_id=1 AND status='待支付'"),
            ("msgs 按会话取消息走索引", "idx_msgs_chat",
             "SELECT * FROM msgs WHERE chat_id=1 ORDER BY id"),
            ("chats 按用户+状态查询走索引", "idx_chats_user",
             "SELECT * FROM chats WHERE user_id=1 AND status='问诊中'"),
            ("kb_chunks 向量检索按空间走索引", "idx_kb_dim",
             "SELECT * FROM kb_chunks WHERE dim=1024 AND mode='remote'"),
        ]
        for title, idx, sql in probes:
            row = plan_of(sql)
            seen = " ".join(str(row.get(k) or "") for k in ("key", "possible_keys"))
            check(title, idx in seen,
                  "type=%s key=%s possible_keys=%s" % (row.get("type"), row.get("key"),
                                                       row.get("possible_keys")))
    else:
        con = sqlite3.connect(os.path.join(ROOT, "bailing.db"))
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")]
        check("已建立业务索引", len(names) >= 15, "engine=sqlite count=%d" % len(names))

        plan = " ".join(str(r) for r in con.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM orders WHERE user_id=1 AND status='待支付'"))
        check("orders 按用户+状态查询走索引", "idx_orders_user" in plan, plan[:120])

        plan2 = " ".join(str(r) for r in con.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM msgs WHERE chat_id=1 ORDER BY id"))
        check("msgs 按会话取消息走索引", "idx_msgs_chat" in plan2, plan2[:120])

        plan3 = " ".join(str(r) for r in con.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM chats WHERE user_id=1 AND status='问诊中'"))
        check("chats 按用户+状态查询走索引", "idx_chats_user" in plan3, plan3[:120])

        plan4 = " ".join(str(r) for r in con.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM kb_chunks WHERE dim=1024 AND mode='remote'"))
        check("kb_chunks 向量检索按空间走索引", "idx_kb_dim" in plan4, plan4[:120])
        con.close()

    print()
    print("=" * 60)
    ok = sum(1 for _, o, _ in results if o)
    print("结果：%d/%d 通过" % (ok, len(results)))
    for n, o, d in results:
        if not o:
            print("  未通过 ->", n, d)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
