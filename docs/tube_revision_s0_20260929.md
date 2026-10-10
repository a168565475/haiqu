# 管材改造 S0 只读现状核查

核查日期：2026-09-29；数据库取证窗口约为北京时间 18:32—18:37。

范围：依据已获整体批准的 `tube_outsourcing_revision_plan_v1_20260929.md`，完成源码、接口、页面引用、主库旧在途及报工关联的只读核查。本次仅新增本文档；未修改业务源码，未执行迁移、业务写入、旧单转换、删除或测试造单。全部数据库查询使用 `BEGIN READ ONLY`，查询后 `ROLLBACK`；现场核验 `transaction_read_only=on`。

新增执行约束：后续必须严格按用户确认的设计图开发；图中未单独设计的控件沿用当前 ERP，不自行创造另一套样式。S0 不是页面图稿确认，也不代表已获正式旧单转换授权。

## 一、已核实结论

1. 管材当前同时经过普通外发和金工原交接／退回重加工两套写链路，统一外发列表及入库记录都依赖其历史读取。不能整文件删除 `p4_services.py`、`original_order_services.py`、普通外发服务或统一查询。
2. 厂内金工入库仍排除带喷塑工艺的计划，仍会按入库占用抬高旧 `completed_pieces`；新最低报工额度不能继续以该字段作为事实来源。
3. 普通外发回货 API 仍以单个 `factory_id` 办理；旧页面明确显示“分批回货入库”。新管材须新增或重构整单确认路径，同时保留面料的原分支。
4. 当前金工报工改删没有已入库／已直发保护；已有保护针对装配。工价换版、计划完成状态及并发锁顺序都在本次最小必要修改范围内。
5. 主库公共库存状态为 `PUBLIC`。一张喷塑旧单仍在途：`WF-20260924-B33D8C34`，5 条原交接共 1166 支；原领料合计 156 根／601.61 米。旧单已有公共库存接续凭证，但单头 `stock_mode` 仍为 `LEGACY`，不能仅看该标记判定无法接续或再次转换。
6. 按旧来源保存的任务产品与稳定部位身份，未找到对应工价方案及工作项。历史已交接必须用旧有效凭证接续，不能直接套新报工不足门禁、补造报工或重新领料。

## 二、现场主库快照与旧单清单

### 2.1 状态与数量

| 核查对象 | 本次只读结果 | 接续含义 |
| --- | --- | --- |
| `inventory_public_stock_cutover_control` | `PUBLIC_STOCK=PUBLIC`；启用时间 2026-09-29 13:55:39 北京时间 | 已在公共库存阶段，不重跑期初 |
| `WF-20260924-B33D8C34` | `PROCESSING`、`LEGACY`、`POWDER_COATING`；1 个产品、5 条原交接、1166 支 | 唯一已查到的加工中外发单；按原交接及接续凭证处理 |
| `WF-20260927-3EFEC2CD` | `CANCELLED`、`LEGACY`、`POWDER_COATING`；无交接 | 维持已取消、只读，不转成待发新单 |
| 金工来源 | 5 条、均 `OPEN`；已领=旧手工完成=已交接=1166 支；预留=0；厂内入库=0 | 新操作停用前保留旧占用，不能将其释放成新完成额度 |
| 普通外发回货 | 上述两单回货单数均为 0，实收合计 0 | 本次快照没有已回货扣减，但正式执行仍须重读 |
| 未喷塑退回／重新加工／重加工外发 | 均 0 条 | 暂无此类实物待接续；零行不构成删表许可 |
| 重加工外发合格回货 | 0 条 | 仍需保留历史结构和旧请求核对逻辑，直到清理验证 |
| 厂内半成品入库 | 全部类别当前 0 张 | 后续不能把“目前无记录”当作车缝流程可删除 |
| 公共库存流水 | `PUBLIC_STOCK_OPENING IN` 321 条；`MATERIAL_ISSUE OUT` 6 条；本次未见半成品回库来源流水 | 仅证明取证时数据库状态，不证明新回货流程已经实现 |

五项原交接均有 `metal_original_handoff_public_transition` 记录，保存的接续数量与现场交接数量一致，历史已收及未喷塑退回均为 0：

