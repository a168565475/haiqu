from django.db.models import Prefetch, Q

from apps.production_tasks.selectors import accessible_production_tasks

from .models import MaterialIssue, MaterialIssuePublicStockAllocation


def accessible_material_issues(request):
    queryset = MaterialIssue.objects.all()
    if request.user.is_superuser or request.user.has_perm("material_issues.view_all_materialissue"):
        return queryset
    task_ids = accessible_production_tasks(request).values("id")
    return queryset.filter(
        Q(production_task_id__in=task_ids)
        | Q(production_task__isnull=True, created_by_employee=request.employee)
    )


def material_issues_with_context(queryset=None):
    if queryset is None:
        queryset = MaterialIssue.objects.all()
    return queryset.select_related(
        "production_task",
        "production_task__customer_account",
        "product_line",
        "product_line__image_file",
        "product_line__unit",
        "workshop",
        "recipient_workshop_employee",
        "created_by_employee",
        "updated_by_employee",
        "submitted_by_employee",
        "issued_by_employee",
    ).prefetch_related(
        "lines__requirement",
        "lines__batch_allocations",
        # 已出库明细只读冻结扣量；避免默认外键排序联查当前库存及库区。
        Prefetch("lines__public_stock_allocations", queryset=MaterialIssuePublicStockAllocation.objects.order_by("line_id", "created_at", "id")),
        "lines__semi_requirement__bom_line",
        "lines__semi_requirement__completed_craft",
        "lines__semi_requirement__unit",
        "lines__raw_material__category",
        "lines__raw_material__color",
        "lines__semi_finished_balance__bom_line",
        "lines__semi_finished_balance__completed_craft",
        "lines__semi_finished_balance__zone__warehouse",
        "lines__unit",
        "audit_events__actor_employee",
    )


def search_material_issues(queryset, keyword):
    if not keyword:
        return queryset
    return queryset.filter(
        Q(issue_number__icontains=keyword)
        | Q(production_task__task_number__icontains=keyword)
        | Q(production_task__order_number__icontains=keyword)
        | Q(product_line__product_name_snapshot__icontains=keyword)
        | Q(recipient_workshop_employee__name__icontains=keyword)
    ).distinct()
