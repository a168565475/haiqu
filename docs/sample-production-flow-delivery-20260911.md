# 打样流程接通交付记录（2026-09-11）

## 本次范围

新申请以现有 `application_payload_hash` 区分。沿用创建、厂长确认及退回重提，不改历史财务／PMC流程。

- 打样部明确提交“无需用料”，或仓库确认足量供料，进入待金工参数上传。
- 缺料保持待采购；内部接收真实验收入库结果，部分合格入库仅更新进度，全部齐备后进入参数阶段。
- 两份参数与两项生产完成标志分别记录；参数齐全、生产未完成时为 `PRODUCTION_PENDING`（待生产完成）。所有条件满足才结束流程并允许样品入库。
- 入库候选查询与实际入库写入使用同一资格判断。新流程不补写虚假的财务或PMC审批。
- 列表“更多”固定提供查看用料需求；材料及仓库提交后只读。详情提供参数上传、精简报工和材料到货进度。

## 文件与组件

本次在原有未提交改动之上增量修改；以下清单只描述本任务的功能落点，不表示这些文件全部由本次创建。

| 范围 | 文件（相对项目根目录） |
| --- | --- |
| 新生产与到货服务 | `src/backend/apps/samples/production_services.py`、`material_arrival_services.py` |
| 状态、来源及数据库结构 | `src/backend/apps/samples/models.py`、`migrations/0024_production_material_arrivals.py`、`0025_material_purchase_source.py` |
| 材料及参数流程 | `src/backend/apps/samples/material_services.py`、`services.py` |
| 权限、详情与接口 | `src/backend/apps/samples/selectors.py`、`api/views.py`、`api/serializers.py`、`api/material_views.py`、`api/material_serializers.py` |
| 入库资格统一 | `src/backend/apps/samples/inventory_selectors.py`、`inventory_services.py`、`api/inventory_serializers.py` |
| 旧新版停留单预检 | `src/backend/apps/samples/management/commands/advance_ready_sample_applications.py` |
| 页面 | `src/frontend/src/views/samples/SampleListView.vue`、`SampleMaterialRequestView.vue`、`SampleWarehouseReviewView.vue`、`SampleDetailView.vue` |
| 新增可复用组件 | `src/frontend/src/components/samples/SampleMaterialProgress.vue`、`SampleProductionReportDialog.vue` |
| 前端接口与类型 | `src/frontend/src/api/samples.ts`、`sampleMaterials.ts`；`src/frontend/src/types/sample.ts`、`sampleMaterial.ts`；`src/frontend/src/utils/samplePresentation.ts` |
| 测试 | 后端 `test_application_production.py`、`test_material_arrivals.py`、`test_material_api.py`；前端 `SampleProductionReportDialog.spec.ts`、`SampleMaterialFlow.spec.ts`、`SampleListView.spec.ts` |
| 浏览器验收 | `qa/sample_production_connected_1920.cjs` |

复用 `SampleSection`、`SampleStatusTag`、`SampleMaterialApplicationInfo`、`SampleWarehouseComparison`、已有参数上传及样品入库／出库弹窗、Sidebar／Topbar，以及 CRM Token、`sample-dialog` / `sample-controls` SCSS。新增样式仅为 SCSS，无新增依赖。

## 接口与采购后续接入约定

1. `POST /api/v1/sample-requests/{id}/no-materials/`：打样部权限、当前状态及 `If-Match` 版本校验；保留已有草稿，明确标记无需用料并留记录。
2. `POST /api/v1/sample-requests/{id}/production-report/`：`items` 仅包含所属样品项目ID、金工／裁剪报工数量、两个完成标志。数量为0到打样数量的整数；项目不能增删、重复或跨样品。需要有效员工及现有样品修改权限。
3. 材料查询增加 `progress`，逐项返回需求、仓库供料、采购已入库和剩余缺口。
4. `receive_material_arrival(...)` 是内部服务，未开放手工到货接口。采购创建时需在同一事务中建立 `SampleMaterialPurchaseSource`，将采购行明确绑定缺料快照及材料行。不能按名称、规格相同猜测关联，也不能事后随意改绑。
5. 接收数量来自真实、已确认的材料验收入库行 `accepted_quantity`。不合格数量不计入；一个入库行只能分配给一个缺料来源，重复接收不重复累计。还会校验名称、规格、材质和单位。
6. 当前约定一个采购行对应一个样品缺料行。合并采购、多来源分摊、单位换算及后续退货／撤销入库回退，需要采购接入时明确处理。颜色需求保留在缺料快照，采购绑定时必须据此选择正确物料。

**未开发采购页面及其调用方，没有手工到货按钮或通知中心。当前真实缺料单仍停留待到货；不能把内部服务测试通过表述为采购业务已闭环。**

