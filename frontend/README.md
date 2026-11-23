---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 9e0d676646cf2ab4665bcf1595228cef_5a96536fde7a11f1bff2525400cd780f
    ReservedCode1: OS6djY82ScGYdKRfhtGWOULOcltlvg5U72JumnHGacUXEEEFAJFj3nkMsoLALAiSKBkfqQY4GmbtgKQjVQVzq7HOW0MbpOFwAyUr25zqqJtayBU9CJThCi5i31ftfWc/D7CuLiA4cuomYk2jPkj3J+JBL0A09Dx351Iz8nlt1Gg/bkpV5xgOoTI4IR0=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 9e0d676646cf2ab4665bcf1595228cef_5a96536fde7a11f1bff2525400cd780f
    ReservedCode2: OS6djY82ScGYdKRfhtGWOULOcltlvg5U72JumnHGacUXEEEFAJFj3nkMsoLALAiSKBkfqQY4GmbtgKQjVQVzq7HOW0MbpOFwAyUr25zqqJtayBU9CJThCi5i31ftfWc/D7CuLiA4cuomYk2jPkj3J+JBL0A09Dx351Iz8nlt1Gg/bkpV5xgOoTI4IR0=
---

# 百灵医生 · 前端（Vue3 + Vite）

移动端 375px 布局，Vite + Vue3（`<script setup>`）+ Vue Router（hash 模式）+ Pinia + Axios，UI 采用精简手写 CSS + Vant Toast/Dialog 函数式组件，图标全部使用 emoji，无外链图片。

## 安装

```bash
cd frontend
npm install
```

## 开发

```bash
npm run dev
```

- 开发服务默认 `http://127.0.0.1:5173`
- `/api` 通过 Vite 代理转发到后端 `http://127.0.0.1:8000`（见 `vite.config.js`）
- 后端启动：在项目根目录执行 `python app.py` 或 `uvicorn app:app --port 8000`
- 接口前缀由 `.env.development` 的 `VITE_API_BASE` 控制（默认 `/api`）

## 构建

```bash
npm run build
```

- 产物输出到 `../static`（即后端 `static/` 目录），`emptyOutDir: false` 保证不误删后端其他静态资源
- 构建后直接访问后端首页 `/`（FastAPI `GET /` 返回 `static/index.html`）即可运行
- 资源以根路径（`base: '/'`）打包并输出到 `static/assets`，后端通过 `app.mount('/assets', ...)` 挂载
- 深链接（如 `/doctor/3`）由 FastAPI 末尾的 `@app.get('/{path:path}')` 回退到 `static/index.html`；前端路由为 hash 模式，刷新任意页面均不会 404

## 目录结构

```
frontend/
├── .env.development      # VITE_API_BASE=/api
├── index.html            # 单页入口
├── vite.config.js        # @ 别名、/api 代理、构建输出到 ../static
├── package.json
└── src/
    ├── main.js           # 应用入口
    ├── App.vue           # 手机外壳 + TabBar 控制
    ├── api/index.js      # axios 实例：注入 X-Uid / Bearer、ok=false 提示、401 跳登录
    ├── stores/user.js    # 登录态：uid / token / user / stat
    ├── router/index.js   # 30 条路由（26 个页面 + 重定向/兜底）+ 登录守卫
    ├── styles/app.css    # 全局样式（设计变量与公共类）
    ├── components/       # TopBar / TabBar / Sheet
    ├── utils/format.js   # 金额格式化
    └── views/            # 一个页面一个 .vue
```

## 页面与路由对照

| 页面 | 路由 | 主要接口 |
| --- | --- | --- |
| 登录注册 | `/login` | `POST /login`、`POST /register` |
| 首页 | `/home` | `GET /home` |
| 极速问诊 | `/ask` | `GET /depts`、`GET /vip`、`POST /chat/start` |
| 问诊支付 | `/paychat/:cid` | `GET /chat/{cid}`、`GET /coupons/usable`、`POST /chat/{cid}/pay` |
| 聊天 / 视频通话 | `/chat/:cid` | `GET /chat/{cid}`、`POST /chat/enter`、`/chat/send`、`/chat/end`、`POST /rx` |
| 找医生 | `/doctors` | `GET /doctors` |
| 医生主页 | `/doctor/:id` | `GET /doctor/{id}`、`POST /appt` |
| 消息列表 | `/msgs` | `GET /msgs`、`POST /msgs/read` |
| 会员中心 | `/vip` | `GET /vip`、`POST /vip/buy` |
| 商城首页 | `/shop` | `GET /meds`、`GET /cart`、`POST /cart` |
| 商品详情 | `/product/:id` | `GET /meds`（列表内按 id 匹配，后端无单商品接口） |
| 购物车 | `/cart` | `GET /cart`、`PUT /cart/{med_id}`（qty=0 删除） |
| 确认订单 | `/confirm` | `POST /order/preview`、`POST /order`、`POST /order/{id}/pay` |
| 收货地址 | `/address` | `GET|POST /addresses`、`PUT|DELETE /addresses/{id}`、`POST /addresses/{id}/default`、`POST /addresses/wechat` |
| 个人中心 | `/me` | `GET /me` |
| 我的问诊 | `/mychats` | `GET /chats`、`POST /chat/{id}/cancel` |
| 我的处方 | `/rxs`、`/rx/:id` | `GET /rxs`、`GET /rx/{id}`、`POST /rx/{id}/audit`、`DELETE /rx/{id}` |
| 优惠券 | `/coupons` | `GET /coupons`、`POST /coupons/claim` |
| 我的订单 | `/orders` | `GET /orders`、`POST /order/{id}/cancel|ship|finish|refund` |
| 电子病历 | `/records` | `GET /records`、`POST /record/upload`、`GET /record/file/{id}`、`DELETE /record/{id}` |
| 健康资讯 | `/news`、`/news/:id` | `GET /news`、`GET /news/{id}`、`POST /news/generate` |
| 特色门诊 | `/pkgs`、`/pkg/:id` | `GET /pkgs`、`GET /pkgs/{id}` |
| 我的预约 | `/appts` | `GET /appts`、`POST /appt/{id}/cancel` |

## 约定

- 后端以请求头 `X-Uid` 识别用户（非 JWT），axios 请求拦截器自动注入 `X-Uid` 与 `Authorization: Bearer <uid>`
- 后端业务失败返回 `{ok:false,msg}`，axios 响应拦截器统一 Toast 提示，调用方只需判断 `j.ok`
- 路由使用 hash 模式（`createWebHashHistory`），同时后端已配置 history 回退，两种模式均可直接刷新深链接
- 登录守卫：未写入 `localStorage.uid` 时统一跳 `/login`；已登录访问 `/login` 则回首页
*（内容由AI生成，仅供参考）*
