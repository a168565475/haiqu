# 委外统一入口只读接口（2026-09-27）

对应已确认方案：`outsourcing_unified_entry_plan_20260927.md`。

## 统一外发单

`GET /api/v1/unified-outsourcing-orders/`

沿用Session认证、有效员工检查。具有普通外发查看或金工来源查看权限即可进入，但每笔单据仍按原组织、任务和来源可见范围过滤。

参数：`page`、`page_size`、`search`、`status`、`craft_id`、`factory_id`、`source_kind`、`production_task_id`、`product_line_id`、`issue_id`。ID参数为UUID；状态和来源枚举非法时返回现有标准错误结构。数据库先合并符合范围的原单及重加工新单，再按更新时间和ID统一排序、计数、分页。

响应沿用 `{data: [...], meta: {...}}`，摘要兼容原外发列表，并增加：

| 字段 | 含义 |
| --- | --- |
| `record_type` | `ORIGINAL`原单、`REWORK`重加工新单 |
| `row_key` | 类型与原始ID组成的唯一行键 |
| `source_kind` | `RAW`仓库原料、`METAL`金工加工件、`REWORK`重加工件、`UNSELECTED`待选择 |
| `source_label` | 来源中文名称 |
| `dispatched_quantities` | 实际已发出量，数组项为`quantity`与`unit` |
| `returned_quantities` | 合格回货量，按单位分组；不与发出量跨单位相除 |
| `detail_access` | `REGULAR`沿普通详情权限可见，`METAL`仅通过金工来源投影可见 |
| `source_issue_line_id` | 可见金工领料明细定位；无关联时为空 |

只有金工通道可见的原单隐藏整单金额、交期等未获授权字段，数量只汇总可访问来源。双权限用户也逐单核对普通范围，不能因持有权限名称就跳过数据范围。金工首次原单不重复计入；重加工新单未记录独立交期时为空。

`GET /api/v1/unified-outsourcing-orders/options/`提供该列表的工艺、加工厂、状态和来源筛选项，沿用相同入口权限并集。

## 来源定位

`GET /api/v1/metal-processing-sources/`增加`original_order_id`、`source_id`查询参数，在原`processing_lines`可见范围内缩小结果，供单据详情定位真实来源。

## 路由及写入边界

- 原单详情：`/workshop/outsourcing/:orderId`；受限金工投影使用`?view=metal`。
- 重加工新单：`/workshop/outsourcing/rework/:orderId`。
- 来源区：`/workshop/outsourcing?tab=sources`。
- 旧`/workshop/outsourcing/metal-processing`兼容跳转，保留领料、任务、产品等查询参数。
- 预选金工来源使用`source_issue_line_id`读取真实记录，不持久化虚假的来源锁定。实际交接仍由原服务校验任务、产品、部位、加工厂、数量和并发版本。
- 本次新增接口全部只读；原写入接口、单位换算、库存事务、并发控制和幂等请求机制继续沿用。无新增表或迁移。
