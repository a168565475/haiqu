"""裁片与车缝部位的冻结实物身份；旧库存继续使用原有版本。"""
import json

from apps.material_catalog.definitions import TEMPLATES

from .public_stock_identity import _craft, _invalid, _make_identity, _positive_integer, _text, _uuid


PART_FLOW_KINDS = {'CUT_PIECE', 'SEWN_PART'}
COMPONENT_ATTRIBUTE_FIELDS = {field['key'] for field in TEMPLATES['FABRIC_SEMI']['fields']
                              if field['kind'] != 'unit'}


def _normalized_component_attributes(attributes):
    if not isinstance(attributes, dict) or set(attributes) - COMPONENT_ATTRIBUTE_FIELDS:
        _invalid('component_attributes', '部位或裁片属性必须使用裁片档案支持的属性字段。')
    return {key: _text(attributes[key], f'component_attributes.{key}') for key in sorted(attributes)}


def _component_attributes(line):
    snapshot = getattr(line, 'material_selection_snapshot', None) or {}
    if not isinstance(snapshot, dict):
        _invalid('material_selection_snapshot', '部位或裁片品名引用格式不正确。')
    version = snapshot.get('identity_attributes_version')
    # 旧引用即使选过属性，也继续按原身份解释，不能因本次升级重新合并或拆分库存。
    if version is None:
        return {}
    if (type(version) is not int or version != 1
            or snapshot.get('selection_kind') != 'BOM_COMPONENT_REFERENCE'):
        _invalid('identity_attributes_version', '部位或裁片属性身份版本不正确。')
    return _normalized_component_attributes(snapshot.get('attributes'))


def _source_properties(line):
    source = getattr(line, 'fabric_source_line', None)
    if source is None or source.section.bom_id != line.section.bom_id:
        _invalid('fabric_source_line', '裁片必须关联同一 BOM 中的真实面料或棉原料。')
    if getattr(source, 'material_catalog_id', None):
        from apps.material_catalog.saved_selection import validate_saved_material
        from apps.material_catalog.snapshots import material_identity_key
        selected = validate_saved_material(source.material_selection_snapshot,
            material_catalog_id=source.material_catalog_id)
        if selected['processing_state'] != 'RAW':
            _invalid('fabric_source_line', '裁片来源必须是原材料。')
        attrs = selected['attributes']
        return {'identity_key': material_identity_key(selected), 'material': selected['name'],
                'specification': _text(source.specification, 'source.specification'),
                'color': _text(attrs.get('color'), 'source.color', required=False),
                'unit': selected['unit_name']}
    values = source.raw_values or {}
    return {'identity_key': '', 'material': _text(source.material, 'source.material'),
            'specification': _text(source.specification, 'source.specification'),
            'color': _text(values.get('fabric_color_name') or values.get('fabric_color_code')
                           or values.get('auxiliary_color') or values.get('accessory_color'),
                           'source.color', required=False),
            'unit': _text(source.unit, 'source.unit')}


def _piece_properties(line):
    piece = {'name': _text(line.part_name, 'part_name'),
             'specification': _text(line.specification, 'specification'),
             'source': _source_properties(line)}
    unit_name = _text(line.unit, 'unit')
    # 片沿用旧形状和哈希；其他单位须进入父组成，防止不同计数口径混库。
    if unit_name != '片':
        piece['unit_name'] = unit_name
    return piece


def build_part_flow_identity(*, bom_line, completed_craft, unit):
    kind = bom_line.component_kind
    craft = _craft(completed_craft)
    unit_name = _text(unit.unit_name, 'unit_name')
    component_attributes = _component_attributes(bom_line)
    extended = bool(component_attributes)
    if kind == 'CUT_PIECE':
        if craft['code'] != 'CUTTING':
            _invalid('completed_craft', '裁片库存必须是裁剪完成状态。')
        piece = _piece_properties(bom_line)
        if unit_name != piece.get('unit_name', '片'):
            _invalid('unit', '裁片库存单位必须与 BOM 保存的单位一致。')
        if extended:
            piece['component_attributes'] = component_attributes
        composition = [{'piece': piece, 'quantity': 1}]
        material, color = piece['source']['material'], piece['source']['color']
    elif kind == 'SEWN_PART':
        if unit_name != _text(bom_line.unit, 'unit'):
            _invalid('unit', '部位库存单位必须与 BOM 保存的独立单位一致。')
        if craft['code'] not in {'SEWING', 'SCREEN_PRINTING', 'EMBROIDERY'}:
            _invalid('completed_craft', '部位库存须为车缝、丝印或刺绣完成状态。')
        children = list(bom_line.cut_pieces.all())
        child_attributes = [_component_attributes(child) for child in children]
        extended = extended or any(child_attributes)
        composition = []
        for child, attributes in zip(children, child_attributes):
            if child.component_kind != 'CUT_PIECE' or child.section.bom_id != bom_line.section.bom_id:
                _invalid('parent_part', '部位组成必须是同一 BOM 的裁片。')
            piece = _piece_properties(child)
            if extended:
                piece['component_attributes'] = attributes
            composition.append({'piece': piece,
                'quantity': _positive_integer(child.pieces_per_part, 'pieces_per_part')})
        if not composition:
            _invalid('cut_pieces', '部位尚无裁片组成，不能建立半成品库存。')
        composition.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
        material = ' / '.join(sorted({row['piece']['source']['material'] for row in composition}))
        color = ' / '.join(sorted({row['piece']['source']['color'] for row in composition
                                 if row['piece']['source']['color']}))
    else:
        _invalid('component_kind', '不是部位裁片流程。')
    snapshot = {'schema_version': 3, 'stock_kind': 'SEMI', 'semi_kind': kind,
        'unit_id': _uuid(unit.pk, 'unit_id'), 'unit_name': unit_name,
        'category': '裁片' if kind == 'CUT_PIECE' else '车缝部位',
        'part_name': _text(bom_line.part_name, 'part_name'),
        'specification': _text(bom_line.specification, 'specification', required=kind == 'CUT_PIECE'),
        'material': material, 'color': color, 'completed_craft': craft, 'composition': composition}
    if extended:
        snapshot['component_attributes'] = component_attributes
    return _make_identity(snapshot)


