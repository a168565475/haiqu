"""材料流程共用的纯计算；不访问数据库，不改变调用方的 Decimal 精度。"""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext

CUTTING_USAGE_FIELDS = ("cutting_pieces_per_set", "fabric_meters_per_piece", "cutting_sets_per_product")
CUTTING_QUANTITY_FIELDS = ("cutting_pieces_per_set", "cutting_sets_per_product")
PIPE_PURCHASE_ALLOWANCE_RULES = ("NONE", "PLUS_5", "PLUS_8", "PERCENT_0_5", "PERCENT_1")
PIPE_PURCHASE_ALLOWANCE_MODES = ("AUTO", "MANUAL")


class MaterialFlowValueError(ValueError):
    def __init__(self, field, detail, code="MATERIAL_FLOW_VALUE_INVALID"):
        self.field = field
        self.code = code
        super().__init__(detail)


def decimal_quantity(value, field, *, places=4, max_digits=18, allow_zero=False):
    if isinstance(value, (bool, float)) or value is None:
        raise MaterialFlowValueError(field, "数量必须使用有效的十进制数字字符串。")
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise MaterialFlowValueError(field, "数量格式无效。") from None
    if not number.is_finite() or number < 0 or (not allow_zero and number == 0):
        raise MaterialFlowValueError(field, "数量必须是有效的正数。")
    if number >= Decimal(10) ** (max_digits - places):
        raise MaterialFlowValueError(field, "数量超出字段范围。")
    with localcontext() as context:
        context.prec = 64
        quant = Decimal(1).scaleb(-places)
        if number != number.quantize(quant):
            raise MaterialFlowValueError(field, f"数量最多保留 {places} 位小数。")
        return number.quantize(quant)


def positive_integer(value, field, *, allow_zero=False):
    return int(decimal_quantity(value, field, places=0, max_digits=14, allow_zero=allow_zero))


def default_pipe_purchase_allowance_rule(base_bar_count):
    """按基础采购根数返回默认余量选项；边界归入前一档。"""
    roots = positive_integer(base_bar_count, "base_purchase_bar_count")
    if roots <= 500:
        return "PLUS_5"
    if roots <= 1000:
        return "PLUS_8"
    return "PERCENT_1"


def pipe_purchase_allowance_roots(base_bar_count, rule):
    roots = positive_integer(base_bar_count, "base_purchase_bar_count")
    if rule not in PIPE_PURCHASE_ALLOWANCE_RULES:
        raise MaterialFlowValueError("purchase_allowance_rule", "采购余量选项无效。")
    if rule == "NONE":
        return 0
    if rule == "PLUS_5":
        return 5
    if rule == "PLUS_8":
        return 8
    percent = Decimal("0.5") if rule == "PERCENT_0_5" else Decimal("1")
    with localcontext() as context:
        context.prec = 64
        return positive_integer(
            (Decimal(roots) * percent / Decimal("100")).to_integral_value(rounding=ROUND_CEILING),
            "purchase_allowance_bar_count",
            allow_zero=True,
        )


def packaging_quantity(*, units_per_box, order_quantity):
    box = positive_integer(units_per_box, "units_per_box")
    order = decimal_quantity(order_quantity, "order_quantity", allow_zero=True)
    with localcontext() as context:
        context.prec = 64
        quantity = (order / box).to_integral_value(rounding=ROUND_CEILING)
    return positive_integer(quantity, "packaging_quantity", allow_zero=True)


def cutting_quantity_plan(*, cutting_pieces_per_set=None, cutting_sets_per_product=None, order_quantity):
    """裁片只计算套数与片数；两项全空保留旧记录，不从历史耗米猜数量。"""
    values = (cutting_pieces_per_set, cutting_sets_per_product)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise MaterialFlowValueError("cutting_quantity", "每套片数和每成品套数必须同时填写。")
    pieces = positive_integer(cutting_pieces_per_set, "cutting_pieces_per_set")
    sets = positive_integer(cutting_sets_per_product, "cutting_sets_per_product")
    order = positive_integer(order_quantity, "order_quantity")
    required_sets = positive_integer(order * sets, "cutting_required_sets")
    required_pieces = positive_integer(required_sets * pieces, "cutting_required_pieces")
    return {
        "cutting_pieces_per_set": pieces,
        "cutting_sets_per_product": sets,
        "required_sets": required_sets,
        "required_pieces": required_pieces,
    }


