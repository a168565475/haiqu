from django.utils import timezone
from rest_framework import serializers

from apps.organizations.selectors import active_department_employees
from apps.core.serializers import EmployeeSummarySerializer
from apps.organizations.models import Employee
from apps.reference_data.models import ReferenceDictionary
from apps.workflow.models import TaskPriority

from ..models import (
    ContactMethodType,
    ContactRoleType,
    ContactStatus,
    CustomerContact,
    CustomerContactEmploymentEvent,
    CustomerContactMethod,
)


STATUS_LABELS = {
    ContactStatus.ACTIVE: "在职",
    ContactStatus.INACTIVE: "停用",
    ContactStatus.LEFT: "已离职",
}


def validate_dictionary_code(category_code, value, label):
    if not value:
        return ""
    exists = ReferenceDictionary.objects.filter(
        category_code=category_code,
        item_code=value,
        status="ACTIVE",
        archived_at__isnull=True,
    ).exists()
    if not exists:
        raise serializers.ValidationError(f"{label}不是有效配置项。")
    return value


def validate_timezone_code(value):
    if not value:
        return ""
    exists = ReferenceDictionary.objects.filter(
        category_code="CONTACT_TIMEZONE",
        status="ACTIVE",
        archived_at__isnull=True,
        extra_data__timezone_code=value,
    ).exists()
    if not exists:
        raise serializers.ValidationError("时区不是有效配置项。")
    return value


def mask_contact_value(method_type, value):
    value = value or ""
    if not value:
        return ""
    if method_type == ContactMethodType.EMAIL and "@" in value:
        local, domain = value.split("@", 1)
        visible = local[:1]
        return f"{visible}{'*' * max(3, len(local) - 1)}@{domain}"
    if method_type in {ContactMethodType.PHONE, ContactMethodType.MOBILE, ContactMethodType.WHATSAPP}:
        if len(value) <= 4:
            return "*" * len(value)
        return f"{value[:3]}{'*' * max(4, len(value) - 7)}{value[-4:]}"
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[:1]}{'*' * max(2, len(value) - 2)}{value[-1:]}"


class ContactMethodReadSerializer(serializers.ModelSerializer):
    display_value = serializers.SerializerMethodField()
    masked_value = serializers.SerializerMethodField()
    normalized_value = serializers.SerializerMethodField()
    method_type_display = serializers.CharField(source="get_method_type_display", read_only=True)

    class Meta:
        model = CustomerContactMethod
        fields = [
            "id", "method_type", "method_type_display", "display_value", "masked_value", "normalized_value",
            "is_primary", "is_preferred", "verification_status", "archived_at", "updated_at",
        ]

    def get_masked_value(self, obj) -> str:
        return mask_contact_value(obj.method_type, obj.raw_value)

    def get_display_value(self, obj) -> str:
        if self.context.get("allow_sensitive", False):
            return obj.raw_value
        return mask_contact_value(obj.method_type, obj.raw_value)

    def get_normalized_value(self, obj) -> str:
        if self.context.get("allow_sensitive", False):
            return obj.normalized_value
        return mask_contact_value(obj.method_type, obj.normalized_value)


class ContactMethodInputSerializer(serializers.Serializer):
    method_type = serializers.ChoiceField(choices=ContactMethodType.choices)
    raw_value = serializers.CharField(max_length=255, trim_whitespace=True)
    is_primary = serializers.BooleanField(required=False, default=False)
    is_preferred = serializers.BooleanField(required=False, default=False)
    verification_status = serializers.CharField(max_length=20, required=False, default="UNVERIFIED")


class CustomerContactListSerializer(serializers.ModelSerializer):
    customer = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    methods = serializers.SerializerMethodField()
    active_roles = serializers.SerializerMethodField()
    last_interaction = serializers.SerializerMethodField()
    open_task_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = CustomerContact
        fields = [
            "id", "customer", "display_name", "english_name", "position_title", "department_name",
            "preferred_language_code", "timezone_code", "is_key_contact", "is_primary_contact",
            "status", "status_display", "methods", "active_roles", "last_interaction",
            "open_task_count", "left_effective_date", "marketing_opt_out",
            "archived_at", "created_at", "updated_at",
        ]

    def get_customer(self, obj) -> dict:
        return {
            "id": str(obj.customer_account_id),
            "account_code": obj.customer_account.account_code,
            "account_name": obj.customer_account.account_name,
        }

    def get_status_display(self, obj) -> str:
        return STATUS_LABELS.get(obj.status, obj.get_status_display())

    def get_methods(self, obj) -> list:
        methods = getattr(obj, "active_methods", [])
        return ContactMethodReadSerializer(methods, many=True, context={"allow_sensitive": True}).data

    def get_active_roles(self, obj) -> list:
        return [
            {"id": str(role.id), "role_type": role.role_type, "role_type_display": role.get_role_type_display()}
            for role in getattr(obj, "active_roles_prefetched", [])
        ]

    def get_last_interaction(self, obj) -> dict | None:
        occurred_at = getattr(obj, "last_interaction_at", None)
        if occurred_at is None:
            return None
        return {
            "occurred_at": occurred_at,
            "communication_type": getattr(obj, "last_interaction_type", None),
        }


