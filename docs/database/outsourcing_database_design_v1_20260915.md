# 委外加工数据库设计 V1

> **2026-09-17 前向修订**：加工明细、加工厂分配和回货数量由整数“套”改为 `numeric(18,4)`，并在加工明细固化 BOM 生产单位与单位快照；单价含义改为“元/BOM 单位”。回货半成品库存使用该 BOM 单位。迁移前的历史数据继续按原产品单位解释，迁移只固化其旧单位，不换算历史数量。

日期：2026-09-15，2026-09-17 更新数量口径。状态：已生成并执行 `outsourcing.0004_processing_quantity_uses_bom_unit`；本文保留后续模块的设计说明。

## 1. 设计依据与结论

本方案承接用户已确认的 `2026-09-15-r2` 原型及 2026-09-17 数量口径确认。外发来源为已生成的主排产计划，一张外发单对应一张计划、一道厂外工艺，可以包含多个产品、多个加工厂。仓库一次全部发料，加工厂按厂、按明细分批回货。加工数量和半成品数量使用 BOM 明细单位并保留 4 位小数，材料数量保留各自原单位。

建议采用 13 张委外业务表、2 张半成品库存表，以及 5 张来源依赖表，共 20 张新增表的设计。来源依赖包括 3 张主排产表及 2 张跨 BOM 版本的部件对应表；这些表不是 20 个用户页面。工艺、任务单、产品、BOM、材料入库批次、仓库、员工、文件和审计复用现有数据。

本轮交付是设计，不代表上述表已经建成。表名、精度、索引、事务方式属于技术建议；后文标记“待确认”的业务门槛尚未定案。

依据：

- [委外 PRD 修订 5](../production_outsourcing_prd_draft_20260914.md)：最新来源、数量、计价、多厂、分批回货及纠错原则。
- [排产 PRD](../production_scheduling_prd_v0_1_20260914.md)：主计划及产品级日期、工艺关系。
- [已确认原型基线](../../outputs/production_prototype_20260914_v1/revision_20260915_r2/confirmed_baseline.json)：2026-09-15 用户确认的原型。
- [历史待决清单](../../outputs/production_review_20260915/decision_checklist.md)：其中“原型未确认”已被最新确认替代；未回答的业务细则单独保留。

### 1.1 已确认规则

| 事项 | 数据库设计采用的口径 |
| --- | --- |
| 选择来源 | 先选厂外工艺，再选已生成计划中勾选该工艺的产品行；不能直接从生产任务单新建外发 |
| 单据粒度 | 一张外发单＝一张主计划＋一道厂外工艺；可含多产品、多厂 |
| 额度 | 生产任务单产品行＋稳定 BOM 部件＋工艺，跨计划、版本、加工厂、外发单累计 |
| 数量上限 | BOM 单个用量（裁剪明细优先裁片量，其他明细取单件用量）×任务单产品行订单数量；主排产数量仅参考 |
| 占用时点 | 保存有效外发单即占用加工额度；未发料取消释放；回货、完成不释放 |
| 分配 | 同一加工明细分给多厂，各厂 BOM 单位数量合计等于本明细外发数量 |
| 发料 | 整单一次发出；按实际材料和实际来源扣库存，创建外发单不扣库、不预占材料库存 |
| 回货 | 一张回货单选择一个加工厂，可含该厂多个加工明细；允许多批回货 |
| 入库 | 实收＝合格＋不良；合格入半成品可用库存，不良分开存放 |
| 库存身份 | 任务单产品行＋稳定 BOM 部件＋已完成工艺；加工厂和回货批次继续可追溯 |
| 计价 | 全部工艺按元/BOM 单位，包括喷塑；不增加元/平方米费用，不自动生成应付款 |
| 图片 | 加工明细、加工厂分配、材料明细、回货异常明细均可关联图片 |
| 后续边界 | 本期不做刺绣，不建设外发裁剪回来再外发车缝的连续加工链 |
| 改单 | 发料前可修改取消并留痕；执行后不能删除或改写实际出入库数量 |

### 1.2 当前源码核对结果

以下为模型及服务代码事实，没有连接真实数据库验证迁移状态或核实业务数据。

| 现有对象 | 核对结果 | 本方案处理 |
| --- | --- | --- |
| `production_task` / `production_task_product` | 产品行有产品、颜色、图片、单位及整数 `quantity`；任务已确认状态为 `READY` | 复用真实外键，额度锁定产品行 |
| `production_run_batch` | 已有执行批次，只含任务、计划量、实际量及状态等；没有产品级工艺、四日期结构 | 不当作主排产表，不改造成委外单 |
| 主排产、委外应用 | 在当前 `apps` 目录及相关模型中未发现对应实现 | 设计来源依赖和新委外应用 |
| `workshop_config_craft` | 有厂内/厂外类型、名称、状态；没有稳定业务分类编码 | 复用工艺 ID，建议补可选业务编码，禁止按模糊名称分流 |
| `bom` / `bom_line` | BOM 有版本；数量类字段多为文本；特殊来源 ID 在 `raw_values`；BOM 允许编辑和删除旧明细 | 保留版本、引用和快照；跨版本部件不能用行号或名称猜测 |
| BOM 分区 | 后端类型仅 PROFILE / ACCESSORY / FABRIC；细分七区依标题判断 | 统一适配七区，不能把 FABRIC 全部当裁剪明细 |
| `inventory_material_inbound_line` | 保存采购或额外入库来源、库区、入库/退货/验收数量，没有剩余量字段 | 原记录不覆盖；另记实际委外出库流水 |
| 材料库存查询 | `material_inventory_rows` 当前汇总 `accepted_quantity` | 必须改成验收量减已记账委外出库，再汇总展示 |
| `material_received_totals` | 统计采购到货事实 | 保持到货口径，不能因为材料被领用就减少采购已到货量 |
| 仓库 | 已有 MATERIAL / SEMI_FINISHED / FINISHED / DEFECTIVE；支持库区及可选库位 | 材料沿用库区口径；合格、不良校验对应仓库类型 |
| 半成品库存 | 已有半成品仓类型，未发现本次按部件/工艺记账的库存模型 | 新建半成品批次及流水，不混入成品库存 |
| 加工厂 | 已有采购供应商模型，但当前未发现独立加工厂模型 | 独立加工厂档案，不强行塞入材料/成品供应商分类 |
| 图片、审计 | 已有 `business_file`、`audit_log` | 复用，不另建文件存储或通用审计系统 |

## 2. 总体关系与表清单

关系路径：生产任务单 → 主排产计划 → 计划产品行 → 外发单产品 → 加工明细 → 加工厂分配 → 分批回货明细 → 半成品批次。

材料路径：外发单产品的 BOM 材料 → 接收加工厂分配行 → 本单材料明细 → 仓库一次发料 → 实际材料入库批次。

