from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.core.models import (
    ArchivableModel,
    TimeStampedModel,
    currency_code_validator,
    uppercase_code_condition,
    uppercase_code_validator,
)


class SampleRequestStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    DIRECTOR_REVIEW = "DIRECTOR_REVIEW", "待厂长确认"
    APPLICATION_RETURNED = "APPLICATION_RETURNED", "退回业务员补充"
    MATERIALS_PENDING = "MATERIALS_PENDING", "待打样部填写"
    WAREHOUSE_PENDING = "WAREHOUSE_PENDING", "待仓库核对"
    PROCUREMENT_PENDING = "PROCUREMENT_PENDING", "待采购处理"
    MATERIALS_READY = "MATERIALS_READY", "材料已核对齐备"
    MATERIAL_ISSUE_PENDING = "MATERIAL_ISSUE_PENDING", "待发起领料"
    MATERIAL_ISSUE_REVIEW = "MATERIAL_ISSUE_REVIEW", "待仓库确认领料"
    PENDING_COMPLETION = "PENDING_COMPLETION", "待工厂完善"
    PENDING = "PENDING", "财务待确认"
    PMC_REVIEW = "PMC_REVIEW", "PMC待审核"
    METALWORK_PENDING = "METALWORK_PENDING", "待上传金工参数"
    CUTTING_PENDING = "CUTTING_PENDING", "待上传裁剪参数"
    PRODUCTION_PENDING = "PRODUCTION_PENDING", "待生产完成"
    FINISHED = "FINISHED", "流程已结束"
    # 以下状态仅兼容历史样品数据，不再进入新建样品主流程。
    PREPARING = "PREPARING", "待寄出"
    SHIPPED = "SHIPPED", "运输中"
    DELIVERED = "DELIVERED", "已签收"
    FEEDBACK_PENDING = "FEEDBACK_PENDING", "待反馈"
    CONFIRMED = "CONFIRMED", "已确认"
    COMPLETED = "COMPLETED", "已确认（历史）"
    REJECTED = "REJECTED", "未通过"
    CANCELLED = "CANCELLED", "已取消"


class SampleType(models.TextChoices):
    PRE_SALES = "PRE_SALES", "售前样"
    PRE_PRODUCTION = "PRE_PRODUCTION", "产前样"
    TESTING = "TESTING", "检测样"
    BULK_CONFIRMATION = "BULK_CONFIRMATION", "大货确认样"


class SampleShippingMethod(models.TextChoices):
    MAIL = "MAIL", "邮寄"
    OTHER = "OTHER", "其他"


class SampleDeliveryBatch(models.TextChoices):
    SINGLE = "SINGLE", "一次交货"
    PARTIAL = "PARTIAL", "分批交货"


class SampleTolerance(models.TextChoices):
    NONE = "NONE", "无"
    PLUS_MINUS_0_5_CM = "PLUS_MINUS_0_5_CM", "±0.5cm"
    PLUS_MINUS_1_CM = "PLUS_MINUS_1_CM", "±1cm"


class SampleWorkflowStage(models.TextChoices):
    MATERIALS_READY = "MATERIALS_READY", "材料齐备，允许生产"
    REQUEST_CREATED = "REQUEST_CREATED", "创建样品需求"
    REQUIREMENTS_COMPLETED = "REQUIREMENTS_COMPLETED", "工厂完善并提交"
    FINANCE_CONFIRMED = "FINANCE_CONFIRMED", "财务确认完成"
    PMC_APPROVED = "PMC_APPROVED", "PMC审核通过"
    METALWORK_PARAMETERS = "METALWORK_PARAMETERS", "金工参数上传"
    CUTTING_PARAMETERS = "CUTTING_PARAMETERS", "裁剪参数上传"
    WORKFLOW_FINISHED = "WORKFLOW_FINISHED", "样品单流程结束"


class SampleParameterType(models.TextChoices):
    METALWORK = "METALWORK", "金工"
    CUTTING = "CUTTING", "裁剪"


