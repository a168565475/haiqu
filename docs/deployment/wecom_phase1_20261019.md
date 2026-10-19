# 企业微信一期部署与管理员操作说明

日期：2026-10-19。状态：**已部署到服务器工厂试用站点，尚未完成真实企业微信客户端验收。** 用户明确确认后，已执行 `wecom.0001_initial`、生成服务器独立加密密钥并切换本期镜像；三表在迁移完成时均为空，未回填员工或启用入口。公网只读验收通过不代表真实企业的可信域名、出口 IP、成员可见范围和工作台登录可用。部署及数据保全结果见 [本次发布记录](release_20261019.md)。本文后续命令是操作模板，不构成未来写库或外部调用授权。

后续本机执行记录：用户明确授权后，已在本机 Compose 数据库 `haiqu_erp` 执行 `wecom.0001_initial`，三张表及约束已创建且记录数均为 0，迁移检查及健康检查通过。本机 `WECOM_FERNET_KEYS` 尚未配置，未录入应用凭据；此本机迁移不代表本文服务器发布步骤已经执行。详见 [实施报告](../superpowers/reports/wecom-phase1-20261019.md)。

## 1. 本期交付边界

企业微信自建应用工作台发起网页登录，继续使用 Django Session + CSRF。已绑定成员进入原 ERP 账号；首次访问的未绑定成员在一个事务中创建员工、无可用密码的账号及身份绑定，新账号无角色时只进入等待授权页，角色仍由管理员在原权限管理页手工分配。

独立管理页为 `/settings/wecom`，包含登录配置、员工绑定和审计。消息回调 Token、EncodingAESKey 只提供独立的密文保存及“已配置”状态，**本期不提供消息/事件接收端点、消息模板或消息发送能力**。不能将网页登录 callback URL 填成消息接收 URL，也不能据此在企业微信后台开启消息接收。

## 2. 发布前置条件与新增配置

源码新增 Django 应用 `apps.wecom`，前向迁移为 `apps/wecom/migrations/0001_initial.py`，依赖 `organizations.0002_seed_root_organization`。迁移新增 `wecom_config`、`wecom_binding`、`wecom_oauth_state` 三张表及约束，不自动映射或回填既有员工。身份唯一性按企业 ID + 不区分大小写的 UserID 裁决，一个员工只能有一个企微绑定。

新增服务端环境变量 `WECOM_FERNET_KEYS`，示例入口是仓库 `.env.example`，本部署读取 `/etc/haiqu-erp/server.env`。该值是独立 Fernet 加密密钥列表，用逗号分隔；不是企业微信 Secret、Token 或 EncodingAESKey。由获授权运维在受控环境生成并安全写入，保留环境文件 `600` 权限，不粘贴到聊天、终端日志、工单、前端配置或 Git。所有应用实例必须使用同一套有效密钥。

第一把密钥用于新加密，列表中所有密钥用于解密旧密文。轮换时可将新密钥放首位并保留旧密钥；当前没有批量重加密命令，不能直接删除仍被旧密文使用的密钥。密钥丢失后须恢复受保护的原密钥或重新录入凭据，不能从“已配置”状态恢复明文。原有邮件加密密钥及业务开关保持原值，不复用或替换为本变量。

管理 API 复用现有授权边界：已登录、有效员工、有效且用户名为 `admin` 的超级管理员，以及已启用 `ACCESS_MANAGEMENT_ENABLED`。页面入口可见不代表后端授权已满足。若原权限管理尚未启用，应按其既有分阶段方案处理，不为接入企微顺带打开所有业务权限开关。

**正式部署、真实业务库迁移、真实写库 QA、实际企微 API 调用均须取得对应项目授权。** 本次只执行用户已确认的试用站点迁移、独立密钥和应用切换，未执行真实写库 QA 或企微 API 调用。现有服务器文档的“不新增备份”约定仍有效；保全已有备份、业务数据和附件，不自行创建、删除或覆盖它们。

### 授权后的发布核对

