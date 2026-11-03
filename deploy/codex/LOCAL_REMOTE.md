# 本机 ERP 使用服务器 Codex

本机入口为 <http://localhost:8080>，数据库为现有 `haiqu_erp`。服务器继续运行专属 Codex；本机仅增加两个 worker、Linux 命名卷和受限 SSH 传输桥。用户自行登录、导入、核对和保存，本次启用不代用户新建或重复创建生产任务。

`compose.local-remote.yml` 只与项目根 `compose.yml` 合并，不与 `compose.codex.yml`、`compose.import.yml` 同时使用。它不包含本机 runtime、代理、公开 HTTP 端口或迁移命令，不把服务器 Codex 认证文件/代理凭据复制到本机。已有 ERP 端口与网络边界继续由基础 Compose 管理。

## 固定接口与持久资源

| 对象 | 确定值及用途 |
| --- | --- |
| Codex worker | 服务 `codex-worker`，容器 `haiqu-codex-worker`；`process_codex_operations --watch`。 |
| 导入 worker | 服务 `production-import-worker`，容器 `haiqu-production-import-worker`；`process_production_task_imports --watch`。 |
| 目录初始化 | `codex-local-storage-init` / `haiqu-codex-local-storage-init`，无网络的一次性进程；只核对/初始化两个卷根。 |
| socket 卷 | `haiqu-erp-codex-bridge-socket` → `/run/haiqu-codex`；根目录 `10001:10001`、0750；backend 只读挂载，Codex worker 可写挂载供桥接进程创建 socket。 |
| socket | `/run/haiqu-codex/runtime.sock`，由桥接进程创建为 `10001:10001`、0660，不经 Windows 文件系统共享。 |
| 私有导入卷 | `haiqu-erp-production-imports` → `/state/production-imports`；根目录 `0:0`、0700；backend/导入 worker 可写，Codex worker 只读。 |
| 卷归属标记 | 两个卷根分别有 `.haiqu-local-remote-owner.json`，标记自身 `0:0`、0600，记录固定用途、项目和目录权限。空卷才初始化；非空且无合法标记、链接、非目录或元数据不符时拒绝启动。已初始化卷不递归改属主、不清空来源。 |
| 源码与媒体 | backend 及两 worker 使用 `haiqu-erp-backend:latest` 和同一 `src/backend`；worker 源码只读。导入 worker 挂载现有 `data/media`，不创建替代媒体库。 |
| 桥接脚本 | `deploy/codex/bridge` 只读挂载到 Codex worker 的 `/opt/haiqu-codex-bridge`。本机 Windows 管理进程持有 SSH 连接；不将 SSH 私钥或凭据交给 ERP 容器。 |

2026-11-03 只读核对本机 backend 实际 UID/GID 为 `0:0`，因此导入卷和两 worker 明确沿用此身份。若未来改变 backend 用户，先调整对应持久目录权限方案，不直接递归 `chown` 已有来源。

以上是长期功能资源，不是验收临时资料；停止功能不删除卷、数据库记录、媒体或服务器账号。未保存导入资料按已确认的 7 天规则由导入 worker 清理，已保存单据必要来源继续保留。需要备份时应覆盖数据库、私有导入卷与媒体的一致状态。

## 启用顺序

以下命令均从 `E:\workspace\_project\project001_haiqu_ERP_CRM` 执行。静态配置检查不创建容器或卷：

```powershell
docker compose -f compose.yml -f deploy/codex/compose.local-remote.yml config --quiet
```

1. 核实当前服务器专属 runtime、唯一登录锁和固定公开 transport 脚本；完成本机 Windows 桥接管理进程接入。核实本机两命名卷不存在或确属本部署，不能把同名未知卷当空卷复用。桥接源码目录必须已存在；配置禁止自动创建缺失 bind 路径。
2. 在已经明确的本机启用范围内，复核 `haiqu_erp` 前向迁移计划。2026-11-03 实查尚缺且目标计划仅有：`codex_connection.0002_remove_codexoperation_codex_operation_action_valid_and_more`、`production_task_imports.0001_initial`。由主流程完成这两项迁移及权限目录核对，再启动 worker；本叠加配置不会自动迁移或授予角色。
3. 按下列命令初始化已登记卷、更新 backend 挂载与扫描配置、启动两 worker；沿用既有数据库、Redis 和 ClamAV。使用当前同版源码与镜像，不在此步骤自动构建或拉取镜像。

