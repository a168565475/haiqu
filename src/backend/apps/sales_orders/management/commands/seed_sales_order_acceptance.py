import hashlib
import json
import uuid
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.api.concurrency import etag_for_instance
from apps.customers.models import ContactStatus, CustomerTransactionEntity
from apps.files.models import USABLE_FILE_SCAN_STATUSES
from apps.organizations.models import Employee, EmployeeStatus
from apps.products.models import ProductInformation, ProductScale, ProductStatus
from apps.production_tasks.api.serializers import ProductionTaskCreateFromSalesOrderSerializer
from apps.production_tasks.services import create_production_order_from_sales_order
from apps.quotations.models import (
    QuotationLine,
    QuotationLinePrice,
    QuotationOutcomeStatus,
    QuotationPriceBasis,
    QuotationVersionStatus,
)
from apps.quotations.services import (
    confirm_manual_dispatch,
    create_quotation_draft,
    issue_version,
    lock_version,
    set_line_product_image,
    transition_quotation,
)
from apps.quotations.uploads import MAX_IMAGE_BYTES, save_quotation_product_image
from apps.sales_orders.api.serializers import (
    CollaborationEventInputSerializer,
    SalesOrderWriteSerializer,
)
from apps.sales_orders.models import (
    CollaborationEventStatus,
    CollaborationEventType,
    CustomerConfirmationMethod,
    SalesOrder,
    SalesOrderSource,
    SalesOrderStatus,
)
from apps.sales_orders.services import (
    add_collaboration_event,
    complete_sales_order,
    confirm_sales_order,
    create_sales_order,
)


CONFIRM_TOKEN = "CREATE-SO-20-20260914"
MARKER_PREFIX = "QA-SO-260914-"
PRODUCT_PREFIX = "QA-SO-PROD-260914-"
EXPECTED_COUNT = 20
STATUS_SEQUENCE = [
    SalesOrderStatus.DRAFT,
    SalesOrderStatus.CONFIRMED,
    SalesOrderStatus.FULFILLING,
    SalesOrderStatus.COMPLETED,
] * 5
CURRENCY_SETTINGS = [
    ("USD", Decimal("7.120000"), "FOB", "30%订金，70%发货前"),
    ("EUR", Decimal("7.750000"), "CIF", "20%订金，80%提单副本后"),
    ("GBP", Decimal("9.120000"), "EXW", "全款到账后发货"),
    ("CNY", Decimal("1.000000"), "DDP", "月结30天"),
]
CONFIRMATION_METHODS = list(CustomerConfirmationMethod.values)


def _etag_request(instance):
    return SimpleNamespace(headers={"If-Match": etag_for_instance(instance)}, META={})


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _product_name(image_path):
    stem = image_path.stem
    return stem.split("-", 1)[1] if "-" in stem else stem


