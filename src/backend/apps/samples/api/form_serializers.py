from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.core.models import uppercase_code_validator
from apps.customers.models import CustomerAccount, CustomerContact
from apps.customers.selectors import accessible_customers
from apps.organizations.models import Employee
from apps.reference_data.models import (
    ProductCategory,
    ProductColor,
    ProductItemType,
    ReferenceStatus,
)

from ..models import (
    SampleDeliveryBatch,
    SampleRequest,
    SampleShippingMethod,
    SampleTolerance,
    SampleType,
)


class SampleFormDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    product_color_id = serializers.PrimaryKeyRelatedField(
        source="product_color",
        queryset=ProductColor.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
    )
    color_code = serializers.CharField(max_length=100, required=False, allow_blank=True, trim_whitespace=True)
    sample_quantity = serializers.IntegerField(min_value=1)
    tolerance = serializers.ChoiceField(choices=SampleTolerance.choices, default=SampleTolerance.NONE)
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    cutting_reported_quantity = serializers.IntegerField(min_value=0, default=0)
    metalwork_reported_quantity = serializers.IntegerField(min_value=0, default=0)
    cutting_completed = serializers.BooleanField(default=False)
    metalwork_completed = serializers.BooleanField(default=False)

    def validate(self, attrs):
        quantity = attrs["sample_quantity"]
        errors = {}
        if attrs["cutting_reported_quantity"] > quantity:
            errors["cutting_reported_quantity"] = "裁剪报工数量不能超过打样数量。"
        if attrs["metalwork_reported_quantity"] > quantity:
            errors["metalwork_reported_quantity"] = "金工报工数量不能超过打样数量。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class SampleProductSamplingDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    client_key = serializers.RegexField(r"^[A-Za-z0-9_-]{1,64}$")
    template_key = serializers.CharField(max_length=64, required=False, allow_blank=True, trim_whitespace=True)
    detail_type = serializers.CharField(max_length=100, trim_whitespace=True)
    category_label = serializers.CharField(max_length=100, required=False, allow_blank=True, trim_whitespace=True)
    is_selected = serializers.BooleanField()
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class SampleFormProductSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    client_key = serializers.RegexField(r"^[A-Za-z0-9_-]{1,64}$")
    source_inquiry_item_id = serializers.UUIDField(required=False, allow_null=True)
    source_quotation_line_id = serializers.UUIDField(required=False, allow_null=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=ProductCategory.objects.filter(
            item_type=ProductItemType.FINISHED,
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ),
    )
    product_name = serializers.CharField(max_length=500, trim_whitespace=True)
    specification = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    length_cm = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True
    )
    armrest_width_cm = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True
    )
    seat_width_cm = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True
    )
    back_height_cm = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True
    )
    seat_height_cm = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True
    )
    details = SampleFormDetailSerializer(many=True, min_length=1, max_length=200)
    sampling_details = SampleProductSamplingDetailSerializer(many=True, required=False, default=list, max_length=100)


