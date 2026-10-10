# 打样列表开发与验收 — 2026-09-10

来源：Figma `czPqlJ7fXYn5cq4cbQyTFm` / `1897:18624`，本轮实际读取设计上下文及节点尺寸。正式基准 1920×1080。

已使用 Frontend Design、figma-design-to-code 和 figma-use 技能。未找到已安装的 verification-before-completion 同名技能，按用户指定的先验证再报告流程执行。

## 本轮文件范围

- `src/frontend/src/views/samples/SampleListView.vue`：申请日期筛选；保存/恢复日期条件；批量操作锁定选择及 ETag；防重复提交；弹窗保存期间禁止关闭；编辑、删除入口权限检查。
- `src/frontend/src/views/samples/sampleList.scss`：输入框和快捷条 4px 圆角、占位文字色、筛选按钮顶对齐、表格外轮廓、Checkbox 对齐、分页位置。
- `src/frontend/src/utils/samplePresentation.ts`：本地自然日转接口时间范围、保存视图日期恢复。
- `src/frontend/src/types/sample.ts`：已有后端 `requested_from` / `requested_to` 查询参数类型。
- `src/frontend/src/App.vue`：仅为 samples 路由传入品牌变体。期间其他任务加入的 customer-contacts 等改动保留。
- `src/frontend/src/layouts/ErpLayout.vue`：新增可选的列表品牌图片属性，默认行为保持不变。
- `src/frontend/src/components/navigation/AppSidebar.vue`：仅 samples 路由按原型排列已授权菜单、调整样品子菜单图标/名称及底部间距；额外业务模块仍保留。
- `src/frontend/src/assets/crm-v2/sample-list-brand.svg`：从 Figma Brand 节点导出的实际 SVG，不是手绘图标。
- `src/frontend/src/router/index.ts`：删除详情路由 meta 中重复的同值 `flushPage: true`，解除共享工作区类型检查错误；未改变路由行为。
- `src/backend/apps/samples/api/views.py`：现有搜索字段仅增加 `products__product_name` 和 `items__product_description_snapshot`。没有修改状态、模型、迁移或业务流程。
- `src/frontend/src/views/samples/SampleListView.spec.ts`、`src/frontend/src/utils/samplePresentation.spec.ts`、`src/backend/apps/samples/tests/test_sample_api.py`：新增对应回归测试。
- `qa/sample_list_alignment_readonly.cjs`：真实导航和真实 API 的浏览器验收。

本轮修改前副本及差异文件位于 `outputs/sample_list_alignment_20260910/`。差异快照可能包含并发任务在共享文件中的新增内容，不能将其全部视为本轮变更。

## 组件复用

复用 `ErpLayout`、`AppSidebar`、`AppHeader`、`AppBreadcrumb`、`PageContainer`、`CrmPageHeader`、`DataTableToolbar`、`SampleStatusTag`（内部复用 `CustomerActivityTag`），以及 CRM tokens、mixins 和 sample-controls。

Input、Select、DatePicker、Button、Table、Pagination、Popover、Dialog 使用项目现有 Element Plus，通过页面作用域 SCSS 调整。当前没有通用 Filter / EmptyState 包装组件，沿用已有结构，没有为单个页面再造公共组件。未新增普通 CSS。

## 功能与兼容边界

- 搜索编号、客户、样品名称；兼容历史样品明细名称。多个匹配产品不重复返回申请。
- 真实状态、样品类型、业务员、本人负责、申请日期、快递单号筛选；重置、排序、分页、刷新、列设置、保存视图及导出保留。
- 日期使用后端已有 `requested_at`，不是表格的 `submitted_on`；起止日期按浏览器当地自然日边界转换为 ISO 时间。
- 查看详情、新建申请和现有更多操作保留真实路由及权限检查。
- 批量转交和提醒使用既有接口及 ETag，确认期间锁定打开时选择；终止态编辑不开放。
- 材料情况接口尚无对应字段，显示 `—`。
- 个人待办、厂长确认、仓库核对、采购处理四个新分类缺少对应统计和筛选接口：保留原型位置、显示未知并解释不可用，未借用财务/PMC/参数流程状态。
- 新建按钮能导航到现有创建页；该页的 V3 提交厂长接口仍未开放，本轮没有改变创建页或伪造提交成功。

## 验证结果

- `npm run test -- src/views/samples/SampleListView.spec.ts src/utils/samplePresentation.spec.ts src/api/samples.spec.ts src/api/sampleApplication.spec.ts`：4 文件、26 项通过。
- `npm run type-check`：通过。
- `npm run build`：通过。仍有既有依赖注释和大包体警告，不影响本轮构建；没有做无关依赖或打包重构。
- 项目无 lint 命令或配置，因此没有可执行的 lint 验收。
- 后端 `SampleApiTests` 六个专项通过：本轮的产品名称去重、旧名称和日期、搜索数据范围/权限，以及原有列表批量契约、完整产品列、跨客户范围测试。仅使用 Django 测试数据库。
- `node qa/sample_list_alignment_readonly.cjs`：真实导航、实际读取、搜索、状态/类型筛选、本人负责、日期、排序、分页、空结果、错误恢复、详情/新建入口、选中/悬停/焦点、加载态验证。浏览器业务写请求为 0。

## 视觉证据

输出目录：`outputs/sample_list_alignment_20260910/`。

- `list-1920.png`：正式基准截图。
- `list-more-filters.png`、`list-date-filter.png`：日期筛选。
- `list-selection.png`、`list-loading.png`、`list-empty.png`、`list-error.png`：交互与异常状态。
- `list-1440.png`：仅兼容检查，整页无横向溢出，表格内部滚动。
- `list-live-evidence.json`：实际几何、色值、查询、控制台错误和业务写请求记录。

核对值：Sidebar 230；Topbar 64；正文 x=258、宽 1634；左右 Padding 28；标题区域 y=92/h=48；快捷条 h=46；筛选 y=202/h=40；工具栏 y=256/h=36；表格 y=314；表头 44；行高 52；分页 y=982/h=80；输入高度 40；按钮高度 36；Tag 高度 24，自适应文字宽度。列宽依次为 40/214/214/266/78/90/88/124/156/148/216。

与原型仍有的差异：真实记录、状态、统计和页码不同；原型未包含的产品管理/生产车间入口因现有业务需要保留；四个新分类和材料情况受接口缺失影响。未声称整页逐像素完全相同。
