# D3 管材整单喷塑回货接口（2026-09-30 已批准契约）

范围：仅 S3 隔离后端及前端。沿用 Session 登录、CSRF、防重复提交、现有可配置工艺范围。候选、预览、确认与原请求回查使用 `outsourcing.confirm_return_outsourcingorder`。只读凭证允许查看或回货权限各自在该原单冻结工艺范围内通过，不交叉拼接权限范围。实际发出凭证必须存在；计划或 BOM 后改不改变原单冻结喷塑颜色及实物身份。

路径基于 `/api/v1/tube-outsourcing-orders/`。所有响应包在 `data` 内。所有数量响应为整数字符串。

1. `GET receipt-candidates/?search=&source_kind=&page=1&page_size=50`
   返回 `{items,total,page,page_size}`。仅加工中、存在真实实际发出动作且无最终凭证的原单。搜索外发单号、生产单号、产品及原单加工厂；来源可选 `RAW_PIPE/PUBLIC_SEMI/METAL`；每页 1–100。
   行字段：`id,order_number,task_number,task_order_number,product_number,item_number,product_name,color,source_kind,source_label,actual_dispatch_date,expected_return_date,total_quantity,factory_names:string[]`。

2. `GET {id}/receipt-preview/`
   返回 `{order,etag,can_receive,blockers:string[],actor_name,today,warehouses,zones,receipt}`。`order` 为 D4 详情（冻结行的 `quantity` 是原实发支数）；日期为 `YYYY-MM-DD`。`warehouses:[{id,name}]`；`zones:[{id,warehouse_id,warehouse,name}]`。已完成原单允许查看或回货权限各自在冻结工艺范围内查看真实只读 `receipt`，不能继续登记；加工中仍必须具有本单回货权限。

3. `POST {id}/confirm-receipt/`，必须携带预览 `If-Match`。
   输入：
   ```json
   {"client_request_id":"UUID","receipt_date":"2026-09-30","warehouse_id":null,"remark":"",
    "lines":[{"order_line_id":"UUID","received_quantity":"0","shortage_reason":"未收到，本单结束","zone_id":null}]}
   ```
   原单全部明细完整且唯一提交。实收为 0 至实发的整数，空白/null 按 0；每个少回部位原因必填。有正数时一个有效半成品仓，正数行各自选择该仓有效库区；允许不同库区。零行不记位置，全零不选仓/区。不能注入身份、颜色、工厂、原数量。201 为首次成功；200 为相同原请求重放；均直接返回下面的凭证。

4. `GET {id}/receipt-by-request/{UUID}/`：原成功请求回查，返回真实凭证，未提交成功为 404。不能靠新请求重做未知结果。
5. `GET {id}/receipt/`：只读最终凭证。

凭证字段：`id,receipt_number,order_id,order_number,status:COMPLETED,source_kind,source_label,client_request_id,receipt_date,warehouse_id,warehouse_name,confirmed_at,actor_name,remark,total_dispatched_quantity,total_received_quantity,total_shortage_quantity,etag,created,lines`。

每行：`id,order_line_id,component_identity,part_name,material,specification,thickness,cutting_length_mm,raw_color,spray_color,factory_id,factory_name,dispatched_quantity,received_quantity,shortage_quantity,shortage_reason,zone_id,zone_name,stock_movement_id`。零行位置与流水 ID 为 null。正数行为真实已喷塑公共半成品入库流水，一支一支，不换根米；三来源使用原单同一冻结身份可合并公共库存。

首次确认整单原子入账、记录全部零行并将原单改为 COMPLETED；全零不创建库存流水。失败不保留部分凭证或库存。已发生实际外发数量继续占订单外发额度、金工首次产出及报工保护，不因差额或结单恢复；不扣原料、不退回未喷塑件、不做补登记。

常见失败：400 参数/范围/位置/差额原因或发出凭证不完整；403 当前权限或工艺范围不足；404 不存在/不可见；409 已最终登记或相同请求内容冲突；412 原单 ETag 已变化；428 缺少 If-Match。成功回货及回查返回当前订单 `ETag` 响应头。
