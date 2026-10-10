from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.api.permissions import HasActiveEmployee
from apps.core.audit import write_audit_log
from apps.files.uploads import save_scanned_image
from apps.reference_data.published_reads import published_config_state, published_catalog
from apps.reference_data.configuration_cache import ConfigurationListCacheMixin
from apps.reference_data.models import (
    AccessoryColor,
    AccessoryMaterial,
    AccessoryProductName,
    AccessorySpecification,
    ConfigRelease,
    ConfigReleaseStatus,
    Country,
    Courier,
    Currency,
    DictionaryType,
    ExchangeRate,
    FabricMaterial,
    FabricSpecification,
    FabricWidth,
    Incoterm,
    NumberRule,
    PaymentMethod,
    Port,
    ProductCategory,
    ProductColor,
    ProductItem,
    ProductionUnit,
    ReferenceDictionary,
    ReferenceStatus,
    SystemParameterDefinition,
    SystemParameterValue,
    TubeCoatingColor,
    TubeDiameter,
    TubeMaterial,
    TubeProductName,
    TubeShape,
    TubeThickness,
    TransportMethod,
    Unit,
)
from apps.reference_data.services import (
    dictionary_reference_breakdown,
    dictionary_reference_count,
    latest_published_release,
    pending_config_change_count,
    publish_config,
    published_dictionary_options,
)

from .serializers import (
    AccessoryColorSerializer,
    AccessoryMaterialSerializer,
    AccessoryProductNameSerializer,
    AccessorySpecificationSerializer,
    ArchiveActionSerializer,
    ConfigReleaseSerializer,
    CountrySerializer,
    CourierSerializer,
    CurrencySerializer,
    DictionaryTypeSerializer,
    ExchangeRateCorrectionSerializer,
    ExchangeRateSerializer,
    FabricMaterialSerializer,
    FabricSpecificationSerializer,
    FabricWidthSerializer,
    IncotermSerializer,
    MasterDataSummarySerializer,
    NumberRuleSerializer,
    PaymentMethodSerializer,
    PortSerializer,
    ProductCategorySerializer,
    ProductColorSerializer,
    ProductItemSerializer,
    ProductionDataSummarySerializer,
    ProductionUnitSerializer,
    PublishedOptionsResponseSerializer,
    PublishedConfigVersionResponseSerializer,
    PublishedOptionsBatchQuerySerializer,
    PublishedOptionsBatchResponseSerializer,
    PublishConfigSerializer,
    ReferenceDictionarySerializer,
    ReferenceDataSummarySerializer,
    StatusActionSerializer,
    SystemParameterDraftSerializer,
    SystemParameterSerializer,
    TubeCoatingColorSerializer,
    TubeDiameterSerializer,
    TubeMaterialSerializer,
    TubeProductNameSerializer,
    TubeShapeSerializer,
    TubeThicknessSerializer,
    TransportMethodSerializer,
    UnitSerializer,
)


class ReferenceDataManagementPermission(BasePermission):
    message = "当前账号没有对应的基础配置管理权限。"

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        required_permission = getattr(view, "required_permission", None)
        if required_permission:
            return request.user.has_perm(required_permission)
        model = getattr(view, "permission_model", None)
        if model is None and getattr(view, "queryset", None) is not None:
            model = view.queryset.model
        if model is None:
            return False
        action = getattr(view, "action", None)
        # 路由不支持的方法没有 action；放行到 DRF 自身返回 405，不能误报为权限不足。
        if action is None:
            return True
        if model is ConfigRelease and action == "create":
            return request.user.has_perm("reference_data.publish_configrelease")
        from apps.access_control import module_policy
        if module_policy.enabled() and action in {'activate', 'deactivate', 'archive'}:
            code = f'access_control.{action}_reference_{model._meta.model_name}'
            if module_policy.has_permission(request, code):
                return True
            from apps.access_control.sales_policy import legacy_permission
            return legacy_permission(request, f'reference_data.change_{model._meta.model_name}')
        permission_action = {
            "list": "view",
            "retrieve": "view",
            "create": "add",
            "update": "change",
            "partial_update": "change",
            "activate": "change",
            "deactivate": "change",
            "archive": "change",
            "correct": "add",
        }.get(action)
        if action == "image":
            permission_action = "view" if request.method in ("GET", "HEAD", "OPTIONS") else "change"
        if permission_action is None:
            return False
        return request.user.has_perm(
            f"{model._meta.app_label}.{permission_action}_{model._meta.model_name}"
        )


class StandardMasterDataPermission(ReferenceDataManagementPermission):
    """标准代码允许在职员工读取，管理写操作仍使用模型权限。"""

    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return bool(request.user and request.user.is_authenticated)
        return super().has_permission(request, view)


