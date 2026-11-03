"""加工单据保存输入和产出材料事实；不查询目录，不构造库存哈希。"""
from rest_framework.exceptions import ValidationError

from apps.material_catalog.saved_selection import validate_saved_material
from .public_stock_identity import _craft

KILOGRAM_TUBE_PROCESSING_MESSAGE = '按公斤计量的管材暂不支持加工／外发。'


def tube_processing_not_enabled(bom_line):
    selected = bom_line.material_selection_snapshot or {}
    if (bom_line.material_catalog_id and selected.get('category_key') == 'TUBE'
            and str(selected.get('unit_name', '')).strip().lower() in {'公斤', '千克', 'kg'}):
        return KILOGRAM_TUBE_PROCESSING_MESSAGE
    return ''


def _fail(field, message):
    raise ValidationError({field: message})


def copy_material_selection(snapshot, *, field, catalog_id=None):
    """校验单据边界的保存结构；不拿当前目录选项重新解释历史。"""
    try:
        saved = validate_saved_material(snapshot, material_catalog_id=catalog_id)
    except ValidationError as error:
        raise ValidationError({field: error.detail}) from error
    if any(value.strip() in {'/', '-', '—'} for value in saved['attributes'].values()):
        _fail(field, '材料快照缺少确定的实物属性。')
    return saved


def freeze_processing_materials(*, input_snapshot, output_snapshot, output_catalog_id,
                                completed_craft, semi_kind, input_catalog_id=None):
    """来源由业务入口解析，库存工艺由调用方传入（厂内车缝沿用共用车缝工艺）。"""
    source = copy_material_selection(input_snapshot, field='input_material_selection_snapshot',
                                     catalog_id=input_catalog_id)
    result = copy_material_selection(output_snapshot, field='output_material_selection_snapshot',
                                     catalog_id=output_catalog_id)
    actual = _craft(completed_craft)
    if (result['processing_state'] != 'PROCESSED' or result['completed_craft'] != actual
            or result['processing_stage'] != actual['code'] or result['semi_kind'] != semi_kind):
        _fail('output_material_selection_snapshot', '产出材料与本次实际完成工艺不一致。')
    return {'input_material_selection_snapshot': source, 'output_material_selection_snapshot': result}
