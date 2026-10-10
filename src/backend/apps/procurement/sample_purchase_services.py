"""从仓库冻结的样品缺料创建采购，保留逐行来源以便真实入库回写。"""
import hashlib
import json
from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import NotFound, ValidationError

from apps.core.audit import write_audit_log
from apps.reference_data.models import Currency, ReferenceStatus
from apps.samples.models import SampleMaterialProcurementRequest, SampleMaterialPurchaseSource, SampleRequest

from .models import PurchaseOrder, PurchaseOrderLine, PurchaseOrderSourceType, Supplier
from .selectors import purchase_orders_with_context
from .source_access import accessible_purchase_samples


CATEGORIES = {
    "tube": ("PROFILE", "管材类"), "hardware": ("HARDWARE", "五金件"),
    "plastic": ("PLASTIC", "塑料件"), "accessory": ("ACCESSORY", "辅料"),
    "fabric": ("FABRIC", "面料类"), "packaging": ("PACKAGING", "包装"),
}


def sample_procurement_sources(request):
    return SampleMaterialProcurementRequest.objects.filter(
        material_request__sample_request__in=accessible_purchase_samples(request),
        material_request__sample_request__status="PROCUREMENT_PENDING",
        material_request__reviewed_at__isnull=False,
    ).exclude(material_request__sample_request__application_payload_hash="").select_related(
        "material_request__sample_request__customer_account",
    )