class MasterDataSummaryPermission(BasePermission):
    message = "当前账号没有基础资料查看权限。"
    view_permissions = (
        "reference_data.view_country",
        "reference_data.view_currency",
        "reference_data.view_exchangerate",
        "reference_data.view_unit",
        "reference_data.view_incoterm",
        "reference_data.view_paymentmethod",
        "reference_data.view_transportmethod",
        "reference_data.view_port",
        "reference_data.view_courier",
    )

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_superuser or any(
            request.user.has_perm(permission) for permission in self.view_permissions
        )


class ProductionDataSummaryPermission(BasePermission):
    message = "当前账号没有生产资料查看权限。"
    view_permissions = (
        "reference_data.view_productcategory",
        "reference_data.view_productionunit",
        "reference_data.view_productcolor",
        "reference_data.view_productitem",
        "reference_data.view_fabricmaterial",
        "reference_data.view_fabricspecification",
        "reference_data.view_fabricwidth",
        "reference_data.view_tubeproductname",
        "reference_data.view_tubethickness",
        "reference_data.view_tubediameter",
        "reference_data.view_tubematerial",
        "reference_data.view_tubeshape",
        "reference_data.view_tubecoatingcolor",
        "reference_data.view_accessoryproductname",
        "reference_data.view_accessoryspecification",
        "reference_data.view_accessorycolor",
        "reference_data.view_accessorymaterial",
    )

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_superuser or any(
            request.user.has_perm(permission) for permission in self.view_permissions
        )


class ManagedReferenceViewSet(
    ConfigurationListCacheMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, HasActiveEmployee, ReferenceDataManagementPermission]
    search_fields = ("code", "chinese_name", "english_name")
    object_type = "REFERENCE_DATA"

    def actor_employee(self):
        return getattr(self.request, "employee", None)

    def locked_instance(self, pk):
        # 列表查询可能带统计分组或可空关联；PostgreSQL 不允许直接对这类查询加 FOR UPDATE。
        # 并发写入只需锁定当前模型的主表记录，响应时再按需读取关联数据。
        return self.queryset.model._default_manager.select_for_update().get(pk=pk)

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("include_archived") != "true":
            queryset = queryset.filter(archived_at__isnull=True)
        requested_status = self.request.query_params.get("status")
        if requested_status in ReferenceStatus.values:
            queryset = queryset.filter(status=requested_status)
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            filters = Q()
            for field_name in self.search_fields:
                filters |= Q(**{f"{field_name}__icontains": keyword})
            queryset = queryset.filter(filters)
        source = self.request.query_params.get("source", "").strip()
        if source and any(field.name == "source_version" for field in queryset.model._meta.fields):
            queryset = queryset.filter(source_version__icontains=source)
        return queryset

    def response_with_etag(self, data, instance, response_status=status.HTTP_200_OK):
        response = Response({"data": data}, status=response_status)
        response["ETag"] = etag_for_instance(instance)
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return self.response_with_etag(self.get_serializer(instance).data, instance)

    def perform_create(self, serializer):
        serializer.save()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            instance = serializer.save()
            write_audit_log(
                object_type=self.object_type,
                object_id=instance.pk,
                action="CREATED",
                actor_employee=self.actor_employee(),
                after_data=self.get_serializer(instance).data,
                request=request,
            )
        return self.response_with_etag(
            self.get_serializer(instance).data,
            instance,
            status.HTTP_201_CREATED,
        )

    def _update(self, request, *, partial):
        current = self.get_object()
        require_matching_etag(request, current)
        with transaction.atomic():
            instance = self.locked_instance(current.pk)
            require_matching_etag(request, instance)
            before_data = self.get_serializer(instance).data
            from apps.access_control import module_policy, sales_policy
            if module_policy.enabled() and 'status' in request.data and request.data['status'] != instance.status:
                old = f'reference_data.change_{instance._meta.model_name}'
                if not sales_policy.legacy_permission(request, old):
                    from rest_framework.exceptions import PermissionDenied
                    raise PermissionDenied('启用或停用请使用对应操作入口。')
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
            write_audit_log(
                object_type=self.object_type,
                object_id=instance.pk,
                action="UPDATED",
                actor_employee=self.actor_employee(),
                before_data=before_data,
                after_data=self.get_serializer(instance).data,
                request=request,
            )
        return self.response_with_etag(self.get_serializer(instance).data, instance)

    def update(self, request, *args, **kwargs):
        return self._update(request, partial=kwargs.pop("partial", False))

    def partial_update(self, request, *args, **kwargs):
        return self._update(request, partial=True)

    def _set_status(self, request, target_status):
        current = self.get_object()
        require_matching_etag(request, current)
        serializer = StatusActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reference_count = 0
        reference_breakdown = []
        if isinstance(current, ReferenceDictionary):
            reference_count = dictionary_reference_count(current)
            reference_breakdown = dictionary_reference_breakdown(current)
            if (
                target_status == ReferenceStatus.INACTIVE
                and reference_count
                and not serializer.validated_data["confirm_references"]
            ):
                raise Conflict(
                    {
                        "detail": "该字典项已被业务数据引用，请确认影响后再停用。",
                        "reference_count": reference_count,
                        "references": reference_breakdown,
                    }
                )
        with transaction.atomic():
            instance = self.locked_instance(current.pk)
            require_matching_etag(request, instance)
            before_data = self.get_serializer(instance).data
            instance.status = target_status
            instance.save(update_fields=["status", "updated_at"])
            write_audit_log(
                object_type=self.object_type,
                object_id=instance.pk,
                action="ACTIVATED" if target_status == ReferenceStatus.ACTIVE else "DEACTIVATED",
                actor_employee=self.actor_employee(),
                before_data=before_data,
                after_data={
                    **self.get_serializer(instance).data,
                    "reason": serializer.validated_data["reason"],
                    "reference_count": reference_count,
                },
                request=request,
            )
        return self.response_with_etag(self.get_serializer(instance).data, instance)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        return self._set_status(request, ReferenceStatus.INACTIVE)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._set_status(request, ReferenceStatus.ACTIVE)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        current = self.get_object()
        require_matching_etag(request, current)
        serializer = ArchiveActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if isinstance(current, ReferenceDictionary):
            reference_count = dictionary_reference_count(current)
            if reference_count:
                raise Conflict(
                    {
                        "detail": "该字典项已被业务数据引用，不能归档；可在确认影响后停用。",
                        "reference_count": reference_count,
                        "references": dictionary_reference_breakdown(current),
                    }
                )
        with transaction.atomic():
            instance = self.locked_instance(current.pk)
            require_matching_etag(request, instance)
            before_data = self.get_serializer(instance).data
            instance.archived_at = timezone.now()
            instance.archived_by_employee = self.actor_employee()
            instance.archive_reason = serializer.validated_data["reason"]
            instance.status = ReferenceStatus.INACTIVE
            instance.save(
                update_fields=[
                    "archived_at",
                    "archived_by_employee",
                    "archive_reason",
                    "status",
                    "updated_at",
                ]
            )
            write_audit_log(
                object_type=self.object_type,
                object_id=instance.pk,
                action="ARCHIVED",
                actor_employee=self.actor_employee(),
                before_data=before_data,
                after_data=self.get_serializer(instance).data,
                request=request,
            )
        return self.response_with_etag(self.get_serializer(instance).data, instance)


