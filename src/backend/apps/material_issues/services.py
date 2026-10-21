from apps.inventory.public_stock_cutover import stock_write_transaction
import hashlib
import json
from decimal import Decimal

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.numbering import next_business_number
from apps.boms.material_attributes import bom_attribute_fields, merge_bom_attribute_fields
from apps.inventory.models import MaterialStockQuality, SemiFinishedStockBalance
from apps.inventory.public_stock_mode import public_issues_enabled, require_document_stock_mode
from apps.inventory.stock_services import (
    debit_material_stock,
    debit_semi_finished_stock,
)
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from apps.production_scheduling.models import (
    ProductionSchedule,
    ProductionScheduleProduct,
    ProductionScheduleProductCraft,
    ScheduleStatus,
)
from apps.workshop_config.models import (
    CraftType,
    PlanCategory,
    RecordStatus,
    Workshop,
    WorkshopEmployee,
)
from apps.workshop_config.selectors import active_employees, locked_active_employees

from .models import (
    MaterialIssue,
    MaterialIssueAction,
    MaterialIssueAuditEvent,
    MaterialIssueLine,
    MaterialIssueStatus,
    OrderMaterialRequirement,
)
from .requirements import build_requirement_specs, sync_order_requirements
from .material_flow import (sync_selected_pipes, pipe_line_snapshot, semi_errors,
    validate_pipe_lines, lock_issue_stock, auto_allocate_pipe_lines, issue_pipe_line, line_stock, line_flow_data)
from .scopes import filter_blockers_for_scope, material_section_codes_for_issue


EDITABLE_STATUSES = {MaterialIssueStatus.DRAFT, MaterialIssueStatus.RETURNED}
ELIGIBLE_TASK_STATUSES = {ProductionTaskStatus.READY, ProductionTaskStatus.IN_PRODUCTION}
PLAN_WORKSHOP_NAMES = {
    PlanCategory.METAL: "金工车间",
    PlanCategory.CUTTING: "车缝车间",
    PlanCategory.SEWING: "车缝车间",
    PlanCategory.ASSEMBLY: "装配车间",
}


def is_pipe_semi_balance(balance):
    """管材身份取 BOM 所属分组，不取可能被修改或清空的原料切割参数。"""
    return balance.bom_line.section.title.strip() == "管材类"


def _semi_quantity_errors(balance, quantity):
    errors = semi_errors(balance, quantity)
    if is_pipe_semi_balance(balance) and quantity != quantity.to_integral_value() and "INTEGER_REQUIRED" not in errors:
        errors.append("INTEGER_REQUIRED")
    return errors


class MaterialIssueValidationError(ValidationError):
    def __init__(self, detail, *, code, meta=None):
        self.api_error_code = code
        if meta is not None:
            self.error_meta = meta
        super().__init__(detail)


class MaterialIssueConflict(Conflict):
    def __init__(self, detail, *, code="INVALID_STATE", meta=None):
        self.api_error_code = code
        if meta is not None:
            self.error_meta = meta
        super().__init__(detail)


def pending_issue_quantities(*, requirement_ids=(), semi_balance_ids=(), exclude_issue_id=None, exclude_tube_order_id=None):
    """统计已经提交、尚未出库的领料数量；草稿和退回单不占用额度。"""
    requirement_ids = tuple(requirement_ids)
    lines = MaterialIssueLine.objects.filter(issue__status=MaterialIssueStatus.PENDING_REVIEW)
    if exclude_issue_id:
        lines = lines.exclude(issue_id=exclude_issue_id)
    raw_rows = (
        lines.filter(requirement_id__in=list(requirement_ids), requirement_id__isnull=False)
        .values("requirement_id")
        .annotate(quantity=Sum("requested_quantity"))
    )
    semi_rows = (
        lines.filter(semi_finished_balance_id__in=list(semi_balance_ids), semi_finished_balance_id__isnull=False)
        .values("semi_finished_balance_id")
        .annotate(quantity=Sum("requested_quantity"))
    )
    raw_pending = {item["requirement_id"]: item["quantity"] or Decimal("0") for item in raw_rows}
    from apps.inventory.tube_outsourcing_reservations import tube_material_reserved_quantities
    tube_pending, _ = tube_material_reserved_quantities(requirement_ids=requirement_ids,
        exclude_order_id=exclude_tube_order_id)
    for key, value in tube_pending.items():
        raw_pending[key] = raw_pending.get(key, Decimal(0)) + value
    return (
        raw_pending,
        {item["semi_finished_balance_id"]: item["quantity"] or Decimal("0") for item in semi_rows},
    )


def _require_issue_owner(issue, actor_employee, request):
    if request.user.is_superuser or issue.created_by_employee_id == actor_employee.pk:
        return
    from apps.access_control.sales_policy import access_for
    from apps.access_control.resource_scopes import current_permission
    code = current_permission(request, 'material_issues.change_materialissue')
    access = access_for(request)
    if access['active'] and 'MODULE' in access['actions'].get(code, {}).get('scopes', []):
        return
    raise PermissionDenied("只有制单人可以修改或提交该领料单。")


def _payload_hash(value):
    encoded = json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False))


def _issue_number():
    return next_business_number("MATERIAL_ISSUE")


def _material_color(material):
    return material.color.color_name if material.color_id else material.color_snapshot


