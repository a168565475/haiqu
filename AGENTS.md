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
| `qa/` | 浏览器验收脚本、截图和视觉证据；`qa/run.py` 是统一编排入口，历史脚本仍可独立运行 |
| `data/` | PostgreSQL、Redis 和上传文件等运行数据，禁止删除或提交 |
| `backups/` | 数据库和缓存备份，禁止删除或提交 |
| `logs/` | 启动及运行日志，不属于源码 |
| `config/` | 当前为空；长期职责为 UNKNOWN |
| `start_haiqu_erp.ps1` | Windows 开发环境启动与健康检查脚本 |
| `configure_lan_firewall.ps1` | 修改 Windows 防火墙规则的管理员脚本，属于高风险操作 |

README 中提到的 `src/build_prd_docx.py` 当前不存在。PRD 文档的现行生成命令为 UNKNOWN，不得自行编造。

## 3. 开发规则和修改边界

1. 开始开发前，先检查需求是否存在错误前提、逻辑跳跃、缺失数据或未确认的业务规则，明确区分事实、推测和建议。
2. 每次开发任务以用户在本次对话中明确的协作方式为准（“连续开发”或“分单元确认”）；用户未明确时再询问，未确认前只做只读检查和方案整理。
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
10. 字典、员工、客户及其他业务功能和验收必须使用真实数据库和真实 API。接口或数据缺失时标记 `UNKNOWN` 并请求确认，不得用硬编码或 Mock 冒充完成。单元测试允许使用 Mock（模拟依赖）、Fixture（预置测试数据）和 Factory（测试数据工厂），但不能用测试替身代替真实功能验收。
11. 前端请求契约集中放在 `src/frontend/src/api/`，类型集中放在 `src/frontend/src/types/`，不得在多个组件内重复定义同一接口。
12. 只有任务明确提供 Figma 节点或设计稿时，才以该指定来源作为视觉基准。未取得对应节点时不得声称“像素级一致”。
13. 变更命令、环境变量、端口或部署流程时，同步更新 README 或对应运维文档。
14. 未经用户确认，不得修改本 `AGENTS.md`。

### 3.1 原型视觉实现防疏漏规则

只有任务明确要求还原 Figma 设计、确认原型或用户标注截图，或明确要求视觉验收时，才对任务涉及的页面、弹窗和组件执行以下完整视觉门禁；普通页面按任务范围做基本检查：

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

运行测试前，先按第 5.2 节登记临时资源并核实目标测试库不存在，或确属本任务独占；不得让 `--noinput` 自动覆盖来源不明的既有库。

