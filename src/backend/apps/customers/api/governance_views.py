from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log

from ..governance_services import (
    cancel_transfer,
    create_access_grant,
    create_transfer_request,
    decide_transfer,
    execute_merge,
    merge_preview,
    revoke_access_grant,
)
from ..models import (
    CustomerAccount,
    CustomerDataAccessGrant,
    CustomerDuplicateCandidate,
    CustomerDuplicateCase,
    CustomerMergeOperation,
    CustomerMergeMember,
    CustomerTransferRequest,
    DuplicateCaseStatus,
    DuplicateDecision,
    MergeMemberRole,
    MergeStatus,
    TransferStatus,
)
from ..selectors import accessible_customers
from .governance_serializers import (
    CustomerAccessGrantCreateSerializer,
    CustomerAccessGrantSerializer,
    CustomerTransferCreateSerializer,
    CustomerTransferRequestSerializer,
    DecisionNoteSerializer,
    DuplicateCaseCreateSerializer,
    DuplicateCaseSerializer,
    DuplicateDecisionSerializer,
    MergeOperationSerializer,
    MergeRequestSerializer,
)
from .views import CustomerApiViewSetBase


def _all_case_customers_accessible(request, case, permission_codename="merge_customer"):
    candidate_ids = set(case.candidates.values_list("customer_account_id", flat=True))
    accessible_ids = set(
        accessible_customers(request, permission_codename).filter(pk__in=candidate_ids).values_list("pk", flat=True)
    )
    if bool(candidate_ids) and candidate_ids == accessible_ids:
        return True
    return CustomerMergeMember.objects.filter(
        merge_operation__duplicate_case=case,
        merge_operation__status=MergeStatus.COMPLETED,
        member_role=MergeMemberRole.SURVIVOR,
        customer_account__in=accessible_customers(request, permission_codename),
    ).exists()


class CustomerTransferRequestViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, CustomerApiViewSetBase
):
    serializer_class = CustomerTransferRequestSerializer
    ordering = ["-submitted_at", "-id"]
    action_permission_map = {
        "list": "customers.transfer_customer",
        "retrieve": "customers.transfer_customer",
        "create": "customers.transfer_customer",
        "approve": "customers.approve_customer_transfer",
        "reject": "customers.approve_customer_transfer",
        "cancel": "customers.transfer_customer",
    }

    def get_queryset(self):
        permission = "approve_customer_transfer" if self.action in {"approve", "reject"} else "transfer_customer"
        customers = accessible_customers(self.request, permission)
        queryset = CustomerTransferRequest.objects.filter(customer_account__in=customers).select_related(
            "customer_account", "from_employee", "to_employee", "requested_by_employee", "decided_by_employee"
        )
        status_value = self.request.query_params.get("status")
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset.order_by(*self.ordering)

    def get_serializer_class(self):
        return CustomerTransferCreateSerializer if self.action == "create" else CustomerTransferRequestSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = accessible_customers(request, "transfer_customer").filter(
            pk=serializer.validated_data["customer_id"], archived_at__isnull=True
        ).first()
        if customer is None:
            raise NotFound("客户不存在或无权发起转移。")
        transfer = create_transfer_request(
            customer=customer, to_employee=serializer.validated_data["to_employee"],
            reason=serializer.validated_data["reason"], actor_employee=self.actor_employee(), request=request,
        )
        transfer = self.get_queryset().get(pk=transfer.pk)
        output = CustomerTransferRequestSerializer(transfer)
        return self.response_with_etag({"data": output.data}, transfer, status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        transfer = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(transfer).data}, transfer)

    def _decide(self, request, decision):
        transfer = self.get_object()
        serializer = DecisionNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer = decide_transfer(
            transfer=transfer, decision=decision, note=serializer.validated_data["decision_note"],
            actor_employee=self.actor_employee(), request=request,
        )
        transfer = CustomerTransferRequest.objects.select_related(
            "customer_account", "from_employee", "to_employee", "requested_by_employee", "decided_by_employee"
        ).get(pk=transfer.pk)
        return self.response_with_etag({"data": CustomerTransferRequestSerializer(transfer).data}, transfer)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, TransferStatus.APPROVED)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, TransferStatus.REJECTED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        transfer = self.get_object()
        serializer = DecisionNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer = cancel_transfer(
            transfer=transfer, note=serializer.validated_data["decision_note"],
            actor_employee=self.actor_employee(), request=request,
        )
        transfer = CustomerTransferRequest.objects.select_related(
            "customer_account", "from_employee", "to_employee", "requested_by_employee", "decided_by_employee"
        ).get(pk=transfer.pk)
        return self.response_with_etag({"data": CustomerTransferRequestSerializer(transfer).data}, transfer)


