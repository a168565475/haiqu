from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.crm.models import CustomerCommunication, CustomerTimelineEvent
from apps.inquiries.models import Inquiry
from apps.quotations.models import Quotation
from apps.samples.models import SampleRequest

from .models import (
    AssignmentRole,
    CustomerAccount,
    CustomerAssignment,
    CustomerContact,
    CustomerDataAccessGrant,
    CustomerDuplicateCandidate,
    CustomerDuplicateCase,
    CustomerFileLink,
    CustomerMergeChange,
    CustomerMergeMember,
    CustomerMergeOperation,
    CustomerTaskLink,
    CustomerTransferRequest,
    CustomerTransactionEntity,
    DuplicateCaseStatus,
    DuplicateDecision,
    MergeMemberRole,
    MergeStatus,
    TransferStatus,
)
from .services import model_snapshot, write_customer_timeline


MERGEABLE_FIELDS = {
    "account_name", "english_name", "short_name", "lifecycle_stage", "primary_country_code",
    "primary_website_url", "source_system", "external_id", "notes",
}


def _current_period(now):
    return Q(effective_from__lte=now) & (Q(effective_to__isnull=True) | Q(effective_to__gt=now))


def create_transfer_request(*, customer, to_employee, reason, actor_employee, request):
    if actor_employee is None:
        raise PermissionDenied("发起客户转移需要绑定有效员工档案。")
    now = timezone.now()
    with transaction.atomic():
        locked_customer = CustomerAccount.objects.select_for_update().get(pk=customer.pk)
        current_owner = CustomerAssignment.objects.select_for_update().filter(
            _current_period(now), customer_account=locked_customer, assignment_role=AssignmentRole.PRIMARY_OWNER
        ).select_related("employee").first()
        if current_owner is None:
            raise Conflict("客户当前没有有效主负责人，不能发起转移。")
        if current_owner.employee_id == to_employee.pk:
            raise ValidationError({"to_employee_id": "新负责人不能与当前负责人相同。"})
        if locked_customer.transfer_requests.filter(status=TransferStatus.PENDING).exists():
            raise Conflict("该客户已有待处理的转移申请。")
        transfer = locked_customer.transfer_requests.create(
            from_employee=current_owner.employee,
            to_employee=to_employee,
            requested_by_employee=actor_employee,
            request_reason=reason,
            submitted_at=now,
        )
        write_audit_log(
            object_type="CUSTOMER_TRANSFER_REQUEST", object_id=transfer.pk,
            context_type="CUSTOMER_ACCOUNT", context_id=locked_customer.pk, action="CREATED",
            actor_employee=actor_employee,
            after_data={"from_employee_id": current_owner.employee_id, "to_employee_id": to_employee.pk, "reason": reason},
            request=request,
        )
        write_customer_timeline(
            customer=locked_customer, event_type="CUSTOMER_TRANSFER_REQUESTED", title="客户转移申请已提交",
            summary=reason, source_type="CUSTOMER_TRANSFER_REQUEST", source_id=transfer.pk,
            actor_employee=actor_employee,
        )
    return transfer