def _event_snapshot(issue):
    return {
        "issue_number": issue.issue_number,
        "status": issue.status,
        "version": issue.version,
        "production_task_id": str(issue.production_task_id) if issue.production_task_id else None,
        "product_line_id": str(issue.product_line_id) if issue.product_line_id else None,
        "workshop_id": str(issue.workshop_id) if issue.workshop_id else None,
        "recipient_workshop_employee_id": (
            str(issue.recipient_workshop_employee_id) if issue.recipient_workshop_employee_id else None
        ),
        "issue_at": issue.issue_at,
        "remark": issue.remark,
        "lines": [
            {
                "requirement_id": str(line.requirement_id or line.semi_requirement_id or line.semi_finished_balance_id),
                "line_type": line.line_type,
                "requested_quantity": str(line.requested_quantity),
                **line_flow_data(line),
            }
            for line in issue.lines.all().order_by("line_number", "id")
        ],
    }


def _record_event(
    issue,
    action,
    actor_employee,
    *,
    reason="",
    request_id=None,
    request_hash="",
    plan_source=None,
    snapshot_extra=None,
):
    snapshot = _event_snapshot(issue)
    if plan_source:
        snapshot["plan_source"] = plan_source
    if snapshot_extra:
        snapshot.update(snapshot_extra)
    return MaterialIssueAuditEvent.objects.create(
        issue=issue,
        action=action,
        issue_version=issue.version,
        actor_employee=actor_employee,
        reason=reason,
        request_id=request_id,
        request_payload_hash=request_hash,
        snapshot=_json_safe(snapshot),
    )


def _validate_plan_source(*, schedule_product_id, plan_category, production_task_id, product_line_id, workshop_id):
    if plan_category not in PLAN_WORKSHOP_NAMES:
        raise ValidationError({"plan_category": "该作业计划暂未开放生产领料。"})
    try:
        source_schedule_id = ProductionScheduleProduct.objects.only("schedule_id").get(pk=schedule_product_id).schedule_id
        schedule = ProductionSchedule.objects.select_for_update().get(pk=source_schedule_id)
        schedule_product = ProductionScheduleProduct.objects.select_for_update().get(pk=schedule_product_id)
    except (ProductionScheduleProduct.DoesNotExist, ProductionSchedule.DoesNotExist) as exc:
        raise ValidationError({"schedule_product_id": "作业计划产品不存在或已失效。"}) from exc
    if schedule.record_status != ScheduleStatus.ACTIVE or schedule_product.removed_at is not None:
        raise ValidationError({"schedule_product_id": "作业计划已作废或该产品已移除。"})
    if schedule.production_task_id != production_task_id or schedule_product.product_line_id != product_line_id:
        raise ValidationError({"schedule_product_id": "作业计划与所选生产订单或产品不一致。"})
    expected_workshop_name = PLAN_WORKSHOP_NAMES[plan_category]
    if not Workshop.objects.filter(pk=workshop_id, name=expected_workshop_name, status=RecordStatus.ACTIVE).exists():
        raise ValidationError({"workshop_id": "领料车间与作业计划类型不一致。"})
    has_category = ProductionScheduleProductCraft.objects.select_for_update().filter(
        schedule_product=schedule_product,
        removed_at__isnull=True,
        craft_type_snapshot=CraftType.INTERNAL,
        plan_category=plan_category,
    ).exists()
    if not has_category:
        raise ValidationError({"plan_category": "该产品当前排产中不存在对应的厂内作业计划。"})
    return {
        "schedule_id": str(schedule.pk),
        "schedule_product_id": str(schedule_product.pk),
        "plan_category": plan_category,
    }


def _validate_relations(issue, *, require_complete=False, lock_employee=False):
    if require_complete and not issue.production_task_id:
        raise ValidationError({"production_task_id": "提交前必须选择生产订单。"})
    if issue.production_task_id:
        if issue.production_task.archived_at is not None or issue.production_task.status not in ELIGIBLE_TASK_STATUSES:
            raise ValidationError({"production_task_id": "生产订单当前不可领料。"})
    if require_complete and not issue.product_line_id:
        raise ValidationError({"product_line_id": "提交前必须选择产品。"})
    if issue.product_line_id and issue.product_line.production_task_id != issue.production_task_id:
        raise ValidationError({"product_line_id": "所选产品不属于该生产订单。"})
    if require_complete and not issue.workshop_id:
        raise ValidationError({"workshop_id": "提交前必须选择车间。"})
    if issue.workshop_id and issue.workshop.status != RecordStatus.ACTIVE:
        raise ValidationError({"workshop_id": "所选车间已停用。"})
    if issue.workshop_id and material_section_codes_for_issue(issue) is None:
        raise ValidationError({"workshop_id": "该车间暂未开放生产领料。"})
    if require_complete and not issue.recipient_workshop_employee_id:
        raise ValidationError({"recipient_workshop_employee_id": "提交前必须选择领料人。"})
    if issue.recipient_workshop_employee_id:
        candidates = WorkshopEmployee.objects.filter(pk=issue.recipient_workshop_employee_id)
        eligible = locked_active_employees(candidates) if lock_employee else list(active_employees(candidates))
        if not eligible:
            raise ValidationError({"recipient_workshop_employee_id": "领料人已停用、离职或关联员工不可用。"})
        recipient = eligible[0]
        issue.recipient_workshop_employee = recipient
        if recipient.workshop_id != issue.workshop_id:
            raise ValidationError({"recipient_workshop_employee_id": "领料人不属于所选车间。"})
    if require_complete and issue.issue_at is None:
        raise ValidationError({"issue_at": "提交前必须填写领料时间。"})