class SampleRequest(ArchivableModel):
    customer_account = models.ForeignKey(
        "customers.CustomerAccount",
        on_delete=models.PROTECT,
        related_name="sample_requests",
    )
    transaction_entity = models.ForeignKey(
        "customers.CustomerTransactionEntity",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_requests",
    )
    customer_contact = models.ForeignKey(
        "customers.CustomerContact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_requests",
    )
    owner_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="owned_sample_requests",
    )
    source_inquiry = models.ForeignKey(
        "inquiries.Inquiry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_requests",
    )
    source_quotation_version = models.ForeignKey(
        "quotations.QuotationVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_requests",
    )
    request_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    intake_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    manual_request_number = models.CharField(max_length=46, unique=True, null=True, blank=True)
    requested_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="requested_sample_requests",
    )
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_sample_requests",
    )
    shipping_method = models.CharField(max_length=20, choices=SampleShippingMethod.choices, blank=True)
    order_date = models.DateField(null=True, blank=True)
    sample_due_date = models.DateField(null=True, blank=True)
    delivery_batch = models.CharField(max_length=20, choices=SampleDeliveryBatch.choices, blank=True)
    is_repeat_order = models.BooleanField(null=True, blank=True)
    submitted_on = models.DateField(null=True, blank=True)
    creation_idempotency_key = models.CharField(max_length=64, blank=True)
    application_payload_hash = models.CharField(max_length=64, blank=True)
    reference_image = models.ForeignKey(
        "files.BusinessFile", null=True, blank=True, on_delete=models.PROTECT,
        related_name="sample_application_references",
    )
    director_note = models.TextField(blank=True)
    status = models.CharField(
        max_length=30,
        choices=SampleRequestStatus.choices,
        default=SampleRequestStatus.DRAFT,
    )
    sample_type = models.CharField(
        max_length=30,
        choices=SampleType.choices,
        default=SampleType.PRE_SALES,
    )
    purpose = models.TextField(blank=True)
    requested_at = models.DateTimeField()
    requested_due_at = models.DateTimeField(null=True, blank=True)
    expected_shipped_at = models.DateTimeField(null=True, blank=True)
    expected_received_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    collaborators = models.ManyToManyField(
        "organizations.Employee",
        through="SampleCollaborator",
        related_name="collaborated_sample_requests",
        blank=True,
    )

    class Meta:
        db_table = "sample_request"
        permissions = [
            ("decide_sample_fee", "可决定样品费用"),
            ("ship_sample", "可寄送样品"),
            ("view_all_samplerequest", "可查看全部样品流程"),
            ("complete_sample_requirements", "可完善样品需求"),
            ("review_sample_application", "可厂长确认或退回打样申请"),
            ("edit_sample_materials", "可填写并提交打样材料需求"),
            ("review_sample_materials", "可仓库核对打样材料"),
            ("view_sample_procurement", "可查看打样缺料采购需求"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=SampleRequestStatus.values),
                name="sample_request_status_valid",
            ),
            models.CheckConstraint(
                condition=uppercase_code_condition("request_number"),
                name="sample_request_number_uppercase",
            ),
            models.UniqueConstraint(
                fields=["creation_idempotency_key"],
                condition=~Q(creation_idempotency_key=""),
                name="sample_create_idempotency_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["owner_employee", "status", "-updated_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="sample_owner_status_idx",
            ),
            models.Index(
                fields=["status", "requested_at", "id"],
                condition=Q(
                    archived_at__isnull=True,
                    status__in=[
                        SampleRequestStatus.PENDING_COMPLETION,
                        SampleRequestStatus.PENDING,
                        SampleRequestStatus.PMC_REVIEW,
                        SampleRequestStatus.METALWORK_PENDING,
                        SampleRequestStatus.CUTTING_PENDING,
                        SampleRequestStatus.PREPARING,
                        SampleRequestStatus.SHIPPED,
                        SampleRequestStatus.DELIVERED,
                        SampleRequestStatus.FEEDBACK_PENDING,
                    ],
                ),
                name="sample_processing_queue_idx",
            ),
            models.Index(
                fields=["customer_account", "-requested_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="sample_customer_idx",
            ),
            models.Index(
                fields=["source_inquiry", "-requested_at", "-id"],
                condition=Q(source_inquiry__isnull=False),
                name="sample_inquiry_source_idx",
            ),
            models.Index(
                fields=["source_quotation_version", "-requested_at", "-id"],
                condition=Q(source_quotation_version__isnull=False),
                name="sample_quote_source_idx",
            ),
        ]

    def __str__(self):
        return self.request_number

    def clean(self):
        super().clean()
        errors = {}
        if self.transaction_entity_id and self.transaction_entity.customer_account_id != self.customer_account_id:
            errors["transaction_entity"] = "样品交易主体必须属于同一客户账户。"
        if self.customer_contact_id and self.customer_contact.customer_account_id != self.customer_account_id:
            errors["customer_contact"] = "样品联系人必须属于同一客户账户。"
        if self.source_inquiry_id and self.source_inquiry.customer_account_id != self.customer_account_id:
            errors["source_inquiry"] = "来源询价必须属于同一客户账户。"
        if (
            self.source_quotation_version_id
            and self.source_quotation_version.quotation.customer_account_id != self.customer_account_id
        ):
            errors["source_quotation_version"] = "来源报价版本必须属于同一客户账户。"
        if (
            self.source_inquiry_id
            and self.source_quotation_version_id
            and self.source_quotation_version.quotation.source_inquiry_id != self.source_inquiry_id
        ):
            errors["source_quotation_version"] = "来源报价版本必须来自当前来源询价。"
        if errors:
            raise ValidationError(errors)


class SampleMaterialRequest(TimeStampedModel):
    """自由录入材料保留草稿；提交后冻结需求，仓库仅填写供料数量。"""
    sample_request = models.OneToOneField(SampleRequest, on_delete=models.PROTECT, related_name="material_request")
    draft = models.JSONField(default=dict)
    no_materials = models.BooleanField(default=False)
    warehouse_draft = models.JSONField(default=dict)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey("organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="sample_material_submissions")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey("organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="sample_material_reviews")

    class Meta:
        db_table = "sample_material_request"


