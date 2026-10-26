from decimal import Decimal

from django.db import transaction
from django.db.models import Prefetch, Sum
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.boms.models import Bom, BomLine, BomStatus
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.production_tasks.models import ProductionTaskStatus

from .models import (
    PurchaseAllocationStatus,
    PurchaseRequest,
    PurchaseRequestAllocation,
    PurchaseRequestLine,
    PurchaseRequestStatus,
    Supplier,
)
from .services import PurchaseQuantityParseStatus, _source_quantity
from .selectors import purchase_request_lines_with_allocated_quantity


def _request_snapshot(purchase_request):
    return {
        "request_number": purchase_request.request_number,
        "production_task_id": str(purchase_request.production_task_id),
        "bom_id": str(purchase_request.bom_id),
        "status": purchase_request.status,
        "lines": [
            {
                "id": str(line.pk),
                "bom_line_id": str(line.bom_line_id),
                "gross_requirement_quantity": str(line.gross_requirement_quantity),
                "actual_request_quantity": str(line.actual_request_quantity) if line.actual_request_quantity is not None else None,
                "allocated_quantity": str(line.allocated_quantity),
                "remaining_quantity": str(line.remaining_quantity),
                "required_date": line.required_date.isoformat() if line.required_date else None,
            }
            for line in purchase_request_lines_with_allocated_quantity(
                purchase_request.lines.order_by("line_number", "id"),
            )
        ],
    }


def purchase_requests_with_context(queryset=None):
    queryset = queryset if queryset is not None else PurchaseRequest.objects.all()
    return queryset.select_related(
        "production_task",
        "production_task__sales_order",
        "sales_order_delivery_batch",
        "bom",
        "requested_by_employee",
    ).prefetch_related(
        Prefetch("lines", queryset=purchase_request_lines_with_allocated_quantity(PurchaseRequestLine.objects.order_by("line_number", "id"))),
        "lines__bom_line",
        "lines__suggested_supplier",
        "lines__allocations__supplier",
    )


@transaction.atomic
def create_purchase_request(*, bom, actor_employee, request=None):
    locked_bom = Bom.objects.select_for_update().select_related(
        "production_task",
        "product_line",
    ).get(pk=bom.pk)
    task = locked_bom.production_task
    if task.status not in {
        ProductionTaskStatus.READY,
        ProductionTaskStatus.IN_PRODUCTION,
        ProductionTaskStatus.PAUSED,
        ProductionTaskStatus.COMPLETED,
    }:
        raise Conflict("生产订单尚未确认，不能创建采购申请。")
    if locked_bom.status != BomStatus.VERIFIED:
        raise Conflict("当前订单 BOM 尚未确认，不能创建采购申请。")
    latest_bom_id = Bom.objects.filter(
        product_line=locked_bom.product_line,
        archived_at__isnull=True,
    ).order_by("-version_number", "-id").values_list("id", flat=True).first()
    if latest_bom_id != locked_bom.pk:
        raise Conflict("只能从当前最新已确认 BOM 创建采购申请。")
    if PurchaseRequest.objects.filter(bom=locked_bom, archived_at__isnull=True).exists():
        raise Conflict("该 BOM 已经生成采购申请。")

    source_lines = list(
        BomLine.objects.select_for_update()
        .filter(section__bom=locked_bom)
        .select_related("section")
        .order_by("section__line_number", "line_number", "id")
    )
    if not source_lines:
        raise ValidationError({"bom": "BOM 没有物料明细，不能创建采购申请。"})
    parsed_lines = []
    errors = []
    for source_line in source_lines:
        if source_line.section.section_type == 'PROFILE':
            raise Conflict('管材须从采购汇总单的根米采购入口下单，旧采购申请分配入口不支持新管材。')
        quantity, _field, _text, unit, parse_status = _source_quantity(source_line, locked_bom)
        if parse_status != PurchaseQuantityParseStatus.READY or quantity is None or quantity <= 0:
            errors.append(f"{source_line.section.title} 第 {source_line.line_number} 行毛需求量未正确填写")
        if not str(unit or "").strip():
            errors.append(f"{source_line.section.title} 第 {source_line.line_number} 行单位未填写")
        parsed_lines.append((source_line, quantity, str(unit or "").strip()))
    if errors:
        raise ValidationError({"bom_lines": errors})

    purchase_request = PurchaseRequest.objects.create(
        request_number=next_business_number("PURCHASE_REQUEST"),
        production_task=task,
        sales_order_delivery_batch=task.sales_order_delivery_batch,
        bom=locked_bom,
        requested_by_employee=actor_employee,
    )
    for line_number, (source_line, quantity, unit) in enumerate(parsed_lines, start=1):
        PurchaseRequestLine.objects.create(
            purchase_request=purchase_request,
            line_number=line_number,
            bom_line=source_line,
            material_snapshot=source_line.part_name or source_line.material or source_line.raw_material,
            specification_snapshot=source_line.specification,
            unit_snapshot=unit,
            gross_requirement_quantity=quantity,
        )
    write_audit_log(
        object_type="PURCHASE_REQUEST",
        object_id=purchase_request.pk,
        context_type="PRODUCTION_TASK",
        context_id=task.pk,
        action="CREATED",
        actor_employee=actor_employee,
        after_data=_request_snapshot(purchase_request),
        request=request,
    )
    return purchase_request


