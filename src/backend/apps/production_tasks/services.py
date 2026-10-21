from decimal import Decimal, ROUND_HALF_UP
import json
import re

from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.files.uploads import save_scanned_image
from apps.products.models import ProductStatus
from apps.organizations.models import Employee, EmployeeStatus
from apps.reference_data.models import Currency, ProductionUnit, ReferenceStatus
from apps.sales_orders.pricing import cny_line_amounts
from apps.sales_orders.models import (
    CollaborationEventStatus,
    CollaborationEventType,
    DeliveryBatchStatus,
    SalesOrder,
    SalesOrderDeliveryBatch,
    SalesOrderStatus,
)

from .models import (
    ProductionDeliveryBatch,
    ProductionPriority,
    ProductionRunBatch,
    ProductionRunBatchStatus,
    ProductionTask,
    ProductionTaskDetail,
    ProductionTaskProduct,
    ProductionTaskProductImage,
    ProductionTaskStatus,
)


CONTRACT_NUMBER_TOKEN_SALT = "production-task-contract-number"
CONTRACT_NUMBER_TOKEN_MAX_AGE_SECONDS = 24 * 60 * 60
BOM_SYNC_TOKEN_SALT = "production-task-bom-sync"
BOM_SYNC_TOKEN_MAX_AGE_SECONDS = 15 * 60
MAX_IMAGES_PER_PRODUCT_LINE = 20
MAX_PRODUCT_IMAGE_BYTES = 10 * 1024 * 1024


def _production_cny_rate_snapshot():
    return {
        "record_id": None, "base_currency_code": "CNY", "quote_currency_code": "CNY",
        "rate": "1.00000000", "effective_date": None, "source_name": "人民币恒等汇率", "source_version": "",
    }


def _product_line_snapshot_values(*, product, color, data):
    """整理产品行的正式显示快照与客户原始输入。

    在 BOM 确认前，产品主数据可以暂时不存在；此时使用客户输入作为显示快照，
    产品编号、货号等主数据字段留空。已有主数据的旧调用仍沿用原来的快照值。
    """
    customer_product_name = str(data.pop("customer_product_name", "") or "").strip()
    customer_specification = str(data.pop("customer_specification", "") or "").strip()
    customer_color = str(data.pop("customer_color", "") or "").strip()
    color_code = str(data.pop("color_code", "") or "").strip()
    material = str(data.pop("material", "") or "").strip()
    category_input = data.pop("product_category", None)

    if product is not None:
        product_number = product.product_number
        product_code = product.product_code
        item_number = product.product_item.item_number
        product_name = product.product_name
        specification = product.specification
        customer_product_name = customer_product_name or product.product_name
        customer_specification = customer_specification or product.specification
        product_category = product.category
    else:
        product_number = ""
        product_code = ""
        item_number = ""
        product_name = customer_product_name
        specification = customer_specification
        product_category = category_input

    if color is not None:
        color_card = color.color_card
        color_name = color.color_name
        color_code = color_code or color.color_code
        customer_color = customer_color or color.color_name
    else:
        color_card = ""
        color_name = customer_color

    return {
        "product": product,
        "product_category": product_category,
        "product_number_snapshot": product_number,
        "product_code_snapshot": product_code,
        "item_number_snapshot": item_number,
        "product_name_snapshot": product_name,
        "specification_snapshot": specification,
        "customer_product_name_snapshot": customer_product_name,
        "customer_specification_snapshot": customer_specification,
        "customer_color_snapshot": customer_color,
        "material_snapshot": material,
        "product_color": color,
        "color_card_snapshot": color_card,
        "color_name_snapshot": color_name,
        "color_code_snapshot": color_code,
    }


def _bom_sync_token_payload(task, actor_employee, affected_lines):
    return {
        "task_id": str(task.pk),
        "employee_id": str(actor_employee.pk),
        "affected_boms": sorted(
            [
                {
                    "product_line_id": item["product_line_id"],
                    "new_product_id": item["new_product_id"],
                    "new_product_color_id": item["new_product_color_id"],
                    "new_color_code": item["new_color_code"],
                    "new_quantity": item["new_quantity"],
                    "bom_id": item["bom_id"],
                    "bom_version_number": item["bom_version_number"],
                    "bom_updated_at": item["bom_updated_at"],
                }
                for item in affected_lines
            ],
            key=lambda item: (item["product_line_id"], item["bom_id"]),
        ),
    }


