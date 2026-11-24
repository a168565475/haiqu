# 生产排产 API V1

日期：2026-09-15，2026-11-05 更新逐产品 BOM 排产与整单完成保护。范围：主排产 P01–P04 与金工、裁剪、车缝、装配计划 P05–P08。

## 1. 业务规则

- 一张生产任务单同一时刻只允许一张 `ACTIVE` 有效排产；作废后可以重新排产，历史记录不删除。
- 来源任务必须为 `READY` 且未归档，至少一个产品的最新未归档 BOM 为 `VERIFIED` 即可进入排产；实际提交的每个产品都必须满足该条件，其他未选产品缺 BOM 或待确认不阻断。生产任务列表、详情及排产候选入口一致，服务端创建和编辑时再次校验。
- 采购进度仅供参考：未建采购、采购草稿、采购中都不阻断排产。保存排产不代表材料已入库或实际开工。
- 同任务后续产品确认 BOM 后，通过编辑原有效排产计划加入；不新建第二张有效计划。任务仍有产品未纳入有效排产时，禁止整单完成；已移除的排产产品仍算未排产，旧作废计划不计入覆盖。
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
| `GET production-schedules/{id}/detail-summary/` | 只读查询每产品内部作业、外发、领料和金额汇总 | `view_productionschedule`，金额和关联记录另外校验来源模块权限 |
| `PATCH production-schedules/{id}/` | 编辑整张排产单 | `change_productionschedule` |
| `POST production-schedules/{id}/void/` | 整单作废 | `void_productionschedule` |
| `POST production-schedules/{id}/complete/` | 四项进度均为 100% 后完成关联生产任务单，按销售现有条件同步 | `access_control.finish_productiontask`（模块权限未启用时沿用 `production_tasks.change_productiontask`），同时校验排产读取与生产任务操作范围 |
| `GET production-schedules/{id}/completion-preview/` | 完成弹窗只读核对任务/销售状态、四项进度、逐产品要求量与累计成品入库量及提交版本 | 与完成入口相同，销售内容另校验查看权限与对象范围 |
| `GET production-schedules/task-candidates/` | 查询 READY 任务候选 | `view_productionschedule` |
| `GET production-schedules/task-candidates/{task_id}/` | 查询任务与全部产品来源版本 | `view_productionschedule` |
| `GET production-schedules/task-files/{task_id}/{file_id}/` | 读取可访问任务的产品图片或其明确关联销售订单行图片，并校验归档、扫描策略和文件路径 | `view_productionschedule` |
| `GET production-schedules/options/` | 查询工艺、计划分类和可访问客户 | `view_productionschedule` |
| `GET production-schedule-items/` | 按四类计划查询产品行 | `view_productionschedule` |

四类计划的 `category` 必须为 `METAL`、`CUTTING`、`SEWING` 或 `ASSEMBLY`。可使用 `schedule_id`、`schedule_product_id` 保留从主计划进入时的上下文。

2026-11-05：生产任务列表和详情新增 `has_confirmed_bom_product` 布尔字段，表示至少一个当前任务产品的最新有效 BOM 已确认；原 `bom_status` 继续表示整张任务的汇总状态，不改为单产品含义。排产候选详情的 `scheduling_ready` 表示有可排产品，前端根据每个产品原有的 `bom_status` 控制勾选。完成预览新增 `unscheduled_product_count`，大于 0 时提示先补齐排产并禁用确认；服务端的排产完成和生产任务完成接口均重新检查，不信任前端预览结果。

候选产品及摘要增加 `specification_display`（剥离由独立字段证实的历史颜色、材质尾缀）和 `material`（任务产品材质快照）。原 `specification` 与来源版本哈希保持原契约。

2026-10-17：四类内部计划的 `GET production-schedule-items/` 响应 `product` 同样增加 `specification_display` 与 `material`。颜色仍取排产产品快照 `color_name`；材质优先取快照已存字段，旧快照缺字段时取关联任务产品的 `material_snapshot`。规格仅在尾缀与独立颜色/材质字段一致时剥离；未知或不一致尾缀保留，缺材质返回空字符串。原 `specification` 和持久化快照不回写，权限、分页与数据范围不变。前端按规格、颜色、材质三列展示。

候选 `image_file_id` 优先取任务产品主图，其次为任务多图；任务无图时仅回退到其明确关联、属于任务所选销售订单及交付批次的订单产品行图片。文件接口沿用任务访问权限，不按相同产品编号借用其他订单图片。新建或编辑排产时保存同一来源图片，不批量回填历史任务或排产记录。

