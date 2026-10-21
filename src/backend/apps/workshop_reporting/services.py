from apps.access_control.resource_scopes import require_workshop
import hashlib
import json
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.boms.models import Bom, BomLine, BomSectionType, BomStatus
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.numbering import next_business_number
from apps.production_scheduling.models import (
    ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft, ScheduleStatus,
)
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from apps.workshop_config.constants import METAL_WORKSHOP_NAME
from apps.workshop_config.models import (
    Craft, CraftType, Operation, PlanCategory, RecordStatus, Workshop, WorkshopEmployee,
)

from apps.workshop_config.selectors import locked_active_employees

from .models import (
    WageScheme, WageSchemeAction, WageSchemeCraft, WageSchemeEvent, WageSchemeLine,
    WageSchemeLineStatus, WageSchemeStatus, WorkCountingMode, WorkItem, WorkReport, WorkReportLine,
    WorkshopPlanExecution, WorkshopPlanStatus,
)
from .report_history import history_enabled, existing_submission, remember_report, scheme_was_used


EDITABLE_SCHEME_STATUSES = {WageSchemeStatus.DRAFT, WageSchemeStatus.RETURNED}
WAGE_SCHEME_TASK_STATUSES = {ProductionTaskStatus.READY, ProductionTaskStatus.IN_PRODUCTION}
WORK_REPORT_TASK_STATUSES = {
    ProductionTaskStatus.READY,
    ProductionTaskStatus.IN_PRODUCTION,
    ProductionTaskStatus.PAUSED,
    ProductionTaskStatus.COMPLETED,
    ProductionTaskStatus.CANCELLED,
}
MAX_WORK_REPORT_AMOUNT = Decimal("9999999999999999999999.99")
MAX_REQUIRED_QUANTITY = Decimal("99999999999999999999.9999")


def bom_options_for_product_line(product_line_id):
    bom = Bom.objects.filter(
        product_line_id=product_line_id,
        status=BomStatus.VERIFIED,
        archived_at__isnull=True,
    ).order_by("-version_number", "-updated_at", "-id").first()
    if not bom:
        return []
    options = []
    lines = BomLine.objects.filter(
        section__bom=bom,
    ).filter(
        Q(section__section_type=BomSectionType.PROFILE)
        | Q(section__section_type=BomSectionType.FABRIC, section__title="裁剪明细")
    ).order_by("section__line_number", "line_number", "id")
    for line in lines:
        name = (line.part_name or "").strip()
        material = (line.material or "").strip()
        specification = (line.specification or "").strip()
        if not name:
            continue
        source_type = (
            PlanCategory.METAL
            if line.section.section_type == BomSectionType.PROFILE
            else PlanCategory.CUTTING
        )
        label_parts = [name]
        if source_type == PlanCategory.METAL and material:
            label_parts.append(material)
        if specification:
            label_parts.append(specification)
        label = "-".join(label_parts)
        option = {
            "id": str(line.pk),
            "component_identity": str(line.component_identity),
            "name": name,
            "material": material,
            "specification": specification,
            "label": label,
            "source_type": source_type,
            "pieces_per_product": line.pieces_per_product,
            "cutting_sets_per_product": line.cutting_sets_per_product,
            "cutting_pieces_per_set": line.cutting_pieces_per_set,
        }
        options.append(option)
    return options


def metal_bom_options_for_product_line(product_line_id):
    return [
        item for item in bom_options_for_product_line(product_line_id)
        if item["source_type"] == PlanCategory.METAL
    ]


def _is_metal_craft_scope(crafts):
    return (
        len(crafts) == 1
        and crafts[0].workshop
        and crafts[0].workshop.name == METAL_WORKSHOP_NAME
    )


def _lock_tube_scheme_scope(scheme):
    from .tube_plan_services import is_tube_scheme
    if not is_tube_scheme(scheme):
        return False
    from apps.inventory.tube_processing_services import lock_tube_product_scope
    lock_tube_product_scope(scheme.product_line_id)
    return True


def _lock_tube_report_scope(schedule_product_id, scheme):
    from .tube_plan_services import is_tube_scheme
    if not is_tube_scheme(scheme):
        return False
    source = ProductionScheduleProduct.objects.filter(pk=schedule_product_id).values('product_line_id').first()
    if not source:
        return False
    if source['product_line_id'] != scheme.product_line_id:
        raise ValidationError({'scheme_id': '工价方案不属于当前排产产品。'})
    return _lock_tube_scheme_scope(scheme)


def _lock_sewing_scheme_scope(scheme):
    from apps.inventory.sewing_processing_services import is_sewing_craft_scope, lock_sewing_product_scope
    if not scheme or not is_sewing_craft_scope(scheme.product_line_id, scheme.scope_craft_id):
        return False
    lock_sewing_product_scope(scheme.product_line_id)
    return True


def _lock_sewing_report_scope(schedule_product_id, scheme):
    if not scheme:
        return False
    source = ProductionScheduleProduct.objects.filter(pk=schedule_product_id).values('product_line_id').first()
    if source and source['product_line_id'] != scheme.product_line_id:
        raise ValidationError({'scheme_id': '工价方案不属于当前排产产品。'})
    return _lock_sewing_scheme_scope(scheme) if source else False


def payload_hash(value):
    encoded = json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _snapshot(scheme):
    return {
        "status": scheme.status,
        "revision": scheme.revision,
        "effective_from": scheme.effective_from,
        "effective_to": scheme.effective_to,
        "lines": [
            {
                "id": str(line.pk), "work_item_id": str(line.work_item_id),
                "price": str(line.declared_price), "status": line.status,
                "counting_mode": line.counting_mode,
                "required_quantity": (
                    str(line.required_quantity_snapshot)
                    if line.required_quantity_snapshot is not None else None
                ),
            }
            for line in scheme.lines.all().order_by("line_number", "id")
        ],
    }


def _event(scheme, action, actor, comment=""):
    WageSchemeEvent.objects.create(
        scheme=scheme, action=action, scheme_revision=scheme.revision,
        actor_employee=actor, comment=comment, snapshot=json.loads(json.dumps(_snapshot(scheme), cls=DjangoJSONEncoder)),
    )


