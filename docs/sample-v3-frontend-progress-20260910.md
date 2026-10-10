# 打样 V3 前端实现进度

目标来源：本任务附件 goal-objective.md。范围为最新已确认 Figma 对应页面的完整前端实现、现有 API 接入、逐页视觉与交互验收，最后运行全量检查并审查。当前未完成整个目标。

## 当前事实与边界

- Figma 文件：czPqlJ7fXYn5cq4cbQyTFm，业务页面 0:1。
- 当前最新 V3 有 7 个画板（5 个业务页面，材料与仓库各含全屏画板）。没有独立 V3 编辑、采购处理或完成画板。不得为满足页面数量擅自设计新页。
- 旧版详情、费用、物流、PMC、完成、样品库存/出库/借出仍存在；未替换范围需要继续核对，不可直接宣布全部完成。
- 保留现有工作区改动。本任务修改前的列表、App、Router、样品 API、Sidebar 已保存到 outputs/sample_v3_frontend_20260910/baseline。
- SCSS 已存在于项目依赖，不新增依赖。未找到 verification-before-completion、systematic-debugging、requesting-code-review 同名 Skill；使用等价的证据验收、根因定位和审查流程。

## 页面映射

| 页面 | Figma | Route | 代码 | 进度 |
| --- | --- | --- | --- | --- |
| 打样申请总列表 | 1897:18624 | /samples | SampleListView.vue | 已实现默认列、筛选、分页、排序、列设置、批量动作、保存视图、导出；已做真实浏览器只读验收 |
| 创建打样申请 | 1851:18496 | /samples/new | SampleApplicationCreateView.vue | 已实现分区、真实选项、来源、客户联系人、产品查询、图片选择、数量校验、离开保护；提交厂长接口缺失，Service 显式拒绝 |
| 编辑申请 | V3 无独立画板 | /samples/:sampleId/edit | SampleFormView.vue | 已修正仅报工保存适配、权限、版本与离开保护；真实只读验收通过；原布局仍待视觉适配 |
| 厂长确认 | 1812:18474 | /samples/:sampleId/director-review | SampleDirectorReviewView.vue | 已实现真实申请读取、退回必填及离开保护；1920/1440 浏览器验证通过；确认/退回接口仍缺失 |
| 填写材料 | 1878:18504 / 1880:19771 | /samples/:sampleId/materials | SampleMaterialRequestView.vue | 已实现六分区、简化字段、真实单位选项、增删、普通/全屏保留输入、未保存保护；1920/1440 浏览器验证通过；保存/提交仓库接口缺失 |
| 仓库核对 | 1887:18596 / 1891:18615 | /samples/:sampleId/warehouse-review | SampleWarehouseReviewView.vue | 已实现普通/全屏、可供校验和正缺口计算、真实库存查询；1920/1440 浏览器脚本通过；材料读取与核对写接口缺失 |
| 详情、PMC、完成 | 245:5933 / 765:8900 / 779:8870 | /samples/:sampleId | SampleDetailView.vue | 待核对 |
| 费用 | 258:5218 | /samples/:sampleId/fees | SampleFeeView.vue | 待核对 |
| 物流、反馈、再报价 | 258:5608 / 502:7853 | /samples/:sampleId/fulfillment | SampleFulfillmentView.vue | 待核对 |
| 库存、出库、借出 | 810:8933 / 812:8933 / 812:9236 | /samples/inventory、outbound、loans | 对应已有页面 | 待核对 |
| 批量选择弹窗 | 814:8933 / 814:9235 / 814:9529 | 上述页面弹窗 | 对应已有组件 | 待核对 |
| 库存单据详情 | 816:8933 / 816:9236 / 816:9535 | 上述页面单据详情 | 对应已有页面 | 待核对 |

## 已发现业务与 API 差异