| 编号 | 建议表名 | 所属应用 | 一条记录表示什么 |
| --- | --- | --- | --- |
| S01 | `production_schedule` | 建议 `production_scheduling` | 一张主排产计划，委外前置依赖 |
| S02 | `production_schedule_product` | 同上 | 计划中的一个任务单产品 |
| S03 | `production_schedule_product_craft` | 同上 | 一个计划产品选中的一道工艺 |
| B01 | `bom_product_component` | `boms` | 某任务单产品内跨版本不变的部件身份 |
| B02 | `bom_component_line_binding` | `boms` | 某版本 BOM 行与稳定部件的明确对应 |
| F01 | `outsourcing_factory` | 建议 `outsourcing` | 一个加工厂档案 |
| F02 | `outsourcing_factory_craft` | 同上 | 加工厂能承接的一道厂外工艺 |
| O01 | `outsourcing_order` | 同上 | 一张外发单 |
| O02 | `outsourcing_order_product` | 同上 | 本单选中的一个计划产品及使用的 BOM |
| O03 | `outsourcing_processing_item` | 同上 | 本单某产品的一个待加工部件 |
| O04 | `outsourcing_factory_allocation` | 同上 | 加工明细分给某厂的套数与单价 |
| O05 | `outsourcing_material_item` | 同上 | 某加工分配行需要发给该厂的一种 BOM 材料 |
| W01 | `outsourcing_dispatch` | 同上 | 整张外发单唯一一次确认发料 |
| W02 | `outsourcing_dispatch_line` | 同上 | 某材料明细实际从一个入库批次发出的数量 |
| R01 | `outsourcing_return` | 同上 | 某加工厂的一次回货登记及确认 |
| R02 | `outsourcing_return_line` | 同上 | 本批某加工分配行的合格、不良套数 |
| I01 | `inventory_semi_finished_lot` | `inventory` | 某回货明细的一种品质、一个库区的库存批次 |
| I02 | `inventory_semi_finished_movement` | `inventory` | 对半成品批次实际记账的一笔库存变化 |
| E01 | `outsourcing_exception` | `outsourcing` | 不良、短少或损耗问题的登记与待处理证据 |
| A01 | `outsourcing_line_image` | 同上 | 某项明细所关联的一张图片 |

不新增“金工/裁剪/车缝/装配”四套可独立修改的计划表，不另建加工厂进度表，不增加应付账款、自动排程、内部报工或连续半成品外发表。

## 3. 通用字段及约束规则

- 所有新表使用 UUID 主键 `id`；正常业务表沿用 `TimeStampedModel` 的 `created_at`、`updated_at`。流水只追加，不修改历史数量。
- 除表中明确“可空”的字段，业务必填字段为非空。选填文字默认空字符串，选填 JSON 默认空对象；不要用 0 冒充缺失数量。
- 可编辑单头增加 `version integer > 0`、创建/更新员工外键。沿用项目 ETag / `If-Match` 校验版本，拒绝覆盖别人的修改。
- 创建人、发料人、回货确认人、异常登记人等实际业务操作人必须记录；对应 `organizations.Employee`，删除策略 PROTECT。历史导入如缺少身份，单独设计受控导入方式，不伪造员工。
- 金额、材料数量均采用 Decimal，对应 PostgreSQL numeric，禁止浮点数。加工套数为 bigint 正整数。
- 加工单价建议 `numeric(18,4)`；计划金额建议 `numeric(22,4)`，与现有采购精度保持一致。页面按最终显示规范格式化；存储不因每次展示或分批回货重新舍入。精度上限溢出必须拒绝。
- 材料数量建议 `numeric(18,4)`；转换系数和单套用量 `numeric(22,8)`。超精度输入明确报错或按已声明规则处理，不悄悄截断。
- 单据编号 `varchar(50) UNIQUE`，由服务端生成，不使用 `MAX+1`。具体编号前缀沿用项目编号规则，本文不把示例编号视为已确认规则。
- 业务外键默认 PROTECT。外发取消保留原单及行，不物理删除；加工厂停用不删除历史。对子行的发料前编辑采用差异更新和审计，已有图片及历史引用不得级联丢失。
- O02/O03/O04/O05 统一增加 `removed_at timestamptz 可空`、`removed_by_employee_id FK Employee 可空`，成对保存。发料前移除行时标记停用并保留历史，移除父行时同事务标记其活动子行；发料后禁止移除。有效明细指本行及所有父明细均未移除。四表的业务唯一约束只对 `removed_at IS NULL` 生效，允许先前移除后重新选择。未移除子行不得指向已移除父行。
- JSON 仅存来源展示、扩展加工参数和请求摘要；额度、工艺、产品、加工厂、材料来源、数量、库存都必须有独立字段/外键。
- 跨表归属与汇总规则不能只写在前端，也不能谎称普通 CHECK 可检查其他行：服务事务负责锁和校验，数据库使用唯一约束、行内 CHECK，以及必要的延迟约束触发器兜底。

## 4. 来源依赖

S01–S03 的完整字段、工艺映射、版本、维护保护与查询定义见[主订单排产数据库设计 V1](production_scheduling_database_design_v1_20260915.md)。两模块共用这三张表，不重复建表。以下为关联摘要；新增请求幂等、单位及主图引用、来源数量快照、产品/工艺移除历史等详细字段以主排产设计为准。

### S01 `production_schedule`：主排产计划

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| schedule_number | varchar(50), UNIQUE | 排产单号 |
| production_task_id | FK → ProductionTask | 来源任务单 |
| record_status | varchar(20) | ACTIVE / VOID；作废动作门槛仍待排产 Q5 确认 |
| source_snapshot | jsonb | 任务单号、销售订单号、客户等展示快照 |
| source_revision_hash | varchar(64) | 服务端生成的关键来源摘要，不能假设旧模型已有版本字段 |
| version、创建/更新人 | 通用字段 | 来源变更检测及审计 |
| void_reason、voided_at、voided_by_employee_id | text / 时间 / FK，可空 | 仅为将来作废留数据位置，不据此开放作废功能 |

数据库部分唯一约束：同一 `production_task_id` 最多一张 `record_status=ACTIVE` 的计划。任务确认状态在建计划时校验 `READY`；不将它误用于禁止所有生产中的历史计划办理合法回货。

### S02 `production_schedule_product`：计划产品

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| schedule_id | FK → S01 | 所属计划 |
| product_line_id | FK → ProductionTaskProduct | 来源任务单产品行；必须属于计划任务单 |
| line_number | integer > 0 | 展示顺序 |
| planned_quantity | bigint > 0 | 排产数量，沿用任务单产品单位，不超过对应产品数量；委外加工数量另按 BOM 用量计算 |
| material_inbound_date | date，可空 | 材料入库时间 |
| metal_return_date | date，可空 | 金工回货时间 |
| sewing_return_date | date，可空 | 车缝回货时间，裁剪/车缝计划共用 |
| finished_inbound_date | date，可空 | 成品入库时间 |
| product_snapshot | jsonb | 编号、货号、名称、规格、颜色、单位、图片来源及订单数量 |
| source_revision_hash | varchar(64) | 来源产品关键数据摘要 |

对未移除行条件 UNIQUE `(schedule_id, product_line_id)`、`(schedule_id, line_number)`；移除及引用保护见主排产设计。四日期存储允许空，以兼容尚未决定的必填规则；不能据此宣称业务允许缺日期。四个日期分别是计划日期，不作为实际出入库凭证。

