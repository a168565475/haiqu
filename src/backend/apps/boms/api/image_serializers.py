from django.urls import reverse
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from ..models import BomLineImage, BomLineImageDraft


class BomLineImageSerializer(serializers.ModelSerializer):
    file_id = serializers.UUIDField(source="business_file_id", read_only=True)
    name = serializers.CharField(source="business_file.original_name", read_only=True)
    content_type = serializers.CharField(source="business_file.content_type", read_only=True)
    size_bytes = serializers.IntegerField(source="business_file.size_bytes", read_only=True)
    content_url = serializers.SerializerMethodField()

    class Meta:
        model = BomLineImage
        fields = [
            "id",
            "file_id",
            "position",
            "name",
            "content_type",
            "size_bytes",
            "content_url",
        ]
        read_only_fields = fields

    def get_content_url(self, instance) -> str:
        return reverse(
            "bom-line-image-content",
            kwargs={
                "bom_id": instance.bom_line.section.bom_id,
                "line_id": instance.bom_line_id,
                "image_id": instance.pk,
            },
        )


class BomLineImageUploadSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=serializers.FileField(allow_empty_file=False),
        allow_empty=False,
        max_length=10,
    )


class BomLineImageDraftSerializer(serializers.ModelSerializer):
    file_id = serializers.UUIDField(source="business_file_id", read_only=True)
    name = serializers.CharField(source="business_file.original_name", read_only=True)
    content_type = serializers.CharField(source="business_file.content_type", read_only=True)
    size_bytes = serializers.IntegerField(source="business_file.size_bytes", read_only=True)
    content_url = serializers.SerializerMethodField()

    class Meta:
        model = BomLineImageDraft
        fields = [
            "id",
            "file_id",
            "draft_key",
            "position",
            "name",
            "content_type",
            "size_bytes",
            "content_url",
            "expires_at",
        ]
        read_only_fields = fields

    def get_content_url(self, instance) -> str:
        return reverse(
            "bom-line-image-draft-content",
            kwargs={"bom_id": instance.bom_id, "draft_id": instance.pk},
        )


class BomLineImageDraftUploadSerializer(BomLineImageUploadSerializer):
    draft_key = serializers.UUIDField()


@extend_schema_serializer(many=False)
class BomLineImageListResponseSerializer(serializers.Serializer):
    data = BomLineImageSerializer(many=True)


@extend_schema_serializer(many=False)
class BomLineImageDraftListResponseSerializer(serializers.Serializer):
    data = BomLineImageDraftSerializer(many=True)


class BomLineImageDeleteDataSerializer(serializers.Serializer):
    deleted_id = serializers.UUIDField()


class BomLineImageDeleteResponseSerializer(serializers.Serializer):
    data = BomLineImageDeleteDataSerializer()
