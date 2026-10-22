from decimal import Decimal

from django.db.models import Case, CharField, Exists, OuterRef, Prefetch, Q, Sum, Value, When

from apps.customers.selectors import accessible_customers
from apps.files.models import USABLE_FILE_SCAN_STATUSES

from .models import ProductionTask, ProductionTaskProduct, ProductionTaskStatus


def production_task_source_image_ids(task, *, product_ids=None):
    products = ProductionTaskProduct.objects.filter(
        production_task=task,
        sales_order_delivery_batch_line__delivery_batch_id=task.sales_order_delivery_batch_id,
        sales_order_delivery_batch_line__sales_order_line__sales_order_id=task.sales_order_id,
    )
    if product_ids is not None:
        products = products.filter(pk__in=product_ids)
    return products.values("sales_order_delivery_batch_line__sales_order_line__product_image_id")


def production_task_product_image(line):
    def usable(image):
        return image is not None and image.archived_at is None and image.scan_status in USABLE_FILE_SCAN_STATUSES

    if usable(line.image_file):
        return line.image_file
    for item in line.images.all():
        if usable(item.image_file):
            return item.image_file
    if not line.sales_order_delivery_batch_line_id:
        return None
    source = line.sales_order_delivery_batch_line
    task = line.production_task
    if (source.delivery_batch_id != task.sales_order_delivery_batch_id
            or source.sales_order_line.sales_order_id != task.sales_order_id):
        return None
    image = source.sales_order_line.product_image
    return image if usable(image) else None


def external_business_relations(model):
    """仅检查反向业务外键；本模块子记录由删除服务显式处理。"""
    return [relation for relation in model._meta.related_objects
            if relation.related_model._meta.app_label != "production_tasks"
            and not relation.many_to_many]


def external_business_blocker(instance):
    for relation in external_business_relations(type(instance)):
        if relation.related_model._base_manager.filter(**{relation.field.name: instance.pk}).exists():
            return business_relation_message(relation)
    return ""


def business_relation_message(relation):
    module = {"boms": "BOM", "production_scheduling": "排产", "procurement": "采购",
              "inventory": "库存", "material_issues": "领料", "outsourcing": "外协",
              "workshop_reporting": "工价或报工"}.get(
                  relation.related_model._meta.app_label, str(relation.related_model._meta.verbose_name))
    return f"已关联{module}记录，不能删除。"


def production_quantity_source(line):
    if line.sales_order_delivery_batch_line_id:
        return line.sales_order_delivery_batch_line
    task = line.production_task
    if task.sales_order_id and task.sales_order_delivery_batch_id and task.sales_order_line_id:
        from apps.sales_orders.models import SalesOrderDeliveryBatchLine
        return SalesOrderDeliveryBatchLine.objects.filter(
            delivery_batch_id=task.sales_order_delivery_batch_id,
            sales_order_line_id=task.sales_order_line_id,
        ).first()
    return None


def max_production_quantity(line):
    source = production_quantity_source(line)
    if source is None:
        return None
    # 兼容旧任务只在任务头记录销售行的占用，仍按名义数量计算，不加误差。
    allocated = ProductionTaskProduct.objects.filter(
        Q(sales_order_delivery_batch_line_id=source.pk)
        | Q(sales_order_delivery_batch_line__isnull=True,
            production_task__sales_order_delivery_batch_id=source.delivery_batch_id,
            production_task__sales_order_line_id=source.sales_order_line_id),
    ).exclude(production_task_id=line.production_task_id).exclude(
        production_task__status=ProductionTaskStatus.CANCELLED,
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    return max(0, int(Decimal(source.quantity) - allocated))


def production_sales_order_sources(request):
    """生产建单、来源读取和来源图片共用同一数据权限边界。"""
    from apps.access_control import module_policy
    from apps.sales_orders.models import SalesOrder, SalesOrderStatus
    from apps.sales_orders.selectors import accessible_sales_orders

    can_select_sources = (
        module_policy.has_module_grant(request, "production_tasks")
        if module_policy.enabled()
        else request.user.has_perm("production_tasks.add_productiontask")
    )
    if can_select_sources:
        queryset = SalesOrder.objects.all()
    else:
        queryset = accessible_sales_orders(request)
    return queryset.filter(
        archived_at__isnull=True, customer_account__archived_at__isnull=True,
        status__in=[SalesOrderStatus.CONFIRMED, SalesOrderStatus.FULFILLING],
    )


def accessible_production_tasks(request):
    queryset = ProductionTask.objects.all()
    from apps.access_control import module_policy
    view = (getattr(request, 'parser_context', None) or {}).get('view')
    permission = module_policy.action_permission(request, view) if view is not None else None
    direct = type(view).__name__ == 'ProductionTaskViewSet'
    modules = ('production_tasks',) if direct else (
        'production_tasks', 'production_scheduling', 'boms', 'procurement', 'inventory',
        'material_issues', 'outsourcing', 'workshop_reporting')
    if view is not None and not direct:
        if isinstance(permission, str):
            from apps.access_control.catalog import module_for
            modules = (module_for(permission),)
    if module_policy.enabled() and module_policy.has_module_grant(request, *modules):
        return queryset
    if request.user.is_superuser or request.user.has_perm("production_tasks.view_all_productiontask"):
        return queryset
    from apps.access_control import resource_scopes
    if not direct and (resource_scopes.enabled() or isinstance(permission, str) and resource_scopes.enforcing(request, permission)):
        from apps.access_control.sales_policy import access_for
        access = access_for(request)
        ids = {pk for code, entry in access['actions'].items()
               if (code == permission if isinstance(permission, str) else code.startswith(('production_scheduling.', 'material_issues.', 'workshop_reporting.')))
               for source in entry.get('sources', []) if source.get('scope') == 'WORKSHOP'
               for pk in source.get('resource_ids', [])}
        if isinstance(permission, str) and 'WORKSHOP' in access['actions'].get(permission, {}).get('scopes', []) and not ids and not resource_scopes.has_legacy_permission(request, permission):
            return queryset.none()
        if ids:
            return queryset.filter(production_schedules__record_status='ACTIVE',
                production_schedules__products__removed_at__isnull=True,
                production_schedules__products__crafts__removed_at__isnull=True,
                production_schedules__products__crafts__craft__workshop_id__in=ids).distinct()
    return legacy_accessible_production_tasks(request)


def legacy_accessible_production_tasks(request):
    """旧直授/原生组只沿用原归属；不借其他角色的模块/车间读取放宽。"""
    queryset = ProductionTask.objects.all()
    if request.user.is_superuser or request.user.has_perm('production_tasks.view_all_productiontask'):
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
    blockers = [When(
        Exists(relation.related_model._base_manager.filter(**{relation.field.name: OuterRef("pk")})),
        then=Value(business_relation_message(relation)),
    ) for relation in external_business_relations(ProductionTaskProduct)]
    product_queryset = ProductionTaskProduct.objects.annotate(
        _deletion_blocked_reason=Case(*blockers, default=Value(""), output_field=CharField()),
    )
    prefetched = [
        Prefetch("products", queryset=product_queryset),
        "followers",
        "products__product",
        "products__unit",
        "products__currency",
        "products__product_color",
        "products__sales_order_delivery_batch_line__sales_order_line__source_quotation_line__source_inquiry_item",
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
    from apps.procurement.selectors import active_purchase_orders, purchase_orders_with_product_ids

    return queryset.prefetch_related(
        Prefetch(
            "purchase_orders",
            queryset=purchase_orders_with_product_ids(active_purchase_orders()),
            to_attr="_active_purchase_orders_for_status",
        ),
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