### S03 `production_schedule_product_craft`：计划工艺

字段：`schedule_product_id FK S02`、`craft_id FK Craft`、`craft_type_snapshot varchar(20)`、`craft_name_snapshot varchar(100)`、`plan_category varchar(20) 可空`。

对未移除行条件 UNIQUE `(schedule_product_id, craft_id)`。厂内分类 METAL / CUTTING / SEWING / ASSEMBLY 来自明确工艺映射；厂外不填车间计划分类。厂外筛选通过本行及父产品均未移除的真实关联，不用逗号字符串、Tag 文案或备注检索。

**工艺业务编码建议：**为现有 Craft 增加 `outsourcing_code varchar(30) 可空`，仅四种值 POWDER_COATING / SCREEN_PRINTING / CUTTING / SEWING；非空唯一，必须为 EXTERNAL。通过现有真实工艺 ID 一次性核对绑定，不从名字模糊推导；已被订单引用后禁止随意改类型、改业务编码。工艺名称允许维护，但旧单保留名称快照。该字段只管理本期四种外发分类，不要求其他工艺补值。

### B01 `bom_product_component`：稳定部件身份

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| product_line_id | FK → ProductionTaskProduct | 稳定身份限定在该任务单产品内 |
| component_code | varchar(50) | 该产品内稳定编号，UNIQUE(product_line_id, component_code) |
| display_name | varchar(300) | 便于人工核对；名称不作为唯一身份 |
| created_by_employee_id | FK Employee | 建立或核对人 |

部件不是通用原料 SKU。同一个产品可能两处使用相同原料，不能直接把原料 ID 当部件 ID。部件身份本身不包含工艺，因此同一部件的不同工艺可分别统计额度、分别存半成品库存。

### B02 `bom_component_line_binding`：版本行与部件对应

字段：`bom_line_id FK BomLine UNIQUE`、`component_id FK B01`、`bom_id FK Bom`、`mapping_method varchar(20)`（INITIAL / COPIED / MANUAL）、`source_binding_id FK self 可空`、`confirmed_by_employee_id FK Employee`、`confirmed_at timestamptz`、`mapping_note text`。

UNIQUE `(bom_id, component_id)`，保证一个版本中同一稳定部件只有一个计量行。跨表校验 BOM 行归属、BOM 产品与部件产品一致。若业务存在同一部件在一个版本拆成多行，不能直接绕过唯一约束：需先定义合并后的计量单位和拆分关系，此规则未纳入本期。

建立对应时：首次使用可以建立稳定部件；复制且来源关系明确时继承部件；存在旧版本但无法明确对应时人工核对。禁止按名称、规格相似或新行号自动给满额度。已经用于外发或库存的对应不可重指向另一个部件。

现有 BOM 更新会删除未保留的旧行；接入后须捕获受保护引用并给出“该行已用于委外，请保留历史并创建新版本”等业务提示。只加外键、不处理旧编辑服务，会导致原 BOM 保存报错。存快照也不能代替这一兼容工作。

## 5. 加工厂及外发单

### F01 `outsourcing_factory`：加工厂

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| factory_number | varchar(50), UNIQUE | 系统编号 |
| name | varchar(255) | 名称；同名提示查重，不擅自按名称判定同一实体 |
| processing_type | varchar(200) | 加工类型原文，与外协工艺分开 |
| estimated_output | numeric(18,4)，可空，≥0 | 加工厂预产量，缺失不当 0 |
| estimated_output_unit、estimated_output_period | varchar(50)，选填 | 周期/单位未定，不默认“套/天” |
| contact_name | varchar(100) | 联系人 |
| contact_phone | varchar(100) | 电话按文本保存，可保留分机、前导零 |
| address | varchar(500) | 地址 |
| remark | text，选填 | 备注 |
| payment_cycle | varchar(20)，默认 MONTHLY | 本期只记录“月结”，不解释成月末后 30 天 |
| status | varchar(20)，默认 ACTIVE | ACTIVE / DISABLED |
| version、创建/更新人 | 通用字段 | 并发及审计 |

输入必填要求与已确认新增/编辑弹窗对齐；存储结构允许迁移资料先报告缺失，不能绕过表单校验静默填假值。附件加工厂 Excel 不是自动导入指令。

### F02 `outsourcing_factory_craft`：工厂工艺能力

字段：`factory_id FK F01`、`craft_id FK Craft`；UNIQUE `(factory_id, craft_id)`；必须为本期启用的厂外工艺。

这张表可兼容单工艺或多工艺资料。当前已向用户询问是否允许一家工厂多选；答复前不把多选标为业务已确认。若只能单选，加 `UNIQUE(factory_id)`；若允许多选，保留联合唯一。停用工厂/工艺后不可新分配，但历史查询与已发订单回货不能因此丢失或被无条件阻断。

### O01 `outsourcing_order`：外发单头

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| order_number | varchar(50), UNIQUE | 外发单号 |
| schedule_id | FK S01 | 唯一来源主计划，不可跨计划混单 |
| craft_id | FK Craft | 整单一道厂外工艺 |
| craft_name_snapshot、craft_code_snapshot | varchar(100/30) | 历史工艺含义 |
| delivery_date | date | 交货日期；按已确认原型单头字段设计，不扩展分厂日期 |
| status | varchar(30) | PENDING_DISPATCH / PROCESSING / PARTIAL_RETURN / COMPLETED / CANCELLED |
| source_snapshot、source_revision_hash | jsonb / varchar(64) | 计划、任务单、销售单和客户信息及关键来源版本 |
| remark | text，选填 | 加工总说明 |
| client_request_id | uuid, UNIQUE | 本次创建请求的稳定标识 |
| request_payload_hash | varchar(64) | 防止同请求标识被换成另一份内容 |
| version、创建/更新人 | 通用字段 | 编辑并发控制 |
| cancelled_at、cancelled_by_employee_id、cancel_reason | 时间/FK/text，可空 | 未发料取消依据 |

任务单通过 `schedule.production_task` 追溯，不另存可独立修改的任务外键。取消字段成组完整；只有未发料单可取消。金额由加工分配行汇总，不在单头另建一个可手填的总额。

### O02 `outsourcing_order_product`：本单产品与 BOM

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| order_id | FK O01 | 外发单 |
| schedule_product_id | FK S02 | 来源计划产品行 |
| bom_id | FK Bom | 本次实际使用的 BOM |
| line_number | integer >0 | 产品展示顺序 |
| product_snapshot | jsonb | 产品编号、名称、货号、规格、颜色、单位和图片 |
| order_quantity_snapshot | bigint >0 | 建单时订单产品数量，供历史展示；额度仍实时核对来源 |
| planned_quantity_snapshot | bigint >0 | 建单时主计划数量，仅参考 |
| bom_number_snapshot、bom_version_snapshot | varchar(80) / integer >0 | BOM 版本展示 |
| source_revision_hash | varchar(64) | 服务端记录关键产品、工艺选择及 BOM 内容摘要 |

