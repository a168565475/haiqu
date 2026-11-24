# Codex 连接运行环境（单元二）

本目录包含部署配方和专属运行端维护脚本，实际启用状态以对应运行记录为准。`compose.codex.yml` 是 Linux Docker 主机的叠加文件，不能把本地开发 Compose 当作当前线上部署源。本机 ERP 已使用专属远端 Codex 的接法见 `LOCAL_REMOTE.md`。

## 服务边界

- ERP backend：权限、Session/CSRF、版本校验、状态与操作记录；只挂载专用 socket 目录。
- `codex-worker`：同版 Django 源码和 ERP 数据库连接，运行 `process_codex_operations --watch`；通过 socket 调用固定动作。
- `codex-runtime`：Python 3.13、固定 Codex 0.165.0 与独立 DXF 工具包（ezdxf/Shapely）；仅专用隔离网络、账号目录、共享互斥锁、socket 和内存临时目录。无 ERP `.env`、数据库、上传目录、Docker socket 或公网端口。
- 已验证的专用代理继续承担该隔离网络的出口。ERP 服务不设置此代理。

## 准备与授权

1. 审阅前向迁移及权限变化，取得目标数据库迁移授权。`manage_codex_connection` 只进入权限目录，不自动授予普通角色；遵循项目现有在职超级管理员规则。
2. 核验当时实际使用的 ERP Compose、镜像与 worker 叠加配置，构建包含同一份单元二源码的 ERP 镜像；原后台服务仍须使用同一版本。
3. 构建 `src/codex_runtime/Dockerfile`，复用已验证的 Codex 二进制镜像。独立基础镜像不包含 ERP 依赖或源代码。
4. `CODEX_SOCKET_DIR` 须为本任务独占目录，Linux UID/GID 10001、权限 0750；服务创建 socket 0660。backend/worker 使用附加组 10001 访问。`CODEX_AUTH_DIR` 为专属账号目录，10001:10001、0700，auth 文件 0600。
5. `CODEX_LOCK_FILE` 必须是所有账号操作共用的同一个 inode，10001:10001、0600。单元一 `/opt/haiqu-erp/ai-verification/state/login.lock` 原为 root:root/0600，切换前应确认无旧 probe 进程占用，再更新所有旧入口或停用旧入口；不能另建一把锁冒充全局互斥。
6. 已有专用网络必须再次核验 internal/isolated、无宿主网关、仅代理可出站。设置 `CODEX_INTERNAL_NETWORK` 和 `CODEX_PROXY_URL`。不导出代理节点凭据。
7. 显式设置 `CODEX_ERP_IMAGE`、`CODEX_RUNTIME_IMAGE`、`ERP_ENV_FILE`、四个上述路径/网络变量；先合并 `docker compose ... -f deploy/codex/compose.codex.yml config --quiet`，再按授权准备和启动。本文不替代发布授权，不列未经验证的线上完整启动命令。

账号凭据是正式配置，结束测试不能当临时资料删除。操作日志只保留动作、代次、操作者和白名单错误码；登录验证码在运行服务和当前发起页面内存中暂存。首次显示“已连接”只证明账号读取成功，所选模型最小测试通过后才显示就绪。

运行服务、backend/worker 与前端须使用相互匹配的单元二版本：明确的官方用量限制现通过 `USAGE_LIMIT_EXCEEDED` 传递，backend 必须包含该错误码白名单。用量限制保持 ERROR/暂停并显示明确原因，不自动重新授权或重试。b4 只增加该准确分类；真实账号证据与修后单元测试、镜像构建分别见单元二报告，不能把构建等同再次真实模型验证。

重启后 worker 对账 boot_id 与操作标识，不自动重放登录或最小测试。切换/退出先等待已有调用结束，取消登录则通过独立控制路径执行官方取消并确认旧进程退出。

设备码本地展示期限为 15 分钟，完成通知另留 120 秒有界余量；登录/换号操作总上限 1920 秒，包含原 900 秒启动、注销、读取及刷新预算，其余操作仍为 900 秒。失败后的清理与账号对账另有 90 秒、必要退出重试最多 20 秒。worker 使用短 RPC 持续轮询与续租，不应用 10 分钟或 15 分钟的总截止提前中断设备码流程。页面展示截止不是官方返回的有效期，须继续等待真实操作结果。

## BOM DXF 执行端升级

ERP 仅上传原始文件和参数、跟踪任务、接收完整排版图和单耗，并在用户确认后回填。Codex 在专属任务工作区实际调用固定工具完成裁片提取、排料优化、无重叠验证、单耗计算和 SVG/DXF 导出。旧的“ERP 本地先排基准，模型只给顺序建议，ERP 再复排”方案已被替换；不再作为降级路径。

DXF 使用 schema 2、`nest_tools_v1` 能力及逐件 artifact 回传。旧服务缺少能力时必须明确失败，不把账号连通当作排料可用。只升级 `runtime-local-erp` 的文件、镜像和专属容器，不发布服务器 ERP backend/frontend/worker，不迁移服务器业务库。可审核离线包、分阶段命令和回滚边界见 [DXF_RUNTIME_UPGRADE.md](DXF_RUNTIME_UPGRADE.md)。旧首次安装器继续拒绝已存在的目标，不用于本次升级。