def _resolve_source(product_line_id, workshop_id, schedule_product_id, craft_ids):
    if len(set(craft_ids)) != 1:
        raise ValidationError({"craft_ids": "工价方案必须且只能选择一项工艺。"})
    try:
        product_line = ProductionTaskProduct.objects.select_related("production_task").get(pk=product_line_id)
        workshop = Workshop.objects.get(pk=workshop_id, status=RecordStatus.ACTIVE)
    except (ProductionTaskProduct.DoesNotExist, Workshop.DoesNotExist) as exc:
        raise ValidationError("生产任务产品或车间不存在。") from exc
    if product_line.production_task.status not in WAGE_SCHEME_TASK_STATUSES:
        raise ValidationError({"product_line_id": "生产任务当前状态不可建立工价方案。"})
    schedule_product = None
    if schedule_product_id:
        try:
            schedule_product = ProductionScheduleProduct.objects.select_related("schedule").get(pk=schedule_product_id)
        except ProductionScheduleProduct.DoesNotExist as exc:
            raise ValidationError({"schedule_product_id": "排产产品不存在。"}) from exc
        if (
            schedule_product.product_line_id != product_line.pk
            or schedule_product.removed_at is not None
            or schedule_product.schedule.record_status != ScheduleStatus.ACTIVE
        ):
            raise ValidationError({"schedule_product_id": "排产产品与生产任务产品不一致或已失效。"})
    crafts = list(Craft.objects.filter(pk__in=craft_ids, status=RecordStatus.ACTIVE, craft_type=CraftType.INTERNAL).select_related("workshop"))
    if len(crafts) != len(set(craft_ids)):
        raise ValidationError({"craft_ids": "存在无效或非厂内工艺。"})
    if any(item.workshop_id != workshop.pk for item in crafts):
        raise ValidationError({"craft_ids": "所选工艺不属于该车间。"})
    if schedule_product and ProductionScheduleProductCraft.objects.filter(
        schedule_product=schedule_product, removed_at__isnull=True, craft_id__in=[item.pk for item in crafts]
    ).count() != len(crafts):
        raise ValidationError({"craft_ids": "所选工艺不在当前有效排产产品中。"})
    return product_line, workshop, schedule_product, crafts


def _line_counting_basis(*, craft, item, bom_options, order_quantity):
    plan_category = (
        PlanCategory.METAL
        if craft.workshop and craft.workshop.name == METAL_WORKSHOP_NAME
        else craft.plan_category
    )
    bom_option = None
    counting_mode = WorkCountingMode.ORDER
    display_name = item.get("display_name", "").strip()

    if plan_category in {PlanCategory.METAL, PlanCategory.CUTTING, PlanCategory.SEWING}:
        bom_line_id = str(item.get("bom_line_id") or "")
        bom_option = bom_options.get(bom_line_id)
        expected_source = PlanCategory.METAL if plan_category == PlanCategory.METAL else PlanCategory.CUTTING
        if not bom_option or bom_option["source_type"] != expected_source:
            label = "管材" if plan_category == PlanCategory.METAL else "裁剪明细"
            raise ValidationError({"lines": f"名称/部位必须从当前已确认 BOM 的{label}中选择。"})
        display_name = bom_option["label"]
        if plan_category == PlanCategory.METAL:
            counting_mode = WorkCountingMode.PIECE
            factor = bom_option["pieces_per_product"]
            if factor is None or factor <= 0:
                raise ValidationError({"lines": f"BOM“{display_name}”缺少每件支数，请先完善 BOM。"})
            required_quantity = Decimal(order_quantity) * Decimal(factor)
        else:
            sets = bom_option["cutting_sets_per_product"]
            pieces = bom_option["cutting_pieces_per_set"]
            if sets is None or sets <= 0 or pieces is None or pieces <= 0:
                raise ValidationError({"lines": f"BOM“{display_name}”缺少每件套数或每套裁片数，请先完善 BOM。"})
            if plan_category == PlanCategory.CUTTING:
                counting_mode = WorkCountingMode.SET
            else:
                counting_mode = item.get("counting_mode")
                if counting_mode not in {WorkCountingMode.SET, WorkCountingMode.PIECE}:
                    raise ValidationError({"lines": f"车缝明细“{display_name}”必须选择按套或按片。"})
            required_quantity = Decimal(order_quantity) * Decimal(sets)
            if counting_mode == WorkCountingMode.PIECE:
                required_quantity *= Decimal(pieces)
    else:
        if not display_name:
            raise ValidationError({"lines": "名称/部位不能为空。"})
        required_quantity = Decimal(order_quantity)

    if required_quantity <= 0 or required_quantity > MAX_REQUIRED_QUANTITY:
        raise ValidationError({"lines": f"明细“{display_name}”的需完成次数超出系统可保存范围。"})
    return {
        "bom_option": bom_option,
        "counting_mode": counting_mode,
        "display_name": display_name,
        "order_quantity": order_quantity,
        "required_quantity": required_quantity.quantize(Decimal("0.0001")),
    }


def _work_item_for_line(*, product_line, workshop, craft_map, item, basis):
    try:
        craft = craft_map[item["craft_id"]]
        operation = Operation.objects.select_related("reporting_unit").get(pk=item["operation_id"], status=RecordStatus.ACTIVE)
    except (KeyError, Operation.DoesNotExist) as exc:
        raise ValidationError({"lines": "明细包含无效工艺或工序。"}) from exc
    if operation.craft_id != craft.pk:
        raise ValidationError({"lines": f"工序 {operation.name} 不属于所选工艺。"})
    display_name = basis["display_name"]
    bom_option = basis["bom_option"]
    component_identity = bom_option["component_identity"] if bom_option else None
    counting_mode = basis["counting_mode"]
    if item.get("work_item_id"):
        try:
            work_item = WorkItem.objects.select_related("unit").get(
                pk=item["work_item_id"], product_line=product_line, workshop=workshop
            )
        except WorkItem.DoesNotExist as exc:
            raise ValidationError({"lines": "原工作项不存在或不属于当前订单产品。"}) from exc
        if work_item.craft_id != craft.pk or work_item.operation_id != operation.pk:
            raise ValidationError({"lines": "变更方案不能改变原工作项的工艺或工序。"})
        if component_identity:
            if work_item.bom_component_identity and str(work_item.bom_component_identity) != component_identity:
                raise ValidationError({"lines": "变更方案不能把原工作项改为其他 BOM 名称/部位。"})
            if work_item.counting_mode != counting_mode and work_item.bom_component_identity:
                raise ValidationError({"lines": "变更计数方式会形成新的工作项，请删除原行后重新添加。"})
            changed_fields = []
            if not work_item.bom_component_identity:
                work_item.bom_component_identity = component_identity
                changed_fields.append("bom_component_identity")
            if work_item.counting_mode != counting_mode:
                work_item.counting_mode = counting_mode
                changed_fields.append("counting_mode")
            if work_item.display_name != display_name:
                work_item.display_name = display_name
                changed_fields.append("display_name")
            if changed_fields:
                work_item.save(update_fields=[*changed_fields, "updated_at"])
        elif work_item.display_name != display_name:
            raise ValidationError({"lines": "变更方案不能改变原工作项的名称/部位。"})
        return work_item, craft, operation
    identity_part = component_identity or display_name.casefold()
    identity_source = f"{craft.pk}:{operation.pk}:{identity_part}:{counting_mode}"
    identity_key = hashlib.sha256(identity_source.encode()).hexdigest()
    work_item, _ = WorkItem.objects.get_or_create(
        product_line=product_line, workshop=workshop, identity_key=identity_key,
        defaults={
            "craft": craft, "operation": operation, "unit": operation.reporting_unit,
            "display_name": display_name, "bom_component_identity": component_identity,
            "counting_mode": counting_mode,
        },
    )
    return work_item, craft, operation


