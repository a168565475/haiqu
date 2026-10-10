# 打样材料填写与仓库核对接通记录

## 本次交付

- 沿用现有 Figma 材料填写页 `1878:18504` / 全屏 `1880:19771`、仓库核对页 `1887:18596` / 全屏 `1891:18615`。
- 材料草稿可保存、刷新恢复，提交后冻结名称、规格、材质、颜色、需求数量及单位快照。
- 仓库草稿保存可供数量和备注；提交前必须逐项确认，允许 0，不允许负数、超过需求或超过 14 位整数 / 4 位小数。
- 采购缺口用服务端十进制运算计算；仅正缺口生成一次性独立打样采购需求快照。全额可供时不生成采购需求。
- 列表接入真实仓库、采购状态统计和筛选，材料情况展示未填写 / 填写中 / 待核对 / 缺料 / 已齐备；查看动作进入当前环节页面。

## 状态与采购兼容边界

`MATERIALS_PENDING → WAREHOUSE_PENDING → PROCUREMENT_PENDING（有缺口）/ MATERIALS_READY（无缺口）`

现有生产采购申请必须绑定生产任务和 BOM。打样需求没有这些关联，因此使用独立 `SampleMaterialProcurementRequest` 保存仓库确认时的缺口来源，采购人员可在打样列表“待采购处理”进入只读核对页并查看缺料。

本次交付到缺料需求交接为止，尚未实现打样采购的供应商分配、采购下单、到货及补料流转。独立快照没有伪造生产任务或 BOM，也没有改动现有采购业务流程。

材料库存接口是已验收入库汇总，缺少独立颜色字段和可扣减余额。库存参考只查询同名称、规格、材质、单位的候选；颜色、占用及实际可供量由仓库核实。缺少库存权限或无候选时显示未知，不显示虚假零库存。本次确认不扣减、预留或锁定实际库存。

## 接口与权限

- `GET /api/v1/sample-requests/material-units/`：当前有效生产单位，仅需样品查看权限。
- `GET/PUT /api/v1/sample-requests/{id}/materials/`：读取 / 保存材料；PUT 为 `{draft: {lines, notes}, submit: boolean}`。
- `GET/PUT /api/v1/sample-requests/{id}/warehouse-review/`：读取 / 保存仓库核对。PUT 只接纳行标识、可供数量及备注，不接纳对需求字段的修改。
- 读取响应含 `available`、`draft`、`etag`、`canEdit`、真实状态及交接时间；仓库另含库存刷新时间、确认时间、采购快照。
- PUT 必须携带 `If-Match`；缺失返回 428，过期返回 412，流程不允许返回 409。事务内锁定申请，确保供料、采购快照、状态和审计一起提交或回滚。
- 新权限：`samples.edit_sample_materials`（材料填写）、`samples.review_sample_materials`（仓库核对）、`samples.view_sample_procurement`（查看缺料需求）。普通账号需管理员按岗位授权，并具备 `samples.view_samplerequest`；超级管理员已有权限。
- 部门读取范围从其交接阶段开始；原有客户 / 申请人数据权限继续有效。库存详情另遵守 `inventory.view_materialinbound`。

## 文件与复用

前端：
- `src/frontend/src/api/sampleMaterials.ts`、`sampleWarehouse.ts`、`sampleApplication.ts`
- `src/frontend/src/types/sampleMaterial.ts`、`sampleWarehouse.ts`、`sampleApplication.ts`、`sample.ts`
- `src/frontend/src/views/samples/SampleMaterialRequestView.vue`、`SampleWarehouseReviewView.vue`、`SampleListView.vue`
- `src/frontend/src/components/samples/SampleWarehouseComparison.vue`
- `src/frontend/src/utils/sampleMaterial.ts`、`sampleWarehouse.ts`、`samplePresentation.ts` 及相关测试

后端：
- `src/backend/apps/samples/material_services.py`
- `src/backend/apps/samples/api/material_views.py`、`material_serializers.py`
- `models.py`、`selectors.py`、`application_services.py`、`api/views.py`、`api/serializers.py`
- `migrations/0022_material_warehouse_flow.py`、`0023_material_procurement_snapshot.py`
- `tests/test_material_api.py`

复用 `SampleMaterialEditor`、`SampleMaterialTabs`、`SampleWarehouseComparison`、`SampleInventoryLookup`、`SampleStatusTag` / `CustomerActivityTag`、`SampleReadonlyField`、`SampleFullscreenHeader`、现有未保存保护、全屏、SCSS Token 和控件规范。没有新增公共 UI 组件或运行依赖。

## 验收证据

- 后端 57 项专项测试通过，包括新材料 API、申请/厂长 API、旧样品 API；覆盖草稿、冻结、权限、部门读取范围、最小权限单位读取、非法数量、ETag、原子回滚、正缺口及零缺口。
- 前端 8 文件 51 项测试通过；包括真实 API 契约、只读状态、保存失败保留内容、提交期间禁用、库存刷新不覆盖未保存数量、版本变更关闭提交。
- `npm run type-check`、生产构建通过；构建保留现有 PURE 注释和大包警告。项目未配置 lint 脚本。
- OpenAPI 验证 0 错误、454 条警告（158 类）；材料响应明确使用专用响应封装。
- 真实浏览器 1920×1080 全流程使用独立数据库 `qa_sample_application_20260910`，脚本 `qa/sample_material_flow.cjs`。实际完成创建、退回重提、厂长确认、材料保存刷新、提交仓库、供料保存刷新、全屏、仅看缺料、缺口采购交接、列表回查，无页面运行时错误。
- 截图和 JSON 证据：`outputs/sample_material_flow_20260910/`。量测：侧栏 230px；顶栏含边框 64px；内容 padding 28px；仓库表宽 1586px、行高 82px；缺口列宽 150px，背景透明；列表状态标签高 24px。普通页标题标签沿用该页原型的 34px。
- 日常环境只读脚本 `qa/sample_material_live_readonly.cjs` 验证列表、单位、统计返回 200，未发送业务写请求。
- 与原型的差异：真实菜单 / 账号 / 数据及流程状态；原型“已匹配”文案仅在有足够数据时才可成立，当前显示库存候选参考或待匹配。已确认的缺口无背景规则保持不变。

## 部署

- 迁移前备份：`backups/haiqu_before_material_flow_20260910.dump`，2,273,520 字节，PostgreSQL CUSTOM 格式。
- 本地业务库已应用样品迁移 0022、0023；`manage.py migrate samples --check` 通过。
- 全项目迁移检查发现其他任务的 `inquiries.0008_inquiry_worktime_policy` 尚未应用，本次未执行该迁移。
- 业务库没有插入浏览器测试记录。验收库与业务库隔离。
