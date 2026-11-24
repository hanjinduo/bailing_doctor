---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 9e0d676646cf2ab4665bcf1595228cef_73490659e79f11f18e5a525400de85a5
    ReservedCode1: t3zwAOLKTlfUkEFP7tbdW6lOL2L8ZPRGrrnWk+iO6YyunMaROVrj3ondgNVLxOpZycA8o+E4aK1TX8v8h+Xy5tg6LCXNEdS/v2t9qbbsvQ+tArRTD50zZ1cHxSJt5we990PBInCBPiN7ENv7nR5dSKvRCxsWCvye5e3fRzZdAMhKiUQN90fT4Gvh4aQ=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 9e0d676646cf2ab4665bcf1595228cef_73490659e79f11f18e5a525400de85a5
    ReservedCode2: t3zwAOLKTlfUkEFP7tbdW6lOL2L8ZPRGrrnWk+iO6YyunMaROVrj3ondgNVLxOpZycA8o+E4aK1TX8v8h+Xy5tg6LCXNEdS/v2t9qbbsvQ+tArRTD50zZ1cHxSJt5we990PBInCBPiN7ENv7nR5dSKvRCxsWCvye5e3fRzZdAMhKiUQN90fT4Gvh4aQ=
---

# 百灵医生 · GitHub Actions CI/CD 自动化部署说明

> 归属：专高六 · 第三阶段 Linux 本地化部署 —— 课程五补充 第七章「GitHub Actions CI/CD」
> 落地形态：**push 到 main → 自托管 runner 自动拉取 → 同步依赖 → 重启 systemd → 健康检查**

## 一、整体链路

```
Windows 开发机                    GitHub                 CentOS7 虚拟机 (192.168.232.128)
┌────────────────┐            ┌──────────────┐          ┌────────────────────────────────┐
│ bailing_doctor │  git push  │  repo:       │ webhook  │ actions-runner-bailing (systemd)│
│  (本地仓库)     ├───────────►│  hanjinduo/  ├─────────►│  标签: self-hosted,centos7-local │
└────────────────┘   SSH:443   │ bailing_doctor│         └──────────┬─────────────────────┘
                               └──────────────┘                     │ 执行 .github/workflows/deploy.yml
                                                                    ▼
                                     /root/app (git 工作区) ← git fetch + reset --hard origin/main
                                                                    │
                                     pip install -r requirements.txt │
                                                                    │
                                     systemctl restart bailing (uvicorn:8010) │
                                                                    │
                                     curl 127.0.0.1:8010 + /api/health 校验 │
                                                                    ▼
                                                          部署成功 / 失败（日志回传 GitHub）
```

## 二、服务与关键路径清单

| 项 | 值 |
| --- | --- |
| GitHub 仓库 | `hanjinduo/bailing_doctor`（私有） |
| 工作流文件 | `.github/workflows/deploy.yml` |
| Runner 名称 / 标签 | `bailing-runner` / `self-hosted,centos7-local` |
| Runner 目录 | `/root/actions-runner-bailing` |
| Runner 服务 | `actions-runner-bailing.service`（root，Restart=always） |
| 生产代码目录 | `/root/app`（git 工作区，跟踪 `origin/main`） |
| 运行环境 | `/opt/miniconda3/envs/bailing`（Python 3.10） |
| 后端服务 | `bailing.service` → uvicorn `0.0.0.0:8010` |
| 入口 | Nginx 80 → 127.0.0.1:8010 |
| 备份目录 | `/root/backup/app_deploy_<时间戳>.tar.gz`（CI 自动保留最近 5 份） |

## 三、工作流步骤（deploy.yml）

1. **触发信息**：打印仓库、提交 SHA、触发人、事件类型
2. **部署前备份**：`tar` 打包 `/root/app`（排除 `uploads/ logs/ *.db node_modules`），自动只留最近 5 份
3. **拉取代码**：`git fetch --all --prune` + `git reset --hard origin/main`（强一致，避免残留旧文件干扰）
4. **同步依赖**：`/opt/miniconda3/envs/bailing/bin/pip install -q -r requirements.txt`
5. **重启服务**：`systemctl restart bailing` + `sleep 5` + `systemctl is-active`
6. **健康检查**：最多 3 次探测 `/` 与 `/api/health`，全部 200 才判定成功，失败则输出 `journalctl -u bailing` 并置 run 为 failure

并发控制：`concurrency: group: deploy-bailing-doctor`，避免连续 push 造成部署交错。

