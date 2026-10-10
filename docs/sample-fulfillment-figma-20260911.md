# 样品物流、反馈及再报价页面 · 2026-09-11

本轮先读取完整目标附件，再读取 Figma `258:5608`（1920 物流页）、`502:7853`（1440 再报价弹窗），沿用已确认的 Warm ERP、230px 侧栏、64px 顶栏、深色编号、24px 实色标签。没有修改 Figma 或后端业务流程。上一轮费用页有实现与验证证据，属于实际进展；完整目标继续进行。

## 本轮文件

- `src/frontend/src/views/samples/SampleFulfillmentView.vue`、`sampleFulfillment.scss`、`SampleFulfillmentView.spec.ts`。
- `src/frontend/src/components/samples/SampleFeedbackRequotationDialog.vue`、`sampleFeedbackRequotation.scss`、`SampleFeedbackRequotationDialog.spec.ts`。
- `src/frontend/src/styles/crm/_sample-dialog.scss`：新增具名弹窗公共样式 mixin，仅用于这两个样品弹窗范围，复用 Token 和 sample-controls，无全局 Element Plus 覆盖。
- `src/frontend/src/App.vue`：仅将 sample-fulfillment 接入现有 crmV2Route。
- `qa/sample_fulfillment_figma_readonly_20260911.cjs`、本报告及总映射。

复用 SampleStatusTag、CustomerActivityTag、既有再报价弹窗、PageContainer/ErpLayout、按钮及表单控件；未新增公共 Vue 组件或依赖。原有普通 CSS 改为 SCSS。

## 实现与修复

- 物流概览 118px、闭环进度 86px、主侧栏 1142:474 比例、轨迹/反馈及右侧检查/提醒/来源区对齐原型。
- 闭环展示改为已寄出、已签收、待反馈、客户确认、订单解除阻塞。未知订单状态保持待核验，不将前置事实通过冒充订单解除阻塞。
- 保留真实创建寄送、确认寄出、人工签收、异常、物料进度、客户反馈及确认、历史报价复制接口。
- 按后端状态和权限限制反馈、寄送、签收、异常、进度操作；保存检查 ETag，忙态禁止重复操作和修改数量，失败保留输入。
- 页面已有样品但物流加载/刷新失败时显示错误并可重试。联系人和收货地址加载失败单独提示，不冒充业务资料不存在。
- 反馈保存期间禁止取消、遮罩、Esc 及关闭按钮，避免输入被重开动作清空。
- 再报价弹窗：720px、同客户报价单选、目标报价/有效期双列、反馈说明折叠保留、真实新版本/新报价业务分支。加载失败可重试；关闭后丢弃旧请求响应；缺少版本、无效来源或权限不足不提交。
- 修正弹层受父页面 40px 控件及全局 draggable 顶距 16px 影响的问题；局部控件恢复 34px，弹窗居中。

## 仍有差异及接口边界

- 原图通用壳层、旧冷色与标签由用户后续确认的 Warm ERP 规范覆盖。
- 物流摘要采用现有接口可验证字段（实际寄出、地区、收件人、实际签收、本次寄送物料），未将收件人冒充签收人，未伪造预计签收及有效时效。
- 原图“同步物流”“查看承运商”服务仍未接入，入口禁用。自动提醒区描述已实现的签收创建待办机制，不声称当前记录已经生成待办；48 小时主管升级未接入。
- 当前页没有订单解除阻塞的权威接口，因此显示“待订单核验”和明确说明，没有执行订单操作。
- 真实物料进度和额外反馈存在时允许区块纵向增长；再报价保留整改说明和可编辑反馈备注，当前夹具高度 608px，与原图示例高度存在差异。
- 未接入生产数据库的写流程验收。本轮不能证明寄送、反馈、再报价整个真实写链路已完成，也不代表全部打样页面完成。

## 验证

- 最新专项：`npm run test -- src/views/samples/SampleFulfillmentView.spec.ts src/components/samples/SampleFeedbackRequotationDialog.spec.ts`，10/10 通过。
- `npm run type-check` 通过。最终 `npm run build` 通过（包含 vue-tsc -b，Vite 24.26 秒）。仍有原有第三方 PURE 和大包警告。
- 项目未配置 lint 脚本，没有新增依赖来替代。
- 独立代码审查发现并修复：已有内容刷新错误不可见、创建寄送期间数量可修改、反馈保存时遮罩可关闭；复核对应问题已解决。
- 真实浏览器：从列表进入真实 FINISHED 详情，再访问同记录物流路由；1920×1080/1440×900 无横向溢出，侧栏 230/64px、顶栏 64px、概览 118px、进度 86px、按钮 34px、标签 24px，返回详情正常。页面异常 0，业务写请求 0。
- 再报价独立浏览器视觉夹具：仅在无头浏览器替换 GET 数据，拦截所有业务写请求，未改数据库。两种尺寸下宽720、高608、输入/按钮34px，无内部溢出，垂直居中（顶距236/146px），取消正常。此结果是视觉验证，不是后端联调证明。
- 截图和测量：`outputs/sample_fulfillment_figma_20260911/`；`evidence.json` 为真实页面，`requote-visual-fixture.json` 为独立夹具，两者分开保存。最终日志 `outputs/sample_fulfillment_build.log`。

下一步继续库存、出库、借出及其批量弹窗/单据页面，再补全隔离写流程和全模块验收。
