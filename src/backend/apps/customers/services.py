from apps.access_control import sales_policy as sales_policy
import json
import re
import uuid

from django.core.serializers.json import DjangoJSONEncoder
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
    CustomerActivityReview,
    CustomerAssignment,
    CustomerAttentionReview,
    CustomerBusinessSnapshot,
    CustomerContact,
    CustomerContactMethod,
    CustomerGradeReview,
    CustomerInterestedProduct,
    CustomerSourceAttribution,
    CustomerTagAssignment,
    CustomerTypeAssignment,
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
    safe_event_data = json.loads(DjangoJSONEncoder().encode(event_data or {}))
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
            **safe_event_data,
            "actor_employee_id": str(actor_employee.pk) if actor_employee else None,
        },
    )


@transaction.atomic
def create_customer(*, validated_data, actor_employee, request):
    primary_owner = validated_data.pop("primary_owner_employee", None) or actor_employee
    sales_policy.require_owner(request, "customers.add_customeraccount", primary_owner, field="primary_owner_employee_id")
    source_item = validated_data.pop("customer_source_item")
    grade_item = validated_data.pop("customer_grade_item", None)
    type_items = validated_data.pop("customer_type_items", [])
    customer_tags = validated_data.pop("customer_tags", [])
    interested_product_items = validated_data.pop("interested_product_items", [])
    contact_name = validated_data.pop("contact_name", "").strip()
    contact_method_type = validated_data.pop("contact_method_type", "")
    contact_method_value = validated_data.pop("contact_method_value", "").strip()
    if primary_owner is None:
        raise ValidationError({"primary_owner_employee_id": ["当前账号未绑定员工，请明确选择负责人。"]})
    if (
        not sales_policy.enabled()
        and actor_employee is not None
        and primary_owner.pk != actor_employee.pk
        and not request.user.has_perm("customers.transfer_customer")
    ):
        raise ValidationError({"primary_owner_employee_id": ["你没有为其他员工创建客户的权限。"]})

    now = timezone.now()
    # 新建客户的建档信息由系统自动写入；历史导入可以明确传入原始值。
    validated_data.setdefault("recorded_by_employee", actor_employee)
    validated_data.setdefault("recorded_at", now)
    customer = CustomerAccount.objects.create(
        account_code=next_business_number("CUSTOMER"),
        **validated_data,
    )
    assignment = CustomerAssignment.objects.create(
        customer_account=customer,
        employee=primary_owner,
        assignment_role="PRIMARY_OWNER",
        effective_from=now,
        assigned_by_employee=actor_employee,
        reason="客户建档时指定主负责人",
    )
    CustomerSourceAttribution.objects.create(
        customer_account=customer,
        source_item=source_item,
        recorded_by_employee=actor_employee or primary_owner,
        notes="客户建档时记录的首次来源",
        effective_from=now,
    )
    if grade_item is not None:
        CustomerGradeReview.objects.create(
            customer_account=customer,
            grade_item=grade_item,
            reviewed_by_employee=actor_employee or primary_owner,
            reason="客户建档时设置初始等级",
            effective_from=now,
        )
    CustomerTypeAssignment.objects.bulk_create(
        [
            CustomerTypeAssignment(
                customer_account=customer,
                type_item=type_item,
                assigned_by_employee=actor_employee or primary_owner,
                reason="客户建档时设置初始类型",
                effective_from=now,
            )
            for type_item in type_items
        ]
    )
    CustomerTagAssignment.objects.bulk_create(
        [
            CustomerTagAssignment(
                customer_account=customer,
                customer_tag=customer_tag,
                assigned_by_employee=actor_employee or primary_owner,
                reason="客户建档时设置初始标签",
                effective_from=now,
            )
            for customer_tag in customer_tags
        ]
    )
    CustomerInterestedProduct.objects.bulk_create(
        [
            CustomerInterestedProduct(
                customer_account=customer,
                product_item=product_item,
                assigned_by_employee=actor_employee or primary_owner,
            )
            for product_item in interested_product_items
        ]
    )
    CustomerActivityReview.objects.create(
        customer_account=customer,
        activity_status="INSUFFICIENT_DATA",
        source_type="SYSTEM",
        reason="客户刚建档，互动和交易数据不足。",
        formula_version="initial-v1",
        effective_from=now,
    )
    if contact_name:
        contact = CustomerContact.objects.create(
            customer_account=customer,
            display_name=contact_name,
        )
        if contact_method_type and contact_method_value:
            method_data = prepare_contact_method(
                {
                    "method_type": contact_method_type,
                    "raw_value": contact_method_value,
                    "is_primary": True,
                    "is_preferred": True,
                }
            )
            CustomerContactMethod.objects.create(customer_contact=contact, **method_data)
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
                "legacy_source_data",
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
        event_data={
            "primary_owner_employee_id": str(primary_owner.pk),
            "customer_source": source_item.item_code,
        },
    )
    return customer, assignment


