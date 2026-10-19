# 企业微信第一阶段后端实施交接

状态：后端源代码与测试已编写；数据库/API 测试由主任务在已登记的独占临时 PostgreSQL 库统一执行，最终结果以主任务验收报告为准。未执行主库迁移、真实企业微信调用、业务库验收写入或部署。

## 修改范围

- 新增 `src/backend/apps/wecom/` 的模型、迁移、凭据加密、查询、业务服务、Serializer、管理 API、OAuth 入口与测试。
- `client.py` 与 `tests/test_client.py` 由客户端子任务负责；主任务负责 `settings`、根路由、原有会话门禁和访问日志处理。
- 本子任务没有修改原有模块、项目 `AGENTS.md` 或真实 `.env`，没有提交代码。

## 已实现行为

1. `WeComConfig` 通过单例约束保存配置。未配置 GET 返回默认值与 `"wecom-unconfigured"`，不创建行。写入必须携带当前 ETag。CorpID 已有绑定时禁止更改；网页登录配置变化会清除旧连接检查状态。
2. Secret、消息回调 Token、EncodingAESKey 使用独立 `WECOM_FERNET_KEYS` 加密。省略或空串保留旧值，响应和审计只有配置状态，不含明密文。首个密钥写入、轮换密钥均可解密。消息回调凭据首期仅保存，不启用消息处理。
3. `WeComBinding` 使用 `CorpID + lower(UserID)` 数据库唯一约束与员工一对一约束；保留官方 UserID 原始大小写。手工绑定保留原账号、密码和角色；员工无账号时创建不可用密码账号，不分配角色。
4. 首次静默 OAuth 登录核实本企业成员、应用可见性、激活状态和真实姓名后，在同一事务创建账号、员工、绑定及审计。员工编号、用户名独立生成，不按姓名或拼音自动匹配旧员工。
5. `OAuthState` 仅保存状态和发起会话摘要、发起人、有效期及配置 ETag。有效期 5 分钟，条件更新保证并发一次消费。入口拒绝附加参数，不接收外部 `next`；失败只跳转本站公共错误码页面。
6. 已登录 A 返回 B 时在建档前拒绝并保留 A。登录沿用员工、用户加锁与 Session 保存，停用或归档账户不会被重新激活。
7. `waiting_for_role(user)` 只约束 `created_account=True` 的企微账号，使用现有 `current_assignments` 每次读取有效角色。已有密码账号的权限行为保持不变；密码重置不会改变账号来源。
8. 新模块迁移尚未执行时，旧账号继续原登录流程，企微管理 API 返回 503，OAuth 返回 `CONFIGURATION_ERROR`，不查询新表。
9. 管理接口复用 `IsAuthenticated + HasActiveEmployee + CanManageAccess`，包括当前 `admin` 超级管理员及 `ACCESS_MANAGEMENT_ENABLED` 边界；写请求继续使用 Session、CSRF 和 ETag。
10. 成功建档/绑定审计和业务在同一事务；失败绑定和已配置模块的 OAuth 拒绝另记受限审计。内部异常不吞掉。敏感函数加注解，并对本模块请求安装强制敏感错误过滤器，开发 `DEBUG=True` 也执行过滤；OAuth 参数读取后从错误报告可见的 GET/META 中移除。

## 接口交接

- `apps.wecom.urls` 挂在 `/api/v1/wecom/`。
- `apps.wecom.auth_urls` 挂在 `/api/auth/wecom/`。
- 管理接口及响应字段保持 `docs/superpowers/plans/2026-10-19-wecom-phase1.md` 契约。
- `agent_id` 为字符串数字；客户端进入官方 API 前转正整数。
- OAuth 出站公共错误码：`STATE_INVALID`、`CONFIGURATION_ERROR`、`IDENTITY_MISMATCH`、`MEMBER_REJECTED`、`UPSTREAM_UNAVAILABLE`、`LOGIN_FAILED`。
- `source` 为 `AUTO/MANUAL`；`role_status` 为 `waiting/active/inactive`。
- Token 为 1–32 位 ASCII 英文或数字；EncodingAESKey 为 43 位 ASCII 英文或数字。官方回调说明没有提供 Token 最小 3 位约束，因此没有擅自设置 3 位下限。

