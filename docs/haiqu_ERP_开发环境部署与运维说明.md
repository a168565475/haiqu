# haiqu ERP 开发环境部署与运维说明

## 1. 部署结果

- 部署时间：2026-08-21
- 项目目录：`E:\workspace\_project\project001_haiqu_ERP_CRM`
- 状态：基础开发环境部署完成，四个服务均为 `healthy`
- 范围：Docker、Django、PostgreSQL、Redis、Vue 3、Element Plus 与前后端联调
- 未包含：Nginx、Celery、CRM 具体业务功能、生产部署配置

## 2. 实际版本

| 组件 | 实际版本 |
|---|---|
| Docker | 29.7.2 |
| Docker Compose | v5.4.0 |
| Python | 3.13.15 |
| Django | 5.2.17 LTS |
| Django REST Framework | 3.16.1 |
| Node.js | 24.19.0 |
| npm | 11.17.0 |
| PostgreSQL | 17.11 |
| Redis | 7.4.11 |
| Vue | 3.x |
| Vite | 7.3.6 |

## 3. 服务与访问地址

| 服务 | 容器名 | 地址 / 端口 |
|---|---|---|
| Frontend | `haiqu-frontend` | http://localhost:8080 |
| Backend | `haiqu-backend` | http://localhost:8000 |
| Health API | `haiqu-backend` | http://localhost:8000/api/health/ |
| PostgreSQL | `haiqu-postgres` | 127.0.0.1:15432 |
| Redis | `haiqu-redis` | 容器内 `redis:6379`；宿主机 `127.0.0.1:16379` |

当前局域网地址：

- Frontend：http://192.168.1.103:8080
- Backend：http://192.168.1.103:8000
- Health API：http://192.168.1.103:8000/api/health/

前端和后端监听 `0.0.0.0`，PostgreSQL 与 Redis 仍只监听 `127.0.0.1`，不会向局域网暴露数据库端口。

Windows 当前保留了 `5151–5550` 与 `63434–63833` 等 TCP 端口范围，原先的 5173、5432、6380 均不可稳定绑定。本项目改用宿主机端口 8080、15432、16379；后端仍通过 Docker 网络连接 `postgres:5432` 和 `redis:6379`，不受影响。

## 4. 数据持久化与防误删

PostgreSQL 和 Redis 均使用 bind mount，数据实际保存在项目宿主目录：

- PostgreSQL：`E:\workspace\_project\project001_haiqu_ERP_CRM\data\postgres`
- Redis：`E:\workspace\_project\project001_haiqu_ERP_CRM\data\redis`
- PostgreSQL 容器目标：`/var/lib/postgresql/data`
- Redis 容器目标：`/data`
- Redis 持久化：AOF=`yes`，appendfsync=`everysec`

已执行普通 `docker compose down` / `docker compose up -d` 重启测试：

- Redis 测试键 `haiqu:persistence_probe` 重启后仍为 `ok`
- PostgreSQL `django_migrations` 重启前后均为 18 条
- 四个容器重建后均恢复为 `healthy`

### 禁止日常执行

```powershell
docker compose down -v
docker compose rm -v
docker system prune -a --volumes
docker volume prune
Remove-Item -Recurse -Force .\data
Remove-Item -Recurse -Force .\backups
```

主机挂载能避免 Docker 删除卷时连带清空数据库，但不能防止误删宿主目录，也不能替代备份。

## 5. 已完成备份与恢复演练

### PostgreSQL

- 文件：`E:\workspace\_project\project001_haiqu_ERP_CRM\backups\postgres\haiqu_erp_20260821_173029.dump`
- 大小：29,705 bytes
- SHA-256：`72689333B0D9C0B9C4FBB8C467A27CDDF820272F8670353FB3B06343E1320D6A`

### Redis

- 文件：`E:\workspace\_project\project001_haiqu_ERP_CRM\backups\redis\redis_20260821_173029.rdb`
- 大小：122 bytes
- SHA-256：`43F402717DC6B0904B196CDC5C8549C54251CCC5D1758188EB01BE02677CA9D6`

PostgreSQL dump 已恢复到独立临时数据库，恢复后查询到 18 条 migration 记录；验证完成后仅删除临时验证数据库，主数据库未被覆盖。