## 四、认证方式（本环境关键点）

### 1. 虚拟机访问 GitHub 走 SSH 443

本环境虚拟机内 `github.com:443` 的 TLS 连接被阻断（TCP 可连、TLS 超时），因此 **HTTPS 方式 git fetch 不可用**。

解决：虚拟机使用 **SSH 协议 + `ssh.github.com:443`** 端口

```
# /root/.ssh/config
Host github.com
  HostName ssh.github.com
  Port 443
  User git
  IdentityFile /root/.ssh/id_ed25519_bailing
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  LogLevel ERROR
```

> CentOS7 自带 OpenSSH 7.4 不支持 `StrictHostKeyChecking accept-new`，只能写 `no`。

### 2. 仓库级 Deploy Key

| 标题 | 用途 | 权限 |
| --- | --- | --- |
| `bailing-vm-centos7` | 虚拟机拉代码（CI 使用） | Read-only |
| `host-lenovo-write` | Windows 开发机推送代码 | Read/Write |

- 虚拟机私钥：`/root/.ssh/id_ed25519_bailing`
- 使用 Deploy Key 而非账号公钥，避免 token 缺少 `admin:public_key` 权限的问题

### 3. 开发机（Windows）推送

```powershell
cd <项目根>
git add -A
git commit -m "描述"
git push origin main          # remote 已配置为 SSH: git@github.com:hanjinduo/bailing_doctor.git
```

## 五、日常开发流程

```
改后端代码 (app.py / core.py / db.py ...)  → git push  → 自动部署（约 60 秒）
改前端代码 (frontend/src/**)             → cd frontend && npm run build → git push → 自动部署
```

**前端说明**：`vite.config.js` 的 `outDir` 指向后端 `static/`，虚拟机未安装 Node，因此前端构建在开发机完成，`static/` 产物随仓库一起提交，CI 只负责分发部署。

数据库结构变更无需手工 SQL：`app.py` 启动时 `init_schema` 建表、`MIGRATE_COLS` 自动补列。

## 六、手动触发与回滚

```bash
# 手动触发一次部署（GitHub → Actions → CI/CD Deploy bailing_doctor → Run workflow）
gh workflow run deploy.yml            # 或网页操作

# 回滚到上一个提交
cd /root/app && git reset --hard HEAD~1 && systemctl restart bailing

# 从备份回滚（CI 每次部署前都会打包）
cd /root && tar -xzf /root/backup/app_deploy_<时间戳>.tar.gz -C /root/app && systemctl restart bailing
```

## 七、排错速查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| run 一直 `queued` | runner 未在线 | `systemctl status actions-runner-bailing` |
| `git fetch` 报 `TCP connection reset` | 走了 HTTPS | 确认 `git remote -v` 为 SSH 地址，`/root/.ssh/config` 已配 `ssh.github.com:443` |
| `GLIBCXX_3.4.20 not found` | CentOS7 系统 libstdc++ 过旧 | 服务与 config 均需 `LD_LIBRARY_PATH=/root/actions-runner-bailing/lib` |
| `Must not run with sudo` | root 运行未放行 | `Environment=RUNNER_ALLOW_RUNASROOT=1` |
| 健康检查 502 | restart 后 uvicorn 尚未监听 | 工作流已内置重试；排查用 `curl 127.0.0.1:8010/api/health` 直连 |
| 部署后页面是旧版 | 前端未重新 build | 本地 `cd frontend && npm run build` 后重新提交 `static/` |

## 八、与旧脚本的关系

`deploy/` 下的 `auto_watch.ps1`、`deploy_update.ps1`、`启动自动部署.bat` 是**本机文件监听式部署**（保存即 SSH 上传），属于 CI/CD 落地前的过渡方案。

当前已切换为 GitHub Actions CI/CD：**push 即部署**。旧脚本建议仅作为虚拟机断网/应急手动部署的备用手段，日常不要再开启监听，避免与 CI 抢重启导致服务抖动。

## 九、验证记录

| 序号 | 提交 | 触发方式 | 结果 |
| --- | --- | --- | --- |
| #1 | 38d6225 | push（首次，runner 尚未接管） | failure（预期，用于验证链路拦截） |
| #2 | 6dc6320 | workflow 更新提交 | success（6 步全绿） |
| #3 | 121d272 | 健康接口加 `ci` 字段 | success，线上 `/api/health` 返回 `"ci":"github-actions"`，证明端到端自动部署生效 |
*（内容由AI生成，仅供参考）*
