from django.contrib.auth.models import Permission
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeBoundary, RangeOperators
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.core.models import (
    ArchivableModel,
    DateTimeRange,
    TimeStampedModel,
    country_code_validator,
    uppercase_code_condition,
    uppercase_code_validator,
)


class CustomerLifecycleStage(models.TextChoices):
    PROSPECT = "PROSPECT", "潜在客户"
    ACTIVE = "ACTIVE", "活跃客户"
    DORMANT = "DORMANT", "沉默客户"
    CLOSED = "CLOSED", "停止合作"


class CustomerAccount(ArchivableModel):
    account_code = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    account_name = models.CharField(max_length=250)
    english_name = models.CharField(max_length=250, blank=True)
    short_name = models.CharField(max_length=150, blank=True)
    lifecycle_stage = models.CharField(
        max_length=20,
        choices=CustomerLifecycleStage.choices,
        default=CustomerLifecycleStage.PROSPECT,
    )
    primary_country_code = models.CharField(
        max_length=2,
        blank=True,
        validators=[country_code_validator],
        help_text="销售管理使用的商业归属国家，不等同于注册国或收货地址。",
    )
    primary_website_url = models.URLField(max_length=500, blank=True)
    source_system = models.CharField(max_length=50, blank=True, validators=[uppercase_code_validator])
    external_id = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "customer_account"
        permissions = [
            ("view_all_customer", "可查看全部客户"),
            ("transfer_customer", "可发起客户转移"),
            ("approve_customer_transfer", "可审批客户转移"),
            ("merge_customer", "可合并客户"),
            ("manage_customer_access", "可管理客户数据授权"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(lifecycle_stage__in=CustomerLifecycleStage.values),
                name="customer_lifecycle_valid",
            ),
            models.CheckConstraint(
                condition=uppercase_code_condition("account_code"),
                name="customer_account_code_uppercase",
            ),
            models.CheckConstraint(
                condition=Q(source_system="", external_id="")
                | (~Q(source_system="") & ~Q(external_id="")),
                name="customer_source_pair_consistent",
            ),
            models.UniqueConstraint(
                fields=["source_system", "external_id"],
                condition=~Q(source_system="") & ~Q(external_id=""),
                name="customer_external_source_uniq",
            ),
        ]
        indexes = [
            GinIndex(fields=["account_name"], opclasses=["gin_trgm_ops"], name="customer_name_trgm_idx"),
            GinIndex(fields=["english_name"], opclasses=["gin_trgm_ops"], name="customer_english_trgm_idx"),
            GinIndex(fields=["short_name"], opclasses=["gin_trgm_ops"], name="customer_short_trgm_idx"),
            models.Index(
                fields=["primary_country_code", "-updated_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="customer_country_active_idx",
            ),
            models.Index(
                fields=["lifecycle_stage", "-updated_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="customer_stage_active_idx",
            ),
            models.Index(
                fields=["-created_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="customer_created_active_idx",
            ),
        ]

    def __str__(self):
        return f"{self.account_code} - {self.account_name}"


class TransactionEntityType(models.TextChoices):
    COMPANY = "COMPANY", "公司"
    INDIVIDUAL = "INDIVIDUAL", "个人"
    OTHER = "OTHER", "其他"


class CustomerTransactionEntity(ArchivableModel):
    customer_account = models.ForeignKey(
        CustomerAccount,
        on_delete=models.PROTECT,
        related_name="transaction_entities",
    )
    entity_code = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    entity_type = models.CharField(
        max_length=20,
        choices=TransactionEntityType.choices,
        default=TransactionEntityType.COMPANY,
    )
    legal_name = models.CharField(max_length=250)
    english_legal_name = models.CharField(max_length=250, blank=True)
    registration_country_code = models.CharField(max_length=2, blank=True, validators=[country_code_validator])
    registration_number = models.CharField(max_length=100, blank=True)
    tax_country_code = models.CharField(max_length=2, blank=True, validators=[country_code_validator])
    tax_identifier = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "customer_transaction_entity"
        constraints = [
            models.CheckConstraint(
                condition=uppercase_code_condition("entity_code"),
                name="cust_entity_code_uppercase",
            ),
        ]
        indexes = [
            models.Index(
                fields=["customer_account", "legal_name", "id"],
                condition=Q(archived_at__isnull=True),
                name="cust_entity_account_active_idx",
            ),
            GinIndex(fields=["legal_name"], opclasses=["gin_trgm_ops"], name="cust_entity_name_trgm_idx"),
            models.Index(
                fields=["registration_country_code", "registration_number"],
                condition=~Q(registration_number="") & Q(archived_at__isnull=True),
                name="cust_entity_reg_lookup_idx",
            ),
            models.Index(
                fields=["tax_country_code", "tax_identifier"],
                condition=~Q(tax_identifier="") & Q(archived_at__isnull=True),
                name="cust_entity_tax_lookup_idx",
            ),
        ]

    def __str__(self):
        return f"{self.entity_code} - {self.legal_name}"


class TransactionEntityRoleType(models.TextChoices):
    CONTRACTING = "CONTRACTING", "签约主体"
    BILL_TO = "BILL_TO", "账单主体"
    SHIP_TO = "SHIP_TO", "收货主体"
    OTHER = "OTHER", "其他"


class CustomerTransactionEntityRole(TimeStampedModel):
    transaction_entity = models.ForeignKey(
        CustomerTransactionEntity,
        on_delete=models.PROTECT,
        related_name="entity_roles",
    )
    role_type = models.CharField(max_length=30, choices=TransactionEntityRoleType.choices)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "customer_transaction_entity_role"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gt=F("effective_from")),
                name="cust_entity_role_valid_range",
            ),
            ExclusionConstraint(
                name="cust_entity_role_no_overlap",
                expressions=[
                    ("transaction_entity", RangeOperators.EQUAL),
                    ("role_type", RangeOperators.EQUAL),
                    (DateTimeRange("effective_from", "effective_to", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
            ),
        ]


class CustomerEntityAddress(ArchivableModel):
    transaction_entity = models.ForeignKey(
        CustomerTransactionEntity,
        on_delete=models.PROTECT,
        related_name="addresses",
    )
    address_code = models.CharField(max_length=50, validators=[uppercase_code_validator])
    label = models.CharField(max_length=150, blank=True)
    country_code = models.CharField(max_length=2, validators=[country_code_validator])
    state_province = models.CharField(max_length=150, blank=True)
    city = models.CharField(max_length=150, blank=True)
    postal_code = models.CharField(max_length=30, blank=True)
    address_line1 = models.CharField(max_length=250)
    address_line2 = models.CharField(max_length=250, blank=True)
    recipient_name = models.CharField(max_length=150, blank=True)
    recipient_phone = models.CharField(max_length=50, blank=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        db_table = "customer_entity_address"
        constraints = [
            models.CheckConstraint(
                condition=uppercase_code_condition("address_code"),
                name="cust_address_code_uppercase",
            ),
            models.UniqueConstraint(
                fields=["transaction_entity", "address_code"],
                name="cust_entity_address_code_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["transaction_entity", "address_code", "id"],
                condition=Q(archived_at__isnull=True),
                name="cust_address_entity_active_idx",
            ),
        ]


class AddressUsageType(models.TextChoices):
    REGISTERED = "REGISTERED", "注册地址"
    BILLING = "BILLING", "账单地址"
    SHIPPING = "SHIPPING", "收货地址"
    SAMPLE = "SAMPLE", "样品地址"
    OTHER = "OTHER", "其他"


class CustomerEntityAddressUsage(TimeStampedModel):
    entity_address = models.ForeignKey(
        CustomerEntityAddress,
        on_delete=models.PROTECT,
        related_name="usages",
    )
    usage_type = models.CharField(max_length=30, choices=AddressUsageType.choices)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "customer_entity_address_usage"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gt=F("effective_from")),
                name="cust_address_usage_valid_range",
            ),
            ExclusionConstraint(
                name="cust_address_usage_no_overlap",
                expressions=[
                    ("entity_address", RangeOperators.EQUAL),
                    ("usage_type", RangeOperators.EQUAL),
                    (DateTimeRange("effective_from", "effective_to", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
            ),
        ]


class ContactStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "有效"
    INACTIVE = "INACTIVE", "停用"
    LEFT = "LEFT", "已离职"


class CustomerContact(ArchivableModel):
    customer_account = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name="contacts")
    transaction_entity = models.ForeignKey(
        CustomerTransactionEntity,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="contacts",
    )
    source_contact = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="successor_contacts",
    )
    display_name = models.CharField(max_length=150)
    position_title = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=20, choices=ContactStatus.choices, default=ContactStatus.ACTIVE)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "customer_contact"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ContactStatus.values), name="contact_status_valid"),
            models.CheckConstraint(condition=~Q(id=F("source_contact_id")), name="contact_source_not_self"),
        ]
        indexes = [
            models.Index(
                fields=["customer_account", "display_name", "id"],
                condition=Q(archived_at__isnull=True),
                name="contact_account_active_idx",
            ),
            models.Index(
                fields=["transaction_entity", "display_name", "id"],
                condition=Q(transaction_entity__isnull=False, archived_at__isnull=True),
                name="contact_entity_active_idx",
            ),
            GinIndex(fields=["display_name"], opclasses=["gin_trgm_ops"], name="contact_name_trgm_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.transaction_entity_id and self.transaction_entity.customer_account_id != self.customer_account_id:
            errors["transaction_entity"] = "联系人和交易主体必须属于同一客户账户。"
        if self.source_contact_id and self.source_contact.customer_account_id != self.customer_account_id:
            errors["source_contact"] = "新旧联系人必须属于同一客户账户。"
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.display_name


class ContactMethodType(models.TextChoices):
    EMAIL = "EMAIL", "邮箱"
    PHONE = "PHONE", "电话"
    MOBILE = "MOBILE", "手机"
    WECHAT = "WECHAT", "微信"
    WHATSAPP = "WHATSAPP", "WhatsApp"
    OTHER = "OTHER", "其他"


class CustomerContactMethod(ArchivableModel):
    customer_contact = models.ForeignKey(CustomerContact, on_delete=models.PROTECT, related_name="methods")
    method_type = models.CharField(max_length=20, choices=ContactMethodType.choices)
    raw_value = models.CharField(max_length=255)
    normalized_value = models.CharField(max_length=255)
    normalization_version = models.PositiveSmallIntegerField(default=1)
    normalized_at = models.DateTimeField()
    is_primary = models.BooleanField(default=False)
    is_preferred = models.BooleanField(default=False)
    verification_status = models.CharField(max_length=20, default="UNVERIFIED")

    class Meta:
        db_table = "customer_contact_method"
        constraints = [
            models.UniqueConstraint(
                fields=["customer_contact", "method_type"],
                condition=Q(is_primary=True, archived_at__isnull=True),
                name="contact_method_primary_uniq",
            ),
            models.UniqueConstraint(
                fields=["customer_contact", "method_type"],
                condition=Q(is_preferred=True, archived_at__isnull=True),
                name="contact_method_preferred_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["method_type", "normalized_value"],
                condition=Q(archived_at__isnull=True),
                name="contact_method_lookup_idx",
            ),
        ]


class ContactRoleType(models.TextChoices):
    DECISION_MAKER = "DECISION_MAKER", "决策人"
    BUYER = "BUYER", "采购联系人"
    TECHNICAL = "TECHNICAL", "技术联系人"
    FINANCE = "FINANCE", "财务联系人"
    LOGISTICS = "LOGISTICS", "物流联系人"
    OTHER = "OTHER", "其他"


class CustomerContactRole(TimeStampedModel):
    customer_contact = models.ForeignKey(CustomerContact, on_delete=models.PROTECT, related_name="roles")
    role_type = models.CharField(max_length=30, choices=ContactRoleType.choices)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "customer_contact_role"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gt=F("effective_from")),
                name="contact_role_valid_range",
            ),
            ExclusionConstraint(
                name="contact_role_no_overlap",
                expressions=[
                    ("customer_contact", RangeOperators.EQUAL),
                    ("role_type", RangeOperators.EQUAL),
                    (DateTimeRange("effective_from", "effective_to", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
            ),
        ]
        indexes = [models.Index(fields=["customer_contact", "-effective_from", "-id"], name="contact_role_history_idx")]


class AssignmentRole(models.TextChoices):
    PRIMARY_OWNER = "PRIMARY_OWNER", "主负责人"
    COLLABORATOR = "COLLABORATOR", "协作人"


class CustomerAssignment(TimeStampedModel):
    customer_account = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name="assignments")
    employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="customer_assignments",
    )
    assignment_role = models.CharField(max_length=30, choices=AssignmentRole.choices)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    assigned_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_assignments_created",
    )
    reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "customer_assignment"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gt=F("effective_from")),
                name="customer_assignment_valid_range",
            ),
            ExclusionConstraint(
                name="customer_primary_owner_no_overlap",
                expressions=[
                    ("customer_account", RangeOperators.EQUAL),
                    (DateTimeRange("effective_from", "effective_to", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
                condition=Q(assignment_role=AssignmentRole.PRIMARY_OWNER),
            ),
        ]
        indexes = [
            models.Index(
                fields=["employee", "assignment_role", "customer_account"],
                condition=Q(effective_to__isnull=True),
                name="cust_assign_current_emp_idx",
            ),
            models.Index(fields=["customer_account", "-effective_from", "-id"], name="cust_assign_history_idx"),
        ]


class TransferStatus(models.TextChoices):
    PENDING = "PENDING", "待处理"
    APPROVED = "APPROVED", "已通过"
    REJECTED = "REJECTED", "已拒绝"
    CANCELLED = "CANCELLED", "已取消"


class CustomerTransferRequest(TimeStampedModel):
    customer_account = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name="transfer_requests")
    from_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="customer_transfers_from",
    )
    to_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="customer_transfers_to",
    )
    requested_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_transfer_requests_created",
    )
    decided_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_transfer_requests_decided",
    )
    status = models.CharField(max_length=20, choices=TransferStatus.choices, default=TransferStatus.PENDING)
    request_reason = models.TextField()
    decision_note = models.TextField(blank=True)
    submitted_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "customer_transfer_request"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=TransferStatus.values), name="cust_transfer_status_valid"),
            models.CheckConstraint(condition=~Q(from_employee=F("to_employee")), name="cust_transfer_different_emp"),
        ]
        indexes = [
            models.Index(
                fields=["status", "submitted_at", "id"],
                condition=Q(status=TransferStatus.PENDING),
                name="cust_transfer_pending_idx",
            ),
            models.Index(fields=["customer_account", "-submitted_at", "-id"], name="cust_transfer_history_idx"),
        ]


