"""管材采购数量与来源快照；采购、到货和打印共享同一根米口径。"""
from decimal import Decimal, InvalidOperation, localcontext

from rest_framework.exceptions import ValidationError
from apps.core.api.exceptions import Conflict
from apps.boms.material_flow_calculations import MaterialFlowValueError, decimal_quantity, pipe_plan_for_line, positive_integer
from apps.products.material_identity import resolve_bom_line_raw_material


PIPE_PURCHASE_FIELDS = ('raw_bar_length_m', 'suggested_bar_count', 'suggested_purchase_meters',
                        'actual_bar_count', 'actual_purchase_meters', 'quantity_difference_reason', 'calculation_snapshot')


def is_sample_total_meter_snapshot(snapshot):
    return isinstance(snapshot, dict) and snapshot.get('schema_version') == 3 \
        and snapshot.get('measurement_kind') == 'PIPE' \
        and snapshot.get('source') == 'SAMPLE'


def pipe_source_snapshot(line):
    if line is None or line.section.section_type != 'PROFILE':
        raise ValidationError({'lines': '管材采购缺少明确的 BOM 部位来源。'})
    material, _ = resolve_bom_line_raw_material(line)
    if (material is None or material.item_type != 'MATERIAL' or material.category.category_name != '管材'
            or material.unit.unit_name != '根' or material.unit.status != 'ACTIVE' or material.unit.archived_at
            or material.category.status != 'ACTIVE' or material.category.archived_at):
        raise ValidationError({'lines': '管材须关联有效的根制原材料。'})
    try:
        result = pipe_plan_for_line(line)
    except MaterialFlowValueError as error:
        raise ValidationError({error.field: f'请先补齐并确认管材 BOM：{error}'}) from error
    if (line.raw_bar_length_m != Decimal(result['raw_bar_length_m'])
            or line.suggested_bar_count != result['suggested_bar_count']
            or line.suggested_purchase_meters != Decimal(result['suggested_purchase_meters'])):
        raise Conflict('管材 BOM 的计算参数与结果不一致，请重新确认 BOM。')
    pipe_meters(result['suggested_bar_count'], result['raw_bar_length_m'])
    return {**result, 'bom_id': str(line.section.bom_id), 'bom_line_id': str(line.pk),
            'component_identity': str(line.component_identity), 'raw_material_id': str(material.pk)}


def pipe_meters(bars, length, *, field='bar_count', allow_zero=False):
    try:
        roots = positive_integer(bars, field, allow_zero=allow_zero)
        meters_per_root = decimal_quantity(length, 'raw_bar_length_m', places=2)
        with localcontext() as context:
            context.prec = 64
            # 现有采购/到货数量字段保留 18,4；不能让派生值溢出旧数量列。
            meters = decimal_quantity(roots * meters_per_root, 'meter_quantity', allow_zero=allow_zero)
        return roots, meters
    except MaterialFlowValueError as error:
        raise ValidationError({error.field: str(error)}) from error


def purchase_pipe_values(snapshot, data):
    if is_sample_total_meter_snapshot(snapshot):
        roots = data.get('actual_bar_count')
        length = data.get('raw_bar_length_m')
        # 采购草稿可以先不填根数和单根长度；提交确认时由上层门禁要求完整。
        if roots is None and length is None:
            return {
                'raw_bar_length_m': None, 'suggested_bar_count': None,
                'suggested_purchase_meters': None, 'actual_bar_count': None,
                'actual_purchase_meters': None,
                'quantity_difference_reason': str(data.get('quantity_difference_reason') or '').strip(),
                'calculation_snapshot': snapshot,
            }
        if roots is None or length is None:
            raise ValidationError({'actual_bar_count': '打样管材采购必须同时填写采购根数和单根长度。'})
        roots, meters = pipe_meters(roots, length, field='actual_bar_count')
        submitted_quantity = data.get('actual_purchase_quantity')
        if submitted_quantity is not None and Decimal(str(submitted_quantity)) != meters:
            raise ValidationError({'actual_purchase_quantity': '打样管材采购米数由根数和单根长度自动计算。'})
        # 采购来源没有预设根长，填写后将实际根米结果写入采购行；需求快照仍保留在 calculation_snapshot。
        return {
            'raw_bar_length_m': length, 'suggested_bar_count': roots,
            'suggested_purchase_meters': meters, 'actual_bar_count': roots,
            'actual_purchase_meters': meters,
            'quantity_difference_reason': str(data.get('quantity_difference_reason') or '').strip(),
            'calculation_snapshot': snapshot,
        }
    values = {key: snapshot[key] for key in ('raw_bar_length_m', 'suggested_bar_count', 'suggested_purchase_meters')}
    values.update(calculation_snapshot=snapshot, actual_bar_count=None, actual_purchase_meters=None,
                  quantity_difference_reason=str(data.get('quantity_difference_reason') or '').strip())
    if data.get('actual_bar_count') is not None:
        roots, meters = pipe_meters(data['actual_bar_count'], snapshot['raw_bar_length_m'], field='actual_bar_count')
        values.update(actual_bar_count=roots, actual_purchase_meters=meters)
    elif data.get('actual_purchase_quantity') is not None:
        raise ValidationError({'actual_bar_count': '管材请填写实际采购根数，米数由系统计算。'})
    return values


