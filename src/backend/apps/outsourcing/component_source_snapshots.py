"""只读冻结的裁片来源；旧单缺少字段时不查当前 BOM 或材料档案。"""
from copy import deepcopy


def frozen_component_source_materials(snapshot, input_identity=None):
    if 'component_source_materials' in snapshot:
        return deepcopy(snapshot['component_source_materials'])
    identity = snapshot.get('public_output_identity') or input_identity or snapshot.get('input_identity') or {}
    rows = []
    for item in identity.get('identity_snapshot', {}).get('composition', []):
        source = item.get('piece', {}).get('source', {})
        if not source:
            continue
        # 旧 catalog 身份把品名放在 material；没有保存真正材质，不能猜补。
        catalog = bool(source.get('identity_key'))
        row = {'source_bom_line_id': '', 'name': source.get('material', '') if catalog else '',
            'material': '' if catalog else source.get('material', ''), 'color': source.get('color', ''),
            'color_code': '', 'fabric_spec': source.get('specification', ''), 'width': '',
            'unit': source.get('unit', '')}
        if row not in rows:
            rows.append(row)
    return rows