class NumberRuleViewSet(ConfigurationListCacheMixin, viewsets.ReadOnlyModelViewSet):
    queryset = NumberRule.objects.filter(archived_at__isnull=True).order_by("sort_order", "number_type")
    serializer_class = NumberRuleSerializer
    permission_classes = [IsAuthenticated, HasActiveEmployee, ReferenceDataManagementPermission]
    permission_model = NumberRule


class DictionaryTypeViewSet(ManagedReferenceViewSet):
    queryset = DictionaryType.objects.all()
    serializer_class = DictionaryTypeSerializer
    object_type = "DICTIONARY_TYPE"

    def get_queryset(self):
        return super().get_queryset().annotate(item_count=Count("items")).prefetch_related("items")


class ReferenceDictionaryViewSet(ManagedReferenceViewSet):
    queryset = ReferenceDictionary.objects.select_related("dictionary_type")
    serializer_class = ReferenceDictionarySerializer
    search_fields = ("item_code", "display_name", "english_name")
    object_type = "REFERENCE_DICTIONARY"

    def get_queryset(self):
        queryset = super().get_queryset()
        type_code = self.request.query_params.get("type_code", "").strip().upper()
        return queryset.filter(category_code=type_code) if type_code else queryset


class CountryViewSet(ManagedReferenceViewSet):
    queryset = Country.objects.all()
    serializer_class = CountrySerializer
    object_type = "COUNTRY"
    permission_classes = [IsAuthenticated, HasActiveEmployee, StandardMasterDataPermission]


class CurrencyViewSet(ManagedReferenceViewSet):
    queryset = Currency.objects.all()
    serializer_class = CurrencySerializer
    object_type = "CURRENCY"
    permission_classes = [IsAuthenticated, HasActiveEmployee, StandardMasterDataPermission]