def _apply_header(issue, data):
    relation_models = {
        "production_task_id": ProductionTask,
        "product_line_id": ProductionTaskProduct,
        "workshop_id": Workshop,
        "recipient_workshop_employee_id": WorkshopEmployee,
    }
    for field, model in relation_models.items():
        if field in data:
            value = data.get(field)
            setattr(issue, field, value)
            if value:
                try:
                    setattr(issue, field[:-3], model.objects.get(pk=value))
                except model.DoesNotExist as exc:
                    raise ValidationError({field: "所选记录不存在。"}) from exc
    for field in ("issue_at", "remark"):
        if field in data:
            setattr(issue, field, data[field])


def _replace_lines(issue, line_inputs):
    if issue.stock_mode == "PUBLIC_V2":
        from .public_issue_services import replace_public_issue_lines
        return replace_public_issue_lines(issue, line_inputs)
    issue.lines.all().delete()
    if not line_inputs:
        return
    if not issue.production_task_id:
        raise ValidationError({"lines": "添加领料明细前必须先选择生产订单。"})
    if not issue.workshop_id:
        raise ValidationError({"lines": "添加领料明细前必须先选择领料车间。"})
    allowed_section_codes = material_section_codes_for_issue(issue)
    if allowed_section_codes is None:
        raise ValidationError({"workshop_id": "该车间暂未开放生产领料。"})
    semi_balance_map = {
        item.pk: item
        for item in SemiFinishedStockBalance.objects.select_related(
            "bom_line__section", "completed_craft", "unit", "zone__warehouse"
        ).filter(
            production_task_id=issue.production_task_id,
            product_line_id=issue.product_line_id,
            quality=MaterialStockQuality.AVAILABLE,
            quantity__gt=0,
        )
    }
    requested_ids = {row["requirement_id"] for row in line_inputs}
    requirement_map, revision_hash = {}, ""
    if requested_ids - semi_balance_map.keys():
        _, requirements, _, revision_hash = sync_order_requirements(issue.production_task_id)
        requirements += sync_selected_pipes(issue, requested_ids)
        requirement_map = {item.pk: item for item in requirements}
    seen = set()
    created = []
    for index, item in enumerate(line_inputs, start=1):
        requirement = requirement_map.get(item["requirement_id"])
        semi_balance = semi_balance_map.get(item["requirement_id"])
        if requirement is None and semi_balance is None:
            raise ValidationError({"lines": f"第 {index} 行需求不存在或已失效。"})
        section_code = requirement.section_code if requirement else "SEMI"
        if section_code not in allowed_section_codes:
            raise ValidationError({"lines": f"第 {index} 行材料不属于所选车间的可领范围。"})
        identity = requirement.pk if requirement else semi_balance.pk
        if identity in seen:
            raise ValidationError({"lines": "同一订单材料需求不能重复添加。"})
        seen.add(identity)
        if requirement and issue.product_line_id and not requirement.contributions.filter(
            is_current=True, product_line_id=issue.product_line_id
        ).exists():
            raise ValidationError({"lines": f"第 {index} 行材料不属于所选产品。"})
        quantity = item["requested_quantity"]
        if requirement:
            material = requirement.raw_material
            requirement_attributes = merge_bom_attribute_fields(
                bom_attribute_fields(contribution.bom_line)
                for contribution in requirement.contributions.filter(
                    is_current=True, product_line_id=issue.product_line_id
                ).select_related("bom_line__section")
            )
            conversion_snapshot = pipe_line_snapshot(requirement) if requirement.measurement_kind == "PIPE" else {}
            conversion_snapshot["bom_attributes"] = requirement_attributes
            created.append(MaterialIssueLine(
                issue=issue,
                line_number=index,
                requirement=requirement,
                line_type=requirement.line_type,
                raw_material=material,
                unit=requirement.unit,
                section_code_snapshot=requirement.section_code,
                material_number_snapshot=material.material_number,
                material_name_snapshot=material.material_name,
                specification_snapshot=material.specification,
                color_snapshot=_material_color(material),
                unit_snapshot=requirement.unit.unit_name,
                requested_quantity=quantity,
                conversion_snapshot=conversion_snapshot,
            ))
        else:
            if _semi_quantity_errors(semi_balance, quantity):
                raise ValidationError({"lines": "半成品必须来自有效合格库区，支/套数量须为正整数。"})
            component = semi_balance.bom_line
            pipe_semi = is_pipe_semi_balance(semi_balance)
            component_name = component.part_name or component.material or component.raw_material
            bom_attributes = bom_attribute_fields(component)
            completed_craft = semi_balance.completed_craft.name
            if getattr(semi_balance.completed_craft, "outsourcing_code", "") == "POWDER_COATING":
                bom_attributes = [field for field in bom_attributes if field.get("key") != "spray_color"]
                bom_attributes.append({"key": "spray_color", "label": "喷塑颜色", "value": semi_balance.color_snapshot})
            created.append(MaterialIssueLine(
                issue=issue,
                line_number=index,
                requirement=None,
                line_type="SEMI",
                raw_material=None,
                semi_finished_balance=semi_balance,
                unit=semi_balance.unit,
                section_code_snapshot="SEMI",
                material_number_snapshot=f"SEMI-{str(component.pk)[:8].upper()}",
                material_name_snapshot=component_name,
                specification_snapshot=component.specification,
                color_snapshot=semi_balance.color_snapshot,
                unit_snapshot=semi_balance.unit.unit_name,
                requested_quantity=quantity,
                conversion_snapshot={"kind": "SEMI_PIPE_PIECES" if pipe_semi else "SEMI",
                    "bom_attributes": bom_attributes,
                    "component_identity": str(component.component_identity),
                    **({"integer_required": True, "whole_bar_required": False,
                        "raw_deducted_bar_count": "0", "raw_deducted_meters": "0.00"} if pipe_semi else {}),
                    "completed_craft": completed_craft,
                    "warehouse_zone": f"{semi_balance.zone.warehouse.warehouse_name} / {semi_balance.zone.zone_name}",
                    "quality": semi_balance.quality},
            ))
    MaterialIssueLine.objects.bulk_create(created)
    issue.source_revision_hash = revision_hash
    issue.save(update_fields=["source_revision_hash", "updated_at"])