class CustomerAttentionReview(TimeStampedModel):
    customer_account = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name="attention_reviews")
    attention_level_item = models.ForeignKey(
        "reference_data.ReferenceDictionary",
        on_delete=models.PROTECT,
        related_name="customer_attention_reviews",
    )
    reviewed_by_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="customer_attention_reviews",
    )
    reason = models.TextField()
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "customer_attention_review"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gt=F("effective_from")),
                name="cust_attention_valid_range",
            ),
            ExclusionConstraint(
                name="cust_attention_no_overlap",
                expressions=[
                    ("customer_account", RangeOperators.EQUAL),
                    (DateTimeRange("effective_from", "effective_to", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
            ),
        ]
        indexes = [
            models.Index(
                fields=["attention_level_item", "customer_account"],
                condition=Q(effective_to__isnull=True),
                name="cust_attention_current_idx",
            ),
            models.Index(fields=["customer_account", "-effective_from", "-id"], name="cust_attention_history_idx"),
        ]


class HistoricalConfirmationStatus(models.TextChoices):
    PENDING = "PENDING", "待确认"
    CONFIRMED = "CONFIRMED", "已确认"
    REJECTED = "REJECTED", "已否决"


class CustomerHistoricalTransactionConfirmation(TimeStampedModel):
    customer_account = models.ForeignKey(
        CustomerAccount,
        on_delete=models.PROTECT,
        related_name="historical_transaction_confirmations",
    )
    confirmed_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="historical_customer_confirmations",
    )
    status = models.CharField(
        max_length=20,
        choices=HistoricalConfirmationStatus.choices,
        default=HistoricalConfirmationStatus.PENDING,
    )
    basis_note = models.TextField()
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "customer_historical_transaction_confirmation"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=HistoricalConfirmationStatus.values),
                name="cust_history_confirm_status_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "created_at", "id"],
                condition=Q(status=HistoricalConfirmationStatus.PENDING),
                name="cust_history_confirm_queue_idx",
            ),
            models.Index(fields=["customer_account", "-created_at", "-id"], name="cust_history_confirm_idx"),
        ]


