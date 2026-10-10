# 用料需求参照 BOM 编辑交互

## 本次范围

以当前 `BomEditorView.vue` 的实际交互为依据，调整打样材料填写页，不改 BOM、不新增生产计算字段、不改变材料提交仓库的状态流转。

- 管材 / 面料：添加行，现有生产字典可下拉选择或手动填写。面料维护中的 PU、PVC 等映射到材质。
- 五金 / 塑料件 / 包材：从同一材料主档搜索，分页多选，带入名称、规格、材质、颜色、单位；需求数量留空。
- 辅料：读取辅料维护资料，按品名选择对应规格、颜色和单位；无法匹配有效单位时需手动选择。
- 行内编辑、放大编辑、应用修改、保存编辑下一条 / 保存新增下一条、删除确认及全屏。
- 抽屉修改先留在本地；应用才更新表格，页面保存草稿才写入服务端。取消尚未应用的新行不生成空行。
- 保留未保存离开保护、只读权限、数量校验、ETag 并发控制和提交仓库逻辑。

## 文件

前端修改：
- `components/samples/SampleMaterialEditor.vue`
- `views/samples/SampleMaterialRequestView.vue`
- `api/sampleMaterials.ts`、`types/sampleMaterial.ts`、`utils/sampleMaterial.ts`
- `styles/crm/_sample-controls.scss`：保持原 scoped 用法，增加仅限指定弹窗的普通选择器输出。

新增可复用的材料组件：
- `components/samples/SampleMaterialPicker.vue`
- `components/samples/SampleMaterialLineDrawer.vue`
- `components/samples/SampleMaterialFieldInput.vue`
- `styles/crm/_sample-material-overlays.scss`：两种弹窗共用已有打样 Token 和控件规范。

复用：`PinyinFilterSelect`、`SampleMaterialTabs`、现有全屏和未保存保护、Element Plus 基础控件、Warm ERP SCSS。

后端：新增 `material_reference_selectors.py`；在 `api/material_views.py`、`api/material_serializers.py`、`api/views.py` 增加两个只读资料接口及 `samples.edit_sample_materials` 权限校验。不需要 BOM 编辑或材料主档管理权限，不返回成本字段，无数据库迁移。

测试：`components/samples/SampleMaterialEditor.spec.ts`、`views/samples/SampleMaterialFlow.spec.ts`、后端 `tests/test_material_reference_api.py`、浏览器 `qa/sample_material_bom_interaction.cjs`。

## 验证

- 后端材料及资料接口 15 项测试通过，覆盖有效资料、停用过滤、分类搜索、字段对应、权限及原材料仓库交接。
- 前端 8 文件 44 项专项测试通过，覆盖跨页选择、重复材料、取消、连续编辑、重复点击、保存和只读边界。
- `npm run type-check` 和生产构建通过；构建存在原有第三方 PURE 注释和大包警告。项目未配置 lint 脚本，无新增依赖。
- 真实 Chrome 1920×1080：从列表创建申请、厂长退回重提、确认、选择材料、放大编辑、连续编辑、全屏、保存刷新、提交仓库；接口响应无模拟，使用隔离数据库 `qa_sample_application_20260910`。
- 测得 Sidebar 230px、Topbar 64px、抽屉 600px、页面无横向溢出；两个弹窗主按钮背景为 `rgb(200, 78, 40)`。人工检查普通页、抽屉及材料选择弹窗截图。
- 截图和最终运行证据：`outputs/sample_material_bom_interaction_20260910/`。

## 边界

本次以现有 BOM 交互为新增要求，沿用打样页布局；没有改写 Figma，也不宣称新增弹窗已与 Figma 逐像素一致。选入材料使用文字快照，仍由仓库核实规格、颜色和可供数量；没有自动占用或扣减库存。材料主档缺失时可手填，提交仍必须有有效单位和正数需求数量。验收记录仅写入隔离库。
