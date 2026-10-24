# 企业微信卡片预览限定更新

状态：2026-10-24 已上线，发布号 `card-preview-20261024-01a16b86`。网站：https://erp.cnhitree.com/。

简短更新记录：生产任务确认的人工预览支持企微文字通知卡片，新增“套用卡片示例”；实际发送仍由用户亲自点击。

## 发布范围与基线

- 来源聊天 `01a16b86-7110-7530-8df0-85c90c80f608` 经用户授权交给现有部署窗口执行；最后就绪通知允许准备校验通过后切换。
- 以发布 `20261023-232038`、源码提交 `a4444f2baa86c7e07ccae9f882d2a4238059dc6b` 为固定基线，只叠加5个运行源文件。未使用当前工作区整树，其他并行改动未上线。
- 后端：`apps/wecom/client.py`、`notification_preview_services.py`、新增 `message_cards.py`。前端：`types/notifications.ts`、`views/settings/NotificationRulesView.vue`。
- 仅 `PRODUCTION_TASK_CONFIRMED` 人工预览使用 `template_card/text_notice`；其他规则及自动通知继续沿用原方式。点击示例仅填充草稿，未自动保存或发送。
- 归档16,763,281字节，SHA256 `c738e1d714f0d98b047ebc6881ff3e7f10245257b990c1ba5d2503ba923f4661`。包内470个普通文件、469项内容摘要已核对。
- 只切换 ERP backend/web；无迁移、数据导入、配置覆盖、新增依赖或 worker 变更，没有访问 CRM，没有真实企微外发。

## 上线与核对

- 原发布脚本的只读基线校验通过。首次准备在新镜像文件读取阶段失败，未激活；原因是本窗口解包将文件设为0600、目录0700，运行用户无法读取。
- 经限定授权，仅将本次新增 incoming 及对应新 context 的源码/静态文件权限改为文件0644、目录0755，然后重建两份新镜像；归档字节、源内容摘要、旧 context、环境文件及原失败日志未改动。
- 后端使用 UID10001 全量核对1083项运行文件（1082项源码加部署 settings）；前端使用 nginx 全量核对461项产物，另实际读回 nginx UID101。原 prepare 的清单、运行参数和 Compose 配置检查全部通过，生成 `prepared.json` 后按原 `release_ops.py activate` 切换。
- backend 镜像 `sha256:4dd2bec71705fd5aa67fbeb7e8e14f7538194e3456ae80462c135cabb7d0401f`；web 镜像 `sha256:e763bfa90d0965f02c765585ebe2bbd27ff61b9610be164843d8eaca0296dff0`，均 healthy，运行文件再次逐项核对通过。
- PostgreSQL、Redis、ClamAV 的容器 ID、镜像及启动时间前后一致。数据库结构和迁移记录摘要、32个附件摘要、环境文件摘要未变；这是本次发布未改动上述范围的证据，不代表排除了用户并发业务活动。
- 运行设置实际读回：`SALES_ACCESS_ENABLED`、`MODULE_ACCESS_ENABLED`、`ACCESS_RESOURCE_SCOPES_ENABLED` 均为 true。
- 公网 headless 只读检查16/16通过：HTTPS、健康、登录页、匿名接口、首页与 JS/CSS 摘要、实际浏览器加载资源及1920/390两种视口，无浏览器错误。主 JS 为 `assets/index-Dn3oene7.js`。
- 来源任务的本机证据：前端目标23项、类型检查和生产构建通过；后端首轮61项中60项通过，唯一旧权限断言修正后定向1项通过。部署未重复执行全量测试。
- **UNKNOWN：线上真实登录后的通知规则卡片预览、企微凭据实时有效性、实际收卡展示与打开 ERP 行为。** 没有现成线上会话，不新建身份或借用本机会话；本窗口未点击发送。用户可刷新通知规则页，套用示例、生成预览后自行选择收件人试发。

## 操作、清理与留存

主要操作：固定包 SHA/逐文件核对、原 `release_ops.py inspect`、限定权限恢复及镜像重建、实际用户读取核对、原 `release_ops.py activate`、`node qa/card_preview_deployment_20261024/public_readonly.cjs --run`。

- 本次远端 incoming 的473个已登记文件及6个目录已逐项核对、删除，并复查目录不存在；8个必要脚本/清单/原失败记录复制到留存的 `package_audit`。清理未触及数据库、附件或旧发布。
- 本窗口公网浏览器的3个临时路径已关闭并删除，复查不存在；诊断和验证容器采用 `--rm`，结束确认不存在。本窗口未创建测试库。
- 首次失败构建的两份镜像按原构建日志/诊断中的完整 ID 核对：均无标签、无摘要引用、无任何容器引用；仅对这两个 ID 执行 `docker image rm` 并复查不存在。旧版可回退镜像及当前两份镜像再次核对仍在，未进行全局 prune。
- 保留线上新镜像、旧版可回退镜像、context、必要日志、发布包和验收证据。
- 来源任务两个独占测试库已删除并复查。来源任务固定源码构建临时目录 `.tmp/card-preview-release-01a16b86` 的删除此前被自动审批以 `blocked by policy` 拒绝，没有提供更具体原因；该目录仍保留，未换工具或重试绕过，整体临时资源清理不完整。

本地证据：`qa/card_preview_deployment_20261024/final_result.json`、`prepared.json`、`activated.json`、`permissions_recovery_result.json`、`incoming_cleanup_result.json`；公网完整报告路径记录在 final_result 中。远端留存：`/opt/haiqu-erp/deployment-logs/card-preview-20261024-01a16b86/`。

本记录只提交部署文档；运行源文件及测试的 Git 提交由来源开发任务负责，不能将本记录提交号当成完整运行源码版本。