1. 后端仍使用 DRAFT、PENDING_COMPLETION、PENDING（财务）、PMC_REVIEW、METALWORK_PENDING、CUTTING_PENDING、FINISHED 等状态，没有厂长确认、材料填写、仓库核对、采购缺料阶段。不得改显示名称伪装成新流程。
2. 列表行使用服务端真实状态；材料情况无字段，显示“—”。快捷分类已对齐 V3 的六项：全部申请、我负责的、待我处理、待厂长确认、待仓库核对、待采购处理。前两项接真实 summary 统计（本人负责用 owner_employee_id），后四项缺接口，显示“—”并说明不可用；不将旧流程计数改名为新阶段。
3. 后端 config/settings.py 的 SEARCH_PARAM 为 q，旧列表传 search 导致搜索被忽略；本次在 api/samples.ts 的列表/导出调用中添加适配，并通过真实无结果查询验证。
4. 样品名称搜索缺口已在列表专项修复：后端 search_fields 增加 products__product_name 与 items__product_description_snapshot，使用真实全量查询；详见 sample-list-alignment-20260910.md。没有在前端过滤当前页冒充搜索。
5. 完整创建接口要求手写单号、颜色明细、任务单图片；简化创建与来源创建走草稿/待工厂完善。都不等于 V3 提交厂长确认。api/sampleApplication.ts 为明确 TODO Service，返回不可用错误，不丢弃字段、不伪造 ID。
6. 产品接口和来源上下文没有产品外观图片字段；新页用“暂无产品图片”状态。参考图片仅在本页选择和预览，没有真实成功上传提示；参考图持久化接口缺失。
7. 创建页直接进入时允许用真实客户、联系人、员工和产品选项填写；带 sourceType/sourceId 时从真实 form-context 读取并锁定客户、联系人、员工。未改变旧 sample-request-new 来源批量创建入口，后续需核对。
8. 原申请可包含多个产品/色卡和报工数据，V3 单样品页编辑时必须保护这些数据，不能简单清空旧明细。
9. 材料单位来自真实 `/raw-materials/options/` 的 ProductionUnit（unit_name），不是通用 `/reference-data/units/` 的 Unit。前者没有单位小数精度，因此不擅自限制“支/个必须整数”。该接口需要 products.view_rawmaterialinformation 权限；未来打样材料选项接口应明确角色访问范围。
10. 材料需求读取、保存、提交仓库及仓库核对读取、保存、确认供料、提交采购均没有对应接口。分别由 api/sampleMaterials.ts 和 api/sampleWarehouse.ts 隔离；未知需求显示“—”而非零项，保存动作不会伪造成功或调用旧报工接口。
11. 库存 GET `/material-inventory/` 的 inventory_quantity 是 confirmed accepted_quantity 汇总，不是扣除占用后的可用量，且响应没有独立颜色字段。库存查询只能提供候选参考，不能自动认定同材质/颜色/单位匹配。前端供料输入和需求比较使用十进制字符串运算，仅生成正缺口采购项；接口恢复后仍需服务端锁库、单位和并发校验。
12. 旧后端状态不能跳转到新厂长、材料或仓库环节。新路由可加载真实申请进行只读检查，但列表暂不能冒充提供新阶段处理动作；待后端提供真实可用动作后接入。

## 本轮新增复用结构

- SampleReadonlyField、SampleApplicationSummary：只读字段和申请分区。
- SampleMaterialApplicationInfo、SampleMaterialEditor、SampleMaterialTabs：材料录入摘要、表格和六分区；仓库复用分区组件。
- SampleWarehouseComparison、SampleInventoryLookup：供料对照及真实库存候选查询。
- SampleFullscreenHeader、useSampleFullscreen、useSampleUnsavedChanges：全屏页头、退出焦点恢复、路由/浏览器离开保护。
- `_sample-workspace.scss` 复用工作区及固定页脚；`_sample-controls.scss` 隔离打样控件视觉并集中 V3 表单按钮主色。仅新增 SCSS，没有改变其他模块的全局样式。
- SampleStatusTag 的列表样式保持 24px 紧凑实色；page 变体按最新 Figma 使用 34px 页面顶部样式。

## 已执行验证

