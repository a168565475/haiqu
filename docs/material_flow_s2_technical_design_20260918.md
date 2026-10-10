# 材料流程 S2 技术定稿清单 V1.0（已确认）

日期：2026-09-18。状态：用户已整体确认本 V1.0 技术清单并授权 S3；Q-S2-01=B、Q-S2-02=A 不变。S3 已在隔离副本完成，实际改动、验证及限制见 [S3 实施结果](material_flow_s3_result_20260918.md)。S4 已获用户确认并在隔离副本完成，见 [S4 实施结果](material_flow_s4_result_20260918.md)；S5 已在隔离副本完成，Q-S5-01 已确认 A：打样用料填写切割长度、每根切割支数及所需支数，见 [S5 实施结果](material_flow_s5_result_20260918.md)。业务库迁移和清理未执行。

依据：[业务方案 V1.3（R28、R29 已逐项确认）](material_flow_development_plan_v1_20260918.md)、[S1 只读预检](material_flow_s1_preflight_20260918.md)、[两张设计预览及修订记录](../outputs/material_flow_s2_design_20260918/design_notes.md)。早前“开始”授权 S2，随后用户“确认”另行授权 S3 隔离开发；均不包括业务库迁移或清理。

本文“现有”指 S2 源码核对时的事实；“新增/调整”为已批准设计。S3—S5 已实施，具体以各步实施报告为准；S6 及后续接口和页面仍待相应步骤确认。S1 数据数量属于当时快照，不能用于正式删除。

## 1. 本轮发现及必须确认的差异

| 编号 | 事实、影响 | 处理建议和状态 |
| --- | --- | --- |
| Q-S2-01 | `apps/material_issues/scopes.py` 中，金工允许 PROFILE/HARDWARE/PLASTIC/SEMI，车缝允许 FABRIC/AUXILIARY/SEMI，装配目前只允许 PACKAGING/SEMI；已确认领料图展示装配领取管材原料 | **2026-09-18 用户已选 B**：装配范围改为 PROFILE/PACKAGING/SEMI。保留图中装配示例；不增加五金、塑料、面料原料或辅料范围。S7同步前端选料、后端提交/审核/出库校验，其他车间不变 |
| Q-S2-02 | `OutsourcingOrderStatus` 没有 DRAFT，现有创建操作直接形成 PENDING_DISPATCH；外发旧预览包含“保存草稿”按钮 | **2026-09-18 用户已选 A**：去掉外发保存草稿，保存须通过现有完整性校验，成功后待外发，仓库确认发料才扣库。已生成 outsourcing_pipe_dispatch_v2.png；不新增DRAFT或不完整保存接口。生产领料原有草稿功能保留 |
| D01 | 仅两张正常状态位图获布局和风格批准，实际 1672×941，没有 Figma 节点；原方案第 5 节还列出全部弹窗及异常图 | 本轮遵从用户“设计2张图”，不继续生成其他图片。图稿批准不代表全部状态已画或1920像素验收通过；S6/S7 开发前须确认新增弹窗/未画状态的具体设计范围 |
| D02 | 当前余额按物料/单位/库区/品质合并；批次余量通过流水回放，厂内出库没有逐批次记录 | 管材必须在既有余额账中增加批次身份和单根长度；所有扣库通道同时改造，不能只修改外发页面 |
| D03 | 当前裁片来源与原料来源共用解析函数，并优先读取 `source_cutting_material_id` | 新裁片→面料关联使用独立字段和解析入口，不能把裁片半成品 ID 当作发出面料 ID |
| D04 | 现有外发按累计回货自动判断完成；回货未包含退料、损耗双侧对账 | S6 改为显式结清检查，回货只增加半成品；待结清时保留现有加工中/部分回货状态，返回可结清标志与差额，不因回货数量满额自动完成 |

技术判断：沿用现有两类库存账、权限、事务、单据模型；不新增通用库存平台。图片仅确认布局，不能凭示例扩大车间权限或增加业务状态。

## 2. 数量与公式的唯一口径

