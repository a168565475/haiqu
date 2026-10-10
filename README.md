# haiqu ERP

## 权限管理方案进度（2026-09-28）

用户已确认可配置角色权限总方案，采用每阶段验收后再继续的方式。阶段 1—5 已确认通过；阶段 6 回归及管理启用范围已确认，主库 5 个权限迁移和 20 个空角色初始化已完成，**权限管理已开放**。admin 可进入系统配置下的权限管理；销售与其他业务范围开关仍关闭，待员工、团队及审批人配置后开启。客户、询盘、报价、销售订单的范围设计统一取客户当前主负责人，历史负责人不回填。阶段 6 后端 119 项、隔离浏览器 74 项通过，类型检查与构建通过；前端全量 779 项中 772 项通过，7 项失败已在本阶段修改前基线复现。正式启用另有 12 项只读浏览器检查通过，账号、员工及历史授权保持不变。此前阶段 5 的兼容回归限制继续保留，详见阶段报告。

当前入口：[权限管理](http://localhost:8080/settings/access)。实际备份、迁移、初始化及验证见 [正式启用记录](docs/permissions_management_activation_20260928.md)。

入口：[实施方案](docs/erp_permissions_plan_20260928.md)、[阶段 1 审阅材料](docs/permissions_stage1_20260928/module_matrix_and_gaps.md)、[管理页面预览](docs/permissions_stage1_20260928/management_preview.html)、[阶段 2 后端与迁移审阅](docs/permissions_stage2_20260928.md)、[阶段 3 页面与联调验收](docs/permissions_stage3_20260928.md)、[阶段 4 销售权限验收](docs/permissions_stage4_20260928.md)、[阶段 5 模块与审批验收](docs/permissions_stage5_20260928.md)、[阶段 6 联合回归](docs/permissions_stage6_20260928.md)、[使用说明](docs/permissions_user_guide.md)、[正式启用审阅](docs/permissions_stage6_activation_review.md)。本次不修改客户转移功能，不实现字段级权限或企业微信实际接入。

## 项目定位与范围

HAIQU ERP 面向户外用品外贸及工厂业务，按模块逐步建设。当前建设范围包括客户与销售、产品与物料、采购与库存、生产与委外，以及权限和基础配置。

纳入建设范围，不代表已经全部开发、验收或启用；具体状态查看对应模块的实施与验收记录。完整财务和企业微信实际接入仍需专项确认。

### 历史范围（最初 CRM 阶段）

> 以下内容保留最初 CRM 阶段的背景与范围，不作为当前项目范围；当前范围以上文为准。

为户外用品外贸公司从零设计 haiqu ERP 第一阶段的客户 CRM 模块，形成可供产品评审、交互设计、技术设计和研发验收使用的 PRD V1.0。

- 客户全生命周期管理
- 客户 360 度详情页与 CRM 首页
- 客户档案、联系人、沟通、询盘、固定模板报价、轻量样品跟进、订单里程碑/商业单据只读追溯、客户产品关系
- 信用、客诉、任务、沉睡与流失、归属、去重合并、权限、日志与自动化
- 未来订单、产品、财务和售后模块的接口边界

采购、库存、生产和完整财务流程不属于第一阶段。

## 设计规范与知识入口

[DESIGN.md](DESIGN.md) 第 10 章是 HAIQU ERP 正式设计规则的唯一维护入口，已纳入本轮确认的基础项和 10 批共 50 项通用规则；第 11—15 批只登记源码差异与页面例外，不计入通用规则项。前 1—9 章保留为历史参考；README 不复制组件参数，避免两套规范漂移。

查阅顺序：[项目执行约定](AGENTS.md) → [正式设计规范](DESIGN.md) → 对应页面最新已确认原型 → 真实组件与页面代码。新增元素或与现有规范不一致时，先提取来源和差异，再按用户要求分批确认后写入。

[已确认汇总与实施差异](qa/design_knowledge_review_20260929/confirmed_design_summary.html)按 5 组提供 50 项通用规则详情，并保留各批审核稿链接；[第 11 批源码差异与页面例外](qa/design_knowledge_review_20260930/design_batch11_source_diff_review.html)、[第 12 批全局页面选项卡差异](qa/design_knowledge_review_20260930/design_batch12_source_diff_review.html)、[第 13 批 CRM v2 侧栏差异](qa/design_knowledge_review_20260930/design_batch13_source_diff_review.html)、[第 14 批页面例外](qa/design_knowledge_review_20260930/design_batch14_source_diff_review.html)和[第 15 批报工与采购详情页面模式](qa/design_knowledge_review_20260930/design_batch15_source_diff_review.html)单独记录实施边界。审核稿是来源证据；后续规则更新以 DESIGN.md 为准。规范已确认不表示旧 ERP 页面已全部实施或验收；代码改动仍按对应开发任务执行，不据此扩展业务、接口、权限或数据写入范围。

Project Brain 入口：[HAIQU ERP Project Brain](docs/project_brain/README.md)。入口页只负责项目导航、事实来源和当前状态，不复制详细业务规则、设计参数或接口契约。

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

2026-08-22 已完成基础框架 Step 03 左侧导航 / 菜单：依据 Figma 复核导出图落地 8 个一级业务入口、工作台二级项、选中态与底部系统配置；未完成入口不伪造路由，正式路由和权限过滤分别留待 Step 05、Step 06。

2026-08-22 已完成基础框架 Step 04 顶部导航 / 用户区域：依据 Figma 复核导出图落地 56px Header、模块标题、全局搜索外观、帮助与通知入口、真实员工姓名和首字头像；缺少完整交互条件的入口保持禁用，退出功能留待 Step 06。

2026-08-22 已完成基础框架 Step 05 路由 / 面包屑 / 页面容器：建立类型化路由元数据、按设计可选的面包屑、流式/受控宽度页面容器和受登录保护的 404 兜底；工作台保持无面包屑，未开发业务地址不创建假页面。

2026-08-22 已完成基础框架 Step 06 登录状态 / 权限 / 退出：有效员工与超级用户可使用 ERP，员工停用或归档后已有 Session 会被立即注销；时间有效的员工角色分配已接入 Django 权限判断，前端菜单按真实权限显示，后端继续执行接口权限校验，并完成真实角色、CSRF、Session 与退出流程联调。基础框架整体验收尚未开始。

2026-08-22 基础框架整体验收已通过：Step 01 至 Step 06 在真实 Django、PostgreSQL、Session、CSRF、临时员工角色权限和浏览器环境下完成全链路复验，85 项后端测试、OpenAPI、迁移检查、前端生产构建及六套浏览器脚本均通过；临时验收数据已清理。客户 CRM 前端开发尚未开始，等待确认后从客户专属类型与 API Client 单元进入。

2026-08-22 已完成客户 CRM Unit 01 前端类型与专属 API Client：依据真实 Serializer、筛选器、分页契约和交接报告建立客户列表、选项、查重、新建、ETag 编辑、详情摘要、时间线、画像历史及人工业务快照类型与请求方法；补齐浏览器读取 `ETag` 和发送 `If-Match` 所需的 CORS 契约，并通过真实 Session/CSRF 浏览器联调、85 项后端测试和前端生产构建。客户列表页面尚未开始。

2026-08-22 已完成 CRM CUS-01 客户列表：按 Figma 原型接入真实服务端分页、搜索、筛选、排序、统计、保存视图、CSV 导出、批量标签和转移申请，并展示最近联系、下次跟进及明确标注来源/截止时间的人工客户价值；真实 PostgreSQL 保留 8 条 DEMO 客户数据用于验收，浏览器 Session/CSRF 联调、94 项后端测试和前端生产构建均通过。

2026-08-22 已完成 CRM 联系人模块：提供独立联系人列表与客户联系人页、组合创建与查重确认、ETag 编辑、敏感联系方式脱敏、单笔/批量离职、批量任务、保存视图及同步 CSV/XLSX 导入；导入文件通过内网 ClamAV 流式扫描。95 项后端测试、前端类型检查与组件测试、生产构建、OpenAPI/迁移检查及桌面/移动浏览器验收均通过。

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

- Frontend：http://localhost:8080
- Backend：http://localhost:8000
- Health API：http://localhost:8000/api/health/
- 局域网 Frontend：http://192.168.1.103:8080
- 局域网 Backend：http://192.168.1.103:8000
- 局域网 Health API：http://192.168.1.103:8000/api/health/
- PostgreSQL：127.0.0.1:15432
- Redis 容器：redis:6379；宿主机：127.0.0.1:16379

一键启动会自动检测当前局域网 IPv4，并把该地址注入前后端配置。Windows 防火墙当前仅允许 `192.168.1.0/24` 子网访问 TCP 8080 和 8000；数据库与 Redis 不向局域网开放。

完整命令、数据保护、备份和故障排查请查看：

- `docs/haiqu_ERP_开发环境部署与运维说明.md`
- `docs/haiqu_ERP_Docker常用命令速查.md`

### 前端开发性能与热更新

Windows 挂载目录的 Vite 文件监听保留轮询：源码每 1 秒检查一次，二进制资源每 2 秒检查一次；`.tmp`、`qa`、`outputs`、`logs` 下的产物不参与热更新监听。这些目录不要存放运行中的应用源码。过密的全目录轮询会挤占 Node 文件检查与 DNS 解析共享的工作线程，使接口代理出现额外等待。

受保护页面导航可复用最近 30 秒内验证过的前端登录状态；窗口聚焦或可见性改变会使其失效，下次导航重新检查。退出后的公开登录页保持原行为，业务接口仍逐次执行后端 Session、权限和 CSRF 校验。客户列表的业务数据每次进入都重新读取，筛选配置保持发布版本与兼容回退规则。

客户列表加载优化的测量、回归与边界记录见 `qa/customer_list_loading_fix_20260915/report.md`。

## 注意事项

当前仍缺少完整且现行的公司销售 SOP、客户分级规则、信用政策、汇率与毛利核算口径。PRD 将用可配置规则和待确认项处理，不能将假设误写为既定制度。

本地开发环境不要执行 `docker compose down -v`、`docker volume prune` 或 `docker system prune -a --volumes`。数据库虽然绑定到宿主机目录，但宿主目录被误删仍会造成数据丢失，必须保留并验证备份。

一键启动脚本只执行检查、启动和只读验证，不包含停止未知进程、删除容器卷、清理 Docker 或删除 `data` / `backups` 目录的命令。

本项目使用 Django 与 Vite 开发服务器。局域网访问仅适合可信办公/家庭网络，不要在公共 Wi-Fi 上继续开放，也不要在路由器配置公网端口映射。