| 切割长度 mm | 截面 | 原交接支数 | 原交接 ID | 原部位身份 |
| --- | --- | ---: | --- | --- |
| 415 | 20×28 | 210 | `6ba89821-4403-44af-955c-d8705feb69c6` | `f017874e-09fe-4a7d-af7c-2adfc1add885` |
| 460 | 20×28 | 320 | `e3a0b0e4-7592-491c-9e96-f5ba86ca9c6b` | `bf8beb61-ad18-421f-bc55-3d747d4f61a4` |
| 505 | 20×28 | 108 | `05ac00b7-8e03-43c1-bb87-5e0752860848` | `7e37fbec-96dd-42b1-8264-27d22e434cbb` |
| 550 | 20×28 | 210 | `1c397725-ee7d-4391-8723-083724408a92` | `0ac8e333-7608-4d56-bde0-589de1af9e51` |
| 595 | 10×20 | 318 | `0be91672-5f80-49b5-9962-b244cdf24ee0` | `4bb23f3a-06ab-459a-bb76-8cd24bb2e81d` |
| 合计 | — | 1166 | — | — |

这些尺寸来自已有接续身份快照，本次没有修改或重新确认实物。S6/S7 必须复核接续记录中的历史凭证、补充确认及哈希，不以本表替代原凭证，也不把历史审计缺口描述为已补齐。

### 2.2 报工关联核查

- 以五项 `MetalProcessingSource.source_snapshot.product_line_id` 查询工价方案，返回 0 张；以该任务产品与 `component_identity` 关联 `WorkItem`，五项均为 0 个关联工作项。
- 因此五项均不存在可直接复用的对应工序最低报工依据；这不代表整个系统没有报工。全库已有 5 张 `APPROVED`、2 张 `SUPERSEDED` 工价方案，且存在有效报工明细。
- 不按“铁管”等相同显示名称匹配其他任务产品或其他部位的报工；不使用全库报工合计填补旧单。
- 旧交接可继续保留已发生占用和库存接续凭证；新单必须采用新报工门禁。此边界应在接续预演中逐项断言。

## 三、后端精确拟修改范围

以下路径均以 `src/backend/apps/` 为基准。标为“拟修改”不表示本阶段已开发。

| 文件／入口 | 当前函数或类 | 后续最小修改 |
| --- | --- | --- |
| `inventory/internal_receipt_services.py` | `load_receipt_context`（62）、`preview_data`（220）、`confirm_receipt`（238） | 解除金工带喷塑整批排除；按部位输出工序最低报工、首次入库／直发／预留；确认时重读额度；不再通过入库抬高手工完成量；保留车缝分支 |
| `inventory/internal_receipt_quantities.py` | `calculate_receipt`、`_calculate`、`validate_receipt` | 增加厂内金工报工上限与共享占用校验，保留订单净需求和已领投入边界；保留 `fabric_input_per_set` 的面料规则 |
| `inventory/internal_receipt_limits.py` | `validate_combined_output` | 区分首次产出、公共未喷塑转换回库、原管材整根余量回库；现有按阶段累计且按 BOM 净需求封顶不能原样套用全部新管材回货 |
| `inventory/internal_receipt_progress.py` | `receipt_progress_for_plans` | 进度按真实首次产出／阶段区分；不得把未喷塑入库和喷塑回库累计成二次生产 |
| `inventory/api/internal_receipts.py` | `InternalReceiptViewSet.preview/create/list/retrieve`、`record_data` | 厂内入库接口增加新额度信息；入库记录能读取新喷塑结果，保留厂内、普通外发、P4 历史来源 |
| `workshop_reporting/services.py` | `_work_item_for_line`、`approve_scheme`、`_validated_work_report_lines`、`_locked_schedule_product`、`update_work_report` | 同工作项跨版累加；新工序不继承旧工序量；金工工价生效与报工改动保护已处理／预留量；复核已完成计划状态，使新必做工序可以合法报工；不改历史工费 |
| `workshop_reporting/deletion_services.py` | `delete_work_report`、`_reopen_incomplete_plans`、`_completion_scheme` | 在现有原因、ETag、审计、幂等历史保护中加入金工约束；失败回滚整单；保留历史完成版本选择逻辑 |
| `workshop_reporting/api/views.py` | `PlanWageStatusView`、`ScheduleProgressStatusView`；相关工价／报工视图 | 对齐计划与任务产品累计范围；不得为改库存额度重写非金工报工规则 |
| `outsourcing/services.py` | `_validate_order_source`、`create_order`、`cancel_order`、`confirm_dispatch`、`confirm_return` | 管材三来源、同一排产／工艺范围内多产品多厂多部位；取消只释放未发预留；管材整单回货新分支；面料保留原函数行为 |
| `outsourcing/dispatch_services.py` | `flow_dispatch_context`、`confirm_flow_dispatch` | 按来源分流；原管材保留支／根／米换算；加工件按支交接，公共未喷塑按支扣库 |
| `outsourcing/public_stock_services.py` | `public_dispatch_context`、`_requirements`、`_lines`、`confirm_public_dispatch`、`public_output_identity` | 增加公共未喷塑出库来源；保留公共原料、面料及公共记账能力，不重新引入采购批次分配 |
| `outsourcing/reconciliation_services.py` | `reconciliation`、`order_action_candidates`、`complete_order` 等 | 新管材不再进入旧投入损耗／退料／结清操作；面料仍使用原规则；历史查询继续可读 |
| `outsourcing/unified_selectors.py` | `unified_order_candidates`、`_regular_rows`、`_original_quantities`、`unified_order_rows` | 新管材状态与数量并入统一列表；保留旧普通单、原交接、重加工来源读取 |
| `material_issues/public_semi_requirements.py` | `build_public_semi_specs`、`public_semi_requirement_rows`、`sync_public_semi_requirements` | 解除带喷塑时排除 METAL 完成阶段的候选规则；两种状态各自库存、共用同部位净需求及待审占用 |
| `material_issues/public_issue_services.py` | `replace_public_issue_lines`、`validate_public_issue`、`confirm_public_issue`、`public_line_quantities` | 混领时服务端合计检查与扣库；不是每个状态各分配一份净需求 |
| `inventory/public_stock_identity.py` | `_pipe_properties`、`build_semi_finished_identity` | 明确未喷塑／已喷塑身份及颜色，保持材质、截面、厚度、切割长度、单位匹配 |
| `inventory/public_stock_services.py` | `_validate_source_context`、`_check_replay`、`credit_public_stock`、`debit_public_stock` | 若采用新来源类型，补来源验证和幂等读取；继续复用记账服务，不另写第二套库存账 |

