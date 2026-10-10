from django.db import connection
from django.utils import timezone


NUMBER_CONFIG = {
    "CUSTOMER": ("haiqu_customer_number_seq", "CUS", False),
    "INQUIRY": ("haiqu_inquiry_number_seq", "INQ", True),
    "QUOTATION": ("haiqu_quotation_number_seq", "QUO", True),
    "SAMPLE": ("haiqu_sample_number_seq", "SMP", True),
    "SAMPLE_INTAKE": ("haiqu_sample_intake_number_seq", "SRQ", True),
    "SAMPLE_INVENTORY_RECEIPT": ("haiqu_sample_inventory_receipt_seq", "RK", True),
    "SAMPLE_INVENTORY_OUTBOUND": ("haiqu_sample_inventory_outbound_seq", "CK", True),
    "SAMPLE_INVENTORY_LOAN": ("haiqu_sample_inventory_loan_seq", "JC", True),
    "SALES_ORDER": ("haiqu_sales_order_number_seq", "SO", True),
    "PRODUCTION_ORDER": ("haiqu_production_order_number_seq", "HT", True),
    "PURCHASE_REQUEST": ("haiqu_purchase_request_number_seq", "PR", True),
    "PURCHASE_RETURN": ("haiqu_purchase_return_number_seq", "TH", True),
    "PRODUCTION_TASK": ("haiqu_production_task_number_seq", "HT", True),
    "PRODUCTION_SCHEDULE": ("haiqu_production_schedule_number_seq", "PC", True),
    "SALES_CONTRACT": ("haiqu_sales_contract_number_seq", "HTC", True),
    "BOM": ("haiqu_bom_number_seq", "BOM", False),
    "COMPLAINT": ("haiqu_complaint_number_seq", "CS", False),
    "SUPPLIER": ("haiqu_supplier_number_seq", "GYS", False),
    "FINISHED_GOODS_RECEIPT": ("haiqu_finished_goods_receipt_seq", "CPRK", True),
    "FINISHED_GOODS_OUTBOUND": ("haiqu_finished_goods_outbound_seq", "CPCK", True),
    "MATERIAL_INBOUND": ("haiqu_material_inbound_seq", "CLRK", True),
    "WAGE_SCHEME": ("haiqu_wage_scheme_seq", "GJ", True),
    "WORK_REPORT": ("haiqu_work_report_seq", "BG", True),
}


def _registered_number_rule(number_type):
    # 延迟导入避免 core 与 reference_data 应用初始化时形成循环依赖。
    from apps.reference_data.models import NumberRule, ReferenceStatus

    return NumberRule.objects.filter(
        number_type=number_type,
        is_configured=True,
        status=ReferenceStatus.ACTIVE,
        archived_at__isnull=True,
    ).first()


def next_business_number(number_type, business_date=None):
    if number_type in {"PRODUCTION_ORDER", "PRODUCTION_TASK"}:
        # 两条历史入口现在共用一套生产任务年度流水，避免继续产生 MO 与旧 HT 格式。
        from apps.production_tasks.numbering import next_production_task_number

        return next_production_task_number(business_date)

    rule = _registered_number_rule(number_type)
    if rule is None:
        if number_type not in NUMBER_CONFIG:
            raise ValueError(f"不支持或尚未配置的业务编号类型：{number_type}")
        # 仅供迁移尚未落库的启动窗口兼容，正式运行以登记表为准。
        sequence_name, prefix, include_month = NUMBER_CONFIG[number_type]
        date_granularity = "MONTH" if include_month else ("YEAR" if number_type == "COMPLAINT" else "NONE")
        if number_type == "SUPPLIER":
            padding = 5
            format_pattern = "{prefix}{sequence}"
        elif number_type == "BOM":
            padding = 7
            format_pattern = "{prefix}{sequence}"
        else:
            padding = 4 if number_type == "COMPLAINT" else 6
            format_pattern = "{prefix}-{date}-{sequence}" if date_granularity != "NONE" else "{prefix}-{sequence}"
    else:
        if rule.reset_policy != "NEVER":
            raise ValueError(f"编号类型 {number_type} 使用重置流水，必须调用对应业务模块的专用生成器。")
        sequence_name = rule.sequence_name
        prefix = rule.prefix
        date_granularity = rule.date_granularity
        padding = rule.sequence_padding
        format_pattern = rule.format_pattern

    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(%s::regclass)", [sequence_name])
        sequence_value = cursor.fetchone()[0]

    number_date = business_date or timezone.localdate()
    date_value = ""
    if date_granularity == "YEAR":
        date_value = f"{number_date:%Y}"
    elif date_granularity == "MONTH":
        date_value = f"{number_date:%Y%m}"
    elif date_granularity == "DAY":
        date_value = f"{number_date:%Y%m%d}"
    return format_pattern.format(
        prefix=prefix,
        date=date_value,
        sequence=str(sequence_value).zfill(padding),
    )