官方格式依据：[接收消息与事件](https://developer.work.weixin.qq.com/document/path/90930)、[加解密方案说明](https://developer.work.weixin.qq.com/document/path/90968)，由客户端调研子任务在本次执行中核实。

## 验证与边界

- 先编写集成测试，再实施对应模块。
- `test_integration.py` 当前 33 项，覆盖配置只读默认值、ETag、加密/脱敏、CSRF、原账号角色保留、冲突审计、等待授权门禁、状态期限/重放/会话错配、建档事务回滚、未知数据库错误不吞掉、迁移前兼容和 `DEBUG=True` 错误报告脱敏。
- `test_concurrency.py` 3 项：同一状态并发单次消费、同一成员并发首次建档、账号停用与登录加锁。
- 本子任务实际执行：`docker compose exec -T backend python -c "import ast,pathlib; files=list(pathlib.Path('/app/apps/wecom').rglob('*.py')); [ast.parse(p.read_text(encoding='utf-8')) for p in files]; print(f'Parsed {len(files)} Python files')"`，输出 `Parsed 17 Python files`，退出码 0。
- `0001_initial.py` 由主任务执行 `makemigrations wecom --noinput` 生成；本子任务已检查只新增本模块三张表和对应约束。
- 尚不能据上述静态校验声称 API 或真实企业微信验收通过。数据库测试、OpenAPI、页面验收与资源清理由主任务统一报告。
- 本子任务未新建临时数据库、上传文件、浏览器目录或中间导出文件；上述源代码、迁移、测试和本报告属于交付物。

## 隔离浏览器集成测试入口

- 新增 `apps.wecom.tests.test_browser_fixture.WeComBrowserFixtureTests`，默认跳过；仅 `WECOM_BROWSER_QA=1` 显式启用。
- 使用 Django `LiveServerTestCase`，监听 `0.0.0.0:8000`，只允许已登记测试库 `test_haiqu_wecom_page_20261019_01a1519b`。主任务负责启动独占容器、核实库不存在、运行测试及最终销毁数据库。
- 仅创建测试管理员、待角色账号、对应有效员工、单个来源明确的测试绑定和审计。企微配置禁用，Secret/Token/EncodingAESKey 全为空；测试用 Fernet key 只用于隔离测试进程。
- 真实 Django Session、CSRF 和数据库 API 可供浏览器检查；企微客户端被测试保护直接阻断，任何调用尝试使测试失败。此测试不能替代真实企业微信身份链路验收。
- `/qa-control/ready.json` 只公布测试用户名、测试密码和端口；等待 `/qa-control/finished` 最多 300 秒，超时明确失败。两文件由主任务预先登记，本入口在 `finally` 中清理本次控制文件；Django 测试运行器结束后销毁测试库。
- 已核对首轮 77 项测试中的 Token fixture 失败：旧值含横杠；当前 fixture 已为 `callbackToken123`，没有放松已核实的官方英数字符校验。浏览器入口代码已写入，本子任务未启动其容器或测试。

## 独立审查后的入口脱敏修正

- 回调参数保护提前到新 `WeComOAuthSensitiveMiddleware`，由主任务注册为首个中间件。先清空错误报告可见的 GET/META 查询，再解析局部原始查询并暂存 `state/code`，供视图一次消费；`finally` 清除私有存储。
- `schema_is_ready` 在视图消费并脱敏参数后执行，数据库异常继续传播；认证中间件更早的数据库异常也处于强制敏感过滤范围。
- 新增 4 项无数据库测试：迁移查询异常、提前认证查询异常的 DEBUG 响应不含参数；视图仍能消费原参数；下游异常传播且私有属性被清除。子任务未自行启动测试，待主任务收敛复验。

## 主任务统一回归反馈与连接清理修正

- 主任务反馈：4 项敏感中间件回归全部通过；228 项扩大回归中 218 项通过、10 项失败，本轮企业微信测试均通过。
- 10 项失败分别为 9 项既有 `CraftResourceApiTests` 报工依据 fixture 返回 400，以及 1 项 `test_sales_policy.py` 的 `readable_files` 断言；仅记录范围外失败，不据此声称扩大回归全通过，也不擅自修改。
- 本次发现测试库销毁仍有 2 个连接。已将本任务 3 个并发工作线程的 `finally` 从只清理过期连接改为线程内 `connections.close_all()`，确保有效连接也关闭。主任务负责确认连接为零后精确清理本任务测试库，并进行最终定向回归；本子任务未执行数据库删除。

主任务最终复验：100 项中 99 通过，1 项按设计跳过浏览器长驻 fixture，93.574 秒，退出 0；最终测试库正常销毁并查无此库。隔离浏览器 fixture 单独运行 1 项通过，配套 headless 40 项通过；真实企业微信、业务库迁移和公网发布仍未验收。完整命令、范围外失败和资源清理边界见 `wecom-phase1-20261019.md`。
