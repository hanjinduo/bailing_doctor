---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 9e0d676646cf2ab4665bcf1595228cef_0352de6ce49311f1b820525400de85a5
    ReservedCode1: YYykd02G/iJmkhy+EiCtFEfH1flx+Otw9+/CSxTTckWgnw1RN/JouXbOtMIJDo6GWX8SXOd70t73fd4HkR8G2umKiiXBpXzcr3C/tbICS3LEhyQtfHdiBd6b4rf3BIQllG415HEltTCZEvd+UHg9/viM/9vVyVZc1f8hy7I2XCEFmWaSYM/bWigzvCE=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 9e0d676646cf2ab4665bcf1595228cef_0352de6ce49311f1b820525400de85a5
    ReservedCode2: YYykd02G/iJmkhy+EiCtFEfH1flx+Otw9+/CSxTTckWgnw1RN/JouXbOtMIJDo6GWX8SXOd70t73fd4HkR8G2umKiiXBpXzcr3C/tbICS3LEhyQtfHdiBd6b4rf3BIQllG415HEltTCZEvd+UHg9/viM/9vVyVZc1f8hy7I2XCEFmWaSYM/bWigzvCE=
---



# 百灵医生 · 更新部署手册

适用环境：CentOS7 虚拟机 192.168.232.128（FastAPI + systemd + Nginx + MariaDB + cloudflared 隧道）

## 一、日常更新：一条命令

改完代码（本地项目根 = 本文件上级目录 `bailing_doctor`），在 PowerShell 执行：

```powershell
cd <bailing_doctor 路径>
powershell -ExecutionPolicy Bypass -File .\deploy\deploy_update.ps1
```

脚本自动完成 6 步，全程约 25 秒：

| 步骤 | 动作 |
|---|---|
| 1 | 预检虚拟机连通性 + 服务状态 |
| 2 | 前端 `npm run build` → 产物写入 `static/`（vite outDir 已指向 ../static） |
| 3 | 打包（318KB 左右，排除生产配置与数据） |
| 4 | 上传 + 远端自动备份 `/root/backup/app_时间戳.tar.gz` |
| 5 | 覆盖解压到 `/root/app` + `pip install -r requirements.txt` |
| 6 | `systemctl restart bailing` + 健康检查（首页 / 接口须 200） |

## 二、按改动类型选择参数

| 你改了什么 | 命令 | 说明 |
|---|---|---|
| 前端 Vue 页面/样式 | `deploy_update.ps1` | 必须重新 build，脚本默认执行 |
| 后端 py 逻辑（接口/业务） | `deploy_update.ps1 -SkipBuild` | 跳过 build，快约 5 秒 |
| 新增 pip 依赖（requirements.txt） | `deploy_update.ps1` | 脚本自动 pip install |
| 只改文件、暂不重启 | `加 -NoRestart` | 需手动 `systemctl restart bailing` 生效 |
| 数据库加表 / 加字段 | 无需手工 SQL | `app.py` 启动时 `db.init_schema` 建表 + `MIGRATE_COLS` 自动补列，重启即生效 |
| 新增 `.env` 配置项 | **需手工处理** | `.env` 被排除不上传，请在虚拟机内编辑 `/root/app/.env`，systemd unit 里的 `MYSQL_*` 同理 |
| 虚拟机 IP 变了 | `deploy_update.ps1 -VM 192.168.232.130` | 同时要改 `启动公网隧道.bat` 里的地址 |

## 三、脚本刻意排除了什么（防误覆盖）

`.env`、`bailing.db`、`uploads/`（用户上传文件）、`logs/`、`node_modules/`、`__pycache__`、`.git`、`.idea`、`.pytest_cache`、`deploy/`

实测：两次部署后远端 `/root/app/.env` 时间戳保持 11-18 14:27 未被改写，`uploads/` 未被清空。

## 四、回滚

```bash
ssh root@192.168.232.128
tar -xzf /root/backup/app_20261120_112909.tar.gz -C /root/app
systemctl restart bailing
```

备份保留在 `/root/backup/`，每部署一次产生一份，可定期清理旧包。

## 五、常用运维命令（虚拟机内）

```bash
systemctl status bailing          # 服务状态
systemctl restart bailing         # 重启后端
journalctl -u bailing -n 100 -f   # 实时日志
systemctl status nginx            # 入口层
tail -f /root/app/logs/*.log      # 应用日志
mysql -ubailing -pBailing2026 bailing_doctor -e "show tables;"
```

## 六、公网访问

- 内网：`http://192.168.232.128/`
- 公网：宿主机跑 `output/public_tunnel/启动公网隧道.bat`，用 cloudflared 快速隧道把 `http://192.168.232.128` 映射成 `https://xxx.trycloudflare.com`
- 隧道是宿主机独立进程，**更新部署不影响它**，无需重启隧道；只有宿主机重启/隧道进程被杀掉后才需要重开，且**域名每次都会变**
- 已实测：本轮两次部署后原域名仍返回 200

