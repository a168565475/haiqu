# S6 联合验收：只读准备核查与浏览器联合验收

日期：2026-10-01。状态：只读准备核查、隔离后端联测和隔离浏览器联合验收完成；没有修改正式配置、业务代码或正式业务数据。

## 核对结果

1. 当前正式数据库的 `PublicStockCutoverControl` 状态为 `PUBLIC`。虽然容器环境变量没有显式设置两个公共库存开关，但运行时 `public_flow_enabled()` 和 `public_issues_enabled()` 均为 `True`，不需要重复修改配置。
2. 当前正式 compose 已启用 `TUBE_OUTSOURCING_ENABLED=True`。
3. 正式浏览器只读打开并检查了以下入口：
   - 委外统一列表
   - 新建管材外发单
   - 半成品库存
   - 半成品入库记录
   - 喷塑入库
   - 厂内半成品入库
   - 生产领料
4. 上述检查没有页面错误、接口错误或业务写请求。统一列表当前没有新管材测试单，显示的是现有旧流程记录；这不代表新管材入口关闭。

## 隔离后端联测

在独立测试库 `test_tube_s3_codex_s6_20261001` 运行以下专项：

- `apps.outsourcing.tests.test_unified_tube_orders`
- `apps.outsourcing.tests.test_tube_actions_api`
- `apps.outsourcing.tests.test_tube_receipts_api`
- `apps.outsourcing.tests.test_tube_ended_reads`

共 77 项，全部通过。覆盖三种管材来源、根米换算、公共半成品支数、厂内未入库半成品、一次实际发出、待发取消、一次最终回货、少回/零回、权限、幂等和并发扣减。测试库已删除。

## 本阶段没有做的事

- 没有在正式库创建外发单、发料、回货或半成品入库记录。
- 没有启用或修改环境开关。
- 没有做旧管材转换。
- 没有删除旧退回、返工、结清或补登记代码。

## S6 第二阶段：隔离浏览器联合验收

使用当前源码启动前端（1920×1080）和独立 S3 隔离数据库，登录 `wage-admin` 后仅打开页面和执行 GET 查询；所有非 GET 请求均在浏览器侧阻断。本次浏览器检查结果：10 个入口全部返回 200，页面错误 0，接口错误 0，业务写请求 0。

已检查：委外统一列表、原材料／未喷塑半成品／未入库半成品三种管材外发单详情、半成品库存、半成品入库记录、喷塑入库、厂内金工半成品入库、装配生产领料新建及管材外发新建。统一列表显示 5 张隔离管材外发单，来源标签分别为“原材料”“未喷塑半成品”“未入库半成品”；详情显示支数、扣根、扣米、实收支数和一次结束状态。半成品库存按“未喷塑／已喷塑”区分，半成品入库记录区分“厂内入库／外发入库”。

装配生产领料在正确的 `ASSEMBLY` 入口打开“添加半成品”后，显示 2 条公共半成品候选：同一部位、材质和规格下的“已喷塑 38 支”和“未喷塑 300 支”。选择器无多选框、按行“添加”，匹配依据为 BOM 部位、材质、规格和颜色；本次仍没有提交领料。

设计规范现场测量：表头 44px、数据行 40px、输入框 32px；和已确认的 ERP 规范一致。对应截图和结果：

- `qa/tube_revision_s6_20261001/s6-outsourcing-list.png`
- `qa/tube_revision_s6_20261001/s6-metal-receive.png`
- `qa/tube_revision_s6_20261001/s6-material-issue-semi-picker-assembly.png`
- `qa/tube_revision_s6_20261001/browser_joint_qa.json`
- `qa/tube_revision_s6_20261001/material_issue_semi_picker_assembly.json`

## 下一步

## S6 第三阶段：隔离库一次真实写入

已确认后，在隔离库办理外发单 `WF-20260930-232A381E9570`：

1. 通过页面“确认实际发出”，实际发出 20 支，日期为 2026-10-01。服务端按每根 10 支换算并扣除 2 根、10.10 米，单据状态变为“加工中”。
2. 通过“喷塑入库”选择该单，入库仓库为“隔离SEMI仓”、库区为“测试区”，实收 20 支，日期为 2026-10-01；页面以一次整单登记完成回货，单据状态变为“已结束”。
3. 回货凭证为 `WFHK20261001131004131922A8AF`，实发 20 支、实收 20 支、差额 0 支。

写入后的只读对账结果：5.05 米原材料池为 86 根、434.30 米；已喷塑公共半成品由 38 支增加至 58 支；未喷塑半成品仍为 300 支；统一外发列表显示该单已结束、实发 20 支、回货 20 支。这个结果验证了“支数 → 整根 → 米数扣减”和“回货按支数进入已喷塑公共半成品”的闭环。正式库仍未写入。

第三阶段证据：

- `qa/tube_revision_s6_20261001/s6-raw-after-dispatch.png`
- `qa/tube_revision_s6_20261001/s6-tube-return-picker-after-dispatch.png`
- `qa/tube_revision_s6_20261001/s6-raw-after-receipt.png`
- `qa/tube_revision_s6_20261001/s6_dispatch_result.json`
- `qa/tube_revision_s6_20261001/s6_receipt_result.json`
- `qa/tube_revision_s6_20261001/s6_after_receipt_state.json`

S6 已完成。旧管材转换（S7）和旧代码清理（S8）继续按此前约定暂缓。

证据截图：`qa/tube_revision_s6_readonly_20261001-formal-list-1920.png`、`qa/tube_revision_s6_readonly_20261001-last-page-1920.png`。
