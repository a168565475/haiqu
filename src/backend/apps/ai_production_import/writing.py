from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.datastructures import MultiValueDict
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.access_control import module_policy
from apps.boms.api.serializers import BomUpdateInputSerializer, FIXED_BOM_SECTIONS
from apps.boms.models import BomCreationMethod
from apps.boms.services import create_bom, update_bom_lines
from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.production_tasks.api.serializers import AiProductionTaskWriteSerializer
from apps.production_tasks.models import ProductionTaskProduct, ProductionTaskStatus
from apps.production_tasks.services import create_production_task

from .models import AiImportState, AiProductionImport
from .services import _mapping_active
from .task_selection import require_task_key


def _require_permission(request, code):
    """写入动作仍由服务端权限控制，不能依赖新页面是否显示按钮。"""
    allowed = module_policy.has_permission(request, code)
    if not allowed:
        raise PermissionDenied("当前账号没有执行该动作的权限。")


def _lock_record(employee, record_id):
    return get_object_or_404(AiProductionImport.objects.select_for_update(), owner=employee, pk=record_id)


def create_task_draft(*, employee, record_id, payload, request, task_key=None):
    _require_permission(request, "production_tasks.add_productiontask")
    with transaction.atomic():
        record = _lock_record(employee, record_id)
        require_matching_etag(request, record)
        require_task_key(record, task_key)
        if record.task_id:
            return record, True
        if _mapping_active(record):
            raise Conflict("正在对应 ERP 字段，请完成后再创建任务。")
        if record.state != AiImportState.REVIEW or not record.result:
            raise Conflict("当前导入记录不在待核对状态，不能创建生产任务。")

        serializer = AiProductionTaskWriteSerializer(
            data=payload,
            context={
                "request": request,
                "require_contract_number_token": True,
            },
        )
        serializer.is_valid(raise_exception=True)
        product_keys = [item["client_key"] for item in serializer.validated_data["products"]]
        task = create_production_task(
            validated_data=serializer.validated_data,
            files=MultiValueDict(),
            actor_employee=employee,
            request=request,
            allow_incomplete_import=True,
        )
        record.task_id = task.pk
        record.task_number = task.task_number
        record.created_by_employee_id = employee.pk
        record.state = AiImportState.TASK_DRAFT
        created_products = list(task.products.order_by("line_number", "id"))
        if len(created_products) != len(product_keys):
            raise ValidationError({"products": "创建结果与提交产品行数不一致，已取消本次创建。"})
        record.source = {**record.source, "created_product_keys": {
            str(product.pk): key for product, key in zip(created_products, product_keys, strict=True)
        }}
        record.save(update_fields=["task_id", "task_number", "created_by_employee_id", "state", "source", "updated_at"])
    return record, False


class _BomWriteRequest:
    """把导入服务的 JSON 动作适配到现有 BOM 服务的请求契约。"""

    def __init__(self, request, data, etag):
        self.data = data
        self.FILES = {}
        self.user = request.user
        self.employee = request.employee
        self.request_id = getattr(request, "request_id", None)
        self.META = getattr(request, "META", {})
        self.headers = {"If-Match": etag}


def _normalize_line(line, index):
    if not isinstance(line, dict):
        raise ValidationError({"plans": f"第 {index} 条 BOM 用料明细必须是对象。"})
    result = dict(line)
    # 原表“数量”可能指总需求或单耗，不能擅自转换为 ERP 用量。
    if result.get("quantity") not in (None, "") or result.get("material_quantity") not in (None, ""):
        raise ValidationError({"plans": "请将原表数量核对到对应分区的单耗、切支或装箱数量后再创建 BOM。"})
    result.pop("quantity", None)
    result.pop("material_quantity", None)
    result.pop("line_key", None)
    result.pop("section", None)
    result.setdefault("part_name", "")
    if "material_quantity" in result and result["material_quantity"] in (None, ""):
        result.pop("material_quantity")
    return result


