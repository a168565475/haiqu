"""管材单件面积与重量计算；只解释白名单算术节点，不执行用户代码。"""

import ast
import re
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext

from rest_framework.exceptions import ValidationError


TUBE_FORMULA_GROUPS = {
    "ROUND": {"label": "圆管", "shapes": ("圆管",), "variables": ("直径", "壁厚", "管材长度")},
    "RECTANGULAR": {"label": "方管 / 矩形管", "shapes": ("方管", "矩形管"), "variables": ("截面长", "截面宽", "壁厚", "管材长度")},
    "OVAL": {"label": "椭圆管 / 扁圆管", "shapes": ("椭圆管", "扁圆管"), "variables": ("截面长", "截面宽", "壁厚", "管材长度")},
}

DEFAULT_TUBE_FORMULAS = {
    "ROUND": {
        "group_key": "ROUND",
        "area_expression": "直径*3.14*管材长度/1000000",
        "weight_expression": "(直径-壁厚)*壁厚*3.14*7.854*管材长度/1000000",
    },
    "RECTANGULAR": {
        "group_key": "RECTANGULAR",
        "area_expression": "(截面长+截面宽)*2*管材长度/1000000",
        "weight_expression": "((截面长+截面宽)*2/3.14-壁厚)*壁厚*3.14*7.854*管材长度/1000000",
    },
    "OVAL": {
        "group_key": "OVAL",
        "area_expression": "截面长/2*截面宽/2*3.14*管材长度/1000000",
        "weight_expression": "(截面长*截面宽-(截面长-2*壁厚)*(截面宽-2*壁厚))/4*3.14*7.854*管材长度/1000000",
    },
}

MAX_EXPRESSION_LENGTH = 500
MAX_AST_NODES = 100
MAX_EXPRESSION_DEPTH = 20
MAX_VALUE = Decimal("1e24")
DECIMAL_PATTERN = re.compile(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)\Z")
EXPRESSION_PATTERN = re.compile(r"[0-9.+\-*/()\s直径截面长宽壁厚管材度]+\Z")


def get_tube_formula_group(shape):
    if not isinstance(shape, str):
        raise ValidationError({"tube_shape": "请选择支持计算的管材形状。"})
    shape = shape.strip()
    for key, group in TUBE_FORMULA_GROUPS.items():
        if any(shape in (name, name.removesuffix("管")) for name in group["shapes"]):
            return key
    raise ValidationError({"tube_shape": "该管材形状尚未配置计算公式。"})


def _positive_decimal(value, field):
    text = str(value).strip() if value is not None else ""
    text = re.sub(r"(?:mm|毫米)$", "", text, flags=re.IGNORECASE).strip()
    if len(text) > 50 or not DECIMAL_PATTERN.fullmatch(text):
        raise ValidationError({field: "请输入有效的正数，单位为毫米。"})
    number = Decimal(text)
    if not number.is_finite() or number <= 0 or number > Decimal("1e12"):
        raise ValidationError({field: "尺寸必须大于 0，且不能超过 1000000000000 毫米。"})
    return number


def parse_tube_dimensions(*, shape, specification, thickness, length_mm):
    """只检查几何输入，可用于确认旧 BOM，不读取最新公式。"""
    group_key = get_tube_formula_group(shape)
    text = str(specification).strip() if specification is not None else ""
    if len(text) > 100:
        raise ValidationError({"tube_diameter": "管材规格过长。"})
    text = re.sub(r"^[φø]", "", text, flags=re.IGNORECASE).strip()
    parts = re.split(r"[×xX*]", text)
    if group_key == "RECTANGULAR" and len(parts) == 1:
        parts *= 2
    expected_count = 1 if group_key == "ROUND" else 2
    if len(parts) != expected_count:
        message = "圆管规格应填写一个直径。" if group_key == "ROUND" else "管材规格应填写截面长×截面宽。"
        raise ValidationError({"tube_diameter": message})
    sizes = [_positive_decimal(part, "tube_diameter") for part in parts]
    wall = _positive_decimal(thickness, "tube_thickness")
    length = _positive_decimal(length_mm, "cutting_length_mm")
    if wall * 2 >= min(sizes):
        raise ValidationError({"tube_thickness": "壁厚的两倍必须小于管材的最小外部尺寸。"})
    dimensions = {"壁厚": wall, "管材长度": length}
    if group_key == "ROUND":
        dimensions["直径"] = sizes[0]
    else:
        dimensions.update({"截面长": sizes[0], "截面宽": sizes[1]})
    return dimensions