class DuplicateCaseStatus(models.TextChoices):
    OPEN = "OPEN", "待处理"
    REVIEWING = "REVIEWING", "审核中"
    RESOLVED = "RESOLVED", "已解决"
    DISMISSED = "DISMISSED", "已忽略"


class CustomerDuplicateCase(TimeStampedModel):
    reviewer_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_duplicate_cases",
    )
    status = models.CharField(max_length=20, choices=DuplicateCaseStatus.choices, default=DuplicateCaseStatus.OPEN)
    matching_strategy_version = models.CharField(max_length=50)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "customer_duplicate_case"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=DuplicateCaseStatus.values),
                name="cust_duplicate_case_status_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "created_at", "id"],
                condition=Q(status__in=[DuplicateCaseStatus.OPEN, DuplicateCaseStatus.REVIEWING]),
                name="cust_dup_case_open_idx",
            ),
            models.Index(fields=["reviewer_employee", "status", "created_at", "id"], name="cust_dup_reviewer_idx"),
        ]


class DuplicateDecision(models.TextChoices):
    PENDING = "PENDING", "待判断"
    DUPLICATE = "DUPLICATE", "重复"
    NOT_DUPLICATE = "NOT_DUPLICATE", "不重复"
    SURVIVOR = "SURVIVOR", "存续客户"


