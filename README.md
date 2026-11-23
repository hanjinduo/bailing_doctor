---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 9e0d676646cf2ab4665bcf1595228cef_68461554dcdc11f1bff2525400cd780f
    ReservedCode1: okK1Ku9mE+h2QXzVuFDDNyZphOudWkVLgUWpabbc3o+jHo21Vdkr1nXcqCpCHNjJB/5UZc+VaVASq+9aQPBYFJVn4TcigDxWIanRziAd/TJnP4ToxqM/rddPtsXUwt6QJE+vku3uitFE4yUM7e+3Gwp38Ji+kJcKIsrWfKZbaeTyGRtLsntfaXb6tQ8=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 9e0d676646cf2ab4665bcf1595228cef_68461554dcdc11f1bff2525400cd780f
    ReservedCode2: okK1Ku9mE+h2QXzVuFDDNyZphOudWkVLgUWpabbc3o+jHo21Vdkr1nXcqCpCHNjJB/5UZc+VaVASq+9aQPBYFJVn4TcigDxWIanRziAd/TJnP4ToxqM/rddPtsXUwt6QJE+vku3uitFE4yUM7e+3Gwp38Ji+kJcKIsrWfKZbaeTyGRtLsntfaXb6tQ8=
---

# 百灵医生 · 在线问诊系统

面向面试演示与内部试用的完整闭环项目：**FastAPI + Vue3**，前后端分离、JWT 鉴权、参数强校验、结构化日志、限流与容器化一键部署。
数据库默认走 **MySQL 8.0**（`127.0.0.1:3306` / 库 `bailing_doctor` / 用户 `root`，`charset=utf8mb4`），并保留 **SQLite（零配置，显式切换）** 与 **PostgreSQL（可选）** 两条通道，切换只改环境变量。方言差异——`?` 占位符、自增主键回填、TEXT 列参与索引的窄化、索引幂等、事务起点、`rowcount` 语义——全部收敛在 `db.py` 方言层，业务代码零改动。
接入**阿里云百炼 / 通义千问**驱动智能问诊、用药建议与健康资讯生成，无 Key 时全部走本地规则兜底，功能不受影响。

问诊链路具备 **RAG 知识库检索增强**（8 篇科室指南 / 48 个语义块 / text-embedding-v3）与 **SSE 流式输出**（逐字推送，首字百毫秒级），且两处均设计为可降级：向量接口不可用时切本地哈希向量，模型不可用时用知识库摘要兜底。技术细节见 [docs/bailing_doctor_interview.md](docs/bailing_doctor_interview.md)。

## 一、快速启动

### 方式 A：本地直接跑（默认 MySQL 8.0）

前置条件：本机已安装并启动 MySQL 8.0（默认 `127.0.0.1:3306`），具备 `root` 账号；首次运行需先把演示数据导入 MySQL。

```powershell
pip install -r requirements.txt
# 首次运行：建库 bailing_doctor + 建 20 张表 + 导数据 + 建 18 条业务索引（幂等，可重复执行）
python tools\migrate_sqlite_to_mysql.py
# 启动（不设任何数据库变量 → 默认 MySQL）
uvicorn app:app --host 127.0.0.1 --port 8010
```

- 默认连接：`127.0.0.1:3306` / 库 `bailing_doctor` / 用户 `root` / `charset=utf8mb4`（表引擎 InnoDB），可用 `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_DB` / `MYSQL_USER` 覆盖
- 口令：`MYSQL_PWD` > `MYSQL_PASSWORD` > 本机 phpstudy 默认口令；走回退值时启动日志打 `WARNING`，生产环境务必设置环境变量
- 启动日志会自报实际方言，便于确认没有连错库：`engine=mysql dsn=127.0.0.1:3306/bailing_doctor user=root charset=utf8mb4 pwd_from=...`，随后一行 `indexes ready ok=18`

浏览器打开 <http://127.0.0.1:8010>　演示账号：`13800000000` / `123456`

### 方式 B：改跑 SQLite（零配置，显式切换）

```powershell
$env:DATABASE_URL = "sqlite:///bailing.db"    # 或 $env:DB_ENGINE = "sqlite"
uvicorn app:app --host 127.0.0.1 --port 8010
```

- 走项目根 `bailing.db`，首次启动自动建表 + 写种子 + 建索引，无需任何数据库服务
- 适合离线演示与快速回滚；行为与 MySQL 模式一致（36 条测试两模式均全绿）

### 方式 C：Docker 一键起「应用 + PostgreSQL」（可选，非默认）