def _valid_bom_sync_token(token, task, actor_employee, affected_lines):
    if not token:
        return False
    try:
        payload = signing.loads(
            token,
            salt=BOM_SYNC_TOKEN_SALT,
            max_age=BOM_SYNC_TOKEN_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return False
    return payload == _bom_sync_token_payload(task, actor_employee, affected_lines)


class BomSyncConfirmationRequired(Conflict):
    api_error_code = "BOM_SYNC_CONFIRMATION_REQUIRED"

    def __init__(self, task, actor_employee, affected_lines):
        self.error_meta = {
            "affected_bom_count": len(affected_lines),
            "affected_lines": affected_lines,
            "confirmation_token": signing.dumps(
                _bom_sync_token_payload(task, actor_employee, affected_lines),
                salt=BOM_SYNC_TOKEN_SALT,
            ),
        }
        super().__init__("订单产品、颜色或数量与关联 BOM 不一致，请选择是否同步更新 BOM。")


def _snapshot(task):
    return {
        "task_number": task.task_number,
        "contract_number": task.contract_number,
        "order_number": task.order_number,
        "status": task.status,
        "status_reason": task.status_reason,
        "sales_order_id": str(task.sales_order_id) if task.sales_order_id else None,
        "sales_order_delivery_batch_id": str(task.sales_order_delivery_batch_id) if task.sales_order_delivery_batch_id else None,
        "sales_order_line_id": str(task.sales_order_line_id) if task.sales_order_line_id else None,
        "planned_start_date": task.planned_start_date.isoformat() if task.planned_start_date else None,
        "planned_end_date": task.planned_end_date.isoformat() if task.planned_end_date else None,
        "delivery_date": task.delivery_date.isoformat(),
        "order_date": task.order_date.isoformat(),
        "preproduction_sample_required": task.preproduction_sample_required,
        "planner_id": str(task.planner_id) if task.planner_id else None,
        "production_batch_number": task.production_batch_number,
        "special_requirements_html": task.special_requirements_html,
        "delivery_batches": [
            {"id": str(batch.pk), "delivery_date": batch.delivery_date.isoformat(),
             "quantity": str(batch.quantity), "note": batch.note}
            for batch in task.delivery_batches.order_by("line_number", "id")
        ],
        "production_priority": task.production_priority,
        "actual_quantity": str(task.actual_quantity),
        "actual_good_quantity": str(task.actual_good_quantity),
        "excess_quantity": str(task.excess_quantity),
        "customer_account_id": str(task.customer_account_id) if task.customer_account_id else None,
        "salesperson_id": str(task.salesperson_id),
        "follower_ids": [str(pk) for pk in task.followers.values_list("pk", flat=True)],
        "includes_tax": task.includes_tax,
        "tax_rate": getattr(task, "tax_rate", None),
        "order_tolerance_percent": str(task.order_tolerance_percent),
        "is_repeat_order": task.is_repeat_order,
        "delivery_method": task.delivery_method,
        "freight_amount": str(task.freight_amount),
        "other_fee_amount": str(task.other_fee_amount),
        "products": [
            {
                "id": str(product.pk),
                "source_delivery_batch_line_id": (
                    str(product.sales_order_delivery_batch_line_id)
                    if product.sales_order_delivery_batch_line_id else None
                ),
                "product_name": product.product_name_snapshot,
                "color_name": product.color_name_snapshot,
                "quantity": str(product.quantity),
                "product_id": str(product.product_id) if product.product_id else None,
                "product_category_id": str(product.product_category_id) if product.product_category_id else None,
                "specification": product.specification_snapshot,
                "customer_product_name": product.customer_product_name_snapshot,
                "customer_specification": product.customer_specification_snapshot,
                "customer_color": product.customer_color_snapshot,
                "material": product.material_snapshot,
                "color_code": product.color_code_snapshot,
                "unit_id": str(product.unit_id),
                "currency_id": str(product.currency_id),
                "unit_price": str(product.unit_price),
                "total_amount": str(product.total_amount),
                "exchange_rate": str(product.exchange_rate),
                "exchange_rate_snapshot": product.exchange_rate_snapshot,
                "special_requirements": product.special_requirements,
                "packaging_method": product.packaging_method,
                "image_file_id": str(product.image_file_id) if product.image_file_id else None,
                "images": [{"id": str(image.pk), "image_file_id": str(image.image_file_id),
                            "line_number": image.line_number} for image in product.images.all()],
                "details": [{"id": str(detail.pk), "detail_type": detail.detail_type,
                             "template_key": detail.template_key, "category_label": detail.category_label,
                             "is_selected": detail.is_selected, "description": detail.description,
                             "image_file_id": str(detail.image_file_id) if detail.image_file_id else None}
                            for detail in product.details.all()],
            }
            for product in task.products.order_by("line_number", "id")
        ],
        "run_batches": [{"id": str(batch.pk), "batch_number": batch.batch_number,
                         "planned_quantity": str(batch.planned_quantity),
                         "actual_quantity": str(batch.actual_quantity), "good_quantity": str(batch.good_quantity),
                         "status": batch.status, "note": batch.note} for batch in task.run_batches.all()],
    }


def _bom_relevant_changes(task, products):
    existing_lines = {
        str(line.pk): line
        for line in task.products.select_for_update().all()
    }
    affected_lines = []
    for product_data in products:
        line = existing_lines.get(str(product_data["client_key"]))
        if line is None:
            continue
        latest_bom = (
            line.boms.select_for_update()
            .filter(archived_at__isnull=True)
            .order_by("-version_number", "-id")
            .first()
        )
        if latest_bom is None:
            continue
        incoming_product = product_data.get("product")
        incoming_color = product_data.get("product_color")
        incoming_color_code = product_data.get("color_code", "") or getattr(incoming_color, "color_code", "")
        incoming_product_name = (
            incoming_product.product_name
            if incoming_product is not None
            else str(product_data.get("customer_product_name") or "").strip()
        )
        incoming_product_code = getattr(incoming_product, "product_code", "")
        incoming_product_number = getattr(incoming_product, "product_number", "")
        incoming_quantity = Decimal(product_data["quantity"])
        order_quantity_changed = Decimal(line.quantity) != incoming_quantity
        bom_quantity_outdated = Decimal(latest_bom.order_quantity) != incoming_quantity
        product_changed = line.product_id != getattr(incoming_product, "pk", None)
        color_changed = (
            line.product_color_id != getattr(incoming_color, "pk", None)
            or line.color_code_snapshot != incoming_color_code
        )
        bom_product_outdated = any(
            [
                latest_bom.product_number_snapshot != incoming_product_number,
                latest_bom.product_code_snapshot != incoming_product_code,
                latest_bom.product_name_snapshot != incoming_product_name,
            ]
        )
        if not any(
            [
                order_quantity_changed,
                bom_quantity_outdated,
                product_changed,
                color_changed,
                bom_product_outdated,
            ]
        ):
            continue
        change_types = []
        if order_quantity_changed or bom_quantity_outdated:
            change_types.append("QUANTITY")
        if product_changed or bom_product_outdated:
            change_types.append("PRODUCT")
        if color_changed:
            change_types.append("COLOR")
        affected_lines.append(
            {
                "product_line_id": str(line.pk),
                "product_name": line.product_name_snapshot,
                "old_product_name": line.product_name_snapshot,
                "new_product_id": str(incoming_product.pk) if incoming_product is not None else None,
                "new_product_name": incoming_product_name,
                "color_name": line.color_name_snapshot,
                "old_color_name": line.color_name_snapshot,
                "new_product_color_id": str(incoming_color.pk) if incoming_color is not None else None,
                "new_color_name": (
                    incoming_color.color_name
                    if incoming_color is not None
                    else str(product_data.get("customer_color") or "").strip()
                ),
                "new_color_code": incoming_color_code,
                "old_quantity": str(line.quantity),
                "new_quantity": str(product_data["quantity"]),
                "bom_quantity": str(latest_bom.order_quantity),
                "change_types": change_types,
                "bom_number": latest_bom.bom_number,
                "bom_id": str(latest_bom.pk),
                "bom_version_number": latest_bom.version_number,
                "bom_status": latest_bom.status,
                "bom_updated_at": latest_bom.updated_at.isoformat(),
            }
        )
    return affected_lines


def _image_for(files, field_name, actor_employee, saved_files):
    uploads = files.getlist(field_name)
    if len(uploads) > 1:
        raise ValidationError({field_name: "每个位置只能上传一张图片。"})
    if not uploads:
        return None
    image = save_scanned_image(
        uploads[0],
        actor_employee,
        storage_folder="production_tasks",
        field_label="生产任务单图片",
    )
    saved_files.append(image)
    return image


def _images_for(files, field_name, actor_employee, saved_files):
    uploads = files.getlist(field_name)
    if len(uploads) > MAX_IMAGES_PER_PRODUCT_LINE:
        raise ValidationError({field_name: f"每条颜色明细最多上传 {MAX_IMAGES_PER_PRODUCT_LINE} 张图片。"})
    images = []
    for upload in uploads:
        image = save_scanned_image(
            upload,
            actor_employee,
            storage_folder="production_tasks",
            field_label="生产任务单明细图片",
            max_bytes=MAX_PRODUCT_IMAGE_BYTES,
        )
        saved_files.append(image)
        images.append(image)
    return images


def reserve_contract_number(*, order_date, actor_employee):
    contract_number = next_business_number("SALES_CONTRACT", order_date)
    token = signing.dumps(
        {"contract_number": contract_number, "employee_id": str(actor_employee.pk)},
        salt=CONTRACT_NUMBER_TOKEN_SALT,
    )
    return contract_number, token


def _contract_number_from_token(token, actor_employee, requested_contract_number):
    try:
        payload = signing.loads(
            token,
            salt=CONTRACT_NUMBER_TOKEN_SALT,
            max_age=CONTRACT_NUMBER_TOKEN_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise ValidationError({"contract_number_token": "合同编号已过期，请刷新页面后重新生成。"}) from exc
    except signing.BadSignature as exc:
        raise ValidationError({"contract_number_token": "合同编号校验失败，请刷新页面后重新生成。"}) from exc
    if payload.get("employee_id") != str(actor_employee.pk):
        raise ValidationError({"contract_number_token": "合同编号不属于当前操作人，请刷新页面后重新生成。"})
    reserved_contract_number = str(payload.get("contract_number", "")).strip()
    if not reserved_contract_number:
        raise ValidationError({"contract_number_token": "合同编号校验失败，请刷新页面后重新生成。"})
    contract_number = str(requested_contract_number).strip()
    if not contract_number or ProductionTask.objects.filter(contract_number=contract_number).exists():
        raise ValidationError({"contract_number": "合同编号已被使用，请更换后重试。"})
    return contract_number


def _create_children(
    task,
    products,
    batches,
    files,
    actor_employee,
    *,
    existing_product_images=None,
    existing_detail_images=None,
):
    existing_product_images = existing_product_images or {}
    existing_detail_images = existing_detail_images or {}
    saved_files = []
    try:
        for product_index, product_data in enumerate(products, start=1):
            data = dict(product_data)
            client_key = data.pop("client_key")
            details = data.pop("details", [])
            retained_image_ids = {str(image_id) for image_id in data.pop("retained_image_ids", [])}
            product = data.pop("product", None)
            color = data.pop("product_color", None)
            snapshot_values = _product_line_snapshot_values(product=product, color=color, data=data)
            retained_images = [
                image
                for image in existing_product_images.get(client_key, [])
                if str(image.pk) in retained_image_ids
            ]
            uploaded_images = _images_for(
                files,
                f"product_image_{client_key}",
                actor_employee,
                saved_files,
            )
            product_images = retained_images + uploaded_images
            line = ProductionTaskProduct.objects.create(
                production_task=task,
                line_number=product_index,
                **snapshot_values,
                image_file=product_images[0] if product_images else None,
                total_amount=(data["quantity"] * data["unit_price"]).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                exchange_rate_snapshot=_production_cny_rate_snapshot(),
                **data,
            )
            ProductionTaskProductImage.objects.bulk_create(
                [
                    ProductionTaskProductImage(
                        product_line=line,
                        line_number=image_index,
                        image_file=image,
                    )
                    for image_index, image in enumerate(product_images, start=1)
                ]
            )
            for detail_index, detail_data in enumerate(details, start=1):
                detail = dict(detail_data)
                detail_key = detail.pop("client_key", "")
                detail_image = _image_for(files, f"detail_image_{detail_key}", actor_employee, saved_files) if detail_key else None
                if detail_image is None:
                    detail_image = existing_detail_images.get(detail_key)
                ProductionTaskDetail.objects.create(
                    product_line=line,
                    line_number=detail_index,
                    image_file=detail_image,
                    **detail,
                )
        for batch_index, batch_data in enumerate(batches, start=1):
            ProductionDeliveryBatch.objects.create(
                production_task=task,
                line_number=batch_index,
                **batch_data,
            )
    except Exception:
        # 数据库事务会回滚记录；已落盘文件由现有文件清理任务按无引用文件回收。
        raise


def _reported_quantity_lower_bound(rows):
    """报工按工序次数计量，依据冻结口径折算成品当量，不能直接相加各工序。"""
    by_work_item = {}
    legacy_floor = Decimal("0")
    for row in rows:
        order_quantity = Decimal(row["order_quantity_snapshot"])
        required_quantity = row["required_quantity_snapshot"]
        # 旧记录缺少折算口径时，保留其原成品数量下限，不猜测倍数。
        if not required_quantity:
            legacy_floor = max(legacy_floor, order_quantity)
            continue
        equivalent = Decimal(row["quantity"]) * order_quantity / Decimal(required_quantity)
        key = row["work_item_id"]
        by_work_item[key] = by_work_item.get(key, Decimal("0")) + equivalent
    return max(legacy_floor, max(by_work_item.values(), default=Decimal("0")))


def _validate_sales_products(task, products, files):
    from .selectors import max_production_quantity, production_quantity_source

    existing_lines = list(task.products.select_related("sales_order_delivery_batch_line").all())
    if not task.sales_order_id and not any(line.sales_order_delivery_batch_line_id for line in existing_lines):
        return
    if files:
        raise ValidationError({"products": "销售来源产品的图片和明细只读，不允许上传文件。"})
    existing_by_id = {str(line.pk): line for line in existing_lines}
    requested_by_source = {}
    maximum_by_source = {}
    if set(existing_by_id) != {str(item["client_key"]) for item in products} or len(products) != len(existing_lines):
        raise ValidationError({"products": "销售订单来源产品不可新增或删除；请回到销售订单交付批次调整。"})
    for product_data in products:
        line = existing_by_id.get(str(product_data["client_key"]))
        if line is None:
            raise ValidationError({"products": "销售订单来源产品不可新增或改为无来源产品。"})
        incoming_product = product_data.get("product")
        if line.product_id != getattr(incoming_product, "pk", None):
            raise ValidationError({"products": f"产品“{line.product_name_snapshot}”由销售订单锁定，不能替换。"})
        incoming_color = product_data.get("product_color")
        if (
            line.product_color_id != getattr(incoming_color, "pk", None)
            or line.color_code_snapshot != product_data.get("color_code", "")
            or line.customer_color_snapshot != product_data.get("customer_color", "")
        ):
            raise ValidationError({"products": f"产品“{line.product_name_snapshot}”的颜色由销售订单锁定。"})
        for name in ("customer_product_name", "customer_specification", "material"):
            if name in product_data and product_data[name] != getattr(line, f"{name}_snapshot"):
                raise ValidationError({"products": "销售来源产品名称、规格和材质不可修改。"})
        if "product_category" in product_data and getattr(product_data["product_category"], "pk", None) != line.product_category_id:
            raise ValidationError({"products": "销售来源产品分类不可修改。"})
        source = production_quantity_source(line)
        maximum = max_production_quantity(line)
        if source is None and int(product_data["quantity"]) != int(line.quantity):
            raise ValidationError({"products": "UNKNOWN：历史销售产品缺少可确认的交付批次行，不能调整数量。"})
        if source is not None:
            requested_by_source[source.pk] = requested_by_source.get(source.pk, 0) + int(product_data["quantity"])
            maximum_by_source[source.pk] = maximum
        if maximum is not None and int(product_data["quantity"]) > maximum:
            raise ValidationError({"products": f"产品“{line.product_name_snapshot}”本次生产数量最多为 {maximum}。"})
        if line.unit_id != product_data["unit"].pk or line.currency_id != product_data["currency"].pk:
            raise ValidationError({"products": f"产品“{line.product_name_snapshot}”的单位和币种由销售订单锁定。"})
        if Decimal(line.exchange_rate) != Decimal(product_data["exchange_rate"]):
            raise ValidationError({"products": "销售来源汇率快照不可修改。"})
        if Decimal(line.unit_price) != Decimal(product_data["unit_price"]):
            raise ValidationError({"products": f"产品“{line.product_name_snapshot}”的单价由销售订单锁定。"})
        for name in ("special_requirements", "packaging_method"):
            if name in product_data and product_data[name] != getattr(line, name):
                raise ValidationError({"products": "销售来源产品的生产要求和包装方式不可修改。"})
        if product_data.get("replace_primary_image"):
            raise ValidationError({"products": "销售来源产品图片不可替换。"})
        if "retained_image_ids" in product_data:
            expected_images = set(line.images.values_list("image_file_id", flat=True))
            if set(product_data["retained_image_ids"]) != expected_images:
                raise ValidationError({"products": "销售来源产品图片不可新增、删除或替换。"})
        if "details" in product_data:
            details_by_id = {str(detail.pk): detail for detail in line.details.all()}
            incoming_details = product_data["details"]
            if len(incoming_details) != len(details_by_id):
                raise ValidationError({"products": "销售来源产品明细不可新增或删除。"})
            for detail_data in incoming_details:
                detail = details_by_id.get(str(detail_data.get("client_key", "")))
                if detail is None or any(
                    name in detail_data and detail_data[name] != getattr(detail, name)
                    for name in ("template_key", "detail_type", "category_label", "is_selected", "description")
                ):
                    raise ValidationError({"products": "销售来源产品明细不可修改或替换。"})
    for source_id, quantity in requested_by_source.items():
        if quantity > maximum_by_source[source_id]:
            raise ValidationError({"products": f"同一销售交付批次行的本次生产数量合计最多为 {maximum_by_source[source_id]}。"})


def _sync_children(
    task,
    products,
    batches,
    files,
    actor_employee,
    *,
    allow_bom_product_change=False,
):
    """按现有明细编号原位更新，避免删除被 BOM 引用的产品明细。"""
    saved_files = []
    existing_lines = list(
        task.products.select_related("image_file")
        .prefetch_related("images__image_file", "details__image_file", "boms")
    )
    existing_by_id = {str(line.pk): line for line in existing_lines}
    incoming_existing_ids = {
        str(product_data["client_key"])
        for product_data in products
        if str(product_data["client_key"]) in existing_by_id
    }

    removed_lines = [line for line in existing_lines if str(line.pk) not in incoming_existing_ids]
    for line in removed_lines:
        if line.boms.exists():
            raise Conflict(f"产品“{line.product_name_snapshot}”已生成 BOM，不能删除或更换。")
        if line.schedule_products.exists():
            raise Conflict(f"产品“{line.product_name_snapshot}”已有排产历史，不能从生产任务单删除。")
        from .selectors import external_business_blocker
        blocker = external_business_blocker(line)
        if blocker:
            raise Conflict(f"产品“{line.product_name_snapshot}”：{blocker}")

    total_quantity = sum(Decimal(item["quantity"]) for item in products)
    actual_quantity = max(task.actual_quantity, task.actual_good_quantity,
                          task.run_batches.aggregate(total=Sum("actual_quantity"))["total"] or Decimal("0"),
                          task.run_batches.aggregate(total=Sum("good_quantity"))["total"] or Decimal("0"))
    if total_quantity < actual_quantity:
        raise Conflict(f"任务数量不能低于已有实际生产数量 {actual_quantity}。")
    if batches is None:
        existing_batches = list(task.delivery_batches.select_for_update().all())
        if len(existing_batches) == 1:
            batch = existing_batches[0]
            if batch.quantity != total_quantity:
                batch.quantity = total_quantity
                batch.save(update_fields=["quantity", "updated_at"])
        elif existing_batches and sum(batch.quantity for batch in existing_batches) != total_quantity:
            raise ValidationError({"delivery_batches": "修改产品总数量时，请同时调整已有各交付批次数量，保证合计一致。"})

    # 先把旧序号移到临时区，支持安全调整行顺序并避免唯一约束冲突。
    for offset, line in enumerate(existing_lines, start=1):
        line.line_number = 1_000_000 + offset
        line.save(update_fields=["line_number"])

    try:
        for product_index, product_data in enumerate(products, start=1):
            data = dict(product_data)
            client_key = str(data.pop("client_key"))
            replace_primary_image = data.pop("replace_primary_image", False)
            details = data.pop("details", [])
            retained_image_ids = {str(image_id) for image_id in data.pop("retained_image_ids", [])}
            product = data.pop("product", None)
            color = data.pop("product_color", None)
            snapshot_values = _product_line_snapshot_values(product=product, color=color, data=data)
            line = existing_by_id.get(client_key)

            if line is not None:
                from apps.workshop_reporting.models import WorkReportLine
                reported = _reported_quantity_lower_bound(WorkReportLine.objects.filter(
                    report__product_line=line,
                ).values("quantity", "work_item_id", "order_quantity_snapshot", "required_quantity_snapshot"))
                if Decimal(data["quantity"]) < reported:
                    raise Conflict(f"产品“{line.product_name_snapshot}”数量不能低于已有报工折算成品数量 {reported}。")

            if line is not None and line.schedule_products.exists():
                active_planned = line.schedule_products.filter(
                    schedule__record_status="ACTIVE", removed_at__isnull=True
                ).order_by("-planned_quantity").first()
                if line.product_id != getattr(product, "pk", None) or line.unit_id != data["unit"].pk:
                    raise Conflict(f"产品“{line.product_name_snapshot}”已有排产历史，不能更换产品或单位。")
                if active_planned is not None and int(data["quantity"]) < int(active_planned.planned_quantity):
                    raise Conflict(
                        f"产品“{line.product_name_snapshot}”当前有效排产数量为 {active_planned.planned_quantity}，"
                        "任务数量不能下调到该值以下。"
                    )

            if (
                line is not None
                and line.product_id != getattr(product, "pk", None)
                and line.boms.exists()
                and not allow_bom_product_change
            ):
                raise Conflict(f"产品“{line.product_name_snapshot}”已生成 BOM，不能更换产品。")

            if line is not None and (task.sales_order_id or line.sales_order_delivery_batch_line_id):
                # 来源产品只更新本次数量；即使调用方省略图片、明细等字段，也完整保留。
                line.line_number = product_index
                line.quantity = data["quantity"]
                line.total_amount = (line.quantity * line.unit_price).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP,
                )
                line.full_clean()
                line.save(update_fields=["line_number", "quantity", "total_amount", "updated_at"])
                continue

            existing_image_links = list(line.images.all()) if line is not None else []
            retained_links = [
                link for link in existing_image_links if str(link.image_file_id) in retained_image_ids
            ]
            retained_link_image_ids = {str(link.image_file_id) for link in retained_links}
            retained_unlinked_images = []
            if (
                line is not None
                and line.image_file_id
                and str(line.image_file_id) in retained_image_ids
                and str(line.image_file_id) not in retained_link_image_ids
            ):
                retained_unlinked_images.append(line.image_file)
            uploaded_images = _images_for(
                files,
                f"product_image_{client_key}",
                actor_employee,
                saved_files,
            )
            if replace_primary_image and not uploaded_images:
                raise ValidationError({f"product_image_{client_key}": "替换主图时必须上传新图片。"})
            retained_images = [link.image_file for link in retained_links] + retained_unlinked_images
            product_images = (uploaded_images + retained_images if replace_primary_image
                              else retained_images + uploaded_images)
            if len(product_images) > MAX_IMAGES_PER_PRODUCT_LINE:
                raise ValidationError(
                    {f"product_image_{client_key}": f"每条颜色明细最多保留 {MAX_IMAGES_PER_PRODUCT_LINE} 张图片。"}
                )

            if line is None:
                line = ProductionTaskProduct(production_task=task)
                if data["currency"].code == "CNY":
                    line.exchange_rate_snapshot = _production_cny_rate_snapshot()
            line.line_number = product_index
            line.product = product
            if not task.sales_order_id and not line.sales_order_delivery_batch_line_id:
                for field_name, value in snapshot_values.items():
                    setattr(line, field_name, value)
            line.image_file = product_images[0] if product_images else None
            if not task.sales_order_id and not line.sales_order_delivery_batch_line_id:
                # 没有销售订单来源的行允许在 BOM 前由客户文本暂存产品信息。
                for field_name, value in snapshot_values.items():
                    setattr(line, field_name, value)
            line.total_amount = (data["quantity"] * data["unit_price"]).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )
            for field_name, value in data.items():
                setattr(line, field_name, value)
            line.full_clean()
            line.save()

            retained_link_ids = {link.pk for link in retained_links}
            for link in existing_image_links:
                if link.pk not in retained_link_ids:
                    link.delete()
            for image_index, link in enumerate(retained_links, start=1):
                link.line_number = 1_000_000 + image_index
                link.save(update_fields=["line_number"])
            for image_index, link in enumerate(retained_links, start=1):
                link.line_number = image_index + (len(uploaded_images) if replace_primary_image else 0)
                link.save(update_fields=["line_number"])
            unlinked = (uploaded_images + retained_unlinked_images if replace_primary_image
                        else retained_unlinked_images + uploaded_images)
            for image_index, image in enumerate(unlinked):
                if replace_primary_image and image_index < len(uploaded_images):
                    next_image_number = image_index + 1
                else:
                    next_image_number = len(retained_links) + image_index + 1
                ProductionTaskProductImage.objects.create(
                    product_line=line,
                    line_number=next_image_number,
                    image_file=image,
                )

            existing_details = list(line.details.all())
            existing_details_by_id = {str(detail.pk): detail for detail in existing_details}
            incoming_detail_ids = {
                str(detail_data.get("client_key", ""))
                for detail_data in details
                if str(detail_data.get("client_key", "")) in existing_details_by_id
            }
            for detail in existing_details:
                detail.line_number = 1_000_000 + detail.line_number
                detail.save(update_fields=["line_number"])
            for detail_index, detail_data in enumerate(details, start=1):
                detail_values = dict(detail_data)
                detail_key = str(detail_values.pop("client_key", ""))
                detail = existing_details_by_id.get(detail_key)
                detail_image = (
                    _image_for(files, f"detail_image_{detail_key}", actor_employee, saved_files)
                    if detail_key
                    else None
                )
                detail = detail or ProductionTaskDetail(product_line=line)
                detail.line_number = detail_index
                if detail_image is not None:
                    detail.image_file = detail_image
                for field_name, value in detail_values.items():
                    setattr(detail, field_name, value)
                detail.full_clean()
                detail.save()
            for detail in existing_details:
                if str(detail.pk) not in incoming_detail_ids:
                    detail.delete()

        for line in removed_lines:
            ProductionTaskDetail.objects.filter(product_line=line).delete()
            ProductionTaskProductImage.objects.filter(product_line=line).delete()
            try:
                line.delete()
            except ProtectedError as exc:
                raise Conflict(f"产品“{line.product_name_snapshot}”已被其他业务数据引用，不能删除或更换。") from exc

        if batches is not None:
            ProductionDeliveryBatch.objects.filter(production_task=task).delete()
            for batch_index, batch_data in enumerate(batches, start=1):
                ProductionDeliveryBatch.objects.create(
                    production_task=task,
                    line_number=batch_index,
                    **batch_data,
                )
    except Exception:
        # 数据库事务会回滚记录；已落盘文件由现有文件清理任务按无引用文件回收。
        raise


