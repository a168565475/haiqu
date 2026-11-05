# 管材外发喷塑面积与双计价方式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管材委外明细逐部位支持默认按平方米、可切换按支计价，并用建单时冻结的 BOM 单支喷塑面积计算行面积、整单面积和计划金额。

**Architecture:** 服务端仍是金额和面积的权威计算方：从已锁定的已确认 BOM 读取单支喷塑面积，冻结到 `TubeOutsourcingLine`，再按计价单位计算金额。前端只提交计价方式、数量和单价，使用同一十进制字符串算法做即时预览；历史记录通过数据库默认值继续按支，绝不读取当前 BOM 回填面积。

**Tech Stack:** Python 3.13、Django 5.2、Django REST Framework、PostgreSQL 17、Vue 3、TypeScript、Element Plus、Vitest

**Spec:** `docs/superpowers/specs/2026-11-04-outsourcing-spray-area-pricing-design.md`

## Global Constraints

- 只修改管材委外；五金、裁片、车缝、刺绣、丝印和旧金工重加工不改变计价方式。
- 新建管材行默认按平方米；既有记录和缺少新字段的旧请求按支解释。
- 面积只取建单时锁定的已确认 BOM，服务端不接受客户端传入面积，也不反向回填历史单。
- 五金不参与面积或加工金额。
- 保持 Session、CSRF、事务、ETag/幂等和现有库存流转规则。
- 不新增依赖，不修改 `AGENTS.md`，不执行主库迁移、真实业务写入或部署。
- 工作区已有大量无关改动；只暂存或提交本计划列出的精确文件。若用户未要求 Git 提交，执行阶段记录提交点但不创建提交。

## Review Focus

- BOM 面积为空、非数字、零或负数：来源接口明确返回不可按面积计价，按平方米保存须被服务端拒绝；Task 1 API 测试固定此行为。
- 小数面积乘大数量产生半分金额：前后端都使用十进制定点和银行家舍入（ROUND_HALF_EVEN）到两位；Task 1、Task 2 使用同一组边界断言。
- 同一张单混用按㎡和按支：每行金额分别计算，整单金额与总面积分别汇总；Task 1、Task 3 覆盖。
- 旧待核对请求缺少 `price_unit`：必须按支原样重放，不能自动改成默认按㎡；Task 1、Task 3 覆盖。
- BOM 在建单前发生变化：来源版本或保存时锁定校验应阻止旧页面面积进入新单；Task 1 覆盖来源修订和服务端重读。

---

## File map

- `src/backend/apps/outsourcing/tube_models.py`：保存计价单位与单支面积快照，并声明数据库约束。
- `src/backend/apps/outsourcing/migrations/0019_tube_line_area_pricing.py`：给历史明细设置按支默认，面积保持空。
- `src/backend/apps/inventory/tube_outsourcing_limits.py`：把已确认 BOM 的单支喷塑面积加入管材来源上下文。
- `src/backend/apps/outsourcing/api/tube_serializers.py`：接收并验证计价单位，兼容旧请求。
- `src/backend/apps/outsourcing/tube_prices.py`：集中解析面积、计算行面积/行金额/整单面积/整单金额。
- `src/backend/apps/outsourcing/tube_services.py`：在锁定 BOM 后重读面积、冻结快照并写审计。
- `src/backend/apps/outsourcing/plan_services.py`：实际分批发出沿用总单冻结的计价方式、面积和单价。
- `src/backend/apps/outsourcing/tube_selectors.py`：输出冻结面积、计价单位及汇总结果。
- `src/backend/apps/outsourcing/tests/test_tube_prices_api.py`：后端金额、面积、历史兼容、幂等与边界测试。
- `src/frontend/src/types/tubeOutsourcing.ts`：扩展来源、请求和详情类型。
- `src/frontend/src/utils/outsourcingPrices.ts`：前端面积和双计价预览算法。
- `src/frontend/src/utils/outsourcingPrices.spec.ts`：十进制、舍入和混合计价单元测试。
- `src/frontend/src/views/outsourcing/TubeOutsourcingFormView.vue`：逐行计价下拉、面积展示、动态单价单位及总面积。
- `src/frontend/src/views/outsourcing/TubeOutsourcingFormView.spec.ts`：默认值、切换、缺面积、旧请求和提交契约测试。
- `src/frontend/src/views/outsourcing/TubeOutsourcingDetailView.vue`：车间详情展示冻结面积和计价方式，仓库继续隐藏价款。
- `src/frontend/src/views/outsourcing/TubeOutsourcingDetailView.spec.ts`：新旧详情与仓库隐藏回归测试。

