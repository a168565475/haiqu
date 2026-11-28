"""仓库材料台账从实际库存流水取数，原单用于范围、日期与追溯。"""
from dataclasses import dataclass

from django.db.models import Case, CharField, DateField, Exists, F, OuterRef, Q, QuerySet, Subquery, Sum, Value, When
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast, Coalesce, NullIf, TruncDate

from apps.access_control.module_policy import has_permission
from apps.material_issues.selectors import accessible_material_issues
from apps.outsourcing.models import OutsourcingDispatch, OutsourcingOrder, OutsourcingRawReturn, TubeOutsourcingAction, TubeOutsourcingOrder
from apps.outsourcing.plan_correction_stock import DISPATCH_SOURCE, MATERIAL_SOURCE
from apps.outsourcing.selectors import accessible_outsourcing_orders
from apps.outsourcing.tube_selectors import VIEW_PERMISSION, saved_orders_for_permission
from apps.outsourcing.warehouse_access import warehouse_regular_orders, warehouse_tube_orders
from apps.procurement.models import PurchaseReturnLine
from apps.samples.models import SampleMaterialIssue
from apps.samples.selectors import accessible_sample_requests

from .bom_inventory_sections import RAW_SECTIONS
from .models import MaterialInbound, MaterialInboundLine, MaterialStockMovement, MaterialTransfer, PublicStockMovement
from .purchase_receipt_records import RECEIPT_PERMISSIONS, purchase_receipt_scope, transfer_receipt_scope
from .purchase_receiving_sections import OTHER_SECTION, assigned_receiving_sections, with_receipt_section_history, with_receiving_section
from .selectors import visible_confirmed_material_receipts


RAW_KINDS = ("RAW_PIPE", "CATALOG_RAW")
MOVEMENT_LABELS = {
    "MATERIAL_INBOUND": "采购入库", "MANUAL_INBOUND": "普通收料",
    "TRANSFER_IN": "普通收进", "TRANSFER_OUT": "普通发出",
    "MATERIAL_ISSUE": "车间实发", "SAMPLE_MATERIAL_ISSUE": "样品领料",
    "OUTSOURCING_DISPATCH": "委外发料", "TUBE_OUTSOURCING_DISPATCH": "委外发料",
    "TUBE_OUTSOURCING_MATERIAL_DISPATCH": "委外发料", "OUTSOURCING_RAW_RETURN": "委外退回原料",
    "PURCHASE_RETURN": "采购退货扣库",
}


@dataclass(frozen=True)
class Source:
    records: QuerySet
    fields: dict
    lookup: str = "source_id"


def _purchase_lines(request, allowed):
    purchases, lines, _ = purchase_receipt_scope(request, allowed)
    visible = Q(inbound_id__in=purchases.order_by().values("pk")) & Q(pk__in=lines.order_by().values("pk"))
    if RECEIPT_PERMISSIONS[2] in allowed:
        manual = visible_confirmed_material_receipts(request).filter(purchase_order__isnull=True)
        visible |= Q(inbound_id__in=manual.order_by().values("pk"))
    return with_receiving_section(MaterialInboundLine.objects.filter(visible))


def _outsourcing_sources(request, direction):
    orders = warehouse_regular_orders(request)
    tubes = warehouse_tube_orders(request)
    if has_permission(request, VIEW_PERMISSION):
        orders = OutsourcingOrder.objects.filter(
            Q(pk__in=orders.order_by().values("pk"))
            | Q(pk__in=accessible_outsourcing_orders(request, VIEW_PERMISSION).order_by().values("pk")),
        )
        tubes = TubeOutsourcingOrder.objects.filter(
            Q(pk__in=tubes.order_by().values("pk"))
            | Q(pk__in=saved_orders_for_permission(request).order_by().values("pk")),
        )
    if direction == "IN":
        returns = OutsourcingRawReturn.objects.filter(order_id__in=orders.order_by().values("pk")).annotate(
            actual_day=TruncDate("confirmed_at"),
        )
        return {"OUTSOURCING_RAW_RETURN": Source(returns, {
            "business_date": "actual_day", "voucher_number": "order__order_number", "origin_id": "order_id",
            "counterparty": "factory__name", "note": "reason",
        })}

    dispatches = OutsourcingDispatch.objects.filter(order_id__in=orders.order_by().values("pk"))
    readable = tubes.exclude(status="CANCELLED").order_by().values("pk")
    batches = TubeOutsourcingOrder.objects.filter(
        Q(pk__in=readable) | Q(plan_id__in=readable), is_plan=False, status__in=("PROCESSING", "COMPLETED"),
    )
    actions = TubeOutsourcingAction.objects.filter(order_id__in=batches.order_by().values("pk"), kind="DISPATCH").annotate(
        original_order=Coalesce("order__plan_id", "order_id"),
    )
    tube = Source(actions, {
        "business_date": "actual_dispatch_date", "voucher_number": "order__order_number",
        "origin_id": "original_order", "note": "remark",
    }, "order_id")
    return {
        "OUTSOURCING_DISPATCH": Source(dispatches, {
            "business_date": "dispatch_date", "voucher_number": Coalesce(NullIf("dispatch_number", Value("")), "order__order_number"),
            "origin_id": "order_id", "note": "remark",
        }),
        "TUBE_OUTSOURCING_DISPATCH": tube,
        "TUBE_OUTSOURCING_MATERIAL_DISPATCH": tube,
    }


