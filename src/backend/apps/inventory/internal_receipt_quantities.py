"""厂内入库数量核算：订单净需求与实际投入共同封顶。

本模块只做精确计算，不访问数据库或修改库存。调用服务必须在事务锁内从
服务端读取已出库投入、既有产出及外发占用，不能信任前端传来的这些数值。
source_key 是订单内的材料投入汇总键，不是采购批次或入库批次。
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from types import MappingProxyType
from collections.abc import Mapping


MAX_AMOUNT = Decimal('99999999999999.9999')
MAX_WHOLE = Decimal('99999999999999')
ZERO = Decimal('0')


class ReceiptQuantityError(ValueError):
    def __init__(self, code, message, *, key=''):
        super().__init__(message)
        self.code = code
        self.key = key


@dataclass(frozen=True)
class InputPool:
    scope_key: str
    source_key: str
    unit: str
    issued: Decimal
    externally_committed: Decimal = ZERO


@dataclass(frozen=True)
class ComponentDemand:
    scope_key: str
    component_key: str
    source_key: str
    input_unit: str
    output_unit: str
    required: Decimal
    input_per_output: Decimal
    completed_elsewhere: Decimal = ZERO


@dataclass(frozen=True)
class ReceivedOutput:
    scope_key: str
    component_key: str
    source_key: str
    input_unit: str
    output_unit: str
    quantity: Decimal
    input_quantity: Decimal


@dataclass(frozen=True)
class ComponentAllowance:
    required: Decimal
    received: Decimal
    demand_remaining: Decimal
    input_remaining: Decimal
    input_supported: Decimal
    can_receive: Decimal
    requested: Decimal
    consumes_input: Decimal
    received_after: Decimal
    demand_remaining_after: Decimal
    complete_after: bool


@dataclass(frozen=True)
class ReceiptCalculation:
    components: Mapping
    input_remaining_after: Mapping


def _error(code, message, key=''):
    raise ReceiptQuantityError(code, message, key=key)


def _key(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 300:
        _error('IDENTITY_INVALID', f'{label}缺失或格式不正确。')
    return value


def _number(value, label, *, positive=False, whole=False):
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        _error('QUANTITY_INVALID', f'{label}必须是准确的十进制数，不接受浮点数或布尔值。')
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        _error('QUANTITY_INVALID', f'{label}不是有效数字。')
    if not number.is_finite() or number < 0 or (positive and number == 0):
        _error('QUANTITY_INVALID', f'{label}必须是有限的非负数，实际入库及单耗必须大于0。')
    if number > (MAX_WHOLE if whole else MAX_AMOUNT):
        _error('QUANTITY_OVERFLOW', f'{label}超出可保存的数量范围。')
    if whole and number != number.to_integral_value():
        _error('WHOLE_QUANTITY_REQUIRED', f'{label}必须为整数。')
    if whole:
        return number.to_integral_value()
    # 数据库Decimal字段常带尾零；只拒绝实际超过四位的小数，不按字符串长度判断。
    with localcontext() as context:
        context.prec = 60
        canonical = number.quantize(Decimal('0.0001'))
    if canonical != number:
        _error('QUANTITY_PRECISION', f'{label}最多4位小数，不自动舍入。')
    return canonical


def net_component_demand(order_quantity, usage_per_product):
    """只算BOM净需求，不增加采购余量、整根取整余量或成品偏差。"""
    order = _number(order_quantity, '订单数量', positive=True, whole=True)
    usage = _number(usage_per_product, '单个用量', positive=True, whole=True)
    with localcontext() as context:
        context.prec = 60
        return _number(order * usage, '部位需求', positive=True, whole=True)


def fabric_input_per_set(pieces_per_set, meters_per_piece):
    """每套耗布＝每套裁片数×每片用米；不把片数当成套数。"""
    pieces = _number(pieces_per_set, '每套片数', positive=True, whole=True)
    meters = _number(meters_per_piece, '每片用米', positive=True)
    with localcontext() as context:
        context.prec = 60
        return _number(pieces * meters, '每套用米', positive=True)


def _scope(item, expected):
    if _key(item.scope_key, '订单范围') != expected:
        _error('SCOPE_MISMATCH', '投入或产出不属于当前订单，不能混算入库额度。')


def calculate_receipt(*, scope_key, demands, inputs, history=(), requested=None):
    """返回各部位单独可入量，同时校验整张申请对共享投入的合计占用。

    history 必须包含本订单相关投入池的全部有效历史产出，不因库存已领走而删除。
    externally_committed 是已交外发及有效待交占用之和，不再重复包含 history。
    requested=None/{} 只用于预览；实际确认须使用 validate_receipt。
    """
    scope_key = _key(scope_key, '订单范围')
    if not isinstance(demands, (tuple, list)) or not isinstance(inputs, (tuple, list)) or not isinstance(history, (tuple, list)):
        _error('PAYLOAD_INVALID', '需求、投入和历史产出必须是完整明细列表。')
    if requested is None:
        requested = {}
    if not isinstance(requested, Mapping):
        _error('PAYLOAD_INVALID', '本次入库数量必须按部位提供。')
    # 大数与小数相乘时不依赖调用方的全局Decimal精度。
    with localcontext() as context:
        context.prec = 60
        return _calculate(scope_key, demands, inputs, history, requested)


def _calculate(scope_key, demands, inputs, history, requested):
    pools, specs, received, input_used = {}, {}, {}, {}
    for pool in inputs:
        if not isinstance(pool, InputPool):
            _error('PAYLOAD_INVALID', '投入池格式不正确。')
        _scope(pool, scope_key)
        key = _key(pool.source_key, '投入汇总键')
        if key in pools:
            _error('DUPLICATE_INPUT', '同一材料投入只能汇总一次，不能重复提供。', key)
        unit = _key(pool.unit, '投入单位')
        if unit not in {'支', '米'}:
            _error('UNIT_MISMATCH', '本期投入单位必须为支或米。', key)
        issued = _number(pool.issued, '已审核实际出库量', whole=unit == '支')
        external = _number(pool.externally_committed, '外发已用及占用量', whole=unit == '支')
        if external > issued:
            _error('INPUT_HISTORY_CONFLICT', '外发已用及占用量超过实际投入，请先核对。', key)
        pools[key] = (unit, issued, external)
        input_used[key] = ZERO

    for demand in demands:
        if not isinstance(demand, ComponentDemand):
            _error('PAYLOAD_INVALID', '部位需求格式不正确。')
        _scope(demand, scope_key)
        key = _key(demand.component_key, '部位汇总键')
        if key in specs:
            _error('DUPLICATE_COMPONENT', '同一部位同阶段只能提供一份累计需求。', key)
        source = _key(demand.source_key, '投入汇总键')
        if source not in pools:
            _error('INPUT_MISSING', '未找到该部位对应的材料投入，不能猜测可入数量。', key)
        input_unit = _key(demand.input_unit, 'BOM投入单位')
        output_unit = _key(demand.output_unit, '产出单位')
        if input_unit != pools[source][0]:
            _error('UNIT_MISMATCH', 'BOM用量单位与实际投入单位不一致。', key)
        if (input_unit, output_unit) not in {('支', '支'), ('米', '套')}:
            _error('UNIT_MISMATCH', '本期仅支持金工支→支、车缝米→套。', key)
        required = _number(demand.required, '部位需求', positive=True, whole=True)
        usage = _number(demand.input_per_output, '每单位产出耗用', positive=True)
        if demand.output_unit == '支' and usage != 1:
            _error('UNIT_MISMATCH', '金工投入按已领切割支数核算，每支产出占用一支。', key)
        specs[key] = (demand, required, usage)
        received[key] = _number(demand.completed_elsewhere, '外发同阶段已入库', whole=True)

    for entry in history:
        if not isinstance(entry, ReceivedOutput):
            _error('PAYLOAD_INVALID', '历史入库记录格式不正确。')
        _scope(entry, scope_key)
        key = _key(entry.component_key, '历史部位汇总键')
        if key not in specs:
            _error('HISTORY_UNRESOLVED', '历史入库部位不在当前需求中，不能丢弃历史占用。', key)
        demand, required, usage = specs[key]
        if (entry.source_key, entry.input_unit, entry.output_unit) != (demand.source_key, demand.input_unit, demand.output_unit):
            _error('SOURCE_CHANGED', '历史入库的投入来源或单位发生变化，须先核对需求版本。', key)
        quantity = _number(entry.quantity, '历史入库量', positive=True, whole=True)
        used = _number(entry.input_quantity, '历史投入占用', positive=True)
        if used != quantity * usage:
            _error('SOURCE_CHANGED', '历史投入占用与当前单耗不一致，不自动重算旧记录。', key)
        received[key] += quantity
        if received[key] > required:
            _error('DEMAND_HISTORY_CONFLICT', '累计已入库超过当前BOM需求，请核对需求变更。', key)
        input_used[entry.source_key] += used

    remaining_inputs = {}
    for key, (_, issued, external) in pools.items():
        remaining_inputs[key] = issued - external - input_used[key]
        if remaining_inputs[key] < 0:
            _error('INPUT_HISTORY_CONFLICT', '有效历史产出与外发占用合计超过实际投入。', key)

    requests = {}
    for key, value in requested.items():
        if key not in specs:
            _error('COMPONENT_UNKNOWN', '本次入库部位不属于可办理的需求。', str(key))
        requests[key] = _number(value, '本次入库数量', positive=True, whole=True)

    result, total_input_requests = {}, {key: ZERO for key in pools}
    for key, (demand, required, usage) in specs.items():
        remaining = required - received[key]
        available_input = remaining_inputs[demand.source_key]
        supported = available_input // usage
        allowance = min(remaining, supported)
        quantity = requests.get(key, ZERO)
        if quantity > remaining:
            _error('DEMAND_EXCEEDED', '本次入库超过该部位订单剩余需求。', key)
        if quantity > supported:
            _error('INPUT_INSUFFICIENT', '已审核出库材料扣除历史产出及外发占用后不足。', key)
        consumed = quantity * usage
        total_input_requests[demand.source_key] += consumed
        result[key] = ComponentAllowance(required, received[key], remaining, available_input, supported,
                                         allowance, quantity, consumed, received[key] + quantity,
                                         remaining - quantity, quantity == remaining)

    for key, used in total_input_requests.items():
        if used > remaining_inputs[key]:
            _error('SHARED_INPUT_INSUFFICIENT', '多个部位合计用料超过同一份实际投入，请减少本次入库。', key)
    return ReceiptCalculation(MappingProxyType(result), MappingProxyType({
        key: remaining_inputs[key] - total_input_requests[key] for key in pools
    }))


def validate_receipt(**kwargs):
    """确认时不允许空单；服务必须在锁内重新读取事实后调用。"""
    if not kwargs.get('requested'):
        _error('EMPTY_RECEIPT', '请至少填写一个部位的入库数量。')
    return calculate_receipt(**kwargs)