class UnitViewSet(ManagedReferenceViewSet):
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    object_type = "UNIT"
    permission_classes = [IsAuthenticated, HasActiveEmployee, StandardMasterDataPermission]


class ProductCategoryViewSet(ManagedReferenceViewSet):
    queryset = ProductCategory.objects.annotate(
        product_item_count=Count(
            "product_items",
            filter=Q(product_items__archived_at__isnull=True),
            distinct=True,
        ),
        raw_material_count=Count(
            "raw_materials",
            filter=Q(raw_materials__archived_at__isnull=True),
            distinct=True,
        ),
    ).order_by("sort_order", "category_name", "id")
    serializer_class = ProductCategorySerializer
    search_fields = ("category_name", "item_type")
    object_type = "PRODUCT_CATEGORY"

    def get_queryset(self):
        queryset = super().get_queryset()
        item_type = self.request.query_params.get("item_type", "").strip().upper()
        return queryset.filter(item_type=item_type) if item_type else queryset

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        instance = self.get_object()
        if (
            instance.product_items.filter(archived_at__isnull=True).exists()
            or instance.raw_materials.filter(archived_at__isnull=True).exists()
        ):
            raise Conflict("该产品类别已被货号或原料信息引用，不能归档；可改为停用。")
        return super().archive(request, pk=pk)


class ProductionUnitViewSet(ManagedReferenceViewSet):
    queryset = ProductionUnit.objects.all()
    serializer_class = ProductionUnitSerializer
    search_fields = ("unit_code", "unit_name")
    object_type = "PRODUCTION_UNIT"


class ProductColorViewSet(ManagedReferenceViewSet):
    queryset = ProductColor.objects.select_related("image_file")
    serializer_class = ProductColorSerializer
    search_fields = ("color_card", "color_code", "color_name")
    object_type = "PRODUCT_COLOR"

    def get_queryset(self):
        queryset = super().get_queryset()
        has_image = self.request.query_params.get("has_image", "").strip().lower()
        if has_image == "true":
            queryset = queryset.filter(image_file__isnull=False)
        elif has_image == "false":
            queryset = queryset.filter(image_file__isnull=True)
        return queryset

    @staticmethod
    def _archive_replaced_file(business_file, actor_employee):
        if business_file is None or business_file.product_colors.filter(archived_at__isnull=True).exists():
            return
        business_file.archived_at = timezone.now()
        business_file.archived_by_employee = actor_employee
        business_file.archive_reason = "颜色图片已替换或清除。"
        business_file.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])

    @action(detail=True, methods=["get", "post", "delete"])
    def image(self, request, pk=None):
        current = self.get_object()
        if request.method == "GET":
            if not current.image_file_id:
                raise Http404("该颜色尚未上传图片。")
            media_root = Path(settings.MEDIA_ROOT).resolve()
            file_path = (media_root / current.image_file.storage_key).resolve()
            try:
                file_path.relative_to(media_root)
            except ValueError as exc:
                raise Http404("图片路径无效。") from exc
            if not file_path.is_file():
                raise Http404("图片文件不存在。")
            response = FileResponse(file_path.open("rb"), content_type=current.image_file.content_type)
            response["Content-Disposition"] = f'inline; filename="{current.image_file.original_name}"'
            return response

        require_matching_etag(request, current)
        uploaded_file = request.FILES.get("image") if request.method == "POST" else None
        if request.method == "POST" and uploaded_file is None:
            raise ValidationError({"image": "请选择需要上传的颜色图片。"})

        with transaction.atomic():
            instance = self.locked_instance(current.pk)
            require_matching_etag(request, instance)
            before_data = self.get_serializer(instance).data
            old_file = instance.image_file
            if request.method == "POST":
                instance.image_file = save_scanned_image(
                    uploaded_file,
                    self.actor_employee(),
                    storage_folder="production-colors",
                    field_label="颜色图片",
                )
                audit_action = "IMAGE_UPDATED"
            else:
                instance.image_file = None
                audit_action = "IMAGE_CLEARED"
            instance.save(update_fields=["image_file", "updated_at"])
            self._archive_replaced_file(old_file, self.actor_employee())
            after_data = self.get_serializer(instance).data
            write_audit_log(
                object_type=self.object_type,
                object_id=instance.pk,
                action=audit_action,
                actor_employee=self.actor_employee(),
                before_data=before_data,
                after_data=after_data,
                request=request,
            )
        return self.response_with_etag(after_data, instance)