UNIQUE `(order_id, schedule_product_id)`、`(order_id, line_number)`。计划产品必须属于单头计划，且有该单工艺；BOM 必须属于该任务单产品。是否要求 VERIFIED 正在等待答复，不默认“最新版本”一定可用。

### O03 `outsourcing_processing_item`：加工明细

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| order_product_id | FK O02 | 本单产品 |
| component_binding_id | FK B02 | 对应所选 BOM 的部件行与稳定部件 |
| line_number | integer >0 | 行号 |
| quantity | numeric(18,4) >0 | 本部件外发总数量，按 BOM 单位计算 |
| unit_id | FK ProductionUnit | BOM 单位对应的生产单位 |
| unit_snapshot | varchar(50) | 建单时的 BOM 单位快照 |
| component_snapshot | jsonb | BOM 行 UUID、分区、名称、规格、颜色、加工参数和原始用量文本 |
| processing_requirement | text，选填 | 加工要求 |

UNIQUE `(order_product_id, component_binding_id)`、`(order_product_id, line_number)`。数量由 BOM 单个用量乘订单产品数量得到，单位随 BOM 明细固化且不允许用户另选。加工对象与材料扣库对象分开存。

### O04 `outsourcing_factory_allocation`：加工厂分配

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| processing_item_id | FK O03 | 加工部件 |
| factory_id | FK F01 | 承接加工厂 |
| allocated_quantity | numeric(18,4) >0 | 按加工明细 BOM 单位分配的数量 |
| unit_price | numeric(18,4)，≥0 | 元/BOM 单位，是否允许免费加工由表单最终规则决定 |
| factory_snapshot | jsonb | 名称、联系人、电话、地址、付款周期快照 |
| remark | text，选填 | 针对该厂的加工说明 |

UNIQUE `(processing_item_id, factory_id)`。金额以 `allocated_quantity × unit_price` 计算。各厂合计必须等于加工明细 `quantity`；一条加工明细至少一厂。

不单独存可手改的“本厂已回数量”或“本厂已完成状态”，从已确认回货明细聚合。同厂多明细的快照由服务一次生成，避免同单展示多个互相矛盾的联系方式。

### O05 `outsourcing_material_item`：计划发料明细

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| allocation_id | FK O04 | 对应加工分配；接收厂由此确定，避免另选到无关厂 |
| bom_material_line_id | FK BomLine | 对应本产品 BOM 的材料行 |
| line_number | integer >0 | 同分配内行号 |
| material_snapshot | jsonb | 材料编号、名称、规格、颜色、来源字典 ID、分区和原始用量文本 |
| unit_text | varchar(50) | 本次材料数量单位，不得空 |
| reference_order_quantity_sets | bigint >0 | 计算参考需求时使用的来源订单套数 |
| consumption_basis | varchar(20) | PER_SET / ORDER_TOTAL / UNPARSED |
| consumption_per_set | numeric(22,8)，可空，>0 | 确认为单套用量时保存 |
| reference_required_quantity | numeric(18,4)，可空，≥0 | 参考需求；不可解析时为空 |
| planned_issue_quantity | numeric(18,4)，>0 | 人工填写本次发给该厂的数量 |
| difference_reason | text，选填 | 数量差异说明；何时强制必填待答复 |
| remark | text，选填 | 发料要求 |

UNIQUE `(allocation_id, bom_material_line_id)`、`(allocation_id, line_number)`。同一材料可以服务多个部件，但须人工拆分各行数量；展示中可以合并，写库时不能复制整份需求。

参考需求：确认是单套用量时乘订单套数；若字段已经是整单用量则直接采用，不再次乘订单数量。参考需求属于该产品材料的整单口径，在同材料多厂/多部件行重复展示也只能计一次，不能把参考量相加为新增需求。实际发料为本单所有材料行数量之和，仍按人工分配，不能自动按工厂套数比例复制材料。

## 6. BOM 取数、来源变化与材料识别

| 厂外工艺编码 | 加工对象 | 可选发料来源 |
| --- | --- | --- |
| CUTTING / SEWING / SCREEN_PRINTING | FABRIC 且标题为“裁剪明细”的行 | FABRIC 且标题为“面料类”或“辅料类”的行 |
| POWDER_COATING | 暂按 PROFILE“管材类”部件设计，原始用词仍需核实 | PROFILE“管材类”及 ACCESSORY“五金件” |

用统一适配函数识别现有七个固定分区；新单快照保存稳定分区码 CUTTING_DETAIL / TUBE / HARDWARE / FABRIC / AUXILIARY。裁剪明细中关联的半成品资料是加工对象资料，不表示本期允许从半成品库存再次发料。

不能凭存在 `unit_consumption` 字段就声称它总能计算：现有字段是文本，部分有公式/单位混写；保存原始文本、解析结果及计算口径，解析失败显示“待核对”，不转成 0。

来源保存时快照化，发料时再次核对关键摘要。若计划作废、产品不再属于计划、工艺被移除或 BOM 关键内容改变，未发料单须先核对并按正式编辑重新保存；不静默换版本。已经发出后按交接快照回货，上游改名或新版本不能抹掉在途事实。

材料库存不能只通过名称/规格文本相同自动匹配。优先核实采购入库 → 采购行 → 来源 BOM 行；额外入库可利用其真实原料 FK，BOM 中可用的来源字典 ID 做明确匹配。没有统一原料 ID 时，由仓库明确选择实际批次，记录核对人、方式和原因；不能伪造 UUID、默认全库同名可领或宣称已有自动精确配料关系。

## 7. 一次仓库外发

### W01 `outsourcing_dispatch`：发料单

字段：`dispatch_number varchar(50) UNIQUE`、`order_id FK O01 UNIQUE`、`dispatch_date date`、`confirmed_at timestamptz`、`confirmed_by_employee_id FK Employee`、`client_request_id uuid UNIQUE`、`request_payload_hash varchar(64)`、`remark text`。

只保存确认成功的实际发料记录，没有独立可分批确认的发料子单。`UNIQUE(order_id)` 从数据库保证一次发料；多加工厂只形成同一次发料里的不同明细。确认过程失败整笔事务回滚。

### W02 `outsourcing_dispatch_line`：材料出库流水

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| dispatch_id | FK W01 | 本次发料 |
| material_item_id | FK O05 | 本单材料分配行 |
| inbound_line_id | FK MaterialInboundLine | 实际消耗的来源库存批次 |
| source_quantity | numeric(18,4)，>0 | 真正扣该批次库存的数量 |
| source_unit_snapshot | varchar(50) | 库存原单位 |
| material_quantity | numeric(18,4)，>0 | 换算为本单材料单位的数量 |
| conversion_factor | numeric(22,8)，>0 | 1 个库存单位＝多少个本单材料单位；同单位为 1 |
| conversion_evidence | text，选填 | 不是 1 时必须有明确有效的换算依据 |
| zone_id、location_id | FK WarehouseZone / WarehouseLocation | 库区必填，库位可空；保存实际发出位置 |
| source_snapshot | jsonb | 材料、批次、仓库/库区、来源采购单等历史信息 |
| match_method | varchar(30) | BOM_LINE / REFERENCE_ID / MANUAL_CONFIRMED |
| match_reason | text，选填 | 人工确认实际材料身份时必填；核对人采用发料确认人 |

