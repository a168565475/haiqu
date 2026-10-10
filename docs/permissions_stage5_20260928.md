# 权限第 5 阶段：其他模块与审批

状态：本阶段已获用户确认；后续第 6 阶段已完成联合回归并仅开放权限管理，主库已创建 20 个空角色，销售和其他业务范围开关仍关闭。见 [阶段 6 报告](permissions_stage6_20260928.md)及[正式启用记录](permissions_management_activation_20260928.md)。下文保留本阶段当时的验证与执行边界。

范围：按模块开放生产、采购、库存、BOM、外发、报工与基础字典的操作权限；样品支持销售范围和生产模块范围；任务每项操作独立范围；实际审批禁止提交人自审，包括 admin。保留原有状态、事务、CSRF、ETag 和独立历史授权。客户转移、企业微信接入不在本阶段。

主库不执行迁移、初始化或开启新权限。隔离测试库 test_haiqu_access_stage5_20260928；新 MODULE_ACCESS_ENABLED 默认 False。

## 交付行为

- 生产、采购、库存、BOM、外发、报工和基础字典沿用模块权限；新增必要的独立操作授权，查看、编辑、完成、审批、启停和归档不相互替代。采购合同模板与供应商采购单保留各自权限。
- 样品支持本人、团队、全部及生产模块范围；销售范围统一取客户当前主负责人。前端根据当前记录返回的权限显示操作，团队查看不会扩大本人编辑或报工权限。仅报工人员可以进入报工表单，基础产品与打样数量保持锁定。
- 任务的编辑、完成、改期、取消和批量操作各自校验范围；批量操作同时校验批量授权及实际操作授权。列表、详情、来源选项及附件执行相同的数据可见性约束。
- 生产或采购模块可读取完成业务所需的客户、销售订单及样品来源摘要；不因此取得完整客户、订单、询盘或样品的查看权限。
- 审批提交人按当前提交事件或 submitted_by 字段核验，不用最初创建人猜测。兼任角色或 admin 身份不能绕过禁止自审；既有指定审批人约束继续有效。无法核实提交人的历史审批要求重新提交。
- 样品费用重新提交会关闭旧待审批记录，并以审计记录关联本次费用与审批；通用报价审批入口拒绝处理样品费用审批，避免借用另一种审批权限。
- 独立的历史直授、分组和角色权限保留兼容。角色投影产生的分组权限不视为独立旧授权，避免撤权后残留。

## 代码、迁移与开关

修改前保存了 1247 个代码文件，清单见 [baseline_manifest.json](../qa/permissions_stage5_20260928/baseline_manifest.json)。与本阶段基线比较，58 个文件修改、7 个文件新增、没有基线文件被删除；见含 SHA256 的 [change_inventory.json](../qa/permissions_stage5_20260928/change_inventory.json)。API 操作盘点见 [action_inventory.json](../qa/permissions_stage5_20260928/action_inventory.json)。文档及 `.env.example` 不计入该代码基线。

新增 `access_control/0005_module_operation_permissions.py` 为操作权限的模型选项迁移，没有修改历史迁移。本阶段没有在主库执行任何权限迁移或角色初始化。`ACCESS_MANAGEMENT_ENABLED`、`SALES_ACCESS_ENABLED`、`MODULE_ACCESS_ENABLED` 主库均为 False。

隔离测试与浏览器数据分别使用 `test_haiqu_access_stage5_compat_20260928`、`test_haiqu_access_stage5_20260928`；修改前代码对照使用 `test_haiqu_access_stage5_baseline_20260928`。浏览器使用真实本地 API 和隔离验收数据，非正式业务数据。测试账号密码仅放入忽略的 `.tmp` 文件，没有写入报告。

验收结束后已停止本次 QA 后端容器及 8185 端口的 Vite 服务，保留测试库与证据。凭据文件的忽略规则写入本地 `.git/info/exclude`；没有提交、推送或部署代码，也未修改独立财务系统。

## 验证证据