def cutting_usage_plan(*, cutting_pieces_per_set=None, fabric_meters_per_piece=None,
                       cutting_sets_per_product=None, order_quantity):
    """三字段全空保留旧口径；新口径分别计算套数、片数与米数，不猜历史值。"""
    values = (cutting_pieces_per_set, fabric_meters_per_piece, cutting_sets_per_product)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise MaterialFlowValueError("cutting_usage", "每套片数、每片耗米和每成品套数必须同时填写。")
    pieces = positive_integer(cutting_pieces_per_set, "cutting_pieces_per_set")
    meters = decimal_quantity(fabric_meters_per_piece, "fabric_meters_per_piece")
    sets = positive_integer(cutting_sets_per_product, "cutting_sets_per_product")
    order = positive_integer(order_quantity, "order_quantity")
    with localcontext() as context:
        context.prec = 64
        per_set = decimal_quantity(pieces * meters, "fabric_meters_per_set")
        required_sets = positive_integer(order * sets, "cutting_required_sets")
        required_pieces = positive_integer(required_sets * pieces, "cutting_required_pieces")
        required_meters = decimal_quantity(required_sets * per_set, "cutting_required_meters")
    return {
        "cutting_pieces_per_set": pieces,
        "fabric_meters_per_piece": format(meters, ".4f"),
        "cutting_sets_per_product": sets,
        "fabric_meters_per_set": format(per_set, ".4f"),
        "required_sets": required_sets,
        "required_pieces": required_pieces,
        "required_meters": format(required_meters, ".4f"),
    }


def pipe_plan(*, cutting_length_mm, pieces_per_product, pieces_per_bar, order_quantity, calculation_version=3,
              source_purchase_allowance_percent=None, source_raw_bar_length_m=None,
              purchase_allowance_rule=None, purchase_allowance_mode=None):
    if type(calculation_version) is not int or calculation_version not in (2, 3, 4):
        raise MaterialFlowValueError("pipe_plan_version", "管材计算版本无效。")
    uses_allowance = calculation_version == 4 or purchase_allowance_mode not in (None, "")
    allowance_values = {}
    if uses_allowance:
        purchase_allowance_mode = purchase_allowance_mode or "AUTO"
        if purchase_allowance_mode not in PIPE_PURCHASE_ALLOWANCE_MODES:
            raise MaterialFlowValueError("purchase_allowance_mode", "采购余量模式无效。")
        if purchase_allowance_rule not in (None, "") and purchase_allowance_rule not in PIPE_PURCHASE_ALLOWANCE_RULES:
            raise MaterialFlowValueError("purchase_allowance_rule", "采购余量选项无效。")
        if purchase_allowance_mode == "MANUAL" and purchase_allowance_rule not in PIPE_PURCHASE_ALLOWANCE_RULES:
            raise MaterialFlowValueError("purchase_allowance_rule", "手动采购余量必须选择有效选项。")
        calculation_version = 4
    elif purchase_allowance_rule not in (None, ""):
        raise MaterialFlowValueError("purchase_allowance_mode", "选择采购余量时必须同时指定模式。")
    length = positive_integer(cutting_length_mm, "cutting_length_mm")
    consumption = positive_integer(pieces_per_product, "pieces_per_product")
    cuts = positive_integer(pieces_per_bar, "pieces_per_bar")
    order = positive_integer(order_quantity, "order_quantity")
    with localcontext() as context:
        context.prec = 64
        meters = ((Decimal(length) * cuts + 50) / 1000).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        meters = decimal_quantity(meters, "raw_bar_length_m", places=2)
        source_values = {}
        if source_raw_bar_length_m not in (None, ""):
            meters = decimal_quantity(source_raw_bar_length_m, "source_raw_bar_length_m", places=2)
            if meters * 1000 < length * cuts:
                raise MaterialFlowValueError("source_raw_bar_length_m", "原表长料长度不足以切出当前每根支数，请核对切割长度和长料长度。")
            source_values["source_raw_bar_length_m"] = format(meters, ".2f")
        demand = positive_integer(order * consumption, "demand_pieces")
        base_bars = positive_integer(
            (Decimal(demand) / cuts).to_integral_value(rounding=ROUND_CEILING),
            "base_purchase_bar_count",
        )
        factor = 100
        if source_purchase_allowance_percent not in (None, ""):
            percent = decimal_quantity(source_purchase_allowance_percent, "source_purchase_allowance_percent", allow_zero=True)
            if percent > 100:
                raise MaterialFlowValueError("source_purchase_allowance_percent", "原表采购余量百分比不能超过 100。")
            factor = Decimal("100") + percent
            source_values["source_purchase_allowance_percent"] = format(percent, "f")
        elif calculation_version == 2:
            factor = 101
        if uses_allowance:
            allowance_rule = (default_pipe_purchase_allowance_rule(base_bars)
                              if purchase_allowance_mode == "AUTO" else purchase_allowance_rule)
            allowance_bars = pipe_purchase_allowance_roots(base_bars, allowance_rule)
            bars = positive_integer(base_bars + allowance_bars, "suggested_bar_count")
            allowance_values = {
                "base_purchase_bar_count": base_bars,
                "purchase_allowance_rule": allowance_rule,
                "purchase_allowance_mode": purchase_allowance_mode,
                "purchase_allowance_bar_count": allowance_bars,
            }
        else:
            bars = positive_integer((Decimal(demand) * factor / (cuts * 100)).to_integral_value(rounding=ROUND_CEILING), "suggested_bar_count")
        allowance = positive_integer(bars * cuts, "allowance_pieces")
        total = decimal_quantity(bars * meters, "suggested_purchase_meters", places=2, max_digits=22)
    # 数量规则单独标记；结构版本不变，旧快照不新增键以保留来源版本摘要。
    return {
        "schema_version": 2,
        **({"calculation_version": calculation_version} if calculation_version in (3, 4) else {}),
        **source_values,
        "cutting_length_mm": length,
        "pieces_per_product": consumption,
        "pieces_per_bar": cuts,
        "order_quantity": order,
        "demand_pieces": demand,
        **allowance_values,
        "raw_bar_length_m": format(meters, ".2f"),
        "suggested_bar_count": bars,
        "suggested_purchase_meters": format(total, ".2f"),
        "allowance_pieces": allowance,
    }


