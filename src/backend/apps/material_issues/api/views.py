from uuid import UUID, NAMESPACE_URL, uuid5
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from apps.boms.material_attributes import bom_attribute_fields, merge_bom_attribute_fields, override_bom_attribute
from apps.inventory.models import MaterialStockBalance, MaterialStockQuality, SemiFinishedStockBalance
from apps.inventory.stock_services import available_stock
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from apps.production_tasks.selectors import accessible_production_tasks, production_task_source_image_ids
from apps.workshop_config.models import RecordStatus, Workshop
from apps.workshop_config.selectors import active_employees

from ..material_flow import pipe_requirement_rows
from ..models import MaterialIssueStatus, OrderMaterialRequirement
from ..requirements import build_requirement_specs
from ..scopes import (
    WORKSHOP_MATERIAL_SECTION_CODES,
    filter_blockers_for_scope,
    material_section_codes_for_issue,
    material_section_codes_for_workshop,
)
from ..selectors import accessible_material_issues, material_issues_with_context, search_material_issues
from ..services import (
    confirm_issue,
    create_issue,
    is_pipe_semi_balance,
    preview_issue,
    pending_issue_quantities,
    return_issue,
    submit_issue,
    update_issue,
)
from .serializers import (
    MaterialIssueConfirmSerializer,
    MaterialIssueReadSerializer,
    MaterialIssueReturnSerializer,
    MaterialIssueWriteSerializer,
    material_issue_product_data,
)


def _uuid(value, field):
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: "参数不是有效 UUID。"}) from exc


