from apps.access_control import sales_policy
import json
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.exceptions import Conflict
from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from apps.workflow.models import BusinessTask, TaskPriority, TaskStatus

from .models import (
    AssignmentRole,
    ContactMethodType,
    ContactEmploymentEventType,
    ContactStatus,
    CustomerAssignment,
    CustomerContact,
    CustomerContactEmploymentEvent,
    CustomerContactMethod,
    CustomerContactRole,
    CustomerContactTaskLink,
    CustomerTaskLink,
)
from .services import model_snapshot, normalize_contact_value, prepare_contact_method, write_customer_timeline


def current_primary_owner(customer, *, for_update=False):
    now = timezone.now()
    queryset = CustomerAssignment.objects.filter(
        customer_account=customer,
        assignment_role=AssignmentRole.PRIMARY_OWNER,
        effective_from__lte=now,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    if for_update:
        queryset = queryset.select_for_update()
    assignment = queryset.select_related("employee").order_by("-effective_from", "-id").first()
    if assignment and assignment.employee.status == "ACTIVE" and assignment.employee.archived_at is None:
        return assignment.employee
    return None


def _active_role_types(contact):
    now = timezone.now()
    return list(
        contact.roles.filter(effective_from__lte=now)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
        .order_by("role_type")
        .values_list("role_type", flat=True)
    )


def _record_employment_event(
    contact,
    *,
    event_type,
    effective_on,
    title,
    actor_employee,
    notes="",
    change_data=None,
):
    return CustomerContactEmploymentEvent.objects.create(
        customer_contact=contact,
        event_type=event_type,
        effective_on=effective_on,
        title=title,
        position_title=contact.position_title,
        department_name=contact.department_name,
        role_types=_active_role_types(contact),
        is_primary_contact=contact.is_primary_contact,
        notes=notes,
        change_data=json.loads(DjangoJSONEncoder().encode(change_data or {})),
        actor_employee=actor_employee,
    )


def _clear_other_primary_contacts(contact, *, actor_employee, effective_on):
    others = list(
        CustomerContact.objects.select_for_update()
        .filter(
            customer_account=contact.customer_account,
            status=ContactStatus.ACTIVE,
            is_primary_contact=True,
            archived_at__isnull=True,
        )
        .exclude(pk=contact.pk)
    )
    for other in others:
        other.is_primary_contact = False
        other.save(update_fields=["is_primary_contact", "updated_at"])
        _record_employment_event(
            other,
            event_type=ContactEmploymentEventType.PRIMARY_CHANGED,
            effective_on=effective_on,
            title="取消主要联系人",
            actor_employee=actor_employee,
            change_data={"is_primary_contact": {"before": True, "after": False}},
        )


def _sync_contact_roles(contact, role_types, request):
    now = timezone.now()
    desired = set(role_types)
    active = list(
        contact.roles.select_for_update()
        .filter(effective_from__lte=now)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    )
    active_types = {role.role_type for role in active}
    if active_types - desired:
        sales_policy.require_customer(request, "customers.change_customercontactrole", contact.customer_account)
    if desired - active_types:
        sales_policy.require_customer(request, "customers.add_customercontactrole", contact.customer_account)
    for role in active:
        if role.role_type not in desired:
            role.effective_to = now
            role.save(update_fields=["effective_to", "updated_at"])
    for role_type in sorted(desired - active_types):
        CustomerContactRole.objects.create(
            customer_contact=contact,
            role_type=role_type,
            effective_from=now,
        )


def _sync_contact_methods(contact, methods, duplicate_acknowledged, request):
    for method_data in methods:
        existing = (
            contact.methods.select_for_update()
            .filter(method_type=method_data["method_type"], archived_at__isnull=True)
            .order_by("-is_primary", "id")
            .first()
        )
        validate_contact_method_duplicate(
            customer=contact.customer_account,
            method_data=method_data,
            duplicate_acknowledged=duplicate_acknowledged,
            exclude_method_id=existing.pk if existing else None,
        )
        prepared = prepare_contact_method(dict(method_data))
        if not existing or any(getattr(existing, key) != value for key, value in prepared.items()):
            code = "change_customercontactmethod" if existing else "add_customercontactmethod"
            sales_policy.require_customer(request, f"customers.{code}", contact.customer_account)
        if existing:
            for field_name, value in prepared.items():
                setattr(existing, field_name, value)
            existing.save()
        else:
            CustomerContactMethod.objects.create(customer_contact=contact, **prepared)


@transaction.atomic
def update_contact_profile(
    *,
    contact,
    validated_data,
    actor_employee,
    request,
    event_title="更新任职资料",
    effective_on=None,
    event_notes="",
):
    locked = CustomerContact.objects.select_for_update().select_related("customer_account").get(pk=contact.pk)
    require_matching_etag(request, locked)
    methods = validated_data.pop("methods", None)
    role_types = validated_data.pop("role_types", None)
    duplicate_acknowledged = validated_data.pop("duplicate_acknowledged", False)
    effective_on = effective_on or timezone.localdate()
    before_data = model_snapshot(
        locked,
        [
            "display_name", "english_name", "position_title", "department_name",
            "preferred_language_code", "timezone_code", "is_key_contact",
            "is_primary_contact", "status", "notes",
        ],
    )

    requested_primary = validated_data.get("is_primary_contact")
    if requested_primary is True:
        _clear_other_primary_contacts(locked, actor_employee=actor_employee, effective_on=effective_on)
    if validated_data.get("status") in {ContactStatus.INACTIVE, ContactStatus.LEFT}:
        validated_data["is_primary_contact"] = False
    for field_name, value in validated_data.items():
        setattr(locked, field_name, value)
    locked.save()

    if role_types is not None:
        _sync_contact_roles(locked, role_types, request)
    if methods is not None:
        _sync_contact_methods(locked, methods, duplicate_acknowledged, request)

    after_data = model_snapshot(
        locked,
        [
            "display_name", "english_name", "position_title", "department_name",
            "preferred_language_code", "timezone_code", "is_key_contact",
            "is_primary_contact", "status", "notes",
        ],
    )
    event_type = (
        ContactEmploymentEventType.PRIMARY_CHANGED
        if before_data.get("is_primary_contact") != after_data.get("is_primary_contact")
        else ContactEmploymentEventType.PROFILE_CHANGED
    )
    _record_employment_event(
        locked,
        event_type=event_type,
        effective_on=effective_on,
        title=event_title,
        actor_employee=actor_employee,
        notes=event_notes,
        change_data={"before": before_data, "after": after_data},
    )
    write_audit_log(
        object_type="CUSTOMER_CONTACT",
        object_id=locked.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=locked.customer_account_id,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=after_data,
        request=request,
    )
    write_customer_timeline(
        customer=locked.customer_account,
        event_type="CUSTOMER_CONTACT_UPDATED",
        title=f"更新联系人：{locked.display_name}",
        summary=event_title,
        source_type="CUSTOMER_CONTACT",
        source_id=locked.pk,
        actor_employee=actor_employee,
    )
    return locked


def duplicate_summary(*, request, customer, method_type, raw_value, exclude_contact_id=None):
    normalized = normalize_contact_value(method_type, raw_value)
    base = CustomerContactMethod.objects.filter(
        method_type=method_type,
        normalized_value=normalized,
        archived_at__isnull=True,
        customer_contact__archived_at__isnull=True,
    )
    if exclude_contact_id:
        base = base.exclude(customer_contact_id=exclude_contact_id)

    same_customer = base.filter(customer_contact__customer_account=customer)
    accessible_customer_ids = set(
        request._contact_accessible_customer_ids
        if hasattr(request, "_contact_accessible_customer_ids")
        else []
    )
    cross_customer = base.exclude(customer_contact__customer_account=customer)
    visible_cross = cross_customer.filter(customer_contact__customer_account_id__in=accessible_customer_ids)
    hidden_cross_count = 0 if sales_policy.enabled() else cross_customer.exclude(
        customer_contact__customer_account_id__in=accessible_customer_ids
    ).values("customer_contact__customer_account_id").distinct().count()

    domain_count = 0
    if method_type == ContactMethodType.EMAIL and "@" in normalized:
        domain = normalized.rsplit("@", 1)[1]
        domain_methods = CustomerContactMethod.objects.all()
        if sales_policy.enabled():
            domain_methods = domain_methods.filter(customer_contact__customer_account_id__in=accessible_customer_ids)
        domain_count = domain_methods.filter(
            method_type=ContactMethodType.EMAIL,
            normalized_value__iendswith=f"@{domain}",
            archived_at__isnull=True,
            customer_contact__archived_at__isnull=True,
        ).exclude(customer_contact__customer_account=customer).values(
            "customer_contact__customer_account_id"
        ).distinct().count()

    return {
        "normalized_value": normalized,
        "requires_acknowledgement": method_type in {ContactMethodType.EMAIL, ContactMethodType.MOBILE}
        and same_customer.exists(),
        "same_customer_matches": [
            {"contact_id": str(item.customer_contact_id), "display_name": item.customer_contact.display_name}
            for item in same_customer.select_related("customer_contact").order_by("customer_contact__display_name", "id")[:10]
        ],
        "cross_customer_matches": [
            {
                "contact_id": str(item.customer_contact_id),
                "display_name": item.customer_contact.display_name,
                "customer_id": str(item.customer_contact.customer_account_id),
                "customer_name": item.customer_contact.customer_account.account_name,
            }
            for item in visible_cross.select_related("customer_contact__customer_account").order_by(
                "customer_contact__customer_account__account_name", "id"
            )[:10]
        ],
        "hidden_cross_customer_count": hidden_cross_count,
        "cross_customer_domain_count": domain_count,
    }


def _validate_duplicate_methods(customer, methods, duplicate_acknowledged):
    for method in methods:
        if method["method_type"] not in {ContactMethodType.EMAIL, ContactMethodType.MOBILE}:
            continue
        normalized = normalize_contact_value(method["method_type"], method["raw_value"])
        duplicate_exists = CustomerContactMethod.objects.select_for_update().filter(
            customer_contact__customer_account=customer,
            customer_contact__archived_at__isnull=True,
            method_type=method["method_type"],
            normalized_value=normalized,
            archived_at__isnull=True,
        ).exists()
        if duplicate_exists and not duplicate_acknowledged:
            raise Conflict("同一客户下已存在相同邮箱或手机，请确认重复风险后重试。")


def validate_contact_method_duplicate(*, customer, method_data, duplicate_acknowledged, exclude_method_id=None):
    if method_data["method_type"] not in {ContactMethodType.EMAIL, ContactMethodType.MOBILE}:
        return
    normalized = normalize_contact_value(method_data["method_type"], method_data["raw_value"])
    queryset = CustomerContactMethod.objects.filter(
        customer_contact__customer_account=customer,
        customer_contact__archived_at__isnull=True,
        method_type=method_data["method_type"],
        normalized_value=normalized,
        archived_at__isnull=True,
    )
    if exclude_method_id:
        queryset = queryset.exclude(pk=exclude_method_id)
    if queryset.exists() and not duplicate_acknowledged:
        raise Conflict("同一客户下已存在相同邮箱或手机，请确认重复风险后重试。")


@transaction.atomic
def create_contact(*, customer, validated_data, actor_employee, request):
    methods = validated_data.pop("methods")
    role_types = validated_data.pop("role_types", [])
    duplicate_acknowledged = validated_data.pop("duplicate_acknowledged", False)
    _validate_duplicate_methods(customer, methods, duplicate_acknowledged)
    now = timezone.now()
    if validated_data.get("is_primary_contact"):
        old_primary_contacts = list(CustomerContact.objects.select_for_update().filter(
            customer_account=customer,
            status=ContactStatus.ACTIVE,
            is_primary_contact=True,
            archived_at__isnull=True,
        ))
        for old_primary in old_primary_contacts:
            old_primary.is_primary_contact = False
            old_primary.save(update_fields=["is_primary_contact", "updated_at"])
            _record_employment_event(
                old_primary,
                event_type=ContactEmploymentEventType.PRIMARY_CHANGED,
                effective_on=timezone.localdate(),
                title="取消主要联系人",
                actor_employee=actor_employee,
                change_data={"is_primary_contact": {"before": True, "after": False}},
            )
    contact = CustomerContact.objects.create(customer_account=customer, **validated_data)
    for method_data in methods:
        prepared = prepare_contact_method(dict(method_data))
        CustomerContactMethod.objects.create(customer_contact=contact, **prepared)
    for role_type in role_types:
        CustomerContactRole.objects.create(
            customer_contact=contact,
            role_type=role_type,
            effective_from=now,
        )
    _record_employment_event(
        contact,
        event_type=ContactEmploymentEventType.JOINED,
        effective_on=timezone.localdate(),
        title="加入当前客户公司",
        actor_employee=actor_employee,
        notes="创建联系人档案",
    )
    write_audit_log(
        object_type="CUSTOMER_CONTACT",
        object_id=contact.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=customer.pk,
        action="CREATED",
        actor_employee=actor_employee,
        after_data=model_snapshot(
            contact,
            [
                "display_name", "english_name", "position_title", "department_name",
                "preferred_language_code", "timezone_code", "is_key_contact",
                "is_primary_contact", "status", "notes", "legacy_source_data",
            ],
        ),
        request=request,
    )
    write_customer_timeline(
        customer=customer,
        event_type="CUSTOMER_CONTACT_CREATED",
        title=f"新增联系人：{contact.display_name}",
        source_type="CUSTOMER_CONTACT",
        source_id=contact.pk,
        actor_employee=actor_employee,
    )
    return contact


def _create_replacement_task(contact, actor_employee):
    owner = current_primary_owner(contact.customer_account, for_update=True)
    if owner is None:
        raise Conflict("客户缺少当前主要负责人，请先补充负责人后再标记关键联系人离职。")
    task, created = BusinessTask.objects.get_or_create(
        automation_key=f"CONTACT_REPLACEMENT:{contact.pk}",
        defaults={
            "assignee_employee": owner,
            "created_by_employee": actor_employee,
            "title": f"补充关键联系人：{contact.customer_account.account_name}",
            "description": f"关键联系人 {contact.display_name} 已离职，请及时补充新的关键联系人。",
            "priority": TaskPriority.HIGH,
            "due_at": timezone.now() + timedelta(days=3),
        },
    )
    if created:
        CustomerTaskLink.objects.create(
            customer_account=contact.customer_account,
            business_task=task,
            is_primary_source=True,
        )
        CustomerContactTaskLink.objects.create(customer_contact=contact, business_task=task)
    return task


def _mark_contact_left_locked(
    contact,
    *,
    reason,
    actor_employee,
    request,
    effective_date=None,
    replacement_contact_id=None,
    unfinished_task_policy="TRANSFER_TO_OWNER",
    remove_from_marketing=True,
    notify_stakeholders=False,
):
    if contact.status == ContactStatus.LEFT:
        raise Conflict(f"联系人 {contact.display_name} 已经是离职状态。")
    effective_date = effective_date or timezone.localdate()
    was_primary = contact.is_primary_contact
    replacement = None
    eligible_replacements = CustomerContact.objects.select_for_update().filter(
        customer_account=contact.customer_account,
        status=ContactStatus.ACTIVE,
        archived_at__isnull=True,
    ).exclude(pk=contact.pk)
    if replacement_contact_id:
        replacement = eligible_replacements.filter(pk=replacement_contact_id).first()
        if replacement is None:
            raise ValidationError({"replacement_contact_id": "新的主要联系人必须是同一客户的在职联系人。"})
    if was_primary and eligible_replacements.exists() and replacement is None:
        raise Conflict("该联系人是主要联系人，请先选择新的主要联系人。")

    open_task_ids = CustomerContactTaskLink.objects.filter(
        customer_contact=contact,
        business_task__status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
        business_task__archived_at__isnull=True,
    ).values_list("business_task_id", flat=True)
    open_tasks = list(
        BusinessTask.objects.select_for_update().filter(
            pk__in=open_task_ids,
            status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
            archived_at__isnull=True,
        )
    )
    if unfinished_task_policy == "TRANSFER_TO_OWNER" and open_tasks:
        owner = current_primary_owner(contact.customer_account, for_update=True)
        if owner is None:
            raise Conflict("客户缺少当前主要负责人，无法转移未完成任务。")
        for open_task in open_tasks:
            open_task.assignee_employee = owner
            open_task.save(update_fields=["assignee_employee", "updated_at"])
    elif unfinished_task_policy == "CANCEL_OPEN":
        for open_task in open_tasks:
            open_task.status = TaskStatus.CANCELLED
            open_task.save(update_fields=["status", "updated_at"])

    task = _create_replacement_task(contact, actor_employee) if contact.is_key_contact else None
    before_data = model_snapshot(
        contact,
        ["status", "is_primary_contact", "left_effective_date", "marketing_opt_out", "notes"],
    )
    contact.status = ContactStatus.LEFT
    contact.is_primary_contact = False
    contact.left_effective_date = effective_date
    if remove_from_marketing:
        contact.marketing_opt_out = True
        contact.marketing_opt_out_at = timezone.now()
        contact.marketing_opt_out_by_employee = actor_employee
    contact.notes = f"{contact.notes}\n离职原因：{reason}".strip()
    contact.save(update_fields=[
        "status", "is_primary_contact", "left_effective_date", "marketing_opt_out",
        "marketing_opt_out_at", "marketing_opt_out_by_employee", "notes", "updated_at",
    ])
    if replacement is not None:
        _clear_other_primary_contacts(replacement, actor_employee=actor_employee, effective_on=effective_date)
        replacement.is_primary_contact = True
        replacement.save(update_fields=["is_primary_contact", "updated_at"])
        _record_employment_event(
            replacement,
            event_type=ContactEmploymentEventType.PRIMARY_CHANGED,
            effective_on=effective_date,
            title="设为主要联系人",
            actor_employee=actor_employee,
            notes=f"接替已离职联系人 {contact.display_name}",
            change_data={"replaced_contact_id": str(contact.pk)},
        )

    if notify_stakeholders:
        owner = current_primary_owner(contact.customer_account, for_update=True)
        if owner is not None:
            notification_task, created = BusinessTask.objects.get_or_create(
                automation_key=f"CONTACT_LEFT_NOTICE:{contact.pk}:{effective_date.isoformat()}",
                defaults={
                    "assignee_employee": owner,
                    "created_by_employee": actor_employee,
                    "title": f"联系人离职交接：{contact.display_name}",
                    "description": "请核对客户主要联系人、未完成任务和后续沟通安排。",
                    "priority": TaskPriority.HIGH,
                    "due_at": timezone.now() + timedelta(days=1),
                },
            )
            if created:
                CustomerTaskLink.objects.create(
                    customer_account=contact.customer_account,
                    business_task=notification_task,
                    is_primary_source=True,
                )
                CustomerContactTaskLink.objects.create(
                    customer_contact=contact,
                    business_task=notification_task,
                )

    _record_employment_event(
        contact,
        event_type=ContactEmploymentEventType.LEFT,
        effective_on=effective_date,
        title="标记联系人离职",
        actor_employee=actor_employee,
        notes=reason,
        change_data={
            "replacement_contact_id": str(replacement.pk) if replacement else None,
            "unfinished_task_policy": unfinished_task_policy,
            "open_task_count": len(open_tasks),
            "remove_from_marketing": remove_from_marketing,
            "notify_stakeholders": notify_stakeholders,
        },
    )
    write_audit_log(
        object_type="CUSTOMER_CONTACT",
        object_id=contact.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=contact.customer_account_id,
        action="MARKED_LEFT",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=model_snapshot(
            contact,
            ["status", "is_primary_contact", "left_effective_date", "marketing_opt_out", "notes"],
        ),
        request=request,
    )
    write_customer_timeline(
        customer=contact.customer_account,
        event_type="CUSTOMER_CONTACT_LEFT",
        title=f"联系人离职：{contact.display_name}",
        summary=reason,
        source_type="CUSTOMER_CONTACT",
        source_id=contact.pk,
        actor_employee=actor_employee,
        event_data={
            "replacement_task_id": str(task.pk) if task else None,
            "replacement_contact_id": str(replacement.pk) if replacement else None,
            "unfinished_task_policy": unfinished_task_policy,
            "open_task_count": len(open_tasks),
            "marketing_opt_out": contact.marketing_opt_out,
            "notification_recorded": notify_stakeholders,
        },
    )
    return contact, task


@transaction.atomic
def mark_contact_left(*, contact, reason, actor_employee, request, **options):
    locked = CustomerContact.objects.select_for_update().select_related("customer_account").get(pk=contact.pk)
    return _mark_contact_left_locked(
        locked,
        reason=reason,
        actor_employee=actor_employee,
        request=request,
        **options,
    )


@transaction.atomic
def bulk_mark_contacts_left(*, contacts, reason, actor_employee, request):
    contact_ids = [contact.pk for contact in contacts]
    locked_contacts = list(
        CustomerContact.objects.select_for_update().select_related("customer_account").filter(
            pk__in=contact_ids
        ).order_by("id")
    )
    if len(locked_contacts) != len(contact_ids):
        raise ValidationError({"contact_ids": "部分联系人不存在或无权访问。"})
    for contact in locked_contacts:
        if contact.status == ContactStatus.LEFT:
            raise Conflict(f"联系人 {contact.display_name} 已经是离职状态。")
        if contact.is_key_contact and current_primary_owner(contact.customer_account, for_update=True) is None:
            raise Conflict(f"客户 {contact.customer_account.account_name} 缺少当前主要负责人。")
    results = []
    for contact in locked_contacts:
        results.append(
            _mark_contact_left_locked(
                contact,
                reason=reason,
                actor_employee=actor_employee,
                request=request,
            )
        )
    return results


@transaction.atomic
def bulk_create_contact_tasks(*, contacts, validated_data, actor_employee):
    mode = validated_data["assignee_mode"]
    specific_assignee = validated_data.get("assignee_employee")
    results = []
    for contact in contacts:
        assignee = specific_assignee if mode == "SPECIFIC" else current_primary_owner(contact.customer_account)
        if assignee is None:
            raise Conflict(f"客户 {contact.customer_account.account_name} 缺少当前主要负责人。")
        task = BusinessTask.objects.create(
            assignee_employee=assignee,
            created_by_employee=actor_employee,
            title=validated_data["title"],
            description=(
                f"联系人：{contact.display_name}\n{validated_data.get('description', '')}"
            ).strip(),
            priority=validated_data["priority"],
            due_at=validated_data["due_at"],
        )
        CustomerTaskLink.objects.create(
            customer_account=contact.customer_account,
            business_task=task,
            is_primary_source=True,
        )
        CustomerContactTaskLink.objects.create(customer_contact=contact, business_task=task)
        results.append(task)
    return results
