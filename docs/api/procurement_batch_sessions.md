# 采购批次与供应商采购表

一次进入「新增采购批次」生成一个 `batch_session_id`。刷新页面和切换到同一个已打开的页签会继续使用这个标识。再次从采购需求点击「新增采购批次」会生成新的标识。

| 接口 | 字段与行为 |
| --- | --- |
| `GET /api/v1/purchase-groups/{id}/` | 可选查询参数 `batch_session_id` 为 UUID。传入时，`data.batch_page` 返回已分配的 `current_batch_number`、预计的 `next_batch_number`、本页已保存的 `submitted_line_ids` 和存在时的 `draft_orders`。只有保存成功才为页面分配批次号。 |
| `POST /api/v1/purchase-groups/{id}/submit-supplier-batch/` | `save_as_draft=true` 时必须传 `batch_session_id`。此时每家供应商独立保存为采购单草稿，同一页面内复用批次号。旧客户端省略该选项时沿用直接确认并生成采购表的流程。 |
| `POST /api/v1/purchase-groups/{id}/batches/` | 支持同一 `batch_session_id`，页面内保存草稿和进入确认时沿用本批。 |
| `POST /api/v1/purchase-groups/{id}/confirm-batch-page/` | 传 `batch_session_id`，统一确认同一采购需求和页面内未归档的采购单草稿。可在 `additional` 中带入确认窗口中一起列出的新增明细。一次事务确认全部采购单、生成各供应商采购表草稿。 |
| `GET /api/v1/supplier-purchase-sheets/` | 可用 `purchase_group_id` 读取一份采购需求下各批次的采购表，沿用现有数据范围和当前版本规则。每张表的 `purchase_batch_number` 来自对应采购单。未关联采购批次时返回 `null`。 |

批次号在采购需求事务锁内分配。旧客户端可以省略 `batch_session_id`，每次提交继续独立分配批次号。重复请求仍凭 `request_id` 返回原结果，写操作继续校验采购需求的 `If-Match`。

待统一确认的采购单草稿计入计划采购量，确认前采购数量仍按原有有效采购口径统计。统一确认失败时保留已保存的草稿。
