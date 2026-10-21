"""打样管材需求与采购快照。

新口径的打样只填写总米数，采购阶段再填写采购根数和单根长度；旧口径
仍保留切割长度、每根支数的计算，保证历史样品和生产 BOM 不被改写。
"""
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from apps.boms.material_flow_calculations import MaterialFlowValueError, pipe_plan, positive_integer
from apps.products.models import RawMaterialInformation


PIPE_TOTAL_METERS_SCHEMA = 3


def is_total_meter_pipe(row):
    """判断是否为新口径的总米数需求。旧草稿没有该标记时按旧字段兼容。"""
    return bool(
        row.get('pipeInputMode') == 'TOTAL_METERS'
        or row.get('pipeCalculation', {}).get('schema_version') == PIPE_TOTAL_METERS_SCHEMA
        or (
            row.get('category') == 'tube'
            and not row.get('cuttingLengthMm')
            and not row.get('piecesPerBar')
            and row.get('pipeCalculation', {}).get('schema_version') != 2
        )
    )


def total_meter_value(value, field, *, allow_zero=False):
    if value in (None, ''):
        raise ValidationError({field: '请填写总米数。'})
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError({field: '总米数必须是有效数字。'}) from None
    if not result.is_finite() or result < 0 or (not allow_zero and result <= 0):
        raise ValidationError({field: '总米数必须大于 0。' if not allow_zero else '数量不能小于 0。'})
    if result.as_tuple().exponent < -4:
        raise ValidationError({field: '总米数最多保留 4 位小数。'})
    return result


def sample_pipe_material(row):
    material_id = row.get('rawMaterialId')
    try:
        material = RawMaterialInformation.objects.select_related('unit', 'category').filter(
            pk=material_id, archived_at__isnull=True, item_type='MATERIAL',
            category__category_name='管材', category__status='ACTIVE', category__archived_at__isnull=True,
            unit__unit_name='根', unit__status='ACTIVE', unit__archived_at__isnull=True,
        ).first() if material_id else None
    except (ValueError, TypeError, DjangoValidationError):
        material = None
    if material is None:
        raise ValidationError({'rawMaterialId': '请从材料资料选择有效的根制管材原材料，不能仅凭名称关联库存。'})
    return material


def sample_pipe_plan(row, quantity=None):
    try:
        return pipe_plan(cutting_length_mm=row.get('cuttingLengthMm'), pieces_per_product=1,
                         pieces_per_bar=row.get('piecesPerBar'),
                         order_quantity=row.get('quantity') if quantity is None else quantity,
                         calculation_version=2)
    except MaterialFlowValueError as error:
        raise ValidationError({error.field: str(error)}) from error


def sample_pipe_meter_snapshot(row, *, supply=None, shortage=None):
    """创建总米数快照，不推断采购根数或单根长度。"""
    demand = total_meter_value(row.get('quantity'), 'quantity')
    if supply is None:
        supply_value = total_meter_value(row.get('supplyQuantity'), 'supplyQuantity', allow_zero=True)
    else:
        supply_value = total_meter_value(supply, 'supplyQuantity', allow_zero=True)
    if shortage is None:
        shortage_value = demand - supply_value
    else:
        shortage_value = total_meter_value(shortage, 'shortageQuantity', allow_zero=True)
    if shortage_value < 0 or demand - supply_value != shortage_value:
        raise ValidationError({'lines': '打样管材需求、可供和缺料总米数不一致。'})
    return {
        'schema_version': PIPE_TOTAL_METERS_SCHEMA,
        'measurement_kind': 'PIPE',
        'source': 'SAMPLE',
        'required_meters': format(demand, 'f'),
        'supply_meters': format(supply_value, 'f'),
        'shortage_meters': format(shortage_value, 'f'),
        'sample_line_key': str(row['key']),
        'raw_material_id': str(row.get('rawMaterialId') or ''),
    }