def replace_unbound_product_line(*, task, product_line, product_data, files, actor_employee, request):
    """为尚未生成 BOM 的颜色行更换产品，并复用生产任务单的明细校验结果。"""
    if product_line.sales_order_delivery_batch_line_id:
        raise Conflict("该颜色明细来源于销售订单，产品、颜色和数量必须保持锁定。")
    if product_line.boms.select_for_update().exists():
        raise Conflict("该颜色明细已经生成 BOM，不能更换产品。")
    if product_line.schedule_products.exists():
        raise Conflict("该颜色明细已有排产历史，不能更换产品。")

    before_data = _snapshot(task)
    data = dict(product_data)
    client_key = str(data.pop("client_key"))
    details = data.pop("details", [])
    data.pop("retained_image_ids", None)
    product = data.pop("product", None)
    color = data.pop("product_color", None)
    snapshot_values = _product_line_snapshot_values(product=product, color=color, data=data)
    saved_files = []

    uploaded_images = _images_for(
        files,
        f"product_image_{client_key}",
        actor_employee,
        saved_files,
    )
    ProductionTaskProductImage.objects.filter(product_line=product_line).delete()
    ProductionTaskDetail.objects.filter(product_line=product_line).delete()

    for field_name, value in snapshot_values.items():
        setattr(product_line, field_name, value)
    product_line.image_file = uploaded_images[0] if uploaded_images else None
    product_line.total_amount = (data["quantity"] * data["unit_price"]).quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )
    for field_name, value in data.items():
        setattr(product_line, field_name, value)
    product_line.full_clean()
    product_line.save()

    ProductionTaskProductImage.objects.bulk_create(
        [
            ProductionTaskProductImage(product_line=product_line, line_number=index, image_file=image)
            for index, image in enumerate(uploaded_images, start=1)
        ]
    )
    for index, detail_data in enumerate(details, start=1):
        values = dict(detail_data)
        detail_key = str(values.pop("client_key", ""))
        detail_image = _image_for(
            files,
            f"detail_image_{detail_key}",
            actor_employee,
            saved_files,
        ) if detail_key else None
        detail = ProductionTaskDetail(
            product_line=product_line,
            line_number=index,
            image_file=detail_image,
            **values,
        )
        detail.full_clean()
        detail.save()

    task.updated_at = timezone.now()
    task.save(update_fields=["updated_at"])
    write_audit_log(
        object_type="PRODUCTION_TASK",
        object_id=task.pk,
        **_audit_context(task),
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=_snapshot(task),
        request=request,
    )
    return product_line


