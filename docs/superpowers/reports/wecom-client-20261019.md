# 企业微信 HTTP 客户端实施与单元测试

日期：2026-10-19。范围仅为企业微信第一阶段客户端；不是正式环境或真实企业微信登录验收。

## 修改文件

- `src/backend/apps/wecom/client.py`
- `src/backend/apps/wecom/tests/test_client.py`
- 本报告。

## 实现范围

- 标准库 urllib 访问固定 `https://qyapi.weixin.qq.com/cgi-bin/`，不新增依赖；禁止重定向，单次 socket 超时 8 秒，响应最多 1 MiB。
- 官方新版 `auth/getuserinfo` 使用小写 `userid`，拒绝外部身份和不匹配的企业；调用方仍须调用 `get_member` 确认应用可见范围。
- `user/get` 必须返回同一个 userid、真实非空姓名、整数状态 1；不使用用户 ID 或手机号冒充姓名，不返回额外成员字段。
- 连接检查使用 `agent/get` 确认配置 AgentID。
- `caches['wecom']` 共享 token，缓存键由 CorpID、AgentID、凭据密文的 SHA-256 产生；TTL 根据 expires_in 减去安全余量。解密通过独立 credentials 模块完成。
- 只有官方错误码 40014/42001 触发一次 token 刷新及请求重发；网络失败、无效 OAuth code 不自动重试。
- 错误为固定中文文案和公开错误码，不暴露 URL、code、Secret、access_token 或原始 errmsg；外部异常禁止在响应异常链中透出，敏感局部变量标记为不进入 Django 错误报告。

## 实际验证

命令：`docker compose exec -T backend python manage.py test apps.wecom.tests.test_client --verbosity 1`

1. 先编写测试，首次运行因客户端模块尚未实现而失败（ModuleNotFoundError）；未创建测试库。
2. 首轮实现后 18 个测试通过。
3. 补充非法 Unicode 等边界测试后，23 个测试中非法 Unicode 输入暴露 UnicodeEncodeError；修复输入校验后 23 个测试全部通过。
4. 覆盖真实 urllib 重定向处理链只尝试一次传输、HTTP/网络错误脱敏、响应大小/JSON/类型校验、配置/输入/解密/缓存异常、token 隔离/过期/刷新、成员有效性和应用匹配。
5. 与真实配置契约联调后补充 AgentID 字符串、UserID 大小写和可操作错误提示。最终独立执行同一命令，29 项全部通过（0.149 秒）；尚未调用真实企微 API。

Mock 仅替代外部 HTTP 和凭据解密边界，缓存使用本任务独立 LocMem。单元测试的模拟响应不能证明真实企业微信配置、可信域名、出口 IP、成员可见范围或工作台登录可用。全模块业务/API测试由主任务统一运行，本子任务未创建数据库、调用真实企业微信、迁移主库或部署。

## 资源与清理

未创建临时数据库、上传文件、导出副本或浏览器目录。测试内存缓存位于独立名称 `wecom-client-tests-20261019`，每个测试结束通过 addCleanup 清空，测试进程已退出。保留源码、可复用测试和本报告作为交付证据。