def sample_source(procurement):
    sample = procurement.material_request.sample_request
    existing = PurchaseOrder.objects.filter(sample_procurement_request=procurement).first()
    if not existing:
        binding = procurement.purchase_sources.select_related("purchase_order_line__purchase_order").first()
        existing = binding.purchase_order_line.purchase_order if binding else None
    blockers = []
    if existing:
        blockers.append({"code": "PURCHASE_ORDER_EXISTS", "message": "该打样单缺料已建立采购订单，请进入原采购单继续处理。"})
    if not procurement.lines:
        blockers.append({"code": "SAMPLE_NO_SHORTAGE", "message": "该打样单没有已确认的缺料采购需求。"})
    from apps.samples.pipe_materials import sample_pipe_snapshot
    from apps.samples.material_identity import sample_material_snapshot
    pipe_snapshots = {}
    for row in procurement.lines:
        if row.get('category') == 'tube':
            try:
                pipe_snapshots[row['key']] = sample_pipe_snapshot(procurement, row)
            except ValidationError as error:
                blockers.append({'code': 'PIPE_PARAMETERS_REQUIRED', 'message': f'打样管材参数或原料关联不完整：{error.detail}'})
        else:
            try:
                pipe_snapshots[row['key']] = sample_material_snapshot(procurement, row)
            except ValidationError as error:
                blockers.append({'code': 'MATERIAL_IDENTITY_REQUIRED', 'message': f'打样原料关联不完整：{error.detail}'})
    payload = {
        "id": str(procurement.pk), "sample_request_id": str(sample.pk),
        "source_type": "SAMPLE", "source_type_display": "打样单",
        "source_number": sample.request_number, "customer_name": sample.customer_account.account_name,
        "delivery_date": sample.sample_due_date, "product_count": sample.items.count(),
        "demand_count": len(procurement.lines), "status": sample.status,
        "status_display": "采购中" if existing else "待采购", "can_create": not blockers,
        "blockers": blockers, "existing_purchase_order_id": str(existing.pk) if existing else None,
        "existing_purchase_order_number": existing.order_number if existing else "",
        "summary": "；".join(" · ".join(filter(None, [item.product_description_snapshot, item.color_name_snapshot,
            f"打样数量 {item.sample_quantity if item.sample_quantity is not None else item.requested_quantity} {item.unit_code}"])) for item in sample.items.all()),
    }
    revision = hashlib.sha256(json.dumps({
        "id": str(procurement.pk), "lines": procurement.lines, "notes": procurement.notes,
        "sample_updated_at": str(sample.updated_at), "status": sample.status,
    }, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    lines = []
    for i, row in enumerate(procurement.lines, 1):
        section, category = CATEGORIES[row["category"]]
        lines.append({
            "sample_line_key": row["key"], "line_number": i,
            "part_name": row["name"], "specification": row["specification"],
            "raw_material": row["material"], "material": row["material"], "product_color": row.get("color", ""),
            "section_type": section, "section_title": category, "category": category,
            "product_name": "样品采购需求", "product_number": "", "product_specification": "",
            "sample_demand_quantity": row["quantity"], "sample_supply_quantity": row["supplyQuantity"],
            "required_quantity": row["shortageQuantity"], "source_quantity_text": row["shortageQuantity"],
            "source_quantity_field": "shortageQuantity", "source_unit_text": row["unitLabel"],
            "quantity_parse_status": "READY", "suggested_supplier_category": section, "category_source": "SECTION",
        })
        if row['key'] in pipe_snapshots:
            snapshot = pipe_snapshots[row['key']]
            if row['category'] != 'tube':
                lines[-1]['calculation_snapshot'] = snapshot
                continue
            lines[-1].update(required_quantity=snapshot.get('suggested_purchase_meters') or snapshot.get('shortage_meters'), source_unit_text='米',
                             source_quantity_text=snapshot.get('suggested_purchase_meters') or snapshot.get('shortage_meters'),
                             source_quantity_field='suggested_purchase_meters' if snapshot.get('schema_version') != 3 else 'shortage_meters',
                             calculation_snapshot=snapshot,
                             **{key: snapshot.get(key) for key in ('raw_bar_length_m', 'suggested_bar_count', 'suggested_purchase_meters')})
    return {
        "source_type": "SAMPLE", "sample_request": payload, "can_create": not blockers,
        "source_revision": revision, "blockers": blockers, "lines": lines if not blockers else [],
        "preview_lines": lines if blockers else [], "bom_options": [], "selected_bom_id": None,
        "has_creatable_bom": False, "requires_bom_selection": False, "notes": procurement.notes,
        "existing_purchase_order_id": payload["existing_purchase_order_id"],
        "existing_purchase_order_number": payload["existing_purchase_order_number"],
    }


@transaction.atomic
def create_sample_purchase_order(*, validated_data, actor_employee, request):
    from .services import PurchaseSourceChanged, PurchaseSourceUnavailable, _money, next_purchase_order_number, purchase_order_snapshot
    procurement_id = validated_data["sample_procurement_request_id"]
    candidate = sample_procurement_sources(request).filter(pk=procurement_id).first()
    if candidate is None:
        raise NotFound("打样采购需求不存在、当前不可采购或不在账号数据范围内。")
    SampleRequest.objects.select_for_update().get(pk=candidate.material_request.sample_request_id)
    procurement = sample_procurement_sources(request).select_for_update(of=("self",)).filter(pk=procurement_id).first()
    if procurement is None:
        raise NotFound("打样单状态已变化，请重新选择采购来源。")
    from apps.products.material_identity import lock_bom_line_material_identities
    lock_bom_line_material_identities([], extra_raw_material_ids=[row.get('rawMaterialId') for row in procurement.lines])
    source = sample_source(procurement)
    if not source["can_create"]:
        raise PurchaseSourceUnavailable(source["blockers"])
    if source["source_revision"] != validated_data["source_revision"]:
        raise PurchaseSourceChanged(source["source_revision"])
    submitted = validated_data["lines"]
    inputs = {str(row["sample_line_key"]): row for row in submitted}
    if len(inputs) != len(submitted) or set(inputs) != {row["sample_line_key"] for row in source["lines"]}:
        raise ValidationError({"lines": "采购明细必须完整对应当前打样单的缺料需求，不能遗漏、重复或混入其他来源。"})
    currency = None
    if validated_data.get("currency_id"):
        currency = Currency.objects.select_for_update().filter(
            pk=validated_data["currency_id"], status=ReferenceStatus.ACTIVE, archived_at__isnull=True,
        ).first()
        if currency is None:
            raise ValidationError({"currency_id": "采购币种不存在或已停用。"})
    ids = {row["supplier_id"] for row in submitted if row.get("supplier_id")}
    suppliers = {s.pk: s for s in Supplier.objects.select_for_update().filter(pk__in=ids, archived_at__isnull=True, is_disabled=False)}
    if ids - suppliers.keys():
        raise ValidationError({"lines": "采购明细包含不存在、已禁用或已归档的供应商。"})
    sample = procurement.material_request.sample_request
    order = PurchaseOrder.objects.create(
        order_number=next_purchase_order_number(), source_type=PurchaseOrderSourceType.SAMPLE,
        sample_procurement_request=procurement, sample_number_snapshot=sample.request_number,
        customer_name_snapshot=sample.customer_account.account_name, source_revision=source["source_revision"],
        currency=currency, currency_code_snapshot=currency.code if currency else "",
        currency_name_snapshot=currency.chinese_name if currency else "", currency_symbol_snapshot=currency.symbol if currency else "",
        is_mailed=validated_data.get("is_mailed"), created_by_employee=actor_employee,
    )
    amounts = []
    for row in source["lines"]:
        entry = inputs[row["sample_line_key"]]
        supplier = suppliers.get(entry.get("supplier_id"))
        quantity, price = entry.get("actual_purchase_quantity"), entry.get("unit_price")
        pipe_values = {}
        if row.get('section_type') == 'PROFILE':
            from .pipe_purchase import purchase_pipe_values
            pipe_values = purchase_pipe_values(row['calculation_snapshot'], entry)
            quantity = pipe_values['actual_purchase_meters']
        else:
            pipe_values = {'calculation_snapshot': row['calculation_snapshot']}
        amount = _money(quantity * price) if quantity is not None and price is not None else None
        amounts.append(amount)
        line = PurchaseOrderLine.objects.create(
            purchase_order=order, line_number=row["line_number"], product_name_snapshot="样品采购需求",
            section_type_snapshot=row["section_type"], section_title_snapshot=row["section_title"], category_snapshot=row["category"],
            part_name_snapshot=row["part_name"], specification_snapshot=row["specification"], raw_material_snapshot=row["raw_material"],
            color_snapshot=row["product_color"], required_quantity=Decimal(row["required_quantity"]),
            sample_demand_quantity=Decimal(row["sample_demand_quantity"]), sample_supply_quantity=Decimal(row["sample_supply_quantity"]),
            source_quantity_field=row['source_quantity_field'], source_quantity_text=row["source_quantity_text"],
            source_unit_text=row["source_unit_text"], quantity_parse_status="READY",
            supplier=supplier, supplier_number_snapshot=supplier.supplier_number if supplier else "",
            supplier_name_snapshot=supplier.supplier_name if supplier else "", supplier_type_snapshot=supplier.supplier_type if supplier else "",
            supplier_categories_snapshot=list(supplier.supplier_categories) if supplier else [],
            delivery_date=entry.get("delivery_date"), actual_purchase_quantity=quantity, unit_price=price, amount=amount,
            **pipe_values,
        )
        SampleMaterialPurchaseSource.objects.create(procurement_request=procurement, line_key=row["sample_line_key"], purchase_order_line=line)
    if currency and amounts and all(amount is not None for amount in amounts):
        order.total_amount = _money(sum(amounts, Decimal("0")))
        order.save(update_fields=["total_amount", "updated_at"])
    write_audit_log(object_type="PURCHASE_ORDER", object_id=order.pk, context_type="SAMPLE_REQUEST", context_id=sample.pk,
                    action="CREATED", actor_employee=actor_employee, after_data=purchase_order_snapshot(order), request=request)
    return purchase_orders_with_context().get(pk=order.pk)
