"""仅处理材料账重置后的采购来源复核，不自动切换 BOM 或覆盖价格。"""
from decimal import Decimal
from apps.core.api.exceptions import Conflict


def validate_purchase_description(line, source):
    for current_field, snapshot_field in [('part_name','part_name_snapshot'),('specification','specification_snapshot'),
                                          ('raw_material','raw_material_snapshot'),('material','material_snapshot')]:
        if getattr(source,current_field) != getattr(line,snapshot_field):
            raise Conflict('当前 BOM 材料名称、规格或材质与原采购快照不一致，必须人工核对，不能自动沿用旧价格。')


def current_bom_source(line):
    from apps.boms.models import Bom
    from apps.procurement.services import _source_quantity
    from apps.products.material_identity import resolve_bom_line_raw_material
    if not line.bom_line_id:
        raise Conflict('采购来源 BOM 明细缺失，请核对后重新建立采购。')
    source = line.bom_line
    validate_purchase_description(line,source)
    bom = source.section.bom
    latest = Bom.objects.filter(product_line_id=bom.product_line_id, archived_at__isnull=True).order_by('-version_number','-id').first()
    if bom.archived_at or not latest or bom.pk != latest.pk or bom.status != 'VERIFIED':
        raise Conflict('重置后的采购来源不是当前已确认 BOM，请先核对来源。')
    material, _ = resolve_bom_line_raw_material(source)
    if material is None or material.archived_at or material.item_type != 'MATERIAL':
        raise Conflict('采购缺少有效的原材料关联，请修正 BOM。')
    quantity, field, text, unit, status = _source_quantity(source, bom)
    if status != 'READY' or quantity is None or quantity <= 0 or unit not in {material.unit.unit_name,material.unit.unit_code}:
        raise Conflict('采购来源数量或单位无效，请修正 BOM。')
    if source.section.section_type != line.section_type_snapshot:
        raise Conflict('采购分类与来源 BOM 不一致。')
    return {'bom_line_id':str(source.pk), 'bom_id':str(bom.pk), 'raw_material_id':str(material.pk),
            'quantity':str(quantity), 'unit':unit, 'part_name':source.part_name,
            'source_quantity_field':field, 'source_quantity_text':text,
            'specification':source.specification, 'raw_material':source.raw_material}


def reset_source_snapshot(line):
    from django.core.exceptions import ObjectDoesNotExist
    from rest_framework.exceptions import APIException
    try:
        if line.purchase_order.source_type == 'SAMPLE':
            from apps.procurement.pipe_purchase import validate_sample_purchase_identity
            validate_sample_purchase_identity(line)
            return {'sample':True}, ''
        return current_bom_source(line), ''
    except (APIException, ObjectDoesNotExist) as error:
        return {'blocked':str(error)}, str(error)


def validate_reset_source(line):
    snapshot = line.calculation_snapshot.get('reset_source')
    if snapshot is None:
        return
    current, warning = reset_source_snapshot(line)
    if warning or current != snapshot:
        raise Conflict('重置采购的数量、物料或 BOM 来源需重新核对，不能沿用旧采购确认。' + warning)
    if line.purchase_order.source_type != 'SAMPLE':
        if line.required_quantity != Decimal(current['quantity']) or line.source_unit_text != current['unit']:
            raise Conflict('重置采购的建议数量或单位与当前 BOM 不一致，请核对来源。')


def refresh_reset_purchase_source(line):
    blocked = line.calculation_snapshot.get('reset_source',{}).get('blocked')
    if blocked:
        if line.purchase_order.status != 'DRAFT':
            raise Conflict('重置来源只允许在待确认采购中刷新。')
        snapshot, warning = reset_source_snapshot(line)
        if warning:
            raise Conflict(warning)
        if not snapshot.get('sample'):
            if snapshot['unit'] != line.source_unit_text:
                raise Conflict('修复后的原料单位与旧采购不一致，不能自动沿用旧数量和价格。')
            line.required_quantity = Decimal(snapshot['quantity'])
            line.source_quantity_field = snapshot['source_quantity_field']
            line.source_quantity_text = snapshot['source_quantity_text']
            line.quantity_parse_status = 'READY'
        line.calculation_snapshot = {**line.calculation_snapshot,'reset_source':snapshot}
        return ['required_quantity','source_quantity_field','source_quantity_text','quantity_parse_status']
    if not line.calculation_snapshot.get('requires_source_confirmation'):
        return []
    if line.purchase_order.status != 'DRAFT':
        raise Conflict('重置管材来源只允许在待确认采购中刷新。')
    from apps.procurement.pipe_purchase import pipe_source_snapshot, validate_pipe_purchase_source
    if line.purchase_order.source_type == 'SAMPLE':
        from django.core.exceptions import ObjectDoesNotExist
        from apps.samples.pipe_materials import sample_pipe_snapshot
        try:
            binding = line.sample_material_source
            row = next(r for r in binding.procurement_request.lines if r['key'] == str(binding.line_key))
            snapshot = sample_pipe_snapshot(binding.procurement_request,row)
        except (ObjectDoesNotExist,StopIteration) as error:
            raise Conflict('打样采购原需求关联缺失，请先核对来源。') from error
    else:
        if line.bom_line_id:
            validate_purchase_description(line,line.bom_line)
        snapshot = pipe_source_snapshot(line.bom_line)
    line.calculation_snapshot = snapshot
    for key in ('raw_bar_length_m','suggested_bar_count','suggested_purchase_meters'):
        setattr(line,key,snapshot[key])
    line.required_quantity = Decimal(snapshot['suggested_purchase_meters'])
    line.source_quantity_text = str(line.required_quantity)
    line.quantity_parse_status = 'READY'
    validate_pipe_purchase_source(line)
    return ['required_quantity','source_quantity_text','quantity_parse_status']
