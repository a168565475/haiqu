# 全局上传病毒扫描策略实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留上传校验、权限和事务边界的前提下，通过全局可逆配置让当前内部环境的所有用户上传跳过 ClamAV，并以 `SKIPPED` 真实记录且可正常使用。

**Architecture:** 在 `apps.files` 提供统一扫描策略适配器和可用状态集合；所有上传保存器只负责自身格式/签名/大小/路径校验并调用适配器；业务读取端统一使用 `CLEAN`/`SKIPPED` 可用规则。`FILE_VIRUS_SCAN_ENABLED` 默认开启，当前 `.env` 显式关闭。

**Tech Stack:** Python 3.13、Django 5.2、Django REST Framework、PostgreSQL 17、Vue 3、TypeScript、Vite、Docker Compose。

**Spec:** `docs/superpowers/specs/2026-10-14-global-upload-scan-policy-design.md`

## Global Constraints

- 保留 Session + CSRF、权限、客户数据范围、ETag/`If-Match`、事务和现有上传格式限制。
- 未扫描文件必须写入 `FileScanStatus.SKIPPED`，不能伪装成 `CLEAN`。
- `PENDING`、`FAILED`、`INFECTED` 继续禁止预览、下载和复用。
- 不修改历史 Migration，不删除 ClamAV 镜像或数据卷，不清理已有业务文件。
- 只修改本任务涉及文件；保留工作区其他未提交改动，不修改 `AGENTS.md`。
- 真实业务 API 和数据库行为必须用后端测试及现有 QA 规则验证，不能用 Mock 代替真实验收。

## Review Focus

- 开关关闭时是否仍执行格式、签名、大小和事务清理：由任务 1、2 的保存器测试覆盖。
- 自定义扫描链路是否漏改或仍调用 ClamAV：由任务 2 的调用断言和全量测试覆盖。
- `SKIPPED` 是否在任一读取/复用入口被误判为不可用：由任务 3 的代表性 API 测试和源码扫描覆盖。
- 默认值是否在未配置环境中意外关闭安全策略：由任务 1 的 settings 测试和任务 4 的配置检查覆盖。
- 前端是否把 `SKIPPED` 显示为待处理或继续提示重复句号：由任务 5 的组件测试与类型检查覆盖。

### Task 1: 建立统一扫描策略和通用上传器契约

**Files:**
- Modify: `src/backend/config/settings.py`
- Modify: `src/backend/apps/files/models.py`
- Modify: `src/backend/apps/imports/security.py`
- Modify: `src/backend/apps/files/uploads.py`
- Create: `src/backend/apps/files/tests/__init__.py`
- Create: `src/backend/apps/files/tests/test_upload_scan_policy.py`

**Interfaces:**
- Produces `FILE_VIRUS_SCAN_ENABLED`（默认 `True`）。
- Produces `scan_upload(path, scanner=...) -> tuple[FileScanStatus, str]` 或等价的 `apps.files` 统一适配器。
- Produces `USABLE_FILE_SCAN_STATUSES` 或等价判断函数，值只包含 `CLEAN` 和 `SKIPPED`。
- `save_scanned_image`、`save_scanned_document` 和 `save_and_scan_upload` 使用适配器返回的状态与消息。

- [ ] **Step 1: 写失败测试**：在 `test_upload_scan_policy.py` 覆盖默认配置开启、`override_settings(FILE_VIRUS_SCAN_ENABLED=False)` 时扫描函数不被调用且返回 `SKIPPED`、开启时成功返回 `CLEAN`、感染/不可用异常继续向上抛出；通用图片和文档保存分别断言 `scan_status`、`scanned_at` 和落盘文件。
- [ ] **Step 2: 运行测试确认失败**：运行 `docker compose exec -T backend python manage.py test apps.files.tests.test_upload_scan_policy --noinput -v 2`；预期因配置和适配器尚不存在或状态仍为 `CLEAN` 失败。
- [ ] **Step 3: 实现最小契约**：在 settings 增加默认开启的开关；在 `apps.files` 提供可用状态集合；在 `apps.imports.security` 或 `apps.files` 增加接收可替换 scanner 的策略适配器。修改通用保存器使用返回状态，关闭时不连 ClamAV、`scanned_at=None`，开启时保持现有异常记录与清理语义。
- [ ] **Step 4: 运行测试确认通过**：重复任务 1 的测试，并运行 `docker compose exec -T backend python manage.py test apps.files.tests.test_upload_scan_policy apps.boms.tests.test_bom_api --noinput -v 1`。