class SampleRequestFormSerializer(serializers.Serializer):
    manual_request_number = serializers.CharField(max_length=46, trim_whitespace=True)
    customer_account_id = serializers.PrimaryKeyRelatedField(
        source="customer_account",
        queryset=CustomerAccount.objects.none(),
    )
    customer_contact_id = serializers.PrimaryKeyRelatedField(
        source="customer_contact",
        queryset=CustomerContact.objects.none(),
        required=False,
        allow_null=True,
    )
    owner_employee_id = serializers.PrimaryKeyRelatedField(
        source="owner_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    shipping_method = serializers.ChoiceField(choices=SampleShippingMethod.choices)
    order_date = serializers.DateField()
    sample_due_date = serializers.DateField()
    delivery_batch = serializers.ChoiceField(choices=SampleDeliveryBatch.choices)
    sample_type = serializers.ChoiceField(choices=SampleType.choices)
    is_repeat_order = serializers.BooleanField()
    submitted_on = serializers.DateField()
    purpose = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    source_type = serializers.ChoiceField(choices=["inquiry", "quotation"], required=False, allow_null=True)
    source_id = serializers.UUIDField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(min_length=8, max_length=64, required=False, allow_blank=True)
    products = SampleFormProductSerializer(many=True, min_length=1, max_length=50)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return
        customers = accessible_customers(request, "add_samplerequest").filter(archived_at__isnull=True)
        if self.instance is not None:
            customers = CustomerAccount.objects.filter(pk=self.instance.customer_account_id)
        self.fields["customer_account_id"].queryset = customers
        self.fields["customer_contact_id"].queryset = CustomerContact.objects.filter(
            customer_account__in=customers,
            archived_at__isnull=True,
        )

    def validate_manual_request_number(self, value):
        normalized = value.strip().upper()
        if normalized.startswith("HTS-"):
            raise serializers.ValidationError("手写打样单号不要填写 HTS- 前缀，系统会自动生成。")
        try:
            uppercase_code_validator(normalized)
            uppercase_code_validator(f"HTS-{normalized}")
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return normalized

    def validate(self, attrs):
        contact = attrs.get("customer_contact")
        customer = attrs["customer_account"]
        if contact and contact.customer_account_id != customer.pk:
            raise serializers.ValidationError({"customer_contact_id": "联系人必须属于当前客户。"})
        source_type = attrs.get("source_type")
        source_id = attrs.get("source_id")
        if bool(source_type) != bool(source_id):
            raise serializers.ValidationError({"source_id": "来源类型和来源编号必须同时提交。"})
        product_keys = [product["client_key"] for product in attrs["products"]]
        if len(product_keys) != len(set(product_keys)):
            raise serializers.ValidationError({"products": "产品客户端键不能重复。"})
        product_ids = [product.get("id") for product in attrs["products"] if product.get("id")]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError({"products": "产品 UUID 不能重复。"})
        detail_ids = [
            detail.get("id")
            for product in attrs["products"]
            for detail in product["details"]
            if detail.get("id")
        ]
        if len(detail_ids) != len(set(detail_ids)):
            raise serializers.ValidationError({"products": "样品明细 UUID 不能重复。"})
        sampling_client_keys = [
            detail["client_key"]
            for product in attrs["products"]
            for detail in product["sampling_details"]
        ]
        if len(sampling_client_keys) != len(set(sampling_client_keys)):
            raise serializers.ValidationError({"products": "打样信息明细客户端键不能重复。"})
        sampling_detail_ids = [
            detail.get("id")
            for product in attrs["products"]
            for detail in product["sampling_details"]
            if detail.get("id")
        ]
        if len(sampling_detail_ids) != len(set(sampling_detail_ids)):
            raise serializers.ValidationError({"products": "打样信息明细 UUID 不能重复。"})
        if sum(len(product["details"]) for product in attrs["products"]) > 200:
            raise serializers.ValidationError({"products": "单张样品申请最多包含 200 条样品明细。"})
        if sum(len(product["sampling_details"]) for product in attrs["products"]) > 1000:
            raise serializers.ValidationError({"products": "单张样品申请最多包含 1000 条打样信息明细。"})
        return attrs


class SampleFormDetailReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    product_color_id = serializers.UUIDField(allow_null=True)
    color_card = serializers.CharField(source="color_card_snapshot")
    color_name = serializers.CharField(source="color_name_snapshot")
    color_code = serializers.CharField(source="color_code_snapshot")
    sample_quantity = serializers.IntegerField(allow_null=True)
    tolerance = serializers.CharField()
    tolerance_display = serializers.CharField(source="get_tolerance_display")
    notes = serializers.CharField()
    cutting_reported_quantity = serializers.IntegerField()
    metalwork_reported_quantity = serializers.IntegerField()
    cutting_completed = serializers.BooleanField()
    metalwork_completed = serializers.BooleanField()


class SampleProductSamplingDetailReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    line_number = serializers.IntegerField()
    template_key = serializers.CharField()
    detail_type = serializers.CharField()
    category_label = serializers.CharField()
    is_selected = serializers.BooleanField()
    description = serializers.CharField()
    image_file_id = serializers.UUIDField(allow_null=True)
    image_file_name = serializers.CharField(source="image_file.original_name", default="")
    image_content_type = serializers.CharField(source="image_file.content_type", default="")
    image_size_bytes = serializers.IntegerField(source="image_file.size_bytes", default=0)


class SampleFormProductReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    line_number = serializers.IntegerField()
    source_inquiry_item_id = serializers.UUIDField(allow_null=True)
    source_quotation_line_id = serializers.UUIDField(allow_null=True)
    category_id = serializers.UUIDField(allow_null=True)
    category_name = serializers.CharField(source="category_name_snapshot")
    product_name = serializers.CharField()
    specification = serializers.CharField()
    task_sheet_file_id = serializers.UUIDField(allow_null=True)
    task_sheet_file_name = serializers.CharField(source="task_sheet_file.original_name", default="")
    task_sheet_content_type = serializers.CharField(source="task_sheet_file.content_type", default="")
    task_sheet_size_bytes = serializers.IntegerField(source="task_sheet_file.size_bytes", default=0)
    length_cm = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    armrest_width_cm = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    seat_width_cm = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    back_height_cm = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    seat_height_cm = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    total_sample_quantity = serializers.SerializerMethodField()
    details = SampleFormDetailReadSerializer(many=True)
    sampling_details = SampleProductSamplingDetailReadSerializer(many=True)

    def get_total_sample_quantity(self, instance):
        return sum(detail.sample_quantity or 0 for detail in instance.details.all())