### Task 1: 服务端面积快照、双计价和历史兼容

**Files:**
- Create: `src/backend/apps/outsourcing/migrations/0019_tube_line_area_pricing.py`
- Modify: `src/backend/apps/outsourcing/tube_models.py`
- Modify: `src/backend/apps/inventory/tube_outsourcing_limits.py`
- Modify: `src/backend/apps/outsourcing/api/tube_serializers.py`
- Modify: `src/backend/apps/outsourcing/tube_prices.py`
- Modify: `src/backend/apps/outsourcing/tube_services.py`
- Modify: `src/backend/apps/outsourcing/plan_services.py`
- Modify: `src/backend/apps/outsourcing/tube_selectors.py`
- Test: `src/backend/apps/outsourcing/tests/test_tube_prices_api.py`

**Interfaces:**
- Produces: `PriceUnit.PIECE = "PIECE"`、`PriceUnit.SQUARE_METER = "SQUARE_METER"`；`parse_unit_area(value) -> Decimal | None`；`line_area_data(line) -> dict`；`line_price_data(line) -> dict`；`total_area(lines) -> str | None`；`planned_amount(lines) -> str | None`。
- Produces API fields: source row `unit_area_sqm`; write line `price_unit`; detail line `price_unit`, `unit_area_sqm`, `line_area_sqm`; order `total_area_sqm`。

- [x] **Step 1: 写失败的后端测试**

在 `TubePricesApiTests` 增加以下用例并使用真实 BOM `raw_values["coating_unit_area_sqm"]`：

- `test_source_context_exposes_positive_bom_unit_area`
- `test_square_meter_price_freezes_area_and_calculates_amount`
- `test_mixed_piece_and_square_meter_lines_sum_amount_and_area`
- `test_missing_zero_or_invalid_area_rejects_square_meter_but_allows_piece`
- `test_legacy_missing_price_unit_remains_piece_and_area_unknown`
- `test_changed_area_or_price_unit_conflicts_for_same_client_request`
- `test_saved_area_does_not_change_after_bom_edit`
- `test_plan_dispatch_inherits_frozen_area_price_without_warehouse_override`
- `test_square_meter_rounding_matches_decimal_half_even`
- `test_cutting_source_rejects_square_meter_price_unit`

关键断言：单支面积 `0.1250`、20 支、`2.50 元/㎡` 得到行面积 `2.5000`、金额 `6.25`；旧请求缺字段保存为 `PIECE`；历史面积为 `null`；五金不进入汇总。

- [x] **Step 2: 运行测试确认失败**

先设置本任务独占的 `POSTGRES_TEST_DB`，并在 PostgreSQL 中核实该完整库名不存在且无连接，再运行：

`docker compose exec -T -e POSTGRES_TEST_DB=<本任务登记库名> backend python manage.py test apps.outsourcing.tests.test_tube_prices_api --noinput --verbosity 1`

Expected: FAIL，原因是字段、迁移或计算接口尚不存在；测试命令结束后确认 Django 已删除该测试库。

- [x] **Step 3: 增加模型字段和前向迁移**

在 `TubeOutsourcingLine` 增加：

- `price_unit`: `CharField(max_length=20, choices=PriceUnit.choices, default=PriceUnit.PIECE)`。
- `unit_area_sqm`: `DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)`。
- 约束：计价单位只允许两个枚举值，面积为空或非负；历史行由迁移写成 `PIECE`，不回填面积。

- [x] **Step 4: 实现权威面积与金额计算**

在 `tube_prices.py` 使用 `Decimal` 和 `ROUND_HALF_EVEN`：按支使用 `quantity × unit_price`；按平方米使用 `quantity × unit_area_sqm × unit_price`；面积统一输出四位、金额两位。任一参与行缺面积时 `total_area()` 返回 `None`，任一行缺价格时 `planned_amount()` 返回 `None`。

- [x] **Step 5: 把 BOM 面积加入来源并在保存时重新核验**

`tube_outsourcing_limits.py` 只把 `PROFILE` 行的 `raw_values["coating_unit_area_sqm"]` 解析结果作为 `unit_area_sqm` 输出。`tube_services.py` 在事务内锁定并取得 `BomLine` 后再次解析：`SQUARE_METER` 要求正面积，`PIECE` 允许面积为空；保存模型字段并把 `price_unit`、`unit_area_sqm` 写入审计快照。若 `plan` 不为空，则按 `component_identity` 从总单明细复制冻结的 `price_unit`、`unit_area_sqm` 和 `unit_price`，不能重新读取当前 BOM 或信任仓库请求覆盖；`plan_services.py` 负责建立该映射并在 ETag/事务保护内传给实际分批单。