def _parse_expression(expression, group_key):
    if group_key not in TUBE_FORMULA_GROUPS:
        raise ValidationError("管材公式组无效。")
    if not isinstance(expression, str) or not 0 < len(expression.strip()) <= MAX_EXPRESSION_LENGTH:
        raise ValidationError("公式必须是 1 至 500 个字符。")
    expression = expression.strip().translate(str.maketrans({"×": "*", "÷": "/", "（": "(", "）": ")"}))
    if not EXPRESSION_PATTERN.fullmatch(expression):
        raise ValidationError("公式只能使用规定的中文变量、数字、括号及加减乘除。")
    depth = 0
    for character in expression:
        depth += (character == "(") - (character == ")")
        if depth > MAX_EXPRESSION_DEPTH:
            raise ValidationError("公式括号嵌套过深。")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        raise ValidationError("公式语法有误，请检查括号和运算符。") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise ValidationError("公式过于复杂，请减少运算步骤。")
    variables = TUBE_FORMULA_GROUPS[group_key]["variables"]

    def validate_node(node, level=0):
        if level > MAX_EXPRESSION_DEPTH:
            raise ValidationError("公式运算嵌套过深。")
        if isinstance(node, ast.Constant):
            literal = ast.get_source_segment(expression, node)
            if not literal or not DECIMAL_PATTERN.fullmatch(literal) or len(literal) > 50:
                raise ValidationError("公式数字必须使用普通十进制格式。")
            if Decimal(literal) > MAX_VALUE:
                raise ValidationError("公式中的数字过大。")
        elif isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValidationError(f"此形状可用变量：{'、'.join(variables)}。")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            validate_node(node.left, level + 1)
            validate_node(node.right, level + 1)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            validate_node(node.operand, level + 1)
        else:
            raise ValidationError("公式只支持加、减、乘、除和括号。")

    validate_node(tree.body)
    return expression, tree.body


def _evaluate_expression(expression, tree, dimensions):
    def evaluate(node):
        if isinstance(node, ast.Constant):
            value = Decimal(ast.get_source_segment(expression, node))
        elif isinstance(node, ast.Name):
            value = dimensions[node.id]
        elif isinstance(node, ast.UnaryOp):
            value = evaluate(node.operand)
            if isinstance(node.op, ast.USub):
                value = -value
        else:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            else:
                if right == 0:
                    raise ValidationError("公式计算出现除以零，请检查公式与尺寸。")
                value = left / right
        if not value.is_finite() or abs(value) > MAX_VALUE:
            raise ValidationError("公式计算结果超出允许范围。")
        return value

    try:
        with localcontext() as context:
            context.prec = 40
            value = evaluate(tree)
            if value < 0:
                raise ValidationError("公式计算结果不能为负数。")
            return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except DecimalException:
        raise ValidationError("公式数值无法计算，请检查公式与尺寸。") from None


def validate_tube_expression(expression, *, group_key):
    expression, tree = _parse_expression(expression, group_key)
    # 保存时拦截恒定除零、负值等明显错误；实际尺寸仍在每次计算时校验。
    sample = {"直径": Decimal("30"), "截面长": Decimal("30"), "截面宽": Decimal("20"),
              "壁厚": Decimal("1"), "管材长度": Decimal("1000")}
    _evaluate_expression(expression, tree, sample)
    return expression


def calculate_tube_metrics(*, shape, specification, thickness, length_mm, formula=None):
    group_key = get_tube_formula_group(shape)
    dimensions = parse_tube_dimensions(shape=shape, specification=specification, thickness=thickness, length_mm=length_mm)
    if formula is None:
        from .models import TubeCalculationFormula

        try:
            record = TubeCalculationFormula.objects.get(group_key=group_key)
        except TubeCalculationFormula.DoesNotExist:
            raise ValidationError({"tube_shape": "管材计算公式缺失，请先完成生产维护配置。"}) from None
        formula = {"group_key": record.group_key, "area_expression": record.area_expression,
                   "weight_expression": record.weight_expression, "updated_at": record.updated_at.isoformat()}
    if not isinstance(formula, dict) or formula.get("group_key") != group_key:
        raise ValidationError({"formula": "公式快照与管材形状不匹配。"})
    if not isinstance(formula.get("updated_at"), str) or not formula["updated_at"]:
        raise ValidationError({"formula": "公式快照缺少版本时间。"})
    results = {}
    snapshot = {"group_key": group_key, "updated_at": formula["updated_at"]}
    for field, result_field in (("area_expression", "coating_unit_area_sqm"), ("weight_expression", "purchase_unit_weight_kg")):
        try:
            expression, tree = _parse_expression(formula.get(field), group_key)
            results[result_field] = format(_evaluate_expression(expression, tree, dimensions), ".4f")
        except ValidationError as error:
            raise ValidationError({field: error.detail}) from error
        snapshot[field] = expression
    return {**results, "formula_snapshot": snapshot}
