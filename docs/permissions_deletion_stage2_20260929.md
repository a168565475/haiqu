# 报工删除第二段（开发与验收记录）

用户已确认承接第一段继续开发。范围为报工物理删除、原因必填、独立审计与新增请求防重放；只在隔离数据库验证，不删除真实报工、不向正式员工分配权限、不切换主库功能开关。

## 技术与界面清单

- 新删除权限按操作使用车间范围，后端负责校验；日期明细页仅对可删除记录显示入口。
- 先按现有顺序锁定排产、生产任务、产品，再锁报工及相关依据；校验当前 ETag 和删除原因。同一事务写独立审计、保留请求历史，再删除主记录和全部明细。
- 独立历史保留原新增请求标识、摘要、原报工 ID/编号，以及曾引用的工价版本；删除后不能通过旧新增请求重建，不能开放曾用工价的原地修改。
- 新 `WORK_REPORT_DELETION_ENABLED`、`WORK_REPORT_HISTORY_ENABLED` 默认关闭；未迁移的主库不访问新历史表。删除启用时自动使用历史保护；上线同时打开历史保护，之后可单独暂停删除入口，但不能关闭历史保护，否则旧请求可能重放。迁移回填当前仍存在的报工，不伪造已无法从旧记录恢复的更早工价引用历史。
- 日汇总、金额、累计数量从剩余有效报工汇总。用户补充选择 A：不足完成条件时，关联车间计划自动恢复进行中。累计数量按现行产品/车间/工序口径，检查同产品同工艺的相关计划；工价依据取形成完成状态的报工版本（含已删除快照），不套用删除当天新版本。

界面沿用 ERP `DESIGN.md` 第10章和既有 `AppWindowDialog`。删除确认弹窗宽520px，控件/按钮32px，多行原因为96px、最多1000字；表单字号13px、标题16px、间距16px，内容内边距由通用弹窗独占（上下20px、左右24px）。外围单层1px边框、5px圆角，颜色沿用 crm tokens；无多余内外滚动。确认按钮采用已有危险色，原因空白或提交中禁用；提交中禁止关闭，失败保留原因，成功刷新明细和数量。覆盖普通、空原因、错误、提交中和无权限状态。

## 验证

- 前端定向 Vitest 5/5 通过：原因必填及去除首尾空白、提交期间防连击、失败保留原因、412重新核对新版本、超时后已删除结果核对，以及保留原计划查询条件。见 `qa/permissions_deletion_stage2_20260929/frontend-tests.log`。
- `npm run build` 通过（包含 TypeScript 检查）；有既有大包体提示。上一段的 `WorkshopConfigManager.vue` 旧字段赋值由工作区其他改动修正，不记为本轮贡献。见 `frontend-build.log`。
- 独立 Chrome 视觉验收通过：1920×1080，520px弹窗、四边1px、5px圆角、32px按钮、96px文本域、20px/24px内边距，无额外滚动。已人工复核截图 `02_delete_reason.png`。该页使用明确标注的视觉样例，业务 API 调用0；不将其当作真实删除流程验收。见 `browser_visual_results.json`。
- 独立代码复审发现并修复删除先提交后编辑的500分支，以及响应组装期间可能被删除的竞态；创建/编辑API事务覆盖到响应数据组装。测试中的送审步骤和作废计划约束也已补齐。静态复审不替代运行验证。
- 后端新增15项接口/事务/范围/历史用例及2项真实并发用例，**均未执行**。Docker Desktop Linux引擎的容器查询和version接口返回500；ERP `http://localhost:8000/api/health/` 5秒超时。本轮没有重启Docker；已请求确认重启对其他容器的影响。
- 新迁移 `workshop_reporting.0014_workreport_history` 已编写，尚未运行迁移漂移检查、隔离迁移或正式迁移。OpenAPI校验、后端相关回归和真实API浏览器删除流程仍待Docker恢复后完成。

## 恢复环境后的验证入口

后端使用 `config.permissions_deletion_test_settings`，TEST库固定为 `test_haiqu_access_deletion_20260929`。先跑两份新增后端测试，再跑车间相关回归；测试命令不能换成无指定settings的主环境命令。真实浏览器另配实际NAME指向该隔离库的preview settings，等待数据库测试完全结束后再开始。

```
docker compose exec -T backend python manage.py test apps.workshop_reporting.tests.test_work_report_deletion apps.workshop_reporting.tests.test_work_report_deletion_concurrency --settings=config.permissions_deletion_test_settings --keepdb --noinput --verbosity 2
docker compose exec -T backend python manage.py makemigrations --check --dry-run
```

所有源码变更保留在ERP目录。独立财务项目未改动；本轮没有写入正式授权、切换正式开关或删除真实报工。当前状态为代码及前端验证完成、后端和完整业务验收受环境阻塞，不能报告本段已经正式完成或可启用。