新增纯计算文件 `src/backend/apps/boms/material_flow_calculations.py`，由 BOM、采购、库存校验、外发、领料共同调用。此文件不写数据库，不反向调用采购服务，消除目前领料直接借用采购私有数量函数的单位混淆。

| 场景 | 输入 | 输出/约束 |
| --- | --- | --- |
| 管材 BOM | 切割长度 L(mm)、单耗 U(支/件)、每根切割 K(支/根)、订单 Q | L/U/K/Q 为正整数；M=ceil((L×K+50)/1000, 2位)，D=Q×U，R=ceil(D/K×1.01)，P=R×M，额度 A=R×K |
| 管材原料外发/领料 | 本部位支数 N、已确认 K/M、指定批次 | N 正整数且 N%K=0；根数=N/K，米数=根数×M；按工厂、部位、批次分别整除，不能跨行凑整 |
| 管材到货/质检/退货 | 整根数、采购快照 M | 根数×M得到米数；单根长度必须与来源一致，禁止手工改总米数制造半根 |
| 面料采购 | 本成品耗米 C、订单 Q | 建议米数=C×Q；不能将所有 FABRIC 枚举行强制当作面料 |
| 面料外发 | 分配给该裁片的米数 F、每套耗米 C | 预计套数=floor(F/C)，余料=F−预计套数×C；不足一套允许保留余料，不能自动报废 |
| 半成品领用 | 半成品余额 ID、申请支/套 | 正整数、合格库存足够；不查整根倍数，不重复占原料额度、不扣原料 |
| 其他物料 | 有效单位、用量 | 保留现有最多4位数量小数，不能把“个”等历史小数擅自四舍五入；非法占位单位阻止业务确认 |

所有金额/小数用 Decimal，接口小数传字符串。管材根、支使用整数；单根米数与管材总米数2位；面料沿用数量最多4位，裁片每套耗米4位；现有价格4位、金额4位精度保留，不在本期新增财务舍入规则。管材金额=实际采购米数×每米单价，以现有金额舍入规则保存/打印，不从界面展示的舍入值再计算。

校验空值、负数、0、NaN/Infinity、超字段范围、超过允许小数位；不静默截断。50mm只加一次，1%只影响采购建议及原料额度，不能自动转为损耗。实际采购与建议不同须原因，不自动改变订单额度。

## 3. BOM 与来源身份

### 3.1 字段设计（新增均为候选）

| 模型/字段 | 类型/来源 | 约束与迁移方式 |
| --- | --- | --- |
| BomLine.component_identity | UUID | 同产品同部位跨 BOM 版本的稳定编号；新行生成，修订同部位继承，复制到其他产品生成新编号。禁止凭名称自动合并；现有各行初始化编号，不凭历史名称推断谱系 |
| BomLine.cutting_length_mm | PositiveBigInteger，可空过渡 | 管材切割长度；合法旧 `length_value` 严格解析，非整数列补资料；正式管材确认时必须>0 |
| BomLine.pieces_per_product | PositiveBigInteger，可空过渡 | 管材单耗；合法旧 `unit_consumption` 解析 |
| BomLine.pieces_per_bar | PositiveBigInteger，可空过渡 | 原 `raw_values.tube_cut_piece_count`；不使用裁片的 `cut_piece_quantity` |
| BomLine.raw_bar_length_m | Decimal(18,2)，后端计算 | 新公式 M；旧 `raw_values.tube_cut_length_m` 不作可信输入 |
| BomLine.suggested_bar_count | PositiveBigInteger，后端计算 | R；旧 `branch_count` 对外改称采购根数 |
| BomLine.suggested_purchase_meters | Decimal(22,2)，后端计算 | P，不允许前端直接写入 |
| BomLine.fabric_source_line | 自关联 FK，PROTECT，可空 | 裁片明确选择同 BOM 中的面料原料行；一条裁片只有一个来源，但多个裁片可共享面料行。所选行必须解析到有效 MATERIAL 且单位米 |
| BomLine.fabric_meters_per_set | Decimal(18,4)，可空 | 裁片每套耗米，>0；不以裁片数量代替，不按名称自动补齐 |

