"""委外专用材料快照保存；库存身份仍由inventory公共入口负责。"""
from rest_framework.exceptions import ValidationError

from apps.inventory.processing_material_snapshots import freeze_processing_materials
from apps.inventory.public_stock_identity import validate_public_identity


def processing_line_fields(*, bom_line, row, craft):
    if not bom_line.material_catalog_id:
        return {}
    frozen = row.get('snapshot', {})
    pair = freeze_processing_materials(
        input_snapshot=frozen.get('input_material_selection_snapshot'),
        output_snapshot=frozen.get('output_material_selection_snapshot'),
        input_catalog_id=bom_line.material_catalog_id, output_catalog_id=bom_line.material_catalog_id,
        completed_craft=craft, semi_kind='PIPE' if bom_line.section.section_type == 'PROFILE' else 'CUTTING',
    )
    return {**pair, 'input_material_catalog_id': pair['input_material_selection_snapshot']['catalog_id'],
            'output_material_catalog_id': pair['output_material_selection_snapshot']['catalog_id']}


def require_saved_processing_materials(line):
    """回货校验只读取原单；不能用当前BOM或目录补齐缺损的新材料快照。"""
    if not line.output_material_catalog_id and not line.input_material_catalog_id:
        return
    if not line.output_material_catalog_id or not line.input_material_catalog_id:
        raise ValidationError({'lines': '原单输入和产出材料关联不完整，不能办理回货。'})
    pair = freeze_processing_materials(
        input_snapshot=line.input_material_selection_snapshot,
        output_snapshot=line.output_material_selection_snapshot,
        input_catalog_id=line.input_material_catalog_id, output_catalog_id=line.output_material_catalog_id,
        completed_craft=line.order.craft,
        semi_kind='CUTTING' if line.order.source_kind in {'PUBLIC_CUTTING', 'SEWING'} else 'PIPE',
    )
    identity = validate_public_identity(line.snapshot.get('public_output_identity'))
    if identity['identity_snapshot'].get('material_selection_snapshot') != pair['output_material_selection_snapshot']:
        raise ValidationError({'lines': '原单产出材料与冻结库存身份不一致，不能办理回货。'})
    source = validate_public_identity(line.input_identity)
    if source['identity_snapshot'].get('material_selection_snapshot') != pair['input_material_selection_snapshot']:
        raise ValidationError({'lines': '原单投入材料与冻结库存身份不一致，不能办理回货。'})
