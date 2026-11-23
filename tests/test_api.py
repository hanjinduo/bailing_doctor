# -*- coding: utf-8 -*-
"""
百灵医生 · 接口冒烟测试
验证 B 档三项硬指标：JWT 鉴权、Pydantic 参数校验、限流与用户数据隔离。

两种跑法（都不需要额外依赖，标准库实现）：
    python -m unittest discover -s tests -v        # 本机唯一可跑法
    pytest tests -v                                 # 装了 pytest 后可直接采集
被测服务默认 http://127.0.0.1:8010，可用环境变量 BASE_URL 覆盖。
注意：限流测试会消耗该 IP 的短信验证码额度，用例名以 z_ 开头保证最后执行。
"""
import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8010").rstrip("/")
DEMO = {"phone": "13800000000", "pwd": "123456"}  # 演示账号


def call(method, path, body=None, token=None):
    """返回 (状态码, 解析后的 body)，4xx 不抛异常。"""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "ignore")}


class TestAuth(unittest.TestCase):
    """鉴权：没有合法 JWT 一律拿不到数据"""

    def test_no_token(self):
        code, _ = call("GET", "/api/me")
        self.assertEqual(code, 401)

    def test_garbage_token(self):
        code, _ = call("GET", "/api/me", token="abc.def.ghi")
        self.assertEqual(code, 401)

    def test_forged_token(self):
        # 自己拼一个 payload 带 uid=3 的 token，签名是假值 —— 必须 401
        import base64
        head = base64.urlsafe_b64encode(b'{"uid":3,"exp":4102444800}').decode().rstrip("=")
        forged = head + "." + head + "." + "A" * 43
        code, _ = call("GET", "/api/me", token=forged)
        self.assertEqual(code, 401)

    def test_login_and_me(self):
        code, r = call("POST", "/api/login", DEMO)
        self.assertEqual(code, 200)
        self.assertTrue(r.get("token"))
        code, me = call("GET", "/api/me", token=r["token"])
        self.assertEqual(code, 200)
        self.assertEqual(me["user"]["id"], 1)


class TestValidation(unittest.TestCase):
    """参数校验：非法入参返回 422 且是中文提示，而不是 500"""

    def test_missing_field(self):
        code, r = call("POST", "/api/login", {})
        self.assertEqual(code, 422)
        self.assertIn("缺少参数", json.dumps(r, ensure_ascii=False))

    def test_bad_phone(self):
        code, r = call("POST", "/api/sms/code", {"phone": "123"})
        self.assertEqual(code, 422)
        self.assertIn("手机号", json.dumps(r, ensure_ascii=False))

    def test_short_password(self):
        code, r = call("POST", "/api/register",
                       {"phone": "13900009999", "pwd": "1", "code": "123456"})
        self.assertEqual(code, 422)
        self.assertIn("密码", json.dumps(r, ensure_ascii=False))

    def test_empty_symptom(self):
        token = call("POST", "/api/login", DEMO)[1]["token"]
        code, r = call("POST", "/api/chat/start", {"symptom": ""}, token=token)
        self.assertEqual(code, 422)


class TestIsolation(unittest.TestCase):
    """用户数据隔离：A 的 token 只能看 A 自己的数据"""

    @classmethod
    def setUpClass(cls):
        cls.token = call("POST", "/api/login", DEMO)[1]["token"]

    def test_orders_belong_to_me(self):
        code, r = call("GET", "/api/orders", token=self.token)
        self.assertEqual(code, 200)
        self.assertTrue(r.get("orders"))
        self.assertTrue(all(o.get("user_id") in (None, 1) for o in r["orders"]))

    def test_cannot_read_others_chat(self):
        # chat 10 属于 uid=3，用 uid=1 的 token 读必须被拒
        code, r = call("GET", "/api/chat/10", token=self.token)
        self.assertEqual(code, 200)
        self.assertFalse(r.get("ok"))
        self.assertIn("不存在", r.get("msg", ""))

    def test_cannot_read_others_order(self):
        code, r = call("GET", "/api/orders", token=self.token)
        others = [o["id"] for o in r["orders"] if o.get("user_id") not in (None, 1)]
        self.assertEqual(others, [])


class TestBusiness(unittest.TestCase):
    """核心业务接口可用（不验证 UI，只验证链路不 500）"""

    @classmethod
    def setUpClass(cls):
        cls.token = call("POST", "/api/login", DEMO)[1]["token"]

    def test_home(self):
        code, r = call("GET", "/api/home", token=self.token)
        self.assertEqual(code, 200)
        self.assertIn("depts", r)
        self.assertIn("doctors", r)

    def test_doctors(self):
        code, r = call("GET", "/api/doctors", token=self.token)
        self.assertEqual(code, 200)
        self.assertGreaterEqual(len(r["doctors"]), 9)

    def test_coupons(self):
        code, r = call("GET", "/api/coupons", token=self.token)
        self.assertEqual(code, 200)
        self.assertIn("coupons", r)

    def test_order_preview(self):
        code, r = call("POST", "/api/order/preview", {}, token=self.token)
        self.assertEqual(code, 200)
        self.assertIn("quote", r)


class TestzRateLimit(unittest.TestCase):
    """限流：同一 IP 打爆验证码接口后返回 429"""

    def test_sms_rate_limit(self):
        codes = [call("POST", "/api/sms/code", {"phone": "13800000000"})[0] for _ in range(12)]
        self.assertIn(429, codes, "未触发限流：%s" % codes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