## 七、已知限制

1. 采用"tar 覆盖"而非镜像同步：本地**删除**的文件不会从远端删掉（代码兼容性安全，但会有残留）。要强一致可在远端改用
   `rsync -av --delete --exclude=.env --exclude=uploads --exclude=logs ...`（远端已装 rsync）。
2. 部署过程服务中断约 3 秒（若在面试演示现场，建议提前说明或避开演示中部署）。
3. 脚本需宿主机已配 SSH 免密到 root@虚拟机；未配置则会在上传步骤要求输密码。

## 八、自动化部署（改完保存即上线）

### 8.1 三种自动化程度，按需选择

| 档位 | 触发方式 | 是否需要人操作 | 适用场景 | 当前状态 |
|---|---|---|---|---|
| L1 手动一键 | 敲一条命令 `deploy_update.ps1` | 需要 | 稳定性优先，发布可控 | 已具备 |
| **L2 保存即部署** | **改完代码保存，8 秒后自动上线** | **不需要** | 开发调试迭代、面试演示"改一行代码网页立刻变" | **已具备（本次新增）** |
| L3 git push 部署 | `git push deploy` 触发远端 hook | 需要一次 push | 想要版本化 + 可回滚的正统 CI 流程 | 未配置，可按需搭建 |

### 8.2 L2：自动部署守护（推荐日常使用）

双击 `deploy\启动自动部署.bat`，窗口保持开着即可。之后在编辑器里改任何 `.py` / `.vue` / `.js` / `.css` 文件，**保存后原地等约 8 秒，虚拟机上的服务自动更新并重启**。

命令行用法：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\auto_watch.ps1
powershell -ExecutionPolicy Bypass -File .\deploy\auto_watch.ps1 -DryRun -Once   # 只验证监听链路，不真部署
powershell -ExecutionPolicy Bypass -File .\deploy\auto_watch.ps1 -QuietSeconds 15 # 改完 15 秒后才部署
powershell -ExecutionPolicy Bypass -File .\deploy\auto_watch.ps1 -NoRestart       # 只同步文件不重启
```

参数说明：

| 参数 | 默认 | 作用 |
|---|---|---|
| `-VM` | 192.168.232.128 | 目标虚拟机地址，IP 变了改这里 |
| `-QuietSeconds` | 8 | 改动停止多少秒后触发部署（防抖，避免一次保存触发多次） |
| `-NoRestart` | 关 | 只传文件不重启服务 |
| `-Once` | 关 | 检测到一次改动并部署后退出 |
| `-DryRun` | 关 | 只打印将要执行的命令，不实际部署 |

内部做了三件关键事：

1. **噪音过滤**：`node_modules`、`.git`、`static`、`logs`、`uploads`、`__pycache__`、`deploy` 的变动一律忽略，防止构建产物自己触发自己。
2. **智能跳过构建**：本轮改动若全在后端（`.py`），自动加 `-SkipBuild`，单次约 6 秒；一旦碰到 `frontend\` 下的文件才跑 `npm run build`。
3. **部署期冻结监听**：部署时暂停文件监听并清空积压事件，部署完成后重新取基线，杜绝死循环。

日志：`logs\autodeploy.log`（已被打包排除，不会上传到远端）。

### 8.3 L3：git push 部署（可选，需一次性搭建）

正统 CI 流程：虚拟机内建裸仓库 `/root/repo/bailing.git`，它的 `post-receive` 钩子在收到 push 后自动 `checkout` 到 `/root/app` → `pip install` → `systemctl restart bailing`。宿主机加远端后，日常只需：

```powershell
git add -A; git commit -m "feat: xxx"; git push deploy main
```

优点：每次部署天然对应一个 commit，回滚就是 `git revert` 再 push，面试时"版本化部署 + 可回滚"讲得清楚。
成本：一次性配置（本地 `git init`、远端裸仓库、hook 脚本），并需注意 `.env` / `uploads` / `logs` 不能进 git，否则会被 checkout 覆盖。

### 8.4 关于云端 CI（GitHub Actions / GitLab CI）

本项目**不适合**直接上云端 CI：虚拟机是 VMware NAT 内网地址，云端 runner 无法回调到内网，跑不了部署。要用云端 CI 只有两条路——把服务搬到有公网 IP 的云主机，或用 cloudflared 命名隧道把内网暴露出去（需自有域名）。作为课程/面试作品，L2 + L3 已经能说清"自动化部署"，不必引入云端 CI。

### 8.5 项目自带的容器化方案（备选）

仓库根已有 `Dockerfile` 与 `docker-compose.yml`（应用 + PostgreSQL），在装了 Docker 的机器上是 `docker compose up -d --build` 一条命令起全栈。但本虚拟机是 CentOS7，Docker 安装与国内镜像源配置成本较高，当前仍以 systemd + Miniconda 方式运行，容器方案可作为"未来迁移云环境"的说明点。
*（内容由AI生成，仅供参考）*
*（内容由AI生成，仅供参考）*
