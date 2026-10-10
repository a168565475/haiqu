# 出库单详情原型实现与验收 · 2026-09-11

Figma：`816:9236`；路由：`/samples/outbound/documents/:outboundId`。

- `SampleOutboundDetailView.vue` 复用 `SampleStatusTag`、`CustomerActivityTag` 和单据公共SCSS；页面差异仅在 `sampleOutboundDetail.scss` 中定义九列宽度。`App.vue` 将此路由纳入已有Warm布局和滚动范围。
- 接入现有真实详情API；权限与后端 `samples.view_sampleinventoryoutboundline` 一致。来源入库及来源申请分别检查权限和有效标识。请求序号防止切换单据时旧响应覆盖，具备空态、403/404/服务异常和重试。
- 九列继续展示入库批次、来源申请、产品、规格颜色、数量、出库方式、快递公司、单号、备注。不改API和出库规则。
- 9项详情测试、入库详情9项、出库列表8项共26项通过，类型检查通过；构建通过（28.77秒，`outputs/sample-outbound-detail-build-20260911.log`）。项目未配置lint。
- `qa/sample_outbound_detail_figma_20260911.cjs` 从真实样品库出库入口打开1条明细单据。1920×1080和1440×900检查通过：230/64外壳（1440自动折叠64侧栏）、标题28、98×34按钮、148/108/300/200分区、44表头、68行、24自适应标签。列宽170/170/150/180/90/130/120/170/180；小屏内部滚动，无页面横向溢出。
- 来源入库批次跳转、来源申请跳转、返回列表、503重试、403/404、空明细夹具通过；无页面异常或业务写请求。代码审查无P1/P2。
- 截图及证据：`outputs/sample_outbound_detail_figma_20260911/`，已检查清晰1920截图。

沿用已确认Warm ERP规则，替代旧画板冲突的通用壳层、蓝编号、浅标签和圆角；底部原型开发备注改为查看来源的业务说明。不新增业务操作，完整模块写流程验收仍未结束。
