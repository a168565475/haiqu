# P4-D1 后端结果：退回、重新加工、新外发与合格回货

状态：P4-D1 已完成；P4-D2“半成品按部位聚合领料接口及前端接入”尚未开始。主数据库未迁移，未写入真实业务数据。

## 本步实现内容

1. 新增原金工完成件交接记录，校验交接量不超过“合格完成 − 已交接 − 待占用”；交接只增加已交接，不恢复原料根数、米数或来源额度。
2. 新增未喷塑退回记录，关联原外发单和原交接，登记接收人、金工暂存位置和日期；退回不写原料库存、不写半成品库存、不记不良或报废。
3. 新增重新加工记录，退回件可分次重新加工；累计重新加工支数不能超过该退回记录，原完成记录和原外发历史保持不变。
4. 新增独立 P4 外发单，关联原退回、新加工记录、加工厂和喷塑工艺；新加工完成量可拆分到多个新单，累计分配不能超量。
5. 新外发单交接要求实际交接支数等于已保存分配支数；原料不重复扣减。
6. 新外发单只登记合格回货，按支直接进入选择的半成品库区；不创建不良品字段、库区或原因。
7. 支持少回货备注结清；结清后仍可追加合格回货，追加必须写原因，原结清快照保持只读；累计足额后自动完成并锁定继续回货。
8. 半成品入库流水保存任务、产品、BOM 部位、喷塑工艺、库区和新外发单来源；领料聚合查询接口已预留，尚未接入领料写入流程。

## 新接口

- `POST /api/v1/metal-processing-sources/{issue_line_id}/handoffs/`
- `POST /api/v1/metal-processing-handoffs/{handoff_id}/returns/`
- `POST /api/v1/metal-processing-unsprayed-returns/{return_id}/rework/`
- `POST /api/v1/metal-processing-reworks/{rework_id}/orders/`
- `GET|POST /api/v1/metal-processing-external-orders/`
- `POST /api/v1/metal-processing-external-orders/{id}/handoff/`
- `POST /api/v1/metal-processing-external-orders/{id}/returns/`
- `POST /api/v1/metal-processing-external-orders/{id}/close/`
- `GET /api/v1/metal-processing-external-orders/{id}/semi-stock/`

写入接口均使用事务、请求幂等标识、权限校验和 `If-Match` 版本门禁；返回数量和库存身份由服务端确定，客户端不能伪造。结清后追加回货保持 `CLOSED` 状态，达到实际交接量后转为 `COMPLETED`。

## 代码和迁移

- `src/backend/apps/material_issues/models.py`：新增 P4 交接、退回、重新加工、新外发单、回货和结清模型。
- `src/backend/apps/material_issues/p4_services.py`：新增 P4 事务服务和半成品库存身份解析。
- `src/backend/apps/material_issues/api/p4_serializers.py`、`p4_views.py`：新增写入校验和接口。
- `src/backend/apps/material_issues/api/processing_views.py`、`api/urls.py`：接入原来源交接动作和 P4 路由。
- `src/backend/apps/material_issues/migrations/0007_metalprocessingoriginalhandoff_and_more.py`、`0008_alter_metalprocessingsource_options.py`：新增表、约束和权限。
- `src/backend/apps/material_issues/tests/test_metal_processing_p4.py`：覆盖 P4 正常链路、拆分、不恢复原料、结清后追加回货和超量阻止。

## 验证结果

- `manage.py check`：通过。
- `makemigrations --check --dry-run`：`No changes detected`。
- OpenAPI 生成校验：错误 0；项目原有警告仍存在。
- 隔离 PostgreSQL 种子回归：100 项全部通过（原相关回归 77 项、P3 20 项、P4 新增 3 项）。
- 主数据库：未迁移、未写入。

## 尚未完成

1. 半成品领料的后端写入：按任务、产品、BOM 部位、工艺和半成品库区聚合可用支数，不选择回货批次，不跨部位扣减。
2. 退回、新外发、回货和半成品领料的正式前端页面接入。
3. 1920×1080 浏览器真实页面验收和前端业务写入回归。

