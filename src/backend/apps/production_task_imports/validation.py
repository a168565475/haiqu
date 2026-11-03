"""固定两份提取契约的结构和来源校验；不信任模型返回的 ERP ID 或成功声明。"""
import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from .storage import ImportFailure


def require(condition, code='INVALID_MODEL_OUTPUT'):
    if not condition:
        raise ImportFailure(code)


def schema_for(phase):
    require(phase in ('discovery', 'extraction'))
    return json.loads((Path(__file__).parent / 'schemas' / f'{phase}.json').read_text(encoding='utf-8'))


def validate_schema(value, schema, root=None, depth=0):
    """仅处理本模块固定 schema 的 type/properties/items/enum/$ref；不加载外部引用。"""
    require(depth <= 24)
    root = schema if root is None else root
    if '$ref' in schema:
        reference = schema['$ref']
        require(reference.startswith('#/$defs/') and reference[8:] in root.get('$defs', {}))
        return validate_schema(value, root['$defs'][reference[8:]], root, depth + 1)
    types = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
    kinds = {dict: 'object', list: 'array', str: 'string', bool: 'boolean', type(None): 'null'}
    require(kinds.get(type(value)) in types)
    if 'enum' in schema:
        require(value in schema['enum'])
    if isinstance(value, dict):
        require(set(value) == set(schema['required']) and set(value) <= set(schema['properties']))
        for key, item in value.items():
            validate_schema(item, schema['properties'][key], root, depth + 1)
    elif isinstance(value, list):
        require(len(value) <= 10000)
        for item in value:
            validate_schema(item, schema['items'], root, depth + 1)
    elif isinstance(value, str):
        require(len(value) <= 20000 and '\x00' not in value)


def validate_result_size(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError):
        raise ImportFailure('INVALID_MODEL_OUTPUT') from None
    require(len(encoded) <= 2 * 1024 * 1024, 'OUTPUT_LIMIT')


def references(ids, allowed, *, nonempty=False):
    require(isinstance(ids, list) and all(isinstance(item, str) for item in ids))
    require(len(ids) == len(set(ids)) and set(ids) <= allowed and (ids or not nonempty))


def source_scope(manifest, candidate):
    selected = set(candidate['task_source_ids'] + candidate['auxiliary_source_ids'])

    def add_known_source(item):
        source_id = item.get('source_id')
        if source_id in manifest['source_index']:
            selected.add(source_id)

    def add_picture_sources(picture):
        add_known_source(picture)
        for kind in ('embed', 'link'):
            relation = picture.get(kind) or {}
            if relation.get('external'):
                add_known_source(relation)

    # 工作表标题表示完整该表；单元格引用不隐式扩大到整本或同名表。
    sheets = {item['sheet_part'] for key, item in manifest['source_index'].items()
              if key in selected and item['kind'] == 'sheet_title'}
    selected |= {key for key, item in manifest['source_index'].items() if item.get('sheet_part') in sheets}
    images = set()
    for sheet in manifest['sheets']:
        for cell in sheet['cells']:
            picture = cell.get('dispimg', {}).get('picture') or {}
            if cell['source_id'] in selected:
                add_known_source(cell.get('dispimg') or {})
                add_picture_sources(picture)
                images.update(picture.get(key) for key in ('embed_image_id', 'link_image_id') if picture.get(key))
        for picture in sheet['pictures']:
            if picture['source_id'] in selected:
                add_picture_sources(picture)
                images.update(picture.get(key) for key in ('embed_image_id', 'link_image_id') if picture.get(key))
    for image in manifest['images']:
        if image['id'] in images or image['source_id'] in selected:
            images.add(image['id'])
            selected.add(image['source_id'])
    # runtime_payload 会发送这些全局图片元数据及其嵌套关系；只补引用，不扩张图片或工作表。
    for picture in manifest.get('cell_images', {}).values():
        if picture.get('embed_image_id') in images or picture.get('link_image_id') in images:
            add_picture_sources(picture)
    return selected, images