@stock_write_transaction
def create_issue(*, validated_data, actor_employee, request=None):
    if request is not None:
        from apps.access_control.workshop_scopes import require_task_workshop
        require_task_workshop(request, 'material_issues.add_materialissue', validated_data.get('production_task_id'), validated_data.get('workshop_id'), owner_id=actor_employee.pk)
    payload_hash = _payload_hash(validated_data)
    request_id = validated_data["client_request_id"]
    existing = MaterialIssue.objects.filter(client_request_id=request_id).first()
    if existing:
        if request is not None:
            require_task_workshop(request, 'material_issues.add_materialissue', existing.production_task_id, existing.workshop_id, owner_id=existing.created_by_employee_id)
        if existing.created_by_employee_id != actor_employee.pk:
            raise MaterialIssueConflict("相同提交标识已由其他制单人使用。")
        if existing.request_payload_hash != payload_hash:
            raise MaterialIssueConflict("同一提交标识不能用于不同的领料单内容。")
        return existing
    line_inputs = validated_data.pop("lines", [])
    schedule_product_id = validated_data.pop("schedule_product_id")
    plan_category = validated_data.pop("plan_category")
    plan_source = _validate_plan_source(
        schedule_product_id=schedule_product_id,
        plan_category=plan_category,
        production_task_id=validated_data.get("production_task_id"),
        product_line_id=validated_data.get("product_line_id"),
        workshop_id=validated_data.get("workshop_id"),
    )
    try:
        with transaction.atomic():
            issue = MaterialIssue(
                issue_number=_issue_number(),
                stock_mode="PUBLIC_V2" if public_issues_enabled() else "LEGACY",
                client_request_id=validated_data.pop("client_request_id"),
                request_payload_hash=payload_hash,
                created_by_employee=actor_employee,
                updated_by_employee=actor_employee,
            )
            issue._material_issue_plan_category = plan_category
            _apply_header(issue, validated_data)
            _validate_relations(issue, lock_employee=True)
            # client_request_id 的并发唯一性由数据库约束裁决，避免 ORM 预检与插入之间的竞态。
            issue.full_clean(validate_unique=False)
            issue.save()
            _replace_lines(issue, line_inputs)
            _record_event(issue, MaterialIssueAction.CREATED, actor_employee, plan_source=plan_source)
            return issue
    except IntegrityError as exc:
        existing = MaterialIssue.objects.filter(client_request_id=request_id).first()
        if existing:
            if existing.request_payload_hash == payload_hash and existing.created_by_employee_id == actor_employee.pk:
                return existing
            raise MaterialIssueConflict("同一提交标识不能用于不同的领料单内容。") from exc
        raise exc


@stock_write_transaction
def update_issue(*, issue_id, validated_data, actor_employee, request):
    issue = MaterialIssue.objects.select_for_update().get(pk=issue_id)
    from apps.access_control.workshop_scopes import require_task_workshop
    require_task_workshop(request, 'material_issues.change_materialissue', issue.production_task_id, issue.workshop_id, owner_id=issue.created_by_employee_id, legacy_global='material_issues.view_all_materialissue')
    require_task_workshop(request, 'material_issues.change_materialissue', validated_data.get('production_task_id', issue.production_task_id), validated_data.get('workshop_id', issue.workshop_id), owner_id=issue.created_by_employee_id, legacy_global='material_issues.view_all_materialissue')
    _require_issue_owner(issue, actor_employee, request)
    require_matching_etag(request, issue)
    if issue.status not in EDITABLE_STATUSES:
        raise MaterialIssueConflict("当前状态不允许修改领料单。")
    line_inputs = validated_data.pop("lines", None)
    previous_scope = (issue.production_task_id, issue.product_line_id)
    _apply_header(issue, validated_data)
    created_event = issue.audit_events.filter(action=MaterialIssueAction.CREATED).order_by("created_at", "id").first()
    plan_source = (created_event.snapshot or {}).get("plan_source") if created_event else None
    if plan_source:
        issue._material_issue_plan_category = plan_source.get("plan_category", "")
        _validate_plan_source(
            schedule_product_id=plan_source.get("schedule_product_id"),
            plan_category=plan_source.get("plan_category"),
            production_task_id=issue.production_task_id,
            product_line_id=issue.product_line_id,
            workshop_id=issue.workshop_id,
        )
    if (
        line_inputs is None
        and previous_scope != (issue.production_task_id, issue.product_line_id)
        and issue.lines.exists()
    ):
        raise ValidationError({"lines": "更换生产订单或产品时必须同时重新提交领料明细。"})
    _validate_relations(issue, lock_employee=True)
    issue.version += 1
    issue.updated_by_employee = actor_employee
    issue.save()
    if line_inputs is not None:
        _replace_lines(issue, line_inputs)
    _record_event(issue, MaterialIssueAction.UPDATED, actor_employee)
    return issue