def _replace_scheme_lines(scheme, items, crafts):
    if scheme_was_used(scheme):
        raise Conflict("已有报工引用的方案不能修改明细，请发起变更版本。")
    scheme.lines.all().delete()
    craft_map = {item.pk: item for item in crafts}
    is_metal_scope = _is_metal_craft_scope(crafts)
    bom_options = {
        item["id"]: item for item in bom_options_for_product_line(scheme.product_line_id)
    }
    order_quantity = (
        scheme.schedule_product.source_quantity_snapshot
        if scheme.schedule_product_id else scheme.product_line.quantity
    )
    seen = set()
    created = []
    for index, item in enumerate(items, start=1):
        craft = craft_map.get(item["craft_id"])
        if not craft:
            raise ValidationError({"lines": "明细包含无效工艺。"})
        basis = _line_counting_basis(
            craft=craft, item=item, bom_options=bom_options, order_quantity=order_quantity,
        )
        work_item, craft, operation = _work_item_for_line(
            product_line=scheme.product_line, workshop=scheme.workshop, craft_map=craft_map,
            item=item, basis=basis,
        )
        if not is_metal_scope and operation.product_name != scheme.operation_product_name_snapshot:
            raise ValidationError({"lines": f"工序 {operation.name} 不属于当前选择的工序品名。"})
        if work_item.pk in seen:
            raise ValidationError({"lines": "同一方案不能重复添加同一工作项。"})
        seen.add(work_item.pk)
        created.append(WageSchemeLine(
            scheme=scheme, work_item=work_item, line_number=index,
            display_name_snapshot=basis["display_name"],
            production_description=item.get("production_description", "").strip(),
            craft_name_snapshot=craft.name,
            operation_name_snapshot=operation.name, operation_number_snapshot=operation.operation_number,
            unit_name_snapshot=work_item.unit.unit_name if work_item.unit_id else "",
            bom_component_identity_snapshot=(
                basis["bom_option"]["component_identity"] if basis["bom_option"] else None
            ),
            counting_mode=basis["counting_mode"],
            order_quantity_snapshot=basis["order_quantity"],
            bom_sets_per_product_snapshot=(
                basis["bom_option"]["cutting_sets_per_product"] if basis["bom_option"] else None
            ),
            bom_pieces_per_set_snapshot=(
                basis["bom_option"]["cutting_pieces_per_set"] if basis["bom_option"] else None
            ),
            required_quantity_snapshot=basis["required_quantity"],
            previous_price=item.get("previous_price"), revised_price=item.get("revised_price"),
            declared_price=item["declared_price"], status=item.get("status", WageSchemeLineStatus.ACTIVE),
            note=item.get("note", ""),
        ))
    WageSchemeLine.objects.bulk_create(created)


def _refresh_scheme_required_quantities(scheme):
    options = bom_options_for_product_line(scheme.product_line_id)
    options_by_component = {item["component_identity"]: item for item in options}
    order_quantity = (
        scheme.schedule_product.source_quantity_snapshot
        if scheme.schedule_product_id else scheme.product_line.quantity
    )
    changed = []
    for line in scheme.lines.select_related("work_item").all():
        bom_option = (
            options_by_component.get(str(line.bom_component_identity_snapshot))
            if line.bom_component_identity_snapshot else None
        )
        basis = _line_counting_basis(
            craft=scheme.scope_craft,
            item={
                "bom_line_id": bom_option["id"] if bom_option else None,
                "display_name": line.display_name_snapshot,
                "counting_mode": line.counting_mode,
            },
            bom_options={item["id"]: item for item in options},
            order_quantity=order_quantity,
        )
        line.display_name_snapshot = basis["display_name"]
        line.order_quantity_snapshot = basis["order_quantity"]
        line.required_quantity_snapshot = basis["required_quantity"]
        line.bom_sets_per_product_snapshot = (
            basis["bom_option"]["cutting_sets_per_product"] if basis["bom_option"] else None
        )
        line.bom_pieces_per_set_snapshot = (
            basis["bom_option"]["cutting_pieces_per_set"] if basis["bom_option"] else None
        )
        changed.append(line)
    if changed:
        WageSchemeLine.objects.bulk_update(changed, [
            "display_name_snapshot", "order_quantity_snapshot", "required_quantity_snapshot",
            "bom_sets_per_product_snapshot", "bom_pieces_per_set_snapshot",
        ])