- npm run type-check：最新全量重查通过（exec session 97068，exit 0）。期间曾被 CustomerDetailView.vue:1000 的 TS2367 阻断，未修改该无关模块；其工作区内容更新后再次验证通过。
- 打样专项 Vitest：8 文件，33 测试通过（含列表、表单、材料单位适配、库存 API、数量边界、精确小数和正缺口筛选）。
- qa/sample_v3_list_readonly.cjs：真实入口、真实 GET 列表、搜索无结果、重置、排序、1920 尺寸与标签颜色、1440 无整页横向溢出通过。未执行业务写操作。
- qa/sample_v3_create_readonly.cjs：真实入口与 form-options、四个分区 1920 精确坐标、数量/必填入口、取消离开保护、1440 滚动与固定页脚通过。请求监听确认无 /api/v1/ 写操作。
- qa/sample_v3_director_readonly.cjs：真实申请读取、1920 分区、退回必填、接口缺失不提交、意见离开保护、1440 无横向溢出通过。
- qa/sample_v3_materials_readonly.cjs：真实申请/材料单位、六分区本地输入、全屏状态保持、保存失败提示、1920 普通/全屏几何和 44px 按钮、1440 表格内部滚动、离开保护通过。
- qa/sample_v3_warehouse_readonly.cjs：完整脚本已通过，验证真实申请页未知数据状态、1920 普通/全屏几何、1440 内部滚动和真实库存 GET。独立组件场景验证有数据时供料、正缺口筛选、普通/全屏采购缺口单元格透明背景；不能当成真实材料需求流程的端到端通过。errors=[]、writes=[]。
- 视觉截图与 JSON 证据：outputs/sample_v3_frontend_20260910。
- 第一次浏览器搜索失败已定位为 q/search 契约差异并修复。一次缩放截图捕获下拉关闭动画导致瞬时溢出，改为等待组件关闭和布局稳定后复验，无持续溢出。
- lint 未配置，不可写成通过。本轮最新 npm run build 通过（exec session 57641，4764 modules、22.67s）；仍有 VueUse PURE 注释及大于 500KB 的构建包警告。此前构建曾被工作区询盘/客户详情页当时的未完成编辑中断，保留了其改动。整个目标的最终全量 test 和完整代码 Review 尚未完成。
- 浏览器复验期间曾遭遇 InquiryDetailView.vue 缺结束标签及后端代理暂时拒绝连接，均未重启或修改其他任务代码。当前容器健康检查返回 ok；验收以每次实际结果为准。

## 接续重点

继续编辑/详情与其余实际页面。创建/编辑、来源入口、旧版未替换页面的核对不可遗漏。所有接口缺口留在明确 Service 中，不能以“前端已画好”宣布业务全流程完成。最终按目标文件指定 7 个栏目汇报；当前不能标记目标完成。

最新只读盘点：245:5933、258:5218、258:5608 均仍命名为“[已确认]”；502:7853 为“[开发确认]”。765:8900、779:8870 和样品库存画板仍命名“[草案]”，未依据命名擅自删除或重做。已读取 245:5933 的 get_design_context：白色旧壳层、状态进度、基本信息、样品明细、费用、物流、反馈、右侧任务/附件/时间轴；尚未按此改写现有详情。其与新流程、共享壳层和旧报工数据的对应关系需在继续实现前明确适配，不能覆盖现有数据或假造新阶段。

## 2026-09-10 11:22 编辑保存路径进展