def normalize_sample_pipe(row, *, submit):
    # 新口径只填总米数；旧草稿仍按支数和切割参数计算，不能改写历史快照。
    meter_mode = is_total_meter_pipe(row)
    row['unitId'] = ''
    row['unitLabel'] = '米' if meter_mode else '支'
    if meter_mode:
        row['pipeInputMode'] = 'TOTAL_METERS'
        row.pop('cuttingLengthMm', None)
        row.pop('piecesPerBar', None)
        if row.get('quantity') not in (None, '') or submit:
            total_meter_value(row.get('quantity'), 'quantity')
    else:
        # 支是旧打样需求单位，所选原料资料仍保留根制单位，不修改基础资料。
        for key in ('cuttingLengthMm', 'piecesPerBar', 'quantity'):
            if row.get(key) not in (None, '') or submit:
                try:
                    positive_integer(row.get(key), key)
                except MaterialFlowValueError as error:
                    raise ValidationError({key: str(error)}) from error
    if row.get('rawMaterialId') or submit:
        material = sample_pipe_material(row)
        row.update(rawMaterialId=str(material.pk), name=material.material_name,
                   specification=material.specification, material=material.material)
    if meter_mode:
        if submit or row.get('quantity') not in (None, ''):
            row['pipeCalculation'] = {'schema_version': PIPE_TOTAL_METERS_SCHEMA,
                                      'measurement_kind': 'PIPE',
                                      'required_meters': format(total_meter_value(row.get('quantity'), 'quantity'), 'f')}
        else:
            row.pop('pipeCalculation', None)
    elif submit or all(row.get(key) for key in ('cuttingLengthMm', 'piecesPerBar', 'quantity')):
        row['pipeCalculation'] = sample_pipe_plan(row)
    else:
        row.pop('pipeCalculation', None)


def sample_pipe_snapshot(procurement, row, *, validate_current_material=True):
    from apps.procurement.pipe_purchase import pipe_meters
    if is_total_meter_pipe(row):
        if row.get('unitLabel') != '米':
            raise ValidationError({'lines': '新口径打样管材需求单位必须为米。'})
        if validate_current_material:
            material = sample_pipe_material(row)
            if (row.get('name'), row.get('specification'), row.get('material')) != (
                    material.material_name, material.specification, material.material):
                raise ValidationError({'lines': '打样管材资料已变化，请核对材料来源。'})
        snapshot = sample_pipe_meter_snapshot(row)
        snapshot.update({'sample_procurement_request_id': str(procurement.pk)})
        return snapshot
    if row.get('unitLabel') != '支':
        raise ValidationError({'lines': '旧打样管材缺少支数需求，请补齐参数后重新提交材料需求。'})
    material_id = row.get('rawMaterialId')
    if validate_current_material:
        material = sample_pipe_material(row)
        material_id = str(material.pk)
        if (row.get('name'), row.get('specification'), row.get('material')) != (
                material.material_name, material.specification, material.material):
            raise ValidationError({'lines': '打样管材资料已变化，请核对材料来源。'})
    required = sample_pipe_plan(row)['demand_pieces']
    try:
        supply = positive_integer(row.get('supplyQuantity'), 'supplyQuantity', allow_zero=True)
        shortage = positive_integer(row.get('shortageQuantity'), 'shortageQuantity')
    except MaterialFlowValueError as error:
        raise ValidationError({error.field: str(error)}) from error
    if required - supply != shortage:
        raise ValidationError({'lines': '打样管材需求、可供和缺料支数不一致。'})
    plan = sample_pipe_plan(row, shortage)
    pipe_meters(plan['suggested_bar_count'], plan['raw_bar_length_m'])
    return {**plan, 'source': 'SAMPLE', 'sample_procurement_request_id': str(procurement.pk),
            'sample_line_key': str(row['key']), 'raw_material_id': material_id}


def sample_pipe_arrival_quantity(line, procurement, row):
    # 到货沿用采购时已冻结的身份和参数；基础资料改名不能改写历史合同。
    snapshot = sample_pipe_snapshot(procurement, row, validate_current_material=False)
    if (line.measurement_kind != 'PIPE' or line.source_unit_text_snapshot != '米'
            or str(line.raw_material_information_id) != snapshot['raw_material_id']
            or any(line.calculation_snapshot.get(key) != value for key, value in snapshot.items())
            or line.accepted_bar_count is None
            or not line.raw_bar_length_m
            or line.accepted_quantity != line.raw_bar_length_m * line.accepted_bar_count):
        raise ValidationError({'lines': '打样管材到货与冻结的根米换算来源不一致。'})
    if is_total_meter_pipe(row):
        # 新口径的需求本身就是米数；真实到货仍按采购填写的根数和单根长度换算。
        return Decimal(line.accepted_quantity)
    quantity = line.accepted_bar_count * snapshot['pieces_per_bar']
    try:
        positive_integer(quantity, 'arrivedQuantity')
    except MaterialFlowValueError as error:
        raise ValidationError({error.field: str(error)}) from error
    return Decimal(quantity)
