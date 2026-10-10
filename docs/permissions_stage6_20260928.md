# 权限第 6 阶段：联合回归与启用准备

状态：本阶段联合回归和启用准备已完成；用户随后确认管理启用范围，正式库已迁移并创建 20 个空角色，权限管理已开放，见 [正式启用记录](permissions_management_activation_20260928.md)。销售和其他业务范围开关仍关闭，不能视为全部员工权限隔离已经生效。以下回归及预检记录保留其执行时状态。

用户已确认第 5 阶段并授权推进本阶段；真实库写入继续按已确认方案第 7 节先展示具体影响。本阶段全部写入测试发生在隔离数据库，主库只读事务预检。

## 本阶段交付

- 通过真实管理 API 创建角色、配置不同操作范围并分配多个角色，联合验证客户、样品、任务及生产模块。团队查看不会扩大本人编辑；移除团队角色后保留本人角色。
- 撤权后同一员工会话的后续业务请求被拒绝；停用团队收回团队范围，独立模块权限仍保留；账号停用后重新启用不会复活旧会话，必须重新登录。
- 保留历史独立直授；移除新角色不清除既有授权来源。初始化命令默认预览，20 个空角色可幂等补建，不自动给员工分配。
- 有效授权响应按实际开关返回 ENABLED / PARTIAL / DISABLED，替换旧的固定待接入状态。
- 补齐个人保存视图的查看、新增、编辑目录，仅允许 OWN。现有 API 继续按当前员工过滤；无该权限时任务中心不请求保存视图或显示保存入口，任务主体正常工作。admin 也不能读取别人的个人保存视图。
- 补齐 8 个旧前端测试文件中的新授权接口 mock，保留既有业务断言；新增任务中心缺少保存视图权限的回归用例。

代码范围和基线散列见 [change_inventory.json](../qa/permissions_stage6_20260928/change_inventory.json)。本阶段修改 13 个既有源码/测试文件，新增 2 个隔离配置及 1 个联合测试文件。工作区另有工价页面、样式、路由等 9 个文件被其他任务修改，已单独标记；没有覆盖或清理。构建与全量前端结果是当次共享工作区快照，不代表其他任务未来修改已验证。

## 实际验证结果

| 检查 | 结果与证据 |
| --- | --- |
| 后端权限、认证与 API 基础回归 | **119 项通过**，包含新增 10 项联合测试；[最终日志](../qa/permissions_stage6_20260928/backend_final.txt) |
| 前端全量测试 | **779 项：772 通过、7 失败**，115 个文件；[最终日志](../qa/permissions_stage6_20260928/frontend_final.txt) |
| 前端失败基线对比 | 在本阶段开始前的源码快照中复跑相关 4 个文件，30 项中 23 通过、7 失败；测试名称和首条错误逐项相同；[基线日志](../qa/permissions_stage6_20260928/frontend_baseline_remaining.txt)、[对比](../qa/permissions_stage6_20260928/frontend_failure_comparison.json) |
| 类型检查与生产构建 | `npm run build` 包含 `vue-tsc -b`，通过；仍有既有构建体积提示；[日志](../qa/permissions_stage6_20260928/build_final.txt) |
| 真实浏览器 | 1920×1080，**74 项检查通过、14 张截图、0 JS 错误、0 HTTP 5xx**；[结果](../qa/permissions_stage6_20260928/browser_results.json)、[脚本](../qa/permissions_stage6_20260928/browser_acceptance.cjs) |
| 数据库迁移漂移 | `makemigrations --check --dry-run` 返回 No changes detected；[日志](../qa/permissions_stage6_20260928/migration_check.txt) |
| 隔离迁移与角色初始化演练 | 新建阶段 6 隔离库、完整迁移成功，补建 20 个空角色；[迁移](../qa/permissions_stage6_20260928/migration_rehearsal.txt)、[初始化](../qa/permissions_stage6_20260928/role_initialization_rehearsal.txt) |
| 有界代码审查 | 初审及个人视图补充复审未发现可证实 P1/P2；属于静态范围审查，不是全系统安全认证；[审查记录](../qa/permissions_stage6_20260928/code_review.md) |

浏览器覆盖独立登录、本人/团队/外团队、只读按钮与直接 API 写入拒绝、CSRF、缺少/过期 ETag、多角色合并、同会话撤权、停用恢复、个人视图隔离，以及样品仅报工的真实保存。关键截图：[多角色任务页面](../qa/permissions_stage6_20260928/11_multiple_roles.png)、[撤权后](../qa/permissions_stage6_20260928/12_revoked_permissions.png)、[停用恢复要求重新登录](../qa/permissions_stage6_20260928/13_suspended_session.png)。最终多角色截图已复看，未出现先前保存视图请求导致的红色权限提示；没有改页面视觉设计。

