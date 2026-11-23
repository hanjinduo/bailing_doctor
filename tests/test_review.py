# -*- coding: utf-8 -*-
"""商品评价（评分 + 晒单 + 好评率统计）端到端自测

设计原则：
1. 全部使用自建临时用户，绝不触碰演示账号（13800000000）与演示单 34/35；
2. 结束后物理清理临时数据（评价/订单/购物车/地址/通知/优惠券/用户），并还原商品库存与销量；
3. 标准库 urllib，无第三方依赖，可直接 python tests/test_review.py 运行。

覆盖点：
- 仅「已完成」订单可评价，待支付/待发货/已发货均被拒
- 一单一商品只能评价一次，重复提交被拒
- 评价商品必须在本订单内，否则被拒
- 越权：他人订单不可评价
- 参数校验：rating 超出 1~5 返回 422
- 评价后商品详情与评价接口的均分/条数/好评率/星级分布同步变化
- 列表接口 meds 返回 rating 与 review_count
- 匿名评价对外显示为「匿名用户」，昵称默认脱敏
"""
import json
import os
import random
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
    phone = "137" + "".join(random.choice("0123456789") for _ in range(8))
    st, j = call("/sms/code", {"phone": phone})
    code = j.get("code") or ""
    if not code:
        raise SystemExit("未拿到验证码回显，无法自动注册：%s" % j)
    st, j = call("/register", {"phone": phone, "pwd": "test123456", "code": code, "name": "评价测试" + tag})
    if not j.get("ok"):
        raise SystemExit("注册失败：%s" % j)
    st, j = call("/login", {"phone": phone, "pwd": "test123456"})
    return {"phone": phone, "token": j["token"], "uid": (j.get("user") or {}).get("id"),
            "name": "评价测试" + tag}


