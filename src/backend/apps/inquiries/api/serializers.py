from apps.access_control.sales_sources import require_file
from apps.organizations.selectors import active_department_employees
from apps.access_control import sales_policy
from apps.access_control.sales_policy import SalesAccessSerializerMixin
from functools import cached_property
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.models import currency_code_validator, uppercase_code_validator
from apps.core.serializers import EmployeeSummarySerializer
from apps.customers.models import CustomerAccount, CustomerContact, CustomerTransactionEntity
from apps.customers.selectors import accessible_customers
from apps.files.models import BusinessFile, FileScanStatus, USABLE_FILE_SCAN_STATUSES
from apps.organizations.models import Employee
from apps.products.models import ProductInformation, ProductStatus
from apps.reference_data.models import (
    Currency,
    Incoterm,
    ProductCategory,
    ProductColor,
    ProductItemType,
    ProductionUnit,
    ReferenceDictionary,
    ReferenceStatus,
)
from apps.reference_data.services import (
    published_dictionary_code_is_active,
    published_dictionary_options,
)

from ..figma_demo import demo_override, is_figma_demo_inquiry, is_figma_demo_request
from ..models import Inquiry, InquiryAssignmentHistory, InquiryFileLink, InquiryItem, InquiryPriority, InquirySlaLink
from ..rich_text import rich_text_plain_text, sanitize_rich_text
from ..selectors import inquiry_display_stage, inquiry_product_amount, inquiry_sla_summary


class InquiryProductImageUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class InquiryProductImageMetadataSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    original_name = serializers.CharField()
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField(min_value=0)
    scan_status = serializers.ChoiceField(choices=FileScanStatus.choices)


