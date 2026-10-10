# P4-D2 半成品按部位领料开发结果

日期：2026-09-22

> 2026-09-23 更正：下文第 4、5、6 项属于当时实现记录。用户现已确认 A，管材半成品允许任意正整数支，已移除半成品整根限制和伪扣根米显示；原料整根规则不变。真实 12→5→7 验收见 `material_flow_direct_handoff_p4_semi_integer_result_20260923.md`，历史已出库数据未批量转换。

## 已完成

1. 生产领料需求接口的半成品行按“生产任务、产品、BOM 部位、已完成工艺、颜色、单位、半成品库区”汇总。
2. 页面不显示回货批次和先进先出选择；库区仍然单独显示，避免跨分区扣减。
3. 页面提交时由前端按可用余额自动拆分成后台库存余额行，操作者只填写部位合计支数。
4. 管材半成品从 BOM 读取“每根切割支数、原材料长度”，输入支数必须是整根倍数；界面即时显示预计扣根数和扣米数，后台再次校验。
5. 领料明细保留实际支数，并在 `conversion_snapshot` 保存扣根数、扣米数和换算快照；确认出库仍复用现有半成品库存流水，不恢复或重复扣原料。
6. 新外发单的半成品库存查询补充库区汇总、每根支数、原材料长度和整根校验标识。

## 修改位置

- `src/backend/apps/material_issues/api/views.py`
- `src/backend/apps/material_issues/services.py`
- `src/backend/apps/material_issues/p4_services.py`
- `src/backend/apps/material_issues/tests/test_material_flow.py`
- `src/backend/apps/material_issues/tests/test_metal_processing_p4.py`
- `src/frontend/src/components/workshop/MaterialIssuePartitions.vue`
- `src/frontend/src/views/workshop/material-issues/MaterialIssueFormView.vue`
- `src/frontend/src/views/workshop/material-issues/MaterialIssueDetailView.vue`
- `src/frontend/src/utils/materialIssueQuantities.ts`
- `src/frontend/src/types/materialIssue.ts`

## 验证

- Django `check`：通过。
- `makemigrations --check --dry-run`：无迁移漂移；本步骤没有新增迁移，也没有写入主库。
- 半成品领料相关 `MaterialIssueFlowTests`：18 项通过。
- P4 退回、重新加工、新外发、回货与半成品库区查询：3 项通过。
- 前端 `vue-tsc -b --pretty false`：通过。
- 前端计量单元测试：5 项通过；生产构建：通过（Vite 构建完成）。

## 当前限制

本步骤接入的是现有生产领料页和现有领料审核出库链路；P4 新外发页面的完整业务入口仍按已确认的 P4 图稿逐步接入，未扩大到旧管材历史转换、报废和不良品流程。
