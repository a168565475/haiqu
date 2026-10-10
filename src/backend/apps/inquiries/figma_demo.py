"""仅供开发环境 Figma 视觉验收使用的询盘示例数据。"""

from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.customers.models import CustomerAccount, CustomerContact
from apps.organizations.models import Employee

from .models import Inquiry, InquiryAssignmentHistory, InquiryItem, InquiryStatus


DEMO_SOURCE_SYSTEM = "FIGMA_DEMO"
DEMO_QUERY_VALUE = "figma"


def is_figma_demo_request(request):
    return request.query_params.get("demo") == DEMO_QUERY_VALUE


def is_figma_demo_inquiry(inquiry):
    return inquiry.source_system == DEMO_SOURCE_SYSTEM


DEMO_ROWS = (
    {"external_id": "PENDING-01", "customer_code": "CUS-DEMO-0001", "owner_code": None, "status": InquiryStatus.NEW, "subject": "折叠露营家具采购需求", "source": "EMAIL", "products": (("折叠露营床", "600D 牛津布 / 黑色", "1200", "18.5000"),), "stage": ("PENDING_CONFIRMATION", "待确认"), "sla": ("DUE_SOON", "首响 SLA", 20)},
    {"external_id": "ANALYZING-02", "customer_code": "CUS-DEMO-0002", "owner_code": "DEMO_SALES_A", "status": InquiryStatus.ANALYZING, "subject": "户外折叠椅年度采购询盘", "source": "WEBSITE", "products": (("铝合金折叠椅", "阳极氧化铝管 / 深灰", "800", "12.2000"),), "stage": ("REQUIREMENTS", "需求确认"), "sla": ("BREACHED", "需求确认 SLA", -90)},
    {"external_id": "READY-03", "customer_code": "CUS-DEMO-0003", "owner_code": "DEMO_SALES_B", "status": InquiryStatus.READY_FOR_QUOTE, "subject": "野餐套装定制项目", "source": "EXHIBITION", "products": (("野餐收纳箱", "竹木盖 / 定制丝印", "500", "26.0000"),), "stage": ("REQUIREMENTS", "需求确认"), "sla": ("NORMAL", "需求确认 SLA", 360)},
    {"external_id": "QUOTING-04", "customer_code": "CUS-DEMO-0004", "owner_code": "DEMO_SALES_C", "status": InquiryStatus.QUOTING, "subject": "保温箱与冰袋组合采购", "source": "REFERRAL", "products": (("软式保温箱", "30L / 蓝灰色", "1500", "16.8000"),), "stage": ("QUOTING", "报价中"), "sla": ("NORMAL", "报价跟进 SLA", 480)},
    {"external_id": "ACCEPTED-05", "customer_code": "CUS-DEMO-0005", "owner_code": "DEMO_SALES_A", "status": InquiryStatus.QUOTE_ACCEPTED, "subject": "户外储物柜补货计划", "source": "EMAIL", "products": (("户外储物柜", "PP 材质 / 防水", "300", "59.0000"),), "stage": ("QUOTE_ACCEPTED", "报价已接受"), "sla": ("NORMAL", "订单创建提醒", 720)},
    {"external_id": "DRAFT-EDITOR", "customer_code": "CUS-DEMO-0001", "owner_code": "DEMO_SALES_B", "status": InquiryStatus.DRAFT, "subject": "折叠露营系列新品询盘草稿", "source": "WEBSITE", "products": (("折叠露营床", "600D 牛津布 / 黑色", "1200", "18.5000"), ("折叠露营椅", "铝管 / 承重 120kg", "800", "12.2000"), ("露营收纳包", "防泼水涤纶 / 深灰", "600", "8.6000")), "stage": ("DRAFT", "草稿"), "sla": ("NONE", "", None)},
    {"external_id": "QUOTED-07", "customer_code": "CUS-DEMO-0002", "owner_code": "DEMO_SALES_C", "status": InquiryStatus.QUOTED, "subject": "折叠桌年度框架询盘", "source": "EMAIL", "products": (("铝合金折叠桌", "70 × 50cm / 银色", "600", "22.0000"),), "stage": ("QUOTING", "报价中"), "sla": ("NORMAL", "报价跟进 SLA", 360)},
    {"external_id": "NEW-08", "customer_code": "CUS-DEMO-0003", "owner_code": "DEMO_SALES_B", "status": InquiryStatus.NEW, "subject": "露营床补货采购需求", "source": "EXHIBITION", "products": (("折叠露营床", "加厚牛津布 / 卡其", "400", "25.5000"),), "stage": ("PENDING_CONFIRMATION", "待确认"), "sla": ("BREACHED", "首响 SLA", -120)},
)


