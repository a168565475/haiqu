# 打样模块前端交付与验收 · 2026-09-11

本报告是当前状态汇总，替代各阶段报告中已经过时的“待开发／待验收”描述。以 Figma 文件 `czPqlJ7fXYn5cq4cbQyTFm` 实际页面为基准，保留用户后续确认的编号、标签、BOM 交互及图片规则。现有原型页面已实施，现有接口已接入；没有把仍缺接口的采购后续、订单解锁等描述为已经打通。

## 页面、路由与代码

视图位于 `src/frontend/src/views/samples/`，弹窗位于 `src/frontend/src/components/samples/`。

| 页面 | Figma Node | Route / 入口 | 实现 |
| --- | --- | --- | --- |
| 打样列表 | 1897:18624 | /samples | SampleListView.vue |
| 新建、退回补充申请 | 1851:18496 | /samples/new | SampleApplicationCreateView.vue |
| 厂长确认 | 1812:18474 | /samples/:sampleId/director-review | SampleDirectorReviewView.vue |
| 材料需求、全屏 | 1878:18504 / 1880:19771 | /samples/:sampleId/materials | SampleMaterialRequestView.vue |
| 仓库核对、全屏 | 1887:18596 / 1891:18615 | /samples/:sampleId/warehouse-review | SampleWarehouseReviewView.vue |
| 完善申请、编辑、报工 | 676:9438 / 724:8929 | /samples/:sampleId/edit | SampleFormView.vue |
| 详情、PMC、完成状态 | 245:5933 / 765:8900 / 779:8870 | /samples/:sampleId | SampleDetailView.vue |
| 费用处理 | 258:5218 | /samples/:sampleId/fees | SampleFeeView.vue |
| 物流、反馈 | 258:5608 | /samples/:sampleId/fulfillment | SampleFulfillmentView.vue |
| 反馈再报价 | 502:7853 | 物流反馈页弹窗 | SampleFeedbackRequotationDialog.vue |
| 样品库存 | 810:8933 | /samples/inventory | SampleInventoryView.vue |
| 样品出库 | 812:8933 | /samples/outbound | SampleOutboundView.vue |
| 样品借出 | 812:9236 | /samples/loans | SampleLoanView.vue |
| 批量入库 | 814:8933 | 库存页弹窗 | SampleInventoryReceiptDialog.vue |
| 批量出库 | 814:9235 | 出库页弹窗 | SampleOutboundCreateDialog.vue |
| 批量借出 | 814:9529 | 借出页弹窗 | SampleLoanCreateDialog.vue |
| 入库单详情 | 816:8933 | /samples/inventory/receipts/:receiptId | SampleInventoryReceiptDetailView.vue |
| 出库单详情 | 816:9236 | /samples/outbound/documents/:outboundId | SampleOutboundDetailView.vue |
| 借出单详情 | 816:9535 | /samples/loans/documents/:loanId | SampleLoanDetailView.vue |

旧的询盘/报价 intake 入口作为兼容流程保留，不擅自合并成新材料流程。客户详情“样品 → 新增样品申请”已经接入新申请页，回填可访问且未归档的客户。

## 已接真实业务

- 列表搜索、筛选、日期、重置、排序、分页、列设置、保存视图、现有导出、批量操作与权限门禁。
- 新建、询盘来源、图片继承/替换、提交厂长、退回、同单补充重提、厂长确认。
- 材料保存与提交，分区、全屏、逐行编辑；仓库库存对比、可供数量保存、正缺口提交采购需求快照。
- 旧申请 COMPLETE / FULL / REPORT_ONLY / READ_ONLY 四种服务端模式，财务确认、PMC、金工/裁剪参数至 FINISHED。
- 收费、免费、豁免、实际凭证上传、豁免审批、刷新回填。凭证上传不等于到账核验。
- 寄送创建、人工寄出、物料进度、人工签收、正式客户反馈、确认结果、再报价草稿及对应版本跳转。
- 样品入库、出库、借出及单据详情，成品库存同步，真实数量扣减与来源追溯。

保留 Session/CSRF、ETag、数据范围、操作权限、重复提交锁、并发响应保护、异常重试和未保存离开保护；接口失败不伪装成功。

