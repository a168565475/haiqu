"""新建 BOM 的组成门禁；无创建标记的历史 BOM 保持原口径。"""
from rest_framework.exceptions import ValidationError


STRUCTURE_MESSAGE = '部位与裁片组成待完善：请先整理源表裁片，确认部位、所属裁片、原料来源和用量配比后再确认 BOM；系统不会猜测部位归属或自动归区。'


def new_bom_source_metadata(metadata):
    return {**(metadata or {}), 'component_structure_version': 1}


def _explicit_cutting_source(headers, raw_values, quantity):
    for column, value in (headers or {}).items():
        header = ''.join(str(value or '').split())
        if header == '裁片量' and str(quantity or '').strip():
            return True
        if header == '裁片名称' and str((raw_values or {}).get(column) or '').strip():
            return True
    return False


def component_structure_data(bom, lines=None):
    if lines is None:
        lines = (line for section in bom.sections.all() for line in section.lines.all())
    lines = list(lines)
    required = ((bom.source_metadata or {}).get('component_structure_version') == 1
        or any(line.component_kind in {'CUT_PIECE', 'SEWN_PART'} for line in lines))
    pending = required and any(not line.component_kind and (line.section.title.strip() == '裁剪明细'
        or _explicit_cutting_source(getattr(line.section, 'headers', {}), getattr(line, 'raw_values', {}),
            getattr(line, 'cut_piece_quantity', ''))) for line in lines)
    return {'required': required, 'pending': pending, 'message': STRUCTURE_MESSAGE if pending else ''}


def require_component_structure(bom, lines):
    if component_structure_data(bom, lines)['pending']:
        raise ValidationError({'sections': STRUCTURE_MESSAGE})


def imported_component_structure(plan):
    pending = any(not line.get('component_kind') and (section['title'].strip() == '裁剪明细'
        or _explicit_cutting_source(section.get('headers'), line.get('raw_values'), line.get('cut_piece_quantity')))
        for section in plan['sections'] for line in section['lines'])
    return {'required': True, 'pending': pending, 'message': STRUCTURE_MESSAGE if pending else ''}
