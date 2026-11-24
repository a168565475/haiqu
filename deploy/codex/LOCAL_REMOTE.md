# 本机 ERP 使用服务器 Codex

本连接保留 Codex 账号管理与 BOM DXF 执行能力；旧生产任务/BOM Excel 导入、两种导入 worker 及自动启动入口已移除。

`compose.local-remote.yml` 只与项目根 `compose.yml` 合并，保留 `codex-worker`、socket 卷初始化与加密桥。服务器认证文件和代理凭据不复制到本机。

## 持久资源

- Codex worker：`haiqu-codex-worker`，执行 `process_codex_operations --watch`。
- socket 卷：`haiqu-erp-codex-bridge-socket` 挂载到 `/run/haiqu-codex`；卷根 `10001:10001`、0750，socket 为 0660。
- 初始化服务：`codex-local-storage-init` 只核对/初始化 socket 卷根；非空无归属标记、链接或元数据不符时拒绝启动。
- bridge 源码：`deploy/codex/bridge` 只读挂载到 Codex worker，Windows 管理进程持有 SSH 连接。
- DXF 私有目录：`data/bom_nesting` 供 backend/Codex worker 共享原文件与完整 SVG/DXF 产物；远端通过受控协议接收原文件。

退役导入功能的数据库记录、私有原件和命名卷保留，本配置不再挂载或自动清理。用户本机 Codex、账号和共享 DXF 代码继续保留。

## 启动与检查

从项目根运行 `docker compose -f compose.yml -f deploy/codex/compose.local-remote.yml config --quiet` 检查配置。启用时使用同版源码/镜像，只启动 `backend` 与 `codex-worker`；不再启动 `production-import-worker` 或 `local-production-import-worker`。

`local_codex_bridge.ps1` 的 `Start`、`Status`、`Stop` 管理现有 Windows 桥接。状态目录为 `E:/CodexData/.codex/private/haiqu-erp-local-codex/`。总启动脚本仅在其中的 `enabled.json` 存在时合并本配置并启动共享 Codex worker 和桥。

本配置继续通过 `FILE_VIRUS_SCAN_ENABLED=true` 开启 backend/Codex worker 的现有文件扫描。账号入口为本机 ERP 设置中的“Codex 连接设置”。服务运行不等于账号或模型就绪。

停止前等待当前账号/排料操作完成或明确取消，再停止 Codex worker 和桥；停止不退出服务器账号、不删除持久资料。恢复时重新启动 worker 和桥并检查状态，不自动重放登录、换号、测试或保存。

## BOM DXF

ERP 负责上传原始 DXF、门幅/数量/方向参数、任务跟踪、完整结果展示和确认回填；专属运行端负责实际工具解析、排料、验证、单耗和产物生成。需声明 `nest_tools_v1`；连接可达不能代替能力验证。

原文件上限 5 MiB、单件产物上限 8 MiB、文件调用期限 30 秒。升级和真实模型验收见 [DXF_RUNTIME_UPGRADE.md](DXF_RUNTIME_UPGRADE.md)。

历史记录保留于 [2026-11-03 本机接入交付记录](../../docs/implementation/production_task_ai_local_enable_20261103.md)；其中旧导入启动步骤已退役。
