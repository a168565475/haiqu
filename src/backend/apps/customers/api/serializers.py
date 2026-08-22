from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.serializers import EmployeeSummarySerializer
from apps.core.models import country_code_validator, uppercase_code_validator
from apps.organizations.models import Employee
from apps.reference_data.models import ReferenceDictionary

from ..models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerAttentionReview,
    CustomerContact,
    CustomerContactMethod,
    CustomerContactRole,
    CustomerEntityAddress,
    CustomerEntityAddressUsage,
    CustomerTransactionEntity,
    CustomerTransactionEntityRole,
)


class CustomerAssignmentSerializer(serializers.ModelSerializer):
    employee = EmployeeSummarySerializer(read_only=True)

    class Meta:
        model = CustomerAssignment
        fields = [
            "id",
            "employee",
            "assignment_role",
            "effective_from",
            "effective_to",
            "reason",
            "created_at",
        ]


class AttentionSummarySerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="attention_level_item.item_code")
    display_name = serializers.CharField(source="attention_level_item.display_name")

    class Meta:
        model = CustomerAttentionReview
        fields = ["id", "item_code", "display_name", "reason", "effective_from", "effective_to"]


class CustomerListSerializer(serializers.ModelSerializer):
    primary_owner = serializers.SerializerMethodField()
    attention_level = serializers.SerializerMethodField()
    lifecycle_stage_display = serializers.CharField(source="get_lifecycle_stage_display", read_only=True)

    class Meta:
        model = CustomerAccount
        fields = [
            "id",
            "account_code",
            "account_name",
            "english_name",
            "short_name",
            "lifecycle_stage",
            "lifecycle_stage_display",
            "primary_country_code",
            "primary_owner",
            "attention_level",
            "archived_at",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(EmployeeSummarySerializer(allow_null=True))
    def get_primary_owner(self, obj):
        for assignment in getattr(obj, "current_assignments", []):
            if assignment.assignment_role == "PRIMARY_OWNER":
                return EmployeeSummarySerializer(assignment.employee).data
        return None

    @extend_schema_field(AttentionSummarySerializer(allow_null=True))
    def get_attention_level(self, obj):
        reviews = getattr(obj, "current_attention_reviews", [])
        return AttentionSummarySerializer(reviews[0]).data if reviews else None


class CustomerDetailSerializer(CustomerListSerializer):
    current_assignments = serializers.SerializerMethodField()

    class Meta(CustomerListSerializer.Meta):
        fields = CustomerListSerializer.Meta.fields + [
            "primary_website_url",
            "source_system",
            "external_id",
            "notes",
            "archive_reason",
            "current_assignments",
        ]

    @extend_schema_field(CustomerAssignmentSerializer(many=True))
    def get_current_assignments(self, obj):
        return CustomerAssignmentSerializer(getattr(obj, "current_assignments", []), many=True).data


class CustomerCreateSerializer(serializers.ModelSerializer):
    primary_owner_employee_id = serializers.PrimaryKeyRelatedField(
        source="primary_owner_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
        write_only=True,
    )
    primary_country_code = serializers.CharField(
        min_length=2,
        max_length=2,
        validators=[country_code_validator],
    )
    source_system = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[uppercase_code_validator],
    )
    external_id = serializers.CharField(required=False, allow_blank=True, max_length=150)

    class Meta:
        model = CustomerAccount
        fields = [
            "account_name",
            "english_name",
            "short_name",
            "lifecycle_stage",
            "primary_country_code",
            "primary_website_url",
            "source_system",
            "external_id",
            "notes",
            "primary_owner_employee_id",
        ]
        validators = []

    def validate(self, attrs):
        source_system = attrs.get("source_system", "")
        external_id = attrs.get("external_id", "")
        if bool(source_system) != bool(external_id):
            raise serializers.ValidationError(
                {"source_system": "来源系统和外部编号必须同时填写或同时留空。"}
            )
        if source_system and CustomerAccount.objects.filter(
            source_system=source_system,
            external_id=external_id,
        ).exists():
            raise serializers.ValidationError(
                {"external_id": "该来源系统下的外部编号已经存在。"}
            )
        return attrs


class CustomerUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAccount
        fields = [
            "account_name",
            "english_name",
            "short_name",
            "lifecycle_stage",
            "primary_country_code",
            "primary_website_url",
            "source_system",
            "external_id",
            "notes",
        ]
        validators = []

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        instance = self.instance
        source_system = attrs.get("source_system", instance.source_system)
        external_id = attrs.get("external_id", instance.external_id)
        if bool(source_system) != bool(external_id):
            raise serializers.ValidationError(
                {"source_system": "来源系统和外部编号必须同时填写或同时留空。"}
            )
        duplicate_query = CustomerAccount.objects.filter(
            source_system=source_system,
            external_id=external_id,
        )
        if instance is not None:
            duplicate_query = duplicate_query.exclude(pk=instance.pk)
        if source_system and duplicate_query.exists():
            raise serializers.ValidationError(
                {"external_id": "该来源系统下的外部编号已经存在。"}
            )
        return attrs


class ArchiveSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class CustomerTransactionEntitySerializer(serializers.ModelSerializer):
    entity_type_display = serializers.CharField(source="get_entity_type_display", read_only=True)

    class Meta:
        model = CustomerTransactionEntity
        fields = [
            "id",
            "customer_account",
            "entity_code",
            "entity_type",
            "entity_type_display",
            "legal_name",
            "english_legal_name",
            "registration_country_code",
            "registration_number",
            "tax_country_code",
            "tax_identifier",
            "notes",
            "archived_at",
            "archive_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["customer_account", "archived_at", "archive_reason"]


class EntityRoleSerializer(serializers.ModelSerializer):
    effective_from = serializers.DateTimeField(required=False)

    class Meta:
        model = CustomerTransactionEntityRole
        fields = ["id", "transaction_entity", "role_type", "effective_from", "effective_to", "created_at"]
        read_only_fields = ["transaction_entity", "effective_to"]


class CustomerAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerEntityAddress
        fields = [
            "id",
            "transaction_entity",
            "address_code",
            "label",
            "country_code",
            "state_province",
            "city",
            "postal_code",
            "address_line1",
            "address_line2",
            "recipient_name",
            "recipient_phone",
            "is_verified",
            "archived_at",
            "archive_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["transaction_entity", "archived_at", "archive_reason"]


class AddressUsageSerializer(serializers.ModelSerializer):
    effective_from = serializers.DateTimeField(required=False)

    class Meta:
        model = CustomerEntityAddressUsage
        fields = ["id", "entity_address", "usage_type", "effective_from", "effective_to", "created_at"]
        read_only_fields = ["entity_address", "effective_to"]


class CustomerContactSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = CustomerContact
        fields = [
            "id",
            "customer_account",
            "transaction_entity",
            "source_contact",
            "display_name",
            "position_title",
            "status",
            "status_display",
            "notes",
            "archived_at",
            "archive_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["customer_account", "archived_at", "archive_reason"]

    def validate(self, attrs):
        customer = self.context.get("customer_account")
        if customer is None and self.instance is not None:
            customer = self.instance.customer_account
        entity = attrs.get("transaction_entity", getattr(self.instance, "transaction_entity", None))
        source = attrs.get("source_contact", getattr(self.instance, "source_contact", None))
        errors = {}
        if entity and customer and entity.customer_account_id != customer.id:
            errors["transaction_entity"] = "交易主体必须属于当前客户。"
        elif entity and entity.archived_at is not None:
            errors["transaction_entity"] = "不能关联已归档的交易主体。"
        if source and customer and source.customer_account_id != customer.id:
            errors["source_contact"] = "来源联系人必须属于当前客户。"
        elif source and source.archived_at is not None:
            errors["source_contact"] = "不能关联已归档的来源联系人。"
        if source and self.instance is not None and source.pk == self.instance.pk:
            errors["source_contact"] = "来源联系人不能是联系人自己。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class ContactMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerContactMethod
        fields = [
            "id",
            "customer_contact",
            "method_type",
            "raw_value",
            "normalized_value",
            "normalization_version",
            "normalized_at",
            "is_primary",
            "is_preferred",
            "verification_status",
            "archived_at",
            "archive_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "customer_contact",
            "normalized_value",
            "normalization_version",
            "normalized_at",
            "archived_at",
            "archive_reason",
        ]


class ContactRoleSerializer(serializers.ModelSerializer):
    effective_from = serializers.DateTimeField(required=False)

    class Meta:
        model = CustomerContactRole
        fields = [
            "id",
            "customer_contact",
            "role_type",
            "effective_from",
            "effective_to",
            "notes",
            "created_at",
        ]
        read_only_fields = ["customer_contact", "effective_to"]


class CollaboratorCreateSerializer(serializers.Serializer):
    employee_id = serializers.PrimaryKeyRelatedField(
        source="employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    effective_from = serializers.DateTimeField(required=False)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class AttentionSetSerializer(serializers.Serializer):
    attention_level_item_id = serializers.PrimaryKeyRelatedField(
        source="attention_level_item",
        queryset=ReferenceDictionary.objects.filter(
            category_code="CUSTOMER_ATTENTION",
            status="ACTIVE",
            archived_at__isnull=True,
        ),
    )
    reason = serializers.CharField(trim_whitespace=True)