def validate_part_flow_identity(identity):
    snapshot = identity['identity_snapshot']
    extended = 'component_attributes' in snapshot
    fields = {'schema_version', 'stock_kind', 'semi_kind', 'unit_id', 'unit_name', 'category',
              'part_name', 'specification', 'material', 'color', 'completed_craft', 'composition'}
    if extended:
        fields.add('component_attributes')
    if set(snapshot) != fields or snapshot['stock_kind'] != 'SEMI' or snapshot['semi_kind'] not in PART_FLOW_KINDS:
        _invalid('identity_snapshot', '裁片或部位库存快照字段不完整。')
    for field in ('unit_name', 'category', 'part_name', 'material', 'specification', 'color'):
        required = field not in {'specification', 'color'} or (field == 'specification' and snapshot['semi_kind'] == 'CUT_PIECE')
        if _text(snapshot[field], field, required=required) != snapshot[field]:
            _invalid(field, '冻结属性未经规范化。')
    if _uuid(snapshot['unit_id'], 'unit_id') != snapshot['unit_id']:
        _invalid('unit_id', '冻结单位编号无效。')
    craft = snapshot['completed_craft']
    if (not isinstance(craft, dict) or set(craft) != {'id', 'craft_type', 'code'}
            or craft['craft_type'] not in {'INTERNAL', 'EXTERNAL'}):
        _invalid('completed_craft', '冻结完成工艺无效。')
    _uuid(craft['id'], 'completed_craft.id')
    allowed = {'CUTTING'} if snapshot['semi_kind'] == 'CUT_PIECE' else {'SEWING', 'SCREEN_PRINTING', 'EMBROIDERY'}
    if craft['code'] not in allowed:
        _invalid('completed_craft', '冻结实物种类、工艺或单位不一致。')
    composition = snapshot['composition']
    if not isinstance(composition, list) or not composition:
        _invalid('composition', '冻结部位组成不能为空。')
    has_attributes = False
    if extended:
        attributes = _normalized_component_attributes(snapshot['component_attributes'])
        if attributes != snapshot['component_attributes']:
            _invalid('component_attributes', '冻结部位或裁片属性未经规范化。')
        has_attributes = bool(attributes)
    for row in composition:
        if not isinstance(row, dict) or set(row) != {'piece', 'quantity'} or type(row['quantity']) is not int:
            _invalid('composition', '冻结裁片组成格式不正确。')
        _positive_integer(row['quantity'], 'composition.quantity')
        piece = row['piece']
        piece_fields = {'name', 'specification', 'source'}
        if isinstance(piece, dict) and 'unit_name' in piece:
            piece_fields.add('unit_name')
        if extended:
            piece_fields.add('component_attributes')
        if not isinstance(piece, dict) or set(piece) != piece_fields:
            _invalid('composition', '冻结裁片属性不完整。')
        if 'unit_name' in piece and (_text(piece['unit_name'], 'composition.unit_name') != piece['unit_name']
                                      or piece['unit_name'] == '片'):
            _invalid('composition.unit_name', '非片裁片须使用明确单位；片须沿用原冻结结构。')
        if snapshot['semi_kind'] == 'CUT_PIECE' and snapshot['unit_name'] != piece.get('unit_name', '片'):
            _invalid('unit', '裁片库存单位与冻结组成单位不一致。')
        if extended:
            attributes = _normalized_component_attributes(piece['component_attributes'])
            if attributes != piece['component_attributes']:
                _invalid('component_attributes', '冻结裁片属性未经规范化。')
            has_attributes = has_attributes or bool(attributes)
            if snapshot['semi_kind'] == 'CUT_PIECE' and attributes != snapshot['component_attributes']:
                _invalid('component_attributes', '裁片及其组成中的冻结属性不一致。')
        for field in ('name', 'specification'):
            if _text(piece[field], field) != piece[field]:
                _invalid('composition', '冻结裁片属性未经规范化。')
        source = piece['source']
        if not isinstance(source, dict) or set(source) != {'identity_key', 'material', 'specification', 'color', 'unit'}:
            _invalid('composition', '冻结原料属性不完整。')
        for field in source:
            if _text(source[field], field, required=field not in {'identity_key', 'color'}) != source[field]:
                _invalid('composition', '冻结原料属性未经规范化。')
    if snapshot['semi_kind'] == 'CUT_PIECE' and (len(composition) != 1 or composition[0]['quantity'] != 1):
        _invalid('composition', '单件裁片的库存身份不能带订单用量。')
    if extended and not has_attributes:
        _invalid('component_attributes', '没有实际属性时必须沿用原裁片或部位身份。')
    expected = _make_identity(snapshot)
    if identity != expected:
        _invalid('identity', '库存身份索引、单位或冻结组成不一致。')
    return expected
