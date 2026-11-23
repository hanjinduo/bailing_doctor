# -*- coding: utf-8 -*-
"""订单详情 / 物流轨迹 / 状态流转 端到端自测

设计原则：
1. 全部使用自建临时用户，绝不触碰演示账号（13800000000）与演示单 34/35；
2. 结束后物理清理临时数据，并把测试商品的库存/销量还原到测试前快照；
3. 用标准库 urllib，不引入第三方依赖，可直接 python tests/test_order_flow.py 运行。

覆盖点：
- 订单号格式 BL+日期+6 位序号
- 物流轨迹随状态推进（待支付 → 已支付 → 已发货 → 已签收），且不臆造未发生节点
- 运单号按订单稳定生成（同一订单多次读取一致）
- 已完成订单不可退款；待发货订单可退款且轨迹出现退款成功
- 越权读取他人订单被拒；删除后详情 404
"""
import json
import os
import random
import re
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  <<< " + str(detail)))


def call(path, body=None, token=None, method=None):
    url = BASE + "/api" + path
    data = json.dumps(body).encode() if body is not None else None
    # 无 body 的写接口（发货/收货/退款/取消）必须显式 POST，否则会退化成 GET 收到 405
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def new_user(tag):
    phone = "139" + "".join(random.choice("0123456789") for _ in range(8))
    st, j = call("/sms/code", {"phone": phone})
    code = j.get("code") or ""
    if not code:
        raise SystemExit("未拿到验证码回显，无法自动注册：%s" % j)
    st, j = call("/register", {"phone": phone, "pwd": "test123456", "code": code, "name": "物流测试" + tag})
    if not j.get("ok"):
        raise SystemExit("注册失败：%s" % j)
    st, j = call("/login", {"phone": phone, "pwd": "test123456"})
    return {"phone": phone, "pwd": "test123456", "token": j["token"], "uid": j.get("user", {}).get("id")}


