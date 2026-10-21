from django.db.models import Prefetch

from apps.production_scheduling.selectors import accessible_production_schedules

from .models import (
    OutsourcingFactory,
    OutsourcingFactoryAllocation,
    OutsourcingFactoryCraft,
    OutsourcingDispatchLine,
    OutsourcingMaterialItem,
    OutsourcingOrder,
    OutsourcingOrderProduct,
    OutsourcingProcessingItem,
    OutsourcingReturn,
    OutsourcingReturnLine,
)


def factories_with_context(queryset=None):
    queryset = queryset if queryset is not None else OutsourcingFactory.objects.all()
    return queryset.prefetch_related(
        Prefetch(
            "craft_links",
            queryset=OutsourcingFactoryCraft.objects.select_related("craft").order_by("craft_name_snapshot", "id"),
            to_attr="prefetched_craft_links",
        )
    ).select_related("created_by_employee", "updated_by_employee")


def accessible_outsourcing_orders(request, permission=None):
    from apps.access_control.resource_scopes import current_permission, filter_crafts, has_resource_grant, craft_access_union
    permission = permission or current_permission(request, 'outsourcing.view_outsourcingorder')
    queryset = OutsourcingOrder.objects.all()
    legacy_queryset = queryset.filter(schedule_id__in=accessible_production_schedules(request).values('id'))
    from .source_access import scoped_regular_orders
    from apps.access_control.resource_scopes import enforcing
    if enforcing(request, permission):
        return scoped_regular_orders(queryset, request, permission, legacy_queryset)
    if has_resource_grant(request, permission, 'CRAFT'):
        return craft_access_union(queryset, legacy_queryset, request, permission)
    return filter_crafts(legacy_queryset, request, permission)


def outsourcing_source_schedules(request, permission=None, craft_id=None):
    """Local source summaries for this operation; never grants the production API."""
    from apps.access_control.resource_scopes import current_permission, filter_crafts, has_resource_grant, has_legacy_permission
    from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProductCraft
    permission = permission or current_permission(request, 'outsourcing.view_outsourcingorder')
    from .source_access import source_grants
    from apps.access_control.resource_scopes import enabled
    if enabled() and any(source.get('scope') in {'MODULE', 'STOCK', 'WORKSHOP'}
                         for source in source_grants(request, permission)):
        sources = source_grants(request, permission)
        if any(source.get('scope') in {'MODULE', 'STOCK'} for source in sources):
            return ProductionSchedule.objects.all()
        ids = {pk for source in sources if source.get('scope') == 'WORKSHOP' for pk in source.get('resource_ids', [])}
        return ProductionSchedule.objects.filter(products__removed_at__isnull=True,
            products__crafts__removed_at__isnull=True, products__crafts__craft__workshop_id__in=ids).distinct()
    if not has_resource_grant(request, permission, 'CRAFT'):
        return accessible_production_schedules(request)
    links = filter_crafts(ProductionScheduleProductCraft.objects.filter(
        removed_at__isnull=True, schedule_product__removed_at__isnull=True), request, permission, include_legacy=False)
    if craft_id is not None:
        links = links.filter(craft_id=craft_id)
    queryset = ProductionSchedule.objects.filter(pk__in=links.values('schedule_product__schedule_id'))
    if has_legacy_permission(request, permission):
        queryset = queryset.distinct() | accessible_production_schedules(request).distinct()
    return queryset.distinct()


def orders_with_context(queryset=None, *, include_detail_records=False):
    queryset = queryset if queryset is not None else OutsourcingOrder.objects.all()
    material_items = OutsourcingMaterialItem.objects.select_related("bom_material_line").order_by("line_number", "id")
    allocation_prefetches = [
        Prefetch("material_items", queryset=material_items, to_attr="prefetched_material_items")
    ]
    if include_detail_records:
        allocation_prefetches.append(Prefetch(
            "return_lines",
            queryset=OutsourcingReturnLine.objects.order_by("id"),
            to_attr="prefetched_return_lines",
        ))
    allocations = OutsourcingFactoryAllocation.objects.select_related("factory").prefetch_related(
        *allocation_prefetches
    ).order_by("factory__name", "id")
    processing_items = OutsourcingProcessingItem.objects.select_related(
        "bom_line", "bom_line__section", "unit",
    ).prefetch_related(
        Prefetch("allocations", queryset=allocations, to_attr="prefetched_allocations")
    ).order_by("line_number", "id")
    products = OutsourcingOrderProduct.objects.select_related(
        "schedule_product", "bom", "schedule_product__image_file"
    ).prefetch_related(
        Prefetch("processing_items", queryset=processing_items, to_attr="prefetched_processing_items")
    ).order_by("line_number", "id")
    queryset = queryset.select_related(
        "schedule", "schedule__production_task", "schedule__production_task__customer_account",
        "craft", "created_by_employee", "updated_by_employee",
    ).prefetch_related(
        Prefetch("products", queryset=products, to_attr="prefetched_products"),
    )
    if not include_detail_records:
        return queryset
    return_lines = OutsourcingReturnLine.objects.select_related(
        "allocation__processing_item__unit",
        "public_stock_movement",
    ).order_by("id")
    return_records = OutsourcingReturn.objects.select_related(
        "factory", "zone", "defective_zone", "received_by_employee", "confirmed_by_employee"
    ).prefetch_related(
        Prefetch("lines", queryset=return_lines, to_attr="prefetched_lines")
    ).order_by("confirmed_at", "id")
    dispatch_lines = OutsourcingDispatchLine.objects.select_related("unit").order_by("id")
    return queryset.select_related(
        "dispatch_record", "dispatch_record__confirmed_by_employee",
    ).prefetch_related(
        Prefetch("return_records", queryset=return_records, to_attr="prefetched_return_records"),
        Prefetch("dispatch_record__lines", queryset=dispatch_lines, to_attr="prefetched_lines"),
    )
