# 打样完整目标恢复核查 · 2026-09-11

> 最终更新：编辑四模式、费用、物流、再报价、库存写链路和全模块审查已补齐。当前交付状态及剩余接口边界统一见 [sample-module-delivery-20260911.md](sample-module-delivery-20260911.md)。下文保留恢复过程记录，其中“待验收”不再代表最终结果；前端最终 434 项中 432 通过，打样 242 项全部通过，后端打样 115 项通过。

> 后续复核修正：本报告下文“必须再次确认设计来源”的结论已撤回。目标已经授权以 Figma 实际存在的页面为准；不能仅凭没有 V3 命名或仍带草案标签推断缺少授权。后续按各功能当前节点继续，存在新版替代则使用新版，不从旧代码臆造视觉。明确的全局要求（230px 侧栏、64px 顶栏、Warm ERP、编号/状态标签）仍优先于旧画板中冲突的通用壳层。完整范围继续 active，不再以画板命名为 blocked 理由。详情页已读取 765:8900、779:8870 并开始布局修正，见 `sample-detail-layout-20260911.md`。

目标仍为附件 `goal-objective.md` 中的全部打样页面开发与完整验收，不缩减为上一轮材料与图片调整。上一轮完成了实现、测试及真实隔离浏览器验证，属于实际进展。本轮为目标恢复后的首次阻塞复核，不将历史 blocked 次数直接累计到本次。

## 最新证据

- 重新读取目标附件、项目 AGENTS、DESIGN、当前 Token、路由、申请/材料接口和已有验收记录。
- Figma 只读核查 `czPqlJ7fXYn5cq4cbQyTFm` 的页面目录及 `0:1` 全页打样画板，当前仍有 7 个 SAM-V3 画板。详情、费用、物流及样品库相关画板没有发现新版替代。
- 当前真实 API 已覆盖创建、重提、厂长确认、材料草稿/提交、仓库核对。旧报告中这些“接口缺失”的段落已不代表当前状态，应以本轮源码核查和 9 月 10 日后续交付报告为准。

## 页面 → Figma → 路由 → 当前代码 → 开发状态

以下前端路径均相对 `src/frontend/src/views/samples/`；已实现不等于整个模块重新验收通过。

| 页面 | Figma Node | Route | 当前代码 | 状态 |
| --- | --- | --- | --- | --- |
| 打样列表 | 1897:18624 | /samples | SampleListView.vue | V3 已实现，真实列表/状态筛选；个人待办仍明确不可用 |
| 新建申请、退回补充 | 1851:18496 | /samples/new（补充通过查询参数） | SampleApplicationCreateView.vue | 已接真实提交/重提；产品规格、图片继承和替换已实现 |
| 厂长确认 | 1812:18474 | /samples/:sampleId/director-review | SampleDirectorReviewView.vue | 已接真实确认/退回 |
| 材料需求、全屏 | 1878:18504 / 1880:19771 | /samples/:sampleId/materials | SampleMaterialRequestView.vue | 已接真实保存/提交，采用后续确认的 BOM 交互 |
| 仓库核对、全屏 | 1887:18596 / 1891:18615 | /samples/:sampleId/warehouse-review | SampleWarehouseReviewView.vue | 已接真实核对与正缺口提交 |
| 编辑、打样信息填写 | 676:9438 / 724:8929 | /samples/:sampleId/edit | SampleFormView.vue | 已对齐紧凑标题/分区/表单/表格/页脚并修复连续选图，21 项专项通过；真实只读桌面验收通过，可编辑状态仍待隔离流程验证，见 sample-edit-figma-20260911.md |
| 详情、PMC、完成 | 245:5933 / 765:8900 / 779:8870 | /samples/:sampleId | SampleDetailView.vue | 已对齐主布局、产品明细、参数、图片及完成态汇总，12 项专项通过；完整验收仍待补齐，见详情进度报告 |
| 费用 | 258:5218 | /samples/:sampleId/fees | SampleFeeView.vue | 已按现存节点实施，10 项专项与构建通过，1920/1440 真实终态只读检查通过；写流程仍待隔离验收，草稿/发票/受控账户 API 缺口见 sample-fee-figma-20260911.md |
| 物流、反馈、再报价 | 258:5608 / 502:7853 | /samples/:sampleId/fulfillment | SampleFulfillmentView.vue | 已按节点实施，10项专项/类型/构建通过；1920/1440真实只读与再报价独立视觉夹具通过，真实写链路待补，见 sample-fulfillment-figma-20260911.md |
| 库存 | 810:8933 | /samples/inventory | SampleInventoryView.vue | 已对齐布局与Warm ERP；12项专项通过，1920/1440真实只读及独立错误夹具通过，审查两项P2已修复；写操作与弹窗另待验收，见 sample-inventory-figma-20260911.md |
| 出库 | 812:8933 | /samples/outbound | SampleOutboundView.vue | 已对齐并接真实列表操作，专项8项；1920/1440真实只读和错误夹具通过；写入与弹窗另待验收，见 sample-outbound-figma-20260911.md |
| 借出 | 812:9236 | /samples/loans | SampleLoanView.vue | 已对齐并接真实列表操作，专项8项；三页共用SCSS、28项回归/类型/构建/代码审查通过；1920/1440真实只读和错误夹具通过，见 sample-loan-figma-20260911.md |
| 批量入库 | 814:8933 | 样品库内 | SampleInventoryReceiptDialog.vue | 已对齐并保留成品仓同步；11项专项及1920/1440真实读取、输入与错误夹具通过，实际入库及成品同步链路也已隔离验证，见 sample-receipt-dialog-figma-20260911.md、sample-inventory-write-flow-20260911.md |
| 批量出库 | 814:9235 | 样品出库内 | SampleOutboundCreateDialog.vue | 已对齐三种方式交互、分页及并发保护；11项专项及1920/1440真实读取、输入与错误夹具通过，实际出库扣减链路也已隔离验证，见 sample-outbound-dialog-figma-20260911.md、sample-inventory-write-flow-20260911.md |
| 批量借出 | 814:9529 | 样品借出内 | SampleLoanCreateDialog.vue | 已按原型实现，9项专项及1920/1440真实读取、输入和异常夹具通过，实际借出占用链路也已隔离验证，见 sample-loan-dialog-figma-20260911.md、sample-inventory-write-flow-20260911.md |
| 入库单详情 | 816:8933 | /samples/inventory/receipts/:receiptId | SampleInventoryReceiptDetailView.vue | 已实现，9项专项、真实来源跳转及两档桌面验收通过，见 sample-receipt-detail-figma-20260911.md |
| 出库单详情 | 816:9236 | /samples/outbound/documents/:outboundId | SampleOutboundDetailView.vue | 已实现，9项专项、真实来源跳转及两档桌面验收通过，见 sample-outbound-detail-figma-20260911.md |
| 借出单详情 | 816:9535 | /samples/loans/documents/:loanId | SampleLoanDetailView.vue | 已实现，9项专项、真实来源跳转及两档桌面验收通过，见 sample-loan-detail-figma-20260911.md |
| 采购处理及其后续新流程 | 未发现对应 V3 全页画板 | 当前采购待处理行打开仓库核对页 | SampleWarehouseReviewView.vue / 现有缺口接口 | 不把缺口快照当成完整采购操作页；后续流程仍缺设计和业务契约 |