管材新类型字段为新流程权威值。现有字符串字段和 raw_values 保留作导入原文与过渡展示；S4 后端在同一保存事务中投影旧展示字段，不允许两个独立可编辑真值。旧字段不得由采购/外发继续各自解析成另一种数量。BOM列表、复制、导入、订单数量同步、预览/打印都必须使用同一计算口径。

`fabric_source_line` 链接到 BOM 原料行，再通过 `products/material_identity.py` 解析真实面料 ID；无需另存一个可能矛盾的面料 ID。复制 BOM 时二次映射自关联，不能保留指向旧 BOM 的外键。裁片原有 `source_cutting_material_id` 保留为产出身份。

部位编号与本期历史重置配合：S9 后新交易使用当前确认版本。后续新建 BOM 版本必须保留明确部位谱系；存在历史领用而不能明确继承的行，阻止确认/同步并提示人工处理，不能当新行再发一份额度。历史确认单据参数快照不随 BOM 编辑重算。

## 4. 采购、入库与既有库存账

### 4.1 采购行

在 `PurchaseOrderLine` 新增 `raw_bar_length_m`、`suggested_bar_count`、`suggested_purchase_meters`、`actual_bar_count`、`actual_purchase_meters`、`quantity_difference_reason`、`calculation_snapshot`。米数字段 Decimal(22,2)，根数正整数，差异原因为 Text，快照为 JSON（含 schema_version=2、BOM/部位身份、L/U/K/M/Q、来源摘要）。单价继续使用 `unit_price`，管材单位明确元/米。

管材原 `required_quantity` 和 `actual_purchase_quantity` 在新单位流程中统一表达建议米数/实际米数，`source_unit_text` 为米，根数由新增字段表示；非管材沿用原义。这个变更必须连同到货、退货、模板、样品回写一起启用，禁止只改采购字段提前上线。客户端填写 `actual_bar_count`，服务端计算米数/金额；来源变化返回冲突并要求刷新，不能悄悄保存旧预览。

供应商表 `content_snapshot` 加入 schema_version 与根数/单根米数/总米数/元每米字段，PDF、XLSX、页面使用同一快照。管材不能走 ACTUAL_WEIGHT 按重量结算分支，提示改选按米模板；不改现有非管材重量业务。旧供应商表删除仍须 S8/S9 实施，不在结构迁移里顺带删除。

### 4.2 入库行

`MaterialInboundLine` 新增 `measurement_kind`（PIPE/OTHER）、`raw_bar_length_m`、`received_bar_count`、`accepted_bar_count`、`return_bar_count`、`calculation_snapshot`。管材既有 received/accepted/return_quantity 对应米，API 同时返回根数；质检按整根拆分，合格根数+不良退货根数=到货根数。未质检不得提前形成合格可用余额。手工入库也要求有效管材身份和长度，不能绕过同一验证。

### 4.3 余额与流水

沿用 `MaterialStockBalance`，新增 `measurement_kind`、`inbound_line`（管材批次 FK，PROTECT）、`raw_bar_length_m`、`meter_quantity`。管材 `quantity` 明确存根数，必须整数；`meter_quantity=quantity×raw_bar_length_m`。非管材 quantity 仍按原单位，新增管材字段为空。

替换旧唯一约束为两类条件唯一约束：OTHER仍为物料/单位/库区/品质；PIPE为入库行/库区/品质。管材单根长度在批次形成后不可改；检查根数非负、米数非负、正长度和根米等式。跨表物料/单位/批次一致性由服务端在锁内验证；不能误写成跨表数据库 CHECK。

`MaterialStockMovement` 新增管材 `meter_quantity`、`before_meter_quantity`、`after_meter_quantity`，quantity/before/after_quantity 保存根数。每条管材流水必须定位管材余额（因此定位入库批次），快照记录申请支数、K/M、BOM部位、实际根米。流水唯一来源约束保留；扣多批次须使用独立的分配行 ID，不能复用同一来源行造成唯一冲突。