排产完成接口只接受当前有效排产、未归档且生产中的任务，并在事务及行锁内重新计算列表中的材料、金工、车缝、成品入库四项进度。四项 `percentage` 均为 `100` 才允许完成；使用列表现有整数四舍五入口径，不额外要求逐工序未舍入值满额。车缝包含裁剪与车缝，成品入库按原入库单累计量，不使用装配报工量。缺项、未配工价、不适用或进度不足均不放行。

请求头 `If-Match` 为排产详情版本；请求体仅接受 `{task_etag, reason, sales_order_etag?}`，其中 `task_etag` 为生产任务详情版本，`reason` 必填且最多 500 字（沿用任务状态说明字段长度）。实际数、合格数和生产批次字段不接受，完成时原样保留。成功更新生产任务为 `COMPLETED`、完成时间、排产更新时间，并写入审计；排产记录仍为 `ACTIVE`，列表的来源任务状态反映已完成。

关联销售订单仅在拥有 `access_control.complete_salesorder` 及该订单操作范围、提供匹配的 `sales_order_etag`、订单为已确认或履约中、累计发货覆盖有效交付需求且余款已登记完成时，调用现有正常完结服务同步为 `COMPLETED`。不执行异常关闭，不补造发货或收款记录。未满足条件、缺少权限或销售版本缺失/变化时，只完成生产并返回明确原因；销售同步发生非预期异常时整个事务回滚。响应为 `{data: {schedule_id, production_task_id, production_task_status, progress, sales_sync: {status, reason}}}`；同步状态为 `COMPLETED`、`SKIPPED`、`NOT_APPLICABLE` 或 `ALREADY_COMPLETED`。

2026-10-21 弹窗追加：`completion-preview/` 返回 `{data:{schedule_id,schedule_number,schedule_etag,task,progress,products,sales_order}}`。`task` 含任务编号、状态/显示名和 `etag`；`products` 逐产品返回独立规格、颜色、材质、单位以及 `required_quantity`、`received_quantity`。要求量取当前生产任务产品数量，累计入库量取该任务产品的成品入库原单 `received_quantity` 合计，包含已出库部分，不取库存剩余数量，不等同销售订单总量，也不混单位合计。预览没有写入或审计副作用。

销售预览仅在 `sales_orders.view_salesorder` 及该权限对象范围都满足时返回编号、状态和 `etag`；否则均为 `null` 并说明不可读取。`can_sync` 另外校验销售完结权限与对象范围；前端只在其为真且取得版本时附带 `sales_order_etag`。正式提交继续按原规则重新校验。

完成响应新增 `production_sync:{before_status,after_status}`，`sales_sync` 新增同名前后状态字段；缺少销售读取授权时新增字段为 `null`，原同步结果状态及说明语义保持。客户端提交中显示核验及等待更新结果，收到响应后显示实际前后状态和同步/跳过原因，保留弹窗供核对，不用定时器伪造分阶段成功。未收到响应或代理异常时标为“结果待核实”，禁止直接重复提交，需要关闭后刷新核实。

### 2.1 排产详情执行摘要（2026-10-20）

`detail-summary/` 返回 `{data: {schedule_id, products, totals}}`。每个产品用 `schedule_product_id` 关联详情产品行，包含 `internal_plans`、`outsourcing`、`material_issues` 及各自金额状态。完整字段由 `api/detail_serializers.py` 定义并登记在 OpenAPI；该 GET 不创建或修改业务记录。

内部作业的 `estimated_wage` 按当天有效的已批准工价及计数快照计算；快照数量基数与本排产不一致时返回 `null/QUANTITY_BASIS_MISMATCH`。`reported_amount` 按本排产产品、车间及工艺累计历史报工金额，不用当前工价重算。工价和报工各自检查来源权限及车间范围；无权限、缺价、冲突或不完整金额返回 `null`，真实零金额返回数值字符串。历史移除产品或工艺存在报工时，不把可见部分显示为完整总额。

外发及领料按生产任务和产品关联，不能据此断言只属于本次排产。接口保留按单据、产品、部位、加工厂拆行的外发明细及各自数量单位；页面按 `order_kind + order_id` 归并为每张外发单一行，不展示物料/部位行。数量仅在全部已知且单位一致时合计，不能将不同单位混加或用实发减实收推算短少；数量为本产品单内加工量合计，不是成品排产数量。工厂去重展示，多种单价不取平均值。普通外发金额沿用四位精度后汇总，展示及最终小计保留两位，任一明细金额未知则单据金额保持未知。`outsourcing_planned_amount` 为可见关联记录的计划金额，包含取消记录，不代表结算金额。权限范围未覆盖完整排产时，`totals.complete_scope=false` 且整单金额返回 `null`。详情原有 `product` 同时提供独立的 `specification_display`、`color_name`、`material`，不回写历史快照。

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
- `428`：编辑、作废或完成缺少排产 `If-Match`。

