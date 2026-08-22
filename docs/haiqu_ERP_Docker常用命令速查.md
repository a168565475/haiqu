# haiqu ERP Docker 常用命令速查

## 进入项目

```powershell
Set-Location 'E:\workspace\_project\project001_haiqu_ERP_CRM'
```

## 一键启动（推荐）

双击桌面的：

```text
启动 haiqu ERP.cmd
```

它会自动启动 Docker Desktop、检查端口、启动并等待四个服务健康、验证数据挂载与前后端联调，然后打开前端。日志位于 `logs/startup_*.log`。

命令行执行但不打开浏览器：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_haiqu_erp.ps1 -NoBrowser
```

## 手动启动

```powershell
docker compose up -d
docker compose ps
```

## 停止与重启

```powershell
docker compose stop
docker compose start
docker compose restart
docker compose down
```

## 首次构建或依赖变化后重建

```powershell
docker compose build
docker compose up -d
```

## 查看日志

```powershell
docker compose logs -f --tail=200
docker compose logs -f --tail=200 backend
docker compose logs -f --tail=200 frontend
docker compose logs -f --tail=200 postgres
docker compose logs -f --tail=200 redis
```

## Django 维护

```powershell
docker compose exec backend python manage.py check
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py shell
```

## 服务验证

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8000/api/health/
docker compose exec postgres pg_isready -U haiqu -d haiqu_erp
docker compose exec redis redis-cli ping
```

## 访问地址

- Frontend：http://localhost:5173
- Backend：http://localhost:8000
- Health API：http://localhost:8000/api/health/
- 局域网 Frontend：http://192.168.1.103:5173
- 局域网 Backend：http://192.168.1.103:8000
- 局域网 Health API：http://192.168.1.103:8000/api/health/
- PostgreSQL：127.0.0.1:5432
- Redis：127.0.0.1:6380（容器内部 `redis:6379`）

一键启动会检测当前局域网 IPv4。防火墙仅允许 `192.168.1.0/24` 访问 5173/8000，5432/6380 始终仅限本机。

## 数据位置

- PostgreSQL：`E:\workspace\_project\project001_haiqu_ERP_CRM\data\postgres`
- Redis：`E:\workspace\_project\project001_haiqu_ERP_CRM\data\redis`
- PostgreSQL 备份：`E:\workspace\_project\project001_haiqu_ERP_CRM\backups\postgres`
- Redis 备份：`E:\workspace\_project\project001_haiqu_ERP_CRM\backups\redis`

## 快速备份

```powershell
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'

docker compose exec postgres pg_dump -U haiqu -d haiqu_erp -Fc -f /tmp/haiqu_erp.dump
docker compose cp postgres:/tmp/haiqu_erp.dump ".\backups\postgres\haiqu_erp_$stamp.dump"
docker compose exec postgres rm -f /tmp/haiqu_erp.dump

docker compose exec redis redis-cli SAVE
docker compose cp redis:/data/dump.rdb ".\backups\redis\redis_$stamp.rdb"
```

## 故障排查

```powershell
docker version
docker info
docker compose config --quiet
docker compose ps -a
docker compose logs --tail=200
docker system df
```

一键启动失败时，窗口会显示首个错误、服务状态和最近日志，并保持打开。端口冲突只报告 PID/进程名，不会自动杀进程。

局域网切换到其他子网后，以管理员身份更新防火墙范围：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\configure_lan_firewall.ps1 -RemoteSubnet '新的子网/前缀'
```

## 危险命令：日常禁止

```powershell
# 禁止：可能删除卷或其他项目数据
docker compose down -v
docker compose rm -v
docker volume prune
docker system prune -a --volumes

# 禁止：直接删除宿主机数据库与备份
Remove-Item -Recurse -Force .\data
Remove-Item -Recurse -Force .\backups
```

如确需执行破坏性清理或主库恢复，必须先验证备份、核对绝对路径，并取得明确授权。

一键启动脚本不包含上述危险命令，也不会删除 `data`、`backups` 或 Docker 卷。
