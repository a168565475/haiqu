"""新版申请的提交、退回重提与厂长审核；不改写历史单据状态。"""
from apps.access_control.module_policy import can_sample
import hashlib
import json
from pathlib import Path

from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.numbering import next_business_number
from apps.customers.services import model_snapshot
from apps.customers.selectors import accessible_customers
from apps.files.uploads import save_scanned_image
from apps.quotations.models import QuotationLine
from .form_selectors import resolve_form_source, inquiry_reference_images
from .form_services import _source_relations, _validate_source_tampering, _legacy_datetime
from .models import SampleItem, SampleProduct, SampleRequest, SampleRequestStatus
from .services import SAMPLE_FIELDS, _write_sample_records


def application_actions(sample, request):
    from .material_services import material_actions
    actor = getattr(request, 'employee', None) if request else None
    active = bool(actor and sample.archived_at is None and sample.customer_account.archived_at is None)
    can_resubmit = bool(active and sample.status == SampleRequestStatus.APPLICATION_RETURNED and request.user.has_perm('samples.add_samplerequest') and (request.user.is_superuser or actor.pk in [sample.requested_by_employee_id, sample.owner_employee_id]))
    if can_resubmit:
        source_permission = 'quotations.view_quotationversion' if sample.source_quotation_version_id else 'inquiries.view_inquiry' if sample.source_inquiry_id else None
        can_resubmit = (not source_permission or request.user.has_perm(source_permission)) and accessible_customers(request, 'add_samplerequest').filter(pk=sample.customer_account_id, archived_at__isnull=True).exists()
    return {
        **material_actions(sample, request),
        'is_application': bool(sample.application_payload_hash),
        'can_director_review': bool(active and sample.status == SampleRequestStatus.DIRECTOR_REVIEW and can_sample(request, sample, 'samples.review_sample_application')),
        'can_resubmit': bool(can_resubmit),
    }


def _fingerprint(data, uploaded_file):
    normalized = {key: str(value.pk) if hasattr(value, 'pk') else value for key, value in data.items() if key != 'idempotency_key'}
    if uploaded_file:
        digest = hashlib.sha256()
        for chunk in uploaded_file.chunks():
            digest.update(chunk)
        uploaded_file.seek(0)
        normalized['image_hash'] = digest.hexdigest()
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, default=str).encode()).hexdigest()