@transaction.atomic
def update_purchase_request(*, purchase_request, line_values, actor_employee, request=None):
    purchase_request = PurchaseRequest.objects.select_for_update().get(pk=purchase_request.pk)
    require_matching_etag(request, purchase_request)
    if purchase_request.status != PurchaseRequestStatus.DRAFT:
        raise Conflict("只有草稿采购申请可以修改。")
    before = _request_snapshot(purchase_request)
    existing = {
        str(line.pk): line
        for line in purchase_request.lines.select_for_update().all()
    }
    submitted_ids = [str(item["id"]) for item in line_values]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ValidationError({"lines": "采购申请明细不能重复。"})
    if set(submitted_ids) - set(existing):
        raise ValidationError({"lines": "采购申请包含不属于当前申请的明细。"})
    for values in line_values:
        line = existing[str(values["id"])]
        if line.bom_line and line.bom_line.section.section_type == 'PROFILE':
            raise Conflict('旧管材采购申请不能继续按单数量编辑，请从采购汇总单重新建立根米采购。')
        actual = Decimal(values["actual_request_quantity"])
        reason = str(values.get("difference_reason", "")).strip()
        if actual != line.gross_requirement_quantity and not reason:
            raise ValidationError({"lines": f"第 {line.line_number} 行实际申请量与毛需求不同，必须填写差异原因。"})
        line.actual_request_quantity = actual
        line.difference_reason = reason
        line.required_date = values["required_date"]
        line.suggested_supplier = values.get("suggested_supplier")
        line.save()
    purchase_request.updated_at = timezone.now()
    purchase_request.save(update_fields=["updated_at"])
    write_audit_log(
        object_type="PURCHASE_REQUEST",
        object_id=purchase_request.pk,
        context_type="PRODUCTION_TASK",
        context_id=purchase_request.production_task_id,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=_request_snapshot(purchase_request),
        request=request,
    )
    return purchase_request


@transaction.atomic
def submit_purchase_request(*, purchase_request, actor_employee, request=None):
    purchase_request = PurchaseRequest.objects.select_for_update().get(pk=purchase_request.pk)
    require_matching_etag(request, purchase_request)
    if purchase_request.status != PurchaseRequestStatus.DRAFT:
        raise Conflict("只有草稿采购申请可以提交。")
    errors = []
    lines = list(purchase_request.lines.select_for_update().all())
    for line in lines:
        if line.bom_line and line.bom_line.section.section_type == 'PROFILE':
            raise Conflict('旧管材采购申请不能继续提交，请从采购汇总单重新建立根米采购。')
        if line.actual_request_quantity is None or line.actual_request_quantity <= 0:
            errors.append(f"第 {line.line_number} 行缺少实际申请量")
        if line.required_date is None:
            errors.append(f"第 {line.line_number} 行缺少需求日期")
        if (
            line.actual_request_quantity is not None
            and line.actual_request_quantity != line.gross_requirement_quantity
            and not line.difference_reason.strip()
        ):
            errors.append(f"第 {line.line_number} 行缺少差异原因")
    if errors:
        raise ValidationError({"lines": errors})
    before = _request_snapshot(purchase_request)
    purchase_request.status = PurchaseRequestStatus.SUBMITTED
    purchase_request.submitted_at = timezone.now()
    purchase_request.save(update_fields=["status", "submitted_at", "updated_at"])
    write_audit_log(
        object_type="PURCHASE_REQUEST",
        object_id=purchase_request.pk,
        context_type="PRODUCTION_TASK",
        context_id=purchase_request.production_task_id,
        action="SUBMITTED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=_request_snapshot(purchase_request),
        request=request,
    )
    return purchase_request


