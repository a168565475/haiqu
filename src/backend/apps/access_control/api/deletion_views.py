from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from .. import deletion_services as services
from .base import IF_MATCH
from .serializers import StrictSerializer


class DeleteItemSerializer(StrictSerializer):
    id = serializers.UUIDField()
    etag = serializers.CharField(max_length=150)


class DeletePreviewSerializer(StrictSerializer):
    items = DeleteItemSerializer(many=True, allow_empty=False, max_length=500)


class DeleteConfirmSerializer(DeletePreviewSerializer):
    token = serializers.CharField(max_length=4000)
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value):
        if not value:
            raise serializers.ValidationError("请确认删除影响后再执行。")
        return value


class DeleteResultSerializer(serializers.Serializer):
    rows = serializers.ListField(child=serializers.DictField())
    token = serializers.CharField(required=False)
    etag = serializers.CharField(required=False)
    self_deleted = serializers.BooleanField(required=False)


class DeletionActions:
    @extend_schema(request=DeletePreviewSerializer, responses=DeleteResultSerializer)
    @action(detail=False, methods=["post"], url_path="delete-preview")
    def delete_preview(self, request):
        serializer = DeletePreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.preview_deletion(request, self.deletion_kind, serializer.validated_data["items"])
        result["etag"] = f'"{services.fingerprint(result["rows"])}"'
        return Response(result, headers={"ETag": result["etag"], "Cache-Control": "no-store"})

    @extend_schema(request=DeleteConfirmSerializer, responses=DeleteResultSerializer, parameters=[IF_MATCH])
    @action(detail=False, methods=["post"], url_path="delete-selected")
    def delete_selected(self, request):
        serializer = DeleteConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = services.delete_selected(request, self.deletion_kind, data["items"], data["token"])
        return Response(result)
