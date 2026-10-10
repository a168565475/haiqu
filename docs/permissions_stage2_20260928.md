# 权限第二阶段：基础后端与迁移审阅

日期：2026-09-28。范围依据 [已确认实施方案](erp_permissions_plan_20260928.md) 的阶段 2。用户已确认规范优化后的管理预览，本阶段实现角色授权基础后端，不进入第三阶段页面开发。

## 1. 本阶段交付

- 复用 `RoleProfile`、`auth.Group`、`EmployeeRoleAssignment`；新建 `RoleActionGrant` 保存每项权限的 OWN / TEAM / ALL / MODULE 范围。
- 角色新建默认空权限，支持修改说明、停用/恢复、复制授权；复制不带员工、账号或原生组成员。
- 按同一操作合并多角色范围，查看团队数据不扩大本人编辑范围。有效权限响应列出来源和版本摘要。
- 角色管理、员工角色分配、目录和授权审计接口仅允许有效的 `admin` 超级管理员及其有效员工档案。用户名叫 admin 但不是超级管理员、其他超级管理员、普通员工即使拥有全部 Django 原生权限，也不能使用本阶段管理接口。
- 角色修改、授权替换、复制和员工角色替换使用 `If-Match`；事务内锁定对象、更新权限组投影并写入现有 `AuditLog`。审计失败时整笔回滚。
- 新接口继续使用现有 Session + CSRF 和统一错误格式；未知输入字段、非法权限码、范围不匹配、重复授权、非法编号均被拒绝。
- 旧直授、原生组和历史角色授权保留，并列出为旧授权来源；不猜测成 OWN/TEAM，也不把旧账号说成无权限账号。管理接口遇到旧角色投影差异或原生组成员时明确拒绝覆盖，要求先审阅。
- `initialize_access_roles` 默认只预览，显式 `--apply` 才创建缺少的 20 个空角色；不根据角色名称授予权限，不包含“查看全部权限”，不分配成员。重复运行保持现有授权与状态。

## 2. 权限目录与后续接入

目录为明确白名单，现有模型自动生成但没有对应业务入口的权限不自动开放。依据阶段 1 路由/权限盘点及本阶段对动态基础资料接口的补查，包含 **423 个目录项**，其中 **89 个独立流程权限码**准备在阶段 4/5 接入。

这 89 项包括销售订单确认/完成、采购申请提交/分配/取消分配/生成供应商订单、采购退货确认/完成，以及 27 类基础配置各自的启用、停用、归档。基础配置“编辑”与这些操作分别存储，能够配置允许编辑而不授权归档。采购编辑使用独立 `change_purchaseorder`，报价模板编辑使用已有 `change_quotationtemplate`。

导出报价跟随报价查看，联系人导入跟随联系人新增；现有专用权限码通过权限组投影兼容。导入覆盖已有对象仍需编辑和对象范围，实际入口核验属于阶段 4/5。

目录返回 `integration_stage`，有效权限响应明确标识 `PENDING_STAGES_4_5`。本阶段仅验证存储、合并和管理能力，**没有宣称现有销售、生产接口已执行新数据范围**。同样，基础资料旧业务入口的共用权限判断将在阶段 5 替换；不能提前启用员工使用。

员工账号创建、密码重置、销售团队模型/API/页面及关闭自动 admin 登录在阶段 3；销售范围过滤在阶段 4；其他模块和自审限制在阶段 5。企业微信实际接入和客户业务转移继续不在本轮范围内。

## 3. 管理 API

前缀为 `/api/v1/access/`，所有管理路径统一执行上述管理员与员工状态校验。

| 方法与路径 | 行为 | 并发要求 |
| --- | --- | --- |
| GET catalog/ | 明确权限目录、范围与接入阶段 | 只读 |
| GET / POST roles/ | 分页角色列表 / 新建空角色 | 新建编码冲突拒绝 |
| GET / PATCH roles/{id}/ | 详情 / 名称、说明及停用状态 | PATCH 必须 If-Match |
| GET / PUT roles/{id}/grants/ | 读取 / 整体替换授权 | PUT 必须 If-Match |
| POST roles/{id}/copy/ | 复制为新角色 | 必须匹配源角色版本 |
| GET employees/ | 分页员工与账号摘要 | 只读 |
| GET / PUT employees/{id}/roles/ | 读取 / 替换员工角色 | PUT 必须匹配员工版本 |
| GET employees/{id}/effective-access/ | 每操作范围、角色和旧来源 | 只读 |
| GET audit-events/、audit-events/{id}/ | 授权日志列表与详情 | 只读，不能修改或删除 |