def _refresh_allocation_status(purchase_request):
    lines = list(purchase_request_lines_with_allocated_quantity(purchase_request.lines.all()))
    fully_allocated = bool(lines) and all(line.remaining_quantity <= 0 for line in lines)
    purchase_request.status = (
        PurchaseRequestStatus.FULLY_ALLOCATED if fully_allocated else PurchaseRequestStatus.ALLOCATING
    )
    purchase_request.save(update_fields=["status", "updated_at"])


@transaction.atomic
def allocate_purchase_request_line(*, line, validated_data, actor_employee, request=None):
    line = PurchaseRequestLine.objects.select_for_update().select_related("purchase_request").get(pk=line.pk)
    purchase_request = PurchaseRequest.objects.select_for_update().get(pk=line.purchase_request_id)
    require_matching_etag(request, purchase_request)
    if line.bom_line and line.bom_line.section.section_type == 'PROFILE':
        raise Conflict('旧管材采购申请不能继续分配，请从采购汇总单重新建立根米采购。')
    if purchase_request.status not in {
        PurchaseRequestStatus.SUBMITTED,
        PurchaseRequestStatus.ALLOCATING,
        PurchaseRequestStatus.FULLY_ALLOCATED,
    }:
        raise Conflict("采购申请提交后才能分配供应商和采购批次。")
    quantity = Decimal(validated_data["quantity"])
    allocated = line.allocations.filter(
        status__in=[PurchaseAllocationStatus.DRAFT, PurchaseAllocationStatus.ORDERED]
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    remaining = Decimal(line.actual_request_quantity or 0) - Decimal(allocated)
    if quantity > remaining:
        raise ValidationError({"quantity": f"该申请行剩余可分配量为 {remaining}，不能超量分配。"})
    supplier = validated_data["supplier"]
    if supplier.archived_at or supplier.is_disabled:
        raise ValidationError({"supplier_id": "供应商已禁用或归档。"})
    allocation = PurchaseRequestAllocation.objects.create(
        purchase_request_line=line,
        supplier=supplier,
        procurement_batch_number=validated_data["procurement_batch_number"].strip(),
        quantity=quantity,
        expected_arrival_date=validated_data["expected_arrival_date"],
        created_by_employee=actor_employee,
    )
    _refresh_allocation_status(purchase_request)
    write_audit_log(
        object_type="PURCHASE_REQUEST",
        object_id=purchase_request.pk,
        context_type="PRODUCTION_TASK",
        context_id=purchase_request.production_task_id,
        action="ALLOCATED",
        actor_employee=actor_employee,
        after_data={
            "allocation_id": str(allocation.pk),
            "line_id": str(line.pk),
            "supplier_id": str(supplier.pk),
            "quantity": str(quantity),
        },
        request=request,
    )
    return allocation, purchase_request


@transaction.atomic
def cancel_purchase_allocation(*, allocation, reason, actor_employee, request=None):
    allocation = PurchaseRequestAllocation.objects.select_for_update().select_related(
        "purchase_request_line__purchase_request"
    ).get(pk=allocation.pk)
    purchase_request = PurchaseRequest.objects.select_for_update().get(pk=allocation.purchase_request_line.purchase_request_id)
    require_matching_etag(request, purchase_request)
    if allocation.status == PurchaseAllocationStatus.ORDERED:
        raise Conflict("已下达供应商采购单的分配不能直接释放，必须先处理采购单变更或取消。")
    if allocation.status == PurchaseAllocationStatus.CANCELLED:
        raise Conflict("该分配已经取消。")
    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValidationError({"reason": "取消分配必须填写原因。"})
    allocation.status = PurchaseAllocationStatus.CANCELLED
    allocation.save(update_fields=["status", "updated_at"])
    _refresh_allocation_status(purchase_request)
    write_audit_log(
        object_type="PURCHASE_REQUEST",
        object_id=purchase_request.pk,
        context_type="PRODUCTION_TASK",
        context_id=purchase_request.production_task_id,
        action="ALLOCATION_CANCELLED",
        actor_employee=actor_employee,
        after_data={"allocation_id": str(allocation.pk), "reason": normalized_reason},
        request=request,
    )
    return allocation, purchase_request
