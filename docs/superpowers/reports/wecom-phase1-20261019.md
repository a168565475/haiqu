# 企业微信第一阶段实施与验证报告

日期：2026-10-19。分支：`codex/wecom-phase1`。用户已批准页面预览并授权连续开发，追加 Token 配置。没有修改已批准预览，没有新增依赖，没有提交、推送或发布。

## 实际实现

- 新增 `src/backend/apps/wecom/`：配置、Fernet 加密、官方 HTTP 接口、身份映射、会话绑定的一次性 OAuth state、事务建档、管理员绑定与审计；新增 `0001_initial` 前向迁移。
- 新增员工账号使用不可用密码，无默认角色、权限或管理员身份。CorpID + 不区分大小写 UserID 唯一；首次建档并发只创建一组员工/账号/绑定。已有员工只能管理员明确绑定，禁止自动同名/手机号/邮箱合并。
- 核心认证改动限于 `core/middleware.py`、`views.py`、`serializers.py`、`urls.py` 和 `config/settings.py`；保留 Session + CSRF，待角色状态由后端限制业务 API、管理后台，保留会话查询/退出。原密码登录保留。
- 新增 `src/frontend/src/views/settings/WeComSettingsView.vue`、`views/auth/`、`api/wecom.ts`、`api/wecomSession.ts`、`types/wecom.ts`、`router/wecomGuard.ts` 及测试；接入 `App.vue`、导航、Router、auth Store/Type。管理页、等待页、固定错误页使用真实接口。
- Token 与 EncodingAESKey 在独立“消息回调凭据”区安全保存，只返回配置状态；与网页登录 Secret 分开。本期没有消息事件接收、消息发送、模板发送或通讯录批量同步。
- OAuth 参数在首层中间件清理，覆盖更早的会话/认证/数据库异常；开发访问日志、内层 Nginx 和 Gunicorn 日志避免记录回调查询。部署配置变更在 `deploy/server/web.conf`、`Dockerfile.backend`，尚未发布。
- 新增 `.env.example` 的 `WECOM_FERNET_KEYS` 和可指定独占测试库的 `POSTGRES_TEST_DB`。真实秘密没有录入源码、配置文件、提示词、日志或本报告。
- 新增 `qa/wecom_phase1_isolated.cjs` 并登记至 `qa/runner_manifest.json`，统一入口支持 `wecom`。脚本仅允许已登记的隔离测试 API，风险级别为 `isolated-write`。

现有其他任务未提交内容保持原样；未执行 `git add`、重置、恢复或清理原有工作区。

## 实际命令与结果

| 检查 | 实际结果与边界 |
| --- | --- |
| `docker compose config --quiet`；`python manage.py check` | 通过 |
| `python manage.py makemigrations --check --dry-run` | 无模型漂移 |
| 代码验收阶段 `python manage.py migrate --check`；`showmigrations --plan` | 当时返回 1；唯一待执行项 `wecom.0001_initial`。后续获授权的本机迁移结果见末节 |
| `python manage.py test apps.wecom.tests.test_client --verbosity 1` | 29 项通过；官方 HTTP 使用 Mock，不能代替真实企微验收 |
| `python manage.py test apps.wecom.tests.test_sensitive_middleware --verbosity 1` | 4 项通过；验证 schema/认证数据库异常时 DEBUG 不显示 code/state |
| `python manage.py test apps.wecom apps.core apps.access_control apps.organizations --noinput --verbosity 1`，专属测试库 | 228 项中 218 通过、10 失败；企业微信用例通过。失败详情见下一节 |
| 最终定向后端回归（同一专属测试库、先确认不存在） | 100 项：99 通过，1 项按设计跳过长驻浏览器 fixture；93.574 秒，退出 0 |
| `npm run type-check` | 通过 |
| `npm run test` | 首轮 1544/1546，两个样品用例超时；未改超时阈值或样品代码 |
| `npm run test -- --maxWorkers=2` | 193 个文件、1546 项全部通过；降低并发后两个超时用例均正常通过。之后仅局部修正企微页标题，组件 8/8、类型检查再次通过，未重复全套 |
| `npm run build -- --outDir ../../qa/wecom_phase1_20261019/frontend_dist` | 最终标题修正后再次通过，37.11 秒；仍有已有大 chunk 与第三方 PURE 注释警告 |
| `python manage.py spectacular --file /tmp/wecom-phase1-openapi.json --validate` | 命令退出 0，但报告 594 条 warning（207 类）、32 条 error（1 类），不能报告全项目 OpenAPI 无错误 |
| 企微 OpenAPI 定向检查 | 5 个管理路径存在，响应不含凭据，三个写入凭据字段均为 writeOnly；原生 Django OAuth 路由见部署文档 |
| `python qa/run.py --audit-headless` | 扫描 574 个启动点，无违规 |
| `python qa/run.py wecom --allow-db-write --report-dir qa/wecom_phase1_20261019/runner` | 40 项检查全部通过、10 张最终截图；统一入口为 PASS_WITH_GAPS，按协议退出 1。真实企微链路、业务库迁移/真实绑定、公网部署仍缺验收 |
| 独立安全代码审查 | 发现并修复“脱敏晚于数据库访问”，复核已覆盖；详见 `wecom-review-20261019.md` |

