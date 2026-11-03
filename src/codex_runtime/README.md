# Codex 账号与解析运行桥（单元二、三）

管理 ERP 专属 Codex 账号，并通过固定 discover/extract 动作整理生产任务来源；没有任意提示词或任意工具入口。依赖 Python 3.13 标准库和已核验的 Codex CLI 0.165.0，不安装 Python 包。`protocol.py` 管理唯一 stdio 读泵，`service.py` 管理操作，`server.py` 提供私有 Unix socket。

## 运行边界

- 本目录开发只新增源码与测试，不连接服务器、不访问账号、不改现有锁或凭据。
- 镜像构建使用项目根作为 context，显式 `--build-arg CODEX_IMAGE=<已核验的0.165.0镜像>`；新运行镜像来自 Python 3.13 slim，只从该 Codex 镜像复制二进制及公开 CA，不继承 ERP 镜像、业务源码或依赖。
- 启动命令为 `python -B -m codex_runtime`，用户必须 `10001:10001`。部署须设置只读根、cap_drop ALL、no-new-privileges、资源上限、init、无公开端口；runtime 只连接专属 internal/isolated 网络。
- `HTTP_PROXY` 与 `HTTPS_PROXY` 必须相同，格式为 `http://专属内部IPv4:18080`。App Server 子进程只接收固定 PATH、HOME、CODEX_HOME、CA、代理和 NO_PROXY 白名单，不继承 Django `.env`。
- socket 默认 `/run/haiqu-codex/runtime.sock`，可用 `CODEX_RUNTIME_SOCKET` 配置；父目录须 UID10001且对其他用户无权限，socket 模式0660。该目录卷只共享给 backend/协调worker。
- 专属凭据目录固定 `/state/codex`，UID10001、0700；锁固定 `/state/login.lock`，必须由部署者预置为 UID10001、0600、单链接普通文件。启动只获取现有文件的 OS flock，不创建或改变单元一旧锁。部署者必须让所有账号操作者统一此锁，不能并存两套逻辑互斥。
- 只读系统配置位于 `/etc/codex/config.toml`。`/tmp`、`/work/current` 应为受限 tmpfs。每个 App Server 子进程在 `/tmp/codex-runtime-*` 内创建独占状态/日志目录，通过固定两个配置项指定；进程退出后检查目录归属并删除。凭据独立保留。
- 同一时刻只存在一个活动操作；旧进程退出及必要账号对账完成前保持 RUNNING/BUSY。建议容器 `stop_grace_period: 120s`。强制关机不能当成正常清理通过。

## 冻结桥接协议

一连接一请求。先发送4字节大端无符号长度，再发送UTF-8 JSON；单包最多16MiB。状态等非 result 响应在 ERP 客户端仍限制256KiB；提取输入最多12MiB、结果最多2MiB。响应相同帧格式：`{"ok":true,"data":...}`，或 `{"ok":false,"error":{"code":"固定错误码"}}`。读写均有超时，不支持 HTTP、任意 RPC、路径、环境或提示词透传。

单元三新增：start 的 discover/extract 仅接收固定 payload `{sources, selected_candidate, images}`，schema 与提示词来自程序文件；图片仅允许受限 JPEG data URL。`result` 用 operation_id/generation 读取已完成的结构化结果，普通 status/operation 不包含业务正文。每次终态清除输入图片/来源缓存；成功结果保留至下一操作或服务退出以支持断线领取，失败不保留结果。ERP 落库后才领取下一操作。来源结构、ID 和人工核对仍由 Django 校验，runtime 完成不代表允许业务保存。

| method | params | data |
| --- | --- | --- |
| status | `{}` | runtime snapshot，仅缓存，不调用上游 |
| start | operation_id UUID、generation正整数、action、model字符串；解析动作另带固定payload | 立即返回snapshot；action仅login/switch/disconnect/refresh/test/discover/extract |
| result | operation_id、generation | 仅解析成功后返回同boot_id、operation_id、generation的结构化结果 |
| operation | operation_id、generation | boot_id、operation（未知ID为null）、snapshot |
| cancel | operation_id、generation | 快速设置取消并返回snapshot；RUNNING保持至退出/对账屏障完成 |
| challenge | operation_id、generation | operation_id、官方verification_url、user_code、expires_at，仅内存有效期内可读 |

snapshot 包含 `boot_id/cli_version/account/models/rate_limits/limits_updated_at/operation`；operation 包含 `id/generation/action/state/error_code/completed_at`，状态为 RUNNING/SUCCEEDED/FAILED/CANCELED。账号只返回如 `a***@e***.com` 的掩码，不返回原邮箱或账号ID。模型最多200项、额度窗口最多20项，超限不截断。模型必须从真实可见列表显式选择，不把首项当默认。额度缺失保留null，不补零；仅额度读取失败不会丢弃已确认账号/模型或阻断模型测试。

相同 operation_id+payload 在本次 boot 内幂等；不同payload拒绝。最多保留4096条轻量操作记录，达到上限拒绝新操作，不淘汰后重新执行旧ID。bridge重启后boot_id变化，旧操作不自动恢复或重跑。后端仍负责自己的 attempt_no/lease_id/config_generation 写回保护。