## 6. 日常运维

### 一键启动（推荐）

双击桌面的 `启动 haiqu ERP.cmd`。项目根目录也保存了一份同名入口，两者调用同一个主脚本：

`E:\workspace\_project\project001_haiqu_ERP_CRM\start_haiqu_erp.ps1`

一键启动会按以下流程执行：

1. 检查 Docker CLI；Docker 引擎未运行时自动启动 Docker Desktop。
2. 自动检测带默认网关的局域网 IPv4，并注入 Django、CORS、CSRF 和前端 API 配置。
3. 最长等待 Docker 引擎 180 秒。
4. 验证 Compose 配置，并检查 15432、16379、8000、8080 端口。
5. 已运行的本项目容器允许继续；其他进程占用端口时显示 PID 和进程名，但不会结束进程。
6. 执行 `docker compose up -d`。首次运行或镜像缺失时由 Compose 自动构建，日常启动复用现有镜像。
7. 最长等待四个容器健康 240 秒，顺序由 Compose 健康依赖保证：PostgreSQL / Redis → Backend → Frontend。
8. 验证主机数据挂载、本机与局域网 Health API、数据库连接、Redis PONG、CORS 和前端 HTTP 200。
9. 全部成功后打开 http://localhost:8080，窗口 5 秒后关闭，并显示当前局域网访问地址。

每次运行都会写入 `logs/startup_yyyyMMdd_HHmmss.log`。失败时窗口保持打开，并显示服务状态、最近 80 行日志和排查提示；完整文件记录最近 200 行容器日志。

如仅需验证而不打开浏览器：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_haiqu_erp.ps1 -NoBrowser
```

脚本不会停止未知进程，也不包含 `down -v`、`prune` 或删除 `data` / `backups` 的操作。

### 文件扫描策略

各上传入口保留现有的扩展名、大小、签名等文件校验，再按 `FILE_VIRUS_SCAN_ENABLED` 决定是否调用 ClamAV。该变量默认是 `true`；当前内部开发环境 `.env` 显式设为 `false`，上传文件会记录为 `SKIPPED`（已跳过病毒扫描），仍受业务权限、客户数据范围、路径安全和文件校验约束。读取和复用只允许 `CLEAN` 或 `SKIPPED`，`PENDING`、`FAILED`、`INFECTED` 继续拒绝。

重新启用扫描时，将 `.env` 中的 `FILE_VIRUS_SCAN_ENABLED` 改为 `true`，确认 `clamav` 容器健康后重启后端：

```powershell
docker compose up -d clamav
docker compose up -d backend
docker compose ps
```

关闭扫描只适用于受控的内部环境；对外部或生产环境应保持开启，并在切换后重新验证上传、下载和复用链路。

### 手动启动与状态

```powershell
Set-Location 'E:\workspace\_project\project001_haiqu_ERP_CRM'
docker compose up -d
docker compose ps
```

### 停止、重启与普通关闭

```powershell
docker compose stop
docker compose start
docker compose restart
docker compose down
```

`docker compose down` 不带 `-v` 时会删除容器和项目网络，但不会删除本项目宿主机数据目录。

### 构建

```powershell
docker compose build
docker compose up -d
```

当前网络无法连接 Docker Hub，基础镜像已改用 AWS Public ECR 中的 Docker 官方镜像副本。

### 日志

```powershell
docker compose logs -f --tail=200
docker compose logs -f --tail=200 backend
docker compose logs -f --tail=200 frontend
docker compose logs -f --tail=200 postgres
docker compose logs -f --tail=200 redis
```

### Django

```powershell
docker compose exec backend python manage.py check
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py shell
```

### 健康检查

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8000/api/health/
docker compose exec postgres pg_isready -U haiqu -d haiqu_erp
docker compose exec redis redis-cli ping
```

成功标准：Health API 返回 `status=ok`、`database=ok`、`redis=ok`，Redis 返回 `PONG`。

## 7. 备份命令

### PostgreSQL

```powershell
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
docker compose exec postgres pg_dump -U haiqu -d haiqu_erp -Fc -f /tmp/haiqu_erp.dump
docker compose cp postgres:/tmp/haiqu_erp.dump ".\backups\postgres\haiqu_erp_$stamp.dump"
docker compose exec postgres rm -f /tmp/haiqu_erp.dump
Get-FileHash ".\backups\postgres\haiqu_erp_$stamp.dump" -Algorithm SHA256
```