现有 `inbound_batch_available_quantities` 的非管材回放逻辑保留；管材改读确切批次余额，不用历史FIFO推测。同一物料不同长度不能合并后计算米数。列表可汇总根/米，明细必须显示长度及批次；不能用总根数乘某一个长度。半成品继续用 `SemiFinishedStockBalance/Movement`，管材支、裁片套，不另建竞争库存账。

## 5. 订单额度、领料及批次分配

管材额度按“生产任务+产品行+component_identity”保存，单位支；同部位换版本不产生新额度。

`OrderMaterialRequirement` 新增 `measurement_kind`、`product_line`、`component_identity`、`pieces_per_bar`、`raw_bar_length_m`。PIPE 条件唯一键为任务/产品/部位；OTHER 保留任务/原料/单位/类型的原唯一口径。PIPE required_quantity=A，internal_issued_quantity 与 outsourcing_issued_quantity 都存支。`RequirementContribution` 保留来源 BOM/行及计算快照；汇总展示不参与跨部位取整。

新增/扩展稳定需求 ID 生成规则，管材加入产品及部位编号，禁止沿用仅原料/单位的旧 UUID 生成导致碰撞。更新需求、发料、领料、原料退回必须锁同一订单和需求记录。BOM 增减额度不得低于已净领用数量；来源原料、K、M变更且存在交易时返回来源冲突，不能把历史支数除以新K。未映射旧历史谱系不允许绕过。

`MaterialIssueLine` 原 requested_quantity/issued_quantity：管材原料改为支；半成品支/套；其他按原单位。新增 `calculation_snapshot` 和管材 `issued_bar_count`、`issued_meters`。未确认时实际扣库值为空，只返回预计值。

新增 `MaterialIssueStockAllocation` 子表：issue_line、inbound_line、stock_balance、requested_piece_count、issued_bar_count、issued_meters、calculation_snapshot。同一领料行可以明确选择多个批次，每个批次分配独立整根；同一行仍只有一条订单额度。草稿的分配不锁库存，确认前重新校验。出库流水 source_line_id 使用分配行 ID；其他物料与半成品保留原通道，不强制增加管材字段。

原材料退回当前批准范围为外发原料退回，不在 S7 擅自增加“厂内已出库领料退库”。领料 API 现有 `/return/` 是退回修改申请，不是实物退库。

## 6. 外发、回货与结清

### 6.1 数量字段

`OutsourcingProcessingItem.quantity/unit` 与 `FactoryAllocation.allocated_quantity` 始终表示产出计划：管材支，裁片套。新增 allocation 的 `input_quantity`、`input_unit_snapshot`、`conversion_snapshot`：管材输入支；裁片用户填写米，服务端换算预计套数及剩余米。这样既有加工单价继续按实际加工单位元/支或元/套，不把采购米价当加工价；界面必须保留现有加工价录入及单位。

`OutsourcingMaterialItem.planned_issue_quantity/unit_text` 表示原料计划扣库：管材根，面料米；新增 `planned_piece_count`、`planned_meters`、`conversion_snapshot`。相同面料的多个裁片分配必须分别明确米数，发料按分配合计，只占用一次总面料额度。

`OutsourcingDispatchLine`：issued_quantity 管材根/面料米，新增 `issued_piece_count`、`issued_meters`、`stock_balance`；关联既有 inbound_line，并保存K/M/部位及来源摘要。旧 source_quantity/material_quantity/conversion_factor 仅按新契约输出可解释值，不允许手输任意比例绕过整数校验。发料服务同时增加 requirement.outsourcing_issued_quantity（管材支，面料米）。

### 6.2 原料退回与损耗

新增 `OutsourcingRawReturn` / `OutsourcingRawReturnLine`：头含order、factory、request_id/payload_hash、操作者/时间/原因；行关联原dispatch_line、quantity（根或米）、meter_quantity、piece_quantity_equivalent、snapshot。只退到原批次及有效原库区，管材整根，恢复根米库存与原部位净发额度；不得退超过该发料尚未投入、未报损、未退数量。

