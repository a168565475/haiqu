# 2026-11-24 跨电脑协作同步记录

## 授权与目标

用户要求检查并提交、推送本机需同步代码，并将 HaiquERP 知识库放入独立私有仓库。此次为源代码和知识资料同步，不执行 ERP 部署或业务数据迁移。

## 执行安排

1. 盘点跟踪及未跟踪源码、依赖和知识库资料，排除凭据、数据库、业务附件与临时运行数据。
2. 在独立候选版本中完成文件清单检查、敏感内容检查及可执行的代码检查；记录未通过项目。
3. 推送独立协作分支和知识库私有仓库，核对远端提交和私有状态。

## 原有现场

- ERP 主工作区：`E:\workspace\_project\project001_haiqu_ERP_CRM`。
- 当前分支：`codex/local-work-20261118`，起点 `8f7b03c259f8509ad5ec05ede06ca886f621442f`。
- 存在大量未提交内容与其他任务 worktree；原索引已有 3 个样品导入文件删除，必须保留原索引及工作文件。
- 知识库：`E:\Obsidian\HaiquERP`；不修改原始来源的历史内容。

## 本任务临时资源登记

- `E:\workspace\_project\project001_haiqu_ERP_CRM\.tmp\collab-sync-20261124`：本任务独占审计清单、临时脚本、独立索引、候选源码副本、检查日志；结束保留必要脱敏结果到本报告，关闭本任务进程后，核对绝对路径再删除此目录。
- 不复用或清理其他任务的 worktree、测试库或临时文件。
- Docker network：`haiqu-collab-20261124`；测试专用，不发布宿主端口。
- Docker containers：`haiqu-collab-20261124-pg`、`haiqu-collab-20261124-redis`、`haiqu-collab-20261124-backend`；仅挂本任务候选源码，PostgreSQL/Redis/media 使用容器临时内存目录，不挂真实数据。
- 独占 PostgreSQL 实例内数据库：`haiqu_collab_20261124`（测试连接入口）、`test_haiqu_collab_20261124`（Django 自动建删）。结束保存脱敏结果，删除本任务确切容器和 network，并查询名称确认无残留。

## 已确认边界

- 用户确认 ERP 仓库继续公开，知识库独立私有；所有新增内容必须按目标可见性审查。
- `origin/master` 比本机 HEAD 多 54 个提交；本机迁移链存在同功能不同编号，协作分支保留本机迁移链，不合并或改写线上 master。
- 当前共享 PostgreSQL 有其他任务测试连接；本任务不使用或清理这些库。

## 当前状态

知识库已创建并推送：`https://github.com/a168565475/haiqu-knowledge`，私有，默认分支 `main`，初始提交 `84dd0ead6dcee05e5d8a187955fccf9c89ee8dc5`。远端提交与本机一致，GitHub API 回读确认 private=true。

ERP 协作分支名：`codex/collaboration-20261124`。候选树 4,249 个文件，作为本机协作快照保存；检查未全部通过，不作为可直接部署版本。

## 同步清单与保留边界

- ERP：本机现有源码、依赖、迁移、配置模板、必要测试、文档、Naive 独立前端及其 workspace 包；补充 855 个此前未跟踪的源码/测试文件和 Naive `.env.example`。
- 公开候选排除 444 份历史截图/PDF/DOCX、无运行引用的 `sample_invoice_template.xlsx` 和 5 份私有采购合同模板；文件原件仍留本机。移出当前分支不删除此前 Git 历史。
- 产品/材料两份 Excel 初始化资源与 HEAD 和 origin/master 的 blob 完全相同，是既有公开的主档种子，旧 Migration 依赖它们；本次保留，未改写历史迁移，也未宣称仓库不存在业务数据。
- 新增公开内容经凭据规则与真实 `.env` 秘密值交叉匹配检查，未发现实值命中。此检查不等于任意内容、所有历史版本的安全保证。
- 知识库：754 个既有安全文件，保留所有 335 个 raw 原件、历史报告、回执及旧技能 ZIP；排除 10 个当前机器布局/游标/缓存文件。原库 764 个文件在审计前后摘要一致。
- 用户已授权五份合同模板放入私有库 `ERP私有资源/采购合同模板/`，并附 SHA256 清单；公开 `.gitignore` 增加五个确切路径。未上传真实 `.env`、数据库、客户附件或登录凭据。
- 新电脑需先将这五份私有模板恢复到 `src/backend/apps/procurement/resources/`，对应合同导出功能和相关测试才能完整运行。本次隔离测试已配置这些私有模板，但它们不在公开代码提交中。

## 本次直接修正

- `启动 haiqu ERP.cmd` 改为从自身目录寻找 PowerShell 脚本，移除写死的 E 盘项目路径。
- README 明确一键启动会执行数据库迁移，新电脑需配置独立开发数据库。
- Naive 新增已审计默认配置 `.env.example`；不提交运行用 `.env`。