@transaction.atomic
def create_scheme(*, data, actor, parent_scheme=None, request=None):
    if request is not None:
        require_workshop(request, "workshop_reporting.change_wagescheme" if parent_scheme else "workshop_reporting.add_wagescheme", data["workshop_id"])
    craft_ids = list(dict.fromkeys(data.pop("craft_ids")))
    lines = data.pop("lines")
    history_source_id = data.pop("history_source_scheme_id", None)
    operation_product_name = data.pop("operation_product_name", "").strip()
    product_line, workshop, schedule_product, crafts = _resolve_source(
        data.pop("product_line_id"), data.pop("workshop_id"), data.pop("schedule_product_id", None), craft_ids
    )
    if _is_metal_craft_scope(crafts):
        operation_product_name = crafts[0].name
    elif not operation_product_name:
        raise ValidationError({"operation_product_name": "非金工工价方案必须选择工序品名。"})
    from .tube_plan_services import is_tube_craft_scope
    if is_tube_craft_scope(product_line.pk, crafts[0].pk):
        from apps.inventory.tube_processing_services import lock_tube_product_scope
        lock_tube_product_scope(product_line.pk)
    from apps.inventory.sewing_processing_services import is_sewing_craft_scope, lock_sewing_product_scope
    if is_sewing_craft_scope(product_line.pk, crafts[0].pk):
        lock_sewing_product_scope(product_line.pk)
    ProductionTaskProduct.objects.select_for_update().only("pk").get(pk=product_line.pk)
    scope_craft = crafts[0]
    if parent_scheme is None and WageScheme.objects.filter(
        product_line=product_line, workshop=workshop, scope_craft=scope_craft,
        parent_scheme__isnull=True,
    ).exists():
        raise Conflict("该订单产品和工艺已有方案版本链，请继续处理现有方案。")
    if history_source_id:
        history_source = WageScheme.objects.filter(
            pk=history_source_id, status=WageSchemeStatus.APPROVED, workshop=workshop
        ).first()
        if (
            not history_source
            or history_source.scope_craft_id != scope_craft.pk
            or (
                not _is_metal_craft_scope(crafts)
                and history_source.operation_product_name_snapshot != operation_product_name
            )
        ):
            raise ValidationError({"history_source_scheme_id": "历史方案必须已批准，且车间、工艺和工序品名与当前方案完全一致。"})
    scheme = WageScheme.objects.create(
        scheme_number=next_business_number("WAGE_SCHEME"), product_line=product_line, workshop=workshop,
            parent_scheme=parent_scheme, version=parent_scheme.version + 1 if parent_scheme else 1,
            scope_craft=scope_craft,
        schedule_product=schedule_product, product_name_snapshot=product_line.product_name_snapshot,
        product_number_snapshot=product_line.product_number_snapshot,
        product_specification_snapshot=product_line.specification_snapshot, remark=data.get("remark", ""),
        operation_product_name_snapshot=operation_product_name,
        history_source_scheme_id=history_source_id, created_by_employee=actor, updated_by_employee=actor,
    )
    WageSchemeCraft.objects.bulk_create([WageSchemeCraft(scheme=scheme, craft=item) for item in crafts])
    _replace_scheme_lines(scheme, lines, crafts)
    _event(scheme, WageSchemeAction.CREATED, actor)
    return scheme


@transaction.atomic
def update_scheme(*, scheme_id, data, actor, request):
    scheme_scope = WageScheme.objects.get(pk=scheme_id)
    _lock_tube_scheme_scope(scheme_scope)
    _lock_sewing_scheme_scope(scheme_scope)
    scheme = WageScheme.objects.select_for_update().get(pk=scheme_id)
    require_workshop(request, "workshop_reporting.change_wagescheme", scheme.workshop_id)
    require_workshop(request, "workshop_reporting.change_wagescheme", data.get("workshop_id", scheme.workshop_id))
    require_matching_etag(request, scheme)
    if scheme.status not in EDITABLE_SCHEME_STATUSES:
        raise Conflict("当前状态不允许修改工价方案。")
    from apps.access_control.sales_policy import access_for
    edit_scopes = access_for(request)["actions"].get("workshop_reporting.change_wagescheme", {}).get("scopes", [])
    if scheme.created_by_employee_id != actor.pk and not request.user.is_superuser and not set(edit_scopes) & {"MODULE", "ALL"}:
        raise PermissionDenied("只有创建人可以修改该工价方案。")
    craft_ids = data.pop("craft_ids", None)
    lines = data.pop("lines", None)
    operation_product_name = data.pop("operation_product_name", scheme.operation_product_name_snapshot).strip()
    product_line_id = data.pop("product_line_id", scheme.product_line_id)
    workshop_id = data.pop("workshop_id", scheme.workshop_id)
    schedule_product_id = data.pop("schedule_product_id", scheme.schedule_product_id)
    effective_craft_ids = craft_ids or list(scheme.scheme_crafts.values_list("craft_id", flat=True))
    product_line, workshop, schedule_product, crafts = _resolve_source(
        product_line_id, workshop_id, schedule_product_id, effective_craft_ids
    )
    if _is_metal_craft_scope(crafts):
        operation_product_name = crafts[0].name
    if scheme.lines.exists() and (product_line.pk != scheme.product_line_id or workshop.pk != scheme.workshop_id):
        raise ValidationError("已有明细时不能更换生产任务产品或车间。")
    if scheme.scope_craft_id != crafts[0].pk:
        raise ValidationError({"craft_ids": "已有方案不能更换所属工艺。"})
    if lines is None and operation_product_name != scheme.operation_product_name_snapshot:
        raise ValidationError({"operation_product_name": "更换工序品名时必须同时提交并重新核对工价明细。"})
    scheme.product_line, scheme.workshop, scheme.schedule_product = product_line, workshop, schedule_product
    scheme.operation_product_name_snapshot = operation_product_name
    if craft_ids is not None:
        scheme.scheme_crafts.all().delete()
        WageSchemeCraft.objects.bulk_create([WageSchemeCraft(scheme=scheme, craft=item) for item in crafts])
    if "remark" in data:
        scheme.remark = data["remark"]
    scheme.revision += 1
    scheme.updated_by_employee = actor
    scheme.save()
    if lines is not None:
        _replace_scheme_lines(scheme, lines, crafts)
    _event(scheme, WageSchemeAction.UPDATED, actor)
    return scheme


