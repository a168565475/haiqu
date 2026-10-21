"""新管材外发单的真实预留；不受入口开关影响，不读取采购批次。"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Q, Sum


def tube_raw_reserved_quantities(product_components, *, exclude_order_id=None):
    """按订单产品和稳定部位一次汇总待发原料支数。"""
    from apps.outsourcing.models import TubeOutsourcingLine

    targets = {(str(product), str(component)) for product, component in product_components
               if product and component}
    if not targets:
        return {}
    scope = Q(pk__in=[])
    for product, component in targets:
        scope |= Q(order__product_line_id=product, component_identity=component)
    rows = TubeOutsourcingLine.objects.filter(
        scope, order__status="PENDING_DISPATCH", order__source_kind="RAW_PIPE",
    )
    if exclude_order_id:
        rows = rows.exclude(order_id=exclude_order_id)
    rows = rows.values("order__product_line_id", "component_identity").annotate(total=Sum("quantity"))
    return {(str(row["order__product_line_id"]), str(row["component_identity"])): Decimal(row["total"])
            for row in rows}


def tube_public_reserved_quantities(identities, *, zone_id=None, exclude_order_id=None):
    """一次汇总各公共物料、单位和库区的待发实物量（根或支）。"""
    from apps.outsourcing.models import TubeOutsourcingLine

    pools = {(value["stock_kind"], str(value["identity_key"]), str(value["unit_id"]))
             for value in identities}
    if not pools:
        return {}
    scope = Q(pk__in=[])
    for kind, key, unit in pools:
        scope |= Q(input_identity__stock_kind=kind, input_identity__identity_key=key,
                   input_identity__unit_id=unit)
    rows = TubeOutsourcingLine.objects.filter(
        scope, order__status="PENDING_DISPATCH", order__source_kind__in=["RAW_PIPE", "PUBLIC_SEMI", "PUBLIC_CUTTING"],
    )
    if exclude_order_id:
        rows = rows.exclude(order_id=exclude_order_id)
    if zone_id is not None:
        rows = rows.filter(order__zone_id=zone_id)
    rows = rows.values("input_identity__stock_kind", "input_identity__identity_key",
                       "input_identity__unit_id", "order__zone_id").annotate(total=Sum("stock_quantity"))
    reserved = defaultdict(Decimal)
    for row in rows:
        pool = (row["input_identity__stock_kind"], str(row["input_identity__identity_key"]),
                str(row["input_identity__unit_id"]))
        reserved[(pool, str(row["order__zone_id"]))] += Decimal(row["total"] or 0)
    return reserved


def reserved_quantity_for_balance(balance):
    pool = (balance.stock_kind, balance.identity_key, str(balance.unit_id))
    reserved = tube_public_reserved_quantities([
        {"stock_kind": pool[0], "identity_key": pool[1], "unit_id": pool[2]},
    ], zone_id=balance.zone_id)
    return reserved.get((pool, str(balance.zone_id)), Decimal(0))


def tube_material_reserved_quantities(*, requirement_ids=(), raw_material_ids=(), exclude_order_id=None):
    """附带五金同时占用订单额度及普通原料库区；与管材预留共用主单状态。"""
    from apps.outsourcing.models import TubeOutsourcingMaterial

    rows = TubeOutsourcingMaterial.objects.filter(order__status='PENDING_DISPATCH')
    if exclude_order_id:
        rows = rows.exclude(order_id=exclude_order_id)
    by_requirement = {row['requirement_id']: row['total'] for row in rows.filter(
        requirement_id__in=requirement_ids).values('requirement_id').annotate(total=Sum('quantity'))}
    by_zone = {(str(row['raw_material_id']), str(row['unit_id']), str(row['zone_id'])): row['total']
        for row in rows.filter(raw_material_id__in=raw_material_ids)
        .values('raw_material_id', 'unit_id', 'zone_id').annotate(total=Sum('quantity'))}
    return by_requirement, by_zone