def _create_numbered_task(**values):
    task_number = values.get("task_number", "")
    if not isinstance(task_number, str) or len(task_number) > 50 or re.fullmatch(r"HT[0-9]+(?:-[0-9]+)*", task_number) is None:
        raise ValidationError({"task_number": "生产任务单号必须为 HT 加数字，可用连字符连接数字。"})
    try:
        with transaction.atomic():
            return ProductionTask.objects.create(**values)
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", "")
        if constraint == "production_task_task_number_key":
            raise ValidationError({"task_number": "生产任务单号已存在，请更换后重试。"}) from exc
        raise


def _audit_context(task):
    if task.sales_order_id:
        return {"context_type": "SALES_ORDER", "context_id": task.sales_order_id}
    if task.customer_account_id:
        return {"context_type": "CUSTOMER_ACCOUNT", "context_id": task.customer_account_id}
    return {"context_type": "", "context_id": None}


def _validate_task_tax(*, includes_tax, tax_rate):
    if includes_tax and tax_rate not in {3, 5, 7}:
        raise ValidationError({"tax_rate": "含税时税率必须选择 3%、5% 或 7%。"})
    if not includes_tax and tax_rate is not None:
        raise ValidationError({"tax_rate": "不含税时税率必须为空。"})


def _validate_followers(followers):
    follower_ids = {employee.pk for employee in followers}
    if not follower_ids:
        raise ValidationError({"follower_ids": "必须选择生产跟单员。"})
    valid_count = Employee.objects.filter(
        pk__in=follower_ids, status=EmployeeStatus.ACTIVE, archived_at__isnull=True,
    ).count()
    if valid_count != len(follower_ids):
        raise ValidationError({"follower_ids": "跟单员已停用或归档，请重新选择。"})


def _sync_sales_delivery_date(*, task, actor_employee, request):
    if not task.sales_order_id or not task.sales_order_delivery_batch_id:
        return
    source_order = SalesOrder.objects.select_for_update().get(pk=task.sales_order_id)
    source_batch = SalesOrderDeliveryBatch.objects.select_for_update().get(
        pk=task.sales_order_delivery_batch_id, sales_order=source_order,
    )
    if source_batch.planned_delivery_date == task.delivery_date:
        return
    before_date = source_batch.planned_delivery_date
    source_batch.planned_delivery_date = task.delivery_date
    source_batch.save(update_fields=["planned_delivery_date", "updated_at"])
    # 刷新销售订单 ETag，阻止旧页面覆盖已由生产侧同步的交期。
    source_order.save(update_fields=["updated_at"])
    write_audit_log(
        object_type="SALES_ORDER", object_id=source_order.pk,
        context_type="SALES_ORDER", context_id=source_order.pk,
        action="PRODUCTION_DELIVERY_DATE_UPDATED", actor_employee=actor_employee,
        before_data={"delivery_batch_id": str(source_batch.pk), "planned_delivery_date": before_date.isoformat()},
        after_data={"delivery_batch_id": str(source_batch.pk), "planned_delivery_date": task.delivery_date.isoformat(), "production_task_id": str(task.pk)},
        request=request,
    )


