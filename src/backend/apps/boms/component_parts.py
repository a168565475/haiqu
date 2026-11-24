"""部位与裁片的组成关系；旧空类型行继续使用原有套数规则。"""
from rest_framework.exceptions import ValidationError

from apps.reference_data.models import ProductionUnit
from .material_flow_calculations import MaterialFlowValueError, positive_integer


COMPONENT_FIELDS = ("component_kind", "pieces_per_part", "parts_per_product")


def is_cut_piece(line):
    return getattr(line, "component_kind", "") == "CUT_PIECE"


def is_sewn_part(line):
    return getattr(line, "component_kind", "") == "SEWN_PART"


def required_component_quantity(line, order_quantity=None):
    """返回本订单应制造的部位数或裁片数，缺失配比不得猜成 1。"""
    if not (is_cut_piece(line) or is_sewn_part(line)):
        raise ValidationError({"component_kind": "该行不是部位或裁片。"})
    if order_quantity is None:
        order_quantity = line.section.bom.order_quantity
    part = line.parent_part if is_cut_piece(line) else line
    if part is None or not is_sewn_part(part):
        raise ValidationError({"parent_part_id": "裁片必须关联车缝部位。"})
    try:
        order = positive_integer(order_quantity, "order_quantity")
        parts = positive_integer(part.parts_per_product, "parts_per_product")
        quantity = positive_integer(order * parts, "required_parts")
        if is_cut_piece(line):
            pieces = positive_integer(line.pieces_per_part, "pieces_per_part")
            quantity = positive_integer(quantity * pieces, "required_pieces")
        return quantity
    except MaterialFlowValueError as error:
        raise ValidationError({error.field: str(error)}) from error


def is_cut_piece_source(source):
    if source is None or getattr(source, "component_kind", ""):
        return False
    title = source.section.title.strip()
    if source.section.section_type != "FABRIC" or title not in {"面料类", "辅料类"}:
        return False
    if source.material_catalog_id:
        snapshot = source.material_selection_snapshot or {}
        expected = "FABRIC" if title == "面料类" else "AUXILIARY"
        # 来源行由用户明确选定为待裁原料；辅料还包括 EVA/PEVA 等可裁材料，不能只准棉。
        return snapshot.get("processing_state") == "RAW" and snapshot.get("category_key") == expected
    return True


def validate_component_parts(lines, *, require_complete=False):
    current = {line.pk: line for line in lines}
    typed = [line for line in lines if getattr(line, "component_kind", "")]
    units = {line.unit.strip() for line in typed if line.unit.strip()}
    valid_units = set(ProductionUnit.objects.filter(unit_name__in=units, status="ACTIVE", archived_at__isnull=True)
                      .values_list("unit_name", flat=True)) if units else set()
    children = set()
    for line in lines:
        kind = getattr(line, "component_kind", "")
        parent_id = getattr(line, "parent_part_id", None)
        if not kind:
            if parent_id or line.pieces_per_part is not None or line.parts_per_product is not None:
                raise ValidationError({"sections": "历史用料不能填写部位组成字段，请明确选择部位或裁片。"})
            continue
        label = f"裁剪明细第 {line.line_number} 行"
        if kind not in {"CUT_PIECE", "SEWN_PART"} or line.section.title.strip() != "裁剪明细" or line.section.section_type != "FABRIC":
            raise ValidationError({"sections": "部位和裁片只能保存在裁剪明细分区。"})
        if line.unit and line.unit not in valid_units:
            raise ValidationError({"sections": f"{label}请选择有效的生产单位。"})
        if require_complete and not line.unit:
            raise ValidationError({"sections": f"{label}请选择单位。"})
        if any(getattr(line, field) is not None for field in ("cutting_pieces_per_set", "cutting_sets_per_product", "fabric_meters_per_piece", "fabric_meters_per_set")):
            raise ValidationError({"sections": f"{label}不能同时填写旧裁剪套数或耗米字段。"})
        if any((line.raw_values or {}).get(key) for key in (
                "source_inventory_material_id", "source_raw_material_id", "source_cutting_material_id",
                "source_packaging_material_id", "source_fabric_material_id", "source_accessory_material_id")):
            raise ValidationError({"sections": f"{label}请通过裁片来源行关联原料，不能直接挂接原料档案。"})
        from .component_catalog import is_component_catalog_reference, validate_component_catalog_reference
        reference = is_component_catalog_reference(line.material_selection_snapshot)
        if reference:
            validate_component_catalog_reference(line)
        if is_sewn_part(line):
            if parent_id or line.pieces_per_part is not None:
                raise ValidationError({"sections": f"{label}部位不能再隶属其他部位。"})
            if (line.material_catalog_id or line.material_selection_snapshot) and not reference:
                raise ValidationError({"sections": f"{label}部位只能引用品名，不能直接挂接原料档案或旧加工快照。"})
        else:
            if line.parts_per_product is not None:
                raise ValidationError({"sections": f"{label}每产品部位数只能填在父部位。"})
            if parent_id:
                parent = current.get(parent_id)
                if (parent is None or not is_sewn_part(parent) or parent.pk == line.pk
                        or parent.section.bom_id != line.section.bom_id or parent.section_id != line.section_id):
                    raise ValidationError({"sections": f"{label}须关联本 BOM 同一分区保留的车缝部位。"})
                line.parent_part = parent
                children.add(parent.pk)
            elif require_complete:
                raise ValidationError({"sections": f"{label}请选择所属部位。"})
            if require_complete:
                from .material_flow_bom import validate_cutting_specification
                validate_cutting_specification(line.specification, line.line_number)
        value = line.parts_per_product if is_sewn_part(line) else line.pieces_per_part
        if value is not None or require_complete:
            try:
                positive_integer(value, "parts_per_product" if is_sewn_part(line) else "pieces_per_part")
            except MaterialFlowValueError as error:
                raise ValidationError({"sections": f"{label}：{error}"}) from error
    if require_complete:
        for part in typed:
            if is_sewn_part(part) and part.pk not in children:
                raise ValidationError({"sections": f"部位“{part.part_name}”至少需要一条裁片明细。"})