class SampleMaterialProcurementRequest(TimeStampedModel):
    """仓库确认时生成的不可变缺料快照，后续采购按此来源接续。"""
    material_request = models.OneToOneField(SampleMaterialRequest, on_delete=models.PROTECT, related_name="procurement_request")
    lines = models.JSONField(default=list)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "sample_material_procurement_request"


class SampleMaterialPurchaseSource(TimeStampedModel):
    """采购创建时冻结来源；没有来源绑定的入库不能推进打样。"""
    procurement_request = models.ForeignKey(SampleMaterialProcurementRequest, on_delete=models.PROTECT, related_name='purchase_sources')
    line_key = models.UUIDField()
    purchase_order_line = models.OneToOneField('procurement.PurchaseOrderLine', on_delete=models.PROTECT, related_name='sample_material_source')

    class Meta:
        db_table = 'sample_material_purchase_source'


class SampleMaterialArrival(TimeStampedModel):
    """一个真实入库行只接续一项样品缺料，不能重复分配入库数量。"""
    procurement_request = models.ForeignKey(SampleMaterialProcurementRequest, on_delete=models.PROTECT, related_name='arrivals')
    line_key = models.UUIDField()
    inbound_line = models.OneToOneField('inventory.MaterialInboundLine', on_delete=models.PROTECT, related_name='sample_material_arrival')
    accepted_quantity = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = 'sample_material_arrival'
        constraints = [models.CheckConstraint(condition=Q(accepted_quantity__gt=0), name='sample_arrival_qty_positive')]


class SampleMaterialIssueStatus(models.TextChoices):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION", "待仓库确认"
    ISSUED = "ISSUED", "已领料"


class SampleMaterialIssue(TimeStampedModel):
    """样品专用领料单；与生产领料单隔离，只冻结样品用料快照。"""

    material_request = models.OneToOneField(
        SampleMaterialRequest,
        on_delete=models.PROTECT,
        related_name="issue",
    )
    status = models.CharField(
        max_length=30,
        choices=SampleMaterialIssueStatus.choices,
        default=SampleMaterialIssueStatus.PENDING_CONFIRMATION,
    )
    version = models.PositiveIntegerField(default=1)
    client_request_id = models.UUIDField(null=True, blank=True, unique=True)
    confirmation_request_id = models.UUIDField(null=True, blank=True, unique=True)
    initiated_by = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="initiated_sample_material_issues",
    )
    initiated_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="confirmed_sample_material_issues",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        db_table = "sample_material_issue"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=SampleMaterialIssueStatus.values),
                name="sample_issue_status_valid",
            ),
            models.CheckConstraint(condition=Q(version__gt=0), name="sample_issue_version_positive"),
        ]


class SampleMaterialIssueLine(TimeStampedModel):
    issue = models.ForeignKey(SampleMaterialIssue, on_delete=models.PROTECT, related_name="lines")
    line_key = models.UUIDField()
    raw_material = models.ForeignKey(
        "products.RawMaterialInformation",
        on_delete=models.PROTECT,
        related_name="sample_material_issue_lines",
    )
    unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        on_delete=models.PROTECT,
        related_name="sample_material_issue_lines",
    )
    category = models.CharField(max_length=30)
    name_snapshot = models.CharField(max_length=500)
    specification_snapshot = models.CharField(max_length=500, blank=True)
    material_snapshot = models.CharField(max_length=500, blank=True)
    color_snapshot = models.CharField(max_length=500, blank=True)
    requested_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    warehouse_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    arrived_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    available_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    issued_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    shortage_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        db_table = "sample_material_issue_line"
        ordering = ["issue", "id"]
        constraints = [
            models.UniqueConstraint(fields=["issue", "line_key"], name="sample_issue_line_key_uniq"),
            models.CheckConstraint(condition=Q(requested_quantity__gt=0), name="sample_issue_line_request_positive"),
            models.CheckConstraint(condition=Q(warehouse_quantity__gte=0), name="sample_issue_line_warehouse_nonnegative"),
            models.CheckConstraint(condition=Q(arrived_quantity__gte=0), name="sample_issue_line_arrived_nonnegative"),
            models.CheckConstraint(condition=Q(available_quantity__gte=0), name="sample_issue_line_available_nonnegative"),
            models.CheckConstraint(condition=Q(shortage_quantity__gte=0), name="sample_issue_line_shortage_nonnegative"),
            models.CheckConstraint(
                condition=Q(issued_quantity__isnull=True) | Q(issued_quantity__gte=0),
                name="sample_issue_line_issued_nonnegative",
            ),
        ]


class SampleCollaborator(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="collaborator_links")
    employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="sample_collaborator_links")

    class Meta:
        db_table = "sample_collaborator"
        constraints = [
            models.UniqueConstraint(fields=["sample_request", "employee"], name="sample_collaborator_unique"),
        ]


