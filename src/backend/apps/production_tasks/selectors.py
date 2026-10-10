from django.db.models import Prefetch, Q

from apps.customers.selectors import accessible_customers

from .models import ProductionTask


def accessible_production_tasks(request):
    queryset = ProductionTask.objects.all()
    from apps.access_control import module_policy
    if module_policy.enabled() and module_policy.has_module_grant(request,
            'production_tasks', 'production_scheduling', 'boms', 'procurement', 'inventory',
            'material_issues', 'outsourcing', 'workshop_reporting'):
        return queryset
    if request.user.is_superuser or request.user.has_perm("production_tasks.view_all_productiontask"):
        return queryset
    employee = getattr(request, "employee", None)
    if employee is None:
        return queryset.none()
    customer_ids = accessible_customers(request).values("id")
    return queryset.filter(
        Q(customer_account_id__in=customer_ids)
        | Q(salesperson=employee)
        | Q(followers=employee)
        | Q(created_by_employee=employee)
    ).distinct()


def production_tasks_with_context(queryset=None, *, include_progress=False, list_mode=False):
    if queryset is None:
        queryset = ProductionTask.objects.all()
    related = [
        "customer_account",
        "salesperson",
        "currency",
        "sales_order",
        "sales_order_delivery_batch",
    ]
    if not list_mode:
        related.extend([
            "created_by_employee", "sales_order_line", "sales_order__source_quotation_version",
            "planner", "accepted_by_employee", "start_waiver_by_employee",
        ])
    prefetched = [
        "followers",
        "products__product",
        "products__unit",
        "products__currency",
        "products__product_color",
        "products__sales_order_delivery_batch_line__sales_order_line",
        "products__image_file",
        "products__images__image_file",
        "products__details__image_file",
        "delivery_batches",
    ]
    if not list_mode:
        prefetched.append("run_batches")
    queryset = queryset.select_related(*related).prefetch_related(*prefetched)
    if not include_progress:
        return queryset

    from apps.boms.models import Bom
    from apps.procurement.models import PurchaseRequest

    return queryset.select_related("purchase_order").prefetch_related(
        Prefetch(
            "boms",
            queryset=Bom.objects.filter(archived_at__isnull=True).order_by(
                "product_line_id", "-version_number", "-created_at", "-id"
            ),
            to_attr="_active_boms_for_status",
        ),
        Prefetch(
            "purchase_requests",
            queryset=PurchaseRequest.objects.filter(archived_at__isnull=True).order_by(
                "-created_at", "-id"
            ),
            to_attr="_active_purchase_requests_for_status",
        ),
    )