class ProductItemViewSet(ManagedReferenceViewSet):
    queryset = ProductItem.objects.select_related("category")
    serializer_class = ProductItemSerializer
    search_fields = ("item_number", "legacy_data_id", "category__category_name")
    object_type = "PRODUCT_ITEM"

    def get_queryset(self):
        queryset = super().get_queryset()
        category_id = self.request.query_params.get("category_id", "").strip()
        if not category_id:
            return queryset
        try:
            normalized_category_id = UUID(category_id)
        except ValueError as exc:
            raise ValidationError({"category_id": "产品类别编号格式不正确。"}) from exc
        return queryset.filter(category_id=normalized_category_id)


class FabricMaterialViewSet(ManagedReferenceViewSet):
    queryset = FabricMaterial.objects.select_related("inventory_raw_material", "inventory_raw_material__unit")
    serializer_class = FabricMaterialSerializer
    search_fields = (
        "material_name", "inventory_raw_material__material_number", "inventory_raw_material__material_name",
    )
    object_type = "FABRIC_MATERIAL"


class FabricSpecificationViewSet(ManagedReferenceViewSet):
    queryset = FabricSpecification.objects.all()
    serializer_class = FabricSpecificationSerializer
    search_fields = ("specification_name",)
    object_type = "FABRIC_SPECIFICATION"


class FabricWidthViewSet(ManagedReferenceViewSet):
    queryset = FabricWidth.objects.all()
    serializer_class = FabricWidthSerializer
    search_fields = ("width_value",)
    object_type = "FABRIC_WIDTH"


class TubeProductNameViewSet(ManagedReferenceViewSet):
    queryset = TubeProductName.objects.all()
    serializer_class = TubeProductNameSerializer
    search_fields = ("product_name", "pinyin_search")
    object_type = "TUBE_PRODUCT_NAME"


class TubeThicknessViewSet(ManagedReferenceViewSet):
    queryset = TubeThickness.objects.all()
    serializer_class = TubeThicknessSerializer
    search_fields = ("thickness_value",)
    object_type = "TUBE_THICKNESS"


class TubeDiameterViewSet(ManagedReferenceViewSet):
    queryset = TubeDiameter.objects.all()
    serializer_class = TubeDiameterSerializer
    search_fields = ("diameter_value",)
    object_type = "TUBE_DIAMETER"


class TubeMaterialViewSet(ManagedReferenceViewSet):
    queryset = TubeMaterial.objects.all()
    serializer_class = TubeMaterialSerializer
    search_fields = ("material_name", "pinyin_search")
    object_type = "TUBE_MATERIAL"


class TubeShapeViewSet(ManagedReferenceViewSet):
    queryset = TubeShape.objects.all()
    serializer_class = TubeShapeSerializer
    search_fields = ("shape_name", "pinyin_search")
    object_type = "TUBE_SHAPE"


class TubeCoatingColorViewSet(ManagedReferenceViewSet):
    queryset = TubeCoatingColor.objects.all()
    serializer_class = TubeCoatingColorSerializer
    search_fields = ("color_name",)
    object_type = "TUBE_COATING_COLOR"


class AccessoryProductNameViewSet(ManagedReferenceViewSet):
    queryset = AccessoryProductName.objects.all()
    serializer_class = AccessoryProductNameSerializer
    search_fields = ("product_name", "unit_name")
    object_type = "ACCESSORY_PRODUCT_NAME"

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        instance = self.get_object()
        if (
            instance.specifications.filter(archived_at__isnull=True).exists()
            or instance.colors.filter(archived_at__isnull=True).exists()
        ):
            raise Conflict("该辅料品名已被规格或颜色引用，不能归档；可改为停用。")
        return super().archive(request, pk=pk)


class AccessorySpecificationViewSet(ManagedReferenceViewSet):
    queryset = AccessorySpecification.objects.select_related("product_name")
    serializer_class = AccessorySpecificationSerializer
    search_fields = ("product_name__product_name", "specification_value", "weight")
    object_type = "ACCESSORY_SPECIFICATION"

    def get_queryset(self):
        queryset = super().get_queryset()
        product_name_id = self.request.query_params.get("product_name_id", "").strip()
        if not product_name_id:
            return queryset
        try:
            normalized_id = UUID(product_name_id)
        except ValueError as exc:
            raise ValidationError({"product_name_id": "辅料品名编号格式不正确。"}) from exc
        return queryset.filter(product_name_id=normalized_id)