def apply_component_quantities(line, order_quantity, *, require_complete=False):
    if not (is_cut_piece(line) or is_sewn_part(line)):
        return False
    if line.section.title.strip() != "裁剪明细" or line.section.section_type != "FABRIC":
        raise ValidationError({"sections": "部位和裁片只能保存在裁剪明细分区。"})
    part = line.parent_part if is_cut_piece(line) else line
    complete = part is not None and part.parts_per_product is not None and (not is_cut_piece(line) or line.pieces_per_part is not None)
    quantity = required_component_quantity(line, order_quantity) if complete or require_complete else None
    line.total_consumption = str(quantity) if quantity is not None else ""
    line.unit_consumption = str(line.parts_per_product or "") if is_sewn_part(line) else str(line.pieces_per_part or "")
    line.cut_piece_quantity = str(line.pieces_per_part or "") if is_cut_piece(line) else ""
    line.total_purchase_quantity = ""
    return True


def _used_component_identities(bom, identities):
    from django.db.models import Q
    from .models import BomLine
    # 同产品复制出的 BOM 沿用组成编号，业务记录也可能仍引用上一版 BOM 行。
    return set(BomLine.objects.filter(section__bom__product_line_id=bom.product_line_id,
        component_identity__in=identities).filter(
            Q(internal_receipt_lines__isnull=False) | Q(public_stock_movements__isnull=False)
            | Q(semi_finished_stock_balances__isnull=False) | Q(outsourcing_processing_items__isnull=False)
            | Q(tube_outsourcing_lines__isnull=False) | Q(outsourcing_inputs__isnull=False)
            | Q(semi_finished_requirements__internal_issued_quantity__gt=0)
            | Q(semi_finished_requirements__issue_lines__isnull=False)
        ).values_list("component_identity", flat=True).distinct())


def _component_structure(line, lines):
    from apps.inventory.part_flow_identity import _piece_properties
    from .component_catalog import is_component_catalog_reference
    snapshot = line.material_selection_snapshot or {}
    catalog = (str(line.material_catalog_id or ""),
               snapshot.get("attributes") if is_component_catalog_reference(snapshot) else None,
               snapshot.get("identity_attributes_version") if is_component_catalog_reference(snapshot) else None)
    if is_cut_piece(line):
        source = line.fabric_source_line
        parent = line.parent_part
        return (line.component_kind, catalog, line.unit, _piece_properties(line), line.pieces_per_part,
                source.component_identity if source else None, parent.component_identity if parent else None)
    children = sorted((child for child in lines if child.parent_part_id == line.pk), key=lambda child: str(child.component_identity))
    source = getattr(line, "fabric_source_line", None)
    return (line.component_kind, catalog, line.part_name, line.specification, line.unit,
            source.component_identity if source else None,
            [(child.component_identity, _component_structure(child, lines)) for child in children])


def validate_used_component_structure(bom, existing_lines, planned_lines):
    """已发生流转的实物及所属组成保持不变；每产品目标数可独立调整。"""
    existing_lines, planned_lines = list(existing_lines), list(planned_lines)
    old = {line.component_identity: line for line in existing_lines if is_cut_piece(line) or is_sewn_part(line)}
    has_new_structure = any(is_cut_piece(line) or is_sewn_part(line) for line in planned_lines)
    legacy = {line.component_identity: line for line in existing_lines
              if not line.component_kind and line.section.title.strip() == '裁剪明细'} if has_new_structure else {}
    if not old and not legacy:
        return
    used = _used_component_identities(bom, set(old) | set(legacy))
    if not used:
        return
    current = {line.component_identity: line for line in planned_lines}
    for identity, previous in legacy.items():
        line = current.get(identity)
        if identity in used and (line is None or is_cut_piece(line) or is_sewn_part(line)):
            raise ValidationError({'sections': f'“{previous.part_name}”已有历史流转记录，不能原地改成新部位或裁片，也不能删除后用新组成替代；请保留历史行的原有身份。'})
    # 已用裁片的父部位也冻结组成，避免改变每部位片数后混用旧领料/完工口径。
    used.update(line.parent_part.component_identity for identity, line in old.items()
                if identity in used and is_cut_piece(line) and line.parent_part_id)
    for identity in used:
        previous = old.get(identity)
        if previous is None:
            continue
        line = current.get(identity)
        if (line is None or line.component_kind != previous.component_kind
                or _component_structure(previous, existing_lines) != _component_structure(line, planned_lines)):
            raise ValidationError({"sections": f"“{previous.part_name}”已有入库或外发记录，不能删除或修改部位、裁片组成、原料、规格及单位；目标数量仍可调整。"})