### 3.1 模型／接口契约需要新增或调整的能力

- 整单一次回货结果必须能记录每个厂／部位的实发、实收、差额、原因，并允许全单 0 实收。不能只依靠正数库存流水推定“已办理”；具体采用扩展模型还是新增结果模型，在 S2/S4 的迁移设计中列明，当前未建表。
- 新来源与有效预留须有稳定关联和可复算占用；厂内产出与半成品阶段转换需要可辨来源。仅增加前端字段不够。
- 双喷塑入口调用同一个确认操作，服务端保证每张新管材单最多一个最终结果，网络重试返回原结果。
- 现有 `outsourcing_return` 单头有单一 `factory_id`，不能把“按厂循环调用原回货 API”包装成整单一次；失败必须全单回滚。
- 结构改变仅新增前向迁移，不改旧 Migration。旧业务表、关联、流水及审计均不删除。

### 3.2 需要改造的现有 API

API 基础路径为 `/api/v1/`：

| API | 处置 |
| --- | --- |
| `GET semi-finished-receipts/preview/`、`POST semi-finished-receipts/` | 金工加入新报工额度；保留车缝 |
| `GET semi-finished-receipts/`、`GET semi-finished-receipts/{id}/` | 保留历史来源，补新喷塑结果关联 |
| `POST outsourcing-orders/`、`POST outsourcing-orders/{id}/cancel/` | 支持三来源和未发预留释放；既有取消记录保留 |
| `GET outsourcing-orders/{id}/dispatch-context/`、`POST outsourcing-orders/{id}/confirm-dispatch/` | 按三来源区分扣量，保留面料 |
| `POST outsourcing-orders/{id}/confirm-return/` | 面料继续原行为；管材改走整单唯一确认，不能继续单厂分次 |
| `GET unified-outsourcing-orders/` 及其汇总接口、普通单 GET 详情 | 保留并扩展新管材状态，不撤掉历史查询 |
| `workshop-reporting/wage-schemes/{id}/approve/`、`PATCH workshop-reporting/work-reports/{id}/`、`DELETE workshop-reporting/work-reports/{id}/` | 加金工额度保护，继续既有权限、ETag、审计与开关 |

喷塑整单确认最终 URL 尚未冻结；本文不把拟定 URL 冒充已有接口。

## 四、旧管材写操作停用与保留清单

停用顺序：S6 隔离预演通过 → S7 获准旧单接续及启用新入口 → 禁止旧管材继续新增写入 → S8 核对无调用后移除专用写代码。只隐藏按钮不能替代后端停止旧写入。