@transaction.atomic
def create_production_task(*, validated_data, files, actor_employee, request):
    validated_data.pop("bom_sync_mode", None)
    validated_data.pop("bom_sync_token", None)
    products = validated_data.pop("products")
    batches = validated_data.pop("delivery_batches", [])
    followers = validated_data.pop("followers", [])
    _validate_followers(followers)
    if validated_data.get("customer_account") is not None:
        raise ValidationError({"customer_account_id": "手动生产任务单不关联客户。"})
    if validated_data["currency"].code != "CNY" or any(item["currency"].code != "CNY" for item in products):
        raise ValidationError({"currency_id": "手动生产任务单必须使用人民币 CNY。"})
    _validate_task_tax(includes_tax=validated_data["includes_tax"], tax_rate=validated_data.get("tax_rate"))
    validated_data["order_source"] = "REPEAT" if validated_data["is_repeat_order"] else "NEW"
    contract_number = _contract_number_from_token(
        validated_data.pop("contract_number_token"),
        actor_employee,
        validated_data.pop("contract_number"),
    )
    task = _create_numbered_task(
        contract_number=contract_number,
        created_by_employee=actor_employee,
        status=ProductionTaskStatus.DRAFT,
        **validated_data,
    )
    task.followers.set(followers)
    _create_children(task, products, batches, files, actor_employee)
    write_audit_log(
        object_type="PRODUCTION_TASK",
        object_id=task.pk,
        **_audit_context(task),
        action="CREATED",
        actor_employee=actor_employee,
        after_data=_snapshot(task),
        request=request,
    )
    return task


@transaction.atomic
def update_production_task(*, task, validated_data, files, actor_employee, request):
    task = ProductionTask.objects.select_for_update().get(pk=task.pk)
    require_matching_etag(request, task)
    original_status = task.status
    if original_status in {ProductionTaskStatus.COMPLETED, ProductionTaskStatus.CANCELLED}:
        raise Conflict("已完成或已取消的生产订单属于历史记录，不能再修改。")
    if task.sales_order_id:
        if set(validated_data) & {"salesperson", "order_date", "preproduction_sample_required"}:
            raise ValidationError("销售来源任务的业务员、下单日期和产前样要求不可修改。")
        # 与销售来源创建使用同一订单锁，数量检查和保存必须串行完成。
        SalesOrder.objects.select_for_update().get(pk=task.sales_order_id)
        if task.sales_order_delivery_batch_id:
            SalesOrderDeliveryBatch.objects.select_for_update().get(pk=task.sales_order_delivery_batch_id)
        from apps.sales_orders.models import SalesOrderDeliveryBatchLine
        list(SalesOrderDeliveryBatchLine.objects.select_for_update().filter(
            delivery_batch_id=task.sales_order_delivery_batch_id,
        ).order_by("pk"))
    _validate_task_tax(includes_tax=validated_data.get("includes_tax", task.includes_tax),
                       tax_rate=validated_data.get("tax_rate", task.tax_rate))
    start = validated_data.get("planned_start_date", task.planned_start_date)
    end = validated_data.get("planned_end_date", task.planned_end_date)
    if (start is None) != (end is None) or (start and end and end < start):
        raise ValidationError({"planned_end_date": "计划开始和完工日期须同时填写，完工不能早于开始。"})
    batch_dates = validated_data.pop("delivery_batch_dates", None)
    date_changes = []
    if batch_dates is not None:
        if not batch_dates or set(validated_data) - {"delivery_date"}:
            raise ValidationError({"delivery_batch_dates": "请单独提交非空的批次日期，可同时提交任务交期。"})
        batch_ids = [item["id"] for item in batch_dates]
        existing = {item.pk: item for item in task.delivery_batches.select_for_update().filter(pk__in=batch_ids)}
        if len(set(batch_ids)) != len(batch_ids) or len(existing) != len(batch_ids):
            raise ValidationError({"delivery_batch_dates": "批次编号重复、不存在或不属于当前任务。"})
        for item in batch_dates:
            batch = existing[item["id"]]
            if item["delivery_date"] < task.order_date:
                raise ValidationError({"delivery_batch_dates": "分批交期不能早于下单日期。"})
            if batch.delivery_date != item["delivery_date"]:
                date_changes.append((batch, item["delivery_date"]))
        if not date_changes and validated_data.get("delivery_date", task.delivery_date) == task.delivery_date:
            raise ValidationError({"delivery_batch_dates": "日期没有变化，无需保存。"})
    bom_sync_mode = validated_data.pop("bom_sync_mode", None)
    bom_sync_token = validated_data.pop("bom_sync_token", None)
    products = validated_data.pop("products", None)
    batches = validated_data.pop("delivery_batches", None)
    followers = validated_data.pop("followers", None)
    if batches is not None and products is None:
        raise ValidationError(
            {"delivery_batches": "修改生产批次时必须同时提交产品明细，以便校验数量一致性。"}
        )
    if not validated_data and products is None and followers is None and batch_dates is None:
        raise ValidationError("请至少提交一个需要修改的字段。")
    if products is not None:
        _validate_sales_products(task, products, files)
    affected_lines = _bom_relevant_changes(task, products) if products is not None else []
    if affected_lines and (
        bom_sync_mode is None
        or not _valid_bom_sync_token(bom_sync_token, task, actor_employee, affected_lines)
    ):
        raise BomSyncConfirmationRequired(task, actor_employee, affected_lines)
    if affected_lines and bom_sync_mode == "SYNC" and not request.user.has_perm("boms.change_bom"):
        raise PermissionDenied("当前账号没有修改 BOM 的权限，可选择仅保存订单。")
    if (
        affected_lines
        and bom_sync_mode == "SYNC"
        and any(item["bom_status"] == "VERIFIED" for item in affected_lines)
        and not request.user.has_perm("boms.add_bom")
    ):
        raise PermissionDenied("已校验 BOM 需要建立新版本，当前账号没有新建 BOM 的权限。")

    before_data = _snapshot(task)
    for field_name, value in validated_data.items():
        setattr(task, field_name, value)
    if "is_repeat_order" in validated_data:
        task.order_source = "REPEAT" if task.is_repeat_order else "NEW"
    if original_status in {
        ProductionTaskStatus.PENDING_VALIDATION,
        ProductionTaskStatus.READY,
    }:
        task.status = ProductionTaskStatus.DRAFT
        task.submitted_at = None
    task.full_clean()
    task.save()
    if "delivery_date" in validated_data:
        _sync_sales_delivery_date(task=task, actor_employee=actor_employee, request=request)
    for batch, delivery_date in date_changes:
        batch.delivery_date = delivery_date
        batch.save(update_fields=["delivery_date", "updated_at"])
    if followers is not None:
        _validate_followers(followers)
        task.followers.set(followers)
    if products is not None:
        _sync_children(
            task,
            products,
            batches,
            files,
            actor_employee,
            allow_bom_product_change=bom_sync_mode in {"SYNC", "KEEP"},
        )
    if affected_lines and bom_sync_mode == "SYNC":
        from apps.boms.services import sync_latest_boms_from_order

        sync_latest_boms_from_order(
            product_line_ids=[item["product_line_id"] for item in affected_lines],
            actor_employee=actor_employee,
            request=request,
        )
    if products is not None:
        from apps.boms.notification_events import expire_task_bom_events
        expire_task_bom_events(task.pk)
    write_audit_log(
        object_type="PRODUCTION_TASK",
        object_id=task.pk,
        **_audit_context(task),
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=_snapshot(task),
        request=request,
    )
    return task


@transaction.atomic
def delete_production_task(*, task, actor_employee, request):
    from .selectors import external_business_blocker

    task = ProductionTask.objects.select_for_update().get(pk=task.pk)
    require_matching_etag(request, task)
    if task.status != ProductionTaskStatus.CANCELLED:
        raise Conflict("只有已取消且没有下游业务记录的生产任务单可以删除。")
    if task.actual_quantity or task.actual_good_quantity:
        raise Conflict("任务已有实际生产数量，不能删除。")
    runs = list(task.run_batches.select_for_update().all())
    if any(batch.actual_quantity or batch.good_quantity or batch.started_at or batch.completed_at
           or batch.status not in {ProductionRunBatchStatus.PLANNED, ProductionRunBatchStatus.CANCELLED}
           for batch in runs):
        raise Conflict("生产批已有开工或实际生产记录，不能删除。")
    products = list(task.products.select_for_update().all())
    for record in [task, *products, *runs, *task.delivery_batches.all()]:
        blocker = external_business_blocker(record)
        if blocker:
            raise Conflict(blocker)
    before_data = _snapshot(task)
    before_data["deleted_records"] = json.loads(json.dumps({
        "task": ProductionTask.objects.filter(pk=task.pk).values().get(),
        "followers": list(task.follower_links.values()),
        "products": list(task.products.values()),
        "images": list(ProductionTaskProductImage.objects.filter(product_line__production_task=task).values()),
        "details": list(ProductionTaskDetail.objects.filter(product_line__production_task=task).values()),
        "delivery_batches": list(task.delivery_batches.values()),
        "run_batches": list(task.run_batches.values()),
    }, cls=DjangoJSONEncoder))
    write_audit_log(object_type="PRODUCTION_TASK", object_id=task.pk, **_audit_context(task),
                    action="DELETED", actor_employee=actor_employee, before_data=before_data,
                    after_data={"deleted": True}, request=request)
    try:
        # 只移除本单所有的关联记录，BusinessFile、销售、产品和审计均不删除。
        ProductionTaskDetail.objects.filter(product_line__production_task=task).delete()
        ProductionTaskProductImage.objects.filter(product_line__production_task=task).delete()
        task.run_batches.all().delete()
        task.delivery_batches.all().delete()
        task.follower_links.all().delete()
        task.products.all().delete()
        task.delete()
    except ProtectedError as exc:
        raise Conflict("任务或产品仍被下游业务引用，不能删除；请刷新并检查关联记录。") from exc