- 已重新读取目标附件、项目规则、DESIGN、实际 API 与编辑代码，并复查 0:1 当前全部 SAM 画板。Figma 第一页现为设计系统封面，后续读取业务节点应显式切换 0:1，不能使用 children[0] 推断。
- 再次读取 765:8900 详情/PMC 的 get_design_context，作为尚未替换的实际状态页证据；未因此回退 V3 创建页，也未将旧样式宣称为 V3 编辑已完成。
- 旧编辑的 REPORT_ONLY 阶段错误复用完整表单校验，会因不可编辑的空规格、展示色卡/色号、空打样信息数组而阻止合法报工。新增 utils/sampleFormEditing.ts 按读取快照及原产品/行 UUID 合并，仅接纳报工数量、完成状态和特殊说明。
- 保留全部产品、来源、颜色、原需求数量、打样信息行 ID、尺寸与日期；未上传文件字段，服务端按原行 ID 保留任务单和材料图片。未知数量不再显示为默认 1，真实报工零值显示 0。
- SampleFormView 已接入适配器，并按真实 change_samplerequest / complete_sample_requirements 权限与能力标志控制编辑。保存有处理中门禁和缺失 ETag 拒绝，复用 useSampleUnsavedChanges；失败保留输入，成功后返回真实详情。
- 没有改后端、数据模型、状态名称或共享布局，没有执行真实业务写入。
- 新增 12 项适配测试、4 项实际 Vue 表单组件测试、1 项 FormData/If-Match 契约测试；打样专项现为 10 文件 50 测试通过。type-check 通过（session 54733，exit 0）。
- 本轮生产构建通过（session 45865，exit 0，4765 modules，21.38s）。仍有 VueUse PURE 注释与大包警告，未为本次局部修复修改全局打包策略。
- qa/sample_v3_edit_readonly.cjs 已通过：真实列表入口取得申请 ID、读取真实编辑数据（READ_ONLY）、产品/明细数量一致、终态保存入口关闭、返回详情、1920/1440 无整页横向溢出，errors=[]、writes=[]。证据为 edit-live-evidence.json 和 edit-current-1920/1440.png。
- 测试中的报工数据仅用于独立组件/适配器，不替代真实 API，不代表生产数据库报工写入验收。完整编辑/完善需求的视觉和完整契约适配、详情及其余页面仍未完成，整个目标继续保持 active。

## 2026-09-10 11:30 列表快捷分类对齐

- 重读目标文件，并通过 get_design_context 与实际节点属性再次核对 1897:18624。发现旧实现七个流程快捷分类与当前 Figma 六项不同，已修正结构、13px 字号、46px 高度和 2px 激活底线；各项宽度为 164/186/186/186/186/186px。
- api/sampleApplication.ts 新增真实列表统计适配。全部与本人负责分别调用现有 summary；本人负责传当前登录员工 owner_employee_id。两个统计独立处理失败，未知不冒充 0，未关联员工不发送空 owner 查询。其余四项缺失能力由明确 TODO 描述，点击不会清空已有筛选或发送错误阶段参数。
- 原有全部状态仍可在“当前环节”下拉筛选，列表行状态保持原 API 标签；没有删除原业务筛选能力或替换状态语义。统计失败也保留快捷区高度，避免列表跳动。
- 浏览器脚本扩展后通过：本次真实全部 134、本人负责 1，owner 筛选及返回全部均响应 200；六项结构/尺寸、编号深色、24px 标签、搜索、排序、1920/1440 和无业务写请求均通过。证据已更新 list-live-evidence.json、list-1920.png、list-1440.png。
- 专项测试现为 11 文件 61 项通过；type-check 通过（session 30725，exit 0）。
- 本轮 build 通过（session 27785，exit 0，4765 modules，21.64s）；既有 PURE 注释和大包警告仍在。未将专项通过等同于完整目标验收。
- 已向用户发出一个待答设计基准问题：编辑/详情/完成等仍只有旧版画板，但目标明确禁止以旧打样页作为视觉标准；需选择复用 V3 分区并保留字段、补齐 V3 设计稿，或允许使用这些现存画板。该问题不影响已确认 V3 页面的继续修正，不应视为整个目标已完成或立即 blocked。

## 2026-09-10 11:36 全屏交互审查

