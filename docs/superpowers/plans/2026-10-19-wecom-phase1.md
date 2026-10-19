# 企业微信第一阶段接入实施记录

用户已确认预览并授权连续开发。2026-10-19 补充：实施时增加消息回调 Token 配置；同时保存 EncodingAESKey 配置，二者与网页登录 Secret 分区，首期不启用消息事件处理。预览保持不改。

## 边界与工作区

- 需求与已确认布局：本会话任务包及 `qa/wecom_phase1_20261019/review.md`、`preview.html`。
- 当前目录为用户指定项目，已有其他任务未提交内容；在 `codex/wecom-phase1` 分支按文件划分责任，只修改必要文件，不清理原有内容，不自动提交。
- Session + CSRF，后端权限边界；不新增依赖，不把测试替身当真实企微验收。
- 编写前向迁移，但不运行主库 migrate，不向业务库写验收记录，不部署。上述动作在实现和检查结果可审阅后按项目规则取得具体授权。
- 单元测试使用本任务独占临时 PostgreSQL 库并先登记、查不存在；结束删除及复查，不共用历史测试库。

## 实施任务和验证

1. 新增 `apps/wecom`：配置加密、官方HTTP接口、身份映射、事务建档、绑定审计、静默OAuth；验证唯一约束、状态防重放、会话错配、成员有效性和异常脱敏。
2. 集成现有认证：企微创建账号没有有效角色时限制所有业务API，保留会话查询/退出；验证已有密码账号不受新门禁影响，分配和撤销角色立即生效。
3. 按批准预览实现管理页、消息回调凭据区和等待授权页；验证类型、组件测试、构建、页面状态与布局。
4. 独立代码审查与后端/API/OpenAPI检查；按QA白名单/headless规则实测，明确真实企业微信链路和发布状态。

## 固定接口契约（前后端共同依据）

认证：`GET /api/auth/wecom/start/`、`GET /api/auth/wecom/callback/`；成功回跳本站，待授权到 `/auth/waiting-role`，失败到 `/auth/wecom-error?reason=<公开错误码>`。不得在URL携带凭据或原始第三方错误。`/api/auth/me/` 用户增加 `waiting_for_role: boolean`；原有账号默认false。

2026-10-19 用户更正主页要求：应用主页保留 `https://erp.cnhitree.com`。前端在会话查询成功确认匿名、企业微信环境且访问受保护页面时自动进入现有 start；普通浏览器保留密码登录。显式 `/login`、错误页与等待页不自动授权，已有会话不覆盖；匿名回跳用仅含布尔值的会话存储标记防循环，存储不可用则保留密码入口。后端 `login_url` 仍是 start，管理页工作台主页改展示 `erp_origin`；尚未发布及真实验收，见 `qa/wecom_home_entry_20261019/report.md`。

管理接口均要求 `IsAuthenticated + HasActiveEmployee + CanManageAccess`，沿用当前管理员边界。

- `GET/PATCH /api/v1/wecom/config/`：返回 `{data: config}` 和 `ETag`。首次未配置GET只返回默认值，不写库，ETag为 `"wecom-unconfigured"`。PATCH必须If-Match。
- config字段：`corp_id, agent_id, erp_origin, enabled, has_secret, has_callback_token, has_callback_aes_key, encryption_ready, configuration_complete, last_check_status (NOT_CHECKED/SUCCESS/FAILED), last_check_message, last_checked_at, login_url, callback_url, trusted_domain`。默认CorpID与AgentID为用户确认值；ERP origin为 `https://erp.cnhitree.com`。`enabled`默认false。
- PATCH写字段：`corp_id, agent_id, erp_origin, enabled, secret?, callback_token?, callback_aes_key?`。省略密钥代表保留，空串不覆盖。2026-10-19 用户追加要求覆盖原“只返回状态、保存清空”的方案：ConfigResponse.data 增加 `secret, callback_token, callback_aes_key`（`string | null`），只对原管理员权限返回真实解密值；未保存为空字符串，解密失败字段为 `null`，`credential_read_errors` 列出对应字段名，页面明确提示重新填写。旧密文损坏不阻止关闭入口或替换新凭据；网页登录连接检查不依赖消息回调凭据。页面明文回填，保存/刷新保留；数据库仍加密，响应禁止缓存，审计/日志/浏览器持久化存储不含明文或密文。
- `POST /api/v1/wecom/config/check/`：必须If-Match，检查服务器到官方应用连接并返回更新后的config及ETag；成功仍不能声称真实工作台登录验收通过。
- `GET /api/v1/wecom/bindings/?search=&status=&page=1&page_size=20`：`{data: Binding[], count, page, page_size}`。status取 `waiting/active/inactive`，空值全部。Binding字段 `id, user_id, member_name, employee_id, employee_code, employee_name, username, role_status, source, created_at`。
- `GET /api/v1/wecom/employees/?search=`：`{data: EmployeeOption[]}`，受限最多50条；字段 `id, employee_code, display_name, username, etag`，只显示有效员工，已绑定员工可由后端拒绝或排除。
- `POST /api/v1/wecom/bindings/`：`{user_id, employee_id, confirmed:true}`，If-Match为所选员工etag；服务器调用官方成员接口确认，事务绑定已有员工，返回 `{data: Binding}`。冲突409，不覆盖、不合并。
- `GET /api/v1/wecom/audits/?page=1&page_size=20`：`{data: Audit[], count, page, page_size}`；Audit字段 `id, occurred_at, actor_name, action, user_id, employee_name, result, message`；只暴露本模块安全审计字段。

## 分工与接口核对

| 工作 | 产出/消费关系 | 结论 |
| --- | --- | --- |
| 企微后端 / 核心认证 | 后端产出 `selectors.waiting_for_role(user)`，核心认证查询并门禁 | 独立于can_access_erp，避免等待页循环退出 |
| 企微后端 / 前端 | 上述管理接口、错误跳转码和waiting_for_role | 按本契约实现，变更先同步 |
| 核心认证 / 前端 | /auth/me字段及403错误码WECOM_ROLE_REQUIRED | 前端刷新会话并进入等待页，不清空会话 |
| 配置 / 现有数据 | 新增模型迁移，已有员工不回填、不自动匹配 | 需要管理员先映射，旧账号角色归属保留 |

## 进度

- 页面预览：已批准，静态检查49项通过；不代表功能验收。
- 后端、认证集成、前端：已实现。后端专项99通过/1跳过；前端全量1546通过，标题局部修复后组件8项、类型检查、最终构建通过。实际headless页面40项通过，统一QA为PASS_WITH_GAPS；真实企微、业务库和公网部署仍缺验收。
- 测试库、容器、浏览器目录和OpenAPI中间文件已清理并复查；构建目录frontend_dist的精确清理被自动审批以blocked by policy拒绝，残留已登记。扩大回归10项失败、全局OpenAPI问题详见最终报告，不声称全项目验收通过。
- 本机主库迁移：用户后续明确回复“执行”，已完成 `haiqu_erp` 的 `wecom.0001_initial`；三表为空，迁移检查及健康检查通过。
- 真实企微、员工写库验收、正式环境迁移和部署：未执行。本机尚未配置企微专用加密密钥，未录入应用凭据。
