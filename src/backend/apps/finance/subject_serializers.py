from rest_framework import serializers

from apps.core.api.concurrency import etag_for_instance
from .models import AccountingSubject, FinanceAccount
from .serializers import TextField
from .subject_selectors import ancestors


class SubjectWriteSerializer(serializers.Serializer):
    parent_id = serializers.UUIDField(allow_null=True)
    level = serializers.IntegerField(min_value=1, max_value=3)
    name = TextField(max_length=100)
    status = serializers.ChoiceField(choices=FinanceAccount.Status.choices)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({"non_field_errors": "请求必须是 JSON 对象。"})
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({field: "不支持此字段。" for field in sorted(unknown)})
        if self.partial and set(data) & {"parent_id", "level"}:
            raise serializers.ValidationError({"non_field_errors": "已有科目只能修改名称和启停，不允许移动层级。"})
        return super().to_internal_value(data)


class SubjectQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=306, required=False, allow_blank=True)
    level = serializers.IntegerField(min_value=1, max_value=3, required=False)
    parent_id = serializers.UUIDField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=FinanceAccount.Status.choices, required=False)
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class SubjectSerializer(serializers.ModelSerializer):
    parent_id = serializers.UUIDField(allow_null=True, read_only=True)
    full_path = serializers.CharField(read_only=True)
    path_names = serializers.SerializerMethodField()
    etag = serializers.SerializerMethodField()
    effective_status = serializers.SerializerMethodField()
    blocked_by_ancestor = serializers.SerializerMethodField()
    child_count = serializers.IntegerField(read_only=True)
    affected_path_count = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    delete_block_reason = serializers.SerializerMethodField()

    class Meta:
        model = AccountingSubject
        fields = ("id", "parent_id", "level", "name", "status", "full_path", "path_names", "effective_status",
                  "blocked_by_ancestor", "child_count", "affected_path_count", "can_delete", "delete_block_reason",
                  "created_at", "updated_at", "etag")

    def get_etag(self, obj) -> str:
        return etag_for_instance(obj)

    def get_path_names(self, obj) -> list[str]:
        return [node.name for node in ancestors(obj)] + [obj.name]

    def get_blocked_by_ancestor(self, obj) -> str | None:
        inactive = [node.name for node in ancestors(obj) if node.status == "INACTIVE"]
        return "上级停用：" + " / ".join(inactive) if inactive else None

    def get_effective_status(self, obj) -> str:
        return "INACTIVE" if obj.status == "INACTIVE" or self.get_blocked_by_ancestor(obj) else "ACTIVE"

    def get_affected_path_count(self, obj) -> int:
        return 1 if obj.level == 3 else obj.child_count if obj.level == 2 else obj.grandchild_count

    def get_can_delete(self, obj) -> bool:
        return obj.child_count == 0

    def get_delete_block_reason(self, obj) -> str | None:
        return "含下级科目，请先处理下级；不能级联删除。" if obj.child_count else None


class SubjectResponseSerializer(serializers.Serializer):
    data = SubjectSerializer()