def pipe_plan_for_line(line, *, order_quantity=None):
    """按已保存 BOM 的版本复算；未标记的旧行保留原快照及来源版本摘要。"""
    return pipe_plan(
        cutting_length_mm=line.cutting_length_mm,
        pieces_per_product=line.pieces_per_product,
        pieces_per_bar=line.pieces_per_bar,
        order_quantity=line.section.bom.order_quantity if order_quantity is None else order_quantity,
        calculation_version=(line.raw_values or {}).get("pipe_plan_version", 2),
        source_purchase_allowance_percent=(line.raw_values or {}).get("source_purchase_allowance_percent"),
        source_raw_bar_length_m=(line.raw_values or {}).get("source_raw_bar_length_m"),
        purchase_allowance_rule=(line.raw_values or {}).get("purchase_allowance_rule"),
        purchase_allowance_mode=(line.raw_values or {}).get("purchase_allowance_mode"),
    )


def pipe_issue(*, requested_pieces, pieces_per_bar, raw_bar_length_m):
    pieces = positive_integer(requested_pieces, "requested_pieces")
    cuts = positive_integer(pieces_per_bar, "pieces_per_bar")
    length = decimal_quantity(raw_bar_length_m, "raw_bar_length_m", places=2)
    if pieces % cuts:
        raise MaterialFlowValueError("requested_pieces", f"申请支数必须是 {cuts} 的整数倍。", "PIPE_WHOLE_BAR_REQUIRED")
    bars = pieces // cuts
    with localcontext() as context:
        context.prec = 64
        meters = decimal_quantity(bars * length, "issued_meters", places=2, max_digits=22)
    return {"requested_pieces": pieces, "bar_count": bars, "meters": format(meters, ".2f")}


def fabric_output(*, issued_meters, meters_per_set):
    meters = decimal_quantity(issued_meters, "issued_meters")
    consumption = decimal_quantity(meters_per_set, "meters_per_set")
    with localcontext() as context:
        context.prec = 64
        sets = positive_integer((meters / consumption).to_integral_value(rounding=ROUND_FLOOR), "expected_sets", allow_zero=True)
        remainder = meters - sets * consumption
    return {"expected_sets": sets, "remainder_meters": format(remainder, ".4f")}