def _sources(request, direction, allowed):
    sources = _outsourcing_sources(request, direction)
    lines = _purchase_lines(request, allowed)
    receipt_history = with_receipt_section_history(MaterialInbound.objects.all())
    if direction == "IN":
        lines = lines.annotate(
            record_kind=Case(When(inbound__purchase_order__isnull=True, then=Value("MANUAL_INBOUND")), default=Value("MATERIAL_INBOUND")),
            legacy_packaging=Exists(receipt_history.filter(pk=OuterRef("inbound_id"), has_legacy_packaging=True)),
        )
        transfers, _ = transfer_receipt_scope(request, allowed)
        sources["MATERIAL_INBOUND"] = Source(lines, {
            "business_date": "inbound__inbound_date", "voucher_number": "inbound__inbound_number",
            "origin_id": "inbound_id", "origin_section": "inbound__material_section", "legacy_packaging": "legacy_packaging",
            "counterparty": "supplier_name_snapshot", "note": "remark", "category": NullIf("receiving_section", Value(OTHER_SECTION)),
            "item_name": "part_name_snapshot", "specification": "specification_snapshot",
            "task_number": "inbound__purchase_order__production_task_number_snapshot", "record_kind": "record_kind",
            "actor_name": "inbound__received_by_employee__display_name",
        }, "source_line_id")
    else:
        transfers = MaterialTransfer.objects.filter(direction="OUT")
        if has_permission(request, "material_issues.view_materialissue"):
            issues = accessible_material_issues(request, "material_issues.view_materialissue").annotate(
                actual_day=TruncDate("issued_at"),
            )
            sources["MATERIAL_ISSUE"] = Source(issues, {
                "business_date": "actual_day", "voucher_number": "issue_number",
                "recipient_name": "recipient_name_snapshot",
            })
        if has_permission(request, "samples.view_samplerequest"):
            samples = accessible_sample_requests(request, "view_samplerequest")
            issues = SampleMaterialIssue.objects.filter(material_request__sample_request_id__in=samples.order_by().values("pk")).annotate(
                actual_day=TruncDate("confirmed_at"),
            )
            sources["SAMPLE_MATERIAL_ISSUE"] = Source(issues, {
                "business_date": "actual_day", "voucher_number": "material_request__sample_request__request_number",
                "origin_id": "material_request__sample_request_id", "note": "note",
            })
        returns = PurchaseReturnLine.objects.filter(inbound_line_id__in=lines.order_by().values("pk")).annotate(
            legacy_packaging=Exists(receipt_history.filter(pk=OuterRef("inbound_line__inbound_id"), has_legacy_packaging=True)),
        )
        sources["PURCHASE_RETURN"] = Source(returns, {
            "voucher_number": "return_order__return_number", "origin_id": "return_order_id",
            "origin_section": "inbound_line__inbound__material_section", "counterparty": "return_order__supplier_name_snapshot",
            "legacy_packaging": "legacy_packaging",
            "item_name": "inbound_line__part_name_snapshot", "specification": "inbound_line__specification_snapshot",
            "task_number": "return_order__purchase_order__production_task_number_snapshot",
            "note": "inbound_line__quality_remark",
        }, "source_line_id")
    sources["MATERIAL_TRANSFER"] = Source(transfers, {
        "business_date": "transfer_date", "voucher_number": "transfer_number", "note": "remark",
        "record_kind": Value(f"TRANSFER_{direction}"),
    })
    return sources


def _source_value(sources, field, fallback, output_field=None):
    cases = []
    for code, source in sources.items():
        columns = source.fields.get(field)
        if columns is None:
            continue
        local_field, outer_field = ("order_id", "source_id") if source.lookup == "order_id" else ("pk", source.lookup)
        expression = F(columns) if isinstance(columns, str) else columns
        value = Subquery(source.records.filter(**{local_field: OuterRef(outer_field)}).order_by()
                         .annotate(stock_record_value=expression).values("stock_record_value")[:1])
        if isinstance(output_field, CharField):
            value = NullIf(value, Value(""))
        cases.append(When(source_type=code, then=value))
    return Coalesce(Case(*cases, default=Value(None), output_field=output_field), fallback, output_field=output_field) if cases else fallback


