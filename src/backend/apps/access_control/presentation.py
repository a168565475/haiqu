"""Human labels and matrix grouping, independent of persisted permission identities."""
RESOURCE_NAMES = dict(item.split(":", 1) for item in (
    "financeaccount:公司账户",
    "accountingsubject:会计科目",
    "receivablestatement:应收对账单",
    "receipt:收款确认单",
    "workshop:车间",
    "productcatalog:产品管理",
    "materialcatalog:原料管理",
    "savedview:个人保存视图",
    "dictionarytype:字典分类", "referencedictionary:字典项", "configrelease:配置版本", "systemparameterdefinition:业务参数",
    "country:国家", "currency:币种", "unit:单位", "incoterm:贸易条款", "paymentmethod:付款方式", "transportmethod:运输方式", "port:港口", "courier:快递公司", "exchangerate:汇率",
    "productcategory:产品分类", "productionunit:生产单位", "productcolor:产品颜色", "productitem:产品款式",
    "fabricmaterial:面料材质", "fabricspecification:面料规格", "fabricwidth:面料门幅", "tubeproductname:管材名称", "tubethickness:管材壁厚", "tubediameter:管材直径", "tubematerial:管材材质", "tubeshape:管材形状", "tubecoatingcolor:喷塑颜色",
    "accessoryproductname:配件名称", "accessoryspecification:配件规格", "accessorycolor:配件颜色", "accessorymaterial:配件材质", "numberrule:编号规则",
    "productinformation:产品信息", "rawmaterialinformation:原料信息", "businesstask:任务", "slapolicy:处理时限", "slatracking:时限记录", "approvalrequest:审批申请",
    "customeraccount:客户档案", "customertransactionentity:交易主体", "customertransactionentityrole:交易主体角色", "customerentityaddress:主体地址", "customerentityaddressusage:地址用途", "customercontact:联系人", "customercontactmethod:联系方式", "customercontactrole:联系人角色", "customerassignment:客户归属", "customerattentionreview:客户关注度", "customergradereview:客户等级", "customersourceattribution:客户来源", "customertag:客户标签", "customeractivityreview:客户活跃度", "customerbusinesssnapshot:客户业务概况", "customercomplaint:客诉",
    "inquiry:询盘", "inquiryitem:询盘明细", "inquiryfilelink:询盘附件", "quotationtemplate:报价模板", "quotation:报价", "quotationversion:报价版本", "quotationline:报价明细", "quotationcontainerconfig:报价装柜配置", "quotationcontainertier:装柜档位", "quotationquantitytier:数量档位", "quotationdocument:报价文件", "quotationdispatchrecord:报价发送记录",
    "samplerequest:打样申请", "sampleitem:打样明细", "samplefeerecord:样品费用", "sampleshipment:样品发货", "samplefeedback:样品反馈", "samplefilelink:样品附件", "sampleinventoryreceipt:样品入库", "sampleinventoryline:样品库存", "sampleinventoryoutbound:样品出库", "sampleinventoryoutboundline:样品出库明细", "sampleinventoryloan:样品借出", "sampleinventoryloanline:样品借出明细",
    "salesorder:销售订单", "productiontask:生产订单", "productionschedule:计划排产", "outsourcingfactory:外协工厂", "outsourcingorder:外协订单", "bom:BOM", "supplier:供应商", "purchaseorder:采购订单", "purchaserequest:采购申请", "purchaserequestallocation:采购分配", "supplierorder:供应商订单", "purchasereturn:采购退货", "purchasecontracttemplate:采购合同模板", "supplierpurchasesheet:供应商采购单",
    "warehouse:仓库", "warehousezone:库区", "warehouselocation:库位", "finishedgoodsreceipt:成品入库", "finishedgoodsoutbound:成品出库", "materialinbound:材料入库", "materialstockbalance:材料库存", "semifinishedstockbalance:半成品库存", "internalsemifinishedreceipt:厂内半成品入库", "materialissue:生产领料",
    "metalprocessingsource:金工料源", "metalprocessingcompletion:金工完工", "metalprocessingoriginalhandoff:原始交接", "metalprocessingunsprayedreturn:未喷塑回厂", "metalprocessingrework:金工返工", "metalprocessingexternalorder:金工外协单", "metalprocessingexternalhandoff:金工外协交接",
    "workshopemployee:车间员工", "craft:工艺", "operation:工序", "wagescheme:工价方案", "workreport:报工记录", "customercommunication:沟通记录", "customertimelineevent:客户动态", "auditlog:业务审计",
))
ACTION_NAMES = {
    "view": "查看", "add": "新增", "change": "编辑", "delete": "删除", "submit": "提交", "approve": "审批",
    "activate": "启用", "deactivate": "停用", "archive": "归档", "confirm": "确认", "complete": "完成",
    "cancel": "取消", "allocate": "分配", "generate": "生成", "view_all": "查看全部", "view_team": "查看团队",
    "bulk_change": "批量编辑", "bulk_create_contact_task": "批量创建联系人任务", "assign": "分配", "reassign": "重新分配",
    "issue": "签发", "dispatch": "发送", "accept": "接受", "verify": "校核", "start": "开工", "void": "作废", "publish": "发布",
    "confirm_dispatch": "确认发出", "confirm_return": "确认回厂", "return_raw": "原料退回", "disable": "停用", "reconcile": "对账",
    "review": "审核", "close": "关闭", "register": "登记", "create": "创建", "receive": "收货", "quality_confirm": "品质确认",
}


