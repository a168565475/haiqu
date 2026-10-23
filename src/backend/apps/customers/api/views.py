from apps.access_control import sales_policy
from apps.organizations.selectors import active_department_employees
from apps.access_control.sales_sources import filter_activity
import csv
import uuid
from datetime import timedelta
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from django.contrib.postgres.search import TrigramSimilarity
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.core.api.pagination import TimelineCursorPagination
from apps.core.audit import write_audit_log
from apps.crm.api.serializers import TimelineEventSerializer, TimelineQuerySerializer
from apps.crm.models import CommunicationTaskLink
from apps.inquiries.models import Inquiry, InquiryTaskLink
from apps.organizations.models import Employee
from apps.quotations.models import Quotation, QuotationVersionTaskLink
from apps.reference_data.models import Country, ReferenceDictionary
from apps.reference_data.services import legacy_dictionary_groups
from apps.samples.models import SampleRequest, SampleTaskLink
from apps.workflow.models import BusinessTask, TaskStatus

from ..models import (
    CustomerAccount,
    CustomerActivityReview,
    CustomerActivityStatus,
    CustomerAssignment,
    CustomerAttentionReview,
    CustomerBusinessSnapshot,
    CustomerContact,
    CustomerContactMethod,
    CustomerContactRole,
    CustomerRegion,
    CustomerComplaint,
    CustomerEntityAddress,
    CustomerEntityAddressUsage,
    CustomerGradeReview,
    CustomerSourceAttribution,
    CustomerTag,
    CustomerTaskLink,
    CustomerTransactionEntity,
    CustomerTransactionEntityRole,
)
from ..contact_selectors import contacts_with_list_context, customer_contact_summary, filter_contacts
from ..hard_delete import permanently_delete_contact, permanently_delete_customer
from ..contact_services import (
    bulk_create_contact_tasks,
    bulk_mark_contacts_left,
    create_contact,
    duplicate_summary,
    mark_contact_left,
    update_contact_profile,
    validate_contact_method_duplicate,
)
from ..selectors import accessible_customers, customers_with_current_context
from ..services import (
    add_collaborator,
    archive_resource,
    create_customer,
    end_collaborator,
    model_snapshot,
    prepare_contact_method,
    restore_customer,
    set_activity,
    set_attention,
    set_business_snapshot,
    set_classification,
    set_grade,
    set_source,
    update_customer,
    write_customer_timeline,
)
from .filters import CustomerFilter
from .contact_serializers import (
    ContactBulkMarkLeftSerializer,
    ContactBulkTaskSerializer,
    ContactDuplicateCheckSerializer,
    ContactEmploymentEventSerializer,
    ContactEmploymentRecordSerializer,
    ContactMarkLeftSerializer,
    ContactMethodReadSerializer,
    CustomerContactCreateSerializer,
    CustomerContactDetailSerializer,
    CustomerContactListSerializer,
    CustomerContactUpdateSerializer,
)
from .serializers import (
    AddressUsageSerializer,
    ActivitySetSerializer,
    ActivitySummarySerializer,
    ArchiveSerializer,
    AttentionSetSerializer,
    AttentionSummarySerializer,
    ClassificationSetSerializer,
    CollaboratorCreateSerializer,
    ContactMethodSerializer,
    ContactRoleSerializer,
    CustomerAddressSerializer,
    CustomerAssignmentSerializer,
    CustomerBusinessSnapshotSerializer,
    CustomerBulkTagSerializer,
    CustomerContactSerializer,
    CustomerCreateSerializer,
    CustomerDetailSerializer,
    CustomerListSerializer,
    CustomerOptionQuerySerializer,
    CustomerTagCreateSerializer,
    CustomerTagSummarySerializer,
    CustomerTransactionEntitySerializer,
    CustomerTypeSummarySerializer,
    CustomerUpdateSerializer,
    DuplicateCheckQuerySerializer,
    EntityRoleSerializer,
    GradeSetSerializer,
    GradeSummarySerializer,
    SourceSetSerializer,
    SourceSummarySerializer,
)


