from django.db import connection
from django.utils import timezone


NUMBER_CONFIG = {
    "CUSTOMER": ("haiqu_customer_number_seq", "CUS", False),
    "INQUIRY": ("haiqu_inquiry_number_seq", "INQ", True),
    "QUOTATION": ("haiqu_quotation_number_seq", "QUO", True),
    "SAMPLE": ("haiqu_sample_number_seq", "SMP", True),
}


def next_business_number(number_type, business_date=None):
    try:
        sequence_name, prefix, include_month = NUMBER_CONFIG[number_type]
    except KeyError as exc:
        raise ValueError(f"不支持的业务编号类型：{number_type}") from exc

    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(%s::regclass)", [sequence_name])
        sequence_value = cursor.fetchone()[0]

    if include_month:
        number_date = business_date or timezone.localdate()
        return f"{prefix}-{number_date:%Y%m}-{sequence_value:06d}"
    return f"{prefix}-{sequence_value:06d}"
