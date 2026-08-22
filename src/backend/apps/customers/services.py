import re
import uuid

from django.db import transaction
from django.forms.models import model_to_dict
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.crm.models import CustomerTimelineEvent

from .models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerAttentionReview,
    CustomerContactMethod,
)


def model_snapshot(instance, field_names):
    data = model_to_dict(instance, fields=field_names)
    data["id"] = instance.pk
    return data


def write_customer_timeline(
    *,
    customer,
    event_type,
    title,
    source_type,
    source_id,
    actor_employee=None,
    summary="",
    event_data=None,
    occurred_at=None,
):
    return CustomerTimelineEvent.objects.create(
        customer_account=customer,
        event_key=f"{source_type}:{source_id}:{event_type}:{uuid.uuid4()}",
        source_type=source_type,
        source_id=source_id,
        event_type=event_type,
        title=title,
        summary=summary,
        occurred_at=occurred_at or timezone.now(),
        event_data={
            **(event_data or {}),
            "actor_employee_id": str(actor_employee.pk) if actor_employee else None,
        },
    )


@transaction.atomic
def create_customer(*, validated_data, actor_employee, request):
    primary_owner = validated_data.pop("primary_owner_employee")
    customer = CustomerAccount.objects.create(
        account_code=next_business_number("CUSTOMER"),
        **validated_data,
    )
    assignment = CustomerAssignment.objects.create(
        customer_account=customer,
        employee=primary_owner,
        assignment_role="PRIMARY_OWNER",
        effective_from=timezone.now(),
        assigned_by_employee=actor_employee,
        reason="客户建档时指定主负责人",
    )
    write_audit_log(
        object_type="CUSTOMER_ACCOUNT",
        object_id=customer.pk,
        action="CREATED",
        actor_employee=actor_employee,
        after_data=model_snapshot(
            customer,
            [
                "account_code",
                "account_name",
                "english_name",
                "short_name",
                "lifecycle_stage",
                "primary_country_code",
                "primary_website_url",
                "source_system",
                "external_id",
                "notes",
            ],
        ),
        request=request,
    )
    write_customer_timeline(
        customer=customer,
        event_type="CUSTOMER_CREATED",
        title="客户建档",
        source_type="CUSTOMER_ACCOUNT",
        source_id=customer.pk,
        actor_employee=actor_employee,
        event_data={"primary_owner_employee_id": str(primary_owner.pk)},
    )
    return customer, assignment


@transaction.atomic
def update_customer(*, customer, validated_data, actor_employee, request):
    customer = CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    require_matching_etag(request, customer)
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
    before_data = model_snapshot(customer, fields)
    for field_name, value in validated_data.items():
        setattr(customer, field_name, value)
    customer.save(update_fields=[*validated_data.keys(), "updated_at"])
    after_data = model_snapshot(customer, fields)
    write_audit_log(
        object_type="CUSTOMER_ACCOUNT",
        object_id=customer.pk,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=after_data,
        request=request,
    )
    write_customer_timeline(
        customer=customer,
        event_type="CUSTOMER_UPDATED",
        title="客户档案已更新",
        source_type="CUSTOMER_ACCOUNT",
        source_id=customer.pk,
        actor_employee=actor_employee,
    )
    return customer


@transaction.atomic
def archive_resource(
    *,
    instance,
    reason,
    actor_employee,
    request,
    object_type,
    customer,
):
    instance = instance.__class__.objects.select_for_update().get(pk=instance.pk)
    require_matching_etag(request, instance)
    if instance.archived_at is not None:
        raise ValidationError({"reason": ["该记录已经归档。"]})
    before_data = model_snapshot(instance, ["archived_at", "archive_reason"])
    instance.archived_at = timezone.now()
    instance.archived_by_employee = actor_employee
    instance.archive_reason = reason
    instance.save(
        update_fields=[
            "archived_at",
            "archived_by_employee",
            "archive_reason",
            "updated_at",
        ]
    )
    write_audit_log(
        object_type=object_type,
        object_id=instance.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=customer.pk,
        action="ARCHIVED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=model_snapshot(instance, ["archived_at", "archive_reason"]),
        request=request,
    )
    write_customer_timeline(
        customer=customer,
        event_type=f"{object_type}_ARCHIVED",
        title="业务记录已归档",
        summary=reason,
        source_type=object_type,
        source_id=instance.pk,
        actor_employee=actor_employee,
    )
    return instance


@transaction.atomic
def restore_customer(*, customer, actor_employee, request):
    customer = CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    require_matching_etag(request, customer)
    if customer.archived_at is None:
        raise ValidationError({"detail": ["该客户未归档。"]})
    before_data = model_snapshot(customer, ["archived_at", "archive_reason"])
    customer.archived_at = None
    customer.archived_by_employee = None
    customer.archive_reason = ""
    customer.save(
        update_fields=[
            "archived_at",
            "archived_by_employee",
            "archive_reason",
            "updated_at",
        ]
    )
    write_audit_log(
        object_type="CUSTOMER_ACCOUNT",
        object_id=customer.pk,
        action="RESTORED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=model_snapshot(customer, ["archived_at", "archive_reason"]),
        request=request,
    )
    write_customer_timeline(
        customer=customer,
        event_type="CUSTOMER_RESTORED",
        title="客户已恢复",
        source_type="CUSTOMER_ACCOUNT",
        source_id=customer.pk,
        actor_employee=actor_employee,
    )
    return customer