UUID_URL_REGEX = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class CustomerApiViewSetBase(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    lookup_value_regex = UUID_URL_REGEX

    def actor_employee(self):
        return getattr(self.request, "employee", None)

    def response_with_etag(self, data, instance, response_status=status.HTTP_200_OK):
        response = Response(data, status=response_status)
        response["ETag"] = etag_for_instance(instance)
        return response

    def action_permission_codename(self, default="view_customeraccount"):
        from apps.access_control.sales_policy import action_permission
        from apps.access_control import module_policy
        permission = module_policy.action_permission(self.request, self) if module_policy.enabled() and type(self).__name__ in module_policy.ACTION_OVERRIDES else action_permission(self.request, self)
        return permission.split(".", 1)[-1] if permission else default

    def raise_integrity_validation_error(self, exc):
        raise Conflict("数据与现有记录冲突，请检查编号、唯一标记或有效期是否重复。") from exc

    def audit_created(self, instance, serializer, object_type, customer):
        write_audit_log(
            object_type=object_type,
            object_id=instance.pk,
            context_type="CUSTOMER_ACCOUNT",
            context_id=customer.pk,
            action="CREATED",
            actor_employee=self.actor_employee(),
            after_data=serializer.data,
            request=self.request,
        )
        write_customer_timeline(
            customer=customer,
            event_type=f"{object_type}_CREATED",
            title="新增客户业务记录",
            source_type=object_type,
            source_id=instance.pk,
            actor_employee=self.actor_employee(),
        )

    def create_audited(self, serializer, object_type, customer, **save_kwargs):
        try:
            with transaction.atomic():
                instance = serializer.save(**save_kwargs)
                self.audit_created(instance, serializer, object_type, customer)
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return instance

    def update_instance(self, instance, serializer_class, object_type, customer):
        require_matching_etag(self.request, instance)
        try:
            with transaction.atomic():
                locked = instance.__class__.objects.select_for_update().get(pk=instance.pk)
                require_matching_etag(self.request, locked)
                before_data = model_snapshot(
                    locked,
                    [field.name for field in locked._meta.fields if field.name not in {"id", "updated_at"}],
                )
                serializer = serializer_class(
                    locked,
                    data=self.request.data,
                    partial=True,
                    context={**self.get_serializer_context(), "customer_account": customer},
                )
                serializer.is_valid(raise_exception=True)
                if not serializer.validated_data:
                    raise ValidationError({"detail": ["请至少提交一个需要修改的字段。"]})
                updated = serializer.save()
                write_audit_log(
                    object_type=object_type,
                    object_id=updated.pk,
                    context_type="CUSTOMER_ACCOUNT",
                    context_id=customer.pk,
                    action="UPDATED",
                    actor_employee=self.actor_employee(),
                    before_data=before_data,
                    after_data=serializer.data,
                    request=self.request,
                )
                write_customer_timeline(
                    customer=customer,
                    event_type=f"{object_type}_UPDATED",
                    title="更新客户业务记录",
                    source_type=object_type,
                    source_id=updated.pk,
                    actor_employee=self.actor_employee(),
                )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return updated


class CustomerViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = CustomerDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = CustomerFilter
    search_fields = ["account_code", "account_name", "english_name", "short_name"]
    ordering_fields = ["account_code", "account_name", "created_at", "updated_at"]
    ordering = ["-updated_at", "-id"]
    sales_action_permission_map = {"archive": "access_control.archive_customeraccount", "restore": "access_control.restore_customeraccount"}
    action_permission_map = {
        "list": "customers.view_customeraccount",
        "retrieve": "customers.view_customeraccount",
        "create": "customers.add_customeraccount",
        "destroy": "customers.delete_customeraccount",
        "partial_update": "customers.change_customeraccount",
        "archive": "customers.change_customeraccount",
        "restore": "customers.change_customeraccount",
        "summary": "customers.view_customeraccount",
        "timeline": "crm.view_customertimelineevent",
        "assignments": "customers.view_customerassignment",
        "collaborators.POST": "customers.add_customerassignment",
        "end_collaborator.POST": "customers.change_customerassignment",
        "entities.GET": "customers.view_customertransactionentity",
        "entities.POST": "customers.add_customertransactionentity",
        "contacts.GET": "customers.view_customercontact",
        "contacts.POST": "customers.add_customercontact",
        "attention_history": "customers.view_customerattentionreview",
        "set_attention": "customers.add_customerattentionreview",
        "options": "customers.view_customeraccount",
        "create_tag": "customers.add_customertag",
        "duplicate_check": "customers.view_customeraccount",
        "grade_history": "customers.view_customergradereview",
        "set_grade": "customers.add_customergradereview",
        "source_history": "customers.view_customersourceattribution",
        "set_source": "customers.add_customersourceattribution",
        "activity_history": "customers.view_customeractivityreview",
        "set_activity": "customers.add_customeractivityreview",
        "set_classification": "customers.change_customeraccount",
        "business_snapshot_history": "customers.view_customerbusinesssnapshot",
        "set_business_snapshot": "customers.add_customerbusinesssnapshot",
        "stats": "customers.view_customeraccount",
        "export": "customers.view_customeraccount",
        "bulk_add_tags": "customers.change_customeraccount",
    }

    def get_scope_permission(self):
        return self.action_permission_codename()

    def get_queryset(self):
        queryset = accessible_customers(self.request, self.get_scope_permission())
        if self.action != "restore":
            archived = self.request.query_params.get("archived", "false").lower()
            if archived == "true":
                queryset = queryset.filter(archived_at__isnull=False)
            elif archived != "all":
                queryset = queryset.filter(archived_at__isnull=True)
        return customers_with_current_context(queryset, request=self.request)

    def get_serializer_class(self):
        if self.action == "list":
            return CustomerListSerializer
        if self.action == "create":
            return CustomerCreateSerializer
        if self.action == "partial_update":
            return CustomerUpdateSerializer
        return CustomerDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            customer, _ = create_customer(
                validated_data=dict(serializer.validated_data),
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        customer = customers_with_current_context(CustomerAccount.objects.filter(pk=customer.pk), request=self.request).get()
        output = CustomerDetailSerializer(customer, context=self.get_serializer_context())
        return self.response_with_etag({"data": output.data}, customer, status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        customer = self.get_object()
        require_matching_etag(request, customer)
        return Response({"data": permanently_delete_customer(customer)})

    @extend_schema(
        request=CustomerTagCreateSerializer,
        responses={status.HTTP_201_CREATED: CustomerTagCreateSerializer},
    )
    @action(detail=False, methods=["post"], url_path="tags")
    def create_tag(self, request):
        serializer = CustomerTagCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                customer_tag = serializer.save(
                    tag_code=f"CUSTOM_{uuid.uuid4().hex[:12].upper()}"
                )
                write_audit_log(
                    object_type="CUSTOMER_TAG",
                    object_id=customer_tag.pk,
                    action="CREATED",
                    actor_employee=self.actor_employee(),
                    after_data=serializer.data,
                    request=request,
                )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return Response({"data": serializer.data}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        customers = accessible_customers(request, "view_customeraccount").filter(
            archived_at__isnull=True
        )
        employee = self.actor_employee()
        my_customers = customers.filter(
            assignments__employee=employee,
            assignments__assignment_role="PRIMARY_OWNER",
            assignments__effective_from__lte=now,
        ).filter(
            Q(assignments__effective_to__isnull=True) | Q(assignments__effective_to__gt=now)
        ).distinct()
        today_follow_up = customers.filter(
            task_links__business_task__archived_at__isnull=True,
            task_links__business_task__status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
            task_links__business_task__due_at__gte=today_start,
            task_links__business_task__due_at__lt=tomorrow_start,
        ).distinct()
        high_value = customers.filter(
            grade_reviews__grade_item__item_code="A",
            grade_reviews__effective_from__lte=now,
        ).filter(
            Q(grade_reviews__effective_to__isnull=True) | Q(grade_reviews__effective_to__gt=now)
        ).distinct()

        def activity_count(activity_status):
            return customers.filter(
                activity_reviews__activity_status=activity_status,
                activity_reviews__effective_from__lte=now,
            ).filter(
                Q(activity_reviews__effective_to__isnull=True)
                | Q(activity_reviews__effective_to__gt=now)
            ).distinct().count()

        return Response(
            {
                "data": {
                    "total": customers.count(),
                    "mine": my_customers.count(),
                    "today_follow_up": today_follow_up.count(),
                    "high_value": high_value.count(),
                    "high_risk": activity_count("HIGH_RISK"),
                    "dormant": activity_count("DORMANT"),
                    "high_value_definition": "CURRENT_GRADE_A",
                }
            }
        )

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        if queryset.count() > 5000:
            raise ValidationError({"detail": "单次最多导出 5000 条，请缩小筛选范围后重试。"})
        queryset = queryset[:5000]
        rows = CustomerListSerializer(queryset, many=True, context=self.get_serializer_context()).data
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(
            [
                "客户编号", "客户名称", "国家/地区", "客户等级", "来源", "负责人",
                "最近联系", "下次跟进", "人工客户价值", "币种", "活跃状态", "数据截止时间",
            ]
        )
        def safe_csv(value):
            text = "" if value is None else str(value)
            if text.startswith(("=", "+", "-", "@", "\t", "\r")):
                return f"'{text}"
            return text

        for row in rows:
            value = row.get("customer_value") or {}
            writer.writerow(
                [safe_csv(item) for item in [
                    row["account_code"], row["account_name"], row["primary_country_code"],
                    (row.get("customer_grade") or {}).get("display_name", ""),
                    (row.get("latest_source") or {}).get("display_name", ""),
                    (row.get("primary_owner") or {}).get("display_name", ""),
                    row.get("last_contact_at") or "", row.get("next_follow_up_at") or "",
                    value.get("customer_total_value") or "", value.get("currency_code") or "",
                    (row.get("activity") or {}).get("display_name", ""), value.get("as_of_at") or "",
                ]]
            )
        response["Content-Disposition"] = 'attachment; filename="customers.csv"'
        return response

    @action(detail=False, methods=["post"], url_path="bulk-add-tags")
    def bulk_add_tags(self, request):
        serializer = CustomerBulkTagSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer_ids = serializer.validated_data["customer_ids"]
        customers = list(
            accessible_customers(request, "change_customeraccount")
            .filter(pk__in=customer_ids, archived_at__isnull=True)
            .order_by("id")
        )
        if len(customers) != len(customer_ids):
            raise ValidationError({"customer_ids": "部分客户不存在、已归档或无权修改。"})
        selected_tags = serializer.validated_data["customer_tags"]
        reason = serializer.validated_data["reason"]
        with transaction.atomic():
            for customer in customers:
                current_tags = list(
                    CustomerTag.objects.filter(
                        customer_assignments__customer_account=customer,
                        customer_assignments__effective_from__lte=timezone.now(),
                    ).filter(
                        Q(customer_assignments__effective_to__isnull=True)
                        | Q(customer_assignments__effective_to__gt=timezone.now())
                    ).distinct()
                )
                tag_by_id = {tag.pk: tag for tag in [*current_tags, *selected_tags]}
                set_classification(
                    customer=customer,
                    customer_type_items=None,
                    customer_tags=list(tag_by_id.values()),
                    reason=reason,
                    actor_employee=self.actor_employee(),
                    request=request,
                )
        return Response({"data": {"updated_count": len(customers)}})

    @action(detail=False, methods=["get"])
    def options(self, request):
        query_serializer = CustomerOptionQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        keyword = query_serializer.validated_data.get("q", "").strip()
        grouped, _config_version = legacy_dictionary_groups(
            [
                "CUSTOMER_GRADE",
                "CUSTOMER_TYPE",
                "CUSTOMER_SOURCE",
                "CUSTOMER_INDUSTRY",
                "CUSTOMER_INTERESTED_PRODUCT",
            ]
        )
        def customer_dictionary_options(category_code):
            return [
                {
                    "id": item["id"],
                    "item_code": item["item_code"],
                    "display_name": item["display_name"],
                    "description": item["description"],
                }
                for item in grouped[category_code]
            ]

        employees = active_department_employees("DEPT_BUSINESS")
        if keyword:
            employees = employees.filter(
                Q(employee_code__icontains=keyword)
                | Q(display_name__icontains=keyword)
                | Q(email__icontains=keyword)
            )
        owner_options = [
            {
                "id": str(employee.pk),
                "employee_code": employee.employee_code,
                "display_name": employee.display_name,
                "email": employee.email,
            }
            for employee in employees.order_by("employee_code")[:50]
        ]
        tags = [
            {
                "id": str(customer_tag.pk),
                "tag_code": customer_tag.tag_code,
                "tag_name": customer_tag.tag_name,
                "color": customer_tag.color,
            }
            for customer_tag in CustomerTag.objects.filter(archived_at__isnull=True).order_by("tag_name")
        ]
        regions = CustomerRegion.objects.filter(
            is_active=True,
            archived_at__isnull=True,
        ).select_related("parent", "country").order_by("level", "parent__sort_order", "sort_order")
        primary_regions = [
            {
                "id": str(region.pk),
                "legacy_selector_code": region.legacy_selector_code,
                "legacy_tree_code": region.legacy_tree_code,
                "region_name": region.region_name,
            }
            for region in regions
            if region.level == 1
        ]
        secondary_regions = [
            {
                "id": str(region.pk),
                "parent_id": str(region.parent_id),
                "legacy_selector_code": region.legacy_selector_code,
                "legacy_tree_code": region.legacy_tree_code,
                "region_name": region.region_name,
                "country_code": region.country.code if region.country_id else "",
            }
            for region in regions
            if region.level == 2
        ]
        country_options = [
            {
                "id": str(country.pk),
                "item_code": country.code,
                "display_name": country.chinese_name,
                "description": country.english_name,
            }
            for country in Country.objects.filter(
                status="ACTIVE",
                archived_at__isnull=True,
            ).order_by("sort_order", "code")
        ]
        return Response(
            {
                "data": {
                    "lifecycle_stages": [
                        {"item_code": item_code, "display_name": display_name}
                        for item_code, display_name in CustomerAccount._meta.get_field("lifecycle_stage").choices
                    ],
                    "activity_statuses": [
                        {"item_code": item_code, "display_name": display_name}
                        for item_code, display_name in CustomerActivityStatus.choices
                    ],
                    "customer_grades": customer_dictionary_options("CUSTOMER_GRADE"),
                    "customer_types": customer_dictionary_options("CUSTOMER_TYPE"),
                    "customer_sources": customer_dictionary_options("CUSTOMER_SOURCE"),
                    "industries": customer_dictionary_options("CUSTOMER_INDUSTRY"),
                    "interested_products": customer_dictionary_options("CUSTOMER_INTERESTED_PRODUCT"),
                    "primary_regions": primary_regions,
                    "secondary_regions": secondary_regions,
                    "customer_tags": tags,
                    "owner_options": owner_options,
                    "country_options": country_options,
                }
            }
        )

    @action(detail=False, methods=["get"], url_path="duplicate-check")
    def duplicate_check(self, request):
        query_serializer = DuplicateCheckQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        query = query_serializer.validated_data
        name = query.get("name", "")
        website = query.get("website", "")
        country_code = query.get("country_code", "")
        exclude_customer_id = query.get("exclude_customer_id")
        website_host = self._website_host(website)

        candidates = accessible_customers(request, "view_customeraccount").filter(archived_at__isnull=True)
        if exclude_customer_id:
            candidates = candidates.exclude(pk=exclude_customer_id)
        if name:
            candidates = candidates.annotate(name_similarity=TrigramSimilarity("account_name", name))
            candidate_filter = Q(name_similarity__gte=0.2)
            if website_host:
                candidate_filter |= Q(primary_website_url__icontains=website_host)
            candidates = candidates.filter(candidate_filter).order_by("-name_similarity", "-updated_at")
        else:
            candidates = candidates.filter(primary_website_url__icontains=website_host).order_by("-updated_at")

        matches = []
        for candidate in candidates[:200]:
            name_ratio = 0
            if name:
                names = [candidate.account_name, candidate.english_name, candidate.short_name]
                name_ratio = max(
                    SequenceMatcher(None, name.casefold(), candidate_name.casefold()).ratio()
                    for candidate_name in names
                    if candidate_name
                )
            candidate_host = self._website_host(candidate.primary_website_url)
            website_exact = bool(website_host and candidate_host == website_host)
            country_exact = bool(country_code and candidate.primary_country_code == country_code)
            score = min(100, round(name_ratio * 70) + (80 if website_exact else 0) + (10 if country_exact else 0))
            if score < 30:
                continue
            matched_fields = []
            if name_ratio >= 0.8:
                matched_fields.append("NAME")
            if website_exact:
                matched_fields.append("WEBSITE")
            if country_exact:
                matched_fields.append("COUNTRY")
            matches.append(
                {
                    "customer_id": str(candidate.pk),
                    "account_code": candidate.account_code,
                    "account_name": candidate.account_name,
                    "primary_country_code": candidate.primary_country_code,
                    "primary_website_url": candidate.primary_website_url,
                    "lifecycle_stage": candidate.lifecycle_stage,
                    "match_score": score,
                    "match_level": "HIGH" if score >= 70 else "MEDIUM",
                    "matched_fields": matched_fields,
                }
            )
        matches.sort(key=lambda item: (-item["match_score"], item["account_code"]))
        matches = matches[:10]
        return Response(
            {
                "data": {
                    "has_high_risk_match": any(item["match_level"] == "HIGH" for item in matches),
                    "recommended_action": "REVIEW_BEFORE_CREATE" if matches else "CREATE_ALLOWED",
                    "matches": matches,
                }
            }
        )

    @staticmethod
    def _website_host(value):
        if not value:
            return ""
        normalized = value if "://" in value else f"https://{value}"
        hostname = (urlsplit(normalized).hostname or "").lower()
        return hostname[4:] if hostname.startswith("www.") else hostname

    def retrieve(self, request, *args, **kwargs):
        customer = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(customer).data}, customer)

    def partial_update(self, request, *args, **kwargs):
        customer = self.get_object()
        require_matching_etag(request, customer)
        serializer = self.get_serializer(customer, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            customer = update_customer(
                customer=customer,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        customer = customers_with_current_context(CustomerAccount.objects.filter(pk=customer.pk), request=self.request).get()
        output = CustomerDetailSerializer(customer, context=self.get_serializer_context())
        return self.response_with_etag({"data": output.data}, customer)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        customer = self.get_object()
        require_matching_etag(request, customer)
        serializer = ArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = archive_resource(
            instance=customer,
            reason=serializer.validated_data["reason"],
            actor_employee=self.actor_employee(),
            request=request,
            object_type="CUSTOMER_ACCOUNT",
            customer=customer,
        )
        customer = customers_with_current_context(CustomerAccount.objects.filter(pk=customer.pk), request=self.request).get()
        return self.response_with_etag({"data": CustomerDetailSerializer(customer, context=self.get_serializer_context()).data}, customer)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        customer = self.get_object()
        require_matching_etag(request, customer)
        customer = restore_customer(
            customer=customer,
            actor_employee=self.actor_employee(),
            request=request,
        )
        customer = customers_with_current_context(CustomerAccount.objects.filter(pk=customer.pk), request=self.request).get()
        return self.response_with_etag({"data": CustomerDetailSerializer(customer, context=self.get_serializer_context()).data}, customer)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        customer = self.get_object()
        active_inquiry_statuses = ["DRAFT", "SUBMITTED", "IN_PROGRESS", "QUOTED"]
        active_sample_statuses = ["DRAFT", "PENDING", "PREPARING", "SHIPPED", "FEEDBACK_PENDING"]
        # 先在各关联表取任务 ID，再用一次聚合统计，避免跨五张表的 OR + DISTINCT 查询被执行两遍。
        customer_task_ids = CustomerTaskLink.objects.filter(
            customer_account=customer,
            is_primary_source=True,
        ).values("business_task_id").union(
            CommunicationTaskLink.objects.filter(
                communication__customer_account=customer,
                is_primary_source=True,
            ).values("business_task_id"),
            InquiryTaskLink.objects.filter(
                inquiry__customer_account=customer,
                is_primary_source=True,
            ).values("business_task_id"),
            QuotationVersionTaskLink.objects.filter(
                quotation_version__quotation__customer_account=customer,
                is_primary_source=True,
            ).values("business_task_id"),
            SampleTaskLink.objects.filter(
                sample_request__customer_account=customer,
                is_primary_source=True,
            ).values("business_task_id"),
        )
        customer_task_counts = BusinessTask.objects.filter(
            id__in=customer_task_ids,
            archived_at__isnull=True,
            status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
        ).aggregate(
            open_tasks=Count("id"),
            overdue_tasks=Count("id", filter=Q(due_at__lt=timezone.now())),
        )
        primary_owner = None
        for assignment in getattr(customer, "current_assignments", []):
            if assignment.assignment_role == "PRIMARY_OWNER":
                primary_owner = assignment.employee
                break
        attention = getattr(customer, "current_attention_reviews", [])
        data = {
            "customer": CustomerListSerializer(customer, context=self.get_serializer_context()).data,
            "primary_owner": (
                {
                    "id": primary_owner.pk,
                    "employee_code": primary_owner.employee_code,
                    "display_name": primary_owner.display_name,
                }
                if primary_owner
                else None
            ),
            "attention_level": AttentionSummarySerializer(attention[0]).data if attention else None,
            "counts": {
                "entities": customer.transaction_entities.filter(archived_at__isnull=True).count(),
                "contacts": customer.contacts.filter(archived_at__isnull=True).count(),
                "open_inquiries": Inquiry.objects.filter(
                    customer_account=customer,
                    archived_at__isnull=True,
                    status__in=active_inquiry_statuses,
                ).count(),
                "open_quotations": Quotation.objects.filter(
                    customer_account=customer,
                    archived_at__isnull=True,
                    outcome_status="OPEN",
                ).count(),
                "active_samples": SampleRequest.objects.filter(
                    customer_account=customer,
                    archived_at__isnull=True,
                    status__in=active_sample_statuses,
                ).count(),
                "open_complaints": CustomerComplaint.objects.filter(
                    customer_account=customer,
                ).exclude(
                    status__in=["CLOSED", "CANCELLED"],
                ).count(),
                "open_tasks": customer_task_counts["open_tasks"],
                "overdue_tasks": customer_task_counts["overdue_tasks"],
            },
        }
        if sales_policy.enabled():
            for key, code in {
                "entities": "customers.view_customertransactionentity",
                "contacts": "customers.view_customercontact",
                "open_inquiries": "inquiries.view_inquiry",
                "open_quotations": "quotations.view_quotation",
                "active_samples": "samples.view_samplerequest",
                "open_complaints": "customers.view_customercomplaint",
            }.items():
                if not sales_policy.can_customer(request, code, customer.pk):
                    data["counts"][key] = 0
            from apps.workflow.selectors import accessible_tasks
            tasks = accessible_tasks(request, scope="ANY_ACCESS").filter(id__in=customer_task_ids, archived_at__isnull=True, status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS])
            data["counts"]["open_tasks"] = tasks.count() if sales_policy.has_permission(request, "workflow.view_businesstask") else 0
            data["counts"]["overdue_tasks"] = tasks.filter(due_at__lt=timezone.now()).count() if sales_policy.has_permission(request, "workflow.view_businesstask") else 0
        return Response({"data": data})

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        customer = self.get_object()
        query_serializer = TimelineQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        query = query_serializer.validated_data
        queryset = filter_activity(customer.timeline_events.all(), request).order_by("-occurred_at", "-id")
        if query.get("event_type"):
            queryset = queryset.filter(event_type=query["event_type"])
        if query.get("source_type"):
            queryset = queryset.filter(source_type=query["source_type"])
        if query.get("occurred_from"):
            queryset = queryset.filter(occurred_at__gte=query["occurred_from"])
        if query.get("occurred_to"):
            queryset = queryset.filter(occurred_at__lte=query["occurred_to"])

        paginator = TimelineCursorPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        output = TimelineEventSerializer(page, many=True)
        return paginator.get_paginated_response(output.data)

    @action(detail=True, methods=["get"])
    def assignments(self, request, pk=None):
        customer = self.get_object()
        queryset = customer.assignments.select_related("employee").order_by("-effective_from", "-id")
        return Response({"data": CustomerAssignmentSerializer(queryset, many=True).data})

    @action(detail=True, methods=["post"])
    def collaborators(self, request, pk=None):
        customer = self.get_object()
        serializer = CollaboratorCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = add_collaborator(
            customer=customer,
            employee=serializer.validated_data["employee"],
            effective_from=serializer.validated_data.get("effective_from"),
            reason=serializer.validated_data.get("reason", ""),
            actor_employee=self.actor_employee(),
            request=request,
        )
        return Response(
            {"data": CustomerAssignmentSerializer(assignment).data},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="employee_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="要结束协作关系的员工 UUID",
            )
        ]
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=rf"collaborators/(?P<employee_id>{UUID_URL_REGEX})/end",
    )
    def end_collaborator(self, request, employee_id=None, pk=None):
        customer = self.get_object()
        serializer = ArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = end_collaborator(
            customer=customer,
            employee_id=employee_id,
            reason=serializer.validated_data["reason"],
            actor_employee=self.actor_employee(),
            request=request,
        )
        return Response({"data": CustomerAssignmentSerializer(assignment).data})

    @action(detail=True, methods=["get", "post"])
    def entities(self, request, pk=None):
        customer = self.get_object()
        if request.method == "GET":
            queryset = customer.transaction_entities.filter(archived_at__isnull=True).order_by("entity_code")
            return Response({"data": CustomerTransactionEntitySerializer(queryset, many=True).data})
        serializer = CustomerTransactionEntitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity = self.create_audited(
            serializer,
            "CUSTOMER_TRANSACTION_ENTITY",
            customer,
            customer_account=customer,
        )
        return self.response_with_etag(
            {"data": CustomerTransactionEntitySerializer(entity).data},
            entity,
            status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"])
    def contacts(self, request, pk=None):
        # 联系人筛选同样使用 q，但父级 CustomerViewSet 的 SearchFilter 也会消费 q。
        # 子资源必须只按主键解析父客户，否则联系人姓名会被错误用于筛选客户名称并返回 404。
        customer = get_object_or_404(self.get_queryset(), pk=pk)
        if request.method == "GET":
            queryset = contacts_with_list_context(CustomerContact.objects.filter(customer_account=customer))
            queryset = filter_contacts(queryset, request.query_params)
            page = self.paginate_queryset(queryset)
            output = CustomerContactListSerializer(page, many=True, context=self.get_serializer_context())
            response = self.get_paginated_response(output.data)
            if request.query_params.get("include_summary", "").lower() == "true":
                response.data["summary"] = customer_contact_summary(customer)
            return response
        serializer = CustomerContactCreateSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "customer_account": customer},
        )
        serializer.is_valid(raise_exception=True)
        contact = create_contact(
            customer=customer,
            validated_data=dict(serializer.validated_data),
            actor_employee=self.actor_employee(),
            request=request,
        )
        contact = contacts_with_list_context(CustomerContact.objects.filter(pk=contact.pk)).get()
        return self.response_with_etag(
            {"data": CustomerContactDetailSerializer(contact, context=self.get_serializer_context()).data},
            contact,
            status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="attention-history")
    def attention_history(self, request, pk=None):
        customer = self.get_object()
        queryset = customer.attention_reviews.select_related("attention_level_item").order_by(
            "-effective_from",
            "-id",
        )
        return Response({"data": AttentionSummarySerializer(queryset, many=True).data})

    @action(detail=True, methods=["post"], url_path="set-attention")
    def set_attention(self, request, pk=None):
        customer = self.get_object()
        serializer = AttentionSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = set_attention(
                customer=customer,
                attention_level_item=serializer.validated_data["attention_level_item"],
                reason=serializer.validated_data["reason"],
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return Response(
            {"data": AttentionSummarySerializer(review).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="grade-history")
    def grade_history(self, request, pk=None):
        customer = self.get_object()
        queryset = customer.grade_reviews.select_related("grade_item").order_by("-effective_from", "-id")
        return Response({"data": GradeSummarySerializer(queryset, many=True).data})

    @action(detail=True, methods=["post"], url_path="set-grade")
    def set_grade(self, request, pk=None):
        customer = self.get_object()
        serializer = GradeSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = set_grade(
                customer=customer,
                grade_item=serializer.validated_data["grade_item"],
                reason=serializer.validated_data["reason"],
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return Response({"data": GradeSummarySerializer(review).data}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="source-history")
    def source_history(self, request, pk=None):
        customer = self.get_object()
        queryset = customer.source_attributions.select_related("source_item").order_by("effective_from", "id")
        return Response({"data": SourceSummarySerializer(queryset, many=True).data})

    @action(detail=True, methods=["post"], url_path="set-source")
    def set_source(self, request, pk=None):
        customer = self.get_object()
        serializer = SourceSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            attribution = set_source(
                customer=customer,
                source_item=serializer.validated_data["source_item"],
                notes=serializer.validated_data.get("notes", ""),
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return Response({"data": SourceSummarySerializer(attribution).data}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="activity-history")
    def activity_history(self, request, pk=None):
        customer = self.get_object()
        queryset = customer.activity_reviews.order_by("-effective_from", "-id")
        return Response({"data": ActivitySummarySerializer(queryset, many=True).data})

    @action(detail=True, methods=["post"], url_path="set-activity")
    def set_activity(self, request, pk=None):
        customer = self.get_object()
        serializer = ActivitySetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = set_activity(
                customer=customer,
                activity_status=serializer.validated_data["activity_status"],
                reason=serializer.validated_data["reason"],
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return Response({"data": ActivitySummarySerializer(review).data}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="set-classification")
    def set_classification(self, request, pk=None):
        customer = self.get_object()
        serializer = ClassificationSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            set_classification(
                customer=customer,
                customer_type_items=serializer.validated_data.get("customer_type_items"),
                customer_tags=serializer.validated_data.get("customer_tags"),
                reason=serializer.validated_data["reason"],
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        customer = customers_with_current_context(CustomerAccount.objects.filter(pk=customer.pk), request=self.request).get()
        return Response(
            {
                "data": {
                    "customer_types": CustomerTypeSummarySerializer(
                        customer.current_type_assignments,
                        many=True,
                    ).data,
                    "customer_tags": CustomerTagSummarySerializer(
                        customer.current_tag_assignments,
                        many=True,
                    ).data,
                }
            }
        )

    @action(detail=True, methods=["get"], url_path="business-snapshot-history")
    def business_snapshot_history(self, request, pk=None):
        customer = self.get_object()
        queryset = customer.business_snapshots.select_related("entered_by_employee").order_by("-as_of_at", "-id")
        return Response({"data": CustomerBusinessSnapshotSerializer(queryset, many=True).data})

    @action(detail=True, methods=["post"], url_path="set-business-snapshot")
    def set_business_snapshot(self, request, pk=None):
        customer = self.get_object()
        serializer = CustomerBusinessSnapshotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            snapshot = set_business_snapshot(
                customer=customer,
                validated_data=dict(serializer.validated_data),
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return Response(
            {"data": CustomerBusinessSnapshotSerializer(snapshot).data},
            status=status.HTTP_201_CREATED,
        )


class CustomerEntityViewSet(
    mixins.RetrieveModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = CustomerTransactionEntitySerializer
    action_permission_map = {
        "retrieve": "customers.view_customertransactionentity",
        "partial_update": "customers.change_customertransactionentity",
        "archive": "customers.change_customertransactionentity",
        "roles.GET": "customers.view_customertransactionentityrole",
        "roles.POST": "customers.add_customertransactionentityrole",
        "addresses.GET": "customers.view_customerentityaddress",
        "addresses.POST": "customers.add_customerentityaddress",
    }

    def get_queryset(self):
        queryset = CustomerTransactionEntity.objects.filter(
            customer_account__in=accessible_customers(
                self.request,
                self.action_permission_codename("view_customertransactionentity"),
            ),
        ).select_related("customer_account")
        if self.request.method not in SAFE_METHODS:
            queryset = queryset.filter(
                archived_at__isnull=True,
                customer_account__archived_at__isnull=True,
            )
        return queryset

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(instance).data}, instance)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        updated = self.update_instance(
            instance,
            CustomerTransactionEntitySerializer,
            "CUSTOMER_TRANSACTION_ENTITY",
            instance.customer_account,
        )
        return self.response_with_etag({"data": self.get_serializer(updated).data}, updated)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        instance = self.get_object()
        require_matching_etag(request, instance)
        serializer = ArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = archive_resource(
            instance=instance,
            reason=serializer.validated_data["reason"],
            actor_employee=self.actor_employee(),
            request=request,
            object_type="CUSTOMER_TRANSACTION_ENTITY",
            customer=instance.customer_account,
        )
        return self.response_with_etag({"data": self.get_serializer(instance).data}, instance)

    @action(detail=True, methods=["get", "post"])
    def roles(self, request, pk=None):
        entity = self.get_object()
        if request.method == "GET":
            queryset = entity.entity_roles.order_by("-effective_from", "-id")
            return Response({"data": EntityRoleSerializer(queryset, many=True).data})
        serializer = EntityRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = self.create_audited(
            serializer,
            "CUSTOMER_TRANSACTION_ENTITY_ROLE",
            entity.customer_account,
            transaction_entity=entity,
            effective_from=serializer.validated_data.get("effective_from", timezone.now()),
        )
        return self.response_with_etag(
            {"data": EntityRoleSerializer(role).data},
            role,
            status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"])
    def addresses(self, request, pk=None):
        entity = self.get_object()
        if request.method == "GET":
            queryset = entity.addresses.filter(archived_at__isnull=True).order_by("address_code")
            return Response({"data": CustomerAddressSerializer(queryset, many=True).data})
        serializer = CustomerAddressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        address = self.create_audited(
            serializer,
            "CUSTOMER_ENTITY_ADDRESS",
            entity.customer_account,
            transaction_entity=entity,
        )
        return self.response_with_etag(
            {"data": CustomerAddressSerializer(address).data},
            address,
            status.HTTP_201_CREATED,
        )


class CustomerAddressViewSet(mixins.RetrieveModelMixin, CustomerApiViewSetBase):
    serializer_class = CustomerAddressSerializer
    action_permission_map = {
        "retrieve": "customers.view_customerentityaddress",
        "partial_update": "customers.change_customerentityaddress",
        "archive": "customers.change_customerentityaddress",
        "usages.GET": "customers.view_customerentityaddressusage",
        "usages.POST": "customers.add_customerentityaddressusage",
    }

    def get_queryset(self):
        queryset = CustomerEntityAddress.objects.filter(
            transaction_entity__customer_account__in=accessible_customers(
                self.request,
                self.action_permission_codename("view_customerentityaddress"),
            ),
        ).select_related("transaction_entity__customer_account")
        if self.request.method not in SAFE_METHODS:
            queryset = queryset.filter(
                archived_at__isnull=True,
                transaction_entity__archived_at__isnull=True,
                transaction_entity__customer_account__archived_at__isnull=True,
            )
        return queryset

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(instance).data}, instance)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        updated = self.update_instance(
            instance,
            CustomerAddressSerializer,
            "CUSTOMER_ENTITY_ADDRESS",
            instance.transaction_entity.customer_account,
        )
        return self.response_with_etag({"data": self.get_serializer(updated).data}, updated)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        instance = self.get_object()
        require_matching_etag(request, instance)
        serializer = ArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = archive_resource(
            instance=instance,
            reason=serializer.validated_data["reason"],
            actor_employee=self.actor_employee(),
            request=request,
            object_type="CUSTOMER_ENTITY_ADDRESS",
            customer=instance.transaction_entity.customer_account,
        )
        return self.response_with_etag({"data": self.get_serializer(instance).data}, instance)

    @action(detail=True, methods=["get", "post"])
    def usages(self, request, pk=None):
        address = self.get_object()
        if request.method == "GET":
            queryset = address.usages.order_by("-effective_from", "-id")
            return Response({"data": AddressUsageSerializer(queryset, many=True).data})
        serializer = AddressUsageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        usage = self.create_audited(
            serializer,
            "CUSTOMER_ENTITY_ADDRESS_USAGE",
            address.transaction_entity.customer_account,
            entity_address=address,
            effective_from=serializer.validated_data.get("effective_from", timezone.now()),
        )
        return self.response_with_etag(
            {"data": AddressUsageSerializer(usage).data},
            usage,
            status.HTTP_201_CREATED,
        )


class CustomerContactViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = CustomerContactDetailSerializer
    action_permission_map = {
        "list": "customers.view_customercontact",
        "retrieve": "customers.view_customercontact",
        "destroy": "customers.delete_customercontact",
        "partial_update": "customers.change_customercontact",
        "archive": "customers.change_customercontact",
        "duplicate_check": "customers.view_customercontact",
        "configuration": "customers.view_customercontact",
        "employment_history.GET": "customers.view_customercontact",
        "employment_history.POST": "customers.change_customercontact",
        "mark_left": "customers.change_customercontact",
        "bulk_mark_left": "customers.bulk_change_customercontact",
        "bulk_create_tasks": "customers.bulk_create_contact_task",
        "methods.GET": "customers.view_customercontactmethod",
        "methods.POST": "customers.add_customercontactmethod",
        "roles.GET": "customers.view_customercontactrole",
        "roles.POST": "customers.add_customercontactrole",
    }

    def get_queryset(self):
        accessible = accessible_customers(
            self.request,
            self.action_permission_codename("view_customercontact"),
        )
        queryset = contacts_with_list_context(
            CustomerContact.objects.filter(customer_account__in=accessible)
        )
        if self.request.method not in SAFE_METHODS:
            queryset = queryset.filter(
                archived_at__isnull=True,
                customer_account__archived_at__isnull=True,
            )
        if self.action == "list":
            queryset = filter_contacts(queryset, self.request.query_params)
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return CustomerContactListSerializer
        if self.action == "partial_update":
            return CustomerContactUpdateSerializer
        return CustomerContactDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(instance).data}, instance)

    def destroy(self, request, *args, **kwargs):
        contact = self.get_object()
        require_matching_etag(request, contact)
        return Response({"data": permanently_delete_contact(contact)})

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = CustomerContactUpdateSerializer(
            instance,
            data=request.data,
            partial=True,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        if not serializer.validated_data:
            raise ValidationError({"detail": ["请至少提交一个需要修改的字段。"]})
        updated = update_contact_profile(
            contact=instance,
            validated_data=dict(serializer.validated_data),
            actor_employee=self.actor_employee(),
            request=request,
        )
        updated = contacts_with_list_context(CustomerContact.objects.filter(pk=updated.pk)).get()
        return self.response_with_etag(
            {"data": CustomerContactDetailSerializer(updated, context=self.get_serializer_context()).data},
            updated,
        )

    @action(detail=False, methods=["get"], url_path="options")
    def configuration(self, request):
        grouped, _config_version = legacy_dictionary_groups(
            ["CONTACT_LANGUAGE", "CONTACT_TIMEZONE"]
        )
        language_options = grouped["CONTACT_LANGUAGE"]
        timezone_options = grouped["CONTACT_TIMEZONE"]
        return Response({
            "data": {
                "role_options": [
                    {"value": value, "label": label}
                    for value, label in CustomerContactRole._meta.get_field("role_type").choices
                ],
                "status_options": [
                    {"value": value, "label": label}
                    for value, label in CustomerContact._meta.get_field("status").choices
                ],
                "language_options": [
                    {"value": item["item_code"], "label": item["display_name"]}
                    for item in language_options
                ],
                "timezone_options": [
                    {
                        "value": item["extra_data"].get("timezone_code", ""),
                        "label": item["display_name"],
                    }
                    for item in timezone_options
                    if item["extra_data"].get("timezone_code")
                ],
            }
        })

    @action(detail=False, methods=["get"], url_path="duplicate-check")
    def duplicate_check(self, request):
        serializer = ContactDuplicateCheckSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        accessible = accessible_customers(request, "view_customercontact")
        customer = accessible.filter(pk=data["customer_id"], archived_at__isnull=True).first()
        if customer is None:
            raise ValidationError({"customer_id": "客户不存在或无权访问。"})
        request._contact_accessible_customer_ids = list(accessible.values_list("id", flat=True))
        result = duplicate_summary(
            request=request,
            customer=customer,
            method_type=data["method_type"],
            raw_value=data["value"],
            exclude_contact_id=data.get("exclude_contact_id"),
        )
        return Response({"data": result})

    @action(detail=True, methods=["post"], url_path="mark-left")
    def mark_left(self, request, pk=None):
        contact = self.get_object()
        require_matching_etag(request, contact)
        serializer = ContactMarkLeftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        leave_data = dict(serializer.validated_data)
        reason = leave_data.pop("reason")
        leave_data.pop("preserve_history", None)
        updated, task = mark_contact_left(
            contact=contact,
            reason=reason,
            actor_employee=self.actor_employee(),
            request=request,
            **leave_data,
        )
        updated = contacts_with_list_context(CustomerContact.objects.filter(pk=updated.pk)).get()
        return self.response_with_etag(
            {
                "data": CustomerContactDetailSerializer(updated, context=self.get_serializer_context()).data,
                "replacement_task_id": str(task.pk) if task else None,
            },
            updated,
        )

    @action(detail=True, methods=["get", "post"], url_path="employment-history")
    def employment_history(self, request, pk=None):
        contact = self.get_object()
        if request.method == "GET":
            queryset = contact.employment_events.select_related("actor_employee").order_by(
                "-effective_on", "-created_at", "-id"
            )
            return Response({"data": ContactEmploymentEventSerializer(queryset, many=True).data})

        serializer = ContactEmploymentRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        effective_on = data.pop("effective_on")
        title = data.pop("title")
        notes = data.pop("notes", "")
        updated = update_contact_profile(
            contact=contact,
            validated_data=data,
            actor_employee=self.actor_employee(),
            request=request,
            event_title=title,
            effective_on=effective_on,
            event_notes=notes,
        )
        latest = updated.employment_events.select_related("actor_employee").order_by(
            "-created_at", "-id"
        ).first()
        return self.response_with_etag(
            {"data": ContactEmploymentEventSerializer(latest).data},
            updated,
            status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="bulk-mark-left")
    def bulk_mark_left(self, request):
        serializer = ContactBulkMarkLeftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact_ids = serializer.validated_data["contact_ids"]
        contacts = list(self.get_queryset().filter(pk__in=contact_ids))
        if len(contacts) != len(contact_ids):
            raise ValidationError({"contact_ids": "部分联系人不存在或无权访问。"})
        results = bulk_mark_contacts_left(
            contacts=contacts,
            reason=serializer.validated_data["reason"],
            actor_employee=self.actor_employee(),
            request=request,
        )
        return Response(
            {
                "data": {
                    "updated_count": len(results),
                    "contact_ids": [str(contact.pk) for contact, _ in results],
                    "replacement_task_ids": [str(task.pk) for _, task in results if task],
                }
            }
        )

    @action(detail=False, methods=["post"], url_path="bulk-create-tasks")
    def bulk_create_tasks(self, request):
        serializer = ContactBulkTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact_ids = serializer.validated_data["contact_ids"]
        contacts = list(self.get_queryset().filter(pk__in=contact_ids).select_related("customer_account"))
        if len(contacts) != len(contact_ids):
            raise ValidationError({"contact_ids": "部分联系人不存在或无权访问。"})
        tasks = bulk_create_contact_tasks(
            contacts=contacts,
            validated_data=serializer.validated_data,
            actor_employee=self.actor_employee(),
        )
        return Response(
            {"data": {"created_count": len(tasks), "task_ids": [str(task.pk) for task in tasks]}},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        instance = self.get_object()
        require_matching_etag(request, instance)
        serializer = ArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = archive_resource(
            instance=instance,
            reason=serializer.validated_data["reason"],
            actor_employee=self.actor_employee(),
            request=request,
            object_type="CUSTOMER_CONTACT",
            customer=instance.customer_account,
        )
        return self.response_with_etag({"data": self.get_serializer(instance).data}, instance)

    @action(detail=True, methods=["get", "post"])
    def methods(self, request, pk=None):
        contact = self.get_object()
        allow_sensitive = request.user.has_perm("customers.view_sensitive_customercontactmethod")
        if request.method == "GET":
            queryset = contact.methods.filter(archived_at__isnull=True).order_by("-is_primary", "method_type", "id")
            return Response(
                {"data": ContactMethodReadSerializer(
                    queryset, many=True, context={"allow_sensitive": allow_sensitive}
                ).data}
            )
        serializer = ContactMethodSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        duplicate_acknowledged = serializer.validated_data.pop("duplicate_acknowledged", False)
        validate_contact_method_duplicate(
            customer=contact.customer_account,
            method_data=serializer.validated_data,
            duplicate_acknowledged=duplicate_acknowledged,
        )
        method_data = prepare_contact_method(dict(serializer.validated_data))
        method = self.create_audited(
            serializer,
            "CUSTOMER_CONTACT_METHOD",
            contact.customer_account,
            customer_contact=contact,
            **method_data,
        )
        return self.response_with_etag(
            {"data": ContactMethodReadSerializer(
                method, context={"allow_sensitive": allow_sensitive}
            ).data},
            method,
            status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"])
    def roles(self, request, pk=None):
        contact = self.get_object()
        if request.method == "GET":
            queryset = contact.roles.order_by("-effective_from", "-id")
            return Response({"data": ContactRoleSerializer(queryset, many=True).data})
        serializer = ContactRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = self.create_audited(
            serializer,
            "CUSTOMER_CONTACT_ROLE",
            contact.customer_account,
            customer_contact=contact,
            effective_from=serializer.validated_data.get("effective_from", timezone.now()),
        )
        return self.response_with_etag(
            {"data": ContactRoleSerializer(role).data},
            role,
            status.HTTP_201_CREATED,
        )


class ContactMethodViewSet(mixins.RetrieveModelMixin, CustomerApiViewSetBase):
    serializer_class = ContactMethodSerializer
    action_permission_map = {
        "retrieve": "customers.view_customercontactmethod",
        "partial_update": "customers.change_customercontactmethod",
        "archive": "customers.change_customercontactmethod",
    }

    def get_queryset(self):
        queryset = CustomerContactMethod.objects.filter(
            customer_contact__customer_account__in=accessible_customers(
                self.request,
                self.action_permission_codename("view_customercontactmethod"),
            ),
        ).select_related("customer_contact__customer_account")
        if self.request.method not in SAFE_METHODS:
            queryset = queryset.filter(
                archived_at__isnull=True,
                customer_contact__archived_at__isnull=True,
                customer_contact__customer_account__archived_at__isnull=True,
            )
        return queryset

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        output = ContactMethodReadSerializer(
            instance,
            context={"allow_sensitive": request.user.has_perm("customers.view_sensitive_customercontactmethod")},
        )
        return self.response_with_etag({"data": output.data}, instance)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        require_matching_etag(request, instance)
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if not serializer.validated_data:
            raise ValidationError({"detail": ["请至少提交一个需要修改的字段。"]})
        duplicate_acknowledged = serializer.validated_data.pop("duplicate_acknowledged", False)
        data = {**model_snapshot(instance, ["method_type", "raw_value", "is_primary", "is_preferred", "verification_status"]), **serializer.validated_data}
        validate_contact_method_duplicate(
            customer=instance.customer_contact.customer_account,
            method_data=data,
            duplicate_acknowledged=duplicate_acknowledged,
            exclude_method_id=instance.pk,
        )
        prepared = prepare_contact_method(
            {
                "method_type": data["method_type"],
                "raw_value": data["raw_value"],
                "is_primary": data["is_primary"],
                "is_preferred": data["is_preferred"],
                "verification_status": data["verification_status"],
            }
        )
        try:
            with transaction.atomic():
                locked = CustomerContactMethod.objects.select_for_update().get(pk=instance.pk)
                require_matching_etag(request, locked)
                before_data = model_snapshot(
                    locked,
                    [
                        "method_type",
                        "raw_value",
                        "normalized_value",
                        "normalization_version",
                        "normalized_at",
                        "is_primary",
                        "is_preferred",
                        "verification_status",
                    ],
                )
                for field_name, value in prepared.items():
                    setattr(locked, field_name, value)
                locked.save()
                write_audit_log(
                    object_type="CUSTOMER_CONTACT_METHOD",
                    object_id=locked.pk,
                    context_type="CUSTOMER_ACCOUNT",
                    context_id=locked.customer_contact.customer_account_id,
                    action="UPDATED",
                    actor_employee=self.actor_employee(),
                    before_data=before_data,
                    after_data=ContactMethodSerializer(locked).data,
                    request=request,
                )
                write_customer_timeline(
                    customer=locked.customer_contact.customer_account,
                    event_type="CUSTOMER_CONTACT_METHOD_UPDATED",
                    title="更新客户联系方式",
                    source_type="CUSTOMER_CONTACT_METHOD",
                    source_id=locked.pk,
                    actor_employee=self.actor_employee(),
                )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        output = ContactMethodReadSerializer(
            locked,
            context={"allow_sensitive": request.user.has_perm("customers.view_sensitive_customercontactmethod")},
        )
        return self.response_with_etag({"data": output.data}, locked)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        instance = self.get_object()
        require_matching_etag(request, instance)
        serializer = ArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if (
            instance.customer_contact.status == "ACTIVE"
            and instance.customer_contact.methods.filter(archived_at__isnull=True).count() <= 1
        ):
            raise Conflict("在职联系人必须至少保留一种有效联系方式。")
        instance = archive_resource(
            instance=instance,
            reason=serializer.validated_data["reason"],
            actor_employee=self.actor_employee(),
            request=request,
            object_type="CUSTOMER_CONTACT_METHOD",
            customer=instance.customer_contact.customer_account,
        )
        output = ContactMethodReadSerializer(
            instance,
            context={"allow_sensitive": request.user.has_perm("customers.view_sensitive_customercontactmethod")},
        )
        return self.response_with_etag({"data": output.data}, instance)


class EffectiveRecordViewSet(mixins.RetrieveModelMixin, CustomerApiViewSetBase):
    model = None
    customer_lookup = None
    object_type = None
    customer_attribute = None
    active_parent_filters = {}
    serializer_class = None
    action_permission_map = {}

    def get_queryset(self):
        queryset = self.model.objects.filter(
            **{
                f"{self.customer_lookup}__in": accessible_customers(
                    self.request,
                    self.action_permission_codename(),
                )
            }
        )
        if self.request.method not in SAFE_METHODS:
            queryset = queryset.filter(**self.active_parent_filters)
        return queryset

    def get_customer(self, instance):
        value = instance
        for attribute in self.customer_attribute.split("."):
            value = getattr(value, attribute)
        return value

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(instance).data}, instance)

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        instance = self.get_object()
        require_matching_etag(request, instance)
        customer = self.get_customer(instance)
        with transaction.atomic():
            instance = self.model.objects.select_for_update().get(pk=instance.pk)
            require_matching_etag(request, instance)
            if instance.effective_to is None:
                before_data = model_snapshot(instance, ["effective_from", "effective_to"])
                instance.effective_to = timezone.now()
                instance.save(update_fields=["effective_to", "updated_at"])
                write_audit_log(
                    object_type=self.object_type,
                    object_id=instance.pk,
                    context_type="CUSTOMER_ACCOUNT",
                    context_id=customer.pk,
                    action="ENDED",
                    actor_employee=self.actor_employee(),
                    before_data=before_data,
                    after_data=model_snapshot(instance, ["effective_from", "effective_to"]),
                    request=request,
                )
                write_customer_timeline(
                    customer=customer,
                    event_type=f"{self.object_type}_ENDED",
                    title="结束客户业务角色",
                    source_type=self.object_type,
                    source_id=instance.pk,
                    actor_employee=self.actor_employee(),
                )
        return self.response_with_etag({"data": self.get_serializer(instance).data}, instance)


class EntityRoleViewSet(EffectiveRecordViewSet):
    model = CustomerTransactionEntityRole
    serializer_class = EntityRoleSerializer
    customer_lookup = "transaction_entity__customer_account"
    customer_attribute = "transaction_entity.customer_account"
    object_type = "CUSTOMER_TRANSACTION_ENTITY_ROLE"
    active_parent_filters = {
        "transaction_entity__archived_at__isnull": True,
        "transaction_entity__customer_account__archived_at__isnull": True,
    }
    action_permission_map = {
        "retrieve": "customers.view_customertransactionentityrole",
        "end": "customers.change_customertransactionentityrole",
    }


class AddressUsageViewSet(EffectiveRecordViewSet):
    model = CustomerEntityAddressUsage
    serializer_class = AddressUsageSerializer
    customer_lookup = "entity_address__transaction_entity__customer_account"
    customer_attribute = "entity_address.transaction_entity.customer_account"
    object_type = "CUSTOMER_ENTITY_ADDRESS_USAGE"
    active_parent_filters = {
        "entity_address__archived_at__isnull": True,
        "entity_address__transaction_entity__archived_at__isnull": True,
        "entity_address__transaction_entity__customer_account__archived_at__isnull": True,
    }
    action_permission_map = {
        "retrieve": "customers.view_customerentityaddressusage",
        "end": "customers.change_customerentityaddressusage",
    }


class ContactRoleViewSet(EffectiveRecordViewSet):
    model = CustomerContactRole
    serializer_class = ContactRoleSerializer
    customer_lookup = "customer_contact__customer_account"
    customer_attribute = "customer_contact.customer_account"
    object_type = "CUSTOMER_CONTACT_ROLE"
    active_parent_filters = {
        "customer_contact__archived_at__isnull": True,
        "customer_contact__customer_account__archived_at__isnull": True,
    }
    action_permission_map = {
        "retrieve": "customers.view_customercontactrole",
        "end": "customers.change_customercontactrole",
    }
