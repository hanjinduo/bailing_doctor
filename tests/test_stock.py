"""库存能力验收：商品单查 + 加购/改量库存校验 + 支付期原子扣减（不超卖）

覆盖：
1. GET /api/meds/{id} 单查（旧前端用分页列表本地 find 会漏掉 id 靠后的商品）
2. 加购 / 改数量超过库存被拒；售罄商品不可加购
3. 下单预检库存
4. 并发支付同一 1 件库存的两张订单：仅一张成功，库存不为负、销量只加一次
5. 支付成功后库存正确扣减

用法：先启动 127.0.0.1:8010，再 `python tests/test_stock.py`。
脚本自建临时用户、自改库存，结束前恢复库存并物理清理全部测试数据（不动演示账号与演示单）。
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import db  # noqa: E402

results = []
TEST_MED = 22          # 演示库中库存较多的普通商品，测试期间临时改成 1
PHONE = "139" + str(int(time.time()))[-8:]


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("[PASS] " if ok else "[FAIL] ") + name + ("  " + str(detail)[:200] if detail else ""))


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


def main():
    med0 = db.one("SELECT * FROM meds WHERE id=?", (TEST_MED,))
    if not med0:
        print("测试商品不存在，终止")
        return 2
    old_stock, old_sales = med0["stock"], med0["sales"]
    uid = None
    created_orders = []
    try:
        # ---------- 1. 商品单查 ----------
        j = req("/api/meds/%d" % TEST_MED)
        check("商品单查 /api/meds/{id} 返回商品与库存",
              j.get("ok") and j["med"]["id"] == TEST_MED and "stock" in j["med"], j.get("med", {}).get("stock"))
        # id 靠后的商品（分页默认 20 条，21 以后列表里取不到）必须能单查到
        j = req("/api/meds/24")
        check("id=24（超出默认分页 20 条的商品）可单查到", bool(j.get("ok")), j.get("med", {}).get("name"))
        j = req("/api/meds/999999")
        check("不存在商品返回 ok=false", j.get("ok") is False and "不存在" in str(j.get("msg")), j.get("msg"))

        # ---------- 2. 建临时用户（与演示账号完全隔离） ----------
        c = req("/api/sms/code", {"phone": PHONE})
        code = str(c.get("code") or "")
        reg = req("/api/register", {"phone": PHONE, "pwd": "123456", "code": code, "name": "库存测试"})
        check("临时用户注册成功", bool(reg.get("ok")), reg.get("msg"))
        lg = req("/api/login", {"phone": PHONE, "pwd": "123456"})
        token = lg.get("token")
        uid = lg.get("uid") or (lg.get("user") or {}).get("id")
        check("临时用户登录拿到 token", bool(token and uid), uid)
        ad = req("/api/addresses", {"name": "测试", "phone": PHONE, "region": "上海市 浦东新区",
                                    "detail": "测试路 1 号", "is_default": 1}, token)
        addr_id = ad.get("id") or (ad.get("addr") or {}).get("id")
        check("临时地址创建成功", bool(ad.get("ok") and addr_id), ad.get("msg"))

        # ---------- 3. 加购与改量的库存校验 ----------
        db.run("UPDATE meds SET stock=? WHERE id=?", (1, TEST_MED))
        j = req("/api/cart", {"med_id": TEST_MED, "qty": 5}, token)
        check("加购超过库存被拒", j.get("ok") is False and "库存不足" in str(j.get("msg")), j.get("msg"))
        j = req("/api/cart", {"med_id": TEST_MED, "qty": 1}, token)
        check("库存内加购成功", bool(j.get("ok")), j.get("msg"))
        j = req("/api/cart", {"med_id": TEST_MED, "qty": 1}, token)
        check("再次加购累计超库存被拒", j.get("ok") is False and "库存不足" in str(j.get("msg")), j.get("msg"))
        j = req("/api/cart/%d" % TEST_MED, {"qty": 3}, token, "PUT")
        check("改数量超过库存被拒", j.get("ok") is False and "库存不足" in str(j.get("msg")), j.get("msg"))
        j = req("/api/cart", None, token)
        item = next((i for i in j.get("items", []) if i["med_id"] == TEST_MED), None)
        check("购物车返回库存字段且数量仍为 1", bool(item and item["stock"] == 1 and item["qty"] == 1),
              item and (item["stock"], item["qty"]))

        # ---------- 4. 下单预检 + 并发支付不超卖 ----------
        o1 = req("/api/order", {"addr_id": addr_id}, token)
        o2 = req("/api/order", {"addr_id": addr_id}, token)
        created_orders = [x.get("order_id") for x in (o1, o2) if x.get("order_id")]
        check("库存 1 件时连续两张待支付单可创建", len(created_orders) == 2, created_orders)

        res = {}
        barrier = threading.Barrier(2)

        def pay(oid, key):
            barrier.wait()
            res[key] = req("/api/order/%d/pay" % oid, {"pay": "微信"}, token)

        ts = [threading.Thread(target=pay, args=(created_orders[0], "a")),
              threading.Thread(target=pay, args=(created_orders[1], "b"))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        okc = sum(1 for v in res.values() if v.get("ok"))
        check("并发支付同一 1 件库存：仅 1 单成功", okc == 1, {k: v.get("msg") for k, v in res.items()})

        m = db.one("SELECT stock, sales FROM meds WHERE id=?", (TEST_MED,))
        check("库存扣到 0 且未出现负库存", m["stock"] == 0, m["stock"])
        check("销量只加一次", m["sales"] == old_sales + 1, (old_sales, m["sales"]))

        st = db.rows("SELECT id,status FROM orders WHERE id IN (%s)" %
                     ",".join(str(i) for i in created_orders))
        paid = [r["id"] for r in st if r["status"] in ("待发货", "已完成")]
        check("一张单已支付、一张单仍待支付", len(paid) == 1 and len(st) == 2, st)

        # ---------- 5. 售罄后前端动作全部被挡 ----------
        j = req("/api/cart", {"med_id": TEST_MED, "qty": 1}, token)
        check("售罄后加购被拒", j.get("ok") is False and ("售罄" in str(j.get("msg"))), j.get("msg"))

        # ---------- 6. 退款回补库存与销量（否则退款越多库存越少） ----------
        pid = paid[0]
        r1 = req("/api/order/%d/refund" % pid, {}, token)
        check("已支付订单可退款", bool(r1.get("ok")), r1.get("msg"))
        m2 = db.one("SELECT stock, sales FROM meds WHERE id=?", (TEST_MED,))
        check("退款后库存回补 1 件", m2["stock"] == 1, m2["stock"])
        check("退款后销量回退", m2["sales"] == old_sales, (old_sales, m2["sales"]))
        r2 = req("/api/order/%d/refund" % pid, {}, token)
        check("重复退款被拒（状态已迁移）", r2.get("ok") is False, r2.get("msg"))
        n = db.one("SELECT COUNT(*) n FROM notices WHERE user_id=? AND title='退款成功'", (uid,))
        check("退款通知只写一条", n["n"] == 1, n["n"])
        j = req("/api/cart", {"med_id": TEST_MED, "qty": 1}, token)
        check("回补库存后可再次加购", bool(j.get("ok")), j.get("msg"))

        db.run("DELETE FROM cart WHERE user_id=?", (uid,))
        j = req("/api/order", {"addr_id": addr_id}, token)
        check("购物车为空时不可下单", j.get("ok") is False, j.get("msg"))
    finally:
        # ---------- 清理：恢复库存/销量，物理删除临时用户全部数据 ----------
        db.run("UPDATE meds SET stock=?, sales=? WHERE id=?", (old_stock, old_sales, TEST_MED))
        if uid:
            db.run("DELETE FROM cart WHERE user_id=?", (uid,))
            db.run("DELETE FROM notices WHERE user_id=?", (uid,))
            db.run("DELETE FROM coupons WHERE user_id=?", (uid,))
            db.run("DELETE FROM addresses WHERE user_id=?", (uid,))
            db.run("DELETE FROM orders WHERE user_id=?", (uid,))
            db.run("DELETE FROM users WHERE id=?", (uid,))
        m = db.one("SELECT stock, sales FROM meds WHERE id=?", (TEST_MED,))
        left = db.one("SELECT COUNT(*) n FROM orders WHERE user_id=?", (uid,)) if uid else {"n": 0}
        check("清理后库存/销量已还原且无残留订单",
              m["stock"] == old_stock and m["sales"] == old_sales and left["n"] == 0, m)
        demo = db.rows("SELECT id,status,amount FROM orders WHERE id IN (34,35) ORDER BY id")
        check("演示单 34/35 未被改动", len(demo) == 2, demo)

    passed = sum(1 for _, ok, _ in results if ok)
    print("\nSUMMARY pass=%d/%d" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

