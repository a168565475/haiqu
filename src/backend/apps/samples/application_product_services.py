"""维护新版申请的基础信息与产品资料，保留权限、并发和审计约束。"""
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.access_control.module_policy import can_sample
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.customers.services import model_snapshot
from apps.customers.selectors import accessible_customers
from apps.inquiries.models import Inquiry
from apps.quotations.models import QuotationVersion
from apps.products.models import ProductInformation, ProductStatus
from apps.files.uploads import save_scanned_image
from .form_services import application_requirements_pending, _legacy_datetime
from .models import SampleInventoryLine, SampleItem, SampleRequest, SampleRequestStatus, SampleWorkflowStage
from .services import SAMPLE_FIELDS, _record_workflow_stage, _start_sla, _write_sample_records, sample_product_values_from_source


def require_application_product_edit(sample, request):
    actor = getattr(request, 'employee', None)
    if not actor or not can_sample(request, sample, 'samples.complete_sample_requirements'):
        raise PermissionDenied('当前账号没有完善样品需求的权限。')
    if sample.archived_at or sample.customer_account.archived_at:
        raise Conflict('已归档的申请或客户不能编辑。')
    if not sample.application_payload_hash:
        raise Conflict('当前申请不是新版打样需求。')


def application_product_candidates(*, sample, query, request):
    require_application_product_edit(sample, request)
    products = ProductInformation.objects.filter(status=ProductStatus.ACTIVE, archived_at__isnull=True)
    if query:
        products = products.filter(Q(product_name__icontains=query) | Q(specification__icontains=query) | Q(product_number__icontains=query))
    return products.order_by('product_number', 'id').values('id', 'product_name', 'specification', 'category_id')[:50]


def _application_basic_values(*, sample, basic, request):
    values = dict(basic)
    source_type = values.pop('source_type')
    source_id = values.pop('source_id')
    previous_type = 'quotation' if sample.source_quotation_version_id else 'inquiry' if sample.source_inquiry_id else None
    previous_id = sample.source_quotation_version_id if previous_type == 'quotation' else sample.source_inquiry_id
    source_changed = (source_type, source_id) != (previous_type, previous_id)
    if source_changed:
        values.update(source_inquiry=None, source_quotation_version=None, transaction_entity=None)
        if source_type:
            permission = 'inquiries.view_inquiry' if source_type == 'inquiry' else 'quotations.view_quotationversion'
            if not request.user.has_perm(permission):
                raise PermissionDenied('当前账号没有查看来源记录的权限。')
            customers = accessible_customers(request, permission).filter(archived_at__isnull=True)
            if source_type == 'inquiry':
                source = Inquiry.objects.select_for_update().filter(pk=source_id, customer_account__in=customers, archived_at__isnull=True).first()
                if source is None:
                    raise ValidationError({'basic': {'source_id': '来源询盘不存在或当前账号无权访问。'}})
                values.update(source_inquiry=source, transaction_entity=source.transaction_entity)
            else:
                source = QuotationVersion.objects.select_for_update(of=('self',)).select_related('quotation').filter(
                    pk=source_id, quotation__customer_account__in=customers, quotation__archived_at__isnull=True,
                ).first()
                if source is None:
                    raise ValidationError({'basic': {'source_id': '来源报价版本不存在或当前账号无权访问。'}})
                values.update(source_quotation_version=source, source_inquiry=source.quotation.source_inquiry,
                              transaction_entity=source.quotation.transaction_entity)
    elif values['customer_account'].pk != sample.customer_account_id:
        values['transaction_entity'] = None
    inquiry = values.get('source_inquiry', sample.source_inquiry)
    quotation = values.get('source_quotation_version', sample.source_quotation_version)
    if ((inquiry and inquiry.customer_account_id != values['customer_account'].pk)
            or (quotation and quotation.quotation.customer_account_id != values['customer_account'].pk)):
        raise ValidationError({'basic': {'customer_account_id': '客户必须与所选来源记录属于同一客户账户。'}})
    values['requested_due_at'] = _legacy_datetime(values['sample_due_date']) if values['sample_due_date'] else None
    return values, source_changed


def complete_application_products(*, sample_id, data, request, uploaded_file=None):
    saved_images = []
    try:
        return _complete_application_products(sample_id=sample_id, data=data, request=request,
                                              uploaded_file=uploaded_file, saved_images=saved_images)
    except Exception:
        # atomic退出（含提交）失败后，数据库回滚不会清理物理文件；只删本次新图。
        for image in saved_images:
            root = Path(settings.MEDIA_ROOT).resolve()
            path = (root / image.storage_key).resolve()
            if not path.is_relative_to(root):
                raise RuntimeError('新参考图片存储路径超出MEDIA_ROOT。')
            path.unlink(missing_ok=True)
        raise


