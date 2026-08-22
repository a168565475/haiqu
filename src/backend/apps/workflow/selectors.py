from django.db.models import Q

from .models import ApprovalRequest, BusinessTask, SlaTracking


def accessible_tasks(request):
    queryset = BusinessTask.objects.all()
    if request.user.is_superuser:
        return queryset
    employee = getattr(request, "employee", None)
    if employee is None:
        return queryset.none()
    return queryset.filter(
        Q(assignee_employee=employee) | Q(created_by_employee=employee)
    ).distinct()


def tasks_with_context(queryset=None):
    if queryset is None:
        queryset = BusinessTask.objects.all()
    return queryset.select_related(
        "assignee_employee",
        "created_by_employee",
    ).prefetch_related(
        "customer_links",
        "communication_links",
        "inquiry_links",
        "quotation_links",
        "sample_links",
    )


def accessible_approvals(request):
    queryset = ApprovalRequest.objects.all()
    if request.user.is_superuser:
        return queryset
    employee = getattr(request, "employee", None)
    if employee is None:
        return queryset.none()
    return queryset.filter(
        Q(current_approver_employee=employee) | Q(requested_by_employee=employee)
    ).distinct()


def approvals_with_context(queryset=None):
    if queryset is None:
        queryset = ApprovalRequest.objects.all()
    return queryset.select_related(
        "current_approver_employee",
        "requested_by_employee",
        "quotation_link__quotation_version",
        "quotation_link__quotation_version__quotation",
        "quotation_link__quotation_version__quotation__customer_account",
    )


def accessible_sla_trackings(request):
    from apps.customers.selectors import accessible_customers

    customers = accessible_customers(request, "view_slatracking")
    return SlaTracking.objects.filter(
        Q(inquiry_link__inquiry__customer_account__in=customers)
        | Q(quotation_link__quotation_version__quotation__customer_account__in=customers)
        | Q(sample_link__sample_request__customer_account__in=customers)
    ).distinct()


def sla_trackings_with_context(queryset=None):
    if queryset is None:
        queryset = SlaTracking.objects.all()
    return queryset.select_related(
        "sla_policy",
        "inquiry_link__inquiry",
        "quotation_link__quotation_version",
        "sample_link__sample_request",
    )