```bash
docker compose up -d --build
```

- 应用：<http://127.0.0.1:8010>
- 数据库：PostgreSQL 16（数据持久化在 `pgdata` 卷，首次启动自动建表 + 写种子数据）
- 该 compose 内置的是 PostgreSQL，**不是默认形态**：它在容器内注入 `DATABASE_URL=postgresql://...`，从而把引擎切到 PG；本地默认仍是上面的 MySQL
- 健康检查：`GET /api/health`

### 前端改造（可选）

前端已构建产物在 `static/`，由 FastAPI 直接托管，无需再启 Node。若要改前端：

```bash
cd frontend && npm install && npm run build   # 产物自动输出到 ../static
```

## 二、环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `JWT_SECRET` | `bailing-dev-secret-change-me` | **生产必须替换**，否则 token 可被伪造 |
| `DATABASE_URL` | 空（默认连本机 MySQL） | 支持三种前缀：`sqlite:///bailing.db` → SQLite；`mysql://user:pwd@host:3306/db` → MySQL；`postgresql://user:pwd@host:5432/db` → PostgreSQL |
| `DB_ENGINE` | 空 | 显式指定引擎：`mysql` / `sqlite`（`sqlite3` 亦可）/ `postgresql`（`pg` 亦可）；`DATABASE_URL` 优先于它 |
| `MYSQL_HOST` / `MYSQL_PORT` | `127.0.0.1` / `3306` | 默认 MySQL 主机与端口 |
| `MYSQL_DB` / `MYSQL_USER` | `bailing_doctor` / `root` | 默认库名与账号（库不存在时迁移脚本会创建） |
| `MYSQL_PWD` / `MYSQL_PASSWORD` | 空 | MySQL 口令；两者都为空时回退本机 phpstudy 默认口令并打 `WARNING` |
| `CORS_ORIGINS` | `*` | 允许的前端源，逗号分隔；非 `*` 时自动开启 credentials |
| `RATE_LIMIT_PER_MIN` | `300` | 单 IP 每分钟总请求上限 |
| `LOG_LEVEL` | `INFO` | 日志级别，文件固定写 `logs/app.log`（10MB × 4 轮转） |
| `EMB_MODEL` | `text-embedding-v3` | RAG 向量模型名；调用失败自动降级本地 256 维哈希向量 |
| `QINAWEN_API_KEY` / `QINAWEN_BASE_URL` | 读 `.env` | 大模型配置，缺失则本地兜底 |

引擎判定优先级（自上而下命中即停）：`DATABASE_URL` 前缀（`postgres://`/`postgresql://` → PG、`sqlite` → SQLite、`mysql` → MySQL）→ `DB_ENGINE` 取值（`sqlite` / `mysql` / `postgresql`）→ 全部未设置则 MySQL。切换引擎不需要改任何代码。

RAG 参数集中在 `rag.py` 顶部：切块 320 字 / 重叠 60 字、`TOP_K=3`、相似度阈值 `MIN_SCORE=0.32`（低于阈值视为未命中，不注入上下文）。

大模型另支持 `QIANWEN_*`、`DASHSCOPE_*` 两套键名；`.env` 查找顺序：项目根 `.env` → `static/.env` → 桌面默认路径。环境变量优先级最高。

## 三、工程化能力（可交付口径）