- [x] **Step 6: 扩展序列化与读取契约**

`TubeLineWriteSerializer.price_unit` 可省略且默认 `PIECE`；管材允许两种，裁片来源只能 `PIECE`。`saved_order_data()` 使用冻结字段输出行面积、行金额、整单面积和整单金额，不访问当前 BOM。

- [x] **Step 7: 运行后端定向测试和迁移漂移检查**

Run:

- `docker compose exec -T -e POSTGRES_TEST_DB=<本任务登记库名> backend python manage.py test apps.outsourcing.tests.test_tube_prices_api --noinput --verbosity 1`
- `docker compose exec -T backend python manage.py makemigrations --check --dry-run`
- `docker compose exec -T backend python manage.py check`

Expected: 定向测试 PASS；`No changes detected`；系统检查无错误；临时测试库复查不存在。

- [x] **Step 8: 记录提交点**

仅记录建议提交信息 `feat: add tube outsourcing area pricing model`；除非用户明确要求，不执行 Git 提交。

### Task 2: 前端十进制面积与双计价工具

**Files:**
- Modify: `src/frontend/src/types/tubeOutsourcing.ts`
- Modify: `src/frontend/src/utils/outsourcingPrices.ts`
- Test: `src/frontend/src/utils/outsourcingPrices.spec.ts`

**Interfaces:**
- Consumes: Task 1 的 `PIECE | SQUARE_METER` 与 API 字段名。
- Produces: `type OutsourcingPriceUnit = 'PIECE' | 'SQUARE_METER'`；`outsourcingLineArea(quantity, unitArea) -> string | null`；`outsourcingLineAmount(quantity, unitPrice, priceUnit, unitArea?) -> string | null`；`sumOutsourcingAreas(values) -> string | null`。

- [x] **Step 1: 写失败的前端工具测试**

覆盖按支原行为、`0.1250 × 20 = 2.5000㎡`、面积计价 `2.5000 × 2.50 = 6.25`、多行汇总、缺面积返回 `null`、大整数不丢精度，以及与后端一致的恰好半分/非半分 `ROUND_HALF_EVEN` 边界。

- [x] **Step 2: 运行工具测试确认失败**

Run: `npm run test -- src/utils/outsourcingPrices.spec.ts`

Workdir: `src/frontend`

Expected: FAIL，缺少新类型或函数。

- [x] **Step 3: 实现无浮点误差的字符串算法并扩展类型**

使用 `BigInt` 表示面积万分位和价格分，禁止 `Number` 承担金额计算；面积保留四位，金额按银行家舍入到分。扩展 `TubeSourceRow`、`TubeOrderInput`、`TubePendingOrderInput`、`TubeDetailLine`、`TubeOrderResult`，旧待核对请求的 `price_unit` 继续可选。

- [x] **Step 4: 运行工具测试**

Run: `npm run test -- src/utils/outsourcingPrices.spec.ts`

Expected: PASS。

- [x] **Step 5: 记录提交点**

建议提交信息 `feat: add outsourcing area price utilities`；默认不创建提交。

### Task 3: 车间新建页逐部位计价交互

**Files:**
- Modify: `src/frontend/src/views/outsourcing/TubeOutsourcingFormView.vue`
- Test: `src/frontend/src/views/outsourcing/TubeOutsourcingFormView.spec.ts`

**Interfaces:**
- Consumes: Task 2 的类型和计算函数。
- Produces: 管材 `Entry.priceUnit`；提交行 `{ component_identity, quantity, factory_id, price_unit, unit_price }`；页面 `totalArea` 预览。

- [x] **Step 1: 写失败的表单测试**

增加并调整用例：

- 管材行初始 `priceUnit === 'SQUARE_METER'`，页面显示单支/本行/整单面积。
- 切到 `PIECE` 后金额改按支，另一行仍可按平方米。
- 面积缺失、零或无效时默认按平方米但禁止保存，并提示改按支；切到按支后可保存。
- 新请求提交 `price_unit`，旧 localStorage 请求缺字段时原样回查/重放且按支解释。
- 裁片模式不出现计价下拉，继续按套提交且不带面积计价。
- 更换来源和重填会清理本次新增的计价状态，刷新来源保留用户已选方式。

- [x] **Step 2: 运行表单测试确认失败**

Run: `npm run test -- src/views/outsourcing/TubeOutsourcingFormView.spec.ts`

Workdir: `src/frontend`

Expected: FAIL，新控件、状态和请求字段尚不存在。

- [x] **Step 3: 实现管材专用列和校验**