## 9月11日费用与物流写流程补齐

费用、物流反馈已完成真实隔离写链路，见 `sample-fee-fulfillment-write-flow-20260911.md`。详情新增费用／物流导航，豁免审批人刷新回填、寄送新增与查看权限组合均已修复并复审。费用三分支及凭证上传、物流创建至客户确认均从正常列表详情入口通过；1920/1440 无页面溢出和标题操作交叠。当前相关三个页面专项 30 项通过，类型检查通过。上表“费用写流程待验收”和“物流真实写链路待补”已由此证据更新；再报价实际创建仍待补齐，编辑及整体目标继续进行。

## 9月11日单据页收尾后的最新全量测试

`outputs/sample-goal-progress-20260911-tests.json`：415项，413通过，2失败；打样相关31个文件共227项全部通过。失败仍是 `MasterDataCenterView.spec.ts` 的国家字段与空汇率历史断言；现有模拟未导出页面调用的 `fetchAllMasterDataRecords`。未修改无关基础资料页面或跳过用例。

新增批量借出及三种单据详情已经完成逐页专项、真实只读桌面验收及代码审查。最新类型检查通过，最新构建27.81秒通过，见 `sample-loan-detail-build-20260911.log`。项目没有lint脚本。库存实际入库、出库、借出及成品同步已经隔离验收通过，见 sample-inventory-write-flow-20260911.md。后端打样全量115项通过（190.528秒）。完整目标仍包含编辑、费用、物流反馈写流程及总审查；不能将已完成部分当作整个业务流程通过。

## 较早执行的全量测试（以下保留历史）

命令（`src/frontend`）：

```powershell
npm run test -- --reporter=json --outputFile=../../outputs/sample-goal-audit-20260911-tests.json
```

退出码 1：287 项测试，285 通过、2 失败。路径含 sample 的 31 个测试文件全部通过。失败均为 `MasterDataCenterView.spec.ts`：国家字段、空汇率历史断言。当前测试模拟仍未导出页面实际调用的 `fetchAllMasterDataRecords`；没有更改无关基础资料中心或通过跳过测试掩盖失败。

本轮没有修改产品代码，因此未重复上一轮类型检查、构建或浏览器测试，旧通过结果不作为本轮新执行结果。lint 未配置；整个模块最终 Review 与全部页面视觉验收仍未完成。

## 历史设计来源结论（已撤回，不是当前阻塞）

目标同时要求“以最新 Figma 为唯一基准”“不使用旧打样页面作为视觉标准”“不重新设计”，而剩余页面仍只有原画板或草案。因此需用户明确：允许将现存这些画板作为开发基准，或者提供/允许补齐新版设计。此前建议复用 V3 控件与分区不等于已获设计授权。

本轮未修改 Figma、未擅自选择新设计来源、未删除范围，也没有标记 complete。目标继续 active；本次为恢复后的第一次同一阻塞核查，尚未满足三次 blocked 门槛。