def presentation(code, permission, module):
    if code in {'production_tasks.view_productiontaskcost', 'production_tasks.manage_productiontaskexpense'}:
        viewing = code == 'production_tasks.view_productiontaskcost'
        name = '查看订单成本' if viewing else '维护订单零星费用'
        return {'resource': 'production_tasks.productiontaskcost', 'resource_name': '订单成本',
                'action': 'view' if viewing else 'special', 'action_name': name,
                'label': f'订单成本 · {name}'}
    if code in {'inventory.delete_finishedgoodsreceipt', 'inventory.delete_internalsemifinishedreceipt'}:
        model = code.split('.', 1)[1].removeprefix('delete_')
        return {"resource": f"inventory.{model}", "resource_name": RESOURCE_NAMES[model],
                "action": "delete", "action_name": "删除待入库记录",
                "label": f"{RESOURCE_NAMES[model]} · 删除待入库记录"}
    from .management_permissions import MANAGEMENT_OPERATIONS
    for name, label, _ in MANAGEMENT_OPERATIONS:
        if code == f'access_control.{name}':
            return {"resource": f"access_control.{name}", "resource_name": label,
                    "action": "special", "action_name": label, "label": label}
    if code == "organizations.manage_organization":
        return {"resource": "organizations.organizationunit", "resource_name": "部门与组织",
                "action": "special", "action_name": "管理部门与组织归属", "label": "部门与组织 · 管理部门与组织归属"}
    if module == "attendance":
        actions = {"attendance.view_attendance": ("view", "查看考勤"),
                   "attendance.sync_attendance": ("special", "同步考勤"),
                   "attendance.manage_schedule": ("special", "设置月度上班时间")}
        action, name = actions[code]
        return {"resource": "attendance.attendancemonth", "resource_name": "企业微信考勤",
                "action": action, "action_name": name, "label": f"企业微信考勤 · {name}"}
    codename = code.split(".", 1)[1]
    model = permission.content_type.model if permission else ""
    # 新模块代码先部署、迁移尚未执行时，目录仍可显示为不可用。
    if code in {f"finance.{action}_financeaccount" for action in ("view", "add", "change", "delete")}:
        model = "financeaccount"
    if code in {f"finance.{action}_accountingsubject" for action in ("view", "add", "change", "delete")}:
        model = "accountingsubject"
    if code in {f"finance.{action}_receivablestatement" for action in ("view", "add", "change", "void", "delete")}:
        model = "receivablestatement"
    if code.startswith("access_control."):
        model = codename.split("_reference_", 1)[-1] if "_reference_" in codename else codename.split("_", 1)[1]
    model = {'samplefee': 'samplefeerecord', 'sample': 'samplerequest', 'purchasesheets': 'supplierpurchasesheet', 'bomquantity': 'bom'}.get(model, model)
    resource_name = RESOURCE_NAMES.get(model)
    if resource_name is None:
        raise ValueError(f"Missing access catalog resource label: {code} ({model})")
    prefix = codename[:-(len(model) + 1)] if codename.endswith("_" + model) else codename
    prefix = prefix.removesuffix("_reference")
    is_plain = prefix in {"view", "add", "change", "delete", "submit", "approve"}
    name = ACTION_NAMES.get(prefix)
    if not name:
        original = permission.name if permission else ""
        name = original if any('\u4e00' <= c <= '\u9fff' for c in original) else (
            {"manage_sla_policy": "管理处理时限", "approve_customer_transfer": "审批客户转移", "transfer_customer": "转移客户", "merge_customer": "合并客户",
             "process_customer_complaint": "处理客诉", "decide_sample_fee": "审批样品费用", "edit_sample_materials": "编辑样品材料",
             "review_sample_application": "审核打样申请", "review_sample_materials": "审核样品材料", "ship_sample": "样品发货",
             "receive_material": "材料收货", "view_material_receipt": "查看材料收货", "quality_confirm_material": "材料品质确认",
             "confirm_metalprocessingexternalreturn": "确认金工外协回厂", "bulk_create_contact_task": "批量创建联系人任务"}.get(codename, "专项操作"))
    return {"resource": f"{module}.{model}", "resource_name": resource_name,
            "action": prefix if is_plain else "special", "action_name": name,
            "label": f"{resource_name} · {name}"}