## 5. 部署说明

部署时按正常发布流程执行前向迁移：先增加 `Craft.plan_category`，再建立三张排产表和排产单号规则。当前开发过程未对正式业务库执行迁移，也未写入演示排产数据。

## 生产事件时间轴（2026-10-22）

`GET /api/v1/production-schedules/{id}/timeline/`

- 权限：排产查看权限与该排产数据范围；各来源继续检查对应模块的查看权限和数据范围。
- 参数：`search`（事项/操作人/单号，最长100字）、`page`（从1开始）、`page_size`（默认20，最大100）。
- 返回：`data[]` 包含稳定事件ID、kind、title、actor_name、occurred_at、document_number、detail_path、changes；`meta` 包含 total/page/page_size。
- 时间：使用操作实际时间，默认按 occurred_at、稳定事件ID升序；前端以北京时间显示到秒。
- 来源：生产任务、BOM、采购申请/订单/采购表/退货、采购入库、排产、工价事件、报工、领料事件、普通/管材外发、金工加工/补加工凭证、厂内半成品入库、成品入库和出库。仅聚合真实日志/凭证，不回填伪造历史，不写业务数据。
- 查看详情返回白名单字段的历史变化及已有路由入口，不返回原始审计快照、IP、请求信息和金额。不存在独立详情路由或原单已删除时，保留事件详情，不提供失效单据入口。
- 补齐新报工创建审计、厂内半成品待入库删除审计、装配待入库删除审计，均与原操作同事务执行。历史报工创建可由真实创建时间与记录人快照显示；已删除的旧记录只有保存了归属和时间证据才可恢复索引。

## 排产列表进度口径修订（2026-10-22）

`GET /api/v1/workshop-reporting/schedule-progress-statuses/` 的列表展示字段：

- `stage_progress.METAL/CUTTING/SEWING` 分别显示“金工完成 / 裁剪完成 / 车缝完成”，均按厂内累计报工次数除以当前有效批准工价方案的需报工次数计算。每道明细分别封顶，超报不能抵消另一道欠量；未报工、未填写方案或需报工基数时为 0%。无可见工艺、范围不完整、版本冲突或数量基数不一致继续区分不适用与未知。金工、车缝不再依赖半成品入库或外发回货；原计划日期仍用于时间预警。
- 外发圈的 `outsourcing_status.METAL/SEWING.records` 以 `order_kind + order_id` 合并，每张外发单一条，包含单号、工艺、厂家、交期、状态、风险和未回数量；不再返回产品 ID 和部位。`remaining_display` 为按单位分开的未回数量文本；某单位任一行未知则该单位显示“—”，不使用部分数量冒充完整总数。每行未回数量先封底再汇总，超回不能抵消另一部位欠量。权限过滤、取消单排除、交期预警及回齐判定沿用原规则。
- `outbound_progress` 改为累计出库数量除以生产任务产品订单数量，不再以累计入库为分母。产品字段新增 `order_quantity`，保留 `received_quantity` 和 `outbound_quantity`；悬浮显示订单数量及出库数量。整单按各产品订单数量加权，每个产品分别封顶；订单 100 套、入库并出库 50 套时为 50%。产品范围不完整、无出库查看权限或分批排产归属不明时保持未知。
- 总进度仍为金工、裁剪、车缝、装配各占 25%；外发与出库不纳入。这里只调整列表展示，不改变既有完成订单的校验或任何库存凭证。

2026-10-24：四类内部计划列表新增 `production_task_status`，返回关联生产任务的实时状态（与任务状态枚举一致），不使用可能回退为‘进行中’的 `job_status` 推断入库资格。前端原入库菜单仅在该字段为 `IN_PRODUCTION` 时启用；其他状态保留菜单并提示‘仅生产中的订单可入库’。字段复用已加载的关联任务，不新增查询；权限、类别、分页及后端状态/数量/版本校验不变。
已有本浏览器待核对请求时保留原菜单进入路径，允许核对原提交；会话存储不可读时也保留入口由入库页报告恢复问题。此例外不放宽后端对新入库的状态校验。