`/api/auth/me/` 在新管理功能启用时追加 `effective_access`，保留原来的 permissions/data_scope 字段。关闭时响应与原有契约一致，不查询新表。普通员工只能通过自己的认证响应取得自身摘要，不能访问其他员工管理接口。

错误响应沿用 `error.code / message / field_errors / request_id`：未登录 401、无管理能力 403、非法输入 400、资源不存在或非法 UUID 404、历史授权冲突 409、旧版本 412、缺少 If-Match 428、功能尚未启用 503。

## 4. 迁移范围与主库状态

| 迁移 | 影响 |
| --- | --- |
| access_control.0001_role_action_grants | 新增一张授权表，含角色/权限外键、范围校验、角色+权限+范围唯一约束；准备首批流程权限 |
| access_control.0002_independent_workflow_permissions | 补齐独立流程权限定义；迁移后 Django post_migrate 创建本应用总计 89 个权限元数据 |

不修改现有组织/员工/角色表字段，不回填或删除历史授权，不创建真实员工账号。角色初始化是单独命令，迁移本身不创建 20 个角色或分配权限。审阅 SQL 见 [第一份迁移 SQL](../qa/permissions_stage2_20260928/migration_0001.sql)。

主库只读核验结果见 [证据](../qa/permissions_stage2_20260928/main_readonly_evidence.json)：`haiqu_erp` 内新授权表不存在，本应用迁移记录为空；仍为 10 个账号、44 名员工、0 个角色/组/角色分配，admin 仍启用且为超级管理员。**本阶段没有执行主库迁移、角色初始化或真实业务写入。**

`ACCESS_MANAGEMENT_ENABLED` 默认 false，防止未迁移时读取新表，也防止基础后端完成就提前开放。后续执行主库迁移、初始化或启用前仍须按已确认范围审阅影响与恢复方式。

恢复边界：本阶段无需恢复主库，因为没有写入。未来角色授权已经使用后，不应直接倒退迁移删除授权表；应先关闭管理开关，审阅新增角色、授权、投影和审计，再按备份与具体变更清单处理。

## 5. 验证与代码审查

使用专用 PostgreSQL 测试库 `test_haiqu_access_stage2_20260928`，独立于主库和其他任务默认测试库；测试库保留用于复验。测试中的员工、账号、角色与密码均为该库的测试夹具。

执行命令：

```powershell
docker compose exec -T backend python manage.py check
docker compose exec -T backend python manage.py test apps.access_control.tests apps.core.tests.test_auth_api apps.core.tests.test_api_foundation --settings=config.permissions_test_settings --keepdb --noinput --verbosity 1
docker compose exec -T backend python manage.py makemigrations --check --dry-run
docker compose exec -T backend python manage.py spectacular --urlconf apps.access_control.api.urls --file /tmp/access_stage2_openapi.yaml --validate --fail-on-warn
```

最终 **49 项测试通过**（50.065 秒），包括本阶段授权测试及原有认证/API 基础回归，见 [测试日志](../qa/permissions_stage2_20260928/test_results.txt)。系统检查无问题，迁移漂移检查为 `No changes detected`，见 [日志](../qa/permissions_stage2_20260928/migration_check.txt)。本阶段 API 定义见 [OpenAPI](../qa/permissions_stage2_20260928/openapi_access.yaml)：路径相对于 `/api/v1/access/`，独立 schema 的 `--validate --fail-on-warn` 校验通过、无警告。原有全局 schema 在基础回归中仍有其他业务模块的类型注解、枚举重名和 operationId 警告，未将它们报告为已消除。

代码审查发现并修复三项：非法 UUID 写接口返回 500、管理员员工锁与授权审计外键检查形成的并发死锁、基础配置编辑/启停/归档共用权限码。分别新增异常编号、真实双连接并发和独立流程授权回归。审查复核未发现新增阻断问题。

本阶段未修改前端产品页面，因此不重复执行前端类型检查或视觉验收；第一阶段已通过的原型继续作为下一阶段界面依据。未提交、推送或部署。

## 6. 阶段停止点

提交本阶段后端代码、测试证据和迁移范围供用户确认。确认后进入阶段 3 的账号、角色与销售团队页面及真实联调；本阶段不跨阶段连续开发。
