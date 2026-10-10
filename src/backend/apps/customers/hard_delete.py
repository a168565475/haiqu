from collections import Counter
from dataclasses import dataclass, field

from django.db import connection, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from rest_framework.exceptions import ValidationError

from apps.crm.models import (
    CommunicationContactParticipant,
    CommunicationInquiryLink,
    CommunicationQuotationVersionLink,
    CommunicationSampleRequestLink,
    CommunicationTaskLink,
    CustomerCommunication,
)
from apps.inquiries.models import Inquiry, InquiryTaskLink
from apps.quotations.models import Quotation, QuotationVersion, QuotationVersionTaskLink
from apps.samples.models import SampleRequest, SampleTaskLink
from apps.workflow.models import BusinessTask

from .models import (
    CustomerAccount,
    CustomerContact,
    CustomerContactTaskLink,
    CustomerTaskLink,
)


@dataclass
class DeletionScope:
    customer_ids: set = field(default_factory=set)
    contact_ids: set = field(default_factory=set)
    inquiry_ids: set = field(default_factory=set)
    quotation_ids: set = field(default_factory=set)
    quotation_version_ids: set = field(default_factory=set)
    sample_ids: set = field(default_factory=set)
    communication_ids: set = field(default_factory=set)
    task_ids: set = field(default_factory=set)


def _ids(queryset):
    return set(queryset.values_list("id", flat=True))


def _add_related_tasks(scope):
    task_ids = set(scope.task_ids)
    if scope.customer_ids:
        task_ids.update(
            CustomerTaskLink.objects.filter(customer_account_id__in=scope.customer_ids).values_list(
                "business_task_id", flat=True
            )
        )
    if scope.contact_ids:
        task_ids.update(
            CustomerContactTaskLink.objects.filter(customer_contact_id__in=scope.contact_ids).values_list(
                "business_task_id", flat=True
            )
        )
        task_ids.update(BusinessTask.objects.filter(contact_id__in=scope.contact_ids).values_list("id", flat=True))
    if scope.inquiry_ids:
        task_ids.update(
            InquiryTaskLink.objects.filter(inquiry_id__in=scope.inquiry_ids).values_list("business_task_id", flat=True)
        )
    if scope.quotation_version_ids:
        task_ids.update(
            QuotationVersionTaskLink.objects.filter(
                quotation_version_id__in=scope.quotation_version_ids
            ).values_list("business_task_id", flat=True)
        )
    if scope.sample_ids:
        task_ids.update(
            SampleTaskLink.objects.filter(sample_request_id__in=scope.sample_ids).values_list("business_task_id", flat=True)
        )
    if scope.communication_ids:
        task_ids.update(
            CommunicationTaskLink.objects.filter(communication_id__in=scope.communication_ids).values_list(
                "business_task_id", flat=True
            )
        )
    scope.task_ids = task_ids


def _add_quotation_descendants(scope):
    if not scope.quotation_ids:
        return
    scope.quotation_version_ids.update(
        _ids(QuotationVersion.objects.filter(quotation_id__in=scope.quotation_ids))
    )
    scope.sample_ids.update(
        _ids(SampleRequest.objects.filter(source_quotation_version_id__in=scope.quotation_version_ids))
    )
    scope.communication_ids.update(
        CommunicationQuotationVersionLink.objects.filter(
            quotation_version_id__in=scope.quotation_version_ids
        ).values_list("communication_id", flat=True)
    )


def _scope_for_customer(customer):
    scope = DeletionScope(customer_ids={customer.pk})
    scope.contact_ids = _ids(CustomerContact.objects.filter(customer_account=customer))
    scope.inquiry_ids = _ids(Inquiry.objects.filter(customer_account=customer))
    scope.quotation_ids = _ids(Quotation.objects.filter(customer_account=customer))
    scope.sample_ids = _ids(SampleRequest.objects.filter(customer_account=customer))
    scope.communication_ids = _ids(CustomerCommunication.objects.filter(customer_account=customer))
    _add_quotation_descendants(scope)
    _add_related_tasks(scope)
    return scope


def _scope_for_contact(contact):
    scope = DeletionScope(contact_ids={contact.pk})
    scope.inquiry_ids = _ids(Inquiry.objects.filter(customer_contact=contact))
    scope.sample_ids = _ids(SampleRequest.objects.filter(customer_contact=contact))
    scope.quotation_ids = _ids(Quotation.objects.filter(source_inquiry_id__in=scope.inquiry_ids))
    scope.communication_ids = set(
        CommunicationContactParticipant.objects.filter(customer_contact=contact).values_list(
            "communication_id", flat=True
        )
    )
    _add_quotation_descendants(scope)
    _add_related_tasks(scope)
    return scope