沿用 [服务器部署说明](../../deploy/server/README.md) 的白名单构建和镜像载入流程，前端以 `VITE_API_BASE_URL=same-origin` 构建。新镜像须包含本期后端应用、前端产物及部署日志配置，不能只更新前端。先核对目标主机、Compose 项目、数据库实例和库名、迁移计划、镜像版本及本次获准范围。

以下为服务器端操作模板，`<版本号>` 必须替换为已审阅、已载入的实际版本；本次版本 `20261019-102306` 已按授权完成相应步骤，未来更新仍须核对当次范围：

```sh
cd '/opt/haiqu-erp/releases/<版本号>/context'
export ERP_ENV_FILE=/etc/haiqu-erp/server.env ERP_BUILD_CONTEXT="$PWD" RELEASE_TAG='<版本号>'
docker compose --env-file "$ERP_ENV_FILE" -f deployment/compose.yml config --quiet
docker compose --env-file "$ERP_ENV_FILE" -f deployment/compose.yml run --rm --no-deps backend python manage.py migrate wecom 0001 --plan
# 确认计划及真实业务库迁移授权后，才执行下一行。
docker compose --env-file "$ERP_ENV_FILE" -f deployment/compose.yml run --rm --no-deps backend python manage.py migrate wecom 0001 --noinput
docker compose --env-file "$ERP_ENV_FILE" -f deployment/compose.yml up -d --no-deps --no-build --pull never backend web
docker compose --env-file "$ERP_ENV_FILE" -f deployment/compose.yml exec -T backend python manage.py migrate --check
docker compose --env-file "$ERP_ENV_FILE" -f deployment/compose.yml ps
```

`--no-deps` 假定既有 PostgreSQL、Redis、ClamAV 服务已健康；不包含重启或新建它们的授权。若迁移计划出现本期以外的未执行变更，先报告并重新确认范围。应用启动不会自动迁移；新代码未迁移时，符合管理权限的企微配置请求返回明确的 503，不能把它当作保存成功。发布后另核对实际运行镜像 ID、公开同源 API、旧密码登录和管理页，不以健康检查 200 代替这些检查。

## 3. 管理员配置顺序

1. **先部署迁移和服务端加密密钥。** 用原有密码登录有效 `admin` 账号，打开 `/settings/wecom`，确认接口可用、服务端加密状态可用，保持“启用工作台入口”关闭。
2. **核对企业和应用，保存网页登录 Secret。** 本次确认的 CorpID 为 `ww08890a52e3ab432d`，AgentID 为 `1000010`，ERP 站点为 `https://erp.cnhitree.com`。Secret 必须来自该自建应用。页面及接口只返回配置状态，保存后清空敏感输入；空白表示保留已有值，不表示删除。
3. **完成企业微信后台域名、可见范围和出口 IP 配置，再检查连接。** “检查连接”会真实调用官方接口，并保存检查结果。成功仅证明该时刻应用接口可用，不代表真实 OAuth（网页身份授权）登录通过。
4. **完成所有原有员工映射，再启用工作台入口。** 在“员工绑定”输入企微 UserID，选择已有员工并明确确认同一人；不根据同名、手机号或邮箱自动匹配。已有有效账号沿用原账号；已有员工没有账号时会创建无可用密码的待授权账号。已停用、已归档或已被绑定的员工不能强行覆盖。UserID 大小写变体属于同一身份，与 ERP 员工编号规则无关。
5. **保存启用开关，并开展获授权的真实客户端验收。** 首次访问的新员工自动建档后停留 `/auth/waiting-role`；管理员通过 `/settings/access` 分配角色，成员点击“检查授权状态”后进入业务系统。企微管理页不代替角色管理。

配置保存/检查及员工绑定继续使用 Session、CSRF、ETag/`If-Match`。遇到 412，重新读取最新状态再操作；遇到 409，按页面给出的加密或绑定冲突原因处理，不反复强制覆盖。若在映射前让已有员工首次登录产生新档，本期没有自动合并或改绑流程，应停止该成员继续验收并人工核查，不能直接删档掩盖重复记录。