class Command(BaseCommand):
    help = "创建20条带真实报价图片链路的销售订单验收数据。默认仅预检，写入需显式确认。"

    def add_arguments(self, parser):
        parser.add_argument("--image-dir", required=True, help="包含20张PNG产品设计图的目录。")
        parser.add_argument("--commit", action="store_true", help="执行真实数据库写入。")
        parser.add_argument("--confirm", help=f"写入时必须传入 {CONFIRM_TOKEN}。")
        parser.add_argument("--report", help="将创建与验收结果写入JSON文件。")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("仅允许在 DEBUG 开发环境执行验收数据命令。")

        image_dir = Path(options["image_dir"]).resolve()
        image_paths = sorted(image_dir.glob("*.png"))
        dependencies = self._validate_dependencies(image_dir, image_paths)

        if not options["commit"]:
            self.stdout.write(self.style.SUCCESS(
                f"预检通过：20张PNG、4组完整客户资料、可用员工/产品基准/币种均已确认。"
                f"如需写入，请追加 --commit --confirm {CONFIRM_TOKEN}。"
            ))
            return
        if options.get("confirm") != CONFIRM_TOKEN:
            raise CommandError(f"请明确追加 --confirm {CONFIRM_TOKEN} 后再写入。")

        existing_orders = SalesOrder.objects.filter(customer_po_number__startswith=MARKER_PREFIX)
        if existing_orders.exists():
            if existing_orders.count() != EXPECTED_COUNT:
                raise CommandError(
                    f"检测到 {existing_orders.count()} 条同批次订单，不是预期20条；请先人工核对，命令不会覆盖。"
                )
            report = self._build_report(image_paths)
            self._write_report(options.get("report"), report)
            self.stdout.write(self.style.WARNING("20条同批次订单已存在，本次未重复写入。"))
            return

        created_storage_paths = []
        try:
            with transaction.atomic():
                self._create_dataset(image_paths, dependencies, created_storage_paths)
                report = self._build_report(image_paths)
                if not report["checks"]["all_passed"]:
                    raise CommandError("写入后的完整性验收未通过，事务已回滚。")
        except Exception:
            for storage_path in created_storage_paths:
                storage_path.unlink(missing_ok=True)
            raise

        self._write_report(options.get("report"), report)
        self.stdout.write(self.style.SUCCESS(
            f"销售订单验收数据已创建：20条；状态分布 {report['status_counts']}；"
            f"20张产品图均为安全扫描通过并与报价明细关联。"
        ))

    def _validate_dependencies(self, image_dir, image_paths):
        if not image_dir.is_dir():
            raise CommandError(f"图片目录不存在：{image_dir}")
        if len(image_paths) != EXPECTED_COUNT:
            raise CommandError(f"图片目录必须恰好包含20张PNG，当前为 {len(image_paths)} 张。")
        for image_path in image_paths:
            size = image_path.stat().st_size
            if size <= 0 or size > MAX_IMAGE_BYTES:
                raise CommandError(f"图片大小不合法：{image_path.name}（{size}字节）。")
            if image_path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                raise CommandError(f"文件扩展名与PNG签名不一致：{image_path.name}")

        contexts = []
        entity_queryset = CustomerTransactionEntity.objects.filter(
            archived_at__isnull=True,
            addresses__archived_at__isnull=True,
            customer_account__contacts__status=ContactStatus.ACTIVE,
            customer_account__contacts__archived_at__isnull=True,
        ).select_related("customer_account").distinct().order_by("entity_code", "id")
        for entity in entity_queryset:
            address = entity.addresses.filter(archived_at__isnull=True).order_by("address_code", "id").first()
            contact = entity.customer_account.contacts.filter(
                status=ContactStatus.ACTIVE,
                archived_at__isnull=True,
            ).order_by("-is_primary_contact", "display_name", "id").first()
            if address and contact:
                contexts.append((entity, address, contact))
        if len(contexts) < 4:
            raise CommandError(f"至少需要4组完整客户主体/地址/联系人，当前只有 {len(contexts)} 组。")

        employees = list(Employee.objects.filter(
            status=EmployeeStatus.ACTIVE,
            archived_at__isnull=True,
        ).order_by("employee_code", "id"))
        if len(employees) < 3:
            raise CommandError("至少需要3名有效员工用于业务员、跟单员和计划员。")

        reference_product = ProductInformation.objects.filter(
            status=ProductStatus.ACTIVE,
            archived_at__isnull=True,
            category__archived_at__isnull=True,
            unit__archived_at__isnull=True,
            product_item__archived_at__isnull=True,
        ).select_related("category", "unit", "product_item").order_by("product_number", "id").first()
        if reference_product is None:
            raise CommandError("缺少可复用类别、单位和产品项目的有效成品资料。")

        currency_codes = [item[0] for item in CURRENCY_SETTINGS]
        from apps.reference_data.models import Currency, ReferenceStatus

        currencies = {
            item.code: item
            for item in Currency.objects.filter(
                code__in=currency_codes,
                status=ReferenceStatus.ACTIVE,
                archived_at__isnull=True,
            )
        }
        missing_currencies = sorted(set(currency_codes) - set(currencies))
        if missing_currencies:
            raise CommandError(f"缺少有效币种：{'、'.join(missing_currencies)}。")

        actor = next((item for item in employees if item.user_id and item.user.is_superuser), employees[0])
        return {
            "contexts": contexts[:4],
            "employees": employees,
            "reference_product": reference_product,
            "currencies": currencies,
            "actor": actor,
        }

    def _create_dataset(self, image_paths, dependencies, created_storage_paths):
        products = self._create_products(image_paths, dependencies["reference_product"])
        quote_lines = self._create_accepted_quotes(
            image_paths,
            products,
            dependencies,
            created_storage_paths,
        )
        self._create_orders(products, quote_lines, dependencies)

    def _create_products(self, image_paths, reference_product):
        products = []
        for index, image_path in enumerate(image_paths, start=1):
            product = ProductInformation(
                product_number=f"{PRODUCT_PREFIX}{index:03d}",
                product_code=f"SOQA260914{index:03d}",
                category=reference_product.category,
                product_name=_product_name(image_path),
                specification=f"设计图款式 {index:02d}；尺寸、颜色按客户确认样",
                unit=reference_product.unit,
                product_item=reference_product.product_item,
                warehouse_number="QA-WH-01",
                warehouse_name="销售订单验收样品区",
                scale=ProductScale.CUSTOM if index % 2 else ProductScale.REGULAR,
                status=ProductStatus.ACTIVE,
            )
            product.full_clean()
            product.save()
            products.append(product)
        return products

    def _create_accepted_quotes(self, image_paths, products, dependencies, created_storage_paths):
        actor = dependencies["actor"]
        quote_lines = []
        base_date = date(2026, 9, 14)
        for group_index, (entity, address, contact) in enumerate(dependencies["contexts"], start=1):
            currency_code, _rate, incoterm, payment_terms = CURRENCY_SETTINGS[group_index - 1]
            quotation, version = create_quotation_draft(
                quotation_data={
                    "customer_account": entity.customer_account,
                    "transaction_entity": entity,
                    "source_inquiry": None,
                    "owner_employee": actor,
                    "subject": f"{MARKER_PREFIX}QUOTE-{group_index:02d} 户外产品组合报价",
                    "creation_idempotency_key": f"SO260914Q{group_index:02d}",
                },
                version_data={"currency_code": currency_code, "valid_until": base_date + timedelta(days=45)},
                actor_employee=actor,
                request=None,
            )
            basis = QuotationPriceBasis.objects.create(
                quotation_version=version,
                label=f"{incoterm} 验收价",
                incoterm_code=incoterm,
                named_place="宁波" if incoterm != "DDP" else "客户指定仓",
                currency_code=currency_code,
                is_default=True,
                sort_order=1,
                notes=payment_terms,
            )
            for offset in range(5):
                index = (group_index - 1) * 5 + offset
                quantity = Decimal(120 + index * 15)
                unit_price = Decimal("18.5000") + Decimal(index) * Decimal("1.3750")
                line = QuotationLine.objects.create(
                    quotation_version=version,
                    line_number=offset + 1,
                    product_description_snapshot=products[index].product_name,
                    specification_snapshot=products[index].specification,
                    quantity=quantity,
                    unit_code=products[index].unit.unit_code,
                    unit_price=unit_price,
                    discount_rate=Decimal("0.000000"),
                    line_total=quantity * unit_price,
                    notes=f"产品编号 {products[index].product_number}；图片来源：{image_paths[index].name}",
                )
                QuotationLinePrice.objects.create(
                    quotation_line=line,
                    price_basis=basis,
                    unit_price=unit_price,
                )
                with image_paths[index].open("rb") as image_stream:
                    business_file = save_quotation_product_image(
                        File(image_stream, name=image_paths[index].name),
                        actor,
                    )
                created_storage_paths.append(Path(settings.MEDIA_ROOT) / business_file.storage_key)
                line, version = set_line_product_image(
                    line=line,
                    business_file=business_file,
                    actor_employee=actor,
                    request=_etag_request(version),
                )
                quote_lines.append(line)

            version.refresh_from_db()
            version = lock_version(
                version=version,
                address=address,
                contact=contact,
                tax_rate=Decimal("0"),
                terms={
                    "incoterm_code": incoterm,
                    "payment_terms": payment_terms,
                    "price_validity": "45天",
                },
                actor_employee=actor,
                request=_etag_request(version),
            )
            version = issue_version(
                version=version,
                actor_employee=actor,
                request=_etag_request(version),
                note="销售订单验收数据：报价签发",
            )
            _record, version = confirm_manual_dispatch(
                version=version,
                price_basis=basis,
                recipient_snapshot={"name": contact.display_name, "email": "qa-customer@example.com"},
                evidence_file=None,
                external_reference=f"QA-MANUAL-DISPATCH-{group_index:02d}",
                follow_up_due_at=timezone.make_aware(
                    datetime.combine(base_date + timedelta(days=3), time(9, 0))
                ),
                evidence_note="本地验收：模拟客户邮件发送记录，无外部消息。",
                actor_employee=actor,
                request=_etag_request(version),
            )
            quotation.refresh_from_db()
            transition_quotation(
                quotation=quotation,
                action="ACCEPTED",
                accepted_version=version,
                accepted_price_basis=basis,
                customer_contact=contact,
                accepted_at=timezone.make_aware(datetime.combine(base_date, time(10, group_index))),
                acceptance_source="EMAIL",
                note="客户已书面接受该组产品报价（本地验收数据）。",
                actor_employee=actor,
                request=_etag_request(quotation),
            )
        return quote_lines

    def _create_orders(self, products, quote_lines, dependencies):
        employees = dependencies["employees"]
        actor = dependencies["actor"]
        base_date = date(2026, 9, 14)
        for index, target_status in enumerate(STATUS_SEQUENCE, start=1):
            quote_line = quote_lines[index - 1]
            version = quote_line.quotation_version
            quotation = version.quotation
            context_index = (index - 1) // 5
            entity, address, contact = dependencies["contexts"][context_index]
            currency_code, exchange_rate, incoterm, payment_terms = CURRENCY_SETTINGS[context_index]
            salesperson = employees[(index - 1) % len(employees)]
            merchandiser = employees[index % len(employees)]
            quantity = quote_line.quantity
            delivery_date = base_date + timedelta(days=7 + index)
            line_key = f"line-{index:02d}"
            method = CONFIRMATION_METHODS[(index - 1) % len(CONFIRMATION_METHODS)]
            payload = {
                "source_type": SalesOrderSource.QUOTATION,
                "source_quotation_version_id": str(version.pk),
                "customer_account_id": str(quotation.customer_account_id),
                "transaction_entity_id": str(entity.pk),
                "buyer_address_id": str(address.pk),
                "salesperson_id": str(salesperson.pk),
                "merchandiser_id": str(merchandiser.pk),
                "customer_po_number": f"{MARKER_PREFIX}{index:03d}",
                "contract_number": f"QA-CON-260914-{index:03d}",
                "order_date": (base_date - timedelta(days=index % 6)).isoformat(),
                "currency_code": currency_code,
                "exchange_rate": str(exchange_rate),
                "incoterm_code": incoterm,
                "payment_terms": payment_terms,
                "deposit_required": index % 3 != 0,
                "includes_tax": currency_code == "CNY",
                "tax_basis": "含13%增值税" if currency_code == "CNY" else "出口免税",
                "order_tolerance_percent": str(index % 4),
                "preproduction_sample_required": index % 2 == 1,
                "seller_snapshot": version.template_snapshot,
                "terms_snapshot": version.terms_snapshot,
                "customer_requirement_snapshot": {
                    "design_image": quote_line.product_image.original_name,
                    "inspection_focus": ["结构稳定性", "面料色差", "包装唛头"],
                    "qa_dataset": MARKER_PREFIX,
                },
                "confirmation_method": method,
                "customer_confirmer": contact.display_name,
                "customer_confirmed_at": timezone.make_aware(
                    datetime.combine(base_date - timedelta(days=index % 3), time(9 + index % 8, index % 60))
                ).isoformat(),
                "confirmation_summary": f"客户确认第{index:02d}款产品、数量、价格、交期及设计图。",
                "lines": [{
                    "client_key": line_key,
                    "source_quotation_line_id": str(quote_line.pk),
                    "product_id": str(products[index - 1].pk),
                    "quantity": str(quantity),
                    "unit_price": str(quote_line.unit_price),
                    "lower_price_reason": "",
                    "quality_requirements": f"第{index:02d}款：承重、折叠结构和表面处理按确认样验收。",
                    "packaging_requirements": f"每箱{2 + index % 5}件，附说明书与追溯标签。",
                    "shipping_mark_requirements": f"外箱印 QA260914-{index:03d}、客户PO和目的港。",
                }],
                "delivery_batches": [{
                    "client_key": f"batch-{index:02d}",
                    "planned_delivery_date": delivery_date.isoformat(),
                    "notes": f"第{index:02d}款首批交付；目的地按{incoterm}条款执行。",
                    "lines": [{"sales_order_line_client_key": line_key, "quantity": str(quantity)}],
                }],
            }
            serializer = SalesOrderWriteSerializer(data=payload)
            serializer.is_valid(raise_exception=True)
            order = create_sales_order(
                validated_data=dict(serializer.validated_data),
                actor_employee=actor,
                request=None,
            )
            if target_status == SalesOrderStatus.DRAFT:
                continue

            order = confirm_sales_order(
                order=order,
                actor_employee=actor,
                request=_etag_request(order),
            )
            if target_status == SalesOrderStatus.CONFIRMED:
                continue

            if target_status == SalesOrderStatus.FULFILLING:
                batch_line = order.delivery_batches.get().lines.get()
                production_payload = {
                    "request_key": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{MARKER_PREFIX}{index:03d}:production")),
                    "delivery_batch_line_id": str(batch_line.pk),
                    "quantity": int(batch_line.quantity),
                    "planned_start_date": base_date.isoformat(),
                    "planned_end_date": delivery_date.isoformat(),
                    "production_priority": "HIGH" if index % 2 else "NORMAL",
                    "production_batch_number": f"SOQA-PROD-{index:03d}",
                    "planner_id": str(employees[(index + 1) % len(employees)].pk),
                }
                production_serializer = ProductionTaskCreateFromSalesOrderSerializer(data=production_payload)
                production_serializer.is_valid(raise_exception=True)
                create_production_order_from_sales_order(
                    validated_data=dict(production_serializer.validated_data),
                    actor_employee=actor,
                    request=None,
                )
                continue

            for event_payload in (
                {
                    "delivery_batch_id": str(order.delivery_batches.get().pk),
                    "event_type": CollaborationEventType.SHIPMENT,
                    "status": CollaborationEventStatus.COMPLETED,
                    "title": "整单发货完成",
                    "note": "物流签收信息已核对。",
                    "quantity": str(quantity),
                    "occurred_at": timezone.now().isoformat(),
                },
                {
                    "event_type": CollaborationEventType.BALANCE,
                    "status": CollaborationEventStatus.COMPLETED,
                    "title": "余款已登记完成",
                    "note": "财务收款记录已登记。",
                    "occurred_at": timezone.now().isoformat(),
                },
            ):
                event_serializer = CollaborationEventInputSerializer(data=event_payload)
                event_serializer.is_valid(raise_exception=True)
                _event, order = add_collaboration_event(
                    order=order,
                    validated_data=dict(event_serializer.validated_data),
                    actor_employee=actor,
                    request=_etag_request(order),
                )
            complete_sales_order(
                order=order,
                exception_close=False,
                reason=f"{MARKER_PREFIX}{index:03d} 正常完结验收",
                actor_employee=actor,
                request=_etag_request(order),
            )

    def _build_report(self, image_paths):
        orders = list(
            SalesOrder.objects.filter(customer_po_number__startswith=MARKER_PREFIX)
            .select_related("customer_account", "source_quotation_version__quotation")
            .prefetch_related(
                "lines__product",
                "lines__source_quotation_line__product_image",
                "delivery_batches__lines",
                "collaboration_events",
                "production_tasks",
                "versions",
            )
            .order_by("customer_po_number")
        )
        status_counts = Counter(order.status for order in orders)
        order_rows = []
        image_links_valid = True
        media_hashes_match = True
        production_links_valid = True
        completion_gates_valid = True
        for index, order in enumerate(orders, start=1):
            line = order.lines.get()
            image = line.source_quotation_line.product_image if line.source_quotation_line_id else None
            media_path = Path(settings.MEDIA_ROOT) / image.storage_key if image else None
            image_ok = bool(
                image
                and image.scan_status in USABLE_FILE_SCAN_STATUSES
                and media_path.is_file()
            )
            image_links_valid = image_links_valid and image_ok
            source_hash = _sha256(image_paths[index - 1])
            stored_hash = _sha256(media_path) if image_ok else None
            hash_ok = source_hash == stored_hash == getattr(image, "content_hash", None)
            media_hashes_match = media_hashes_match and hash_ok
            has_production = order.production_tasks.exclude(status="CANCELLED").exists()
            if order.status == SalesOrderStatus.FULFILLING:
                production_links_valid = production_links_valid and has_production
            shipment_total = sum(
                (event.quantity or Decimal("0"))
                for event in order.collaboration_events.all()
                if event.event_type == CollaborationEventType.SHIPMENT
                and event.status == CollaborationEventStatus.COMPLETED
            )
            balance_completed = any(
                event.event_type == CollaborationEventType.BALANCE
                and event.status == CollaborationEventStatus.COMPLETED
                for event in order.collaboration_events.all()
            )
            if order.status == SalesOrderStatus.COMPLETED:
                completion_gates_valid = completion_gates_valid and shipment_total >= line.quantity and balance_completed
            order_rows.append({
                "index": index,
                "id": str(order.pk),
                "order_number": order.order_number,
                "status": order.status,
                "customer_po_number": order.customer_po_number,
                "customer": order.customer_account.account_name,
                "product_number": line.product.product_number,
                "product_name": line.product.product_name,
                "quantity": str(line.quantity),
                "currency": order.currency_code,
                "amount": str(order.total_amount),
                "source_quotation": order.source_quotation_version.quotation.quotation_number,
                "image_file": image.original_name if image else None,
                "image_scan_status": image.scan_status if image else None,
                "image_sha256": stored_hash,
                "has_production_order": has_production,
                "shipment_total": str(shipment_total),
                "balance_completed": balance_completed,
            })

        expected_status_counts = {
            SalesOrderStatus.DRAFT: 5,
            SalesOrderStatus.CONFIRMED: 5,
            SalesOrderStatus.FULFILLING: 5,
            SalesOrderStatus.COMPLETED: 5,
        }
        checks = {
            "order_count_20": len(orders) == EXPECTED_COUNT,
            "status_distribution_5_each": dict(status_counts) == expected_status_counts,
            "unique_product_count_20": len({row["product_number"] for row in order_rows}) == EXPECTED_COUNT,
            "all_source_quotes_won": all(
                order.source_quotation_version.quotation.outcome_status == QuotationOutcomeStatus.WON
                and order.source_quotation_version.quotation.accepted_version_id == order.source_quotation_version_id
                and order.source_quotation_version.status == QuotationVersionStatus.SENT
                for order in orders
            ),
            "all_quote_images_clean_and_present": image_links_valid,
            "all_image_hashes_match_sources": media_hashes_match,
            "fulfilling_orders_have_production": production_links_valid,
            "completed_orders_pass_shipment_and_balance": completion_gates_valid,
            "confirmed_orders_have_versions": all(
                order.status == SalesOrderStatus.DRAFT or order.versions.exists()
                for order in orders
            ),
        }
        checks["all_passed"] = all(checks.values())
        return {
            "dataset": MARKER_PREFIX,
            "generated_at": timezone.now().isoformat(),
            "order_count": len(orders),
            "status_counts": dict(sorted(status_counts.items())),
            "checks": checks,
            "known_flow_gap": (
                "订单状态枚举包含PAUSED/CANCELLED，但当前销售订单API没有订单级暂停或取消入口；"
                "异常关闭按已确认开发方案写入COMPLETED。"
            ),
            "image_scope_note": (
                "图片保存在已接受报价明细QuotationLine.product_image；SalesOrderLine保存来源报价行，"
                "当前销售订单自身没有独立图片快照字段。"
            ),
            "orders": order_rows,
        }

    def _write_report(self, report_path, report):
        if not report_path:
            return
        path = Path(report_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"验收报告：{path}")
