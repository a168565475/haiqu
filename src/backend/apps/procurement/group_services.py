from .catalog_materials import purchase_catalog_selection, physical_pipe_quantity, priced_quantity
from apps.material_catalog.saved_selection import validate_saved_material
"""生产采购总单：冻结来源，原 PurchaseOrder 继续承担批次履约。"""
import hashlib
import json
from decimal import Decimal
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.boms.models import Bom, BomLine
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.products.material_identity import lock_bom_line_material_identities
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import Currency, ReferenceStatus

from .material_receipt_identity import build_purchase_material_snapshot, resolve_purchase_material
from .group_selectors import purchase_group_completion_summary, purchase_groups_with_context
from .models import PurchaseGroup, PurchaseGroupLine, PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus, Supplier
from .pipe_purchase import pipe_source_snapshot, purchase_pipe_values
from .selectors import production_tasks_with_purchase_sources, purchase_orders_with_context
from .services import (
    PURCHASABLE_TASK_STATUSES, PurchaseSourceChanged, PurchaseSourceUnavailable, _money, evaluate_purchase_source,
    next_purchase_order_number, purchase_order_snapshot,
)


SOURCE_FIELDS = (
    "material_catalog_id", "material_selection_snapshot",
    "bom_id", "bom_line_id", "source_bom_line_id_snapshot", "product_line_id_snapshot",
    "bom_number_snapshot", "product_number_snapshot", "product_code_snapshot", "product_name_snapshot",
    "product_specification_snapshot", "section_type_snapshot", "section_title_snapshot",
    "category_snapshot", "material_snapshot", "part_name_snapshot", "specification_snapshot",
    "raw_material_snapshot", "material_attributes_snapshot", "required_quantity",
    "source_quantity_field", "source_quantity_text", "source_unit_text", "quantity_parse_status",
    "raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters", "calculation_snapshot",
)


@transaction.atomic
def complete_purchase_group(*, group_id, remark, allowed_task_ids, actor_employee, request):
    task_id = PurchaseGroup.objects.filter(
        pk=group_id, production_task_id__in=allowed_task_ids, archived_at__isnull=True,
    ).values_list("production_task_id", flat=True).first()
    if task_id is None:
        raise NotFound("采购总单不存在或不在当前账号的数据范围内。")
    task = ProductionTask.objects.select_for_update().get(pk=task_id)
    group = PurchaseGroup.objects.select_for_update().get(pk=group_id)
    if task.archived_at or group.archived_at:
        raise NotFound("采购总单或生产订单已归档。")
    require_matching_etag(request, group)
    # 入库先锁采购单；锁完当前所有批次后重新读取流程，不能依赖页面预取或总单版本代替重核。
    list(PurchaseOrder.objects.select_for_update().filter(
        purchase_group=group, archived_at__isnull=True,
    ).order_by("id"))
    current = purchase_groups_with_context().get(pk=group.pk)
    summary = purchase_group_completion_summary(current)
    if not summary["can_complete"]:
        raise Conflict(summary["blocked_reason"])
    remark = remark.strip()
    if len(remark) > 2000:
        raise ValidationError({"remark": "完成备注不能超过2000字。"})
    group.manual_completed_at = timezone.now()
    group.manual_completed_by_employee = actor_employee
    group.manual_completion_remark = remark
    group.save(update_fields=["manual_completed_at", "manual_completed_by_employee", "manual_completion_remark", "updated_at"])
    write_audit_log(
        object_type="PURCHASE_GROUP", object_id=group.pk, action="MANUALLY_COMPLETED",
        context_type="PRODUCTION_TASK", context_id=group.production_task_id, actor_employee=actor_employee,
        before_data={"manual_completed_at": None},
        after_data={"manual_completed_at": group.manual_completed_at,
                    "manual_completed_by_employee_id": actor_employee.pk, "manual_completion_remark": remark},
        request=request,
    )
    return purchase_groups_with_context().get(pk=group.pk)