@transaction.atomic
def set_initial_activity_to_follow_up_from_imported_contact(*, customer):
    """仅将初始的“数据不足”状态更新为源表联系记录对应的“需跟进”。"""
    CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    current_review = (
        CustomerActivityReview.objects.select_for_update()
        .filter(customer_account=customer, effective_to__isnull=True)
        .first()
    )
    if (
        current_review is None
        or current_review.activity_status != "INSUFFICIENT_DATA"
        or current_review.source_type != "SYSTEM"
        or current_review.formula_version != "initial-v1"
    ):
        return None

    now = timezone.now()
    current_review.effective_to = now
    current_review.save(update_fields=["effective_to", "updated_at"])
    return CustomerActivityReview.objects.create(
        customer_account=customer,
        activity_status="FOLLOW_UP",
        source_type="SYSTEM",
        reason="源表已导入最后联系时间，未导入下次跟进时间。",
        formula_version="ente-last-contact-v1",
        effective_from=now,
    )


@transaction.atomic
def update_customer(*, customer, validated_data, actor_employee, request):
    customer = CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    require_matching_etag(request, customer)
    interested_product_items = validated_data.pop("interested_product_items", None)
    fields = [
        "account_name",
        "english_name",
        "short_name",
        "lifecycle_stage",
        "primary_country_code",
        "primary_region",
        "secondary_region",
        "primary_website_url",
        "inquiry_keywords",
        "industry_item",
        "source_system",
        "external_id",
        "notes",
    ]
    before_data = model_snapshot(customer, fields)
    for field_name, value in validated_data.items():
        setattr(customer, field_name, value)
    if validated_data:
        customer.save(update_fields=[*validated_data.keys(), "updated_at"])
    if interested_product_items is not None:
        CustomerInterestedProduct.objects.filter(customer_account=customer).delete()
        CustomerInterestedProduct.objects.bulk_create(
            [
                CustomerInterestedProduct(
                    customer_account=customer,
                    product_item=product_item,
                    assigned_by_employee=actor_employee,
                )
                for product_item in interested_product_items
            ]
        )
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


def require_actor_employee(actor_employee, action_name):
    if actor_employee is None:
        raise ValidationError({"detail": [f"{action_name}需要绑定有效员工档案。"]})


def write_profile_change(*, customer, object_type, instance, action, title, actor_employee, request, data):
    write_audit_log(
        object_type=object_type,
        object_id=instance.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=customer.pk,
        action=action,
        actor_employee=actor_employee,
        after_data=data,
        request=request,
    )
    write_customer_timeline(
        customer=customer,
        event_type=action,
        title=title,
        source_type=object_type,
        source_id=instance.pk,
        actor_employee=actor_employee,
        event_data=data,
    )


@transaction.atomic
def set_grade(*, customer, grade_item, reason, actor_employee, request):
    require_actor_employee(actor_employee, "调整客户等级")
    CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    now = timezone.now()
    CustomerGradeReview.objects.select_for_update().filter(
        customer_account=customer,
        effective_to__isnull=True,
    ).update(effective_to=now, updated_at=now)
    review = CustomerGradeReview.objects.create(
        customer_account=customer,
        grade_item=grade_item,
        reviewed_by_employee=actor_employee,
        reason=reason,
        effective_from=now,
    )
    data = {"grade": grade_item.item_code, "reason": reason, "effective_from": now}
    write_profile_change(
        customer=customer,
        object_type="CUSTOMER_GRADE_REVIEW",
        instance=review,
        action="CUSTOMER_GRADE_CHANGED",
        title="客户等级已调整",
        actor_employee=actor_employee,
        request=request,
        data=data,
    )
    return review


@transaction.atomic
def set_source(*, customer, source_item, notes, actor_employee, request):
    require_actor_employee(actor_employee, "调整客户来源")
    CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    now = timezone.now()
    CustomerSourceAttribution.objects.select_for_update().filter(
        customer_account=customer,
        effective_to__isnull=True,
    ).update(effective_to=now, updated_at=now)
    attribution = CustomerSourceAttribution.objects.create(
        customer_account=customer,
        source_item=source_item,
        recorded_by_employee=actor_employee,
        notes=notes,
        effective_from=now,
    )
    data = {"source": source_item.item_code, "notes": notes, "effective_from": now}
    write_profile_change(
        customer=customer,
        object_type="CUSTOMER_SOURCE_ATTRIBUTION",
        instance=attribution,
        action="CUSTOMER_SOURCE_CHANGED",
        title="客户来源已调整",
        actor_employee=actor_employee,
        request=request,
        data=data,
    )
    return attribution