def _demo_metadata(row):
    state, policy_name, minutes = row["sla"]
    deadline = timezone.now() + timedelta(minutes=minutes) if minutes is not None else None
    return {"figma_demo": True, "display_stage": {"code": row["stage"][0], "label": row["stage"][1]}, "sla": {"state": state, "policy_name": policy_name, "next_deadline_at": deadline.isoformat() if deadline else None, "remaining_seconds": minutes * 60 if minutes is not None else None}}


def demo_override(inquiry):
    return (inquiry.source_snapshot or {}).get("figma_demo", {})


@transaction.atomic
def seed_figma_demo_inquiries():
    """创建一次性、幂等的开发库示例询盘；绝不修改已有记录。"""
    if not settings.DEBUG:
        raise ValidationError("Figma 示例数据只能在开发环境初始化。")
    customers = {customer.account_code: customer for customer in CustomerAccount.objects.filter(account_code__in=[row["customer_code"] for row in DEMO_ROWS], archived_at__isnull=True)}
    missing_customers = sorted({row["customer_code"] for row in DEMO_ROWS} - set(customers))
    if missing_customers:
        raise ValidationError({"detail": f"缺少 Figma 演示客户：{', '.join(missing_customers)}。"})
    owners = {employee.employee_code: employee for employee in Employee.objects.filter(employee_code__in=[row["owner_code"] for row in DEMO_ROWS if row["owner_code"]], status="ACTIVE", archived_at__isnull=True)}
    missing_owners = sorted({row["owner_code"] for row in DEMO_ROWS if row["owner_code"]} - set(owners))
    if missing_owners:
        raise ValidationError({"detail": f"缺少 Figma 演示负责人：{', '.join(missing_owners)}。"})
    seeded = []
    for index, row in enumerate(DEMO_ROWS, start=1):
        inquiry = Inquiry.objects.filter(source_system=DEMO_SOURCE_SYSTEM, external_id=row["external_id"]).first()
        if inquiry is not None:
            seeded.append(inquiry)
            continue
        customer = customers[row["customer_code"]]
        contact = CustomerContact.objects.filter(customer_account=customer, archived_at__isnull=True, status="ACTIVE").order_by("-is_primary_contact", "id").first()
        owner = owners.get(row["owner_code"])
        received_at = timezone.now() - timedelta(hours=index * 3)
        inquiry = Inquiry.objects.create(customer_account=customer, customer_contact=contact, owner_employee=owner, inquiry_number=f"INQ-FIGMA-{index:02d}", status=InquiryStatus.DRAFT, inquiry_source=row["source"], subject=row["subject"], description="用于 Figma 页面视觉验收的受控示例需求。示例数据不代表真实业务事实。", received_at=received_at, requested_due_at=received_at + timedelta(days=7), source_system=DEMO_SOURCE_SYSTEM, external_id=row["external_id"], customer_snapshot={"account_code": customer.account_code, "account_name": customer.account_name}, source_snapshot={"figma_demo": _demo_metadata(row)}, customer_language_code="EN", trade_term_code="FOB", trade_term_place="NINGBO", delivery_requirement="下单后 45 天", estimated_amount_min="18000.00", estimated_amount_max="48000.00", estimated_currency_code="USD", draft_version=1)
        InquiryItem.objects.bulk_create([InquiryItem(inquiry=inquiry, line_number=line_number, product_description=product, specification=specification, quantity=quantity, unit_code="PCS", target_unit_price=price, target_currency_code="USD", expected_date=date.today() + timedelta(days=30 + line_number), product_match_status="PENDING") for line_number, (product, specification, quantity, price) in enumerate(row["products"], start=1)])
        if row["status"] != InquiryStatus.DRAFT:
            inquiry.status = row["status"]
            inquiry.submitted_at = received_at + timedelta(minutes=15)
            inquiry.assigned_at = received_at + timedelta(minutes=20) if owner else None
            inquiry.save(update_fields=["status", "submitted_at", "assigned_at", "updated_at"])
        if owner:
            InquiryAssignmentHistory.objects.create(inquiry=inquiry, previous_owner_employee=None, new_owner_employee=owner, assigned_by_employee=owner, assignment_reason="Figma 视觉验收示例初始化", assignment_type="FIGMA_DEMO", assigned_at=received_at + timedelta(minutes=20))
        seeded.append(inquiry)
    return seeded
