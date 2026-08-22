from apps.customers.selectors import accessible_customers

from .models import SampleRequest, SampleShipment


def accessible_sample_requests(request, permission_codename):
    return SampleRequest.objects.filter(
        customer_account__in=accessible_customers(request, permission_codename)
    )


def sample_requests_with_context(queryset=None):
    if queryset is None:
        queryset = SampleRequest.objects.all()
    return queryset.select_related(
        "customer_account",
        "transaction_entity",
        "customer_contact",
        "owner_employee",
        "source_inquiry",
        "source_quotation_version__quotation",
    ).prefetch_related(
        "items",
        "fee_records__decided_by_employee",
        "shipments__items__sample_item",
        "shipments__shipped_by_employee",
        "feedback_records__customer_contact",
        "feedback_records__recorded_by_employee",
        "file_links__business_file",
        "sla_links__sla_tracking__sla_policy",
        "task_links__business_task",
    )


def shipments_with_context(queryset=None):
    if queryset is None:
        queryset = SampleShipment.objects.all()
    return queryset.select_related(
        "sample_request",
        "sample_request__customer_account",
        "shipped_by_employee",
        "fee_warning_acknowledged_by_employee",
    ).prefetch_related("items__sample_item")