| 旧 API（均 `/api/v1/` 下） | 当前服务 | 后续处置 |
| --- | --- | --- |
| `POST metal-processing-sources/{id}/completions/`、`.../close/` | `processing_services.record_processing` | 停用新登记手工完成及来源备注结清；保留历史完成／结清记录读取 |
| `POST metal-processing-sources/{id}/handoffs/` | `p4_services.create_original_handoff` | 新加工件改走新单按支发出；旧交接读取保留 |
| `POST metal-processing-handoffs/{id}/good-returns/` | `confirm_original_good_return` | 被新整单确认替代；旧请求结果核对必须保留或迁入兼容读取 |
| `POST metal-processing-handoffs/{id}/returns/` | `create_unsprayed_return` | 停用新未喷塑退回登记；历史明细保留 |
| `POST metal-processing-unsprayed-returns/{id}/rework/` | `create_rework` | 停用新返工 |
| `POST metal-processing-reworks/{id}/orders/` | `create_external_order` | 停用新返工外发 |
| `POST metal-processing-external-orders/{id}/allocation/`、`.../handoff/`、`.../returns/`、`.../close/` | `adjust_external_allocation`、`confirm_external_handoff`、`confirm_external_good_return`、`close_external_order` | 停用旧返工外发写路径，包括结清后补回；保留历史订单／分配／回货／结清读取 |
| `POST metal-processing-original-orders/{id}/close/`、`.../cancel-pending/` | `original_order_services.write_original_order_closure` | 旧在途处置完后停用旧收尾写法；新单未发取消用新预留路径；历史结清快照保留 |
| `POST outsourcing-orders/{id}/confirm-raw-return/`、`.../confirm-reconciliation/`、`.../complete/`、`.../revoke-dispatched/` | 普通外发公共服务／`reconciliation_services` | 对新管材停用；保留面料及其必要历史行为，不删除整个共用 API |

必须保留或先拆出的读取依赖：

- `processing_selectors.source_data/quantity_state/frozen_source`：旧来源、原料换算、数量和历史明细。
- `p4_services.original_good_return_context/original_direct_handoff_summary/_source_result/_order_result/unsprayed_return_result/rework_result/available_p4_semi_identity`：统一外发列表、详情及历史库存关联仍使用。
- `original_order_services.original_order_context/original_closure_data/cancelled_pending_pieces`：原单差额、结清时快照、后补历史展示。
- `legacy_public_transition.trusted_handoff_transition/require_original_handoff_mode` 及已保存 `OriginalHandoffPublicTransition`：本次 5 项旧在途的公共库存接续依据，禁止在旧写操作清理时一起删除。
- `InternalReceiptViewSet.list/retrieve` 读取 `INTERNAL_SEMI_RECEIPT`、`OUTSOURCING_RETURN`、`METAL_P4_EXTERNAL_RETURN`；公共流水的旧 `source_type` 不改写。
- `MetalProcessingSource/Completion/Closure/OriginalHandoff/UnsprayedReturn/Rework/ExternalOrder/ExternalHandoff/ExternalGoodReturn/ExternalClosure` 及对应 Migration 全部保留数据与结构。本轮没有删表计划。

## 五、前端精确引用与设计范围

以下路径以 `src/frontend/src/` 为基准。业务开发前须对应 D1—D5 确认图。