UNIQUE `(dispatch_id, material_item_id, inbound_line_id)`。同一材料行可用多个库存批次凑齐，同一批次也可分发多厂。服务按入库批次汇总所有来源数量检查库存，不能逐行各自看见相同余额。

`material_quantity = source_quantity × conversion_factor`，结果按声明精度核对；无法准确换算时禁止记账，不静默把米当千克。本期优先同单位，不增加通用单位换算维护系统。

每个 O05 的 W02 `material_quantity` 合计须等于 `planned_issue_quantity`。缺料不能提交部分发出；确需改材料时先编辑未发料单再确认。每条 W02 必须属于 W01 的外发单，接收工厂从 O05 → O04 追溯。

### 材料库存余额与既有采购兼容

对一个已确认材料入库批次：

`可用量 = accepted_quantity - SUM(已记账 W02.source_quantity)`。

W01/W02 同事务提交即记账；不另用可能不同步的布尔标记决定是否扣库。当前范围没有撤销/退料按钮；后续若建设，新增对应的反向流水与原流水关联，再扩展余额公式，不能删除 W02 或改旧数量。

- 不修改 `received_quantity`、`return_quantity`、`accepted_quantity` 来冒充委外出库；采购验收与品质退货的原记录保持其原业务含义。
- 当前采购品质退货数量已经从 `accepted_quantity` 扣除，不能在本公式再次减一次品质退货。
- 当前材料库存查询、库存导出、可用批次选择等使用净余额；采购到货统计继续使用原验收量，领用不产生“重新待采购”。
- 不直接把入库表连接多条出库行后 SUM 入库量，会重复放大库存。先逐批次子查询聚合出库，再算余额，最后按材料和库区汇总。
- 本公式适用于本次新增委外出库；上线前须核对所有材料领用入口。若另有打样消耗等已实际占用同一批次，必须合并进同一可用量口径并共用锁，不能把“关联到打样”自动当成已消耗，也不能重复使用已消耗库存。
- 已消耗批次的库区/单位/来源及验收事实不能任意改写；今后退货或更正不得把有效余额减成负数。
- 现有仓库/库区停用检查主要针对成品结存。接入委外时须补查材料净余额、半成品/不良结存，并与发料/回货共享库区锁；仅增加两张半成品表不会自动获得这些保护。

## 8. 分批回货与半成品库存

### R01 `outsourcing_return`：回货单头

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| return_number | varchar(50), UNIQUE | 回货单号 |
| order_id | FK O01 | 已发料的外发单 |
| factory_id | FK F01 | 本批只属于一家加工厂 |
| return_date | date | 实际回货日期 |
| delivery_note_number | varchar(100)，选填 | 加工厂送货单号，仅查重提示，不假定跨厂唯一 |
| factory_snapshot | jsonb | 本次交接加工厂信息 |
| received_by_employee_id | FK Employee | 对应已确认 W04 的接收人；必填，与实际确认操作者分别记录 |
| status | varchar(20) | DRAFT / CONFIRMED；技术中间状态不增加原型外的菜单 |
| confirmed_at、confirmed_by_employee_id | 时间/FK，可空 | CONFIRMED 时同时必填 |
| client_request_id | uuid, UNIQUE | 同一登记请求重试复用 |
| request_payload_hash | varchar(64) | 同 ID 不同内容拒绝 |
| version、创建/更新人、remark | 通用字段 | 登记及确认依据 |

按原型若只有一次确认提交，可以在同一事务创建并确认，不强迫用户先保存草稿。草稿不计已回、不增加库存；已确认批次不可覆盖修改。回货不受新单选厂的“必须仍启用”限制，但仍须验证真实订单分配和操作权限。

接收人是本批实际业务接收员工，confirmed_by_employee_id 始终记录发起确认的实际操作者；下拉选择他人不能替换审计身份。W04 表头选择的合格/不良库区分别写入本批对应品质明细，保留逐行实际库区追溯。

### R02 `outsourcing_return_line`：回货明细

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| return_id | FK R01 | 本次回货 |
| allocation_id | FK O04 | 精确对应本厂、本产品、本部件分配 |
| line_number | integer >0 | 展示顺序 |
| returned_quantity | numeric(18,4) >0 | 本批实收数量，单位继承加工明细 BOM 单位 |
| good_quantity | numeric(18,4) ≥0 | 合格数量，单位同上 |
| defective_quantity | numeric(18,4) ≥0 | 不良数量，单位同上 |
| good_zone_id | FK WarehouseZone，可空 | 合格量大于 0 时必填，仓库类型 SEMI_FINISHED |
| defective_zone_id | FK WarehouseZone，可空 | 不良量大于 0 时必填，仓库类型 DEFECTIVE |
| defect_reason | text，选填 | 不良量大于 0 时必填 |
| component_snapshot | jsonb | 交接时产品、部件、工艺信息；来自外发依据 |
| remark | text，选填 | 本批说明 |

UNIQUE `(return_id, allocation_id)`、`(return_id, line_number)`；CHECK `returned_quantity = good_quantity + defective_quantity`。本批允许只填写回来的明细，未回行不存 0 占位；同一批次不能把一条分配重复拆行绕过校验。

工厂、订单跨表归属必须相同。对于每条分配：`本次实收 ≤ BOM 单位分配数量 - 历次已确认实收`；不良也占已实收数量，不能借不良再重复收一批超分配量。返工复收或退货重收需后续专门动作和反向记录，本期不能直接新增“正常回货”绕过上限。

### I01 `inventory_semi_finished_lot`：半成品库存批次

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| lot_number | varchar(50), UNIQUE | 批次编号 |
| return_line_id | FK R02 | 入库来源 |
| product_line_id | FK ProductionTaskProduct | 冗余查询键，与来源严格一致 |
| component_id | FK B01 | 稳定部件身份，与来源一致 |
| craft_id | FK Craft | 已完成工艺，与外发单一致 |
| quality | varchar(20) | GOOD / DEFECTIVE |
| zone_id | FK WarehouseZone | 实际库区，校验品质对应仓库类型 |
| received_quantity | numeric(18,4) >0 | 本批该品质入库数量，单位继承加工明细 BOM 单位 |
| remaining_quantity | numeric(18,4) ≥0 | 当前物理结存，不能超过本批入库数量 |
| unit_id | FK ProductionUnit | 半成品库存生产单位，与加工明细一致 |
| source_snapshot | jsonb | 产品/颜色/BOM 版本/工艺/加工厂/回货单等历史展示信息 |

UNIQUE `(return_line_id, quality)`。本期每回货行最多一个合格批次和一个不良批次；数量为 0 的品质不建库存。仓库类型限制用跨表校验，不能只靠 quality 标签。

业务库存按 `product_line_id + component_id + craft_id + quality + zone_id` 汇总，批次层继续保留加工厂和单据来源。产品颜色跟随任务单产品行，不能同名同规格就混为一个库存身份。

