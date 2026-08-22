from apps.customers.selectors import accessible_customers

from .models import Quotation, QuotationVersion


def accessible_quotations(request, permission_codename):
    return Quotation.objects.filter(
        customer_account__in=accessible_customers(request, permission_codename)
    )


def quotations_with_context(queryset=None):
    if queryset is None:
        queryset = Quotation.objects.all()
    return queryset.select_related(
        "customer_account",
        "transaction_entity",
        "source_inquiry",
        "owner_employee",
        "accepted_version",
    ).prefetch_related("versions")


def versions_with_context(queryset=None):
    if queryset is None:
        queryset = QuotationVersion.objects.all()
    return queryset.select_related(
        "quotation",
        "quotation__customer_account",
        "quotation__transaction_entity",
        "quotation__owner_employee",
        "quotation_template",
        "locked_by_employee",
    ).prefetch_related(
        "lines__quantity_tiers",
        "documents__business_file",
        "dispatch_records__dispatched_by_employee",
        "approval_links__approval_request__current_approver_employee",
        "approval_links__approval_request__requested_by_employee",
        "task_links__business_task",
        "sla_links__sla_tracking__sla_policy",
    )