@transaction.atomic
def create_change_scheme(*, source_scheme_id, data, actor, request):
    source_scope = WageScheme.objects.only("product_line_id", "scope_craft_id").get(pk=source_scheme_id)
    _lock_tube_scheme_scope(source_scope)
    _lock_sewing_scheme_scope(source_scope)
    ProductionTaskProduct.objects.select_for_update().only("pk").get(pk=source_scope.product_line_id)
    source = WageScheme.objects.select_for_update().get(pk=source_scheme_id)
    require_workshop(request, "workshop_reporting.change_wagescheme", source.workshop_id)
    require_workshop(request, "workshop_reporting.submit_wagescheme", source.workshop_id)
    require_matching_etag(request, source)
    if source.status != WageSchemeStatus.APPROVED:
        raise Conflict("只有已批准方案可以发起变更。")
    latest_approved = WageScheme.objects.filter(
        product_line=source.product_line, workshop=source.workshop, scope_craft=source.scope_craft,
        status=WageSchemeStatus.APPROVED,
    ).order_by("-effective_from", "-approved_at", "-id").first()
    if not latest_approved or latest_approved.pk != source.pk:
        raise Conflict("只能从当前最新的批准版本发起变更。")
    if source.change_versions.exists():
        raise Conflict("该方案已存在变更版本，请继续处理现有版本。")
    if data.get("product_line_id") != source.product_line_id or data.get("workshop_id") != source.workshop_id:
        raise ValidationError("变更版本必须保持原生产任务产品和车间。")
    if set(data.get("craft_ids") or []) != {source.scope_craft_id}:
        raise ValidationError({"craft_ids": "变更版本必须保持原所属工艺。"})
    new_scheme = create_scheme(data=data, actor=actor, parent_scheme=source, request=request)
    source_lines = {item.work_item_id: item.pk for item in source.lines.all()}
    changed_lines = []
    for line in new_scheme.lines.all():
        line.source_line_id = source_lines.get(line.work_item_id)
        if line.source_line_id:
            changed_lines.append(line)
    if changed_lines:
        WageSchemeLine.objects.bulk_update(changed_lines, ["source_line"])
    source.revision += 1
    source.updated_by_employee = actor
    source.save(update_fields=["revision", "updated_by_employee", "updated_at"])
    _event(source, WageSchemeAction.CHANGE_CREATED, actor, f"已生成变更方案 {new_scheme.scheme_number}")
    _event(new_scheme, WageSchemeAction.CHANGE_CREATED, actor)
    return new_scheme


@transaction.atomic
def submit_scheme(*, scheme_id, actor, request, comment=""):
    scheme_scope = WageScheme.objects.get(pk=scheme_id)
    _lock_tube_scheme_scope(scheme_scope)
    _lock_sewing_scheme_scope(scheme_scope)
    scheme = WageScheme.objects.select_for_update().get(pk=scheme_id)
    require_workshop(request, "workshop_reporting.submit_wagescheme", scheme.workshop_id)
    require_matching_etag(request, scheme)
    if scheme.status not in EDITABLE_SCHEME_STATUSES:
        raise Conflict("只有草稿或退回方案可以送审。")
    _refresh_scheme_required_quantities(scheme)
    lines = list(scheme.lines.select_related("work_item__operation").all())
    if not lines:
        raise ValidationError({"lines": "送审前至少需要一条工价明细。"})
    active_lines = [line for line in lines if line.status == WageSchemeLineStatus.ACTIVE]
    if not active_lines:
        raise ValidationError({"lines": "送审前至少需要一条正常状态的工价明细。"})
    scheme.status = WageSchemeStatus.PENDING_APPROVAL
    scheme.revision += 1
    scheme.updated_by_employee = actor
    scheme.save()
    _event(scheme, WageSchemeAction.SUBMITTED, actor, comment)
    from apps.wecom.workshop_notifications import scheme_changed
    scheme_changed(scheme, actor, submitted=True)
    return scheme


@transaction.atomic
def approve_scheme(*, scheme_id, actor, request, effective_from=None, effective_to=None, comment=""):
    scheme_scope = WageScheme.objects.only("product_line_id", "scope_craft_id").get(pk=scheme_id)
    tube_scope = _lock_tube_scheme_scope(scheme_scope)
    sewing_scope = _lock_sewing_scheme_scope(scheme_scope)
    # 同一生产任务产品是工价版本审批的稳定锁范围，避免两个方案同时通过重叠校验。
    ProductionTaskProduct.objects.select_for_update().only("pk").get(pk=scheme_scope.product_line_id)
    scheme = WageScheme.objects.select_for_update().select_related("product_line").get(pk=scheme_id)
    require_workshop(request, "workshop_reporting.approve_wagescheme", scheme.workshop_id)
    from apps.access_control.module_policy import prohibit_self_approval, enabled
    if enabled():
        submitter = scheme.events.filter(action=WageSchemeAction.SUBMITTED).order_by('-scheme_revision', '-created_at', '-id').values_list('actor_employee_id', flat=True).first()
        prohibit_self_approval(actor, submitter)
    require_matching_etag(request, scheme)
    if scheme.status != WageSchemeStatus.PENDING_APPROVAL:
        raise Conflict("只有待审批方案可以批准。")
    _refresh_scheme_required_quantities(scheme)
    effective_from = effective_from or timezone.localdate()
    approved_versions = list(WageScheme.objects.select_for_update().filter(
        product_line=scheme.product_line, workshop=scheme.workshop, scope_craft=scheme.scope_craft,
        status=WageSchemeStatus.APPROVED,
    ).exclude(pk=scheme.pk).order_by("effective_from", "approved_at", "pk"))
    if approved_versions:
        latest = approved_versions[-1]
        if not scheme.parent_scheme_id:
            raise Conflict("该订单产品和车间已有批准方案，请从最新批准版发起变更。")
        if latest.pk != scheme.parent_scheme_id:
            raise Conflict("变更方案不再基于最新批准版本，请重新发起。")
        same_or_earlier_effective_date = effective_from <= latest.effective_from
        if same_or_earlier_effective_date:
            latest.status = WageSchemeStatus.SUPERSEDED
        else:
            latest.effective_to = effective_from - timedelta(days=1)
        latest.revision += 1
        latest.updated_by_employee = actor
        latest.save(update_fields=[
            "status" if same_or_earlier_effective_date else "effective_to",
            "revision", "updated_by_employee", "updated_at",
        ])
        _event(
            latest, WageSchemeAction.UPDATED, actor,
            (
                f"批准新版本 {scheme.scheme_number}，旧版已被替代。"
                if same_or_earlier_effective_date
                else f"批准新版本 {scheme.scheme_number}，旧版自动截止到 {latest.effective_to.isoformat()}。"
            ),
        )
    elif scheme.parent_scheme_id:
        raise Conflict("变更方案的来源批准版本不存在。")
    scheme.status = WageSchemeStatus.APPROVED
    scheme.effective_from = effective_from
    scheme.effective_to = effective_to
    scheme.approved_by_employee = actor
    scheme.approved_at = timezone.now()
    scheme.revision += 1
    scheme.updated_by_employee = actor
    scheme.save()
    _event(scheme, WageSchemeAction.APPROVED, actor, comment)
    if tube_scope:
        from apps.inventory.tube_processing_services import assert_tube_reports_cover_usage
        from .tube_plan_services import reopen_tube_plans_for_scheme
        assert_tube_reports_cover_usage(scheme.product_line_id)
        reopen_tube_plans_for_scheme(scheme, actor)
    if sewing_scope:
        from apps.inventory.sewing_processing_services import assert_sewing_reports_cover_usage
        assert_sewing_reports_cover_usage(scheme.product_line_id)
    from apps.wecom.workshop_notifications import scheme_changed
    scheme_changed(scheme, actor)
    return scheme