| 能力 | 实现 |
| --- | --- |
| 鉴权 | HS256 JWT（标准库 hmac 手写，零外部依赖）；`Authorization: Bearer <token>`，签名或过期即 401；前端 401 自动清 token 跳登录 |
| 数据隔离 | 全部业务查询以 token 内 `uid` 为条件，越权访问他人会话/订单返回「不存在」 |
| 参数校验 | Pydantic v2 模型 20 个，覆盖全部写接口；错误统一渲染为中文，如「缺少参数：手机号」「手机号格式不正确」 |
| 统一异常 | 422 校验失败 / 401、429 业务异常 / 500 未捕获异常 三级处理，响应恒为 `{ok, msg, detail}` |
| 结构化日志 | 每请求一行 `access method= path= status= ms= ip= uid=`；异常堆栈落文件；轮转防爆盘 |
| CORS | 可配置白名单，预检请求正常放行 |
| 限流 | 内存滑动窗口，默认 300 次/分/IP；`/api/sms/code` 5、`/api/login` 10、`/api/register` 5，超限 429 并写日志 |
| RAG 知识库 | `rag.py` 自研检索链路：切块 → 向量化 → 向量库（BLOB 列，随所选引擎落库）→ Top-K 阈值检索 → 注入 Prompt；远端/本地双通道 Embedding 自动降级 |
| 流式对话 | `POST /api/chat/stream` 返回 `text/event-stream`，`delta` 增量 + `done` 汇总两帧协议；前端 `fetch + ReadableStream` 手工解帧（支持 POST 与 Bearer 头） |
| 数据库索引 | 18 条 `CREATE INDEX` 按真实查询模式建复合索引，启动幂等执行（MySQL 8 无 `IF NOT EXISTS`，由方言层剥除并容错 errno 1061）；四条高频查询经 `EXPLAIN` 验证全部走索引（SQLite 侧走 `EXPLAIN QUERY PLAN`） |
| 多数据库 | 默认 MySQL 8.0；`DATABASE_URL` / `DB_ENGINE` 可切 SQLite 与 PostgreSQL，方言差异（占位符、自增主键、索引列窄化、事务起点、`rowcount` 语义）全部收敛在 `db.py` |
| 容器化 | `Dockerfile` + `docker-compose.yml`（web + postgres + healthcheck + 持久化卷） |
| 自动化测试 | `tests/` 共 36 条：16 条冒烟（鉴权/校验/越权隔离/限流）+ 20 条第一档验收（RAG/SSE/索引） |

## 四、功能清单

| 模块 | 说明 |
| --- | --- |
| 登录注册 | 手机号 + 密码（SHA256 加盐）+ 验证码注册，签发 JWT |
| 极速问诊 | 选科室 + 三种方式（文字 / 语音 / 视频）+ 症状描述，自动派单该科室医生 |
| 语音 · 视频问诊 | 模拟通话界面：跳动音波、通话计时、挂断自动生成问诊小结 |
| 图文问诊 | 聊天气泡对话，医生按科室人设由大模型回复，可随时结束生成小结 |
| 找医生 | 9 科室筛选，医生主页含职称、医院、擅长、排班，可预约挂号 |
| 电子病历 | 上传文件到 `uploads/`，支持在线查看与删除，医生端可查阅 |
| 我的处方 | 问诊结束后开具处方，生成药品 + 用法用量 + 注意事项 |
| 在线购药 | 24 种药品，处方药（Rx）必须绑定有效处方；带库存（售罄 / 仅剩 N 件 / 限购上限），支付时事务内原子扣减，并发不超卖 |
| 支付 | 微信 / 支付宝 / 医保卡三种模拟支付，下单生成订单（模拟，无真实交易） |
| 健康资讯 | 三分类 + 详情 + 一键大模型生成 |
| 会员 | 月 / 季 / 年卡，含极速问诊免服务费等权益 |
| 消息 / 我的 | 会话列表 + 系统通知 + 未读标记；个人信息与统计聚合 |

科室：内科、外科、妇产科、儿科、耳鼻喉科、中医科、呼吸内科、神经内科、皮肤科（19 位医生）。

## 五、目录结构

```
bailing_doctor/
├── app.py              # 路由与业务逻辑（67 个 /api 接口）
├── core.py             # 日志 / 统一异常 / CORS / 限流
├── db.py               # 数据库方言层（默认 MySQL / 可切 SQLite / 保留 PostgreSQL）
├── schemas.py          # Pydantic 请求模型 + 中文错误文案
├── rag.py              # RAG 检索链路（切块 / 向量化 / 向量库 / 检索）
├── kb/                 # 知识库语料（8 篇科室诊疗指南）
├── frontend/           # Vue3 + Vite + Pinia + Vant4 源码
│   └── src/api/stream.js   # SSE 流式请求封装
├── static/             # 前端构建产物（FastAPI 托管）
├── tools/              # migrate_sqlite_to_mysql.py（SQLite → MySQL 建库 / 导数据 / 建索引）
├── tests/              # test_api.py（冒烟 16）+ test_tier1.py（验收 20）+ test_stock.py（库存 20）+ run_all.py
├── docs/               # 面试版技术说明、各轮加固与 MySQL 切换报告
├── uploads/            # 电子病历文件
├── logs/               # 运行日志
├── Dockerfile / docker-compose.yml
└── bailing.db          # SQLite 演示库（MySQL 为默认；切 SQLite 时使用，首启自动建表 + 种子 + 建索引）
```

## 六、主要接口