后端最后一轮标签：`apps.wecom apps.core.tests.test_auth_api apps.core.tests.test_wecom_session_gate apps.core.tests.test_wecom_logging apps.access_control.tests.test_accounts_teams apps.organizations`。使用环境变量 `POSTGRES_TEST_DB=test_haiqu_wecom_20261019_01a1519b`，没有使用 `--keepdb`。

收尾按本任务既有修改文件清单执行 `git diff --check -- <精确文件列表>`，退出 0，仅有 LF/CRLF 提示。独立只读复核确认部署步骤与迁移、密钥注入及发布命令一致；新增文本静态检查未发现真实明文凭据，但没有进行用户原始凭据逐值比对。未暂存或提交工作区中的任何其他任务改动。

## 未通过的扩大回归与范围外问题

1. `CraftResourceApiTests` 的 9 项在初始化时报 400，尚未执行权限断言。Compose 开启新管材流程，测试复用的旧工厂只写加工完成量，没有现行规则要求的工价/报工依据。
2. `test_same_customer_quote_file_is_not_readable_via_upload_ownership` 创建的文件默认扫描状态为 PENDING；当前查询只接受 CLEAN/SKIPPED，因此即使上传者本人也不可读。
3. OpenAPI 的唯一 error 类是 `TubeOutsourcingOrderViewSet` 缺少可推导的 serializer，相关路径被生成器忽略；不在本期变更范围。

已核对上述测试/业务文件与 HEAD 一致，未发现企微变更的直接调用路径。没有运行修改前基线，不能声称“历史测试本来失败”；本次扩大回归仍未全部通过。未擅自修改样品、管材、金工或文件安全规则。

## 页面检查与证据

实际组件页面完成 40 项检查，保存 10 张最终截图，覆盖配置、独立 Token/AES 区、绑定表/弹窗、审计、空数据、网络失败恢复、等待授权和错误页。配置页检查视口为 1920×1080、1440×1000、1024×900、390×844；绑定弹窗另查桌面与 390px，等待页和错误页检查 390px。证据为 `qa/wecom_phase1_20261019/page_checks.json`、`actual_*.png` 及 `runner/report.json`。

实际 DOM/计算样式确认控件高 32px、圆角 8px、卡片四边单层 1px；表头 38px、数据行 40px，末行末列无叠边，桌面表格及各配置视口无不必要的横向滚动。发现旧设置页样式把标题覆盖为 34px/衬线字体后，仅在本页 scoped 样式修复；最终桌面无衬线 700 字重 36px/44px，390px 为 28px/38px。真实 Django API 检查覆盖凭据不回传、CSRF 403、ETag 412、待角色业务 403 但会话仍有效、等待页不循环且能退出。浏览器 JavaScript pageerror 为 0。

使用独占测试数据库和真实 Django Session/API，外部企业微信客户端被测试保护强制禁止。页面数据来自隔离 fixture，不能作为真实员工或真实企业微信身份链路验收。最终浏览器 fixture 自身 1 项通过，38.688 秒，数据库正常销毁。

首轮页面脚本把 `/src/api/*.ts` 也当成业务 API 转发，导致页面模块加载失败；已把路径匹配收紧为根路径 `/api/`。第二轮员工单元格包含编号，精确文本定位超时，已按实际单元格语义修正。第三轮全部通过，同时修正统一 QA 返回协议。上述检查脚本失败均保留记录，未用截图或 Mock API 冒充页面通过。

## 临时资源与清理

创建前清单在 `qa/wecom_phase1_20261019/implementation-report.md`。正式数据库、上传目录和备份均未修改。