class SampleProduct(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="products")
    source_inquiry_item = models.ForeignKey(
        "inquiries.InquiryItem",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_products",
    )
    source_quotation_line = models.ForeignKey(
        "quotations.QuotationLine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_products",
    )
    line_number = models.PositiveIntegerField()
    category = models.ForeignKey(
        "reference_data.ProductCategory",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_products",
    )
    category_name_snapshot = models.CharField(max_length=150, blank=True)
    product = models.ForeignKey(
        "products.ProductInformation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_products",
    )
    product_name = models.CharField(max_length=500)
    specification = models.TextField(blank=True)
    product_number_snapshot = models.CharField(max_length=100, blank=True)
    product_code_snapshot = models.CharField(max_length=100, blank=True)
    item_number_snapshot = models.CharField(max_length=100, blank=True)
    material_snapshot = models.TextField(blank=True)
    product_image = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_product_images",
    )
    task_sheet_file = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_product_task_sheets",
    )
    length_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    armrest_width_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    seat_width_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    back_height_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    seat_height_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "sample_product"
        ordering = ["sample_request", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["sample_request", "line_number"], name="sample_product_line_uniq"),
            models.CheckConstraint(condition=Q(length_cm__isnull=True) | Q(length_cm__gt=0), name="sample_product_length_pos"),
            models.CheckConstraint(condition=Q(armrest_width_cm__isnull=True) | Q(armrest_width_cm__gt=0), name="sample_product_armrest_pos"),
            models.CheckConstraint(condition=Q(seat_width_cm__isnull=True) | Q(seat_width_cm__gt=0), name="sample_product_seat_width_pos"),
            models.CheckConstraint(condition=Q(back_height_cm__isnull=True) | Q(back_height_cm__gt=0), name="sample_product_back_height_pos"),
            models.CheckConstraint(condition=Q(seat_height_cm__isnull=True) | Q(seat_height_cm__gt=0), name="sample_product_seat_height_pos"),
        ]
        indexes = [
            models.Index(fields=["source_inquiry_item", "line_number"], name="sample_product_inquiry_idx"),
            models.Index(fields=["source_quotation_line", "line_number"], name="sample_product_quote_idx"),
            models.Index(fields=["product", "id"], name="sample_product_master_idx"),
        ]

    def __str__(self):
        return f"{self.sample_request.request_number} - {self.product_name}"


class SampleProductSamplingDetail(TimeStampedModel):
    sample_product = models.ForeignKey(
        SampleProduct,
        on_delete=models.PROTECT,
        related_name="sampling_details",
    )
    line_number = models.PositiveIntegerField()
    template_key = models.CharField(max_length=64, blank=True)
    detail_type = models.CharField(max_length=100)
    category_label = models.CharField(max_length=100, blank=True)
    is_selected = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    image_file = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_product_sampling_details",
    )

    class Meta:
        db_table = "sample_product_sampling_detail"
        ordering = ["sample_product", "line_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["sample_product", "line_number"],
                name="sample_product_sampling_detail_line_uniq",
            ),
        ]


class SampleItem(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="items")
    sample_product = models.ForeignKey(
        SampleProduct,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="details",
    )
    source_inquiry_item = models.ForeignKey(
        "inquiries.InquiryItem",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_items",
    )
    source_quotation_line = models.ForeignKey(
        "quotations.QuotationLine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_items",
    )
    line_number = models.PositiveIntegerField()
    product_description_snapshot = models.CharField(max_length=500)
    specification_snapshot = models.TextField(blank=True)
    requested_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    unit_code = models.CharField(max_length=30, validators=[uppercase_code_validator])
    product_color = models.ForeignKey(
        "reference_data.ProductColor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_items",
    )
    color_card_snapshot = models.CharField(max_length=100, blank=True)
    color_name_snapshot = models.CharField(max_length=200, blank=True)
    color_code_snapshot = models.CharField(max_length=100, blank=True)
    tolerance = models.CharField(max_length=30, choices=SampleTolerance.choices, default=SampleTolerance.NONE)
    sample_quantity = models.PositiveIntegerField(null=True, blank=True)
    cutting_reported_quantity = models.PositiveIntegerField(default=0)
    metalwork_reported_quantity = models.PositiveIntegerField(default=0)
    cutting_completed = models.BooleanField(default=False)
    metalwork_completed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "sample_item"
        ordering = ["sample_request", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["sample_request", "line_number"], name="sample_item_line_uniq"),
            models.CheckConstraint(condition=Q(requested_quantity__gt=0), name="sample_item_qty_positive"),
            models.CheckConstraint(
                condition=Q(sample_quantity__isnull=True) | Q(cutting_reported_quantity__lte=F("sample_quantity")),
                name="sample_item_cutting_lte_qty",
            ),
            models.CheckConstraint(
                condition=Q(sample_quantity__isnull=True) | Q(metalwork_reported_quantity__lte=F("sample_quantity")),
                name="sample_item_metal_lte_qty",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.source_inquiry_item_id:
            if not self.sample_request.source_inquiry_id:
                errors["source_inquiry_item"] = "样品明细关联询价行时，样品申请必须有关联询价。"
            elif self.source_inquiry_item.inquiry_id != self.sample_request.source_inquiry_id:
                errors["source_inquiry_item"] = "来源询价行必须属于样品申请的来源询价。"
        if self.source_quotation_line_id:
            if not self.sample_request.source_quotation_version_id:
                errors["source_quotation_line"] = "样品明细关联报价行时，样品申请必须有关联报价版本。"
            elif self.source_quotation_line.quotation_version_id != self.sample_request.source_quotation_version_id:
                errors["source_quotation_line"] = "来源报价行必须属于样品申请的来源报价版本。"
        if errors:
            raise ValidationError(errors)


class SampleWorkflowRecord(TimeStampedModel):
    sample_request = models.ForeignKey(
        SampleRequest,
        on_delete=models.PROTECT,
        related_name="workflow_records",
    )
    stage = models.CharField(max_length=40, choices=SampleWorkflowStage.choices)
    business_file = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_workflow_records",
    )
    note = models.TextField(blank=True)
    operated_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_workflow_operations",
    )
    operated_at = models.DateTimeField()

    class Meta:
        db_table = "sample_workflow_record"
        ordering = ["operated_at", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sample_request", "stage"],
                name="sample_workflow_stage_uniq",
            ),
            models.CheckConstraint(
                condition=Q(stage__in=SampleWorkflowStage.values),
                name="sample_workflow_stage_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["sample_request", "operated_at", "id"],
                name="sample_workflow_timeline_idx",
            ),
        ]


