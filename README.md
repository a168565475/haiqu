# haiqu ERP CRM

## 项目背景与目标

为户外用品外贸公司从零设计 haiqu ERP 第一阶段的客户 CRM 模块，形成可供产品评审、交互设计、技术设计和研发验收使用的 PRD V1.0。

## 当前范围

- 客户全生命周期管理
- 客户 360 度详情页与 CRM 首页
- 客户档案、联系人、沟通、询盘、固定模板报价、轻量样品跟进、订单里程碑/商业单据只读追溯、客户产品关系
- 信用、客诉、任务、沉睡与流失、归属、去重合并、权限、日志与自动化
- 未来订单、产品、财务和售后模块的接口边界

采购、库存、生产和完整财务流程不属于第一阶段。

## 技术与交付形式

项目同时包含正式产品需求文档与可运行的基础开发环境。开发环境技术栈已经固定：

- Backend：Python 3.13、Django 5.2 LTS、Django REST Framework
- Database / Cache：PostgreSQL、Redis
- Frontend：Vue 3、TypeScript、Vite、Element Plus、Vue Router、Pinia、Axios
- Runtime：Docker Compose

## 目录结构

- `docs`：正式 PRD 与源稿
- `src/backend`：Django / DRF 后端
- `src/frontend`：Vue 3 前端
- `src/build_prd_docx.py`：PRD 文档生成脚本
- `data/postgres`：PostgreSQL 宿主机持久化数据
- `data/redis`：Redis 宿主机持久化数据
- `backups`：数据库主机备份（不提交 Git）
- `config`：配置说明
- `logs`：项目日志
- `qa`：文档渲染检查中间产物

## 当前状态

PRD V1.0 已结合订单流程、报价单、PI/采购合同和样品发票资料完成完善。Word 成品已通过结构检查、可访问性检查和 65 页逐页渲染复核。

2026-08-21 已完成基础开发环境部署：四个 Docker 服务均通过健康检查，Django migration、Health API、前端构建、浏览器联调、PostgreSQL / Redis 持久化重启和独立数据库恢复演练均成功。

2026-08-22 已完成 CRM 数据库落地，以及 API V1 切片 A 至 G：71 张业务表、客户数据范围、客户主数据、沟通与任务、询价、报价、样品、客户转移、客户级显式授权、去重合并、全局搜索、个人/管理驾驶舱、保存视图和分级审计查询均已实现，并通过 75 项自动测试与 OpenAPI 校验。订单模块按已确认范围暂不实施，待客户侧订单方案完成后再设计。

2026-08-22 已完成基础框架 Step 01 登录页面：继续使用 Django Session + CSRF，补齐普通用户有效员工档案准入、前端会话恢复、登录路由保护与真实浏览器联调；尚未开始 Step 02 ERP 后台整体 Layout。

2026-08-22 已完成基础框架 Step 02 ERP 后台整体 Layout：依据 23 张 Figma 复核导出图落地 240px Sidebar、56px Header、独立滚动主工作区和登录页隔离；菜单、顶部用户区与面包屑仍分别留待 Step 03、Step 04、Step 05。

## 开发环境快速启动

### 一键启动（推荐）

双击桌面的：

```text
启动 haiqu ERP.cmd
```

入口会自动启动并等待 Docker Desktop，检查端口冲突，启动 PostgreSQL、Redis、Backend、Frontend，验证健康接口和主机数据挂载，成功后自动打开前端页面。启动日志保存在 `logs/startup_*.log`。

如果启动失败，窗口不会闪退，也不会自动结束占用端口的其他程序。请按窗口提示查看首个错误和对应启动日志。

### 手动启动

```powershell
Set-Location 'E:\workspace\_project\project001_haiqu_ERP_CRM'
docker compose up -d
docker compose ps
```

访问地址：

- Frontend：http://localhost:5173
- Backend：http://localhost:8000
- Health API：http://localhost:8000/api/health/
- 局域网 Frontend：http://192.168.1.103:5173
- 局域网 Backend：http://192.168.1.103:8000
- 局域网 Health API：http://192.168.1.103:8000/api/health/
- PostgreSQL：127.0.0.1:5432
- Redis 容器：redis:6379；宿主机：127.0.0.1:6380

一键启动会自动检测当前局域网 IPv4，并把该地址注入前后端配置。Windows 防火墙当前仅允许 `192.168.1.0/24` 子网访问 TCP 5173 和 8000；数据库与 Redis 不向局域网开放。

完整命令、数据保护、备份和故障排查请查看：

- `docs/haiqu_ERP_开发环境部署与运维说明.md`
- `docs/haiqu_ERP_Docker常用命令速查.md`

## 注意事项

当前仍缺少完整且现行的公司销售 SOP、客户分级规则、信用政策、汇率与毛利核算口径。PRD 将用可配置规则和待确认项处理，不能将假设误写为既定制度。

本地开发环境不要执行 `docker compose down -v`、`docker volume prune` 或 `docker system prune -a --volumes`。数据库虽然绑定到宿主机目录，但宿主目录被误删仍会造成数据丢失，必须保留并验证备份。

一键启动脚本只执行检查、启动和只读验证，不包含停止未知进程、删除容器卷、清理 Docker 或删除 `data` / `backups` 目录的命令。

本项目使用 Django 与 Vite 开发服务器。局域网访问仅适合可信办公/家庭网络，不要在公共 Wi-Fi 上继续开放，也不要在路由器配置公网端口映射。
