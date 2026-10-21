"""材料流程共用的纯计算；不访问数据库，不改变调用方的 Decimal 精度。"""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext

CUTTING_USAGE_FIELDS = ("cutting_pieces_per_set", "fabric_meters_per_piece", "cutting_sets_per_product")
CUTTING_QUANTITY_FIELDS = ("cutting_pieces_per_set", "cutting_sets_per_product")


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


def pipe_plan(*, cutting_length_mm, pieces_per_product, pieces_per_bar, order_quantity, calculation_version=3):
    if type(calculation_version) is not int or calculation_version not in (2, 3):
        raise MaterialFlowValueError("pipe_plan_version", "管材计算版本无效。")
    length = positive_integer(cutting_length_mm, "cutting_length_mm")
    consumption = positive_integer(pieces_per_product, "pieces_per_product")
    cuts = positive_integer(pieces_per_bar, "pieces_per_bar")
    order = positive_integer(order_quantity, "order_quantity")
    with localcontext() as context:
        context.prec = 64
        meters = ((Decimal(length) * cuts + 50) / 1000).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        meters = decimal_quantity(meters, "raw_bar_length_m", places=2)
        demand = positive_integer(order * consumption, "demand_pieces")
        # 整数分数向上取整，避免 1/3 等无限小数的中间舍入。
        # 旧版本保留已确认的 1% 采购余量；新版本只按净需求向上取整根数。
        factor = 101 if calculation_version == 2 else 100
        bars = positive_integer((demand * factor + cuts * 100 - 1) // (cuts * 100), "suggested_bar_count")
        allowance = positive_integer(bars * cuts, "allowance_pieces")
        total = decimal_quantity(bars * meters, "suggested_purchase_meters", places=2, max_digits=22)
    # 数量规则单独标记；结构版本不变，旧快照不新增键以保留来源版本摘要。
    return {
        "schema_version": 2,
        **({"calculation_version": 3} if calculation_version == 3 else {}),
        "cutting_length_mm": length,
        "pieces_per_product": consumption,
        "pieces_per_bar": cuts,
        "order_quantity": order,
        "demand_pieces": demand,
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