### Task 2: 接入所有自定义用户上传入口

**Files:**
- Modify: `src/backend/apps/inquiries/uploads.py`
- Modify: `src/backend/apps/inquiries/api/views.py`（沟通图片保存调用）
- Modify: `src/backend/apps/quotations/uploads.py`
- Modify: `src/backend/apps/samples/uploads.py`
- Modify: `src/backend/apps/samples/application_services.py`（参考图调用）
- Modify: `src/backend/apps/imports/security.py`（联系人导入保存流程，如任务 1 未完整覆盖）
- Test: `src/backend/apps/inquiries/tests/test_inquiry_create_attachments.py`
- Test: `src/backend/apps/inquiries/tests/test_inquiry_api.py`
- Test: `src/backend/apps/quotations/tests/test_quotation_api.py`
- Test: `src/backend/apps/samples/tests/test_sample_api.py`
- Test: `src/backend/apps/imports/tests/test_contact_import_api.py`

**Interfaces:**
- 所有自定义保存器复用任务 1 的适配器，并向适配器传入本模块的 scanner 引用，保留现有 patch 边界。
- 上传成功的 `BusinessFile` 统一使用 `CLEAN` 或 `SKIPPED`；失败仍不关联业务对象。

- [ ] **Step 1: 为每条自定义链路增加关闭开关的失败测试**：询盘附件、沟通图片、报价正式文件/产品图、样品付款/参数/任务图片、联系人导入分别断言 scanner 未调用、文件可读且状态为 `SKIPPED`。
- [ ] **Step 2: 运行相关测试确认失败**：分别运行上述模块的定向测试，预期当前仍调用 scanner 或仍返回 `CLEAN`。
- [ ] **Step 3: 替换自定义扫描调用**：将直接 `_clamav_scan` 的分支改为统一适配器；保存时按状态设置 `scanned_at` 和说明；保留每条链路的签名、XLSX 容器、大小、事务和异常清理。
- [ ] **Step 4: 补充询盘产品图回归**：增加产品图上传在 scanner unavailable 模拟下仍成功、返回 `SKIPPED`、GET 可读取、失败时不产生错误关联的测试；修复通用保存器异常时的孤儿记录清理仅在不改变现有状态语义的范围内进行。
- [ ] **Step 5: 运行定向测试确认通过**：运行询盘、报价、样品、导入相关测试集，并核对每条链路的 scanner 调用次数。

### Task 3: 统一 `CLEAN`/`SKIPPED` 读取、下载和复用规则

**Files:**
- Modify: `src/backend/apps/inquiries/api/views.py`
- Modify: `src/backend/apps/inquiries/images.py`
- Modify: `src/backend/apps/boms/api/image_views.py`
- Modify: `src/backend/apps/customers/api/complaint_views.py`
- Modify: `src/backend/apps/outsourcing/api/views.py`
- Modify: `src/backend/apps/production_tasks/api/views.py`
- Modify: `src/backend/apps/production_scheduling/api/views.py`
- Modify: `src/backend/apps/workflow/api/views.py`
- Modify: `src/backend/apps/workflow/api/serializers.py`
- Modify: `src/backend/apps/quotations/api/views.py`
- Modify: `src/backend/apps/quotations/api/serializers.py`
- Modify: `src/backend/apps/quotations/formal_quotation.py`
- Modify: `src/backend/apps/quotations/sample_invoice.py`
- Modify: `src/backend/apps/samples/form_selectors.py`
- Modify: `src/backend/apps/samples/application_services.py`
- Modify: `src/backend/apps/samples/api/views.py`
- Modify: `src/backend/apps/sales_orders/management/commands/seed_sales_order_acceptance.py`（如其验收判断仍要求 CLEAN）
- Test: `src/backend/apps/inquiries/tests/test_inquiry_downloads.py`
- Test: `src/backend/apps/quotations/tests/test_inquiry_product_images.py`
- Test: `src/backend/apps/samples/tests/test_application_image_inheritance.py`
- Test: `src/backend/apps/boms/tests/test_bom_line_images.py`

**Interfaces:**
- 所有业务读取条件使用任务 1 的可用状态集合或判断函数。
- 现有权限、客户归属、关联关系、归档状态和安全路径检查保持不变。

