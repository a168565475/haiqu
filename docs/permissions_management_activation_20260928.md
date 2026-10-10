# 权限管理正式启用记录

2026-09-28，用户明确确认 [正式启用审阅](permissions_stage6_activation_review.md) 后执行。**权限管理已开放；销售与其他业务范围限制尚未开启。**

入口：[权限管理](http://localhost:8080/settings/access)，使用现有 admin 登录。20 个角色为空，可自行配置查看、新增、编辑、删除、审批和专项操作；角色名称不预置岗位权限。

## 实际执行与结果

1. 再次只读预检，账号、员工、角色、迁移、历史授权及开关与批准清单完全一致。没有扩大执行范围。
2. 19:39 暂停主后端接收请求。在维护期间生成完整 PostgreSQL 自定义格式备份，校验 `pg_restore --list` 和 SHA256 后才执行迁移。
3. 仅执行 access_control 0001—0005，全部成功。为保持维护窗口内业务请求关闭，通过 `docker compose run --rm --no-deps -T backend` 运行同一镜像、挂载和正式数据库配置的管理命令；未启动另一个业务服务、未执行其他应用迁移。
4. `initialize_access_roles` 预览缺少 20 个角色且无冲突；仅在初始化命令进程设置管理开关并执行 `--apply`，创建 20 个空角色、20 个权限组和 20 条由 admin 员工记录的创建审计。
5. 仅修改 `.env` 的四个批准变量，其他配置内容保持原状。重建主后端；19:44:17 后端健康接口及前端认证代理均返回 200，容器 healthy。其他服务未重建。
6. 正式主库后检无待迁移项；真实 admin 已有登录会话仍有效，1920×1080 浏览器只读验收通过；未重置密码、创建新登录会话或修改业务数据。

| 配置 | 当前值 |
| --- | --- |
| ACCESS_MANAGEMENT_ENABLED | true |
| SALES_ACCESS_ENABLED | false |
| MODULE_ACCESS_ENABLED | false |
| DEV_AUTO_LOGIN_ENABLED | false |

角色：总经理、厂长、采购、金工主任、装配主任、车缝主任、仓管、跟单、品质、财务、外协、PMC、行政、技术、喷塑收发料、金工打样、布面打样、出纳、业务员、客户经理。没有“查看全部权限”角色。

## 数据核对

维护窗口内对全部既有表逐行散列，输出只保留计数和摘要，不输出数据内容。245 张既有表保持完全一致，包括账号、员工、旧直授、用户组成员、组权限、员工角色关系及业务单据。

预期变化：5 条迁移记录、3 个内容类型、131 个权限目录项、20 个权限组、20 个角色及 20 条创建审计。新增 `role_action_grant`、`access_sales_team`、`access_sales_team_membership` 三张表均为空。10 个账号、44 名员工保持不变；未分配员工角色、未创建团队、未更改客户或单据负责人。

验证脚本首次使用了不带 `access_` 前缀的团队表名称，导致检查停止在环境修改之前；核对实际模型 `db_table` 后按正确名称重新验证通过。没有修改数据库来迎合检查，没有重复执行迁移或初始化。

## 验证证据与边界

- [迁移日志](../qa/permissions_stage6_20260928/activation_migration.txt)、[角色预览](../qa/permissions_stage6_20260928/activation_roles_preview.txt)、[实际初始化](../qa/permissions_stage6_20260928/activation_roles_apply.txt)。
- [表数据对比](../qa/permissions_stage6_20260928/activation_data_comparison.json)、[启用前预检](../qa/permissions_stage6_20260928/activation_preflight.json)、[启用后预检](../qa/permissions_stage6_20260928/activation_postflight.json)、[实际开关](../qa/permissions_stage6_20260928/activation_flags.json)。
- [正式浏览器结果](../qa/permissions_stage6_20260928/activation_browser_results.json)：12 项检查通过，admin 会话、20 个空角色、470 项权限目录、无横向溢出及未登录拒绝均已验证，0 JS 错误、0 HTTP 5xx；[页面截图](../qa/permissions_stage6_20260928/activation_admin_management.png)。复用有效的现有会话，凭据仅在进程内存中，未记录到脚本或证据。
- 普通账号没有可复用的有效 HTTP 会话，因此在 READ ONLY 事务内用真实数据库的 9 个非 admin 账号进行 DRF 请求分派：管理读取与新增共 18 次均返回 403；另外验证 20 条审计均来自 admin，470 个目录权限全部可用。[结果](../qa/permissions_stage6_20260928/activation_policy_results.json)。此项验证权限策略，不冒称为普通账号密码登录测试。
- [健康检查](../qa/permissions_stage6_20260928/activation_health.json)通过。没有修改业务实现，未重复运行此前已完成的全部回归；此前已披露的前端及兼容测试遗留失败继续见[阶段 6 报告](permissions_stage6_20260928.md)。

## 备份与后续

备份路径：`backups/permissions_activation_20260928T113955571Z/haiqu_erp_before_permissions.dump`，8,354,349 字节。SHA256：`76bb1ee116dcb6f8ff7ba53651645e1c46a6d98ce869b766f83944e1e1351084`。[备份元数据](../qa/permissions_stage6_20260928/activation_backup.json)。备份及 `.env` 均已核实排除 Git 跟踪；未提交或推送。

本次验证了备份归档目录可读取，没有执行整库恢复，不能视为恢复演练已完成。恢复边界继续遵守已批准审阅：仅关闭管理时保留表、空角色和审计；不反向删除迁移，不自动覆盖整库。

下一步由 admin 配置角色权限、员工和销售团队，明确非本人审批的处理人后，再审阅开启 SALES_ACCESS_ENABLED 与 MODULE_ACCESS_ENABLED。**当前新“本人/团队”业务范围尚未生效；角色分配可能通过保留的旧授权机制增加操作能力，配置准备期间不可将新范围当作已经生效的隔离边界。**

企业微信、客户转移、历史账号删除仍不在此次执行范围。
