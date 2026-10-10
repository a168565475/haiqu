from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import BooleanField, Case, CharField, F, Q, Value, When
from django.db.models.functions import NullIf
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.core.audit import write_audit_log
from apps.products.models import (
    ProductInformation,
    ProductScale,
    ProductStatus,
    RawMaterialBoxShape,
    RawMaterialInformation,
)
from apps.reference_data.models import (
    ProductCategory,
    ProductColor,
    ProductItem,
    ProductItemType,
    ProductionUnit,
    ReferenceStatus,
)

from .serializers import (
    ProductInformationSerializer,
    ProductOptionsResponseSerializer,
    RawMaterialInformationSerializer,
    RawMaterialOptionsResponseSerializer,
)


class ProductOptionsPermission(BasePermission):
    message = "当前账号没有产品信息查看权限。"

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.has_perm("products.view_productinformation")
            )
        )


class ProductOptionsView(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, ProductOptionsPermission]

    @extend_schema(responses=ProductOptionsResponseSerializer)
    def list(self, request):
        categories = ProductCategory.objects.filter(
            item_type=ProductItemType.FINISHED,
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).order_by("sort_order", "category_name", "id")
        units = ProductionUnit.objects.filter(
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).order_by("sort_order", "unit_code", "id")
        items = ProductItem.objects.filter(
            category__item_type=ProductItemType.FINISHED,
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
            category__archived_at__isnull=True,
        ).select_related("category").order_by("sort_order", "item_number", "id")
        return Response(
            {
                "data": {
                    "categories": [
                        {"id": str(item.pk), "category_name": item.category_name}
                        for item in categories
                    ],
                    "units": [
                        {"id": str(item.pk), "unit_code": item.unit_code, "unit_name": item.unit_name}
                        for item in units
                    ],
                    "items": [
                        {
                            "id": str(item.pk),
                            "item_number": item.item_number,
                            "category_id": str(item.category_id),
                            "category_name": item.category.category_name,
                        }
                        for item in items
                    ],
                }
            }
        )


class ProductInformationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ProductInformationSerializer
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "list": "products.view_productinformation",
        "retrieve": "products.view_productinformation",
        "create": "products.add_productinformation",
        "update": "products.change_productinformation",
        "partial_update": "products.change_productinformation",
    }

    def actor_employee(self):
        return getattr(self.request, "employee", None)

    def get_queryset(self):
        queryset = ProductInformation.objects.filter(archived_at__isnull=True).select_related(
            "category",
            "unit",
            "product_item",
            "product_item__category",
        )
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(product_number__icontains=keyword)
                | Q(product_code__icontains=keyword)
                | Q(product_name__icontains=keyword)
                | Q(specification__icontains=keyword)
                | Q(product_item__item_number__icontains=keyword)
                | Q(warehouse_number__icontains=keyword)
                | Q(warehouse_name__icontains=keyword)
            )

        requested_status = self.request.query_params.get("status", "").strip().upper()
        if requested_status:
            if requested_status not in ProductStatus.values:
                raise ValidationError({"status": "产品状态参数不正确。"})
            queryset = queryset.filter(status=requested_status)

        requested_scale = self.request.query_params.get("scale", "").strip().upper()
        if requested_scale:
            if requested_scale not in ProductScale.values:
                raise ValidationError({"scale": "产品规模参数不正确。"})
            queryset = queryset.filter(scale=requested_scale)

        category_id = self.request.query_params.get("category_id", "").strip()
        if category_id:
            try:
                category_id = UUID(category_id)
            except ValueError as exc:
                raise ValidationError({"category_id": "产品类别编号格式不正确。"}) from exc
            queryset = queryset.filter(category_id=category_id)

        ordering = self.request.query_params.get("ordering", "product_number").strip()
        allowed_ordering = {
            "product_number",
            "-product_number",
            "product_code",
            "-product_code",
            "product_name",
            "-product_name",
            "updated_at",
            "-updated_at",
        }
        if ordering not in allowed_ordering:
            raise ValidationError({"ordering": "排序参数不正确。"})
        return queryset.order_by(ordering, "id")

    def response_with_etag(self, instance, response_status=status.HTTP_200_OK):
        response = Response(
            {"data": self.get_serializer(instance).data},
            status=response_status,
        )
        response["ETag"] = etag_for_instance(instance)
        return response

    def retrieve(self, request, *args, **kwargs):
        return self.response_with_etag(self.get_object())

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                instance = serializer.save()
                write_audit_log(
                    object_type="PRODUCT_INFORMATION",
                    object_id=instance.pk,
                    action="CREATED",
                    actor_employee=self.actor_employee(),
                    after_data=self.get_serializer(instance).data,
                    request=request,
                )
        except IntegrityError as exc:
            raise ValidationError({"detail": "品号或产品编码已存在。"}) from exc
        return self.response_with_etag(instance, status.HTTP_201_CREATED)

    def _update(self, request, *, partial):
        current = self.get_object()
        require_matching_etag(request, current)
        try:
            with transaction.atomic():
                instance = ProductInformation.objects.select_for_update().get(pk=current.pk)
                require_matching_etag(request, instance)
                before_data = self.get_serializer(instance).data
                serializer = self.get_serializer(instance, data=request.data, partial=partial)
                serializer.is_valid(raise_exception=True)
                instance = serializer.save()
                write_audit_log(
                    object_type="PRODUCT_INFORMATION",
                    object_id=instance.pk,
                    action="UPDATED",
                    actor_employee=self.actor_employee(),
                    before_data=before_data,
                    after_data=self.get_serializer(instance).data,
                    request=request,
                )
        except IntegrityError as exc:
            raise ValidationError({"detail": "品号或产品编码已存在。"}) from exc
        return self.response_with_etag(instance)

    def update(self, request, *args, **kwargs):
        return self._update(request, partial=kwargs.pop("partial", False))

    def partial_update(self, request, *args, **kwargs):
        return self._update(request, partial=True)


class RawMaterialOptionsPermission(BasePermission):
    message = "当前账号没有原料信息查看权限。"

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.has_perm("products.view_rawmaterialinformation")
            )
        )


class RawMaterialOptionsView(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, RawMaterialOptionsPermission]

    @extend_schema(responses=RawMaterialOptionsResponseSerializer)
    def list(self, request):
        categories = ProductCategory.objects.filter(
            item_type__in=[ProductItemType.MATERIAL, ProductItemType.SEMI_FINISHED],
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).order_by("item_type", "sort_order", "category_name", "id")
        units = ProductionUnit.objects.filter(
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).order_by("sort_order", "unit_code", "id")
        colors = ProductColor.objects.filter(
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).order_by("sort_order", "color_card", "color_code", "color_name", "id")
        warehouses = (
            RawMaterialInformation.objects.exclude(warehouse_number="")
            .exclude(warehouse_name="")
            .values("warehouse_number", "warehouse_name")
            .distinct()
            .order_by("warehouse_number", "warehouse_name")
        )
        return Response(
            {
                "data": {
                    "item_types": [
                        {"value": ProductItemType.MATERIAL, "label": "材料"},
                        {"value": ProductItemType.SEMI_FINISHED, "label": "半成品"},
                    ],
                    "categories": [
                        {
                            "id": str(item.pk),
                            "item_type": item.item_type,
                            "category_name": item.category_name,
                        }
                        for item in categories
                    ],
                    "units": [
                        {
                            "id": str(item.pk),
                            "unit_code": item.unit_code,
                            "unit_name": item.unit_name,
                        }
                        for item in units
                    ],
                    "colors": [
                        {
                            "id": str(item.pk),
                            "color_card": item.color_card,
                            "color_code": item.color_code,
                            "color_name": item.color_name,
                            "label": " / ".join(
                                value
                                for value in (item.color_card, item.color_code, item.color_name)
                                if value
                            ),
                        }
                        for item in colors
                    ],
                    "warehouses": list(warehouses),
                    "box_shapes": [
                        {"value": value, "label": label}
                        for value, label in RawMaterialBoxShape.choices
                    ],
                }
            }
        )


class RawMaterialInformationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = RawMaterialInformationSerializer
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "list": "products.view_rawmaterialinformation",
        "retrieve": "products.view_rawmaterialinformation",
        "create": "products.add_rawmaterialinformation",
        "update": "products.change_rawmaterialinformation",
        "partial_update": "products.change_rawmaterialinformation",
    }

    def actor_employee(self):
        return getattr(self.request, "employee", None)

    @staticmethod
    def _directional(expression, descending):
        if descending:
            return expression.desc(nulls_last=True)
        return expression.asc(nulls_last=True)

    def get_queryset(self):
        queryset = RawMaterialInformation.objects.filter(archived_at__isnull=True).select_related(
            "category",
            "unit",
            "color",
        )
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(material_number__icontains=keyword)
                | Q(material_name__icontains=keyword)
                | Q(specification__icontains=keyword)
                | Q(color_snapshot__icontains=keyword)
                | Q(material__icontains=keyword)
                | Q(warehouse_number__icontains=keyword)
                | Q(warehouse_name__icontains=keyword)
            )

        item_type = self.request.query_params.get("item_type", "").strip().upper()
        if item_type:
            if item_type not in {ProductItemType.MATERIAL, ProductItemType.SEMI_FINISHED}:
                raise ValidationError({"item_type": "原料类型参数不正确。"})
            queryset = queryset.filter(item_type=item_type)

        category_id = self.request.query_params.get("category_id", "").strip()
        if category_id:
            try:
                category_id = UUID(category_id)
            except ValueError as exc:
                raise ValidationError({"category_id": "原料类别编号格式不正确。"}) from exc
            queryset = queryset.filter(category_id=category_id)

        warehouse_number = self.request.query_params.get("warehouse_number", "").strip()
        if warehouse_number:
            queryset = queryset.filter(warehouse_number=warehouse_number)

        ordering = self.request.query_params.get("ordering", "material_number").strip()
        descending = ordering.startswith("-")
        ordering_key = ordering[1:] if descending else ordering
        allowed_ordering = {
            "material_number",
            "item_type",
            "category_name",
            "material_name",
            "specification",
            "unit_name",
            "color_name",
            "warehouse",
            "is_packaging_auxiliary",
            "box_shape",
            "updated_at",
        }
        if ordering_key not in allowed_ordering:
            raise ValidationError({"ordering": "排序参数不正确。"})

        queryset = queryset.alias(
            ordering_color_name=NullIf(
                Case(
                    When(color__isnull=False, then=F("color__color_name")),
                    default=F("color_snapshot"),
                    output_field=CharField(),
                ),
                Value(""),
            ),
            ordering_is_packaging_auxiliary=Case(
                When(
                    item_type=ProductItemType.MATERIAL,
                    category__category_name="包材",
                    then=F("is_packaging_auxiliary"),
                ),
                default=Value(None),
                output_field=BooleanField(),
            ),
            ordering_box_shape=Case(
                When(
                    item_type=ProductItemType.MATERIAL,
                    category__category_name="包材",
                    box_shape=RawMaterialBoxShape.HALF_COVER,
                    then=Value(RawMaterialBoxShape.HALF_COVER.label),
                ),
                When(
                    item_type=ProductItemType.MATERIAL,
                    category__category_name="包材",
                    box_shape=RawMaterialBoxShape.FULL_COVER,
                    then=Value(RawMaterialBoxShape.FULL_COVER.label),
                ),
                When(
                    item_type=ProductItemType.MATERIAL,
                    category__category_name="包材",
                    box_shape=RawMaterialBoxShape.LID_AND_BASE,
                    then=Value(RawMaterialBoxShape.LID_AND_BASE.label),
                ),
                When(
                    item_type=ProductItemType.MATERIAL,
                    category__category_name="包材",
                    box_shape=RawMaterialBoxShape.DISPLAY_BOX,
                    then=Value(RawMaterialBoxShape.DISPLAY_BOX.label),
                ),
                When(
                    item_type=ProductItemType.MATERIAL,
                    category__category_name="包材",
                    box_shape=RawMaterialBoxShape.OTHER,
                    then=Value(RawMaterialBoxShape.OTHER.label),
                ),
                default=Value(None),
                output_field=CharField(),
            ),
        )
        text_ordering = {
            "material_number": "material_number",
            "item_type": "item_type",
            "category_name": "category__category_name",
            "material_name": "material_name",
            "specification": "specification",
            "unit_name": "unit__unit_name",
            "color_name": "ordering_color_name",
            "updated_at": "updated_at",
        }
        if ordering_key == "warehouse":
            ordering_expressions = [
                self._directional(NullIf(F("warehouse_number"), Value("")), descending),
                self._directional(NullIf(F("warehouse_name"), Value("")), descending),
            ]
        elif ordering_key == "is_packaging_auxiliary":
            ordering_expressions = [
                self._directional(F("ordering_is_packaging_auxiliary"), descending)
            ]
        elif ordering_key == "box_shape":
            ordering_expressions = [self._directional(F("ordering_box_shape"), descending)]
        else:
            field_name = text_ordering[ordering_key]
            expression = F(field_name)
            if ordering_key not in {"item_type", "updated_at"}:
                expression = NullIf(expression, Value(""))
            ordering_expressions = [self._directional(expression, descending)]

        return queryset.order_by(
            *ordering_expressions,
            F("source_row_number").asc(nulls_last=True),
            "id",
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="ordering",
                type=str,
                location=OpenApiParameter.QUERY,
                description=(
                    "排序字段。支持 material_number、item_type、category_name、"
                    "material_name、specification、unit_name、color_name、warehouse、"
                    "is_packaging_auxiliary、box_shape、updated_at；前缀 - 表示降序。"
                ),
            )
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def response_with_etag(self, instance, response_status=status.HTTP_200_OK):
        response = Response(
            {"data": self.get_serializer(instance).data},
            status=response_status,
        )
        response["ETag"] = etag_for_instance(instance)
        return response

    def retrieve(self, request, *args, **kwargs):
        return self.response_with_etag(self.get_object())

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                instance = serializer.save()
                write_audit_log(
                    object_type="RAW_MATERIAL_INFORMATION",
                    object_id=instance.pk,
                    action="CREATED",
                    actor_employee=self.actor_employee(),
                    after_data=self.get_serializer(instance).data,
                    request=request,
                )
        except IntegrityError as exc:
            raise ValidationError({"detail": "品号已存在。"}) from exc
        return self.response_with_etag(instance, status.HTTP_201_CREATED)

    def _update(self, request, *, partial):
        current = self.get_object()
        require_matching_etag(request, current)
        try:
            with transaction.atomic():
                instance = RawMaterialInformation.objects.select_for_update().get(pk=current.pk)
                require_matching_etag(request, instance)
                before_data = self.get_serializer(instance).data
                serializer = self.get_serializer(instance, data=request.data, partial=partial)
                serializer.is_valid(raise_exception=True)
                instance = serializer.save()
                write_audit_log(
                    object_type="RAW_MATERIAL_INFORMATION",
                    object_id=instance.pk,
                    action="UPDATED",
                    actor_employee=self.actor_employee(),
                    before_data=before_data,
                    after_data=self.get_serializer(instance).data,
                    request=request,
                )
        except IntegrityError as exc:
            raise ValidationError({"detail": "品号已存在。"}) from exc
        return self.response_with_etag(instance)

    def update(self, request, *args, **kwargs):
        return self._update(request, partial=kwargs.pop("partial", False))

    def partial_update(self, request, *args, **kwargs):
        return self._update(request, partial=True)
