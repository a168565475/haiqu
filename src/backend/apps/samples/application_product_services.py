"""只完善新版申请的产品资料，沿用当前需求完善阶段与审计。"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.access_control.module_policy import can_sample
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.customers.services import model_snapshot
from apps.products.models import ProductInformation, ProductStatus
from .form_services import sample_form_edit_capabilities
from .models import SampleRequest, SampleRequestStatus, SampleWorkflowStage
from .services import SAMPLE_FIELDS, _record_workflow_stage, _start_sla, _write_sample_records, sample_product_values_from_source


def require_application_product_edit(sample, request):
    actor = getattr(request, 'employee', None)
    if not actor or not can_sample(request, sample, 'samples.complete_sample_requirements'):
        raise PermissionDenied('当前账号没有完善样品需求的权限。')
    if sample.archived_at or sample.customer_account.archived_at:
        raise Conflict('已归档的申请或客户不能编辑。')
    if not sample.application_payload_hash or not sample_form_edit_capabilities(sample)['can_complete']:
        raise Conflict('当前申请不在新版产品需求完善阶段。')


def application_product_candidates(*, sample, query, request):
    require_application_product_edit(sample, request)
    products = ProductInformation.objects.filter(status=ProductStatus.ACTIVE, archived_at__isnull=True)
    if query:
        products = products.filter(Q(product_name__icontains=query) | Q(specification__icontains=query) | Q(product_number__icontains=query))
    return products.order_by('product_number', 'id').values('id', 'product_name', 'specification', 'category_id')[:50]


@transaction.atomic
def complete_application_products(*, sample_id, data, request):
    sample = SampleRequest.objects.select_for_update().select_related('customer_account').get(pk=sample_id)
    require_matching_etag(request, sample)
    require_application_product_edit(sample, request)
    actor = request.employee
    products = {product.pk: product for product in sample.products.prefetch_related('details')}
    if {product['id'] for product in data['products']} != set(products):
        raise ValidationError({'products': '必须保留当前申请的全部产品，不能新增、删除或引用其他申请的产品。'})
    before = model_snapshot(sample, SAMPLE_FIELDS)
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
        product.category_name_snapshot = product.category.category_name
        product.save()
        for detail_values in values['details']:
            detail = details[detail_values['id']]
            if detail_values['sample_quantity'] < max(detail.cutting_reported_quantity, detail.metalwork_reported_quantity):
                raise ValidationError({'products': '打样数量不能小于已有报工数量。'})
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
            detail.save()
    sample.purpose = data['purpose']
    sample.status = SampleRequestStatus.MATERIALS_PENDING
    sample.save(update_fields=['purpose', 'status', 'updated_at'])
    completed_at = timezone.now()
    _start_sla(sample, completed_at)
    _record_workflow_stage(sample_request=sample, stage=SampleWorkflowStage.REQUIREMENTS_COMPLETED,
                           actor_employee=actor, note='工厂完善并提交样品需求。', operated_at=completed_at)
    _write_sample_records(sample_request=sample, action='REQUIREMENTS_COMPLETED', actor_employee=actor,
                          request=request, before_data=before, note='工厂完善并提交样品需求。')
    return sample