class CustomerContactDetailSerializer(CustomerContactListSerializer):
    methods = serializers.SerializerMethodField()

    class Meta(CustomerContactListSerializer.Meta):
        fields = CustomerContactListSerializer.Meta.fields + [
            "transaction_entity", "source_contact", "notes", "legacy_source_data", "archive_reason",
            "marketing_opt_out_at", "marketing_opt_out_by_employee",
        ]

    def get_methods(self, obj) -> list:
        request = self.context.get("request")
        allow_sensitive = bool(
            request
            and request.user.has_perm("customers.view_sensitive_customercontactmethod")
        )
        methods = getattr(obj, "active_methods", [])
        return ContactMethodReadSerializer(
            methods,
            many=True,
            context={"allow_sensitive": allow_sensitive},
        ).data


class CustomerContactCreateSerializer(serializers.ModelSerializer):
    methods = ContactMethodInputSerializer(many=True, required=False, default=list, write_only=True)
    role_types = serializers.ListField(
        child=serializers.ChoiceField(choices=ContactRoleType.choices),
        required=False,
        default=list,
        write_only=True,
    )
    duplicate_acknowledged = serializers.BooleanField(required=False, default=False, write_only=True)

    class Meta:
        model = CustomerContact
        fields = [
            "transaction_entity", "source_contact", "display_name", "english_name", "position_title",
            "department_name", "preferred_language_code", "timezone_code", "is_key_contact",
            "is_primary_contact", "status", "notes", "methods", "role_types",
            "duplicate_acknowledged",
        ]

    def validate_preferred_language_code(self, value):
        return validate_dictionary_code("CONTACT_LANGUAGE", value, "首选语言")

    def validate_timezone_code(self, value):
        return validate_timezone_code(value)

    def validate(self, attrs):
        customer = self.context["customer_account"]
        entity = attrs.get("transaction_entity")
        source = attrs.get("source_contact")
        if entity and (entity.customer_account_id != customer.id or entity.archived_at is not None):
            raise serializers.ValidationError({"transaction_entity": "交易主体必须是当前客户的有效主体。"})
        if source and (source.customer_account_id != customer.id or source.archived_at is not None):
            raise serializers.ValidationError({"source_contact": "来源联系人必须是当前客户的有效联系人。"})
        methods = attrs.get("methods", [])
        if not methods:
            raise serializers.ValidationError({"methods": "在职联系人至少需要一种有效联系方式。"})
        if len(methods) > 20:
            raise serializers.ValidationError({"methods": "单个联系人最多提交 20 种联系方式。"})
        role_types = attrs.get("role_types", [])
        if len(role_types) != len(set(role_types)):
            raise serializers.ValidationError({"role_types": "联系人角色不能重复。"})
        if attrs.get("status", ContactStatus.ACTIVE) == ContactStatus.LEFT:
            raise serializers.ValidationError({"status": "新联系人不能直接创建为已离职。"})
        return attrs


