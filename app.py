"""
百灵医生 · 在线问诊 APP（FastAPI + SQLite/PostgreSQL + 通义千问 qwen-plus）
运行：python app.py   然后浏览器打开 http://127.0.0.1:8010
"""
import os, re, json, time, hashlib, shutil, urllib.request, hmac, base64, random, secrets
from datetime import date, timedelta

from fastapi import FastAPI, Header, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import core
import db
import rag
import schemas
from schemas import (AddressIn, AddressPatchIn, ApptIn, CartAddIn, CartQtyIn, ChatEndIn,
                     ChatPayIn, ChatSendIn, ChatStartIn, ClaimIn, LoginIn, NewsIn,
                     OrderCreateIn, OrderPayIn, OrderPreviewIn, ProfileIn, RegisterIn,
                     ReviewIn, RxIn, SmsIn, VipIn)

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
UPLOAD = os.path.join(ROOT, "uploads")
os.makedirs(UPLOAD, exist_ok=True)

# ==================== 一、读取配置（.env） ====================
ENV_FILES = [os.path.join(ROOT, ".env"), os.path.join(STATIC, ".env"),
             r"C:\Users\lenovo\Desktop\PythonProject\.env"]


def read_env():
    cfg = {}
    for f in ENV_FILES:
        if not os.path.exists(f):
            continue
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return cfg


ENV = read_env()


def cfg(*names, default=""):
    """按顺序取第一个非空配置，系统环境变量优先于 .env"""
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
        if ENV.get(n):
            return ENV[n]
    return default