def decide_transfer(*, transfer, decision, note, actor_employee, request):
    if actor_employee is None:
        raise PermissionDenied("审批客户转移需要绑定有效员工档案。")
    require_matching_etag(request, transfer)
    now = timezone.now()
    with transaction.atomic():
        locked = CustomerAccount.objects.select_for_update().get(pk=transfer.customer_account_id)
        transfer = transfer.__class__.objects.select_for_update().get(pk=transfer.pk)
        require_matching_etag(request, transfer)
        if transfer.status != TransferStatus.PENDING:
            raise Conflict("该转移申请已处理，不能重复审批。")
        if decision == TransferStatus.APPROVED:
            current_owner = CustomerAssignment.objects.select_for_update().filter(
                _current_period(now), customer_account=locked, assignment_role=AssignmentRole.PRIMARY_OWNER
            ).first()
            if current_owner is None or current_owner.employee_id != transfer.from_employee_id:
                raise Conflict("客户当前负责人已变化，请重新发起转移申请。")
            current_owner.effective_to = now
            current_owner.save(update_fields=["effective_to", "updated_at"])
            CustomerAssignment.objects.create(
                customer_account=locked, employee=transfer.to_employee,
                assignment_role=AssignmentRole.PRIMARY_OWNER, effective_from=now,
                assigned_by_employee=actor_employee, reason=f"转移申请 {transfer.pk} 审批通过",
            )
        transfer.status = decision
        transfer.decision_note = note
        transfer.decided_by_employee = actor_employee
        transfer.decided_at = now
        transfer.save(update_fields=["status", "decision_note", "decided_by_employee", "decided_at", "updated_at"])
        write_audit_log(
            object_type="CUSTOMER_TRANSFER_REQUEST", object_id=transfer.pk,
            context_type="CUSTOMER_ACCOUNT", context_id=locked.pk, action=decision,
            actor_employee=actor_employee, after_data={"status": decision, "decision_note": note}, request=request,
        )
        write_customer_timeline(
            customer=locked, event_type=f"CUSTOMER_TRANSFER_{decision}", title=f"客户转移{transfer.get_status_display()}",
            summary=note, source_type="CUSTOMER_TRANSFER_REQUEST", source_id=transfer.pk,
            actor_employee=actor_employee,
        )
    return transfer


def cancel_transfer(*, transfer, note, actor_employee, request):
    if actor_employee is None or transfer.requested_by_employee_id != actor_employee.pk:
        raise PermissionDenied("仅申请人可以取消待处理的转移申请。")
    return decide_transfer(
        transfer=transfer, decision=TransferStatus.CANCELLED, note=note,
        actor_employee=actor_employee, request=request,
    )


def create_access_grant(*, customer, validated_data, actor_employee, request):
    if actor_employee is None:
        raise PermissionDenied("管理客户授权需要绑定有效员工档案。")
    now = timezone.now()
    effective_from = validated_data.get("effective_from", now)
    effective_to = validated_data.get("effective_to")
    if effective_to and effective_to <= effective_from:
        raise ValidationError({"effective_to": "结束时间必须晚于开始时间。"})
    try:
        with transaction.atomic():
            grant = CustomerDataAccessGrant.objects.create(
                employee=validated_data["employee"], customer_account=customer,
                permission=validated_data["permission_code"], effective_from=effective_from,
                effective_to=effective_to, granted_by_employee=actor_employee, reason=validated_data["reason"],
            )
            write_audit_log(
                object_type="CUSTOMER_DATA_ACCESS_GRANT", object_id=grant.pk,
                context_type="CUSTOMER_ACCOUNT", context_id=customer.pk, action="CREATED",
                actor_employee=actor_employee,
                after_data={
                    "employee_id": grant.employee_id,
                    "permission": f"{grant.permission.content_type.app_label}.{grant.permission.codename}",
                    "effective_from": effective_from, "effective_to": effective_to, "reason": grant.reason,
                }, request=request,
            )
    except IntegrityError as exc:
        raise Conflict("该员工在相同有效期内已经拥有同一客户权限。") from exc
    return grant


def revoke_access_grant(*, grant, actor_employee, request):
    if actor_employee is None:
        raise PermissionDenied("撤销客户授权需要绑定有效员工档案。")
    require_matching_etag(request, grant)
    now = timezone.now()
    with transaction.atomic():
        grant = CustomerDataAccessGrant.objects.select_for_update().get(pk=grant.pk)
        require_matching_etag(request, grant)
        if grant.revoked_at is not None:
            raise Conflict("该授权已被撤销。")
        grant.revoked_at = now
        grant.revoked_by_employee = actor_employee
        if grant.effective_to is None or grant.effective_to > now:
            grant.effective_to = now
        grant.save(update_fields=["revoked_at", "revoked_by_employee", "effective_to", "updated_at"])
        write_audit_log(
            object_type="CUSTOMER_DATA_ACCESS_GRANT", object_id=grant.pk,
            context_type="CUSTOMER_ACCOUNT", context_id=grant.customer_account_id, action="REVOKED",
            actor_employee=actor_employee, after_data={"revoked_at": now}, request=request,
        )
    return grant