## 迁移与衔接

- 已应用样品迁移0024、0025；迁移前备份：`backups/sample-flow-before-20260911.dump`（2,428,154字节）。
- 已执行开发库只读预检，目前 `MATERIALS_READY` 候选为0；没有批量推进业务单，也没有补写生产完成标志。
- 以后可先执行以下预检，核实后只推进指定ID：

```powershell
docker exec haiqu-backend python manage.py advance_ready_sample_applications
docker exec haiqu-backend python manage.py advance_ready_sample_applications --apply --sample-id <已核实的样品ID>
```

## 自动验证

- 后端样品全模块回归：122项通过（独立测试库 `test_sample_production_20260911`）。之后补充到货权限重放测试，最新到货专项3项全部通过。覆盖历史审批、入库出库、新流程参数与报工先后顺序、材料门槛、版本和权限。
- 前端样品相关30个测试文件、236项全部通过。
- 样品范围严格类型检查通过：`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit -p .tmp/sample-production-tsconfig.json`。
- Django `check` 通过；`makemigrations --check --dry-run samples` 无未生成迁移；任务范围 `git diff --check` 通过。
- Vite生产打包通过，保留现有大分包警告。
- 最终完整 `npm run build` 通过（包含 `vue-tsc -b` 全项目类型检查及Vite生产打包）。此前报价、订单及路由文件的并行改动曾阻断检查；最终已消除，本任务未修改这些无关文件。日志：`src/frontend/.tmp/sample-production-build.log`。
- 当前无lint脚本，未声称执行lint。

## 浏览器及视觉验收

验收脚本仅将业务请求转发至18002专用隔离服务，数据库为 `qa_sample_application_20260910`；不向业务库创建验收单。页面来自实际前端，接口没有模拟。

共享8080开发服务在验收期间受报价页新增字体依赖和热更新影响，因此后续验收使用已成功构建的产物预览。最终执行结果、真实单据ID、截图和尺寸数据位于 `outputs/sample_production_connected_20260911/`。

视觉基准：最新Figma文件 `czPqlJ7fXYn5cq4cbQyTFm`、列表节点 `1897:18624`；1920×1080桌面，230px Sidebar、含底边框64px Topbar、24px自适应状态标签、深色申请编号。新增报工及到货区按已确认流程复用设计系统，不宣称它们具有独立Figma节点或全页面逐像素完全相同。

最终完整浏览器脚本运行通过（非断点续跑），使用最终构建产物 `src/frontend/.tmp/sample-production-preview-1459`，预览地址 `http://127.0.0.1:4174`。共享8080服务此前字体解析失败，末次只读检查报价页面模块已返回200。

实际操作路径：

- `6232995e-6f89-4778-abd0-025b01916833`：新建→厂长确认→无需用料→金工参数→裁剪参数→待生产完成→报工完成→入库2件→出库1件，最终剩余1件。入库单 `RK-202609-000015`，验证存在成品库存同步来源。
- `ec070266-f805-4c84-a436-67387c04a975`：真实创建／确认／材料接口建立前置状态，经列表进入仓库实际提交足量12，进入待金工参数上传。
- `3fe17923-98ce-4737-b30f-86f4e653a57e`：经仓库页面实际提交需求12、可供2，形成缺口10，材料显示待到货；上传参数权限为false。
- 所有业务写请求返回200／201，无页面脚本错误。

尺寸检查：10张1920×1080截图均无页面横向溢出，Sidebar230、Topbar64；列表测得30个状态标签全部为24px。实图检查并修正了新增报工弹窗默认按钮色、材料到货表默认边框及表头色，缺口数量没有背景色。

截图：`04-production-report.png`、`06-inventory-receipt.png`、`07-outbound-completed.png`、`07-list-status-and-materials.png`、`08-warehouse-full.png`、`08-warehouse-shortage.png`。完整记录见同目录 `evidence.json`。

采购验收入库通知的部分／全部到货、合格数量累计及重复事件通过内部服务与真实入库API测试验证；尚未由采购业务页面触发。退回重提、历史财务／PMC由既有后端回归覆盖，不能把它们写成本次浏览器逐项操作结果。

只读补验收通过：从最终列表的“更多→查看用料需求”进入已提交缺料单，入口只有一个，显示待到货及剩余10，提交按钮禁用且不显示“无需用料”。见 `10-submitted-materials-readonly.png`、`visual-evidence.json`。列表实测左右Padding28、标题区48、筛选与输入40、创建按钮180×36、表头44、行高52、申请编号颜色#1f1d18。新增区块已复用规范；未对共享导航菜单顺序、既有列表功能或全系统视觉进行改造。