class InquiryItemSerializer(serializers.ModelSerializer):
    line_number = serializers.IntegerField(required=False, min_value=1)
    product_category_name = serializers.CharField(source="product_category.category_name", read_only=True, default="")
    product_id = serializers.PrimaryKeyRelatedField(
        source="product",
        queryset=ProductInformation.objects.filter(status=ProductStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    product_category_id = serializers.PrimaryKeyRelatedField(
        source="product_category",
        queryset=ProductCategory.objects.filter(item_type=ProductItemType.FINISHED, status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    product_unit_id = serializers.PrimaryKeyRelatedField(
        source="product_unit",
        queryset=ProductionUnit.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    product_color_id = serializers.PrimaryKeyRelatedField(
        source="product_color",
        queryset=ProductColor.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    product_image_id = serializers.PrimaryKeyRelatedField(
        source="product_image",
        read_only=True,
        allow_null=True,
    )
    product_image = serializers.SerializerMethodField()
    unit_code = serializers.CharField(max_length=30)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    target_unit_price = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0"),
        required=False,
        allow_null=True,
    )
    target_currency_code = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=3,
        validators=[currency_code_validator],
    )

    class Meta:
        model = InquiryItem
        fields = [
            "id",
            "line_number",
            "product_id",
            "product_category_id",
            "product_category_name",
            "product_unit_id",
            "product_color_id",
            "product_image_id",
            "product_image",
            "product_description",
            "specification",
            "color",
            "material",
            "quantity",
            "unit_code",
            "target_unit_price",
            "target_currency_code",
            "expected_date",
            "product_match_status",
            "notes",
            "product_number_snapshot",
            "product_code_snapshot",
            "item_number_snapshot",
            "customer_product_name_snapshot",
            "customer_specification_snapshot",
            "customer_unit_code_snapshot",
            "customer_color_snapshot",
            "customer_material_snapshot",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "product_number_snapshot",
            "product_code_snapshot",
            "item_number_snapshot",
            "customer_product_name_snapshot",
            "customer_specification_snapshot",
            "customer_unit_code_snapshot",
            "customer_color_snapshot",
            "customer_material_snapshot",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._available_relation_querysets = {
            name: self.fields[name].queryset
            for name in ("product_id", "product_category_id", "product_unit_id", "product_color_id")
        }
        self._saved_item = None

    def to_internal_value(self, data):
        current = self.instance if isinstance(self.instance, InquiryItem) else None
        inquiry = getattr(self.root, "instance", None)
        if current is None and isinstance(inquiry, Inquiry) and isinstance(data, dict) and data.get("id"):
            try:
                item_id = self.fields["id"].run_validation(data["id"])
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({"id": exc.detail}) from exc
            current = InquiryItem.objects.filter(inquiry=inquiry, pk=item_id).select_related(
                "product", "product_unit", "product_color",
            ).first()
        self._saved_item = current
        for name, available in self._available_relation_querysets.items():
            # 只允许本条已保存的关联继续使用；每条明细重置，避免向新明细放开停用项。
            queryset = available.all()
            saved_id = getattr(current, name, None)
            if saved_id is not None:
                queryset = queryset | queryset.model.objects.filter(pk=saved_id)
            self.fields[name].queryset = queryset
        return super().to_internal_value(data)

    def _validate_reference_codes(self, attrs, current=None):
        target_currency = attrs.get(
            "target_currency_code",
            getattr(current, "target_currency_code", ""),
        )
        current_currency = getattr(current, "target_currency_code", "")
        if (
            target_currency
            and target_currency != current_currency
            and not Currency.objects.filter(
                code=target_currency,
                status=ReferenceStatus.ACTIVE,
                archived_at__isnull=True,
            ).exists()
        ):
            raise serializers.ValidationError(
                {"target_currency_code": "目标价币种不存在、已停用或已归档。"}
            )
        return attrs

    @extend_schema_field(InquiryProductImageMetadataSerializer(allow_null=True))
    def get_product_image(self, item) -> dict | None:
        image = item.product_image
        if image is None:
            return None
        return {
            "id": str(image.pk),
            "original_name": image.original_name,
            "content_type": image.content_type,
            "size_bytes": image.size_bytes,
            "scan_status": image.scan_status,
        }

    def _validate_item_rules(self, attrs, current=None):
        attrs = self._validate_reference_codes(attrs, current)
        errors = {}
        unit = attrs.get("product_unit", getattr(current, "product_unit", None))
        unit_text = attrs.get("unit_code", getattr(current, "unit_code", ""))
        unchanged_unit = current is not None and unit is not None and current.product_unit_id == unit.pk and unit_text == current.unit_code
        if unit is not None and not unchanged_unit:
            if unit.status != ReferenceStatus.ACTIVE or unit.archived_at is not None:
                errors["product_unit_id"] = "单位已停用或归档，只能保留原关联及原文字。"
            elif unit_text != unit.unit_code:
                errors["product_unit_id"] = "单位关联与填写内容不一致；手填单位请清除维护项关联。"
        color = attrs.get("product_color", getattr(current, "product_color", None))
        color_text = attrs.get("color", getattr(current, "color", ""))
        unchanged_color = current is not None and color is not None and current.product_color_id == color.pk and color_text == current.color
        if color is not None and not unchanged_color:
            if color.status != ReferenceStatus.ACTIVE or color.archived_at is not None:
                errors["product_color_id"] = "颜色已停用或归档，只能保留原关联及原文字。"
            elif color_text != color.color_name:
                errors["product_color_id"] = "颜色关联与填写内容不一致；手填颜色请清除维护项关联。"
        product = attrs.get("product", getattr(current, "product", None))
        if product is not None:
            unchanged_link = current is not None and current.product_id == product.pk
            if not unchanged_link and (
                product.category.status != ReferenceStatus.ACTIVE
                or product.category.archived_at is not None
                or product.unit.status != ReferenceStatus.ACTIVE
                or product.unit.archived_at is not None
            ):
                errors["product_id"] = "产品的类别或单位已停用或归档，不能建立新的产品关联。"
            category_id = current.product_category_id if unchanged_link else product.category_id
            unit_id = current.product_unit_id if unchanged_link else product.unit_id
            product_name = current.product_description if unchanged_link else product.product_name
            specification = current.specification if unchanged_link else product.specification
            unit_code = current.unit_code if unchanged_link else product.unit.unit_code
            category = attrs.get("product_category")
            if "product_category" in attrs and (category is None or category.pk != category_id):
                errors["product_id"] = "产品类别、产品主档不匹配；如需改规格或单位，请先解除产品关联。"
            unit = attrs.get("product_unit")
            if "product_unit" in attrs and (unit is None or unit.pk != unit_id):
                errors["product_id"] = "产品单位、产品主档不匹配；如需改单位，请先解除产品关联。"
            if attrs.get("product_description", getattr(current, "product_description", product_name)).strip() != product_name:
                errors["product_id"] = "已关联产品不能直接改名；请解除关联后作为定制产品保存。"
            if attrs.get("specification", getattr(current, "specification", specification)).strip() != specification:
                errors["product_id"] = "已关联产品不能直接改规格；不同规格应选择或建立另一条产品记录。"
            if attrs.get("unit_code", getattr(current, "unit_code", unit_code)).strip() != unit_code:
                errors["product_id"] = "已关联产品不能直接改单位；请解除关联后再保存。"

        target_price = attrs.get("target_unit_price", getattr(current, "target_unit_price", None))
        target_currency = attrs.get(
            "target_currency_code",
            getattr(current, "target_currency_code", ""),
        )
        if target_price is not None and not target_currency:
            errors["target_currency_code"] = "填写目标价后必须选择币种。"

        expected_date = attrs.get("expected_date")
        if expected_date is not None and expected_date < timezone.localdate():
            current_date = getattr(current, "expected_date", None)
            if current_date != expected_date:
                errors["expected_date"] = "新录入的期望日期不能早于今天。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def validate(self, attrs):
        return self._validate_item_rules(attrs, self._saved_item)


class InquiryItemUpdateSerializer(InquiryItemSerializer):
    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        return super().validate(attrs)


class InquiryDraftItemSerializer(InquiryItemSerializer):
    id = serializers.UUIDField(required=False)

    class Meta(InquiryItemSerializer.Meta):
        read_only_fields = [field for field in InquiryItemSerializer.Meta.read_only_fields if field != "id"]

    def validate(self, attrs):
        return self._validate_item_rules(attrs, self._saved_item)


class InquiryFileLinkSerializer(serializers.ModelSerializer):
    file_id = serializers.UUIDField(source="business_file_id", read_only=True)
    original_name = serializers.CharField(source="business_file.original_name", read_only=True)
    content_type = serializers.CharField(source="business_file.content_type", read_only=True)
    size_bytes = serializers.IntegerField(source="business_file.size_bytes", read_only=True)
    scan_status = serializers.CharField(source="business_file.scan_status", read_only=True)

    class Meta:
        model = InquiryFileLink
        fields = [
            "id",
            "file_id",
            "original_name",
            "content_type",
            "size_bytes",
            "scan_status",
            "file_role",
            "created_at",
        ]


class InquiryFileLinkCreateSerializer(serializers.Serializer):
    file_id = serializers.PrimaryKeyRelatedField(
        source="business_file",
        queryset=BusinessFile.objects.filter(archived_at__isnull=True, scan_status__in=USABLE_FILE_SCAN_STATUSES),
    )
    file_role = serializers.CharField(max_length=50, validators=[uppercase_code_validator])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inquiry = self.context.get("inquiry")
        request = self.context.get("request")
        if inquiry is None or request is None:
            self.fields["file_id"].queryset = BusinessFile.objects.none()
            return
        actor = getattr(request, "employee", None)
        self.fields["file_id"].queryset = BusinessFile.objects.filter(
            Q(uploaded_by_employee=actor)
            | Q(customer_links__customer_account=inquiry.customer_account)
            | Q(communication_links__communication__customer_account=inquiry.customer_account)
            | Q(inquiry_links__inquiry__customer_account=inquiry.customer_account)
            | Q(quotation_links__quotation_version__quotation__customer_account=inquiry.customer_account)
            | Q(sample_links__sample_request__customer_account=inquiry.customer_account),
            archived_at__isnull=True,
            scan_status__in=USABLE_FILE_SCAN_STATUSES,
        ).distinct()

    def validate_file_id(self, business_file):
        require_file(self.context.get("request"), business_file)
        inquiry = self.context["inquiry"]
        actor = getattr(self.context["request"], "employee", None)
        linked_customer_ids = set(business_file.customer_links.values_list("customer_account_id", flat=True))
        linked_customer_ids.update(
            business_file.communication_links.values_list("communication__customer_account_id", flat=True)
        )
        linked_customer_ids.update(
            business_file.inquiry_links.values_list("inquiry__customer_account_id", flat=True)
        )
        linked_customer_ids.update(
            business_file.quotation_links.values_list(
                "quotation_version__quotation__customer_account_id", flat=True
            )
        )
        linked_customer_ids.update(
            business_file.sample_links.values_list("sample_request__customer_account_id", flat=True)
        )
        if linked_customer_ids and linked_customer_ids != {inquiry.customer_account_id}:
            raise serializers.ValidationError("文件已关联到其他客户，不能跨客户复用。")
        if not linked_customer_ids and business_file.uploaded_by_employee_id != getattr(actor, "pk", None):
            raise serializers.ValidationError("未关联文件只能由上传人首次挂接。")
        return business_file


class InquiryWangImageUploadSerializer(serializers.Serializer):
    file = serializers.FileField(allow_empty_file=False)


class InquirySlaSerializer(serializers.ModelSerializer):
    progress_context = serializers.SerializerMethodField()

    def get_progress_context(self, obj) -> dict:
        data = obj.sla_tracking.tracking_data
        return {key: data.get(key) for key in ['round_number','entry_reason','source_label','completion_reason','quotation_id']}
    work_calendar = serializers.SerializerMethodField()
    target_minutes = serializers.SerializerMethodField()

    def get_work_calendar(self, obj) -> dict | None:
        return obj.sla_tracking.tracking_data.get("work_calendar")

    def get_target_minutes(self, obj) -> int | None:
        return obj.sla_tracking.tracking_data.get("target_minutes")

    policy_code = serializers.CharField(source="sla_tracking.sla_policy.policy_code", read_only=True)
    policy_name = serializers.CharField(source="sla_tracking.sla_policy.display_name", read_only=True)
    status = serializers.CharField(source="sla_tracking.status", read_only=True)
    started_at = serializers.DateTimeField(source="sla_tracking.started_at", read_only=True)
    next_deadline_at = serializers.DateTimeField(source="sla_tracking.next_deadline_at", read_only=True)
    breached_at = serializers.DateTimeField(source="sla_tracking.breached_at", read_only=True)
    completed_at = serializers.DateTimeField(source="sla_tracking.completed_at", read_only=True)

    class Meta:
        model = InquirySlaLink
        fields = [
            "id",
            "stage_code",
            "is_current",
            "policy_code",
            "policy_name",
            "status",
            "started_at",
            "next_deadline_at",
            "breached_at",
            "completed_at",
            "work_calendar",
            "target_minutes",
            "progress_context",
        ]


class InquiryAttachmentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    upload_id = serializers.UUIDField()


class InquiryListSerializer(SalesAccessSerializerMixin, serializers.ModelSerializer):
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    customer_name = serializers.CharField(source="customer_account.account_name", read_only=True)
    owner = EmployeeSummarySerializer(source="owner_employee", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    customer = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()
    product_summary = serializers.SerializerMethodField()
    product_amount = serializers.SerializerMethodField()
    sla_summary = serializers.SerializerMethodField()
    display_stage = serializers.SerializerMethodField()
    display_stage_label = serializers.SerializerMethodField()
    has_sent_quotation = serializers.SerializerMethodField()
    has_quotation = serializers.BooleanField(read_only=True, default=False)
    has_active_sample = serializers.SerializerMethodField()
    etag = serializers.SerializerMethodField()
    allowed_actions = serializers.SerializerMethodField()

    @cached_property
    def source_labels(self):
        options, _version = published_dictionary_options("INQUIRY_SOURCE")
        published = {item["code"]: item["label"] for item in options}
        historical = dict(
            ReferenceDictionary.objects.filter(
                category_code="INQUIRY_SOURCE",
                archived_at__isnull=True,
            ).values_list("item_code", "display_name")
        )
        # 已发布名称优先，数据库当前值只用于补充已停用的历史代码。
        return {**historical, **published}

    def get_customer(self, obj):
        return {"id": str(obj.customer_account_id), "name": obj.customer_account.account_name, "country_code": getattr(obj.customer_account, "primary_country_code", "")}

    def get_source(self, obj):
        code = obj.inquiry_source
        return {"code": code, "display_name": self.source_labels.get(code, code or "未填写")}

    def get_product_summary(self, obj):
        items = getattr(obj, "list_items", [])
        return {"first_description": items[0].product_description if items else "", "item_count": len(items)}

    def get_product_amount(self, obj) -> dict:
        return inquiry_product_amount(obj)

    def get_sla_summary(self, obj):
        request = self.context.get("request")
        if request and is_figma_demo_request(request) and is_figma_demo_inquiry(obj):
            return demo_override(obj).get("sla", {"state": "NONE", "next_deadline_at": None, "remaining_seconds": None})
        return inquiry_sla_summary(obj)

    def get_display_stage(self, obj):
        request = self.context.get("request")
        if request and is_figma_demo_request(request) and is_figma_demo_inquiry(obj):
            return demo_override(obj).get("display_stage", {}).get("code", obj.status)
        return inquiry_display_stage(obj)[0]

    def get_display_stage_label(self, obj):
        request = self.context.get("request")
        if request and is_figma_demo_request(request) and is_figma_demo_inquiry(obj):
            return demo_override(obj).get("display_stage", {}).get("label", obj.get_status_display())
        return inquiry_display_stage(obj)[1]

    def get_has_sent_quotation(self, obj):
        return bool(getattr(obj, "sent_quotations", []))

    def get_has_active_sample(self, obj):
        return bool(getattr(obj, "active_sample_requests", []))

    def get_etag(self, obj):
        from apps.core.api.concurrency import etag_for_instance
        return etag_for_instance(obj)

    def get_allowed_actions(self, obj):
        request = self.context.get("request")
        if request is None:
            return {
                "assign": False,
                "set_priority": False,
                "mark_invalid": False,
                "lifecycle": False,
                "create_quotation": False,
                "attach_contact": False,
                "respond": False,
                "confirm_requirements": False,
                "follow_up": False,
                "create_sample": False,
                "create_sales_order": False,
            }
        item_count = len(getattr(obj, "list_items", []))
        is_terminal = obj.status in {"CONVERTED", "CLOSED", "CANCELLED", "LOST"}
        def can(code):
            if not sales_policy.enabled():
                return request.user.has_perm(code)
            return sales_policy.can_customer(request, code, obj.customer_account_id)
        can_change = can("inquiries.change_inquiry")
        can_create_quotation = False
        if obj.status == "READY_FOR_QUOTE" and can_change and can("quotations.add_quotation"):
            if not hasattr(request, "_inquiry_quote_create_customer_ids"):
                request._inquiry_quote_create_customer_ids = set(
                    accessible_customers(request, "add_quotation").values_list("pk", flat=True)
                )
            can_create_quotation = obj.customer_account_id in request._inquiry_quote_create_customer_ids
        return {
            "assign": can("inquiries.assign_inquiry") and not is_terminal,
            "set_priority": can_change and obj.archived_at is None,
            "mark_invalid": (can("access_control.markinvalid_inquiry") if sales_policy.enabled() else can_change) and obj.status not in {"CONVERTED", "CLOSED", "CANCELLED"},
            "lifecycle": can_change and not is_terminal,
            "create_quotation": can_create_quotation,
            "attach_contact": can_change and obj.customer_contact_id is None and not is_terminal and (not sales_policy.enabled() or can("customers.view_customercontact")),
            "respond": (can("access_control.respond_inquiry") if sales_policy.enabled() else can_change) and obj.status == "NEW" and obj.customer_contact_id is not None,
            "confirm_requirements": (can("access_control.confirmrequirements_inquiry") if sales_policy.enabled() else can_change) and obj.status == "ANALYZING" and obj.customer_contact_id is not None and item_count > 0,
            "follow_up": (can("access_control.followup_inquiry") if sales_policy.enabled() else can_change) and obj.status in {"ANALYZING", "READY_FOR_QUOTE", "QUOTING", "QUOTED", "FOLLOW_UP", "QUOTE_ACCEPTED"},
            "create_sample": obj.status == "QUOTE_ACCEPTED" and item_count > 0,
            "create_sales_order": obj.status == "QUOTE_ACCEPTED" and (not sales_policy.enabled() or can("sales_orders.add_salesorder")),
        }

    class Meta:
        model = Inquiry
        fields = [
            "allowed_permissions",
            "id",
            "inquiry_number",
            "priority",
            "priority_display",
            "customer_account",
            "customer_name",
            "owner",
            "status",
            "status_display",
            "subject",
            "inquiry_source",
            "received_at",
            "requested_due_at",
            "submitted_at",
            "archived_at",
            "created_at",
            "updated_at",
            "customer",
            "source",
            "product_summary",
            "product_amount",
            "sla_summary",
            "display_stage",
            "display_stage_label",
            "has_sent_quotation",
            "has_quotation",
            "has_active_sample",
            "estimated_amount_min",
            "estimated_amount_max",
            "estimated_currency_code",
            "etag",
            "allowed_actions",
        ]


class InquiryDetailSerializer(InquiryListSerializer):
    handling_time_rule = serializers.SerializerMethodField()

    def get_handling_time_rule(self, obj) -> dict | None:
        from apps.workflow.models import SlaPolicy
        policy = SlaPolicy.objects.filter(target_type="INQUIRY", is_enabled=True, archived_at__isnull=True).order_by("policy_code").first()
        if policy is None:
            return None
        return {"name": policy.display_name, "response_minutes": policy.response_minutes,
                "confirmation_minutes": policy.resolution_minutes, "work_calendar": policy.config_data.get("work_calendar"),
                "stage_minutes": policy.config_data.get('stage_minutes', {})}

    items = InquiryItemSerializer(source="list_items", many=True, read_only=True)
    files = InquiryFileLinkSerializer(source="file_links", many=True, read_only=True)
    sla = serializers.SerializerMethodField()
    assignment_history = serializers.SerializerMethodField()
    customer_contact_summary = serializers.SerializerMethodField()
    linked_quotations = serializers.SerializerMethodField()
    linked_samples = serializers.SerializerMethodField()
    linked_sales_orders = serializers.SerializerMethodField()

    def get_assignment_history(self, obj):
        rows = getattr(obj, "assignment_history_rows", obj.assignment_history.all())
        return [
            {
                "id": str(row.pk),
                "previous_owner": EmployeeSummarySerializer(row.previous_owner_employee).data if row.previous_owner_employee_id else None,
                "new_owner": EmployeeSummarySerializer(row.new_owner_employee).data if row.new_owner_employee_id else None,
                "assigned_at": row.assigned_at,
                "assignment_reason": row.assignment_reason,
                "assignment_type": row.assignment_type,
            }
            for row in rows
        ]

    def get_sla(self, obj):
        request = self.context.get("request")
        if request and is_figma_demo_request(request) and is_figma_demo_inquiry(obj):
            summary = demo_override(obj).get("sla", {})
            if summary.get("state") == "NONE":
                return []
            return [{
                "id": f"demo-{obj.pk}", "stage_code": "FIRST_RESPONSE", "is_current": True,
                "policy_code": "FIGMA_DEMO", "policy_name": summary.get("policy_name", "示例 SLA"),
                "status": "RUNNING", "started_at": obj.received_at,
                "next_deadline_at": summary.get("next_deadline_at"), "breached_at": None, "completed_at": None,
            }]
        return InquirySlaSerializer(obj.sla_links.all(), many=True).data

    def get_customer_contact_summary(self, obj):
        contact = obj.customer_contact
        if contact is None:
            return None
        return {
            "id": str(contact.pk),
            "display_name": contact.display_name,
            "english_name": contact.english_name,
            "preferred_language_code": contact.preferred_language_code,
        }

    def get_linked_quotations(self, obj):
        request = self.context.get("request")
        if request is None or not sales_policy.can_customer(request, "quotations.view_quotation", obj.customer_account_id):
            return []
        quotations = getattr(obj, "linked_quotation_rows", obj.quotations.filter(archived_at__isnull=True).prefetch_related("versions"))
        rows = []
        for quotation in quotations:
            versions = list(quotation.versions.all())
            current_version = max(versions, key=lambda version: version.version_number, default=None)
            rows.append({
                "id": str(quotation.pk),
                "quotation_number": quotation.quotation_number,
                "subject": quotation.subject,
                "status": current_version.status if current_version else "DRAFT",
                "version_id": str(current_version.pk) if current_version else None,
                "outcome_status": quotation.outcome_status,
                "accepted_version_id": str(quotation.accepted_version_id) if quotation.accepted_version_id else None,
            })
        return rows

    def get_linked_samples(self, obj):
        samples = getattr(
            obj,
            "linked_sample_rows",
            obj.sample_requests.filter(archived_at__isnull=True).order_by("-updated_at", "-id"),
        )
        return [
            {
                "id": str(sample.pk),
                "request_number": sample.request_number,
                "status": sample.status,
                "status_display": sample.get_status_display(),
                "updated_at": sample.updated_at,
            }
            for sample in samples
        ]

    def get_linked_sales_orders(self, obj):
        from apps.sales_orders.selectors import accessible_sales_orders
        request = self.context.get("request")
        allowed = set(accessible_sales_orders(request).values_list("pk", flat=True)) if request and sales_policy.enabled() else None
        rows = []
        seen = set()
        quotations = getattr(obj, "linked_quotation_rows", [])
        for quotation in quotations:
            for version in quotation.versions.all():
                for order in version.sales_orders.all():
                    if order.pk in seen or order.archived_at is not None or (allowed is not None and order.pk not in allowed):
                        continue
                    seen.add(order.pk)
                    rows.append(
                        {
                            "id": str(order.pk),
                            "order_number": order.order_number,
                            "status": order.status,
                            "status_display": order.get_status_display(),
                            "is_draft": order.status == "DRAFT",
                            "total_amount": order.total_amount,
                            "currency_code": order.currency_code,
                            "updated_at": order.updated_at,
                        }
                    )
        return sorted(rows, key=lambda row: row["updated_at"], reverse=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["description"] = sanitize_rich_text(instance.description, enforce_limits=False)
        return data

    class Meta(InquiryListSerializer.Meta):
        fields = InquiryListSerializer.Meta.fields + [
            "transaction_entity",
            "customer_contact",
            "description",
            "source_system",
            "external_id",
            "customer_snapshot",
            "source_snapshot",
            "customer_language_code",
            "trade_term_code",
            "trade_term_place",
            "delivery_requirement",
            "draft_version",
            "items",
            "files",
            "sla",
            "handling_time_rule",
            "assignment_history",
            "customer_contact_summary",
            "linked_quotations",
            "linked_samples",
            "linked_sales_orders",
        ]


class InquiryWritableSerializer(serializers.ModelSerializer):
    transaction_entity_id = serializers.PrimaryKeyRelatedField(
        source="transaction_entity",
        required=False,
        allow_null=True,
        queryset=CustomerTransactionEntity.objects.filter(archived_at__isnull=True),
    )
    customer_contact_id = serializers.PrimaryKeyRelatedField(
        source="customer_contact",
        required=False,
        allow_null=True,
        queryset=CustomerContact.objects.filter(archived_at__isnull=True),
    )
    inquiry_source = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[uppercase_code_validator],
    )
    source_system = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[uppercase_code_validator],
    )
    external_id = serializers.CharField(required=False, allow_blank=True, max_length=150)
    customer_language_code = serializers.CharField(required=False, allow_blank=True, max_length=30, validators=[uppercase_code_validator])
    trade_term_code = serializers.CharField(required=False, allow_blank=True, max_length=30, validators=[uppercase_code_validator])
    trade_term_place = serializers.CharField(required=False, allow_blank=True, max_length=150)
    delivery_requirement = serializers.CharField(required=False, allow_blank=True, max_length=250)
    estimated_currency_code = serializers.CharField(required=False, allow_blank=True, max_length=3, validators=[currency_code_validator])

    def validate_description(self, value):
        return sanitize_rich_text(value)

    def validate(self, attrs):
        customer = attrs.get("customer_account", getattr(self.instance, "customer_account", None))
        entity = attrs.get("transaction_entity", getattr(self.instance, "transaction_entity", None))
        contact = attrs.get("customer_contact", getattr(self.instance, "customer_contact", None))
        source_system = attrs.get("source_system", getattr(self.instance, "source_system", ""))
        external_id = attrs.get("external_id", getattr(self.instance, "external_id", ""))
        errors = {}
        inquiry_source = attrs.get(
            "inquiry_source",
            getattr(self.instance, "inquiry_source", ""),
        )
        current_source = getattr(self.instance, "inquiry_source", "")
        if (
            inquiry_source
            and inquiry_source != current_source
            and not published_dictionary_code_is_active("INQUIRY_SOURCE", inquiry_source)
        ):
            errors["inquiry_source"] = "询盘来源不存在或尚未发布。"
        trade_term = attrs.get(
            "trade_term_code",
            getattr(self.instance, "trade_term_code", ""),
        )
        current_trade_term = getattr(self.instance, "trade_term_code", "")
        if (
            trade_term
            and trade_term != current_trade_term
            and not Incoterm.objects.filter(
                code=trade_term,
                status=ReferenceStatus.ACTIVE,
                archived_at__isnull=True,
            ).exists()
        ):
            errors["trade_term_code"] = "贸易术语不存在、已停用或已归档。"
        if entity and entity.customer_account_id != customer.pk:
            errors["transaction_entity_id"] = "交易主体必须属于当前客户。"
        if contact and contact.customer_account_id != customer.pk:
            errors["customer_contact_id"] = "联系人必须属于当前客户。"
        if bool(source_system) != bool(external_id):
            errors["source_system"] = "来源系统和外部编号必须同时填写或同时留空。"
        elif source_system:
            duplicate = Inquiry.objects.filter(source_system=source_system, external_id=external_id)
            if self.instance:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                errors["external_id"] = "该来源系统下的外部编号已经存在。"
        if errors:
            raise serializers.ValidationError(errors)
        amount_min = attrs.get("estimated_amount_min", getattr(self.instance, "estimated_amount_min", None))
        amount_max = attrs.get("estimated_amount_max", getattr(self.instance, "estimated_amount_max", None))
        currency = attrs.get("estimated_currency_code", getattr(self.instance, "estimated_currency_code", ""))
        current_currency = getattr(self.instance, "estimated_currency_code", "")
        if (
            currency
            and currency != current_currency
            and not Currency.objects.filter(
                code=currency,
                status=ReferenceStatus.ACTIVE,
                archived_at__isnull=True,
            ).exists()
        ):
            raise serializers.ValidationError(
                {"estimated_currency_code": "预计金额币种不存在、已停用或已归档。"}
            )
        if any(value is not None for value in [amount_min, amount_max]) or currency:
            if amount_min is None or amount_max is None or not currency:
                raise serializers.ValidationError({"estimated_amount_min": "预计金额需同时填写最小值、最大值和币种。"})
            if amount_min < 0 or amount_max < amount_min:
                raise serializers.ValidationError({"estimated_amount_max": "预计金额最大值不能小于最小值。"})
        return attrs


class InquiryCreateSerializer(InquiryWritableSerializer):
    customer_account_id = serializers.PrimaryKeyRelatedField(
        source="customer_account",
        queryset=CustomerAccount.objects.filter(archived_at__isnull=True),
    )
    items = InquiryItemSerializer(many=True, required=False)
    idempotency_key = serializers.CharField(max_length=64, min_length=8, required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Inquiry
        fields = [
            "customer_account_id",
            "transaction_entity_id",
            "customer_contact_id",
            "inquiry_source",
            "subject",
            "description",
            "received_at",
            "requested_due_at",
            "source_system",
            "external_id",
            "customer_language_code",
            "trade_term_code",
            "trade_term_place",
            "delivery_requirement",
            "estimated_amount_min",
            "estimated_amount_max",
            "estimated_currency_code",
            "items",
            "idempotency_key",
        ]
        validators = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return
        allowed = accessible_customers(request, "add_inquiry").filter(archived_at__isnull=True)
        self.fields["customer_account_id"].queryset = allowed
        self.fields["transaction_entity_id"].queryset = CustomerTransactionEntity.objects.filter(
            customer_account__in=allowed, archived_at__isnull=True
        )
        self.fields["customer_contact_id"].queryset = CustomerContact.objects.filter(
            customer_account__in=allowed, archived_at__isnull=True
        )

    def validate_items(self, items):
        if len(items) > 200:
            raise serializers.ValidationError("单张询价最多包含 200 条明细。")
        numbers = [item.get("line_number") for item in items if item.get("line_number") is not None]
        if len(numbers) != len(set(numbers)):
            raise serializers.ValidationError("明细行号不能重复。")
        return items


class InquiryUpdateSerializer(InquiryWritableSerializer):
    class Meta:
        model = Inquiry
        fields = [
            "transaction_entity_id",
            "customer_contact_id",
            "inquiry_source",
            "subject",
            "description",
            "received_at",
            "requested_due_at",
            "source_system",
            "external_id",
            "customer_language_code",
            "trade_term_code",
            "trade_term_place",
            "delivery_requirement",
            "estimated_amount_min",
            "estimated_amount_max",
            "estimated_currency_code",
        ]
        validators = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is None:
            return
        self.fields["transaction_entity_id"].queryset = CustomerTransactionEntity.objects.filter(
            customer_account=self.instance.customer_account,
            archived_at__isnull=True,
        )
        self.fields["customer_contact_id"].queryset = CustomerContact.objects.filter(
            customer_account=self.instance.customer_account,
            archived_at__isnull=True,
        )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        return super().validate(attrs)


class InquiryDraftSaveSerializer(InquiryWritableSerializer):
    items = InquiryDraftItemSerializer(many=True, required=False)
    idempotency_key = serializers.CharField(max_length=64, min_length=8, write_only=True)

    class Meta:
        model = Inquiry
        fields = InquiryUpdateSerializer.Meta.fields + ["items", "idempotency_key"]
        validators = []

    def validate(self, attrs):
        if not attrs.get("idempotency_key"):
            raise serializers.ValidationError({"idempotency_key": "草稿保存必须提供幂等键。"})
        return super().validate(attrs)

    def validate_items(self, items):
        if len(items) > 200:
            raise serializers.ValidationError("单张询价最多包含 200 条明细。")
        ids = [str(item.get("id", "")) for item in items if item.get("id")]
        numbers = [item.get("line_number") for item in items if item.get("line_number") is not None]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("明细不能重复提交。")
        if len(numbers) != len(set(numbers)):
            raise serializers.ValidationError("明细行号不能重复。")
        return items


class InquiryActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class InquiryRequiredNoteSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=500, trim_whitespace=True)


class InquiryRichTextRequiredNoteSerializer(serializers.Serializer):
    note = serializers.CharField(trim_whitespace=False)

    def validate_note(self, value):
        cleaned = sanitize_rich_text(value)
        plain_text = rich_text_plain_text(value).strip()
        if not plain_text:
            raise serializers.ValidationError("记录首响时必须填写实际响应说明。")
        if len(plain_text) > 500:
            raise serializers.ValidationError("记录首响不能超过 500 个文字。")
        return cleaned


class InquiryCommunicationSerializer(serializers.Serializer):
    communication_type = serializers.ChoiceField(
        choices=["EMAIL", "PHONE", "MEETING", "VIDEO", "WECHAT", "WHATSAPP", "OTHER"]
    )
    content = serializers.CharField(trim_whitespace=False)
    occurred_at = serializers.DateTimeField()

    def validate_content(self, value):
        cleaned = sanitize_rich_text(value)
        plain_text = rich_text_plain_text(cleaned).strip()
        if not plain_text:
            raise serializers.ValidationError("必须填写实际沟通内容。")
        if len(plain_text) > 2000:
            raise serializers.ValidationError("沟通内容不能超过 2000 个文字。")
        return cleaned


class InquiryContactAttachSerializer(serializers.Serializer):
    customer_contact_id = serializers.PrimaryKeyRelatedField(
        source="customer_contact",
        queryset=CustomerContact.objects.filter(archived_at__isnull=True),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inquiry = self.context.get("inquiry")
        if inquiry is not None:
            self.fields["customer_contact_id"].queryset = CustomerContact.objects.filter(
                customer_account_id=inquiry.customer_account_id,
                archived_at__isnull=True,
            ).order_by("display_name", "id")


class InquiryReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class InquiryPrioritySerializer(serializers.Serializer):
    priority = serializers.ChoiceField(choices=InquiryPriority.choices, allow_blank=True)


class InquiryAssignSerializer(serializers.Serializer):
    owner_employee_id = serializers.PrimaryKeyRelatedField(
        source="owner_employee", queryset=active_department_employees("DEPT_BUSINESS")
    )
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class InquiryInvalidSerializer(serializers.Serializer):
    reason_code = serializers.ChoiceField(choices=["DUPLICATE", "SPAM", "UNPROCESSABLE", "OTHER"])
    reason_detail = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class InquiryBulkSerializer(serializers.Serializer):
    items = serializers.ListField(child=serializers.DictField(), min_length=1, max_length=100)

    def validate_items(self, items):
        ids = [str(item.get("id", "")) for item in items]
        if any(not item.get("id") or not item.get("etag") for item in items):
            raise serializers.ValidationError("每条记录必须包含 id 与 etag。")
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("批量记录不能重复。")
        return items


class InquiryBulkAssignSerializer(InquiryBulkSerializer):
    owner_employee_id = serializers.PrimaryKeyRelatedField(
        source="owner_employee", queryset=active_department_employees("DEPT_BUSINESS")
    )
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class InquiryBulkInvalidSerializer(InquiryBulkSerializer):
    reason_code = serializers.ChoiceField(choices=["DUPLICATE", "SPAM", "UNPROCESSABLE", "OTHER"])
    reason_detail = serializers.CharField(required=False, allow_blank=True, max_length=1000)
