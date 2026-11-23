"""
工程化基础设施：结构化日志 / 统一异常 / CORS / 限流。

app.py 只需在创建 app 后调 3 行：
    core.setup_logging()
    core.install(app)          # 异常处理 + CORS + 访问日志 + 限流
"""
import base64
import json
import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler
from urllib.parse import unquote

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import schemas

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(ROOT, "logs")
log = logging.getLogger("bailing")


# ==================== 日志 ====================
def setup_logging():
    """控制台 + 文件（logs/app.log，10MB 轮转 3 份），格式固定为 key=value 便于检索"""
    if log.handlers:
        return log
    os.makedirs(LOG_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(os.path.join(LOG_DIR, "app.log"), maxBytes=10 * 1024 * 1024,
                             backupCount=3, encoding="utf-8")
    sh = logging.StreamHandler()
    for h in (fh, sh):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    return log


# ==================== 限流（内存滑动窗口，单进程演示够用） ====================
class RateLimiter:
    """内存滑动窗口限流。

    除命中记录外维护一个计数器与上次清理时间，用于周期性 sweep：
    清理「窗口内已无命中」的过期 key，避免长时间运行（大量不同 IP/路径组合）时
    self.hits 无限膨胀。对外语义（RULES / DEFAULT_LIMIT / 429）完全不变。
    """

    SWEEP_EVERY = 500      # 累计调用达到 500 次触发一次清理
    SWEEP_SECONDS = 60     # 或距上次清理超过 60 秒触发

    def __init__(self, sweep_every=None, sweep_seconds=None):
        self.hits = {}     # key -> [最近命中时间戳...]（窗口内）
        self._lock = threading.Lock()
        self._calls = 0
        self._last_sweep = time.time()
        self.sweep_every = sweep_every or self.SWEEP_EVERY
        self.sweep_seconds = sweep_seconds or self.SWEEP_SECONDS
        self.sweep_count = 0       # 便于自测/观测
        self.swept_keys = 0

    def allow(self, key, limit, window=60):
        t = time.time()
        with self._lock:
            q = self.hits.setdefault(key, [])
            q[:] = [x for x in q if t - x < window]  # 丢掉窗口外的记录
            ok = len(q) < limit
            if ok:
                q.append(t)
            self._calls += 1
            need = self._calls >= self.sweep_every or (t - self._last_sweep) >= self.sweep_seconds
            if need:
                self._sweep(t, window)
            return ok

    def sweep(self, now=None, window=60):
        """手动触发清理（自测用），返回清理掉的 key 数量"""
        with self._lock:
            return self._sweep(time.time() if now is None else now, window)

    def _sweep(self, t, window):
        """调用方须持锁：删除窗口内无命中、已过期的 key"""
        dead = []
        for k, q in self.hits.items():
            if not q:
                dead.append(k)
                continue
            if t - q[-1] >= window:          # 最近一次命中已在窗口外 -> 该 key 过期
                q[:] = [x for x in q if t - x < window]
                if not q:
                    dead.append(k)
        for k in dead:
            self.hits.pop(k, None)
        self._last_sweep = t
        self._calls = 0
        self.sweep_count += 1
        self.swept_keys += len(dead)
        return len(dead)



LIMITER = RateLimiter()
DEFAULT_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "300"))       # 普通接口：每 IP 每分钟 300 次
RULES = {                                                        # 敏感接口单独收紧
    "/api/sms/code": 5,
    "/api/login": 10,
    "/api/register": 5,
}


def client_ip(request):
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "-")


def token_uid(request):
    """只为日志审计解析 uid，不做鉴权（鉴权在 app.uid 依赖里做）"""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return "-"
    try:
        body = auth[7:].strip().split(".")[1]
        raw = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return raw.get("uid", "-")
    except Exception:
        return "-"