只在非裁片模式增加“喷塑面积”“计价方式”列；面积单元格显示 `单支 X㎡ / 合计 Y㎡`；下拉为“按㎡”“按支”；单价输入后缀随行变化；计划金额、确认弹窗和页脚使用 Task 2 工具。来源新加载默认 `SQUARE_METER`，旧 pending 缺字段不改写。

- [x] **Step 4: 运行表单和工具测试**

Run: `npm run test -- src/utils/outsourcingPrices.spec.ts src/views/outsourcing/TubeOutsourcingFormView.spec.ts`

Expected: PASS。

- [x] **Step 5: 记录提交点**

建议提交信息 `feat: add per-line tube pricing selector`；默认不创建提交。

### Task 4: 车间详情与仓库隐藏回归

**Files:**
- Modify: `src/frontend/src/views/outsourcing/TubeOutsourcingDetailView.vue`
- Test: `src/frontend/src/views/outsourcing/TubeOutsourcingDetailView.spec.ts`

**Interfaces:**
- Consumes: Task 1 的详情字段与 Task 2 的展示类型。
- Produces: 车间详情面积/计价显示；仓库详情继续不显示计价和金额。

- [x] **Step 1: 写失败的详情测试**

覆盖：新按㎡单显示单支面积、本行面积、`元/㎡` 和整单总面积；混合单逐行显示正确单位；历史按支且面积为空显示“—”；仓库 `warehouseWorkspace` 和 action-only 弹窗不出现单价、计价方式或计划金额。

- [x] **Step 2: 运行详情测试确认失败**

Run: `npm run test -- src/views/outsourcing/TubeOutsourcingDetailView.spec.ts`

Workdir: `src/frontend`

Expected: FAIL，新字段尚未渲染。

- [x] **Step 3: 实现详情展示**

车间管材表增加冻结单支面积、本行面积和计价方式；单价表头/单元格展示行单位；页脚增加总喷塑面积。裁片和仓库列保持原样，不把价格隐藏误报为后端权限隔离。

- [x] **Step 4: 运行前端定向检查**

Run:

- `npm run test -- src/utils/outsourcingPrices.spec.ts src/views/outsourcing/TubeOutsourcingFormView.spec.ts src/views/outsourcing/TubeOutsourcingDetailView.spec.ts`
- `npm run type-check`
- `npm run build`

Expected: 定向 Vitest、类型检查和生产构建全部通过。

- [x] **Step 5: 记录提交点**

建议提交信息 `feat: show frozen spray area in workshop outsourcing`；默认不创建提交。

### Task 5: 集成核对与临时资源清理

**Files:**
- Modify only if contract changed: `docs/superpowers/specs/2026-11-04-outsourcing-spray-area-pricing-design.md`
- Modify: `docs/superpowers/plans/2026-11-04-outsourcing-spray-area-pricing.md`（勾选实际完成项和记录偏差）

**Interfaces:**
- Consumes: Tasks 1–4 的最终契约。
- Produces: 可复核的定向验收和清理记录。

- [x] **Step 1: 核对精确差异**

运行 `git diff -- <本计划列出的文件>`，确认每一行修改都能追溯到需求，无五金/裁片/库存/权限范围外改动；另用 `git status --short` 区分任务前已有改动。

- [x] **Step 2: 运行最终相关检查**

后端使用新的本任务独占测试库名，先核不存在再运行 Task 1 定向测试；前端运行 Tasks 2–4 定向测试、类型检查和构建。不得把未运行的 OpenAPI、全量后端、全量前端或真实页面写成通过。

- [x] **Step 3: 清理并复查**

复查本任务测试数据库、临时输出和浏览器目录；删除本任务确切创建的资源，保留源码、迁移、测试及报告。归属不明或既有资源不处理并标记 UNKNOWN。

- [x] **Step 4: 交付报告**

列出实际修改文件、命令及结果、迁移未应用状态、未进行的真实业务写入/浏览器验收及原因、临时资源清理复查结果；明确仓库价格仍是页面隐藏而非接口脱敏。

## 实际实施偏差

- 新建管材单实际走“委外总单”详情，因此除原计划的普通详情页外，同步修改了 `TubeOutsourcingPlanDetail`、`TubeOutsourcingPlanRecords` 和 `plan_selectors.py`，确保总单、实际外发批次及历史批次明细使用同一冻结计价口径。
- 为保持现有 TypeScript 契约严格，补齐了喷塑入库和结束单据测试夹具中的新只读字段；未改变对应业务页面逻辑。
- 额外运行了前端全量测试：342 个测试文件通过、16 个失败；失败均位于本任务未修改区域，未在本任务中扩展修复。