class CustomerDuplicateCandidate(TimeStampedModel):
    duplicate_case = models.ForeignKey(CustomerDuplicateCase, on_delete=models.PROTECT, related_name="candidates")
    customer_account = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name="duplicate_candidates")
    confidence_score = models.DecimalField(max_digits=5, decimal_places=4)
    matched_fields = models.JSONField(default=dict, blank=True)
    decision = models.CharField(max_length=20, choices=DuplicateDecision.choices, default=DuplicateDecision.PENDING)

    class Meta:
        db_table = "customer_duplicate_candidate"
        constraints = [
            models.CheckConstraint(condition=Q(decision__in=DuplicateDecision.values), name="cust_dup_decision_valid"),
            models.UniqueConstraint(fields=["duplicate_case", "customer_account"], name="cust_dup_candidate_uniq"),
            models.CheckConstraint(
                condition=Q(confidence_score__gte=0) & Q(confidence_score__lte=1),
                name="cust_dup_score_range",
            ),
        ]
        indexes = [
            models.Index(fields=["duplicate_case", "-confidence_score", "-id"], name="cust_dup_case_score_idx"),
            models.Index(fields=["customer_account", "-created_at", "-id"], name="cust_dup_account_idx"),
        ]


class MergeStatus(models.TextChoices):
    PLANNED = "PLANNED", "待执行"
    COMPLETED = "COMPLETED", "已完成"
    FAILED = "FAILED", "失败"
    ROLLED_BACK = "ROLLED_BACK", "已回退"