class SampleFeeDecision(models.TextChoices):
    PENDING = "PENDING", "待决定"
    FREE = "FREE", "免费"
    PAID = "PAID", "收费"
    WAIVED = "WAIVED", "已减免"


class FeeVerificationStatus(models.TextChoices):
    PENDING = "PENDING", "待财务确认"
    NOT_REQUIRED = "NOT_REQUIRED", "无需确认"
    EVIDENCE_UPLOADED = "EVIDENCE_UPLOADED", "已上传凭证"
    MANUALLY_CONFIRMED = "MANUALLY_CONFIRMED", "已人工确认"
    REJECTED = "REJECTED", "凭证无效"


class FeeApprovalStatus(models.TextChoices):
    NOT_REQUIRED = "NOT_REQUIRED", "无需审批"
    PENDING = "PENDING", "待审批"
    APPROVED = "APPROVED", "审批通过"
    REJECTED = "REJECTED", "审批拒绝"


class FreightBearer(models.TextChoices):
    CUSTOMER = "CUSTOMER", "客户承担"
    COMPANY = "COMPANY", "我方承担"
    NEGOTIATED = "NEGOTIATED", "协商承担"


class SampleFeeRecord(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="fee_records")
    fee_decision = models.CharField(
        max_length=20,
        choices=SampleFeeDecision.choices,
        default=SampleFeeDecision.PENDING,
    )
    amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    currency_code = models.CharField(max_length=3, validators=[currency_code_validator])
    requested_decision = models.CharField(
        max_length=20,
        choices=SampleFeeDecision.choices,
        default=SampleFeeDecision.PENDING,
    )
    sample_fee_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    shipping_fee_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    payable_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    payment_terms = models.CharField(max_length=200, blank=True)
    freight_bearer = models.CharField(
        max_length=20,
        choices=FreightBearer.choices,
        blank=True,
    )
    payment_due_at = models.DateTimeField(null=True, blank=True)
    account_reference = models.CharField(max_length=200, blank=True)
    approval_status = models.CharField(
        max_length=20,
        choices=FeeApprovalStatus.choices,
        default=FeeApprovalStatus.NOT_REQUIRED,
    )
    free_confirmed_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_free_fee_confirmations",
    )
    verification_status = models.CharField(
        max_length=30,
        choices=FeeVerificationStatus.choices,
        default=FeeVerificationStatus.NOT_REQUIRED,
    )
    decision_reason = models.TextField(blank=True)
    decided_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_fee_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sample_fee_record"
        constraints = [
            models.CheckConstraint(
                condition=Q(fee_decision__in=SampleFeeDecision.values),
                name="sample_fee_decision_valid",
            ),
            models.CheckConstraint(
                condition=Q(verification_status__in=FeeVerificationStatus.values),
                name="sample_fee_verify_status_valid",
            ),
            models.CheckConstraint(condition=Q(amount__gte=0), name="sample_fee_amount_nonneg"),
            models.CheckConstraint(
                condition=Q(fee_decision=SampleFeeDecision.PAID, amount__gt=0)
                | Q(fee_decision__in=[SampleFeeDecision.FREE, SampleFeeDecision.WAIVED], amount=0)
                | Q(fee_decision=SampleFeeDecision.PENDING),
                name="sample_fee_decision_amount_match",
            ),
            models.UniqueConstraint(
                fields=["sample_request"],
                condition=Q(superseded_at__isnull=True),
                name="sample_fee_current_record_uniq",
            ),
        ]


class SampleShipmentStatus(models.TextChoices):
    PREPARING = "PREPARING", "准备中"
    SHIPPED = "SHIPPED", "已寄出"
    DELIVERED = "DELIVERED", "已送达"
    EXCEPTION = "EXCEPTION", "异常"
    CANCELLED = "CANCELLED", "已取消"


class ShipmentEventSource(models.TextChoices):
    MANUAL = "MANUAL", "人工录入"
    CARRIER = "CARRIER", "承运商同步"


class ShipmentEventType(models.TextChoices):
    SHIPPED = "SHIPPED", "已寄出"
    DELIVERED = "DELIVERED", "已签收"
    EXCEPTION = "EXCEPTION", "物流异常"
    PROGRESS = "PROGRESS", "物料进度更新"