### Redis

```powershell
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
docker compose exec redis redis-cli SAVE
docker compose cp redis:/data/dump.rdb ".\backups\redis\redis_$stamp.rdb"
Get-FileHash ".\backups\redis\redis_$stamp.rdb" -Algorithm SHA256
```

覆盖主数据库的恢复属于破坏性操作。必须先在独立临时数据库完成恢复演练，并获得明确授权后再恢复主库。

## 8. Docker 常见问题

### Docker Hub 连接超时

现象：无法访问 `auth.docker.io` 或 `registry-1.docker.io`。

处理：本项目已使用 `public.ecr.aws/docker/library/...` 官方镜像副本。不要删除本地镜像或数据库目录。

### Backend 首次启动连接被拒绝

原因：PostgreSQL 初始化期间会短暂启动并重启临时实例。

处理：后端已加入 `wait_for_services.py`，在正式启动 Django 前实际连接 PostgreSQL 和 Redis。

### Redis 6379 端口冲突

原因：Windows Redis 服务已使用 6379。

处理：项目 Redis 容器内仍为 6379，宿主机端口使用 16379。不要停止未知系统服务。

### 一键启动提示端口被占用

脚本只允许当前 `haiqu-erp` Compose 项目继续使用既定端口。若是其他程序占用，脚本会显示端口、PID 和进程名后退出，不会擅自结束进程。

先确认占用者是否可以关闭或修改端口，再重新双击启动入口。不要通过强制结束未知系统进程解决冲突。

### 一键启动等待 Docker 超时

确认 Docker Desktop 已安装并能手动打开；若界面正在更新、首次初始化或等待 WSL，完成相应操作后再次双击入口。不要删除 Docker 数据目录来绕过启动错误。

### 局域网设备无法访问

当前 Windows 网络为“公用网络”，未修改系统网络分类。项目使用两条精确防火墙规则，仅允许当前 `192.168.1.0/24` 子网访问：

- `haiqu ERP Frontend (LAN)`：TCP 8080
- `haiqu ERP Backend (LAN)`：TCP 8000

先确认访问设备与本机连接同一局域网，且地址仍属于 `192.168.1.x`。一键启动会自动适应本机 IP 变化；如果切换到不同子网，需要以管理员身份重新运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\configure_lan_firewall.ps1 -RemoteSubnet '新的子网/前缀'
```

不要开放 TCP 15432 或 16379，不要配置路由器公网端口映射。Django/Vite 当前是开发服务器，仅适合可信的办公或家庭局域网。

### 容器不健康或反复重启

```powershell
docker compose ps -a
docker compose logs --tail=200 <service>
docker inspect <container>
docker system df
```

先定位第一个真实错误，不要通过循环重启、删除数据目录或 `prune --volumes` 掩盖问题。

## 9. 验证记录

- Django migration：18 条基础迁移成功
- Django system check：0 issues
- Frontend TypeScript + Vite build：成功
- npm audit：0 vulnerabilities
- Health API：HTTP 200
- CORS：允许 `http://localhost:8080`
- 浏览器 QA：Edge 无头模式实际渲染成功，无 console / page error
- 截图：`qa/runtime/frontend_home.png`
- 持久化重启：成功
- PostgreSQL 独立恢复演练：成功
- 一键启动：从 Docker Desktop 未运行状态自动启动成功
- 一键启动验证：四容器 healthy、主机数据挂载、Health API、PostgreSQL、Redis、Frontend 全部成功
- 局域网验证：192.168.1.103 的 Frontend、Health API、Django Host 与 CORS 全部成功
- Windows 防火墙：仅 192.168.1.0/24 可访问 TCP 8080/8000；数据库端口未开放

## 10. 当前限制

- 使用 Django 与 Vite 开发服务器，仅适合本地开发，不是生产部署。
- 前端构建提示主包超过 500 kB；基础环境不受影响，正式业务开发时应按路由拆包。
- 当前未配置 Nginx、Celery、HTTPS、生产 WSGI/ASGI 或 CRM 业务功能。