def _normalize_sections(sections):
    if not isinstance(sections, list):
        raise ValidationError({"plans": "BOM sections 必须是数组。"})
    expected = dict(FIXED_BOM_SECTIONS)
    normalized = []
    seen = set()
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            raise ValidationError({"plans": f"第 {index} 个 BOM 分区必须是对象。"})
        title = str(section.get("title", "")).strip()
        section_type = section.get("section_type")
        if title not in expected or expected[title] != section_type or title in seen:
            raise ValidationError({"plans": "BOM 必须提交固定七个分区，名称和类型必须匹配。"})
        seen.add(title)
        lines = section.get("lines", [])
        if not isinstance(lines, list):
            raise ValidationError({"plans": f"BOM 分区 {title} 的 lines 必须是数组。"})
        normalized.append({
            **({"id": section["id"]} if section.get("id") else {}),
            "title": title,
            "section_type": section_type,
            "lines": [_normalize_line(line, index) for index, line in enumerate(lines, start=1)],
        })
    if seen != set(expected):
        raise ValidationError({"plans": "BOM 必须完整提交固定七个分区。"})
    return normalized


def create_boms(*, employee, record_id, plans, request, task_key=None):
    _require_permission(request, "boms.add_bom")
    with transaction.atomic():
        record = _lock_record(employee, record_id)
        require_matching_etag(request, record)
        require_task_key(record, task_key)
        if record.bom_ids:
            return record, list(record.bom_ids), True
        if not record.task_id:
            raise Conflict("请先创建生产任务草稿。")
        if record.state not in {AiImportState.TASK_DRAFT, AiImportState.REVIEW}:
            raise Conflict("当前导入记录不允许创建 BOM。")

        from apps.production_tasks.models import ProductionTask
        task = ProductionTask.objects.select_for_update().get(pk=record.task_id)
        if task.status not in {ProductionTaskStatus.READY, ProductionTaskStatus.IN_PRODUCTION}:
            raise Conflict("生产任务单必须经 PMC 确认后，才能创建 BOM。")
        if not isinstance(plans, list) or not plans:
            raise ValidationError({"plans": "至少提交一个 BOM 计划。"})

        product_lines = {
            str(row.pk): row
            for row in ProductionTaskProduct.objects.select_for_update().filter(production_task=task)
        }
        created = []
        for index, plan in enumerate(plans, start=1):
            if not isinstance(plan, dict):
                raise ValidationError({"plans": f"第 {index} 个 BOM 计划必须是对象。"})
            line_id = str(plan.get("production_task_product_id", ""))
            product_line = product_lines.get(line_id)
            if product_line is None:
                raise ValidationError({"plans": f"第 {index} 个 BOM 计划的产品明细不属于当前任务。"})

            bom = create_bom(
                product_line=product_line,
                creation_method=BomCreationMethod.BLANK,
                actor_employee=employee,
                request=request,
            )
            sections = _normalize_sections(plan.get("sections"))
            # 空白 BOM 会预建“管材类”分区，必须携带其 ID；其它固定分区由保存服务创建。
            first_section = bom.sections.order_by("line_number", "id").first()
            if first_section:
                for section in sections:
                    if section["title"] == first_section.title and not section.get("id"):
                        section["id"] = first_section.pk
                        break
            bom_etag = etag_for_instance(bom)
            write_request = _BomWriteRequest(request, {"sections": sections, "intent": "draft"}, bom_etag)
            serializer = BomUpdateInputSerializer(data=write_request.data, context={"bom": bom})
            serializer.is_valid(raise_exception=True)
            updated = update_bom_lines(
                bom=bom,
                sections=serializer.validated_data["sections"],
                actor_employee=employee,
                request=write_request,
                intent="draft",
            )
            created.append({"id": str(updated.pk), "bom_number": updated.bom_number, "status": updated.status})

        ids = [item["id"] for item in created]
        record.bom_ids = ids
        record.bom_id = ids[0] if ids else None
        record.state = AiImportState.BOM_PENDING
        record.save(update_fields=["bom_ids", "bom_id", "state", "updated_at"])
    return record, created, False