def validate_merge_request(*, duplicate_case, validated_data, lock=False):
    member_ids = [validated_data["survivor_customer_id"], *validated_data["source_customer_ids"]]
    customer_query = CustomerAccount.objects.filter(pk__in=member_ids)
    if lock:
        customer_query = customer_query.select_for_update().order_by("pk")
    customers = {customer.pk: customer for customer in customer_query}
    if len(customers) != len(member_ids):
        raise ValidationError({"source_customer_ids": "存续客户或来源客户不存在。"})
    if customers[validated_data["survivor_customer_id"]].archived_at is not None:
        raise Conflict("存续客户已归档，不能执行合并。")
    if any(customers[item].archived_at is not None for item in validated_data["source_customer_ids"]):
        raise Conflict("来源客户中存在已归档记录，不能重复合并。")

    candidates = {
        item.customer_account_id: item
        for item in duplicate_case.candidates.filter(customer_account_id__in=member_ids)
    }
    if len(candidates) != len(member_ids):
        raise ValidationError("所有合并成员都必须属于当前去重案例。")
    if candidates[validated_data["survivor_customer_id"]].decision != DuplicateDecision.SURVIVOR:
        raise Conflict("存续客户候选必须先标记为“存续客户”。")
    if any(candidates[item].decision != DuplicateDecision.DUPLICATE for item in validated_data["source_customer_ids"]):
        raise Conflict("每个来源客户候选都必须先标记为“重复”。")

    decisions = validated_data.get("field_decisions", {})
    invalid_fields = set(decisions) - MERGEABLE_FIELDS
    if invalid_fields:
        raise ValidationError({"field_decisions": f"不允许合并字段：{', '.join(sorted(invalid_fields))}。"})
    for field_name, selected_customer_id in decisions.items():
        try:
            selected_customer_id = type(validated_data["survivor_customer_id"])(str(selected_customer_id))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"field_decisions": f"{field_name} 的值必须是候选客户 UUID。"}) from exc
        if selected_customer_id not in customers:
            raise ValidationError({"field_decisions": f"{field_name} 选择的客户不在合并成员中。"})
        decisions[field_name] = selected_customer_id

    survivor = customers[validated_data["survivor_customer_id"]]
    final_values = {field: getattr(survivor, field) for field in MERGEABLE_FIELDS}
    for field_name, selected_customer_id in decisions.items():
        final_values[field_name] = getattr(customers[selected_customer_id], field_name)
    if bool(final_values["source_system"]) != bool(final_values["external_id"]):
        raise ValidationError({"field_decisions": "来源系统和外部编号的最终值必须同时存在或同时留空。"})
    if final_values["source_system"] and CustomerAccount.objects.exclude(pk__in=member_ids).filter(
        source_system=final_values["source_system"], external_id=final_values["external_id"]
    ).exists():
        raise Conflict("合并后的来源系统与外部编号已被其他客户占用。")
    return customers, final_values


def merge_preview(*, duplicate_case, validated_data):
    customers, final_values = validate_merge_request(duplicate_case=duplicate_case, validated_data=validated_data)
    source_ids = validated_data["source_customer_ids"]
    return {
        "case_id": str(duplicate_case.pk),
        "survivor_customer_id": str(validated_data["survivor_customer_id"]),
        "source_customer_ids": [str(item) for item in source_ids],
        "resolved_fields": final_values,
        "move_counts": {
            "transaction_entities": CustomerTransactionEntity.objects.filter(customer_account_id__in=source_ids).count(),
            "contacts": CustomerContact.objects.filter(customer_account_id__in=source_ids).count(),
            "communications": CustomerCommunication.objects.filter(customer_account_id__in=source_ids).count(),
            "inquiries": Inquiry.objects.filter(customer_account_id__in=source_ids).count(),
            "quotations": Quotation.objects.filter(customer_account_id__in=source_ids).count(),
            "sample_requests": SampleRequest.objects.filter(customer_account_id__in=source_ids).count(),
            "timeline_events": CustomerTimelineEvent.objects.filter(customer_account_id__in=source_ids).count(),
        },
        "warnings": ["来源客户会归档；历史负责人、历史授权、审计日志和合并证据不会改写。"],
    }