新增 `OutsourcingReconciliationEntry`：order、allocation、dispatch_line（涉及原料时必填）、kind、quantity、unit_snapshot、reason、request_id/payload_hash、actor、confirmed_at、snapshot。kind 分 RAW_INPUT（投入加工）、RAW_LOSS（原料损失）、OUTPUT_SCRAP（加工报废）。管材原料侧单位根；面料米；产出侧单位支/套。只追加，不直接编辑已确认记录；错误更正需要明确后续方案，不能以负数冲销绕过数量验证。

加工投入按对应BOM转换为可解释产出：管材投入根×K；面料投入米÷每套耗米，必须以整套投入量解释，无法成套的余米保持未投入、退回或另登记原料损失。50mm已包含每根加工预留，不再单列库存损失。

两组结清等式（按工厂、部位和来源分别核对）：

- 已发原料 = 已退原料 + 投入加工原料 + 原料损失 + 尚在厂未处理原料。
- 已投入的可产出支/套 = 合格回货 + 不良回货 + 加工报废 + 尚待加工或回货。

回货可在同一事务中登记对应实际投入；既有投入记录不得重复登记。回货未产生原料第二次扣库，损耗亦不再扣仓库（原料已于发料扣库）。退回净额、投入、损失三者不能重用同一来源数量。回库不良已进入不良余额，不得再作为“未回库报废”解释一次。

`confirm_return` 保留现有合格/不良分库和重复请求保护，支/套为整数。新增显式 complete 操作检查全部原料差额及产出差额为0后才设 COMPLETED；有差额返回明细，不自动损耗、不以全部回货替代结清。

## 7. 接口清单

以下为路由注册的资源后缀，沿用项目既有 API 总前缀；新增接口不表示已可调用。读接口和预览不得建账、同步持久化需求或扣库存。

| 资源/动作 | 现有或拟新增 | 契约改动 |
| --- | --- | --- |
| boms 详情/编辑/复制/确认 | 现有 | 返回类型化参数、根米结果、裁片来源及缺资料列表；派生字段只读；修改携带已有并发版本 |
| boms/material-flow-preview | 新增 POST，无写入 | 输入待编辑行参数与订单数量，返回后端权威计算和字段错误，供BOM弹窗与采购预览复用 |
| purchase-orders 详情/更新/confirm | 现有 | actual_bar_count、差异原因、米价；返回建议根米/实际根米/来源摘要；confirm锁内重算 |
| generate-sheets / 供应商表打印导出 | 现有 | 使用同一按米金额快照，拒绝旧单位快照继续下单 |
| material-inventory eligible-lines/receipts/batch-receipts/quality-batches确认/manual-receipts | 现有 | 收货/质检按根输入，米数只读，校验单根长度；原料/半成品过滤和不同ID类型明确 |
| material-inventory 列表/详情 | 现有 | 增 stock_kind=RAW/SEMI；RAW管材批次返回根/单根米/总米，SEMI返回支/套及品质 |
| purchase-returns | 现有 | 管材整根退货，累计与原批次及采购行联校，同步根/米/金额进度 |
| outsourcing-orders source-products/.../bom、创建、dispatch-context | 现有 | 管材支及整根预览；裁片米、预计套/余米；稳定原料/半成品来源分开 |
| outsourcing-orders/{id}/confirm-dispatch | 现有 | 每批次/工厂指定支数或米，后端生成实际扣库根米；提交request_id与If-Match |
| outsourcing-orders/{id}/confirm-return | 现有 | 实收支/套、合格/不良、实际投入来源；不扣原料；返回剩余对账差额 |
| outsourcing-orders/{id}/reconciliation | 新增 GET | 按工厂/明细返回两组去向明细及can_complete/阻断原因 |
| outsourcing-orders/{id}/confirm-raw-return | 新增 POST | 原发料行、整根/米数、原因、request_id、If-Match；恢复原库存及净额度 |
| outsourcing-orders/{id}/confirm-reconciliation | 新增 POST | 实际投入/原料损失/加工报废记录，单位由服务端确定，原因必填 |
| outsourcing-orders/{id}/complete | 新增 POST | 只在双侧结清且权限及版本有效时完成 |
| material-issues requirements、创建/更新/submit/preview-issue/confirm-issue | 现有 | RAW/SEMI分区；管材行关联部位需求及批次分配；预览无写入，confirm全量复核 |
| material-issues/{id}/return | 现有 | 保留退回修改，不混为实物退库 |

