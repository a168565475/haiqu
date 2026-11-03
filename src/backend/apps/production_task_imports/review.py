from copy import deepcopy

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .matching import match_result
from .services import audit, editable
from .validation import validate_result_size


HEADER_FIELDS = ('task_number', 'order_date', 'delivery_date', 'salesperson_id', 'follower_ids',
                 'includes_tax', 'tax_rate', 'order_tolerance_percent', 'is_repeat_order',
                 'preproduction_sample_required', 'delivery_method')
PRODUCT_FIELDS = ('customer_product_name', 'customer_specification', 'customer_color', 'material',
                  'quantity', 'unit_id', 'unit_price', 'special_requirements', 'packaging_method')
NONBLOCKING_TYPES = {'UNMAPPED', 'IMAGE_UNRESOLVED', 'EXTERNAL_REFERENCE'}


def issue_list(record):
    issues = []
    for index, issue in enumerate(record.extraction.get('issues', [])):
        issues.append({**issue, 'id': 'issue_' + str(index), 'blocking': issue['type'] not in NONBLOCKING_TYPES})
    for index, item in enumerate(record.extraction.get('unmapped_content', [])):
        issues.append({'id': 'unmapped_' + str(index), 'type': 'UNMAPPED', 'blocking': False,
                       'message': item['summary'], 'field_path': None, 'source_ids': item['source_ids']})
    groups = [('fields', record.extraction.get('fields', {}))]
    groups.extend((f"products.{row['line_key']}.fields", row['fields']) for row in record.extraction.get('products', []))
    for prefix, fields in groups:
        for name, field in fields.items():
            if field['status'] == 'CONFLICT':
                issues.append({'id': prefix + '.' + name, 'type': 'CONFLICT', 'blocking': True,
                               'message': '字段有多个冲突来源，请明确处置。', 'field_path': prefix + '.' + name,
                               'source_ids': field['source_ids']})
    return issues


def validate_review(record, review, *, complete=True):
    validate_result_size(review)
    if (not isinstance(review, dict) or set(review) != {'payload', 'confirmed_fields', 'issues', 'selected_images'}
            or not isinstance(review['payload'], dict) or not isinstance(review['confirmed_fields'], list)
            or not all(isinstance(item, str) for item in review['confirmed_fields'])
            or not isinstance(review['issues'], dict) or not isinstance(review['selected_images'], dict)):
        raise ValidationError({'review': '核对稿结构不正确。'})
    payload = review['payload']
    if set(payload) & {'import_object_id', 'result_revision', 'contract_number_token', 'contract_number'}:
        raise ValidationError({'review': '核对稿不接收导入关联或 ERP 合同号。'})
    products = payload.get('products')
    if not isinstance(products, list) or not products or len(products) > 100 or any(not isinstance(row, dict) for row in products):
        raise ValidationError({'products': '请核对至少一条有效产品。'})
    line_keys = [row.get('client_key') for row in products]
    expected = {row['line_key'] for row in record.extraction['products']}
    if (any(not isinstance(key, str) for key in line_keys) or len(line_keys) != len(set(line_keys))
            or set(line_keys) != expected):
        raise ValidationError({'products': '导入产品必须逐行核对；需要其他产品请使用独立手工草稿。'})
    required = set(HEADER_FIELDS)
    required |= {f'products.{key}.{field}' for key in line_keys for field in PRODUCT_FIELDS}
    if complete and not required <= set(review['confirmed_fields']):
        raise ValidationError({'confirmed_fields': '请明确核对所有任务字段和产品字段，页面默认值不作为已识别依据。'})
    issues = issue_list(record)
    if set(review['issues']) - {item['id'] for item in issues}:
        raise ValidationError({'issues': '核对稿包含不存在的问题。'})
    for issue in issues:
        resolution = review['issues'].get(issue['id'])
        if not complete and resolution is None:
            continue
        if (not isinstance(resolution, dict) or set(resolution) != {'status', 'note'}
                or resolution['status'] not in ('RESOLVED', 'TODO')
                or not isinstance(resolution['note'], str) or not 1 <= len(resolution['note'].strip()) <= 2000):
            raise ValidationError({'issues': '请逐项填写冲突/待办的处置说明。'})
        if complete and issue['blocking'] and resolution['status'] != 'RESOLVED':
            raise ValidationError({'issues': '关键冲突解决后才能保存。'})
    allowed_images = {image['image_id'] for image in record.extraction.get('image_candidates', [])}
    if set(review['selected_images']) - expected:
        raise ValidationError({'selected_images': '图片指定了不存在的产品行。'})
    if any(image is not None and image not in allowed_images for image in review['selected_images'].values()):
        raise ValidationError({'selected_images': '只能选择此任务解析得到的图片。'})
    return deepcopy(review)


@transaction.atomic
def save_review(request, record_id, review):
    record = editable(request, record_id, ('REVIEW',))
    record.review = validate_review(record, review, complete=False)
    record.reviewed_at = timezone.now()
    record.save()
    audit(record, 'IMPORT_REVIEWED', request)
    return record


@transaction.atomic
def rematch(request, record_id):
    record = editable(request, record_id, ('REVIEW',))
    record.matching = match_result(record.extraction)
    record.save()
    return record
