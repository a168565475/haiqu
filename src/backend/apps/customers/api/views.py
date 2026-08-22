from django.db import IntegrityError, transaction
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
from apps.inquiries.models import Inquiry
from apps.quotations.models import Quotation
from apps.samples.models import SampleRequest

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
from ..selectors import accessible_customers, customers_with_current_context
from ..services import (
    add_collaborator,
    archive_resource,
    create_customer,
    end_collaborator,
    model_snapshot,
    prepare_contact_method,
    restore_customer,
    set_attention,
    update_customer,
    write_customer_timeline,
)
from .filters import CustomerFilter
from .serializers import (
    AddressUsageSerializer,
    ArchiveSerializer,
    AttentionSetSerializer,
    AttentionSummarySerializer,
    CollaboratorCreateSerializer,
    ContactMethodSerializer,
    ContactRoleSerializer,
    CustomerAddressSerializer,
    CustomerAssignmentSerializer,
    CustomerContactSerializer,
    CustomerCreateSerializer,
    CustomerDetailSerializer,
    CustomerListSerializer,
    CustomerTransactionEntitySerializer,
    CustomerUpdateSerializer,
    EntityRoleSerializer,
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
        permission_map = getattr(self, "action_permission_map", {})
        permission = permission_map.get(f"{self.action}.{self.request.method}") or permission_map.get(
            self.action
        )
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
    CustomerApiViewSetBase,
):
    serializer_class = CustomerDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = CustomerFilter
    search_fields = ["account_code", "account_name", "english_name", "short_name"]
    ordering_fields = ["account_code", "account_name", "created_at", "updated_at"]
    ordering = ["-updated_at", "-id"]
    action_permission_map = {
        "list": "customers.view_customeraccount",
        "retrieve": "customers.view_customeraccount",
        "create": "customers.add_customeraccount",
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
        return customers_with_current_context(queryset)

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
        customer = customers_with_current_context(CustomerAccount.objects.filter(pk=customer.pk)).get()
        output = CustomerDetailSerializer(customer, context=self.get_serializer_context())
        return self.response_with_etag({"data": output.data}, customer, status.HTTP_201_CREATED)

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
        customer = customers_with_current_context(CustomerAccount.objects.filter(pk=customer.pk)).get()
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
        customer = customers_with_current_context(CustomerAccount.objects.filter(pk=customer.pk)).get()
        return self.response_with_etag({"data": CustomerDetailSerializer(customer).data}, customer)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        customer = self.get_object()
        require_matching_etag(request, customer)
        customer = restore_customer(
            customer=customer,
            actor_employee=self.actor_employee(),
            request=request,
        )
        customer = customers_with_current_context(CustomerAccount.objects.filter(pk=customer.pk)).get()
        return self.response_with_etag({"data": CustomerDetailSerializer(customer).data}, customer)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        customer = self.get_object()
        active_inquiry_statuses = ["DRAFT", "SUBMITTED", "IN_PROGRESS", "QUOTED"]
        active_sample_statuses = ["DRAFT", "PENDING", "PREPARING", "SHIPPED", "FEEDBACK_PENDING"]
        primary_owner = None
        for assignment in getattr(customer, "current_assignments", []):
            if assignment.assignment_role == "PRIMARY_OWNER":
                primary_owner = assignment.employee
                break
        attention = getattr(customer, "current_attention_reviews", [])
        data = {
            "customer": CustomerListSerializer(customer).data,
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
                "open_tasks": customer.task_links.filter(
                    business_task__archived_at__isnull=True,
                    business_task__status__in=["PENDING", "IN_PROGRESS"],
                ).count(),
                "overdue_tasks": customer.task_links.filter(
                    business_task__archived_at__isnull=True,
                    business_task__status__in=["PENDING", "IN_PROGRESS"],
                    business_task__due_at__lt=timezone.now(),
                ).count(),
            },
        }
        return Response({"data": data})

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        customer = self.get_object()
        query_serializer = TimelineQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        query = query_serializer.validated_data
        queryset = customer.timeline_events.order_by("-occurred_at", "-id")
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
        customer = self.get_object()
        if request.method == "GET":
            queryset = customer.contacts.filter(archived_at__isnull=True).order_by("display_name", "id")
            return Response({"data": CustomerContactSerializer(queryset, many=True).data})
        serializer = CustomerContactSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "customer_account": customer},
        )
        serializer.is_valid(raise_exception=True)
        contact = self.create_audited(
            serializer,
            "CUSTOMER_CONTACT",
            customer,
            customer_account=customer,
        )
        return self.response_with_etag(
            {"data": CustomerContactSerializer(contact).data},
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


class CustomerContactViewSet(mixins.RetrieveModelMixin, CustomerApiViewSetBase):
    serializer_class = CustomerContactSerializer
    action_permission_map = {
        "retrieve": "customers.view_customercontact",
        "partial_update": "customers.change_customercontact",
        "archive": "customers.change_customercontact",
        "methods.GET": "customers.view_customercontactmethod",
        "methods.POST": "customers.add_customercontactmethod",
        "roles.GET": "customers.view_customercontactrole",
        "roles.POST": "customers.add_customercontactrole",
    }

    def get_queryset(self):
        queryset = CustomerContact.objects.filter(
            customer_account__in=accessible_customers(
                self.request,
                self.action_permission_codename("view_customercontact"),
            ),
        ).select_related("customer_account", "transaction_entity", "source_contact")
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
            CustomerContactSerializer,
            "CUSTOMER_CONTACT",
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
            object_type="CUSTOMER_CONTACT",
            customer=instance.customer_account,
        )
        return self.response_with_etag({"data": self.get_serializer(instance).data}, instance)

    @action(detail=True, methods=["get", "post"])
    def methods(self, request, pk=None):
        contact = self.get_object()
        if request.method == "GET":
            queryset = contact.methods.filter(archived_at__isnull=True).order_by("-is_primary", "method_type", "id")
            return Response({"data": ContactMethodSerializer(queryset, many=True).data})
        serializer = ContactMethodSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        method_data = prepare_contact_method(dict(serializer.validated_data))
        method = self.create_audited(
            serializer,
            "CUSTOMER_CONTACT_METHOD",
            contact.customer_account,
            customer_contact=contact,
            **method_data,
        )
        return self.response_with_etag(
            {"data": ContactMethodSerializer(method).data},
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
        return self.response_with_etag({"data": self.get_serializer(instance).data}, instance)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        require_matching_etag(request, instance)
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if not serializer.validated_data:
            raise ValidationError({"detail": ["请至少提交一个需要修改的字段。"]})
        data = {**model_snapshot(instance, ["method_type", "raw_value", "is_primary", "is_preferred", "verification_status"]), **serializer.validated_data}
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
        return self.response_with_etag({"data": self.get_serializer(locked).data}, locked)

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
            object_type="CUSTOMER_CONTACT_METHOD",
            customer=instance.customer_contact.customer_account,
        )
        return self.response_with_etag({"data": self.get_serializer(instance).data}, instance)


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
