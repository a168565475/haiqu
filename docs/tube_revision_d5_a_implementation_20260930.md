# D5-A 半成品库存页开发结果

日期：2026-09-30

## 开发前确认

- 已确认 D5-A 设计稿。
- 按用户意见删除顶部统计区，不混合统计支、套、个等不同单位。
- D5-B 半成品入库记录、D5-C 半成品领料本轮未开发。

## 本步改动

1. 材料库存页读取 `?stock_kind=SEMI`，直接进入半成品库存；切换原材料／半成品时同步路由参数。
2. 半成品筛选增加加工状态：未喷塑、已喷塑。后端按冻结库存属性中的工艺编码筛选，`METAL` 显示“未喷塑”，`POWDER_COATING` 显示“已喷塑”，其它工艺显示实际工艺名称。
3. 半成品列表增加“规格/切割长度”“厚度”“加工状态”列，保留材质、部件、颜色、数量、单位、材料仓、库区和最近入库日期；不显示采购批次。
4. “喷塑入库”沿用已有喷塑回货页面，按已有权限控制；“入库记录”沿用半成品入库记录入口。
5. 没有新增数据库表、迁移、半成品档案或采购批次关联。

## 验证结果

- 后端：`apps.inventory.tests.test_public_inventory_flow`，18 项通过。
- 前端：`npm run type-check` 通过；`WarehouseLoading.spec.ts`，7 项通过。
- 浏览器只读验收：`/inventory/materials?stock_kind=SEMI` 返回 3 条半成品，API 只有 GET，无业务写入；无页面错误和控制台错误。
- 浏览器尺寸：表头 44.5px（含边框渲染）、数据行 40px、控件 32px。

## 截图

- [D5-A 正式页面截图](../qa/tube_revision_d5_a_implementation_20260930/d5-a-formal-1920.png)
- [D5-A 浏览器验收记录](../qa/tube_revision_d5_a_implementation_20260930/browser-verification.json)

下一步需要重新提交 D5-B 设计图，确认后再开发半成品入库记录页；本步不包含 D5-B、D5-C。
