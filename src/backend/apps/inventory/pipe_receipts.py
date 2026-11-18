"""根米收货和品质确认；不把未质检数量写成可用余额。"""
from apps.boms.material_flow_calculations import pipe_meters_text
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from rest_framework.exceptions import ValidationError
from apps.core.api.exceptions import Conflict
from apps.procurement.pipe_purchase import pipe_meters
from apps.products.models import RawMaterialInformation
from .hardware_receipts import hardware_receipt_values, is_hardware_weight, quality_hardware_quantities


def receipt_pipe_values(item, purchase_line=None, material=None):
    if purchase_line is not None:
        if is_hardware_weight(purchase_line):
            from apps.procurement.material_receipt_identity import resolve_purchase_material
            material = resolve_purchase_material(purchase_line)
            if material is None:
                raise ValidationError({"items": "五金采购缺少可验证的原料身份。"})
            return {"raw_material_information": material,
                    **hardware_receipt_values(purchase_line=purchase_line, item=item, piece_unit=material.unit.unit_name)}
        if purchase_line.section_type_snapshot != 'PROFILE':
            if item.get('received_bar_count') is not None or item.get('raw_bar_length_m') is not None:
                raise ValidationError({'items': '非管材不能提交管材根数。'})
            if purchase_line.purchase_order.source_type == 'SAMPLE':
                snapshot = purchase_line.calculation_snapshot
                material = RawMaterialInformation.objects.select_related('unit', 'category').filter(
                    pk=snapshot.get('raw_material_id'), item_type='MATERIAL', archived_at__isnull=True,
                    unit_id=snapshot.get('unit_id'), unit__status='ACTIVE', unit__archived_at__isnull=True,
                    category__status='ACTIVE', category__archived_at__isnull=True,
                ).exclude(category__category_name='管材').first()
                if material is None or purchase_line.source_unit_text not in {material.unit.unit_name, material.unit.unit_code}:
                    raise ValidationError({'items': '打样采购缺少有效原材料或单位来源，请重新核对采购来源。'})
                return {'raw_material_information': material, 'calculation_snapshot': snapshot}
            return {}
        if not purchase_line.raw_bar_length_m or not purchase_line.calculation_snapshot:
            raise Conflict('旧口径管材采购不能入库，请先补齐并重新确认根米采购。')
        length = purchase_line.raw_bar_length_m
        if item.get('raw_bar_length_m') is not None and item['raw_bar_length_m'] != length:
            raise ValidationError({'raw_bar_length_m': '实到单根长度与采购定制长度不同，不能按原长度入库。'})
        snapshot = purchase_line.calculation_snapshot
        material = RawMaterialInformation.objects.select_related('unit', 'category').filter(pk=snapshot.get('raw_material_id')).first()
    else:
        is_pipe = material is not None and material.item_type == 'MATERIAL' and material.category.category_name == '管材'
        if not is_pipe:
            if item.get('received_bar_count') is not None or item.get('raw_bar_length_m') is not None:
                raise ValidationError({'items': '非管材不能提交管材根数或长度。'})
            return {}
        length = item.get('raw_bar_length_m')
        snapshot = {'schema_version': 2, 'source': 'MANUAL', 'raw_material_id': str(material.pk)}
    if (material is None or material.archived_at or material.item_type != 'MATERIAL'
            or material.category.category_name != '管材' or material.unit.unit_name != '根'
            or material.unit.status != 'ACTIVE' or material.unit.archived_at
            or material.category.status != 'ACTIVE' or material.category.archived_at):
        raise ValidationError({'items': '管材入库缺少有效的根制原料身份。'})
    snapshot = snapshot or {}
    if purchase_line is None:
        try:
            weight = Decimal(str(item.get("received_weight_kg")))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValidationError({"received_weight_kg": "请填写管材实际入库重量（KG）。"}) from error
        if not weight.is_finite() or weight <= 0:
            raise ValidationError({"received_weight_kg": "管材实际入库重量必须大于0。"})
        if weight > Decimal("99999999999999.9999") or weight.as_tuple().exponent < -4:
            raise ValidationError({"received_weight_kg": "管材实际入库重量超出范围或超过4位小数。"})
        roots, meters = pipe_meters(item.get("received_bar_count"), length, field="received_bar_count")
        item["received_quantity"] = meters
        return {"measurement_kind": "PIPE", "raw_bar_length_m": length, "bar_weight_kg": None,
            "received_bar_count": roots, "accepted_bar_count": roots, "return_bar_count": 0,
            "received_weight_kg": weight, "accepted_weight_kg": weight, "return_weight_kg": Decimal("0"),
            "calculation_snapshot": {**snapshot, "measurement_unit": "kg", "received_bar_count": roots,
                "received_meters": pipe_meters_text(meters), "received_weight_kg": format(weight, ".4f")},
            "raw_material_information": material}
    weight_text = snapshot.get("raw_bar_weight_kg") or getattr(purchase_line, "raw_bar_weight_kg", None)
    weight_mode = str(getattr(purchase_line, "source_unit_text", "") or "") in {"KG", "kg", "千克"}
    if weight_mode:
        try:
            weight = Decimal(str(item.get("received_weight_kg", item.get("received_quantity"))))
            bar_weight = Decimal(str(weight_text))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValidationError({"received_weight_kg": "管材采购重量或每根标准重量无效。"}) from error
        if not weight.is_finite() or weight <= 0 or not bar_weight.is_finite() or bar_weight <= 0:
            raise ValidationError({"received_weight_kg": "管材采购重量和每根标准重量必须大于 0。"})
        roots = item.get("received_bar_count")
        if roots is None:
            roots = int((weight / bar_weight).to_integral_value(rounding=ROUND_CEILING))
        roots, meters = pipe_meters(roots, length, field="received_bar_count")
        item["received_weight_kg"] = weight
        item["received_quantity"] = meters
        return {'measurement_kind': 'PIPE', 'raw_bar_length_m': length, 'bar_weight_kg': bar_weight,
                'received_bar_count': roots, 'accepted_bar_count': roots, 'return_bar_count': 0,
                'received_weight_kg': weight, 'accepted_weight_kg': weight, 'return_weight_kg': Decimal("0"),
                'calculation_snapshot': {**snapshot, 'received_bar_count': roots,
                                         'received_meters': pipe_meters_text(meters),
                                         'received_weight_kg': format(weight, '.4f')},
                'raw_material_information': material}
    roots, meters = pipe_meters(item.get('received_bar_count'), length, field='received_bar_count')
    item['received_quantity'] = meters
    return {'measurement_kind': 'PIPE', 'raw_bar_length_m': length, 'received_bar_count': roots,
            'accepted_bar_count': roots, 'return_bar_count': 0,
            'received_weight_kg': None, 'accepted_weight_kg': None, 'return_weight_kg': None,
            'calculation_snapshot': {**snapshot, 'received_bar_count': roots, 'received_meters': pipe_meters_text(meters)},
            'raw_material_information': material}


