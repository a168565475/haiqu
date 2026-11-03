# Codex 连接运行环境（单元二）

本目录为待审阅配置，尚未启用或发布。不执行主库迁移，不改变当前 ERP 启动方式。`compose.codex.yml` 是 Linux Docker 主机的叠加文件，不能把本地开发 Compose 当作当前线上部署源。

## 服务边界

- ERP backend：权限、Session/CSRF、版本校验、状态与操作记录；只挂载专用 socket 目录。
- `codex-worker`：同版 Django 源码和 ERP 数据库连接，运行 `process_codex_operations --watch`；通过 socket 调用固定动作。
- `codex-runtime`：Python 3.13 标准库与固定 Codex 0.165.0；仅专用隔离网络、账号目录、共享互斥锁、socket 和内存临时目录。无 ERP `.env`、数据库、上传目录、Docker socket 或公网端口。
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

## 单元三导入叠加配置（待验收，未启用）

`compose.import.yml` 仅在原 Codex 叠加配置之后显式合并。backend、两个 worker 必须使用同版单元三 Django 镜像；runtime 也必须包含新增 discover/extract/result 固定协议。旧镜像不能混用。

- `PRODUCTION_IMPORT_DIR`：独立、非符号链接、非 Web 公开目录。backend 与导入 worker 需要读写，Codex worker 只读；runtime **不挂载**此目录、ERP 媒体或业务环境。Django 进程的 Linux UID 必须一致并有权访问 0700 目录/0600 文件。
- `ERP_MEDIA_DIR`：指向已核实的当前 ERP 媒体目录，只供导入 worker 按已登记的文件清单恢复失败保存；不是新建或清空目录。不得猜测路径。
- 导入 worker 使用 ERP 数据库与现有 ClamAV 端点。`FILE_VIRUS_SCAN_ENABLED` 必须为 true；扫描不可用或非 CLEAN 不调用模型、不保存图片。
- 迁移计划包含 `codex_connection.0002_remove_codexoperation_codex_operation_action_valid_and_more` 与 `production_task_imports.0001_initial`。执行前核对目标、备份和待执行计划；此文档不授权 migrate。
- `production_task_imports.import_production_task` 进入现有权限目录，不自动授予角色；使用者还必须有新增生产任务权限。前台和 worker 都会重新检查员工/权限。
- `process_production_task_imports --watch` 负责安全预处理、入队、每 60 秒检查失败保存归属清单、清理超过 7 天且未保存的来源。缺迁移时显式退出。Codex worker 仍负责模型轮询与账号操作互斥。已保存来源继续保留。
- `pending-media.json` 是正式图片移动前落盘的追加归属清单。事务回滚时仅删除数据库无记录、路径和哈希一致的文件；异常中止由导入 worker 再核对。归属或哈希不符标 `CLEANUP_UNKNOWN_RESOURCE`，保留现场并处理后再启动，不能扩大删除范围。
- 单次提取最多 600 秒、单模型轮次 300 秒；超过 4 张图按 4 张一批描述后汇总。最大内部帧 16 MiB、输入 12 MiB、最终结果 2 MiB，超限失败。单元三主样本发现约 70 秒、提取约 224 秒；多版本发现约 70 秒。这是两个样本的观测值，费用与并发容量未压测。
- 同一员工重复上传同一字节文件时，成功发现的任务列表保持首次结果，避免模型描述变化生成新的对象身份；若原任务选择有误，核对后使用修正的源文件。已保存关联优先于 ETag/任务号校验，保存响应丢失时前端先查询关联再决定是否预留合同号。

默认 Compose 未增加服务或目录挂载；本轮不执行实际合并启动、目录初始化、迁移或发布。启用后需要备份的是导入记录及 `PRODUCTION_IMPORT_DIR`，不能把保留的来源或账号凭据当测试临时文件删除。