| 检查 | 结果及证据 |
| --- | --- |
| 权限后端 | 85 项通过，包含前四阶段及本阶段 27 项模块/审批测试；[日志](../qa/permissions_stage5_20260928/access_final_verified.txt) |
| 前端定向回归 | 7 个文件、39 项通过；[日志](../qa/permissions_stage5_20260928/frontend_regression.txt) |
| 类型与生产构建 | `npm run build` 内含 `vue-tsc -b`，通过；存在构建包体积提示；[日志](../qa/permissions_stage5_20260928/frontend_build_final.txt) |
| 迁移漂移 | `makemigrations --check --dry-run`：No changes detected；[日志](../qa/permissions_stage5_20260928/migration_check_final.txt) |
| OpenAPI | 0 错误，562 条警告（182 种），不能称零警告；[日志](../qa/permissions_stage5_20260928/openapi_check_final.txt) |
| 主库只读复核 | admin 仍有效且为超级管理员；三个开关关闭；access_control 迁移未执行；[结果](../qa/permissions_stage5_20260928/main_readonly_final.json) |

权限测试包含：空权限直接访问拒绝、独立操作不可代替、本人/团队隔离、必要来源摘要、基础字典状态旁路、批量任务范围、样品创建来源越权、仅报工、历史明细授权不可放大报工范围、实际提交人自审拒绝、费用审批绑定与过期审批拒绝。Session、CSRF、ETag、事务与业务状态保护继续保留。

### 扩大回归的边界

第一次扩大回归在复用测试库运行，受迁移初始字典缺失和 TransactionTestCase/serialized_rollback 数据生命周期影响，298 项实际执行、61 失败、82 错误，见 [原始日志](../qa/permissions_stage5_20260928/backend_regression.txt)，该次结果不作为通过依据。

随后在新建隔离数据库运行 197 项兼容回归，160 项通过、36 失败、1 错误，见 [兼容回归日志](../qa/permissions_stage5_20260928/compat_regression.txt)。已将本阶段修改前的 Python 基线复制到容器独立临时目录，在另一测试库复跑全部 37 项失败用例：同样 36 失败、1 错误；逐项比较测试名称、错误类型和关键错误信息（只归一化随机 UUID），全部一致，见 [逐项对照结果](../qa/permissions_stage5_20260928/baseline_failure_comparison.json)。因此这 37 项为本阶段之前已有的回归差异，不能称旧功能测试全绿，也不能把该限定对照推断为全系统无回归。

失败集中在旧采购测试的空采购明细/不可采购预期、旧管材口径入库被新业务规则拒绝、生产数量同步的整根取整预期，以及半成品需求标识预期。本阶段没有为了让旧测试通过而修改这些业务规则。对照脚本及原始结果分别见 [baseline_failure_replay.py](../qa/permissions_stage5_20260928/baseline_failure_replay.py)、[对照日志](../qa/permissions_stage5_20260928/baseline_failure_replay.txt)。

### 浏览器及审阅

1920×1080 浏览器 **40 项检查通过、11 张截图**，无 JavaScript 错误、无 HTTP 5xx，各页面无整体横向溢出，见 [结果](../qa/permissions_stage5_20260928/browser_results.json) 与 [脚本](../qa/permissions_stage5_20260928/browser_acceptance.cjs)。覆盖团队任务只读、本人任务操作、越权直接请求、采购及模板只读、生产跨销售归属查看样品、仅报工表单、字典编辑不可启停、空权限页及 admin 权限目录。

真实写入仅发生于隔离验收数据：本人任务编辑验证了 CSRF、ETag、旧版本冲突；仅报工账号从真实表单保存裁剪数量，重新 GET 确认持久化。报工按钮实际高度 32px，打样数量被禁用而报工数量可编辑。最初简化样品缺必填基础信息导致原有校验拦截，补齐测试数据后完成保存；没有修改该校验规则。

截图示例：[团队任务只读](../qa/permissions_stage5_20260928/02_team_task_readonly.png)、[仅报工表单](../qa/permissions_stage5_20260928/08_report_only_form.png)、[权限管理](../qa/permissions_stage5_20260928/10_admin_catalog.png)。

界面依据根目录 `DESIGN.md` 第 10 章和已确认的权限管理设计；本阶段主要调整操作可见性与可用性，沿用页面布局，不宣称全站像素级重验通过。

独立审阅已检查模块权限、任务/样品范围、批量与幂等路径、审批绑定、前端操作联动；指出的样品来源越权、历史明细报工范围及仅报工入口等问题已修正。末轮限定复审未发现新增 P1/P2，范围与限制见 [复审记录](../qa/permissions_stage5_20260928/code_review.md)；审阅没有代替测试或浏览器验证。

## 下一阶段边界

本阶段验收后才进入第 6 阶段整体回归与启用准备。实际迁移、20 个目标角色补缺、账号角色分配及开关启用前，须提供具体影响与恢复方案；目前员工权限尚未在主库正式生效。客户转移、团队调动、企业微信实际接入均未开发。