- 继续前已重读完整目标附件。上一轮是实际进展（六项快捷分类、真实个人统计及验证），本轮未改变目标范围。
- 新增真实浏览器验收复现：材料全屏状态点击“删除”后按 Escape，确认框取消，但页面也意外退出全屏。原 useSampleFullscreen 只排除 el-dialog 和 Select，遗漏了 el-message-box。
- 共享全屏逻辑现检查按键的事件传播路径，尊重已处理事件，并排除确认框、对话框与下拉控件；取消局部操作不再连带退出全屏。普通字段 Escape 仍退出全屏并恢复进入按钮焦点。
- 新增 5 项组合函数测试全部通过；材料完整只读脚本（session 34502）与仓库完整只读脚本（session 88440）复验通过，覆盖上述真实问题、普通/全屏几何、1440 内部滚动和采购缺口透明背景。两份证据均 errors=[]、writes=[]。
- npm run build 通过（session 6342，exit 0，包含 vue-tsc 类型检查，4765 modules，21.64s），仍有既有 PURE/大包警告。未重复宣称已执行整个目标的最终全量测试。
- 编辑/详情等的设计基准问题尚未收到答复。当前完成的是已确认 V3 页面的交互修复，其他未完成页面仍按原映射保留，目标未完成，也未标记 blocked。

## 2026-09-10 全量测试与继续开发边界复核

- 已再次完整读取目标附件；本节不缩减页面范围，也不把现有七个 V3 画板等同于全部模块完成。
- 重新读取实际 Figma 业务页 0:1：V3 仍为七个画板。编辑/详情 245:5933、PMC 765:8900、完成 779:8870，以及费用、物流、样品库存及相关弹窗/单据详情仍只有原画板，没有发现对应的新 V3 画板。当前 SampleFormView 仍使用旧标题装饰和普通 scoped 样式，不能作为新视觉已完成的证据。
- 用户最新标注的采购缺口底色已实时核实：1887:18596 与 1891:18615 内的缺口单元格 fills 均为空；两个 1920×1080 导出截图也显示无底色。本次没有重复写入 Figma。
- 已执行全量前端测试，结果记录于 outputs/sample_v3_frontend_20260910/frontend-full-test.json：54 个测试文件，53 个通过、1 个失败；220 项测试，218 项通过、2 项失败。JSON 的 numTotalTestSuites 包含 describe 层级，不能用它代替测试文件数。打样相关测试均通过。
- 两项失败均在 MasterDataCenterView.spec.ts：国家标准字段展示、空汇率提示。当前页面 loadRecords 调用 fetchAllMasterDataRecords，测试对 @/api/referenceData 的替身没有提供该导出，导致落入读取失败状态。这是当前无关模块的测试契约不匹配；没有基线对照，不能称为“既有失败”，也没有删断言或改其生产代码来绕过测试。
- 当前 package.json 仍没有 lint 命令。此前最近 type-check/build 通过的证据保留在上节；本轮没有重跑，也不宣称它们是本轮全量验收。

### 目标完成性审查

| 要求 | 当前证据与判断 |
| --- | --- |
| 读取规则、设计系统、代码/API并建立映射 | 已有完整映射与差异清单；本轮重新核实目标、AGENTS、DESIGN、Figma、实际源码和测试结果 |
| 全部实际打样页面逐页实现 | 未完成：编辑、详情、打样信息、费用/物流/反馈、PMC/完成、库存及相关页面仍须继续，不能移出范围 |
| 最新 Figma 为唯一视觉标准且不使用旧稿、不自行设计 | 剩余页面缺少兼容这两条限制的明确视觉来源；此前设计基准问题仍待答 |
| 新开发 SCSS、组件/Token复用、避免全局影响 | 已实现 V3 页按上述结构执行；尚不能推及未实现页面，完整代码 Review 未完成 |
| 真实 API、状态/权限/数据保持 | 已接现有查询与可用业务动作；缺失新流程接口由 Service/TODO 明确隔离，按目标允许的方式记录，不伪造成功 |
| 编号、Tag、采购缺口特殊规范 | 列表浏览器证据及仓库普通/全屏证据已记录；采购缺口本轮重新核实 Figma |
| 1920与常见桌面尺寸、状态及交互验收 | 已实现页面有逐页证据；未完成页面仍未达到完整验收 |
| lint/typecheck/build/test与全量Review | lint 未配置；最近类型/构建通过；全量测试未全通过；整个模块完整 Review 仍待实现结束后执行 |
| 最终七栏交付报告且尚未完成为无 | 条件未满足，不能报告整个目标完成 |

