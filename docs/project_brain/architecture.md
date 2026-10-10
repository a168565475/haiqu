# HAIQU ERP 技术架构与运行边界

本文记录当前代码和运行配置已经证明的技术边界，帮助新窗口知道每一层负责什么、不能越过什么。未来方案不写成当前事实，未验证内容标记为 `draft` 或 `unknown`。

## 1. 当前分层

| 层 | 当前实现 | 负责什么 | 不负责什么 |
| --- | --- | --- | --- |
| 前端 | Vue 3、TypeScript、Vite、Element Plus、Vue Router、Pinia、Axios | 页面、路由、交互、状态展示和 API 调用 | 不能代替后端权限、数据范围或业务状态校验 |
| 后端 | Python、Django、Django REST Framework | API、业务校验、权限、数据范围和写入控制 | 不把前端菜单状态当成安全边界 |
| 数据库 | PostgreSQL | 业务数据、关系、历史和持久化记录 | 不由前端直接连接或修改 |
| 缓存/运行支持 | Redis | 由后端按实际代码使用缓存或运行支持 | 不默认视为业务事实存储 |
| 文件安全 | ClamAV 服务 | 文件上传流程中的病毒扫描支持 | 不决定业务文件是否允许提交，业务限制仍由后端模块负责 |
| 本地编排 | Docker Compose | 启动服务、依赖顺序、健康检查和本地开发网络 | 不等于生产部署方案或公网发布方案 |

**可信度**：`verified`，来源为 `src/frontend/package.json`、`src/backend/config/settings.py`、`compose.yml` 和实际目录。

## 2. 请求和数据流边界

正常业务请求按下面方向流动：

```text
浏览器
  ↓
Vue 前端页面 / API Client
  ↓ HTTP 会话请求
Django / DRF API
  ↓
业务服务、权限与数据范围校验
  ↓
PostgreSQL
```

后端需要时可以调用 Redis 或 ClamAV。前端不直接连接 PostgreSQL、Redis 或 ClamAV；页面显示的权限、状态和数量必须来自后端允许返回的数据。

## 3. 认证、权限和数据范围

- 当前认证使用 Django Session，并配合 CSRF 校验；前端请求配置发送 `X-CSRFToken`。
- DRF 默认使用项目的 Session 认证、已登录用户检查和有效员工检查。
- 权限判断至少包括账号/员工状态、具体操作权限、数据范围和原有业务状态门禁。
- 前端隐藏菜单或禁用按钮只是交互表现，不能替代后端 API 和数据查询限制。
- 权限和数据范围的详细规则以权限专项方案、后端代码和对应验收为准，本文不复制权限清单。

来源：`src/backend/config/settings.py`、`src/backend/apps/core/api`、`src/backend/apps/access_control`、`src/frontend/src/api/request.ts`。

## 4. 数据和文件边界

- PostgreSQL 数据目录绑定到 `data/postgres`；Redis 数据目录绑定到 `data/redis`。
- 数据库备份放在 `backups`，备份是否完整要看具体备份记录，不能只看目录存在。
- 后端媒体文件位于 `data/media` 对应的服务挂载中，文件上传限制、业务归属和可见范围由具体模块决定。
- ClamAV 是文件安全检查服务；扫描通过不等于业务对象已经保存或流程已经完成。
- 不得用 `docker compose down -v`、`docker volume prune` 或 `docker system prune -a --volumes` 代替故障排查。

## 5. 本地运行边界

- Docker Compose 当前编排 PostgreSQL、Redis、ClamAV、Django 后端和 Vite 前端。
- 本地主要访问入口是前端 `8080`、后端 `8000`；数据库和 Redis 默认只绑定本机端口。
- 局域网访问需要以当前启动脚本、环境变量和防火墙规则为准，不代表可以直接公网部署。
- 运行环境、健康检查和数据挂载发生变化时，必须同时检查 `compose.yml`、启动脚本和部署说明。

## 6. 当前未接入的边界

- 企业微信真实身份接入和同步尚未作为当前架构事实；未来接入必须建立明确的外部身份映射，不能按姓名自动合并员工。
- 完整财务、总账、应收核销和完整毛利核算不因数据库或权限代码存在就自动成为已接入架构。
- 未经专项确认的外部服务、消息队列、异步任务系统或公网部署方案不能写进当前架构。

## 7. 架构事实来源

| 内容 | 事实来源 |
| --- | --- |
| 前端依赖和脚本 | `src/frontend/package.json` |
| 后端依赖和配置 | `src/backend/requirements`、`src/backend/config/settings.py` |
| 服务、端口、挂载和健康检查 | `compose.yml`、启动脚本 |
| 认证和权限 | `src/backend/apps/core`、`src/backend/apps/access_control`、前端 API 请求代码 |
| 数据持久化与备份 | `data`、`backups`、部署运维说明 |

## 8. 更新规则

- 新增或移除服务、数据库、缓存、认证方式、权限层或外部集成时更新本文。
- 只修改页面样式或单个模块实现时，不自动修改全局架构。
- 代码、配置、文档冲突时先记录差异和来源；未核对前不把讨论方案写成当前架构。
- 架构变更需要对应迁移、健康检查、回滚/备份和验收证据；没有这些证据时标记为 `draft`。

最后更新：2026-10-01