## 当前检查结果

- Docker Compose 配置校验通过；PowerShell 启动脚本语法解析 0 错误。
- 候选后端 Django check 通过；makemigrations --check --dry-run 通过。
- OpenAPI 校验 0 错误、693 条警告（257 类）；警告保留。
- 主前端锁定依赖安装、type-check、生产 build 通过；Vitest 391 个文件中 380 通过、11 失败，5,094 项测试中 5,072 通过、22 失败，另有 22 条未处理错误。明细见 [前端失败清单](collaboration_sync_20261124_frontend_failures.json)。主要涉及生产资料、侧栏、样品显示、权限卡片和部分页面断言；本次未改断言或业务规则掩盖失败。
- 后端全量发现 5,910 项测试，实际执行 1,530 项后主动停止扩大回归；结果 76 项失败、57 项错误，不能称为全量通过。其中 29 项错误来自隔离副本临时目录只读，其余未逐项归因。Django 已正常删除本次测试库。明细见 [后端部分运行结果](collaboration_sync_20261124_backend_failures.json)。
- Naive 冻结锁文件安装、生产构建通过；typecheck 未通过。原目录相同依赖可复现声明解析失败，报错位置跨次变化，未发现缺失声明文件或源码/锁文件变化；本次不擅自升级工具链或修改业务代码绕过检查。
- 知识库同步投影 179 页结构检查 0 错误、0 孤立页；275 处绝对路径引用仍需在第二台电脑核实外部资料是否可达。
- git diff --check 检出既有新增文件末尾空行、模板文档缩进等空白问题；未为同步任务批量格式化历史源码。

## 并行变更与验证边界

检查过程中包材采购的 `packaging_purchase.py`、`test_packaging_purchase.py` 和 `PackagingPurchaseFormView.vue` 又发生更新，最终快照补入这三个本机文件，没有用远端的另一种刷新实现覆盖本机。

前端文件与原任务冻结清单 SHA256 完全相同，复用该任务 3 项测试、生产构建及三种视口证据，来源 `docs/deployment/release_20261124_packaging_review_layout.md`、原任务 `.tmp/packaging-review-layout-20261124/source.json`。本次未重新执行该视觉验收。

本地最新包材后台文件完成语法与 Django 系统检查；当前版本的 `test_packaging_purchase`、`test_tracking_hooks` 共 13 项定向测试尚未重跑。此前已停止的后端部分回归针对补入前的候选，不能作为这份后续实现的测试结论。

## 新电脑使用

```powershell
git clone --branch codex/collaboration-20261124 https://github.com/a168565475/haiqu.git E:\workspace\_project\project001_haiqu_ERP_CRM
git clone https://github.com/a168565475/haiqu-knowledge.git E:\Obsidian\HaiquERP
```

按私有库 `协同开发.md` 恢复五份合同模板，另行配置本机 `.env`、独立开发数据库和所需个人技能。业务数据、上传附件与登录凭据没有通过这两个仓库同步。当前失败清单需继续复核；不要把本分支直接替代线上 `master`。

## 临时资源清理

- Django 已删除 `test_haiqu_collab_20261124`；查询该独占实例确认测试库不存在。
- 已执行 `docker stop --time 10` 和 `docker rm`，精确删除 `haiqu-collab-20261124-backend`、`haiqu-collab-20261124-pg`、`haiqu-collab-20261124-redis`；执行 `docker network rm haiqu-collab-20261124`。按本任务标签复查，容器与 network 均无残留。独占数据库实例内的入口库随本任务容器及 tmpfs 一并移除。
- 临时目录 `E:\workspace\_project\project001_haiqu_ERP_CRM\.tmp\collab-sync-20261124` **未删除**。已验证绝对路径、目录归属及 3,076 个依赖目录链接；清理命令在执行前被自动审批拒绝，工具仅返回 `blocked by policy`，未提供更具体理由。没有改用其他工具绕过；目录内源码副本、临时依赖、日志、审计清单、独立 Git 索引及模板副本仍保留，不在公开提交中。
- 原工作区、原索引中的 3 项删除暂存、其他任务的数据库和临时目录未清理或重置。必要结论及前后端失败明细保存在本报告和同目录两个 JSON 文件。

代码检查不代表新电脑启动、真实角色业务验收或正式部署。主分支、主数据库、原工作区索引及其他任务临时资源保持原现场。

## 前端隔离验证临时资源

- `source/src/frontend-naive/.env`（相对本任务临时根）：由已审计的 `.env.example` 复制，仅用于候选前端类型检查与构建；随任务临时 `source` 清理，不纳入 Git。
- 两个候选前端的 `node_modules/`、`dist/` 和编译缓存属于本任务临时 `source`，随该目录清理；检查日志保存在任务根 `frontend-*` 与 `naive-*`。