API_KEY = cfg("QINAWEN_API_KEY", "QIANWEN_API_KEY", "DASHSCOPE_API_KEY")
BASE_URL = cfg("QINAWEN_BASE_URL", "QIANWEN_BASE_URL", "DASHSCOPE_BASE_URL",
               default="https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = cfg("QINAWEN_MODEL", "QIANWEN_MODEL", "DASHSCOPE_MODEL")
BASE_URL = BASE_URL.rstrip("/")
CHAT_URL = BASE_URL if BASE_URL.endswith("/chat/completions") else BASE_URL + "/chat/completions"

LLM_LAST = {"ok": None, "err": ""}


def llm(messages, timeout=60):
    """调用通义千问（OpenAI 兼容协议）。无 key 或失败返回空串，调用方走本地兜底。"""
    if not API_KEY:
        LLM_LAST.update(ok=False, err="未配置 API_KEY")
        return ""
    body = json.dumps({"model": MODEL, "messages": messages, "temperature": 0.7},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(CHAT_URL, data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        LLM_LAST.update(ok=True, err="")
        return text
    except Exception as e:
        LLM_LAST.update(ok=False, err=str(e)[:200])
        core.log.warning("llm_fallback err=%s", e)
        return ""


def llm_stream(messages, timeout=60):
    """流式调用通义千问（OpenAI 兼容 SSE）。

    逐个 yield 增量文本；一旦异常立即停止 yield，由调用方判断是否降级本地回复。
    这样前端拿到的仍是可逐字渲染的流，无 key / 配额耗尽时也不会白屏。
    """
    if not API_KEY:
        LLM_LAST.update(ok=False, err="未配置 API_KEY")
        return
    body = json.dumps({"model": MODEL, "messages": messages, "temperature": 0.7, "stream": True},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(CHAT_URL, data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + API_KEY})
    got = False
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    ch = json.loads(data)["choices"][0].get("delta", {}).get("content")
                except Exception:
                    continue
                if ch:
                    got = True
                    yield ch
        LLM_LAST.update(ok=got, err="" if got else "empty stream")
    except Exception as e:
        LLM_LAST.update(ok=False, err=str(e)[:200])
        core.log.warning("llm_stream_fallback err=%s", e)


# ==================== 二、数据库 ====================
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE,
  pwd TEXT, name TEXT, sex TEXT DEFAULT '男', age INT DEFAULT 30, avatar TEXT DEFAULT '👤',
  vip_until TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS depts(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, icon TEXT, intro TEXT);
CREATE TABLE IF NOT EXISTS doctors(id INTEGER PRIMARY KEY AUTOINCREMENT, dept_id INT, name TEXT,
  title TEXT, hospital TEXT, good TEXT, intro TEXT, years INT, fee REAL, icon TEXT);
CREATE TABLE IF NOT EXISTS slots(id INTEGER PRIMARY KEY AUTOINCREMENT, doctor_id INT, day TEXT,
  time TEXT, left INT);
CREATE TABLE IF NOT EXISTS appts(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, doctor_id INT,
  day TEXT, time TEXT, fee REAL, status TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, doctor_id INT,
  dept TEXT, mode TEXT, symptom TEXT, summary TEXT, duration INT DEFAULT 0, status TEXT,
  fee REAL DEFAULT 0, pay TEXT, pay_time TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS msgs(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INT, role TEXT,
  text TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, name TEXT,
  path TEXT, note TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS rxs(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, chat_id INT,
  doctor_id INT, dept TEXT, diag TEXT, advice TEXT, status TEXT DEFAULT '审核中',
  expire TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS rx_items(id INTEGER PRIMARY KEY AUTOINCREMENT, rx_id INT, name TEXT,
  spec TEXT, usage TEXT, days INT, qty INT);
CREATE TABLE IF NOT EXISTS meds(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, cat TEXT,
  spec TEXT, price REAL, intro TEXT, icon TEXT, rx INT DEFAULT 0, sales INT DEFAULT 0,
  stock INT DEFAULT NULL);
CREATE TABLE IF NOT EXISTS cart(user_id INT, med_id INT, qty INT, PRIMARY KEY(user_id, med_id));
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, items TEXT,
  amount REAL, pay TEXT, status TEXT, rx_id INT, addr_id INT, coupon_id INT, discount REAL DEFAULT 0,
  ship_fee REAL DEFAULT 0, kind TEXT DEFAULT '商品', chat_id INT, pay_time TEXT, note TEXT,
  ship_time TEXT, finish_time TEXT, express_no TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS addresses(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, name TEXT,
  phone TEXT, region TEXT, detail TEXT, is_default INT DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS coupon_tpl(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, amount REAL,
  threshold REAL, scope TEXT, days INT, icon TEXT);
CREATE TABLE IF NOT EXISTS coupons(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, tpl_id INT,
  status TEXT, got TEXT, expire TEXT, used_at TEXT);
CREATE TABLE IF NOT EXISTS pkgs(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, sub TEXT,
  price REAL, icon TEXT, intro TEXT, days INT DEFAULT 7);
CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT, cat TEXT, title TEXT,
  digest TEXT, body TEXT, icon TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, title TEXT,
  body TEXT, read INT DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, med_id INT,
  order_id INT, nick TEXT, rating INT, content TEXT, anon INT DEFAULT 0, created TEXT);
"""

# 旧库平滑升级：缺列自动补
MIGRATE_COLS = {
    "users": [("avatar", "TEXT DEFAULT '👤'"), ("token_ver", "INT DEFAULT 0")],
    "chats": [("fee", "REAL DEFAULT 0"), ("pay", "TEXT"), ("pay_time", "TEXT"),
              ("deleted", "INT DEFAULT 0")],
    "rxs": [("status", "TEXT DEFAULT '审核中'"), ("expire", "TEXT")],
    "orders": [("addr_id", "INT"), ("coupon_id", "INT"), ("discount", "REAL DEFAULT 0"),
               ("ship_fee", "REAL DEFAULT 0"), ("kind", "TEXT DEFAULT '商品'"),
               ("chat_id", "INT"), ("pay_time", "TEXT"), ("note", "TEXT"),
               ("ship_time", "TEXT"), ("finish_time", "TEXT"), ("express_no", "TEXT"),
               ("deleted", "INT DEFAULT 0")],
    "meds": [("sales", "INT DEFAULT 0"), ("stock", "INT DEFAULT NULL")],
}

# 高频过滤列建索引。
# 清单/详情接口几乎都按 user_id、chat_id、status 过滤（我的问诊、我的订单、消息列表、
# 可用号源等），没有索引时每次查询都是全表扫描：orders 表 6519px 的渲染压力背后就是
# 全量拉取 + 无索引。CREATE INDEX IF NOT EXISTS 在 SQLite 与 PostgreSQL 上语法一致，
# 双栈通用；索引名统一 idx_ 前缀，便于启动日志与 EXPLAIN 核对。
INDEXES = [
    ("idx_chats_user", "chats", "user_id, status"),      # 我的问诊按用户 + 状态筛选
    ("idx_chats_doctor", "chats", "doctor_id"),
    ("idx_chats_created", "chats", "created"),
    ("idx_msgs_chat", "msgs", "chat_id, id"),            # 会话消息按 chat_id 取并保序
    ("idx_orders_user", "orders", "user_id, status"),    # 我的订单分状态
    ("idx_orders_created", "orders", "created"),
    ("idx_rxs_user", "rxs", "user_id, status"),          # 我的处方
    ("idx_rxs_chat", "rxs", "chat_id"),
    ("idx_rx_items_rx", "rx_items", "rx_id"),            # 处方明细一对多回查
    ("idx_appts_user", "appts", "user_id, status"),      # 我的挂号
    ("idx_appts_slot", "appts", "doctor_id, day"),
    ("idx_slots_doc", "slots", "doctor_id, day"),        # 排班号源查询
    ("idx_records_user", "records", "user_id"),          # 健康档案
    ("idx_addresses_user", "addresses", "user_id"),
    ("idx_coupons_user", "coupons", "user_id, status"),  # 我的卡包
    ("idx_notices_user", "notices", "user_id, read"),    # 未读数统计
    ("idx_meds_cat", "meds", "cat, rx"),
    ("idx_kb_dim", "kb_chunks", "dim, mode"),            # RAG 向量检索按空间隔离
    ("idx_reviews_med", "reviews", "med_id, id"),        # 商品评价列表/评分统计
    ("idx_reviews_order", "reviews", "order_id, med_id"),  # 一单一商品只允许评价一次
]


def ensure_indexes():
    """启动时幂等建索引。返回 (成功列表, 跳过列表)，跳过通常是表尚未创建"""
    done, skip = [], []
    for name, table, cols in INDEXES:
        try:
            db.run("CREATE INDEX IF NOT EXISTS %s ON %s(%s)" % (name, table, cols))
            done.append(name)
        except Exception as e:
            skip.append("%s(%s)" % (name, str(e)[:50]))
    core.log.info("indexes ready ok=%d skip=%d skip_detail=%s", len(done), len(skip), skip or "-")
    return done, skip


def migrate():
    """旧库平滑升级：缺列自动补、老数据状态归一（SQLite / PostgreSQL 通用）"""
    for t, cols in MIGRATE_COLS.items():
        have = db.columns(t)
        if not have:
            continue
        for name, ddl in cols:
            if name not in have:
                db.run("ALTER TABLE %s ADD COLUMN %s %s" % (t, name, ddl))
    # 老处方补有效期：created + 3 天（日期运算放 Python 侧，两库语法无关）
    for r in q("SELECT id, created FROM rxs WHERE expire IS NULL"):
        try:
            d0 = date(*time.strptime((r["created"] or "")[:10], "%Y-%m-%d")[:3])
            exp = (d0 + timedelta(days=3)).isoformat()
        except Exception:
            exp = today()
        db.run("UPDATE rxs SET expire=? WHERE id=?", (exp, r["id"]))
    db.run("UPDATE rxs SET status='可使用' WHERE status IS NULL OR status=''")
    db.run("UPDATE chats SET status='问诊中' WHERE status='进行中'")
    db.run("UPDATE orders SET status='待发货' WHERE status='已支付'")


def q(sql, args=(), one=False):
    return db.one(sql, args) if one else db.rows(sql, args)


def x(sql, args=()):
    return db.run(sql, args)


def now():
    return time.strftime("%Y-%m-%d %H:%M")


def today():
    return date.today().isoformat()


def paging(limit, offset):
    """统一分页参数：limit 默认 20，夹紧 1~100；offset 负数归 0。
    列表接口一律“SQL 层 LIMIT/OFFSET + 同条件 COUNT(*)”取 total，不把全量数据搬到内存。"""
    try:
        limit = int(limit)
    except Exception:
        limit = 20
    try:
        offset = int(offset)
    except Exception:
        offset = 0
    return max(1, min(100, limit)), max(0, offset)


def page_meta(total, limit, offset, got):
    """返回体统一追加的分页字段（原有字段一律不动，只追加）"""
    return {"total": int(total or 0), "limit": limit, "offset": offset,
            "has_more": offset + got < int(total or 0)}


DEPTS = [("内科", "🩺", "感冒发热、高血压、糖尿病等常见内科疾病"),
         ("外科", "🔪", "外伤处理、疝气、阑尾炎等外科问题"),
         ("妇产科", "🤰", "月经不调、孕期保健、妇科炎症"),
         ("儿科", "👶", "小儿发热、咳嗽、腹泻与生长发育"),
         ("耳鼻喉科", "👂", "鼻炎、咽炎、中耳炎、听力问题"),
         ("中医科", "🌿", "中医辨证调理、失眠、体质虚弱"),
         ("呼吸内科", "🫁", "咳嗽、哮喘、慢阻肺、肺部感染"),
         ("神经内科", "🧠", "头痛、头晕、失眠、面瘫、脑血管病"),
         ("皮肤科", "🧴", "湿疹、荨麻疹、痤疮、脱发")]

# (科室, 医生名, 职称, 擅长, 工龄, 挂号费)
DOCTORS = [
    ("内科", "张明", "主任医师", "高血压、糖尿病等慢性病长期管理", 26, 50),
    ("内科", "李晓东", "副主任医师", "发热待查、上呼吸道感染、胃肠功能紊乱", 18, 35),
    ("内科", "王芳", "主治医师", "贫血、甲状腺疾病、体检报告解读", 11, 20),
    ("外科", "陈建国", "主任医师", "腹股沟疝、阑尾炎、甲状腺结节手术", 28, 50),
    ("外科", "周涛", "主治医师", "伤口处理、体表肿物、术后康复指导", 12, 20),
    ("妇产科", "刘慧", "主任医师", "孕期保健、高危妊娠、子宫肌瘤", 24, 50),
    ("妇产科", "孙倩", "主治医师", "月经不调、阴道炎、备孕咨询", 10, 20),
    ("儿科", "赵丽娟", "主任医师", "小儿反复呼吸道感染、腹泻、过敏", 25, 50),
    ("儿科", "吴凯", "主治医师", "新生儿黄疸、儿童营养与生长发育", 9, 20),
    ("耳鼻喉科", "黄志强", "主任医师", "过敏性鼻炎、鼻窦炎、中耳炎", 22, 50),
    ("耳鼻喉科", "郑小雨", "主治医师", "咽喉炎、扁桃体炎、耳鸣", 8, 20),
    ("中医科", "何文斌", "主任医师", "中医辨证调理、失眠、脾胃虚弱", 30, 50),
    ("中医科", "林静", "副主任医师", "中医体质调理、颈肩腰腿痛、针灸", 16, 35),
    ("呼吸内科", "徐立新", "主任医师", "哮喘、慢阻肺、肺部感染", 27, 50),
    ("呼吸内科", "马晓峰", "主治医师", "慢性咳嗽、支气管炎、戒烟指导", 10, 20),
    ("神经内科", "高云", "主任医师", "偏头痛、眩晕、脑血管病防治", 23, 50),
    ("神经内科", "谢峰", "主治医师", "面神经炎、失眠、周围神经病变", 9, 20),
    ("皮肤科", "杨丽", "主任医师", "湿疹、银屑病、慢性荨麻疹", 21, 50),
    ("皮肤科", "邓佳", "主治医师", "痤疮、脱发、过敏性皮炎", 8, 20)]

# 商城金刚区分类（顺序即前端展示顺序）
MED_CATS = ["感冒发热", "儿科用药", "耳鼻喉", "皮肤用药", "肠胃用药", "营养保健", "慢病用药", "抗感染", "中成药"]

# (药名, 分类, 规格, 价格, 简介, 图标, 是否处方药)
MEDS = [
    ("连花清瘟胶囊", "感冒发热", "0.35g*24粒", 25.8, "清瘟解毒、宣肺泄热，用于流感所致的发热、咳嗽、乏力", "💊", 0),
    ("蒙脱石散", "肠胃用药", "3g*10袋", 18.5, "用于成人及儿童急、慢性腹泻", "🧂", 0),
    ("维生素C片", "营养保健", "100mg*100片", 12.0, "补充维生素C，帮助增强抵抗力", "🍊", 0),
    ("板蓝根颗粒", "感冒发热", "10g*20袋", 15.6, "清热解毒、凉血利咽，用于咽喉肿痛", "🌿", 0),
    ("氯雷他定片", "皮肤用药", "10mg*6片", 22.0, "缓解过敏性鼻炎、荨麻疹引起的瘙痒", "💠", 0),
    ("健胃消食片", "肠胃用药", "0.8g*32片", 16.8, "健胃消食，用于脾胃虚弱所致的食积", "🍬", 0),
    ("藿香正气水", "中成药", "10ml*10支", 19.9, "解表化湿，用于外感风寒、中暑腹胀", "🧴", 0),
    ("布洛芬缓释胶囊", "感冒发热", "0.3g*20粒", 28.6, "缓解轻中度疼痛，也可用于退热", "💊", 0),
    ("阿莫西林胶囊", "抗感染", "0.25g*24粒", 26.5, "用于敏感菌引起的呼吸道、泌尿道感染", "💉", 1),
    ("头孢克肟片", "抗感染", "0.1g*12片", 45.0, "用于支气管炎、扁桃体炎等细菌感染", "💉", 1),
    ("二甲双胍缓释片", "慢病用药", "0.5g*30片", 32.0, "用于 2 型糖尿病患者的血糖控制", "🩸", 1),
    ("阿托伐他汀钙片", "慢病用药", "20mg*7片", 58.0, "用于高胆固醇血症、冠心病二级预防", "❤️", 1),
    ("氨氯地平片", "慢病用药", "5mg*28片", 39.0, "用于高血压、慢性稳定型心绞痛", "🫀", 1),
    ("左氧氟沙星片", "抗感染", "0.5g*6片", 42.0, "用于呼吸道、泌尿道细菌感染", "💉", 1),
    ("小儿氨酚黄那敏颗粒", "儿科用药", "6g*10袋", 18.9, "缓解儿童感冒引起的发热、鼻塞、流涕", "🧸", 0),
    ("小儿止咳糖浆", "儿科用药", "100ml", 22.5, "祛痰镇咳，用于小儿感冒引起的咳嗽", "🍯", 0),
    ("派瑞松曲安奈德益康唑乳膏", "皮肤用药", "15g", 28.5, "用于湿疹、体癣、手足癣等真菌与皮炎混合感染", "🧴", 0),
    ("糠酸莫米松鼻喷雾剂", "耳鼻喉", "50μg*60揿", 45.0, "用于过敏性鼻炎的预防与治疗", "👃", 0),
    ("蒲地蓝消炎口服液", "耳鼻喉", "10ml*6支", 32.0, "清热解毒、抗炎消肿，用于咽炎、扁桃体炎", "🍶", 0),
    ("奥美拉唑肠溶胶囊", "肠胃用药", "20mg*14粒", 25.0, "用于胃溃疡、反流性食管炎、胃酸过多", "💊", 0),
    ("复合维生素B片", "营养保健", "100片", 13.5, "补充B族维生素，用于口角炎、疲劳乏力", "🟡", 0),
    ("氨溴索口服溶液", "感冒发热", "100ml", 29.8, "祛痰药，用于痰液黏稠不易咳出", "🧪", 0),
    ("维生素D滴剂", "营养保健", "400IU*30粒", 26.0, "促进钙吸收，用于儿童与成人维生素D缺乏", "☀️", 0),
    ("复方甘草片", "感冒发热", "100片", 9.9, "镇咳祛痰，用于上呼吸道感染引起的咳嗽", "🍂", 0)]

COUPON_TPLS = [("满9减5", 5, 9, "全场", 7, "🎫"),
               ("满29减10", 10, 29, "全场", 15, "🎁"),
               ("满99减20", 20, 99, "商品", 30, "💊"),
               ("问诊满50减10", 10, 50, "问诊", 30, "🩺")]

# 服务定价（图文 / 语音 / 视频）
SERVICES = {"text": {"name": "图文问诊", "price": 50.0},
            "voice": {"name": "语音问诊", "price": 50.0},
            "video": {"name": "视频问诊", "price": 150.0}}
SHIP_FEE = 8.0
FREE_SHIP = 99.0

# 特色门诊服务套餐（虚拟服务，下单免收货地址）
PKGS = [
    ("百灵特色门诊 · 睡眠医学改善方案", "睡眠专科医生 1 对 1 评估 + 4 周改善计划", 199.0, "🌙",
     "由神经内科与中医科联合制定：含 1 次图文问诊、匹兹堡睡眠质量指数评估、作息与用药建议、"
     "4 周随访提醒。适合入睡困难、易醒、早醒人群。", 28),
    ("慢病管理季度套餐", "高血压 / 糖尿病 3 个月随访管理", 399.0, "🩸",
     "含 4 次图文问诊、2 次用药方案调整、血压血糖记录解读与饮食运动处方，专属健康管家跟进。", 90),
    ("儿童生长发育评估", "儿科医生评估 + 生长曲线解读", 129.0, "🧸",
     "含 1 次图文问诊、身高体重曲线评估、营养与睡眠建议，适合 3 至 12 岁儿童。", 14),
]

NEWS = [
    ("疾病预防", "秋冬流感高发，这几件事比吃药更重要", "流感季来临，预防的关键在细节",
     "每年 11 月至次年 3 月是流感高发期。接种流感疫苗是最有效的预防手段，建议老人、儿童、孕妇及慢性病患者优先接种。日常保持室内通风，每天开窗 2 至 3 次、每次 20 分钟；勤洗手，尽量用流动水加肥皂揉搓 20 秒以上。出现发热、咽痛、全身酸痛时应尽早就诊，不要带病上班上学。抗生素对病毒无效，切勿自行服用。", "🛡️"),
    ("疾病预防", "高血压患者如何在家正确测血压", "测量姿势不对，数值可能差 10mmHg",
     "家庭自测血压建议使用上臂式电子血压计。测量前静坐 5 分钟，不喝咖啡不吸烟，袖带与心脏保持同一水平。每次测 2 至 3 遍，间隔 1 分钟，取平均值记录。建议早晨起床后 1 小时内和晚上睡前各测一次，连续记录一周供医生判断。若家庭自测血压持续高于 135/85mmHg，应及时到内科就诊调整用药。", "🩺"),
    ("疾病预防", "久坐族的颈椎自救指南", "每天 5 分钟，缓解颈部僵硬",
     "长时间低头会使颈椎承受数倍于头部的压力。建议每工作 45 分钟起身活动，做米字操或颈部后伸训练。电脑屏幕上缘与视线平齐，手机尽量抬到胸前使用。枕头高度以一拳为宜，避免过高或过低。若出现手臂麻木、头晕、行走不稳，需到神经内科或骨科进一步检查，不要盲目按摩。", "🧠"),
    ("养生保健", "晚上睡不好？先排查这 6 个习惯", "失眠往往不是病，是习惯的问题",
     "睡前 4 小时避免咖啡、浓茶和酒精；睡前 1 小时不看手机，蓝光会抑制褪黑素分泌；卧室温度保持在 20 至 24 摄氏度；固定起床时间比固定入睡时间更重要；白天午睡不超过 30 分钟；躺下 20 分钟睡不着就起身做些轻松的事。长期失眠超过 3 个月，建议到神经内科或中医科就诊，不建议自行长期服用安眠药。", "🌙"),
    ("养生保健", "换季易感冒，中医教你固护正气", "中医讲“正气存内，邪不可干”",
     "换季时节气温波动大，人体卫外功能容易失调。日常可用黄芪、白术、防风各 10 克煮水代茶饮，适合易感冒、易出汗的气虚体质。饮食上少食生冷，多用山药、莲子、小米健脾胃。每晚温水泡脚 15 分钟，微微出汗即可。若反复感冒、乏力明显，建议到中医科辨证调理，不要盲目进补。", "🌿"),
    ("养生保健", "每天走多少步才真正有益健康", "不是越多越好，关键在强度和规律",
     "研究显示，每天 6000 至 8000 步即可显著降低心血管风险，超过 1 万步的额外收益有限。更重要的是每周累计 150 分钟中等强度运动，即走路时能说话但不能唱歌的程度。老年人或关节不适者可用快慢交替的方式，避免一次走太久。运动后出现胸闷、心悸、持续关节疼痛应及时就医。", "🚶"),
    ("饮食营养", "控糖不等于不吃主食，这样吃更稳", "主食选对，血糖更平稳",
     "完全不吃主食容易导致低血糖和代谢紊乱。建议用杂粮饭、燕麦、荞麦面替代部分白米白面，占主食的三分之一左右。进食顺序调整为蔬菜、蛋白质、主食，可明显降低餐后血糖峰值。每餐主食控制在一小碗，搭配足量绿叶菜和优质蛋白。糖尿病患者需在医生指导下结合用药调整饮食方案。", "🍚"),
    ("饮食营养", "外卖族的护胃饮食清单", "胃病多是吃出来的，改这几点就够",
     "长期高油高盐、进食不规律是年轻人胃病的主因。点外卖时优先选蒸、煮、炖类菜品，少选油炸和重辣；每餐配一份蔬菜；避免空腹喝咖啡和冰饮；晚餐与睡觉间隔 3 小时以上。若出现反酸、上腹隐痛、餐后饱胀超过两周，建议到内科做胃部检查，不要长期自行服用抑酸药。", "🥗"),
    ("饮食营养", "补钙别只喝骨头汤，这些食物更靠谱", "骨头汤里的钙，其实少得可怜",
     "骨头汤中钙含量很低，反而脂肪较多。真正高效的补钙来源是牛奶及酸奶（每 300 毫升约含 300 毫克钙）、豆腐及豆制品、深绿色蔬菜、小鱼小虾连骨食用。成人每日推荐摄入 800 毫克钙，50 岁以上建议 1000 毫克。补钙同时注意维生素 D，每天晒太阳 15 至 20 分钟有助吸收。是否需要钙片，建议先评估饮食摄入再决定。", "🥛")]

CAT_OLD_MAP = {"感冒用药": "感冒发热", "解热镇痛": "感冒发热", "营养补充": "营养保健",
               "降糖用药": "慢病用药", "降脂用药": "慢病用药", "降压用药": "慢病用药"}


def seed():
    if not q("SELECT id FROM depts LIMIT 1"):
        for n, i, it in DEPTS:
            x("INSERT INTO depts(name,icon,intro) VALUES(?,?,?)", (n, i, it))
    if not q("SELECT id FROM doctors LIMIT 1"):
        dept_id = {d["name"]: d["id"] for d in q("SELECT id,name FROM depts")}
        for d, name, title, good, yrs, fee in DOCTORS:
            intro = f"{d}·{title}，从医 {yrs} 年，累计接诊超 {yrs * 900} 人次。擅长{good}，主张先明确诊断再规范治疗。"
            x("INSERT INTO doctors(dept_id,name,title,hospital,good,intro,years,fee,icon) VALUES(?,?,?,?,?,?,?,?,?)",
              (dept_id[d], name, title, "百灵互联网医院", good, intro, yrs, fee, "👨‍⚕️" if name[0] in "张李王陈周" else "👩‍⚕️"))
    if not q("SELECT id FROM slots LIMIT 1"):
        for d in q("SELECT id FROM doctors"):
            for k in range(1, 4):
                day = (date.today() + timedelta(days=k)).isoformat()
                for t in ("上午 09:00", "下午 14:30", "晚上 19:00"):
                    x("INSERT INTO slots(doctor_id,day,time,left) VALUES(?,?,?,?)", (d["id"], day, t, 5))
    # 药品：按名称增量补齐，旧分类自动归一（兼容老库）
    for old, new in CAT_OLD_MAP.items():
        x("UPDATE meds SET cat=? WHERE cat=?", (new, old))
    for m in MEDS:
        if not q("SELECT id FROM meds WHERE name=?", (m[0],), one=True):
            x("INSERT INTO meds(name,cat,spec,price,intro,icon,rx,sales) VALUES(?,?,?,?,?,?,?,?)",
              m + (int(m[3] * 3) % 97 + 6,))
    # 演示评价：只在空表时灌入，避免覆盖真实评价
    if not q("SELECT id FROM reviews LIMIT 1"):
        uid0 = (q("SELECT id FROM users ORDER BY id LIMIT 1", one=True) or {}).get("id")
        med_id = {m["name"]: m["id"] for m in q("SELECT id,name FROM meds")}
        for nm, nick, rating, content, days in SEED_REVIEWS:
            if nm in med_id:
                x("INSERT INTO reviews(user_id,med_id,order_id,nick,rating,content,anon,created)"
                  " VALUES(?,?,?,?,?,?,?,?)",
                  (uid0, med_id[nm], 0, nick, rating, content, 0,
                   (date.today() - timedelta(days=days)).isoformat() + " 20:15"))
    if not q("SELECT id FROM news LIMIT 1"):
        for c, t, dg, b, i in NEWS:
            x("INSERT INTO news(cat,title,digest,body,icon,created) VALUES(?,?,?,?,?,?)", (c, t, dg, b, i, now()))
    if not q("SELECT id FROM coupon_tpl LIMIT 1"):
        for n, a, th, sc, dy, ic in COUPON_TPLS:
            x("INSERT INTO coupon_tpl(name,amount,threshold,scope,days,icon) VALUES(?,?,?,?,?,?)",
              (n, a, th, sc, dy, ic))
    for p in PKGS:
        if not q("SELECT id FROM pkgs WHERE name=?", (p[0],), one=True):
            x("INSERT INTO pkgs(name,sub,price,icon,intro,days) VALUES(?,?,?,?,?,?)", p)
    uid = ensure_demo_user()
    if not q("SELECT id FROM addresses WHERE user_id=?", (uid,), one=True):
        x("INSERT INTO addresses(user_id,name,phone,region,detail,is_default,created) VALUES(?,?,?,?,?,?,?)",
          (uid, "张三", "18812345678", "浙江省杭州市余杭区", "仓前街道 111 号 3 幢 502 室", 1, now()))
    if not q("SELECT id FROM coupons WHERE user_id=?", (uid,), one=True):
        # 演示券：2 张可用 + 1 张已过期（供"查看已失效卡券"展示）
        tpls = {t["name"]: t for t in q("SELECT * FROM coupon_tpl")}
        for nm, expire in (("满29减10", (date.today() + timedelta(days=15)).isoformat()),
                           ("满9减5", (date.today() + timedelta(days=7)).isoformat()),
                           ("满99减20", (date.today() - timedelta(days=2)).isoformat())):
            t = tpls.get(nm)
            if t:
                x("INSERT INTO coupons(user_id,tpl_id,status,got,expire) VALUES(?,?,?,?,?)",
                  (uid, t["id"], "已失效" if expire < today() else "未使用", now(), expire))

    # 库存初始化：NULL 表示「尚未初始化」（新库建表、旧库 ALTER 补列都会是 NULL）。
    # 只补 NULL 行，重跑不覆盖已调整的库存，幂等；人工改过库存的药品不会被重置。
    # 差异化规则：默认 30~130 件；每 7 个里有 1 个设 4（库存紧张）、每 11 个里有 1 个设 0（售罄），
    # 用于演示「库存不足 / 售罄禁买」，也是并发支付不超卖的验证对象。
    fresh = q("SELECT id FROM meds WHERE stock IS NULL ORDER BY id")
    for i, r in enumerate(fresh):
        st = 30 + (r["id"] * 17) % 100
        if i % 11 == 5:
            st = 0
        elif i % 7 == 3:
            st = 4
        x("UPDATE meds SET stock=? WHERE id=?", (st, r["id"]))
    if fresh:
        core.log.info("meds stock initialized rows=%d", len(fresh))


def ensure_demo_user():
    u = q("SELECT id FROM users WHERE phone='13800000000'", one=True)
    if u:
        return u["id"]
    return x("INSERT INTO users(phone,pwd,name,sex,age,created) VALUES(?,?,?,?,?,?)",
             ("13800000000", hash_password("123456"), "李小百", "男", 28, now()))


# ==================== 密码哈希：pbkdf2_sha256 + 随机盐 ====================
# 存储格式 "pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>"；
# 老库仍是 sha256("bailing"+pwd) 的 64 位 hex，verify_password 兼容并在登录成功时惰性迁移。
PBKDF2_ITER = 200000
PBKDF2_PREFIX = "pbkdf2_sha256$"


def _legacy_hash(p):
    """历史算法：sha256("bailing"+明文) —— 仅用于校验老数据，不再用于写入"""
    return hashlib.sha256(("bailing" + p).encode()).hexdigest()


def hash_password(p):
    """新账号/新密码统一走 pbkdf2_sha256，16 字节随机盐，逐用户独立"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", p.encode("utf-8"), salt, PBKDF2_ITER)
    return "%s%d$%s$%s" % (PBKDF2_PREFIX, PBKDF2_ITER, salt.hex(), dk.hex())


def verify_password(p, stored):
    """校验密码：新格式 pbkdf2 常数时间比较；旧格式兼容 sha256，校验通过由调用方写回新格式"""
    stored = stored or ""
    if stored.startswith(PBKDF2_PREFIX):
        try:
            _tag, iters, salt_hex, hash_hex = stored.split("$", 3)
            dk = hashlib.pbkdf2_hmac("sha256", p.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
            return hmac.compare_digest(dk.hex(), hash_hex)
        except Exception:
            return False
    # 旧格式：64 位 hex
    return hmac.compare_digest(_legacy_hash(p), stored)


def is_legacy_hash(stored):
    return not (stored or "").startswith(PBKDF2_PREFIX)


def upgrade_password(uid_, pwd):
    """惰性迁移：老格式校验通过后写回 pbkdf2；失败只记日志，不影响本次登录"""
    try:
        x("UPDATE users SET pwd=? WHERE id=?", (hash_password(pwd), uid_))
        core.log.info("pwd_migrate uid=%s -> pbkdf2", uid_)
        return True
    except Exception as e:
        core.log.warning("pwd_migrate_fail uid=%s err=%s", uid_, e)
        return False



# ==================== 三、应用与通用工具 ====================
app = FastAPI(title="百灵医生 · 在线问诊")
core.install(app)  # 结构化日志 + 统一异常 + CORS + 限流

# 前端（Vue3 + Vite）构建产物位于 static/assets，需要以静态资源方式挂载
if os.path.isdir(os.path.join(STATIC, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC, "assets")), name="assets")
app.mount("/uploads", StaticFiles(directory=UPLOAD), name="uploads")


# ==================== 鉴权：HS256 JWT（标准库实现，零外部依赖） ====================
def load_jwt_secret():
    """密钥强制：系统环境变量 > .env（复用 cfg），任何情况下都不再用公开默认密钥兜底。

    1) 已配置但不足 32 位 -> 直接拒绝启动，避免弱密钥被离线爆破；
    2) 完全未配置 -> 进程内随机密钥，本次运行可用，重启后旧 token 全部失效；
    3) 已配置且 >= 32 位 -> 正常使用，日志只打位数不打内容。
    """
    secret = cfg("JWT_SECRET")
    if secret:
        if len(secret) < 32:
            raise RuntimeError("JWT_SECRET 长度不足 32 位，拒绝启动")
        core.log.info("JWT_SECRET 已加载（%d 位）", len(secret))
        return secret.encode("utf-8")
    core.log.warning("未配置 JWT_SECRET，本次使用进程内随机密钥，重启后需重新登录；生产环境必须配置")
    return secrets.token_bytes(32)


SECRET_KEY = load_jwt_secret()
TOKEN_TTL = 7 * 24 * 3600  # 有效期 7 天


def _b64e(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def current_token_ver(u):
    """读取用户当前 token 版本号；老库/异常一律按 0，保证存量 token 不批量失效"""
    try:
        r = q("SELECT token_ver FROM users WHERE id=?", (u,), one=True)
        return int((r or {}).get("token_ver") or 0)
    except Exception:
        return 0


def make_token(u):
    """签发 HS256 JWT，payload 含 uid、ver（token 版本号）与 exp"""
    head = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64e(json.dumps({"uid": u, "ver": current_token_ver(u),
                             "exp": int(time.time()) + TOKEN_TTL}, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(SECRET_KEY, f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def uid(authorization: str = Header(default="")):
    """从 Authorization: Bearer <token> 解析用户 id，校验签名、过期与 token 版本号，失败返回 401"""
    tok = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    try:
        head, body, sig = tok.split(".")
        good = _b64e(hmac.new(SECRET_KEY, f"{head}.{body}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            raise ValueError("bad signature")
        payload = json.loads(_b64d(body))
        if int(payload["exp"]) < time.time():
            raise ValueError("expired")
        u = int(payload["uid"])
        # 版本号比对：登出会使 token_ver+1，此前签发的 token 全部失效；
        # 历史 token 无 ver 字段按 0 处理，兼容上线前已发出的 token。
        pv = int(payload.get("ver", 0) or 0)
        if pv != current_token_ver(u):
            raise ValueError("token revoked")
        return u
    except Exception:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")


def money(v):
    return round(float(v or 0), 2)


def is_vip(u):
    r = q("SELECT vip_until FROM users WHERE id=?", (u,), one=True)
    return bool(r and r["vip_until"] and r["vip_until"] >= today())


def chat_row(cid):
    return q("SELECT * FROM chats WHERE id=?", (cid,), one=True)


def rx_auto_expire():
    """已过有效期的可用处方自动失效"""
    x("UPDATE rxs SET status='已失效' WHERE status='可使用' AND expire IS NOT NULL AND expire<?", (today(),))


def rx_row(rid):
    r = q("SELECT * FROM rxs WHERE id=?", (rid,), one=True)
    if r and r["status"] == "可使用" and r["expire"] and r["expire"] < today():
        x("UPDATE rxs SET status='已失效' WHERE id=?", (rid,))
        r["status"] = "已失效"
    return r


# ---------- 优惠券 ----------
def coupon_view(c):
    t = q("SELECT * FROM coupon_tpl WHERE id=?", (c["tpl_id"],), one=True) or {}
    st = c["status"]
    if st in ("未使用", "已锁定") and (c["expire"] or "") < today():
        x("UPDATE coupons SET status='已失效' WHERE id=?", (c["id"],))
        st = "已失效"
    return {"id": c["id"], "name": t.get("name", "优惠券"), "amount": money(t.get("amount")),
            "threshold": money(t.get("threshold")), "scope": t.get("scope", "全场"),
            "icon": t.get("icon", "🎫"), "expire": c["expire"], "status": st,
            "got": c["got"], "used_at": c["used_at"]}


def lock_coupon(u, cid, amount, kind, tx=None):
    """校验并锁定优惠券，返回抵扣金额；不合规抛 ValueError。

    tx 传入时，券校验、锁券与本事务内其它写操作共用同一连接：任一步失败整体回滚，
    不会出现“券被锁住但订单没建出来”的脏数据。
    """
    get = (lambda sql, args=(): tx.one(sql, args)) if tx else (lambda sql, args=(): q(sql, args, one=True))
    put = (lambda sql, args=(): tx.run(sql, args)) if tx else (lambda sql, args=(): x(sql, args))
    c = get("SELECT * FROM coupons WHERE id=? AND user_id=?", (cid, u))
    if not c:
        raise ValueError("优惠券不存在")
    t = get("SELECT * FROM coupon_tpl WHERE id=?", (c["tpl_id"],)) or {}
    st = c["status"]
    if st in ("未使用", "已锁定") and (c["expire"] or "") < today():
        put("UPDATE coupons SET status='已失效' WHERE id=?", (c["id"],))
        st = "已失效"
    if st != "未使用":
        raise ValueError("该优惠券%s，不可使用" % st)
    if t.get("scope", "全场") not in ("全场", kind):
        raise ValueError("该券仅限「%s」使用" % t.get("scope"))
    if amount < money(t.get("threshold")):
        raise ValueError("未满 ¥%s，不能使用该券" % money(t.get("threshold")))
    put("UPDATE coupons SET status='已锁定' WHERE id=? AND status='未使用'", (cid,))
    if tx and tx.rowcount == 0:
        raise ValueError("该优惠券已被占用，请重新选择")
    return money(t.get("amount"))


def use_coupon(cid):
    if cid:
        x("UPDATE coupons SET status='已使用', used_at=? WHERE id=?", (now(), cid))


def release_coupon(cid):
    if cid:
        x("UPDATE coupons SET status=CASE WHEN expire>=? THEN '未使用' ELSE '已失效' END "
          "WHERE id=? AND status='已锁定'", (today(), cid))


def close_timeout():
    """待支付订单 / 待支付问诊单超过 30 分钟自动关闭，并释放锁定券"""
    ts = time.time()
    for o in q("SELECT * FROM orders WHERE status='待支付'"):
        try:
            t = time.mktime(time.strptime(o["created"], "%Y-%m-%d %H:%M"))
        except Exception:
            continue
        if ts - t > 30 * 60:
            x("UPDATE orders SET status='已关闭' WHERE id=? AND status='待支付'", (o["id"],))
            release_coupon(o["coupon_id"])
    for c in q("SELECT * FROM chats WHERE status='待支付'"):
        try:
            t = time.mktime(time.strptime(c["created"], "%Y-%m-%d %H:%M"))
        except Exception:
            continue
        if ts - t > 30 * 60:
            x("UPDATE chats SET status='已取消' WHERE id=? AND status='待支付'", (c["id"],))


def address_of(u, aid):
    return q("SELECT * FROM addresses WHERE id=? AND user_id=?", (aid, u), one=True)


def addr_view(a):
    return {"id": a["id"], "name": a["name"], "phone": a["phone"], "region": a["region"],
            "detail": a["detail"], "is_default": a["is_default"],
            "full": "%s%s" % (a["region"], a["detail"])}


# ==================== 四、登录与首页 ====================
@app.on_event("startup")
def on_start():
    db.init_schema(SCHEMA)
    migrate()
    seed()
    close_timeout()
    rx_auto_expire()
    ensure_indexes()
    try:
        r = rag.build()          # 增量灌库：内容未变则秒过，变更才重新向量化
        core.log.info("rag ready msg=%s chunks=%s mode=%s", r.get("msg"), r.get("chunks"), r.get("mode"))
    except Exception as e:
        core.log.warning("rag_skip err=%s", e)   # 知识库不可用不影响问诊主链路
    core.log.info("startup db=%s driver=%s model=%s key=%s",
                  db.URL or db.SQLITE_PATH, "postgresql" if db.PG else "sqlite", MODEL,
                  "已配置" if API_KEY else "未配置（走本地兜底）")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/health")
def health():
    return {"ok": True, "model": MODEL, "llm_last": LLM_LAST,
            "ci": "github-actions",
            "key": "已配置" if API_KEY else "未配置", "db": os.path.basename(db.SQLITE_PATH)}


@app.get("/api/rag/status")
def rag_status():
    """RAG 链路自检：块数、向量通道、embedding 模型、知识库文件数"""
    return rag.status()


@app.get("/api/rag/search")
def rag_search(q: str = "", k: int = 3):
    """知识库检索调试接口，返回命中片段与相关度，便于面试演示检索效果"""
    q = (q or "").strip()
    if not q:
        return {"ok": False, "msg": "请输入查询内容"}
    try:
        hits = rag.search(q, k=max(1, min(k, 10)))
    except Exception as e:
        return {"ok": False, "msg": "检索失败：%s" % str(e)[:120]}
    return {"ok": True, "query": q, "count": len(hits), "min_score": rag.MIN_SCORE, "hits": hits}


@app.post("/api/rag/rebuild")
def rag_rebuild(force: bool = False):
    """重建知识库索引。force=true 全量重算，否则按内容哈希增量更新"""
    try:
        return rag.build(force=force)
    except Exception as e:
        core.log.warning("rag_rebuild_fail err=%s", e)
        return {"ok": False, "msg": "重建失败：%s" % str(e)[:120]}


SMS_CODE = {}  # 演示环境验证码：phone -> (code, expire)
SMS_LAST = {}  # 演示环境发送时间：phone -> ts（60 秒冷却）
SMS_TRY = {}   # 演示环境校验次数：phone -> 失败次数（5 次作废）


@app.post("/api/sms/code")
def sms_code(body: SmsIn):
    """发码：不区分号码是否已注册（枚举防护），文案/结构完全一致；已注册号同样走 60 秒冷却"""
    phone = body.phone
    if time.time() - SMS_LAST.get(phone, 0) < 60:
        left = int(60 - (time.time() - SMS_LAST.get(phone, 0))) + 1
        return {"ok": False, "msg": "发送过于频繁，请 %d 秒后再试" % left}
    code = "%04d" % random.randint(0, 9999)
    SMS_CODE[phone] = (code, time.time() + 300)
    SMS_LAST[phone] = time.time()
    SMS_TRY[phone] = 0
    # 已注册号也照常写码（供验证码登录/后续流程）；两条分支返回完全一致，不暴露注册状态
    return {"ok": True, "code": code, "msg": "验证码已发送，请注意查收"}


@app.post("/api/register")
def register(body: RegisterIn):
    phone, pwd, code = body.phone, body.pwd, body.code
    rec = SMS_CODE.get(phone)
    if not rec or rec[1] < time.time():
        return {"ok": False, "msg": "验证码已过期，请重新获取"}
    if rec[0] != code:
        SMS_TRY[phone] = SMS_TRY.get(phone, 0) + 1
        if SMS_TRY[phone] >= 5:
            SMS_CODE.pop(phone, None)
            return {"ok": False, "msg": "验证码错误次数过多，请重新获取"}
        return {"ok": False, "msg": "验证码错误"}
    if q("SELECT id FROM users WHERE phone=?", (phone,), one=True):
        return {"ok": False, "msg": "该手机号已注册"}
    name = body.name or "用户" + phone[-4:]
    SMS_CODE.pop(phone, None)
    SMS_TRY.pop(phone, None)
    nid = x("INSERT INTO users(phone,pwd,name,sex,age,created) VALUES(?,?,?,?,?,?)",
            (phone, hash_password(pwd), name, "男", 30, now()))
    for t in q("SELECT * FROM coupon_tpl ORDER BY threshold LIMIT 2"):
        x("INSERT INTO coupons(user_id,tpl_id,status,got,expire) VALUES(?,?,?,?,?)",
          (nid, t["id"], "未使用", now(), (date.today() + timedelta(days=t["days"])).isoformat()))
    x("INSERT INTO notices(user_id,title,body,created) VALUES(?,?,?,?)",
      (nid, "欢迎使用百灵医生", "注册成功已发放新人优惠券，可在我的-优惠券中查看，在线问诊更方便。", now()))
    return {"ok": True, "token": make_token(nid), "user": q("SELECT id,phone,name,sex,age,vip_until FROM users WHERE id=?", (nid,), one=True)}


# 用户不存在时也跑一次同等开销的 pbkdf2，避免响应时间差异被用来枚举手机号
_NO_USER_HASH = "%s%d$%s$%s" % (PBKDF2_PREFIX, PBKDF2_ITER, "00" * 16, "00" * 32)


@app.post("/api/login")
def login(body: LoginIn):
    """登录：按手机号取用户后统一走 verify_password；老格式密码校验通过即惰性迁移为 pbkdf2"""
    u = q("SELECT * FROM users WHERE phone=?", (body.phone,), one=True)
    if not u:
        verify_password(body.pwd, _NO_USER_HASH)
        return JSONResponse({"ok": False, "msg": "手机号或密码错误"}, status_code=401)
    if not verify_password(body.pwd, u.get("pwd")):
        return JSONResponse({"ok": False, "msg": "手机号或密码错误"}, status_code=401)
    stored = u.pop("pwd", "") or ""
    if is_legacy_hash(stored):
        upgrade_password(u["id"], body.pwd)  # 惰性迁移，失败不影响本次登录
    u["vip"] = is_vip(u["id"])
    return {"ok": True, "token": make_token(u["id"]), "user": u}


@app.post("/api/logout")
def logout(u=Depends(uid)):
    """退出登录：token_ver+1，使该用户此前签发的所有 token 立即失效（401）"""
    x("UPDATE users SET token_ver=COALESCE(token_ver,0)+1 WHERE id=?", (u,))
    core.log.info("logout uid=%s token_ver+1", u)
    return {"ok": True, "msg": "已退出登录"}


@app.get("/api/home")
def home():
    return {"banner": {"title": "三甲名医在线问诊", "sub": "图文 / 语音 / 视频，平均 3 分钟接诊"},
            "depts": q("SELECT * FROM depts"),
            "doctors": q("SELECT d.*, p.name dept FROM doctors d JOIN depts p ON p.id=d.dept_id ORDER BY d.years DESC LIMIT 5"),
            "news": q("SELECT * FROM news ORDER BY id DESC LIMIT 3")}


@app.get("/api/depts")
def depts():
    return {"depts": q("SELECT * FROM depts")}


# ==================== 五、个人中心 ====================
@app.get("/api/me")
def me(u: int = Depends(uid)):
    close_timeout()
    rx_auto_expire()
    usr = q("SELECT id,phone,name,sex,age,avatar,vip_until,created FROM users WHERE id=?", (u,), one=True)
    if not usr:
        return {"ok": False, "msg": "用户不存在"}
    cnt = lambda sql, a=(): (q(sql, a, one=True) or {"n": 0})["n"]
    # 所有订单 / 会话统计统一排除软删除（deleted=1），与列表接口口径一致
    ORD_LIVE = " AND COALESCE(deleted,0)=0"
    wait_pay = cnt("SELECT COUNT(*) n FROM orders WHERE user_id=?" + ORD_LIVE, (u,)) + \
        cnt("SELECT COUNT(*) n FROM chats WHERE user_id=?" + ORD_LIVE, (u,))
    # 各状态细分数（全量 GROUP BY，不受列表接口分页影响，供个人中心宫格角标使用）
    ogrp = {r["status"]: r["n"] for r in
            q("SELECT status, COUNT(*) n FROM orders WHERE user_id=?" + ORD_LIVE + " GROUP BY status", (u,))}
    cgrp = {r["status"]: r["n"] for r in
            q("SELECT status, COUNT(*) n FROM chats WHERE user_id=?" + ORD_LIVE + " GROUP BY status", (u,))}
    stat = {"wait_pay": wait_pay,
            "wait_accept": cnt("SELECT COUNT(*) n FROM chats WHERE user_id=? AND status='待接诊'" + ORD_LIVE, (u,)),
            "in_consult": cnt("SELECT COUNT(*) n FROM chats WHERE user_id=? AND status='问诊中'" + ORD_LIVE, (u,)),
            "chats": cnt("SELECT COUNT(*) n FROM chats WHERE user_id=?" + ORD_LIVE, (u,)),
            "rxs": cnt("SELECT COUNT(*) n FROM rxs WHERE user_id=? AND status='可使用'", (u,)),
            "orders": cnt("SELECT COUNT(*) n FROM orders WHERE user_id=?" + ORD_LIVE, (u,)),
            "records": cnt("SELECT COUNT(*) n FROM records WHERE user_id=?", (u,)),
            "coupons": cnt("SELECT COUNT(*) n FROM coupons WHERE user_id=? AND status='未使用'", (u,)),
            "appts": cnt("SELECT COUNT(*) n FROM appts WHERE user_id=?", (u,)),
            "order_status": ogrp,
            "chat_status": cgrp}
    usr["vip"] = is_vip(u)
    return {"ok": True, "user": usr, "stat": stat}


@app.put("/api/me")
def me_update(body: ProfileIn, u: int = Depends(uid)):
    if body.name:
        x("UPDATE users SET name=? WHERE id=?", (body.name, u))
    if body.avatar:
        x("UPDATE users SET avatar=? WHERE id=?", (body.avatar, u))
    return {"ok": True, "msg": "资料已更新"}


# ==================== 六、收货地址 ====================
@app.get("/api/addresses")
def addresses(limit: int = 100, offset: int = 0, u: int = Depends(uid)):
    """收货地址分页：默认 limit=100（paging 上限），不传参时展示与改造前一致；
    排序仍为「默认地址优先 + id 倒序」，另加 id 作为稳定次序键。"""
    limit, offset = paging(limit, offset)
    total = (q("SELECT COUNT(*) n FROM addresses WHERE user_id=?", (u,), one=True) or {}).get("n") or 0
    rows = q("SELECT * FROM addresses WHERE user_id=? ORDER BY is_default DESC, id DESC LIMIT ? OFFSET ?",
             (u, limit, offset))
    return {"ok": True, "addresses": [addr_view(a) for a in rows],
            **page_meta(total, limit, offset, len(rows))}


@app.post("/api/addresses")
def address_add(body: AddressIn, u: int = Depends(uid)):
    name, phone, region, detail = body.name, body.phone, body.region, body.detail
    has = q("SELECT id FROM addresses WHERE user_id=?", (u,), one=True)
    is_def = 1 if (body.is_default or not has) else 0
    if is_def:
        x("UPDATE addresses SET is_default=0 WHERE user_id=?", (u,))
    aid = x("INSERT INTO addresses(user_id,name,phone,region,detail,is_default,created) VALUES(?,?,?,?,?,?,?)",
            (u, name, phone, region, detail, is_def, now()))
    return {"ok": True, "msg": "地址已保存", "id": aid}


@app.put("/api/addresses/{aid}")
def address_edit(aid: int, body: AddressPatchIn, u: int = Depends(uid)):
    a = address_of(u, aid)
    if not a:
        return {"ok": False, "msg": "地址不存在"}
    name = body.name or a["name"]
    phone = body.phone or a["phone"]
    region = body.region or a["region"]
    detail = body.detail or a["detail"]
    x("UPDATE addresses SET name=?,phone=?,region=?,detail=? WHERE id=?", (name, phone, region, detail, aid))
    if body.is_default:
        x("UPDATE addresses SET is_default=0 WHERE user_id=?", (u,))
        x("UPDATE addresses SET is_default=1 WHERE id=?", (aid,))
    return {"ok": True, "msg": "地址已更新"}


@app.post("/api/addresses/{aid}/default")
def address_default(aid: int, u: int = Depends(uid)):
    if not address_of(u, aid):
        return {"ok": False, "msg": "地址不存在"}
    x("UPDATE addresses SET is_default=0 WHERE user_id=?", (u,))
    x("UPDATE addresses SET is_default=1 WHERE id=?", (aid,))
    return {"ok": True, "msg": "已设为默认地址"}


@app.delete("/api/addresses/{aid}")
def address_del(aid: int, u: int = Depends(uid)):
    a = address_of(u, aid)
    if not a:
        return {"ok": False, "msg": "地址不存在"}
    x("DELETE FROM addresses WHERE id=?", (aid,))
    if a["is_default"]:
        left = q("SELECT id FROM addresses WHERE user_id=? ORDER BY id DESC", (u,), one=True)
        if left:
            x("UPDATE addresses SET is_default=1 WHERE id=?", (left["id"],))
    return {"ok": True, "msg": "地址已删除"}


@app.post("/api/addresses/wechat")
def address_wechat(u: int = Depends(uid)):
    """模拟从微信授权导入一条收货地址"""
    demo = [("张三", "18812345678", "浙江省杭州市余杭区", "文一西路 969 号 8 幢 1801 室"),
            ("李小百", "13800000000", "浙江省杭州市西湖区", "文三路 90 号东部软件园 6 号楼"),
            ("张伟", "13566778899", "江苏省南京市玄武区", "珠江路 588 号 2 单元 302")]
    exist = {a["detail"] for a in q("SELECT detail FROM addresses WHERE user_id=?", (u,))}
    picked = next((d for d in demo if d[3] not in exist), None)
    if not picked:
        old = q("SELECT id FROM addresses WHERE user_id=? AND detail=?", (u, demo[0][3]), one=True)
        if old:
            x("UPDATE addresses SET is_default=0 WHERE user_id=?", (u,))
            x("UPDATE addresses SET is_default=1 WHERE id=?", (old["id"],))
            return {"ok": True, "msg": "微信地址已存在，已设为默认地址", "reused": True}
        return {"ok": False, "msg": "微信地址已全部导入"}
    is_def = 1 if not q("SELECT id FROM addresses WHERE user_id=?", (u,), one=True) else 0
    x("INSERT INTO addresses(user_id,name,phone,region,detail,is_default,created) VALUES(?,?,?,?,?,?,?)",
      (u, picked[0], picked[1], picked[2], picked[3], is_def, now()))
    return {"ok": True, "msg": "已导入微信地址：%s %s" % (picked[0], picked[1])}


# ==================== 七、优惠券 ====================
@app.get("/api/coupons")
def coupons(limit: int = 100, offset: int = 0, u: int = Depends(uid)):
    """优惠券分页：分页作用于「我的券」全集（id 倒序切片），切片后再按状态分为
    coupons（可用）/invalid（已失效），tpls（领券中心）不受分页影响。
    默认 limit=100（paging 上限），不传参时展示与改造前一致。"""
    limit, offset = paging(limit, offset)
    total = (q("SELECT COUNT(*) n FROM coupons WHERE user_id=?", (u,), one=True) or {}).get("n") or 0
    rows = q("SELECT * FROM coupons WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?", (u, limit, offset))
    mine = [coupon_view(c) for c in rows]
    got = {c["tpl_id"] for c in q("SELECT tpl_id FROM coupons WHERE user_id=?", (u,))}
    tpls = [dict(t, claimed=bool(t["id"] in got)) for t in q("SELECT * FROM coupon_tpl ORDER BY threshold")]
    return {"ok": True, "coupons": [c for c in mine if c["status"] != "已失效"],
            "invalid": [c for c in mine if c["status"] == "已失效"], "tpls": tpls,
            **page_meta(total, limit, offset, len(rows))}


@app.post("/api/coupons/claim")
def coupon_claim(body: ClaimIn, u: int = Depends(uid)):
    t = q("SELECT * FROM coupon_tpl WHERE id=?", (body.tpl_id,), one=True)
    if not t:
        return {"ok": False, "msg": "优惠券不存在"}
    if q("SELECT id FROM coupons WHERE user_id=? AND tpl_id=?", (u, t["id"]), one=True):
        return {"ok": False, "msg": "该券已领取"}
    expire = (date.today() + timedelta(days=t["days"])).isoformat()
    x("INSERT INTO coupons(user_id,tpl_id,status,got,expire) VALUES(?,?,?,?,?)",
      (u, t["id"], "未使用", now(), expire))
    return {"ok": True, "msg": "领取成功：%s" % t["name"]}


@app.get("/api/coupons/usable")
def coupons_usable(amount: float = 0, kind: str = "商品", u: int = Depends(uid)):
    out = []
    for c in q("SELECT * FROM coupons WHERE user_id=? AND status='未使用'", (u,)):
        v = coupon_view(c)
        if v["status"] == "未使用" and v["scope"] in ("全场", kind) and amount >= v["threshold"]:
            out.append(v)
    out.sort(key=lambda a: -a["amount"])
    return {"ok": True, "coupons": out}



# ==================== 八、医生与挂号 ====================
def pick_doctor(dept=None, doctor_id=None):
    if doctor_id:
        return q("SELECT d.*, p.name dept FROM doctors d JOIN depts p ON p.id=d.dept_id WHERE d.id=?",
                 (doctor_id,), one=True)
    if dept:
        r = q("SELECT d.*, p.name dept FROM doctors d JOIN depts p ON p.id=d.dept_id "
              "WHERE p.name=? ORDER BY d.years DESC LIMIT 1", (dept,), one=True)
        if r:
            return r
    return q("SELECT d.*, p.name dept FROM doctors d JOIN depts p ON p.id=d.dept_id LIMIT 1", one=True)


@app.get("/api/doctors")
def doctors(dept_id: int = 0, limit: int = 100, offset: int = 0):
    """医生列表分页：dept_id 筛选语义不变；默认 limit=100 即 paging() 上限，
    保证现有 19 条医生数据在不传分页参数时展示与改造前完全一致。"""
    limit, offset = paging(limit, offset)
    where, args = "", []
    if dept_id:
        where, args = " WHERE d.dept_id=?", [dept_id]
    total = (q("SELECT COUNT(*) n FROM doctors d" + where, args, one=True) or {}).get("n") or 0
    # 排序加 id 作为稳定次序键，避免 LIMIT/OFFSET 翻页错行；与原顺序一致
    order = " ORDER BY d.id" if dept_id else " ORDER BY d.dept_id, d.id"
    rows = q("SELECT d.*, p.name dept FROM doctors d JOIN depts p ON p.id=d.dept_id" + where +
             order + " LIMIT ? OFFSET ?", args + [limit, offset])
    return {"doctors": rows, **page_meta(total, limit, offset, len(rows))}


@app.get("/api/doctor/{did}")
def doctor(did: int):
    d = q("SELECT d.*, p.name dept FROM doctors d JOIN depts p ON p.id=d.dept_id WHERE d.id=?", (did,), one=True)
    if not d:
        return {"ok": False, "msg": "医生不存在"}
    d["services"] = [{"mode": k, "name": v["name"], "price": v["price"]} for k, v in SERVICES.items()]
    d["reviews"] = [
        {"name": "王**", "score": 5, "text": "%s医生问得很细，给的用药建议很清楚，第二天就好多了。" % d["name"][0]},
        {"name": "李**", "score": 5, "text": "回复很快，没有乱开药，还提醒我什么情况需要线下就诊。"},
        {"name": "赵**", "score": 4, "text": "整体不错，视频问诊很顺畅，希望能多给一点饮食建议。"}]
    d["score"] = 4.9
    d["serve"] = 1200 + d["years"] * 83
    return {"ok": True, "doctor": d, "slots": q("SELECT * FROM slots WHERE doctor_id=? ORDER BY day,time", (did,))}


@app.post("/api/appt")
def appt(body: ApptIn, u: int = Depends(uid)):
    s = q("SELECT * FROM slots WHERE id=?", (body.slot_id,), one=True)
    if not s or s["left"] <= 0:
        return {"ok": False, "msg": "该号源已约满"}
    d = q("SELECT * FROM doctors WHERE id=?", (s["doctor_id"],), one=True)
    x("UPDATE slots SET left=left-1 WHERE id=?", (s["id"],))
    x("INSERT INTO appts(user_id,doctor_id,day,time,fee,status,created) VALUES(?,?,?,?,?,?,?)",
      (u, s["doctor_id"], s["day"], s["time"], d["fee"], "待就诊", now()))
    x("INSERT INTO notices(user_id,title,body,created) VALUES(?,?,?,?)",
      (u, "挂号成功", "%s %s 医生 %s %s，请提前 15 分钟到院。" % (s["day"], d["name"], s["time"], "") , now()))
    return {"ok": True, "msg": "挂号成功：%s %s" % (s["day"], s["time"])}


@app.get("/api/appts")
def appts(limit: int = 20, offset: int = 0, u: int = Depends(uid)):
    limit, offset = paging(limit, offset)
    base = ("FROM appts a JOIN doctors d ON d.id=a.doctor_id JOIN depts p ON p.id=d.dept_id "
            "WHERE a.user_id=?")
    total = (q("SELECT COUNT(*) n " + base, (u,), one=True) or {}).get("n") or 0
    rows = q("SELECT a.*, d.name doc, d.title, p.name dept " + base +
             " ORDER BY a.id DESC LIMIT ? OFFSET ?", (u, limit, offset))
    return {"appts": rows, **page_meta(total, limit, offset, len(rows))}


# ==================== 九、在线问诊（待支付 → 待接诊 → 问诊中 → 已结束） ====================
def rag_hits(c, text, k=3):
    """检索医疗知识库。任何异常都静默降级为空，绝不阻断问诊主链路。"""
    try:
        return rag.build_context(("%s %s" % (c["symptom"] or "", text or "")).strip(), k=k)
    except Exception as e:
        core.log.warning("rag_error err=%s", e)
        return "", []


def kb_digest(hits, limit=150):
    """把命中的知识库片段压成 2 到 3 句可读建议，供无大模型时降级使用"""
    if not hits:
        return ""
    body = re.sub(r"^#{1,3} .*$", "", hits[0]["text"], flags=re.M)
    out = ""
    for s in [x.strip() for x in re.split(r"[。\n]", body) if x.strip()]:
        if out and len(out) + len(s) > limit:
            break
        out += s + "。"
    return out


def fallback_reply(symptom, text, hits=None):
    """本地兜底回复：优先用知识库检索结果组织答案，未命中才退回关键词规则。
    这样即使大模型不可用（无 key / 配额耗尽），回复仍是基于资料的专业内容，
    而不是简单的关键词模板。"""
    digest = kb_digest(hits)
    if digest:
        s = (symptom or "").strip()
        s = s[:20] + ("…" if len(s) > 20 else "")
        return ("根据您描述的「%s」，可参考以下建议：%s"
                "以上为健康科普，不能替代面诊；如症状持续加重或出现新的不适，请及时线下就医。" % (s, digest))
    t = (text or "") + (symptom or "")
    if any(k in t for k in ("发烧", "发热", "体温")):
        return ("发热多久了？有没有超过 38.5 度？建议先物理降温、多喝温水，"
                "若持续高热或伴呼吸困难请立刻线下就诊。")
    if any(k in t for k in ("咳嗽", "咳痰", "嗓子", "咽")):
        return "咳嗽是干咳还是有痰？晚上是否加重？近期有没有受凉或接触感冒患者？"
    if any(k in t for k in ("肚子", "腹痛", "腹泻", "胃")):
        return "疼痛在哪个位置？是隐隐作痛还是绞痛？有没有呕吐或腹泻？"
    if any(k in t for k in ("头痛", "头晕")):
        return "头痛是胀痛还是跳痛？有没有伴恶心、视物模糊？最近睡眠和血压如何？"
    return "我已了解您的情况。请问症状持续多久了？之前有没有用过药、有没有药物过敏史？"


def build_msgs(c, doc, text, ctx=""):
    """组装问诊对话的 messages：角色设定 + 检索到的资料 + 最近 6 轮历史 + 本次提问"""
    sys = ("你是%s（%s·%s），正在为患者做在线问诊。请用专业、亲切的中文简短回复（100字内），"
           "必要时追问关键信息，不做确定性诊断，重症要提示线下就诊。" % (doc["name"], doc["dept"], doc["title"]))
    if ctx:
        sys += ("\n\n下面是本次问诊检索到的诊疗资料，请优先依据资料作答，"
                "资料未涉及的不要编造，尤其不得给出具体处方剂量：\n" + ctx)
    hist = q("SELECT role,text FROM msgs WHERE chat_id=? ORDER BY id", (c["id"],))[-6:]
    msgs = [{"role": "system", "content": sys},
            {"role": "user", "content": "患者主诉：" + (c["symptom"] or "")}]
    for h in hist:
        msgs.append({"role": "assistant" if h["role"] == "dr" else "user", "content": h["text"]})
    msgs.append({"role": "user", "content": text})
    return msgs


def doctor_reply(c, doc, text):
    """非流式回复（保留给老接口与测试用）"""
    ctx, hits = rag_hits(c, text)
    return llm(build_msgs(c, doc, text, ctx)) or fallback_reply(c["symptom"], text, hits)


def quick_free_left(u: int) -> int:
    """会员每月 3 次免费极速问诊，按当月 fee=0 的图文单计数。"""
    if not is_vip(u):
        return 0
    m = now()[:7]
    r = q("SELECT COUNT(*) AS n FROM chats WHERE user_id=? AND mode='text' AND fee=0 AND created LIKE ?",
          (u, m + "%"), one=True)
    return max(0, 3 - int((r or {}).get("n") or 0))


@app.post("/api/chat/start")
def chat_start(body: ChatStartIn, u: int = Depends(uid)):
    mode = body.mode if body.mode in SERVICES else "text"
    symptom = body.symptom
    d = pick_doctor(body.dept or None, body.doctor_id)
    if not d:
        return {"ok": False, "msg": "暂无医生可接诊"}
    fee = SERVICES[mode]["price"]
    free_quick = False
    if is_vip(u):
        # 会员权益：每月 3 次极速问诊免服务费（mode=text 且未指定医生）
        if mode == "text" and not body.doctor_id and quick_free_left(u) > 0:
            fee, free_quick = 0.0, True
        else:
            fee = fee * 0.9
    cid = x("INSERT INTO chats(user_id,doctor_id,dept,mode,symptom,status,fee,created) VALUES(?,?,?,?,?,?,?,?)",
            (u, d["id"], d["dept"], mode, symptom, "待支付", money(fee), now()))
    return {"ok": True, "chat_id": cid, "fee": money(fee), "service": SERVICES[mode]["name"],
            "doctor": d["name"], "vip_discount": is_vip(u), "free_quick": free_quick,
            "free_left": quick_free_left(u), "need_pay": True}


@app.get("/api/chat/{cid}")
def chat_get(cid: int, u: int = Depends(uid)):
    c = chat_row(cid)
    if not c or c["user_id"] != u:
        return {"ok": False, "msg": "会话不存在"}
    d = q("SELECT d.*, p.name dept FROM doctors d JOIN depts p ON p.id=d.dept_id WHERE d.id=?",
          (c["doctor_id"],), one=True)
    c.update({"doc": d["name"], "title": d["title"], "icon": d["icon"]})
    r = q("SELECT * FROM rxs WHERE chat_id=?", (cid,), one=True)
    return {"ok": True, "chat": c, "msgs": q("SELECT * FROM msgs WHERE chat_id=? ORDER BY id", (cid,)),
            "rx": {"id": r["id"], "status": r["status"]} if r else None}


@app.post("/api/chat/{cid}/pay")
def chat_pay(cid: int, body: ChatPayIn, u: int = Depends(uid)):
    c = chat_row(cid)
    if not c or c["user_id"] != u:
        return {"ok": False, "msg": "会话不存在"}
    if c["status"] != "待支付":
        return {"ok": False, "msg": "该问诊单无需支付（当前：%s）" % c["status"]}
    disc = 0.0
    try:
        if body.coupon_id:
            disc = lock_coupon(u, body.coupon_id, c["fee"], "问诊")
    except ValueError as e:
        return {"ok": False, "msg": str(e)}
    payable = money(max(0.0, c["fee"] - disc))
    x("UPDATE chats SET status='待接诊', pay=?, pay_time=? WHERE id=? AND status='待支付'",
      (body.pay or "微信支付", now(), cid))
    use_coupon(body.coupon_id or None)
    x("INSERT INTO notices(user_id,title,body,created) VALUES(?,?,?,?)",
      (u, "问诊支付成功", "已支付 ¥%.2f，%s %s 医生将尽快接诊。" % (payable, c["dept"], ""), now()))
    return {"ok": True, "msg": "支付成功 ¥%.2f，等待医生接诊" % payable,
            "payable": payable, "discount": disc, "status": "待接诊"}


@app.post("/api/chat/{cid}/cancel")
def chat_cancel(cid: int, u: int = Depends(uid)):
    c = chat_row(cid)
    if not c or c["user_id"] != u:
        return {"ok": False, "msg": "会话不存在"}
    if c["status"] != "待支付":
        return {"ok": False, "msg": "已支付的问诊单不支持取消，可联系客服处理"}
    x("UPDATE chats SET status='已取消' WHERE id=?", (cid,))
    return {"ok": True, "msg": "问诊单已取消"}


@app.post("/api/chat/{cid}/enter")
def chat_enter(cid: int, u: int = Depends(uid)):
    """进入问诊：待接诊 → 问诊中，并生成医生首条回复"""
    c = chat_row(cid)
    if not c or c["user_id"] != u:
        return {"ok": False, "msg": "会话不存在"}
    if c["status"] == "待支付":
        return {"ok": False, "msg": "请先完成支付"}
    if c["status"] == "待接诊":
        x("UPDATE chats SET status='问诊中' WHERE id=?", (cid,))
        c["status"] = "问诊中"
    if c["status"] == "问诊中" and not q("SELECT id FROM msgs WHERE chat_id=?", (cid,), one=True):
        d = q("SELECT * FROM doctors WHERE id=?", (c["doctor_id"],), one=True)
        d = dict(d, dept=c["dept"])
        txt = llm([{"role": "system", "content": "你是%s %s（%s·%s）。请用一句专业亲切的中文向患者打招呼，"
                                                  "针对其症状追问 1 到 2 个关键问题，80 字内。"
                                                  % (c["dept"], d["name"], c["dept"], d["title"])},
                   {"role": "user", "content": "患者主诉：" + (c["symptom"] or "")}])
        if not txt:
            txt = "您好，我是%s医生。您提到「%s」，请问症状持续多久了？有无发热或自行用药？" % (d["name"], c["symptom"])
        x("INSERT INTO msgs(chat_id,role,text,created) VALUES(?,?,?,?)", (cid, "dr", txt, now()))
    return {"ok": True, "status": c["status"]}


@app.post("/api/chat/send")
def chat_send(body: ChatSendIn, u: int = Depends(uid)):
    c = chat_row(body.chat_id)
    if not c or c["user_id"] != u:
        return {"ok": False, "msg": "会话不存在"}
    if c["status"] != "问诊中":
        return {"ok": False, "msg": "当前状态为「%s」，无法继续对话" % c["status"]}
    text = body.text
    if not text:
        return {"ok": False, "msg": "消息不能为空"}
    x("INSERT INTO msgs(chat_id,role,text,created) VALUES(?,?,?,?)", (c["id"], "user", text, now()))
    d = q("SELECT * FROM doctors WHERE id=?", (c["doctor_id"],), one=True)
    reply = doctor_reply(c, dict(d, dept=c["dept"]), text)
    x("INSERT INTO msgs(chat_id,role,text,created) VALUES(?,?,?,?)", (c["id"], "dr", reply, now()))
    return {"ok": True, "reply": reply, "llm": LLM_LAST["ok"]}


def sse(obj):
    """SSE 单帧：data: <json>\\n\\n"""
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


@app.post("/api/chat/stream")
def chat_stream(body: ChatSendIn, u: int = Depends(uid)):
    """SSE 流式问诊回复（推荐前端使用，非流式的 /api/chat/send 保留兼容）。

    帧格式：data: {"t":"delta","v":"增量文本"}
             data: {"t":"done","reply":"完整回复","source":"llm|kb|rule","hits":[...]}
    source 说明：llm=大模型生成，kb=大模型不可用时由知识库检索结果组织，rule=关键词兜底
    """
    c = chat_row(body.chat_id)
    if not c or c["user_id"] != u:
        return {"ok": False, "msg": "会话不存在"}
    if c["status"] != "问诊中":
        return {"ok": False, "msg": "当前状态为「%s」，无法继续对话" % c["status"]}
    text = body.text
    if not text:
        return {"ok": False, "msg": "消息不能为空"}

    x("INSERT INTO msgs(chat_id,role,text,created) VALUES(?,?,?,?)", (c["id"], "user", text, now()))
    d = q("SELECT * FROM doctors WHERE id=?", (c["doctor_id"],), one=True) or {}
    doc = dict(d, dept=c["dept"], name=d.get("name", "医生"), title=d.get("title", ""))
    ctx, hits = rag_hits(c, text)
    msgs = build_msgs(c, doc, text, ctx)
    cid, symptom = c["id"], c["symptom"]

    def gen():
        buf = ""
        for ch in llm_stream(msgs):
            buf += ch
            yield sse({"t": "delta", "v": ch})
        source = "llm"
        if not buf:
            source = "kb" if hits else "rule"
            local = fallback_reply(symptom, text, hits)
            for seg in re.findall(r"[^，。；！？,;!?]{1,12}[，。；！？,;!?]?", local):
                buf += seg
                yield sse({"t": "delta", "v": seg})
                time.sleep(0.03)      # 无大模型时按字推送，前端体验与真实流式一致
        x("INSERT INTO msgs(chat_id,role,text,created) VALUES(?,?,?,?)", (cid, "dr", buf, now()))
        yield sse({"t": "done", "reply": buf, "source": source, "llm": LLM_LAST["ok"],
                   "hits": [{"src": h["src"], "score": h["score"]} for h in hits]})

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@app.post("/api/chat/end")
def chat_end(body: ChatEndIn, u: int = Depends(uid)):
    c = chat_row(body.chat_id)
    if not c or c["user_id"] != u:
        return {"ok": False, "msg": "会话不存在"}
    if c["status"] == "待支付":
        return {"ok": False, "msg": "请先完成支付"}
    if c["status"] == "已结束":
        return {"ok": True, "msg": "问诊已结束"}
    d = q("SELECT * FROM doctors WHERE id=?", (c["doctor_id"],), one=True)
    conv = "\n".join("%s：%s" % ("医生" if m["role"] == "dr" else "患者", m["text"])
                     for m in q("SELECT * FROM msgs WHERE chat_id=? ORDER BY id", (c["id"],)))
    txt = llm([{"role": "system", "content": "请根据以下在线问诊对话，输出 3 到 5 句中文问诊小结，"
                                              "包含主诉、初步判断、处理建议与就医提醒，不要开具体处方剂量。"},
               {"role": "user", "content": "患者主诉：%s\n对话：\n%s" % (c["symptom"], conv or "（无对话）")}])
    if not txt:
        txt = ("患者主诉：%s。结合对话，考虑为常见轻症，建议注意休息、清淡饮食、多饮水，"
               "按需对症处理并观察 2 至 3 天；若症状加重、出现高热或呼吸困难，请及时线下就诊。" % c["symptom"])
    dur = body.duration or c["duration"] or 0
    x("UPDATE chats SET status='已结束', summary=?, duration=? WHERE id=?", (txt, dur, c["id"]))
    x("INSERT INTO notices(user_id,title,body,created) VALUES(?,?,?,?)",
      (u, "问诊已结束", "与%s医生的%s已完成，可在「我的问诊」查看小结并请医生开具处方。"
       % (d["name"], SERVICES.get(c["mode"], {}).get("name", "图文问诊")), now()))
    return {"ok": True, "msg": "问诊已结束", "summary": txt}


@app.get("/api/chats")
def chats(limit: int = 20, offset: int = 0, u: int = Depends(uid)):
    close_timeout()
    limit, offset = paging(limit, offset)
    base = "FROM chats c JOIN doctors d ON d.id=c.doctor_id WHERE c.user_id=? AND COALESCE(c.deleted,0)=0"
    total = (q("SELECT COUNT(*) n " + base, (u,), one=True) or {}).get("n") or 0
    rows = q("SELECT c.*, d.name doc, d.title, d.icon " + base +
             " ORDER BY c.id DESC LIMIT ? OFFSET ?", (u, limit, offset))
    for r in rows:
        rx = q("SELECT id,status FROM rxs WHERE chat_id=?", (r["id"],), one=True)
        r["rx"] = rx
        r["service"] = SERVICES.get(r["mode"], {}).get("name", "图文问诊")
    return {"chats": rows, **page_meta(total, limit, offset, len(rows))}


# ==================== 十、处方（审核中 → 可使用 → 已失效） ====================
RX_FALLBACK = [
    ("连花清瘟胶囊", "口服，一次 4 粒，一日 3 次", 5, 2),
    ("维生素C片", "口服，一次 1 片，一日 3 次", 7, 1),
]


@app.post("/api/rx")
def make_rx(body: RxIn, u: int = Depends(uid)):
    c = chat_row(body.chat_id)
    if not c or c["user_id"] != u:
        return {"ok": False, "msg": "会话不存在"}
    if c["status"] != "已结束":
        return {"ok": False, "msg": "请先结束问诊再开具处方"}
    old = q("SELECT id FROM rxs WHERE chat_id=?", (c["id"],), one=True)
    if old:
        return {"ok": True, "msg": "该问诊已有处方", "rx": {"id": old["id"]}}
    d = q("SELECT * FROM doctors WHERE id=?", (c["doctor_id"],), one=True)
    conv = "\n".join("%s：%s" % ("医生" if m["role"] == "dr" else "患者", m["text"])
                     for m in q("SELECT * FROM msgs WHERE chat_id=? ORDER BY id", (c["id"],)))
    prompt = ("请根据在线问诊对话给出处方建议，只输出 JSON，不要任何解释，格式："
              '{"diag":"初步诊断","advice":"注意事项(2-3句)","meds":[{"name":"药名","usage":"用法用量","days":5,"qty":1}]}。'
              "药名请从常见 OTC 药品中选择，最多 3 种。")
    raw = llm([{"role": "system", "content": "你是%s·%s，请谨慎开具处方建议。" % (c["dept"], d["title"])},
               {"role": "user", "content": "主诉：%s\n对话：\n%s\n%s" % (c["symptom"], conv or "（无）", prompt)}])
    diag, advice, items = "", "", []
    if raw:
        try:
            s = raw[raw.find("{"):raw.rfind("}") + 1]
            obj = json.loads(s)
            diag = obj.get("diag") or ""
            advice = obj.get("advice") or ""
            items = [i for i in obj.get("meds", []) if i.get("name")][:3]
        except Exception:
            diag = ""
    if not diag:
        diag = c["symptom"][:24]
    if not advice:
        advice = ("按说明书或医嘱用药，避免同时服用成分重复的复方感冒药；用药 3 天症状无改善或加重，"
                  "请及时线下就诊。孕妇、哺乳期、肝肾功能异常者用药前请咨询医师。")
    if not items:
        items = [{"name": n, "usage": us, "days": dy, "qty": qt} for n, us, dy, qt in RX_FALLBACK]
    created = now()
    expire = (date.today() + timedelta(days=3)).isoformat()
    rid = x("INSERT INTO rxs(user_id,chat_id,doctor_id,dept,diag,advice,status,expire,created) VALUES(?,?,?,?,?,?,?,?,?)",
            (u, c["id"], c["doctor_id"], c["dept"], diag, advice, "审核中", expire, created))
    for i in items:
        spec = q("SELECT spec FROM meds WHERE name=?", (i["name"],), one=True)
        x("INSERT INTO rx_items(rx_id,name,spec,usage,days,qty) VALUES(?,?,?,?,?,?)",
          (rid, i["name"], (spec or {}).get("spec", "常规规格"), i.get("usage", "按说明书服用"),
           int(i.get("days") or 5), int(i.get("qty") or 1)))
    x("INSERT INTO notices(user_id,title,body,created) VALUES(?,?,?,?)",
      (u, "处方已开具", "处方 #%d 已提交药师审核，审核通过后可用于购买处方药。" % rid, now()))
    return {"ok": True, "msg": "处方已开具，等待药师审核", "rx": {"id": rid, "status": "审核中"}}


@app.get("/api/rxs")
def rxs(status: str = "", limit: int = 20, offset: int = 0, u: int = Depends(uid)):
    rx_auto_expire()
    limit, offset = paging(limit, offset)
    sql = "FROM rxs r JOIN doctors d ON d.id=r.doctor_id WHERE r.user_id=?"
    args = [u]
    if status:
        sql += " AND r.status=?"
        args.append(status)
    total = (q("SELECT COUNT(*) n " + sql, args, one=True) or {}).get("n") or 0
    rows = q("SELECT r.*, d.name doc, d.title " + sql + " ORDER BY r.id DESC LIMIT ? OFFSET ?",
             args + [limit, offset])
    for r in rows:
        r["no"] = "BL-RX-%06d" % r["id"]
        r["count"] = len(q("SELECT id FROM rx_items WHERE rx_id=?", (r["id"],)))
    # tabs 是全部状态的分组计数，必须用全量统计，不能受分页影响
    allrows = q("SELECT status, COUNT(*) n FROM rxs WHERE user_id=? GROUP BY status", (u,))
    tabs = {"全部": sum(t["n"] for t in allrows)}
    for t in allrows:
        tabs[t["status"]] = t["n"]
    return {"ok": True, "rxs": rows, "tabs": tabs, **page_meta(total, limit, offset, len(rows))}


@app.get("/api/rx/{rid}")
def rx_get(rid: int, u: int = Depends(uid)):
    r = rx_row(rid)
    if not r or r["user_id"] != u:
        return {"ok": False, "msg": "处方不存在"}
    d = q("SELECT * FROM doctors WHERE id=?", (r["doctor_id"],), one=True)
    r.update({"doc": d["name"], "title": d["title"], "no": "BL-RX-%06d" % r["id"]})
    return {"ok": True, "rx": r, "items": q("SELECT * FROM rx_items WHERE rx_id=?", (rid,))}


@app.post("/api/rx/{rid}/audit")
def rx_audit(rid: int, u: int = Depends(uid)):
    r = rx_row(rid)
    if not r or r["user_id"] != u:
        return {"ok": False, "msg": "处方不存在"}
    if r["status"] != "审核中":
        return {"ok": False, "msg": "当前状态为「%s」，无需审核" % r["status"]}
    x("UPDATE rxs SET status='可使用' WHERE id=?", (rid,))
    x("INSERT INTO notices(user_id,title,body,created) VALUES(?,?,?,?)",
      (u, "处方审核通过", "处方 #%d 已通过药师审核，有效期至 %s，可凭方购买处方药。" % (rid, r["expire"]), now()))
    return {"ok": True, "msg": "药师审核通过，处方已可使用"}


@app.post("/api/rx/{rid}/invalid")
def rx_invalid(rid: int, u: int = Depends(uid)):
    r = rx_row(rid)
    if not r or r["user_id"] != u:
        return {"ok": False, "msg": "处方不存在"}
    x("UPDATE rxs SET status='已失效' WHERE id=?", (rid,))
    return {"ok": True, "msg": "处方已作废"}


@app.delete("/api/rx/{rid}")
def rx_del(rid: int, u: int = Depends(uid)):
    r = rx_row(rid)
    if not r or r["user_id"] != u:
        return {"ok": False, "msg": "处方不存在"}
    if q("SELECT id FROM orders WHERE rx_id=?", (rid,), one=True):
        return {"ok": False, "msg": "该处方已用于购药订单，不能删除"}
    x("DELETE FROM rx_items WHERE rx_id=?", (rid,))
    x("DELETE FROM rxs WHERE id=?", (rid,))
    return {"ok": True, "msg": "处方已删除"}



# ==================== 十一、商城：分类 / 商品 / 购物车 ====================
CAT_ICON = {"感冒发热": "🌡️", "儿科用药": "🧸", "耳鼻喉": "👂", "皮肤用药": "🧴", "肠胃用药": "🍽️",
            "营养保健": "🥛", "慢病用药": "🩸", "抗感染": "💉", "中成药": "🌿"}


def stock_of(m):
    """药品库存口径：None（未初始化）与负值均视为「不限库存」，>=0 为真实库存。

    统一在这里判定，避免各接口对 NULL / -1 的理解不一致。
    """
    s = (m or {}).get("stock")
    return -1 if s is None or int(s) < 0 else int(s)


def out_of_stock(m, need=1):
    """库存是否不足以满足 need 件（不限库存恒为 False）"""
    st = stock_of(m)
    return st >= 0 and need > st


@app.get("/api/medcats")
def medcats():
    rows = q("SELECT cat, COUNT(*) n FROM meds GROUP BY cat")
    cnt = {r["cat"]: r["n"] for r in rows}
    return {"cats": [{"name": c, "icon": CAT_ICON.get(c, "💊"), "count": cnt.get(c, 0)} for c in MED_CATS]}


# ---------- 商品评价（详情页展示 + 已完成订单提交） ----------
# 演示用历史评价：仅当 reviews 表为空时灌入，老库/已有数据不会被覆盖。
SEED_REVIEWS = [
    ("连花清瘟胶囊", "李**", 5, "感冒第三天开始吃，两次后嗓子没那么疼了，物流也快，第二天就到了。", 1),
    ("连花清瘟胶囊", "王**", 4, "效果不错，就是味道有点冲，饭后吃会好一些。", 6),
    ("连花清瘟胶囊", "陈**", 5, "家里常备，换季的时候用得上，包装完好。", 12),
    ("蒲地蓝消炎口服液", "张**", 5, "孩子嗓子发炎医生推荐的口服液，口感微苦但能接受，喝完两天见效。", 2),
    ("蒲地蓝消炎口服液", "赵**", 4, "日期新鲜，快递包装有防撞气泡膜，好评。", 9),
    ("健胃消食片", "刘**", 5, "吃多了胀气含两片就舒服点，酸甜的像山楂片，老人也能接受。", 3),
    ("健胃消食片", "孙**", 5, "回购第三次了，家里药箱必备，比线下便宜。", 15),
    ("派瑞松", "周**", 4, "脚气用了两周好转明显，就是药膏略油，建议晚上涂。", 5),
    ("布洛芬缓释胶囊", "吴**", 5, "痛经的时候吃，半小时左右见效，胃里没有明显不适。", 4),
    ("布洛芬缓释胶囊", "郑**", 5, "常备药，退烧也管用，注意别空腹吃。", 11),
    ("维生素C泡腾片", "冯**", 4, "橘子味，冲开有点甜，每天一片精神好一些。", 7),
    ("维生素C泡腾片", "蒋**", 5, "适合上班族补充，杯子里的气泡很有仪式感。", 18),
]


def nick_of(name):
    """昵称脱敏：保留首字其余打码，与真实电商的评价展示口径一致"""
    name = (name or "").strip()
    if not name:
        return "用户"
    return name[0] + "*" * min(max(len(name) - 1, 1), 3)


def review_out(r):
    return {"id": r["id"], "med_id": r["med_id"], "rating": int(r["rating"] or 5),
            "content": r.get("content") or "",
            "nick": "匿名用户" if r.get("anon") else (r.get("nick") or "用户"),
            "created": (r.get("created") or "")[:16]}


def review_stats(mid):
    """评分总览：均分、条数、好评率（4~5 星）、五星到一星分布"""
    got = {int(r["rating"] or 0): int(r["n"] or 0)
           for r in q("SELECT rating, COUNT(*) n FROM reviews WHERE med_id=? GROUP BY rating", (mid,))}
    total = sum(got.values())
    good = sum(v for k, v in got.items() if k >= 4)
    avg = round(sum(k * v for k, v in got.items()) / total, 1) if total else 0.0
    return {"avg": avg, "count": total,
            "good_rate": (round(good * 100 / total) if total else 0),
            "dist": [{"star": s, "n": got.get(s, 0)} for s in (5, 4, 3, 2, 1)]}


@app.get("/api/meds/{mid}/reviews")
def med_reviews(mid: int, limit: int = 10, offset: int = 0):
    limit, offset = paging(limit, offset)
    m = q("SELECT id,name FROM meds WHERE id=?", (mid,), one=True)
    if not m:
        return {"ok": False, "msg": "商品不存在或已下架"}
    rows = q("SELECT * FROM reviews WHERE med_id=? ORDER BY id DESC LIMIT ? OFFSET ?", (mid, limit, offset))
    st = review_stats(mid)
    return {"ok": True, "med": m, "summary": st, "reviews": [review_out(r) for r in rows],
            **page_meta(st["count"], limit, offset, len(rows))}


@app.post("/api/order/{oid}/review")
def order_review(oid: int, body: ReviewIn, u: int = Depends(uid)):
    o = own_order(u, oid)
    if not o:
        return {"ok": False, "msg": "订单不存在"}
    if o["status"] != "已完成":
        return {"ok": False, "msg": "仅已完成的订单可评价"}
    items = json.loads(o["items"] or "[]") if isinstance(o.get("items"), str) else (o.get("items") or [])
    if not any(int(it.get("med_id") or 0) == body.med_id for it in items):
        return {"ok": False, "msg": "该商品不在本订单中"}
    if q("SELECT id FROM reviews WHERE order_id=? AND med_id=?", (oid, body.med_id), one=True):
        return {"ok": False, "msg": "该商品已评价过，去商品详情看看"}
    name = (q("SELECT name FROM users WHERE id=?", (u,), one=True) or {}).get("name") or ""
    x("INSERT INTO reviews(user_id,med_id,order_id,nick,rating,content,anon,created) VALUES(?,?,?,?,?,?,?,?)",
      (u, body.med_id, oid, nick_of(name), body.rating, (body.content or "").strip(), 1 if body.anon else 0, now()))
    return {"ok": True, "msg": "评价成功，感谢你的反馈"}


@app.get("/api/meds")
def meds(cat: str = "", kind: str = "", limit: int = 20, offset: int = 0):
    limit, offset = paging(limit, offset)
    where, args = " WHERE 1=1", []
    if cat:
        where += " AND cat=?"
        args.append(cat)
    if kind == "rx":
        where += " AND rx=1"
    elif kind == "otc":
        where += " AND rx=0"
    total = (q("SELECT COUNT(*) n FROM meds" + where, args, one=True) or {}).get("n") or 0
    rows = q("SELECT m.*, (SELECT ROUND(AVG(rating),1) FROM reviews r WHERE r.med_id=m.id) rating,"
             " (SELECT COUNT(*) FROM reviews r WHERE r.med_id=m.id) review_count"
             " FROM meds m" + where.replace("cat=", "m.cat=").replace("rx=", "m.rx=")
             + " ORDER BY m.sales DESC, m.id LIMIT ? OFFSET ?",
             args + [limit, offset])
    return {"meds": rows, "cats": medcats()["cats"],
            "banner": {"title": "百灵大药房", "sub": "正品保障 · 24 小时发货 · 满 %d 包邮" % FREE_SHIP},
            **page_meta(total, limit, offset, len(rows))}


@app.get("/api/meds/{mid}")
def med_one(mid: int):
    """单个商品详情。

    此前前端商品详情页用 GET /api/meds 全量列表本地 find(id)，列表分页后 limit 默认 20，
    24 个药品里 id 靠后的商品会被判成「商品不存在或已下架」；改为按主键查，顺带返回库存。
    """
    m = q("SELECT * FROM meds WHERE id=?", (mid,), one=True)
    if not m:
        return {"ok": False, "msg": "商品不存在或已下架"}
    st = review_stats(mid)
    m["rating"] = st["avg"]
    m["review_count"] = st["count"]
    m["stock_note"] = "不限量" if stock_of(m) < 0 else ("仅剩 %d 件" % stock_of(m) if stock_of(m) else "已售罄")
    m["tips"] = ["正品保障 · 24 小时发货 · 满 ¥%d 包邮（会员包邮）" % FREE_SHIP,
                 "规格：%s，请按说明书或遵医嘱使用" % (m.get("spec") or "-"),
                 "7 天无理由退换，处方药需凭有效处方购买"]
    return {"ok": True, "med": m}


@app.get("/api/pkgs")
def pkgs():
    return {"ok": True, "pkgs": q("SELECT * FROM pkgs ORDER BY price")}


@app.get("/api/pkgs/{pid}")
def pkg_one(pid: int):
    p = q("SELECT * FROM pkgs WHERE id=?", (pid,), one=True)
    if not p:
        return {"ok": False, "msg": "服务不存在"}
    p["tips"] = ["下单后 24 小时内健康管家电话联系确认时间", "服务有效期 %d 天，未使用可申请退款" % p["days"],
                 "虚拟服务无需收货地址，购买后可在订单中查看服务凭证"]
    return {"ok": True, "pkg": p}


@app.get("/api/cart")
def cart_get(u: int = Depends(uid)):
    items = cart_items(u)
    return {"items": items, "amount": money(sum(i["amount"] for i in items)),
            "has_rx": any(i["rx"] for i in items)}


@app.post("/api/cart")
def cart_add(body: CartAddIn, u: int = Depends(uid)):
    m = q("SELECT * FROM meds WHERE id=?", (body.med_id,), one=True)
    if not m:
        return {"ok": False, "msg": "商品不存在"}
    qty = body.qty
    old = q("SELECT qty FROM cart WHERE user_id=? AND med_id=?", (u, m["id"]), one=True)
    have = old["qty"] if old else 0
    # 库存校验：累计数量（购物车已有 + 本次）超过真实库存时拒绝，避免加进去才发现买不了
    if out_of_stock(m, have + qty):
        st = stock_of(m)
        return {"ok": False, "msg": "「%s」库存不足，仅剩 %d 件" % (m["name"], st) if st
                else "「%s」已售罄" % m["name"]}
    if old:
        x("UPDATE cart SET qty=? WHERE user_id=? AND med_id=?", (have + qty, u, m["id"]))
    else:
        x("INSERT INTO cart(user_id,med_id,qty) VALUES(?,?,?)", (u, m["id"], qty))
    return {"ok": True, "msg": "已加入购物车：%s" % m["name"]}


@app.put("/api/cart/{mid}")
def cart_qty(mid: int, body: CartQtyIn, u: int = Depends(uid)):
    qty = body.qty  # qty=0 即删除该商品
    if qty <= 0:
        x("DELETE FROM cart WHERE user_id=? AND med_id=?", (u, mid))
        return {"ok": True, "msg": "已更新"}
    m = q("SELECT * FROM meds WHERE id=?", (mid,), one=True)
    if out_of_stock(m, qty):
        st = stock_of(m)
        return {"ok": False, "msg": "「%s」库存不足，最多可买 %d 件" % (m["name"], st) if st
                else "「%s」已售罄" % m["name"]}
    x("UPDATE cart SET qty=? WHERE user_id=? AND med_id=?", (qty, u, mid))
    return {"ok": True, "msg": "已更新"}


@app.delete("/api/cart/{mid}")
def cart_del(mid: int, u: int = Depends(uid)):
    x("DELETE FROM cart WHERE user_id=? AND med_id=?", (u, mid))
    return {"ok": True, "msg": "已移除"}


def cart_items(u):
    rows = q("SELECT c.qty, m.id mid, m.name, m.spec, m.price, m.rx, m.icon, m.cat, m.stock FROM cart c "
             "JOIN meds m ON m.id=c.med_id WHERE c.user_id=? ORDER BY m.id", (u,))
    return [{"med_id": r["mid"], "name": r["name"], "spec": r["spec"], "price": money(r["price"]),
             "qty": r["qty"], "rx": r["rx"], "icon": r["icon"], "cat": r["cat"],
             "stock": stock_of(r), "amount": money(r["price"] * r["qty"])} for r in rows]


def quote(u, items, coupon_id=None, kind="商品"):
    subtotal = money(sum(i["amount"] for i in items))
    vip = is_vip(u)
    ship = 0.0 if (vip or subtotal >= FREE_SHIP or subtotal <= 0) else SHIP_FEE
    disc = 0.0
    if coupon_id:
        c = q("SELECT * FROM coupons WHERE id=? AND user_id=?", (int(coupon_id), u), one=True)
        if c:
            v = coupon_view(c)
            if v["status"] == "未使用" and v["scope"] in ("全场", kind) and subtotal >= v["threshold"]:
                disc = v["amount"]
    return {"subtotal": subtotal, "ship": money(ship), "discount": money(disc),
            "total": money(max(0.0, subtotal + ship - disc)), "vip": vip,
            "free_ship_at": FREE_SHIP, "ship_fee": SHIP_FEE}


# ==================== 十二、确认订单 / 订单状态机 ====================
@app.post("/api/order/preview")
def order_preview(body: OrderPreviewIn, u: int = Depends(uid)):
    kind = "商品"
    pkg = q("SELECT * FROM pkgs WHERE id=?", (body.pkg_id,), one=True) if body.pkg_id else None
    if pkg:
        kind = "服务"
        items = [{"name": pkg["name"], "spec": pkg["sub"], "price": money(pkg["price"]), "qty": 1,
                  "amount": money(pkg["price"]), "rx": 0, "icon": pkg["icon"], "med_id": 0}]
    else:
        items = cart_items(u)
    q0 = quote(u, items, body.coupon_id or None, kind)
    usable, others = [], []
    for c in q("SELECT * FROM coupons WHERE user_id=? AND status='未使用'", (u,)):
        v = coupon_view(c)
        if v["status"] != "未使用":
            continue
        ok = v["scope"] in ("全场", kind) and q0["subtotal"] >= v["threshold"]
        (usable if ok else others).append(dict(v, usable=ok))
    usable.sort(key=lambda a: -a["amount"])
    addrs = q("SELECT * FROM addresses WHERE user_id=? ORDER BY is_default DESC, id DESC", (u,))
    rx_list = [r for r in q("SELECT * FROM rxs WHERE user_id=? ORDER BY id DESC", (u,)) if rx_row(r["id"])["status"] == "可使用"]
    return {"ok": True, "kind": kind, "pkg": pkg, "items": items, "quote": q0, "coupons": usable,
            "coupons_disabled": others, "addresses": [addr_view(a) for a in addrs],
            "has_rx": any(i["rx"] for i in items),
            "rxs": [{"id": r["id"], "diag": r["diag"], "no": "BL-RX-%06d" % r["id"]} for r in rx_list]}


@app.post("/api/order")
def order_create(body: OrderCreateIn, u: int = Depends(uid)):
    pkg = q("SELECT * FROM pkgs WHERE id=?", (body.pkg_id,), one=True) if body.pkg_id else None
    if pkg:
        kind = "服务"
        items = [{"name": pkg["name"], "spec": pkg["sub"], "price": money(pkg["price"]), "qty": 1,
                  "amount": money(pkg["price"]), "rx": 0, "icon": pkg["icon"], "med_id": 0}]
    else:
        kind = "商品"
        items = cart_items(u)
    if not items:
        return {"ok": False, "msg": "购物车为空"}
    need_rx = any(i["rx"] for i in items)
    addr = None
    if body.addr_id:
        addr = address_of(u, body.addr_id)
        if not addr:
            return {"ok": False, "msg": "收货地址不存在"}
    elif kind == "商品" and not need_rx:
        return {"ok": False, "msg": "请先选择收货地址"}
    rx = None
    if need_rx:
        if not body.rx_id:
            return {"ok": False, "msg": "含处方药，请选择有效处方"}
        rx = rx_row(body.rx_id)
        if not rx or rx["user_id"] != u:
            return {"ok": False, "msg": "处方不存在"}
        if rx["status"] != "可使用":
            return {"ok": False, "msg": "该处方%s，不能用于购买处方药" % rx["status"]}
    # 库存预检：下单前先挡一次，避免用户走到支付页才被拒。
    # 真正的强一致在 order_pay 的事务内用条件 UPDATE 扣减兜住（并发下不会超卖）。
    for i in items:
        if not i.get("med_id"):
            continue
        mm = q("SELECT * FROM meds WHERE id=?", (i["med_id"],), one=True)
        if out_of_stock(mm, i["qty"]):
            st = stock_of(mm)
            return {"ok": False, "msg": "「%s」库存不足，仅剩 %d 件" % (i["name"], st) if st
                    else "「%s」已售罄" % i["name"]}
    q0 = quote(u, items, body.coupon_id or None, kind)
    try:
        # 券校验 → 锁券 → 建单 三步同一事务：任一步失败整体回滚，不会留下被锁死却无单的券
        with db.tx() as t:
            disc = 0.0
            if body.coupon_id:
                disc = lock_coupon(u, body.coupon_id, q0["subtotal"], kind, tx=t)
            q0["discount"] = disc
            q0["total"] = money(max(0.0, q0["subtotal"] + q0["ship"] - disc))
            oid = t.run("INSERT INTO orders(user_id,items,amount,pay,status,rx_id,addr_id,coupon_id,discount,ship_fee,"
                        "kind,note,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (u, json.dumps(items, ensure_ascii=False), q0["total"], body.pay or "微信支付",
                         "待支付", rx["id"] if rx else None, addr["id"] if addr else None,
                         body.coupon_id or None, disc, q0["ship"], kind, body.note, now()))
    except ValueError as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": True, "msg": "订单已提交，请支付 ¥%.2f" % q0["total"], "order_id": oid,
            "payable": q0["total"], "discount": disc, "ship": q0["ship"], "kind": kind}


@app.get("/api/orders")
def orders(status: str = "", limit: int = 20, offset: int = 0, u: int = Depends(uid)):
    close_timeout()
    limit, offset = paging(limit, offset)
    # 软删除：deleted=1 的订单（用户主动删除）不再出现在列表与计数中
    where, args = " WHERE user_id=? AND COALESCE(deleted,0)=0", [u]
    if status:
        where += " AND status=?"
        args.append(status)
    total = (q("SELECT COUNT(*) n FROM orders" + where, args, one=True) or {}).get("n") or 0
    rows = q("SELECT * FROM orders" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
             args + [limit, offset])
    out = [order_attach(o) for o in rows]
    return {"ok": True, "orders": out, **page_meta(total, limit, offset, len(out))}


@app.get("/api/order/{oid}")
def order_get(oid: int, u: int = Depends(uid)):
    o = q("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, u), one=True)
    if not o:
        return {"ok": False, "msg": "订单不存在"}
    # 已软删除的订单不可再读：404，避免旧链接/分享继续访问已删数据
    if o.get("deleted"):
        return JSONResponse({"ok": False, "msg": "订单不存在"}, status_code=404)
    return {"ok": True, "order": order_attach(o)}


def own_order(u, oid):
    return q("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, u), one=True)


# ---------- 订单号与物流轨迹（对外展示口径，与内部自增 id 解耦） ----------
def order_no(o):
    """对外单号：BL + 下单日期 + 6 位序号，例如 BL20261119000042"""
    d = str(o.get("created") or "")[:10].replace("-", "") or time.strftime("%Y%m%d")
    return "BL%s%06d" % (d, int(o.get("id") or 0))


def express_no(o):
    """运单号：发货时落库；历史订单按 id 推导，保证同一订单多次读取稳定一致"""
    return o.get("express_no") or "SF%010d" % (int(o.get("id") or 0) * 137 + 4021)


def _dt(s):
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return time.strptime(str(s or ""), f)
        except Exception:
            pass
    return None


def _shift(s, hours):
    t = _dt(s)
    if not t:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(time.mktime(t) + hours * 3600))


def order_timeline(o):
    """按订单真实字段（created/pay_time/ship_time/finish_time）生成物流轨迹，不臆造已完成节点。
       返回按时间正序的节点，state: done 已完成 / doing 进行中 / wait 未开始。"""
    st = o.get("status") or ""
    nodes = [{"title": "订单提交成功", "desc": "等待买家付款",
              "time": o.get("created") or "", "state": "done"}]
    if o.get("pay_time"):
        nodes.append({"title": "支付成功", "desc": o.get("pay") or "在线支付",
                      "time": o["pay_time"], "state": "done"})
    elif st == "待支付":
        nodes.append({"title": "等待支付", "desc": "下单后 30 分钟内未支付将自动关闭",
                      "time": "", "state": "doing"})
    if st == "已取消":
        nodes.append({"title": "订单已取消", "desc": "买家主动取消，券与库存已退回",
                      "time": "", "state": "done"})
    elif st == "已关闭":
        nodes.append({"title": "订单已关闭", "desc": "超时未支付，系统自动关闭",
                      "time": "", "state": "done"})
    elif st == "已退款":
        nodes.append({"title": "退款成功", "desc": "款项已原路退回，库存已回补",
                      "time": "", "state": "done"})

    if o.get("ship_time"):
        nodes.append({"title": "药房已出库", "desc": "百灵大药房（杭州仓）",
                      "time": o["ship_time"], "state": "done"})
        nodes.append({"title": "快递已揽收", "desc": "顺丰速运 " + express_no(o),
                      "time": _shift(o["ship_time"], 2), "state": "done"})
        nodes.append({"title": "运输中", "desc": "快件已到达【杭州转运中心】",
                      "time": _shift(o["ship_time"], 9), "state": "done"})
        if o.get("finish_time"):
            nodes.append({"title": "已签收", "desc": "本人签收，感谢使用百灵医生",
                          "time": o["finish_time"], "state": "done"})
        else:
            nodes.append({"title": "派送中", "desc": "派送员 王师傅 138****6621 正在为您派送",
                          "time": _shift(o["ship_time"], 26), "state": "doing"})
    elif st == "待发货":
        nodes.append({"title": "药房备货中", "desc": "订单已推送至药房，预计 24 小时内出库",
                      "time": "", "state": "doing"})
    return nodes


def order_attach(o):
    """统一的订单对外视图：单号、地址快照、券名、状态文案、物流轨迹"""
    o["items"] = json.loads(o["items"] or "[]") if isinstance(o.get("items"), str) else (o.get("items") or [])
    a = q("SELECT * FROM addresses WHERE id=?", (o["addr_id"],), one=True) if o.get("addr_id") else None
    o["addr"] = ("%s %s %s%s" % (a["name"], a["phone"], a["region"], a["detail"])) if a else ""
    o["addr_info"] = {"name": a["name"], "phone": a["phone"],
                      "region": a["region"], "detail": a["detail"]} if a else None
    c = q("SELECT * FROM coupon_tpl WHERE id=(SELECT tpl_id FROM coupons WHERE id=?)",
          (o["coupon_id"],), one=True) if o.get("coupon_id") else None
    o["coupon_name"] = c["name"] if c else ""
    o["order_no"] = order_no(o)
    o["express_no"] = express_no(o) if o.get("ship_time") else ""
    o["status_text"] = {"待支付": "待支付", "待发货": "已支付 · 待发货", "已发货": "已发货",
                        "已完成": "已完成", "已取消": "已取消", "已关闭": "已关闭（超时）",
                        "已退款": "已退款"}.get(o["status"], o["status"])
    o["status_tip"] = {"待支付": "请在 30 分钟内完成支付，超时订单将自动关闭",
                       "待发货": "药房正在备货，发货后将推送物流单号",
                       "已发货": "快件运输中，收到商品后请确认收货",
                       "已完成": "交易已完成，可按需申请售后或再次购买",
                       "已取消": "订单已取消，优惠券与库存已退回",
                       "已关闭": "订单因超时未支付已自动关闭",
                       "已退款": "退款已原路退回，到账时间以支付渠道为准"}.get(o["status"], "")
    o["timeline"] = order_timeline(o)
    # 已完成订单里每件商品是否已评价，供订单详情页渲染「评价/已评价」按钮
    if o.get("status") == "已完成":
        done = {r["med_id"] for r in q("SELECT med_id FROM reviews WHERE order_id=?", (o["id"],))}
        for it in o["items"]:
            it["reviewed"] = int(it.get("med_id") or 0) in done
    o["can_review"] = o.get("status") == "已完成" and any(not it.get("reviewed") for it in o["items"])
    return o


@app.post("/api/order/{oid}/pay")
def order_pay(oid: int, body: OrderPayIn | None = None, u: int = Depends(uid)):
    o = own_order(u, oid)
    if not o:
        return {"ok": False, "msg": "订单不存在"}
    # 不再用读出状态提前拦截：状态是否可支付一律由事务内 UPDATE ... WHERE status='待支付'
    # 的 rowcount 判定，避免「先查后改」在并发下双写
    svc = (o["kind"] or "商品") == "服务"
    pay = (body.pay if body else "") or o["pay"] or "微信支付"
    items = json.loads(o["items"] or "[]")
    ntitle = "服务购买成功" if svc else "支付成功"
    nbody = ("订单 #%d 已支付 ¥%.2f，健康管家将在 24 小时内与您联系确认服务时间。" % (oid, o["amount"])
             if svc else "订单 #%d 已支付 ¥%.2f，仓库将于 24 小时内发货。" % (oid, o["amount"]))
    try:
        # 状态迁移 → 核销券 → 加销量 → 清购物车 → 写通知，全部同一事务；
        # 迁移 rowcount=0 说明订单已被其它请求处理，整体回滚，避免销量/通知重复累加
        with db.tx() as t:
            t.run("UPDATE orders SET status=?, pay=?, pay_time=? WHERE id=? AND status='待支付'",
                  ("已完成" if svc else "待发货", pay, now(), oid))
            if t.rowcount == 0:
                raise ValueError("订单已处理，请勿重复支付")
            if o["coupon_id"]:
                t.run("UPDATE coupons SET status='已使用', used_at=? WHERE id=? AND status='已锁定'",
                      (now(), o["coupon_id"]))
            if not svc:
                for i in items:
                    # 库存扣减与销量累加用「条件更新」完成：stock>=qty 才扣，
                    # rowcount=0 说明库存已被别的订单抢走，整单回滚，天然不超卖；
                    # stock 为 NULL / 负值表示不限库存（虚拟商品），走第二条只累加销量。
                    t.run("UPDATE meds SET stock=stock-?, sales=sales+? WHERE id=? AND stock>=?",
                          (i["qty"], i["qty"], i["med_id"], i["qty"]))
                    if t.rowcount == 0:
                        t.run("UPDATE meds SET sales=sales+? WHERE id=? AND (stock IS NULL OR stock<0)",
                              (i["qty"], i["med_id"]))
                        if t.rowcount == 0:
                            raise ValueError("「%s」库存不足，本次支付已取消，库存已释放" % i.get("name", "商品"))
                t.run("DELETE FROM cart WHERE user_id=?", (u,))
            t.run("INSERT INTO notices(user_id,title,body,created) VALUES(?,?,?,?)",
                  (u, ntitle, nbody, now()))
    except ValueError as e:
        return {"ok": False, "msg": str(e)}
    if svc:
        return {"ok": True, "msg": "支付成功 ¥%.2f，服务已预约" % o["amount"], "status": "已完成"}
    return {"ok": True, "msg": "支付成功 ¥%.2f" % o["amount"], "status": "待发货"}


@app.post("/api/order/{oid}/cancel")
def order_cancel(oid: int, u: int = Depends(uid)):
    o = own_order(u, oid)
    if not o:
        return {"ok": False, "msg": "订单不存在"}
    if o["status"] != "待支付":
        return {"ok": False, "msg": "仅待支付订单可取消，已支付订单请申请退款"}
    x("UPDATE orders SET status='已取消' WHERE id=? AND status='待支付'", (oid,))
    release_coupon(o["coupon_id"])
    return {"ok": True, "msg": "订单已取消，优惠券已退回"}


@app.post("/api/order/{oid}/ship")
def order_ship(oid: int, u: int = Depends(uid)):
    o = own_order(u, oid)
    if not o:
        return {"ok": False, "msg": "订单不存在"}
    if o["status"] != "待发货":
        return {"ok": False, "msg": "订单当前状态为「%s」，不能发货" % o["status"]}
    eno = express_no(o)
    x("UPDATE orders SET status='已发货', ship_time=?, express_no=? WHERE id=?", (now(), eno, oid))
    x("INSERT INTO notices(user_id,title,body,created) VALUES(?,?,?,?)",
      (u, "您的订单已发货", "订单 %s 已由百灵大药房发出，顺丰速运 %s，可在订单详情查看物流轨迹。"
       % (order_no(o), eno), now()))
    return {"ok": True, "msg": "商家已发货（模拟）"}


@app.post("/api/order/{oid}/finish")
def order_finish(oid: int, u: int = Depends(uid)):
    o = own_order(u, oid)
    if not o:
        return {"ok": False, "msg": "订单不存在"}
    if o["status"] != "已发货":
        return {"ok": False, "msg": "订单当前状态为「%s」，不能确认收货" % o["status"]}
    x("UPDATE orders SET status='已完成', finish_time=? WHERE id=?", (now(), oid))
    return {"ok": True, "msg": "已确认收货，订单完成"}


@app.post("/api/order/{oid}/refund")
def order_refund(oid: int, u: int = Depends(uid)):
    """退款：状态迁移 + 库存回补 + 销量回退 + 通知，同一事务；重复退款由条件更新 rowcount 兜住"""
    o = own_order(u, oid)
    if not o:
        return {"ok": False, "msg": "订单不存在"}
    if o["status"] not in ("待发货", "已发货"):
        return {"ok": False, "msg": "订单当前状态为「%s」，不支持退款" % o["status"]}
    items = json.loads(o["items"] or "[]")
    svc = (o["kind"] or "商品") == "服务"
    try:
        with db.tx() as t:
            t.run("UPDATE orders SET status='已退款' WHERE id=? AND user_id=? AND status IN ('待发货','已发货')",
                  (oid, u))
            if t.rowcount == 0:
                raise ValueError("订单已处理，请勿重复退款")
            if not svc:
                # 支付时扣掉的库存要还回来，否则退款越多库存越少；销量同步回退，不低于 0
                for i in items:
                    mid = i.get("med_id") or 0
                    qty = int(i.get("qty") or 0)
                    if not mid or qty <= 0:
                        continue
                    t.run("UPDATE meds SET stock=CASE WHEN stock IS NULL THEN NULL ELSE stock+? END,"
                          " sales=CASE WHEN sales>=? THEN sales-? ELSE 0 END WHERE id=?",
                          (qty, qty, qty, mid))
            t.run("INSERT INTO notices(user_id,title,body,created) VALUES(?,?,?,?)",
                  (u, "退款成功", "订单 #%d 已模拟退款 ¥%.2f，预计 1 至 3 个工作日原路返回。"
                   % (oid, o["amount"]), now()))
    except ValueError as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": True, "msg": "已模拟退款 ¥%.2f" % o["amount"]}


# 可删除的订单状态：均为业务终态，删除不会影响售后/履约流程
ORDER_DELETABLE = ("已取消", "已关闭", "已退款", "已完成")


@app.delete("/api/order/{oid}")
def order_delete(oid: int, u: int = Depends(uid)):
    """订单软删除：置 deleted=1，列表/详情/统计统一排除，历史数据与售后链路不受影响"""
    o = q("SELECT * FROM orders WHERE id=? AND user_id=? AND COALESCE(deleted,0)=0",
          (oid, u), one=True)
    # 不存在 / 越权 / 已删 一律 404，不泄露他人订单是否存在
    if not o:
        return JSONResponse({"ok": False, "msg": "订单不存在"}, status_code=404)
    if o["status"] not in ORDER_DELETABLE:
        return JSONResponse({"ok": False, "msg": "当前状态不可删除"}, status_code=400)
    try:
        with db.tx() as t:
            # 条件更新 + rowcount 判定：并发下重复删除只有一次能命中
            t.run("UPDATE orders SET deleted=1 WHERE id=? AND user_id=? AND COALESCE(deleted,0)=0",
                  (oid, u))
            if t.rowcount == 0:
                raise LookupError("订单不存在")
    except LookupError as e:
        return JSONResponse({"ok": False, "msg": str(e)}, status_code=404)
    return {"ok": True, "msg": "订单已删除"}


# ==================== 十三、消息 / 资讯 / 病历 / 会员 ====================
@app.get("/api/msgs")
def msgs(limit: int = 20, offset: int = 0, u: int = Depends(uid)):
    """会话列表、未读数保持全量（不受分页影响），只对消息中心的 notices 列表分页"""
    limit, offset = paging(limit, offset)
    rows = q("SELECT c.*, d.name doc, d.icon, (SELECT text FROM msgs WHERE chat_id=c.id ORDER BY id DESC LIMIT 1) last "
             "FROM chats c JOIN doctors d ON d.id=c.doctor_id "
             "WHERE c.user_id=? AND COALESCE(c.deleted,0)=0 ORDER BY c.id DESC", (u,))
    total = (q("SELECT COUNT(*) n FROM notices WHERE user_id=?", (u,), one=True) or {}).get("n") or 0
    notices = q("SELECT * FROM notices WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (u, limit, offset))
    return {"chats": rows, "notices": notices,
            "unread": len(q("SELECT id FROM notices WHERE user_id=? AND read=0", (u,))),
            **page_meta(total, limit, offset, len(notices))}


@app.post("/api/msgs/read")
def msgs_read(u: int = Depends(uid)):
    x("UPDATE notices SET read=1 WHERE user_id=?", (u,))
    return {"ok": True, "msg": "已全部标记为已读"}


@app.delete("/api/msg/notice/{nid}")
def notice_delete(nid: int, u: int = Depends(uid)):
    """系统通知硬删除：通知是单条播报，无下游引用，直接物理删除"""
    with db.tx() as t:
        t.run("DELETE FROM notices WHERE id=? AND user_id=?", (nid, u))
        n = t.rowcount
    if not n:
        return JSONResponse({"ok": False, "msg": "通知不存在"}, status_code=404)
    return {"ok": True, "msg": "通知已删除"}


@app.delete("/api/chat/{cid}")
def chat_delete(cid: int, u: int = Depends(uid)):
    """会话软删除：订单/处方详情可能跳转到会话页，软删保证详情接口不断链"""
    try:
        with db.tx() as t:
            t.run("UPDATE chats SET deleted=1 WHERE id=? AND user_id=? AND COALESCE(deleted,0)=0",
                  (cid, u))
            if t.rowcount == 0:
                raise LookupError("会话不存在")
    except LookupError as e:
        return JSONResponse({"ok": False, "msg": str(e)}, status_code=404)
    return {"ok": True, "msg": "会话已删除"}


@app.get("/api/news")
def news(cat: str = "全部", limit: int = 20, offset: int = 0):
    limit, offset = paging(limit, offset)
    where, args = "", []
    if cat and cat != "全部":
        where, args = " WHERE cat=?", [cat]
    total = (q("SELECT COUNT(*) n FROM news" + where, args, one=True) or {}).get("n") or 0
    rows = q("SELECT * FROM news" + where + " ORDER BY id DESC LIMIT ? OFFSET ?", args + [limit, offset])
    cats = ["全部"] + [r["cat"] for r in q("SELECT DISTINCT cat FROM news ORDER BY cat")]
    return {"news": rows, "cats": cats, **page_meta(total, limit, offset, len(rows))}


@app.get("/api/news/{nid}")
def news_one(nid: int):
    n = q("SELECT * FROM news WHERE id=?", (nid,), one=True)
    return {"ok": bool(n), "news": n}


@app.post("/api/news/generate")
def news_gen(body: NewsIn | None = None):
    cat = (body.cat if body else "") or "养生保健"
    txt = llm([{"role": "system", "content": "你是健康科普编辑。请输出 JSON："
                                              '{"title":"标题","digest":"一句话摘要","body":"正文300字左右"}，不要额外解释。'},
               {"role": "user", "content": "写一篇关于「%s」的科普文章，内容科学准确，适合大众阅读。" % cat}])
    title, digest, body_t = "", "", ""
    if txt:
        try:
            obj = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
            title, digest, body_t = obj.get("title", ""), obj.get("digest", ""), obj.get("body", "")
        except Exception:
            body_t = txt
    if not title:
        title = "换季健康小贴士"
        digest = "规律作息、均衡饮食比盲目进补更重要"
        body_t = ("换季时气温与湿度变化明显，人体适应能力下降，容易出现疲劳、咽干、睡眠变差等问题。"
                  "建议保持规律作息，每天保证 7 小时睡眠；饮食上少油少盐，增加蔬菜水果和优质蛋白；"
                  "适度运动以微微出汗为宜。若出现持续不适，建议及时在线问诊或到院检查。")
    nid = x("INSERT INTO news(cat,title,digest,body,icon,created) VALUES(?,?,?,?,?,?)",
            (cat, title, digest, body_t, "✨", now()))
    return {"ok": True, "news": {"id": nid, "title": title, "digest": digest, "cat": cat, "body": body_t}}


@app.get("/api/records")
def records(limit: int = 20, offset: int = 0, u: int = Depends(uid)):
    limit, offset = paging(limit, offset)
    total = (q("SELECT COUNT(*) n FROM records WHERE user_id=?", (u,), one=True) or {}).get("n") or 0
    rows = q("SELECT * FROM records WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
             (u, limit, offset))
    return {"records": rows, **page_meta(total, limit, offset, len(rows))}


# ==================== 上传安全：类型白名单 + 5MB 上限 ====================
UPLOAD_MAX = 5 * 1024 * 1024                      # 5MB
UPLOAD_EXT_MAP = {"jpg": ".jpg", "jpeg": ".jpg", "png": ".png", "webp": ".webp", "pdf": ".pdf"}
UPLOAD_CTYPE_MAP = {                              # content_type -> 允许的客户端扩展名
    "image/jpeg": {"jpg", "jpeg"},
    "image/png": {"png"},
    "image/webp": {"webp"},
    "application/pdf": {"pdf"},
}
UPLOAD_BAD_TYPE = {"ok": False, "msg": "仅支持 JPG/PNG/WEBP/PDF 格式"}
UPLOAD_BAD_SIZE = {"ok": False, "msg": "文件大小不能超过 5MB"}


def upload_magic_ok(head, ext):
    """文件头 magic 字节校验：扩展名必须与真实内容一致"""
    if ext in ("jpg", "jpeg"):
        return head[:3] == b"\xff\xd8\xff"
    if ext == "png":
        return head[:4] == b"\x89PNG"
    if ext == "webp":
        return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext == "pdf":
        return head[:4] == b"%PDF"
    return False


def upload_safe_name(name):
    """展示用文件名：只取 basename 并限长，避免客户端 filename 携带路径分隔符"""
    base = (name or "").replace("\\", "/").split("/")[-1].strip()
    return base[:120] or "record"


@app.post("/api/record/upload")
async def record_upload(file: UploadFile = File(...), note: str = Form(""), u: int = Depends(uid)):
    name = upload_safe_name(file.filename)
    raw_ext = os.path.splitext(name)[1].lstrip(".").lower()
    ctype = (file.content_type or "").split(";")[0].strip().lower()
    # 校验一、二重：扩展名白名单 + content_type 与扩展名一致
    if raw_ext not in UPLOAD_EXT_MAP or raw_ext not in UPLOAD_CTYPE_MAP.get(ctype, set()):
        return JSONResponse(UPLOAD_BAD_TYPE, status_code=400)
    # 校验三重：magic 字节
    head = await file.read(16)
    if not upload_magic_ok(head, raw_ext):
        return JSONResponse(UPLOAD_BAD_TYPE, status_code=400)
    # 边读边计数，超限立即中止；此时尚未落盘，不会残留半成品
    buf = bytearray(head)
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > UPLOAD_MAX:
            return JSONResponse(UPLOAD_BAD_SIZE, status_code=400)
    # 落盘名完全由服务端生成（不取客户端 filename）；records.name 保留原名用于展示与下载
    ext = UPLOAD_EXT_MAP[raw_ext]
    path = os.path.join(UPLOAD, "%d_%d_%s%s" % (u, int(time.time() * 1000), secrets.token_hex(4), ext))
    tmp = path + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(bytes(buf))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)                      # 原子替换，避免出现半截文件
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        core.log.exception("upload_write_fail uid=%s name=%s", u, name)
        return JSONResponse({"ok": False, "msg": "上传失败，请稍后重试"}, status_code=500)
    x("INSERT INTO records(user_id,name,path,note,created) VALUES(?,?,?,?,?)", (u, name, path, note, now()))
    core.log.info("upload_ok uid=%s size=%d ext=%s", u, len(buf), raw_ext)
    return {"ok": True, "msg": "上传成功"}


@app.get("/api/record/file/{rid}")
def record_file(rid: int, u: int = Depends(uid)):
    r = q("SELECT * FROM records WHERE id=?", (rid,), one=True)
    if not r or not os.path.exists(r["path"]):
        return JSONResponse({"ok": False, "msg": "文件不存在"}, status_code=404)
    return FileResponse(r["path"], filename=r["name"])


@app.delete("/api/record/{rid}")
def record_del(rid: int, u: int = Depends(uid)):
    r = q("SELECT * FROM records WHERE id=? AND user_id=?", (rid, u), one=True)
    if not r:
        return {"ok": False, "msg": "病历不存在"}
    if os.path.exists(r["path"]):
        try:
            os.remove(r["path"])
        except Exception:
            pass
    x("DELETE FROM records WHERE id=?", (rid,))
    return {"ok": True, "msg": "已删除"}


@app.get("/api/vip")
def vip_info(u: int = Depends(uid)):
    r = q("SELECT vip_until FROM users WHERE id=?", (u,), one=True)
    until = r["vip_until"] if r else None
    active = bool(until and until >= today())
    return {"ok": True, "vip": active, "vip_until": until if active else None,
            "quick_free_left": quick_free_left(u), "quick_free_total": 3,
            "benefits": [{"icon": "⚡", "name": "免费极速问诊", "desc": "会员每月 3 次极速问诊免服务费"},
                         {"icon": "💬", "name": "图文问诊优惠", "desc": "图文问诊 9 折，全年不限次"},
                         {"icon": "🎥", "name": "视频问诊优惠", "desc": "视频问诊 9 折，优先安排名医"},
                         {"icon": "📦", "name": "购药包邮", "desc": "商城订单不限金额包邮"}],
            "plans": [{"name": "连续包月", "price": 19, "months": 1, "note": "首月 9 元"},
                      {"name": "季度会员", "price": 49, "months": 3, "note": "折合 16.3 元/月"},
                      {"name": "年度会员", "price": 168, "months": 12, "note": "折合 14 元/月，赠 2 张问诊券"}]}


@app.post("/api/vip/buy")
def vip_buy(body: VipIn, u: int = Depends(uid)):
    months = body.months
    price = {1: 19, 3: 49, 12: 168}.get(months, months * 19)
    r = q("SELECT vip_until FROM users WHERE id=?", (u,), one=True)
    start = date.today()
    if r and r["vip_until"] and r["vip_until"] > today():
        start = date(*map(int, r["vip_until"].split("-")))
    until = (start + timedelta(days=30 * months)).isoformat()
    x("UPDATE users SET vip_until=? WHERE id=?", (until, u))
    x("INSERT INTO notices(user_id,title,body,created) VALUES(?,?,?,?)",
      (u, "会员开通成功", "百灵健康会员已开通 %d 个月，有效期至 %s，问诊享 9 折、购药包邮。" % (months, until), now()))
    return {"ok": True, "msg": "开通成功，有效期至 %s" % until, "vip_until": until, "price": price}


# ==================== 十四、启动 ====================
if __name__ == "__main__":
    import uvicorn
    print("百灵医生启动中：http://127.0.0.1:8010")
    uvicorn.run(app, host="0.0.0.0", port=8010)


# ==================== 前端 SPA 路由回退（Vue Router history 模式深链接） ====================
@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/") or path.startswith("uploads/"):
        return JSONResponse({"ok": False, "msg": "接口不存在"}, status_code=404)
    f = os.path.join(STATIC, path)
    if path and os.path.isfile(f) and os.path.abspath(f).startswith(os.path.abspath(STATIC)):
        return FileResponse(f)
    return FileResponse(os.path.join(STATIC, "index.html"))