`GOOD` 才计入可用半成品，`DEFECTIVE` 即使有物理结存也不可用。实际后续领用不在本期，但不能设计成无法追溯的单一总余额。

### I02 `inventory_semi_finished_movement`：半成品流水

字段：`lot_id FK I01`、`movement_type varchar(30)`（本期仅 OUTSOURCING_RETURN_IN）、`quantity_delta numeric(18,4) >0`、`source_return_line_id FK R02`、`occurred_at timestamptz`、`actor_employee_id FK Employee`、`request_id uuid`。

UNIQUE `(lot_id, movement_type)`，同回货品质批次只入账一次；来源必须与 lot 相同。流水、批次和回货确认同事务写入，流水数量等于对应批次首次入库量。禁止更新/删除流水。

本期仅回货入库，因此有效批次结存等于累计流水量；后续有领用、退货、撤销时须新增动作和迁移扩展流水类型、正负数规则及唯一策略，重新定义余额约束。本文没有预先开放任意负数调账接口。

### E01 `outsourcing_exception`：异常登记

字段：`allocation_id FK O04`、`return_line_id FK R02 可空`、`exception_type varchar(20)`（DEFECT / SHORTAGE / LOSS）、`reported_quantity_sets bigint >0`、`reason text`、`reported_by_employee_id FK Employee`、`reported_at timestamptz`、`assigned_to_employee_id FK Employee 可空`、`status varchar(20)`（本期登记后 OPEN）。

不良回货确认时自动关联一条 DEFECT 记录，数量等于该行不良量；非空 `return_line_id` 与 DEFECT 组合唯一，防止重复登记。短少/损耗可登记观察事实，不自动确认损耗、减待回、结算或入库；尚未回货的余额本身不自动产生损耗事件。

关联回货行时必须属于同一 allocation。登记短少/损耗时记录当时待回数量到审计快照，问题量不能超过当时待回量；后续回货不直接覆盖当时的观察记录，也不把多次观察数量相加扣减待回。

**本期未决边界：**异常处置人、短少确认、报废/返工/退货及冲销动作尚未定，不能靠把 status 改 CLOSED 就让库存或订单完成。数据表先留原始问题和证据，具体处置结果、反向流水、关闭校验作为后续独立设计。正常全合格回齐可以自动结束，有未处理异常保持未完成并显示异常提示。

## 9. 图片与审计

### A01 `outsourcing_line_image`

字段：`processing_item_id FK O03 可空`、`allocation_id FK O04 可空`、`material_item_id FK O05 可空`、`return_line_id FK R02 可空`、`business_file_id FK BusinessFile`、`origin varchar(20)`（BOM / UPLOAD）、`position integer >0`、`caption text 选填`、`added_by_employee_id FK Employee`、`removed_at timestamptz 可空`、`removed_by_employee_id FK Employee 可空`。

四种目标外键必须且只能有一个非空，用数据库 CHECK 约束；不用“任意对象 ID”伪关联。对每种目标分别建立条件唯一 `(目标 ID, position)`、`(目标 ID, business_file_id)`，仅对未移除记录生效。移除人/时间成对保存，历史引用不删；更正图片新增关联并写审计。

从 BOM 带入的图片同样引用 BusinessFile，明确 origin=BOM；本单上传不修改 BomLineImage。工厂分配可继承加工项基础图片，分厂新增图仅挂该 allocation。确认发料/回货记录当时图片关联 ID 集合到审计快照，保证后补图片不会伪装为原交接证据。

上传格式、大小、数量、文件扫描状态和访问控制复用现有 files 规则；创建关联时必须验证文件归属与可用状态，不把一个文件 ID 当成访问授权。

操作审计复用 AuditLog，记录创建、修改前后、取消、发料、回货确认、图片更正和异常登记。审计表已有只追加规则；审计不能替代库存流水，库存流水也不能替代业务审计。

## 10. 额度、状态与金额的唯一计算口径

### 10.1 加工额度

对于一个任务产品、一个稳定部件、一种工艺：

`已占用额度 = SUM(所有非 CANCELLED 外发单对应加工项的 quantity)`，统计单位为同一稳定 BOM 部件的 BOM 单位。

各加工项的分厂数量必须与自身 BOM 单位数量相等，因此不能再把加工项合计和分配行合计相加。完成单仍在“非取消”集合内，不释放额度；更换计划 ID、BOM ID 或加工厂 ID 不改变统计键。

上述加工项只统计未移除的有效明细；发料前移除产品/部件或换厂时，父子行移除、当前分配和额度重算必须同事务完成。已移除行用于历史追溯，不参与列表默认明细、金额、发料和当前额度。已执行行不能采用这一机制退回额度。

编辑以新值替换本单旧值，不先释放再在事务外重新占用。来源订单数量下降时，必须检查所有部件/工艺已用额度；不能允许订单更新后已有有效外发超过新上限，更不能截断旧单。

### 10.2 状态派生

| 状态 | 判定依据 |
| --- | --- |
| PENDING_DISPATCH | 有效外发单已保存，尚无 W01 |
| PROCESSING | W01 已确认，尚无已确认实收 |
| PARTIAL_RETURN | 存在已确认实收，但未满足整单完成条件；收齐但仍有异常也保持未完成并提示异常 |
| COMPLETED | 所有加工分配行实收均达到分配量，且不存在待处理异常 |
| CANCELLED | 仅未发料时取消；不能通过取消已发单释放额度 |

以上代码是后台建议，页面中文、Tag 样式使用已确认原型。工厂进度按“order + factory”聚合该厂所有分配行；整单完成不能只看某厂已回齐。明细“回齐”与“异常已处理”分开：实收已够但有不良时，可以数量回齐，订单仍不能完成。

不同 BOM 单位之间不得直接求和计算进度。工厂进度按“加工厂＋BOM 单位”分别汇总，并展示逐明细已回、待回及回齐状态。

### 10.3 金额

`计划加工金额 = SUM(每条加工分配的 allocated_quantity × unit_price)`，其中单价为元/BOM 单位。

合计仅包含有效加工分配行；历史移除行不重复计费。

喷塑面积仅可作为加工参数快照，不增加面积计费列。分批回货不重复累加计划加工金额，不将合格/不良数量自动转换为应付账款或扣款。月结只是加工厂资料。

## 11. 并发、幂等与数据库兜底

### 11.1 新建/编辑外发单

在同一个 `transaction.atomic` 中：

1. 校验员工权限和来源数据范围；构造相关任务/产品 ID 集合，按稳定顺序锁定任务、任务产品、计划及相关来源。读取阶段不信任前端快照，获取锁后重新检查。
2. 新建检查 `client_request_id`；同标识同内容返回既有单据，同标识不同内容冲突。编辑再锁当前订单、检查 If-Match，锁部件对应及涉及工艺/工厂能力记录，避免来源校验后被并发改掉。
3. 验证所有来源链、BOM 取数、工厂能力、单位、正整数和分厂合计。以已锁任务产品为共同入口，汇总跨单累计额度；不能只锁本单或只对不存在的记录 `select_for_update`。
4. 整体保存单头、产品、加工项、分配、材料、图片及审计。任一行错误全部回滚，来源及引用版本不自动替换。

