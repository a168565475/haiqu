# haiqu ERP 项目协作规则

> 适用范围：本文件所在项目根目录及全部子目录。
> 本文件只记录长期有效的项目事实和执行规则。日期化进度、单模块决策、测试账号、截图和临时问题应记录在 `docs/` 或 `qa/`，不得写入本文件。

## 1. 项目入口与范围

当前项目范围以 [README 的“项目定位与范围”](README.md#项目定位与范围) 为准。开始模块任务时，读取对应的已确认方案及最新阶段记录；发现冲突先报告，不自行扩大范围。

固定技术栈：

- 后端：Python 3.13、Django 5.2、Django REST Framework
- 数据库与缓存：PostgreSQL 17、Redis 7.4
- 文件扫描：ClamAV
- 前端：Vue 3、TypeScript、Vite、Element Plus、Vue Router、Pinia、Axios
- 运行方式：Docker Compose
- 认证方式：Django Session + CSRF，不是 JWT
- 生产部署方案：UNKNOWN

## 2. 关键目录及职责

| 路径 | 职责 |
| --- | --- |
| `README.md` | 项目目标、范围、技术栈和开发环境入口 |
| `compose.yml` | 本地开发服务、端口、挂载、依赖和健康检查的主要事实来源 |
| `.env.example` | 环境变量示例；真实 `.env` 不得提交 |
| `src/backend/` | Django 后端源码、依赖、配置和服务等待脚本 |
| `src/backend/config/` | Django 全局配置、根路由和应用入口 |
| `src/backend/apps/` | 按业务域拆分的 Django 应用 |
| `src/backend/apps/*/migrations/` | 数据库前向迁移；数据库结构变更的唯一正式入口 |
| `src/backend/apps/*/tests/` | Django 单元测试、接口测试和数据库约束测试 |
| `src/frontend/` | Vue 前端工程、依赖和构建配置 |
| `src/frontend/src/api/` | 前端接口请求封装 |
| `src/frontend/src/types/` | TypeScript 业务类型 |
| `src/frontend/src/stores/` | Pinia 状态管理 |
| `src/frontend/src/router/` | Vue Router 路由配置 |
| `src/frontend/src/components/` | 可复用组件 |
| `src/frontend/src/views/` | 页面级视图 |
| `docs/` | PRD、API、数据库、部署运维和历史交接报告 |
| `docs/database/` | 数据库说明及只读 Schema 快照 |
| `qa/` | 浏览器验收脚本、截图和视觉证据；不是统一测试入口 |
| `data/` | PostgreSQL、Redis 和上传文件等运行数据，禁止删除或提交 |
| `backups/` | 数据库和缓存备份，禁止删除或提交 |
| `logs/` | 启动及运行日志，不属于源码 |
| `config/` | 当前为空；长期职责为 UNKNOWN |
| `start_haiqu_erp.ps1` | Windows 开发环境启动与健康检查脚本 |
| `configure_lan_firewall.ps1` | 修改 Windows 防火墙规则的管理员脚本，属于高风险操作 |

README 中提到的 `src/build_prd_docx.py` 当前不存在。PRD 文档的现行生成命令为 UNKNOWN，不得自行编造。

## 3. 开发规则和修改边界

1. 开始开发前，先检查需求是否存在错误前提、逻辑跳跃、缺失数据或未确认的业务规则，明确区分事实、推测和建议。
2. 新开发范围开始前，询问用户采用“连续开发”还是“分单元确认”；未确认前只做只读检查和方案整理。
3. 工作区可能包含其他任务的未提交改动。只修改当前任务必需文件，不覆盖、不清理、不重置他人改动。
4. 当 README、历史报告与实际代码冲突时，以当前 `compose.yml`、依赖文件、路由、模型、Migration 和测试为技术事实，并主动报告冲突。
5. 不得自行改变既定技术栈、认证方式、数据库或状态管理方案，不做无关重构、批量格式化或依赖升级。
6. 后端遵守现有分层：
   - Model 和 Migration 定义持久化结构；
   - Serializer 负责输入校验和接口契约；
   - Service 负责事务和跨对象业务规则；
   - Selector 负责查询与查询优化；
   - View/ViewSet 负责请求编排、权限和响应。
7. 数据库结构变更必须新增前向 Migration。不得修改已执行的历史 Migration，不得用手工 SQL 修改正式结构。
8. 后端是权限安全边界。前端隐藏按钮不能替代服务端登录、员工状态、权限和数据范围校验。
9. 写操作继续使用 Session、CSRF、事务及项目已有的 ETag/`If-Match` 并发控制，不得改成前端 Token 存储。
10. 字典、员工、客户及其他业务数据应使用真实数据库和真实 API。接口或数据缺失时标记 `UNKNOWN` 并请求确认，不得用硬编码或 Mock 冒充完成。
11. 前端请求契约集中放在 `src/frontend/src/api/`，类型集中放在 `src/frontend/src/types/`，不得在多个组件内重复定义同一接口。
12. 只有任务明确提供 Figma 节点或设计稿时，才以该指定来源作为视觉基准。未取得对应节点时不得声称“像素级一致”。
13. 变更命令、环境变量、端口或部署流程时，同步更新 README 或对应运维文档。
14. 未经用户确认，不得修改本 `AGENTS.md`。

### 3.1 原型视觉实现防疏漏规则

以下规则适用于所有依据 Figma、确认原型或用户标注截图实施的页面、弹窗和组件，属于交付前强制门禁：

1. **先形成视觉参数清单，再写样式。** 至少逐项记录并核对：四边边框宽度与颜色、背景色、字号与字重、控件高度、表头高度、数据行高度、单元格内边距、圆角、悬停色、选中色、禁用态、列宽、容器间距和滚动规则。不得只凭整体观感判断“基本一致”。
2. **一个可见边界只能有一个绘制责任方。** 外层卡片、内层组件、伪元素、末行末列和固定列覆盖层不得重复绘制同一条边。若卡片负责表格外围边框，表格只负责内部网格线；若表格负责外围边框，外层容器不得再次绘制。禁止用两条 `1px` 边框叠成视觉上的 `2px`。
3. **使用组件库前必须检查其默认渲染层。** Element Plus 等组件除了元素本身，还可能通过 `::before`、`::after`、内部 wrapper、固定列和最后一行/列绘制边框或背景。实施者必须在浏览器中检查实际 DOM、计算样式和伪元素，不能仅依据 Vue 模板或自己编写的 SCSS 推断最终效果。
4. **新增包装层或改布局时必须重新审计叠加样式。** 给既有表格、表单、弹窗增加卡片、容器或统一边框后，应同时检查组件原有的 border、shadow、background、padding 和 overflow；明确保留其中一层，其余在当前模块作用域内取消。不得用全局覆盖修补单页问题。
5. **视觉验收必须包含可测量断言。** 对原型明确给出的像素值，浏览器 QA 至少应断言实际计算值，而不只是保存截图。表格必须检查上、右、下、左四边，首行、末行、首列、末列和内部网格线；同时检查表头色、边框色、悬停色、行高以及宽屏下是否出现多余滚动条。
6. **状态和数据量必须覆盖边界。** 至少检查有数据、空数据、单行、末行/末列；涉及滚动时再检查超出可视区域的数据量。内容能够在当前窗口完整容纳时，不得出现横向或纵向滚动条；只有确实溢出时才允许滚动。
7. **截图、单元测试和构建不能相互替代。** 类型检查、单元测试或构建通过，只能证明对应检查通过；截图看起来接近也不能证明像素值正确。视觉完成必须同时具备目标视口截图、DOM/计算样式证据和原型逐项清单结果。
8. **发现偏差先定位根因，再局部修复。** 必须说明偏差来自组件默认样式、样式继承、层级叠加、响应式规则还是原型理解错误。禁止通过负边距、遮挡、同色覆盖等临时手段掩盖问题；修复应限制在目标页面或组件作用域，并复验关联状态。

## 4. 推荐的文件阅读顺序

1. `AGENTS.md`
2. `README.md`
3. 当前任务对应的 PRD、开发前准备报告或交接报告
4. `compose.yml`、`.env.example`
5. 后端任务：`src/backend/config/settings.py`、根路由、目标应用的 Model、Migration、Service、Selector、Serializer、View、URL
6. 前端任务：`src/frontend/package.json`、Router、API、Type、Store、目标 View 和复用组件
7. 接口或数据库任务：`docs/api/`、`docs/database/README.md`
8. 测试文件和任务对应的 `qa/` 脚本

带日期的完成报告和 QA 截图属于历史证据，可能落后于当前源码。不得仅凭报告判断功能现状。

## 5. 构建、测试和检查命令

所有根目录命令先进入项目：

```powershell
Set-Location 'E:\workspace\_project\project001_haiqu_ERP_CRM'
```

检查 Compose 配置：

```powershell
docker compose config --quiet
```

仅启动本机和局域网开发环境，不开启公网 Quick Tunnel：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_haiqu_erp.ps1 -NoBrowser -QuickTunnel No
```

手动构建和启动：

```powershell
docker compose build
docker compose up -d
docker compose ps
```

后端检查：

```powershell
docker compose exec -T backend python manage.py check
docker compose exec -T backend python manage.py makemigrations --check --dry-run
docker compose exec -T backend python manage.py migrate --check
docker compose exec -T backend python manage.py test --keepdb --noinput --verbosity 1
docker compose exec -T backend python manage.py spectacular --file /tmp/openapi.json --validate
```

前端安装、检查和构建：

```powershell
Set-Location '.\src\frontend'
npm ci
npm run type-check
npm run test
npm run build
```

健康检查：

```powershell
Set-Location 'E:\workspace\_project\project001_haiqu_ERP_CRM'
docker compose ps
Invoke-RestMethod http://localhost:8000/api/health/
docker compose exec -T postgres pg_isready -U haiqu -d haiqu_erp
docker compose exec -T redis redis-cli ping
```

当前未发现以下统一命令：

- 后端或前端 lint：UNKNOWN
- 浏览器端到端测试统一入口：UNKNOWN
- CI 检查流程：UNKNOWN
- 生产构建与部署流程：UNKNOWN
- PRD 文档生成命令：UNKNOWN

`qa/*_e2e.cjs` 使用的 Playwright 包、浏览器路径、账号变量和数据前提不统一，且 Playwright 未声明在前端 `package.json` 中。运行具体脚本前必须先阅读脚本，不得将任意脚本当作全量端到端测试入口。

## 6. 任务完成与验收标准

任务只有同时满足以下条件才可报告完成：

1. 修改范围与用户确认的需求一致，没有夹带无关重构或格式化。
2. 已检查工作区差异，没有覆盖或删除原有未提交内容。
3. 相关后端测试通过；涉及模型时包含前向 Migration，并通过迁移漂移检查。
4. 涉及 API 时完成权限、参数、错误响应和 OpenAPI 校验。
5. 相关前端变更通过类型检查、Vitest 和生产构建。
6. 涉及真实写操作时，验证 Session、CSRF、权限、事务、并发冲突和异常恢复。
7. 涉及页面视觉时，在任务指定视口核对设计来源，并覆盖 Loading、Empty、错误和权限状态。
8. 不使用假数据、假接口、假文件、假成功状态或不可访问路由代替未完成能力。
9. 命令、配置或运行方式发生变化时，相应文档已经同步。
10. 完成报告列出实际修改范围、实际执行的命令、结果、未执行项及原因。
11. 未配置的 lint、CI、端到端测试或生产部署不得写成“已通过”。

## 7. 禁止事项和高风险操作

### 严格禁止

- `git reset --hard`
- `git restore` 或 `git checkout --` 覆盖现有改动
- 未检查文件清单就执行 `git add .`
- `docker compose down -v`
- `docker compose rm -v`
- `docker volume prune`
- `docker system prune -a --volumes`
- 递归删除 `data/`、`backups/` 或未知 Docker 卷
- 修改已执行的历史 Migration
- 直接用 `docs/database/haiqu_erp_schema.sql` 替代 Migration
- 提交 `.env`、密码、密钥、Session Cookie、真实客户文件或未脱敏业务数据
- 把 Django/Vite 开发服务器描述为生产部署

### 必须获得明确授权

- 执行 `migrate`、`loaddata`、数据修复、批量更新或主库恢复
- 运行会向开发数据库写入数据的浏览器 QA 脚本
- 启动 Cloudflare Quick Tunnel 或其他公网入口
- 运行 `configure_lan_firewall.ps1` 修改 Windows 防火墙
- 开启真实 SMTP 邮件投递或其他外部系统调用
- 删除、移动、覆盖数据库、上传文件、备份或审计相关数据
- 新增依赖、升级主要版本或修改固定技术栈

当前 `.gitignore` 没有覆盖全部运行数据和备份：`data/media/`、部分 `.sql` 及根目录 `.dump` 仍可能出现在 Git 未跟踪列表。除非用户明确要求并完成脱敏检查，不得暂存或提交 `data/`、`backups/` 下的任何文件。