def _json_value(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def source_issues(snapshot):
    issues = []
    if not snapshot.get("source_bom_line_id_snapshot") or not snapshot.get("product_line_id_snapshot"):
        issues.append("SOURCE_ID_MISSING")
    if snapshot.get("required_quantity") is None or Decimal(str(snapshot["required_quantity"])) <= 0:
        issues.append("SUGGESTED_QUANTITY_MISSING")
    if snapshot.get("quantity_parse_status") != "READY":
        issues.append("SUGGESTED_QUANTITY_UNRESOLVED")
    if not str(snapshot.get("source_unit_text") or "").strip():
        issues.append("UNIT_MISSING")
    if snapshot.get("material_catalog_id"):
        try:
            selected = validate_saved_material(snapshot.get("material_selection_snapshot"), material_catalog_id=snapshot["material_catalog_id"])
            pipe = snapshot.get("section_type_snapshot") == "PROFILE"
            if ("米" if pipe else selected["unit_name"]) != snapshot.get("source_unit_text") or (pipe and selected["unit_name"] != "根"):
                issues.append("UNIT_MISMATCH")
            if pipe and not snapshot.get("raw_bar_length_m"):
                issues.append("PIPE_PARAMETERS_MISSING")
        except ValidationError:
            issues.append("MATERIAL_SNAPSHOT_INVALID")
        return issues
    identity = snapshot.get("calculation_snapshot") or {}
    if not isinstance(identity, dict):
        identity = {}
        issues.append("MATERIAL_SNAPSHOT_INVALID")
    try:
        material_id = UUID(str(identity.get("raw_material_id")))
    except (ValueError, TypeError):
        issues.append("MATERIAL_IDENTITY_MISSING")
    else:
        material = RawMaterialInformation.objects.select_related("unit").filter(
            pk=material_id, item_type="MATERIAL", archived_at__isnull=True,
        ).first()
        if material is None:
            issues.append("MATERIAL_IDENTITY_MISSING")
        elif snapshot.get("section_type_snapshot") != "PROFILE" and (
            snapshot.get("source_unit_text") not in {material.unit.unit_name, material.unit.unit_code}
            or str(identity.get("unit_id") or material.unit_id) != str(material.unit_id)
        ):
            issues.append("UNIT_MISMATCH")
    if snapshot.get("section_type_snapshot") == "PROFILE" and not snapshot.get("raw_bar_length_m"):
        issues.append("PIPE_PARAMETERS_MISSING")
    return issues


def _save_group_line(group, number, snapshot):
    # 历史采购允许凭已保存的原料编号精确唯一识别；绝不按品名或当前BOM猜配。
    identity = snapshot.get("calculation_snapshot") or {}
    if not isinstance(identity, dict):
        identity = {}
    if "raw_material_id" not in identity and snapshot.get("raw_material_snapshot"):
        matches = list(RawMaterialInformation.objects.filter(
            material_number=snapshot["raw_material_snapshot"],
        ).values("id", "item_type", "archived_at", "unit_id")[:2])
        if len(matches) == 1 and matches[0]["item_type"] == "MATERIAL" and matches[0]["archived_at"] is None:
            snapshot["calculation_snapshot"] = {**identity, "raw_material_id": str(matches[0]["id"]),
                                                 "unit_id": str(matches[0]["unit_id"])}
    return PurchaseGroupLine.objects.create(
        purchase_group=group, line_number=number,
        source_bom_line_id_snapshot=snapshot.get("source_bom_line_id_snapshot"),
        product_line_id_snapshot=snapshot.get("product_line_id_snapshot"),
        required_quantity=snapshot.get("required_quantity"),
        source_unit_text=snapshot.get("source_unit_text", ""),
        source_snapshot=snapshot, compatibility_issues=source_issues(snapshot),
    )


def attach_purchase_order_group(order):
    """兼容旧创建入口；只增加归属，保留订单和所有明细的主键。调用方持任务锁。"""
    if order.source_type != "PRODUCTION" or order.purchase_group_id:
        return order.purchase_group if order.purchase_group_id else None
    lines = list(order.lines.order_by("line_number", "id"))
    product_ids = {line.product_line_id_snapshot for line in lines}
    bom_ids = {line.bom_id for line in lines}
    issues = [] if lines else ["SOURCE_LINES_MISSING"]
    if lines and (len(product_ids) != 1 or None in product_ids):
        issues.append("SOURCE_PRODUCT_AMBIGUOUS")
    if lines and (len(bom_ids) != 1 or None in bom_ids):
        issues.append("SOURCE_BOM_AMBIGUOUS")
    existing = PurchaseGroup.objects.select_for_update().filter(
        production_task=order.production_task,
        product_line_id_snapshot__in=product_ids, archived_at__isnull=True,
    ).first()
    if existing is not None:
        if (issues or existing.compatibility_issues or existing.batches.exists()
                or existing.source_bom_id_snapshot not in bom_ids or existing.source_revision != order.source_revision):
            raise Conflict("该产品已有采购总单，不能重建不同来源的采购单。")
        saved_lines = {line.source_bom_line_id_snapshot: line for line in existing.lines.all()}
        if set(saved_lines) != {line.source_bom_line_id_snapshot for line in lines}:
            raise Conflict("原采购总单材料范围已变化，请沿用总单快照新增批次。")
        for line in lines:
            saved = saved_lines[line.source_bom_line_id_snapshot]
            snapshot = _json_value({field: getattr(line, field) for field in SOURCE_FIELDS})
            if saved.compatibility_issues or any(snapshot.get(key) != saved.source_snapshot.get(key) for key in SOURCE_FIELDS):
                raise Conflict("原采购总单来源快照已变化，请沿用总单快照新增批次。")
            line.purchase_group_line = saved
            line.save(update_fields=["purchase_group_line"])
        order.purchase_group = existing
        order.batch_number = 1
        order.save(update_fields=["purchase_group", "batch_number"])
        existing.save(update_fields=["updated_at"])
        return existing
    group = PurchaseGroup.objects.create(
        group_number="CGZD" + order.order_number[4:], production_task=order.production_task,
        product_line_id_snapshot=next(iter(product_ids)) if len(product_ids) == 1 else None,
        source_bom_id_snapshot=next(iter(bom_ids)) if len(bom_ids) == 1 else None,
        production_task_number_snapshot=order.production_task_number_snapshot,
        sales_order_number_snapshot=order.sales_order_number_snapshot,
        customer_name_snapshot=order.customer_name_snapshot, source_revision=order.source_revision,
        created_by_employee=order.created_by_employee,
        compatibility_issues=issues,
    )
    for line in lines:
        snapshot = _json_value({field: getattr(line, field) for field in SOURCE_FIELDS})
        line.purchase_group_line = _save_group_line(group, line.line_number, snapshot)
        # 兼容归属不改原明细时间戳及履约字段。
        line.save(update_fields=["purchase_group_line"])
    order.purchase_group = group
    order.batch_number = 1
    order.save(update_fields=["purchase_group", "batch_number"])
    return group


@transaction.atomic
def create_purchase_group(*, validated_data, allowed_task_ids, actor_employee, request=None):
    task = ProductionTask.objects.select_for_update().filter(
        pk=validated_data["production_task_id"], pk__in=allowed_task_ids, archived_at__isnull=True,
    ).first()
    if task is None:
        raise NotFound("生产订单不存在或不在当前账号的数据范围内。")
    list(ProductionTaskProduct.objects.select_for_update().filter(production_task=task).order_by("id"))
    list(Bom.objects.select_for_update().filter(production_task=task).order_by("id"))
    bom_lines = list(BomLine.objects.select_for_update().filter(section__bom__production_task=task).order_by("id"))
    lock_bom_line_material_identities(bom_lines)
    existing = PurchaseGroup.objects.filter(
        production_task=task, source_bom_id_snapshot=validated_data["bom_id"], archived_at__isnull=True,
    ).first()
    if existing is not None:
        if existing.source_revision != validated_data["source_revision"]:
            raise Conflict("该产品已保存采购总单，请沿用总单快照新增批次。")
        return existing
    source = evaluate_purchase_source(
        production_tasks_with_purchase_sources(ProductionTask.objects.filter(pk=task.pk)).get(),
        bom_id=validated_data["bom_id"],
    )
    if not source["can_create"]:
        raise PurchaseSourceUnavailable(source["blockers"])
    if source["source_revision"] != validated_data["source_revision"]:
        raise PurchaseSourceChanged(source["source_revision"])
    group = PurchaseGroup.objects.create(
        group_number="CGZD" + next_purchase_order_number()[4:], production_task=task,
        product_line_id_snapshot=source["lines"][0]["product_line_id"],
        source_bom_id_snapshot=validated_data["bom_id"],
        production_task_number_snapshot=task.task_number, sales_order_number_snapshot=task.order_number,
        customer_name_snapshot=task.customer_account.account_name if task.customer_account_id else "",
        source_revision=source["source_revision"], created_by_employee=actor_employee,
    )
    for number, item in enumerate(source["lines"], 1):
        snapshot = {key: item[key] for key in (
            "material_catalog_id", "material_selection_snapshot",
            "source_bom_line_id_snapshot", "required_quantity", "source_quantity_field", "source_quantity_text",
            "source_unit_text", "quantity_parse_status", "material_attributes_snapshot",
        )}
        for key in ("bom_number", "product_number", "product_code", "product_name", "product_specification",
                    "section_type", "section_title", "category", "material", "part_name", "specification", "raw_material"):
            snapshot[key + "_snapshot"] = item[key]
        snapshot.update(bom_id=item["bom_id"], bom_line_id=item["bom_line_id"], product_line_id_snapshot=item["product_line_id"])
        if item["section_type"] == "PROFILE":
            calculation = pipe_source_snapshot(item["_bom_line"])
            snapshot.update({key: calculation[key] for key in ("raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters")})
        else:
            calculation = build_purchase_material_snapshot(item["_bom_line"])
        snapshot["calculation_snapshot"] = calculation
        line = _save_group_line(group, number, _json_value(snapshot))
        if line.compatibility_issues:
            raise ValidationError({"lines": f"第{number}行来源建议量、单位或材料身份不完整，请先核对BOM。"})
    write_audit_log(object_type="PURCHASE_GROUP", object_id=group.pk, context_type="PRODUCTION_TASK",
                    context_id=task.pk, action="CREATED", actor_employee=actor_employee,
                    after_data={"group_number": group.group_number, "source_revision": group.source_revision}, request=request)
    return group


def validate_group_line_source(line):
    """分批采用已保存的总单身份；BOM版本变化不能改写历史采购来源。"""
    source = line.purchase_group_line
    if source.purchase_group_id != line.purchase_order.purchase_group_id:
        raise Conflict("采购批次明细不属于当前总单。")
    if source.compatibility_issues:
        raise Conflict("采购总单来源存在待核对项，不能沿用未知来源。")
    if line.source_unit_text != source.source_unit_text or line.required_quantity != source.required_quantity:
        raise Conflict("采购批次单位或建议量与保存的总单快照不一致。")
    if line.calculation_snapshot != source.source_snapshot.get("calculation_snapshot", {}):
        raise Conflict("采购批次材料身份或计算参数与总单快照不一致。")
    if line.material_catalog_id:
        purchase_catalog_selection(line)
        if str(line.material_catalog_id) != str(source.source_snapshot.get("material_catalog_id")) or line.material_selection_snapshot != source.source_snapshot.get("material_selection_snapshot"):
            raise Conflict("采购批次材料与总单保存内容不一致。")
        return
    material = resolve_purchase_material(line)
    if line.section_type_snapshot == "PROFILE" and (
        material.unit.unit_name != "根" or material.unit.status != "ACTIVE" or material.unit.archived_at
        or material.category.category_name != "管材" or material.category.status != "ACTIVE" or material.category.archived_at
    ):
        raise Conflict("管材采购缺少有效的根制材料身份。")


@transaction.atomic
def create_purchase_batch(*, group_id, validated_data, allowed_task_ids, actor_employee, request=None):
    task_id = PurchaseGroup.objects.filter(pk=group_id, production_task_id__in=allowed_task_ids,
                                           archived_at__isnull=True).values_list("production_task_id", flat=True).first()
    if task_id is None:
        raise NotFound("采购总单不存在或不在当前账号的数据范围内。")
    # 与原采购编辑保持任务→总单→明细的锁顺序；批次序号和幂等键在同一事务产生。
    task = ProductionTask.objects.select_for_update().get(pk=task_id)
    if task.archived_at:
        raise NotFound("生产订单已归档。")
    group = PurchaseGroup.objects.select_for_update().get(pk=group_id)
    fingerprint = hashlib.sha256(json.dumps(validated_data, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()
    existing = group.batches.filter(batch_request_id=validated_data["request_id"]).first()
    if existing:
        if existing.batch_request_fingerprint != fingerprint:
            raise Conflict("同一请求编号不能用于不同的采购批次内容。")
        if existing.archived_at:
            raise Conflict("该请求创建的采购批次已归档，请使用新的请求编号。")
        return purchase_orders_with_context().get(pk=existing.pk), False
    if task.status not in PURCHASABLE_TASK_STATUSES:
        raise Conflict("生产任务当前状态不允许新增采购批次。")
    if group.compatibility_issues:
        raise Conflict("采购总单来源归属存在待核对项，不能新增批次。")
    require_matching_etag(request, group)
    source_lines = {str(line.pk): line for line in group.lines.select_for_update().order_by("id")}
    inputs = validated_data["lines"]
    ids = [str(item["purchase_group_line_id"]) for item in inputs]
    if len(ids) != len(set(ids)) or not set(ids).issubset(source_lines):
        raise ValidationError({"lines": "批次材料必须属于当前总单，且不能重复。"})
    if not inputs:
        raise ValidationError({"lines": "采购批次至少选择一项材料。"})
    lock_bom_line_material_identities([], extra_raw_material_ids=[
        source_lines[key].source_snapshot.get("calculation_snapshot", {}).get("raw_material_id") for key in ids
    ])
    currency = Currency.objects.select_for_update().filter(pk=validated_data["currency_id"],
        status=ReferenceStatus.ACTIVE, archived_at__isnull=True).first()
    if currency is None:
        raise ValidationError({"currency_id": "采购币种不存在或已停用。"})
    supplier_ids = {item.get("supplier_id") for item in inputs if item.get("supplier_id")}
    suppliers = {str(row.pk): row for row in Supplier.objects.select_for_update(no_key=True).filter(
        pk__in=supplier_ids, archived_at__isnull=True, is_disabled=False)}
    if {str(pk) for pk in supplier_ids} - set(suppliers):
        raise ValidationError({"lines": "采购明细包含不存在、禁用或归档的供应商。"})
    order = PurchaseOrder.objects.create(
        purchase_group=group, batch_number=(group.batches.aggregate(number=Max("batch_number"))["number"] or 0) + 1,
        batch_type=validated_data["batch_type"], batch_request_id=validated_data["request_id"],
        batch_request_fingerprint=fingerprint, order_number=next_purchase_order_number(),
        production_task=task, production_task_number_snapshot=group.production_task_number_snapshot,
        sales_order_number_snapshot=group.sales_order_number_snapshot, customer_name_snapshot=group.customer_name_snapshot,
        source_revision=group.source_revision, currency=currency, currency_code_snapshot=currency.code,
        currency_name_snapshot=currency.chinese_name, currency_symbol_snapshot=currency.symbol,
        is_mailed=validated_data.get("is_mailed"), created_by_employee=actor_employee,
    )
    amounts = []
    for number, item in enumerate(inputs, 1):
        source = source_lines[str(item["purchase_group_line_id"])]
        if source.compatibility_issues:
            raise Conflict(f"第{source.line_number}项历史来源待核对，不能创建批次。")
        values = {key: value for key, value in source.source_snapshot.items() if key in SOURCE_FIELDS}
        # BOM编辑可删除旧行；稳定来源ID及材料身份仍取保存快照，不重绑新BOM行。
        if values.get("bom_line_id") and not BomLine.objects.filter(pk=values["bom_line_id"]).exists():
            values["bom_line_id"] = None
        quantity = item.get("actual_purchase_quantity")
        if values.get("raw_bar_length_m"):
            values.update(purchase_pipe_values(values["calculation_snapshot"], item))
            quantity = physical_pipe_quantity(values["calculation_snapshot"], item, values)
        if quantity is None or quantity <= 0:
            raise ValidationError({"lines": "所选材料必须填写正数采购数量；管材填写根数。"})
        supplier = suppliers.get(str(item.get("supplier_id")))
        price = item.get("unit_price")
        price_quantity = priced_quantity(section_type=values["section_type_snapshot"], material_catalog_id=values.get("material_catalog_id"), physical_quantity=quantity, pipe_values=values)
        amount = _money(price_quantity * price) if price is not None and price_quantity is not None else None
        line = PurchaseOrderLine(purchase_order=order, purchase_group_line=source, line_number=number,
            **values, supplier=supplier, supplier_number_snapshot=supplier.supplier_number if supplier else "",
            supplier_name_snapshot=supplier.supplier_name if supplier else "",
            supplier_type_snapshot=supplier.supplier_type if supplier else "",
            supplier_categories_snapshot=list(supplier.supplier_categories) if supplier else [],
            delivery_date=item.get("delivery_date"), actual_purchase_quantity=quantity, unit_price=price, amount=amount)
        # Decimal/UUID字段在JSON中为字符串，加载模型字段转换后进行一致性校验。
        line.required_quantity = source.required_quantity
        validate_group_line_source(line)
        line.save()
        amounts.append(amount)
    if all(amount is not None for amount in amounts):
        order.total_amount = _money(sum(amounts, Decimal("0")))
        order.save(update_fields=["total_amount", "updated_at"])
    group.save(update_fields=["updated_at"])
    order = purchase_orders_with_context().get(pk=order.pk)
    write_audit_log(object_type="PURCHASE_ORDER", object_id=order.pk, context_type="PRODUCTION_TASK",
                    context_id=task.pk, action="CREATED", actor_employee=actor_employee,
                    after_data=purchase_order_snapshot(order), request=request)
    return order, True