class SampleShipment(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="shipments")
    shipped_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_shipments",
    )
    status = models.CharField(
        max_length=20,
        choices=SampleShipmentStatus.choices,
        default=SampleShipmentStatus.PREPARING,
    )
    carrier_code = models.CharField(max_length=50, blank=True, validators=[uppercase_code_validator])
    tracking_number = models.CharField(max_length=150, blank=True)
    recipient_snapshot = models.JSONField(default=dict)
    address_snapshot = models.JSONField(default=dict)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    fee_warning_acknowledged = models.BooleanField(default=False)
    fee_warning_acknowledged_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_fee_warnings_acknowledged",
    )
    fee_warning_acknowledged_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "sample_shipment"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=SampleShipmentStatus.values),
                name="sample_shipment_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["sample_request", "-shipped_at", "-id"], name="sample_shipment_history_idx"),
            models.Index(
                fields=["carrier_code", "tracking_number"],
                condition=~Q(tracking_number=""),
                name="sample_tracking_lookup_idx",
            ),
        ]


class SampleShipmentEvent(TimeStampedModel):
    """物流事件快照；第三方承运商接入后按事件标识做幂等写入。"""

    sample_shipment = models.ForeignKey(
        SampleShipment,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_type = models.CharField(max_length=20, choices=ShipmentEventType.choices)
    source = models.CharField(max_length=20, choices=ShipmentEventSource.choices)
    event_identifier = models.CharField(max_length=150)
    source_object_version = models.PositiveIntegerField(default=1)
    occurred_at = models.DateTimeField()
    synchronized_at = models.DateTimeField(null=True, blank=True)
    payload_snapshot = models.JSONField(default=dict, blank=True)
    recorded_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recorded_sample_shipment_events",
    )

    class Meta:
        db_table = "sample_shipment_event"
        ordering = ["-occurred_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sample_shipment", "event_identifier"],
                name="sample_shipment_event_identifier_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["sample_shipment", "-occurred_at", "-id"],
                name="sample_ship_event_hist_idx",
            ),
        ]


class SampleShipmentItem(TimeStampedModel):
    sample_shipment = models.ForeignKey(SampleShipment, on_delete=models.PROTECT, related_name="items")
    sample_item = models.ForeignKey(SampleItem, on_delete=models.PROTECT, related_name="shipment_items")
    shipped_quantity = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = "sample_shipment_item"
        constraints = [
            models.UniqueConstraint(
                fields=["sample_shipment", "sample_item"],
                name="sample_shipment_item_uniq",
            ),
            models.CheckConstraint(condition=Q(shipped_quantity__gt=0), name="sample_ship_item_qty_positive"),
        ]

    def clean(self):
        super().clean()
        if (
            self.sample_shipment_id
            and self.sample_item_id
            and self.sample_shipment.sample_request_id != self.sample_item.sample_request_id
        ):
            raise ValidationError({"sample_item": "寄送明细必须属于同一个样品申请。"})


class SampleFeedbackType(models.TextChoices):
    POSITIVE = "POSITIVE", "正向"
    NEUTRAL = "NEUTRAL", "一般"
    NEGATIVE = "NEGATIVE", "负向"
    FOLLOW_UP = "FOLLOW_UP", "需继续跟进"


class FeedbackConfirmationResult(models.TextChoices):
    PENDING = "PENDING", "待确认"
    PASSED = "PASSED", "确认通过"
    REJECTED = "REJECTED", "确认未通过"


class FeedbackConfirmationSource(models.TextChoices):
    CUSTOMER = "CUSTOMER", "客户确认"
    QUALITY = "QUALITY", "质检确认"
    MANUAL = "MANUAL", "人工录入"


class SampleFeedback(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="feedback_records")
    customer_contact = models.ForeignKey(
        "customers.CustomerContact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_feedback_records",
    )
    recorded_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recorded_sample_feedback",
    )
    feedback_type = models.CharField(max_length=20, choices=SampleFeedbackType.choices)
    feedback_content = models.TextField()
    occurred_at = models.DateTimeField()
    confirmation_result = models.CharField(
        max_length=20,
        choices=FeedbackConfirmationResult.choices,
        default=FeedbackConfirmationResult.PENDING,
    )
    confirmation_source = models.CharField(
        max_length=20,
        choices=FeedbackConfirmationSource.choices,
        default=FeedbackConfirmationSource.MANUAL,
    )
    source_object_version = models.PositiveIntegerField(default=1)
    rejection_reason = models.TextField(blank=True)
    corrective_action_request = models.TextField(blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    requotation_source_version = models.ForeignKey(
        "quotations.QuotationVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_feedback_requotation_sources",
    )
    resulting_quotation_version = models.OneToOneField(
        "quotations.QuotationVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_sample_feedback",
    )
    requotation_created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_sample_feedback_requotations",
    )
    requotation_created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sample_feedback"
        indexes = [models.Index(fields=["sample_request", "-occurred_at", "-id"], name="sample_feedback_history_idx")]

    def clean(self):
        super().clean()
        errors = {}
        customer_id = self.sample_request.customer_account_id
        if self.requotation_source_version_id:
            source_customer_id = self.requotation_source_version.quotation.customer_account_id
            if source_customer_id != customer_id:
                errors["requotation_source_version"] = "再报价复制来源必须属于样品客户。"
        if self.resulting_quotation_version_id:
            result_customer_id = self.resulting_quotation_version.quotation.customer_account_id
            if result_customer_id != customer_id:
                errors["resulting_quotation_version"] = "再报价结果必须属于样品客户。"
            if not self.requotation_source_version_id:
                errors["requotation_source_version"] = "记录再报价结果时必须保留复制来源版本。"
        if errors:
            raise ValidationError(errors)


