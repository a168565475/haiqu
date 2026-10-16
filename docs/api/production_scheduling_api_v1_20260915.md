# 生产排产 API V1

日期：2026-09-15，2026-10-16 更新来源展示与入口门禁。范围：主排产 P01–P04 与金工、裁剪、车缝、装配计划 P05–P08。

## 1. 业务规则

- 一张生产任务单同一时刻只允许一张 `ACTIVE` 有效排产；作废后可以重新排产，历史记录不删除。
- 来源任务必须为 `READY` 且未归档，全部产品最新有效 BOM 为 `VERIFIED`，关联有效采购订单为 `COMPLETED`。生产任务列表、详情的“计划排产”入口同时检查这些条件和排产权限，服务端创建时再次校验。
- 采购完成沿用采购模块的 `COMPLETED` 状态，不据此推断所有材料已足量入库。
- 每个选中产品的排产数量为正整数，且不得超过任务产品数量。
- 材料入库、金工回货、车缝回货、成品入库四个日期全部必填。
- 每个产品厂内、厂外工艺合计至少一项；任意一侧可以为空。
- 创建通过 `client_request_id` 幂等；编辑、作废必须发送详情响应的 `ETag` 到 `If-Match`。

## 2. 接口

统一前缀：`/api/v1/`。

| 方法与路径 | 用途 | 主要权限 |
|---|---|---|
| `GET production-schedules/` | 分页查询排产单 | `view_productionschedule` |
| `POST production-schedules/` | 创建排产单 | `add_productionschedule` |
| `GET production-schedules/{id}/` | 查询详情并返回 ETag | `view_productionschedule` |
| `PATCH production-schedules/{id}/` | 编辑整张排产单 | `change_productionschedule` |
| `POST production-schedules/{id}/void/` | 整单作废 | `void_productionschedule` |
| `GET production-schedules/task-candidates/` | 查询 READY 任务候选 | `view_productionschedule` |
| `GET production-schedules/task-candidates/{task_id}/` | 查询任务与全部产品来源版本 | `view_productionschedule` |
| `GET production-schedules/task-files/{task_id}/{file_id}/` | 读取可访问任务的产品图片或其明确关联销售订单行图片，并校验归档、扫描策略和文件路径 | `view_productionschedule` |
| `GET production-schedules/options/` | 查询工艺、计划分类和可访问客户 | `view_productionschedule` |
| `GET production-schedule-items/` | 按四类计划查询产品行 | `view_productionschedule` |

四类计划的 `category` 必须为 `METAL`、`CUTTING`、`SEWING` 或 `ASSEMBLY`。可使用 `schedule_id`、`schedule_product_id` 保留从主计划进入时的上下文。

候选产品及摘要增加 `specification_display`（剥离由独立字段证实的历史颜色、材质尾缀）和 `material`（任务产品材质快照）。原 `specification` 与来源版本哈希保持原契约。

候选 `image_file_id` 优先取任务产品主图，其次为任务多图；任务无图时仅回退到其明确关联、属于任务所选销售订单及交付批次的订单产品行图片。文件接口沿用任务访问权限，不按相同产品编号借用其他订单图片。新建或编辑排产时保存同一来源图片，不批量回填历史任务或排产记录。

## 3. 写入请求示例

```json
{
  "production_task_id": "任务 UUID",
  "source_revision_hash": "64 位来源版本哈希",
  "client_request_id": "本次创建请求 UUID",
  "items": [
    {
      "product_line_id": "任务产品 UUID",
      "planned_quantity": 100,
      "material_inbound_date": "2026-09-16",
      "metal_return_date": "2026-09-20",
      "sewing_return_date": "2026-09-23",
      "finished_inbound_date": "2026-09-26",
      "craft_ids": ["工艺 UUID"]
    }
  ]
}
```

编辑请求不发送 `production_task_id` 和 `client_request_id`，但必须发送完整 `items` 与当前 `source_revision_hash`。

## 4. 状态与错误

- `400`：字段、日期、数量或工艺校验失败。
- `403`：没有对应权限或数据范围权限。
- `409`：已有有效排产、来源已变化、工艺已停用或记录状态冲突。
- `412`：`If-Match` 对应版本已过期。
- `428`：编辑或作废缺少 `If-Match`。

## 5. 部署说明

部署时按正常发布流程执行前向迁移：先增加 `Craft.plan_category`，再建立三张排产表和排产单号规则。当前开发过程未对正式业务库执行迁移，也未写入演示排产数据。
