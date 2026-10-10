# D4 统一外发列表实现结果（隔离验收版）

日期：2026-09-30

## 本次范围

本次只实现已确认的“统一外发列表”页面，运行在隔离验证副本 `qa/tube_revision_s3_20260929`，未改动正式 ERP 源码目录，也未写入业务数据。

页面沿用已确认设计：1920×1080、表头 44px、行高 40px、控件 32px、单行省略、表格内部滚动、可见分页、无勾选框、主题色 `#c84e28`。

## 已实现内容

1. 把管材外发记录加入统一外发列表，使用独立行标识 `TUBE:{id}`，不与旧流程同 ID 冲突。
2. 加入三类管材来源：原材料、未喷塑半成品、未入库半成品；旧金工加工件单独显示为“金工加工件（旧流程）”。
3. 增加来源分组筛选，保留旧流程的状态、工艺、加工厂、搜索、删除/撤销权限和历史单展示。
4. 管材按支显示发出、回货和差额；合法的 0 支回货显示 `0 支`，凭证缺失不伪造为 0；尚未发出显示“未发出”，尚未回货显示“未回货”。
5. 加工厂筛选只投影所选加工厂的数量，状态仍按整单显示，并提示“数量仅含所选加工厂 · 状态仍为整单”。
6. 管材行只有“查看”入口，进入 `/workshop/outsourcing/tube/:id`；保留“新建管材外发单”入口 `/workshop/outsourcing/tube/new`。
7. 后端按当前页批量读取冻结摘要、发出动作和最终回货凭证；不读取动态 BOM、动态报工、采购批次或额度服务，避免列表逐行查询拖慢页面。

## 验证结果

- 管材专项后端测试：11/11 通过（独立测试库 `test_tube_d4_unified_20260930b`）。
- 前端类型检查：通过。
- 外发相关前端测试：73/73 通过（列表 12、管材详情 28、管材结束页 33）。
- 前端生产构建：通过；只有既有的大包体积提示。
- 后端 `manage.py check`：通过。
- `makemigrations --check --dry-run`：`No changes detected`。
- Python 编译检查：通过。
- 真实浏览器验收：4/4 通过；来源、状态、加工厂、搜索、查看和新建路由均已实测；1920×1080 截图无页面错误、无控制台错误、无业务写请求。
- 代码只读复核：未发现 Critical 或 Important 缺陷。

真实截图：

- [统一列表首屏](/E:/workspace/_project/project001_haiqu_ERP_CRM/qa/tube_revision_d4_list_implementation_20260930/screenshots-final/real-list.png)
- [加工厂筛选](/E:/workspace/_project/project001_haiqu_ERP_CRM/qa/tube_revision_d4_list_implementation_20260930/screenshots-final/real-factory.png)
- [无匹配结果](/E:/workspace/_project/project001_haiqu_ERP_CRM/qa/tube_revision_d4_list_implementation_20260930/screenshots-final/real-search-empty.png)

## 已知限制

旧的 `test_unified_orders` 基线中有既存的公共库存开关和 P4 测试夹具问题，导致部分旧测试在进入统一列表断言前失败；专项管材测试和本次真实浏览器验收未受影响。这不是本次页面逻辑的通过证明，因此没有把旧基线标记为全量通过。

当前结果是隔离验收版，尚未把代码激活到正式 ERP 源码目录；正式激活前仍应针对正式目录做一次冲突检查和启动验收。