def _record_group_change(operation, sequence, object_type, object_ids, survivor_id):
    if not object_ids:
        return sequence
    CustomerMergeChange.objects.create(
        merge_operation=operation, sequence_number=sequence, object_type=object_type,
        object_id=survivor_id,
        change_data={"moved_count": len(object_ids), "object_ids": [str(item) for item in object_ids], "to_customer_id": str(survivor_id)},
    )
    return sequence + 1


def execute_merge(*, duplicate_case, validated_data, actor_employee, request):
    if actor_employee is None:
        raise PermissionDenied("执行客户合并需要绑定有效员工档案。")
    require_matching_etag(request, duplicate_case)
    now = timezone.now()
    try:
        with transaction.atomic():
            duplicate_case = CustomerDuplicateCase.objects.select_for_update().get(pk=duplicate_case.pk)
            require_matching_etag(request, duplicate_case)
            if duplicate_case.status not in {DuplicateCaseStatus.OPEN, DuplicateCaseStatus.REVIEWING}:
                raise Conflict("当前去重案例状态不允许合并。")
            customers, final_values = validate_merge_request(
                duplicate_case=duplicate_case, validated_data=validated_data, lock=True
            )
            survivor = customers[validated_data["survivor_customer_id"]]
            source_ids = validated_data["source_customer_ids"]
            before_survivor = model_snapshot(survivor, sorted(MERGEABLE_FIELDS))
            operation = CustomerMergeOperation.objects.create(
                duplicate_case=duplicate_case, executed_by_employee=actor_employee,
                status=MergeStatus.PLANNED, reason=validated_data["reason"],
            )
            CustomerMergeMember.objects.create(
                merge_operation=operation, customer_account=survivor, member_role=MergeMemberRole.SURVIVOR
            )
            CustomerMergeMember.objects.bulk_create([
                CustomerMergeMember(merge_operation=operation, customer_account=customers[item], member_role=MergeMemberRole.SOURCE)
                for item in source_ids
            ])

            changed_fields = []
            for field_name, value in final_values.items():
                if getattr(survivor, field_name) != value:
                    setattr(survivor, field_name, value)
                    changed_fields.append(field_name)
            if changed_fields:
                survivor.save(update_fields=[*changed_fields, "updated_at"])

            sequence = 1
            if changed_fields:
                CustomerMergeChange.objects.create(
                    merge_operation=operation, sequence_number=sequence, object_type="CUSTOMER_ACCOUNT",
                    object_id=survivor.pk,
                    change_data={"before": before_survivor, "after": model_snapshot(survivor, sorted(MERGEABLE_FIELDS))},
                )
                sequence += 1

            entity_ids = list(CustomerTransactionEntity.objects.filter(customer_account_id__in=source_ids).values_list("pk", flat=True))
            CustomerTransactionEntity.objects.filter(pk__in=entity_ids).update(customer_account=survivor, updated_at=now)
            sequence = _record_group_change(operation, sequence, "CUSTOMER_TRANSACTION_ENTITY", entity_ids, survivor.pk)

            contact_query = CustomerContact.objects.filter(customer_account_id__in=source_ids)
            contact_ids = list(contact_query.values_list("pk", flat=True))
            source_contact_links = list(
                contact_query.exclude(source_contact_id=None).values_list("pk", "source_contact_id")
            )
            # 同一条 UPDATE 同时切换客户并清空旧联系人链，避免数据库一致性触发器看到中间态。
            CustomerContact.objects.filter(pk__in=contact_ids).update(
                customer_account=survivor, source_contact=None, updated_at=now
            )
            # 全部联系人完成归属切换后恢复沿革关系，此时前后联系人已经属于同一存续客户。
            for contact_id, source_contact_id in source_contact_links:
                CustomerContact.objects.filter(pk=contact_id).update(
                    source_contact_id=source_contact_id, updated_at=now
                )
            sequence = _record_group_change(operation, sequence, "CUSTOMER_CONTACT", contact_ids, survivor.pk)

            inquiry_ids = list(Inquiry.objects.filter(customer_account_id__in=source_ids).values_list("pk", flat=True))
            Inquiry.objects.filter(pk__in=inquiry_ids).update(customer_account=survivor, updated_at=now)
            sequence = _record_group_change(operation, sequence, "INQUIRY", inquiry_ids, survivor.pk)

            quotation_ids = list(Quotation.objects.filter(customer_account_id__in=source_ids).values_list("pk", flat=True))
            Quotation.objects.filter(pk__in=quotation_ids).update(customer_account=survivor, updated_at=now)
            sequence = _record_group_change(operation, sequence, "QUOTATION", quotation_ids, survivor.pk)

            sample_ids = list(SampleRequest.objects.filter(customer_account_id__in=source_ids).values_list("pk", flat=True))
            SampleRequest.objects.filter(pk__in=sample_ids).update(customer_account=survivor, updated_at=now)
            sequence = _record_group_change(operation, sequence, "SAMPLE_REQUEST", sample_ids, survivor.pk)

            communication_ids = list(CustomerCommunication.objects.filter(customer_account_id__in=source_ids).values_list("pk", flat=True))
            CustomerCommunication.objects.filter(pk__in=communication_ids).update(customer_account=survivor, updated_at=now)
            sequence = _record_group_change(operation, sequence, "CUSTOMER_COMMUNICATION", communication_ids, survivor.pk)

            timeline_ids = list(CustomerTimelineEvent.objects.filter(customer_account_id__in=source_ids).values_list("pk", flat=True))
            CustomerTimelineEvent.objects.filter(pk__in=timeline_ids).update(customer_account=survivor, updated_at=now)
            sequence = _record_group_change(operation, sequence, "CUSTOMER_TIMELINE_EVENT", timeline_ids, survivor.pk)

            for link in CustomerFileLink.objects.select_for_update().filter(customer_account_id__in=source_ids):
                existing = CustomerFileLink.objects.filter(customer_account=survivor, business_file=link.business_file).first()
                if existing:
                    link.delete()
                else:
                    link.customer_account = survivor
                    link.save(update_fields=["customer_account", "updated_at"])
            for link in CustomerTaskLink.objects.select_for_update().filter(customer_account_id__in=source_ids):
                existing = CustomerTaskLink.objects.filter(customer_account=survivor, business_task=link.business_task).first()
                if existing:
                    link.delete()
                else:
                    link.customer_account = survivor
                    link.save(update_fields=["customer_account", "updated_at"])

            active_assignments = CustomerAssignment.objects.select_for_update().filter(
                _current_period(now), customer_account_id__in=source_ids
            )
            active_assignments.update(effective_to=now, updated_at=now)
            active_grants = CustomerDataAccessGrant.objects.select_for_update().filter(
                _current_period(now), customer_account_id__in=source_ids, revoked_at__isnull=True
            )
            active_grants.update(effective_to=now, revoked_at=now, revoked_by_employee=actor_employee, updated_at=now)
            CustomerTransferRequest.objects.select_for_update().filter(
                customer_account_id__in=source_ids, status=TransferStatus.PENDING
            ).update(
                status=TransferStatus.CANCELLED, decision_note="来源客户已合并，申请自动取消",
                decided_by_employee=actor_employee, decided_at=now, updated_at=now,
            )

            for source_id in source_ids:
                source = customers[source_id]
                source.archived_at = now
                source.archived_by_employee = actor_employee
                source.archive_reason = f"合并至 {survivor.account_code}：{validated_data['reason']}"[:500]
                source.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])

            duplicate_case.status = DuplicateCaseStatus.RESOLVED
            duplicate_case.save(update_fields=["status", "updated_at"])
            operation.status = MergeStatus.COMPLETED
            operation.executed_at = now
            operation.save(update_fields=["status", "executed_at", "updated_at"])
            write_audit_log(
                object_type="CUSTOMER_MERGE_OPERATION", object_id=operation.pk,
                context_type="CUSTOMER_ACCOUNT", context_id=survivor.pk, action="COMPLETED",
                actor_employee=actor_employee,
                after_data={"survivor_customer_id": survivor.pk, "source_customer_ids": source_ids, "reason": operation.reason},
                request=request,
            )
            write_customer_timeline(
                customer=survivor, event_type="CUSTOMER_MERGED", title="客户合并已完成",
                summary=operation.reason, source_type="CUSTOMER_MERGE_OPERATION", source_id=operation.pk,
                actor_employee=actor_employee,
            )
    except IntegrityError as exc:
        raise Conflict("客户合并与当前数据约束冲突，操作已整体回滚。") from exc
    return operation