class SampleTaskLink(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="task_links")
    business_task = models.ForeignKey("workflow.BusinessTask", on_delete=models.PROTECT, related_name="sample_links")
    is_primary_source = models.BooleanField(default=True)

    class Meta:
        db_table = "sample_task_link"
        constraints = [
            models.UniqueConstraint(fields=["sample_request", "business_task"], name="sample_task_link_uniq"),
            models.UniqueConstraint(
                fields=["business_task"],
                condition=Q(is_primary_source=True),
                name="sample_task_primary_uniq",
            ),
        ]


class SampleSlaLink(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="sla_links")
    sla_tracking = models.OneToOneField(
        "workflow.SlaTracking",
        on_delete=models.PROTECT,
        related_name="sample_link",
    )

    class Meta:
        db_table = "sample_sla_link"


class SampleApprovalLink(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="approval_links")
    approval_request = models.OneToOneField(
        "workflow.ApprovalRequest",
        on_delete=models.PROTECT,
        related_name="sample_link",
    )

    class Meta:
        db_table = "sample_approval_link"


class SampleFileLink(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="file_links")
    business_file = models.ForeignKey("files.BusinessFile", on_delete=models.PROTECT, related_name="sample_links")
    file_role = models.CharField(max_length=50, validators=[uppercase_code_validator])

    class Meta:
        db_table = "sample_file_link"
        constraints = [
            models.UniqueConstraint(fields=["sample_request", "business_file"], name="sample_file_link_uniq"),
        ]


class SampleParameterImage(ArchivableModel):
    """新版样品参数图片；一张图片一条记录，删除采用软归档。"""

    sample_request = models.ForeignKey(
        SampleRequest,
        on_delete=models.PROTECT,
        related_name="parameter_images",
    )
    parameter_type = models.CharField(max_length=20, choices=SampleParameterType.choices)
    business_file = models.ForeignKey(
        "files.BusinessFile",
        on_delete=models.PROTECT,
        related_name="sample_parameter_images",
    )
    uploaded_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_sample_parameter_images",
    )
    uploaded_at = models.DateTimeField()

    class Meta:
        db_table = "sample_parameter_image"
        ordering = ["parameter_type", "uploaded_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(parameter_type__in=SampleParameterType.values),
                name="sample_parameter_image_type_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["sample_request", "parameter_type", "archived_at", "uploaded_at"],
                name="sample_param_image_active_idx",
            ),
        ]


class SampleInventoryReceipt(TimeStampedModel):
    receipt_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    submitted_by_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="submitted_sample_inventory_receipts",
    )
    submitted_at = models.DateTimeField()

    class Meta:
        db_table = "sample_inventory_receipt"
        ordering = ["-submitted_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=uppercase_code_condition("receipt_number"),
                name="sample_inventory_receipt_no_upper",
            ),
        ]
        indexes = [
            models.Index(fields=["-submitted_at", "-id"], name="sample_inv_receipt_time_idx"),
        ]

    def __str__(self):
        return self.receipt_number


class SampleInventoryLine(TimeStampedModel):
    receipt = models.ForeignKey(
        SampleInventoryReceipt,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    sample_item = models.ForeignKey(
        SampleItem,
        on_delete=models.PROTECT,
        related_name="inventory_lines",
    )
    category_name_snapshot = models.CharField(max_length=150, blank=True)
    product_name_snapshot = models.CharField(max_length=500)
    specification_snapshot = models.TextField(blank=True)
    color_name_snapshot = models.CharField(max_length=200, blank=True)
    sampling_quantity = models.PositiveIntegerField()
    received_quantity = models.PositiveIntegerField()
    outbound_quantity = models.PositiveIntegerField(default=0)
    loaned_quantity = models.PositiveIntegerField(default=0)
    location = models.CharField(max_length=150, default="样品库")

    class Meta:
        db_table = "sample_inventory_line"
        ordering = ["-receipt__submitted_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["receipt", "sample_item"],
                name="sample_inventory_receipt_item_uniq",
            ),
            models.CheckConstraint(
                condition=Q(sampling_quantity__gt=0),
                name="sample_inventory_sampling_qty_pos",
            ),
            models.CheckConstraint(
                condition=Q(received_quantity__gt=0),
                name="sample_inventory_received_qty_pos",
            ),
            models.CheckConstraint(
                condition=Q(received_quantity__lte=F("sampling_quantity")),
                name="sample_inventory_received_lte_sampled",
            ),
            models.CheckConstraint(
                condition=Q(received_quantity__gte=F("outbound_quantity") + F("loaned_quantity")),
                name="sample_inventory_available_nonneg",
            ),
        ]
        indexes = [
            models.Index(fields=["location", "id"], name="sample_inventory_location_idx"),
            models.Index(fields=["sample_item", "id"], name="sample_inventory_item_idx"),
        ]