def validate_pipe_purchase_source(line):
    from .reset_sources import validate_reset_source
    validate_reset_source(line)
    if line.section_type_snapshot != 'PROFILE':
        if line.purchase_order.source_type == 'SAMPLE':
            validate_sample_purchase_identity(line)
        return
    if not line.calculation_snapshot:
        raise Conflict('该管材采购仍为旧口径或缺少参数，请补齐来源并重新建立新口径采购。')
    if is_sample_total_meter_snapshot(line.calculation_snapshot):
        from apps.samples.models import SampleMaterialPurchaseSource
        binding = SampleMaterialPurchaseSource.objects.select_related('procurement_request').filter(purchase_order_line=line).first()
        if binding is None or binding.procurement_request_id != line.purchase_order.sample_procurement_request_id:
            raise Conflict('打样管材采购来源绑定缺失，请核对来源。')
        row = next((row for row in binding.procurement_request.lines if row['key'] == str(binding.line_key)), None)
        from apps.samples.pipe_materials import sample_pipe_snapshot
        if row is None or sample_pipe_snapshot(binding.procurement_request, row) != line.calculation_snapshot:
            raise Conflict('打样管材需求参数已变化，请重新核对采购来源。')
        # 新口径允许草稿阶段暂不填写根数与单根长度；确认/入库门禁会要求完整。
        return
    if not line.raw_bar_length_m:
        raise Conflict('该管材采购仍为旧口径或缺少参数，请补齐来源并重新建立新口径采购。')
    if line.bom_line_id:
        from apps.boms.models import Bom
        bom = line.bom_line.section.bom
        latest = Bom.objects.filter(product_line_id=bom.product_line_id, archived_at__isnull=True).order_by('-version_number', '-id').first()
        if bom.archived_at or latest is None or latest.pk != bom.pk:
            raise Conflict('采购来源已不是当前有效 BOM，请重新选择来源。')
        if bom.status != 'VERIFIED':
            raise Conflict('采购来源 BOM 尚未确认，请先确认并刷新采购来源。')
        current = pipe_source_snapshot(line.bom_line)
        if current != line.calculation_snapshot:
            raise Conflict('管材 BOM 来源已变化，请核对来源后重新建立采购，不能沿用旧预览。')
    elif line.purchase_order.source_type != 'SAMPLE':
        raise Conflict('管材采购来源已经删除，请核对来源。')
    else:
        from apps.samples.models import SampleMaterialPurchaseSource
        from apps.samples.pipe_materials import sample_pipe_snapshot
        binding = SampleMaterialPurchaseSource.objects.select_related('procurement_request').filter(purchase_order_line=line).first()
        if binding is None or binding.procurement_request_id != line.purchase_order.sample_procurement_request_id:
            raise Conflict('打样管材采购来源绑定缺失，请核对来源。')
        row = next((row for row in binding.procurement_request.lines if row['key'] == str(binding.line_key)), None)
        if row is None or sample_pipe_snapshot(binding.procurement_request, row) != line.calculation_snapshot:
            raise Conflict('打样管材需求参数已变化，请重新核对采购来源。')


def validate_sample_purchase_identity(line):
    from apps.samples.models import SampleMaterialPurchaseSource
    from apps.samples.material_identity import sample_material_snapshot
    binding = SampleMaterialPurchaseSource.objects.select_related('procurement_request').filter(purchase_order_line=line).first()
    if binding is None or binding.procurement_request_id != line.purchase_order.sample_procurement_request_id:
        raise Conflict('打样采购来源绑定缺失，请核对来源。')
    row = next((row for row in binding.procurement_request.lines if row['key'] == str(binding.line_key)), None)
    snapshot = {key:value for key,value in line.calculation_snapshot.items() if key != 'reset_source'}
    if row is None or sample_material_snapshot(binding.procurement_request, row) != snapshot:
        raise Conflict('打样材料来源已变化，请重新核对采购来源。')