统一响应包含申请数量/单位、预计或实际根米、库存余量、订单余量、BOM来源摘要。派生金额、扣库量、unit、material ID必须由来源解析校验，不能信任浏览器提交值。

建议稳定错误码：PIPE_WHOLE_BAR_REQUIRED、PIPE_LENGTH_MISMATCH、FABRIC_MAPPING_REQUIRED、STOCK_INSUFFICIENT、ORDER_ALLOWANCE_EXCEEDED、SOURCE_REVISION_CHANGED、RECONCILIATION_UNBALANCED。参数错误走现有400封装；缺少If-Match返回428，过期ETag返回412（与当前core/api/concurrency.py一致）；库存竞争、业务来源变化、重复请求内容冲突返回409；权限403。返回行ID及允许范围，禁止500替代业务校验。

新增外发权限候选：return_raw_outsourcingorder、reconcile_outsourcingorder、complete_outsourcingorder。沿用现有角色管理配置，不自动给全员授权；界面可见性与后端权限一致。具体角色绑定在S6权限验收清单中核对，不以图片中的管理员为所有用户权限。

## 8. 事务、锁与重复请求

当前外发、领料、半成品入库各自有锁，不能只复制其中一个函数就宣称锁顺序一致。S3 收敛所有交叉写入口，S5/S6/S7按统一契约接入。

目标锁顺序：入口单据（只锁本业务单）→生产任务（多任务按ID）→排产及产品来源→BOM及明细→面料/辅料映射与原料→订单需求（按ID）→入库来源行→库区（按ID）→原料余额（按ID）→半成品余额（按ID）。共同对象不能在持有后序锁时再次首次获取前序锁。BOM编辑、质检入账、采购退货、回货和原料退回同样审计；不能仅改发料两个入口。

特别修正现有半成品 `_locked_semi_finished_balance` 内部锁任务：必须在外层提前取得任务锁，避免回货先锁库区、随后锁任务，与领料顺序反转。建空余额先锁稳定父对象并用唯一约束兜底；IntegrityError重试须独立savepoint，不在已失败事务内继续查询。

一次确认事务包含：重读来源与版本→复算各行→同物料/同额度的全单合计校验→全量加锁→再次验证库存/额度→写流水与余额→写额度与单据状态/审计。中途失败整单回滚。不能按行验证通过一行就提交一行。

同request_id同payload返回原结果，不重复记账；同ID不同payload返回冲突。多批次来源ID唯一，空库存候选立即返回；带 DISTINCT 的候选查询先取ID，再用不带DISTINCT的查询加锁。读预览不为获得结果调用带写入的sync_order_requirements。

## 9. 迁移与分步文件清单

S2 核对时迁移末端：boms 0006；inventory 0012；material_issues 0002；outsourcing 0004；procurement 0017。S3 隔离副本已新增 boms/0007_material_flow_fields、0008_material_flow_constraints，inventory/0013_pipe_batch_quantities、0014_material_flow_constraints，material_issues/0003_component_allowance；只在隔离测试库执行。后续候选 procurement/0018_pipe_meter_purchase、outsourcing/0005_material_flow_reconciliation 尚未开发；各步先核对迁移图和编号，不得修改历史迁移。

结构先增加可空字段及条件约束，旧行标为未准备，不将旧库存自动换算。BOM字段准备与业务库清理分离；有不合法字段的旧BOM保持待补齐，不能默认0。旧管材余额在S9按已批准范围删除，S9启用检查必须确保没有旧口径有效库存/交易遗留。不得在普通迁移中执行不可审查的大范围删除。