@transaction.atomic
def add_collaborator(*, customer, employee, effective_from, reason, actor_employee, request):
    CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    effective_from = effective_from or timezone.now()
    active_exists = CustomerAssignment.objects.filter(
        customer_account=customer,
        employee=employee,
        assignment_role="COLLABORATOR",
        effective_to__isnull=True,
    ).exists()
    if active_exists:
        raise ValidationError({"employee_id": ["该员工已经是当前协作人。"]})

    assignment = CustomerAssignment.objects.create(
        customer_account=customer,
        employee=employee,
        assignment_role="COLLABORATOR",
        effective_from=effective_from,
        assigned_by_employee=actor_employee,
        reason=reason,
    )
    write_audit_log(
        object_type="CUSTOMER_ASSIGNMENT",
        object_id=assignment.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=customer.pk,
        action="COLLABORATOR_ADDED",
        actor_employee=actor_employee,
        after_data={
            "employee_id": employee.pk,
            "effective_from": effective_from,
            "reason": reason,
        },
        request=request,
    )
    write_customer_timeline(
        customer=customer,
        event_type="CUSTOMER_COLLABORATOR_ADDED",
        title="新增客户协作人",
        summary=reason,
        source_type="CUSTOMER_ASSIGNMENT",
        source_id=assignment.pk,
        actor_employee=actor_employee,
        event_data={"employee_id": str(employee.pk)},
    )
    return assignment


@transaction.atomic
def end_collaborator(*, customer, employee_id, reason, actor_employee, request):
    CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    assignment = (
        CustomerAssignment.objects.select_for_update()
        .filter(
            customer_account=customer,
            employee_id=employee_id,
            assignment_role="COLLABORATOR",
            effective_to__isnull=True,
        )
        .first()
    )
    if assignment is None:
        raise ValidationError({"employee_id": ["该员工不是当前协作人。"]})

    assignment.effective_to = timezone.now()
    if reason:
        assignment.reason = reason
    assignment.save(update_fields=["effective_to", "reason", "updated_at"])
    write_audit_log(
        object_type="CUSTOMER_ASSIGNMENT",
        object_id=assignment.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=customer.pk,
        action="COLLABORATOR_ENDED",
        actor_employee=actor_employee,
        after_data={"effective_to": assignment.effective_to, "reason": assignment.reason},
        request=request,
    )
    write_customer_timeline(
        customer=customer,
        event_type="CUSTOMER_COLLABORATOR_ENDED",
        title="结束客户协作",
        summary=assignment.reason,
        source_type="CUSTOMER_ASSIGNMENT",
        source_id=assignment.pk,
        actor_employee=actor_employee,
        event_data={"employee_id": str(assignment.employee_id)},
    )
    return assignment


@transaction.atomic
def set_attention(*, customer, attention_level_item, reason, actor_employee, request):
    if actor_employee is None:
        raise ValidationError({"detail": ["设置客户关注等级需要绑定有效员工档案。"]})

    CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    now = timezone.now()
    CustomerAttentionReview.objects.select_for_update().filter(
        customer_account=customer,
        effective_to__isnull=True,
    ).update(effective_to=now, updated_at=now)
    review = CustomerAttentionReview.objects.create(
        customer_account=customer,
        attention_level_item=attention_level_item,
        reviewed_by_employee=actor_employee,
        reason=reason,
        effective_from=now,
    )
    write_audit_log(
        object_type="CUSTOMER_ATTENTION_REVIEW",
        object_id=review.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=customer.pk,
        action="ATTENTION_CHANGED",
        actor_employee=actor_employee,
        after_data={
            "attention_level_item_id": attention_level_item.pk,
            "item_code": attention_level_item.item_code,
            "reason": reason,
            "effective_from": now,
        },
        request=request,
    )
    write_customer_timeline(
        customer=customer,
        event_type="CUSTOMER_ATTENTION_CHANGED",
        title="客户关注等级已调整",
        summary=reason,
        source_type="CUSTOMER_ATTENTION_REVIEW",
        source_id=review.pk,
        actor_employee=actor_employee,
        event_data={"attention_level": attention_level_item.item_code},
    )
    return review


def normalize_contact_value(method_type, raw_value):
    value = raw_value.strip()
    if not value:
        raise ValidationError({"raw_value": ["联系方式不能为空。"]})
    if method_type == "EMAIL":
        if "@" not in value:
            raise ValidationError({"raw_value": ["邮箱格式不正确。"]})
        return value.lower()
    if method_type in {"PHONE", "MOBILE", "WHATSAPP"}:
        prefix = "+" if value.startswith("+") else ""
        digits = re.sub(r"\D", "", value)
        if len(digits) < 6:
            raise ValidationError({"raw_value": ["电话号码长度不足。"]})
        return f"{prefix}{digits}"
    return value


def prepare_contact_method(validated_data):
    normalized_value = normalize_contact_value(
        validated_data["method_type"],
        validated_data["raw_value"],
    )
    return {
        **validated_data,
        "normalized_value": normalized_value,
        "normalization_version": 1,
        "normalized_at": timezone.now(),
    }