class CustomerMergeOperation(TimeStampedModel):
    duplicate_case = models.ForeignKey(
        CustomerDuplicateCase,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="merge_operations",
    )
    executed_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_merge_operations",
    )
    status = models.CharField(max_length=20, choices=MergeStatus.choices, default=MergeStatus.PLANNED)
    reason = models.TextField()
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "customer_merge_operation"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=MergeStatus.values), name="cust_merge_status_valid"),
        ]
        indexes = [models.Index(fields=["duplicate_case", "-created_at", "-id"], name="cust_merge_case_idx")]


class MergeMemberRole(models.TextChoices):
    SURVIVOR = "SURVIVOR", "存续客户"
    SOURCE = "SOURCE", "来源客户"


class CustomerMergeMember(TimeStampedModel):
    merge_operation = models.ForeignKey(CustomerMergeOperation, on_delete=models.PROTECT, related_name="members")
    customer_account = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name="merge_memberships")
    member_role = models.CharField(max_length=20, choices=MergeMemberRole.choices)

    class Meta:
        db_table = "customer_merge_member"
        constraints = [
            models.UniqueConstraint(fields=["merge_operation", "customer_account"], name="cust_merge_member_uniq"),
            models.UniqueConstraint(
                fields=["merge_operation"],
                condition=Q(member_role=MergeMemberRole.SURVIVOR),
                name="cust_merge_one_survivor_uniq",
            ),
        ]
        indexes = [models.Index(fields=["customer_account", "-created_at", "-id"], name="cust_merge_account_idx")]


