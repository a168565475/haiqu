from django.db.models import Count, OuterRef, Prefetch, Q, Subquery

from apps.production_tasks.selectors import accessible_production_tasks

from .models import Bom, BomSection


def accessible_boms(request):
    queryset = Bom.objects.filter(archived_at__isnull=True)
    if request.user.is_superuser or request.user.has_perm("boms.view_all_bom"):
        return queryset
    accessible_task_ids = accessible_production_tasks(request).values("id")
    return queryset.filter(production_task_id__in=accessible_task_ids)


def boms_with_context(queryset=None, *, include_lines=False, read_optimized=False):
    if queryset is None:
        queryset = Bom.objects.all()
    latest_active_bom = (
        Bom.objects.filter(
            product_line_id=OuterRef("product_line_id"),
            archived_at__isnull=True,
        )
        .order_by("-version_number", "-id")
        .values("id")[:1]
    )
    related = [
        "production_task",
        "production_task__customer_account",
        "production_task__sales_order",
        "product_line",
        "product_line__unit",
        "created_by_employee",
        "updated_by_employee",
        "confirmed_by_employee",
    ]
    # 读取接口只加载序列化真正使用的关联，避免无用 JOIN 增加规划时间。
    if not read_optimized:
        related.extend(["product_line__product", "product_line__product__category", "source_file"])
    if not read_optimized or include_lines:
        related.append("copied_from")
    queryset = queryset.annotate(
        latest_active_bom_id=Subquery(latest_active_bom),
    ).select_related(*related).prefetch_related(
        "production_task__delivery_batches",
        Prefetch(
            "sections",
            queryset=BomSection.objects.annotate(prefetched_line_count=Count("lines")).order_by(
                "bom_id",
                "line_number",
                "id",
            ),
        ),
    )
    if include_lines:
        queryset = queryset.prefetch_related("sections__lines__images__business_file")
    return queryset


def search_boms(queryset, search_text):
    if not search_text:
        return queryset
    return queryset.filter(
        Q(bom_number__icontains=search_text)
        | Q(production_task__task_number__icontains=search_text)
        | Q(production_task__order_number__icontains=search_text)
        | Q(product_code_snapshot__icontains=search_text)
        | Q(product_name_snapshot__icontains=search_text)
    )