```powershell
docker compose exec -T backend python manage.py check
docker compose exec -T backend python manage.py makemigrations --check --dry-run
docker compose exec -T backend python manage.py migrate --check
docker compose exec -T backend python manage.py test --noinput --verbosity 1
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

当前统一 QA 入口（只调度已登记脚本，不自动扫描全部历史文件）：

```powershell
python qa/run.py --list
python qa/run.py production --read-only
python qa/run.py quotation --read-only
python qa/run.py inquiry --read-only
python qa/run.py all --read-only
python qa/run.py --audit-headless
```

入口默认只允许运行注册表中明确标记为 `headless`、`read-only` 的条目；缺少账号、地址、运行时或前置条件时返回阻断状态，不得用人工点击或假数据替代。写库脚本必须显式授权，`all` 不自动包含真实业务写入。

当前仍未配置以下统一能力：

- 后端或前端 lint：UNKNOWN
- 生产/正式环境浏览器端到端白名单：UNKNOWN（入口本身已存在，首批条目仍需逐项确认）
- CI 检查流程：UNKNOWN
- 生产构建与部署流程：UNKNOWN
- PRD 文档生成命令：UNKNOWN

`qa/*_e2e.cjs` 使用的 Playwright 包、浏览器路径、账号变量和数据前提不统一。前端 `package.json` 已声明 `playwright-core`，但没有 `@playwright/test`、`playwright.config.*` 或统一 E2E 命令；运行具体脚本前必须先阅读脚本，不得将任意脚本当作全量端到端测试入口。

### 5.1 haiqu ERP QA规范

#### 默认验收流程

每个模块开发完成后，按以下顺序执行：

1. 后端业务测试；
2. API 测试；
3. 已登记的 QA 自动化脚本；
4. Playwright headless 页面验收；
5. 清理本次新建的临时数据库和文件，并复查清理结果；
6. 输出包含清理结果的统一验收报告。

统一入口只调用 `qa/runner_manifest.json` 中已审查的脚本。历史脚本仍可独立运行；未登记、风险为 `UNKNOWN`、缺少真实账号/地址或前置数据的脚本不得被入口猜测执行。

#### Playwright 规则

默认后台运行（headless，指不显示浏览器窗口）。用于：

- 页面加载验证；
- 元素存在验证；
- 弹窗验证；
- 表单交互验证；
- 下拉选择验证；
- 页面截图和计算样式证据。

普通开发验收不得打开 Chrome 窗口，也不得把人工点击过程当作自动化通过。`python qa/run.py --audit-headless` 用于检查 QA Playwright 启动点是否明确设置 `headless: true`；发现 `headless: false` 或模式不明确时必须先修复或标记 `UNKNOWN`。

#### 浏览器可视模式使用条件

仅在以下情况使用可视模式：

1. 自动化测试失败，需要定位原因；
2. Figma 或原型视觉验收；
3. UI 尺寸、层叠、滚动问题；
4. 动画、拖拽等特殊交互。

其他日常验收禁止使用浏览器人工点击。可视模式产生的截图或观察结果不能替代后端测试、API 测试、数据库核对和 headless 自动化报告。

### 5.2 测试与验收临时资源清理

1. **先登记，再创建。** 测试或验收需要新建临时数据库、上传副本、导出文件、浏览器临时目录等资源时，在任务记录或 QA 报告中登记数据库实例与完整库名，或文件绝对路径，并注明用途、所属任务及清理方式。区分既有资源与本任务新增资源；并行任务不得共用待清理资源。
2. **结束必须清理。** 测试、验收成功、失败或正常中止后，先保存必要结果和证据，再关闭本任务连接与进程，删除本任务新建的临时数据库和文件。编写或修改相关脚本时，用 teardown/finally 等结束处理保证清理；进程被强制终止、断电等导致未清理时，下次恢复任务先核查并处理本任务残留。
3. **默认不保留测试库。** 默认测试命令不得使用 `--keepdb`。执行带 `--noinput` 的测试前，必须核实目标测试库不存在，或确为本任务创建、登记且独占的临时库；该参数不授权自动覆盖、重建历史库或其他任务的库。确需暂时保留时，须由用户明确确认具体资源、原因、保留期限和清理责任，不能把先前的测试授权解释为永久保留授权。
4. **按确切归属清理。** 删除前核对资源清单、数据库连接和进程占用；文件操作核实解析后的绝对路径仍在本任务指定的临时范围内。不得仅凭 `test_` 等名称前缀判断可删，不得通配批删、全局清理或强制断开其他任务连接。发现归属不明或共享占用时停止该资源清理，报告并标记 UNKNOWN。
5. **保护正式数据和交付物。** 不得因此删除正式业务库、系统库/模板库、真实业务文件、备份、审计记录、源码或可复用测试脚本；不得递归清空 `data/`、`backups/`。在共享业务库内创建的测试记录，仍按该次写入授权及已确认清理方案处理，不能删除整个库或绕过审计。
6. **必要证据保留。** 保留脱敏后的最终验收报告、必要日志、截图、问题复现说明及用户要求的交付文件；中间副本和临时导出按清单清理。知识库历史记录继续保留，不能把“清理临时文件”解释为删除历史证据。
7. **清理也要验收。** 完成报告列出本次新增、已删除、获准保留和清理失败的资源，并记录实际清理命令、结果及清理后的复查。除用户明确确认的限期保留项外，本任务新增临时资源应无残留；未能核实或清理失败必须列为未完成项，不得声称已全部完成。符合本节的本任务临时资源结束清理已获规则授权，无需逐项重复询问；历史或来源不明资源须先盘点并另行确认。

## 6. 任务完成与验收标准

任务只有同时满足以下条件才可报告完成：

1. 修改范围与用户确认的需求一致，没有夹带无关重构或格式化。
2. 已检查工作区差异，没有覆盖或删除原有未提交内容。
3. 相关后端测试通过；涉及模型时包含前向 Migration，并通过迁移漂移检查。
4. 涉及 API 时完成权限、参数、错误响应和 OpenAPI 校验。
5. 相关前端变更通过类型检查、Vitest 和生产构建。
6. 涉及真实写操作时，验证 Session、CSRF、权限、事务、并发冲突和异常恢复。
7. 涉及页面视觉时，按任务范围检查布局及加载、空数据、错误和权限状态；满足第 3.1 节适用条件时，执行完整视觉门禁，并在任务指定视口核对设计来源。
8. 不使用假数据、假接口、假文件、假成功状态或不可访问路由代替未完成能力。
9. 命令、配置或运行方式发生变化时，相应文档已经同步。
10. 完成报告列出实际修改范围、实际执行的命令、结果、未执行项及原因。
11. 未配置的 lint、CI、端到端测试或生产部署不得写成“已通过”。
12. 本次测试、验收新建的临时数据库和文件已按第 5.2 节清理并复查；报告列明清理结果及经用户明确确认的保留项，未清理或归属不明的残留不得隐瞒。

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
- 删除、移动、覆盖数据库、上传文件、备份或审计相关数据（符合第 5.2 节的本任务临时资源结束清理由该规则授权；历史或来源不明资源不在此范围）
- 新增依赖、升级主要版本或修改固定技术栈

当前 `.gitignore` 没有覆盖全部运行数据和备份：`data/media/`、部分 `.sql` 及根目录 `.dump` 仍可能出现在 Git 未跟踪列表。除非用户明确要求并完成脱敏检查，不得暂存或提交 `data/`、`backups/` 下的任何文件。