class SampleOutboundMethod(models.TextChoices):
    MERCHANDISER_MAIL = "MERCHANDISER_MAIL", "跟单员邮寄"
    SALESPERSON_CARRY = "SALESPERSON_CARRY", "业务员带走"
    OTHER = "OTHER", "其他"


class SampleInventoryOutbound(TimeStampedModel):
    outbound_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    operated_by_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="sample_inventory_outbounds",
    )
    operated_at = models.DateTimeField()

    class Meta:
        db_table = "sample_inventory_outbound"
        ordering = ["-operated_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=uppercase_code_condition("outbound_number"),
                name="sample_outbound_number_upper",
            ),
        ]
        indexes = [
            models.Index(fields=["-operated_at", "-id"], name="sample_outbound_time_idx"),
        ]

    def __str__(self):
        return self.outbound_number


class SampleInventoryOutboundLine(TimeStampedModel):
    outbound = models.ForeignKey(
        SampleInventoryOutbound,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    inventory_line = models.ForeignKey(
        SampleInventoryLine,
        on_delete=models.PROTECT,
        related_name="outbound_lines",
    )
    outbound_quantity = models.PositiveIntegerField()
    outbound_method = models.CharField(max_length=30, choices=SampleOutboundMethod.choices)
    courier_company = models.CharField(max_length=150, blank=True)
    tracking_number = models.CharField(max_length=150, blank=True)
    remark = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "sample_inventory_outbound_line"
        ordering = ["-outbound__operated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["outbound", "inventory_line"],
                name="sample_outbound_inventory_line_uniq",
            ),
            models.CheckConstraint(
                condition=Q(outbound_quantity__gt=0),
                name="sample_outbound_quantity_pos",
            ),
            models.CheckConstraint(
                condition=Q(outbound_method__in=SampleOutboundMethod.values),
                name="sample_outbound_method_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(outbound_method=SampleOutboundMethod.MERCHANDISER_MAIL)
                    & ~Q(courier_company="")
                    & ~Q(tracking_number="")
                )
                | Q(outbound_method=SampleOutboundMethod.SALESPERSON_CARRY)
                | (Q(outbound_method=SampleOutboundMethod.OTHER) & ~Q(remark="")),
                name="sample_outbound_method_fields",
            ),
        ]
        indexes = [
            models.Index(fields=["outbound_method", "id"], name="sample_outbound_method_idx"),
            models.Index(fields=["inventory_line", "id"], name="sample_outbound_inventory_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.outbound_method == SampleOutboundMethod.MERCHANDISER_MAIL:
            if not self.courier_company.strip():
                errors["courier_company"] = "跟单员邮寄时必须填写快递公司。"
            if not self.tracking_number.strip():
                errors["tracking_number"] = "跟单员邮寄时必须填写快递单号。"
        elif self.outbound_method == SampleOutboundMethod.OTHER and not self.remark.strip():
            errors["remark"] = "出库方式为其他时必须填写备注。"
        if errors:
            raise ValidationError(errors)


class SampleInventoryLoan(TimeStampedModel):
    loan_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    operated_by_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="sample_inventory_loans",
    )
    operated_at = models.DateTimeField()

    class Meta:
        db_table = "sample_inventory_loan"
        ordering = ["-operated_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=uppercase_code_condition("loan_number"),
                name="sample_loan_number_upper",
            ),
        ]
        indexes = [
            models.Index(fields=["-operated_at", "-id"], name="sample_loan_time_idx"),
        ]

    def __str__(self):
        return self.loan_number


class SampleInventoryLoanLine(TimeStampedModel):
    loan = models.ForeignKey(
        SampleInventoryLoan,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    inventory_line = models.ForeignKey(
        SampleInventoryLine,
        on_delete=models.PROTECT,
        related_name="loan_lines",
    )
    loan_quantity = models.PositiveIntegerField()
    borrower_name = models.CharField(max_length=150)
    purpose_note = models.CharField(max_length=500)

    class Meta:
        db_table = "sample_inventory_loan_line"
        ordering = ["-loan__operated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "inventory_line"],
                name="sample_loan_inventory_line_uniq",
            ),
            models.CheckConstraint(
                condition=Q(loan_quantity__gt=0),
                name="sample_loan_quantity_pos",
            ),
            models.CheckConstraint(
                condition=~Q(borrower_name=""),
                name="sample_loan_borrower_required",
            ),
            models.CheckConstraint(
                condition=~Q(purpose_note=""),
                name="sample_loan_purpose_required",
            ),
        ]
        indexes = [
            models.Index(fields=["borrower_name", "id"], name="sample_loan_borrower_idx"),
            models.Index(fields=["inventory_line", "id"], name="sample_loan_inventory_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if not self.borrower_name.strip():
            errors["borrower_name"] = "必须填写借用人。"
        if not self.purpose_note.strip():
            errors["purpose_note"] = "必须填写用途或备注。"
        if errors:
            raise ValidationError(errors)