class MaterialIssueViewSet(viewsets.GenericViewSet):
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    serializer_class = MaterialIssueReadSerializer
    action_permission_map = {
        "list": "material_issues.view_materialissue",
        "retrieve": "material_issues.view_materialissue",
        "options": "material_issues.view_materialissue",
        "eligible_products": "material_issues.view_materialissue",
        "product_image": "material_issues.view_materialissue",
        "requirements": "material_issues.view_materialissue",
        "create": "material_issues.add_materialissue",
        "partial_update": "material_issues.change_materialissue",
        "submit": "material_issues.submit_materialissue",
        "return_issue": "material_issues.review_materialissue",
        "preview_issue": "material_issues.review_materialissue",
        "confirm_issue": "material_issues.review_materialissue",
    }

    def get_queryset(self):
        return material_issues_with_context(accessible_material_issues(self.request))

    def list(self, request):
        queryset = self.get_queryset()
        keyword = request.query_params.get("search", "").strip()
        if len(keyword) > 200:
            raise ValidationError({"search": "搜索内容不能超过 200 个字符。"})
        queryset = search_material_issues(queryset, keyword)
        status_value = request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in MaterialIssueStatus.values:
                raise ValidationError({"status": "领料状态参数不正确。"})
            queryset = queryset.filter(status=status_value)
        workshop_id = _uuid(request.query_params.get("workshop_id"), "workshop_id")
        if workshop_id:
            queryset = queryset.filter(workshop_id=workshop_id)
        recipient_id = _uuid(request.query_params.get("recipient_id"), "recipient_id")
        if recipient_id:
            queryset = queryset.filter(recipient_workshop_employee_id=recipient_id)
        production_task_id = _uuid(request.query_params.get("production_task_id"), "production_task_id")
        if production_task_id:
            queryset = queryset.filter(production_task_id=production_task_id)
        product_line_id = _uuid(request.query_params.get("product_line_id"), "product_line_id")
        if product_line_id:
            queryset = queryset.filter(product_line_id=product_line_id)
        ordering = request.query_params.get("ordering", "-created_at")
        allowed_ordering = {"created_at", "-created_at", "issue_at", "-issue_at", "issue_number", "-issue_number"}
        if ordering not in allowed_ordering:
            raise ValidationError({"ordering": "排序参数不正确。"})
        page = self.paginate_queryset(queryset.order_by(ordering, "-id"))
        return self.get_paginated_response(
            MaterialIssueReadSerializer(page, many=True, context={"include_detail": False}).data
        )

    def retrieve(self, request, pk=None):
        issue = get_object_or_404(self.get_queryset(), pk=pk)
        response = Response({"data": MaterialIssueReadSerializer(issue).data})
        response["ETag"] = etag_for_instance(issue)
        return response

    def create(self, request):
        serializer = MaterialIssueWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task_id = serializer.validated_data.get("production_task_id")
        if task_id and not accessible_production_tasks(request).filter(pk=task_id).exists():
            raise ValidationError({"production_task_id": "生产订单不存在或不可访问。"})
        issue = create_issue(validated_data=dict(serializer.validated_data), actor_employee=request.employee, request=request)
        issue = self.get_queryset().get(pk=issue.pk)
        response = Response({"data": MaterialIssueReadSerializer(issue).data}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(issue)
        return response

    def partial_update(self, request, pk=None):
        current = get_object_or_404(accessible_material_issues(request), pk=pk)
        serializer = MaterialIssueWriteSerializer(instance=current, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        task_id = serializer.validated_data.get("production_task_id", current.production_task_id)
        if task_id and not accessible_production_tasks(request).filter(pk=task_id).exists():
            raise ValidationError({"production_task_id": "生产订单不存在或不可访问。"})
        issue = update_issue(
            issue_id=current.pk,
            validated_data=dict(serializer.validated_data),
            actor_employee=request.employee,
            request=request,
        )
        issue = self.get_queryset().get(pk=issue.pk)
        response = Response({"data": MaterialIssueReadSerializer(issue).data})
        response["ETag"] = etag_for_instance(issue)
        return response

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        current = get_object_or_404(accessible_material_issues(request), pk=pk)
        issue = submit_issue(issue_id=current.pk, actor_employee=request.employee, request=request)
        issue = self.get_queryset().get(pk=issue.pk)
        response = Response({"data": MaterialIssueReadSerializer(issue).data})
        response["ETag"] = etag_for_instance(issue)
        return response

    @action(detail=True, methods=["post"], url_path="return")
    def return_issue(self, request, pk=None):
        current = get_object_or_404(accessible_material_issues(request), pk=pk)
        serializer = MaterialIssueReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issue = return_issue(
            issue_id=current.pk,
            reason=serializer.validated_data["reason"],
            actor_employee=request.employee,
            request=request,
        )
        issue = self.get_queryset().get(pk=issue.pk)
        response = Response({"data": MaterialIssueReadSerializer(issue).data})
        response["ETag"] = etag_for_instance(issue)
        return response

    @action(detail=True, methods=["post"], url_path="preview-issue")
    def preview_issue(self, request, pk=None):
        issue = get_object_or_404(self.get_queryset(), pk=pk)
        return Response({"data": preview_issue(issue)})

    @action(detail=True, methods=["post"], url_path="confirm-issue")
    def confirm_issue(self, request, pk=None):
        current = get_object_or_404(accessible_material_issues(request), pk=pk)
        serializer = MaterialIssueConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issue = confirm_issue(
            issue_id=current.pk,
            request_id=serializer.validated_data["request_id"],
            actor_employee=request.employee,
            request=request,
        )
        issue = self.get_queryset().get(pk=issue.pk)
        response = Response({"data": MaterialIssueReadSerializer(issue).data})
        response["ETag"] = etag_for_instance(issue)
        return response

    @action(detail=False, methods=["get"])
    def options(self, request):
        from apps.access_control.resource_scopes import current_permission, resource_ids, has_legacy_permission
        from apps.production_tasks.selectors import legacy_accessible_production_tasks
        code = current_permission(request, 'material_issues.view_materialissue')
        ids = resource_ids(request, code, 'WORKSHOP', include_legacy=False)
        if request.user.has_perm('material_issues.view_all_materialissue') or (
            has_legacy_permission(request, code) and legacy_accessible_production_tasks(request).exists()
        ):
            ids = None
        task_query = accessible_production_tasks(request).filter(
            archived_at__isnull=True,
            status__in=[ProductionTaskStatus.READY, ProductionTaskStatus.IN_PRODUCTION],
        ).select_related("customer_account").order_by("-created_at", "-id")
        tasks = list(task_query[:100])
        include_task_id = _uuid(request.query_params.get("include_task_id"), "include_task_id")
        if include_task_id and all(item.pk != include_task_id for item in tasks):
            included_task = task_query.filter(pk=include_task_id).first()
            if included_task:
                tasks.insert(0, included_task)
        workshops = list(
            Workshop.objects.filter(
                status=RecordStatus.ACTIVE,
                name__in=WORKSHOP_MATERIAL_SECTION_CODES,
            ).order_by("name", "id").values("id", "name")
        )
        employees = active_employees(Employee.objects.filter(
            workshop__status=RecordStatus.ACTIVE,
            workshop__name__in=WORKSHOP_MATERIAL_SECTION_CODES,
        )).select_related("workshop").order_by("workshop__name", "display_name", "id")
        if ids is not None:
            workshops = [row for row in workshops if str(row['id']) in ids]
            employees = employees.filter(workshop_id__in=ids)
        return Response(
            {
                "data": {
                    "production_tasks": [
                        {
                            "id": str(item.pk),
                            "task_number": item.task_number,
                            "order_number": item.order_number,
                            "customer_name": item.customer_account.account_name if item.customer_account_id else "",
                            "status": item.status,
                        }
                        for item in tasks
                    ],
                    "workshops": [{"id": str(item["id"]), "name": item["name"]} for item in workshops],
                    "recipients": [
                        {"id": str(item.pk), "name": item.display_name, "workshop_id": str(item.workshop_id)}
                        for item in employees
                    ],
                }
            }
        )

    @action(detail=False, methods=["get"], url_path="eligible-products")
    def eligible_products(self, request):
        task_id = _uuid(request.query_params.get("production_task_id"), "production_task_id")
        if not task_id:
            raise ValidationError({"production_task_id": "必须选择生产订单。"})
        task = get_object_or_404(accessible_production_tasks(request), pk=task_id)
        products = task.products.select_related(
            "image_file", "unit", "production_task",
            "sales_order_delivery_batch_line__sales_order_line__product_image",
        ).prefetch_related("images__image_file").order_by("line_number", "id")
        from apps.access_control.workshop_scopes import filter_task_products
        products = filter_task_products(products, request, 'material_issues.view_materialissue')
        return Response(
            {
                "data": [
                    {
                        **material_issue_product_data(item),
                        "line_number": item.line_number,
                        "quantity": item.quantity,
                    }
                    for item in products
                ]
            }
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("task_id", OpenApiTypes.UUID, OpenApiParameter.PATH),
            OpenApiParameter("file_id", OpenApiTypes.UUID, OpenApiParameter.PATH),
        ],
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"product-images/(?P<task_id>[^/.]+)/(?P<file_id>[^/.]+)",
    )
    def product_image(self, request, task_id=None, file_id=None):
        task_id = _uuid(task_id, "production_task_id")
        products = ProductionTaskProduct.objects.filter(production_task_id=task_id)
        from apps.access_control.workshop_scopes import filter_task_products
        if not accessible_production_tasks(request).filter(pk=task_id).exists():
            # 可查看领料单不一定可查看整张生产任务，只放行该领料单明确关联的产品图片。
            products = products.filter(material_issues__in=accessible_material_issues(request).filter(
                production_task_id=task_id,
            ))
        else:
            products = filter_task_products(products, request, 'material_issues.view_materialissue')
        task = get_object_or_404(
            ProductionTask.objects.filter(products__in=products).distinct(), pk=task_id,
        )
        image = get_object_or_404(BusinessFile.objects.filter(
            Q(production_task_product_images__product_line__in=products)
            | Q(production_task_products__in=products)
            | Q(pk__in=production_task_source_image_ids(task, product_ids=products.values("id"))),
            pk=_uuid(file_id, "file_id"), archived_at__isnull=True,
        ).distinct())
        if image.scan_status not in USABLE_FILE_SCAN_STATUSES:
            raise ValidationError({"file": "图片尚未通过安全扫描，暂不能查看。"})
        media_root = Path(settings.MEDIA_ROOT).resolve()
        storage_path = (media_root / image.storage_key).resolve()
        try:
            storage_path.relative_to(media_root)
        except ValueError as exc:
            raise Http404("文件路径无效。") from exc
        if not storage_path.is_file():
            raise Http404("文件不存在。")
        return FileResponse(storage_path.open("rb"), content_type=image.content_type, filename=image.original_name)

    @action(detail=False, methods=["get"])
    def requirements(self, request):
        task_id = _uuid(request.query_params.get("production_task_id"), "production_task_id")
        product_line_id = _uuid(request.query_params.get("product_line_id"), "product_line_id")
        workshop_id = _uuid(request.query_params.get("workshop_id"), "workshop_id")
        if not task_id or not product_line_id or not workshop_id:
            raise ValidationError({"detail": "必须同时选择生产订单、产品和领料车间。"})
        from apps.access_control.resource_scopes import current_permission
        from apps.access_control.workshop_scopes import require_task_workshop, filter_task_products
        code = current_permission(request, 'material_issues.view_materialissue')
        require_task_workshop(request, code, task_id, workshop_id)
        task = get_object_or_404(accessible_production_tasks(request), pk=task_id)
        if not task.products.filter(pk=product_line_id).exists():
            raise ValidationError({"product_line_id": "所选产品不属于该生产订单。"})
        get_object_or_404(filter_task_products(task.products.all(), request, code), pk=product_line_id)
        workshop = get_object_or_404(Workshop.objects.filter(status=RecordStatus.ACTIVE), pk=workshop_id)
        from apps.inventory.public_stock_mode import public_issues_enabled
        public_stock = public_issues_enabled()
        exclude_issue_id = None
        issue_id = _uuid(request.query_params.get("issue_id"), "issue_id")
        if issue_id:
            current_issue = get_object_or_404(accessible_material_issues(request), pk=issue_id)
            if (
                current_issue.production_task_id != task.pk
                or current_issue.product_line_id != product_line_id
                or current_issue.workshop_id != workshop.pk
            ):
                raise ValidationError({"issue_id": "领料单与所选订单、产品或车间不一致。"})
            public_stock = current_issue.stock_mode == "PUBLIC_V2"
            exclude_issue_id = current_issue.pk
            allowed_section_codes = material_section_codes_for_issue(current_issue)
        else:
            plan_category = request.query_params.get("plan_category")
            allowed_section_codes = material_section_codes_for_workshop(workshop.name, plan_category)
        if allowed_section_codes is None:
            raise ValidationError({"plan_category": "作业计划类型与领料车间不一致或暂未开放生产领料。"})
        _, specs, blockers, revision_hash = build_requirement_specs(task.pk)
        blockers = filter_blockers_for_scope(
            blockers,
            product_line_id=product_line_id,
            section_codes=allowed_section_codes,
        )
        blockers = [b for b in blockers if b["code"] != "PIPE_SERVICE_REQUIRED"]
        existing = {
            item.pk: item
            for item in OrderMaterialRequirement.objects.filter(id__in=[item["id"] for item in specs])
        }
        stock_zones = {}
        stock_material_ids = {item["raw_material"].pk for item in specs}
        for balance in MaterialStockBalance.objects.filter(
            measurement_kind="OTHER",
            raw_material_id__in=stock_material_ids,
            quality=MaterialStockQuality.AVAILABLE,
            quantity__gt=0,
            zone__status="ACTIVE",
            zone__warehouse__status="ACTIVE",
        ).select_related("zone").order_by("zone__zone_name", "id"):
            key = (balance.raw_material_id, balance.unit_id)
            zones = stock_zones.setdefault(key, [])
            if balance.zone.zone_name not in zones:
                zones.append(balance.zone.zone_name)
        pending_raw, _ = pending_issue_quantities(requirement_ids=[item["id"] for item in specs], exclude_issue_id=exclude_issue_id)
        public_pending = {}
        if public_stock:
            from ..public_issue_services import public_ordinary_pending_quantities
            public_pending = public_ordinary_pending_quantities(stock_material_ids, exclude_issue_id=exclude_issue_id)
        rows = []
        for spec in specs:
            if spec["section_code"] not in allowed_section_codes:
                continue
            if not any(item["product_line"].pk == product_line_id for item in spec["contributions"]):
                continue
            current = existing.get(spec["id"])
            internal = current.internal_issued_quantity if current else 0
            outsourcing = current.outsourcing_issued_quantity if current else 0
            pending = pending_raw.get(spec["id"], 0)
            remaining = spec["required_quantity"] - internal - outsourcing - pending
            stock = available_stock(spec["raw_material"].pk, spec["unit"].pk)
            stock_pending = public_pending.get((spec["raw_material"].pk, spec["unit"].pk), 0)
            material = spec["raw_material"]
            part_names = list(dict.fromkeys(
                (item["bom_line"].part_name or item["bom_line"].material or "").strip()
                for item in spec["contributions"]
                if item["product_line"].pk == product_line_id
                and (item["bom_line"].part_name or item["bom_line"].material or "").strip()
            ))
            bom_attributes = merge_bom_attribute_fields(
                bom_attribute_fields(item["bom_line"])
                for item in spec["contributions"]
                if item["product_line"].pk == product_line_id
            )
            rows.append(
                {
                    "requirement_id": str(spec["id"]),
                    "stock_item_id": str(material.pk),
                    "line_type": spec["line_type"],
                    "section_code": spec["section_code"],
                    "material_number": material.material_number,
                    "material_name": material.material_name,
                    "part_names": part_names,
                    "bom_attributes": bom_attributes,
                    "specification": material.specification,
                    "color": material.color.color_name if material.color_id else material.color_snapshot,
                    "unit": spec["unit"].unit_name,
                    "required_quantity": str(spec["required_quantity"]),
                    "internal_issued_quantity": str(internal),
                    "outsourcing_issued_quantity": str(outsourcing),
                    "pending_issue_quantity": str(pending),
                    "order_remaining": str(max(remaining, 0)),
                    "available_stock": str(stock),
                    "max_issue_quantity": str(max(min(remaining, stock - stock_pending), 0)),
                    "warehouse_zones": stock_zones.get((material.pk, spec["unit"].pk), []),
                    "bom_version": max(item["bom"].version_number for item in spec["contributions"]),
                    "validation_errors": [],
                }
            )
            if public_stock:
                rows[-1]["public_pending_quantity"] = str(stock_pending)
        if "PROFILE" in allowed_section_codes:
            pipe_rows, pipe_blockers = pipe_requirement_rows(task.pk, product_line_id,
                exclude_issue_id=exclude_issue_id, public_stock=public_stock)
            rows.extend(pipe_rows); blockers.extend(pipe_blockers)
        if public_stock:
            if "SEMI" in allowed_section_codes:
                from ..public_semi_requirements import public_semi_requirement_rows
                semi_rows, semi_blockers = public_semi_requirement_rows(
                    task.pk, product_line_id, exclude_issue_id=exclude_issue_id)
                rows.extend(semi_rows)
                blockers.extend(semi_blockers)
            for row in rows:
                row["stock_mode"] = "PUBLIC_V2"
            return Response({"data": {"stock_mode": "PUBLIC_V2", "source_revision_hash": revision_hash,
                                       "items": rows, "blockers": blockers}})
        semi_balances = SemiFinishedStockBalance.objects.none()
        if "SEMI" in allowed_section_codes:
            semi_balances = SemiFinishedStockBalance.objects.select_related(
                "bom_line__section__bom", "completed_craft", "unit", "zone__warehouse"
            ).filter(
                production_task=task,
                product_line_id=product_line_id,
                quality=MaterialStockQuality.AVAILABLE,
                zone__status="ACTIVE", zone__warehouse__status="ACTIVE", zone__warehouse__warehouse_type="SEMI_FINISHED",
                quantity__gt=0,
            ).order_by("completed_craft__name", "bom_line__line_number", "zone__zone_name", "id")
        semi_balances = list(semi_balances)
        _, pending_semi = pending_issue_quantities(semi_balance_ids=[item.pk for item in semi_balances])
        # 半成品领料按“部位 + 已完成工艺 + 颜色 + 单位 + 库区”聚合，前端不暴露回货批次；
        # 实际领料时再由后端按可用余额自动拆分到各个余额行。
        grouped = {}
        for balance in semi_balances:
            key = (balance.bom_line_id, balance.completed_craft_id, balance.color_snapshot,
                   balance.unit_id, balance.zone_id)
            item = grouped.setdefault(key, {"balances": [], "quantity": 0, "pending": 0, "balance": balance})
            item["balances"].append(balance)
            item["quantity"] += balance.quantity
            item["pending"] += pending_semi.get(balance.pk, 0)
        for item in grouped.values():
            balance = item["balance"]
            component = balance.bom_line
            component_name = component.part_name or component.material or component.raw_material
            remaining = max(item["quantity"] - item["pending"], 0)
            group_id = uuid5(NAMESPACE_URL, "semi:{}:{}:{}:{}:{}".format(
                balance.bom_line_id, balance.completed_craft_id, balance.color_snapshot,
                balance.unit_id, balance.zone_id,
            ))
            conversion = {
                "kind": "SEMI_PIPE_PIECES" if is_pipe_semi_balance(balance) else "SEMI",
                "part_name": component_name,
            }
            if conversion["kind"] == "SEMI_PIPE_PIECES":
                conversion.update({"integer_required": True, "whole_bar_required": False,
                    "raw_deducted_bar_count": "0", "raw_deducted_meters": "0.00"})
            rows.append({
                "requirement_id": str(group_id), "stock_item_id": str(group_id),
                "line_type": "SEMI", "section_code": "SEMI",
                "material_number": f"SEMI-{str(component.pk)[:8].upper()}",
                "material_name": component_name, "specification": component.specification,
                "color": balance.color_snapshot, "unit": balance.unit.unit_name,
                "required_quantity": str(item["quantity"]), "internal_issued_quantity": "0",
                "outsourcing_issued_quantity": "0", "pending_issue_quantity": str(item["pending"]),
                "order_remaining": str(remaining), "available_stock": str(item["quantity"]),
                "max_issue_quantity": str(remaining), "bom_version": component.section.bom.version_number,
                "completed_craft": balance.completed_craft.name,
                "warehouse_zone": f"{balance.zone.warehouse.warehouse_name} / {balance.zone.zone_name}",
                "quality": balance.quality, "validation_errors": [],
                "batch_selection": False,
                "conversion_snapshot": conversion,
                "bom_attributes": override_bom_attribute(
                    bom_attribute_fields(component),
                    "spray_color",
                    balance.color_snapshot if getattr(balance.completed_craft, "outsourcing_code", "") == "POWDER_COATING" else None,
                    "喷塑颜色",
                ),
                "semi_balance_allocations": [
                    {"balance_id": str(row.pk), "available_stock": str(row.quantity),
                     "pending_issue_quantity": str(pending_semi.get(row.pk, 0)),
                     "max_issue_quantity": str(max(row.quantity - pending_semi.get(row.pk, 0), 0))}
                    for row in item["balances"]
                ],
            })
        return Response({"data": {"source_revision_hash": revision_hash, "items": rows, "blockers": blockers}})