- `test_haiqu_wecom_20261019_01a1519b`：扩大回归结束曾因两个测试线程连接未关闭导致自动销毁失败；主进程退出后已确认连接数为 0，精确 `dropdb` 并复查不存在。并发测试 finally 改用 `connections.close_all()`。最终回归已正常销毁，结束查询确认无该数据库。
- `test_haiqu_wecom_page_20261019_01a1519b`、容器 `haiqu-wecom-page-01a1519b`：最终正常销毁/移除，PostgreSQL 精确查询及 `docker ps -a --filter name=haiqu-wecom-page-01a1519b` 均无结果。`Get-NetTCPConnection -LocalPort 18591` 无监听；本任务浏览器进程为 0。
- `page_runtime/ready.json`、`finished` 由 fixture finally 删除；浏览器目录清理后只剩空目录，使用 `Remove-Item -LiteralPath <登记的 page_runtime 绝对路径>` 移除，`Test-Path` 为 False。
- backend `/tmp/wecom-phase1-openapi.json` 已用容器内 `Path.unlink(missing_ok=True)` 精确删除，校验非符号链接且位于 `/tmp`，复查 `openapi_exists=False`。
- **清理未完成：** `E:\workspace\_project\project001_haiqu_ERP_CRM\qa\wecom_phase1_20261019\frontend_dist` 仍存在，仅为本任务生产构建中间产物。已核实绝对路径、Directory 属性且无 ReparsePoint；组合清理被自动审批拒绝后，缩小为单个确切目录的 PowerShell `Remove-Item -LiteralPath ... -Recurse -Force` 仍被拒绝，返回 `blocked by policy`，没有更具体理由。未换工具绕过，未擅自视作获准永久保留。
- 保留脱敏报告、必要截图、可复用 QA 脚本及已批准预览。未保留真实密钥、Cookie 或真实员工数据。

## 未执行与发布状态

未执行正式环境迁移、真实员工绑定/建档、真实企业微信 API 调用、真实工作台登录验收或部署；没有把聊天里的凭据自动写入服务器。当前公网 `/api/auth/wecom/*` 与 `/settings/wecom` 的本期发布状态未验证。实际可信 IP、应用可见范围、HTTPS/Cookie/外层代理日志仍待核查。本机业务库迁移已在后续明确授权后完成，详见下一节。

后续配置、真实写入和正式发布仍按 [部署与操作说明](../../deployment/wecom_phase1_20261019.md) 及项目授权范围执行。首先完成原有员工映射，最后才启用工作台登录。正式客户端身份链路通过前，不报告本期接入已上线完成。

## 后续授权执行：本机迁移（2026-10-19）

用户对“在本机 haiqu_erp 执行 wecom.0001_initial，新增三张企微表，不含正式部署”的明确问题回复“执行”。本次仅实施该授权，没有扩大至凭据写入、员工绑定、真实企微调用或服务器发布。

1. 前置只读检查：`docker compose ps` 所有服务 healthy；`showmigrations wecom` 为 `[ ] 0001_initial`。`migrate wecom 0001 --plan` 仅列出本迁移的 3 个 CreateModel，没有其他历史迁移。Django 实际连接库名为 `haiqu_erp`，迁移前三张表均不存在。只读审查确认迁移无 RunPython/RunSQL，AppConfig 无迁移副作用；Django 常规迁移记录、ContentType 和权限元数据照常维护。
2. 实际执行：`docker compose exec -T backend python manage.py migrate wecom 0001 --noinput`，输出 `Applying wecom.0001_initial... OK`，退出 0。
3. 迁移后：`migrate --check`、`manage.py check`、`showmigrations wecom` 均退出 0；显示 `[X] 0001_initial`，系统检查无问题。数据库 introspection 确认三张表、外键、员工唯一约束及 `wecom_corp_user_ci_unique` 身份唯一索引存在；三张表记录数均为 0。
4. `http://localhost:8000/api/health/` 返回 status/database/redis 均为 ok，Compose 五个服务均 healthy。只查询服务端配置布尔状态，`WECOM_FERNET_KEYS` 尚未配置，没有读取或输出任何密钥。
5. 一条初始只读结构核查命令因 PowerShell 嵌套引号解析失败；改为单引号 here-string 经标准输入传给 Python 后通过，无临时脚本文件，无失败的数据写入。

本轮没有新建测试库、容器、浏览器目录或临时导出文件；新增三张表为正式功能结构，不属于临时清理对象。上一阶段被自动审批阻止删除的 `frontend_dist` 残留状态不变，未重试绕过。下一步仍需安全配置加密密钥与应用凭据，完成既有员工绑定后，再进行真实企业微信工作台验收及获授权的正式发布。