class CustomerMergeChange(TimeStampedModel):
    merge_operation = models.ForeignKey(CustomerMergeOperation, on_delete=models.PROTECT, related_name="changes")
    sequence_number = models.PositiveIntegerField()
    object_type = models.CharField(max_length=80, validators=[uppercase_code_validator])
    object_id = models.UUIDField()
    change_data = models.JSONField(default=dict)

    class Meta:
        db_table = "customer_merge_change"
        constraints = [
            models.UniqueConstraint(fields=["merge_operation", "sequence_number"], name="cust_merge_change_seq_uniq"),
        ]
        ordering = ["merge_operation", "sequence_number"]


class CustomerDataAccessGrant(TimeStampedModel):
    employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="customer_data_grants",
    )
    customer_account = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name="data_grants")
    permission = models.ForeignKey(Permission, on_delete=models.PROTECT, related_name="customer_data_grants")
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    granted_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_data_grants_created",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_data_grants_revoked",
    )
    reason = models.CharField(max_length=500)

    class Meta:
        db_table = "customer_data_access_grant"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gt=F("effective_from")),
                name="cust_grant_valid_range",
            ),
            ExclusionConstraint(
                name="cust_grant_no_overlap",
                expressions=[
                    ("employee", RangeOperators.EQUAL),
                    ("customer_account", RangeOperators.EQUAL),
                    ("permission", RangeOperators.EQUAL),
                    (DateTimeRange("effective_from", "effective_to", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "permission", "customer_account"], name="cust_grant_employee_idx"),
            models.Index(fields=["customer_account", "employee"], name="cust_grant_customer_idx"),
        ]


class CustomerFileLink(TimeStampedModel):
    customer_account = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name="file_links")
    business_file = models.ForeignKey("files.BusinessFile", on_delete=models.PROTECT, related_name="customer_links")
    file_role = models.CharField(max_length=50, validators=[uppercase_code_validator])

    class Meta:
        db_table = "customer_file_link"
        constraints = [
            models.UniqueConstraint(fields=["customer_account", "business_file"], name="customer_file_link_uniq"),
        ]


class CustomerTaskLink(TimeStampedModel):
    customer_account = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name="task_links")
    business_task = models.ForeignKey("workflow.BusinessTask", on_delete=models.PROTECT, related_name="customer_links")
    is_primary_source = models.BooleanField(default=True)

    class Meta:
        db_table = "customer_task_link"
        constraints = [
            models.UniqueConstraint(
                fields=["customer_account", "business_task"],
                name="customer_task_link_uniq",
            ),
            models.UniqueConstraint(
                fields=["business_task"],
                condition=Q(is_primary_source=True),
                name="customer_task_primary_uniq",
            ),
        ]