任务产品锁会将同一产品的委外分配串行化，锁范围略粗，但本期比维护另一套容易漂移的额度余额表更简单。不同产品仍可并行。

### 11.2 仓库确认发料

1. 锁单头并核对版本、未取消且尚未发出；重复请求返回已经确认的发料结果，不再扣库。
2. 按材料入库父单、入库行 ID 稳定顺序锁真实库存来源；按项目既有采购/打样/库区的锁顺序接入，不引入“先锁入库行再反锁采购单”的倒序。
3. 校验批次已品质确认、库区可用、单位可换算。将本次所有厂、所有行按同一入库批次聚合，基于锁后净余额校验充足性。
4. 检查所有材料行一次齐发；同事务写唯一 W01、全部 W02、订单状态与审计。只扣材料出库流水，O03 加工对象不再扣一次。

入库批次父单/行及涉及库区先解析 ID、按统一顺序锁，再重读校验，不能在 for 循环遇到哪个就临时锁哪个。未来其他材料出库动作必须共用相同库存批次锁，否则本模块独自加锁不能阻止跨模块超领。

### 11.3 回货确认

1. 检查 R01 幂等键并锁外发单头，锁本批涉及的 O04 分配行，按 ID 排序；同单并发回货在单头串行以保证最终状态聚合一致。
2. 汇总这些分配行已确认实收，校验本厂本明细剩余，不能挪用另一家工厂额度；检查本批实收＝合格＋不良及库区类型。
3. 先锁将用的库区并复查启用状态，同事务保存 R01/R02、按品质创建 I01/I02、不良 E01、审计，最后刷新订单状态。
4. 若重复请求、确认按钮连点、唯一冲突，回滚本次后查回已存在的结果；响应必须区分同请求重试与不同请求的超量。不同正常批次使用不同请求 UUID。

### 11.4 需要数据库直接保护的规则

| 保护方式 | 内容 |
| --- | --- |
| 主键/唯一约束 | 单号、请求键、单任务有效计划、计划产品不重复、稳定部件版本绑定、分配不重复、单单一次发料、回货明细不重复、库存批次不重复入账 |
| 行内 CHECK | 正整数套数、材料和价格精度/范围、实收＝合格＋不良、品质与状态枚举、取消/确认身份完整、图片目标恰好一个 |
| 归属约束触发器 | 计划→任务、产品→计划、BOM→产品、部件绑定→BOM、材料→同产品 BOM、分配→订单工艺、出库/回货→同订单同工厂、库存→正确回货明细和仓库类型 |
| 提交时延迟约束触发器 | 有效单至少一个产品/加工项/分配；加工分配合计＝加工量；外发材料全部齐发；已确认回货至少一条明细；每种正数品质恰有批次及流水且数量一致 |
| 并发额度/库存保护触发器 | 直接 INSERT/UPDATE/DELETE 子行同样取得对应产品、分配或库存来源锁后校验总量；来源减量也走同一规则。不能只建一个不加锁的 SUM 触发器 |
| 执行事实冻结 | 禁止已发料加工/材料数量及接收方被覆盖；禁止已确认回货数量、原库存流水删除/改写；禁止修改已引用部件对应；取消单也禁止物理删除 |

触发器只针对关键完整性，不接管整套流程编排。服务和触发器必须统一锁顺序并加入死锁/并发回归测试；冲突返回可读错误。未来若允许退料/撤销，须一并扩展冻结规则及反向凭证关联，不能使用一个管理员“跳过约束”开关。

## 12. 查询索引与原型页面对应

外键默认建立索引。除唯一约束产生的索引，建议增加：

| 表 | 索引字段 | 用途 |
| --- | --- | --- |
| S01 | `(production_task_id, record_status)` | 定位任务的有效计划 |
| S03 | `(craft_id, schedule_product_id)` | 先工艺再筛选计划产品 |
| B01 | `(product_line_id, id)` | 产品内稳定部件及额度汇总 |
| F01 | `(status, name, id)` | 工厂列表与下拉选择 |
| F02 | `(craft_id, factory_id)` | 对应工艺的加工厂 |
| O01 | `(status, delivery_date, id)`、`(craft_id, created_at DESC, id)` | 委外与仓库待发列表 |
| O02 | `(schedule_product_id, order_id)` | 来源反查 |
| O03 | `(component_binding_id, order_product_id)` | 跨版本部件额度关联 |
| O04 | `(factory_id, processing_item_id)` | 分厂进度、工厂详情 |
| W02 | `(inbound_line_id, dispatch_id)` | 按批次聚合实际出库 |
| R01 | `(order_id, factory_id, status, return_date, id)` | 分厂回单与批次记录 |
| R02 | `(allocation_id, return_id)` | 已回/待回及并发额度查询 |
| I01 | `(product_line_id, component_id, craft_id, quality, zone_id)` | 半成品库存身份汇总 |
| I01 | `(zone_id, quality, remaining_quantity_sets)` | 库区结存和停用门禁 |
| E01 | `(allocation_id, status)` | 未处理异常与完成门禁 |

单号精确/前缀查询优先；中文包含搜索是否需要 trigram 索引，待数据量和执行计划确认，不为每个文字字段建索引。

| 已确认页面 | 主要数据 |
| --- | --- |
| F01 工厂列表、F02 新增/编辑弹窗、F03 工厂详情 | F01/F02，详情关联 O04/R01/R02 聚合 |
| O01 外发列表、O02–O06 新建及选择弹窗 | O01–O05，S01–S03，BOM 适配及 B01/B02 |
| O07 外发详情/分厂进度 | 单头、产品、加工/材料明细、分厂回货与异常；进度从确认批次计算 |
| W01–W02 仓库查看与确认外发 | O01/O03/O05、真实材料库存、W01/W02 |
| W03–W05 回货列表/登记/详情 | R01/R02、O04 剩余量、图片及库区 |
| 半成品及异常相关页面 | I01/I02、E01；异常处置操作仍按未决范围控制 |
| P01–P08 主排产及四车间计划 | S01–S03；四计划共用产品行，无复制扣量 |

列表及汇总使用服务端完整结果分页，不在前端当前页计算工厂回齐、订单总量或可用库存。

## 13. 场景核对与后续开发验收

以下均为设计验收条件，示例是虚构数据，不代表已经执行过真实接口或数据库测试。

