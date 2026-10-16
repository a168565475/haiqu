from apps.access_control import sales_policy
from datetime import timedelta
from decimal import Decimal, localcontext

from django.db.models import Exists, OuterRef, Prefetch, Q
from django.utils import timezone

from apps.customers.models import AssignmentRole, CustomerAssignment
from apps.customers.selectors import accessible_customers
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit
from apps.workflow.models import SlaTrackingStatus

from .models import Inquiry, InquiryAssignmentHistory, InquiryItem, InquirySlaLink


ACTIVE_INQUIRY_STATUSES = [
    "NEW",
    "ANALYZING",
    "READY_FOR_QUOTE",
    "QUOTING",
    "QUOTED",
    "FOLLOW_UP",
    "QUOTE_ACCEPTED",
]


def inquiry_product_amount(obj):
    """复用预取的产品明细，按币种精确累加目标单价乘数量。"""
    items = getattr(obj, "list_items", None)
    if items is None:
        items = list(obj.items.all())
    totals = {}
    missing_count = 0
    with localcontext() as context:
        # 两个 18 位十进制字段相乘并累加，不能使用默认 28 位精度。
        context.prec = 50
        for item in items:
            if item.target_unit_price is None or not item.target_currency_code:
                missing_count += 1
                continue
            currency = item.target_currency_code
            totals[currency] = totals.get(currency, Decimal(0)) + item.target_unit_price * item.quantity
    return {
        "item_count": len(items),
        "missing_price_count": missing_count,
        "totals": [{"currency_code": currency, "amount": format(amount, "f")} for currency, amount in sorted(totals.items())],
    }


def accessible_inquiries(request, permission_codename="view_inquiry"):
    """询盘始终按客户可见范围裁剪，操作权限不扩大数据范围。"""
    return Inquiry.objects.filter(customer_account__in=accessible_customers(request, permission_codename))


def with_quotation_presence(queryset, request=None):
    """按询盘去重：存在未取消、未归档且至少有一个未作废版本的报价。"""
    from apps.quotations.models import Quotation, QuotationVersionStatus

    active_versions = [value for value in QuotationVersionStatus.values if value != QuotationVersionStatus.VOID]
    quotations = Quotation.objects.filter(
        source_inquiry_id=OuterRef("pk"), archived_at__isnull=True,
        versions__status__in=active_versions,
    ).exclude(outcome_status="CANCELLED")
    if request is not None and sales_policy.enabled():
        quotations = quotations.filter(customer_account__in=accessible_customers(request, "view_quotation"))
    return queryset.annotate(has_quotation=Exists(quotations))