@transaction.atomic
def return_scheme(*, scheme_id, actor, request, comment=""):
    scheme_scope = WageScheme.objects.get(pk=scheme_id)
    _lock_tube_scheme_scope(scheme_scope)
    _lock_sewing_scheme_scope(scheme_scope)
    scheme = WageScheme.objects.select_for_update().get(pk=scheme_id)
    require_workshop(request, "workshop_reporting.approve_wagescheme", scheme.workshop_id)
    from apps.access_control.module_policy import prohibit_self_approval, enabled
    if enabled():
        submitter = scheme.events.filter(action=WageSchemeAction.SUBMITTED).order_by('-scheme_revision', '-created_at', '-id').values_list('actor_employee_id', flat=True).first()
        prohibit_self_approval(actor, submitter)
    require_matching_etag(request, scheme)
    if scheme.status != WageSchemeStatus.PENDING_APPROVAL:
        raise Conflict("只有待审批方案可以退回。")
    scheme.status = WageSchemeStatus.RETURNED
    scheme.revision += 1
    scheme.updated_by_employee = actor
    scheme.save()
    _event(scheme, WageSchemeAction.RETURNED, actor, comment)
    from apps.wecom.workshop_notifications import scheme_changed
    scheme_changed(scheme, actor)
    return scheme


def price_scheme_for(*, product_line_id, workshop_id, craft_id, production_date):
    schemes = WageScheme.objects.filter(
        product_line_id=product_line_id, workshop_id=workshop_id, scope_craft_id=craft_id,
        status=WageSchemeStatus.APPROVED,
        effective_from__lte=production_date,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=production_date)).order_by("-effective_from", "-approved_at", "-id")
    count = schemes.count()
    if count == 0:
        raise ValidationError({"production_date": "该生产日期没有适用的已批准工价方案。"})
    if count > 1:
        raise Conflict("该生产日期存在多个适用工价方案，请先处理版本区间冲突。")
    return schemes.first()