class CustomerAccessGrantNestedViewSet(CustomerApiViewSetBase):
    queryset = CustomerDataAccessGrant.objects.none()
    serializer_class = CustomerAccessGrantSerializer
    action_permission_map = {
        "list": "customers.manage_customer_access",
        "create": "customers.manage_customer_access",
    }

    def _customer(self):
        customer = accessible_customers(self.request, "manage_customer_access").filter(
            pk=self.kwargs["customer_pk"]
        ).first()
        if customer is None:
            raise NotFound("客户不存在或无权管理授权。")
        return customer

    def list(self, request, *args, **kwargs):
        customer = self._customer()
        queryset = customer.data_grants.select_related(
            "employee", "permission__content_type", "granted_by_employee", "revoked_by_employee"
        ).order_by("-effective_from", "-id")
        page = self.paginate_queryset(queryset)
        data = CustomerAccessGrantSerializer(page or queryset, many=True).data
        return self.get_paginated_response(data) if page is not None else Response({"data": data})

    def create(self, request, *args, **kwargs):
        customer = self._customer()
        serializer = CustomerAccessGrantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grant = create_access_grant(
            customer=customer, validated_data=serializer.validated_data,
            actor_employee=self.actor_employee(), request=request,
        )
        grant = CustomerDataAccessGrant.objects.select_related(
            "employee", "permission__content_type", "granted_by_employee", "revoked_by_employee"
        ).get(pk=grant.pk)
        return self.response_with_etag(
            {"data": CustomerAccessGrantSerializer(grant).data}, grant, status.HTTP_201_CREATED
        )


class CustomerAccessGrantViewSet(CustomerApiViewSetBase):
    queryset = CustomerDataAccessGrant.objects.all()
    serializer_class = CustomerAccessGrantSerializer
    action_permission_map = {"revoke": "customers.manage_customer_access"}

    def get_queryset(self):
        customers = accessible_customers(self.request, "manage_customer_access")
        return CustomerDataAccessGrant.objects.filter(customer_account__in=customers).select_related(
            "employee", "permission__content_type", "granted_by_employee", "revoked_by_employee"
        )

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        grant = self.get_object()
        grant = revoke_access_grant(grant=grant, actor_employee=self.actor_employee(), request=request)
        return self.response_with_etag({"data": CustomerAccessGrantSerializer(grant).data}, grant)


class CustomerDuplicateCaseViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, CustomerApiViewSetBase
):
    serializer_class = DuplicateCaseSerializer
    action_permission_map = {
        "list": "customers.merge_customer", "retrieve": "customers.merge_customer",
        "create": "customers.merge_customer", "dismiss": "customers.merge_customer",
        "merge_preview": "customers.merge_customer", "merge": "customers.merge_customer",
    }

    def get_queryset(self):
        accessible = accessible_customers(self.request, "merge_customer")
        visible_completed_merge = CustomerMergeMember.objects.filter(
            merge_operation__duplicate_case_id=OuterRef("pk"),
            merge_operation__status=MergeStatus.COMPLETED,
            member_role=MergeMemberRole.SURVIVOR,
            customer_account__in=accessible,
        )
        queryset = CustomerDuplicateCase.objects.annotate(
            candidate_count=Count("candidates", distinct=True),
            visible_candidate_count=Count(
                "candidates", filter=Q(candidates__customer_account__in=accessible), distinct=True
            ),
            has_visible_completed_merge=Exists(visible_completed_merge),
        ).filter(
            Q(candidate_count__gte=2, candidate_count=F("visible_candidate_count"))
            | Q(has_visible_completed_merge=True)
        ).prefetch_related("candidates__customer_account").select_related("reviewer_employee")
        status_value = self.request.query_params.get("status")
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset.order_by("-created_at", "-id")

    def get_object(self):
        case = super().get_object()
        if not _all_case_customers_accessible(self.request, case):
            raise NotFound("去重案例不存在或无权访问。")
        return case

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        data = self.get_serializer(page or queryset, many=True).data
        return self.get_paginated_response(data) if page is not None else Response({"data": data})

    def get_serializer_class(self):
        return DuplicateCaseCreateSerializer if self.action == "create" else DuplicateCaseSerializer

    def create(self, request, *args, **kwargs):
        if self.actor_employee() is None:
            raise PermissionDenied("创建去重案例需要绑定有效员工档案。")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        candidate_ids = [item["customer_id"] for item in serializer.validated_data["candidates"]]
        customers = {
            customer.pk: customer for customer in accessible_customers(request, "merge_customer").filter(
                pk__in=candidate_ids, archived_at__isnull=True
            )
        }
        if len(customers) != len(candidate_ids):
            raise ValidationError({"candidates": "候选客户不存在、已归档或无权合并。"})
        with transaction.atomic():
            case = CustomerDuplicateCase.objects.create(
                reviewer_employee=serializer.validated_data.get("reviewer_employee"),
                matching_strategy_version=serializer.validated_data["matching_strategy_version"],
                notes=serializer.validated_data.get("notes", ""),
            )
            CustomerDuplicateCandidate.objects.bulk_create([
                CustomerDuplicateCandidate(
                    duplicate_case=case, customer_account=customers[item["customer_id"]],
                    confidence_score=item["confidence_score"], matched_fields=item.get("matched_fields", {}),
                ) for item in serializer.validated_data["candidates"]
            ])
            for customer_id in candidate_ids:
                write_audit_log(
                    object_type="CUSTOMER_DUPLICATE_CASE", object_id=case.pk,
                    context_type="CUSTOMER_ACCOUNT", context_id=customer_id, action="CREATED",
                    actor_employee=self.actor_employee(), after_data={"candidate_customer_ids": candidate_ids}, request=request,
                )
        case = self.get_queryset().get(pk=case.pk)
        return self.response_with_etag(
            {"data": DuplicateCaseSerializer(case).data}, case, status.HTTP_201_CREATED
        )

    def retrieve(self, request, *args, **kwargs):
        case = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(case).data}, case)

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        case = self.get_object()
        require_matching_etag(request, case)
        serializer = DecisionNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            case = CustomerDuplicateCase.objects.select_for_update().get(pk=case.pk)
            require_matching_etag(request, case)
            if case.status not in {DuplicateCaseStatus.OPEN, DuplicateCaseStatus.REVIEWING}:
                raise Conflict("当前去重案例不能忽略。")
            case.status = DuplicateCaseStatus.DISMISSED
            case.notes = f"{case.notes}\n忽略原因：{serializer.validated_data['decision_note']}".strip()
            case.save(update_fields=["status", "notes", "updated_at"])
        return self.response_with_etag({"data": DuplicateCaseSerializer(case).data}, case)

    def _merge_input(self, request):
        serializer = MergeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    @action(detail=True, methods=["post"], url_path="merge-preview")
    def merge_preview(self, request, pk=None):
        case = self.get_object()
        if case.status not in {DuplicateCaseStatus.OPEN, DuplicateCaseStatus.REVIEWING}:
            raise Conflict("当前去重案例状态不允许合并预检。")
        return Response({"data": merge_preview(duplicate_case=case, validated_data=self._merge_input(request))})

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        case = self.get_object()
        operation = execute_merge(
            duplicate_case=case, validated_data=self._merge_input(request),
            actor_employee=self.actor_employee(), request=request,
        )
        operation = CustomerMergeOperation.objects.prefetch_related(
            "members__customer_account", "changes"
        ).select_related("executed_by_employee").get(pk=operation.pk)
        return Response({"data": MergeOperationSerializer(operation).data}, status=status.HTTP_201_CREATED)