## 用户最后七项要求

1. 管材名称从有效品名配置选择。
2. 规格使用直径、厚度配置组合选择，历史规格不丢失。
3. 颜色按“颜色 - 色卡 - 色号”显示并保存。
4. 五金、塑料、辅料、包材采用品名分组选材；没有手动添加材料、添加一行、下一条入口。多选、跨组保留和去重按 BOM 操作。
5. 材质使用配置；没有独立配置表的类别兼容有效材料主档去重值。
6. 产品图片使用打样参考图。
7. 询盘单图自动带入，多图由用户选择；允许替换/移除，原询盘附件不被改写。图片扫描和数据权限均检查。

详细代码范围与图片验证见 `sample-material-choices-images-20260910.md`、`sample-material-choices-recheck-20260911.md`。

## 组件与 SCSS

复用 `ErpLayout`、`AppSidebar`、`AppHeader`、`CrmPageHeader`、`DataTableToolbar`、`PinyinFilterSelect`、Element Plus 功能组件、现有鉴权及 API 封装。

打样共享组件包括 `SampleSection`、`SampleReadonlyField`、`SampleStatusTag`、`SampleApplicationSummary`、`SampleFullscreenHeader`、材料编辑/字段/分区/选材/抽屉、仓库比较及库存查询组件。图片共用组件 `SampleProductImage` 在材料图片调整阶段新增。三种批量操作弹窗和再报价弹窗作为业务组件复用；收尾没有新增基础控件或依赖。

使用已有 Warm ERP Token；公共 SCSS 为 `_sample-controls`、`_sample-workspace`、`_sample-library`、`_sample-document`、`_sample-dialog`、`_sample-batch-dialog`、`_sample-material-overlays`。重复的库列表、单据、弹窗布局由 mixin 共享。页面样式按 scope 或专属弹层 class 限定，未新增普通 CSS，未为本轮修复修改全局 Token。

## 最终验证

| 检查 | 当前结果 | 证据 |
| --- | --- | --- |
| 前端全量 test | 434 项，432 通过、2 失败 | outputs/sample-goal-final-20260911-tests.json |
| 打样相关单元测试 | 31 文件，242 项全部通过 | 同上，路径包含 sample 的用例 |
| 后端打样全量 test | 115 项通过，130.789 秒 | outputs/sample-goal-final-backend-20260911-tests.log |
| type-check | 退出 0 | 最后 28 项专项后独立执行 npm run type-check |
| build | 退出 0，44.19 秒 | outputs/sample-goal-final-build-20260911.log |
| lint | 项目未配置，不能报告通过 | src/frontend/package.json |
| 独立代码复审 | 已修完发现的 P2，未发现剩余 P1/P2 | 本次只读复审记录 |

两个全量失败均来自无关的 `MasterDataCenterView.spec.ts`：国家字段与空汇率历史断言。测试 mock 没有导出页面使用的 `fetchAllMasterDataRecords`。没有跳过测试，也没有修改无关基础资料模块来取得全绿。构建保留已有第三方 PURE 注释和大包警告。

本轮代码审查修复了费用审批人刷新回填、详情费用/物流入口、寄送创建/读取权限组合，以及再报价读取权限、固定反馈版本跳转、客户详情新建样品路由。新增关键回归先失败、修复后通过。非产前样检查显示“不适用”。

## 浏览器与视觉证据

正式基准 1920×1080，兼容验证 1440×900。逐页实现时已检查实际 Figma 上下文、截图和页面；收尾使用最新构建，真实 API 转发到专用隔离库，没有 mock 已有业务接口，也没有向业务库写测试单。

