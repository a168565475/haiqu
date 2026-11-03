"""打样独立选料，复用U2冻结的目录校验/补录事务，不创建BOM或旧组合档。"""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

from rest_framework.exceptions import ValidationError

from apps.boms.catalog_selection import apply_catalog_selection


CATEGORY_TITLES = {
    "tube": "管材类", "hardware": "五金件", "plastic": "塑料件类",
    "accessory": "辅料类", "fabric": "面料类", "packaging": "包材类",
}


def freeze_sample_selection(row, *, previous, request, versions):
    """调用方持有样品锁与外层事务；整单任一行失败会回滚本品名补录。"""
    catalog_id = row.get("material_catalog_id")
    if not catalog_id:
        raise ValidationError({"material_catalog_id": "请从新原料目录选择品名、具体属性及单位。"})
    if row.get("rawMaterialId"):
        raise ValidationError({"rawMaterialId": "新原料选择不能同时关联旧原料。"})
    pipe = row['category'] == 'tube'
    if (pipe and previous and previous.get('category') == 'tube' and previous.get('material_catalog_id')
            and previous.get('pipeInputMode') != 'TOTAL_METERS'
            and (not row.get('material_selection') or row.get('pipeInputMode') != 'TOTAL_METERS')):
        raise ValidationError({'quantity': '原管材数量口径需核实，请重新选料并填写米数，不自动换算旧数量。'})
    section = SimpleNamespace(title=CATEGORY_TITLES[row["category"]], section_type="OTHER")
    # 这是U2选料服务的字段投影，只有材料字段参与；不保存BOM对象或制造数量。
    line = SimpleNamespace(section=section, raw_values={})
    old = None
    if previous and previous.get("material_catalog_id"):
        old = SimpleNamespace(
            section=section, raw_values={}, material_quantity=None,
            material_catalog_id=previous["material_catalog_id"],
            material_selection_snapshot=previous["material_selection_snapshot"],
        )
    data = {"material_catalog_id": catalog_id}
    if row.get("material_selection"):
        data["material_selection"] = deepcopy(row["material_selection"])
    # 外层已核对打样对象范围；填料权只允许使用原料，主档维护仍按原权限校验。
    apply_catalog_selection(line, data, old=old, request=request, persist=True, versions=versions,
                            require_tube_length=False, selection_permission="samples.edit_sample_materials")
    snapshot = line.material_selection_snapshot
    if pipe and snapshot['unit_name'] != '根':
        raise ValidationError({'material_selection': '管材请选择根制原管；样品需求按米填写。'})
    pipe_calculation = None
    if pipe and row.get('quantity'):
        from .pipe_materials import PIPE_TOTAL_METERS_SCHEMA, total_meter_value
        pipe_calculation = {'schema_version': PIPE_TOTAL_METERS_SCHEMA, 'measurement_kind': 'PIPE',
            'required_meters': format(total_meter_value(row['quantity'], 'quantity'), 'f')}
    if not pipe and row.get('quantity') and snapshot['unit_name'] in {'根', '支', '套'}:
        quantity = Decimal(row['quantity'])
        if quantity != quantity.to_integral_value():
            raise ValidationError({'quantity': '根、支、套按整数数量填写，不自动换算。'})
    row.update(
        material_catalog_id=str(line.material_catalog_id),
        material_selection_snapshot=deepcopy(snapshot),
        name=line.part_name, specification=line.specification,
        material=line.material, color=snapshot["attributes"].get("color", ""),
        unitId='' if pipe else snapshot['unit_id'], unitLabel='米' if pipe else snapshot['unit_name'],
    )
    # 输出保存内容，下次普通数量/备注编辑直接复用快照，不能偷刷新目录版本。
    row.pop("material_selection", None)
    if pipe:
        row['pipeInputMode'] = 'TOTAL_METERS'
        if pipe_calculation is not None:
            row['pipeCalculation'] = pipe_calculation
        else:
            row.pop('pipeCalculation', None)
    else:
        row.pop('pipeInputMode', None)
        row.pop('pipeCalculation', None)
    row.pop("cuttingLengthMm", None)
    row.pop("piecesPerBar", None)
    return snapshot


def sample_saved_selection(row):
    """下游只消费已经保存的内容；不能从最新目录重建采购/库存身份。"""
    snapshot = row.get("material_selection_snapshot")
    if not isinstance(snapshot, dict) or str(row.get("material_catalog_id")) != snapshot.get("catalog_id"):
        raise ValidationError({"material_catalog_id": "打样材料缺少一致的已保存原料内容。"})
    from apps.material_catalog.saved_selection import validate_saved_material
    return validate_saved_material(snapshot, material_catalog_id=row['material_catalog_id'])
