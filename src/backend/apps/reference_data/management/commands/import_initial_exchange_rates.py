import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.audit import write_audit_log
from apps.organizations.models import Employee, EmployeeStatus
from apps.reference_data.api.serializers import ExchangeRateSerializer
from apps.reference_data.models import Currency, ExchangeRate


class Command(BaseCommand):
    help = "从已核实的离线文件初始化兑人民币汇率；默认仅预览，不覆盖已有币种对。"

    def add_arguments(self, parser):
        parser.add_argument("path", help="包含 rates 数组的 JSON 文件")
        parser.add_argument("--apply", action="store_true", help="确认写入并记录审计日志")
        parser.add_argument("--employee-code", help="有新增汇率权限的在职员工编号")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            document = json.loads(Path(options["path"]).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CommandError(f"无法读取汇率文件：{exc}") from exc
        rows = document.get("rates") if isinstance(document, dict) else None
        if not isinstance(rows, list) or not rows:
            raise CommandError("文件必须包含非空 rates 数组。")

        actor = None
        if options["apply"]:
            actor = Employee.objects.select_related("user").filter(
                employee_code=options.get("employee_code"),
                status=EmployeeStatus.ACTIVE,
                archived_at__isnull=True,
            ).first()
            if not actor or not actor.user or not actor.user.is_active or not actor.user.has_perm("reference_data.add_exchangerate"):
                raise CommandError("写入必须指定有新增汇率权限的在职员工 --employee-code。")

        # 同一导入命令锁住币种后再核查已有记录，重复执行只跳过，不改历史。
        currency_query = Currency.objects.order_by("pk")
        if options["apply"]:
            currency_query = currency_query.select_for_update()
        currencies = {currency.code: currency for currency in currency_query}
        existing_pairs = set(ExchangeRate.objects.values_list("base_currency_id", "quote_currency_id"))
        serializers = []
        seen = set()
        skipped = 0
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise CommandError(f"第 {index} 条必须为汇率对象。")
            base_code, quote_code = row.get("base_currency_code"), row.get("quote_currency_code")
            if not isinstance(base_code, str) or not isinstance(quote_code, str) or quote_code != "CNY":
                raise CommandError(f"第 {index} 条必须使用现有币种代码并兑人民币 CNY。")
            pair = (base_code, quote_code)
            if pair in seen:
                raise CommandError(f"币种对重复：{base_code}/{quote_code}。")
            seen.add(pair)
            base, quote = currencies.get(base_code), currencies.get(quote_code)
            if base is None or quote is None:
                raise CommandError(f"第 {index} 条币种不存在：{base_code}/{quote_code}。")
            serializer = ExchangeRateSerializer(data={
                "base_currency": str(base.pk), "quote_currency": str(quote.pk),
                **{field: row.get(field, "") for field in (
                    "rate", "effective_date", "source_name", "source_version", "description",
                )},
            })
            if not serializer.is_valid():
                raise CommandError(f"第 {index} 条 {base_code}/{quote_code} 无效：{serializer.errors}")
            if (base.pk, quote.pk) in existing_pairs:
                skipped += 1
            else:
                serializers.append(serializer)

        if options["apply"]:
            for serializer in serializers:
                record = serializer.save(entered_by_employee=actor)
                write_audit_log(
                    object_type="EXCHANGE_RATE", object_id=record.pk, action="CREATED",
                    actor_employee=actor, after_data=serializer.data,
                )
        mode = "已写入" if options["apply"] else "预览，未写入"
        self.stdout.write(f"{mode}：新增 {len(serializers)} 条；已有币种对跳过 {skipped} 条。")