### 当前真正阻塞项

设计基准问题已连续多轮存在且未收到答复。能独立推进的已确认页面修正、报工保存保护、全屏交互修复、真实只读验证与全量测试诊断已执行；继续其余页面的视觉实现会需要擅自选择旧稿或重新设计，与目标的明确限制冲突。

推荐由用户确认：尚无 V3 画板的页面，复用已确认 V3 的分区和控件样式，同时保留现有业务字段及真实状态。该推荐本身不是已获授权的新视觉基准；确认前保留全部现有实现和未完成范围。API 缺口不作为这一暂停的理由，因为目标已允许用 Service/TODO 隔离。

## 2026-09-10 13:44 同路由导航的未保存保护

- 重新读取完整目标文件，完整模块范围不变。上轮列表专项是实际进展，不能替代模块交付。本轮重读创建页 1851:18496 的设计上下文和当前创建代码、Router、共享保护及相关 API。
- 当前本机已安装 verification-before-completion、systematic-debugging、requesting-code-review，已读取并执行；此前“未找到”的记录仅代表当时环境。本轮没有安装依赖或技能。
- 复现根因：App.vue 以 fullPath 作为页面容器 key，同名路由的申请 ID 或查询参数变化会销毁表单，而 useSampleUnsavedChanges 原先只注册离开守卫。真实 Vue Router 测试修前 3 失败、2 通过，证明更新参数没有弹出确认。
- 共享保护增加 onBeforeRouteUpdate，与离开守卫使用同一确认函数。取消保留原地址和输入，确认才切换，未修改时直接导航。没有修改字段、视觉、后台接口或状态流程。
- 修改范围：useSampleUnsavedChanges.ts；新增 useSampleUnsavedChanges.spec.ts（5 项真实路由测试）；SampleFormView.spec.ts 仅补新路由守卫导出的模拟；qa/sample_v3_create_readonly.cjs 增加真实应用的查询参数切换取消验证。
- 专项测试 2 文件 10 项通过。独立只读审查已检查三份源码/测试文件、App.vue 和五个调用页面，未发现 Critical/Important/Minor 问题；此结论不代表整个模块 Review 完成。
- 创建页真实浏览器脚本通过，包含 1920/1440、真实 form-options、必填、普通离开保护和同路由参数变化保护，errors=[]、writes=[]。截图 create-1920.png 已目视检查，四个分区坐标保持原型；真实空产品图片及菜单差异仍存在。
- npm run build 通过（session 92919，exit 0），包含 vue-tsc 类型检查，4777 modules。仍有 VueUse PURE 注释和大包警告；本轮未另跑独立 type-check 命令。
- 最新全量 npm run test：57 文件，56 通过、1 失败；246 项，244 通过、2 失败。结果在 outputs/sample_v3_frontend_20260910/frontend-full-test-latest.json。两项仍位于 MasterDataCenterView.spec.ts，当前测试模拟缺少页面调用的 fetchAllMasterDataRecords 导出；本轮已重新核对双方源文件，未修改无关模块。打样相关测试通过。lint 仍未配置。
- 编辑/详情等尚未完成的页面与设计基准问题保留，整个目标继续 active，未报告全部完成。

## 2026-09-10 V3 表单审查、客户查询与局域网兼容