@transaction.atomic
def submit_application(*, data, uploaded_file, request, sample_id=None):
    actor = getattr(request, 'employee', None)
    if actor is None or not request.user.has_perm('samples.add_samplerequest'):
        raise PermissionDenied('提交申请需要创建权限和有效员工档案。')
    data = dict(data)
    key = str(data.pop('idempotency_key'))
    fingerprint = _fingerprint(data, uploaded_file)
    sample = None
    before = None
    if sample_id:
        sample = SampleRequest.objects.select_for_update().get(pk=sample_id)
        if not application_actions(sample, request)['can_resubmit']:
            raise PermissionDenied('只有被退回申请的业务员或申请人可以修改重提。')
        require_matching_etag(request, sample)
        before = model_snapshot(sample, SAMPLE_FIELDS)
    else:
        # 同一创建键串行化，网络重试和并发双击只生成一份申请。
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ['sample-application:' + key])
        existing = SampleRequest.objects.filter(creation_idempotency_key=key).first()
        if existing:
            if existing.created_by_employee_id != actor.pk or existing.application_payload_hash != fingerprint or existing.archived_at is not None:
                raise Conflict('该提交标识已经使用且内容不同，请刷新列表核对申请。')
            return existing, True

    source_type, source_id = data.pop('source_type'), data.pop('source_id')
    source_product_id = data.pop('source_product_id')
    if sample:
        original_type = 'quotation' if sample.source_quotation_version_id else 'inquiry' if sample.source_inquiry_id else None
        if source_type != original_type:
            raise ValidationError({'source_type': '退回补充不能更换申请来源类型。'})
    relations = {}
    product_source = {}
    if source_type:
        permission = 'inquiries.view_inquiry' if source_type == 'inquiry' else 'quotations.view_quotationversion'
        if not request.user.has_perm(permission):
            raise PermissionDenied('当前账号没有查看来源记录的权限。')
        if sample:
            # 重提延续提交时的来源快照，不因报价升级或询盘关闭而更换版本。
            original = sample.products.get(line_number=1)
            expected_id = sample.source_quotation_version_id if source_type == 'quotation' else sample.source_inquiry_id
            expected_product_id = original.source_quotation_line_id if source_type == 'quotation' else original.source_inquiry_item_id
            if source_id != expected_id or source_product_id != expected_product_id:
                raise ValidationError({'source_id': '退回补充不能更换申请来源或来源产品。'})
            relations = {field: getattr(sample, field) for field in ['customer_account', 'customer_contact', 'owner_employee', 'transaction_entity', 'source_inquiry', 'source_quotation_version']}
            source_product = {'product_name': original.product_name, 'specification': original.specification, 'source_inquiry_item_id': original.source_inquiry_item_id, 'source_quotation_line_id': original.source_quotation_line_id}
        else:
            context = resolve_form_source(request=request, source_type=source_type, source_id=source_id)
            relations = _source_relations(source_type, source_id)
            source_product = next((p for p in context['products'] if p['id'] == str(source_product_id)), None)
        _validate_source_tampering(data, relations)
        if source_product is None or data['product_name'] != source_product['product_name'] or data['specification'] != source_product['specification']:
            raise ValidationError({'source_product_id': '产品必须与当前来源中的产品一致。'})
        product_source = {'source_inquiry_item_id': source_product['source_inquiry_item_id'], 'source_quotation_line_id': source_product['source_quotation_line_id']}
    if sample and (sample.source_inquiry_id != (relations.get('source_inquiry').pk if relations.get('source_inquiry') else None) or sample.source_quotation_version_id != (relations.get('source_quotation_version').pk if relations.get('source_quotation_version') else None)):
        raise ValidationError({'source_id': '退回补充不能更换申请来源。'})

    if uploaded_file and (Path(uploaded_file.name).suffix.lower() not in {'.jpg', '.jpeg', '.png'} or not 0 < uploaded_file.size <= 5 * 1024 * 1024):
        raise ValidationError({'reference_image': '参考图片仅支持 JPG、PNG，且不超过 5MB。'})
    remove_image = data.pop('remove_reference_image')
    source_image_id = data.pop('source_reference_image_id', None)
    inherited_image = None
    if source_image_id:
        if uploaded_file or remove_image:
            raise ValidationError({'source_reference_image_id': '来源图片不能同时上传或移除。'})
        if source_type == 'inquiry':
            inherited_image = inquiry_reference_images(source_id, request).filter(pk=source_image_id).first()
        elif source_type == 'quotation':
            source_line = (
                QuotationLine.objects.filter(
                    pk=source_product_id,
                    quotation_version_id=source_id,
                    product_image_id=source_image_id,
                    product_image__scan_status='CLEAN',
                    product_image__archived_at__isnull=True,
                )
                .select_related('product_image')
                .first()
            )
            inherited_image = source_line.product_image if source_line else None
        if inherited_image is None:
            raise ValidationError({'source_reference_image_id': '来源图片不属于当前所选产品、已失效或没有查看权限，请重新选择。'})
    quantity = data.pop('quantity')
    product_fields = {field: data.pop(field) for field in ['product_name', 'specification', 'length_cm', 'armrest_width_cm', 'seat_width_cm', 'back_height_cm', 'seat_height_cm']}
    data.update({field: relations.get(field) for field in ['transaction_entity', 'source_inquiry', 'source_quotation_version']})
    data.update(status=SampleRequestStatus.DIRECTOR_REVIEW, submitted_on=timezone.localdate(), requested_due_at=_legacy_datetime(data['sample_due_date']) if data['sample_due_date'] else None)
    saved_image = None
    try:
        if uploaded_file:
            saved_image = save_scanned_image(uploaded_file, actor, storage_folder='samples/application-references', field_label='参考图片')
        if sample is None:
            number = next_business_number('SAMPLE_INTAKE')
            sample = SampleRequest.objects.create(**data, request_number=number, intake_number=number, requested_at=timezone.now(), requested_by_employee=actor, created_by_employee=actor, creation_idempotency_key=key, application_payload_hash=fingerprint, reference_image=saved_image or inherited_image)
            product = SampleProduct.objects.create(sample_request=sample, line_number=1, **product_fields, **product_source)
            SampleItem.objects.create(sample_request=sample, sample_product=product, line_number=1, product_description_snapshot=product.product_name, specification_snapshot=product.specification, requested_quantity=quantity, sample_quantity=quantity, unit_code='PCS', **product_source)
        else:
            for field, value in data.items():
                setattr(sample, field, value)
            if saved_image or inherited_image or remove_image:
                sample.reference_image = saved_image or inherited_image
            sample.save()
            product = sample.products.get(line_number=1)
            for field, value in {**product_fields, **product_source}.items():
                setattr(product, field, value)
            product.save()
            item = sample.items.get(line_number=1)
            for field, value in {**product_source, 'product_description_snapshot': product.product_name, 'specification_snapshot': product.specification, 'requested_quantity': quantity, 'sample_quantity': quantity}.items():
                setattr(item, field, value)
            item.save()
        _write_sample_records(sample_request=sample, action='APPLICATION_RESUBMITTED' if sample_id else 'APPLICATION_SUBMITTED', actor_employee=actor, request=request, before_data=before, note='提交厂长确认。')
        from apps.inquiries.handling_time import sample_submitted
        sample_submitted(sample)
        return sample, False
    except Exception:
        if saved_image:
            # 数据事务在外层回滚；先移除未提交的物理文件，避免孤儿上传。
            from django.conf import settings
            path = (Path(settings.MEDIA_ROOT) / saved_image.storage_key).resolve()
            if path.is_relative_to(Path(settings.MEDIA_ROOT).resolve()):
                path.unlink(missing_ok=True)
        raise


@transaction.atomic
def review_application(*, sample_id, data, request):
    sample = SampleRequest.objects.select_for_update().get(pk=sample_id)
    from apps.access_control.module_policy import prohibit_audit_self_approval
    prohibit_audit_self_approval(getattr(request, 'employee', None), 'SAMPLE_REQUEST', sample.pk, ['APPLICATION_SUBMITTED', 'APPLICATION_RESUBMITTED'])
    actor = getattr(request, 'employee', None)
    if not actor or not request.user.has_perm('samples.review_sample_application'):
        raise PermissionDenied('当前账号没有厂长审核权限。')
    require_matching_etag(request, sample)
    if not application_actions(sample, request)['can_director_review']:
        raise Conflict('该申请当前不在待厂长确认阶段，请刷新查看。')
    before = model_snapshot(sample, SAMPLE_FIELDS)
    sample.status = SampleRequestStatus.MATERIALS_PENDING if data['decision'] == 'approve' else SampleRequestStatus.APPLICATION_RETURNED
    sample.director_note = data['note'].strip()
    sample.save(update_fields=['status', 'director_note', 'updated_at'])
    _write_sample_records(sample_request=sample, action='DIRECTOR_APPROVED' if data['decision'] == 'approve' else 'DIRECTOR_RETURNED', actor_employee=actor, request=request, before_data=before, note=sample.director_note)
    return sample