PAGE_FIELDS = ("ledger", "id", "source_type", "source_id", "source_line_id", "occurred_at", "business_date",
               "category", "actual_quantity", "uses_weight")


def _material_description(public):
    raw_name = "balance__raw_material__material_name"
    raw_spec = "balance__raw_material__specification"
    raw_color = "balance__raw_material__color__color_name"
    if not public:
        return {key: Coalesce(path, Value("")) for key, path in (
            ("item_name", raw_name), ("specification", raw_spec), ("color", raw_color),
        )}
    identity = KeyTransform("material_selection_snapshot", F("balance__identity_snapshot"))
    attributes = KeyTransform("attributes", identity)
    return {
        "item_name": Coalesce(NullIf(KeyTextTransform("name", identity), Value("")),
                              raw_name, "balance__material_catalog__name", Value(""), output_field=CharField()),
        # 与现有物料规格显示顺序一致：先取独立规格，再取尺寸、门幅等实物属性。
        "specification": Coalesce(*(NullIf(KeyTextTransform(field, attributes), Value("")) for field in (
            "section_size", "fabric_spec", "specification", "size", "tube_size", "diameter",
            "length", "width", "fabric_width", "thickness", "model",
        )),
                                  raw_spec, Value(""), output_field=CharField()),
        "color": Coalesce(KeyTextTransform("color", attributes), raw_color, Value(""), output_field=CharField()),
    }


def _record_query(model, sources, filters, assigned):
    public = model is PublicStockMovement
    auth = Q(pk__in=[])
    for code, source in sources.items():
        local_field, outer_field = ("order_id", "source_id") if source.lookup == "order_id" else ("pk", source.lookup)
        auth |= Q(source_type=code, **{f"{outer_field}__in": source.records.order_by().values(local_field)})
    rows = model.objects.filter(auth, direction=filters["direction"])
    if public:
        rows = rows.filter(balance__stock_kind__in=RAW_KINDS)
    else:
        # 切库时若同一行、同一库区留下两套流水，采用正式公共库存凭据。
        mirror = PublicStockMovement.objects.filter(balance__stock_kind__in=RAW_KINDS,
            source_type=OuterRef("source_type"), source_line_id=OuterRef("source_line_id"),
            direction=OuterRef("direction"), balance__zone_id=OuterRef("balance__zone_id"))
        rows = rows.filter(~Exists(mirror))

    selected = "balance__identity_snapshot__material_selection_snapshot"
    identity = KeyTransform("material_selection_snapshot", F("balance__identity_snapshot"))
    category = Case(
        When(snapshot__material_selection_snapshot__category_key__in=RAW_SECTIONS,
             then=KeyTextTransform.from_lookup("snapshot__material_selection_snapshot__category_key")),
        *([When(balance__stock_kind="RAW_PIPE", then=Value("TUBE")),
           When(**{f"{selected}__category_key__in": RAW_SECTIONS},
                then=KeyTextTransform("category_key", identity))] if public else []),
        *(When(balance__raw_material__category__category_name__in=aliases, then=Value(key))
          for key, (_, aliases) in RAW_SECTIONS.items()),
        default=Value(OTHER_SECTION), output_field=CharField(),
    )
    quantity = F("quantity")
    if filters["direction"] == "OUT":
        corrections = model.objects.filter(source_type__in=(DISPATCH_SOURCE, MATERIAL_SOURCE)).annotate(
            original_movement=KeyTextTransform("original_movement_id", "snapshot"),
        ).filter(original_movement=Cast(OuterRef("pk"), CharField())).order_by().values("original_movement").annotate(
            delta=Sum(Case(When(direction="OUT", then=F("quantity")), default=-F("quantity"))),
        )
        quantity = Case(
            When(source_type__in=("TUBE_OUTSOURCING_DISPATCH", "TUBE_OUTSOURCING_MATERIAL_DISPATCH"),
                 then=F("quantity") + Coalesce(Subquery(corrections.values("delta")[:1]), Value(0),
                                                output_field=model._meta.get_field("quantity"))),
            default=F("quantity"),
        )
    rows = rows.order_by().annotate(
        category=_source_value(sources, "category", category, CharField()), corrected_quantity=quantity,
    )
    weighed = Q(category="HARDWARE", weight_quantity__gt=0, snapshot__measurement_kind="HARDWARE_WEIGHT",
                source_type__in=("MATERIAL_INBOUND", "PURCHASE_RETURN"))
    rows = rows.annotate(
        ledger=Value("PUBLIC" if public else "LEGACY"),
        business_date=_source_value(sources, "business_date", TruncDate("occurred_at"), DateField()),
        actual_quantity=Case(When(weighed, then=F("weight_quantity")), default=F("corrected_quantity")),
        uses_weight=Case(When(weighed, then=Value(True)), default=Value(False)),
    ).filter(Q(corrected_quantity__gt=0) | weighed)
    if assigned is not None:
        rows = rows.filter(Q(category__in=assigned) | ~Q(source_type="MATERIAL_TRANSFER"))
    if filters["task_number"]:
        rows = rows.alias(task_number=_source_value(sources, "task_number",
            Coalesce("production_task__task_number", Value("")), CharField())).filter(task_number__icontains=filters["task_number"])
    if filters["q"]:
        description = _material_description(public)
        rows = rows.alias(item_name=_source_value(sources, "item_name", description["item_name"], CharField()),
                          specification=_source_value(sources, "specification", description["specification"], CharField()),
                          voucher_number=_source_value(sources, "voucher_number", Value(""), CharField()))
        rows = rows.filter(Q(item_name__icontains=filters["q"]) | Q(voucher_number__icontains=filters["q"])
                           | Q(specification__icontains=filters["q"]))
    if "start_date" in filters:
        rows = rows.filter(business_date__gte=filters["start_date"])
    if "end_date" in filters:
        rows = rows.filter(business_date__lte=filters["end_date"])
    return rows