最终复验前曾因隔离后端刚重启、尚未监听导致 Vite 代理 socket hang up，浏览器登录失败；[启动时失败记录](../qa/permissions_stage6_20260928/browser_startup_failure.json)保留。确认后端与代理 `/api/auth/me/` 均返回 200 后重新完整运行，最终 74 项通过；没有用重试真实业务写入掩盖错误。

后端首次在 `test_haiqu_access_stage6_20260928` 完成 117 项；增加两项测试后最终 119 项使用已有隔离阶段 5 测试配置运行，避开正被浏览器使用的阶段 6 夹具库。没有与浏览器共享同一个正在迁移/重建的测试库。OpenAPI 基础检查包含在后端测试中；仍有 schema 警告，不能报告成零警告。

前端 7 项失败涉及 ProductPickerDialog、MasterDataCenterView、SampleApplicationCreateView、SampleListView，本阶段前后相同；没有删除或放宽失败断言。第 5 阶段已经复现的 37 项既有业务兼容失败仍按[原报告](permissions_stage5_20260928.md)保留，本阶段不宣称全仓全部测试通过，也未重跑该 197 项兼容集合。

主要复现命令（后端和浏览器命令在 ERP 根目录，npm 命令在 `src/frontend`）：

```text
docker compose exec -T backend python manage.py test apps.access_control apps.core.tests.test_auth_api apps.core.tests.test_api_foundation --settings=config.permissions_stage5_compat_settings --keepdb --noinput --verbosity 1
npm run test -- --maxWorkers=4
npm run build
node qa/permissions_stage6_20260928/browser_acceptance.cjs
docker compose exec -T backend python manage.py makemigrations --check --dry-run
```

浏览器脚本依赖本阶段独立 8016 后端、8186 前端及已播种的隔离夹具，不能直接指向正式服务；运行凭据文件仅在本机临时目录并已排除 Git 跟踪。基线目录包含用于测试的 node_modules junction，不应对该目录进行未经路径核实的递归清理。

## 权限目录与路由盘点

[自动盘点](../qa/permissions_stage6_20260928/permission_coverage.json)记录实际可路由的 984 个动作，其中 714 个具有动作权限映射，目录共 470 个可配置权限码。其余路由包含认证、管理及自有权限策略；盘点只证明结构对应关系，不能当作全部路径均已执行的安全测试。

发现两个旧 PUT 更新入口（报价版本、报价行）没有动作映射。已有前端使用 PATCH；本阶段新增测试确认这两个 PUT 入口对普通员工和 admin 均拒绝，保持关闭，不自行新增整对象覆盖能力。

目录外历史权限保留明确边界：客户联系人导入由新增授权蕴含；旧客户归属管理属于本轮明确不更改的转移/共享功能，不新增角色勾选项。个人保存视图的 3 项遗漏已补齐，而非列为遗留问题。

## 主库只读预检与正式启用判断

最终主库预检时间为 2026-09-28 19:32（本地），[预检输出](../qa/permissions_stage6_20260928/main_preflight.json)由 READ ONLY 事务产生：

- 10 个登录账号、44 名员工、0 个角色；20 个目标角色没有名称、编码或组冲突。
- admin 为有效超级管理员并已绑定在职员工。历史 haiqu 没有员工绑定，账号保留，不猜测绑定关系。
- 只有 access_control 0001—0005 待迁移；三个新权限开关均为 False。
- 历史直授及分组保留；缺归属客户及历史单据负责人差异不回填，按已确认规则以客户当前主负责人为准。
- 样品厂长审核、样品仓库核对、生产订单确认、领料审核、工价审批，目前在有效账号/员工及动作权限层面仅 admin 是候选人。禁止自审后，admin 自己提交的记录需要其他合格处理人；不能拿历史测试账号擅自填补正式岗位。

据此先开放权限管理并创建 20 个空角色的建议，已获用户确认并执行。具体备份、5 个迁移、4 个环境变量、后端恢复及验证结果见[正式启用记录](permissions_management_activation_20260928.md)。配置好正式员工、团队和审批人后，再开启销售与其他模块业务范围。

[使用说明](permissions_user_guide.md)已准备。正式库备份已在后续管理启用时完成，整库恢复未执行；归档校验及隔离演练不等于生产恢复证明。未接入企业微信、未改客户转移、未清除历史账号或授权、未提交或推送代码。