class AccessoryColorViewSet(ManagedReferenceViewSet):
    queryset = AccessoryColor.objects.select_related("product_name")
    serializer_class = AccessoryColorSerializer
    search_fields = ("product_name__product_name", "color_name")
    object_type = "ACCESSORY_COLOR"

    def get_queryset(self):
        queryset = super().get_queryset()
        product_name_id = self.request.query_params.get("product_name_id", "").strip()
        if not product_name_id:
            return queryset
        try:
            normalized_id = UUID(product_name_id)
        except ValueError as exc:
            raise ValidationError({"product_name_id": "辅料品名编号格式不正确。"}) from exc
        return queryset.filter(product_name_id=normalized_id)


class AccessoryMaterialViewSet(ManagedReferenceViewSet):
    queryset = AccessoryMaterial.objects.select_related("inventory_raw_material", "inventory_raw_material__unit")
    serializer_class = AccessoryMaterialSerializer
    search_fields = (
        "material_name", "inventory_raw_material__material_number", "inventory_raw_material__material_name",
    )
    object_type = "ACCESSORY_MATERIAL"


class IncotermViewSet(ManagedReferenceViewSet):
    queryset = Incoterm.objects.all()
    serializer_class = IncotermSerializer
    object_type = "INCOTERM"
    permission_classes = [IsAuthenticated, HasActiveEmployee, StandardMasterDataPermission]


class PaymentMethodViewSet(ManagedReferenceViewSet):
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    object_type = "PAYMENT_METHOD"


class TransportMethodViewSet(ManagedReferenceViewSet):
    queryset = TransportMethod.objects.all()
    serializer_class = TransportMethodSerializer
    object_type = "TRANSPORT_METHOD"


class PortViewSet(ManagedReferenceViewSet):
    queryset = Port.objects.select_related("country")
    serializer_class = PortSerializer
    object_type = "PORT"

    def get_queryset(self):
        queryset = super().get_queryset()
        country_code = self.request.query_params.get("country_code", "").strip().upper()
        return queryset.filter(country__code=country_code) if country_code else queryset


class CourierViewSet(ManagedReferenceViewSet):
    queryset = Courier.objects.all()
    serializer_class = CourierSerializer
    object_type = "COURIER"