def inquiries_with_context(queryset=None, *, list_mode=False, request=None):
    """列表所需关联一次预取，序列化阶段不再逐行查询。"""
    if queryset is None:
        queryset = Inquiry.objects.all()
    queryset = with_quotation_presence(queryset, request)
    now = timezone.now()
    current_period = Q(effective_from__lte=now) & (Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    current_sla = InquirySlaLink.objects.filter(is_current=True).select_related("sla_tracking__sla_policy")
    primary_owners = CustomerAssignment.objects.filter(current_period, assignment_role=AssignmentRole.PRIMARY_OWNER).select_related("employee")
    queryset = queryset.select_related("customer_account", "transaction_entity", "customer_contact", "owner_employee").prefetch_related(
        Prefetch(
            "items",
            queryset=InquiryItem.objects.select_related(
                "product",
                "product_category",
                "product_unit",
                "product_color",
                "product_image",
            ).order_by("line_number", "id"),
            to_attr="list_items",
        ),
        Prefetch("sla_links", queryset=current_sla, to_attr="current_sla_links"),
        Prefetch("customer_account__assignments", queryset=primary_owners, to_attr="current_primary_owners"),
    )
    if list_mode:
        from apps.quotations.models import Quotation
        from apps.samples.models import SampleRequest

        sent_quotes = Quotation.objects.filter(archived_at__isnull=True, versions__status="SENT").distinct()
        if request is not None and sales_policy.enabled():
            sent_quotes = sent_quotes.filter(customer_account__in=accessible_customers(request, "view_quotation"))
        queryset = queryset.prefetch_related(
            Prefetch("quotations", queryset=sent_quotes, to_attr="sent_quotations"),
            Prefetch("sample_requests", queryset=SampleRequest.objects.filter(archived_at__isnull=True, status__in=["PENDING", "PREPARING", "SHIPPED", "FEEDBACK_PENDING"]).only("id", "source_inquiry_id"), to_attr="active_sample_requests"),
        )
    else:
        from apps.quotations.models import Quotation
        from apps.samples.models import SampleRequest

        queryset = queryset.prefetch_related(
            "file_links__business_file",
            "task_links__business_task",
            Prefetch(
                "quotations",
                queryset=Quotation.objects.filter(archived_at__isnull=True)
                .prefetch_related("versions__sales_orders")
                .order_by("-created_at", "-id"),
                to_attr="linked_quotation_rows",
            ),
            Prefetch(
                "sample_requests",
                queryset=SampleRequest.objects.filter(archived_at__isnull=True).only("id", "source_inquiry_id", "request_number", "status", "updated_at").order_by("-updated_at", "-id"),
                to_attr="linked_sample_rows",
            ),
            Prefetch(
                "assignment_history",
                queryset=InquiryAssignmentHistory.objects.select_related(
                    "previous_owner_employee", "new_owner_employee"
                ).order_by("-assigned_at", "-id"),
                to_attr="assignment_history_rows",
            ),
        )
    return queryset


def inquiry_sla_summary(inquiry, now=None):
    now = now or timezone.now()
    links = getattr(inquiry, "current_sla_links", None)
    if links is None:
        links = list(inquiry.sla_links.filter(is_current=True).select_related("sla_tracking__sla_policy"))
    if not links:
        return {"state": "NONE", "next_deadline_at": None, "remaining_seconds": None}
    # 多个阶段并行时优先展示最早到期的一项，与详情顺序保持一致。
    links = sorted(links, key=lambda link: (link.sla_tracking.next_deadline_at is None, link.sla_tracking.next_deadline_at or link.created_at, str(link.pk)))
    tracking = links[0].sla_tracking
    deadline = tracking.next_deadline_at
    from .worktime import remaining_seconds
    remaining = remaining_seconds(tracking, now)
    if tracking.status == SlaTrackingStatus.BREACHED or (deadline and tracking.status == SlaTrackingStatus.RUNNING and deadline < now):
        state = "BREACHED"
    elif deadline and tracking.status == SlaTrackingStatus.RUNNING and remaining is not None and remaining <= 1800:
        state = "DUE_SOON"
    else:
        state = "NORMAL"
    return {"state": state, "next_deadline_at": deadline, "remaining_seconds": remaining, "working_time": bool(tracking.tracking_data.get("work_calendar")), "stage_code": links[0].stage_code, "active_count": len(links)}


def inquiry_display_stage(inquiry):
    if inquiry.status == "NEW":
        return "PENDING_CONFIRMATION", "已分配" if inquiry.owner_employee_id else "新询盘"
    if inquiry.owner_employee_id is None and inquiry.status in ACTIVE_INQUIRY_STATUSES:
        return "OWNER_EXCEPTION", "负责人异常"
    if inquiry.status == "QUOTE_ACCEPTED":
        return "QUOTE_ACCEPTED", "报价已接受"
    if inquiry.status in {"QUOTING", "QUOTED", "FOLLOW_UP"}:
        return "QUOTING", "报价中"
    if inquiry.status == "ANALYZING":
        return "REQUIREMENTS", "已首响"
    if inquiry.status == "READY_FOR_QUOTE":
        return "REQUIREMENTS", "需求确认"
    return inquiry.status, inquiry.get_status_display()


def assignable_employees(request):
    """主管只能分配本组织及下级组织的在职员工；无组织时仅本人。"""
    base = Employee.objects.filter(status="ACTIVE", archived_at__isnull=True)
    if request.user.is_superuser or request.user.has_perm("customers.view_all_customer"):
        return base.order_by("employee_code")
    actor = getattr(request, "employee", None)
    if actor is None:
        return base.none()
    now = timezone.now()
    active_period = Q(effective_from__lte=now) & (Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    roots = set(EmployeeOrganizationAssignment.objects.filter(active_period, employee=actor).values_list("organization_unit_id", flat=True))
    if not roots:
        return base.filter(pk=actor.pk)
    descendants, frontier = set(roots), set(roots)
    while frontier:
        children = set(OrganizationUnit.objects.filter(parent_id__in=frontier, archived_at__isnull=True).values_list("id", flat=True))
        frontier = children - descendants
        descendants.update(frontier)
    employee_ids = EmployeeOrganizationAssignment.objects.filter(active_period, organization_unit_id__in=descendants).values_list("employee_id", flat=True)
    return base.filter(Q(pk=actor.pk) | Q(pk__in=employee_ids)).distinct().order_by("employee_code")