def _populate_details(rows, sources):
    movements = {}
    for ledger, model in (("LEGACY", MaterialStockMovement), ("PUBLIC", PublicStockMovement)):
        ids = [row["id"] for row in rows if row["ledger"] == ledger]
        movements[ledger] = model.objects.filter(pk__in=ids).select_related(
            "balance__unit", "balance__zone__warehouse", "actor_employee", "production_task",
        ).annotate(**_material_description(ledger == "PUBLIC")).in_bulk()
    originals = {}
    for code, source in sources.items():
        local_field, outer_field = ("order_id", "source_id") if source.lookup == "order_id" else ("pk", source.lookup)
        ids = [row[outer_field] for row in rows if row["source_type"] == code]
        fields = {f"detail_{key}": F(value) if isinstance(value, str) else value
                  for key, value in source.fields.items() if key not in ("category", "business_date")}
        result = source.records.filter(**{f"{local_field}__in": ids}).order_by().annotate(**fields).values(local_field, *fields)
        originals[code] = {row[local_field]: {key.removeprefix("detail_"): row[key] for key in fields} for row in result}
    for row in rows:
        movement = movements[row["ledger"]][row["id"]]
        code = row["source_type"]
        key = row["source_line_id" if sources[code].lookup == "source_line_id" else "source_id"]
        origin = originals[code][key]
        zone = movement.balance.zone
        row.update(
            record_kind=origin.get("record_kind") or code, origin_id=origin.get("origin_id") or row["source_id"],
            task_number=origin.get("task_number") or (movement.production_task.task_number if movement.production_task_id else ""),
            voucher_number=origin.get("voucher_number") or "", origin_section=origin.get("origin_section") or "",
            legacy_packaging=origin.get("legacy_packaging", False),
            item_name=origin.get("item_name") or movement.item_name, specification=origin.get("specification") or movement.specification,
            color=movement.color, warehouse_name=zone.warehouse.warehouse_name, zone_name=zone.zone_name,
            stock_unit="kg" if row["uses_weight"] else movement.balance.unit.unit_name,
            actor_name=origin.get("actor_name") or movement.actor_employee.display_name,
            recipient_name=origin.get("recipient_name") or "", note=origin.get("note") or "",
            counterparty=origin.get("counterparty") or movement.snapshot.get("factory_name") or movement.snapshot.get("factory") or "",
        )


def material_stock_record_page(request, filters, allowed):
    sources = _sources(request, filters["direction"], allowed)
    assigned = assigned_receiving_sections(request) if filters["direction"] == "IN" else None
    legacy, public = (_record_query(model, sources, filters, assigned) for model in (MaterialStockMovement, PublicStockMovement))
    show_other = legacy.filter(category=OTHER_SECTION).exists() or public.filter(category=OTHER_SECTION).exists()
    section = filters["section"]
    rows = legacy.filter(category=section).values(*PAGE_FIELDS).union(
        public.filter(category=section).values(*PAGE_FIELDS), all=True,
    ).order_by("-business_date", "-occurred_at", "-id")
    offset = (filters["page"] - 1) * filters["page_size"]
    page = list(rows[offset:offset + filters["page_size"]])
    _populate_details(page, sources)
    return page, rows.count(), show_other
