# 生产排产 API V1

日期：2026-09-15。范围：主排产 P01–P04 与金工、裁剪、车缝、装配计划 P05–P08。

## 1. 业务规则

- 一张生产任务单同一时刻只允许一张 `ACTIVE` 有效排产；作废后可以重新排产，历史记录不删除。
- 来源任务必须为 `READY` 且未归档；不增加 BOM、订金或采购完成门槛。
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
| `GET production-schedules/task-files/{task_id}/{file_id}/` | 读取排产范围内已关联且安全扫描通过的任务产品图片 | `view_productionschedule` |
| `GET production-schedules/options/` | 查询工艺、计划分类和可访问客户 | `view_productionschedule` |
| `GET production-schedule-items/` | 按四类计划查询产品行 | `view_productionschedule` |

四类计划的 `category` 必须为 `METAL`、`CUTTING`、`SEWING` 或 `ASSEMBLY`。可使用 `schedule_id`、`schedule_product_id` 保留从主计划进入时的上下文。

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