```
GET  /api/health                 模型与运行状态（容器健康检查用）
POST /api/sms/code               注册验证码（演示环境直接返回）
POST /api/login /api/register    登录 / 注册，均返回 token
GET  /api/me                     用户信息 + 统计
GET  /api/home                   首页聚合：banner/科室/推荐医生/资讯
GET  /api/depts  /api/doctors  /api/doctor/{id}
POST /api/appt                   预约挂号
POST /api/chat/start             发起问诊（dept/mode/symptom/doctor_id）
GET  /api/chat/{id}              会话详情（消息 + 小结 + 处方）
POST /api/chat/send  /api/chat/end
POST /api/chat/stream            流式问诊（SSE，delta/done 两帧协议）
GET  /api/rag/status             RAG 索引状态（块数 / 向量通道 / 模型）
GET  /api/rag/search?q=&k=       知识库检索自检（返回命中片段与相似度）
POST /api/rag/rebuild?force=     重建索引（增量 / 全量）
POST /api/rx  GET /api/rxs  /api/rx/{id}
POST /api/record/upload  GET /api/records  DELETE /api/record/{id}
GET  /api/meds?kind=rx|otc  GET /api/meds/{id}  GET/POST/PUT/DELETE /api/cart
POST /api/order/preview  /api/order  /api/order/pay  GET /api/orders
GET  /api/news  /api/news/{id}  POST /api/news/generate
GET  /api/vip  POST /api/vip/buy
GET  /api/msgs  POST /api/msgs/read
```

鉴权外的接口均需在 Header 带 `Authorization: Bearer <token>`。

## 七、测试

```bash
# A. 一键（自己拉起服务 → 跑完自动关闭）
python tests/run_all.py

# B. 服务已在运行时
python -m unittest discover -s tests -v
# 或
pytest tests -v

# C. 第一档四项验收（需服务在跑）
python tests/test_tier1.py

# D. 库存能力验收（需服务在跑；自建临时用户 + 临时改库存，结束自动还原并清理）
python tests/test_stock.py
```

**冒烟 16 条**：无 token / 垃圾 token / 伪造签名均 401、登录后 /api/me 归属正确、缺字段与格式错误返回 422 中文提示、越权读他人会话与订单被拒、首页/医生/优惠券/下单预览可用、验证码接口触发 429。

**第一档验收 20 条**（`test_tier1.py`）：

| 分组 | 条数 | 验证内容 |
| --- | --- | --- |
| RAG 索引与检索 | 6 | 索引状态、48 块入库、远端 1024 维通道、三例检索各自命中正确科室文件 |
| SSE 流式问诊 | 7 | Content-Type、25 个增量帧、增量拼接 === done.reply、已落库、旧接口兼容 |
| 数据库索引 | 5 | 18 条索引存在 + 4 条高频查询 `EXPLAIN` 全部 `USING INDEX` |

**库存验收 26 条**（`test_stock.py`）：

| 分组 | 条数 | 验证内容 |
| --- | --- | --- |
| 商品单查 | 3 | `/api/meds/{id}` 直接取商品与库存（历史缺陷：前端只在 20 条分页列表里本地查找，id 靠后的商品打不开）；不存在返回中文提示 |
| 加购 / 改量 | 5 | 超库存加购被拒、累计超库存被拒、改量超上限被拒、购物车回传 `stock`、库存内正常加购 |
| 下单预检 | 1 | 库存不足在下单前被挡下 |
| 并发支付 | 4 | 库存 1 件时两张待支付单并发支付仅 1 单成功、库存扣到 0 不为负、销量只加一次、另一单仍为待支付 |
| 售罄与退款回补 | 6 | 售罄后加购被拒、退款回补库存、销量回退、重复退款被拒、退款通知只写一条、回补后可再次加购 |
| 兜底与清理 | 7 | 购物车为空不可下单、临时用户数据物理清理、库存销量还原、演示单 34/35 未动 |

## 八、说明

- 全部医疗内容为演示用途，不构成诊疗意见；急危重症请拨打 120
- 支付、通话均为模拟，不产生真实交易与音视频流
- 问诊回复按 `source` 标记来源：`llm`（模型基于 RAG 资料作答）/ `kb`（模型不可用时用知识库摘要兜底）/ `rule`（关键词规则最底兜底）。当前大模型额度耗尽，实际走 `kb` 通道，问诊功能不受影响
- 知识库为 8 篇科室指南，非完整医学知识库，仅供演示检索链路
- 验证码存进程内存，重启失效、多 worker 不共享，生产需换 Redis
- 上线商用另需：真实支付回调、互联网医院资质、等保测评