消息回调凭据与登录 Secret 分区管理：Token 为 1–32 位英文或数字，EncodingAESKey 为 43 位英文或数字；二者可独立保存并保持空白不覆盖。它们用于后续消息签名校验/解密，不参与本期网页登录完整性判断，缺少它们不应阻止本期登录。用途及官方格式见 [回调配置](https://developer.work.weixin.qq.com/document/path/90930)。

## 4. 企业微信后台及网络要求

| 项目 | 本次配置/核查内容 |
| --- | --- |
| 自建应用工作台主页 | `https://erp.cnhitree.com/api/auth/wecom/start/` |
| ERP 网页登录回调 | `https://erp.cnhitree.com/api/auth/wecom/callback/`；由后端生成，不手工拼接 code/state |
| 网页授权可信域名 | `erp.cnhitree.com`，不带协议或路径；按企业微信后台要求完成域名归属验证 |
| HTTPS | 使用有效证书和默认 443 端口；站点地址不带额外路径、用户信息或查询参数 |
| 应用可见范围 | 包含实际使用/验收的企业成员；同时保证应用能够读取该成员 |
| 企业可信 IP | 按当前企业微信后台要求配置 ERP 服务端调用官方 API 时的出口公网 IP；不能拿员工手机 IP 或未经核实的域名解析 IP 代替 |
| 出站网络 | ERP 后端可访问 `qyapi.weixin.qq.com:443`，成员客户端可完成 `open.weixin.qq.com` 授权和 ERP HTTPS 回跳 |

身份接口要求回跳域名与该应用可信域名匹配，且企业成员身份返回本身不能证明在应用可见范围内；本实现继续调用成员读取接口校验。依据：[获取访问用户身份](https://developer.work.weixin.qq.com/document/path/91023)、[读取成员](https://developer.work.weixin.qq.com/document/path/90196)。企业后台当前验证状态、实际出口 IP、DNS/证书和成员权限仍须上线时核实，本文没有操作企业管理后台。

## 5. HTTPS、Cookie 与日志：源码事实和未验证项

仓库当前 [服务器设置](../../deploy/server/settings_server.py) 已设置 `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")`、HTTPS 重定向及 `https://erp.cnhitree.com` 的 CSRF 信任来源；CORS 允许来源为空，前端走同源。Session Cookie 为 Secure、HttpOnly、SameSite=Lax、无跨域 Domain；CSRF Cookie 为 Secure、SameSite=Lax、无跨域 Domain，HttpOnly=False 供现有 Axios 读取并回传。

[服务器 Compose](../../deploy/server/compose.yml) 仅把内层 Web 发布到 `127.0.0.1:18080`，后端端口不对宿主机发布。[内层 Nginx](../../deploy/server/web.conf) 保留外层传来的协议头。外层 HTTPS 代理必须覆盖可信的 `Host` 与 `X-Forwarded-Proto: https`，不能透传客户端伪造值；实际外层配置是否符合要求是 **UNKNOWN**，需部署时确认。源码设置正确不等于正式 Cookie/代理链已经验收。

本期源码对 Django 开发访问日志的企微回调查询做脱敏，内层 Nginx 不记录该回调访问行，[Gunicorn 启动参数](../../deploy/server/Dockerfile.backend) 的访问日志使用 `%(U)s` 路径而不含查询串；回调请求及凭据的异常报告也有专门过滤。**外层 Nginx、CDN/WAF、出口代理、APM 和集中日志的实际行为仍为 UNKNOWN**。启用前核对整条链路不记录完整回调查询、code/state、Cookie、Secret、Token、EncodingAESKey、access_token 或管理保存请求体。官方 API 使用查询参数传输部分凭据，不能只检查浏览器回调日志。工单和截图仅保留安全错误码、脱敏说明和时间，不粘贴完整授权 URL。

## 6. 本期官方接口与参考

后端标准库 HTTP 客户端只调用下列四个官方 HTTPS GET 接口，不将凭据或 access_token 下发浏览器。连接检查不消耗用户授权 code。

| 官方接口 | 本期作用 | 文档 |
| --- | --- | --- |
| `/cgi-bin/gettoken` | 使用本应用 Secret 获取服务端 access_token | [获取 access_token](https://developer.work.weixin.qq.com/document/path/91039) |
| `/cgi-bin/auth/getuserinfo` | 将一次性授权 code 换成企业成员身份 | [获取访问用户身份](https://developer.work.weixin.qq.com/document/path/91023) |
| `/cgi-bin/user/get` | 核对成员身份、有效状态及可读取的真实姓名 | [读取成员](https://developer.work.weixin.qq.com/document/path/90196) |
| `/cgi-bin/agent/get` | 检查应用配置连通性及 AgentID | [获取应用](https://developer.work.weixin.qq.com/document/path/90227) |

以上四份官方页面在本轮通过公开文档只读 GET 核对标题和接口路径，未调用实际企业 API。[wechatpy GitHub](https://github.com/wechatpy/wechatpy) 是支持企业微信的第三方 Python SDK，可供后续评估；本期使用项目现有依赖和标准库，不需要安装或升级 wechatpy。不能据此把第三方 SDK 的接口示例当作本项目已实现能力。

## 7. 真实企业微信客户端验收清单

以下全部是**待执行项**。先登记真实成员、允许新增/修改的员工账号、角色与清理方案并获得授权；禁止用模拟响应或隔离页面结果勾选。

- [ ] 真实企业微信客户端从应用工作台进入，HTTPS 回跳、Session Cookie 和 CSRF 正常；旧密码登录仍可用。
- [ ] 已手工映射的成员进入正确旧账号，无重复员工/账号、无密码或角色被重置；在权限允许的真实业务页验证其原权限。
- [ ] 获授权的新成员首次进入只产生一组员工/账号/绑定，无可用密码、无自动角色；重复打开及并发进入不重复建档。
- [ ] 无角色账号进入独立等待页，直访业务页面/API 被拒；刷新授权不循环、不注销。管理员授予有效角色后可刷新进入；撤销最后有效角色后再次回到等待状态。
- [ ] 已停用/归档员工或停用账号不能借企微登录恢复；无关企业/外部身份、不可读成员按固定错误页拒绝，未产生多余员工或账号。
- [ ] 会话 A 返回企微身份 B 时拒绝切换且不替 B 建档；由使用者明确退出后重新从工作台发起。过期/重复 state、直接访问 callback、过期 code 均安全失败。
- [ ] 管理保存后敏感输入清空，刷新只见配置状态；空白保留旧值；两个管理员页面的旧 ETag 不能覆盖新状态；重复/冲突绑定不能覆盖另一员工。
- [ ] 桌面及实际使用的移动端查看配置、绑定弹窗、等待页和固定错误页，记录视口、DOM/计算样式及必要脱敏截图；日志核查没有泄露授权查询或凭据。
- [ ] 关闭启用开关后新登录被拒，原密码入口仍可用；实际新增测试资源按已授权清理方案处理并复查，业务审计保留。

若环境缺少真实成员、管理员权限、配置或授权，记录具体阻断项为 UNKNOWN；不得写成全链路通过。

## 8. 故障处理与回退

先通过原密码账号进入 `/settings/wecom`，关闭“启用工作台入口”并保存。关闭后新 OAuth 发起及尚未完成的回调会被拒绝，但**不会注销已经建立的 ERP Session，也不会删除绑定、员工、角色、密文或审计**；待授权门禁仍按账号当前角色状态生效。若需要停用某个账号，通过原“员工与账号”管理流程操作，不把企微开关当作全员强制退出。

页面不可用时先按发布故障流程确认版本、迁移和加密状态，不直接用 SQL 修改正式表。代码回退须另行核对并授权使用已保留的旧镜像；已执行的本期迁移不自动反向撤销，不删除表或业务数据。需要更换 Secret 或修复密钥时保持入口关闭，重新保存、检查和核对员工映射后再启用。

本次文档编写只读取源码和公开文档，新增本说明文件；未创建临时数据库、上传副本、密钥文件或浏览器目录，无需清理运行资源。