def _validate_issue_quantities(issue, *, require_stock=True, include_pending=False):
    if issue.stock_mode == "PUBLIC_V2":
        from .public_issue_services import validate_public_issue
        return validate_public_issue(issue, include_pending=include_pending)["lines"]
    lines = list(issue.lines.select_related(
        "requirement", "raw_material", "unit", "semi_finished_balance__bom_line__section"
    ).order_by("line_number", "id"))
    if not lines:
        raise ValidationError({"lines": "提交前至少选择一项领料明细。"})
    errors = validate_pipe_lines(lines)
    pending_raw = {}
    pending_semi = {}
    if include_pending:
        pending_raw, pending_semi = pending_issue_quantities(
            requirement_ids=[line.requirement_id for line in lines if line.requirement_id],
            semi_balance_ids=[line.semi_finished_balance_id for line in lines if line.semi_finished_balance_id],
            exclude_issue_id=issue.pk,
        )
    allowed_section_codes = material_section_codes_for_issue(issue)
    if allowed_section_codes is None:
        raise ValidationError({"workshop_id": "该车间暂未开放生产领料。"})
    for line in lines:
        if line.section_code_snapshot not in allowed_section_codes:
            errors.append({
                "code": "WORKSHOP_MATERIAL_SCOPE_INVALID",
                "line_id": str(line.pk),
                "detail": "材料不属于当前领料车间的可领范围。",
            })
            continue
        if line.line_type == "SEMI":
            balance = line.semi_finished_balance
            if (
                balance.production_task_id != issue.production_task_id
                or balance.product_line_id != issue.product_line_id
            ):
                errors.append({
                    "code": "LINE_SCOPE_INVALID",
                    "line_id": str(line.pk),
                    "detail": "半成品库存身份不属于当前生产订单和产品。",
                })
                continue
            for code in _semi_quantity_errors(balance, line.requested_quantity):
                errors.append({"line_id": str(line.pk), "code": code, "detail": "半成品库存身份、库区或整数数量不符。"})
            stock = line.semi_finished_balance.quantity
            pending = pending_semi.get(line.semi_finished_balance_id, Decimal("0"))
            available_after_pending = max(stock - pending, Decimal("0"))
            if include_pending and pending > 0 and line.requested_quantity > available_after_pending:
                errors.append({
                    "code": "PENDING_ISSUE_CONFLICT",
                    "line_id": str(line.pk),
                    "detail": "申请数量与其他待仓库审核数量合计超过可用半成品库存。",
                    "pending_issue_quantity": str(pending),
                    "available_stock": str(available_after_pending),
                })
            elif require_stock and line.requested_quantity > stock:
                errors.append({
                    "code": "STOCK_INSUFFICIENT",
                    "line_id": str(line.pk),
                    "detail": "申请数量超过该身份的合格半成品库存。",
                    "available_stock": str(stock),
                })
            continue
        requirement = line.requirement
        if (
            requirement.production_task_id != issue.production_task_id
            or not requirement.contributions.filter(
                is_current=True,
                product_line_id=issue.product_line_id,
            ).exists()
        ):
            errors.append({
                "code": "LINE_SCOPE_INVALID",
                "line_id": str(line.pk),
                "detail": "原料需求不属于当前生产订单和产品。",
            })
            continue
        pending = pending_raw.get(requirement.pk, Decimal("0"))
        remaining = (
            requirement.required_quantity
            - requirement.internal_issued_quantity
            - requirement.outsourcing_issued_quantity
            - pending
        )
        if line.requested_quantity > remaining:
            errors.append(
                {
                    "code": "PENDING_ISSUE_CONFLICT" if pending > 0 else "ORDER_ALLOWANCE_EXCEEDED",
                    "line_id": str(line.pk),
                    "detail": "已有待仓库审核的领料占用额度。" if pending > 0 else "申请数量超过生产订单剩余可领额度。",
                    "order_remaining": str(max(remaining, Decimal("0"))),
                    "pending_issue_quantity": str(pending),
                }
            )
        stock = line_stock(line)
        if require_stock and line.requested_quantity > stock:
            errors.append(
                {
                    "code": "STOCK_INSUFFICIENT",
                    "line_id": str(line.pk),
                    "detail": "申请数量超过合格公共可用库存。",
                    "available_stock": str(stock),
                }
            )
    if errors:
        code = errors[0]["code"]
        detail = "已有待仓库审核的领料占用额度，请刷新领料页面后重新填写。" if code == "PENDING_ISSUE_CONFLICT" else errors[0].get("detail", "领料明细校验未通过。")
        raise MaterialIssueValidationError(
            {"detail": detail, "lines": errors},
            code=code,
            meta={"retryable": True, "lines": errors},
        )
    return lines


def _validate_saved_plan(issue):
    event = issue.audit_events.filter(action=MaterialIssueAction.CREATED).order_by("created_at", "id").first()
    source = event.snapshot.get("plan_source") if event else None
    if source:
        _validate_plan_source(schedule_product_id=source.get("schedule_product_id"), plan_category=source.get("plan_category"),
            production_task_id=issue.production_task_id, product_line_id=issue.product_line_id, workshop_id=issue.workshop_id)


def _sync_issue_sources(issue):
    if issue.stock_mode == "PUBLIC_V2":
        from .public_issue_services import sync_public_issue_sources
        return sync_public_issue_sources(issue)
    raw_lines = list(issue.lines.filter(line_type="RAW").select_related("requirement"))
    if not raw_lines:
        return [], issue.source_revision_hash
    _, _, blockers, revision = sync_order_requirements(issue.production_task_id)
    requirements = sync_selected_pipes(issue, {line.requirement_id for line in raw_lines})
    by_id = {r.pk: r for r in requirements}
    for line in raw_lines:
        if line.conversion_snapshot.get("kind") == "PIPE":
            current = by_id.get(line.requirement_id)
            if current is None or current.source_revision_hash != line.conversion_snapshot.get("source_revision_hash"):
                raise MaterialIssueConflict("管材部位来源已变化，请刷新明细。", code="SOURCE_CHANGED")
    return [b for b in blockers if b["code"] != "PIPE_SERVICE_REQUIRED"], revision