| 文件 | 已发现引用 | 后续边界 |
| --- | --- | --- |
| `views/workshop/WorkshopPlanListView.vue` | `openMetalProcessing`；“金工完成登记”；“半成品入库”路由 | 去掉新手工完成入口；提供图稿确认的金工入库／加工件外发入口；工价、报工和其他车间操作保留 |
| `views/inventory/InternalSemiReceiptView.vue` | 当前厂内半成品入库页面 | 增加最低报工与共享额度信息；保留车缝模式 |
| `views/inventory/MaterialInventoryView.vue` | 公共材料／半成品库存页面 | 半成品区域提供金工与喷塑入库入口、阶段展示；不重做材料库存全页 |
| `views/inventory/SemiReceiptRecordsView.vue` | 厂内／外发记录及详情 | 新喷塑结果接入，历史来源保留；0 回货结果在外发详情保留，不伪造入库流水 |
| `views/outsourcing/OutsourcingOrderListView.vue` | 导入 `MetalProcessingP4View`；`RAW/METAL/REWORK` 来源选项；`tab=sources`；返工创建链接 | 新单三来源按图更新；去掉新返工创建；历史返工筛选和详情是否留入口按 D4 明确，不因无新返工删除历史读取 |
| `views/outsourcing/OutsourcingOrderFormView.vue` | `fetchP4Source`；“合格与不良分别入库”“手动结清”旧说明 | 管材来源和数量改为确认图；管材不保留旧不良／结清说明；面料分支保持 |
| `views/outsourcing/OutsourcingOrderDetailView.vue` | `MetalProcessingP4View`；“选择金工加工件”；“可补登记”“回齐待结清” | 新管材使用喷塑整单入口及已结束状态；旧详情保留真实历史，不给新管材旧操作 |
| `components/outsourcing/OutsourcingFlowActions.vue` | `dispatch/return/raw/record/complete`；单厂选择；“分批回货入库” | 新管材不能复用旧分厂提交；保留面料全部必要行为及发料通用校验 |
| `views/outsourcing/MetalProcessingP4View.vue` | 13 类旧操作弹窗及历史详情混在同一组件；`registerP4SourceCompletion`、`createP4OriginalHandoff`、退回／返工／结清／补回等 | 拆分历史读与旧写后再清理；不是直接删除整组件 |
| `views/outsourcing/OutsourcingReworkDetailView.vue` | 以 `mode=rework` 包装 P4 组件 | 历史返工详情仍应可读；不是新返工入口 |
| `api/metalProcessingP4.ts`、`types/metalProcessingP4.ts` | 旧写 API 与历史 GET／类型共存 | 逐函数去除无调用旧写封装，GET 与历史结构按引用保留 |
| `api/outsourcing.ts`、`types/outsourcing.ts`、`api/unifiedOutsourcing.ts`、`types/unifiedOutsourcing.ts` | 普通外发、统一列表和历史路由 | 增加三来源／整单结果契约，保留面料及历史类型 |
| `components/workshop/MaterialIssuePartitions.vue`、`views/workshop/material-issues/MaterialIssueFormView.vue` | 半成品选择、数量、领料提交 | 已喷塑／未喷塑分列或状态列依图，合计净需求提示及校验 |
| `router/index.ts` | `/inventory/semi-finished/receive`；`/workshop/outsourcing/metal-processing`；`/workshop/outsourcing/rework/:orderId` | 增加确认图对应喷塑入口路由；保留旧书签合理跳转及历史详情，不能只删路由造成历史入口失效 |

`MetalProcessingP4View` 的明确旧写封装包括：`registerP4SourceCompletion`、`closeP4Source`、`createP4OriginalHandoff`、`confirmP4OriginalGoodReturn`、`createP4UnsprayedReturn`、`createP4Rework`、`createP4ExternalOrder`、`adjustP4ExternalAllocation`、`confirmP4ExternalHandoff`、`confirmP4GoodReturn`、`closeP4ExternalOrder`、`closeP4OriginalOrder`、`cancelP4OriginalPending`。删除前逐项 `rg` 搜索调用及测试，不整块删除模块。

## 六、并行改动与实施风险

### 6.1 工作区事实

- Git 当前不是干净工作区。相关 `inventory/`、`material_issues/`、`outsourcing/`、`workshop_reporting/`、前端库存／外发目录大部分为未跟踪目录；`config/settings.py` 和 `router/index.ts` 为已修改文件。
- 因此只用 `git diff HEAD` 不能得到这些模块的完整基线，也不能据此认定某段代码属于当前任务。S2 应从当前文件内容建立隔离工作副本或完整快照，逐文件核对；不 `reset/restore`，不覆盖主目录，不批量暂存。
- 本次哈希是现状识别依据，不证明文件所属作者或没有其他任务正在运行。正式开发与合并前重新比较；主代理与其他任务新增的文档不纳入本次源码修改。

关键文件 SHA-256（采集时点约北京时间 18:35；路径以项目根为基准）：

