# 本机通知自动发送

本机开发 Compose 使用 `notification-worker`，复用 `haiqu-erp-backend` 镜像和只读源码挂载，不需要安装 Celery 或增加依赖。每 5 秒检查一批最多 50 条 PENDING 企业微信投递。ERP 站内消息在业务事务内保存，业务回滚时消息也回滚，与企业微信发送是否成功分开。

## 使用前提

1. 为真实员工分配对应角色，保留有效账号；规则中的接收角色必须有符合权限和范围的成员。
2. 在 ERP 的企业微信管理中保存并启用应用配置，确认接收员工的企业微信绑定。不要在聊天、源码或日志中复制应用密钥。
3. 在通知规则页配置模板和接收角色。预览试发的表迁移为 `wecom.0006_notification_preview_attempt`；`0008` 仅合并迁移分支。
4. 再操作真实业务节点。管理员操作也会产生通知，规则不会自动向所有管理员群发；“通知原提交人”可回给实际提交该单的有效超级管理员。该管理员没有企微绑定时只能收到站内消息。

没有合格收件人：业务事件记录 NO_RECIPIENT，没有投递记录，不对外发送；以后分配角色也不补发这些历史事件。已有合格收件人但应用未配置/停用/凭据无法解密：站内消息正常保存，常驻进程记录 WAITING_CONFIGURATION 并保留 PENDING，不消耗发送次数；配置恢复后自动继续。

缺少员工绑定、账号失效、权限失效或企业微信明确拒绝时记录失败原因。网络结果不明或超过5分钟未返回的处理中记录转 UNCERTAIN，先核对实际收件情况，不自动重发。ACCEPTED 仅代表企业微信受理，不代表员工已读。

## 启停和查看

在项目根目录执行。一键启动会在既有迁移步骤之后启动该服务；已有服务使用 Docker 的 `unless-stopped` 策略自动恢复。仅修改后端源码时，常驻进程需要重新启动加载新代码。

```powershell
docker compose up -d --no-deps notification-worker
docker compose ps notification-worker
docker compose logs --tail 50 notification-worker
docker compose restart notification-worker
docker compose stop notification-worker
```

首次部署需先构建并启动后端。worker 不开放额外端口、不执行迁移、不修改员工角色。仅需暂停对外发送时停止 worker；站内消息仍会生成。

现有一次性命令不加 `--execute` 仍为只读预览。FAILED 或 UNCERTAIN 的重试必须核对后明确指定投递记录 UUID，常驻模式禁止这些重试选项。

```powershell
docker compose exec -T backend python manage.py process_notification_deliveries --limit 50
```

本说明仅适用于本机 Compose，未部署线上。实际验收及限制见 [本轮记录](../qa/notification_auto_delivery_20261022.md)。