def discovery_result(value, manifest):
    validate_result_size(value)
    validate_schema(value, schema_for('discovery'))
    allowed = set(manifest['source_index'])
    require(0 < len(value['candidates']) <= 50)
    keys = [row['candidate_key'] for row in value['candidates']]
    require(len(keys) == len(set(keys)) and all(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key) for key in keys))
    candidates = []
    bom_sources = set()
    for section in value['auxiliary_sections']:
        references(section['source_ids'], allowed, nonempty=True)
        require(set(section['candidate_keys']) <= set(keys))
        if section['kind'] == 'BOM':
            bom_sources.update(section['source_ids'])
    for candidate in value['candidates']:
        references(candidate['task_source_ids'], allowed, nonempty=True)
        references(candidate['auxiliary_source_ids'], allowed)
        require(set(candidate['task_source_ids']) - bom_sources)
        require(candidate['product_summary'].strip())
        if candidate['grouping_uncertain']:
            require(candidate['uncertainty_reason'] and candidate['uncertainty_reason'].strip())
        identity = [manifest['source_sha256'], sorted(candidate['task_source_ids']),
                    candidate['task_number_original'], candidate['version_description']]
        object_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        scope, _ = source_scope(manifest, candidate)
        parts = {manifest['source_index'][key].get('sheet_part') for key in scope}
        candidates.append({**candidate, 'object_id': object_id, 'sheets': [
            {'name': sheet['name'], 'state': sheet['state']} for sheet in manifest['sheets'] if sheet['part'] in parts]})
    require(len({row['object_id'] for row in candidates}) == len(candidates))
    for issue in value['issues']:
        references(issue['source_ids'], allowed)
    return candidates


def extraction_result(value, manifest, candidate):
    validate_result_size(value)
    validate_schema(value, schema_for('extraction'))
    require(value['candidate_key'] == candidate['candidate_key'])
    scope, images = source_scope(manifest, candidate)
    require(0 < len(value['products']) <= 100)
    keys = [row['line_key'] for row in value['products']]
    require(len(keys) == len(set(keys)) and all(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key) for key in keys))
    issues = [row['issue_key'] for row in value['issues']]
    require(len(issues) == len(set(issues)))
    groups = [value['fields']] + [row['fields'] for row in value['products']]
    for fields in groups:
        for name, field in fields.items():
            references(field['source_ids'], scope, nonempty=field['status'] != 'MISSING')
            if field['status'] == 'MISSING':
                require(field['value'] is None)
            elif field['status'] == 'EXTRACTED':
                require(field['value'] is not None and field['value'] != '')
                validate_value(name, field['value'])
            # CONFLICT 的候选值只展示，不进入预填白名单。
    for issue in value['issues']:
        references(issue['source_ids'], scope)
        require(issue['product_line_key'] is None or issue['product_line_key'] in keys)
    for item in value['unmapped_content']:
        references(item['source_ids'], scope, nonempty=True)
    image_keys = [image['image_id'] for image in value['image_candidates']]
    require(len(image_keys) == len(set(image_keys)) and set(image_keys) == images)
    for image in value['image_candidates']:
        references(image['source_ids'], scope, nonempty=True)
        require(image['image_id'] in images)
        require(image['proposed_product_line_key'] is None or image['proposed_product_line_key'] in keys)
    return value


def validate_value(name, value):
    try:
        if name in ('order_date', 'delivery_date'):
            require(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)))
            date.fromisoformat(value)
        elif name == 'quantity':
            require(bool(re.fullmatch(r'[1-9]\d{0,18}', value)) and int(value) <= 9223372036854775807)
        elif name in ('unit_price_cny', 'unit_price_original', 'order_tolerance_percent', 'tax_rate'):
            require(bool(re.fullmatch(r'\d{1,18}(?:\.\d{1,8})?', value)))
            require(Decimal(value).is_finite())
            if name == 'order_tolerance_percent':
                require(0 <= Decimal(value) <= 100)
            if name == 'tax_rate':
                require(Decimal(value) in (3, 5, 7))
        elif name == 'delivery_method':
            require(value in ('SINGLE', 'SPLIT'))
        elif name == 'task_number_suggestion':
            require(bool(re.fullmatch(r'HT\d+(?:-\d+)*', value)) and len(value) <= 50)
        elif name in ('includes_tax', 'is_repeat_order', 'preproduction_sample_required'):
            require(type(value) is bool)
    except (ValueError, TypeError, InvalidOperation):
        raise ImportFailure('INVALID_MODEL_OUTPUT') from None


def extracted(field):
    return field['value'] if field and field['status'] == 'EXTRACTED' else None