def wage_scheme_progress(scheme, cumulative_by_work_item=None):
    cumulative_by_work_item = cumulative_by_work_item or {}
    lines = [line for line in scheme.lines.all() if line.status == WageSchemeLineStatus.ACTIVE]
    if not lines or any(line.required_quantity_snapshot is None for line in lines):
        return None
    required_total = sum((line.required_quantity_snapshot for line in lines), Decimal("0"))
    if required_total <= 0:
        return None
    reported_total = sum(
        (cumulative_by_work_item.get(line.work_item_id, Decimal("0")) for line in lines),
        Decimal("0"),
    )
    percentage = int(
        min(Decimal("100"), (reported_total * Decimal("100") / required_total))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    return {
        "required_total": required_total,
        "reported_total": reported_total,
        "percentage": max(0, percentage),
    }


def _validated_work_report_lines(*, schedule_product, requested_scheme, data, exclude_report_id=None):
    if schedule_product.product_line.production_task.status not in WORK_REPORT_TASK_STATUSES:
        raise ValidationError({"schedule_product_id": "生产任务当前状态不允许报工。"})
    scheduled_craft_ids = set(
        schedule_product.crafts.filter(removed_at__isnull=True).values_list("craft_id", flat=True)
    )
    scheme_craft_ids = set(requested_scheme.scheme_crafts.values_list("craft_id", flat=True))
    if not scheme_craft_ids.issubset(scheduled_craft_ids):
        raise ValidationError({"scheme_id": "工价方案包含当前有效排产产品未安排的工艺。"})
    scheme = price_scheme_for(
        product_line_id=schedule_product.product_line_id,
        workshop_id=requested_scheme.workshop_id,
        craft_id=requested_scheme.scope_craft_id,
        production_date=data["production_date"],
    )
    if scheme.pk != requested_scheme.pk or scheme.revision != data["scheme_revision"]:
        raise Conflict("适用工价版本已变化，请刷新后重新核对。")
    from .tube_plan_services import is_tube_scheme, reopen_tube_plans_for_scheme
    if is_tube_scheme(scheme):
        reopen_tube_plans_for_scheme(scheme)
    if WorkshopPlanExecution.objects.filter(
        schedule_product=schedule_product,
        craft=scheme.scope_craft,
        status=WorkshopPlanStatus.COMPLETED,
    ).exists():
        raise ValidationError({"schedule_product_id": "当前生产计划已完成，不能继续报工。"})
    valid_lines = {
        item.pk: item for item in scheme.lines.select_for_update().select_related("work_item")
        .filter(status=WageSchemeLineStatus.ACTIVE)
    }
    employees = {item.pk: item for item in locked_active_employees(WorkshopEmployee.objects.filter(
        pk__in=[row["workshop_employee_id"] for row in data["lines"]], workshop=scheme.workshop,
    ))}
    if len(employees) != len(set(row["workshop_employee_id"] for row in data["lines"])):
        raise ValidationError({"lines": "存在非本车间或无效员工。"})
    is_assembly = scheme.workshop.name == "装配车间"
    built = []
    total = Decimal("0.00")
    for index, row in enumerate(data["lines"], start=1):
        scheme_line = valid_lines.get(row["scheme_line_id"])
        if not scheme_line:
            raise ValidationError({"lines": f"第 {index} 行工价明细无效或已作废。"})
        production_line = row.get("production_line")
        if is_assembly and production_line not in {1, 2, 3}:
            raise ValidationError({"lines": f"第 {index} 行装配报工必须选择生产线。"})
        if not is_assembly and production_line is not None:
            raise ValidationError({"lines": f"第 {index} 行非装配车间不能填写生产线。"})
        amount = (row["quantity"] * scheme_line.declared_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount > MAX_WORK_REPORT_AMOUNT:
            raise ValidationError({"lines": f"第 {index} 行金额超出系统可保存范围。"})
        total += amount
        if total > MAX_WORK_REPORT_AMOUNT:
            raise ValidationError({"lines": "本次报工金额合计超出系统可保存范围。"})
        built.append((index, row, scheme_line, employees[row["workshop_employee_id"]], amount))
    active_lines = list(valid_lines.values())
    required_by_work_item = {}
    for line in active_lines:
        if line.required_quantity_snapshot is None or line.required_quantity_snapshot <= 0:
            raise ValidationError({"scheme_id": "工价方案缺少需完成次数，请先变更并重新批准工价方案。"})
        required_by_work_item[line.work_item_id] = line.required_quantity_snapshot

    existing_lines = WorkReportLine.objects.filter(
        report__schedule_product_id=schedule_product.pk,
        report__workshop_id=scheme.workshop_id,
        work_item_id__in=required_by_work_item,
    )
    if exclude_report_id:
        existing_lines = existing_lines.exclude(report_id=exclude_report_id)
    existing_by_work_item = {
        row["work_item_id"]: row["quantity"]
        for row in existing_lines.values("work_item_id").annotate(quantity=Sum("quantity"))
    }
    submitted_by_work_item = {}
    for _, row, scheme_line, _, _ in built:
        submitted_by_work_item[scheme_line.work_item_id] = (
            submitted_by_work_item.get(scheme_line.work_item_id, Decimal("0")) + row["quantity"]
        )
    for work_item_id, submitted_quantity in submitted_by_work_item.items():
        required = required_by_work_item[work_item_id]
        already_reported = existing_by_work_item.get(work_item_id, Decimal("0"))
        remaining = required - already_reported
        if submitted_quantity > remaining:
            line = valid_lines[next(
                line_id for line_id, item in valid_lines.items() if item.work_item_id == work_item_id
            )]
            raise ValidationError({
                "lines": (
                    f"“{line.display_name_snapshot} / {line.operation_name_snapshot}”"
                    f"剩余可报 {max(remaining, Decimal('0'))}，本次不能报 {submitted_quantity}。"
                )
            })
    plan_will_complete = all(
        existing_by_work_item.get(work_item_id, Decimal("0"))
        + submitted_by_work_item.get(work_item_id, Decimal("0")) >= required
        for work_item_id, required in required_by_work_item.items()
    )
    if plan_will_complete and not data.get("confirm_plan_completion", False):
        raise ValidationError({
            "confirm_plan_completion": "所有报工数量均已完成，请确认完成当前生产计划后再保存。"
        })
    return scheme, built, total, plan_will_complete


def _work_report_line_instances(*, report, schedule_product, built):
    def build_line(index, row, scheme_line, employee, amount):
        order_quantity = schedule_product.source_quantity_snapshot
        return WorkReportLine(
            report=report, line_number=index, scheme_line=scheme_line, work_item=scheme_line.work_item,
            workshop_employee=employee, production_line=row.get("production_line"), quantity=row["quantity"],
            order_quantity_snapshot=order_quantity,
            required_quantity_snapshot=scheme_line.required_quantity_snapshot,
            unit_price_snapshot=scheme_line.declared_price, amount=amount,
            display_name_snapshot=scheme_line.display_name_snapshot,
            craft_name_snapshot=scheme_line.craft_name_snapshot,
            operation_name_snapshot=scheme_line.operation_name_snapshot,
            unit_name_snapshot=scheme_line.unit_name_snapshot, employee_name_snapshot=employee.name,
        )

    return [
        build_line(index, row, scheme_line, employee, amount)
        for index, row, scheme_line, employee, amount in built
    ]


def _update_plan_execution(*, schedule_product, scheme, completed, actor):
    execution, _ = WorkshopPlanExecution.objects.select_for_update().get_or_create(
        schedule_product=schedule_product,
        craft=scheme.scope_craft,
        defaults={"status": WorkshopPlanStatus.IN_PROGRESS},
    )
    execution.status = WorkshopPlanStatus.COMPLETED if completed else WorkshopPlanStatus.IN_PROGRESS
    execution.completed_at = timezone.now() if completed else None
    execution.completed_by_employee = actor if completed else None
    execution.save(update_fields=[
        "status", "completed_at", "completed_by_employee", "updated_at",
    ])


def _locked_schedule_product(schedule_product_id):
    source = ProductionScheduleProduct.objects.filter(pk=schedule_product_id).values(
        "schedule_id", "product_line_id", "product_line__production_task_id"
    ).first()
    if not source:
        return None
    # 与排产编辑/作废保持同一锁顺序，且每次仅锁目标表，避免 JOIN 锁造成环形等待。
    schedule = ProductionSchedule.objects.select_for_update(of=("self",)).filter(
        pk=source["schedule_id"]
    ).first()
    if not schedule:
        return None
    ProductionTask.objects.select_for_update(of=("self",)).filter(
        pk=source["product_line__production_task_id"]
    ).get()
    ProductionTaskProduct.objects.select_for_update(of=("self",)).filter(
        pk=source["product_line_id"]
    ).get()
    return ProductionScheduleProduct.objects.select_for_update(of=("self",)).select_related(
        "schedule", "product_line__production_task"
    ).filter(pk=schedule_product_id).first()


@transaction.atomic
def create_work_report(*, data, actor, request=None):
    if request is not None:
        requested_workshop = WageScheme.objects.get(pk=data["scheme_id"]).workshop_id
        require_workshop(request, "workshop_reporting.add_workreport", requested_workshop)
    request_id = data["client_request_id"]
    request_hash = payload_hash(data)
    requested_scope = WageScheme.objects.filter(pk=data['scheme_id']).first()
    _lock_tube_report_scope(data['schedule_product_id'], requested_scope)
    _lock_sewing_report_scope(data['schedule_product_id'], requested_scope)
    # Serialize replay, edit and deletion with the existing schedule/product lock order.
    schedule_product = _locked_schedule_product(data["schedule_product_id"]) if history_enabled() else None
    existing = existing_submission(request_id, request_hash)
    if existing:
        return existing
    if not history_enabled():
        schedule_product = _locked_schedule_product(data["schedule_product_id"])
    if not schedule_product or schedule_product.removed_at is not None or schedule_product.schedule.record_status != ScheduleStatus.ACTIVE:
        raise ValidationError({"schedule_product_id": "排产产品不存在或已失效。"})
    requested_scheme = WageScheme.objects.select_for_update().filter(pk=data["scheme_id"]).first()
    if not requested_scheme:
        raise ValidationError({"scheme_id": "工价方案不存在。"})
    scheme, built, total, plan_will_complete = _validated_work_report_lines(
        schedule_product=schedule_product, requested_scheme=requested_scheme, data=data
    )
    try:
        # 唯一键竞争只回滚到内层保存点，外层事务仍可安全读取先提交的幂等结果。
        with transaction.atomic():
            report = WorkReport.objects.create(
                report_number=next_business_number("WORK_REPORT", data["production_date"]),
                production_date=data["production_date"], product_line=schedule_product.product_line,
                task_number_snapshot=schedule_product.product_line.production_task.task_number,
                order_number_snapshot=schedule_product.product_line.production_task.order_number,
                product_name_snapshot=scheme.product_name_snapshot,
                product_number_snapshot=scheme.product_number_snapshot,
                recorder_name_snapshot=actor.display_name,
                schedule_product=schedule_product, workshop=scheme.workshop, scheme=scheme,
                scheme_version_snapshot=scheme.version, recorder_employee=actor, total_amount=total,
                updated_by_employee=actor,
                client_request_id=request_id, request_payload_hash=request_hash,
                completed_plan=plan_will_complete,
            )
            WorkReportLine.objects.bulk_create(_work_report_line_instances(
                report=report, schedule_product=schedule_product, built=built
            ))
            remember_report(report)
            _update_plan_execution(
                schedule_product=schedule_product, scheme=scheme,
                completed=plan_will_complete, actor=actor,
            )
            from apps.wecom.workshop_notifications import report_saved
            report_saved(report, actor)
        return report
    except IntegrityError as exc:
        existing = existing_submission(request_id, request_hash)
        if existing:
            return existing
        raise Conflict("报工提交标识发生冲突。") from exc


@transaction.atomic
def update_work_report(*, report_id, data, actor, request):
    current = WorkReport.objects.select_related('scheme').filter(pk=report_id).first()
    if not current:
        raise Http404('报工记录不存在或已删除。')
    tube_scope = _lock_tube_report_scope(current.schedule_product_id, current.scheme)
    sewing_scope = _lock_sewing_report_scope(current.schedule_product_id, current.scheme)
    requested_scope = WageScheme.objects.filter(pk=data['scheme_id']).first()
    if requested_scope and not tube_scope:
        tube_scope = _lock_tube_report_scope(current.schedule_product_id, requested_scope)
    if requested_scope and not sewing_scope:
        sewing_scope = _lock_sewing_report_scope(current.schedule_product_id, requested_scope)
    schedule_product = _locked_schedule_product(current.schedule_product_id)
    if not schedule_product or schedule_product.removed_at is not None or schedule_product.schedule.record_status != ScheduleStatus.ACTIVE:
        raise ValidationError({"schedule_product_id": "原排产产品不存在或已失效，不能直接编辑。"})
    report = WorkReport.objects.select_for_update().filter(pk=report_id).first()
    if report is None:
        raise Http404('报工记录已被删除，请刷新列表。')
    require_workshop(request, "workshop_reporting.change_workreport", report.workshop_id)
    require_matching_etag(request, report)
    remember_report(report)
    if data["schedule_product_id"] != report.schedule_product_id:
        raise ValidationError({"schedule_product_id": "编辑报工不能更换原排产产品。"})
    requested_scheme = WageScheme.objects.select_for_update().filter(pk=data["scheme_id"]).first()
    if not requested_scheme:
        raise ValidationError({"scheme_id": "工价方案不存在。"})
    scheme, built, total, plan_will_complete = _validated_work_report_lines(
        schedule_product=schedule_product, requested_scheme=requested_scheme, data=data,
        exclude_report_id=report.pk,
    )
    if scheme.workshop_id != report.workshop_id:
        raise ValidationError({"scheme_id": "编辑报工不能更换原车间。"})
    from .deletion_services import _snapshot
    before_snapshot = _snapshot(report)
    from apps.inventory.assembly_reporting_limits import is_assembly_report, assert_reports_cover_receipts
    was_assembly = is_assembly_report(report)
    report.lines.all().delete()
    report.production_date = data["production_date"]
    report.scheme = scheme
    report.scheme_version_snapshot = scheme.version
    report.total_amount = total
    report.completed_plan = plan_will_complete
    report.revision += 1
    report.updated_by_employee = actor
    report.save(update_fields=[
        "production_date", "scheme", "scheme_version_snapshot", "total_amount", "completed_plan", "revision",
        "updated_by_employee", "updated_at",
    ])
    WorkReportLine.objects.bulk_create(_work_report_line_instances(
        report=report, schedule_product=schedule_product, built=built
    ))
    if was_assembly or is_assembly_report(report):
        assert_reports_cover_receipts(schedule_product.product_line)
    if tube_scope:
        from apps.inventory.tube_processing_services import assert_tube_reports_cover_usage
        assert_tube_reports_cover_usage(schedule_product.product_line_id)
    if sewing_scope:
        from apps.inventory.sewing_processing_services import assert_sewing_reports_cover_usage
        assert_sewing_reports_cover_usage(schedule_product.product_line_id)
    remember_report(report)
    _update_plan_execution(
        schedule_product=schedule_product, scheme=scheme,
        completed=plan_will_complete, actor=actor,
    )
    from apps.core.audit import write_audit_log
    write_audit_log(object_type="WORK_REPORT", object_id=report.pk, action="UPDATE", actor_employee=actor,
        before_data=before_snapshot, after_data=_snapshot(report), request=request)
    from apps.wecom.workshop_change_notifications import report_corrected
    report_corrected(report, actor)
    return report
