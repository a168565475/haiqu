from apps.access_control.sales_policy import SalesAccessSerializerMixin
from decimal import Decimal
from urllib.parse import urlsplit

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.serializers import EmployeeSummarySerializer
from apps.core.models import country_code_validator, uppercase_code_validator
from apps.organizations.models import Employee
from apps.reference_data.models import ReferenceDictionary

from ..models import (
    CustomerAccount,
    CustomerActivityReview,
    CustomerActivityStatus,
    CustomerAssignment,
    CustomerAttentionReview,
    CustomerBusinessSnapshot,
    CustomerCompanyContactMethod,
    CustomerContact,
    CustomerContactMethod,
    CustomerContactRole,
    CustomerEntityAddress,
    CustomerEntityAddressUsage,
    CustomerGradeReview,
    CustomerSourceAttribution,
    CustomerTag,
    CustomerTagAssignment,
    CustomerInterestedProduct,
    CustomerTransactionEntity,
    CustomerTransactionEntityRole,
    CustomerTypeAssignment,
    CustomerRegion,
    ContactMethodType,
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


class GradeSummarySerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="grade_item.item_code")
    display_name = serializers.CharField(source="grade_item.display_name")

    class Meta:
        model = CustomerGradeReview
        fields = ["id", "item_code", "display_name", "reason", "effective_from", "effective_to"]


class SourceSummarySerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="source_item.item_code")
    display_name = serializers.CharField(source="source_item.display_name")

    class Meta:
        model = CustomerSourceAttribution
        fields = ["id", "item_code", "display_name", "notes", "effective_from", "effective_to"]


class CustomerTypeSummarySerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="type_item.item_code")
    display_name = serializers.CharField(source="type_item.display_name")

    class Meta:
        model = CustomerTypeAssignment
        fields = ["id", "item_code", "display_name", "reason", "effective_from", "effective_to"]


class CustomerTagSummarySerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="customer_tag.id")
    tag_code = serializers.CharField(source="customer_tag.tag_code")
    tag_name = serializers.CharField(source="customer_tag.tag_name")
    color = serializers.CharField(source="customer_tag.color")

    class Meta:
        model = CustomerTagAssignment
        fields = ["id", "tag_code", "tag_name", "color"]


class CustomerRegionSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerRegion
        fields = ["id", "legacy_selector_code", "legacy_tree_code", "region_name", "level"]


class CustomerProfileDictionarySerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = ReferenceDictionary
        fields = ["id", "item_code", "display_name"]


class CustomerInterestedProductSerializer(serializers.ModelSerializer):
    product_item_id = serializers.UUIDField(source="product_item.id", read_only=True)
    item_code = serializers.CharField(source="product_item.item_code", read_only=True)
    display_name = serializers.CharField(source="product_item.display_name", read_only=True)

    class Meta:
        model = CustomerInterestedProduct
        fields = ["id", "product_item_id", "item_code", "display_name"]


class CustomerCompanyContactMethodSerializer(serializers.ModelSerializer):
    method_type_display = serializers.CharField(source="get_method_type_display", read_only=True)

    class Meta:
        model = CustomerCompanyContactMethod
        fields = ["id", "method_type", "method_type_display", "raw_value", "is_primary"]


class CustomerTagCreateSerializer(serializers.ModelSerializer):
    color = serializers.RegexField(
        regex=r"^#[0-9A-Fa-f]{6}$",
        required=False,
        default="#64748B",
        error_messages={"invalid": "标签颜色必须是 #RRGGBB 格式。"},
    )

    class Meta:
        model = CustomerTag
        fields = ["id", "tag_code", "tag_name", "color"]
        read_only_fields = ["id", "tag_code"]

    def validate_tag_name(self, value):
        normalized_name = value.strip()
        if not normalized_name:
            raise serializers.ValidationError("请输入标签名称。")
        if CustomerTag.objects.filter(tag_name__iexact=normalized_name).exists():
            raise serializers.ValidationError("该标签名称已存在。")
        return normalized_name


class ActivitySummarySerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(source="get_activity_status_display", read_only=True)

    class Meta:
        model = CustomerActivityReview
        fields = [
            "id",
            "activity_status",
            "display_name",
            "source_type",
            "reason",
            "formula_version",
            "effective_from",
            "effective_to",
        ]


class CustomerBusinessSnapshotSerializer(serializers.ModelSerializer):
    source_type_display = serializers.CharField(source="get_source_type_display", read_only=True)
    entered_by = EmployeeSummarySerializer(source="entered_by_employee", read_only=True)

    class Meta:
        model = CustomerBusinessSnapshot
        fields = [
            "id",
            "source_type",
            "source_type_display",
            "source_reference",
            "as_of_at",
            "currency_code",
            "customer_total_value",
            "last_12m_order_amount",
            "last_12m_order_count",
            "quote_conversion_rate",
            "credit_limit",
            "credit_used",
            "open_complaint_count",
            "notes",
            "entered_by",
            "is_current",
            "created_at",
        ]
        read_only_fields = ["source_type", "entered_by", "is_current"]

    def validate_as_of_at(self, value):
        if value > timezone.now():
            raise serializers.ValidationError("数据截止时间不能晚于当前时间。")
        return value

    def validate(self, attrs):
        metric_fields = [
            "customer_total_value",
            "last_12m_order_amount",
            "last_12m_order_count",
            "quote_conversion_rate",
            "credit_limit",
            "credit_used",
            "open_complaint_count",
        ]
        if not any(attrs.get(field_name) is not None for field_name in metric_fields):
            raise serializers.ValidationError({"detail": "请至少填写一个业务指标。"})
        errors = {}
        for field_name in [
            "customer_total_value",
            "last_12m_order_amount",
            "credit_limit",
            "credit_used",
        ]:
            value = attrs.get(field_name)
            if value is not None and value < 0:
                errors[field_name] = "金额不能为负数。"
        conversion_rate = attrs.get("quote_conversion_rate")
        if conversion_rate is not None and not 0 <= conversion_rate <= 100:
            errors["quote_conversion_rate"] = "报价转化率必须在 0 到 100 之间。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class CustomerListSerializer(SalesAccessSerializerMixin, serializers.ModelSerializer):
    primary_owner = serializers.SerializerMethodField()
    attention_level = serializers.SerializerMethodField()
    customer_grade = serializers.SerializerMethodField()
    first_source = serializers.SerializerMethodField()
    latest_source = serializers.SerializerMethodField()
    customer_types = serializers.SerializerMethodField()
    customer_tags = serializers.SerializerMethodField()
    activity = serializers.SerializerMethodField()
    lifecycle_stage_display = serializers.CharField(source="get_lifecycle_stage_display", read_only=True)
    last_contact_at = serializers.DateTimeField(read_only=True, allow_null=True)
    next_follow_up_at = serializers.DateTimeField(read_only=True, allow_null=True)
    customer_value = serializers.SerializerMethodField()
    lifetime_sales_amount = serializers.SerializerMethodField()
    lifetime_sales_order_count = serializers.SerializerMethodField()
    last_12m_sales_amount = serializers.SerializerMethodField()
    last_12m_sales_order_count = serializers.SerializerMethodField()
    quotation_conversion_rate = serializers.SerializerMethodField()
    recent_order = serializers.SerializerMethodField()
    primary_region = CustomerRegionSummarySerializer(read_only=True)
    secondary_region = CustomerRegionSummarySerializer(read_only=True)
    industry = CustomerProfileDictionarySerializer(source="industry_item", read_only=True)
    recorded_by = EmployeeSummarySerializer(source="recorded_by_employee", read_only=True)

    class Meta:
        model = CustomerAccount
        fields = [
            "allowed_permissions",
            "id",
            "account_code",
            "account_name",
            "english_name",
            "short_name",
            "lifecycle_stage",
            "lifecycle_stage_display",
            "primary_country_code",
            "primary_region",
            "secondary_region",
            "industry",
            "inquiry_keywords",
            "recorded_by",
            "recorded_at",
            "primary_owner",
            "attention_level",
            "customer_grade",
            "first_source",
            "latest_source",
            "customer_types",
            "customer_tags",
            "activity",
            "last_contact_at",
            "next_follow_up_at",
            "customer_value",
            "lifetime_sales_amount",
            "lifetime_sales_order_count",
            "last_12m_sales_amount",
            "last_12m_sales_order_count",
            "quotation_conversion_rate",
            "recent_order",
            "archived_at",
            "created_at",
            "updated_at",
        ]

    def _summary_data(self, serializer_class, instance):
        # 每次请求复用字段定义；不复用 .data，避免把上一行数据带到下一行。
        if not hasattr(self, "_summary_serializers"):
            self._summary_serializers = {}
        if serializer_class not in self._summary_serializers:
            self._summary_serializers[serializer_class] = serializer_class(context=self.context)
        return self._summary_serializers[serializer_class].to_representation(instance)

    @extend_schema_field(EmployeeSummarySerializer(allow_null=True))
    def get_primary_owner(self, obj):
        for assignment in getattr(obj, "current_assignments", []):
            if assignment.assignment_role == "PRIMARY_OWNER":
                return self._summary_data(EmployeeSummarySerializer, assignment.employee)
        return None

    @extend_schema_field(AttentionSummarySerializer(allow_null=True))
    def get_attention_level(self, obj):
        reviews = getattr(obj, "current_attention_reviews", [])
        return self._summary_data(AttentionSummarySerializer, reviews[0]) if reviews else None

    @extend_schema_field(GradeSummarySerializer(allow_null=True))
    def get_customer_grade(self, obj):
        reviews = getattr(obj, "current_grade_reviews", [])
        return self._summary_data(GradeSummarySerializer, reviews[0]) if reviews else None

    @extend_schema_field(SourceSummarySerializer(allow_null=True))
    def get_first_source(self, obj):
        source_history = getattr(obj, "source_history", [])
        return self._summary_data(SourceSummarySerializer, source_history[0]) if source_history else None

    @extend_schema_field(SourceSummarySerializer(allow_null=True))
    def get_latest_source(self, obj):
        sources = getattr(obj, "current_source_attributions", [])
        return self._summary_data(SourceSummarySerializer, sources[0]) if sources else None

    @extend_schema_field(CustomerTypeSummarySerializer(many=True))
    def get_customer_types(self, obj):
        return [self._summary_data(CustomerTypeSummarySerializer, item) for item in getattr(obj, "current_type_assignments", [])]

    @extend_schema_field(CustomerTagSummarySerializer(many=True))
    def get_customer_tags(self, obj):
        return [self._summary_data(CustomerTagSummarySerializer, item) for item in getattr(obj, "current_tag_assignments", [])]

    @extend_schema_field(ActivitySummarySerializer(allow_null=True))
    def get_activity(self, obj):
        reviews = getattr(obj, "current_activity_reviews", [])
        return self._summary_data(ActivitySummarySerializer, reviews[0]) if reviews else None

    @extend_schema_field(CustomerBusinessSnapshotSerializer(allow_null=True))
    def get_customer_value(self, obj):
        snapshots = getattr(obj, "current_business_snapshots", [])
        return self._summary_data(CustomerBusinessSnapshotSerializer, snapshots[0]) if snapshots else None

    @staticmethod
    def _money_from_summary(obj, attribute_name):
        summary = getattr(obj, attribute_name, None) or {}
        amount = summary.get("amount")
        if amount is None:
            return None
        return format(Decimal(str(amount)).quantize(Decimal("0.0001")), "f")

    @extend_schema_field(serializers.DecimalField(max_digits=32, decimal_places=4, allow_null=True))
    def get_lifetime_sales_amount(self, obj):
        return self._money_from_summary(obj, "lifetime_sales_summary")

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_lifetime_sales_order_count(self, obj):
        summary = getattr(obj, "lifetime_sales_summary", None) or {}
        return summary.get("order_count")

    @extend_schema_field(serializers.DecimalField(max_digits=32, decimal_places=4, allow_null=True))
    def get_last_12m_sales_amount(self, obj):
        return self._money_from_summary(obj, "last_12m_sales_summary")

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_last_12m_sales_order_count(self, obj):
        summary = getattr(obj, "last_12m_sales_summary", None) or {}
        return summary.get("order_count")

    @extend_schema_field(serializers.DecimalField(max_digits=7, decimal_places=2, allow_null=True))
    def get_quotation_conversion_rate(self, obj):
        summary = getattr(obj, "quotation_conversion_summary", None) or {}
        total = int(summary.get("quotation_count") or 0)
        accepted = int(summary.get("accepted_count") or 0)
        if total <= 0:
            return None
        rate = Decimal(accepted * 100) / Decimal(total)
        return format(rate.quantize(Decimal("0.01")), "f")

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "order_number": {"type": "string"},
                "order_date": {"type": "string", "format": "date"},
                "status": {"type": "string"},
                "status_display": {"type": "string"},
                "currency_code": {"type": "string"},
                "total_amount": {"type": "string"},
            },
        }
    )
    def get_recent_order(self, obj):
        summary = getattr(obj, "recent_order_summary", None) or {}
        if not summary.get("id"):
            return None
        from apps.sales_orders.models import SalesOrderStatus

        status = summary.get("status") or ""
        return {
            "id": summary["id"],
            "order_number": summary.get("order_number") or "",
            "order_date": summary.get("order_date"),
            "status": status,
            "status_display": dict(SalesOrderStatus.choices).get(status, status),
            "currency_code": summary.get("currency_code") or "",
            "total_amount": summary.get("total_amount"),
        }