@stock_write_transaction
def submit_issue(*, issue_id, actor_employee, request):
    issue = MaterialIssue.objects.select_for_update(of=("self",)).select_related(
        "production_task", "product_line", "workshop", "recipient_workshop_employee"
    ).get(pk=issue_id)
    from apps.access_control.workshop_scopes import require_task_workshop
    require_task_workshop(request, 'material_issues.submit_materialissue', issue.production_task_id, issue.workshop_id, owner_id=issue.created_by_employee_id, legacy_global='material_issues.view_all_materialissue')
    _require_issue_owner(issue, actor_employee, request)
    require_matching_etag(request, issue)
    if issue.status not in EDITABLE_STATUSES:
        raise MaterialIssueConflict("当前状态不允许提交审核。")
    require_document_stock_mode(issue, allow_issue_trial=True)
    _validate_saved_plan(issue)
    _validate_relations(issue, require_complete=True, lock_employee=True)
    blockers, revision_hash = _sync_issue_sources(issue)
    issue_lines = list(issue.lines.all())
    blockers = filter_blockers_for_scope(
        blockers,
        product_line_id=issue.product_line_id,
        section_codes=material_section_codes_for_issue(issue),
    )
    if blockers and any(line.line_type == "RAW" for line in issue_lines):
        code = blockers[0]["code"]
        raise MaterialIssueValidationError(
            {"detail": "订单材料需求仍有未解析项目。", "blockers": blockers},
            code=code,
            meta={"retryable": False, "blockers": blockers},
        )
    if any(line.line_type == "RAW" for line in issue_lines) and issue.source_revision_hash and issue.source_revision_hash != revision_hash:
        raise MaterialIssueConflict(
            "BOM 来源已经变化，请刷新领料明细后重新提交。",
            code="SOURCE_CHANGED",
            meta={"retryable": True},
        )
    if issue.stock_mode == "PUBLIC_V2":
        from .public_issue_services import validate_public_issue
        validate_public_issue(issue, include_pending=True, lock=True)
    else:
        _validate_issue_quantities(issue, include_pending=True)
    issue.status = MaterialIssueStatus.PENDING_REVIEW
    issue.submitted_by_employee = actor_employee
    issue.submitted_at = timezone.now()
    issue.updated_by_employee = actor_employee
    issue.version += 1
    issue.source_revision_hash = revision_hash
    issue.save()
    _record_event(issue, MaterialIssueAction.SUBMITTED, actor_employee)
    from apps.wecom.workshop_notifications import issue_submitted
    issue_submitted(issue, actor_employee)
    return issue


@stock_write_transaction
def return_issue(*, issue_id, reason, actor_employee, request):
    issue = MaterialIssue.objects.select_for_update().get(pk=issue_id)
    from apps.access_control.workshop_scopes import require_task_workshop
    require_task_workshop(request, 'material_issues.review_materialissue', issue.production_task_id, issue.workshop_id, owner_id=issue.created_by_employee_id, legacy_global='material_issues.view_all_materialissue')
    from apps.access_control.module_policy import prohibit_self_approval
    prohibit_self_approval(actor_employee, issue.submitted_by_employee_id)
    require_matching_etag(request, issue)
    if issue.status != MaterialIssueStatus.PENDING_REVIEW:
        raise MaterialIssueConflict("只有待仓库审核的领料单可以退回。")
    issue.status = MaterialIssueStatus.RETURNED
    issue.updated_by_employee = actor_employee
    issue.version += 1
    issue.save()
    _record_event(issue, MaterialIssueAction.RETURNED, actor_employee, reason=reason)
    return issue