@transaction.atomic
def submit_production_task(*, task, actor_employee, request):
    task = ProductionTask.objects.select_for_update().prefetch_related("products", "delivery_batches").get(pk=task.pk)
    if task.status not in {ProductionTaskStatus.DRAFT, ProductionTaskStatus.PENDING_VALIDATION}:
        raise Conflict("当前状态不能再次提交校验。")
    products = list(task.products.all())
    if not products:
        raise ValidationError({"products": "请至少添加一个产品。"})
    total_quantity = sum((item.quantity for item in products), Decimal("0"))
    batches = list(task.delivery_batches.all())
    batch_total = sum((item.quantity for item in batches), Decimal("0"))
    if batches and total_quantity != batch_total:
        raise ValidationError(
            {"delivery_batches": f"任务总数 {total_quantity} 与分批合计 {batch_total} 不一致，请确认差异后再提交。"}
        )
    before_data = _snapshot(task)
    task.status = ProductionTaskStatus.PENDING_VALIDATION
    task.submitted_at = timezone.now()
    task.save(update_fields=["status", "submitted_at", "updated_at"])
    write_audit_log(
        object_type="PRODUCTION_TASK",
        object_id=task.pk,
        **_audit_context(task),
        action="SUBMITTED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=_snapshot(task),
        request=request,
    )
    return task


@transaction.atomic
def transition_production_task(*, task, target_status, actor_employee, request):
    from apps.access_control.production_approval import check_production_approval
    allowed = {
        ProductionTaskStatus.PENDING_VALIDATION: ProductionTaskStatus.READY,
    }
    task = ProductionTask.objects.select_for_update().get(pk=task.pk)
    check_production_approval(actor_employee, task)
    if allowed.get(task.status) != target_status:
        raise Conflict("当前生产任务单状态不能执行此操作。")
    before_data = _snapshot(task)
    task.status = target_status
    task.status_reason = ""
    task.save(update_fields=["status", "status_reason", "updated_at"])
    write_audit_log(
        object_type="PRODUCTION_TASK", object_id=task.pk, **_audit_context(task),
        action="CONFIRMED" if target_status == ProductionTaskStatus.READY else "STARTED",
        actor_employee=actor_employee, before_data=before_data, after_data=_snapshot(task), request=request,
    )
    _register_task_confirmed(task, actor_employee)
    return task


def _register_task_confirmed(task, actor_employee):
    from apps.wecom.notification_services import register_business_event

    # 确认时间来自本次已保存状态；两条入口使用同一事件契约。
    version = task.updated_at.isoformat()
    names = list(task.products.order_by("line_number", "id").values_list("product_name_snapshot", flat=True))
    product_name = "未记录产品"
    if names:
        product_name = names[0]
        if len(names) > 1:
            product_name = f"{product_name}等{len(names)}项产品"
    register_business_event(
        event_code="PRODUCTION_TASK_CONFIRMED",
        idempotency_key=f"PRODUCTION_TASK_CONFIRMED:{task.pk}:{version}",
        object_type="production_tasks.ProductionTask", object_id=task.pk, object_version=version,
        context={"document_no": task.task_number, "product_name": product_name, "operator": actor_employee.display_name,
                 "occurred_at": version, "status": task.get_status_display()},
    )


@transaction.atomic
def close_production_task(*, task, target_status, reason, actor_employee, request):
    if target_status not in {ProductionTaskStatus.CANCELLED, ProductionTaskStatus.COMPLETED}:
        raise ValidationError({"status": "目标状态不正确。"})

    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValidationError({"reason": "请填写操作原因。"})

    task = ProductionTask.objects.select_for_update().get(pk=task.pk)
    if task.status in {ProductionTaskStatus.CANCELLED, ProductionTaskStatus.COMPLETED}:
        raise Conflict("订单已经结束或取消，不能重复操作。")

    before_data = _snapshot(task)
    task.status = target_status
    task.status_reason = normalized_reason
    task.save(update_fields=["status", "status_reason", "updated_at"])
    write_audit_log(
        object_type="PRODUCTION_TASK",
        object_id=task.pk,
        **_audit_context(task),
        action="CANCELLED" if target_status == ProductionTaskStatus.CANCELLED else "COMPLETED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=_snapshot(task),
        request=request,
    )
    return task