class CustomerDetailSerializer(CustomerListSerializer):
    current_assignments = serializers.SerializerMethodField()
    business_snapshot = serializers.SerializerMethodField()
    interested_products = CustomerInterestedProductSerializer(many=True, read_only=True)
    company_contact_methods = CustomerCompanyContactMethodSerializer(many=True, read_only=True)

    class Meta(CustomerListSerializer.Meta):
        fields = CustomerListSerializer.Meta.fields + [
            "primary_website_url",
            "source_system",
            "external_id",
            "notes",
            "legacy_source_data",
            "archive_reason",
            "current_assignments",
            "business_snapshot",
            "interested_products",
            "company_contact_methods",
        ]

    @extend_schema_field(CustomerAssignmentSerializer(many=True))
    def get_current_assignments(self, obj):
        return CustomerAssignmentSerializer(getattr(obj, "current_assignments", []), many=True).data

    @extend_schema_field(CustomerBusinessSnapshotSerializer(allow_null=True))
    def get_business_snapshot(self, obj):
        snapshots = getattr(obj, "current_business_snapshots", [])
        return CustomerBusinessSnapshotSerializer(snapshots[0]).data if snapshots else None


class CustomerCreateSerializer(serializers.ModelSerializer):
    primary_website_url = serializers.CharField(required=False, allow_blank=True, max_length=500)
    primary_owner_employee_id = serializers.PrimaryKeyRelatedField(
        source="primary_owner_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
        write_only=True,
        required=False,
    )
    customer_source_item_id = serializers.PrimaryKeyRelatedField(
        source="customer_source_item",
        queryset=ReferenceDictionary.objects.filter(
            category_code="CUSTOMER_SOURCE", status="ACTIVE", archived_at__isnull=True
        ),
        write_only=True,
    )
    customer_grade_item_id = serializers.PrimaryKeyRelatedField(
        source="customer_grade_item",
        queryset=ReferenceDictionary.objects.filter(
            category_code="CUSTOMER_GRADE", status="ACTIVE", archived_at__isnull=True
        ),
        write_only=True,
        required=False,
        allow_null=True,
    )
    customer_type_item_ids = serializers.PrimaryKeyRelatedField(
        source="customer_type_items",
        queryset=ReferenceDictionary.objects.filter(
            category_code="CUSTOMER_TYPE", status="ACTIVE", archived_at__isnull=True
        ),
        many=True,
        write_only=True,
        required=False,
    )
    customer_tag_ids = serializers.PrimaryKeyRelatedField(
        source="customer_tags",
        queryset=CustomerTag.objects.filter(archived_at__isnull=True),
        many=True,
        write_only=True,
        required=False,
    )
    primary_region_id = serializers.PrimaryKeyRelatedField(
        source="primary_region",
        queryset=CustomerRegion.objects.filter(level=CustomerRegion.Level.PRIMARY, is_active=True, archived_at__isnull=True),
        write_only=True,
        required=False,
        allow_null=True,
    )
    secondary_region_id = serializers.PrimaryKeyRelatedField(
        source="secondary_region",
        queryset=CustomerRegion.objects.filter(level=CustomerRegion.Level.SECONDARY, is_active=True, archived_at__isnull=True),
        write_only=True,
        required=False,
        allow_null=True,
    )
    industry_item_id = serializers.PrimaryKeyRelatedField(
        source="industry_item",
        queryset=ReferenceDictionary.objects.filter(
            category_code="CUSTOMER_INDUSTRY", status="ACTIVE", archived_at__isnull=True
        ),
        write_only=True,
        required=False,
        allow_null=True,
    )
    interested_product_item_ids = serializers.PrimaryKeyRelatedField(
        source="interested_product_items",
        queryset=ReferenceDictionary.objects.filter(
            category_code="CUSTOMER_INTERESTED_PRODUCT", status="ACTIVE", archived_at__isnull=True
        ),
        many=True,
        write_only=True,
        required=False,
    )
    contact_name = serializers.CharField(max_length=150, required=False, allow_blank=True, write_only=True)
    contact_method_type = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        write_only=True,
    )
    contact_method_value = serializers.CharField(max_length=255, required=False, allow_blank=True, write_only=True)
    primary_country_code = serializers.CharField(
        min_length=2,
        max_length=2,
        validators=[country_code_validator],
        required=False,
        allow_blank=True,
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
            "primary_region_id",
            "secondary_region_id",
            "primary_website_url",
            "inquiry_keywords",
            "industry_item_id",
            "interested_product_item_ids",
            "source_system",
            "external_id",
            "notes",
            "primary_owner_employee_id",
            "customer_source_item_id",
            "customer_grade_item_id",
            "customer_type_item_ids",
            "customer_tag_ids",
            "contact_name",
            "contact_method_type",
            "contact_method_value",
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
        contact_name = attrs.get("contact_name", "").strip()
        method_type = attrs.get("contact_method_type", "")
        method_value = attrs.get("contact_method_value", "").strip()
        if method_type or method_value:
            if not contact_name:
                raise serializers.ValidationError({"contact_name": "填写联系方式时必须填写联系人姓名。"})
            if not method_type or not method_value:
                raise serializers.ValidationError(
                    {"contact_method_value": "联系方式类型和内容必须同时填写。"}
                )
        if len({item.pk for item in attrs.get("customer_type_items", [])}) != len(
            attrs.get("customer_type_items", [])
        ):
            raise serializers.ValidationError({"customer_type_item_ids": "客户类型不能重复。"})
        if len({item.pk for item in attrs.get("customer_tags", [])}) != len(attrs.get("customer_tags", [])):
            raise serializers.ValidationError({"customer_tag_ids": "客户标签不能重复。"})
        product_items = attrs.get("interested_product_items", [])
        if len({item.pk for item in product_items}) != len(product_items):
            raise serializers.ValidationError({"interested_product_item_ids": "感兴趣产品不能重复。"})
        primary_region = attrs.get("primary_region")
        secondary_region = attrs.get("secondary_region")
        if secondary_region and not primary_region:
            primary_region = secondary_region.parent
            attrs["primary_region"] = primary_region
        if secondary_region and secondary_region.parent_id != primary_region.pk:
            raise serializers.ValidationError({"secondary_region_id": "二级地区不属于所选一级地区。"})
        if secondary_region and secondary_region.country_id:
            attrs["primary_country_code"] = secondary_region.country.code
        elif primary_region and not secondary_region:
            attrs["primary_country_code"] = ""
        return attrs

    def validate_primary_website_url(self, value):
        return normalize_website_url(value)

    def validate_contact_method_type(self, value):
        if value and value not in ContactMethodType.values:
            raise serializers.ValidationError("不支持的联系方式类型。")
        return value


class CustomerUpdateSerializer(serializers.ModelSerializer):
    primary_website_url = serializers.CharField(required=False, allow_blank=True, max_length=500)
    primary_region_id = serializers.PrimaryKeyRelatedField(
        source="primary_region",
        queryset=CustomerRegion.objects.filter(level=CustomerRegion.Level.PRIMARY, is_active=True, archived_at__isnull=True),
        write_only=True,
        required=False,
        allow_null=True,
    )
    secondary_region_id = serializers.PrimaryKeyRelatedField(
        source="secondary_region",
        queryset=CustomerRegion.objects.filter(level=CustomerRegion.Level.SECONDARY, is_active=True, archived_at__isnull=True),
        write_only=True,
        required=False,
        allow_null=True,
    )
    industry_item_id = serializers.PrimaryKeyRelatedField(
        source="industry_item",
        queryset=ReferenceDictionary.objects.filter(category_code="CUSTOMER_INDUSTRY", status="ACTIVE", archived_at__isnull=True),
        write_only=True,
        required=False,
        allow_null=True,
    )
    interested_product_item_ids = serializers.PrimaryKeyRelatedField(
        source="interested_product_items",
        queryset=ReferenceDictionary.objects.filter(
            category_code="CUSTOMER_INTERESTED_PRODUCT", status="ACTIVE", archived_at__isnull=True
        ),
        many=True,
        write_only=True,
        required=False,
    )

    class Meta:
        model = CustomerAccount
        fields = [
            "account_name",
            "english_name",
            "short_name",
            "lifecycle_stage",
            "primary_country_code",
            "primary_region_id",
            "secondary_region_id",
            "primary_website_url",
            "inquiry_keywords",
            "industry_item_id",
            "interested_product_item_ids",
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
        product_items = attrs.get("interested_product_items", [])
        if len({item.pk for item in product_items}) != len(product_items):
            raise serializers.ValidationError({"interested_product_item_ids": "感兴趣产品不能重复。"})
        primary_region = attrs.get("primary_region", instance.primary_region)
        secondary_region = attrs.get("secondary_region", instance.secondary_region)
        if secondary_region and (not primary_region or secondary_region.parent_id != primary_region.pk):
            raise serializers.ValidationError({"secondary_region_id": "二级地区不属于所选一级地区。"})
        if secondary_region and secondary_region.country_id:
            attrs["primary_country_code"] = secondary_region.country.code
        elif "primary_region" in attrs and "secondary_region" not in attrs:
            attrs["primary_country_code"] = ""
        return attrs

    def validate_primary_website_url(self, value):
        return normalize_website_url(value)


def normalize_website_url(value):
    value = value.strip()
    if not value:
        return ""
    normalized = value if "://" in value else f"https://{value}"
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise serializers.ValidationError("请输入有效的网站地址或域名。")
    return normalized


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
            "is_key_contact",
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
    duplicate_acknowledged = serializers.BooleanField(required=False, default=False, write_only=True)

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
            "duplicate_acknowledged",
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


class GradeSetSerializer(serializers.Serializer):
    grade_item_id = serializers.PrimaryKeyRelatedField(
        source="grade_item",
        queryset=ReferenceDictionary.objects.filter(
            category_code="CUSTOMER_GRADE",
            status="ACTIVE",
            archived_at__isnull=True,
        ),
    )
    reason = serializers.CharField(trim_whitespace=True)


class SourceSetSerializer(serializers.Serializer):
    source_item_id = serializers.PrimaryKeyRelatedField(
        source="source_item",
        queryset=ReferenceDictionary.objects.filter(
            category_code="CUSTOMER_SOURCE",
            status="ACTIVE",
            archived_at__isnull=True,
        ),
    )
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ActivitySetSerializer(serializers.Serializer):
    activity_status = serializers.ChoiceField(choices=CustomerActivityStatus.choices)
    reason = serializers.CharField(trim_whitespace=True)


class ClassificationSetSerializer(serializers.Serializer):
    customer_type_item_ids = serializers.PrimaryKeyRelatedField(
        source="customer_type_items",
        queryset=ReferenceDictionary.objects.filter(
            category_code="CUSTOMER_TYPE",
            status="ACTIVE",
            archived_at__isnull=True,
        ),
        many=True,
        required=False,
    )
    customer_tag_ids = serializers.PrimaryKeyRelatedField(
        source="customer_tags",
        queryset=CustomerTag.objects.filter(archived_at__isnull=True),
        many=True,
        required=False,
    )
    reason = serializers.CharField(trim_whitespace=True)

    def validate(self, attrs):
        if "customer_type_items" not in attrs and "customer_tags" not in attrs:
            raise serializers.ValidationError({"detail": "客户类型和标签至少提交一项。"})
        if len({item.pk for item in attrs.get("customer_type_items", [])}) != len(
            attrs.get("customer_type_items", [])
        ):
            raise serializers.ValidationError({"customer_type_item_ids": "客户类型不能重复。"})
        if len({item.pk for item in attrs.get("customer_tags", [])}) != len(attrs.get("customer_tags", [])):
            raise serializers.ValidationError({"customer_tag_ids": "客户标签不能重复。"})
        return attrs


class DuplicateCheckQuerySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=250, required=False, allow_blank=True)
    website = serializers.CharField(max_length=500, required=False, allow_blank=True)
    country_code = serializers.CharField(
        min_length=2,
        max_length=2,
        required=False,
        allow_blank=True,
        validators=[country_code_validator],
    )
    exclude_customer_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        name = attrs.get("name", "").strip()
        website = attrs.get("website", "").strip()
        if not name and not website:
            raise serializers.ValidationError({"detail": "客户名称和网站至少填写一项。"})
        if name and len(name) < 2:
            raise serializers.ValidationError({"name": "客户名称至少输入 2 个字符。"})
        if website:
            attrs["website"] = normalize_website_url(website)
        attrs["name"] = name
        return attrs


class CustomerOptionQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=100, required=False, allow_blank=True)


class CustomerBulkTagSerializer(serializers.Serializer):
    customer_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=100
    )
    customer_tag_ids = serializers.PrimaryKeyRelatedField(
        source="customer_tags",
        queryset=CustomerTag.objects.filter(archived_at__isnull=True),
        many=True,
    )
    reason = serializers.CharField(min_length=2, max_length=500, trim_whitespace=True)

    def validate_customer_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("客户不能重复。")
        return value

    def validate_customer_tags(self, value):
        if not value:
            raise serializers.ValidationError("请至少选择一个标签。")
        if len({item.pk for item in value}) != len(value):
            raise serializers.ValidationError("标签不能重复。")
        return value
