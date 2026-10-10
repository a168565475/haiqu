# 样品费用页实现与验收 · 2026-09-11

本轮读取完整目标，按当前 Figma `czPqlJ7fXYn5cq4cbQyTFm / 258:5218` 实现费用页。完整打样目标仍在进行，本报告不代表全部页面完成。

## 修改范围

- `src/frontend/src/views/samples/SampleFeeView.vue`：三种费用方式、四列费用与约定、发票/凭证横行、备注、审批/账户/控制规则双栏；真实费用状态、权限、版本和忙态限制。
- `src/frontend/src/views/samples/sampleFee.scss`：替换原页面普通 CSS，使用已有 Warm ERP Token 和 sample-controls，局部样式。
- `src/frontend/src/views/samples/SampleFeeView.spec.ts`：10 项回归测试。
- `src/frontend/src/App.vue`：仅将 sample-fees 加入已有 crmV2Route，复用 64px 顶栏、haiqu 品牌和暖色布局。
- `qa/sample_fee_figma_readonly_20260911.cjs`：真实只读浏览器检查。

复用 SampleSection、CustomerActivityTag、useSampleUnsavedChanges、sample-controls、现有 PageContainer/ErpLayout/表单控件。没有新增公共组件、依赖、全局 Token 或后端改动。

## 业务行为

- 费用创建沿用真实 API，限 PENDING/PREPARING 和 decide_sample_fee 权限；提交携带 ETag，阻止重复点击、非法金额和缺少必填项。
- 凭证上传独立按真实文件接口限制终态，允许其他状态补传；检查 PDF/JPG/PNG、非空、10MB 上限。
- 上传后刷新附件与数据版本，保留尚未保存的费用输入；刷新失败显示错误并禁用写操作，重试仍保留输入。
- 当前核验标签使用接口状态，不再把已人工确认显示为待财务确认。
- 当前收费/免费不引用历史豁免审批；只有当前待审批豁免费用、待处理审批、指定审批人和审批权限同时成立才显示审批操作。
- 返回、未保存提醒、初始错误重试保留。

## Figma 差异与接口缺口

- 原画板通用壳层由用户后续确认的 230px 侧栏、64px 顶栏和 Warm ERP 规范覆盖。主/侧栏按 1146:470 比例分配；1920 实测 1153.08/472.92px，源自侧栏宽度变化后的可用空间。
- 为满足现有接口，费用表单增加币种、运费承担方一行；免费/豁免分支同一行显示确认人/审批人。因此表单和下方内容比原画板更高，允许页面纵向滚动。
- 费用草稿、样品发票生成、受控收款账户来源仍未接入。保留原型位置并禁用相应入口；已有 account_reference 只读展示，没有伪造账户或发票。
- 真实记录没有费用/审批/凭证时显示真实空态，不能与原型示例数据逐字相同。

## 验证证据

- `npm run test -- src/views/samples/SampleFeeView.spec.ts`：10/10 通过。
- `npm run type-check` 初次通过；随后全项目 build 曾遇到其他任务修改中的生产页未使用变量报错。未修改该文件，最新 `npm run build` 已通过（包含 vue-tsc -b），Vite 38.19 秒。
- 仍有第三方 PURE 注释和大包警告；项目未配置 lint 脚本。
- 独立只读代码审查发现并修复两项问题：凭证上传状态过严、历史审批错误引用。复核未发现追加问题。
- 真实浏览器从样品列表进入详情，再访问同一终态记录费用路由（终态无费用操作入口）。1920×1080 与 1440×900 通过，分别侧栏 230/64px，顶栏 64px，输入/按钮 34px，决策卡 126px，标签 24px，四列且无横向溢出，返回详情正常。
- 浏览器业务 API 写请求为 0，页面异常为 0。终态输入/提交/上传均禁用。提交、审批、补传和刷新失败分支由单测覆盖，未声称真实写流程已验收。
- 截图与测量：`outputs/sample_fee_figma_20260911/`，包含两种宽度首屏、底部及 evidence.json。构建日志：`outputs/sample_fee_build.log`。

## 下一步

继续按完整目标处理物流、反馈及再报价页面，然后完成库存/出库/借出、弹窗、单据及全模块验收。不得把本轮费用页通过当作整个模块完成。