@transaction.atomic
def create_production_order_from_sales_order(*, validated_data, actor_employee, request=None):
    from apps.sales_orders.models import SalesOrderDeliveryBatchLine
    from .selectors import production_sales_order_sources

    submitted_lines = validated_data.get("lines")
    if submitted_lines:
        requested_items = submitted_lines
        submitted_batch_id = validated_data["delivery_batch"].pk
    else:
        requested_items = [{
            "delivery_batch_line": validated_data["delivery_batch_line"],
            "quantity": validated_data["quantity"],
            **({"product_color": validated_data["product_color"]} if "product_color" in validated_data else {}),
        }]
        submitted_batch_id = validated_data["delivery_batch_line"].delivery_batch_id

    request_key = validated_data.get("request_key")
    if request_key:
        actor_employee.__class__.objects.select_for_update().get(pk=actor_employee.pk)
        existing_task = ProductionTask.objects.filter(source_request_key=request_key).first()
        if existing_task is not None:
            if existing_task.created_by_employee_id != actor_employee.pk:
                raise Conflict("本次请求标识已被其他账号使用，请刷新页面后重试。")
            if existing_task.sales_order_delivery_batch_id != submitted_batch_id:
                raise Conflict("本次请求标识对应的销售交付批次不一致，请刷新页面后重试。")
            existing_items = {
                (
                    item.sales_order_delivery_batch_line_id,
                    int(item.quantity),
                    item.product_color_id,
                    item.special_requirements,
                    item.packaging_method,
                )
                for item in existing_task.products.all()
            }
            submitted_items = {
                (
                    item["delivery_batch_line"].pk,
                    int(item["quantity"]),
                    (getattr(item["product_color"], "pk", None) if "product_color" in item
                     else item["delivery_batch_line"].sales_order_line.product_color_id),
                    item.get("special_requirements", item["delivery_batch_line"].sales_order_line.quality_requirements),
                    item.get("packaging_method", item["delivery_batch_line"].sales_order_line.packaging_requirements),
                )
                for item in requested_items
            }
            common_payload_matches = all((
                existing_task.task_number == validated_data.get("task_number"),
                existing_task.planned_start_date == validated_data.get("planned_start_date"),
                existing_task.planned_end_date == validated_data.get("planned_end_date"),
                existing_task.production_priority == validated_data.get("production_priority", ProductionPriority.NORMAL),
                existing_task.production_batch_number == validated_data.get("production_batch_number", ""),
                existing_task.planner_id == getattr(validated_data.get("planner"), "pk", None),
                set(existing_task.followers.values_list("pk", flat=True)) == {f.pk for f in validated_data["followers"]},
                existing_task.delivery_date == validated_data["delivery_date"],
                existing_task.includes_tax == validated_data["includes_tax"],
                existing_task.tax_rate == validated_data.get("tax_rate"),
                existing_task.order_tolerance_percent == validated_data["order_tolerance_percent"],
                existing_task.is_repeat_order == validated_data["is_repeat_order"],
                existing_task.delivery_method == validated_data["delivery_method"],
            ))
            if existing_items != submitted_items or not common_payload_matches:
                raise Conflict("本次请求标识已用于不同的生产任务内容，请刷新页面后重试。")
            return existing_task

    submitted_order_id = requested_items[0]["delivery_batch_line"].delivery_batch.sales_order_id
    sales_order = SalesOrder.objects.select_for_update(of=("self",)).select_related(
        "customer_account", "salesperson", "merchandiser"
    ).get(pk=submitted_order_id)
    delivery_batch = SalesOrderDeliveryBatch.objects.select_for_update().get(
        pk=submitted_batch_id,
        sales_order=sales_order,
    )

    source_ids = {item["delivery_batch_line"].pk for item in requested_items}
    locked_by_id = {
        item.pk: item
        for item in SalesOrderDeliveryBatchLine.objects.select_for_update(of=("self",)).select_related(
            "delivery_batch__sales_order__customer_account",
            "delivery_batch__sales_order__salesperson",
            "delivery_batch__sales_order__merchandiser",
            "sales_order_line__product__unit",
        ).filter(pk__in=source_ids).order_by("pk")
    }
    if set(locked_by_id) != source_ids:
        raise ValidationError({"lines": "部分销售订单交付批次行已不存在，请刷新后重试。"})
    if any(item.delivery_batch_id != submitted_batch_id for item in locked_by_id.values()):
        raise ValidationError({"lines": "所有来源行必须属于同一个销售订单交付批次。"})

    if request is not None and not production_sales_order_sources(request).filter(pk=sales_order.pk).exists():
        raise PermissionDenied("销售订单不存在或当前账号无权使用。")
    if sales_order.status not in {SalesOrderStatus.CONFIRMED, SalesOrderStatus.FULFILLING}:
        raise Conflict("只有已确认或履约中的销售订单可以创建生产订单。")
    if delivery_batch.status != DeliveryBatchStatus.ACTIVE:
        raise Conflict("已取消的交付批次不能创建生产订单。")

    normalized_items = []
    requested_by_source = {}
    for item in requested_items:
        source_line = locked_by_id[item["delivery_batch_line"].pk]
        requested_quantity = Decimal(item["quantity"])
        if requested_quantity != requested_quantity.to_integral_value():
            raise ValidationError({"quantity": "当前生产订单产品数量只支持整数，请调整销售订单交付数量。"})
        normalized = {**item, "delivery_batch_line": source_line, "quantity": requested_quantity}
        normalized_items.append(normalized)
        requested_by_source[source_line.pk] = requested_by_source.get(source_line.pk, Decimal("0")) + requested_quantity

    allocated_by_source = {
        row["sales_order_delivery_batch_line_id"]: Decimal(row["total"])
        for row in ProductionTaskProduct.objects.filter(
            sales_order_delivery_batch_line_id__in=source_ids,
        ).exclude(
            production_task__status=ProductionTaskStatus.CANCELLED,
        ).values("sales_order_delivery_batch_line_id").annotate(total=Sum("quantity"))
    }
    source_by_sales_line = {item.sales_order_line_id: item.pk for item in locked_by_id.values()}
    legacy_allocations = ProductionTaskProduct.objects.filter(
        sales_order_delivery_batch_line__isnull=True,
        production_task__sales_order_delivery_batch=delivery_batch,
        production_task__sales_order_line_id__in=source_by_sales_line,
    ).exclude(
        production_task__status=ProductionTaskStatus.CANCELLED,
    ).values("production_task__sales_order_line_id").annotate(total=Sum("quantity"))
    for row in legacy_allocations:
        source_id = source_by_sales_line[row["production_task__sales_order_line_id"]]
        allocated_by_source[source_id] = allocated_by_source.get(source_id, Decimal("0")) + Decimal(row["total"])

    for source_line in locked_by_id.values():
        allocated = allocated_by_source.get(source_line.pk, Decimal("0"))
        requested = requested_by_source.get(source_line.pk, Decimal("0"))
        maximum_quantity = Decimal(source_line.quantity)
        if allocated >= Decimal(source_line.quantity) and requested:
            raise ValidationError({"lines": "该销售订单明细已按原订单数量分配完成，不能再次安排。"})
        if allocated + requested > maximum_quantity:
            raise ValidationError({
                "lines": (
                    f"销售订单第 {source_line.sales_order_line.line_number} 行最多可安排 {maximum_quantity}，"
                    f"已安排 {allocated}，本次申请 {requested}。"
                )
            })

    currency = Currency.objects.filter(
        code="CNY",
        status=ReferenceStatus.ACTIVE,
        archived_at__isnull=True,
    ).first()
    if currency is None:
        raise ValidationError({"currency": "人民币 CNY 未在有效币种主数据中维护。"})
    if sales_order.total_amount_cny is None or not sales_order.exchange_rate_snapshot:
        raise ValidationError({"sales_order": "该销售订单尚未保存人民币金额，请先完成历史订单一次性补算。"})
    if any(item["delivery_batch_line"].sales_order_line.unit_price_cny is None for item in normalized_items):
        raise ValidationError({"lines": "来源产品尚未保存人民币单价，请先完成历史订单一次性补算。"})
    rate_snapshot = {
        **_production_cny_rate_snapshot(), "source_sales_order_id": str(sales_order.pk),
        "source_sales_exchange_rate": dict(sales_order.exchange_rate_snapshot),
    }
    _validate_followers(validated_data["followers"])
    _validate_task_tax(includes_tax=validated_data["includes_tax"], tax_rate=validated_data.get("tax_rate"))
    if validated_data["delivery_date"] < sales_order.order_date:
        raise ValidationError({"delivery_date": "交期日期不能早于下单日期。"})
    for item in normalized_items:
        sales_line = item["delivery_batch_line"].sales_order_line
        submitted_color = item.get("product_color")
        if "product_color" in item and getattr(submitted_color, "pk", None) != sales_line.product_color_id:
            raise ValidationError({"product_color_id": "来源颜色由销售订单固化，不能新增或替换。"})
        product = sales_line.product
        if product is not None and (product.status != ProductStatus.ACTIVE or product.archived_at is not None):
            raise ValidationError({"lines": f"产品 {product.product_number} 已停用或归档，不能创建生产任务。"})
    unit_codes = {
        item["delivery_batch_line"].sales_order_line.unit_code_snapshot for item in normalized_items
    }
    unit_by_code = {
        unit.unit_code: unit
        for unit in ProductionUnit.objects.filter(
            unit_code__in=unit_codes,
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        )
    }
    missing_unit_codes = unit_codes - set(unit_by_code)
    if missing_unit_codes:
        raise ValidationError({"lines": f"销售订单单位 {sorted(missing_unit_codes)[0]} 已停用、归档或不存在。"})
    source_sales_lines = {item["delivery_batch_line"].sales_order_line_id for item in normalized_items}
    task_sales_order_line = (
        normalized_items[0]["delivery_batch_line"].sales_order_line if len(source_sales_lines) == 1 else None
    )
    task_number = validated_data["task_number"]
    # 旧字段要求全局唯一；来源合同号仍从 sales_order 读取，不在多张生产订单之间复用该唯一字段。
    contract_number = next_business_number("SALES_CONTRACT", sales_order.order_date)
    task = _create_numbered_task(
        task_number=task_number,
        contract_number=contract_number,
        order_source="REPEAT" if validated_data["is_repeat_order"] else "NEW",
        order_number=sales_order.order_number,
        sales_order=sales_order,
        sales_order_delivery_batch=delivery_batch,
        sales_order_line=task_sales_order_line,
        customer_account=sales_order.customer_account,
        order_date=sales_order.order_date,
        delivery_date=validated_data["delivery_date"],
        salesperson=sales_order.salesperson,
        currency=currency,
        includes_tax=validated_data["includes_tax"],
        tax_rate=validated_data.get("tax_rate"),
        order_tolerance_percent=validated_data["order_tolerance_percent"],
        is_repeat_order=validated_data["is_repeat_order"],
        preproduction_sample_required=sales_order.preproduction_sample_required,
        delivery_method=validated_data["delivery_method"],
        special_requirements_html="",
        packaging_method_html="\n".join(dict.fromkeys(filter(None, [
            item.get("packaging_method") or item["delivery_batch_line"].sales_order_line.packaging_requirements
            for item in normalized_items
        ]))),
        status=ProductionTaskStatus.DRAFT,
        planned_start_date=validated_data.get("planned_start_date"),
        planned_end_date=validated_data.get("planned_end_date"),
        production_priority=validated_data.get("production_priority", ProductionPriority.NORMAL),
        production_batch_number=validated_data.get("production_batch_number", ""),
        planner=validated_data.get("planner"),
        source_request_key=request_key,
        created_by_employee=actor_employee,
    )
    for line_number, item in enumerate(normalized_items, start=1):
        source_line = item["delivery_batch_line"]
        sales_order_line = source_line.sales_order_line
        product = sales_order_line.product
        product_color = sales_order_line.product_color
        customer_product_name = str(
            getattr(sales_order_line, "customer_product_name_snapshot", "")
            or getattr(sales_order_line, "product_name_snapshot", "")
            or ""
        ).strip()
        customer_specification = str(
            getattr(sales_order_line, "customer_specification_snapshot", "")
            or getattr(sales_order_line, "specification_snapshot", "")
            or ""
        ).strip()
        customer_color = str(
            getattr(sales_order_line, "customer_color_snapshot", "")
            or getattr(sales_order_line, "color_snapshot", "")
            or ""
        ).strip()
        product_line = ProductionTaskProduct.objects.create(
            production_task=task,
            image_file=sales_order_line.product_image,
            line_number=line_number,
            product=product,
            sales_order_delivery_batch_line=source_line,
            product_category=getattr(sales_order_line, "product_category", None)
            or (product.category if product else None),
            product_number_snapshot=getattr(sales_order_line, "product_number_snapshot", "") if product else "",
            product_code_snapshot=getattr(sales_order_line, "product_code_snapshot", "") if product else "",
            item_number_snapshot=product.product_item.item_number if product else "",
            product_name_snapshot=sales_order_line.product_name_snapshot,
            specification_snapshot=sales_order_line.specification_snapshot,
            customer_product_name_snapshot=customer_product_name,
            customer_specification_snapshot=customer_specification,
            customer_color_snapshot=customer_color,
            material_snapshot=getattr(sales_order_line, "material_snapshot", ""),
            product_color=product_color,
            color_card_snapshot=product_color.color_card if product_color else "",
            color_name_snapshot=product_color.color_name if product_color else customer_color,
            color_code_snapshot=product_color.color_code if product_color else "",
            quantity=int(item["quantity"]),
            unit=unit_by_code[sales_order_line.unit_code_snapshot],
            currency=currency,
            unit_price=sales_order_line.unit_price_cny,
            total_amount=cny_line_amounts(sales_order_line.unit_price_cny, item["quantity"], Decimal("1"))[1],
            exchange_rate=Decimal("1"),
            exchange_rate_snapshot=rate_snapshot,
            special_requirements=item.get("special_requirements", sales_order_line.quality_requirements),
            packaging_method=item.get("packaging_method", sales_order_line.packaging_requirements),
        )
        if sales_order_line.product_image_id:
            ProductionTaskProductImage.objects.create(
                product_line=product_line, line_number=1, image_file=sales_order_line.product_image,
            )
    task.followers.set(validated_data["followers"])
    _sync_sales_delivery_date(task=task, actor_employee=actor_employee, request=request)
    total_requested_quantity = sum((item["quantity"] for item in normalized_items), Decimal("0"))
    ProductionDeliveryBatch.objects.create(
        production_task=task,
        line_number=1,
        quantity=total_requested_quantity,
        delivery_date=task.delivery_date,
        note=f"来源销售订单 {sales_order.order_number} / {delivery_batch.batch_number}",
    )
    run_batch_number = task.production_batch_number or task.task_number
    ProductionRunBatch.objects.create(
        production_task=task,
        batch_number=run_batch_number,
        planned_quantity=total_requested_quantity,
    )
    if sales_order.status == SalesOrderStatus.CONFIRMED:
        sales_order.status = SalesOrderStatus.FULFILLING
        sales_order.save(update_fields=["status", "updated_at"])
    write_audit_log(
        object_type="PRODUCTION_TASK",
        object_id=task.pk,
        context_type="SALES_ORDER",
        context_id=sales_order.pk,
        action="CREATED_FROM_SALES_ORDER",
        actor_employee=actor_employee,
        after_data=_snapshot(task),
        request=request,
    )
    return task


