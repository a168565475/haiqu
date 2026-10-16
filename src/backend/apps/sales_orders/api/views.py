from apps.access_control import sales_policy
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db.models import Count, F, Min, Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.customers.models import CustomerEntityAddress, CustomerTransactionEntity
from apps.customers.selectors import accessible_customers
from apps.files.models import BusinessFile, FileScanStatus
from apps.files.uploads import save_scanned_document, save_scanned_image
from apps.organizations.models import Employee, EmployeeStatus
from apps.products.models import ProductInformation, ProductStatus
from apps.quotations.models import QuotationOutcomeStatus, QuotationTemplate, QuotationVersion
from apps.reference_data.models import Currency, ReferenceStatus

from ..models import (
    CollaborationEventStatus,
    CollaborationEventType,
    CustomerConfirmationMethod,
    DeliveryBatchStatus,
    SalesOrderEvidence,
    SalesOrderSource,
    SalesOrderStatus,
)
from ..selectors import accessible_sales_orders, sales_orders_with_context
from ..pricing import current_cny_rate
from ..presentation import specification_display
from ..services import (
    _quote_unit_price,
    add_collaboration_event,
    cancel_delivery_batch,
    change_confirmed_sales_order,
    complete_sales_order,
    confirm_sales_order,
    create_sales_order,
    remove_sales_order_line_product_image,
    set_sales_order_line_product_image,
    update_sales_order,
)
from .serializers import (
    CollaborationEventInputSerializer,
    CollaborationEventReadSerializer,
    ConfirmedSalesOrderChangeSerializer,
    DeliveryBatchCancelSerializer,
    SalesOrderDetailSerializer,
    SalesOrderListSerializer,
    SalesOrderCompleteSerializer,
    SalesOrderWriteSerializer,
    SalesOrderExchangeRatePreviewResponseSerializer,
)


FIXED_SELLER_TEMPLATE_CODE = "HAIQU_FIXED_BILINGUAL"


def _quotation_product_mapping(line):
    """优先使用报价行已确认的产品关联，旧数据才按快照候选匹配。"""
    linked_product = getattr(line, "product", None)
    if linked_product is not None:
        if linked_product.status == ProductStatus.ACTIVE and linked_product.archived_at is None:
            return linked_product, "MATCHED", 1
        return None, "UNMATCHED", 0
    description = (line.product_description_snapshot or "").strip()
    specification = (line.specification_snapshot or "").strip().casefold()
    if not description:
        return None, "UNMATCHED", 0

    active_products = ProductInformation.objects.filter(
        status=ProductStatus.ACTIVE,
        archived_at__isnull=True,
    ).select_related("unit", "category", "product_item")
    name_matches = list(active_products.filter(product_name__iexact=description))
    if name_matches:
        specification_matches = [
            product for product in name_matches
            if (product.specification or "").strip().casefold() == specification
        ]
        if len(specification_matches) == 1:
            return specification_matches[0], "MATCHED", len(name_matches)
        return None, "AMBIGUOUS", len(name_matches)
    return None, "UNMATCHED", 0


class SalesOrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    ordering = ["-order_date", "-created_at", "-id"]
    action_permission_map = {
        "list": "sales_orders.view_salesorder", "retrieve": "sales_orders.view_salesorder",
        "options": "sales_orders.view_salesorder", "quotation_options": "sales_orders.add_salesorder",
        "exchange_rate_preview": ("sales_orders.add_salesorder", "sales_orders.change_salesorder", "access_control.confirmedchange_salesorder"),
        "create": "sales_orders.add_salesorder", "partial_update": "sales_orders.change_salesorder",
        "confirm": "access_control.confirm_salesorder", "complete": "access_control.complete_salesorder",
        "confirmed_change": "access_control.confirmedchange_salesorder", "collaboration_events": "access_control.collaborate_salesorder",
        "cancel_batch": "access_control.cancelbatch_salesorder", "upload_evidence": "sales_orders.change_salesorder",
        "business_file": "sales_orders.view_salesorder", "product_image": "sales_orders.change_salesorder",
        "product_image.GET": "sales_orders.view_salesorder", "product_image.HEAD": "sales_orders.view_salesorder",
    }

    def get_permissions(self):
        from apps.access_control.sales_policy import enabled
        from apps.core.api.permissions import BusinessActionPermission
        permissions = super().get_permissions()
        return [*permissions, BusinessActionPermission()] if enabled() or self.action == "exchange_rate_preview" else permissions

    def scope_permission(self):
        from apps.access_control.sales_policy import action_permission
        return action_permission(self.request, self) or "sales_orders.view_salesorder"

    def get_queryset(self):
        queryset = accessible_sales_orders(self.request, self.scope_permission()).filter(archived_at__isnull=True)
        requested_status = self.request.query_params.get("status", "").strip().upper()
        if requested_status:
            if requested_status not in SalesOrderStatus.values:
                raise ValidationError({"status": "销售订单状态参数不正确。"})
            queryset = queryset.filter(status=requested_status)
        source_type = self.request.query_params.get("source_type", "").strip().upper()
        if source_type:
            if source_type not in SalesOrderSource.values:
                raise ValidationError({"source_type": "销售订单来源参数不正确。"})
            queryset = queryset.filter(source_type=source_type)
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(order_number__icontains=keyword)
                | Q(customer_po_number__icontains=keyword)
                | Q(contract_number__icontains=keyword)
                | Q(customer_account__account_code__icontains=keyword)
                | Q(customer_account__account_name__icontains=keyword)
                | Q(lines__product_name_snapshot__icontains=keyword)
                | Q(lines__product_number_snapshot__icontains=keyword)
            )
        customer_id = self.request.query_params.get("customer_id", "").strip()
        if customer_id:
            try:
                queryset = queryset.filter(customer_account_id=UUID(customer_id))
            except ValueError as exc:
                raise ValidationError({"customer_id": "客户编号格式不正确。"}) from exc
        queryset = queryset.annotate(
            line_count=Count("lines", distinct=True),
            delivery_batch_count=Count("delivery_batches", distinct=True),
            next_delivery_date=Min(
                "delivery_batches__planned_delivery_date",
                filter=Q(delivery_batches__status=DeliveryBatchStatus.ACTIVE),
            ),
        ).distinct()
        return sales_orders_with_context(queryset).order_by(*self.ordering)

    def get_serializer_class(self):
        if self.action == "list":
            return SalesOrderListSerializer
        if self.action in {"create", "partial_update"}:
            return SalesOrderWriteSerializer
        return SalesOrderDetailSerializer

    def _detail(self, order_id):
        queryset = accessible_sales_orders(self.request, self.scope_permission()).filter(pk=order_id, archived_at__isnull=True).annotate(
            line_count=Count("lines", distinct=True),
            delivery_batch_count=Count("delivery_batches", distinct=True),
            next_delivery_date=Min(
                "delivery_batches__planned_delivery_date",
                filter=Q(delivery_batches__status=DeliveryBatchStatus.ACTIVE),
            ),
        )
        return sales_orders_with_context(queryset).get()

    def _detail_response(self, order, response_status=status.HTTP_200_OK):
        current = self._detail(order.pk)
        response = Response({"data": SalesOrderDetailSerializer(current, context=self.get_serializer_context()).data}, status=response_status)
        response["ETag"] = etag_for_instance(current)
        return response

    def retrieve(self, request, *args, **kwargs):
        return self._detail_response(self.get_object())

    @extend_schema(
        parameters=[OpenApiParameter("currency_code", str, required=True)],
        responses={200: SalesOrderExchangeRatePreviewResponseSerializer},
        description="读取销售订单原币兑人民币的唯一有效配置汇率，保存时复核记录编号。",
    )
    @action(detail=False, methods=["get"], url_path="exchange-rate-preview")
    def exchange_rate_preview(self, request):
        record, snapshot = current_cny_rate(request.query_params.get("currency_code"))
        return Response({"data": {
            "exchange_rate_record_id": str(record.pk) if record else None,
            "exchange_rate": snapshot["rate"], "exchange_rate_snapshot": snapshot,
        }})

    def create(self, request, *args, **kwargs):
        serializer = SalesOrderWriteSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        order = create_sales_order(
            validated_data=serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        return self._detail_response(order, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        current = self.get_object()
        require_matching_etag(request, current)
        serializer = SalesOrderWriteSerializer(current, data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        order = update_sales_order(
            order=current,
            validated_data=serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        return self._detail_response(order)

    @action(detail=False, methods=["get"])
    def options(self, request):
        customer_queryset = accessible_customers(request, "sales_orders.view_salesorder" if sales_policy.enabled() else "view_customeraccount").filter(archived_at__isnull=True).order_by("account_name", "account_code")[:500]
        customers = list(customer_queryset)
        customer_ids = [item.pk for item in customers]
        entities = list(CustomerTransactionEntity.objects.filter(
            customer_account_id__in=customer_ids,
            archived_at__isnull=True,
        ).order_by("legal_name", "entity_code")[:1000])
        entity_ids = [item.pk for item in entities]
        addresses = CustomerEntityAddress.objects.filter(
            transaction_entity_id__in=entity_ids,
            archived_at__isnull=True,
        ).order_by("transaction_entity_id", "address_code", "id")[:2000]
        seller_template = QuotationTemplate.objects.filter(
            template_code=FIXED_SELLER_TEMPLATE_CODE,
            archived_at__isnull=True,
        ).first()
        employees = Employee.objects.filter(status=EmployeeStatus.ACTIVE, archived_at__isnull=True).order_by("employee_code")[:500]
        products = ProductInformation.objects.filter(status=ProductStatus.ACTIVE, archived_at__isnull=True).select_related("unit", "category", "product_item").order_by("product_number")[:1000]
        currencies = Currency.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True).order_by("sort_order", "code")
        accepted_versions = QuotationVersion.objects.filter(
            quotation__customer_account__in=accessible_customers(request, "view_quotationversion"),
            quotation__outcome_status=QuotationOutcomeStatus.WON,
            quotation__accepted_version_id=F("id"),
            quotation__customer_account_id__in=customer_ids,
        ).select_related("quotation", "quotation__customer_account").order_by("-locked_at", "-created_at")[:500]
        return Response({"data": {
            "source_types": [{"value": value, "label": label} for value, label in SalesOrderSource.choices],
            "statuses": [{"value": value, "label": label} for value, label in SalesOrderStatus.choices],
            "confirmation_methods": [{"value": value, "label": label} for value, label in CustomerConfirmationMethod.choices],
            "customers": [{"id": str(item.pk), "account_code": item.account_code, "account_name": item.account_name} for item in customers],
            "transaction_entities": [{"id": str(item.pk), "customer_account_id": str(item.customer_account_id), "entity_code": item.entity_code, "legal_name": item.legal_name} for item in entities],
            "buyer_addresses": [{
                "id": str(item.pk),
                "transaction_entity_id": str(item.transaction_entity_id),
                "address_code": item.address_code,
                "label": item.label,
                "country_code": item.country_code,
                "state_province": item.state_province,
                "city": item.city,
                "postal_code": item.postal_code,
                "address_line1": item.address_line1,
                "address_line2": item.address_line2,
                "recipient_name": item.recipient_name,
                "recipient_phone": item.recipient_phone,
                "is_verified": item.is_verified,
            } for item in addresses],
            "employees": [{"id": str(item.pk), "employee_code": item.employee_code, "display_name": item.display_name} for item in employees],
            "products": [{"id": str(item.pk), "product_number": item.product_number, "product_code": item.product_code, "item_number": item.product_item.item_number, "product_name": item.product_name, "specification": item.specification, "unit_id": str(item.unit_id), "unit_code": item.unit.unit_code, "unit_name": item.unit.unit_name, "category_id": str(item.category_id), "category_name": item.category.category_name} for item in products],
            "currencies": [{"id": str(item.pk), "code": item.code, "name": item.chinese_name, "symbol": item.symbol} for item in currencies],
            "accepted_quotation_versions": [{
                "id": str(item.pk),
                "quotation_id": str(item.quotation_id),
                "quotation_number": item.quotation.quotation_number,
                "version_number": item.version_number,
                "customer_account_id": str(item.quotation.customer_account_id),
                "customer_name": item.quotation.customer_account.account_name,
                "currency_code": item.currency_code,
            } for item in accepted_versions],
            "seller_template": ({
                "id": str(seller_template.pk),
                "template_code": seller_template.template_code,
                "template_name": seller_template.template_name,
                "template_version": seller_template.template_version,
                "template_config": seller_template.template_config,
            } if seller_template else None),
        }})

    @action(detail=False, methods=["get"], url_path="quotation-options")
    def quotation_options(self, request):
        raw_version_id = request.query_params.get("quotation_version_id", "").strip()
        try:
            version_id = UUID(raw_version_id)
        except ValueError as exc:
            raise ValidationError({"quotation_version_id": "报价版本编号格式不正确。"}) from exc
        version = get_object_or_404(
            QuotationVersion.objects.select_related(
                "quotation",
                "quotation__customer_account",
                "quotation__transaction_entity",
                "quotation__owner_employee",
            ).prefetch_related(
                "lines__basis_prices",
                "lines__product__unit",
                "lines__product__category",
                "lines__product__product_item",
                "lines__product_category",
                "lines__product_unit",
                "lines__product_color",
                "quotation__acceptance",
            ),
            pk=version_id,
        )
        quotation = version.quotation
        sales_policy.require_customer(request, "quotations.view_quotationversion", quotation.customer_account)
        sales_policy.require_customer(request, "sales_orders.add_salesorder", quotation.customer_account)
        if quotation.outcome_status != QuotationOutcomeStatus.WON or quotation.accepted_version_id != version.pk:
            raise ValidationError({"quotation_version_id": "只能读取客户已接受的报价版本。"})
        if not accessible_customers(request).filter(pk=quotation.customer_account_id).exists():
            raise Http404("报价不存在。")
        address_snapshot = dict(version.address_snapshot or {})
        snapshot_address_id = address_snapshot.get("id")
        valid_address_id = None
        if snapshot_address_id:
            try:
                address_id = UUID(str(snapshot_address_id))
            except ValueError:
                address_id = None
            if address_id and CustomerEntityAddress.objects.filter(
                pk=address_id,
                transaction_entity_id=quotation.transaction_entity_id,
                archived_at__isnull=True,
            ).exists():
                valid_address_id = str(address_id)
        converted_statuses = [SalesOrderStatus.CONFIRMED, SalesOrderStatus.FULFILLING, SalesOrderStatus.COMPLETED]
        reserved_statuses = [SalesOrderStatus.DRAFT, *converted_statuses]
        line_payload = []
        for line in version.lines.all():
            converted = line.sales_order_lines.filter(sales_order__status__in=converted_statuses).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
            reserved = line.sales_order_lines.filter(sales_order__status__in=reserved_statuses).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
            quote_price = _quote_unit_price(line, version)
            suggested, mapping_status, mapping_candidate_count = _quotation_product_mapping(line)
            line_payload.append({
                "id": str(line.pk),
                "line_number": line.line_number,
                "product_description": line.product_description_snapshot,
                "specification": line.specification_snapshot,
                "specification_display": specification_display(line),
                "color": line.color_snapshot or "",
                "product_id": str(line.product_id) if line.product_id else None,
                "product_category_id": str(line.product_category_id) if line.product_category_id else None,
                "product_unit_id": str(line.product_unit_id) if line.product_unit_id else None,
                "product_color_id": str(line.product_color_id) if line.product_color_id else None,
                "product_image_id": str(line.product_image_id) if line.product_image_id else None,
                "product_number": line.product_number_snapshot,
                "product_code": line.product_code_snapshot,
                "item_number": line.item_number_snapshot,
                "material": line.material_snapshot,
                "quantity": str(line.quantity),
                "converted_quantity": str(converted),
                "reserved_quantity": str(reserved),
                "remaining_quantity": str(max(Decimal(line.quantity) - Decimal(reserved), Decimal("0"))),
                "unit_code": line.unit_code,
                "quoted_unit_price": str(quote_price) if quote_price is not None else None,
                "suggested_product_id": str(suggested.pk) if suggested else None,
                "suggested_product": ({
                    "id": str(suggested.pk),
                    "product_number": suggested.product_number,
                    "product_code": suggested.product_code,
                    "product_name": suggested.product_name,
                    "specification": suggested.specification,
                    "unit_code": suggested.unit.unit_code,
                    "unit_name": suggested.unit.unit_name,
                    "category_id": str(suggested.category_id),
                    "category_name": suggested.category.category_name,
                } if suggested else None),
                "product_mapping_status": mapping_status,
                "product_mapping_candidate_count": mapping_candidate_count,
            })
        return Response({"data": {
            "quotation_id": str(quotation.pk),
            "quotation_number": quotation.quotation_number,
            "quotation_version_id": str(version.pk),
            "version_number": version.version_number,
            "customer_account_id": str(quotation.customer_account_id),
            "customer_name": quotation.customer_account.account_name,
            "transaction_entity_id": str(quotation.transaction_entity_id),
            "salesperson_id": str(quotation.owner_employee_id),
            "currency_code": version.currency_code,
            "buyer_snapshot": version.transaction_entity_snapshot,
            "buyer_address_id": valid_address_id,
            "buyer_address_snapshot": address_snapshot,
            "seller_snapshot": version.template_snapshot,
            "seller_template_id": str(version.quotation_template_id) if version.quotation_template_id else None,
            "terms_snapshot": version.terms_snapshot,
            "customer_requirement_snapshot": version.customer_requirement_snapshot,
            "lines": line_payload,
        }})

    @action(detail=True, methods=["post"])
    def confirm(self, request, *args, **kwargs):
        order = confirm_sales_order(
            order=self.get_object(),
            actor_employee=request.employee,
            request=request,
        )
        return self._detail_response(order)

    @action(detail=True, methods=["post"], url_path="confirmed-change")
    def confirmed_change(self, request, *args, **kwargs):
        serializer = ConfirmedSalesOrderChangeSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        order = change_confirmed_sales_order(
            order=self.get_object(),
            validated_data=serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        return self._detail_response(order)

    @action(detail=True, methods=["post"], url_path="collaboration-events")
    def collaboration_events(self, request, *args, **kwargs):
        serializer = CollaborationEventInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event, order = add_collaboration_event(
            order=self.get_object(),
            validated_data=serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        response = Response({"data": CollaborationEventReadSerializer(event).data}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(order)
        return response

    @action(detail=True, methods=["post"], url_path=r"delivery-batches/(?P<batch_id>[^/.]+)/cancel")
    def cancel_batch(self, request, pk=None, batch_id=None):
        serializer = DeliveryBatchCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = self.get_object()
        try:
            batch = order.delivery_batches.get(pk=UUID(str(batch_id)))
        except (ValueError, order.delivery_batches.model.DoesNotExist) as exc:
            raise ValidationError({"batch_id": "交付批次不存在或不属于当前销售订单。"}) from exc
        _batch, order = cancel_delivery_batch(
            order=order,
            delivery_batch=batch,
            reason=serializer.validated_data["reason"],
            evidence_file=serializer.validated_data["evidence_file"],
            actor_employee=request.employee,
            request=request,
        )
        return self._detail_response(order)

    @action(detail=True, methods=["post"])
    def complete(self, request, *args, **kwargs):
        serializer = SalesOrderCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = complete_sales_order(
            order=self.get_object(),
            exception_close=serializer.validated_data["exception_close"],
            reason=serializer.validated_data.get("reason", ""),
            actor_employee=request.employee,
            request=request,
        )
        return self._detail_response(order)

    @action(detail=True, methods=["post"], url_path="evidence")
    def upload_evidence(self, request, *args, **kwargs):
        order = self.get_object()
        require_matching_etag(request, order)
        if order.status in {SalesOrderStatus.COMPLETED, SalesOrderStatus.CANCELLED}:
            raise ValidationError({"file": "已完成或已取消订单不能继续补充变更凭证。"})
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            raise ValidationError({"file": "请选择要上传的客户确认凭证。"})
        business_file = save_scanned_document(
            uploaded_file,
            request.employee,
            storage_folder=f"sales-orders/{order.pk}/evidence",
            field_label="客户确认凭证",
        )
        SalesOrderEvidence.objects.create(
            sales_order=order,
            business_file=business_file,
            uploaded_by_employee=request.employee,
        )
        order.updated_at = timezone.now()
        order.save(update_fields=["updated_at"])
        return self._detail_response(order, status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post", "delete"], url_path=r"lines/(?P<line_id>[^/.]+)/product-image")
    def product_image(self, request, pk=None, line_id=None):
        order = self.get_object()
        line = get_object_or_404(order.lines.select_related("product_image"), pk=line_id)
        image = line.product_image
        if request.method in {"GET", "HEAD"}:
            if image is None:
                raise Http404("产品图片不存在。")
            if image.scan_status not in {FileScanStatus.CLEAN, FileScanStatus.SKIPPED}:
                return Response({"detail": "图片未通过安全扫描。"}, status=status.HTTP_409_CONFLICT)
            media_root = Path(settings.MEDIA_ROOT).resolve()
            storage_path = (media_root / image.storage_key).resolve()
            try:
                storage_path.relative_to(media_root)
            except ValueError as exc:
                raise Http404("图片路径无效。") from exc
            if not storage_path.is_file():
                raise Http404("图片文件不存在。")
            return FileResponse(storage_path.open("rb"), content_type=image.content_type)

        require_matching_etag(request, order)
        if order.status != SalesOrderStatus.DRAFT:
            raise Conflict("销售订单确认后不能直接修改产品图片，请发起订单变更。")
        if request.method == "DELETE":
            updated = remove_sales_order_line_product_image(
                order=order, line=line, actor_employee=request.employee, request=request,
            )
            return self._detail_response(updated)
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            raise ValidationError({"file": "请选择产品图片。"})
        business_file = save_scanned_image(
            uploaded_file,
            request.employee,
            storage_folder=f"sales-orders/{order.pk}/product-images",
            field_label="产品图片",
        )
        updated = set_sales_order_line_product_image(
            order=order, line=line, business_file=business_file,
            actor_employee=request.employee, request=request,
        )
        return self._detail_response(updated, status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path=r"business-files/(?P<file_id>[^/.]+)")
    def business_file(self, request, pk=None, file_id=None):
        order = self.get_object()
        business_file = get_object_or_404(
            BusinessFile.objects.filter(
                Q(sales_order_evidence_links__sales_order=order)
                | Q(sales_order_collaboration_events__sales_order=order),
                pk=file_id,
                archived_at__isnull=True,
            ).distinct()
        )
        if business_file.scan_status not in {FileScanStatus.CLEAN, FileScanStatus.SKIPPED}:
            raise ValidationError({"file": "文件尚未通过安全扫描，暂不能查看。"})
        media_root = Path(settings.MEDIA_ROOT).resolve()
        storage_path = (media_root / business_file.storage_key).resolve()
        try:
            storage_path.relative_to(media_root)
        except ValueError as exc:
            raise Http404("文件路径无效。") from exc
        if not storage_path.is_file():
            raise Http404("文件不存在。")
        return FileResponse(
            storage_path.open("rb"),
            content_type=business_file.content_type,
            as_attachment=request.query_params.get("download") == "1",
            filename=business_file.original_name,
        )