def main():
    import db

    mid = 1
    snap = db.one("SELECT id,stock,sales FROM meds WHERE id=?", (mid,))
    print("测试前商品快照：", snap)
    uids = []
    try:
        A = new_user("A")
        B = new_user("B")
        uids = [A["uid"], B["uid"]]
        print("临时用户：", A["phone"], A["uid"], "/", B["phone"], B["uid"])

        st, j = call("/addresses", {"name": "张三", "phone": A["phone"], "region": "浙江省杭州市西湖区",
                                    "detail": "文三路 100 号 3 幢 501", "is_default": 1}, A["token"])
        ok("新建收货地址", j.get("ok") is True, j)
        addr_id = j.get("id") or (j.get("address") or {}).get("id")
        if not addr_id:
            st, j2 = call("/addresses", None, A["token"])
            addr_id = (j2.get("addresses") or [{}])[0].get("id")

        def buy(token, qty=1, note=""):
            call("/cart", {"med_id": mid, "qty": qty}, token)
            st, j = call("/order", {"addr_id": addr_id, "pay": "微信", "note": note}, token)
            return j

        # ---------- 第一单：完整正向流转 ----------
        j = buy(A["token"], 1, "请尽快发货")
        ok("下单成功", j.get("ok") is True, j)
        oid = j.get("id") or j.get("order_id")

        st, j = call("/order/%s" % oid, None, A["token"])
        o = j.get("order") or {}
        ok("订单号格式 BL+日期+序号", bool(re.match(r"^BL\d{14}$", o.get("order_no") or "")), o.get("order_no"))
        ok("待支付状态提示存在", o.get("status") == "待支付" and bool(o.get("status_tip")), o.get("status_tip"))
        titles = [n["title"] for n in o.get("timeline") or []]
        ok("待支付轨迹含「等待支付」进行中", "等待支付" in titles and
           [n["state"] for n in o["timeline"] if n["title"] == "等待支付"] == ["doing"], titles)
        ok("未发货不出现物流节点", "快递已揽收" not in titles, titles)
        ok("收货信息快照完整", (o.get("addr_info") or {}).get("name") == "张三", o.get("addr_info"))
        ok("备注已保存", o.get("note") == "请尽快发货", o.get("note"))

        st, jl = call("/orders?limit=5", None, A["token"])
        row = next((x for x in jl.get("orders") or [] if x["id"] == oid), {})
        ok("列表返回订单号与状态文案", row.get("order_no") == o.get("order_no") and bool(row.get("status_text")), row.get("order_no"))

        st, j = call("/order/%s/pay" % oid, {"pay": "微信"}, A["token"])
        ok("支付成功", j.get("ok") is True, j)
        st, j = call("/order/%s" % oid, None, A["token"])
        o = j["order"]
        titles = [n["title"] for n in o["timeline"]]
        ok("支付后轨迹含「支付成功」", "支付成功" in titles and bool(o.get("pay_time")), titles)
        ok("待发货轨迹含「药房备货中」", "药房备货中" in titles, titles)

        st, j = call("/order/%s/ship" % oid, None, A["token"], "POST")
        ok("发货成功", j.get("ok") is True, j)
        st, j = call("/order/%s" % oid, None, A["token"])
        o = j["order"]
        titles = [n["title"] for n in o["timeline"]]
        ok("运单号格式 SF+10 位", bool(re.match(r"^SF\d{10}$", o.get("express_no") or "")), o.get("express_no"))
        ok("发货后轨迹含出库/揽收/运输/派送",
           all(t in titles for t in ["药房已出库", "快递已揽收", "运输中", "派送中"]), titles)
        eno1 = o.get("express_no")
        st, j2 = call("/order/%s" % oid, None, A["token"])
        ok("运单号多次读取稳定", j2["order"].get("express_no") == eno1, j2["order"].get("express_no"))

        st, j = call("/order/%s/refund" % oid, None, A["token"], "POST")
        ok("已发货可申请退款前先确认收货流程", j.get("ok") is True, j)

        # 上面这一单已被退款，改为再下一单验证「确认收货 → 已签收」
        j = buy(A["token"], 1, "")
        oid2 = j.get("id") or j.get("order_id")
        call("/order/%s/pay" % oid2, {"pay": "支付宝"}, A["token"])
        call("/order/%s/ship" % oid2, None, A["token"], "POST")
        st, j = call("/order/%s/finish" % oid2, None, A["token"], "POST")
        ok("确认收货成功", j.get("ok") is True, j)
        st, j = call("/order/%s" % oid2, None, A["token"])
        o = j["order"]
        titles = [n["title"] for n in o["timeline"]]
        ok("完成后轨迹末节点为「已签收」", titles and titles[-1] == "已签收" and bool(o.get("finish_time")), titles)
        ok("已完成不再出现「派送中」", "派送中" not in titles, titles)
        st, j = call("/order/%s/refund" % oid2, None, A["token"], "POST")
        ok("已完成订单拒绝退款", j.get("ok") is not True and "不支持退款" in (j.get("msg") or ""), j)

        # 已退款那单的轨迹
        st, j = call("/order/%s" % oid, None, A["token"])
        titles = [n["title"] for n in j["order"]["timeline"]]
        ok("退款单轨迹含「退款成功」", "退款成功" in titles, titles)

        # ---------- 越权与删除 ----------
        st, j = call("/order/%s" % oid2, None, B["token"])
        ok("他人订单不可读(404)", st == 404 or j.get("ok") is False, (st, j))
        st, j = call("/order/%s" % oid2, None, A["token"], "DELETE")
        ok("删除订单成功", j.get("ok") is True, j)
        st, j = call("/order/%s" % oid2, None, A["token"])
        ok("已删订单详情 404", st == 404, (st, j))

    finally:
        # ---------- 物理清理 ----------
        try:
            for uid in uids:
                if not uid:
                    continue
                db.run("DELETE FROM orders WHERE user_id=?", (uid,))
                db.run("DELETE FROM cart WHERE user_id=?", (uid,))
                db.run("DELETE FROM addresses WHERE user_id=?", (uid,))
                db.run("DELETE FROM notices WHERE user_id=?", (uid,))
                db.run("DELETE FROM coupons WHERE user_id=?", (uid,))
                db.run("DELETE FROM users WHERE id=?", (uid,))
            if snap:
                db.run("UPDATE meds SET stock=?, sales=? WHERE id=?", (snap["stock"], snap["sales"], mid))
            left = db.one("SELECT stock,sales FROM meds WHERE id=?", (mid,))
            print("清理后商品快照：", left, "（测试前：", snap, "）")
            print("残留临时用户：", [db.one("SELECT id FROM users WHERE id=?", (u,)) for u in uids])
        except Exception as e:
            print("清理异常：", e)

    print("\n结果：PASS %d / FAIL %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