def quality_pipe_quantities(line, item):
    if is_hardware_weight(line):
        return quality_hardware_quantities(line, item)
    if line.measurement_kind != 'PIPE':
        if item.get('return_bar_count') is not None:
            raise ValidationError({'items': '非管材不能按根退货。'})
        if item.get('return_quantity') is None:
            raise ValidationError({'return_quantity': '请填写不良退货数量。'})
        return item['return_quantity']
    weight_mode = line.source_unit_text_snapshot in {"KG", "kg", "千克", "公斤"}
    if weight_mode:
        try:
            weight = Decimal(str(item.get("return_weight_kg", item.get("return_quantity", "0"))))
            bar_weight = Decimal(str(line.bar_weight_kg))
            received_weight = Decimal(str(line.received_weight_kg))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValidationError({"return_weight_kg": "退货重量或每根标准重量无效。"}) from error
        if not weight.is_finite() or weight < 0 or not bar_weight.is_finite() or bar_weight <= 0:
            raise ValidationError({"return_weight_kg": "退货重量不能为负且每根标准重量必须大于 0。"})
        if not received_weight.is_finite() or received_weight <= 0:
            raise ValidationError({"return_weight_kg": "到货重量缺失或无效，请核对原入库记录。"})
        if weight > received_weight:
            raise ValidationError({"return_weight_kg": "退货重量不能超过到货重量。"})
        roots = item.get("return_bar_count")
        automatic_roots = roots is None
        if roots is None:
            if weight == 0:
                roots = 0
            elif weight == received_weight:
                roots = line.received_bar_count
            else:
                # 按剩余重量折算合格根数，避免部分退货将仍有重量的库存扣成零根。
                accepted_roots = min(line.received_bar_count,
                    int(((received_weight - weight) / bar_weight).to_integral_value(rounding=ROUND_CEILING)))
                roots = line.received_bar_count - accepted_roots
        roots, meters = pipe_meters(roots, line.raw_bar_length_m, field="return_bar_count", allow_zero=True)
    else:
        roots, meters = pipe_meters(item.get('return_bar_count'), line.raw_bar_length_m, field='return_bar_count', allow_zero=True)
    if roots > line.received_bar_count:
        raise ValidationError({'return_bar_count': '退货根数不能超过到货根数。'})
    if weight_mode:
        accepted_weight = received_weight - weight
        accepted_roots = line.received_bar_count - roots
        if not automatic_roots and (weight == 0) != (roots == 0):
            raise ValidationError({"return_bar_count": "退货重量和退货根数的零值不一致，请核对真实退货根数。"})
        if (accepted_weight == 0) != (accepted_roots == 0):
            raise ValidationError({"return_bar_count": "合格重量和合格根数不一致：还有重量时须保留合格根数，全退时须退回全部实收根数，请核对真实退货根数。"})
        line.return_weight_kg = weight
        line.accepted_weight_kg = accepted_weight
    line.return_bar_count = roots
    line.accepted_bar_count = line.received_bar_count - roots
    return meters