@stock_write_transaction
def confirm_issue(*, issue_id, request_id, actor_employee, request):
    from apps.access_control.workshop_scopes import require_task_workshop
    from apps.outsourcing.material_flow import lock_request
    lock_request("material_issue_confirm", request_id)
    request_hash = _payload_hash({"issue_id": issue_id, "request_id": request_id})
    existing = MaterialIssueAuditEvent.objects.select_related("issue").filter(request_id=request_id).first()
    if existing:
        require_task_workshop(request, 'material_issues.review_materialissue', existing.issue.production_task_id, existing.issue.workshop_id, owner_id=existing.issue.created_by_employee_id, legacy_global='material_issues.view_all_materialissue')
        if existing.issue_id != issue_id or existing.request_payload_hash != request_hash:
            raise MaterialIssueConflict("相同审核请求标识已用于不同内容。")
        from apps.access_control.module_policy import prohibit_self_approval
        prohibit_self_approval(actor_employee, existing.issue.submitted_by_employee_id)
        return existing.issue

    issue = MaterialIssue.objects.select_for_update(of=("self",)).select_related(
        "production_task", "product_line", "workshop", "recipient_workshop_employee"
    ).get(pk=issue_id)
    require_task_workshop(request, 'material_issues.review_materialissue', issue.production_task_id, issue.workshop_id, owner_id=issue.created_by_employee_id, legacy_global='material_issues.view_all_materialissue')
    from apps.access_control.module_policy import prohibit_self_approval
    prohibit_self_approval(actor_employee, issue.submitted_by_employee_id)
    existing = MaterialIssueAuditEvent.objects.select_related("issue").filter(request_id=request_id).first()
    if existing:
        if existing.issue_id != issue_id or existing.request_payload_hash != request_hash:
            raise MaterialIssueConflict("相同审核请求标识已用于不同内容。")
        return existing.issue
    require_matching_etag(request, issue)
    if issue.status != MaterialIssueStatus.PENDING_REVIEW:
        raise MaterialIssueConflict("只有待仓库审核的领料单可以确认出库。")
    require_document_stock_mode(issue, allow_issue_trial=True)
    _validate_saved_plan(issue)
    issue.production_task = ProductionTask.objects.select_for_update().get(pk=issue.production_task_id)
    issue.product_line = ProductionTaskProduct.objects.select_for_update().get(pk=issue.product_line_id)
    issue.workshop = Workshop.objects.select_for_update().get(pk=issue.workshop_id)
    issue.recipient_workshop_employee = WorkshopEmployee.objects.select_for_update().get(
        pk=issue.recipient_workshop_employee_id
    )
    _validate_saved_plan(issue)
    _validate_relations(issue, require_complete=True, lock_employee=True)
    blockers, revision_hash = _sync_issue_sources(issue)
    issue_lines = list(issue.lines.all())
    blockers = filter_blockers_for_scope(
        blockers,
        product_line_id=issue.product_line_id,
        section_codes=material_section_codes_for_issue(issue),
    )
    if blockers and any(line.line_type == "RAW" for line in issue_lines):
        code = blockers[0]["code"]
        raise MaterialIssueValidationError(
            {"detail": "订单材料需求仍有未解析项目。", "blockers": blockers},
            code=code,
            meta={"retryable": False, "blockers": blockers},
        )
    if any(line.line_type == "RAW" for line in issue_lines) and issue.source_revision_hash != revision_hash:
        raise MaterialIssueConflict(
            "BOM 来源已经变化，请退回申请人刷新后重新提交。",
            code="SOURCE_CHANGED",
            meta={"retryable": True},
        )
    if issue.stock_mode == "PUBLIC_V2":
        from .public_issue_services import confirm_public_issue
        issued_line_snapshots = confirm_public_issue(issue, actor_employee)
        return _finish_issue(issue, actor_employee, request_id, request_hash, issued_line_snapshots)
    requirement_ids = sorted(
        [line.requirement_id for line in issue_lines if line.requirement_id],
        key=str,
    )
    locked_requirements = {
        item.pk: item
        for item in OrderMaterialRequirement.objects.select_for_update().filter(pk__in=requirement_ids).order_by("id")
    }
    lock_issue_stock(issue)
    semi_balance_ids = sorted(
        [line.semi_finished_balance_id for line in issue_lines if line.semi_finished_balance_id],
        key=str,
    )
    locked_semi_balances = {
        item.pk: item
        for item in SemiFinishedStockBalance.objects.select_for_update().filter(
            pk__in=semi_balance_ids
        ).order_by("id")
    }
    lines = list(issue.lines.select_related(
        "raw_material", "unit", "semi_finished_balance"
    ).order_by("line_type", "raw_material_id", "semi_finished_balance_id", "id"))
    for line in lines:
        if line.requirement_id:
            line.requirement = locked_requirements[line.requirement_id]
        if line.semi_finished_balance_id:
            line.semi_finished_balance = locked_semi_balances[line.semi_finished_balance_id]
    _validate_issue_quantities(issue)
    auto_allocate_pipe_lines(lines)
    issued_line_snapshots = []
    for line in lines:
        if line.line_type == "SEMI":
            remaining_after = line.semi_finished_balance.quantity - line.requested_quantity
            pipe_semi = is_pipe_semi_balance(line.semi_finished_balance)
            if pipe_semi:
                # 已切好的半成品只扣支数；旧待审核单确认时也不保存伪原料根米。
                line.conversion_snapshot = {key: value for key, value in line.conversion_snapshot.items()
                    if key not in {"pieces_per_bar", "raw_bar_length_m", "issued_bar_count", "issued_meters"}}
                line.conversion_snapshot.update({"kind": "SEMI_PIPE_PIECES", "integer_required": True,
                    "whole_bar_required": False, "issued_pieces": str(line.requested_quantity),
                    "raw_deducted_bar_count": "0", "raw_deducted_meters": "0.00"})
            debit_semi_finished_stock(
                balance_id=line.semi_finished_balance_id,
                quantity=line.requested_quantity,
                source_type="MATERIAL_ISSUE",
                source_id=issue.pk,
                source_line_id=line.pk,
                actor_employee=actor_employee,
                snapshot={
                    "issue_number": issue.issue_number,
                    "component": line.material_name_snapshot,
                    "completed_craft": line.semi_finished_balance.completed_craft.name,
                    "recipient": issue.recipient_workshop_employee.name,
                    "workshop": issue.workshop.name,
                    **({"issued_pieces": str(line.requested_quantity), "raw_deducted_bar_count": "0",
                        "raw_deducted_meters": "0.00"} if pipe_semi else {}),
                },
            )
            line.issued_quantity = line.requested_quantity
            line.save(update_fields=["issued_quantity", "conversion_snapshot", "updated_at"])
            issued_line_snapshots.append({
                "line_id": str(line.pk),
                "required_quantity": str(line.semi_finished_balance.quantity),
                "internal_issued_quantity": str(line.requested_quantity),
                "outsourcing_issued_quantity": "0",
                "order_remaining": str(remaining_after),
                "available_stock": str(remaining_after),
                "max_issue_quantity": str(remaining_after),
            })
            continue
        requirement = line.requirement
        if line.conversion_snapshot.get("kind") == "PIPE":
            issue_pipe_line(line, actor_employee)
        else:
            _debit_ordinary_line(issue, line, actor_employee)
        line.issued_quantity = line.requested_quantity
        line.save(update_fields=["issued_quantity", "updated_at"])
        remaining_after = requirement.required_quantity - requirement.internal_issued_quantity - requirement.outsourcing_issued_quantity
        stock_after = line_stock(line)
        issued_line_snapshots.append({
            "line_id": str(line.pk), "required_quantity": str(requirement.required_quantity),
            "internal_issued_quantity": str(requirement.internal_issued_quantity),
            "outsourcing_issued_quantity": str(requirement.outsourcing_issued_quantity),
            "order_remaining": str(max(remaining_after, Decimal(0))), "available_stock": str(stock_after),
            "max_issue_quantity": str(max(min(remaining_after, stock_after), Decimal(0))), **line_flow_data(line),
        })
    return _finish_issue(issue, actor_employee, request_id, request_hash, issued_line_snapshots)