class CustomerDuplicateCandidateViewSet(CustomerApiViewSetBase):
    queryset = CustomerDuplicateCandidate.objects.all()
    serializer_class = DuplicateDecisionSerializer
    action_permission_map = {"decide": "customers.merge_customer"}

    def get_queryset(self):
        return CustomerDuplicateCandidate.objects.select_related("duplicate_case", "customer_account")

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        candidate = self.get_object()
        if not _all_case_customers_accessible(request, candidate.duplicate_case):
            raise NotFound("候选记录不存在或无权访问。")
        require_matching_etag(request, candidate)
        serializer = DuplicateDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data["decision"]
        with transaction.atomic():
            candidate = CustomerDuplicateCandidate.objects.select_for_update().select_related("duplicate_case").get(pk=candidate.pk)
            require_matching_etag(request, candidate)
            case = CustomerDuplicateCase.objects.select_for_update().get(pk=candidate.duplicate_case_id)
            if case.status not in {DuplicateCaseStatus.OPEN, DuplicateCaseStatus.REVIEWING}:
                raise Conflict("当前去重案例不能继续判断。")
            if decision == DuplicateDecision.SURVIVOR and case.candidates.exclude(pk=candidate.pk).filter(
                decision=DuplicateDecision.SURVIVOR
            ).exists():
                raise Conflict("一个去重案例只能有一个存续客户。")
            candidate.decision = decision
            candidate.save(update_fields=["decision", "updated_at"])
            if case.status == DuplicateCaseStatus.OPEN:
                case.status = DuplicateCaseStatus.REVIEWING
                case.save(update_fields=["status", "updated_at"])
            write_audit_log(
                object_type="CUSTOMER_DUPLICATE_CANDIDATE", object_id=candidate.pk,
                context_type="CUSTOMER_ACCOUNT", context_id=candidate.customer_account_id, action="DECIDED",
                actor_employee=self.actor_employee(), after_data={"decision": decision}, request=request,
            )
        return self.response_with_etag(
            {"data": {"id": str(candidate.pk), "decision": candidate.decision}}, candidate
        )


class CustomerMergeOperationViewSet(mixins.RetrieveModelMixin, CustomerApiViewSetBase):
    serializer_class = MergeOperationSerializer
    action_permission_map = {"retrieve": "customers.merge_customer"}

    def get_queryset(self):
        return CustomerMergeOperation.objects.prefetch_related(
            "members__customer_account", "changes"
        ).select_related("executed_by_employee")

    def retrieve(self, request, *args, **kwargs):
        operation = self.get_object()
        survivor_ids = list(operation.members.filter(member_role=MergeMemberRole.SURVIVOR).values_list("customer_account_id", flat=True))
        if len(survivor_ids) != 1 or not accessible_customers(request, "merge_customer").filter(pk=survivor_ids[0]).exists():
            raise NotFound("合并记录不存在或无权访问。")
        return self.response_with_etag({"data": self.get_serializer(operation).data}, operation)