# ==================== 统一异常 ====================
def install_errors(app):
    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError):
        msg = schemas.human_error(exc.errors())
        log.warning("invalid method=%s path=%s msg=%s", request.method, request.url.path, msg)
        return JSONResponse({"ok": False, "msg": msg, "detail": msg, "errors": jsonable_encoder(exc.errors())},
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        log.warning("http_error method=%s path=%s status=%s msg=%s",
                    request.method, request.url.path, exc.status_code, exc.detail)
        return JSONResponse({"ok": False, "msg": exc.detail, "detail": exc.detail},
                            status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception):
        log.exception("unhandled method=%s path=%s", request.method, request.url.path)
        return JSONResponse({"ok": False, "msg": "服务异常，请稍后重试"}, status_code=500)


# ==================== 安全响应头 ====================
# 统一给所有响应（含 429/404/异常 JSONResponse、静态资源、挂载目录）补齐安全头
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    # 前端为同源构建产物（无外链 CDN、无内联脚本），严格 CSP 不会破坏页面加载；
    # style 需 'unsafe-inline'：Vue 组件大量使用行内 style 绑定。
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
    ),
}

UPLOAD_PREFIX = "/uploads/"
UPLOAD_ALLOW_EXT = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}  # 上传目录只能放图片/PDF


def is_https(request):
    """判断外部是否 https：直连看 scheme，反代看 X-Forwarded-Proto（避免本地 http 被 HSTS 污染）"""
    if request.url.scheme == "https":
        return True
    return request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"


def harden(resp, request, upload=False):
    """给单个响应补齐安全头（upload=True 时显式强调 nosniff）"""
    for k, v in SECURITY_HEADERS.items():
        resp.headers[k] = v
    if upload:
        resp.headers["X-Content-Type-Options"] = "nosniff"
    if is_https(request):
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    return resp


def upload_path_denied(path):
    """/uploads/ 下非图片/PDF 扩展名视为不可访问（历史遗留 HTML/JS 不再可执行）"""
    if not path.startswith(UPLOAD_PREFIX):
        return False
    return os.path.splitext(unquote(path))[1].lower() not in UPLOAD_ALLOW_EXT


# ==================== 注册到 app ====================
def install(app):
    setup_logging()

    origins = os.getenv("CORS_ORIGINS", "*").split(",")
    origins = [o.strip() for o in origins if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins,
                       allow_credentials=origins != ["*"],
                       allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["X-Process-Time"])

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        ip, path = client_ip(request), request.url.path
        # /uploads 下只允许图片/PDF：其余扩展名（历史遗留 html/js）一律 404，防止被执行
        if upload_path_denied(path):
            log.warning("uploads_deny ip=%s path=%s", ip, path)
            return harden(JSONResponse({"ok": False, "msg": "文件不存在"}, status_code=404),
                          request, upload=True)
        limit = RULES.get(path)
        if limit and not LIMITER.allow(f"{ip}:{path}", limit):
            log.warning("ratelimit ip=%s path=%s limit=%s/min", ip, path, limit)
            return harden(JSONResponse({"ok": False, "msg": "操作过于频繁，请稍后再试"}, status_code=429),
                          request)
        if not LIMITER.allow(f"{ip}:*", DEFAULT_LIMIT):
            log.warning("ratelimit ip=%s path=%s limit=%s/min", ip, path, DEFAULT_LIMIT)
            return harden(JSONResponse({"ok": False, "msg": "请求过于频繁，请稍后再试"}, status_code=429),
                          request)
        t0 = time.time()
        try:
            resp = await call_next(request)
        except Exception:
            log.exception("crash method=%s path=%s ip=%s", request.method, path, ip)
            return harden(JSONResponse({"ok": False, "msg": "服务异常，请稍后重试"}, status_code=500),
                          request)
        ms = int((time.time() - t0) * 1000)
        log.info("access method=%s path=%s status=%s ms=%d ip=%s uid=%s",
                 request.method, path, resp.status_code, ms, ip, token_uid(request))
        resp.headers["X-Process-Time"] = str(ms)
        # 统一补安全头：覆盖正常响应、404/500（含统一异常处理器的 JSONResponse）、静态与挂载目录
        return harden(resp, request, upload=path.startswith(UPLOAD_PREFIX))

    install_errors(app)
    log.info("ready cors=%s rate_limit=%s/min log_file=%s",
             ",".join(origins), DEFAULT_LIMIT, os.path.join(LOG_DIR, "app.log"))
