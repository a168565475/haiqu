# haiqu ERP QA 测试映射

> 盘点日期：2026-10-13。本文是 `qa/*.cjs` 的统一索引；所有分类、用途、执行命令、浏览器模式、数据库影响和账号依赖均为静态审阅结论，不代表已经运行通过。
>
> 统一入口：`python qa/run.py <module> --read-only`。历史脚本仍可独立运行，但未登记脚本不会被入口自动扫描或执行。

## 分类汇总

| 分类 | 数量 | 说明 |
| --- | ---: | --- |
| 视觉测试 | 290 | 截图、尺寸、计算样式、滚动和视觉证据 |
| 业务流程测试 | 169 | 业务页面流程、状态流转或跨页面行为 |
| 数据初始化脚本 | 84 | 准备、迁移、种子或隔离数据 |
| 页面验收测试 | 73 | 页面加载、元素、弹窗和表单验收 |
| API测试辅助脚本 | 68 | API、数据库、请求载荷或结果核对辅助 |
| 辅助/证据脚本 | 109 | 清单、对比、汇总或发布证据 |
| **主 QA 脚本合计** | **793** | 允许一个脚本同时具备多个职责，但表中给出静态主分类 |

当前物理目录中共有 **814** 个 `.cjs` 文件：793 个是主 QA/验收脚本，另有 21 个位于历史隔离快照的 `frontend/qa/` 目录中。后者是源码副本，不纳入统一入口白名单；仍在本文末尾列出，避免把物理文件误报为可执行主入口。

## 字段判定口径

- **浏览器**：`是（headless）` 表示明确设置 `headless: true`；`是（调用浏览器，模式UNKNOWN）` 表示调用浏览器但未找到明确启动模式；`否` 表示未发现浏览器调用。
- **数据库**：`可能写入` 表示发现业务写请求、ORM 写操作、迁移或等价风险；`否（只读/拦截）` 表示静态上限制为只读或拦截写请求；`UNKNOWN` 表示无法安全确认。
- **账号**：`是（账号/Session/环境变量）` 表示依赖真实账号、Session 或环境变量；`否（模拟认证/快照）` 表示使用 fixture/route/mock；`UNKNOWN` 表示无法静态确认。
- 执行命令是保守的 `node <path>` 形式；“参数见脚本”表示必须先阅读脚本，不得把它当作统一入口。

## 主 QA 脚本逐项清单（793 个）

