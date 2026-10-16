from decimal import Decimal, ROUND_HALF_UP, localcontext

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.exceptions import Conflict
from apps.reference_data.models import Currency, ExchangeRate, ReferenceStatus


MONEY_QUANT = Decimal("0.0001")


class SalesExchangeRateChanged(Conflict):
    api_error_code = "SALES_EXCHANGE_RATE_CHANGED"


def current_cny_rate(currency_code, *, record_id=None, lock=False, verify_preview=False):
    """读取销售建单时的配置汇率；原币一单位兑换人民币的金额。"""
    currency_code = str(currency_code or "").strip().upper()
    currencies = Currency.objects.filter(
        code__in={currency_code, "CNY"}, status=ReferenceStatus.ACTIVE, archived_at__isnull=True,
    )
    if set(currencies.values_list("code", flat=True)) != {currency_code, "CNY"}:
        raise ValidationError({"currency_code": "订单币种或人民币币种不存在、已停用或归档。"})
    if currency_code == "CNY":
        if verify_preview and record_id is not None:
            raise ValidationError({"exchange_rate_record_id": "人民币不需要汇率记录。"})
        return None, {
            "record_id": None, "base_currency_code": "CNY", "quote_currency_code": "CNY",
            "rate": "1.00000000", "effective_date": None, "source_name": "人民币恒等汇率", "source_version": "",
        }
    records = ExchangeRate.objects.filter(
        base_currency__code=currency_code, quote_currency__code="CNY",
        status=ReferenceStatus.ACTIVE, archived_at__isnull=True, effective_date__lte=timezone.localdate(),
    ).select_related("base_currency", "quote_currency")
    if lock:
        records = records.select_for_update(of=("self",))
    available = list(records[:2])
    if not available:
        raise ValidationError({"exchange_rate_record_id": f"未维护可用的 {currency_code} → CNY 汇率，请联系管理员。"})
    if len(available) != 1:
        raise ValidationError({"exchange_rate_record_id": f"{currency_code} → CNY 存在多条有效汇率，请先核对系统配置。"})
    record = available[0]
    if not record.rate.is_finite() or record.rate <= 0:
        raise ValidationError({"exchange_rate_record_id": "系统汇率必须为有限的正数，请先核对配置。"})
    if verify_preview:
        if record_id is None:
            raise ValidationError({"exchange_rate_record_id": "请先读取并确认系统汇率。"})
        if str(record.pk) != str(record_id):
            raise SalesExchangeRateChanged("汇率预览已失效，请刷新系统汇率后重试。")
    return record, {
        "record_id": str(record.pk), "base_currency_code": record.base_currency.code,
        "quote_currency_code": record.quote_currency.code, "rate": format(record.rate, ".8f"),
        "effective_date": record.effective_date.isoformat(), "source_name": record.source_name,
        "source_version": record.source_version,
    }


def freeze_sales_rate(values, *, previous=None):
    record_id = values.pop("exchange_rate_record_id", None)
    values.pop("exchange_rate", None)
    if previous is not None and values["currency_code"] == previous.currency_code:
        if previous.total_amount_cny is None or not previous.exchange_rate_snapshot:
            raise ValidationError({"exchange_rate": "历史销售订单尚未补算人民币金额，请先完成一次性补算。"})
        return
    record, snapshot = current_cny_rate(values["currency_code"], record_id=record_id, lock=True, verify_preview=True)
    snapshot.update(
        captured_at=timezone.now().isoformat(), capture_reason="CURRENCY_CHANGED" if previous else "CREATED",
    )
    values.update(exchange_rate_record=record, exchange_rate=Decimal(snapshot["rate"]), exchange_rate_snapshot=snapshot)


def cny_line_amounts(unit_price, quantity, rate):
    # 先舍入人民币单价，再乘数量；销售、部分生产分配和总计采用同一口径。
    with localcontext() as context:
        context.prec = 60
        unit = (Decimal(unit_price) * Decimal(rate)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        total = (unit * Decimal(quantity)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    if not unit.is_finite() or unit < 0 or unit >= Decimal("1e14"):
        raise ValidationError({"lines": "换算后的人民币单价超出可保存范围，请核对单价和系统汇率。"})
    validate_cny_total(total)
    return unit, total


def validate_cny_total(total):
    if not total.is_finite() or total < 0 or total >= Decimal("1e18"):
        raise ValidationError({"total_amount_cny": "人民币金额超出可保存范围，请核对数量、单价和系统汇率。"})