def main():
    import db

    mid = 1
    snap = db.one("SELECT id,stock,sales FROM meds WHERE id=?", (mid,))
    base_stat = db.one("SELECT COUNT(*) n FROM reviews WHERE med_id=?", (mid,))
    print("测试前商品快照：", snap, "已有评价数：", base_stat["n"])
    uids = []
    try:
        A = new_user("A")
        B = new_user("B")
        uids = [A["uid"], B["uid"]]
        print("临时用户：", A["phone"], A["uid"], "/", B["phone"], B["uid"])

        st, j = call("/addresses", {"name": "张三", "phone": A["phone"], "region": "浙江省杭州市西湖区",
                                    "detail": "文三路 100 号 3 幢 501", "is_default": 1}, A["token"])
        addr_id = j.get("id") or (j.get("address") or {}).get("id")

        def buy(token):
            call("/cart", {"med_id": mid, "qty": 1}, token)
            st, j = call("/order", {"addr_id": addr_id, "pay": "微信", "note": ""}, token)
            return j.get("id") or j.get("order_id")

        # ---------- 未完成订单不可评价 ----------
        oid_wait = buy(A["token"])
        st, j = call("/order/%s/review" % oid_wait, {"med_id": mid, "rating": 5, "content": "提前评价"}, A["token"])
        ok("待支付订单不可评价", j.get("ok") is not True and "已完成" in (j.get("msg") or ""), j)

        call("/order/%s/pay" % oid_wait, {"pay": "微信"}, A["token"])
        st, j = call("/order/%s/review" % oid_wait, {"med_id": mid, "rating": 5, "content": "待发货就评"}, A["token"])
        ok("待发货订单不可评价", j.get("ok") is not True, j)

        call("/order/%s/ship" % oid_wait, None, A["token"], "POST")
        st, j = call("/order/%s/review" % oid_wait, {"med_id": mid, "rating": 5, "content": "已发货就评"}, A["token"])
        ok("已发货订单不可评价", j.get("ok") is not True, j)

        # ---------- 已完成订单可评价 ----------
        st, j = call("/order/%s/finish" % oid_wait, None, A["token"], "POST")
        ok("确认收货成功", j.get("ok") is True, j)
        st, j = call("/order/%s" % oid_wait, None, A["token"])
        o = j.get("order") or {}
        items = o.get("items") or []
        ok("已完成订单返回 can_review=true", o.get("can_review") is True, o.get("can_review"))
        ok("订单内商品默认 reviewed=false", items and items[0].get("reviewed") is False, items[:1])

        # 非本单商品
        other = db.one("SELECT id FROM meds WHERE id<>? ORDER BY id LIMIT 1", (mid,))
        st, j = call("/order/%s/review" % oid_wait, {"med_id": other["id"], "rating": 5, "content": "x"}, A["token"])
        ok("评价非本单商品被拒", j.get("ok") is not True and "本订单" in (j.get("msg") or ""), j)

        # 评分越界
        st, j = call("/order/%s/review" % oid_wait, {"med_id": mid, "rating": 6, "content": "6 星"}, A["token"])
        ok("评分越界(6)返回 422", st == 422, (st, j))

        # 越权
        st, j = call("/order/%s/review" % oid_wait, {"med_id": mid, "rating": 5, "content": "我是别人"}, B["token"])
        ok("他人订单不可评价", j.get("ok") is not True, j)

        st, j = call("/order/%s/review" % oid_wait, {"med_id": mid, "rating": 5, "content": "药效不错，第二天就到了，包装完好"}, A["token"])
        ok("已完成订单评价成功", j.get("ok") is True, j)

        st, j = call("/order/%s/review" % oid_wait, {"med_id": mid, "rating": 4, "content": "想改一次"}, A["token"])
        ok("同一商品重复评价被拒", j.get("ok") is not True and "已评价" in (j.get("msg") or ""), j)

        st, j = call("/order/%s" % oid_wait, None, A["token"])
        items = (j.get("order") or {}).get("items") or []
        ok("订单详情回显 reviewed=true", items and items[0].get("reviewed") is True, items[:1])
        ok("全部评完后 can_review=false", (j.get("order") or {}).get("can_review") is False,
           (j.get("order") or {}).get("can_review"))

        # ---------- 统计口径 ----------
        st, j = call("/meds/%s/reviews?limit=3" % mid)
        ok("评价列表接口可匿名访问", st == 200 and j.get("ok") is True, (st, j.get("msg")))
        sm = j.get("summary") or {}
        ok("评价条数 +1", sm.get("count") == (base_stat["n"] or 0) + 1, sm)
        ok("均分在 1~5 区间", 1 <= (sm.get("avg") or 0) <= 5, sm.get("avg"))
        ok("好评率是 0~100 整数百分比", isinstance(sm.get("good_rate"), int) and 0 <= sm["good_rate"] <= 100, sm.get("good_rate"))
        ok("星级分布五档齐全", [d["star"] for d in (sm.get("dist") or [])] == [5, 4, 3, 2, 1], sm.get("dist"))
        ok("分布合计等于总条数", sum(d["n"] for d in sm["dist"]) == sm["count"], sm)
        first = (j.get("reviews") or [{}])[0]
        ok("最新评价置顶且内容一致", first.get("content", "").startswith("药效不错"), first)
        ok("昵称已脱敏", first.get("nick", "").endswith("*") and first.get("nick") != "评价测试A", first.get("nick"))
        ok("分页字段完整", all(k in j for k in ("total", "limit", "offset", "has_more")), list(j.keys()))

        st, j = call("/meds/%s" % mid)
        m = j.get("med") or {}
        ok("商品详情返回评分与评价数", m.get("rating") == sm.get("avg") and m.get("review_count") == sm.get("count"),
           (m.get("rating"), m.get("review_count")))
        st, j = call("/meds?limit=100")
        row = next((x for x in j.get("meds") or [] if x["id"] == mid), {})
        ok("商品列表返回 rating 与 review_count", row.get("rating") == sm.get("avg") and row.get("review_count") == sm.get("count"),
           (row.get("rating"), row.get("review_count")))

        # ---------- 匿名评价 ----------
        oid2 = buy(A["token"])
        call("/order/%s/pay" % oid2, {"pay": "微信"}, A["token"])
        call("/order/%s/ship" % oid2, None, A["token"], "POST")
        call("/order/%s/finish" % oid2, None, A["token"], "POST")
        st, j = call("/order/%s/review" % oid2, {"med_id": mid, "rating": 3, "content": "匿名留个言", "anon": 1}, A["token"])
        ok("匿名评价提交成功", j.get("ok") is True, j)
        st, j = call("/meds/%s/reviews?limit=3" % mid)
        first = (j.get("reviews") or [{}])[0]
        ok("匿名评价对外显示匿名用户", first.get("nick") == "匿名用户" and first.get("rating") == 3, first)

    finally:
        try:
            for uid in uids:
                if not uid:
                    continue
                db.run("DELETE FROM reviews WHERE user_id=?", (uid,))
                db.run("DELETE FROM orders WHERE user_id=?", (uid,))
                db.run("DELETE FROM cart WHERE user_id=?", (uid,))
                db.run("DELETE FROM addresses WHERE user_id=?", (uid,))
                db.run("DELETE FROM notices WHERE user_id=?", (uid,))
                db.run("DELETE FROM coupons WHERE user_id=?", (uid,))
                db.run("DELETE FROM users WHERE id=?", (uid,))
            if snap:
                db.run("UPDATE meds SET stock=?, sales=? WHERE id=?", (snap["stock"], snap["sales"], mid))
            left = db.one("SELECT stock,sales FROM meds WHERE id=?", (mid,))
            n_after = db.one("SELECT COUNT(*) n FROM reviews WHERE med_id=?", (mid,))
            print("清理后商品快照：", left, "（测试前：", snap, "）")
            print("清理后评价数：", n_after["n"], "（测试前：", base_stat["n"], "）")
            print("残留临时用户：", [db.one("SELECT id FROM users WHERE id=?", (u,)) for u in uids])
        except Exception as e:
            print("清理异常：", e)

    print("\n结果：PASS %d / FAIL %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