| 文件路径 | 分类 | 用途/范围（静态推定） | 运行方式 | 浏览器 | 数据库 | 账号 |
| --- | --- | --- | --- | --- | --- | --- |
| qa/action_cell_probe_crm_20260924.cjs | 页面验收测试 | 静态推定：action cell probe crm | node qa/action_cell_probe_crm_20260924.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/all_purchase_completion_20260924/apply.cjs | 数据初始化脚本 | 静态推定：all purchase completion / apply | node qa/all_purchase_completion_20260924/apply.cjs；参数见脚本；需环境变量 | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/all_purchase_completion_20260924/browser_verify.cjs | 业务流程测试 | 静态推定：all purchase completion / browser verify | node qa/all_purchase_completion_20260924/browser_verify.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/all_purchase_completion_20260924/prepare.cjs | 数据初始化脚本 | 静态推定：all purchase completion / prepare | node qa/all_purchase_completion_20260924/prepare.cjs | 否 | 可能写入 | UNKNOWN |
| qa/all_purchase_completion_20260924/run_rehearsal.cjs | 数据初始化脚本 | 静态推定：all purchase completion / run rehearsal | node qa/all_purchase_completion_20260924/run_rehearsal.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/all_purchase_inbound_20260924/apply.cjs | 数据初始化脚本 | 只由根代理在隔离演练通过后执行；无参数不会读取会话，也不会发出请求。 | node qa/all_purchase_inbound_20260924/apply.cjs；参数见脚本 | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/all_purchase_inbound_20260924/browser_verify.cjs | 业务流程测试 | 静态推定：all purchase inbound / browser verify | node qa/all_purchase_inbound_20260924/browser_verify.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 可能写入 | UNKNOWN |
| qa/all_purchase_inbound_20260924/plan_prepare.cjs | 数据初始化脚本 | 静态推定：all purchase inbound / plan prepare | node qa/all_purchase_inbound_20260924/plan_prepare.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/all_purchase_inbound_20260924/preflight.cjs | API测试辅助脚本 | 静态推定：all purchase inbound / preflight | node qa/all_purchase_inbound_20260924/preflight.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/all_purchase_inbound_20260924/preflight_validate_payloads.cjs | API测试辅助脚本 | 静态推定：all purchase inbound / preflight validate payloads | node qa/all_purchase_inbound_20260924/preflight_validate_payloads.cjs；需环境变量 | 否 | 可能写入 | UNKNOWN |
| qa/all_purchase_inbound_20260924/preflight_warehouse_projection_prepare.cjs | 数据初始化脚本 | 静态推定：all purchase inbound / preflight warehouse projection prepare | node qa/all_purchase_inbound_20260924/preflight_warehouse_projection_prepare.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/all_purchase_inbound_20260924/prepare.cjs | 数据初始化脚本 | 静态推定：all purchase inbound / prepare | node qa/all_purchase_inbound_20260924/prepare.cjs | 否 | 可能写入 | UNKNOWN |
| qa/all_purchase_inbound_20260924/run_ledger.cjs | API测试辅助脚本 | 静态推定：all purchase inbound / run ledger | node qa/all_purchase_inbound_20260924/run_ledger.cjs；参数见脚本；需环境变量 | 否 | 可能写入 | UNKNOWN |
| qa/all_purchase_inbound_20260924/run_rehearsal.cjs | 数据初始化脚本 | 静态推定：all purchase inbound / run rehearsal | node qa/all_purchase_inbound_20260924/run_rehearsal.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/all_purchase_ready_20260924/apply.cjs | 数据初始化脚本 | 仅由根代理审核后手动运行。默认无参数只打印说明，不执行任何请求。 | node qa/all_purchase_ready_20260924/apply.cjs；参数见脚本 | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/all_purchase_ready_20260924/auth_diff_readonly.cjs | API测试辅助脚本 | 两个数据库均只读；认证秘密仅在临时进程中比较，落盘只有字段名/布尔结论/时间。 | node qa/all_purchase_ready_20260924/auth_diff_readonly.cjs | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/all_purchase_ready_20260924/browser_verify.cjs | 业务流程测试 | 静态推定：all purchase ready / browser verify | node qa/all_purchase_ready_20260924/browser_verify.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/all_purchase_ready_20260924/final_database_check.cjs | API测试辅助脚本 | 正式采购完成后的只读全库核验，禁止任何业务写入。 | node qa/all_purchase_ready_20260924/final_database_check.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/all_purchase_ready_20260924/prepare.cjs | 数据初始化脚本 | 静态推定：all purchase ready / prepare | node qa/all_purchase_ready_20260924/prepare.cjs | 否 | 可能写入 | UNKNOWN |
| qa/all_purchase_ready_20260924/prepare_plan.cjs | 数据初始化脚本 | 静态推定：all purchase ready / prepare plan | node qa/all_purchase_ready_20260924/prepare_plan.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/all_purchase_ready_20260924/run_apply_migration.cjs | 数据初始化脚本 | 静态推定：all purchase ready / run apply migration | node qa/all_purchase_ready_20260924/run_apply_migration.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/all_purchase_ready_20260924/run_number_tests.cjs | 辅助/证据脚本 | 静态推定：all purchase ready / run number tests | node qa/all_purchase_ready_20260924/run_number_tests.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/all_purchase_ready_20260924/run_rehearsal.cjs | 数据初始化脚本 | 静态推定：all purchase ready / run rehearsal | node qa/all_purchase_ready_20260924/run_rehearsal.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/app_window_dialog_e2e.cjs | 业务流程测试 | 静态推定：app window dialog e2e | node qa/app_window_dialog_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/auth01_login_1920_e2e.cjs | 视觉测试 | 静态推定：auth01 login 1920 e2e | node qa/auth01_login_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/base01_master_data_e2e.cjs | 业务流程测试 | 静态推定：base01 master data e2e | node qa/base01_master_data_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/bom_cutting_usage_fix_20260924/backend_checks.cjs | API测试辅助脚本 | 静态推定：bom cutting usage fix / backend checks | node qa/bom_cutting_usage_fix_20260924/backend_checks.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/bom_cutting_usage_fix_20260924/backend_regression.cjs | API测试辅助脚本 | 静态推定：bom cutting usage fix / backend regression | node qa/bom_cutting_usage_fix_20260924/backend_regression.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/bom_cutting_usage_fix_20260924/baseline_regression.cjs | 辅助/证据脚本 | 静态推定：bom cutting usage fix / baseline regression | node qa/bom_cutting_usage_fix_20260924/baseline_regression.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/bom_cutting_usage_fix_20260924/browser_preview_layout.cjs | 视觉测试 | 静态推定：bom cutting usage fix / browser preview layout | node qa/bom_cutting_usage_fix_20260924/browser_preview_layout.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/bom_cutting_usage_fix_20260924/browser_result_layout.cjs | 视觉测试 | 静态推定：bom cutting usage fix / browser result layout | node qa/bom_cutting_usage_fix_20260924/browser_result_layout.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/bom_cutting_usage_fix_20260924/browser_verify.cjs | 页面验收测试 | 静态推定：bom cutting usage fix / browser verify | node qa/bom_cutting_usage_fix_20260924/browser_verify.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/bom_cutting_usage_fix_20260924/change_manifest.cjs | API测试辅助脚本 | 静态推定：bom cutting usage fix / change manifest | node qa/bom_cutting_usage_fix_20260924/change_manifest.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/bom_cutting_usage_fix_20260924/compare_regression.cjs | API测试辅助脚本 | 静态推定：bom cutting usage fix / compare regression | node qa/bom_cutting_usage_fix_20260924/compare_regression.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/bom_cutting_usage_fix_20260924/prepare_isolated_restore.cjs | 数据初始化脚本 | 静态推定：bom cutting usage fix / prepare isolated restore | node qa/bom_cutting_usage_fix_20260924/prepare_isolated_restore.cjs | 否 | 可能写入 | UNKNOWN |
| qa/bom_cutting_usage_fix_20260924/run_migration.cjs | 辅助/证据脚本 | 静态推定：bom cutting usage fix / run migration | node qa/bom_cutting_usage_fix_20260924/run_migration.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/bom_cutting_usage_fix_20260924/run_session_api.cjs | API测试辅助脚本 | 静态推定：bom cutting usage fix / run session api | node qa/bom_cutting_usage_fix_20260924/run_session_api.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/bom_cutting_usage_readonly_20260924/browser_readonly.cjs | 页面验收测试 | 静态推定：bom cutting usage readonly / browser readonly | node qa/bom_cutting_usage_readonly_20260924/browser_readonly.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/bom_loading_20260916/after-run/measure.cjs | 视觉测试 | 静态推定：after run / measure | node qa/bom_loading_20260916/after-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/bom_loading_20260916/archive_changes.cjs | 辅助/证据脚本 | 静态推定：bom loading / archive changes | node qa/bom_loading_20260916/archive_changes.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/bom_loading_20260916/before-run/measure.cjs | 视觉测试 | 静态推定：before run / measure | node qa/bom_loading_20260916/before-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/bom_loading_20260916/prepare_equivalence.cjs | 数据初始化脚本 | 静态推定：bom loading / prepare equivalence | node qa/bom_loading_20260916/prepare_equivalence.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/bom_loading_20260916/prepare_measure.cjs | 数据初始化脚本 | 静态推定：bom loading / prepare measure | node qa/bom_loading_20260916/prepare_measure.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/bom_loading_20260916/smoke.cjs | 页面验收测试 | 静态推定：bom loading / smoke | node qa/bom_loading_20260916/smoke.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/bom_loading_20260916/summarize.cjs | 辅助/证据脚本 | 静态推定：bom loading / summarize | node qa/bom_loading_20260916/summarize.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/bom_loading_scroll_check_20260924.cjs | 视觉测试 | 静态推定：bom loading scroll check | node qa/bom_loading_scroll_check_20260924.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/bom_pages_1920_e2e.cjs | 视觉测试 | 静态推定：bom pages 1920 e2e | node qa/bom_pages_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/bom_product_picker_1920_e2e.cjs | 视觉测试 | 静态推定：bom product picker 1920 e2e | node qa/bom_product_picker_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/bom_purchase_cutting_update_20260924/apply.cjs | 数据初始化脚本 | 静态推定：bom purchase cutting update / apply | node qa/bom_purchase_cutting_update_20260924/apply.cjs | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/bom_purchase_cutting_update_20260924/browser_verify.cjs | 业务流程测试 | 静态推定：bom purchase cutting update / browser verify | node qa/bom_purchase_cutting_update_20260924/browser_verify.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/bom_purchase_cutting_update_20260924/prepare.cjs | 数据初始化脚本 | 静态推定：bom purchase cutting update / prepare | node qa/bom_purchase_cutting_update_20260924/prepare.cjs | 否 | 可能写入 | UNKNOWN |
| qa/bom_purchase_cutting_update_20260924/run_rehearsal.cjs | 数据初始化脚本 | 静态推定：bom purchase cutting update / run rehearsal | node qa/bom_purchase_cutting_update_20260924/run_rehearsal.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/bom_v3_create_1920_e2e.cjs | 视觉测试 | 静态推定：bom v3 create 1920 e2e | node qa/bom_v3_create_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/business_compact_controls_1920_e2e.cjs | 视觉测试 | 静态推定：business compact controls 1920 e2e | node qa/business_compact_controls_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/capture_metal_plan_columns_20261008.cjs | 视觉测试 | 静态推定：capture metal plan columns | node qa/capture_metal_plan_columns_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/capture_purchase_right_20261008.cjs | 视觉测试 | 静态推定：capture purchase right | node qa/capture_purchase_right_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/cfg01_reference_data_e2e.cjs | 业务流程测试 | 静态推定：cfg01 reference data e2e | node qa/cfg01_reference_data_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/check_after_scroll_fix_20261008.cjs | 视觉测试 | 静态推定：check after scroll fix | node qa/check_after_scroll_fix_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/check_metal_plan_columns_20261008.cjs | 页面验收测试 | 静态推定：check metal plan columns | node qa/check_metal_plan_columns_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/check_purchase_detail_columns_20261008.cjs | 业务流程测试 | 静态推定：check purchase detail columns | node qa/check_purchase_detail_columns_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/check_purchase_source_20261008.cjs | 业务流程测试 | 静态推定：check purchase source | node qa/check_purchase_source_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/check_purchase_tooltip_20261008.cjs | 视觉测试 | 静态推定：check purchase tooltip | node qa/check_purchase_tooltip_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/compact_sidebar_and_tags_e2e.cjs | 视觉测试 | 静态推定：compact sidebar and tags e2e | node qa/compact_sidebar_and_tags_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/complaint_module_e2e.cjs | 业务流程测试 | 静态推定：complaint module e2e | node qa/complaint_module_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/config_on_demand_redis_20260915/measure.cjs | 视觉测试 | 静态推定：config on demand redis / measure | node qa/config_on_demand_redis_20260915/measure.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/config_on_demand_redis_20260915/no_poll.cjs | 页面验收测试 | 静态推定：config on demand redis / no poll | node qa/config_on_demand_redis_20260915/no_poll.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/contact_module_e2e.cjs | 业务流程测试 | 静态推定：contact module e2e | node qa/contact_module_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/contacts_table_scroll_20260924.cjs | 视觉测试 | 静态推定：contacts table scroll | node qa/contacts_table_scroll_20260924.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/crm_unit01_customer_api_client_e2e.cjs | 业务流程测试 | 静态推定：crm unit01 customer api client e2e | node qa/crm_unit01_customer_api_client_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/current_scroll_audit_20261008.cjs | 视觉测试 | 静态推定：current scroll audit | node qa/current_scroll_audit_20261008.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/cus01_customer_list_e2e.cjs | 业务流程测试 | 静态推定：cus01 customer list e2e | node qa/cus01_customer_list_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/cus03_customer_edit_figma_e2e.cjs | 视觉测试 | 静态推定：cus03 customer edit figma e2e | node qa/cus03_customer_edit_figma_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/cus05_contact_figma_e2e.cjs | 视觉测试 | 静态推定：cus05 contact figma e2e | node qa/cus05_contact_figma_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/cus05_contact_mutation_e2e.cjs | 业务流程测试 | 静态推定：cus05 contact mutation e2e | node qa/cus05_contact_mutation_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/customer_config_cache_20260915/interactions.cjs | 业务流程测试 | 静态推定：customer config cache / interactions | node qa/customer_config_cache_20260915/interactions.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/customer_config_cache_20260915/measure.cjs | 视觉测试 | 静态推定：customer config cache / measure | node qa/customer_config_cache_20260915/measure.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/customer_config_cache_20260915/summarize.cjs | 辅助/证据脚本 | 静态推定：customer config cache / summarize | node qa/customer_config_cache_20260915/summarize.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/customer_contacts_v2_1920_e2e.cjs | 视觉测试 | 静态推定：customer contacts v2 1920 e2e | node qa/customer_contacts_v2_1920_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_detail_prototype_e2e.cjs | 业务流程测试 | 静态推定：customer detail prototype e2e | node qa/customer_detail_prototype_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/customer_detail_remaining_v2_e2e.cjs | 业务流程测试 | 静态推定：customer detail remaining v2 e2e | node qa/customer_detail_remaining_v2_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_form_v2_1920_e2e.cjs | 视觉测试 | 静态推定：customer form v2 1920 e2e | node qa/customer_form_v2_1920_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_list_confirmed_1920_e2e.cjs | 视觉测试 | 静态推定：customer list confirmed 1920 e2e | node qa/customer_list_confirmed_1920_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_list_feedback_e2e.cjs | 业务流程测试 | 静态推定：customer list feedback e2e | node qa/customer_list_feedback_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/customer_list_loading_20260915/measure.cjs | 视觉测试 | 静态推定：customer list loading / measure | node qa/customer_list_loading_20260915/measure.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_list_loading_20260915/probe_container.cjs | 辅助/证据脚本 | 静态推定：customer list loading / probe container | node qa/customer_list_loading_20260915/probe_container.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/customer_list_loading_20260915/probe_http.cjs | 业务流程测试 | 静态推定：customer list loading / probe http | node qa/customer_list_loading_20260915/probe_http.cjs | 是（调用浏览器，模式UNKNOWN） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_list_loading_20260915/report.cjs | 辅助/证据脚本 | 静态推定：customer list loading / report | node qa/customer_list_loading_20260915/report.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/customer_list_loading_fix_20260915/final/measure.cjs | 视觉测试 | 静态推定：final / measure | node qa/customer_list_loading_fix_20260915/final/measure.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_list_loading_fix_20260915/profile/measure.cjs | 视觉测试 | 静态推定：profile / measure | node qa/customer_list_loading_fix_20260915/profile/measure.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_list_loading_fix_20260915/step1/measure.cjs | 视觉测试 | 静态推定：step1 / measure | node qa/customer_list_loading_fix_20260915/step1/measure.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_list_loading_fix_20260915/summarize.cjs | 辅助/证据脚本 | 静态推定：customer list loading fix / summarize | node qa/customer_list_loading_fix_20260915/summarize.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/customer_list_loading_fix_20260915/verify_interactions.cjs | 业务流程测试 | 静态推定：customer list loading fix / verify interactions | node qa/customer_list_loading_fix_20260915/verify_interactions.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/customer_list_prototype_e2e.cjs | 业务流程测试 | 静态推定：customer list prototype e2e | node qa/customer_list_prototype_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/customer_loading_20260915/inspect.cjs | 业务流程测试 | 静态推定：customer loading / inspect | node qa/customer_loading_20260915/inspect.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_loading_20260915/measure.cjs | 视觉测试 | 静态推定：customer loading / measure | node qa/customer_loading_20260915/measure.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/customer_loading_20260915/summarize.cjs | 业务流程测试 | 静态推定：customer loading / summarize | node qa/customer_loading_20260915/summarize.cjs | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/customer_loading_breakdown_20260915/measure.cjs | 视觉测试 | 静态推定：customer loading breakdown / measure | node qa/customer_loading_breakdown_20260915/measure.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/customer_loading_breakdown_20260915/summarize.cjs | 辅助/证据脚本 | 静态推定：customer loading breakdown / summarize | node qa/customer_loading_breakdown_20260915/summarize.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/customer_management_table_density_1920_e2e.cjs | 视觉测试 | 静态推定：customer management table density 1920 e2e | node qa/customer_management_table_density_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/customer_module_e2e.cjs | 业务流程测试 | 静态推定：customer module e2e | node qa/customer_module_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/customer_overview_v2_1920_e2e.cjs | 视觉测试 | 静态推定：customer overview v2 1920 e2e | node qa/customer_overview_v2_1920_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_task_integration_e2e.cjs | 业务流程测试 | 静态推定：customer task integration e2e | node qa/customer_task_integration_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/customer_window_dialog_e2e.cjs | 业务流程测试 | 静态推定：customer window dialog e2e | node qa/customer_window_dialog_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/design_knowledge_review_20260929/feedback_batch8_review.check.cjs | 视觉测试 | 静态推定：design knowledge review / feedback batch8 review.check | node qa/design_knowledge_review_20260929/feedback_batch8_review.check.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/design_knowledge_review_20260929/formal_write_20260930/apply_confirmed_design.cjs | 数据初始化脚本 | 本次已批准文档写入的可复查脚本；快照不匹配时停止，避免覆盖并行修改。 | node qa/design_knowledge_review_20260929/formal_write_20260930/apply_confirmed_design.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/design_knowledge_review_20260929/formal_write_20260930/update_review_status.cjs | 辅助/证据脚本 | 静态推定：formal write / update review status | node qa/design_knowledge_review_20260929/formal_write_20260930/update_review_status.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/design_knowledge_review_20260929/formal_write_20260930/verify_formal_write.cjs | 视觉测试 | 静态推定：formal write / verify formal write | node qa/design_knowledge_review_20260929/formal_write_20260930/verify_formal_write.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/design_knowledge_review_20260929/layout_batch10_review.check.cjs | 视觉测试 | 静态推定：design knowledge review / layout batch10 review.check | node qa/design_knowledge_review_20260929/layout_batch10_review.check.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/design_knowledge_review_20260929/media_navigation_batch9_review.check.cjs | 视觉测试 | 静态推定：design knowledge review / media navigation batch9 review.check | node qa/design_knowledge_review_20260929/media_navigation_batch9_review.check.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/design_knowledge_review_20260929/overlays_batch7_review.check.cjs | 视觉测试 | 静态推定：design knowledge review / overlays batch7 review.check | node qa/design_knowledge_review_20260929/overlays_batch7_review.check.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/design_knowledge_review_20260930/batch5_current_ui_verify.cjs | 视觉测试 | 静态推定：design knowledge review / batch5 current ui verify | node qa/design_knowledge_review_20260930/batch5_current_ui_verify.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/design_knowledge_review_20260930/finished_probe_corrected.cjs | 视觉测试 | 静态推定：design knowledge review / finished probe corrected | node qa/design_knowledge_review_20260930/finished_probe_corrected.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/design_knowledge_review_20260930/finished_style_probe.cjs | 视觉测试 | 静态推定：design knowledge review / finished style probe | node qa/design_knowledge_review_20260930/finished_style_probe.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/design_knowledge_review_20260930/input_checkbox_batch1_browser_measurement.cjs | 视觉测试 | 静态推定：design knowledge review / input checkbox batch1 browser measurement | node qa/design_knowledge_review_20260930/input_checkbox_batch1_browser_measurement.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/design_knowledge_review_20260930/input_checkbox_batch1_browser_refine.cjs | 视觉测试 | 静态推定：design knowledge review / input checkbox batch1 browser refine | node qa/design_knowledge_review_20260930/input_checkbox_batch1_browser_refine.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/design_knowledge_review_20260930/post_patch_verify.cjs | 视觉测试 | 静态推定：design knowledge review / post patch verify | node qa/design_knowledge_review_20260930/post_patch_verify.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/design_knowledge_review_20260930/refine_measurement_support_probe.cjs | 视觉测试 | 静态推定：design knowledge review / refine measurement support probe | node qa/design_knowledge_review_20260930/refine_measurement_support_probe.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/design_knowledge_review_20260930/semi_probe_debug.cjs | 视觉测试 | 静态推定：design knowledge review / semi probe debug | node qa/design_knowledge_review_20260930/semi_probe_debug.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/design_knowledge_review_20260930/semi_probe_metal.cjs | 视觉测试 | 静态推定：design knowledge review / semi probe metal | node qa/design_knowledge_review_20260930/semi_probe_metal.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/direct_handoff_activation_20260923/activation_runner.cjs | 数据初始化脚本 | pg_dump恢复会把常量varchar数组的整体text转换写成逐元素转换；仅规范化此精确语法。 | node qa/direct_handoff_activation_20260923/activation_runner.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/direct_handoff_activation_20260923/browser_readonly.cjs | 页面验收测试 | 复用既有管理员会话；会话值只保留在内存，不输出、不保存、不新建登录记录。 | node qa/direct_handoff_activation_20260923/browser_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/direct_handoff_activation_20260923/verify_date_rebase.cjs | 数据初始化脚本 | 刷新只读预览并检查日期、28行数量和已有单据状态，绝不调用业务写接口。 | node qa/direct_handoff_activation_20260923/verify_date_rebase.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/direct_handoff_design_20260922/preview_server.cjs | 辅助/证据脚本 | 静态推定：direct handoff design / preview server | node qa/direct_handoff_design_20260922/preview_server.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/direct_handoff_design_20260922/verify_design.cjs | 视觉测试 | 静态推定：direct handoff design / verify design | node qa/direct_handoff_design_20260922/verify_design.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/direct_handoff_original_closure_design_20260923/preview_server.cjs | 辅助/证据脚本 | 静态推定：direct handoff original closure design / preview server | node qa/direct_handoff_original_closure_design_20260923/preview_server.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/direct_handoff_original_closure_design_20260923/verify_design.cjs | 视觉测试 | 静态推定：direct handoff original closure design / verify design | node qa/direct_handoff_original_closure_design_20260923/verify_design.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/direct_handoff_original_return_20260923/browser_acceptance.cjs | 业务流程测试 | 只拦截越界目标，不模拟任何响应；防止前端默认地址将验收请求发往主服务。 | node qa/direct_handoff_original_return_20260923/browser_acceptance.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/direct_handoff_p4_completion_design_20260923/preview_server.cjs | 辅助/证据脚本 | 静态推定：direct handoff p4 completion design / preview server | node qa/direct_handoff_p4_completion_design_20260923/preview_server.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/direct_handoff_p4_completion_design_20260923/verify_design.cjs | 视觉测试 | 静态推定：direct handoff p4 completion design / verify design | node qa/direct_handoff_p4_completion_design_20260923/verify_design.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/direct_handoff_p4_d3_20260922/p4d3_browser_qa.cjs | 页面验收测试 | 静态推定：direct handoff p4 d3 / p4d3 browser qa | node qa/direct_handoff_p4_d3_20260922/p4d3_browser_qa.cjs | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/direct_handoff_p4_d4_20260922/p4d4_browser_qa.cjs | 页面验收测试 | 静态推定：direct handoff p4 d4 / p4d4 browser qa | node qa/direct_handoff_p4_d4_20260922/p4d4_browser_qa.cjs | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/direct_handoff_p4_design_20260922/preview_server.cjs | 辅助/证据脚本 | 静态推定：direct handoff p4 design / preview server | node qa/direct_handoff_p4_design_20260922/preview_server.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/direct_handoff_p4_design_20260922/verify_design.cjs | 视觉测试 | 静态推定：direct handoff p4 design / verify design | node qa/direct_handoff_p4_design_20260922/verify_design.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/direct_handoff_p4_e_20260923/browser_acceptance.cjs | 业务流程测试 | 静态推定：direct handoff p4 e / browser acceptance | node qa/direct_handoff_p4_e_20260923/browser_acceptance.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/direct_handoff_p4_e_20260923/browser_readback.cjs | 页面验收测试 | 静态推定：direct handoff p4 e / browser readback | node qa/direct_handoff_p4_e_20260923/browser_readback.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/direct_handoff_p4_semi_integer_20260923/browser_acceptance.cjs | 业务流程测试 | 静态推定：direct handoff p4 semi integer / browser acceptance | node qa/direct_handoff_p4_semi_integer_20260923/browser_acceptance.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/direct_handoff_remaining_20260923/browser_final_readonly.cjs | 页面验收测试 | 静态推定：direct handoff remaining / browser final readonly | node qa/direct_handoff_remaining_20260923/browser_final_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/direct_handoff_remaining_20260923/browser_stage_one.cjs | 页面验收测试 | 静态推定：direct handoff remaining / browser stage one | node qa/direct_handoff_remaining_20260923/browser_stage_one.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/direct_handoff_remaining_20260923/browser_stage_three.cjs | 页面验收测试 | 静态推定：direct handoff remaining / browser stage three | node qa/direct_handoff_remaining_20260923/browser_stage_three.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/direct_handoff_remaining_20260923/browser_stage_two.cjs | 页面验收测试 | 静态推定：direct handoff remaining / browser stage two | node qa/direct_handoff_remaining_20260923/browser_stage_two.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/dynamic_scroll_audit_20261008.cjs | 视觉测试 | 静态推定：dynamic scroll audit | node qa/dynamic_scroll_audit_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/eight_modules_loading_20260916/add_pages.cjs | 辅助/证据脚本 | 静态推定：eight modules loading / add pages | node qa/eight_modules_loading_20260916/add_pages.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/eight_modules_loading_20260916/archive.cjs | 辅助/证据脚本 | 静态推定：eight modules loading / archive | node qa/eight_modules_loading_20260916/archive.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/eight_modules_loading_20260916/complaints/after/measure.cjs | 视觉测试 | 静态推定：after / measure | node qa/eight_modules_loading_20260916/complaints/after/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/complaints/before/measure.cjs | 视觉测试 | 静态推定：before / measure | node qa/eight_modules_loading_20260916/complaints/before/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/contacts/after/measure.cjs | 视觉测试 | 静态推定：after / measure | node qa/eight_modules_loading_20260916/contacts/after/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/contacts/before/measure.cjs | 视觉测试 | 静态推定：before / measure | node qa/eight_modules_loading_20260916/contacts/before/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/discover.cjs | 页面验收测试 | 静态推定：eight modules loading / discover | node qa/eight_modules_loading_20260916/discover.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/edit_contacts.cjs | 辅助/证据脚本 | 静态推定：eight modules loading / edit contacts | node qa/eight_modules_loading_20260916/edit_contacts.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/eight_modules_loading_20260916/edit_quotations.cjs | 辅助/证据脚本 | 静态推定：eight modules loading / edit quotations | node qa/eight_modules_loading_20260916/edit_quotations.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/eight_modules_loading_20260916/edit_remaining.cjs | 辅助/证据脚本 | 静态推定：eight modules loading / edit remaining | node qa/eight_modules_loading_20260916/edit_remaining.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/eight_modules_loading_20260916/edit_samples.cjs | 辅助/证据脚本 | 静态推定：eight modules loading / edit samples | node qa/eight_modules_loading_20260916/edit_samples.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/eight_modules_loading_20260916/edit_warehouse.cjs | 辅助/证据脚本 | 静态推定：eight modules loading / edit warehouse | node qa/eight_modules_loading_20260916/edit_warehouse.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/eight_modules_loading_20260916/prepare.cjs | 数据初始化脚本 | 静态推定：eight modules loading / prepare | node qa/eight_modules_loading_20260916/prepare.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/eight_modules_loading_20260916/prepare_measure.cjs | 数据初始化脚本 | 静态推定：eight modules loading / prepare measure | node qa/eight_modules_loading_20260916/prepare_measure.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/eight_modules_loading_20260916/quotations/after/measure.cjs | 视觉测试 | 静态推定：after / measure | node qa/eight_modules_loading_20260916/quotations/after/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/quotations/before/measure.cjs | 视觉测试 | 静态推定：before / measure | node qa/eight_modules_loading_20260916/quotations/before/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/raw/after/measure.cjs | 视觉测试 | 静态推定：after / measure | node qa/eight_modules_loading_20260916/raw/after/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/raw/before/measure.cjs | 视觉测试 | 静态推定：before / measure | node qa/eight_modules_loading_20260916/raw/before/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/report.cjs | 辅助/证据脚本 | 静态推定：eight modules loading / report | node qa/eight_modules_loading_20260916/report.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/eight_modules_loading_20260916/sales/after/measure.cjs | 视觉测试 | 静态推定：after / measure | node qa/eight_modules_loading_20260916/sales/after/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/sales/before/measure.cjs | 视觉测试 | 静态推定：before / measure | node qa/eight_modules_loading_20260916/sales/before/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/samples/after/measure.cjs | 视觉测试 | 静态推定：after / measure | node qa/eight_modules_loading_20260916/samples/after/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/samples/before/measure.cjs | 视觉测试 | 静态推定：before / measure | node qa/eight_modules_loading_20260916/samples/before/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/smoke.cjs | 页面验收测试 | 静态推定：eight modules loading / smoke | node qa/eight_modules_loading_20260916/smoke.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/tasks/after/measure.cjs | 视觉测试 | 静态推定：after / measure | node qa/eight_modules_loading_20260916/tasks/after/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/tasks/before/measure.cjs | 视觉测试 | 静态推定：before / measure | node qa/eight_modules_loading_20260916/tasks/before/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/update_sample_tests.cjs | 辅助/证据脚本 | 单独运行原始样品列表，验证既有弹窗测试失败，不覆盖正在修改的文件。 | node qa/eight_modules_loading_20260916/update_sample_tests.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/eight_modules_loading_20260916/warehouse/after/measure.cjs | 视觉测试 | 静态推定：after / measure | node qa/eight_modules_loading_20260916/warehouse/after/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/eight_modules_loading_20260916/warehouse/before/measure.cjs | 视觉测试 | 静态推定：before / measure | node qa/eight_modules_loading_20260916/warehouse/before/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_bom_editor_probe_20260924.cjs | 页面验收测试 | 静态推定：ellipsis bom editor probe | node qa/ellipsis_bom_editor_probe_20260924.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_drawer_crm_probe_20260924.cjs | 页面验收测试 | 静态推定：ellipsis drawer crm probe | node qa/ellipsis_drawer_crm_probe_20260924.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_native_table_crm_20260924.cjs | 页面验收测试 | 静态推定：ellipsis native table crm | node qa/ellipsis_native_table_crm_20260924.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_ops_custom_scan_20260924.cjs | 页面验收测试 | 静态推定：ellipsis ops custom scan | node qa/ellipsis_ops_custom_scan_20260924.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_ops_dialog_probe_20260924.cjs | 页面验收测试 | 静态推定：ellipsis ops dialog probe | node qa/ellipsis_ops_dialog_probe_20260924.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_ops_probe_20260924.cjs | 页面验收测试 | 静态推定：ellipsis ops probe | node qa/ellipsis_ops_probe_20260924.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_production_controls_20260924.cjs | 业务流程测试 | 静态推定：ellipsis production controls | node qa/ellipsis_production_controls_20260924.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_production_native_20260924.cjs | 业务流程测试 | 静态推定：ellipsis production native | node qa/ellipsis_production_native_20260924.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_production_popups_20260924.cjs | 业务流程测试 | 静态推定：ellipsis production popups | node qa/ellipsis_production_popups_20260924.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_production_scan_20260924.cjs | 业务流程测试 | 静态推定：ellipsis production scan | node qa/ellipsis_production_scan_20260924.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_purchase_selection_check_20260924.cjs | 业务流程测试 | 静态推定：ellipsis purchase selection check | node qa/ellipsis_purchase_selection_check_20260924.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_reference_tooltip_check_20260924.cjs | 视觉测试 | 静态推定：ellipsis reference tooltip check | node qa/ellipsis_reference_tooltip_check_20260924.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_short_badge_probe_crm_20260924.cjs | 页面验收测试 | 静态推定：ellipsis short badge probe crm | node qa/ellipsis_short_badge_probe_crm_20260924.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/ellipsis_supplier_status_check_20260924.cjs | 页面验收测试 | 静态推定：ellipsis supplier status check | node qa/ellipsis_supplier_status_check_20260924.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/email_account_tutorial_e2e.cjs | 业务流程测试 | 静态推定：email account tutorial e2e | node qa/email_account_tutorial_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/ente_customer_import_e2e.cjs | 业务流程测试 | 静态推定：ente customer import e2e | node qa/ente_customer_import_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/extra_scroll_check_20261008.cjs | 视觉测试 | 静态推定：extra scroll check | node qa/extra_scroll_check_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/fabric_unit_flow_audit_20260924/procurement_inventory_readonly.cjs | API测试辅助脚本 | 静态推定：fabric unit flow audit / procurement inventory readonly | node qa/fabric_unit_flow_audit_20260924/procurement_inventory_readonly.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/fabric_unit_flow_audit_20260924/run_unit_chain.cjs | API测试辅助脚本 | 复用已验证的隔离实例、种子及唯一测试库保护，仅加载本次两个审计案例。 | node qa/fabric_unit_flow_audit_20260924/run_unit_chain.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/fabric_unit_flow_audit_20260924/semi_issue_readonly.cjs | API测试辅助脚本 | 静态推定：fabric unit flow audit / semi issue readonly | node qa/fabric_unit_flow_audit_20260924/semi_issue_readonly.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/fabric_unit_flow_audit_20260924/semi_unit_guard_probe.cjs | API测试辅助脚本 | 静态推定：fabric unit flow audit / semi unit guard probe | node qa/fabric_unit_flow_audit_20260924/semi_unit_guard_probe.cjs；需环境变量 | 否 | 否（只读/拦截） | UNKNOWN |
| qa/finished_goods_20260929/capture_browser.cjs | 视觉测试 | 静态推定：finished goods / capture browser | node qa/finished_goods_20260929/capture_browser.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/finished_goods_20260929/connect_frontend.cjs | 辅助/证据脚本 | 静态推定：finished goods / connect frontend | node qa/finished_goods_20260929/connect_frontend.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/finished_goods_20260929/prepare.cjs | 数据初始化脚本 | 静态推定：finished goods / prepare | node qa/finished_goods_20260929/prepare.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/finished_goods_20260929/start_frontend.cjs | 辅助/证据脚本 | 静态推定：finished goods / start frontend | node qa/finished_goods_20260929/start_frontend.cjs；需环境变量 | 否 | UNKNOWN | UNKNOWN |
| qa/finished_goods_20260929/start_preview.cjs | 辅助/证据脚本 | 静态推定：finished goods / start preview | node qa/finished_goods_20260929/start_preview.cjs | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/finished_goods_20260929/verify_backend.cjs | API测试辅助脚本 | 静态推定：finished goods / verify backend | node qa/finished_goods_20260929/verify_backend.cjs；参数见脚本 | 否 | UNKNOWN | 是（账号/Session/环境变量） |
| qa/finished_goods_20260929/verify_business_browser.cjs | 业务流程测试 | 静态推定：finished goods / verify business browser | node qa/finished_goods_20260929/verify_business_browser.cjs；参数见脚本 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/finished_goods_20260929/verify_replay_browser.cjs | 页面验收测试 | 静态推定：finished goods / verify replay browser | node qa/finished_goods_20260929/verify_replay_browser.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/finished_goods_20260929/verify_scope.cjs | API测试辅助脚本 | 静态推定：finished goods / verify scope | node qa/finished_goods_20260929/verify_scope.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/finished_goods_design_20260929/capture_current.cjs | 视觉测试 | 静态推定：finished goods design / capture current | node qa/finished_goods_design_20260929/capture_current.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/finished_goods_design_20260929/capture_latest.cjs | 视觉测试 | 静态推定：finished goods design / capture latest | node qa/finished_goods_design_20260929/capture_latest.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/finished_goods_design_20260929/serve.cjs | 辅助/证据脚本 | 静态推定：finished goods design / serve | node qa/finished_goods_design_20260929/serve.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/finished_goods_design_20260929/verify_design.cjs | 视觉测试 | 静态推定：finished goods design / verify design | node qa/finished_goods_design_20260929/verify_design.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/finished_goods_inventory_1920_e2e.cjs | 视觉测试 | 静态推定：finished goods inventory 1920 e2e | node qa/finished_goods_inventory_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/finished_receipt_compact_20260929/check-alignment.cjs | 视觉测试 | 静态推定：finished receipt compact / check alignment | node qa/finished_receipt_compact_20260929/check-alignment.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/finished_receipt_compact_20260929/check.cjs | 视觉测试 | 静态推定：finished receipt compact / check | node qa/finished_receipt_compact_20260929/check.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/finished_receipt_implementation_20260929/browser.cjs | 业务流程测试 | 以下仅在浏览器拦截测试响应，所有提交均由本脚本响应，不发送至数据库。 | node qa/finished_receipt_implementation_20260929/browser.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/finished_receipt_optional_color_20260929/browser_check.cjs | 视觉测试 | 静态推定：finished receipt optional color / browser check | node qa/finished_receipt_optional_color_20260929/browser_check.cjs | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/finished_receipt_picker_20260929/browser.cjs | 业务流程测试 | 静态推定：finished receipt picker / browser | node qa/finished_receipt_picker_20260929/browser.cjs | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/finished_receipt_picker_20260929/browser_disabled.cjs | 业务流程测试 | 静态推定：finished receipt picker / browser disabled | node qa/finished_receipt_picker_20260929/browser_disabled.cjs | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/global_page_tabs_20260930/browser_check.cjs | 页面验收测试 | 静态推定：global page tabs / browser check | node qa/global_page_tabs_20260930/browser_check.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/global_page_tabs_20260930/compare_design.cjs | 视觉测试 | 静态推定：global page tabs / compare design | node qa/global_page_tabs_20260930/compare_design.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/global_page_tabs_20260930/design_comparison.cjs | 视觉测试 | 静态推定：global page tabs / design comparison | node qa/global_page_tabs_20260930/design_comparison.cjs | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/global_page_tabs_all_routes_20261007/browser_check.cjs | 页面验收测试 | 静态推定：global page tabs all routes / browser check | node qa/global_page_tabs_all_routes_20261007/browser_check.cjs | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/inq_figma_demo_e2e.cjs | 视觉测试 | 静态推定：inq figma demo e2e | node qa/inq_figma_demo_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/inquiry_customer_table_density_1920_e2e.cjs | 视觉测试 | 静态推定：inquiry customer table density 1920 e2e | node qa/inquiry_customer_table_density_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/inquiry_detail_width_probe_20260924.cjs | 视觉测试 | 静态推定：inquiry detail width probe | node qa/inquiry_detail_width_probe_20260924.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/inquiry_list_width_probe_20260924.cjs | 视觉测试 | 静态推定：inquiry list width probe | node qa/inquiry_list_width_probe_20260924.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/inspect_complaint_layout_20261008.cjs | 视觉测试 | 静态推定：inspect complaint layout | node qa/inspect_complaint_layout_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/inspect_login_debug.cjs | 页面验收测试 | 静态推定：inspect login debug | node qa/inspect_login_debug.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/internal_receipt_backend_20260928/capture_final_readonly.cjs | 视觉测试 | 真实日期输入、清空后重新查询。 | node qa/internal_receipt_backend_20260928/capture_final_readonly.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/internal_receipt_backend_20260928/capture_preview.cjs | 视觉测试 | 静态推定：internal receipt backend / capture preview | node qa/internal_receipt_backend_20260928/capture_preview.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/internal_receipt_backend_20260928/prepare_backend.cjs | 数据初始化脚本 | 只创建独立开发副本，保留已验收候选和主环境。 | node qa/internal_receipt_backend_20260928/prepare_backend.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/internal_receipt_backend_20260928/prepare_frontend.cjs | 数据初始化脚本 | 静态推定：internal receipt backend / prepare frontend | node qa/internal_receipt_backend_20260928/prepare_frontend.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/internal_receipt_backend_20260928/start_preview.cjs | API测试辅助脚本 | 静态推定：internal receipt backend / start preview | node qa/internal_receipt_backend_20260928/start_preview.cjs | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/internal_receipt_backend_20260928/verify_backend.cjs | API测试辅助脚本 | 静态推定：internal receipt backend / verify backend | node qa/internal_receipt_backend_20260928/verify_backend.cjs | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/internal_receipt_backend_20260928/verify_browser.cjs | 业务流程测试 | 静态推定：internal receipt backend / verify browser | node qa/internal_receipt_backend_20260928/verify_browser.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/internal_receipt_backend_20260928/verify_frontend_scope.cjs | API测试辅助脚本 | 静态推定：internal receipt backend / verify frontend scope | node qa/internal_receipt_backend_20260928/verify_frontend_scope.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/internal_receipt_backend_20260928/verify_scope.cjs | API测试辅助脚本 | 静态推定：internal receipt backend / verify scope | node qa/internal_receipt_backend_20260928/verify_scope.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/internal_receipt_design_20260928/build_preview.cjs | 辅助/证据脚本 | Reuse locally rendered IconPark SVG assets, not a character-based icon substitute. | node qa/internal_receipt_design_20260928/build_preview.cjs；需环境变量 | 否 | 否（只读/拦截） | UNKNOWN |
| qa/internal_receipt_design_20260928/verify_preview.cjs | 视觉测试 | 静态推定：internal receipt design / verify preview | node qa/internal_receipt_design_20260928/verify_preview.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/inventory_final_integration_20260929/browser_readonly.cjs | 业务流程测试 | 静态推定：inventory final integration / browser readonly | node qa/inventory_final_integration_20260929/browser_readonly.cjs | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/inventory_final_integration_20260929/finalize.cjs | 辅助/证据脚本 | 静态推定：inventory final integration / finalize | node qa/inventory_final_integration_20260929/finalize.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/inventory_final_integration_20260929/manage.cjs | 辅助/证据脚本 | 静态推定：inventory final integration / manage | node qa/inventory_final_integration_20260929/manage.cjs；参数见脚本 | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/inventory_final_integration_20260929/prepare.cjs | 数据初始化脚本 | 静态推定：inventory final integration / prepare | node qa/inventory_final_integration_20260929/prepare.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/inventory_final_integration_20260929/prepare_database.cjs | 数据初始化脚本 | 静态推定：inventory final integration / prepare database | node qa/inventory_final_integration_20260929/prepare_database.cjs | 否 | 可能写入 | UNKNOWN |
| qa/inventory_final_integration_20260929/rehearse_migrations.cjs | 辅助/证据脚本 | 静态推定：inventory final integration / rehearse migrations | node qa/inventory_final_integration_20260929/rehearse_migrations.cjs | 否 | 可能写入 | UNKNOWN |
| qa/inventory_final_integration_20260929/run_checks.cjs | API测试辅助脚本 | 静态推定：inventory final integration / run checks | node qa/inventory_final_integration_20260929/run_checks.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/inventory_final_integration_20260929/start_frontend.cjs | 辅助/证据脚本 | 静态推定：inventory final integration / start frontend | node qa/inventory_final_integration_20260929/start_frontend.cjs；需环境变量 | 否 | UNKNOWN | UNKNOWN |
| qa/inventory_final_integration_20260929/start_preview.cjs | 辅助/证据脚本 | 静态推定：inventory final integration / start preview | node qa/inventory_final_integration_20260929/start_preview.cjs | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/inventory_final_integration_20260929/verify_reporting_update.cjs | API测试辅助脚本 | 静态推定：inventory final integration / verify reporting update | node qa/inventory_final_integration_20260929/verify_reporting_update.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/inventory_final_integration_20260929/verify_resolved_migration.cjs | API测试辅助脚本 | 静态推定：inventory final integration / verify resolved migration | node qa/inventory_final_integration_20260929/verify_resolved_migration.cjs | 否 | 可能写入 | UNKNOWN |
| qa/inventory_main_cutover_20260929/browser_main.cjs | 业务流程测试 | 真实8080主系统1920验收；仅创建登录会话，不提交业务表单。 | node qa/inventory_main_cutover_20260929/browser_main.cjs | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/inventory_main_cutover_20260929/deploy_main.cjs | 数据初始化脚本 | 仅部署已批准冻结文件，前置摘要不一致即停止，不覆盖他人新改动。 | node qa/inventory_main_cutover_20260929/deploy_main.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/inventory_main_cutover_20260929/freeze_payload.cjs | 数据初始化脚本 | 静态推定：inventory main cutover / freeze payload | node qa/inventory_main_cutover_20260929/freeze_payload.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/inventory_main_cutover_20260929/main_runner.cjs | 数据初始化脚本 | 主系统维护专用入口。除 --read-only 外必须先停主前后端。 | node qa/inventory_main_cutover_20260929/main_runner.cjs；参数见脚本 | 否 | 否（只读/拦截） | UNKNOWN |
| qa/inventory_main_cutover_20260929/manage.cjs | 数据初始化脚本 | 静态推定：inventory main cutover / manage | node qa/inventory_main_cutover_20260929/manage.cjs；参数见脚本 | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/inventory_main_cutover_20260929/prepare_database.cjs | 数据初始化脚本 | 静态推定：inventory main cutover / prepare database | node qa/inventory_main_cutover_20260929/prepare_database.cjs | 否 | 可能写入 | UNKNOWN |
| qa/inventory_main_cutover_20260929/prepare_live.cjs | 数据初始化脚本 | 用户已确认主系统切换清单；这里只生成受保护的执行脚本，不执行数据库写入。 | node qa/inventory_main_cutover_20260929/prepare_live.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/inventory_main_cutover_20260929/prepare_readiness.cjs | 数据初始化脚本 | 静态推定：inventory main cutover / prepare readiness | node qa/inventory_main_cutover_20260929/prepare_readiness.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/inventory_main_cutover_20260929/readiness_checks.cjs | 数据初始化脚本 | 静态推定：inventory main cutover / readiness checks | node qa/inventory_main_cutover_20260929/readiness_checks.cjs | 否 | 可能写入 | UNKNOWN |
| qa/inventory_main_cutover_20260929/render_bom_plan.cjs | 数据初始化脚本 | 静态推定：inventory main cutover / render bom plan | node qa/inventory_main_cutover_20260929/render_bom_plan.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/inventory_release_20260929/capture_browser.cjs | 视觉测试 | 仅隔离库的测试会话。令牌只保留在当前进程内，不输出、不保存到文件。 | node qa/inventory_release_20260929/capture_browser.cjs | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/inventory_release_20260929/manage.cjs | 辅助/证据脚本 | 静态推定：inventory release / manage | node qa/inventory_release_20260929/manage.cjs；参数见脚本 | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/inventory_release_20260929/merge_conflicts.cjs | 辅助/证据脚本 | 静态推定：inventory release / merge conflicts | node qa/inventory_release_20260929/merge_conflicts.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/inventory_release_20260929/prepare_database.cjs | 数据初始化脚本 | 静态推定：inventory release / prepare database | node qa/inventory_release_20260929/prepare_database.cjs | 否 | 可能写入 | UNKNOWN |
| qa/inventory_release_20260929/prepare_merge.cjs | 数据初始化脚本 | 静态推定：inventory release / prepare merge | node qa/inventory_release_20260929/prepare_merge.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/inventory_release_20260929/release_manifest.cjs | API测试辅助脚本 | 只读主源码；发布清单携带前后摘要，检测其他任务在准备期间的改动。 | node qa/inventory_release_20260929/release_manifest.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/inventory_release_20260929/render_bom_plan.cjs | 辅助/证据脚本 | 静态推定：inventory release / render bom plan | node qa/inventory_release_20260929/render_bom_plan.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/inventory_release_20260929/resolve_reviewed_merges.cjs | 辅助/证据脚本 | 静态推定：inventory release / resolve reviewed merges | node qa/inventory_release_20260929/resolve_reviewed_merges.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/inventory_release_20260929/start_frontend.cjs | 辅助/证据脚本 | 静态推定：inventory release / start frontend | node qa/inventory_release_20260929/start_frontend.cjs；需环境变量 | 否 | UNKNOWN | UNKNOWN |
| qa/inventory_release_20260929/start_preview.cjs | 辅助/证据脚本 | 只启动主库副本的浏览器检查服务，不执行任何数据初始化。 | node qa/inventory_release_20260929/start_preview.cjs | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/list_table_fill_audit_1920_e2e.cjs | 视觉测试 | 静态推定：list table fill audit 1920 e2e | node qa/list_table_fill_audit_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/login_scroll_check_20260924.cjs | 视觉测试 | 静态推定：login scroll check | node qa/login_scroll_check_20260924.cjs | 是（headless） | 否（未见写请求） | 否（模拟认证/夹具） |
| qa/material_flow_business_trial_20260921/corrected_review_20260922/browser_details.cjs | 业务流程测试 | 静态推定：corrected review / browser details | node qa/material_flow_business_trial_20260921/corrected_review_20260922/browser_details.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_business_trial_20260921/corrected_review_20260922/browser_review.cjs | 业务流程测试 | 静态推定：corrected review / browser review | node qa/material_flow_business_trial_20260921/corrected_review_20260922/browser_review.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_business_trial_20260921/piece_unit_browser.cjs | 业务流程测试 | 静态推定：material flow business trial / piece unit browser | node qa/material_flow_business_trial_20260921/piece_unit_browser.cjs；参数见脚本 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_first_cutting_issue_20260924/browser_result_qa.cjs | 业务流程测试 | 首次厂内裁剪面料领料的只读验收；主任务通知执行后才运行。 | node qa/material_flow_first_cutting_issue_20260924/browser_result_qa.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_first_cutting_issue_20260924/prepare_backup.cjs | 数据初始化脚本 | PostgreSQL 在还原时会改变等价数组类型转换的输出形式，比较前仅统一此语法。 | node qa/material_flow_first_cutting_issue_20260924/prepare_backup.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/material_flow_first_cutting_issue_20260924/verify_ledger.cjs | API测试辅助脚本 | 静态推定：material flow first cutting issue / verify ledger | node qa/material_flow_first_cutting_issue_20260924/verify_ledger.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/material_flow_first_cutting_issue_20260924/workflow.cjs | 辅助/证据脚本 | 静态推定：material flow first cutting issue / workflow | node qa/material_flow_first_cutting_issue_20260924/workflow.cjs；参数见脚本；需环境变量 | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/material_flow_first_metal_completion_20260923/browser_result_qa.cjs | 业务流程测试 | 静态推定：material flow first metal completion / browser result qa | node qa/material_flow_first_metal_completion_20260923/browser_result_qa.cjs | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_first_metal_completion_20260923/workflow.cjs | 辅助/证据脚本 | 静态推定：material flow first metal completion / workflow | node qa/material_flow_first_metal_completion_20260923/workflow.cjs；参数见脚本；需环境变量 | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/material_flow_first_metal_issue_20260923/browser_result_qa.cjs | 业务流程测试 | 首次金工领料结果只读验收。执行阶段完成后，由主任务明确通知再运行。 | node qa/material_flow_first_metal_issue_20260923/browser_result_qa.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_first_metal_issue_20260923/execute_api.cjs | API测试辅助脚本 | 静态推定：material flow first metal issue / execute api | node qa/material_flow_first_metal_issue_20260923/execute_api.cjs | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/material_flow_first_metal_issue_20260923/helpers.cjs | 辅助/证据脚本 | 静态推定：material flow first metal issue / helpers | node qa/material_flow_first_metal_issue_20260923/helpers.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_first_metal_issue_20260923/prepare.cjs | 数据初始化脚本 | 静态推定：material flow first metal issue / prepare | node qa/material_flow_first_metal_issue_20260923/prepare.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/material_flow_first_metal_issue_20260923/prepare_plan.cjs | 数据初始化脚本 | 静态推定：material flow first metal issue / prepare plan | node qa/material_flow_first_metal_issue_20260923/prepare_plan.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/material_flow_first_metal_issue_20260923/recover_rehearsal.cjs | 数据初始化脚本 | 前次已完成隔离出库，仅修正测试器的嵌套字段读取；不重复创建/提交。 | node qa/material_flow_first_metal_issue_20260923/recover_rehearsal.cjs；参数见脚本；需环境变量 | 否 | 可能写入 | UNKNOWN |
| qa/material_flow_first_metal_issue_20260923/rehearse.cjs | 辅助/证据脚本 | 静态推定：material flow first metal issue / rehearse | node qa/material_flow_first_metal_issue_20260923/rehearse.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_first_metal_issue_20260923/verify_ledger.cjs | API测试辅助脚本 | 静态推定：material flow first metal issue / verify ledger | node qa/material_flow_first_metal_issue_20260923/verify_ledger.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/material_flow_first_receipt_20260923/browser_result_qa.cjs | 业务流程测试 | 最终结果页面只读验收；仅在品质确认及最终台账均已通过后运行。 | node qa/material_flow_first_receipt_20260923/browser_result_qa.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_first_receipt_20260923/execute_receipt_ui.cjs | 业务流程测试 | 静态推定：material flow first receipt / execute receipt ui | node qa/material_flow_first_receipt_20260923/execute_receipt_ui.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_first_receipt_20260923/execute_sheets.cjs | 辅助/证据脚本 | 静态推定：material flow first receipt / execute sheets | node qa/material_flow_first_receipt_20260923/execute_sheets.cjs | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_first_receipt_20260923/prepare.cjs | 数据初始化脚本 | 静态推定：material flow first receipt / prepare | node qa/material_flow_first_receipt_20260923/prepare.cjs | 否 | 可能写入 | UNKNOWN |
| qa/material_flow_first_receipt_20260923/run_ledger.cjs | API测试辅助脚本 | 静态推定：material flow first receipt / run ledger | node qa/material_flow_first_receipt_20260923/run_ledger.cjs；参数见脚本 | 否 | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_first_receipt_20260923/session_helpers.cjs | 业务流程测试 | 静态推定：material flow first receipt / session helpers | node qa/material_flow_first_receipt_20260923/session_helpers.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_first_receipt_20260923/verify_scope.cjs | API测试辅助脚本 | 静态推定：material flow first receipt / verify scope | node qa/material_flow_first_receipt_20260923/verify_scope.cjs；参数见脚本；需环境变量 | 否 | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_first_sewing_issue_20260924/browser_result_qa.cjs | 业务流程测试 | 首次车缝辅料领料的只读验收；主任务通知执行后才运行。 | node qa/material_flow_first_sewing_issue_20260924/browser_result_qa.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_first_sewing_issue_20260924/prepare_backup.cjs | 数据初始化脚本 | PostgreSQL 在还原时会改变等价数组类型转换的输出形式，比较前仅统一此语法。 | node qa/material_flow_first_sewing_issue_20260924/prepare_backup.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/material_flow_first_sewing_issue_20260924/verify_ledger.cjs | API测试辅助脚本 | 静态推定：material flow first sewing issue / verify ledger | node qa/material_flow_first_sewing_issue_20260924/verify_ledger.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/material_flow_first_sewing_issue_20260924/workflow.cjs | 辅助/证据脚本 | 静态推定：material flow first sewing issue / workflow | node qa/material_flow_first_sewing_issue_20260924/workflow.cjs；参数见脚本；需环境变量 | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/material_flow_first_spray_handoff_20260923/confirm_factory_readonly.cjs | API测试辅助脚本 | 只读核对并记录用户选择，不创建外发单或登记交接。 | node qa/material_flow_first_spray_handoff_20260923/confirm_factory_readonly.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_first_spray_handoff_20260923/confirm_quantity_readonly.cjs | API测试辅助脚本 | 记录已确认的交接数量，价格未提供前不创建业务单据。 | node qa/material_flow_first_spray_handoff_20260923/confirm_quantity_readonly.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_first_spray_handoff_20260924/browser_result_qa.cjs | 业务流程测试 | order_date 是来源生产任务的下单日期；本轮新增与交接日期分别检查。 | node qa/material_flow_first_spray_handoff_20260924/browser_result_qa.cjs | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_first_spray_handoff_20260924/prepare_backup.cjs | 数据初始化脚本 | PostgreSQL 在还原时会改变等价数组类型转换的输出形式，比较前仅统一此语法。 | node qa/material_flow_first_spray_handoff_20260924/prepare_backup.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/material_flow_first_spray_handoff_20260924/verify_ledger.cjs | API测试辅助脚本 | 静态推定：material flow first spray handoff / verify ledger | node qa/material_flow_first_spray_handoff_20260924/verify_ledger.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/material_flow_first_spray_handoff_20260924/workflow.cjs | 辅助/证据脚本 | 静态推定：material flow first spray handoff / workflow | node qa/material_flow_first_spray_handoff_20260924/workflow.cjs；参数见脚本；需环境变量 | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/material_flow_metal_accessories_issue_20260924/browser_result_qa.cjs | 业务流程测试 | 金工五金塑料领料的只读验收；主任务通知执行后才运行。 | node qa/material_flow_metal_accessories_issue_20260924/browser_result_qa.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_metal_accessories_issue_20260924/prepare_backup.cjs | 数据初始化脚本 | PostgreSQL 在还原时会改变等价数组类型转换的输出形式，比较前仅统一此语法。 | node qa/material_flow_metal_accessories_issue_20260924/prepare_backup.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/material_flow_metal_accessories_issue_20260924/verify_ledger.cjs | API测试辅助脚本 | 静态推定：material flow metal accessories issue / verify ledger | node qa/material_flow_metal_accessories_issue_20260924/verify_ledger.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/material_flow_metal_accessories_issue_20260924/workflow.cjs | 辅助/证据脚本 | 静态推定：material flow metal accessories issue / workflow | node qa/material_flow_metal_accessories_issue_20260924/workflow.cjs；参数见脚本；需环境变量 | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/material_flow_packaging_issue_20260924/browser_result_qa.cjs | 业务流程测试 | 首次装配纸箱领料的只读验收；主任务通知执行后才运行。 | node qa/material_flow_packaging_issue_20260924/browser_result_qa.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_packaging_issue_20260924/final_batch_readonly.cjs | API测试辅助脚本 | 静态推定：material flow packaging issue / final batch readonly | node qa/material_flow_packaging_issue_20260924/final_batch_readonly.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_packaging_issue_20260924/prepare_backup.cjs | 数据初始化脚本 | PostgreSQL 在还原时会改变等价数组类型转换的输出形式，比较前仅统一此语法。 | node qa/material_flow_packaging_issue_20260924/prepare_backup.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/material_flow_packaging_issue_20260924/verify_ledger.cjs | API测试辅助脚本 | 静态推定：material flow packaging issue / verify ledger | node qa/material_flow_packaging_issue_20260924/verify_ledger.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/material_flow_packaging_issue_20260924/workflow.cjs | 辅助/证据脚本 | 静态推定：material flow packaging issue / workflow | node qa/material_flow_packaging_issue_20260924/workflow.cjs；参数见脚本；需环境变量 | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/material_flow_production_continue_20260924/assembly_issue_readonly.cjs | 业务流程测试 | 静态推定：material flow production continue / assembly issue readonly | node qa/material_flow_production_continue_20260924/assembly_issue_readonly.cjs；需环境变量 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_production_continue_20260924/reporting_preflight.cjs | API测试辅助脚本 | 静态推定：material flow production continue / reporting preflight | node qa/material_flow_production_continue_20260924/reporting_preflight.cjs；需环境变量 | 否 | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_production_continue_20260924/spray_return_readonly.cjs | 业务流程测试 | 只验证序列化器的输入规则，不调用 POST、不保存模型。 | node qa/material_flow_production_continue_20260924/spray_return_readonly.cjs；需环境变量 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_replenishment_20260923/browser_result_qa.cjs | 业务流程测试 | 最终结果只读验收：仅在 PURCHASE_COMPLETED 且 ledger_after PASS 后运行。 | node qa/material_flow_replenishment_20260923/browser_result_qa.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_replenishment_20260923/execute_api.cjs | API测试辅助脚本 | 完成门槛允许存在未补收余量，本次另检查全部28行净合格量确已补齐。 | node qa/material_flow_replenishment_20260923/execute_api.cjs；参数见脚本 | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/material_flow_replenishment_20260923/execute_ui.cjs | 业务流程测试 | 静态推定：material flow replenishment / execute ui | node qa/material_flow_replenishment_20260923/execute_ui.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_replenishment_20260923/helpers.cjs | 辅助/证据脚本 | 静态推定：material flow replenishment / helpers | node qa/material_flow_replenishment_20260923/helpers.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/material_flow_replenishment_20260923/prepare.cjs | 数据初始化脚本 | 静态推定：material flow replenishment / prepare | node qa/material_flow_replenishment_20260923/prepare.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/material_flow_replenishment_20260923/run_ledger.cjs | API测试辅助脚本 | 静态推定：material flow replenishment / run ledger | node qa/material_flow_replenishment_20260923/run_ledger.cjs；参数见脚本 | 否 | 否（只读/拦截） | UNKNOWN |
| qa/material_flow_s10_20260921/browser/s4_browser.cjs | 业务流程测试 | 用真实保存接口恢复本轮起始值，避免上一轮501毫米结果影响复验。 | node qa/material_flow_s10_20260921/browser/s4_browser.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s10_20260921/browser/s4_browser_states.cjs | 业务流程测试 | 补充界面状态验收：响应注入仅作用于此浏览器，不写入业务数据。 | node qa/material_flow_s10_20260921/browser/s4_browser_states.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s10_20260921/browser/s5_browser.cjs | 业务流程测试 | 静态推定：browser / s5 browser | node qa/material_flow_s10_20260921/browser/s5_browser.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s10_20260921/browser/s5_sample_browser.cjs | 业务流程测试 | 静态推定：browser / s5 sample browser | node qa/material_flow_s10_20260921/browser/s5_sample_browser.cjs | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/material_flow_s10_20260921/browser/s5_ui_states.cjs | 业务流程测试 | 只模拟读取响应验收 UI 状态；不作为权限或业务链路的后端测试证据。 | node qa/material_flow_s10_20260921/browser/s5_ui_states.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s10_20260921/browser/s6_browser.cjs | 业务流程测试 | 静态推定：browser / s6 browser | node qa/material_flow_s10_20260921/browser/s6_browser.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s10_20260921/browser/s6_ui_states.cjs | 业务流程测试 | 静态推定：browser / s6 ui states | node qa/material_flow_s10_20260921/browser/s6_ui_states.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s10_20260921/browser/s7_browser.cjs | 业务流程测试 | 静态推定：browser / s7 browser | node qa/material_flow_s10_20260921/browser/s7_browser.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s10_20260921/browser/s7_ui_states.cjs | 业务流程测试 | 静态推定：browser / s7 ui states | node qa/material_flow_s10_20260921/browser/s7_ui_states.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s4_20260918/s4_browser.cjs | 业务流程测试 | 静态推定：material flow s4 / s4 browser | node qa/material_flow_s4_20260918/s4_browser.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s4_20260918/s4_browser_states.cjs | 业务流程测试 | 补充界面状态验收：响应注入仅作用于此浏览器，不写入业务数据。 | node qa/material_flow_s4_20260918/s4_browser_states.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s5_20260918/s5_browser.cjs | 业务流程测试 | 静态推定：material flow s5 / s5 browser | node qa/material_flow_s5_20260918/s5_browser.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s5_20260918/s5_sample_browser.cjs | 业务流程测试 | 静态推定：material flow s5 / s5 sample browser | node qa/material_flow_s5_20260918/s5_sample_browser.cjs | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/material_flow_s5_20260918/s5_ui_states.cjs | 业务流程测试 | 只模拟读取响应验收 UI 状态；不作为权限或业务链路的后端测试证据。 | node qa/material_flow_s5_20260918/s5_ui_states.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s6_20260918/s6_browser.cjs | 业务流程测试 | 静态推定：material flow s6 / s6 browser | node qa/material_flow_s6_20260918/s6_browser.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s6_20260918/s6_ui_states.cjs | 业务流程测试 | 静态推定：material flow s6 / s6 ui states | node qa/material_flow_s6_20260918/s6_ui_states.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s7_20260918/s7_browser.cjs | 业务流程测试 | 静态推定：material flow s7 / s7 browser | node qa/material_flow_s7_20260918/s7_browser.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s7_20260918/s7_final_visual.cjs | 视觉测试 | 静态推定：material flow s7 / s7 final visual | node qa/material_flow_s7_20260918/s7_final_visual.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_s7_20260918/s7_ui_states.cjs | 业务流程测试 | 静态推定：material flow s7 / s7 ui states | node qa/material_flow_s7_20260918/s7_ui_states.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_task_dates_20260923/browser_result_qa.cjs | 业务流程测试 | 静态推定：material flow task dates / browser result qa | node qa/material_flow_task_dates_20260923/browser_result_qa.cjs；参数见脚本 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_flow_task_dates_20260923/execute_api.cjs | API测试辅助脚本 | 静态推定：material flow task dates / execute api | node qa/material_flow_task_dates_20260923/execute_api.cjs | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/material_flow_task_dates_20260923/helpers.cjs | 辅助/证据脚本 | 静态推定：material flow task dates / helpers | node qa/material_flow_task_dates_20260923/helpers.cjs；需环境变量 | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/material_flow_task_dates_20260923/prepare.cjs | 数据初始化脚本 | 静态推定：material flow task dates / prepare | node qa/material_flow_task_dates_20260923/prepare.cjs；参数见脚本；需环境变量 | 否 | 可能写入 | UNKNOWN |
| qa/material_flow_task_dates_20260923/prepare_schedule_candidate.cjs | 数据初始化脚本 | 静态推定：material flow task dates / prepare schedule candidate | node qa/material_flow_task_dates_20260923/prepare_schedule_candidate.cjs；需环境变量 | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_inbound_flow_1920_e2e.cjs | 视觉测试 | 静态推定：material inbound flow 1920 e2e | node qa/material_inbound_flow_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/material_inbound_followup_pages_design_20260916.cjs | 视觉测试 | 静态推定：material inbound followup pages design | node qa/material_inbound_followup_pages_design_20260916.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_inbound_v3_1920_e2e.cjs | 视觉测试 | 静态推定：material inbound v3 1920 e2e | node qa/material_inbound_v3_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/material_inventory_1920_e2e.cjs | 视觉测试 | 静态推定：material inventory 1920 e2e | node qa/material_inventory_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/material_inventory_layout_20260914/layout.cjs | 视觉测试 | 静态推定：material inventory layout / layout | node qa/material_inventory_layout_20260914/layout.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/material_issue_columns_20260927.cjs | 业务流程测试 | 静态推定：material issue columns | node qa/material_issue_columns_20260927.cjs | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/material_issue_detail_speed_20260928/browser_after.cjs | 业务流程测试 | 静态推定：material issue detail speed / browser after | node qa/material_issue_detail_speed_20260928/browser_after.cjs；需环境变量 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/material_issue_detail_speed_20260928/verify_results.cjs | API测试辅助脚本 | 静态推定：material issue detail speed / verify results | node qa/material_issue_detail_speed_20260928/verify_results.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/material_issue_form_visual_qa_20260917.cjs | 视觉测试 | 静态推定：material issue form visual qa | node qa/material_issue_form_visual_qa_20260917.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_issue_no_batch_assembly_20260927.cjs | 业务流程测试 | 静态推定：material issue no batch assembly | node qa/material_issue_no_batch_assembly_20260927.cjs | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/material_issue_pipe_rule_20260927.cjs | 业务流程测试 | 静态推定：material issue pipe rule | node qa/material_issue_pipe_rule_20260927.cjs | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/material_issue_records_detail_20260917.cjs | 业务流程测试 | 静态推定：material issue records detail | node qa/material_issue_records_detail_20260917.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_issue_submit_timeout_20260927.cjs | 业务流程测试 | 静态推定：material issue submit timeout | node qa/material_issue_submit_timeout_20260927.cjs | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/material_issue_v1_1920_e2e.cjs | 视觉测试 | 静态推定：material issue v1 1920 e2e | node qa/material_issue_v1_1920_e2e.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_purchase_inbound_design_20260916.cjs | 视觉测试 | 静态推定：material purchase inbound design | node qa/material_purchase_inbound_design_20260916.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/material_stock_no_batch_review_20260928/browser_readonly.cjs | 业务流程测试 | 静态推定：material stock no batch review / browser readonly | node qa/material_stock_no_batch_review_20260928/browser_readonly.cjs；需环境变量 | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/operational_management_density_1920_e2e.cjs | 视觉测试 | 静态推定：operational management density 1920 e2e | node qa/operational_management_density_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/outsourcing_detail_visual_20260917/detail_visual_qa.cjs | 视觉测试 | 静态推定：outsourcing detail visual / detail visual qa | node qa/outsourcing_detail_visual_20260917/detail_visual_qa.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/outsourcing_factory_dialog_comments_1202.cjs | 业务流程测试 | 静态推定：outsourcing factory dialog comments 1202 | node qa/outsourcing_factory_dialog_comments_1202.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/outsourcing_first_five_1920.cjs | 视觉测试 | 静态推定：outsourcing first five 1920 | node qa/outsourcing_first_five_1920.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/outsourcing_o02_o07_20260916/o02_o07_business_visual_e2e.cjs | 视觉测试 | 静态推定：outsourcing o02 o07 / o02 o07 business visual e2e | node qa/outsourcing_o02_o07_20260916/o02_o07_business_visual_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/outsourcing_o03_20260916/o03_browser_comments_1202.cjs | 业务流程测试 | 静态推定：outsourcing o03 / o03 browser comments 1202 | node qa/outsourcing_o03_20260916/o03_browser_comments_1202.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/outsourcing_o03_20260916/o03_multi_select_mock_e2e.cjs | 业务流程测试 | 静态推定：outsourcing o03 / o03 multi select mock e2e | node qa/outsourcing_o03_20260916/o03_multi_select_mock_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/outsourcing_o03_20260916/o03_visual_e2e.cjs | 视觉测试 | 静态推定：outsourcing o03 / o03 visual e2e | node qa/outsourcing_o03_20260916/o03_visual_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/outsourcing_o04_o05_20260916/o04_o05_visual_e2e.cjs | 视觉测试 | 静态推定：outsourcing o04 o05 / o04 o05 visual e2e | node qa/outsourcing_o04_o05_20260916/o04_o05_visual_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/outsourcing_revoke_20260927/browser_verify.cjs | 业务流程测试 | 静态推定：outsourcing revoke / browser verify | node qa/outsourcing_revoke_20260927/browser_verify.cjs；参数见脚本；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/outsourcing_unified_entry_20260927/browser_readonly.cjs | 业务流程测试 | 静态推定：outsourcing unified entry / browser readonly | node qa/outsourcing_unified_entry_20260927/browser_readonly.cjs；参数见脚本；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/outsourcing_unified_entry_20260927/serve_isolated.cjs | 辅助/证据脚本 | 仅在本机18047提供验收页面；API固定指向隔离后端，不连接主库。 | node qa/outsourcing_unified_entry_20260927/serve_isolated.cjs；需环境变量 | 否 | UNKNOWN | UNKNOWN |
| qa/outsourcing_unified_entry_20260927/snapshot.cjs | API测试辅助脚本 | 静态推定：outsourcing unified entry / snapshot | node qa/outsourcing_unified_entry_20260927/snapshot.cjs；参数见脚本 | 否 | 否（只读/拦截） | UNKNOWN |
| qa/outsourcing_unified_entry_20260927/verify_delivery.cjs | API测试辅助脚本 | 静态推定：outsourcing unified entry / verify delivery | node qa/outsourcing_unified_entry_20260927/verify_delivery.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/outsourcing_unified_entry_design_20260927/capture_current.cjs | 视觉测试 | 静态推定：outsourcing unified entry design / capture current | node qa/outsourcing_unified_entry_design_20260927/capture_current.cjs | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/outsourcing_unified_entry_design_20260927/inspect_design.cjs | 视觉测试 | 静态推定：outsourcing unified entry design / inspect design | node qa/outsourcing_unified_entry_design_20260927/inspect_design.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/outsourcing_unified_entry_design_20260927/preview_server.cjs | 辅助/证据脚本 | 静态推定：outsourcing unified entry design / preview server | node qa/outsourcing_unified_entry_design_20260927/preview_server.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/outsourcing_unified_entry_design_20260927/refine_style.cjs | 辅助/证据脚本 | 静态推定：outsourcing unified entry design / refine style | node qa/outsourcing_unified_entry_design_20260927/refine_style.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/outsourcing_unified_entry_design_20260927/verify_design.cjs | 视觉测试 | 静态推定：outsourcing unified entry design / verify design | node qa/outsourcing_unified_entry_design_20260927/verify_design.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/outsourcing_warehouse_flow_20260916/warehouse_flow_visual_e2e.cjs | 视觉测试 | 静态推定：outsourcing warehouse flow / warehouse flow visual e2e | node qa/outsourcing_warehouse_flow_20260916/warehouse_flow_visual_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/page_background_consistency_1920_e2e.cjs | 视觉测试 | 静态推定：page background consistency 1920 e2e | node qa/page_background_consistency_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/page_loading_audit_20260915/analyze.cjs | API测试辅助脚本 | 静态推定：page loading audit / analyze | node qa/page_loading_audit_20260915/analyze.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/page_loading_audit_20260915/cpu_profile.cjs | 页面验收测试 | 静态推定：page loading audit / cpu profile | node qa/page_loading_audit_20260915/cpu_profile.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/page_loading_audit_20260915/measure.cjs | 视觉测试 | 静态推定：page loading audit / measure | node qa/page_loading_audit_20260915/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/page_loading_audit_20260915/verify_artifacts.cjs | 页面验收测试 | 静态推定：page loading audit / verify artifacts | node qa/page_loading_audit_20260915/verify_artifacts.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/page_loading_optimization_20260915/analyze.cjs | 辅助/证据脚本 | 静态推定：page loading optimization / analyze | node qa/page_loading_optimization_20260915/analyze.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/page_loading_optimization_20260915/build_report.cjs | 辅助/证据脚本 | # 范围与测量口径 | node qa/page_loading_optimization_20260915/build_report.cjs | 否 | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/page_loading_optimization_20260915/create_diff.cjs | 辅助/证据脚本 | 静态推定：page loading optimization / create diff | node qa/page_loading_optimization_20260915/create_diff.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/page_loading_optimization_20260915/customer/analyze.cjs | 辅助/证据脚本 | 静态推定：customer / analyze | node qa/page_loading_optimization_20260915/customer/analyze.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/page_loading_optimization_20260915/customer/measure.cjs | 视觉测试 | 静态推定：customer / measure | node qa/page_loading_optimization_20260915/customer/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/page_loading_optimization_20260915/edit_contacts.cjs | 辅助/证据脚本 | 静态推定：page loading optimization / edit contacts | node qa/page_loading_optimization_20260915/edit_contacts.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/page_loading_optimization_20260915/edit_customer.cjs | 辅助/证据脚本 | 每次请求复用字段定义；不复用 .data，避免把上一行数据带到下一行。 | node qa/page_loading_optimization_20260915/edit_customer.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/page_loading_optimization_20260915/edit_inquiry.cjs | 辅助/证据脚本 | 静态推定：page loading optimization / edit inquiry | node qa/page_loading_optimization_20260915/edit_inquiry.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/page_loading_optimization_20260915/edit_production.cjs | 辅助/证据脚本 | 静态推定：page loading optimization / edit production | node qa/page_loading_optimization_20260915/edit_production.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/page_loading_optimization_20260915/inquiry/measure.cjs | 视觉测试 | 静态推定：inquiry / measure | node qa/page_loading_optimization_20260915/inquiry/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/page_loading_optimization_20260915/measure.cjs | 视觉测试 | 静态推定：page loading optimization / measure | node qa/page_loading_optimization_20260915/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/page_loading_optimization_20260915/smoke.cjs | 页面验收测试 | 静态推定：page loading optimization / smoke | node qa/page_loading_optimization_20260915/smoke.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/page_loading_optimization_20260915/verify_artifacts.cjs | 页面验收测试 | 静态推定：page loading optimization / verify artifacts | node qa/page_loading_optimization_20260915/verify_artifacts.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/page_loading_optimization_20260915/verify_customer_data.cjs | API测试辅助脚本 | 静态推定：page loading optimization / verify customer data | node qa/page_loading_optimization_20260915/verify_customer_data.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/page_navigation_compact_20261007/browser_check.cjs | 视觉测试 | 静态推定：page navigation compact / browser check | node qa/page_navigation_compact_20261007/browser_check.cjs | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/page_navigation_flat_style_20260930/browser_check.cjs | 视觉测试 | 静态推定：page navigation flat style / browser check | node qa/page_navigation_flat_style_20260930/browser_check.cjs；参数见脚本 | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/page_navigation_folder_style_20260930/browser_check.cjs | 视觉测试 | 静态推定：page navigation folder style / browser check | node qa/page_navigation_folder_style_20260930/browser_check.cjs；参数见脚本 | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/page_navigation_folder_style_20260930/compare_design.cjs | 视觉测试 | 只在对照画布中统一显示宽度；真实页面始终按 1920×1080 渲染和测量。 | node qa/page_navigation_folder_style_20260930/compare_design.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/page_navigation_folder_style_20260930/functional_regression.cjs | 视觉测试 | 静态推定：page navigation folder style / functional regression | node qa/page_navigation_folder_style_20260930/functional_regression.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/page_navigation_folder_style_20260930/iteration-1/browser_check.cjs | 视觉测试 | 静态推定：iteration 1 / browser check | node qa/page_navigation_folder_style_20260930/iteration-1/browser_check.cjs；参数见脚本 | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/page_navigation_folder_style_20260930/iteration-1/functional_regression.cjs | 视觉测试 | 静态推定：iteration 1 / functional regression | node qa/page_navigation_folder_style_20260930/iteration-1/functional_regression.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/page_navigation_title_only_20260930/browser_check.cjs | 页面验收测试 | 静态推定：page navigation title only / browser check | node qa/page_navigation_title_only_20260930/browser_check.cjs | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/page_shell_standard_1920_e2e.cjs | 视觉测试 | 静态推定：page shell standard 1920 e2e | node qa/page_shell_standard_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/page_tab_close_color_20260930/browser_check.cjs | 视觉测试 | 静态推定：page tab close color / browser check | node qa/page_tab_close_color_20260930/browser_check.cjs；参数见脚本 | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/permissions_deletion_stage2_20260929/browser_visual.cjs | 视觉测试 | 静态推定：permissions deletion stage2 / browser visual | node qa/permissions_deletion_stage2_20260929/browser_visual.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/permissions_scopes_stage1_20260929/browser_acceptance.cjs | 业务流程测试 | 静态推定：permissions scopes stage1 / browser acceptance | node qa/permissions_scopes_stage1_20260929/browser_acceptance.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/permissions_stage1_20260928/build_inventory.cjs | 辅助/证据脚本 | 静态推定：permissions stage1 / build inventory | node qa/permissions_stage1_20260928/build_inventory.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/permissions_stage1_20260928/build_preview.cjs | 辅助/证据脚本 | 静态推定：permissions stage1 / build preview | node qa/permissions_stage1_20260928/build_preview.cjs；需环境变量 | 否 | UNKNOWN | UNKNOWN |
| qa/permissions_stage1_20260928/verify_artifacts.cjs | API测试辅助脚本 | Concurrent workspace change reviewed separately: command imports metal operations, | node qa/permissions_stage1_20260928/verify_artifacts.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/permissions_stage1_20260928/verify_design_polish.cjs | 视觉测试 | 静态推定：permissions stage1 / verify design polish | node qa/permissions_stage1_20260928/verify_design_polish.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/permissions_stage1_20260928/verify_preview.cjs | 业务流程测试 | 静态推定：permissions stage1 / verify preview | node qa/permissions_stage1_20260928/verify_preview.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/permissions_stage3_20260928/browser_acceptance.cjs | 业务流程测试 | Exercise the project's LAN fallback even on localhost, without faking APIs. | node qa/permissions_stage3_20260928/browser_acceptance.cjs | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/permissions_stage4_20260928/browser_acceptance.cjs | 业务流程测试 | 静态推定：permissions stage4 / browser acceptance | node qa/permissions_stage4_20260928/browser_acceptance.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/permissions_stage5_20260928/browser_acceptance.cjs | 业务流程测试 | 静态推定：permissions stage5 / browser acceptance | node qa/permissions_stage5_20260928/browser_acceptance.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/permissions_stage6_20260928/activation_backup.cjs | 数据初始化脚本 | Binary-safe pg_dump backup. Never print database environment or credentials. | node qa/permissions_stage6_20260928/activation_backup.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/permissions_stage6_20260928/activation_browser.cjs | 业务流程测试 | Read-only checks against the real ERP, reusing existing valid sessions in memory. | node qa/permissions_stage6_20260928/activation_browser.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/permissions_stage6_20260928/activation_flags.cjs | 数据初始化脚本 | 静态推定：permissions stage6 / activation flags | node qa/permissions_stage6_20260928/activation_flags.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/permissions_stage6_20260928/browser_acceptance.cjs | 业务流程测试 | 静态推定：permissions stage6 / browser acceptance | node qa/permissions_stage6_20260928/browser_acceptance.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/procurement_inventory_density_1920_e2e.cjs | 视觉测试 | 静态推定：procurement inventory density 1920 e2e | node qa/procurement_inventory_density_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/product_information_e2e.cjs | 业务流程测试 | 静态推定：product information e2e | node qa/product_information_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/product_material_1920_e2e.cjs | 视觉测试 | 静态推定：product material 1920 e2e | node qa/product_material_1920_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/production_bom_v3_detail_preview_1920_visual.cjs | 视觉测试 | 静态推定：production bom v3 detail preview 1920 visual | node qa/production_bom_v3_detail_preview_1920_visual.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/production_bom_v3_lists_1920_visual.cjs | 视觉测试 | 静态推定：production bom v3 lists 1920 visual | node qa/production_bom_v3_lists_1920_visual.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/production_data_e2e.cjs | 业务流程测试 | 静态推定：production data e2e | node qa/production_data_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/production_loading_phase2_20260915/after-run/measure.cjs | 视觉测试 | 静态推定：after run / measure | node qa/production_loading_phase2_20260915/after-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/production_loading_phase2_20260915/archive_changes.cjs | 辅助/证据脚本 | 静态推定：production loading phase2 / archive changes | node qa/production_loading_phase2_20260915/archive_changes.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/production_loading_phase2_20260915/before-run/measure.cjs | 视觉测试 | 静态推定：before run / measure | node qa/production_loading_phase2_20260915/before-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/production_loading_phase2_20260915/prepare_measure.cjs | 数据初始化脚本 | 静态推定：production loading phase2 / prepare measure | node qa/production_loading_phase2_20260915/prepare_measure.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/production_loading_phase2_20260915/smoke.cjs | 业务流程测试 | 静态推定：production loading phase2 / smoke | node qa/production_loading_phase2_20260915/smoke.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/production_loading_phase2_20260915/summarize.cjs | 辅助/证据脚本 | 静态推定：production loading phase2 / summarize | node qa/production_loading_phase2_20260915/summarize.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/production_scheduling_batch_20260916/verify.cjs | 业务流程测试 | 静态推定：production scheduling batch / verify | node qa/production_scheduling_batch_20260916/verify.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/production_scheduling_business_e2e.cjs | 业务流程测试 | 静态推定：production scheduling business e2e | node qa/production_scheduling_business_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/production_scheduling_detail_20260916/verify.cjs | 业务流程测试 | 静态推定：production scheduling detail / verify | node qa/production_scheduling_detail_20260916/verify.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/production_scheduling_visual_1920.cjs | 视觉测试 | 静态推定：production scheduling visual 1920 | node qa/production_scheduling_visual_1920.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/production_scheduling_visual_compare.cjs | 视觉测试 | { box-sizing: border-box; } | node qa/production_scheduling_visual_compare.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/production_task_create_v3_1920_visual.cjs | 视觉测试 | 静态推定：production task create v3 1920 visual | node qa/production_task_create_v3_1920_visual.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/production_task_progress_columns_20260914/verify_live.cjs | 业务流程测试 | 静态推定：production task progress columns / verify live | node qa/production_task_progress_columns_20260914/verify_live.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/production_task_renumber_20260914/verify_live.cjs | 业务流程测试 | 静态推定：production task renumber / verify live | node qa/production_task_renumber_20260914/verify_live.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/production_task_sales_edit_1920_e2e.cjs | 视觉测试 | 静态推定：production task sales edit 1920 e2e | node qa/production_task_sales_edit_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/production_tasks_1920_e2e.cjs | 视觉测试 | 静态推定：production tasks 1920 e2e | node qa/production_tasks_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/public_stock_step4_20260928/browser_acceptance.cjs | 业务流程测试 | 静态推定：public stock step4 / browser acceptance | node qa/public_stock_step4_20260928/browser_acceptance.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/public_stock_step4_20260928/browser_readonly_recheck.cjs | 页面验收测试 | 仅轮询匿名 GET；后端就绪后才创建会话，不重试任何业务写入。 | node qa/public_stock_step4_20260928/browser_readonly_recheck.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/public_stock_step4_20260928/collect_implementation.cjs | 辅助/证据脚本 | 汇总本步独立源码差异和校验哈希，不修改任何源码。 | node qa/public_stock_step4_20260928/collect_implementation.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/public_stock_step4_20260928/verify_isolation.cjs | API测试辅助脚本 | 只读核对主源码和主业务表，写入本步骤的验收证据。 | node qa/public_stock_step4_20260928/verify_isolation.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step5_20260928/build_implementation_manifest.cjs | API测试辅助脚本 | 只比较本步独立代码和复制起点，不读取业务数据。 | node qa/public_stock_step5_20260928/build_implementation_manifest.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/public_stock_step5_20260928/inventory_browser_acceptance.cjs | 业务流程测试 | 仅准备于 QA 目录。必须由主任务明确批准后使用 --execute；其他模式不写业务数据。 | node qa/public_stock_step5_20260928/inventory_browser_acceptance.cjs；参数见脚本；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/public_stock_step5_20260928/outsourcing_browser_acceptance.cjs | 业务流程测试 | S5普通面料委外：仅通过隔离页面发料90米、回货60套并结清。 | node qa/public_stock_step5_20260928/outsourcing_browser_acceptance.cjs；参数见脚本；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/public_stock_step5_20260928/p4_browser_acceptance.cjs | 业务流程测试 | 仅允许S5独立环境；业务写操作全部通过页面，辅助命令只建专用会话或只读对账。 | node qa/public_stock_step5_20260928/p4_browser_acceptance.cjs；参数见脚本；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/public_stock_step5_20260928/summarize_backend_tests.cjs | API测试辅助脚本 | 静态推定：public stock step5 / summarize backend tests | node qa/public_stock_step5_20260928/summarize_backend_tests.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/public_stock_step5_20260928/verify_isolation.cjs | API测试辅助脚本 | 只读核对主源码和主业务表，写入本步骤的验收证据。 | node qa/public_stock_step5_20260928/verify_isolation.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/audit_activation_sources.cjs | 数据初始化脚本 | 只读采集候选源码与主源码摘要；新报告不覆盖既有证据，不访问数据库。 | node qa/public_stock_step6_20260928/audit_activation_sources.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/audit_cutover_sources.cjs | 数据初始化脚本 | 仅只读源码；结果仅写入本步骤 QA 目录，不修改主环境或数据库。 | node qa/public_stock_step6_20260928/audit_cutover_sources.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/audit_cutting_save_sources.cjs | API测试辅助脚本 | 只读冻结本轮裁片保存修复的源码；不连接数据库，不向主目录合入。 | node qa/public_stock_step6_20260928/audit_cutting_save_sources.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/audit_tooling_sources.cjs | API测试辅助脚本 | 只生成候选源码指纹；不复制源码，不修改主系统。 | node qa/public_stock_step6_20260928/audit_tooling_sources.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/backup_main_readonly.cjs | API测试辅助脚本 | 仅对已核实主实例进行一致性只读备份，不执行迁移或修改主业务数据。 | node qa/public_stock_step6_20260928/backup_main_readonly.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/backup_verify_tooling.cjs | API测试辅助脚本 | 仅为 tools 隔离库创建新备份并恢复到新验证库；默认输出计划，不连接数据库。 | node qa/public_stock_step6_20260928/backup_verify_tooling.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/public_stock_step6_20260928/business_trial_browser.cjs | 业务流程测试 | 静态推定：public stock step6 / business trial browser | node qa/public_stock_step6_20260928/business_trial_browser.cjs；参数见脚本 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/public_stock_step6_20260928/chain_browser_acceptance.cjs | 业务流程测试 | 静态推定：public stock step6 / chain browser acceptance | node qa/public_stock_step6_20260928/chain_browser_acceptance.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/public_stock_step6_20260928/finalize_activation_evidence.cjs | 数据初始化脚本 | 汇总本轮已经执行的证据；不连接数据库，不执行切换，不覆盖历史结果。 | node qa/public_stock_step6_20260928/finalize_activation_evidence.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/finalize_business_trial_cutover.cjs | 数据初始化脚本 | 只汇总已有文件并生成待确认清单；不连接数据库，不生成已确认授权。 | node qa/public_stock_step6_20260928/finalize_business_trial_cutover.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/finalize_cutting_save_result.cjs | 辅助/证据脚本 | 汇总已执行的检查；只读取源码和日志、更新 QA 证据与待办，不连接业务数据库。 | node qa/public_stock_step6_20260928/finalize_cutting_save_result.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/finalize_delegated_test_data.cjs | 辅助/证据脚本 | 只更新 QA 证据和任务待办，不连接业务数据库。 | node qa/public_stock_step6_20260928/finalize_delegated_test_data.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/prepare_activation_backup_rehearsal.cjs | 数据初始化脚本 | 默认只打印计划；根代理审核并另行传 --execute 后，才备份 tools 库并恢复至全新验证库。 | node qa/public_stock_step6_20260928/prepare_activation_backup_rehearsal.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/public_stock_step6_20260928/prepare_business_trial_activation_backup.cjs | 数据初始化脚本 | 默认只打印计划；根代理审核并另行传 --execute 后，才备份新业务演练副本并恢复至全新验证库。 | node qa/public_stock_step6_20260928/prepare_business_trial_activation_backup.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/public_stock_step6_20260928/prepare_business_trial_environment.cjs | 数据初始化脚本 | 创建新的完整业务演练副本；不覆盖现有库，不解除既有库维护状态。 | node qa/public_stock_step6_20260928/prepare_business_trial_environment.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/public_stock_step6_20260928/prepare_business_trial_opening_backup.cjs | 数据初始化脚本 | 默认只打印计划；根代理审核并另行传 --execute 后，才备份新业务演练副本并恢复至全新验证库。 | node qa/public_stock_step6_20260928/prepare_business_trial_opening_backup.cjs；参数见脚本 | 否 | 可能写入 | UNKNOWN |
| qa/public_stock_step6_20260928/prepare_supplemented_identity.cjs | 数据初始化脚本 | 保存本任务用户 A 确认的补充凭证；只读原候选，不访问数据库。 | node qa/public_stock_step6_20260928/prepare_supplemented_identity.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/render_bom_readiness_audit.cjs | API测试辅助脚本 | 从已完成的只读快照生成说明；不再连接数据库、不纳入新 QA BOM。 | node qa/public_stock_step6_20260928/render_bom_readiness_audit.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/restore_isolated_backup.cjs | 数据初始化脚本 | 静态推定：public stock step6 / restore isolated backup | node qa/public_stock_step6_20260928/restore_isolated_backup.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/public_stock_step6_20260928/restore_tooling_backup.cjs | 数据初始化脚本 | 默认只核对备份并输出计划；--execute 才恢复到固定、空的隔离库。 | node qa/public_stock_step6_20260928/restore_tooling_backup.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/public_stock_step6_20260928/summarize_business_trial.cjs | 辅助/证据脚本 | 汇总已完成的隔离业务操作证据；不调用数据库或改动产品源码。 | node qa/public_stock_step6_20260928/summarize_business_trial.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/public_stock_step6_20260928/summarize_supplemented_validation.cjs | 辅助/证据脚本 | 仅汇总已经生成的本轮证据，不连接数据库，不执行任何业务动作。 | node qa/public_stock_step6_20260928/summarize_supplemented_validation.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/public_stock_step6_20260928/supplemented_main_review.cjs | 辅助/证据脚本 | 固定主库只读采集；不复制源码、不改数据库、不调用隔离tools环境。 | node qa/public_stock_step6_20260928/supplemented_main_review.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/verify_main_source_unchanged.cjs | API测试辅助脚本 | 只读比较主源码；不依据包含历史改动的 Git 总差异判断本次变化。 | node qa/public_stock_step6_20260928/verify_main_source_unchanged.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/write_business_trial_public_result.cjs | 辅助/证据脚本 | 静态推定：public stock step6 / write business trial public result | node qa/public_stock_step6_20260928/write_business_trial_public_result.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/public_stock_step6_20260928/write_tooling_validation_summary.cjs | 辅助/证据脚本 | 静态推定：public stock step6 / write tooling validation summary | node qa/public_stock_step6_20260928/write_tooling_validation_summary.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/purchase_contract_template_design_20260916.cjs | 视觉测试 | 静态推定：purchase contract template design | node qa/purchase_contract_template_design_20260916.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_inbound_auto_complete_20260917.cjs | 业务流程测试 | 静态推定：purchase inbound auto complete | node qa/purchase_inbound_auto_complete_20260917.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_inbound_loading_20260916/after-run/measure.cjs | 视觉测试 | 静态推定：after run / measure | node qa/purchase_inbound_loading_20260916/after-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_inbound_loading_20260916/archive_changes.cjs | 辅助/证据脚本 | 静态推定：purchase inbound loading / archive changes | node qa/purchase_inbound_loading_20260916/archive_changes.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_inbound_loading_20260916/before-run/measure.cjs | 视觉测试 | 静态推定：before run / measure | node qa/purchase_inbound_loading_20260916/before-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_inbound_loading_20260916/prepare_equivalence.cjs | 数据初始化脚本 | 静态推定：purchase inbound loading / prepare equivalence | node qa/purchase_inbound_loading_20260916/prepare_equivalence.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_inbound_loading_20260916/prepare_measure.cjs | 数据初始化脚本 | 静态推定：purchase inbound loading / prepare measure | node qa/purchase_inbound_loading_20260916/prepare_measure.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_inbound_loading_20260916/smoke.cjs | 业务流程测试 | 表格有固定表头，自动滚动可能把首行的选择器移到表头下面。 | node qa/purchase_inbound_loading_20260916/smoke.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_inbound_loading_20260916/summarize.cjs | 辅助/证据脚本 | 静态推定：purchase inbound loading / summarize | node qa/purchase_inbound_loading_20260916/summarize.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_inbound_loading_20260916/write_report.cjs | 辅助/证据脚本 | 静态推定：purchase inbound loading / write report | node qa/purchase_inbound_loading_20260916/write_report.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/purchase_inbound_table_unified_20260916.cjs | 业务流程测试 | 静态推定：purchase inbound table unified | node qa/purchase_inbound_table_unified_20260916.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_layout_comments_20260914/build_acceptance/purchase_create_1920_e2e.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_layout_comments_20260914/build_acceptance/purchase_create_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_layout_comments_20260914/build_acceptance/source_tags.cjs | 视觉测试 | 静态推定：build acceptance / source tags | node qa/purchase_layout_comments_20260914/build_acceptance/source_tags.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_layout_comments_20260914/build_acceptance/template_compact_e2e.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_layout_comments_20260914/build_acceptance/template_compact_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_layout_comments_20260914/source_tags.cjs | 视觉测试 | 静态推定：purchase layout comments / source tags | node qa/purchase_layout_comments_20260914/source_tags.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_layout_comments_20260914/template_compact_e2e.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_layout_comments_20260914/template_compact_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_list_sources_20260914/list_sources_e2e.cjs | 业务流程测试 | 浏览器端夹具验收：所有 API 都被拦截，不连接业务数据；用户已授权本地 Chromium/Playwright 验收。 | node qa/purchase_list_sources_20260914/list_sources_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_order_confirm_layout_20260916.cjs | 视觉测试 | 静态推定：purchase order confirm layout | node qa/purchase_order_confirm_layout_20260916.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_order_detail_20260929/browser_check.cjs | 业务流程测试 | 静态推定：purchase order detail / browser check | node qa/purchase_order_detail_20260929/browser_check.cjs | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/purchase_order_details_density_20260916.cjs | 视觉测试 | 静态推定：purchase order details density | node qa/purchase_order_details_density_20260916.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_order_inbound_status_qa_20260917.cjs | 业务流程测试 | 静态推定：purchase order inbound status qa | node qa/purchase_order_inbound_status_qa_20260917.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_order_list_status_badge_20260916.cjs | 业务流程测试 | 静态推定：purchase order list status badge | node qa/purchase_order_list_status_badge_20260916.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/purchase_order_loading_20260916/after-run/measure.cjs | 视觉测试 | 静态推定：after run / measure | node qa/purchase_order_loading_20260916/after-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_order_loading_20260916/archive_changes.cjs | 辅助/证据脚本 | 静态推定：purchase order loading / archive changes | node qa/purchase_order_loading_20260916/archive_changes.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_order_loading_20260916/before-run/measure.cjs | 视觉测试 | 静态推定：before run / measure | node qa/purchase_order_loading_20260916/before-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_order_loading_20260916/prepare_equivalence.cjs | 数据初始化脚本 | 静态推定：purchase order loading / prepare equivalence | node qa/purchase_order_loading_20260916/prepare_equivalence.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_order_loading_20260916/prepare_measure.cjs | 数据初始化脚本 | 静态推定：purchase order loading / prepare measure | node qa/purchase_order_loading_20260916/prepare_measure.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_order_loading_20260916/smoke.cjs | 业务流程测试 | 静态推定：purchase order loading / smoke | node qa/purchase_order_loading_20260916/smoke.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_order_loading_20260916/summarize.cjs | 辅助/证据脚本 | 静态推定：purchase order loading / summarize | node qa/purchase_order_loading_20260916/summarize.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/purchase_order_table_fill_1920_e2e.cjs | 视觉测试 | 静态推定：purchase order table fill 1920 e2e | node qa/purchase_order_table_fill_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_orders_1920_e2e.cjs | 视觉测试 | 静态推定：purchase orders 1920 e2e | node qa/purchase_orders_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_orders_live_1920_e2e.cjs | 视觉测试 | 静态推定：purchase orders live 1920 e2e | node qa/purchase_orders_live_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_progress_inbound_20260914/browser.cjs | 业务流程测试 | 所有业务接口均由本脚本拦截；POST 只断言载荷，不写真实数据库。 | node qa/purchase_progress_inbound_20260914/browser.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_progress_inbound_20260914/list.cjs | 业务流程测试 | 浏览器端夹具验收：所有 API 都被拦截，不连接业务数据；用户已授权本地 Chromium/Playwright 验收。 | node qa/purchase_progress_inbound_20260914/list.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_progress_inbound_20260914/scroll.cjs | 视觉测试 | 所有业务接口均由本脚本拦截；POST 只断言载荷，不写真实数据库。 | node qa/purchase_progress_inbound_20260914/scroll.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_regression_20260912/purchase_complete_1920_e2e.cjs | 视觉测试 | 浏览器端夹具验收：所有 API 都被拦截，不连接业务数据；用户已授权本地 Chromium/Playwright 验收。 | node qa/purchase_regression_20260912/purchase_complete_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_regression_20260912/purchase_inbound_details_1920_e2e.cjs | 视觉测试 | 只读浏览器验收，所有 API 均模拟，禁止业务写入。 | node qa/purchase_regression_20260912/purchase_inbound_details_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_regression_20260912/purchase_list_1920_e2e.cjs | 视觉测试 | 浏览器端夹具验收：所有 API 都被拦截，不连接业务数据；用户已授权本地 Chromium/Playwright 验收。 | node qa/purchase_regression_20260912/purchase_list_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_regression_20260912/purchase_quality_1920_e2e.cjs | 视觉测试 | 浏览器模拟接口，仅验证请求，不写真实业务数据。 | node qa/purchase_regression_20260912/purchase_quality_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_regression_20260912/purchase_receiving_1920_e2e.cjs | 视觉测试 | 所有业务接口均由本脚本拦截；POST 只断言载荷，不写真实数据库。 | node qa/purchase_regression_20260912/purchase_receiving_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_regression_20260912/purchase_returns_1920_e2e.cjs | 视觉测试 | 所有业务 API 都被拦截；状态操作只改变本测试内存，不写入正式数据库。 | node qa/purchase_regression_20260912/purchase_returns_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_return_confirmation_flow_1920_e2e.cjs | 视觉测试 | 静态推定：purchase return confirmation flow 1920 e2e | node qa/purchase_return_confirmation_flow_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_return_design_20260916.cjs | 视觉测试 | 当前开发库记录可能已完成；只读改写首条 GET 响应用于核对“确认退货”弹窗，不触发业务写入。 | node qa/purchase_return_design_20260916.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_return_loading_20260916/after-run/measure.cjs | 视觉测试 | 静态推定：after run / measure | node qa/purchase_return_loading_20260916/after-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_return_loading_20260916/archive_changes.cjs | 辅助/证据脚本 | 静态推定：purchase return loading / archive changes | node qa/purchase_return_loading_20260916/archive_changes.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_return_loading_20260916/before-run/measure.cjs | 视觉测试 | 静态推定：before run / measure | node qa/purchase_return_loading_20260916/before-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_return_loading_20260916/edit_frontend.cjs | 辅助/证据脚本 | 静态推定：purchase return loading / edit frontend | node qa/purchase_return_loading_20260916/edit_frontend.cjs | 否 | 可能写入 | UNKNOWN |
| qa/purchase_return_loading_20260916/prepare.cjs | 数据初始化脚本 | 静态推定：purchase return loading / prepare | node qa/purchase_return_loading_20260916/prepare.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_return_loading_20260916/prepare_equivalence.cjs | 数据初始化脚本 | 静态推定：purchase return loading / prepare equivalence | node qa/purchase_return_loading_20260916/prepare_equivalence.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_return_loading_20260916/smoke.cjs | 业务流程测试 | 静态推定：purchase return loading / smoke | node qa/purchase_return_loading_20260916/smoke.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_return_loading_20260916/summarize.cjs | 辅助/证据脚本 | 静态推定：purchase return loading / summarize | node qa/purchase_return_loading_20260916/summarize.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_return_loading_20260916/write_report.cjs | 辅助/证据脚本 | 静态推定：purchase return loading / write report | node qa/purchase_return_loading_20260916/write_report.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/purchase_scroll_audit_20260914/audit.cjs | 视觉测试 | 本地实际页面只读巡检；仅登录建立会话，登录后禁止业务写请求。 | node qa/purchase_scroll_audit_20260914/audit.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/purchase_scroll_audit_20260914/quality.cjs | 视觉测试 | 浏览器模拟接口，仅验证请求，不写真实业务数据。 | node qa/purchase_scroll_audit_20260914/quality.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_sheet_entry_live_1920_e2e.cjs | 视觉测试 | 静态推定：purchase sheet entry live 1920 e2e | node qa/purchase_sheet_entry_live_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_sheet_flow_1920_e2e.cjs | 视觉测试 | 静态推定：purchase sheet flow 1920 e2e | node qa/purchase_sheet_flow_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_sources_20260914/production_regression.cjs | 业务流程测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_sources_20260914/production_regression.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_sources_20260914/sample_editor_e2e.cjs | 业务流程测试 | 拦截全部API；写入、附件与下载使用测试夹具，不写真实数据库。 | node qa/purchase_sources_20260914/sample_editor_e2e.cjs；参数见脚本 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_sources_20260914/source_form_e2e.cjs | 业务流程测试 | 静态推定：purchase sources / source form e2e | node qa/purchase_sources_20260914/source_form_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_template_drawer_compact_20260916.cjs | 视觉测试 | 静态推定：purchase template drawer compact | node qa/purchase_template_drawer_compact_20260916.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/capture_purchase_inbound_details_reference.cjs | 视觉测试 | 下一页只读参考，拦截所有接口，不写业务库。 | node qa/purchase_update_20260910/capture_purchase_inbound_details_reference.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/capture_purchase_quality_reference.cjs | 视觉测试 | 品质确认下一页设计参考；只读模拟接口，不确认真实质检。 | node qa/purchase_update_20260910/capture_purchase_quality_reference.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/capture_purchase_receiving_implemented.cjs | 视觉测试 | 下一页设计参考截图：只读模拟接口，不提交收货。 | node qa/purchase_update_20260910/capture_purchase_receiving_implemented.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/capture_purchase_receiving_reference.cjs | 视觉测试 | 下一页设计参考截图：只读模拟接口，不提交收货。 | node qa/purchase_update_20260910/capture_purchase_receiving_reference.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_complete_1920_e2e.cjs | 视觉测试 | 浏览器端夹具验收：所有 API 都被拦截，不连接业务数据；用户已授权本地 Chromium/Playwright 验收。 | node qa/purchase_update_20260910/purchase_complete_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_confirm_1920_e2e.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/purchase_confirm_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_create_1920_e2e.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/purchase_create_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_editor_1920_e2e.cjs | 视觉测试 | 拦截全部API；写入、附件与下载使用测试夹具，不写真实数据库。 | node qa/purchase_update_20260910/purchase_editor_1920_e2e.cjs；参数见脚本 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_inbound_details_1920_e2e.cjs | 视觉测试 | 只读浏览器验收，所有 API 均模拟，禁止业务写入。 | node qa/purchase_update_20260910/purchase_inbound_details_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_list_1920_e2e.cjs | 视觉测试 | 浏览器端夹具验收：所有 API 都被拦截，不连接业务数据；用户已授权本地 Chromium/Playwright 验收。 | node qa/purchase_update_20260910/purchase_list_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_pdf_preview_1920_e2e.cjs | 视觉测试 | 全部 API 拦截；PDF 为本项目真实生成器生成的独立测试文件。不会写业务数据库。 | node qa/purchase_update_20260910/purchase_pdf_preview_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_publish_confirm_1920_e2e.cjs | 视觉测试 | 浏览器接口全部拦截，仅验证模拟采购表，不写真实业务数据。 | node qa/purchase_update_20260910/purchase_publish_confirm_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_published_view_1920_e2e.cjs | 视觉测试 | 全部业务 API 拦截；真实 PDF 测试文件，不写业务数据库。 | node qa/purchase_update_20260910/purchase_published_view_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_quality_1920_e2e.cjs | 视觉测试 | 浏览器模拟接口，仅验证请求，不写真实业务数据。 | node qa/purchase_update_20260910/purchase_quality_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_receiving_1920_e2e.cjs | 视觉测试 | 所有业务接口均由本脚本拦截；POST 只断言载荷，不写真实数据库。 | node qa/purchase_update_20260910/purchase_receiving_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_returns_1920_e2e.cjs | 视觉测试 | 所有业务 API 都被拦截；状态操作只改变本测试内存，不写入正式数据库。 | node qa/purchase_update_20260910/purchase_returns_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_template_1920_e2e.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/purchase_template_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/purchase_workbench_1920_e2e.cjs | 视觉测试 | 本脚本拦截全部业务API，发布、生成和下载均为模拟响应，不写业务数据库。 | node qa/purchase_update_20260910/purchase_workbench_1920_e2e.cjs | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/supplier_create_before_capture.cjs | 视觉测试 | 只读视觉采集，接口全部使用内存示例，禁止真实业务写入。 | node qa/purchase_update_20260910/supplier_create_before_capture.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/supplier_create_drawer_1920_e2e.cjs | 视觉测试 | 全部接口使用内存夹具，POST仅在拦截器内模拟，禁止真实业务写入。 | node qa/purchase_update_20260910/supplier_create_drawer_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/supplier_create_drawer_capture.cjs | 视觉测试 | 只读视觉采集，接口全部使用内存示例，禁止真实业务写入。 | node qa/purchase_update_20260910/supplier_create_drawer_capture.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/supplier_drawer_isolated_preview.cjs | 辅助/证据脚本 | 仅用于采购专项验收：缺失的销售详情模块替换为明确报错占位；不修改应用源码，不验收销售页面。 | node qa/purchase_update_20260910/supplier_drawer_isolated_preview.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/purchase_update_20260910/supplier_edit_before_capture.cjs | 视觉测试 | 只读视觉采集，接口全部使用内存示例，禁止真实业务写入。 | node qa/purchase_update_20260910/supplier_edit_before_capture.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/supplier_edit_drawer_1920_e2e.cjs | 视觉测试 | 所有 API 均在浏览器内拦截；写请求只模拟，禁止写入真实业务数据。 | node qa/purchase_update_20260910/supplier_edit_drawer_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/supplier_edit_drawer_capture.cjs | 视觉测试 | 所有 API 均在浏览器内拦截；写请求只模拟，禁止写入真实业务数据。 | node qa/purchase_update_20260910/supplier_edit_drawer_capture.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/supplier_list_before_capture.cjs | 视觉测试 | 只读视觉采集，接口全部使用内存示例，禁止真实业务写入。 | node qa/purchase_update_20260910/supplier_list_before_capture.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/supplier_list_current_capture.cjs | 视觉测试 | 只读视觉采集，接口全部使用内存示例，禁止真实业务写入。 | node qa/purchase_update_20260910/supplier_list_current_capture.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/supplier_management_1920_e2e.cjs | 视觉测试 | 全部业务接口使用内存夹具，禁止真实写入。从采购订单入口进入供应商管理。 | node qa/purchase_update_20260910/supplier_management_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_create_1920_e2e.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_create_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_create_before_capture.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_create_before_capture.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_create_capture.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_create_capture.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_create_font_capture.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_create_font_capture.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_edit_1920_e2e.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_edit_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_edit_before_capture.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_edit_before_capture.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_history_1920_e2e.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_history_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_history_before_capture.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_history_before_capture.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_management_1920_e2e.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_management_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_management_after_edit_e2e.cjs | 业务流程测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_management_after_edit_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_management_after_history_e2e.cjs | 业务流程测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_management_after_history_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_management_before_capture.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_management_before_capture.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_management_capture.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_management_capture.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/purchase_update_20260910/template_management_font_check.cjs | 视觉测试 | 全部业务请求通过本地测试拦截器处理，不写真实业务数据库。 | node qa/purchase_update_20260910/template_management_font_check.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/quality_loading_20260916/after-run/measure.cjs | 视觉测试 | 静态推定：after run / measure | node qa/quality_loading_20260916/after-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/quality_loading_20260916/archive_changes.cjs | 辅助/证据脚本 | 静态推定：quality loading / archive changes | node qa/quality_loading_20260916/archive_changes.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/quality_loading_20260916/before-run/measure.cjs | 视觉测试 | 静态推定：before run / measure | node qa/quality_loading_20260916/before-run/measure.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/quality_loading_20260916/prepare.cjs | 数据初始化脚本 | 静态推定：quality loading / prepare | node qa/quality_loading_20260916/prepare.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/quality_loading_20260916/prepare_equivalence.cjs | 数据初始化脚本 | 静态推定：quality loading / prepare equivalence | node qa/quality_loading_20260916/prepare_equivalence.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/quality_loading_20260916/prepare_measure.cjs | 数据初始化脚本 | 静态推定：quality loading / prepare measure | node qa/quality_loading_20260916/prepare_measure.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/quality_loading_20260916/smoke.cjs | 页面验收测试 | 静态推定：quality loading / smoke | node qa/quality_loading_20260916/smoke.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/quality_loading_20260916/summarize.cjs | 辅助/证据脚本 | 静态推定：quality loading / summarize | node qa/quality_loading_20260916/summarize.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/quo01_list_e2e.cjs | 业务流程测试 | 静态推定：quo01 list e2e | node qa/quo01_list_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quo02_editor_e2e.cjs | 业务流程测试 | 静态推定：quo02 editor e2e | node qa/quo02_editor_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quo03_packaging_e2e.cjs | 业务流程测试 | 静态推定：quo03 packaging e2e | node qa/quo03_packaging_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quo04_preview_e2e.cjs | 业务流程测试 | 静态推定：quo04 preview e2e | node qa/quo04_preview_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quo05_versions_e2e.cjs | 业务流程测试 | 静态推定：quo05 versions e2e | node qa/quo05_versions_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quo06_price_history_e2e.cjs | 业务流程测试 | 静态推定：quo06 price history e2e | node qa/quo06_price_history_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quotation_comments_20260914_e2e.cjs | 业务流程测试 | 静态推定：quotation comments e2e | node qa/quotation_comments_20260914_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quotation_create_dialog_e2e.cjs | 业务流程测试 | 静态推定：quotation create dialog e2e | node qa/quotation_create_dialog_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/quotation_downstream_mapping_20260914_e2e.cjs | 业务流程测试 | 静态推定：quotation downstream mapping e2e | node qa/quotation_downstream_mapping_20260914_e2e.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/quotation_f01_f06_1920_e2e.cjs | 视觉测试 | 静态推定：quotation f01 f06 1920 e2e | node qa/quotation_f01_f06_1920_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quotation_f01_f06_state_screenshots.cjs | 视觉测试 | 静态推定：quotation f01 f06 state screenshots | node qa/quotation_f01_f06_state_screenshots.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quotation_flow_confirmed_1920_e2e.cjs | 视觉测试 | 静态推定：quotation flow confirmed 1920 e2e | node qa/quotation_flow_confirmed_1920_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quotation_prototype_alignment_1920_e2e.cjs | 视觉测试 | 静态推定：quotation prototype alignment 1920 e2e | node qa/quotation_prototype_alignment_1920_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quotation_sample_image_mapping_20260914_e2e.cjs | 业务流程测试 | 静态推定：quotation sample image mapping e2e | node qa/quotation_sample_image_mapping_20260914_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/quotation_service_recovery_20260914.cjs | 业务流程测试 | 静态推定：quotation service recovery | node qa/quotation_service_recovery_20260914.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quote_draft_ellipsis_probe_20260924.cjs | 页面验收测试 | 静态推定：quote draft ellipsis probe | node qa/quote_draft_ellipsis_probe_20260924.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/quote_packaging_action_fit_probe_20260924.cjs | 页面验收测试 | 静态推定：quote packaging action fit probe | node qa/quote_packaging_action_fit_probe_20260924.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/raw_material_information_e2e.cjs | 业务流程测试 | 静态推定：raw material information e2e | node qa/raw_material_information_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/raw_material_information_live_e2e.cjs | 业务流程测试 | 静态推定：raw material information live e2e | node qa/raw_material_information_live_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/receipt_reporting_20260929/edit_ui.cjs | 辅助/证据脚本 | 静态推定：receipt reporting / edit ui | node qa/receipt_reporting_20260929/edit_ui.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/receipt_reporting_20260929/finalize_manifest.cjs | API测试辅助脚本 | 本任务没有改过的旧副本不能成为发布目标，避免覆盖并行任务的新版本。 | node qa/receipt_reporting_20260929/finalize_manifest.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/receipt_reporting_20260929/manage.cjs | 辅助/证据脚本 | 静态推定：receipt reporting / manage | node qa/receipt_reporting_20260929/manage.cjs；参数见脚本 | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/receipt_reporting_20260929/prepare.cjs | 数据初始化脚本 | 静态推定：receipt reporting / prepare | node qa/receipt_reporting_20260929/prepare.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/receipt_reporting_20260929/start_frontend.cjs | 辅助/证据脚本 | 静态推定：receipt reporting / start frontend | node qa/receipt_reporting_20260929/start_frontend.cjs；需环境变量 | 否 | UNKNOWN | UNKNOWN |
| qa/receipt_reporting_20260929/start_preview.cjs | 辅助/证据脚本 | 静态推定：receipt reporting / start preview | node qa/receipt_reporting_20260929/start_preview.cjs | 否 | 可能写入 | 是（账号/Session/环境变量） |
| qa/receipt_reporting_20260929/verify_browser.cjs | 业务流程测试 | 静态推定：receipt reporting / verify browser | node qa/receipt_reporting_20260929/verify_browser.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/representative_scroll_audit_20261008.cjs | 视觉测试 | 静态推定：representative scroll audit | node qa/representative_scroll_audit_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/route_scroll_scan_20260924.cjs | 视觉测试 | 静态推定：route scroll scan | node qa/route_scroll_scan_20260924.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sales_order_address_batch_1920_e2e.cjs | 视觉测试 | 静态推定：sales order address batch 1920 e2e | node qa/sales_order_address_batch_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/sales_order_editor_1920_e2e.cjs | 视觉测试 | 静态推定：sales order editor 1920 e2e | node qa/sales_order_editor_1920_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sales_order_prototype_1920_readonly.cjs | 视觉测试 | 静态推定：sales order prototype 1920 readonly | node qa/sales_order_prototype_1920_readonly.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sales_order_seed_20260914/verify_sales_orders_live.cjs | 业务流程测试 | 静态推定：sales order seed / verify sales orders live | node qa/sales_order_seed_20260914/verify_sales_orders_live.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sam03_fee_e2e.cjs | 业务流程测试 | 静态推定：sam03 fee e2e | node qa/sam03_fee_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/sam08_independent_form_e2e.cjs | 业务流程测试 | 静态推定：sam08 independent form e2e | node qa/sam08_independent_form_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sam09_inventory_first_page_1920_e2e.cjs | 视觉测试 | 静态推定：sam09 inventory first page 1920 e2e | node qa/sam09_inventory_first_page_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/sam09_loan_third_page_1920_e2e.cjs | 视觉测试 | 静态推定：sam09 loan third page 1920 e2e | node qa/sam09_loan_third_page_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/sam09_outbound_second_page_1920_e2e.cjs | 视觉测试 | 静态推定：sam09 outbound second page 1920 e2e | node qa/sam09_outbound_second_page_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/sam09_two_stage_1920_e2e.cjs | 视觉测试 | 静态推定：sam09 two stage 1920 e2e | node qa/sam09_two_stage_1920_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sam10_production_workflow_1920_e2e.cjs | 视觉测试 | 静态推定：sam10 production workflow 1920 e2e | node qa/sam10_production_workflow_1920_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sam10a_inventory_receipt_dialog_1920_e2e.cjs | 视觉测试 | 静态推定：sam10a inventory receipt dialog 1920 e2e | node qa/sam10a_inventory_receipt_dialog_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sam10b_outbound_create_dialog_1920_e2e.cjs | 视觉测试 | 静态推定：sam10b outbound create dialog 1920 e2e | node qa/sam10b_outbound_create_dialog_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sam10c_loan_create_dialog_1920_e2e.cjs | 视觉测试 | 静态推定：sam10c loan create dialog 1920 e2e | node qa/sam10c_loan_create_dialog_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sam11_sampling_details_1920_e2e.cjs | 视觉测试 | 静态推定：sam11 sampling details 1920 e2e | node qa/sam11_sampling_details_1920_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sam11a_inventory_receipt_detail_1920_e2e.cjs | 视觉测试 | 静态推定：sam11a inventory receipt detail 1920 e2e | node qa/sam11a_inventory_receipt_detail_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/sam11b_outbound_detail_1920_e2e.cjs | 视觉测试 | 静态推定：sam11b outbound detail 1920 e2e | node qa/sam11b_outbound_detail_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/sam11c_loan_detail_1920_e2e.cjs | 视觉测试 | 静态推定：sam11c loan detail 1920 e2e | node qa/sam11c_loan_detail_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/sam12_sample_list_fields_1920_e2e.cjs | 视觉测试 | 静态推定：sam12 sample list fields 1920 e2e | node qa/sam12_sample_list_fields_1920_e2e.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_application_flow.cjs | 业务流程测试 | 使用相同前端代码，所有 API 都转发到真实的隔离 Django 服务；不模拟接口响应。 | node qa/sample_application_flow.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_completion_figma_20260918.cjs | 视觉测试 | 静态推定：sample completion figma | node qa/sample_completion_figma_20260918.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/sample_detail_figma_readonly_20260911.cjs | 视觉测试 | 只读查找现有主流程记录，再从实际列表的搜索和查看入口进入。 | node qa/sample_detail_figma_readonly_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_edit_figma_readonly_20260911.cjs | 视觉测试 | 从真实列表进入编辑页；只读取接口，不保存或更改业务记录。 | node qa/sample_edit_figma_readonly_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_edit_write_flow_20260911.cjs | 业务流程测试 | 旧完善、编辑、报工与参数交接，固定使用独立18001服务。 | node qa/sample_edit_write_flow_20260911.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_fee_figma_readonly_20260911.cjs | 视觉测试 | 从真实列表进入同一记录费用页，只读业务 API。 | node qa/sample_fee_figma_readonly_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_fee_write_flow_20260911.cjs | 业务流程测试 | 费用真实写流程仅访问18001隔离服务，不模拟业务响应。 | node qa/sample_fee_write_flow_20260911.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_fulfillment_figma_readonly_20260911.cjs | 视觉测试 | 从真实列表进入同一记录费用页，只读业务 API。 | node qa/sample_fulfillment_figma_readonly_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_fulfillment_write_flow_20260911.cjs | 业务流程测试 | 在费用QA生成的免费样上验证真实物流链路；所有接口固定转发到隔离18001。 | node qa/sample_fulfillment_write_flow_20260911.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_inventory_figma_readonly_20260911.cjs | 视觉测试 | 静态推定：sample inventory figma readonly | node qa/sample_inventory_figma_readonly_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_inventory_write_flow_20260911.cjs | 业务流程测试 | 仅转发至专用18001隔离Django；真实Session/CSRF与业务接口，不模拟接口返回。 | node qa/sample_inventory_write_flow_20260911.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_list_alignment_readonly.cjs | 视觉测试 | 通过真实导航进入。除现有开发登录外，只执行 GET 查询，不修改业务数据。 | node qa/sample_list_alignment_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_loan_detail_figma_20260911.cjs | 视觉测试 | 真实入口、真实详情读取；异常夹具仅作用于浏览器，禁止所有业务 API 写入。 | node qa/sample_loan_detail_figma_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_loan_dialog_figma_20260911.cjs | 视觉测试 | 从真实样品借出入口读取；错误和输入状态使用浏览器夹具，所有业务写请求均拦截。 | node qa/sample_loan_dialog_figma_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_loan_figma_readonly_20260911.cjs | 视觉测试 | 静态推定：sample loan figma readonly | node qa/sample_loan_figma_readonly_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_material_bom_interaction.cjs | 业务流程测试 | 使用相同前端代码，所有 API 都转发到真实的隔离 Django 服务；不模拟接口响应。 | node qa/sample_material_bom_interaction.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_material_choices_images.cjs | 业务流程测试 | 全部接口转发到真实隔离服务，不模拟响应，也不写正式业务库。 | node qa/sample_material_choices_images.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_material_choices_readonly_20260911.cjs | 业务流程测试 | 只读复核真实接口与页面；填写停留在浏览器，不保存业务数据。 | node qa/sample_material_choices_readonly_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_material_flow.cjs | 业务流程测试 | 使用相同前端代码，所有 API 都转发到真实的隔离 Django 服务；不模拟接口响应。 | node qa/sample_material_flow.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_material_live_readonly.cjs | 业务流程测试 | 静态推定：sample material live readonly | node qa/sample_material_live_readonly.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/sample_operation_dialog_interaction_e2e.cjs | 业务流程测试 | 静态推定：sample operation dialog interaction e2e | node qa/sample_operation_dialog_interaction_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/sample_outbound_detail_figma_20260911.cjs | 视觉测试 | 真实入口、真实详情读取；异常夹具仅作用于浏览器，禁止所有业务 API 写入。 | node qa/sample_outbound_detail_figma_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_outbound_dialog_figma_20260911.cjs | 视觉测试 | 从真实样品出库入口读取；错误和输入状态使用浏览器夹具，所有业务写请求均拦截。 | node qa/sample_outbound_dialog_figma_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_outbound_figma_readonly_20260911.cjs | 视觉测试 | 静态推定：sample outbound figma readonly | node qa/sample_outbound_figma_readonly_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_procurement_status_1920.cjs | 视觉测试 | 静态推定：sample procurement status 1920 | node qa/sample_procurement_status_1920.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/sample_product_dropdown.cjs | 页面验收测试 | 静态推定：sample product dropdown | node qa/sample_product_dropdown.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/sample_production_connected_1920.cjs | 视觉测试 | 所有业务写操作仅转发到 18002 的打样专用隔离数据库；不模拟业务接口。 | node qa/sample_production_connected_1920.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_production_readonly_1920.cjs | 视觉测试 | 所有业务写操作仅转发到 18002 的打样专用隔离数据库；不模拟业务接口。 | node qa/sample_production_readonly_1920.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_qa_built_app.cjs | 辅助/证据脚本 | 可选：用刚构建的真实前端产物固定浏览器验收版本；API 和媒体继续访问原服务。 | node qa/sample_qa_built_app.cjs；需环境变量 | 否 | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_receipt_detail_figma_20260911.cjs | 视觉测试 | 真实入口、真实详情读取；异常夹具仅作用于浏览器，禁止所有业务 API 写入。 | node qa/sample_receipt_detail_figma_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_receipt_dialog_figma_20260911.cjs | 视觉测试 | 真实读取与独立浏览器状态夹具；所有业务写请求均拦截，不保存入库数据。 | node qa/sample_receipt_dialog_figma_20260911.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_requotation_write_flow_20260911.cjs | 业务流程测试 | 正常入口验证反馈再报价两种分支，所有业务请求转发到专用隔离 API。 | node qa/sample_requotation_write_flow_20260911.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/sample_v3_create_readonly.cjs | 页面验收测试 | 模拟应用内同名路由参数更新，保留真实 Router 和页面容器的重建行为。 | node qa/sample_v3_create_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_v3_detail_isolated_readonly.cjs | 页面验收测试 | 应用其他模块暂时编译失败时的补充检查：挂载真实打样组件、布局和 API。 | node qa/sample_v3_detail_isolated_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_v3_detail_readonly.cjs | 页面验收测试 | 从真实列表进入详情，仅调用 GET；审核写入由组件测试覆盖。 | node qa/sample_v3_detail_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_v3_director_readonly.cjs | 页面验收测试 | 旧记录没有厂长阶段，列表不会冒充提供其状态动作；使用真实 ID 检查新路由只读展示。 | node qa/sample_v3_director_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_v3_edit_readonly.cjs | 页面验收测试 | 只读验收：读取真实申请与编辑页，不提交、创建或修改业务数据。 | node qa/sample_v3_edit_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_v3_final_readonly_20260911.cjs | 页面验收测试 | 最新构建的 V3 七画板只读桌面回归，同时验证客户详情创建入口。 | node qa/sample_v3_final_readonly_20260911.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_v3_list_readonly.cjs | 页面验收测试 | 通过真实导航进入。除现有开发登录外，只执行 GET 查询，不修改业务数据。 | node qa/sample_v3_list_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_v3_materials_readonly.cjs | 业务流程测试 | 旧流程没有材料阶段动作。真实 ID 仅用于读取信息；填写数据仅在浏览器内，不写入数据库。 | node qa/sample_v3_materials_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_v3_shell_readonly.cjs | 页面验收测试 | 未纳入本次 V3 基准的既有页面仍使用原布局分支。 | node qa/sample_v3_shell_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sample_v3_warehouse_readonly.cjs | 页面验收测试 | 独立组件场景：仅测试本地录入/计算/视觉，未替换任何真实 API 响应。 | node qa/sample_v3_warehouse_readonly.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/schedule_finished_progress_20260929/browser_check.cjs | 业务流程测试 | 静态推定：schedule finished progress / browser check | node qa/schedule_finished_progress_20260929/browser_check.cjs | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/screenshot_complaint_after_fix_1201.cjs | 视觉测试 | 静态推定：screenshot complaint after fix 1201 | node qa/screenshot_complaint_after_fix_1201.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/screenshot_complaint_after_fix_20261008.cjs | 视觉测试 | 静态推定：screenshot complaint after fix | node qa/screenshot_complaint_after_fix_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/scroll_audit_ids_20261008.cjs | 视觉测试 | 静态推定：scroll audit ids | node qa/scroll_audit_ids_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/scroll_shell_check_20260924.cjs | 视觉测试 | 静态推定：scroll shell check | node qa/scroll_shell_check_20260924.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/short_ellipsis_dynamic_crm_20260924.cjs | 页面验收测试 | 静态推定：short ellipsis dynamic crm | node qa/short_ellipsis_dynamic_crm_20260924.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/short_ellipsis_scan_crm_20260924.cjs | 页面验收测试 | 静态推定：short ellipsis scan crm | node qa/short_ellipsis_scan_crm_20260924.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sidebar_customer_group_e2e.cjs | 业务流程测试 | 静态推定：sidebar customer group e2e | node qa/sidebar_customer_group_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/sidebar_hidden_scrollbar_20260930/browser_check.cjs | 视觉测试 | 只在验收浏览器缩短滚动区域，验证内容超出时的真实鼠标滚轮行为。 | node qa/sidebar_hidden_scrollbar_20260930/browser_check.cjs | 是（headless） | 否（只读/拦截） | 否（模拟认证/夹具） |
| qa/sidebar_settings_below_warehouse_20260930/browser_check.cjs | 页面验收测试 | 静态推定：sidebar settings below warehouse / browser check | node qa/sidebar_settings_below_warehouse_20260930/browser_check.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/sidebar_unify_1920.cjs | 视觉测试 | 静态推定：sidebar unify 1920 | node qa/sidebar_unify_1920.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/step01_login_e2e.cjs | 业务流程测试 | 静态推定：step01 login e2e | node qa/step01_login_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/step02_layout_e2e.cjs | 视觉测试 | 静态推定：step02 layout e2e | node qa/step02_layout_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/step03_sidebar_e2e.cjs | 业务流程测试 | 静态推定：step03 sidebar e2e | node qa/step03_sidebar_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/step04_header_e2e.cjs | 业务流程测试 | 静态推定：step04 header e2e | node qa/step04_header_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/step05_routing_e2e.cjs | 业务流程测试 | 静态推定：step05 routing e2e | node qa/step05_routing_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/step06_auth_permission_logout_e2e.cjs | 业务流程测试 | 静态推定：step06 auth permission logout e2e | node qa/step06_auth_permission_logout_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/supplier_design_density_20260916.cjs | 视觉测试 | 静态推定：supplier design density | node qa/supplier_design_density_20260916.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/supplier_module_1920_e2e.cjs | 视觉测试 | 静态推定：supplier module 1920 e2e | node qa/supplier_module_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/supplier_purchase_sheet_editor_layout_20260916.cjs | 视觉测试 | 静态推定：supplier purchase sheet editor layout | node qa/supplier_purchase_sheet_editor_layout_20260916.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/supplier_purchase_sheets_batch_publish_dialog_qa_20260917.cjs | 业务流程测试 | 静态推定：supplier purchase sheets batch publish dialog qa | node qa/supplier_purchase_sheets_batch_publish_dialog_qa_20260917.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/supplier_purchase_sheets_design_qa_20260917.cjs | 视觉测试 | 静态推定：supplier purchase sheets design qa | node qa/supplier_purchase_sheets_design_qa_20260917.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/system_settings_density_1920_e2e.cjs | 视觉测试 | 静态推定：system settings density 1920 e2e | node qa/system_settings_density_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/targeted_scroll_audit_20261008.cjs | 视觉测试 | 静态推定：targeted scroll audit | node qa/targeted_scroll_audit_20261008.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/task_center_e2e.cjs | 业务流程测试 | 静态推定：task center e2e | node qa/task_center_e2e.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/tube_revision_d1_20260929/final_scope.cjs | API测试辅助脚本 | 主源码若被并行任务改动，记录具体差异，不回滚或覆盖。 | node qa/tube_revision_d1_20260929/final_scope.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d1_20260929/preflight.cjs | 页面验收测试 | 静态推定：tube revision d1 / preflight | node qa/tube_revision_d1_20260929/preflight.cjs | 是（调用浏览器，模式UNKNOWN） | 可能写入 | 是（账号/Session/环境变量） |
| qa/tube_revision_d1_20260929/prepare.cjs | 数据初始化脚本 | 静态推定：tube revision d1 / prepare | node qa/tube_revision_d1_20260929/prepare.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d1_20260929/verify_browser.cjs | 页面验收测试 | 静态推定：tube revision d1 / verify browser | node qa/tube_revision_d1_20260929/verify_browser.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d1_20260929/verify_gallery.cjs | 视觉测试 | 静态推定：tube revision d1 / verify gallery | node qa/tube_revision_d1_20260929/verify_gallery.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_d1_20260929/verify_stock.cjs | API测试辅助脚本 | 静态推定：tube revision d1 / verify stock | node qa/tube_revision_d1_20260929/verify_stock.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d1_design_20260929/freeze-review.cjs | 辅助/证据脚本 | 静态推定：tube revision d1 design / freeze review | node qa/tube_revision_d1_design_20260929/freeze-review.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d1_design_20260929/inspect.cjs | 视觉测试 | 静态推定：tube revision d1 design / inspect | node qa/tube_revision_d1_design_20260929/inspect.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d1_design_20260929/verify.cjs | 视觉测试 | 静态推定：tube revision d1 design / verify | node qa/tube_revision_d1_design_20260929/verify.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d3_20260930/build_gallery.cjs | 辅助/证据脚本 | 静态推定：tube revision d3 / build gallery | node qa/tube_revision_d3_20260930/build_gallery.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d3_20260930/check_scope.cjs | API测试辅助脚本 | 静态推定：tube revision d3 / check scope | node qa/tube_revision_d3_20260930/check_scope.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d3_20260930/prepare.cjs | 数据初始化脚本 | 静态推定：tube revision d3 / prepare | node qa/tube_revision_d3_20260930/prepare.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d3_20260930/verify_browser.cjs | 页面验收测试 | 先拍仓库选单，随后三张已发原单会各办理一次并从候选消失。 | node qa/tube_revision_d3_20260930/verify_browser.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d3_20260930/verify_delivery.cjs | 页面验收测试 | 静态推定：tube revision d3 / verify delivery | node qa/tube_revision_d3_20260930/verify_delivery.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_d3_20260930/verify_edges.cjs | 页面验收测试 | 静态推定：tube revision d3 / verify edges | node qa/tube_revision_d3_20260930/verify_edges.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d3_20260930/verify_inventory.cjs | API测试辅助脚本 | 静态推定：tube revision d3 / verify inventory | node qa/tube_revision_d3_20260930/verify_inventory.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d3_20260930/verify_layout_after.cjs | 视觉测试 | 静态推定：tube revision d3 / verify layout after | node qa/tube_revision_d3_20260930/verify_layout_after.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d3_design_20260930/check_scope.cjs | API测试辅助脚本 | 静态推定：tube revision d3 design / check scope | node qa/tube_revision_d3_design_20260930/check_scope.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d3_design_20260930/prepare.cjs | 数据初始化脚本 | 静态推定：tube revision d3 design / prepare | node qa/tube_revision_d3_design_20260930/prepare.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d3_design_20260930/publish.cjs | 辅助/证据脚本 | 静态推定：tube revision d3 design / publish | node qa/tube_revision_d3_design_20260930/publish.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d3_design_20260930/verify.cjs | 视觉测试 | 静态推定：tube revision d3 design / verify | node qa/tube_revision_d3_design_20260930/verify.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d3_design_20260930/verify_gallery.cjs | 视觉测试 | 静态推定：tube revision d3 design / verify gallery | node qa/tube_revision_d3_design_20260930/verify_gallery.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_20260930/build_gallery.cjs | 辅助/证据脚本 | 静态推定：tube revision d4 / build gallery | node qa/tube_revision_d4_20260930/build_gallery.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d4_20260930/check_final_scope.cjs | API测试辅助脚本 | 静态推定：tube revision d4 / check final scope | node qa/tube_revision_d4_20260930/check_final_scope.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d4_20260930/freeze_approval.cjs | 辅助/证据脚本 | 静态推定：tube revision d4 / freeze approval | node qa/tube_revision_d4_20260930/freeze_approval.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d4_20260930/verify_browser.cjs | 页面验收测试 | 登录会轮换CSRF；后续接口请求使用当前会话值，不复用登录前令牌。 | node qa/tube_revision_d4_20260930/verify_browser.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d4_20260930/verify_delivery.cjs | 页面验收测试 | 静态推定：tube revision d4 / verify delivery | node qa/tube_revision_d4_20260930/verify_delivery.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_d4_20260930/verify_edges.cjs | 页面验收测试 | 静态推定：tube revision d4 / verify edges | node qa/tube_revision_d4_20260930/verify_edges.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d4_20260930/verify_inventory.cjs | API测试辅助脚本 | 静态推定：tube revision d4 / verify inventory | node qa/tube_revision_d4_20260930/verify_inventory.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d4_design_20260930/build_gallery.cjs | 辅助/证据脚本 | 静态推定：tube revision d4 design / build gallery | node qa/tube_revision_d4_design_20260930/build_gallery.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_design_20260930/check_gallery.cjs | 视觉测试 | 静态推定：tube revision d4 design / check gallery | node qa/tube_revision_d4_design_20260930/check_gallery.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_d4_design_20260930/check_scope.cjs | API测试辅助脚本 | 静态推定：tube revision d4 design / check scope | node qa/tube_revision_d4_design_20260930/check_scope.cjs；参数见脚本 | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d4_design_20260930/inspect_date.cjs | 视觉测试 | 静态推定：tube revision d4 design / inspect date | node qa/tube_revision_d4_design_20260930/inspect_date.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_d4_design_20260930/verify.cjs | 视觉测试 | 静态推定：tube revision d4 design / verify | node qa/tube_revision_d4_design_20260930/verify.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_ended_design_20260930/build-gallery.cjs | 辅助/证据脚本 | 静态推定：tube revision d4 ended design / build gallery | node qa/tube_revision_d4_ended_design_20260930/build-gallery.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_ended_design_20260930/capture-current.cjs | 视觉测试 | 静态推定：tube revision d4 ended design / capture current | node qa/tube_revision_d4_ended_design_20260930/capture-current.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d4_ended_design_20260930/check-scope.cjs | API测试辅助脚本 | 静态推定：tube revision d4 ended design / check scope | node qa/tube_revision_d4_ended_design_20260930/check-scope.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d4_ended_design_20260930/freeze-design.cjs | 辅助/证据脚本 | 静态推定：tube revision d4 ended design / freeze design | node qa/tube_revision_d4_ended_design_20260930/freeze-design.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_ended_design_20260930/prepare.cjs | 数据初始化脚本 | 静态推定：tube revision d4 ended design / prepare | node qa/tube_revision_d4_ended_design_20260930/prepare.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d4_ended_design_20260930/verify-delivery.cjs | 视觉测试 | 静态推定：tube revision d4 ended design / verify delivery | node qa/tube_revision_d4_ended_design_20260930/verify-delivery.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_ended_design_20260930/verify.cjs | 视觉测试 | 静态推定：tube revision d4 ended design / verify | node qa/tube_revision_d4_ended_design_20260930/verify.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_ended_implementation_20260930/browser-qa.cjs | 页面验收测试 | 静态推定：tube revision d4 ended implementation / browser qa | node qa/tube_revision_d4_ended_implementation_20260930/browser-qa.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d4_ended_implementation_20260930/build-gallery.cjs | 辅助/证据脚本 | 静态推定：tube revision d4 ended implementation / build gallery | node qa/tube_revision_d4_ended_implementation_20260930/build-gallery.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_ended_implementation_20260930/check-scope.cjs | API测试辅助脚本 | 静态推定：tube revision d4 ended implementation / check scope | node qa/tube_revision_d4_ended_implementation_20260930/check-scope.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d4_ended_implementation_20260930/freeze-implementation.cjs | 辅助/证据脚本 | 静态推定：tube revision d4 ended implementation / freeze implementation | node qa/tube_revision_d4_ended_implementation_20260930/freeze-implementation.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_ended_implementation_20260930/prepare.cjs | 数据初始化脚本 | 静态推定：tube revision d4 ended implementation / prepare | node qa/tube_revision_d4_ended_implementation_20260930/prepare.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_ended_implementation_20260930/verify-delivery.cjs | 页面验收测试 | 静态推定：tube revision d4 ended implementation / verify delivery | node qa/tube_revision_d4_ended_implementation_20260930/verify-delivery.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_d4_list_design_20260930/capture-current.cjs | 视觉测试 | 静态推定：tube revision d4 list design / capture current | node qa/tube_revision_d4_list_design_20260930/capture-current.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d4_list_design_20260930/deliver.cjs | 辅助/证据脚本 | 静态推定：tube revision d4 list design / deliver | node qa/tube_revision_d4_list_design_20260930/deliver.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d4_list_design_20260930/prepare.cjs | 数据初始化脚本 | 静态推定：tube revision d4 list design / prepare | node qa/tube_revision_d4_list_design_20260930/prepare.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d4_list_design_20260930/verify-delivery.cjs | 视觉测试 | 静态推定：tube revision d4 list design / verify delivery | node qa/tube_revision_d4_list_design_20260930/verify-delivery.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_list_design_20260930/verify.cjs | 视觉测试 | 静态推定：tube revision d4 list design / verify | node qa/tube_revision_d4_list_design_20260930/verify.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d4_list_implementation_20260930/browser-final.cjs | 页面验收测试 | 静态推定：tube revision d4 list implementation / browser final | node qa/tube_revision_d4_list_implementation_20260930/browser-final.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d4_list_implementation_20260930/browser.cjs | 页面验收测试 | 只读验收：真实接口与浏览器模拟分开记录；模拟数据不会写入数据库。 | node qa/tube_revision_d4_list_implementation_20260930/browser.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d4_list_implementation_20260930/prepare.cjs | 数据初始化脚本 | 静态推定：tube revision d4 list implementation / prepare | node qa/tube_revision_d4_list_implementation_20260930/prepare.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_d4_list_implementation_20260930/read-probe.cjs | 页面验收测试 | 静态推定：tube revision d4 list implementation / read probe | node qa/tube_revision_d4_list_implementation_20260930/read-probe.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d5_a_implementation_20260930/browser-formal.cjs | 页面验收测试 | 静态推定：tube revision d5 a implementation / browser formal | node qa/tube_revision_d5_a_implementation_20260930/browser-formal.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_d5_b_implementation_20260930/browser-formal.cjs | 页面验收测试 | 静态推定：tube revision d5 b implementation / browser formal | node qa/tube_revision_d5_b_implementation_20260930/browser-formal.cjs | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_d5_c_implementation_20261001/browser-formal.cjs | 页面验收测试 | 静态推定：tube revision d5 c implementation / browser formal | node qa/tube_revision_d5_c_implementation_20261001/browser-formal.cjs | 是（调用浏览器，模式UNKNOWN） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_design_20260929/capture_current.cjs | 视觉测试 | 静态推定：tube revision design / capture current | node qa/tube_revision_design_20260929/capture_current.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_design_20260929/export_review.cjs | 辅助/证据脚本 | 静态推定：tube revision design / export review | node qa/tube_revision_design_20260929/export_review.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_design_20260929/verify_design.cjs | 视觉测试 | 静态推定：tube revision design / verify design | node qa/tube_revision_design_20260929/verify_design.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_design_20260929/verify_detail_states.cjs | 视觉测试 | 静态推定：tube revision design / verify detail states | node qa/tube_revision_design_20260929/verify_detail_states.cjs | 是（headless） | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_design_20260929/verify_gallery.cjs | 视觉测试 | 静态推定：tube revision design / verify gallery | node qa/tube_revision_design_20260929/verify_gallery.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_design_v2_20260929/export_review.cjs | 辅助/证据脚本 | 静态推定：tube revision design v2 / export review | node qa/tube_revision_design_v2_20260929/export_review.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_design_v2_20260929/revise_d1.cjs | 辅助/证据脚本 | 静态推定：tube revision design v2 / revise d1 | node qa/tube_revision_design_v2_20260929/revise_d1.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_design_v2_20260929/verify_d1.cjs | 视觉测试 | 静态推定：tube revision design v2 / verify d1 | node qa/tube_revision_design_v2_20260929/verify_d1.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_design_v3_20260929/export_review.cjs | 辅助/证据脚本 | 静态推定：tube revision design v3 / export review | node qa/tube_revision_design_v3_20260929/export_review.cjs | 否 | 否（只读/拦截） | UNKNOWN |
| qa/tube_revision_design_v3_20260929/integrate_dispatch.cjs | 辅助/证据脚本 | 静态推定：tube revision design v3 / integrate dispatch | node qa/tube_revision_design_v3_20260929/integrate_dispatch.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_design_v3_20260929/verify_dispatch.cjs | 视觉测试 | 静态推定：tube revision design v3 / verify dispatch | node qa/tube_revision_design_v3_20260929/verify_dispatch.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_s2_20260929/freeze_design.cjs | 辅助/证据脚本 | 静态推定：tube revision s2 / freeze design | node qa/tube_revision_s2_20260929/freeze_design.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_s2_20260929/verify_source_scope.cjs | API测试辅助脚本 | 静态推定：tube revision s2 / verify source scope | node qa/tube_revision_s2_20260929/verify_source_scope.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_s3_20260929/check_preview_pages.cjs | 页面验收测试 | 本检查只打开和查看，防止误产生采购/库存/外发写入。 | node qa/tube_revision_s3_20260929/check_preview_pages.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_s3_20260929/check_scope.cjs | 页面验收测试 | 静态推定：tube revision s3 / check scope | node qa/tube_revision_s3_20260929/check_scope.cjs | 是（调用浏览器，模式UNKNOWN） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_s3_20260929/freeze_approval.cjs | 页面验收测试 | 静态推定：tube revision s3 / freeze approval | node qa/tube_revision_s3_20260929/freeze_approval.cjs | 是（调用浏览器，模式UNKNOWN） | 否（未见写请求） | UNKNOWN |
| qa/tube_revision_s3_20260929/preview_host.cjs | 辅助/证据脚本 | 独立预览进程入口；仅服务本机，不修改业务代码或数据库。 | node qa/tube_revision_s3_20260929/preview_host.cjs；参数见脚本；需环境变量 | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_s3_20260929/setup_isolation.cjs | 数据初始化脚本 | 静态推定：tube revision s3 / setup isolation | node qa/tube_revision_s3_20260929/setup_isolation.cjs | 否 | UNKNOWN | UNKNOWN |
| qa/tube_revision_s3_20260929/verify_browser.cjs | 页面验收测试 | 静态推定：tube revision s3 / verify browser | node qa/tube_revision_s3_20260929/verify_browser.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/tube_revision_s3_20260929/verify_gallery.cjs | 视觉测试 | 静态推定：tube revision s3 / verify gallery | node qa/tube_revision_s3_20260929/verify_gallery.cjs | 是（headless） | 否（未见写请求） | UNKNOWN |
| qa/tube_source_names_20260930/verify.cjs | 页面验收测试 | 静态推定：tube source names / verify | node qa/tube_source_names_20260930/verify.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/verify_outsourcing_factory_import_ui_1202.cjs | 业务流程测试 | 静态推定：verify outsourcing factory import ui 1202 | node qa/verify_outsourcing_factory_import_ui_1202.cjs；需环境变量 | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/wage_scheme_form_comments_20260918.cjs | 页面验收测试 | 静态推定：wage scheme form comments | node qa/wage_scheme_form_comments_20260918.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/work_report_records_design_20260928/browser_qa.cjs | 视觉测试 | 静态推定：work report records design / browser qa | node qa/work_report_records_design_20260928/browser_qa.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/workbench_ellipsis_check_20260924.cjs | 页面验收测试 | 静态推定：workbench ellipsis check | node qa/workbench_ellipsis_check_20260924.cjs | 是（headless） | 可能写入 | 是（账号/Session/环境变量） |
| qa/workbench_layout_regression.cjs | 视觉测试 | 静态推定：workbench layout regression | node qa/workbench_layout_regression.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/workbench_live_e2e.cjs | 业务流程测试 | 静态推定：workbench live e2e | node qa/workbench_live_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/workbench_visual_e2e.cjs | 视觉测试 | 静态推定：workbench visual e2e | node qa/workbench_visual_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |
| qa/workshop_configuration_1920_e2e.cjs | 视觉测试 | 静态推定：workshop configuration 1920 e2e | node qa/workshop_configuration_1920_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/workshop_configuration_design_e2e.cjs | 视觉测试 | 静态推定：workshop configuration design e2e | node qa/workshop_configuration_design_e2e.cjs；需环境变量 | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/workshop_material_issue_scope_1920_e2e.cjs | 视觉测试 | 静态推定：workshop material issue scope 1920 e2e | node qa/workshop_material_issue_scope_1920_e2e.cjs | 是（headless） | 否（只读/拦截） | 是（账号/Session/环境变量） |
| qa/workshop_sidebar_1920_e2e.cjs | 视觉测试 | 静态推定：workshop sidebar 1920 e2e | node qa/workshop_sidebar_1920_e2e.cjs；需环境变量 | 是（headless） | 否（未见写请求） | 是（账号/Session/环境变量） |