| 步骤 | 主要文件（路径均相对项目根） | 本步交付与验证 |
| --- | --- | --- |
| S3 换算和库存基础 | 新增 `src/backend/apps/boms/material_flow_calculations.py`；调整 boms/models.py、inventory/models.py、inventory/stock_services.py、material_issues/models.py、material_issues/requirements.py、products/material_identity.py（均位于src/backend/apps）；上述三个应用新增结构迁移 | 纯计算、类型字段、管材批次余额、部位额度与锁协议；只在独立测试库迁移。新增公式、批次身份、并发和迁移测试；页面不宣称可用 |
| S4 BOM | `src/backend/apps/boms/services.py`、api/serializers.py、工作簿导入及复制相关调用；`src/frontend/src/views/boms/BomEditorView.vue`、BomPreviewView.vue、api/boms.ts、types/bom.ts；新增行编辑弹窗组件 | 所有类别移除底部编辑区，保留原字段/图片/取消逻辑；管材和裁片校验；导入/复制/订单同步/打印回归；受影响页面按已批准范围验收 |
| S5 采购与库存 | `src/backend/apps/procurement/models.py`、services.py、sample_purchase_services.py、purchase_sheet_services.py、purchase_sheet_pdf.py、purchase_sheet_xlsx.py、API；inventory/services.py、selectors.py、API；samples/material_arrival_services.py、material_services.py；相应结构迁移 | 根米贯穿生产及打样采购、收货质检、退货和库存。同步前端采购表单/确认、供应商表、入库质检、手工入库及库存详情和API/types，不留旧数量调用 |
| S6 外发 | `src/backend/apps/outsourcing/models.py`、services.py、selectors.py、api/serializers.py、api/views.py；新增reconciliation_services.py及迁移；前端views/outsourcing三页、components/outsourcing选择弹窗、api/outsourcing.ts、types/outsourcing.ts | 支转根米、米转预计套、分厂分批、实收、原料退回、损耗与结清。Q-S2-02已关闭，采用外发V2图且无草稿；未画交互范围在本步开发前确认；加工单价单位保留 |
| S7 领料 | `src/backend/apps/material_issues/services.py`、selectors.py、scopes.py（仅按Q-S2-01结果）、API；前端views/workshop/material-issues三页、api/materialIssues.ts、types/materialIssue.ts | 原料/半成品分区、批次分配、支根米实扣快照；不改变已确认车间范围以外的权限 |
| S8 清理工具及演练 | 拟新增 `src/backend/apps/inventory/management/commands/reset_material_flow.py`、隔离恢复库演练脚本及qa证据 | 默认只读预览，manifest含所有对象ID/计数/摘要/依赖；执行需显式参数和已审核manifest摘要。删除旧业务交易及库存、删除旧供应商表、采购重置DRAFT；不删除审计/模板/成品/样品成品 |
| S9 正式切换 | 审批后的迁移、清理工具和运行清单，不靠临时手工SQL | 目标库/备份恢复证据/维护窗口/停写/清单摘要逐项确认；演练后重新扫描漂移，切换完成再开放新单位写入 |
| S10 联合验收 | 相关测试、qa真实API链路脚本、1920截图及报告 | 完整链路和权限并发、输出文档、数据保护核对；真实业务环境写测试数据另行明确授权 |

S3—S8使用独立checkout及隔离应用/测试数据库；不得将改了一半的models热加载到现有挂载业务容器。S3开始先检查当前compose挂载和隔离方案，再实施代码；不通过“功能开关关闭界面”替代数据库结构隔离。

S3范围先完成底座，不提前添加采购/外发业务入口。S4/S5/S6/S7按本表各自申请确认；每步报告实际文件、实际结果、验证最终退出码及未完成项。S8清理脚本不能因用户曾说删除就默认获准在业务库执行。

## 10. 可复核验收清单

原方案 T01—T32 继续有效；以下为可直接据此编写的关键场景，当前均 NOT_RUN（未开发）。

