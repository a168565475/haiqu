from apps.access_control import sales_policy
from django.db.models import (
    Count,
    DateTimeField,
    DecimalField,
    ExpressionWrapper,
    F,
    CharField,
    JSONField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
)
from django.db.models.functions import Cast, JSONObject
from django.utils import timezone

from .models import (
    CustomerAccount,
    CustomerActivityReview,
    CustomerAssignment,
    CustomerAttentionReview,
    CustomerBusinessSnapshot,
    CustomerDataAccessGrant,
    CustomerGradeReview,
    CustomerInterestedProduct,
    CustomerCompanyContactMethod,
    CustomerSourceAttribution,
    CustomerTagAssignment,
    CustomerTaskLink,
    CustomerTypeAssignment,
)


def _legacy_accessible_customers(request, permission_codename="view_customeraccount"):
    queryset = CustomerAccount.objects.all()
    user = request.user
    if user.is_superuser or user.has_perm("customers.view_all_customer"):
        return queryset

    employee = getattr(request, "employee", None)
    if employee is None:
        return queryset.none()

    now = timezone.now()
    active_period = Q(effective_from__lte=now) & (Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    assigned_customer_ids = CustomerAssignment.objects.filter(
        active_period,
        employee=employee,
    ).values("customer_account_id")
    granted_customer_ids = CustomerDataAccessGrant.objects.filter(
        active_period,
        employee=employee,
        permission__codename=permission_codename,
        revoked_at__isnull=True,
    ).values("customer_account_id")

    return queryset.filter(
        Q(id__in=assigned_customer_ids) | Q(id__in=granted_customer_ids)
    ).distinct()


def accessible_customers(request, permission_codename="view_customeraccount"):
    from apps.access_control import sales_policy as policy
    from apps.access_control.catalog import SALES_APPS, module_for
    if not policy.enabled():
        return _legacy_accessible_customers(request, permission_codename)
    code = policy.canonical_permission(permission_codename)
    from apps.access_control import module_policy
    if code and module_policy.enabled() and module_for(code) in {'samples', 'workflow'}:
        if not module_policy.has_permission(request, code):
            return CustomerAccount.objects.none()
        access = policy.access_for(request)
        granted = set(access['actions'].get(code, {}).get('scopes', []))
        if access['is_superuser'] or granted & {'MODULE', 'ALL'}:
            return CustomerAccount.objects.all()
        _, owners = policy.allowed_owners(request, code)
        ids = policy.current_primary_assignments().filter(employee__in=owners).values('customer_account_id')
        allowed = Q(pk__in=ids)
        legacy = {row['permission'] for row in access['legacy_sources']}
        for old in {code, module_policy.LEGACY_ALIASES.get(code)} & legacy:
            allowed |= Q(pk__in=_legacy_accessible_customers(request, old.split('.', 1)[1]).values('pk'))
        return CustomerAccount.objects.filter(allowed).distinct()
    # Other non-sales callers retain their established module-specific contract.
    if code is None or module_for(code) not in SALES_APPS:
        return _legacy_accessible_customers(request, permission_codename)
    queryset = CustomerAccount.objects.all()
    access = policy.access_for(request)
    if not access["active"]:
        return queryset.none()
    all_owners, owners = policy.allowed_owners(request, code)
    if all_owners:
        return queryset
    now = timezone.now()
    current = Q(effective_from__lte=now) & (Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    assignments = CustomerAssignment.objects.filter(current)
    owned = assignments.filter(assignment_role="PRIMARY_OWNER", employee__in=owners).values("customer_account_id")
    allowed = Q(pk__in=owned)
    for legacy_codename in policy.legacy_scope_codenames(request, permission_codename):
        allowed |= Q(pk__in=_legacy_accessible_customers(request, legacy_codename).values("pk"))
    if policy.has_permission(request, code):
        employee = getattr(request, "employee", None)
        if code == "customers.view_customeraccount" and employee:
            allowed |= Q(pk__in=assignments.filter(employee=employee, assignment_role="COLLABORATOR").values("customer_account_id"))
        # Preserve explicit per-customer grants only for their exact operation.
        allowed |= Q(pk__in=CustomerDataAccessGrant.objects.filter(
            current, employee=employee, permission__content_type__app_label=code.split(".", 1)[0],
            permission__codename=code.split(".", 1)[1], revoked_at__isnull=True,
        ).values("customer_account_id"))
    return queryset.filter(allowed).distinct()


def customers_with_current_context(queryset, request=None):
    now = timezone.now()
    current_period = Q(effective_from__lte=now) & (Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    assignments = CustomerAssignment.objects.filter(current_period).select_related("employee")
    attention = CustomerAttentionReview.objects.filter(current_period).select_related("attention_level_item")
    grades = (
        CustomerGradeReview.objects.filter(current_period)
        .select_related("grade_item")
        .order_by("-effective_from", "-id")
    )
    current_sources = (
        CustomerSourceAttribution.objects.filter(current_period)
        .select_related("source_item")
        .order_by("-effective_from", "-id")
    )
    source_history = CustomerSourceAttribution.objects.select_related("source_item").order_by(
        "effective_from", "id"
    )[:1]
    customer_types = (
        CustomerTypeAssignment.objects.filter(current_period)
        .select_related("type_item")
        .order_by("type_item__sort_order", "type_item__item_code")
    )
    customer_tags = (
        CustomerTagAssignment.objects.filter(current_period)
        .select_related("customer_tag")
        .order_by("customer_tag__tag_name", "customer_tag__tag_code")
    )
    activity = CustomerActivityReview.objects.filter(current_period).order_by("-effective_from", "-id")
    business_snapshots = (
        CustomerBusinessSnapshot.objects.filter(is_current=True)
        .select_related("entered_by_employee")
        .order_by("-as_of_at", "-id")
    )
    from apps.crm.models import CustomerCommunication
    from apps.quotations.models import Quotation, QuotationOutcomeStatus
    from apps.sales_orders.models import SalesOrder, SalesOrderStatus
    from apps.workflow.models import TaskStatus

    # “近 12 个月”按日历年滚动；2 月 29 日回退到上一年的 2 月 28 日。
    today = timezone.localdate()
    try:
        twelve_months_ago = today.replace(year=today.year - 1)
    except ValueError:
        twelve_months_ago = today.replace(year=today.year - 1, day=28)

    effective_order_statuses = [
        SalesOrderStatus.CONFIRMED,
        SalesOrderStatus.FULFILLING,
        SalesOrderStatus.COMPLETED,
        SalesOrderStatus.PAUSED,
    ]
    effective_orders = SalesOrder.objects.filter(
        customer_account_id=OuterRef("pk"),
        archived_at__isnull=True,
        status__in=effective_order_statuses,
        order_date__lte=today,
    )
    if request is not None and sales_policy.enabled():
        from apps.sales_orders.selectors import accessible_sales_orders
        effective_orders = effective_orders.filter(pk__in=accessible_sales_orders(request).values("pk"))
    recent_order = effective_orders.annotate(
        summary=JSONObject(
            id=Cast("id", output_field=CharField()),
            order_number="order_number",
            order_date=Cast("order_date", output_field=CharField()),
            status="status",
            currency_code="currency_code",
            total_amount=Cast("total_amount", output_field=CharField()),
        )
    ).order_by("-order_date", "-created_at", "-id")
    order_amount_cny = ExpressionWrapper(
        F("total_amount") * F("exchange_rate"),
        output_field=DecimalField(max_digits=32, decimal_places=4),
    )
    rolling_sales = (
        effective_orders.filter(order_date__gte=twelve_months_ago)
        .order_by()
        .values("customer_account_id")
        .annotate(
            amount_cny=Sum(order_amount_cny),
            order_count=Count("id"),
        )
        .annotate(
            summary=JSONObject(
                amount=Cast("amount_cny", output_field=CharField()),
                order_count="order_count",
            )
        )
    )
    lifetime_sales = (
        effective_orders.order_by()
        .values("customer_account_id")
        .annotate(
            amount_cny=Sum(order_amount_cny),
            order_count=Count("id"),
        )
        .annotate(
            summary=JSONObject(
                amount=Cast("amount_cny", output_field=CharField()),
                order_count="order_count",
            )
        )
    )
    visible_quotes = Quotation.objects.all()
    if request is not None and sales_policy.enabled():
        visible_quotes = visible_quotes.filter(customer_account__in=accessible_customers(request, "view_quotation"))
    quotation_conversion = (
        visible_quotes.filter(
            customer_account_id=OuterRef("pk"),
            archived_at__isnull=True,
        )
        .exclude(outcome_status=QuotationOutcomeStatus.CANCELLED)
        .order_by()
        .values("customer_account_id")
        .annotate(
            quotation_count=Count("id"),
            accepted_count=Count("id", filter=Q(outcome_status=QuotationOutcomeStatus.WON)),
        )
        .annotate(
            summary=JSONObject(
                quotation_count="quotation_count",
                accepted_count="accepted_count",
            )
        )
    )

    latest_contact = CustomerCommunication.objects.filter(
        customer_account_id=OuterRef("pk"),
        archived_at__isnull=True,
    ).order_by("-occurred_at", "-id")
    if request is not None and sales_policy.enabled():
        latest_contact = latest_contact.filter(customer_account__in=accessible_customers(request, "view_customercommunication"))
    next_follow_up = CustomerTaskLink.objects.filter(
        customer_account_id=OuterRef("pk"),
        business_task__archived_at__isnull=True,
        business_task__status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
        business_task__due_at__isnull=False,
    ).order_by("business_task__due_at", "business_task__id")
    if request is not None and sales_policy.enabled():
        from apps.workflow.selectors import accessible_tasks
        next_follow_up = next_follow_up.filter(business_task__in=accessible_tasks(request, scope="ANY_ACCESS"))
        if not sales_policy.has_permission(request, "workflow.view_businesstask"):
            next_follow_up = next_follow_up.none()
    interested_products = CustomerInterestedProduct.objects.select_related("product_item").order_by(
        "product_item__sort_order", "product_item__item_code"
    )
    company_contact_methods = CustomerCompanyContactMethod.objects.filter(
        archived_at__isnull=True
    ).order_by("-is_primary", "method_type", "id")
    return queryset.select_related(
        "primary_region",
        "secondary_region",
        "industry_item",
        "recorded_by_employee",
    ).annotate(
        last_contact_at=Subquery(
            latest_contact.values("occurred_at")[:1], output_field=DateTimeField()
        ),
        next_follow_up_at=Subquery(
            next_follow_up.values("business_task__due_at")[:1], output_field=DateTimeField()
        ),
        last_12m_sales_summary=Subquery(
            rolling_sales.values("summary")[:1], output_field=JSONField()
        ),
        lifetime_sales_summary=Subquery(
            lifetime_sales.values("summary")[:1], output_field=JSONField()
        ),
        quotation_conversion_summary=Subquery(
            quotation_conversion.values("summary")[:1], output_field=JSONField()
        ),
        recent_order_summary=Subquery(
            recent_order.values("summary")[:1], output_field=JSONField()
        ),
    ).prefetch_related(
        Prefetch("assignments", queryset=assignments, to_attr="current_assignments"),
        Prefetch("attention_reviews", queryset=attention, to_attr="current_attention_reviews"),
        Prefetch("grade_reviews", queryset=grades, to_attr="current_grade_reviews"),
        Prefetch("source_attributions", queryset=current_sources, to_attr="current_source_attributions"),
        Prefetch("source_attributions", queryset=source_history, to_attr="source_history"),
        Prefetch("type_assignments", queryset=customer_types, to_attr="current_type_assignments"),
        Prefetch("tag_assignments", queryset=customer_tags, to_attr="current_tag_assignments"),
        Prefetch("activity_reviews", queryset=activity, to_attr="current_activity_reviews"),
        Prefetch("business_snapshots", queryset=business_snapshots, to_attr="current_business_snapshots"),
        Prefetch("interested_products", queryset=interested_products),
        Prefetch("company_contact_methods", queryset=company_contact_methods),
    )
