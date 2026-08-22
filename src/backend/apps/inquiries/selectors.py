from apps.customers.selectors import accessible_customers

from .models import Inquiry


def accessible_inquiries(request, permission_codename):
    return Inquiry.objects.filter(
        customer_account__in=accessible_customers(request, permission_codename)
    )


def inquiries_with_context(queryset=None):
    if queryset is None:
        queryset = Inquiry.objects.all()
    return queryset.select_related(
        "customer_account",
        "transaction_entity",
        "customer_contact",
        "owner_employee",
    ).prefetch_related(
        "items",
        "file_links__business_file",
        "task_links__business_task__assignee_employee",
        "task_links__business_task__created_by_employee",
        "sla_links__sla_tracking__sla_policy",
    )