def pipe_sheet_fields(line):
    if not line.raw_bar_length_m:
        if line.section_type_snapshot == 'PROFILE':
            raise Conflict('旧口径管材采购不能生成新供应商表，请先补齐根米参数。')
        return {}
    return {'measurement_kind': 'PIPE', 'schema_version': 2,
            'raw_bar_length_m': format(line.raw_bar_length_m, '.2f'),
            'actual_bar_count': line.actual_bar_count,
            'actual_purchase_meters': format(line.actual_purchase_meters, '.2f') if line.actual_purchase_meters is not None else '',
            'suggested_bar_count': line.suggested_bar_count,
            'suggested_purchase_meters': format(line.suggested_purchase_meters, '.2f'),
            'calculation_snapshot': line.calculation_snapshot, 'price_unit': '元/米'}


def normalize_pipe_sheet_line(original, submitted, settlement_mode):
    """已确认采购的根米快照不可在供应商表里单独改写。"""
    if original.get('measurement_kind') != 'PIPE':
        return {}
    if settlement_mode == 'ACTUAL_WEIGHT':
        raise ValidationError({'settlement_mode': '管材按米计价，不能选择按实际重量结算。'})
    for key in ('raw_bar_length_m', 'actual_bar_count', 'actual_purchase_meters', 'quantity', 'unit', 'unit_price'):
        if str(submitted.get(key, original.get(key))) != str(original.get(key)):
            # 数字允许等值格式，不能利用修改单位、数量、价格使采购和合同脱节。
            if key == 'unit':
                raise ValidationError({'lines': '管材采购单位固定为米。'})
            try:
                equal = Decimal(str(submitted.get(key))) == Decimal(str(original.get(key)))
            except (InvalidOperation, ValueError, TypeError):
                equal = False
            if not equal:
                raise ValidationError({'lines': '管材根数、长度、米数及每米单价已由采购确认，请返回采购流程调整。'})
    keys = ('measurement_kind', 'schema_version', 'raw_bar_length_m', 'actual_bar_count',
            'actual_purchase_meters', 'suggested_bar_count', 'suggested_purchase_meters', 'calculation_snapshot', 'price_unit')
    return {key: original.get(key) for key in keys}


def pipe_print_description(line):
    if line.get('measurement_kind') != 'PIPE':
        return ''
    return f"{line['actual_bar_count']} 根 × {line['raw_bar_length_m']} 米/根 = {line['actual_purchase_meters']} 米；单价：元/米"


def validate_pipe_sheet_source(sheet):
    """真实来源负责识别旧管材，不能仅凭可缺失的 JSON 标志决定放行。"""
    from .models import PurchaseOrderLine, PurchaseRequestAllocation
    if getattr(sheet, 'purchase_request_id', None):
        if PurchaseRequestAllocation.objects.filter(supplier_purchase_sheet=sheet,
                purchase_request_line__bom_line__section__section_type='PROFILE').exists():
            raise ValidationError({'content': '旧管材分配采购表不能继续发布，请重新建立根米采购。'})
    if not getattr(sheet, 'purchase_order_id', None):
        return
    source_lines = PurchaseOrderLine.objects.filter(purchase_order_id=sheet.purchase_order_id,
                                                    supplier_id=sheet.supplier_id, section_type_snapshot='PROFILE')
    snapshot = sheet.content_snapshot if isinstance(sheet.content_snapshot, dict) else {}
    rows = {str(row.get('source_purchase_order_line_id')): row for row in snapshot.get('lines', []) if isinstance(row, dict)}
    for source in source_lines:
        row = rows.get(str(source.pk), {})
        if not source.raw_bar_length_m or row.get('measurement_kind') != 'PIPE' or row.get('schema_version') != 2:
            raise ValidationError({'content': '旧单位管材采购表不能继续发布，请重新建立根米采购表。'})
        expected = {**pipe_sheet_fields(source), 'quantity': str(source.actual_purchase_quantity),
                    'unit': '米', 'unit_price': str(source.unit_price)}
        normalize_pipe_sheet_line(expected, row, snapshot.get('settlement_mode'))