| 文件 | SHA-256 |
| --- | --- |
| `src/backend/apps/inventory/internal_receipt_services.py` | `5345A9DE817B178711E74E0B27F7BAEA2F0021F9EE262272F5180379261F39E4` |
| `src/backend/apps/inventory/internal_receipt_limits.py` | `40D801FA74EA16230486B4D1A9B8E8E3568741F57C77FA3B8AF01322AAD5F7FB` |
| `src/backend/apps/material_issues/p4_services.py` | `E970BD77678D8ADEBF62798AEABFC304564848C88B398109454D66B63F4D4E4C` |
| `src/backend/apps/material_issues/processing_services.py` | `97098B86DBEDA9DD4990B7E2BB43A1E7600D679F04469E568457CD0B13833BEF` |
| `src/backend/apps/material_issues/public_semi_requirements.py` | `48FDFD08CD8B79007A379C1D1CC6CA28372B78BB052DD27C3851FECD408D975C` |
| `src/backend/apps/outsourcing/services.py` | `BC4F6BEE9E3481E5A37E886AD63F8E40F9A54AA448542B4BBF53C3C62BF9C8A6` |
| `src/backend/apps/outsourcing/public_stock_services.py` | `0343C5E883D186B9DFD35942585F37FA4E33C231A6A0BA386911DF5F4D7E8541` |
| `src/backend/apps/workshop_reporting/services.py` | `CC810C4DF6A33AD540119D4552A351FF0FD295183D98D0D46516EBE9F6BE6FEC` |
| `src/backend/apps/workshop_reporting/deletion_services.py` | `1226549E107C877380B3951B09DD826A7C2D16FA584C519EBEE7BAFD7DEC7BB1` |
| `src/frontend/src/components/outsourcing/OutsourcingFlowActions.vue` | `94070949E3CB87591B8E98523A5D1BB40F1CB3AEE98096A13A1F49F8AE31CCF0` |
| `src/frontend/src/views/outsourcing/MetalProcessingP4View.vue` | `789516B587B49B573D6C20B3F668A88A37D5C41A7375A11FF7A3ACC90457AA84` |
| `src/frontend/src/views/workshop/WorkshopPlanListView.vue` | `61E3CA0BF078D75C8660AF5BAD9325BC5CB79334AF3261BE7F120D75509E439C` |

### 6.2 必须进入 S2/S6 的约束

1. **统一计算范围。** 现报工保存／列表按 `schedule_product` 累计，删除恢复按 `product_line` 累计；厂内投入也跨任务产品汇总。新金工额度按任务产品＋稳定部位＋工作项统一，一份报工不能被两个计划各使用一次。
2. **统一锁顺序。** 厂内入库先锁领料／来源，再锁排产、任务、排产产品、任务产品；报工为排产、任务、任务产品、排产产品。不能只追加查询校验，须统一顺序并实测并发，避免超额和互等。
3. **工价与已完成计划。** 新有效必做工序报工不足时，不能仍因原计划 `COMPLETED` 拒绝全部报工；同时不能把历史已入库／交接数量直接降为无依据。方案变更保护、计划状态及已有占用要协调。
4. **原单与公共库存模式。** 在途单仍 `LEGACY`，实际已有 `OriginalHandoffPublicTransition`。接续须走已验证的凭证读取，不能直接改 `stock_mode`、再扣原料或重做公共期初。
5. **正数库存流水与零实收结果分离。** 全 0 时原单正式结束，但库存无新增流水；记录页和幂等不能靠“有没有入库流水”判断是否已办理。
6. **保留旧请求核对。** 前端旧页面和超时重试可能仍携带旧请求 ID；旧写接口停用必须能区分已成功历史结果与新的未授权旧操作，不能引导用户重新点新接口重复入库。
7. **未来生效工价。** 不能仅在审批当天校验；真实入库／直发时仍需按有效工序集合重读并保护已发生数量。生效日期变化不得默默重写历史库存和工资。

## 七、验证记录与交付界限

实际执行：

- `docker compose ps`：后端、前端、PostgreSQL、Redis、ClamAV 运行；本次不因只读核查重启服务。
- 限定模块的 `rg` 函数、路由及调用搜索；实际读取关键服务和页面引用。
- `git status --short` 及相关路径范围查询；发现大量现有未跟踪文件，未清理。
- PostgreSQL `psql -X -v ON_ERROR_STOP=1`：表结构、控制状态、外发／交接／接续记录数量、历史报工匹配查询。每组 SQL 均以 `BEGIN READ ONLY` 开始、`ROLLBACK` 结束。
- 关键 12 个源码文件 SHA-256 采集；报告写入后再次比对，以便发现核查期间源码变化。

没有执行：业务 API 写操作、后端测试、前端构建、浏览器造单、Migration、数据修复、旧单转换、旧代码删除。S0 是只读范围核查，不将其表述为新业务测试通过。

接下来的可审阅产物是 D1—D5 图稿和交互说明；图稿通过后方可按 S2 开始业务开发。S6 必须输出最新旧单逐项数量守恒、拟转换记录、备份／恢复验证及正式执行清单；本报告不是 S7 的执行许可。