| 验证范围 | 最新证据目录 |
| --- | --- |
| 新版列表、新建、厂长、材料/全屏、仓库/全屏、客户入口 | outputs/sample_v3_final_readonly_20260911 |
| 材料配置下拉、四类品名分组及 BOM 交互 | outputs/sample_material_choices_readonly_20260911 |
| 创建/退回/重提/厂长及材料→仓库→正缺口 | outputs/sample_application_flow_20260910、sample_material_flow_20260910 |
| 编辑四模式及 PMC/参数/完成 | outputs/sample_edit_write_flow_20260911 |
| 费用三分支、凭证、豁免审批 | outputs/sample_fee_write_flow_20260911 |
| 创建寄送至签收、反馈、客户确认 | outputs/sample_fulfillment_write_flow_20260911 |
| 再报价两种分支、固定版本、重复打开 | outputs/sample_requotation_write_flow_20260911 |
| 样品入库、出库、借出、成品同步 | outputs/sample_inventory_write_flow_20260911 |
| 库三列表、三弹窗、三单据详情逐页截图 | outputs/sample_{inventory,outbound,loan,receipt_dialog,outbound_dialog,loan_dialog,receipt_detail,outbound_detail,loan_detail}_figma_20260911 |

收尾七画板及客户入口共 16 张截图通过，无页面横向异常溢出；1920 侧栏 230px、顶栏 64px；列表标签实色浅字、高 24px、自适应宽度，编号为正文深色；仓库采购缺口普通和全屏均无底色。1440 按已有壳层规则折叠侧栏、表格内部滚动。费用/物流入口标题没有交叠，再报价弹窗没有超出视口。

人工复核了列表、材料、仓库全屏、客户预填新建、报工、完成详情、收费/豁免、反馈、再报价弹窗与报价预览等最新截图。旧隔离材料单的图片曾随旧容器清理，收尾截图展示“图片暂无法加载”的容错态；图片上传成功证据来自独立写流程，不能混为一项。QA 调试时的失败截图保留，最终以 evidence.json 的结果及同次截图为准。

## 仍存在的设计差异和业务／API 缺口

- 实际数据、权限菜单、统计、历史明细数与原型示例不同；已确认的 Warm ERP 壳层和标签覆盖旧画板的冲突样式。不能宣称所有页面逐像素完全一致。
- 材料下拉、BOM 交互和图片继承是用户后续确认的修改；详情为现有费用/物流功能补充两个导航入口，Figma 原详情未包含这两个按钮。
- 旧完整编辑接口要求的打样信息明细和历史详情折叠区仍保留，以免丢失数据；业务员新建页没有增加样品明细或打样信息明细。
- 管材没有完整规格配置表，以直径×厚度组合；部分材料类别没有独立材质表，兼容有效主档值；询盘图片是单据级附件，多图不推断产品归属。
- 个人待办缺对应统计/筛选契约；费用草稿、发票、受控收款账户、承运商同步、订单解除阻塞、出库/借出导出和归还尚无相应接口，相关入口禁用或明确提示。
- 采购目前只接收到正缺口需求快照；供应商分配、采购下单、到货、实际扣库及新材料流程后续交接，缺完整业务契约和对应 Figma 全页。没有伪造采购处理页，也未把旧财务/PMC流程自动接到新材料流程。
- 上述接口缺口按照目标允许的边界隔离。已存在原型且已有接口的前端实施与验收已完成；整个跨采购、物流外部系统、订单模块的业务闭环仍未完成。

## 本轮收尾变更文件

产品代码：`SampleFeeView.vue`、`SampleDetailView.vue`、`SampleFulfillmentView.vue`、`SampleFeedbackRequotationDialog.vue`、`SampleApplicationCreateView.vue`、`components/customers/CustomerRelatedRecordsV2.vue`，及对应五个测试文件。

验收脚本：`qa/sample_fee_write_flow_20260911.cjs`、`sample_fulfillment_write_flow_20260911.cjs`、`sample_edit_write_flow_20260911.cjs`、`sample_requotation_write_flow_20260911.cjs`、`sample_v3_final_readonly_20260911.cjs`；隔离夹具位于 `src/backend/tmp/sample_{fee,edit,requotation}_flow_qa_seed.py`。本轮没有修改后端业务流程、数据库结构或执行业务迁移。

补充报告：`sample-fee-fulfillment-write-flow-20260911.md`、`sample-edit-write-flow-20260911.md`、`sample-requotation-write-flow-20260911.md`。较早逐页报告继续保留，可追溯各阶段文件和测试结果。
