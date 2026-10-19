# 企业微信第一阶段独立审查记录

日期：2026-10-19。工作区：`E:/workspace/_project/project001_haiqu_ERP_CRM`；分支：`codex/wecom-phase1`。

本记录包含回调异常脱敏问题的定向复查，以及扩大后端回归中 10 项失败的只读因果分析。审查未修改业务代码、未启动测试、未调用真实企业微信接口、未写数据库。客户端 `client.py` 由本审查者实施，不作为独立审查对象。

## 回调异常脱敏问题：修复覆盖原问题

原问题：回调视图在清理 OAuth 查询参数之前执行 `schema_is_ready()` 数据库查询；认证中间件也可能更早加载用户。上述位置异常时，开发错误页可能包含原始 `code/state`。仅在视图内调整数据库查询顺序不足以覆盖认证阶段。

当前源码已覆盖这两个异常窗口：

- `src/backend/config/settings.py:71` 将 `WeComOAuthSensitiveMiddleware` 注册为中间件首项，先于会话、认证和 ERP 会话门禁运行。
- `src/backend/apps/wecom/middleware.py:13` 在进入下游前启用始终生效的异常过滤器，清空 `request.GET`，清理 `QUERY_STRING/RAW_URI/REQUEST_URI`；原始参数仅保存在请求私有属性。解析查询字符串前已清理错误报告可见的请求字段，相关函数标记 `sensitive_variables()`。
- `src/backend/apps/wecom/views.py:154` 先调用 `take_callback_parameters()` 消费私有参数，再执行 `schema_is_ready()`；直接调用视图的路径也会先应用请求保护。
- `src/backend/apps/wecom/middleware.py:47` 在 `finally` 清理未消费的私有参数，保留原异常传播，不伪装成功。

已阅读 `src/backend/apps/wecom/tests/test_sensitive_middleware.py` 的 4 项测试，覆盖 DEBUG 模式下迁移查询异常、认证加载用户异常、参数传递并消费、下游异常传播并清理。主代理同步这 4 项 SimpleTestCase 已通过；本审查未独立复跑。

结论：从当前中间件顺序、参数生命周期和对应测试覆盖判断，原指出的视图前及认证阶段异常脱敏问题已修复。本结论限定于该问题，不替代真实企业微信登录或部署验收。

## 扩大回归的 9 项工艺权限失败

主代理提供的失败位置：`CraftResourceApiTests.setUp()` 调用旧金工测试工厂，在 POST 原外发交接时返回 400：`部位不属于当前BOM或报工依据不完整，请刷新并核对资料。`

当前源码的因果链：

1. `src/backend/apps/access_control/tests/test_resource_scopes.py:198-200` 只在测试工厂期间关闭模块权限和资源范围开关，未覆盖管材新流程开关；9 项测试均在初始化阶段失败，尚未执行各自权限断言。
2. `compose.yml:85` 为后端配置 `TUBE_OUTSOURCING_ENABLED=True`。`src/backend/apps/material_issues/p4_services.py:648-664` 在此开关打开时，对旧原外发交接也调用现行管材数量依据校验。
3. 复用工厂 `src/backend/apps/material_issues/tests/test_metal_processing_p4.py:38` 只登记 12 支旧加工完成量；基础工厂未建立对应的批准工价方案和报工记录。`src/backend/apps/material_issues/processing_services.py:55-69` 的完成登记只更新加工来源并创建 `MetalProcessingCompletion`，不会创建 `WorkReport` 或工价方案。
4. `src/backend/apps/inventory/tube_processing_services.py:119` 读取批准工价方案，`:191-193` 在部位缺少有效工序时加入阻断原因，`:225` 将 `basis_ready` 置为假；`:288-289` 随后抛出与失败输出一致的 400。

归因：旧加工工厂缺少新管材校验所需依据，与当前 Compose 功能开关组合不一致。企业微信等待角色门禁的拒绝响应是 403 `WECOM_ROLE_REQUIRED`，本次请求已进入金工业务校验并返回上述 400，未发现企业微信改动的直接因果。

建议后续单独修正测试前提：若这组权限测试意在覆盖旧金工链路，明确关闭管材新流程开关；若意在覆盖开启新流程的链路，则补齐真实模型的批准工价和报工测试数据。不要放宽业务数量校验来迁就工厂。

## 扩大回归的 1 项文件权限失败

主代理提供的失败断言：`src/backend/apps/access_control/tests/test_sales_policy.py:240` 预期新上传文件可读，实际查询不存在。

当前源码可直接解释该结果：

1. 同文件 `:239` 创建 `BusinessFile` 时没有指定 `scan_status`。
2. `src/backend/apps/files/models.py:38` 默认扫描状态为 `PENDING`；`:15` 允许使用的状态仅为 `CLEAN/SKIPPED`。
3. `src/backend/apps/access_control/sales_sources.py:13` 在判断上传归属和业务来源权限之前，已排除待扫描文件。因此该测试尚未走到其目标的“首次绑定业务前，上传者可读”判断。

归因：文件测试工厂缺少安全扫描已通过的前提。该断言直接调用 selector（查询函数），不经过企业微信中间件。建议在此权限测试的文件工厂显式设置 `CLEAN`；不要放宽扫描过滤。

## 证据边界与交付影响

- 已执行只读 `rg`、`Get-Content` 和 `git diff HEAD -- <相关文件>`。上述失败涉及的测试文件、金工服务、管材依据服务、文件模型、文件查询函数及 Compose 配置均与当前 `HEAD` 一致，没有本次企业微信工作区改动。
- 未运行修改前基线，也未独立复现这 10 项失败。不能据此声称“历史测试已经失败”或“基线必然失败”；本记录依据主代理的失败输出和当前源码说明可核实的触发条件。
- 这 10 项不是已确认的企业微信实现回归阻断，但扩大回归仍未通过，9 项工艺权限断言实际没有获得执行证据。企业微信专项检查结果与扩大回归结果必须分别报告，不能将项目整体描述为全部验收通过。
- 本次审查仅新增本 Markdown 报告；未创建临时数据库、上传副本或浏览器目录，无临时资源待清理。