class CustomerContactUpdateSerializer(serializers.ModelSerializer):
    methods = ContactMethodInputSerializer(many=True, required=False, write_only=True)
    role_types = serializers.ListField(
        child=serializers.ChoiceField(choices=ContactRoleType.choices),
        required=False,
        write_only=True,
    )
    duplicate_acknowledged = serializers.BooleanField(required=False, default=False, write_only=True)

    class Meta:
        model = CustomerContact
        fields = [
            "transaction_entity", "source_contact", "display_name", "english_name", "position_title",
            "department_name", "preferred_language_code", "timezone_code", "is_key_contact",
            "is_primary_contact", "status", "notes", "methods", "role_types",
            "duplicate_acknowledged",
        ]

    def validate_preferred_language_code(self, value):
        return validate_dictionary_code("CONTACT_LANGUAGE", value, "首选语言")

    def validate_timezone_code(self, value):
        return validate_timezone_code(value)

    def validate_status(self, value):
        if value == ContactStatus.LEFT:
            raise serializers.ValidationError("请使用标记离职接口。")
        return value

    def validate(self, attrs):
        customer = self.instance.customer_account
        entity = attrs.get("transaction_entity", self.instance.transaction_entity)
        source = attrs.get("source_contact", self.instance.source_contact)
        if entity and (entity.customer_account_id != customer.id or entity.archived_at is not None):
            raise serializers.ValidationError({"transaction_entity": "交易主体必须是当前客户的有效主体。"})
        if source and (source.customer_account_id != customer.id or source.archived_at is not None):
            raise serializers.ValidationError({"source_contact": "来源联系人必须是当前客户的有效联系人。"})
        if source and source.pk == self.instance.pk:
            raise serializers.ValidationError({"source_contact": "来源联系人不能是联系人自己。"})
        role_types = attrs.get("role_types")
        if role_types is not None and len(role_types) != len(set(role_types)):
            raise serializers.ValidationError({"role_types": "联系人角色不能重复。"})
        return attrs


class ContactDuplicateCheckSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField()
    method_type = serializers.ChoiceField(choices=ContactMethodType.choices)
    value = serializers.CharField(max_length=255, trim_whitespace=True)
    exclude_contact_id = serializers.UUIDField(required=False)


class ContactMarkLeftSerializer(serializers.Serializer):
    effective_date = serializers.DateField(default=timezone.localdate)
    replacement_contact_id = serializers.UUIDField(required=False, allow_null=True)
    unfinished_task_policy = serializers.ChoiceField(
        choices=["TRANSFER_TO_OWNER", "KEEP_ASSIGNEE", "CANCEL_OPEN"],
        default="TRANSFER_TO_OWNER",
    )
    preserve_history = serializers.BooleanField(default=True)
    remove_from_marketing = serializers.BooleanField(default=True)
    notify_stakeholders = serializers.BooleanField(default=False)
    reason = serializers.CharField(max_length=500, trim_whitespace=True, required=False, default="联系人离职")

    def validate_effective_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("离职生效日期不能晚于今天。")
        return value

    def validate_preserve_history(self, value):
        if not value:
            raise serializers.ValidationError("历史沟通和商业单据关联必须保留。")
        return value


class ContactEmploymentEventSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)
    actor_employee = EmployeeSummarySerializer(read_only=True)

    class Meta:
        model = CustomerContactEmploymentEvent
        fields = [
            "id", "event_type", "event_type_display", "effective_on", "title",
            "position_title", "department_name", "role_types", "is_primary_contact",
            "notes", "change_data", "actor_employee", "created_at",
        ]


class ContactEmploymentRecordSerializer(serializers.Serializer):
    effective_on = serializers.DateField(default=timezone.localdate)
    title = serializers.CharField(max_length=250, trim_whitespace=True)
    position_title = serializers.CharField(max_length=150, required=False, allow_blank=True)
    department_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role_types = serializers.ListField(
        child=serializers.ChoiceField(choices=ContactRoleType.choices),
        required=False,
    )
    is_primary_contact = serializers.BooleanField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_effective_on(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("任职记录生效日期不能晚于今天。")
        return value

    def validate_role_types(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("联系人角色不能重复。")
        return value


class ContactBulkMarkLeftSerializer(serializers.Serializer):
    contact_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=100)
    reason = serializers.CharField(max_length=500, trim_whitespace=True)

    def validate_contact_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("联系人编号不能重复。")
        return value


class ContactBulkTaskSerializer(serializers.Serializer):
    contact_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=100)
    title = serializers.CharField(max_length=250, trim_whitespace=True)
    description = serializers.CharField(required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=TaskPriority.choices, default=TaskPriority.NORMAL)
    due_at = serializers.DateTimeField()
    assignee_mode = serializers.ChoiceField(choices=["CUSTOMER_OWNER", "SPECIFIC"], default="CUSTOMER_OWNER")
    assignee_employee_id = serializers.PrimaryKeyRelatedField(
        source="assignee_employee",
        queryset=active_department_employees("DEPT_BUSINESS"),
        required=False,
    )

    def validate_contact_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("联系人编号不能重复。")
        return value

    def validate_due_at(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError("任务截止时间必须晚于当前时间。")
        return value

    def validate(self, attrs):
        if attrs["assignee_mode"] == "SPECIFIC" and not attrs.get("assignee_employee"):
            raise serializers.ValidationError({"assignee_employee_id": "指定负责人模式必须选择负责人。"})
        return attrs
