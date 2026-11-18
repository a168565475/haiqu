"""部位、裁片的原料展示；只读取实际来源行，不解释品名引用为布料。"""
from rest_framework.exceptions import ValidationError

from .component_parts import is_cut_piece, is_cut_piece_source, is_sewn_part
from .material_flow_bom import cutting_fabric_attributes


def _text(value):
    return str(value or '').strip()


def component_source_materials(line):
    if is_sewn_part(line) and getattr(line, 'fabric_source_line', None) is not None:
        sources = [line.fabric_source_line]
    elif is_sewn_part(line) or is_cut_piece(line):
        # 未选归属面布的历史部位仍沿用裁片来源，已选部位只展示自己的选择。
        pieces = line.cut_pieces.all() if is_sewn_part(line) else [line]
        sources = []
        for piece in pieces:
            if (not is_cut_piece(piece) or piece.section.bom_id != line.section.bom_id
                    or piece.section_id != line.section_id):
                raise ValidationError({'parent_part': '部位组成须为同一 BOM 同一分区的裁片。'})
            if piece.fabric_source_line is not None:
                sources.append(piece.fabric_source_line)
    else:
        return []
    result, seen = [], set()
    for source in sources:
        if source.section.bom_id != line.section.bom_id or not is_cut_piece_source(source):
            raise ValidationError({'fabric_source_line': '归属面布或裁片来源须为同一 BOM 的面料或辅料原料行。'})
        source_id = str(source.pk)
        if source_id in seen:
            continue
        seen.add(source_id)
        saved = source.material_selection_snapshot or {}
        values = source.raw_values or {}
        inherited = cutting_fabric_attributes(source)
        result.append({
            'source_bom_line_id': source_id,
            'name': _text(saved.get('name') or source.part_name),
            'material': inherited.get('material', ''),
            'color': _text(inherited.get('color') or saved.get('color_name')
                           or values.get('accessory_color') or values.get('auxiliary_color')),
            'color_code': _text(saved.get('color_code') or values.get('fabric_color_code')),
            'fabric_spec': _text(inherited.get('specification') or saved.get('attributes', {}).get('specification')),
            'width': inherited.get('width', ''),
            'unit': _text(source.unit or saved.get('unit_name')),
        })
    return result
