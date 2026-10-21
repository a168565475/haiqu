import re
import uuid
from datetime import date

from django.db import migrations, models


NUMBER_RULE_NAMESPACE = uuid.UUID("a43e3784-f33f-4d85-a71d-94c74e715b7b")
# 迁移固定当时的规则与来源，不导入之后可能变化的业务生成器。
DAILY_RULES = (
    ("BOM", "BOM 编号", "BOM", (("boms", "Bom", "bom_number"),)),
    ("PURCHASE_ORDER", "采购订单编号", "CGDD", (
        ("procurement", "PurchaseOrder", "order_number"),
        ("procurement", "SupplierPurchaseSheet", "sheet_number"),
    )),
    ("PURCHASE_REQUEST", "请购单编号", "PR", (("procurement", "PurchaseRequest", "request_number"),)),
    ("PURCHASE_RETURN", "采购退货编号", "TH", (("procurement", "PurchaseReturn", "return_number"),)),
    ("PRODUCTION_SCHEDULE", "排产单编号", "PC", (("production_scheduling", "ProductionSchedule", "schedule_number"),)),
    ("MATERIAL_INBOUND", "原料入库编号", "CLRK", (("inventory", "MaterialInbound", "inbound_number"),)),
    ("MATERIAL_ISSUE", "生产领料编号", "LL", (("material_issues", "MaterialIssue", "issue_number"),)),
    ("INTERNAL_SEMI_RECEIPT", "内部半成品入库编号", "BNRK", (("inventory", "InternalSemiFinishedReceipt", "receipt_number"),)),
    ("FINISHED_GOODS_RECEIPT", "成品入库编号", "CPRK", (("inventory", "FinishedGoodsReceipt", "receipt_number"),)),
    ("FINISHED_GOODS_OUTBOUND", "成品出库编号", "CPCK", (("inventory", "FinishedGoodsOutbound", "outbound_number"),)),
    ("OUTSOURCING_ORDER", "委外加工单编号", "WF", (
        ("outsourcing", "OutsourcingOrder", "order_number"),
        ("outsourcing", "TubeOutsourcingOrder", "order_number"),
        ("material_issues", "MetalProcessingExternalOrder", "order_number"),
    )),
    ("OUTSOURCING_DISPATCH", "委外发料编号", "FL", (("outsourcing", "OutsourcingDispatch", "dispatch_number"),)),
    ("OUTSOURCING_RETURN", "委外回货编号", "WH", (
        ("outsourcing", "OutsourcingReturn", "return_number"),
        ("material_issues", "MetalProcessingExternalGoodReturn", "return_number"),
    )),
    ("TUBE_OUTSOURCING_RECEIPT", "管材外发结单回货编号", "WFHK", (("outsourcing", "TubeOutsourcingReceipt", "receipt_number"),)),
    ("WORK_REPORT", "计件报工编号", "BG", (
        ("workshop_reporting", "WorkReport", "report_number"),
        ("workshop_reporting", "WorkReportHistory", "report_number"),
    )),
)


def parse_daily_number(number, prefix):
    # 只判断字符串是否占用新格式号码；旧号若恰好也符合新格式，同样保守预留以免撞号。
    if not isinstance(number, str):
        return None
    matched = re.fullmatch(rf"{re.escape(prefix)}([0-9]{{6}})([0-9]{{3,}})", number)
    if matched is None:
        return None
    short_date, sequence_text = matched.groups()
    try:
        # 短年份按 2000–2099 年初始化，避免 strptime 的 69 年分界将 2099 解释成 1999。
        number_date = date(2000 + int(short_date[:2]), int(short_date[2:4]), int(short_date[4:]))
    except ValueError:
        return None
    sequence = int(sequence_text)
    if sequence < 1 or sequence_text != f"{sequence:03d}":
        return None
    return number_date, sequence