## 隔离快照中的 21 个 `.cjs` 副本

这些文件位于历史隔离前端源码副本中，不能作为当前项目的独立验收入口；统一 runner 不会自动执行它们。

| 文件路径 | 分类 | 用途/范围 | 运行方式 | 浏览器 | 数据库 | 账号 |
| --- | --- | --- | --- | --- | --- | --- |
| qa/inventory_final_integration_20260929/frontend/qa/quo01_browser_e2e.cjs | 辅助/证据脚本（隔离副本） | 隔离前端快照中的报价浏览器脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_final_integration_20260929/frontend/qa/quo01_browser_host_e2e.cjs | 辅助/证据脚本（隔离副本） | 隔离前端快照中的报价浏览器脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_final_integration_20260929/frontend/qa/quo02_editor_mutation_e2e.cjs | 辅助/证据脚本（隔离副本） | 隔离前端快照中的报价编辑脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_final_integration_20260929/frontend/qa/quo03_packaging_e2e.cjs | 辅助/证据脚本（隔离副本） | 隔离前端快照中的报价包装脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_final_integration_20260929/frontend/qa/quo04_preview_e2e.cjs | 辅助/证据脚本（隔离副本） | 隔离前端快照中的报价预览脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_final_integration_20260929/frontend/qa/quo05_version_diff_e2e.cjs | 辅助/证据脚本（隔离副本） | 隔离前端快照中的报价版本差异脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_final_integration_20260929/frontend/qa/quo06_price_history_e2e.cjs | 辅助/证据脚本（隔离副本） | 隔离前端快照中的报价价格历史脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_release_20260929/frontend/qa/quo01_browser_e2e.cjs | 辅助/证据脚本（隔离副本） | 发布隔离前端快照中的报价浏览器脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_release_20260929/frontend/qa/quo01_browser_host_e2e.cjs | 辅助/证据脚本（隔离副本） | 发布隔离前端快照中的报价浏览器脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_release_20260929/frontend/qa/quo02_editor_mutation_e2e.cjs | 辅助/证据脚本（隔离副本） | 发布隔离前端快照中的报价编辑脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_release_20260929/frontend/qa/quo03_packaging_e2e.cjs | 辅助/证据脚本（隔离副本） | 发布隔离前端快照中的报价包装脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_release_20260929/frontend/qa/quo04_preview_e2e.cjs | 辅助/证据脚本（隔离副本） | 发布隔离前端快照中的报价预览脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_release_20260929/frontend/qa/quo05_version_diff_e2e.cjs | 辅助/证据脚本（隔离副本） | 发布隔离前端快照中的报价版本差异脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/inventory_release_20260929/frontend/qa/quo06_price_history_e2e.cjs | 辅助/证据脚本（隔离副本） | 发布隔离前端快照中的报价价格历史脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/receipt_reporting_20260929/frontend/qa/quo01_browser_e2e.cjs | 辅助/证据脚本（隔离副本） | 报表隔离前端快照中的报价浏览器脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/receipt_reporting_20260929/frontend/qa/quo01_browser_host_e2e.cjs | 辅助/证据脚本（隔离副本） | 报表隔离前端快照中的报价浏览器脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/receipt_reporting_20260929/frontend/qa/quo02_editor_mutation_e2e.cjs | 辅助/证据脚本（隔离副本） | 报表隔离前端快照中的报价编辑脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/receipt_reporting_20260929/frontend/qa/quo03_packaging_e2e.cjs | 辅助/证据脚本（隔离副本） | 报表隔离前端快照中的报价包装脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/receipt_reporting_20260929/frontend/qa/quo04_preview_e2e.cjs | 辅助/证据脚本（隔离副本） | 报表隔离前端快照中的报价预览脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/receipt_reporting_20260929/frontend/qa/quo05_version_diff_e2e.cjs | 辅助/证据脚本（隔离副本） | 报表隔离前端快照中的报价版本差异脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |
| qa/receipt_reporting_20260929/frontend/qa/quo06_price_history_e2e.cjs | 辅助/证据脚本（隔离副本） | 报表隔离前端快照中的报价价格历史脚本副本 | 不建议直接执行；先确认隔离环境 | 需复核 | UNKNOWN | UNKNOWN |