- 上一目标轮为实际进展（未保存保护及验证）。本轮重新读取完整目标、当前工作区与 Figma；业务页 0:1 仍有七个 V3 画板，没有发现编辑/详情/费用/物流/完成/样品库的新版替代节点。已向用户明确询问剩余页面采用哪一设计基准，未收到选择，未擅自改变范围或使用旧稿。
- 按 requesting-code-review 技能派出只读审查，覆盖四个 V3 表单及直接依赖。发现两个 Important：材料新增行直接依赖 randomUUID；创建页本地过滤的客户选项被 form-options 截为前 500 条。已分别以失败测试复现并修复，审查复查未发现新增实质问题。
- 新增 utils/clientUuid.ts：优先用原生 UUID，否则用 getRandomValues 生成 UUID v4。SampleMaterialEditor、SampleFormView、SampleRequestIntakeView 复用；旧表单只替换标识生成，未改字段/布局/状态/幂等契约。组件测试验证方法不可用时增删和独立编辑两行，工具测试验证原生分支及降级格式/唯一性。
- SampleApplicationCreateView 使用现有 fetchCustomers(q/page/page_size/archived=false) 做远程查询，保留初始选项与已选客户标签，忽略旧响应，查询失败保留选择并提示；切客户清空联系人。无后端修改。跨出初始选项的场景通过独立组件测试，真实浏览器验证实际客户搜索 GET 返回 200；不声称现库已超过 500 客户。
- 真实局域网 HTTP 地址检测结果：secureContext=false、randomUUID=undefined、getRandomValues=function。该地址停在登录页，本轮未操作账号登录或进行局域网真实录入。实际材料整页验证使用已登录 localhost 与禁用原生 UUID 的浏览器环境，调用真实 GET，材料新增、普通/全屏、1920/1440、离开保护均通过；materials-live-evidence.json 明确记录环境边界，errors=[]、writes=[]。
- Figma 只读核对五个普通 V3 页面的 Brand 属性完全一致。App.vue 仅扩展已有品牌 SVG 的五路由使用条件；新增 qa/sample_v3_shell_readonly.cjs 验证五页品牌区域 (24,16,190,52)、230 侧栏、64 顶栏和零整页溢出，既有详情页保持原分支。五页截图与 shell-live-evidence.json 已输出；create-shell-1920.png 已目视检查。
- 新增测试：SampleMaterialEditor.spec.ts、SampleApplicationCreateView.spec.ts、clientUuid.spec.ts；更新 qa/sample_v3_create_readonly.cjs 加入真实客户搜索，qa/sample_v3_materials_readonly.cjs 增加可选兼容环境及运行环境证据。未新增普通 CSS、依赖或数据写操作。
- 最终专项命令 `npm run test -- src/components/samples/SampleMaterialEditor.spec.ts src/views/samples/SampleApplicationCreateView.spec.ts src/utils/clientUuid.spec.ts src/views/samples/SampleFormView.spec.ts src/utils/sampleFormEditing.spec.ts src/api/samples.spec.ts src/composables/useSampleUnsavedChanges.spec.ts`：7 文件、30 项通过（session 44891，exit 0）。
- `npm run build` 通过（session 34732，exit 0，4781 modules），包含最终 vue-tsc 检查。第一次独立 type-check 发现本轮两处问题（archived 参数枚举、测试 input 类型），已按实际类型修复并通过上述完整构建；不将首次失败命令写成通过。
- 创建页、材料页、五页壳层浏览器脚本均通过。此次未重复全量测试；上一轮 244/246 及基础资料中心两项失败仍作为上一轮结果保留，不宣称全量通过。lint 未配置。全模块最终验收及剩余页面仍未完成。

## 2026-09-10 完整目标阻塞复核

- 上轮为实际进展：客户查询、UUID 兼容、五页品牌复用及测试/浏览器/独立审查。本轮没有将重复检查算作新增开发成果。
- 已重新读取目标附件，并再次实时检查 Figma：仍为七个 V3 画板；详情/编辑 245:5933、费用 258:5218、物流 258:5608、PMC/完成 765:8900/779:8870、样品库及单据详情没有新版替代节点。当前源码已有 sampleForm.scss/sampleDetail.scss，不因此推断获得了新视觉基准或完整页面验收。
- 同一设计来源冲突在恢复后的连续三轮均存在，期间没有收到用户的设计基准选择。前两轮独立推进的保护修复、V3 审查整改和真实浏览器验证已经完成；当前不能在“禁止旧稿、禁止重新设计”约束下继续剩余页面视觉实现。
- 目标保留完整范围，状态改为 blocked（等待用户明确设计来源），不是 complete。所需输入：允许复用已确认 V3 分区与控件并保留现有字段/状态，或提供剩余页面新版节点，或明确允许使用现存旧版画板。此前推荐不视为默认授权。
- 新流程 API 缺口仍按目标允许的 Service/TODO 方式隔离，不作为此次阻塞的理由。全量测试的基础资料中心失败、完整模块最终 Review 和剩余页面验收继续列为未完成；不重复执行未变化的检查来制造进展。