登录仅接受 `https://auth.openai.com`，不允许userinfo、query、fragment或显式端口。`expires_at` 是收到设备码后的本地估计展示截止时间（15分钟），不是官方返回的到期时间；截止后不再提供验证码，但操作仍等待真实完成通知，前端不能据此自动取消。完成通知最多等待1020秒（15分钟加本地工程余量120秒，余量不是官方TTL或已实测轮询间隔）。截止时仅检查当时已入队的有限通知快照，忽略错误loginId，不等待新事件或延长截止。

login/switch从启动操作起保留原900秒启动、注销、读取和刷新预算，另加1020秒设备码等待预算，总上限1920秒；其他操作仍为900秒。失败/取消后的清理与真实账号对账另有90秒上限，必要退出重试最多20秒；调用方阶段超时必须覆盖主体及清理。取消/完成后立即停止提供验证码。取消区分官方 canceled/notFound，旧进程退出后另起只读会话核对实际账号，因此取消竞争中可能显示“操作已取消但账号实际已连接”。runtime不把此状态当作模型测试通过。

依据固定Codex `rust-v0.165.0`（commit `360319d8dee62d87e2d59fc0c21805d79519cfed`）：[设备码轮询15分钟、间隔由接口返回](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/login/src/device_code_auth.rs#L99-L155)；[设备码完成/取消竞争](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/request_processors/account_processor.rs#L746-L810)。官方成功轮询后还需令牌交换、持久化和完成通知，不能把900秒当作整个登录流程的严格上限。a5的原始TIMEOUT回执保留；该配置缺陷不证明当轮具体网络/通知时序，也不能归因用户未授权。

## 定向测试与资源登记

Windows可运行帧、协议及状态机单测；只使用内存 FakeSession，不接账号/API。Linux另跑真实 Unix socket 本机进程通信测试，仍不访问 OpenAI。测试替身不代表真实登录/退出/换号验收。

```text
PYTHONPATH=src python -B -m unittest discover -s src/codex_runtime/tests -v
```

Linux测试若需socket资源，唯一登记目录为 `/tmp/haiqu-codex-runtime-unit02`；用途为本任务stdlib IPC测试，运行前须不存在，由测试创建并在finally关闭服务器、连接及精确清理复查。不得指向既有账号目录。主代理的临时测试容器和tmpfs由其单独登记、清理。本目录不创建测试数据库、真实业务副本或凭据。

开发记录：首轮RED为模块尚未实现；随后补测复现“错误action类型、未知operation响应、旧操作重放返回最新操作、失败刷新保留旧额度”四项真实边界，再定向修复。最终测试结果由主代理汇总；此处不将Windows单测等同Linux部署或真实账号验收。

EOF日志修复复验登记：`test_intentional_session_close_does_not_report_upstream_failure` 启动本任务独占的当前Python子进程，仅从stdin读到关闭，不读取文件或联网；测试finally关闭并等待该进程。Linux复验容器固定 `haiqu-codex-u2-eof-tests`，使用本机已有 `haiqu-erp-backend:latest` 镜像只运行stdlib单测，network none、只读源码挂载、无业务env/目录/账号挂载；测试结束按容器名和 `task=codex_connection_unit02_20261102,run_id=eof-unit-tests` 标签核验后删除并复查。其 `/tmp` 为tmpfs，与既有业务容器无关。a1服务器真实PASS只绑定修复前源码，EOF修复尚不代表已重新部署或真实上游复验。

该修复先由新增主动关闭测试实测RED（意外EOF测试保持通过），再调整停止读泵与关闭stdin的顺序。Windows完整30项结果为28通过、2项Linux IPC跳过；本机Docker Linux完整30项全部通过，容器退出0并已精确删除、复查不存在。异常路径测试仍会输出其预期固定错误事件；主动正常关闭的新增测试断言stderr为空。未访问远端、未重建安装镜像、未调用真实账号或模型。

后续真实a3登录成功而test失败，原始失败细节因旧日志不足仍为UNKNOWN；a4用相同镜像/原u1账号refresh+test诊断通过，不能把a3归因于EOF修改。已按合法协议事件补测两处条件性缺陷：commentary不能当最终JSON；匹配turn/completed后必须先结束活动turn，再校验终态及最终JSON，不能对已终结turn错误interrupt。三个新增测试先实测RED；保持严格JSON结果、工具禁用、进程退出和目录归属边界。失败时另外输出固定 `operation_failure/action/stage/error_code`，在cleanup之前记录主错误，不记录RPC、模型文本、账号或凭据；cleanup失败仍返回INTERRUPTED而不伪装成功。

本轮Linux复验临时容器登记：`haiqu-codex-u2-protocol-b1-tests`，标签task=`codex_connection_unit02_20261102`、run_id=`protocol-b1-unit-tests`，只用既有本机测试镜像、network none、只读本目录挂载、临时/tmp；无账号/DB/业务env。结束按名称、ID、镜像与标签核验后删除并复查。

该条件缺陷修复完整复验：Windows 33项为31通过、2项Linux IPC跳过；本机Linux 33项全通过，测试容器正常exit0并已删除复查。a3原失败归因仍UNKNOWN，后续真实b1探针与fresh账号整链分别记录，不以单测替代。

设备码时限修复b2：新增默认展示期限、完成余量、login/switch外层预算、截止已入队匹配通知、错误ID不延时、非登录原超时、取消竞争与有界队列检查。先实测旧实现6个断言失败及缺少队列接口，再最小修改。Linux复验容器登记为 `haiqu-codex-u2-deadline-b2-tests`，task=`codex_connection_unit02_20261102`、run_id=`deadline-b2-unit-tests`；仅使用本机已有 `haiqu-erp-backend:latest` 镜像、network none、只读runtime源码挂载、tmpfs `/tmp`，无账号/DB/业务env。结束按确切ID、镜像与双标签核验后删除并复查。

b2定向复验结果：Windows完整42项为40通过、2项Linux IPC跳过；本机Linux完整42项全通过，UID10001测试容器exit0，已删除并确认不存在。独立只读审查未发现本次时限/队列边界阻断。以上不代表已重新完成真实授权，a5原始失败证据保持不变。

b3仅补模型终态诊断，不改成功/失败判定、API固定错误码或添加自动重试。每次匹配终态仅输出一条 `model_turn_result`：固定turn状态、error存在布尔、已知codexErrorInfo类别、HTTP整数（100–599，布尔/浮点/字符串无效）、本地cancel布尔，以及同线程/turn最后一条error通知的脱敏分类和willRetry布尔。终态与中间错误分列，未知分类统一UNKNOWN；不记录消息正文、additionalDetails、misalignment、未知字段值、账号、thread/turn ID或模型文本。固定依据为[0.165.0 TurnError与状态](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server-protocol/schema/json/v2/TurnCompletedNotification.json#L1983-L2056)。a6没有这些诊断，不能用新分类倒推旧失败原因。

b3 Linux定向测试资源登记：容器 `haiqu-codex-u2-diagnostic-b3-tests`、task=`codex_connection_unit02_20261102`、run_id=`diagnostic-b3-unit-tests`，仅既有本机测试镜像、UID10001、network none、只读runtime源码和tmpfs `/tmp`，无账号/数据库/业务env；finally按ID/image/标签核验删除并复查。六个诊断测试覆盖真实协议形状的失败枚举、成功与中断、HTTP类型边界、未知秘密值、匹配事件归属和错误形状；单元测试不代表真实账号模型验收。

匹配当前thread/turn的error通知会即时输出 `model_turn_error`（仅分类、HTTP整数、willRetry布尔）；终态仍独立判定，不因willRetry执行额外请求。服务器QA收集器再次严格检查这两类事件的全部键、枚举和类型，即时显示脱敏诊断并写入有界回执；非法诊断只记拒绝标志，不回显原值。

b3复验：Windows完整48项为46通过、2项Linux IPC跳过；Linux完整48项全通过，测试容器exit0并精确删除复查。QA收集器单独内存回归已验证实时输出/回执保留、5类非法或秘密payload拒绝、40条中间事件后最终诊断仍保留且总数不超过32；原始回执不修改。诊断补充不改变原模型判定，不是a6失败原因的补证。

2026-11-03 a8真实模型返回明确 `usageLimitExceeded`，随后已登录账号真实退出成功且测试凭据已清。b4仅在匹配的 `turn/completed` 中 `turn.status=='failed'` 且终态错误类别明确为 `usageLimitExceeded` 时映射固定码 `USAGE_LIMIT_EXCEEDED`；中间错误、缺失/未知类别、中断和其它终态保持原语义，不自动重试，不从HTTP状态或套餐推断额度原因/恢复时间。已完成状态仍须通过原严格JSON校验。a8原回执使用旧API码并保持不变。

b4 Linux回归资源登记：容器 `haiqu-codex-u2-usage-b4-tests`，task=`codex_connection_unit02_20261102`、run_id=`usage-b4-unit-tests`；使用本机已有 `haiqu-erp-backend:latest` 的已核固定image ID，仅作Python测试解释器，UID10001、network none、只读runtime源码、tmpfs `/tmp`。无账号/数据库/业务环境挂载；finally按确切ID/image/双标签清理并复查。测试包含匹配失败终态、仅中间usage、冲突终态错误、中断/异常状态、成功JSON以及未知错误代码净化，不替代新版本真实模型验收。

b4复验：新增错误码与终态边界用例先实测旧实现3个断言失败；修后Windows完整50项为48通过、2项Linux IPC跳过，Linux完整50项全部通过、exit0，测试容器已精确删除并复查不存在。QA收集器内存回归确认新旧固定错误码保留、未知码及额外正文不入回执；b3/b4共6个仅构建CLI入口检查通过。b4仅构建安装镜像，没有再次调用真实账号模型，a8原始回执继续保留。