def _finish_issue(issue, actor_employee, request_id, request_hash, issued_line_snapshots):
    issue.status = MaterialIssueStatus.ISSUED
    issue.issued_by_employee = actor_employee
    issue.issued_at = timezone.now()
    issue.updated_by_employee = actor_employee
    issue.version += 1
    issue.save()
    _record_event(issue, MaterialIssueAction.ISSUED, actor_employee, request_id=request_id, request_hash=request_hash,
        snapshot_extra={"issued_line_snapshots": issued_line_snapshots})
    return issue


def _debit_ordinary_line(issue, line, actor_employee):
    requirement = line.requirement
    debit_material_stock(
        raw_material=line.raw_material,
        unit=line.unit,
        quantity=line.requested_quantity,
        source_type="MATERIAL_ISSUE",
        source_id=issue.pk,
        source_line_id=line.pk,
        actor_employee=actor_employee,
        production_task=issue.production_task,
        snapshot={
            "issue_number": issue.issue_number,
            "material_number": line.material_number_snapshot,
            "recipient": issue.recipient_workshop_employee.name,
            "workshop": issue.workshop.name,
        },
    )
    requirement.internal_issued_quantity += line.requested_quantity
    requirement.save(update_fields=["internal_issued_quantity", "updated_at"])


def preview_issue(issue):
    """与提交共用只读校验，不能在预览时同步额度或创建库存。"""
    if issue.stock_mode == "PUBLIC_V2":
        from .public_issue_services import preview_public_issue
        return preview_public_issue(issue)
    rows = list(issue.lines.select_related("requirement", "raw_material", "unit", "semi_finished_balance").order_by("line_number", "id"))
    errors = []
    try:
        _validate_relations(issue, require_complete=True)
        _validate_issue_quantities(issue)
    except ValidationError as error:
        details = getattr(error, "error_meta", {}).get("lines", [])
        errors.extend(details or [{"code": getattr(error, "api_error_code", "VALIDATION_ERROR"), "detail": "领料资料不完整或已失效，请刷新核对。"}])
    if issue.status != MaterialIssueStatus.PENDING_REVIEW:
        errors.append({"code": "INVALID_STATE", "detail": "只有待仓库审核的领料单可以确认出库。"})
    if any(line.line_type == "RAW" for line in rows):
        _, _, blockers, revision = build_requirement_specs(issue.production_task_id)
        scoped = filter_blockers_for_scope([b for b in blockers if b["code"] != "PIPE_SERVICE_REQUIRED"],
            product_line_id=issue.product_line_id, section_codes=material_section_codes_for_issue(issue) or ())
        errors.extend(scoped)
        if revision != issue.source_revision_hash:
            errors.append({"code": "SOURCE_CHANGED", "detail": "BOM 来源已变化。"})
        from .material_flow import pipe_specs
        specs, _ = pipe_specs(issue.production_task_id, issue.product_line_id)
        current = {s["id"]: s for s in specs}
        for line in rows:
            if line.conversion_snapshot.get("kind") == "PIPE" and (line.requirement_id not in current
                    or current[line.requirement_id]["revision"] != line.conversion_snapshot.get("source_revision_hash")):
                errors.append({"code": "SOURCE_CHANGED", "detail": "管材部位或切割参数已变化。"})
    event = issue.audit_events.filter(action=MaterialIssueAction.CREATED).first()
    source = event.snapshot.get("plan_source") if event else None
    if source:
        plan = ProductionScheduleProduct.objects.filter(pk=source.get("schedule_product_id"), removed_at__isnull=True,
            schedule__record_status="ACTIVE", schedule__production_task_id=issue.production_task_id,
            product_line_id=issue.product_line_id).first()
        if not plan or not ProductionScheduleProductCraft.objects.filter(schedule_product=plan, removed_at__isnull=True,
                craft_type_snapshot=CraftType.INTERNAL, plan_category=source.get("plan_category")).exists():
            errors.append({"code": "SOURCE_CHANGED", "detail": "作业计划来源已失效。"})
    lines = []
    for line in rows:
        if line.line_type == "SEMI":
            stock = remaining = line.semi_finished_balance.quantity
        else:
            requirement = line.requirement
            remaining = requirement.required_quantity - requirement.internal_issued_quantity - requirement.outsourcing_issued_quantity
            stock = line_stock(line)
        lines.append({"line_id": str(line.pk), "order_remaining": str(max(remaining, 0)), "available_stock": str(stock),
            "max_issue_quantity": str(max(min(remaining, stock), 0)), "validation_errors": [e["code"] for e in errors], **line_flow_data(line)})
    return {"can_confirm": bool(lines) and not errors, "lines": lines, "errors": errors}
