from decimal import Decimal

from django.db.models import Prefetch, Q, Sum
from django.db.models.functions import Coalesce

from apps.customers.selectors import accessible_customers

from .models import (
    CollaborationEventStatus, CollaborationEventType, DeliveryBatchStatus,
    SalesOrder, SalesOrderDeliveryBatchLine, SalesOrderLine, SalesOrderStatus,
)


def sales_order_completion_progress(order):
    active_demand = SalesOrderDeliveryBatchLine.objects.filter(
        delivery_batch__sales_order=order,
        delivery_batch__status=DeliveryBatchStatus.ACTIVE,
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    shipped = order.collaboration_events.filter(
        event_type=CollaborationEventType.SHIPMENT,
        status=CollaborationEventStatus.COMPLETED,
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    balance_completed = order.collaboration_events.filter(
        event_type=CollaborationEventType.BALANCE,
        status=CollaborationEventStatus.COMPLETED,
    ).exists()
    blockers = []
    if shipped < active_demand:
        blockers.append(f"累计发货 {shipped}，有效交付需求 {active_demand}")
    if not balance_completed:
        blockers.append("余款尚未登记完成")
    return {"active_demand": active_demand, "shipped_quantity": shipped, "blockers": blockers}


def accessible_sales_orders(request, permission="sales_orders.view_salesorder"):
    from apps.access_control import sales_policy as policy
    queryset = SalesOrder.objects.all()
    employee = getattr(request, "employee", None)
    if policy.enabled():
        if not policy.access_for(request)["active"]:
            return queryset.none()
        allowed = Q(customer_account__in=accessible_customers(request, permission))
        if employee and "OWN" in policy.scopes(request, permission):
            # Assignment never supplies an action grant. Read or write must be
            # granted separately for the assigned order; no customer-wide access.
            allowed |= Q(merchandiser=employee)
        if policy.legacy_permission(request, permission):
            allowed |= Q(salesperson=employee) | Q(merchandiser=employee) | Q(created_by_employee=employee)
        return queryset.filter(allowed).distinct()
    if request.user.is_superuser:
        return queryset
    if employee is None:
        return queryset.none()
    customer_ids = accessible_customers(request).values("id")
    return queryset.filter(
        Q(customer_account_id__in=customer_ids)
        | Q(salesperson=employee)
        | Q(merchandiser=employee)
        | Q(created_by_employee=employee)
    ).distinct()


def sales_orders_with_context(queryset=None):
    queryset = queryset if queryset is not None else SalesOrder.objects.all()
    return queryset.select_related(
        "customer_account",
        "transaction_entity",
        "buyer_address",
        "salesperson",
        "merchandiser",
        "source_quotation_version",
        "source_quotation_version__quotation",
        "confirmed_by_employee",
        "created_by_employee",
    ).prefetch_related(
        "lines__product",
        "lines__product_color",
        "lines__source_quotation_line",
        "lines__price_exceptions__requested_by_employee",
        "lines__price_exceptions__decided_by_employee",
        "delivery_batches__lines__sales_order_line",
        "delivery_batches__lines__production_task_products__production_task",
        "delivery_batches__production_tasks",
        "delivery_batches__production_tasks__products",
        "production_tasks",
        "evidence_links__business_file",
        "collaboration_events__recorded_by_employee",
        "collaboration_events__evidence_file",
        "versions",
    )


def quoted_line_reserved_quantity(quotation_line_id, *, exclude_order_id=None):
    queryset = SalesOrderLine.objects.filter(
        source_quotation_line_id=quotation_line_id,
    ).exclude(sales_order__status=SalesOrderStatus.CANCELLED)
    if exclude_order_id:
        queryset = queryset.exclude(sales_order_id=exclude_order_id)
    return queryset.aggregate(total=Coalesce(Sum("quantity"), 0))["total"]