class ExchangeRateViewSet(
    ConfigurationListCacheMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ExchangeRate.objects.select_related(
        "base_currency",
        "quote_currency",
        "entered_by_employee",
        "correction_of",
    )
    serializer_class = ExchangeRateSerializer
    permission_classes = [IsAuthenticated, HasActiveEmployee, ReferenceDataManagementPermission]
    permission_model = ExchangeRate

    def get_queryset(self):
        queryset = super().get_queryset().filter(archived_at__isnull=True)
        base_code = self.request.query_params.get("base_currency", "").strip().upper()
        quote_code = self.request.query_params.get("quote_currency", "").strip().upper()
        if base_code:
            queryset = queryset.filter(base_currency__code=base_code)
        if quote_code:
            queryset = queryset.filter(quote_currency__code=quote_code)
        requested_status = self.request.query_params.get("status")
        if requested_status in ReferenceStatus.values:
            queryset = queryset.filter(status=requested_status)
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(base_currency__code__icontains=keyword)
                | Q(quote_currency__code__icontains=keyword)
                | Q(source_name__icontains=keyword)
                | Q(source_version__icontains=keyword)
            )
        source = self.request.query_params.get("source", "").strip()
        if source:
            queryset = queryset.filter(
                Q(source_name__icontains=source) | Q(source_version__icontains=source)
            )
        return queryset

    def actor_employee(self):
        return getattr(self.request, "employee", None)

    def _response(self, instance, response_status=status.HTTP_200_OK):
        response = Response({"data": self.get_serializer(instance).data}, status=response_status)
        response["ETag"] = etag_for_instance(instance)
        return response

    def retrieve(self, request, *args, **kwargs):
        return self._response(self.get_object())

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            instance = serializer.save(entered_by_employee=self.actor_employee())
            write_audit_log(
                object_type="EXCHANGE_RATE",
                object_id=instance.pk,
                action="CREATED",
                actor_employee=self.actor_employee(),
                after_data=self.get_serializer(instance).data,
                request=request,
            )
        return self._response(instance, status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def correct(self, request, pk=None):
        current = self.get_object()
        require_matching_etag(request, current)
        serializer = ExchangeRateCorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            # nullable 的 correction_of 使用外连接，不能与 PostgreSQL FOR UPDATE 一起锁定。
            current = ExchangeRate.objects.select_for_update().select_related(
                "base_currency",
                "quote_currency",
            ).get(pk=current.pk)
            require_matching_etag(request, current)
            if hasattr(current, "corrected_by"):
                raise Conflict("该汇率记录已经存在更正记录，请对最新记录继续更正。")
            current.status = ReferenceStatus.INACTIVE
            current.save(update_fields=["status", "updated_at"])
            corrected = ExchangeRate.objects.create(
                base_currency=current.base_currency,
                quote_currency=current.quote_currency,
                correction_of=current,
                entered_by_employee=self.actor_employee(),
                **serializer.validated_data,
            )
            write_audit_log(
                object_type="EXCHANGE_RATE",
                object_id=corrected.pk,
                action="CORRECTED",
                actor_employee=self.actor_employee(),
                before_data=self.get_serializer(current).data,
                after_data=self.get_serializer(corrected).data,
                request=request,
            )
        return self._response(corrected, status.HTTP_201_CREATED)


class ConfigReleaseViewSet(
    ConfigurationListCacheMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ConfigRelease.objects.select_related("published_by_employee")
    serializer_class = ConfigReleaseSerializer
    permission_classes = [IsAuthenticated, HasActiveEmployee, ReferenceDataManagementPermission]
    permission_model = ConfigRelease

    def create(self, request, *args, **kwargs):
        serializer = PublishConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        release = publish_config(
            actor_employee=getattr(request, "employee", None),
            notes=serializer.validated_data.get("notes", ""),
            request=request,
            expected_etag=request.headers.get("If-Match"),
        )
        response = Response({"data": self.get_serializer(release).data}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(release)
        return response

    def retrieve(self, request, *args, **kwargs):
        release = self.get_object()
        response = Response({"data": self.get_serializer(release).data})
        response["ETag"] = etag_for_instance(release)
        return response


class SystemParameterViewSet(
    ConfigurationListCacheMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = SystemParameterDefinition.objects.select_related("value_record")
    serializer_class = SystemParameterSerializer
    permission_classes = [IsAuthenticated, HasActiveEmployee, ReferenceDataManagementPermission]
    permission_model = SystemParameterDefinition

    def get_queryset(self):
        return super().get_queryset().filter(archived_at__isnull=True)

    def _response(self, definition):
        response = Response({"data": self.get_serializer(definition).data})
        response["ETag"] = etag_for_instance(definition.value_record)
        return response

    def retrieve(self, request, *args, **kwargs):
        return self._response(self.get_object())

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        definition = self.get_object()
        value_record = definition.value_record
        require_matching_etag(request, value_record)
        serializer = SystemParameterDraftSerializer(
            data=request.data,
            context={"definition": definition},
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            locked = SystemParameterValue.objects.select_for_update().get(pk=value_record.pk)
            require_matching_etag(request, locked)
            before_value = locked.draft_value
            locked.draft_value = serializer.validated_data["draft_value"]
            locked.updated_by_employee = getattr(request, "employee", None)
            locked.save(update_fields=["draft_value", "updated_by_employee", "updated_at"])
            write_audit_log(
                object_type="SYSTEM_PARAMETER_VALUE",
                object_id=locked.pk,
                action="UPDATED",
                actor_employee=getattr(request, "employee", None),
                before_data={"code": definition.code, "draft_value": before_value},
                after_data={"code": definition.code, "draft_value": locked.draft_value},
                request=request,
            )
        definition = self.get_queryset().get(pk=definition.pk)
        return self._response(definition)


class PublishedConfigVersionView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee]

    @extend_schema(responses=PublishedConfigVersionResponseSerializer)
    def get(self, request):
        _, state = published_config_state()
        return Response({"data": state}, headers={"Cache-Control": "no-store"})


class PublishedOptionsBatchView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee]

    @extend_schema(parameters=[PublishedOptionsBatchQuerySerializer], responses=PublishedOptionsBatchResponseSerializer)
    def get(self, request):
        query = PublishedOptionsBatchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        codes = query.validated_data['type_codes']
        catalog = published_catalog()
        state = catalog['meta']
        active = set(catalog['active'])
        source = catalog['options']
        return Response({
            'data': {code: source.get(code, []) for code in codes if code in active},
            'errors': {code: '字典类型不存在或已停用。' for code in codes if code not in active},
            'meta': state,
        }, headers={'Cache-Control': 'no-store'})


class PublishedOptionsView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="current_id",
                type=str,
                required=False,
                description="编辑历史数据时需要保留显示的当前字典项 UUID。",
            )
        ],
        responses=PublishedOptionsResponseSerializer,
    )
    def get(self, request, type_code):
        normalized_code = type_code.strip().upper()
        if not request.query_params.get('current_id'):
            catalog = published_catalog()
            if normalized_code not in catalog['active']:
                from rest_framework.exceptions import NotFound
                raise NotFound('字典类型不存在或已停用。')
            return Response({'data': catalog['options'].get(normalized_code, []),
                             'meta': {'config_version': catalog['meta']['config_version']}},
                            headers={'Cache-Control': 'no-store'})
        get_object_or_404(
            DictionaryType,
            code=normalized_code,
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        )
        options, version = published_dictionary_options(
            normalized_code,
            current_item_id=request.query_params.get("current_id"),
        )
        return Response({"data": options, "meta": {"config_version": version}},
                        headers={'Cache-Control': 'no-store'})


