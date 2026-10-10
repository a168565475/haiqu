# CGDD2026091701 采购确认结果

2026-09-21，用户选择 A，授权确认本张采购单，保持金额和明细不变。北京时间 14:48:38，现有采购确认服务执行并提交成功。

| 项目 | 实际结果 |
| --- | --- |
| 采购单 | CGDD2026091701，来源 BOM0000399 |
| 状态 | DRAFT（待确认）→ SUBMITTED（已确认） |
| 金额 | 53,585.73 元，未变 |
| 明细 | 29 条全部字段保持不变，包括 ID、数量、单价、金额、供应商、交期和明细更新时间 |
| 主单 | 仅状态和更新时间变化 |
| 审计 | 新增 1 条 CONFIRMED，操作主体及本次入口标记符合预期 |
| 其他数据 | 241 表非目标数据、历史审计不变；全体目标明细另行精确比对不变 |
| 下游动作 | 没有生成采购表，没有发布或发送，没有到货入库、外发或领料 |

确认前重新检查已保存凭据、原值、来源完整性及供应商有效性，显式验证 `procurement.submit_purchaseorder` 确认权限。原有确认服务不检查 If-Match，因此本次专用入口在同一事务中、获得生产任务和采购记录锁后先核对冻结版本，再调用现有确认服务。没有更改应用业务代码。

提交前核对 29 条完整明细、主单字段和非目标数据，任何超范围差异都会使整笔事务回滚。提交后另启动数据库强制只读容器检查结果；详情 GET 返回 200，已确认状态、总额及行数一致。

## 备份与证据

证据目录：`qa/material_flow_business_trial_20260921/purchase_confirm_20260921/`。

- 新备份 `source.dump`：6,374,313 字节，SHA-256 `3f7a291c24cb6501f24150555858617c943318b8198112e421a02bdcda6c600b`。
- 独立新库 `haiqu_trial_confirm_20260921_144656` 恢复成功；241 表、30,348 条记录内容与确认前一致。没有覆盖业务库或既有演练库。
- `preflight.json`、`backup_verified.json`：权限、版本、原值与恢复检查通过。
- `receipt.json`：实际确认提交凭据。
- `verify.json`、`target_before.json`、`new_audit.json`、`full_before.json`、`full_after.json`：提交后独立核对、原值、审计及范围保护。
- 全库记录数 30,348 → 30,349，仅新增一条审计；只有 `procurement_purchase_order` 和 `audit_log` 两表内容发生批准的变化，整张 `procurement_purchase_order_line` 明细表内容指纹保持一致。
- `release.json`、`commands.log`：冻结脚本散列及命令退出记录。

新程序：同级上方目录的 `confirm_purchase.py` 和 `execute_purchase_confirm.py`。只复用旧保存程序的只读工具，不修改或调用旧保存入口；历史批准预览及已保存证据保持不变。独立只读代码审查通过，无必须修复项。

简单复核（既有 Python 环境，无新增依赖）：

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' qa/material_flow_business_trial_20260921/execute_purchase_confirm.py verify
```

成功输出 `CONFIRM_VERIFY_PASSED`。该命令只读；若后续已修改采购或其他保护数据，冻结核对会停止，应先核实新变化，不重跑旧确认。已存在完成凭据时 apply 入口拒绝再次执行；提交成功但凭据落盘失败需要人工核对，本次凭据正常。

## 验证边界与后续

本轮恢复核对覆盖全表内容，未单独进行结构/序列比较。详情接口使用进程内强制认证，只核对状态、总额和行数；全部明细字段一致性由数据库逐字段比对证明，不代表真实 Session/CSRF、浏览器视觉或多连接竞争验收。

报告收尾的补充离线汇总检查首次使用了缺少 `procurement_` 前缀的表名，产生 KeyError；核对实际快照键名后纠正并通过。该错误仅发生于已保存 JSON 的离线读取，未重跑业务确认，也未影响正式 verify 通过的结果。

后续只读模板选项检查显示：辅料、塑料件、面料有系统推荐模板，管材、包材、五金无分类匹配推荐。没有自动选择模板或新增模板，生成供应商采购表需先确认适用模板。模拟价格及参数仍不代表实际供应商报价或生产用量。
