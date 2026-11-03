from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.permissions import HasActiveEmployee
from apps.material_catalog.public_configuration import ACTIVE, SOURCES, public_fields, public_options
from apps.reference_data.models import AccessoryProductName, ProductCategory, ProductItem, TubeDiameter, TubeShape

from .serializers import AttributeValueResponseSerializer, CatalogErrorResponseSerializer, StrictSerializer, UnitOptionSerializer


class PublicConfigurationReadPermission(BasePermission):
    def has_permission(self, request, view):
        models = {row[0] for row in SOURCES.values()} | {TubeDiameter, AccessoryProductName, ProductCategory, ProductItem}
        return request.user.has_perm("material_catalog.view_materialcatalog") or any(
            request.user.has_perm(f"reference_data.view_{model._meta.model_name}") for model in models
        )


class PublicOptionsQuerySerializer(StrictSerializer):
    category_key = serializers.CharField(max_length=30)
    template_key = serializers.CharField(max_length=30)
    scope = serializers.ChoiceField(choices=["BASE", "SPRAY"], default="BASE")


class PublicOptionsDataSerializer(serializers.Serializer):
    category_key = serializers.CharField()
    template_key = serializers.CharField()
    scope = serializers.CharField()
    values = AttributeValueResponseSerializer(many=True)
    units = UnitOptionSerializer(many=True)
    fields = serializers.ListField(child=serializers.DictField())


class PublicOptionsResponseSerializer(serializers.Serializer):
    data = PublicOptionsDataSerializer()


class PublicMetadataResponseSerializer(serializers.Serializer):
    data = serializers.DictField()


class PublicMaterialOptionsView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, PublicConfigurationReadPermission]

    @extend_schema(parameters=[PublicOptionsQuerySerializer], responses={200: PublicOptionsResponseSerializer, 400: CatalogErrorResponseSerializer})
    def get(self, request):
        serializer = PublicOptionsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return Response({"data": public_options(**serializer.validated_data)})


class PublicMaterialFieldsView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, PublicConfigurationReadPermission]

    @extend_schema(responses=PublicMetadataResponseSerializer)
    def get(self, request):
        return Response({"data": public_fields()})


class PublicTubeOptionsView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, PublicConfigurationReadPermission]

    @extend_schema(responses=PublicMetadataResponseSerializer)
    def get(self, request):
        return Response({"data": {
            "shapes": [{"id": str(row.pk), "shape_name": row.shape_name} for row in TubeShape.objects.filter(**ACTIVE)],
            "diameters": [{"id": str(row.pk), "diameter_value": row.diameter_value} for row in TubeDiameter.objects.filter(**ACTIVE)],
        }})