| 编号 | 输入/触发 | 必须结果 |
| --- | --- | --- |
| S2-T01 | Q=1000,U=2,K=6,L=500 | M=3.05，建议337根/1027.85米，额度2022支；不能算336根或额度2000支 |
| S2-T02 | L=501,K=6 | (501×6+50)/1000=3.056，M=3.06，不能四舍五入或显示3.05 |
| S2-T03 | 外发2000支/K6；2004支/K6 | 前者拒绝；后者334根/1018.70米；每厂/批次也独立整根 |
| S2-T04 | 同原料不同部位、不同K/M | 分别计算额度及批次，不聚合平均；跨BOM版本继承部位而不再获一份额度 |
| S2-T05 | 外发1200支后领600支，额度2022 | 剩余222支；两笔并发加总超2022时仅合法事务提交；失败无部分出库 |
| S2-T06 | 外发100m、1.5m/套 | 预计66套及1m余料；实际合格60/不良4/报废2且投入99m、退1m后才可结清 |
| S2-T07 | 座布100套、靠背80套 | 两行独立库存和领料；不能直接合计成180套成品 |
| S2-T08 | 管材半成品领201支/K6 | 库存够即允许，原料账/原料额度不变 |
| S2-T09 | 退回1根原3.05m，K6 | 原批次+1根/+3.05m、原部位净外发-6支；不能退已投入或报损部分 |
| S2-T10 | 原料同入库批次两单竞争；多行重复选择 | 锁内合计，不能负数/半根；重复确认不重复流水；同ID不同请求冲突 |
| S2-T11 | 采购手工改变根数、单价 | 要求差异原因，米数联算、按米金额；模板、PDF、XLSX一致 |
| S2-T12 | 样品管材采购入库/退货及重新确认 | 根米按真实来源，缺参数阻止；到货回写一次、不回退样品成品状态 |
| S2-T13 | BOM修订、更换源面料、单位占位符 | 未确认单提示来源变化；确认单保留快照，缺资料不能按名称猜测 |
| S2-T14 | 原料回货并发领取、质检入账并发发料 | 无锁反转；事务测试在PostgreSQL验证，不用SQLite声称通过 |
| S2-T15 | 装配领取管材/包材/半成品；尝试领取五金/塑料/面料原料/辅料；越权仓库、冻结员工、无操作权限 | 已确认装配前三类在其他校验通过时允许，后四类拒绝；前后端及提交/审核/出库一致，库存及整根规则不能绕过；其他车间原范围回归 |
| S2-T16 | S8演练及恢复 | 全部候选关系闭合、旧余额不能重建、采购DRAFT、旧管材价格为空；保留对象摘要不变；恢复副本验证完整 |
| S2-T17 | 保存外发单、重复保存、仓库确认发料 | 无外发草稿入口；不完整数据拒绝保存；合法保存后PENDING_DISPATCH且库存/已发额度不变；仓库确认仅扣一次。生产领料草稿仍正常 |

开发验证命令沿用项目工具：Django check、makemigrations --check --dry-run、独立PostgreSQL测试、spectacular校验；前端npm run type-check/test/build。对本次文档只检查引用文件存在、源码摘要、公式样例及待确认状态，不把这些称为业务测试通过。

## 11. 当前交付与下一步

S2 已完成源码事实核对、字段/接口/迁移依赖、分步文件和验收清单，Q-S2-01=B、Q-S2-02=A 已登记，外发图已另存 V2，用户已整体确认。随后 S3 已完成隔离开发和专项验证；业务环境未变更，见 [S3 实施结果](material_flow_s3_result_20260918.md)。

两项业务差异均已关闭。本技术清单、业务方案 V1.3 和图稿修正记录继续作为后续开发依据。下一步 S4 须另行确认；不得因 S3 完成提前执行业务库迁移、数据清理或其他步骤。


### S5 补充确认 Q-S5-01=A

用户选择 A：打样用料填写切割长度（整数 mm）、每根切割支数及所需支数。需求、仓库可供及缺料均按整数支记录；按缺料支数和已批准公式计算建议根数与米数。采购和入库保留根米，质检合格根数乘每根切割支数回写齐料进度；这是原料可供支数换算，不生成半成品。选择明确的根制原材料资料并冻结来源，不按材料名称猜测库存身份。其余已批准规则和 S6/S7 确认门禁不变。

### S5 非管材来源补充

为保持原单位材料可入账，打样六类选料保留真实原料 ID，提交仓库前核对分类、名称规格材质、单位；采购及入库冻结该关联。原料改名不改变已确认采购和入库的历史快照。此项为 S5 来源完整性修复，未增加领料或半成品产出。
