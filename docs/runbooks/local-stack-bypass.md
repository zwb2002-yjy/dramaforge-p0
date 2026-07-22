# 本地栈：绕过 Windows ↔ WSL Postgres 断连

## 问题本质

| 组件 | 常跑位置 | 问题 |
|---|---|---|
| PostgreSQL 16 | WSL Ubuntu | 库本身在 WSL 内是稳定的 |
| API (uvicorn) | 若在 **Windows** | `DATABASE_URL=...@127.0.0.1:5432` 依赖 **WSL localhost 端口转发**，会间歇 `ConnectionRefused` → `/health` 报 `db=down` / 503 |
| 前端 Vite | Windows `:5173` | 只代理 HTTP，不直连库；API 挂了才红 |

**根因不是 SQLAlchemy，是跨边界网络。**  
`db=down` 时业务 API 不可用是正确行为（不再假装健康）。

## 推荐绕过（默认）：API 与 PG 同机

**在 WSL 内跑 API，数据库用 WSL 自己的 `127.0.0.1:5432`，彻底不经过 Windows→WSL 转发。**

```powershell
# 一键（默认 Mode=WslApi）
powershell -ExecutionPolicy Bypass -File scripts\start_p0_stack.ps1

# 检查 API、数据库和 Vite 代理
powershell -ExecutionPolicy Bypass -File scripts\start_p0_stack.ps1 -Action Status

# 停止由启动器管理的 API 和 Vite
powershell -ExecutionPolicy Bypass -File scripts\start_p0_stack.ps1 -Action Stop
```

- 启动器从脚本目录进入 WSL 当前目录，不再硬编码 `/mnt/d/...`。这避免 Windows PowerShell 5.1 把 UTF-8 无 BOM 脚本中的中文路径误解码。
- WSL API 由 `systemd --user` 托管。只在进程退出时重启；单次 DB readiness 抖动不会再主动杀掉 API。
- 前端仍在 Windows：`http://127.0.0.1:5173`
- Vite 代理 `/api`、`/health` → 启动器验证过的 API 地址；若 localhost 转发失效，会自动使用 WSL IP。
- 验收：`curl http://127.0.0.1:8010/health` 必须 `status=ok` 且 `db=up`

若 **8010 的 localhost 转发也断**（WSL 提示 mirrored/NAT 异常），浏览器可临时：

1. 查 WSL IP：`wsl -d Ubuntu-24.04 -- hostname -I`
2. 把 `frontend/vite.config.ts` 代理目标改成 `http://<WSL_IP>:8010`
3. 或访问 `http://<WSL_IP>:8010/docs` 直接测 API

## 备选 A：Windows API，但 DATABASE 用 WSL 网卡 IP

不依赖 `127.0.0.1:5432` 转发，改连 `172.x.x.x:5432`（WSL eth0）。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_p0_stack.ps1 -Mode WindowsApi -DbHost WslIp
```

The launcher prepares WSL PostgreSQL and applies migrations before it starts the Windows API. `-Action Stop -Mode WindowsApi` stops only a process started from this repository; it does not take over another listener on port 8010.

注意：WSL IP **重启后会变**，不要写死进长期 `.env`；脚本每次解析 `hostname -I`。

要求：PG `listen_addresses='*'`（本机已是），且 `pg_hba.conf` 允许来自 WSL 网段的密码连接。

## 备选 B：Windows 本机安装 PostgreSQL 15+

完全不碰 WSL 库：

1. 安装 PostgreSQL for Windows，库/用户 `dramaforge` / `dramaforge`
2. `.env`：`DATABASE_URL=postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge`
3. Windows 跑 API + FE

代价：两套库数据不同步；迁移与 fixture 要在本机重跑。适合长期 Windows 开发、不愿维护 WSL 的场景。

## 备选 C：Docker Compose 全容器

```powershell
docker compose up -d postgres redis minio api
```

API 用服务名 `postgres:5432`，**网络在 Docker 内网**，不经 WSL 本地转发。  
前提：本机 Docker Desktop 稳定。**状态（2026-07-21）：DEFERRED，保留 Compose 和部署配置，但不作为当前 P0 MVP 开发路径。** Docker Engine 本次无法启动的已知根因是系统磁盘空间不足；恢复磁盘空间前，不要删除 Docker VHDX、Factory Reset 或改动现有 Compose 文件。

## 备选 D：修 WSL 网络本身（治本但偏系统）

- **WSL 2 mirrored 模式**（Windows 11）：`.wslconfig` 中 `networkingMode=mirrored`，改善 localhost 互通；改后 `wsl --shutdown`。
- `appendWindowsPath` 属于 `[interop]`，不属于 `[boot]`。把 `/etc/wsl.conf` 中的错误 `boot.appendWindowsPath` 移到正确区段后执行 `wsl --shutdown`。
- 管理员 `netsh interface portproxy` 永久映射（脆弱，IP 变化时失效，**不推荐优先**）。

## 恢复 WSL 发行版（仅在同一交互 Windows 账户确认缺失时）

`wsl --list --verbose` 和 `HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss` 都是按 Windows 用户隔离的。不要根据其他账户、沙盒或服务账户的空结果，判断实际开发账户的 Ubuntu 已丢失。只有在运行 DramaForge 的同一交互 Windows 账户中确认发行版缺失时，才执行以下恢复步骤。

1. 先定位旧数据盘：检查原 Ubuntu 包目录或以前自定义安装位置是否仍有 `ext4.vhdx`。
2. 若找到数据盘，先复制一份备份，再通过 `wsl --import` 注册为新发行版。
3. 若找不到数据盘，只能安装一个新的 Ubuntu 发行版，再重新安装 PostgreSQL 16、创建 `dramaforge` 用户/数据库并运行本启动器的迁移。
4. 在确认旧数据盘已经备份或不需要前，**不要**执行 `wsl --unregister`，也不要直接安装空发行版冒充恢复。

## 不要用的“绕过”

| 做法 | 原因 |
|---|---|
| 去掉 health 的 DB 检查 | 用户会再次踩到 500，只是更晚发现 |
| 用 SQLite 顶替 PG | 违反冻结合同（RLS / asyncpg 路径） |
| 假 Adapter 当验收 | 与 §3.1 无关，不能消掉 db=down |

## 决策表

| 你的目标 | 用哪条 |
|---|---|
| 今天就能稳定试 UI / S2 | **WslApi（默认）** |
| 必须在 Windows 里调试 Python | WindowsApi + **DbHost WslIp** |
| Docker 可靠 | Compose 全栈 |
| 长期只做 Windows | 本机 PostgreSQL |

## 快速自检

```powershell
# 1) 库在 WSL 内
wsl -d Ubuntu-24.04 -- bash -lc "pg_isready -h 127.0.0.1"

# 2) API 健康（必须 db=up）
Invoke-RestMethod http://127.0.0.1:8010/health

# 3) 若 2 失败，试 WSL IP
$ip = (wsl -d Ubuntu-24.04 -- hostname -I).Trim().Split()[0]
Invoke-RestMethod "http://${ip}:8010/health"
```