| 编号 | 场景 | 预期结果 |
| --- | --- | --- |
| T01 | 订单产品 1000 套、主排产 800 套，某部件外发 1000 套 | 按已确认订单上限可通过；计划 800 仅参考，仍必须来自含该工艺的计划产品 |
| T02 | 部件 1000 套，甲 600、乙 400 | 合计通过；甲 600、乙 401 拒绝 |
| T03 | 另一外发单再占同部件同工艺 1 个 BOM 单位 | 拒绝；原单回齐/完成也不释放已占用的 BOM 单位额度 |
| T04 | 换新计划或 BOM 版本后重复外发同部件 | 通过稳定部件跨版本累计；未知对应先核对，不能给新额度 |
| T05 | 椅面与扶手各 1000 套 | 两部件分别校验，不误认为 2000 套成品 |
| T06 | 未发料编辑 600→500，或取消 | 同事务替换旧占用，取消释放未执行额度，不产生退库 |
| T07 | 两人同时各占 600，来源仅 1000 | 仅一笔成功或另一笔因剩余不足失败，无超量 |
| T08 | 两厂从同批材料各领 70 米，可用仅 100 米 | 整次拒绝，不生成半张发料单 |
| T09 | 已确认入库 100 米，两厂各领 30 米 | 原验收量仍 100，库存显示 40，采购已到货仍 100 |
| T10 | 同一管件既为喷塑加工对象又出现在材料行 | 只按 W02 扣材料一次 |
| T11 | 待品质确认批次、失效库区或不能换算单位 | 拒绝发料，不先改变订单状态 |
| T12 | 甲分配 600，先回 300，再回 300；乙分配 400 后回 400 | 三批分别入库，甲回齐不使乙或整单提前完成 |
| T13 | 甲已回 300 后再回 301 | 拒绝；不能拿乙的待回量抵扣 |
| T14 | 乙本批实收 400，合格 390，不良 10 | 合格库存增 390，不良库存增 10，有待处理异常，不能自动完成 |
| T15 | 两个并发回货请求各填 400，分配剩余 600 | 只能一笔成功，另一笔重新校验后超收拒绝 |
| T16 | 同一发料或回货请求超时后重试 | 返回同一结果，库存只记一次；同 UUID 换内容拒绝 |
| T17 | 创建回货草稿或仅加工厂声称完工 | 不入账；仓库确认才增加库存 |
| T18 | 无待回且无异常，所有厂所有明细全合格回齐 | 自动 COMPLETED；不能仅据单厂进度或页面合计判定 |
| T19 | 工厂停用、BOM 后续改名/新建版本 | 禁止不合规新分配；保留历史交接和在途回货能力 |
| T20 | 合格＋不良不等于实收、来源跨厂/跨产品/跨工艺 | 数据库和服务双重拒绝，事务全部回滚 |
| T21 | 甲 600×2 元、乙 400×2.5 元 | 计划金额 2200 元；喷塑同样按 BOM 单位；回三次不变成 6600 元 |
| T22 | 单套用料 0.5 米，订单 1000 套；或已给整单用料 500 米 | 两种正确参考需求均为 500 米；不能把总量再乘 1000 |
| T23 | 已有委外后删除 BOM 行、减订单数量、更换部件绑定 | 明确冲突，不破坏历史或绕过额度；原有编辑流程有可读提示 |
| T24 | 归档被引用图片、跨行图片 ID、发料后更换图片 | 访问与归属校验；原交接依据可追溯，不静默覆盖 |
| T25 | 原验收数量已扣品质退货，查询时再扣退货单 | 应避免二次扣减；库存与原采购品质链逐批对账 |
| T26 | 尝试直接 SQL 插入跨订单回货或改历史出库 | 关键约束/触发器拒绝，不依赖前端按钮隐藏 |
| T27 | 库区停用与回货同时提交 | 同一库区锁下重检；不得向已经停用的区提交新库存 |
| T28 | 不良复收、返工、少货强制关闭 | 普通回货入口不能代办；待专门处置规则确定后建设 |

## 14. 待确认项与本次不预设的规则

本轮已发出三项问题，答复前如下保持待确认，不把推荐方案自动写成已确认规则：

| 编号 | 待确认事项 | 本稿兼容方式 |
| --- | --- | --- |
| D01 | 一家加工厂允许多个外协工艺吗 | F02 关联表兼容；单工艺则加 factory 唯一约束 |
| D02 | 外发是否必须使用已确认 BOM | O02 有真实 BOM 和版本快照；推荐 VERIFIED；门槛等待答复 |
| D03 | 材料超过 BOM 需求但库存足够时如何处理 | 保存参考需求、实际数量、差异原因；库存不可超发已确定，需求差异策略等待答复 |
| D04 | O05 的材料参考需求按订单产品总数还是本厂加工分配比例计算 | 材料发料仍按材料自身单位人工确认，不因加工数量切换为 BOM 单位而自动改变 |

委外实施顺序、原型对应、字段差异和逐页验收详见[委外开发与视觉验收方案](../outsourcing_development_plan_20260915.md)。

其他保留项：预产量周期/单位仍按原始参考资料；喷塑加工对象按上下文暂解为管材；交货日期先按确认原型保持整单日期；四日期必填及计划编辑/作废属于排产待决项；短少/不良处置、退料/退货/撤销、最终结算依据尚需专门定义。

这些待决项不影响本稿展示正常委外链的表和关系，但影响正式实现门槛或异常流程。材料无可解析需求时，不能以空值默认 0 或自动通过“禁止超需求”校验；D03 若采用需求上限，需同步确定人工核对入口及跨单累计需求口径。

## 15. 后续实施顺序与本轮交付边界

1. 先确认上述业务门槛，冻结本稿字段及关系；再按用户选择的开发推进方式生成 Django 模型和前向 Migration。
2. 来源依赖优先：S01–S03、工艺真实 ID 映射、B01/B02；BOM 历史对应先只读预检，未知对应不能自动批量配对。
3. 加工厂及外发结构：F01/F02、O01–O05、图片关联；示例工厂和示例订单不作为正式种子导入。
4. 仓库一次发料：W01/W02、净库存查询、现有材料来源与采购/打样兼容、相关冻结约束。
5. 分批回货：R01/R02、I01/I02、E01，补齐幂等、锁、权限与审计。
6. 在独立测试库执行前向迁移和本稿验收用例；检查真实来源链、并发、直接写库约束、库存对账，再连接原型对应页面。之后才更新 schema 只读快照。

本轮没有新增 Python 模型、没有运行迁移、没有导入加工厂或执行库存操作。当前 `docs/database/README.md` 的历史表数量不拿来当今天真实数据库的统计，也不手工改旧 schema 快照。设计文档检查不等于后端、库存或生产业务已经完成。

## 16. 源码定位

- [生产任务单模型](../../src/backend/apps/production_tasks/models.py)
- [工艺与车间模型](../../src/backend/apps/workshop_config/models.py)
- [BOM 模型](../../src/backend/apps/boms/models.py)、[BOM 分区及来源校验](../../src/backend/apps/boms/api/serializers.py)、[BOM 编辑服务](../../src/backend/apps/boms/services.py)
- [采购与品质退货模型](../../src/backend/apps/procurement/models.py)
- [库存模型](../../src/backend/apps/inventory/models.py)、[库存查询](../../src/backend/apps/inventory/selectors.py)、[库存服务](../../src/backend/apps/inventory/services.py)
- [文件模型](../../src/backend/apps/files/models.py)、[审计模型](../../src/backend/apps/audit/models.py)、[通用模型](../../src/backend/apps/core/models.py)
- [数据库维护说明](README.md)