def seed_daily_number_rules(apps, schema_editor):
    alias = schema_editor.connection.alias
    NumberRule = apps.get_model("reference_data", "NumberRule")
    Counter = apps.get_model("core", "DailyBusinessNumberCounter")
    maxima = {}

    def remember(number_type, prefix, number):
        parsed = parse_daily_number(number, prefix)
        if parsed is not None:
            number_date, sequence = parsed
            key = (number_type, number_date)
            maxima[key] = max(maxima.get(key, 0), sequence)

    for index, (number_type, chinese_name, prefix, sources) in enumerate(DAILY_RULES):
        rule, _ = NumberRule.objects.using(alias).get_or_create(
            number_type=number_type,
            defaults={
                "id": uuid.uuid5(NUMBER_RULE_NAMESPACE, number_type),
                "chinese_name": chinese_name,
                "is_configured": False,
                "sort_order": 300 + index * 10,
            },
        )
        NumberRule.objects.using(alias).filter(pk=rule.pk).update(
            prefix=prefix,
            format_pattern="{prefix}{short_date}{sequence}",
            sequence_name="",
            sequence_padding=3,
            date_granularity="DAY",
            reset_policy="DAILY",
            is_configured=True,
            description="前缀+YYMMDD+至少三位日流水；同类型同日共用计数，超过999自动扩位；成功单删除或取消不回退，历史号码不改写。",
        )
        for app_label, model_name, field_name in sources:
            model = apps.get_model(app_label, model_name)
            numbers = model.objects.using(alias).filter(
                **{f"{field_name}__startswith": prefix},
            ).values_list(field_name, flat=True)
            for number in numbers.iterator():
                remember(number_type, prefix, number)

    # 采购及普通外发可物理删除，已发号码在删除审计中保留；只读取明确的类型与字段。
    AuditLog = apps.get_model("audit", "AuditLog")
    deleted_documents = AuditLog.objects.using(alias).filter(
        action="DELETED", object_type__in=["PURCHASE_ORDER", "SUPPLIER_PURCHASE_SHEET", "OUTSOURCING_ORDER"],
    ).values_list("id", "object_type", "before_data")
    for audit_id, object_type, snapshot in deleted_documents.iterator():
        if not isinstance(snapshot, dict):
            raise ValueError(f"删除审计 {audit_id} 的快照不是对象，不能安全初始化日流水。")
        if object_type == "OUTSOURCING_ORDER":
            remember("OUTSOURCING_ORDER", "WF", snapshot.get("order_number"))
        elif object_type == "SUPPLIER_PURCHASE_SHEET":
            remember("PURCHASE_ORDER", "CGDD", snapshot.get("sheet_number"))
        else:
            remember("PURCHASE_ORDER", "CGDD", snapshot.get("order_number"))
            sheets = snapshot.get("deleted_supplier_purchase_sheets", [])
            if not isinstance(sheets, list) or any(not isinstance(sheet, dict) for sheet in sheets):
                raise ValueError(f"采购删除审计 {audit_id} 的采购表快照不是对象列表，不能安全初始化日流水。")
            for sheet in sheets:
                remember("PURCHASE_ORDER", "CGDD", sheet.get("sheet_number"))

    for (number_type, number_date), last_value in maxima.items():
        counter, _ = Counter.objects.using(alias).get_or_create(
            number_type=number_type, business_date=number_date, defaults={"last_value": last_value},
        )
        if counter.last_value < last_value:
            Counter.objects.using(alias).filter(pk=counter.pk).update(last_value=last_value)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_daily_business_number_counter"),
        ("reference_data", "0028_fill_supplemental_accessory_units"),
        ("boms", "0011_product_review_snapshots"),
        ("procurement", "0021_purchaseorderline_material_attributes"),
        ("inventory", "0020_materialinboundline_material_attributes"),
        ("material_issues", "0013_external_order_unit_price"),
        ("outsourcing", "0013_tube_material_factory_and_price"),
        ("production_scheduling", "0005_backfill_scheduled_tasks_in_production"),
        ("workshop_reporting", "0014_workreport_history"),
        ("audit", "0003_alter_auditlog_options"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="numberrule", name="number_rule_configured_fields_required"),
        migrations.AddConstraint(
            model_name="numberrule",
            constraint=models.CheckConstraint(
                condition=models.Q(is_configured=False) | (
                    ~models.Q(prefix="") & ~models.Q(format_pattern="") & (
                        models.Q(reset_policy="DAILY") | ~models.Q(sequence_name="")
                    )
                ),
                name="number_rule_configured_fields_required",
            ),
        ),
        # 已发号码不能回退；规则切换与计数初始化仅提供前向迁移。
        migrations.RunPython(seed_daily_number_rules),
    ]