def _scope_for_inquiry(inquiry):
    scope = DeletionScope(inquiry_ids={inquiry.pk})
    scope.quotation_ids = _ids(Quotation.objects.filter(source_inquiry=inquiry))
    scope.sample_ids = _ids(SampleRequest.objects.filter(source_inquiry=inquiry))
    scope.communication_ids = set(
        CommunicationInquiryLink.objects.filter(inquiry=inquiry).values_list("communication_id", flat=True)
    )
    _add_quotation_descendants(scope)
    _add_related_tasks(scope)
    return scope


def _scope_for_quotation(quotation):
    scope = DeletionScope(quotation_ids={quotation.pk})
    _add_quotation_descendants(scope)
    _add_related_tasks(scope)
    return scope


def _scope_for_sample(sample_request):
    scope = DeletionScope(sample_ids={sample_request.pk})
    scope.communication_ids = set(
        CommunicationSampleRequestLink.objects.filter(sample_request=sample_request).values_list(
            "communication_id", flat=True
        )
    )
    _add_related_tasks(scope)
    return scope


def _delete_with_dependents(queryset, deleted, active_paths):
    ids = tuple(queryset.values_list("id", flat=True))
    if not ids:
        return

    model = queryset.model
    path_key = (model._meta.label, ids)
    if path_key in active_paths:
        raise ValidationError(f"发现无法解除的关联循环：{model._meta.verbose_name}，未执行删除。")

    try:
        _, detail = model.objects.filter(id__in=ids).delete()
        deleted.update(detail)
        return
    except (ProtectedError, RestrictedError) as error:
        blocked_objects = getattr(error, "protected_objects", None) or getattr(error, "restricted_objects", None)
        grouped_ids = {}
        model_by_label = {}
        for blocked in blocked_objects:
            model_by_label[blocked._meta.label] = blocked.__class__
            grouped_ids.setdefault(blocked._meta.label, set()).add(blocked.pk)
        if not grouped_ids:
            raise ValidationError(f"无法识别 {model._meta.verbose_name} 的关联数据，未执行删除。") from error

        next_paths = active_paths | {path_key}
        for model_label in sorted(grouped_ids):
            _delete_with_dependents(
                model_by_label[model_label].objects.filter(id__in=grouped_ids[model_label]),
                deleted,
                next_paths,
            )
        _delete_with_dependents(model.objects.filter(id__in=ids), deleted, active_paths)


def _break_quotation_cycles(scope):
    if not scope.quotation_ids:
        return
    Quotation.objects.filter(id__in=scope.quotation_ids).update(accepted_version=None)
    QuotationVersion.objects.filter(quotation_id__in=scope.quotation_ids).update(parent_version=None)


def _result(deleted):
    return {
        "deleted_count": sum(deleted.values()),
        "deleted": dict(sorted(deleted.items())),
    }


@transaction.atomic
def _delete_root(*, instance, scope, root_queryset):
    root_queryset.model.objects.select_for_update().get(pk=instance.pk)
    with connection.cursor() as cursor:
        # 已确认的物理删除仅在当前事务跳过业务锁定触发器；Django 仍会
        # 按外键递归清理全部关联记录，事务结束后设置自动恢复。
        cursor.execute("SET LOCAL session_replication_role = 'replica'")

    deleted = Counter()
    _break_quotation_cycles(scope)
    if scope.task_ids:
        _delete_with_dependents(BusinessTask.objects.filter(id__in=scope.task_ids), deleted, set())
    _delete_with_dependents(root_queryset, deleted, set())
    return _result(deleted)


def permanently_delete_customer(customer):
    return _delete_root(
        instance=customer,
        scope=_scope_for_customer(customer),
        root_queryset=CustomerAccount.objects.filter(pk=customer.pk),
    )


def permanently_delete_contact(contact):
    return _delete_root(
        instance=contact,
        scope=_scope_for_contact(contact),
        root_queryset=CustomerContact.objects.filter(pk=contact.pk),
    )


def permanently_delete_inquiry(inquiry):
    return _delete_root(
        instance=inquiry,
        scope=_scope_for_inquiry(inquiry),
        root_queryset=Inquiry.objects.filter(pk=inquiry.pk),
    )


def permanently_delete_quotation(quotation):
    return _delete_root(
        instance=quotation,
        scope=_scope_for_quotation(quotation),
        root_queryset=Quotation.objects.filter(pk=quotation.pk),
    )


def permanently_delete_sample(sample_request):
    return _delete_root(
        instance=sample_request,
        scope=_scope_for_sample(sample_request),
        root_queryset=SampleRequest.objects.filter(pk=sample_request.pk),
    )


def permanently_delete_task(task):
    return _delete_root(
        instance=task,
        scope=DeletionScope(task_ids={task.pk}),
        root_queryset=BusinessTask.objects.filter(pk=task.pk),
    )
