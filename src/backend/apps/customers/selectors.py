from django.db.models import Prefetch, Q
from django.utils import timezone

from .models import CustomerAccount, CustomerAssignment, CustomerAttentionReview, CustomerDataAccessGrant


def accessible_customers(request, permission_codename="view_customeraccount"):
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


def customers_with_current_context(queryset):
    now = timezone.now()
    current_period = Q(effective_from__lte=now) & (Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    assignments = CustomerAssignment.objects.filter(current_period).select_related("employee")
    attention = CustomerAttentionReview.objects.filter(current_period).select_related("attention_level_item")
    return queryset.prefetch_related(
        Prefetch("assignments", queryset=assignments, to_attr="current_assignments"),
        Prefetch("attention_reviews", queryset=attention, to_attr="current_attention_reviews"),
    )