class ReferenceDataSummaryView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, ReferenceDataManagementPermission]
    required_permission = "reference_data.view_dictionarytype"

    @extend_schema(responses=ReferenceDataSummarySerializer)
    def get(self, request):
        latest_release = latest_published_release()
        payload = {
            "active_dictionary_items": ReferenceDictionary.objects.filter(
                status=ReferenceStatus.ACTIVE,
                archived_at__isnull=True,
                dictionary_type__status=ReferenceStatus.ACTIVE,
                dictionary_type__archived_at__isnull=True,
            ).count(),
            "active_system_parameters": SystemParameterDefinition.objects.filter(
                status=ReferenceStatus.ACTIVE,
                archived_at__isnull=True,
            ).count(),
            "pending_changes": pending_config_change_count(),
            "config_version": latest_release.version if latest_release else None,
        }
        return Response({"data": payload})


class MasterDataSummaryView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, MasterDataSummaryPermission]
    standard_sources = ["ISO 3166", "ISO 4217", "UN/CEFACT Rec.20", "ICC 2020", "UN/LOCODE"]

    @extend_schema(responses=MasterDataSummarySerializer)
    def get(self, request):
        latest_release = latest_published_release()
        parameters = latest_release.snapshot.get("system_parameters", {}) if latest_release else {}
        payload = {
            "category_counts": {
                "countries": Country.objects.filter(archived_at__isnull=True).count(),
                "currencies": Currency.objects.filter(archived_at__isnull=True).count(),
                "exchange_rates": ExchangeRate.objects.filter(archived_at__isnull=True).count(),
                "units": Unit.objects.filter(archived_at__isnull=True).count(),
                "incoterms": Incoterm.objects.filter(archived_at__isnull=True).count(),
                "payment_methods": PaymentMethod.objects.filter(archived_at__isnull=True).count(),
                "transport_methods": TransportMethod.objects.filter(archived_at__isnull=True).count(),
                "ports": Port.objects.filter(archived_at__isnull=True).count(),
                "couriers": Courier.objects.filter(archived_at__isnull=True).count(),
            },
            "standard_source_count": len(self.standard_sources),
            "standard_sources": self.standard_sources,
            "base_currency": parameters.get("DEFAULT_CURRENCY"),
            "config_version": latest_release.version if latest_release else None,
        }
        return Response({"data": payload})


class ProductionDataSummaryView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, ProductionDataSummaryPermission]

    @extend_schema(responses=ProductionDataSummarySerializer)
    def get(self, request):
        payload = {
            "category_counts": {
                "product_categories": ProductCategory.objects.filter(archived_at__isnull=True).count(),
                "production_units": ProductionUnit.objects.filter(archived_at__isnull=True).count(),
                "product_colors": ProductColor.objects.filter(archived_at__isnull=True).count(),
                "product_items": ProductItem.objects.filter(archived_at__isnull=True).count(),
                "fabric_materials": FabricMaterial.objects.filter(archived_at__isnull=True).count(),
                "fabric_specifications": FabricSpecification.objects.filter(archived_at__isnull=True).count(),
                "fabric_widths": FabricWidth.objects.filter(archived_at__isnull=True).count(),
                "tube_product_names": TubeProductName.objects.filter(archived_at__isnull=True).count(),
                "tube_thicknesses": TubeThickness.objects.filter(archived_at__isnull=True).count(),
                "tube_diameters": TubeDiameter.objects.filter(archived_at__isnull=True).count(),
                "tube_materials": TubeMaterial.objects.filter(archived_at__isnull=True).count(),
                "tube_shapes": TubeShape.objects.filter(archived_at__isnull=True).count(),
                "tube_coating_colors": TubeCoatingColor.objects.filter(archived_at__isnull=True).count(),
                "accessory_product_names": AccessoryProductName.objects.filter(archived_at__isnull=True).count(),
                "accessory_specifications": AccessorySpecification.objects.filter(archived_at__isnull=True).count(),
                "accessory_colors": AccessoryColor.objects.filter(archived_at__isnull=True).count(),
                "accessory_materials": AccessoryMaterial.objects.filter(archived_at__isnull=True).count(),
            }
        }
        return Response({"data": payload})
