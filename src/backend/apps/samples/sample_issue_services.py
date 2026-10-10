"""样品专用领料：冻结样品用料快照，仓库确认实际数量后扣减库存。"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.access_control.module_policy import can_sample
from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.customers.services import model_snapshot
from apps.inventory.models import MaterialStockBalance, MaterialStockMovement, MaterialStockQuality
from apps.inventory.public_stock_cutover import require_business_stock_write
from apps.inventory.stock_services import debit_material_stock
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductionUnit

from .models import (
    SampleMaterialIssue,
    SampleMaterialIssueLine,
    SampleMaterialIssueStatus,
    SampleMaterialRequest,
    SampleRequest,
    SampleRequestStatus,
)
from .material_arrival_services import material_progress
from .production_services import enter_parameter_stage
from .services import SAMPLE_FIELDS, _write_sample_records


ISSUE_START_STATUSES = {
    SampleRequestStatus.MATERIALS_READY,
    SampleRequestStatus.MATERIAL_ISSUE_PENDING,
    SampleRequestStatus.PROCUREMENT_PENDING,
}


def _record(sample):
    return SampleMaterialRequest.objects.filter(sample_request=sample).first()


def _decimal(value, field_name, *, allow_zero=True):
    try:
        result = Decimal(str(value or "0"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError({field_name: "请输入有效数量。"}) from exc
    if result < 0 or (not allow_zero and result <= 0):
        raise ValidationError({field_name: "数量不能为负数。"})
    return result


def _active_material(material_id):
    try:
        material = RawMaterialInformation.objects.select_related("unit", "category").get(pk=material_id)
    except (RawMaterialInformation.DoesNotExist, ValueError, TypeError) as exc:
        raise ValidationError("用料行缺少有效原材料。") from exc
    if material.archived_at is not None or material.item_type != "MATERIAL" or material.unit.status != "ACTIVE":
        raise ValidationError("原材料已停用或单位无效，不能领料。")
    return material


def _issue_permission(request, sample, permission):
    if not request or not getattr(request, "employee", None) or not request.user.has_perm(permission):
        raise PermissionDenied("当前账号没有样品领料权限或有效员工档案。")
    if not can_sample(request, sample, permission):
        raise PermissionDenied("当前账号不在此样品的可操作范围内。")


def _available_rows(sample):
    record = _record(sample)
    if not record or not record.submitted_at or record.no_materials:
        raise Conflict("当前样品没有可领用的材料需求。")
    progress = material_progress(sample)
    result = []
    for row in progress["lines"]:
        requested = _decimal(row.get("quantity"), "quantity", allow_zero=False)
        warehouse = _decimal(row.get("supplyQuantity"), "supplyQuantity")
        arrived = _decimal(row.get("arrivedQuantity"), "arrivedQuantity")
        available = min(requested, warehouse + arrived)
        material = _active_material(row.get("rawMaterialId"))
        result.append({
            "row": deepcopy(row),
            "material": material,
            "requested": requested,
            "warehouse": warehouse,
            "arrived": arrived,
            "available": available,
        })
    if not result or not any(item["available"] > 0 for item in result):
        raise Conflict("当前没有已可供领料的材料。")
    return result


def _line_payload(line):
    return {
        "id": str(line.id),
        "lineKey": str(line.line_key),
        "category": line.category,
        "name": line.name_snapshot,
        "specification": line.specification_snapshot,
        "material": line.material_snapshot,
        "color": line.color_snapshot,
        "unitLabel": line.unit.unit_name,
        "requestedQuantity": str(line.requested_quantity),
        "warehouseQuantity": str(line.warehouse_quantity),
        "arrivedQuantity": str(line.arrived_quantity),
        "availableQuantity": str(line.available_quantity),
        "issuedQuantity": None if line.issued_quantity is None else str(line.issued_quantity),
        "shortageQuantity": str(line.shortage_quantity),
    }


def issue_response(sample, request):
    record = _record(sample)
    if not sample.application_payload_hash:
        return {"available": False, "reason": "历史申请不使用新版样品领料流程。"}
    if not record or record.no_materials:
        return {"available": False, "reason": "无需用料的样品不需要领料。"}
    issue = SampleMaterialIssue.objects.filter(material_request=record).prefetch_related("lines__unit").first()
    progress = material_progress(sample)
    available_for_issue = any(
        min(
            _decimal(row.get("quantity"), "quantity", allow_zero=False),
            _decimal(row.get("supplyQuantity"), "supplyQuantity") + _decimal(row.get("arrivedQuantity"), "arrivedQuantity"),
        ) > 0
        for row in progress["lines"]
    )
    can_initiate = bool(
        sample.status in ISSUE_START_STATUSES
        and available_for_issue
        and request
        and getattr(request, "employee", None)
        and request.user.has_perm("samples.edit_sample_materials")
        and can_sample(request, sample, "samples.edit_sample_materials")
        and issue is None
    )
    can_confirm = bool(
        issue
        and issue.status == SampleMaterialIssueStatus.PENDING_CONFIRMATION
        and request
        and getattr(request, "employee", None)
        and request.user.has_perm("samples.review_sample_materials")
        and can_sample(request, sample, "samples.review_sample_materials")
    )
    lines = [_line_payload(line) for line in issue.lines.all()] if issue else []
    if not issue:
        for row in progress["lines"]:
            available = min(
                _decimal(row.get("quantity"), "quantity", allow_zero=False),
                _decimal(row.get("supplyQuantity"), "supplyQuantity") + _decimal(row.get("arrivedQuantity"), "arrivedQuantity"),
            )
            lines.append({
                "id": None,
                "lineKey": str(row["key"]),
                "category": row.get("category", ""),
                "name": row.get("name", ""),
                "specification": row.get("specification", ""),
                "material": row.get("material", ""),
                "color": row.get("color", ""),
                "unitLabel": row.get("unitLabel", ""),
                "requestedQuantity": str(row.get("quantity", "0")),
                "warehouseQuantity": str(row.get("supplyQuantity", "0")),
                "arrivedQuantity": str(row.get("arrivedQuantity", "0")),
                "availableQuantity": str(available),
                "issuedQuantity": None,
                "shortageQuantity": str(max(_decimal(row.get("quantity"), "quantity") - available, Decimal("0"))),
            })
    return {
        "available": True,
        "status": issue.status if issue else "NOT_STARTED",
        "statusLabel": issue.get_status_display() if issue else "待发起领料",
        "issueId": str(issue.id) if issue else None,
        "etag": etag_for_instance(sample),
        "canInitiate": can_initiate,
        "canConfirm": can_confirm,
        "initiatedAt": issue.initiated_at.isoformat() if issue and issue.initiated_at else None,
        "confirmedAt": issue.confirmed_at.isoformat() if issue and issue.confirmed_at else None,
        "lines": lines,
    }


@transaction.atomic
def initiate_sample_material_issue(*, sample_id, request, client_request_id=None, note=""):
    sample = SampleRequest.objects.select_for_update().get(pk=sample_id)
    require_matching_etag(request, sample)
    _issue_permission(request, sample, "samples.edit_sample_materials")
    if sample.status not in ISSUE_START_STATUSES:
        raise Conflict("当前样品尚未进入可发起领料阶段。")
    record = _record(sample)
    if not record or record.no_materials:
        raise Conflict("无需用料的样品不需要发起领料。")
    existing = SampleMaterialIssue.objects.filter(material_request=record).first()
    if existing:
        if client_request_id and existing.client_request_id == client_request_id:
            return sample
        raise Conflict("当前样品已经发起过领料。")
    rows = _available_rows(sample)
    meter_unit = ProductionUnit.objects.filter(unit_name="米", status="ACTIVE", archived_at__isnull=True).first()
    if any(item["row"].get("category") == "tube" for item in rows) and meter_unit is None:
        raise Conflict("系统缺少有效的米单位，无法发起管材领料。")
    issue = SampleMaterialIssue.objects.create(
        material_request=record,
        status=SampleMaterialIssueStatus.PENDING_CONFIRMATION,
        client_request_id=client_request_id,
        initiated_by=request.employee,
        initiated_at=timezone.now(),
        note=note.strip(),
    )
    for item in rows:
        row = item["row"]
        SampleMaterialIssueLine.objects.create(
            issue=issue,
            line_key=UUID(str(row["key"])),
            raw_material=item["material"],
            unit=meter_unit if row.get("category") == "tube" else item["material"].unit,
            category=row.get("category", ""),
            name_snapshot=row.get("name", ""),
            specification_snapshot=row.get("specification", ""),
            material_snapshot=row.get("material", ""),
            color_snapshot=row.get("color", ""),
            requested_quantity=item["requested"],
            warehouse_quantity=item["warehouse"],
            arrived_quantity=item["arrived"],
            available_quantity=item["available"],
            shortage_quantity=max(item["requested"] - item["available"], Decimal("0")),
        )
    before = model_snapshot(sample, SAMPLE_FIELDS)
    sample.status = SampleRequestStatus.MATERIAL_ISSUE_REVIEW
    sample.save(update_fields=["status", "updated_at"])
    _write_sample_records(sample_request=sample, action="SAMPLE_MATERIAL_ISSUE_INITIATED",
                          actor_employee=request.employee, request=request, before_data=before,
                          note="打样部已发起样品领料，等待仓库确认实际领料数量。")
    return sample


def _debit_pipe_stock(*, raw_material, quantity, source_id, source_line_id, actor_employee, snapshot):
    """按样品填写的米数换算整根扣减，并返回实际扣减米数。"""
    require_business_stock_write(source_type="SAMPLE_MATERIAL_ISSUE", direction="OUT")
    balances = MaterialStockBalance.objects.select_for_update().filter(
        measurement_kind="PIPE",
        raw_material=raw_material,
        unit=raw_material.unit,
        quality=MaterialStockQuality.AVAILABLE,
        quantity__gt=0,
        zone__status="ACTIVE",
        zone__warehouse__status="ACTIVE",
    ).select_related("zone", "zone__warehouse").order_by("zone_id", "id")
    balance = None
    bar_count = 0
    meters = Decimal("0")
    for candidate in balances:
        length = candidate.raw_bar_length_m
        if not length or length <= 0 or candidate.meter_quantity is None:
            continue
        possible_bars = (min(quantity, candidate.meter_quantity) / length).to_integral_value(rounding=ROUND_DOWN)
        possible_bars = int(min(possible_bars, candidate.quantity))
        if possible_bars > 0:
            balance = candidate
            bar_count = possible_bars
            meters = Decimal(bar_count) * length
            break
    if balance is None:
        raise Conflict("管材合格库存不足一整根，无法按当前米数领料。")
    before = balance.quantity
    balance.quantity = before - bar_count
    balance.meter_quantity = (balance.meter_quantity or Decimal("0")) - meters
    balance.version += 1
    balance.save(update_fields=["quantity", "meter_quantity", "version", "updated_at"])
    movement = MaterialStockMovement.objects.create(
        balance=balance,
        direction="OUT",
        quantity=bar_count,
        meter_quantity=meters,
        before_quantity=before,
        after_quantity=balance.quantity,
        before_meter_quantity=(balance.meter_quantity or Decimal("0")) + meters,
        after_meter_quantity=balance.meter_quantity,
        source_type="SAMPLE_MATERIAL_ISSUE",
        source_id=source_id,
        source_line_id=source_line_id,
        actor_employee=actor_employee,
        snapshot={**snapshot, "zone_id": str(balance.zone_id), "raw_bar_length_m": str(balance.raw_bar_length_m),
                  "issued_meters": str(meters), "issued_bar_count": bar_count},
    )
    return movement, meters


@transaction.atomic
def confirm_sample_material_issue(*, sample_id, data, request):
    sample = SampleRequest.objects.select_for_update().get(pk=sample_id)
    require_matching_etag(request, sample)
    _issue_permission(request, sample, "samples.review_sample_materials")
    record = _record(sample)
    issue = SampleMaterialIssue.objects.select_for_update().select_related("material_request").filter(material_request=record).first()
    if not issue:
        raise Conflict("请先由打样部发起领料。")
    request_id = data["request_id"]
    if issue.status == SampleMaterialIssueStatus.ISSUED:
        if issue.confirmation_request_id == request_id:
            return sample
        raise Conflict("该样品已经完成领料确认。")
    if issue.status != SampleMaterialIssueStatus.PENDING_CONFIRMATION:
        raise Conflict("当前领料单状态不可确认。")
    submitted = {str(row["line_id"]): row for row in data["lines"]}
    lines = list(issue.lines.select_for_update().select_related("raw_material", "unit").all())
    if set(submitted) != {str(line.id) for line in lines}:
        raise ValidationError("领料明细必须与发起领料时一致，不能新增、删除或重复。")
    quantities = {}
    for line in lines:
        quantity = _decimal(submitted[str(line.id)]["issued_quantity"], "issued_quantity")
        if quantity > line.available_quantity:
            raise ValidationError({str(line.id): "实际领料数量不能超过当前可供数量。"})
        quantities[line.id] = quantity
    if not any(quantity > 0 for quantity in quantities.values()):
        raise ValidationError("至少确认一项大于 0 的实际领料数量。")
    before = model_snapshot(sample, SAMPLE_FIELDS)
    for line in lines:
        quantity = quantities[line.id]
        actual_quantity = quantity
        if quantity > 0:
            snapshot = {"sample_issue_id": str(issue.id), "sample_issue_line_id": str(line.id),
                        "raw_material_id": str(line.raw_material_id), "unit_id": str(line.unit_id)}
            if line.category == "tube":
                _, actual_quantity = _debit_pipe_stock(raw_material=line.raw_material, quantity=quantity,
                                                        source_id=issue.id, source_line_id=line.id,
                                                        actor_employee=request.employee, snapshot=snapshot)
            else:
                debit_material_stock(raw_material=line.raw_material, unit=line.unit, quantity=quantity,
                                     source_type="SAMPLE_MATERIAL_ISSUE", source_id=issue.id,
                                     source_line_id=line.id, actor_employee=request.employee,
                                     production_task=None, snapshot=snapshot)
        line.issued_quantity = actual_quantity
        line.shortage_quantity = max(line.requested_quantity - actual_quantity, Decimal("0"))
        line.save(update_fields=["issued_quantity", "shortage_quantity", "updated_at"])
    issue.status = SampleMaterialIssueStatus.ISSUED
    issue.confirmation_request_id = request_id
    issue.confirmed_by = request.employee
    issue.confirmed_at = timezone.now()
    issue.version += 1
    issue.save(update_fields=["status", "confirmation_request_id", "confirmed_by", "confirmed_at", "version", "updated_at"])
    enter_parameter_stage(sample, actor_employee=request.employee, note="仓库已确认样品实际领料数量，允许上传参数并生产。")
    _write_sample_records(sample_request=sample, action="SAMPLE_MATERIAL_ISSUE_CONFIRMED",
                          actor_employee=request.employee, request=request, before_data=before,
                          note="仓库已确认实际领料数量；不足部分不补料，采购单继续独立处理。")
    return sample
