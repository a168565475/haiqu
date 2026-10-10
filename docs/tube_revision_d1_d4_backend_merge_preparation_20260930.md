# D1-D4 后端正式目录合并准备

日期：2026-09-30

## 检查范围

对照 `qa/tube_revision_s3_20260929/backend` 与正式 `src/backend`，只检查管材、库存、委外、报工和迁移依赖。没有覆盖正式目录中已存在的文件，也没有执行迁移或业务写入。

## 已复制的完全缺失文件

以下文件在正式目录不存在，已从隔离验收副本复制，保留原相对路径：

- `apps/inventory/tube_outsourcing_limits.py`
- `apps/inventory/tube_outsourcing_reservations.py`
- `apps/inventory/tube_processing_quantities.py`
- `apps/inventory/tube_processing_services.py`
- `apps/inventory/tube_receipt_services.py`
- `apps/outsourcing/api/tube_serializers.py`
- `apps/outsourcing/api/tube_views.py`
- `apps/outsourcing/tube_action_services.py`
- `apps/outsourcing/tube_models.py`
- `apps/outsourcing/tube_receipt_selectors.py`
- `apps/outsourcing/tube_receipt_services.py`
- `apps/outsourcing/tube_selectors.py`
- `apps/outsourcing/tube_services.py`
- `apps/workshop_reporting/tube_plan_services.py`
- `apps/outsourcing/migrations/0009_tubeoutsourcingorder_tubeoutsourcingline_and_more.py`
- `apps/outsourcing/migrations/0010_tube_action_lifecycle.py`
- `apps/outsourcing/migrations/0011_tube_final_receipt.py`

复制后通过正式后端容器执行上述 17 个文件的 `py_compile`。

## 仍需人工合并的已有文件

这些文件正式目录已经存在，隔离副本包含管材逻辑或与既有业务改动冲突，不能直接覆盖：

- `config/settings.py`：增加 `TUBE_OUTSOURCING_ENABLED` 配置项。
- `apps/outsourcing/models.py`：导入管材模型类。
- `apps/outsourcing/api/urls.py`：注册管材外发路由。
- `apps/outsourcing/unified_selectors.py`、`apps/outsourcing/api/unified_views.py`：统一列表的管材行、来源分组和选项接口。
- `apps/inventory/api/internal_receipts.py`、`apps/inventory/internal_receipt_limits.py`、`apps/inventory/internal_receipt_services.py`：管材半成品入库、数量上限、查询和回货凭证逻辑。
- `apps/inventory/public_stock_services.py`：管材外发预留数量校验。
- `apps/inventory/api/finished_receipts.py`、`apps/inventory/api/serializers.py`：隔离副本还包含颜色字段口径变化，需确认是否属于当前合并范围，不能自动覆盖。
- `apps/workshop_reporting/services.py`、`apps/workshop_reporting/deletion_services.py`、`apps/workshop_reporting/api/views.py`：管材报工锁、删除校验和计划状态逻辑。

以上文件的正式工作树与隔离副本均有其他改动，下一阶段必须按函数级差异人工合并，并在合并后做 Django 检查、迁移漂移检查、专项测试和正式浏览器验收。

## 未复制内容

管材专项测试文件和设计报告没有复制到正式源码；测试仍保留在隔离副本，避免把 QA 夹具和正式源码混在一起。迁移未执行。

## 后续状态（2026-09-30）

用户已确认正式激活。上述依赖已完成合并，专项测试文件已补到正式工作树用于正式容器执行；迁移已完成，具体结果见 [正式激活记录](tube_revision_d1_d4_formal_activation_20260930.md)。