- [ ] **Step 1: 增加 `SKIPPED` 读取失败测试**：在询盘附件、询盘产品图来源复用、样品来源图片、BOM 图片和至少一个任务/生产/客诉文件读取测试中先把状态设为 `SKIPPED`，锁定预期成功；同时保留 `PENDING/FAILED/INFECTED` 失败断言。
- [ ] **Step 2: 运行测试确认失败**：运行各模块定向测试，预期当前严格 `CLEAN` 的入口失败。
- [ ] **Step 3: 替换查询与判断**：将严格 `CLEAN` 的查询改为 `__in=USABLE_FILE_SCAN_STATUSES` 或统一判断；不要放宽未关联、跨客户、无权限和路径越界条件。
- [ ] **Step 4: 运行测试确认通过**：重复任务 3 测试，并运行 `docker compose exec -T backend python manage.py test apps.inquiries.tests apps.quotations.tests.test_inquiry_product_images apps.samples.tests.test_application_image_inheritance apps.boms.tests.test_bom_line_images --keepdb --noinput -v 1`。

### Task 4: 配置、Compose 启动边界和运维文档

**Files:**
- Modify: `.env.example`
- Modify: `.env`（仅当前本地开发环境，禁止提交）
- Modify: `compose.yml`
- Modify: `start_haiqu_erp.ps1`
- Modify: `README.md` 或 `docs/haiqu_ERP_开发环境部署与运维说明.md`

**Interfaces:**
- 当前 `.env` 的 `FILE_VIRUS_SCAN_ENABLED=false` 能被 backend 容器读取。
- backend 不再以 `clamav: service_healthy` 作为启动前置；ClamAV 服务定义保留。

- [ ] **Step 1: 写配置检查**：在配置测试或命令检查中断言未设置时默认为 `True`，当前 `.env` 明确为 `false`；Compose 配置能通过解析。
- [ ] **Step 2: 实现配置边界**：更新 `.env.example` 注释、当前 `.env`、Compose backend 的依赖关系和启动脚本提示；文档写明关闭扫描的内部使用前提、`SKIPPED` 含义、重新开启步骤和 ClamAV 健康要求。
- [ ] **Step 3: 验证配置**：运行 `docker compose config --quiet`，检查容器环境变量，不执行删除卷或数据库的命令。

### Task 5: 前端状态与错误提示

**Files:**
- Modify: `src/frontend/src/views/inquiries/InquiryEditorView.vue`
- Modify: `src/frontend/src/views/inquiries/InquiryDetailView.vue`
- Modify: `src/frontend/src/views/contacts/ContactListView.vue`
- Test: 现有询盘/联系人组件测试；必要时新增 `src/frontend/src/views/inquiries/InquiryEditorView.spec.ts`

**Interfaces:**
- `SKIPPED` 状态显示“内部上传，未扫描”或等价明确文案。
- 产品图保存失败提示只追加一个句号，待上传文件仍可重试。
- 下载/预览按钮与后端的 `CLEAN`/`SKIPPED` 契约一致。

- [ ] **Step 1: 写前端失败测试**：断言 `SKIPPED` 不显示“待处理”，错误消息不产生“。。”，失败后 pending 图片仍在。
- [ ] **Step 2: 运行前端定向测试确认失败**。
- [ ] **Step 3: 修改状态映射和错误拼接**：只改目标视图的文案和状态判断，不做全局样式或无关重构。
- [ ] **Step 4: 运行 `npm run type-check`、相关 Vitest 和 `npm run build` 确认通过**。

### Task 6: 全量验证与交付报告

**Files:**
- Modify: `docs/` 下本次任务对应的运维/验收报告（仅在实际验证后创建或更新）

- [ ] **Step 1: 检查差异范围**：运行 `git status --short` 和针对本任务文件的 `git diff --check`，确认没有暂存或覆盖其他任务改动。
- [ ] **Step 2: 运行后端门禁**：`docker compose exec -T backend python manage.py check`、`makemigrations --check --dry-run`、`migrate --check`、相关测试和 `spectacular --validate`。
- [ ] **Step 3: 运行前端门禁**：在 `src/frontend` 执行 `npm run type-check`、`npm run test`、`npm run build`。
- [ ] **Step 4: 运行已登记的只读 QA**：按 `qa/runner_manifest.json` 选择与询盘/文件相关的 headless、read-only 条目；缺少真实账号或前置数据时标记 `UNKNOWN`，不使用假数据替代。
- [ ] **Step 5: 输出报告**：列出实际修改文件、配置开关现值、执行命令、通过项、未执行项及原因，并明确 `SKIPPED` 的安全边界。