```powershell
docker compose -f compose.yml -f deploy/codex/compose.local-remote.yml up -d --no-build backend codex-worker production-import-worker
```

4. 启动本机 Windows 桥接管理进程，并查看状态：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\codex\local_codex_bridge.ps1 -Action Start
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\codex\local_codex_bridge.ps1 -Action Status
```

它调用 `bridge/supervisor.py`，受控状态目录为 `E:\CodexData\.codex\private\haiqu-erp-local-codex\`。首次启用标记 `enabled.json` 由主流程写入；现有 `start_haiqu_erp.ps1` 仅在该标记存在时合并本叠加配置并启动必要 worker 和后台桥接进程。首次主库迁移、标记写入和持久服务启用仍由主流程执行，本文不表示这些动作已经完成。

管理进程的本机子进程接口固定如下；这是连接二进制标准输入/输出的接口，不应手工独立运行后闲置等待：

```text
docker exec --user 10001:10001 -i haiqu-codex-worker python -I -B -u /opt/haiqu-codex-bridge/transport.py local
```

`FILE_VIRUS_SCAN_ENABLED=true` 通过本叠加配置覆盖 backend 和两个 worker，**不修改 `.env`，但会同时开启 backend 其他上传功能的扫描**。沿用现有 ClamAV 端点及权限政策；有效超级管理员按现有规则使用管理入口，普通员工须具备明确的管理或生产导入权限，不能将菜单可见当作后端授权。

用户入口：<http://localhost:8080/settings> → “Codex 连接设置”；<http://localhost:8080/production-tasks/new/manual> → AI 导入。官方授权、选模型、连接测试由用户在页面发起；网页显示“已登录 Codex”后仍以 ERP 端最终状态为准。服务运行和 socket 存在不等于账号或模型 READY。

## 停止与恢复

停止前先不再发起新导入/账号操作，核对页面正在执行的操作；正常完成或明确取消后停止两 worker，再由 Windows 桥接管理进程关闭它持有的 SSH 和本机子进程：

```powershell
docker compose -f compose.yml -f deploy/codex/compose.local-remote.yml stop codex-worker production-import-worker
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\codex\local_codex_bridge.ps1 -Action Stop
```

这不会停止服务器 runtime、退出账号或删除持久资料。backend 仍可显示已有状态；停 worker 后不处理新导入、过期清理或媒体补偿。不要执行 `down -v`、清空命名卷或删除来源来“恢复”。

两 worker 配置 `restart: unless-stopped`、120 秒停止宽限及 backend/ClamAV/目录初始化依赖；进程异常后可重启，但这不是模型或业务成功的证明。Docker/worker 重启后，Windows 桥接管理进程还必须重新建立对应 `docker exec` 与 SSH 连接；手工停止的服务通过上述 `up` 命令恢复，再执行桥接 `-Action Start` 和 `-Action Status`。桥接恢复后，按页面错误状态刷新连接，不自动重放登录、换号、模型测试或保存。导入队列仍等待时查看 `blocked_reason`，不通过重复上传/重复建单消除未知结果。

初始化中断、归属标记不符、socket 被未知进程占用或媒体补偿报错时停止该步骤并核对实际归属，不绕过标记、不递归改权限、不删除锁。此前已成功保存的单据应先查询保存关联，不能因为响应丢失再创建一张。

2026-11-03已按用户明确授权完成本机两项迁移、服务启用、扫描及加密桥接；5项传输单测、实际状态读取与仅SSH连接断开后的自动重连通过。启用标记已写入。当前专属Codex未登录，官方授权和业务测试由用户在ERP发起；本轮未上传样本或代为建单。完整证据及清理结果见 [本机接入交付记录](../../docs/implementation/production_task_ai_local_enable_20261103.md)。