## 2026-09-10 14:17 下一流程：厂长确认页

- 用户要求从创建提示继续下一流程，若存在原型则开发。已实时读取 Figma 1812:18474，复用现有厂长确认页，保持基础信息、样品信息、参考图片、数量、处理意见分区；未重新设计或新增明细表。
- SampleDirectorReviewView.vue 增加请求序号与卸载隔离、加载失败清除旧申请、提交锁和意见保护；复用列表的五种终态限制，将已结束申请的意见和处理按钮设为只读。状态保留真实接口结果。
- 复用 SampleApplicationSummary、SampleSection、SampleStatusTag、useSampleUnsavedChanges、SCSS Token 与 sample-controls；未新增公共组件、依赖或后端逻辑。
- 新增 SampleDirectorReviewView.spec.ts，覆盖 403/404 重试、重复提交、失败意见保留、刷新失败清除旧数据、终态只读。终态测试修复前失败、修复后通过。最终与 sampleApplication.spec.ts 合计 2 文件 12 项通过。
- qa/sample_v3_director_readonly.cjs 真实 GET 验证通过，覆盖 1920 分区几何、网络错误、加载及重试、终态只读、返回列表、1440 内部滚动。director-live-evidence.json 的 errors=[]、writes=[]；截图 director-1920.png 已目视复核。独立只读审查未发现新增实质问题。
- 1920 实测：基础区 (258,176,1634,230)、样品区 (258,424,1042,382)、处理区 (258,824,1634,168)，与当前 Figma 相符；共享侧栏 230、顶栏 64。真实记录的状态、内容、空图片与 Figma 示例存在数据差异，菜单继续遵循已有权限。
- 本轮 npm run build 和最终 npm run type-check 均被 CustomerRelatedRecordsV2.vue:211/214 两处 TS2352 阻挡（查询类型缺少 page/page_size），未修改无关客户代码；lint 脚本未配置，不能报告全量构建通过。
- 创建提交、厂长确认/退回接口仍缺失，由 sampleApplication Service 明确提示并保留输入；本轮未发起业务写入，不能报告从创建到厂长确认已打通。完整模块尚未完成的范围与此前设计来源限制不变。

## 2026-09-10 14:56 创建至厂长审核已接通

- 用户进一步授权“打通”后，完成真实创建提交、厂长确认/退回、原单补充重提、参考图片及列表统计/入口；此前本节以上的“厂长接口缺失”仅为当时状态，现已解决。
- 新版状态独立于旧单流程；备份后已应用 samples.0021。后端 45 项、前端 42 项专项测试通过，类型/构建、OpenAPI、迁移检查通过。
- 独立测试库的 1920 浏览器链路完成创建→退回→补充重提→确认→材料页交接；实际业务库只做只读页面验收，没有添加测试业务单。
- 详细契约、权限、迁移和证据见 [sample-application-flow-20260910.md](sample-application-flow-20260910.md)。材料保存/提交仓库及之后采购接口仍未实现，整个模块目标仍不能报告全部完成。

## 2026-09-10 材料填写与仓库核对 API 接通

材料草稿保存、提交冻结、仓库可供数量保存、缺口需求交接与列表仓库/采购状态已接真实接口。0022/0023 已在备份后应用。后端 57 项、前端 51 项测试通过，1920×1080 隔离库完整流程及日常环境只读验收通过。采购交接使用独立打样缺料快照；供应商分配/采购下单/到货/实际扣库尚未实现。详见 `docs/sample-material-warehouse-flow-20260910.md`。前文材料接口未开放的描述为此前阶段记录。
