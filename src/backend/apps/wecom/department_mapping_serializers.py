from rest_framework import serializers

from .directory_serializers import DirectorySnapshotSerializer

class DepartmentMappingWriteSerializer(serializers.Serializer):
    preview_token = serializers.CharField(max_length=5000, trim_whitespace=False)
    organization_unit_id = serializers.UUIDField(allow_null=True)
    organization_etag = serializers.CharField(max_length=100, trim_whitespace=False, required=False, allow_null=True)
    confirmed = serializers.BooleanField()

    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError("请求包含不支持的字段。")
        if not attrs["confirmed"]:
            raise serializers.ValidationError({"confirmed": "必须确认部门映射或清除操作。"})
        if attrs["organization_unit_id"] is not None and not attrs.get("organization_etag"):
            raise serializers.ValidationError({"organization_etag": "选择 ERP 部门时必须提供其版本。"})
        return attrs


class MappingSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    wecom_department_id = serializers.IntegerField()
    organization_unit_id = serializers.UUIDField(allow_null=True)
    updated_at = serializers.DateTimeField()
    organization_etag = serializers.CharField(allow_null=True)
    organization_active = serializers.BooleanField()
    organization_name = serializers.CharField(allow_blank=True)


class OrganizationOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    unit_code = serializers.CharField()
    unit_name = serializers.CharField()
    status = serializers.ChoiceField(choices=["ACTIVE", "INACTIVE"])
    archived = serializers.BooleanField()
    etag = serializers.CharField()


class SourceDepartmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    parentid = serializers.IntegerField()
    name = serializers.CharField()
    mapping = MappingSerializer(allow_null=True)
    candidates = OrganizationOptionSerializer(many=True)


class DepartmentMappingPreviewSerializer(serializers.Serializer):
    corp_id = serializers.CharField()
    departments = SourceDepartmentSerializer(many=True)
    organizations = OrganizationOptionSerializer(many=True)
    preview_token = serializers.CharField(allow_blank=True)
    can_save_mapping = serializers.BooleanField()
    can_edit_saved_mappings = serializers.BooleanField()
    snapshot = DirectorySnapshotSerializer()


class DepartmentMappingPreviewResponseSerializer(serializers.Serializer):
    data = DepartmentMappingPreviewSerializer()


class DepartmentMappingResponseSerializer(serializers.Serializer):
    data = MappingSerializer()