@transaction.atomic
def decide_production_order_by_pmc(*, task, validated_data, actor_employee, request=None):
    task = ProductionTask.objects.select_for_update().get(pk=task.pk)
    from apps.access_control.production_approval import check_production_approval
    check_production_approval(actor_employee, task)
    require_matching_etag(request, task)
    if task.status != ProductionTaskStatus.PENDING_VALIDATION:
        raise Conflict("只有待 PMC 确认的生产订单可以处理。")
    before = _snapshot(task)
    if validated_data["decision"] == "RETURN":
        task.status = ProductionTaskStatus.DRAFT
        task.status_reason = validated_data["reason"].strip()
        task.submitted_at = None
        action = "RETURNED_BY_PMC"
    else:
        followers = validated_data.get("followers", [])
        _validate_followers(followers)
        for field_name in (
            "planned_start_date",
            "planned_end_date",
            "production_priority",
            "production_batch_number",
            "planner",
            "delivery_date",
            "includes_tax",
            "tax_rate",
            "order_tolerance_percent",
            "is_repeat_order",
            "delivery_method",
        ):
            if field_name in validated_data:
                setattr(task, field_name, validated_data[field_name])
        if "is_repeat_order" in validated_data:
            task.order_source = "REPEAT" if task.is_repeat_order else "NEW"
        _validate_task_tax(includes_tax=task.includes_tax, tax_rate=task.tax_rate)
        if task.delivery_date < task.order_date:
            raise ValidationError({"delivery_date": "交期日期不能早于下单日期。"})
        if not task.planned_start_date or not task.planned_end_date:
            raise ValidationError({"planned_start_date": "PMC 确认前必须填写计划开始和计划完工日期。"})
        if task.planned_end_date < task.planned_start_date:
            raise ValidationError({"planned_end_date": "计划完工日期不能早于计划开始日期。"})
        task.status = ProductionTaskStatus.READY
        task.status_reason = ""
        action = "CONFIRMED"
    task.full_clean()
    task.save()
    if validated_data["decision"] == "CONFIRM":
        task.followers.set(followers)
        if "delivery_date" in validated_data:
            _sync_sales_delivery_date(task=task, actor_employee=actor_employee, request=request)
    write_audit_log(
        object_type="PRODUCTION_TASK",
        object_id=task.pk,
        **_audit_context(task),
        action=action,
        actor_employee=actor_employee,
        before_data=before,
        after_data=_snapshot(task),
        request=request,
    )
    if validated_data["decision"] == "CONFIRM":
        _register_task_confirmed(task, actor_employee)
    return task


@transaction.atomic
def start_production_order(*, task, waiver_reason, actor_employee, request=None):
    task = ProductionTask.objects.select_for_update().get(pk=task.pk)
    require_matching_etag(request, task)
    if task.status != ProductionTaskStatus.READY:
        raise Conflict("只有已接单生产订单可以计划排产。")
    from apps.production_scheduling.models import ProductionSchedule, ScheduleStatus
    if not ProductionSchedule.objects.filter(
        production_task=task,
        record_status=ScheduleStatus.ACTIVE,
    ).exists():
        raise Conflict("请先完成计划排产；保存有效排产计划后任务会自动进入生产中。")
    products = list(
        ProductionTaskProduct.objects.select_for_update()
        .filter(production_task=task)
        .order_by("pk")
    )
    if not products:
        raise ValidationError({"products": "生产订单没有产品明细。"})
    missing_bom = []
    for product in products:
        latest_bom = product.boms.filter(archived_at__isnull=True).order_by("-version_number", "-id").first()
        if latest_bom is None or latest_bom.status != "VERIFIED":
            color_label = product.color_name_snapshot or product.color_code_snapshot
            missing_bom.append(
                f"{product.product_name_snapshot}（{color_label}）" if color_label else product.product_name_snapshot
            )
    if missing_bom:
        raise ValidationError({"bom": f"当前订单 BOM 尚未确认：{'、'.join(missing_bom)}。"})

    normalized_waiver = str(waiver_reason or "").strip()
    if task.sales_order_id and task.sales_order.deposit_required:
        deposit_confirmed = task.sales_order.collaboration_events.filter(
            event_type=CollaborationEventType.DEPOSIT,
            status=CollaborationEventStatus.COMPLETED,
        ).exists()
        if not deposit_confirmed and not normalized_waiver:
            raise ValidationError({"start_waiver_reason": "订金尚未登记到账，必须填写允许先生产原因。"})
    before = _snapshot(task)
    now = timezone.now()
    task.status = ProductionTaskStatus.IN_PRODUCTION
    task.accepted_by_employee = actor_employee
    task.started_at = now
    if normalized_waiver:
        task.start_waiver_reason = normalized_waiver
        task.start_waiver_by_employee = actor_employee
        task.start_waiver_at = now
    task.save()
    task.run_batches.filter(status=ProductionRunBatchStatus.PLANNED).update(
        status=ProductionRunBatchStatus.IN_PROGRESS,
        started_at=now,
        updated_at=now,
    )
    write_audit_log(
        object_type="PRODUCTION_TASK",
        object_id=task.pk,
        **_audit_context(task),
        action="STARTED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=_snapshot(task),
        request=request,
    )
    return task


@transaction.atomic
def complete_production_order(*, task, validated_data, actor_employee, request=None):
    task = ProductionTask.objects.select_for_update().prefetch_related("products", "run_batches").get(pk=task.pk)
    require_matching_etag(request, task)
    if task.status != ProductionTaskStatus.IN_PRODUCTION:
        raise Conflict("只有生产中的订单可以完结。")
    submitted_batches = validated_data.get("run_batches")
    if submitted_batches is not None:
        submitted_numbers = [item["batch_number"] for item in submitted_batches]
        if len(submitted_numbers) != len(set(submitted_numbers)):
            raise ValidationError({"run_batches": "生产批次号不能重复。"})
        ProductionRunBatch.objects.filter(production_task=task).delete()
        for item in submitted_batches:
            values = dict(item)
            status_value = values["status"]
            ProductionRunBatch.objects.create(
                production_task=task,
                started_at=task.started_at if status_value != ProductionRunBatchStatus.PLANNED else None,
                completed_at=timezone.now() if status_value == ProductionRunBatchStatus.COMPLETED else None,
                **values,
            )
    run_batches = list(task.run_batches.exclude(status=ProductionRunBatchStatus.CANCELLED))
    if run_batches and any(item.status != ProductionRunBatchStatus.COMPLETED for item in run_batches):
        raise ValidationError({"run_batches": "全部有效生产批次完成后才能完结生产订单。"})
    planned_quantity = sum((Decimal(item.quantity) for item in task.products.all()), Decimal("0"))
    actual_quantity = Decimal(validated_data["actual_quantity"])
    good_quantity = Decimal(validated_data["actual_good_quantity"])
    if good_quantity > actual_quantity:
        raise ValidationError({"actual_good_quantity": "合格数量不能大于实际生产数量。"})
    if run_batches:
        batch_actual = sum((Decimal(item.actual_quantity) for item in run_batches), Decimal("0"))
        batch_good = sum((Decimal(item.good_quantity) for item in run_batches), Decimal("0"))
        if batch_actual != actual_quantity or batch_good != good_quantity:
            raise ValidationError({
                "run_batches": "生产批次的实际数量、合格数量合计必须分别等于生产订单汇总数量。"
            })
    reason = str(validated_data.get("reason", "")).strip()
    if good_quantity < planned_quantity and not reason:
        raise ValidationError({"reason": "合格数量不足或提前关闭时必须填写异常完结原因（责任提示：PMC）。"})
    before = _snapshot(task)
    task.actual_quantity = actual_quantity
    task.actual_good_quantity = good_quantity
    task.excess_quantity = max(actual_quantity - planned_quantity, Decimal("0"))
    task.status_reason = reason
    task.status = ProductionTaskStatus.COMPLETED
    task.completed_at = timezone.now()
    task.save()
    write_audit_log(
        object_type="PRODUCTION_TASK",
        object_id=task.pk,
        **_audit_context(task),
        action="COMPLETED_EXCEPTION" if good_quantity < planned_quantity else "COMPLETED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=_snapshot(task),
        request=request,
    )
    return task