@transaction.atomic
def set_activity(*, customer, activity_status, reason, actor_employee, request):
    require_actor_employee(actor_employee, "调整客户活跃度")
    CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    now = timezone.now()
    CustomerActivityReview.objects.select_for_update().filter(
        customer_account=customer,
        effective_to__isnull=True,
    ).update(effective_to=now, updated_at=now)
    review = CustomerActivityReview.objects.create(
        customer_account=customer,
        activity_status=activity_status,
        source_type="MANUAL",
        reviewed_by_employee=actor_employee,
        reason=reason,
        effective_from=now,
    )
    data = {"activity_status": activity_status, "reason": reason, "effective_from": now}
    write_profile_change(
        customer=customer,
        object_type="CUSTOMER_ACTIVITY_REVIEW",
        instance=review,
        action="CUSTOMER_ACTIVITY_CHANGED",
        title="客户活跃度已调整",
        actor_employee=actor_employee,
        request=request,
        data=data,
    )
    return review


@transaction.atomic
def set_classification(
    *,
    customer,
    customer_type_items,
    customer_tags,
    reason,
    actor_employee,
    request,
):
    require_actor_employee(actor_employee, "调整客户分类")
    CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    now = timezone.now()

    if customer_type_items is not None:
        type_by_id = {item.pk: item for item in customer_type_items}
        current_types = list(
            CustomerTypeAssignment.objects.select_for_update().filter(
                customer_account=customer,
                effective_to__isnull=True,
            )
        )
        current_type_ids = {assignment.type_item_id for assignment in current_types}
        CustomerTypeAssignment.objects.filter(
            pk__in=[assignment.pk for assignment in current_types if assignment.type_item_id not in type_by_id]
        ).update(effective_to=now, updated_at=now)
        CustomerTypeAssignment.objects.bulk_create(
            [
                CustomerTypeAssignment(
                    customer_account=customer,
                    type_item=type_item,
                    assigned_by_employee=actor_employee,
                    reason=reason,
                    effective_from=now,
                )
                for type_id, type_item in type_by_id.items()
                if type_id not in current_type_ids
            ]
        )

    if customer_tags is not None:
        tag_by_id = {tag.pk: tag for tag in customer_tags}
        current_tags = list(
            CustomerTagAssignment.objects.select_for_update().filter(
                customer_account=customer,
                effective_to__isnull=True,
            )
        )
        current_tag_ids = {assignment.customer_tag_id for assignment in current_tags}
        CustomerTagAssignment.objects.filter(
            pk__in=[assignment.pk for assignment in current_tags if assignment.customer_tag_id not in tag_by_id]
        ).update(effective_to=now, updated_at=now)
        CustomerTagAssignment.objects.bulk_create(
            [
                CustomerTagAssignment(
                    customer_account=customer,
                    customer_tag=customer_tag,
                    assigned_by_employee=actor_employee,
                    reason=reason,
                    effective_from=now,
                )
                for tag_id, customer_tag in tag_by_id.items()
                if tag_id not in current_tag_ids
            ]
        )

    write_audit_log(
        object_type="CUSTOMER_ACCOUNT",
        object_id=customer.pk,
        action="CUSTOMER_CLASSIFICATION_CHANGED",
        actor_employee=actor_employee,
        after_data={
            "customer_type_item_ids": [str(item.pk) for item in customer_type_items]
            if customer_type_items is not None
            else None,
            "customer_tag_ids": [str(tag.pk) for tag in customer_tags] if customer_tags is not None else None,
            "reason": reason,
        },
        request=request,
    )
    write_customer_timeline(
        customer=customer,
        event_type="CUSTOMER_CLASSIFICATION_CHANGED",
        title="客户类型或标签已调整",
        summary=reason,
        source_type="CUSTOMER_ACCOUNT",
        source_id=customer.pk,
        actor_employee=actor_employee,
    )


@transaction.atomic
def set_business_snapshot(*, customer, validated_data, actor_employee, request):
    require_actor_employee(actor_employee, "维护客户业务快照")
    CustomerAccount.objects.select_for_update().get(pk=customer.pk)
    CustomerBusinessSnapshot.objects.select_for_update().filter(
        customer_account=customer,
        is_current=True,
    ).update(is_current=False, updated_at=timezone.now())
    snapshot = CustomerBusinessSnapshot.objects.create(
        customer_account=customer,
        source_type="MANUAL",
        entered_by_employee=actor_employee,
        is_current=True,
        **validated_data,
    )
    data = model_snapshot(
        snapshot,
        [
            "source_type",
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
        ],
    )
    write_profile_change(
        customer=customer,
        object_type="CUSTOMER_BUSINESS_SNAPSHOT",
        instance=snapshot,
        action="CUSTOMER_BUSINESS_SNAPSHOT_UPDATED",
        title="客户业务快照已更新",
        actor_employee=actor_employee,
        request=request,
        data=data,
    )
    return snapshot


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