@transaction.atomic
def _complete_application_products(*, sample_id, data, request, uploaded_file, saved_images):
    sample = SampleRequest.objects.select_for_update().select_related('customer_account').get(pk=sample_id)
    require_matching_etag(request, sample)
    require_application_product_edit(sample, request)
    completing_first_requirements = application_requirements_pending(sample)
    if uploaded_file and (Path(uploaded_file.name).suffix.lower() not in {'.jpg', '.jpeg', '.png'}
                          or uploaded_file.content_type not in {'image/jpeg', 'image/png'}
                          or not 0 < uploaded_file.size <= 5 * 1024 * 1024):
        raise ValidationError({'reference_image': '参考图片仅支持 JPG、PNG，且不超过 5MB。'})
    actor = request.employee
    # 入库也锁定 SampleItem；先取得相同的锁，再读取累计入库量，避免并发降低需求数量。
    products = {product.pk: product for product in sample.products.prefetch_related(
        Prefetch('details', queryset=SampleItem.objects.select_for_update().order_by('id')),
    )}
    received_quantities = dict(SampleInventoryLine.objects.filter(sample_item__sample_request=sample)
                               .values('sample_item_id').annotate(quantity=Sum('received_quantity'))
                               .values_list('sample_item_id', 'quantity'))
    if {product['id'] for product in data['products']} != set(products):
        raise ValidationError({'products': '必须保留当前申请的全部产品，不能新增、删除或引用其他申请的产品。'})
    before = model_snapshot(sample, SAMPLE_FIELDS)
    basic_values, source_changed = _application_basic_values(sample=sample, basic=data['basic'], request=request) if 'basic' in data else ({}, False)
    for field, value in basic_values.items():
        setattr(sample, field, value)
    for values in data['products']:
        product = products[values['id']]
        selected = values.get('product')
        if selected and (values['product_name'] != selected.product_name or values.get('specification', '') != selected.specification):
            # 与现有申请身份解析一致：手改名称/规格后作为自定义产品，不能保留旧档案身份。
            selected = None
        details = {detail.pk: detail for detail in product.details.all()}
        if {detail['id'] for detail in values['details']} != set(details):
            raise ValidationError({'products': '必须保留产品现有颜色明细，不能引用其他产品的明细。'})
        snapshots = sample_product_values_from_source(selected) if selected else {
            'product': None, 'product_number_snapshot': '', 'product_code_snapshot': '',
            'item_number_snapshot': '', 'material_snapshot': '', 'product_image': None,
        }
        for field in ('product', 'product_number_snapshot', 'product_code_snapshot', 'item_number_snapshot', 'material_snapshot', 'product_image'):
            setattr(product, field, snapshots[field])
        for field, value in values.items():
            if field not in {'id', 'details', 'product'}:
                setattr(product, field, value)
        if source_changed:
            product.source_inquiry_item = None
            product.source_quotation_line = None
        product.category_name_snapshot = product.category.category_name
        product.save()
        for detail_values in values['details']:
            detail = details[detail_values['id']]
            if detail_values['sample_quantity'] < max(detail.cutting_reported_quantity, detail.metalwork_reported_quantity):
                raise ValidationError({'products': '打样数量不能小于已有报工数量。'})
            if detail_values['sample_quantity'] < received_quantities.get(detail.pk, 0):
                raise ValidationError({'products': '打样数量不能小于累计已入库数量。'})
            color = detail_values['product_color']
            detail.product_color = color
            detail.color_card_snapshot = color.color_card
            detail.color_name_snapshot = color.color_name
            detail.color_code_snapshot = detail_values.get('color_code') or color.color_code
            detail.sample_quantity = detail_values['sample_quantity']
            detail.requested_quantity = detail.sample_quantity
            detail.tolerance = detail_values['tolerance']
            detail.notes = detail_values.get('notes', '')
            detail.product_description_snapshot = product.product_name
            detail.specification_snapshot = product.specification
            if source_changed:
                detail.source_inquiry_item = None
                detail.source_quotation_line = None
            detail.save()
    if uploaded_file:
        image = save_scanned_image(uploaded_file, actor, storage_folder='samples/application-references', field_label='参考图片')
        saved_images.append(image)
        sample.reference_image = image
    sample.purpose = data['purpose']
    update_fields = ['purpose', 'reference_image', 'updated_at', *basic_values]
    if completing_first_requirements:
        sample.status = SampleRequestStatus.MATERIALS_PENDING
        update_fields.insert(1, 'status')
    sample.save(update_fields=update_fields)
    if completing_first_requirements:
        completed_at = timezone.now()
        _start_sla(sample, completed_at)
        _record_workflow_stage(sample_request=sample, stage=SampleWorkflowStage.REQUIREMENTS_COMPLETED,
                               actor_employee=actor, note='工厂完善并提交样品需求。', operated_at=completed_at)
    _write_sample_records(
        sample_request=sample,
        action='REQUIREMENTS_COMPLETED' if completing_first_requirements else 'PRODUCT_REQUIREMENTS_UPDATED',
        actor_employee=actor,
        request=request,
        before_data=before,
        note='工厂完善并提交样品需求。' if completing_first_requirements else '更新样品基础信息与产品需求。' if basic_values else '更新已提交的产品需求。',
    )
    return sample
