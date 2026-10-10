import json
import warnings
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.paginator import UnorderedObjectListWarning
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.customers.models import CustomerAccount, CustomerEntityAddress, CustomerTransactionEntity
from apps.boms.models import Bom, BomCreationMethod, BomStatus
from apps.files.models import BusinessFile, FileScanStatus
from apps.organizations.models import Employee
from apps.products.models import ProductInformation
from apps.production_tasks.models import ProductionTask, ProductionTaskStatus
from apps.reference_data.models import ProductColor
from apps.quotations.models import (
    Quotation,
    QuotationAcceptance,
    QuotationLine,
    QuotationPriceBasis,
    QuotationVersion,
)
from apps.sales_orders.models import (
    CollaborationEventSource,
    CollaborationEventStatus,
    CollaborationEventType,
    SalesOrderCollaborationEvent,
)


class SalesOrderApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(username="sales_order_admin", password="test")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="SALES_ORDER_ADMIN",
            display_name="销售订单测试员工",
        )
        self.customer = CustomerAccount.objects.create(
            account_code="SALES_ORDER_CUSTOMER",
            account_name="销售订单测试客户",
            primary_country_code="CN",
        )
        self.entity = CustomerTransactionEntity.objects.create(
            customer_account=self.customer,
            entity_code="SALES_ORDER_BUYER",
            legal_name="销售订单测试买方",
        )
        self.address = CustomerEntityAddress.objects.create(
            transaction_entity=self.entity,
            address_code="SALES_ORDER_ADDRESS",
            label="订单地址",
            country_code="CN",
            state_province="浙江省",
            city="金华市",
            address_line1="测试路 1 号",
            recipient_name="Buyer A",
            recipient_phone="13800000000",
            is_verified=False,
        )
        self.product = ProductInformation.objects.filter(status="ACTIVE", archived_at__isnull=True).select_related("unit").first()
        self.currency_code = "CNY"
        self.evidence = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="customer-po.pdf",
            storage_key="tests/customer-po.pdf",
            content_type="application/pdf",
            size_bytes=10,
            scan_status=FileScanStatus.SKIPPED,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def direct_payload(self, *, with_evidence=True, quantity="10.0000", unit_price="20.0000"):
        now = timezone.now()
        return {
            "source_type": "DIRECT",
            "source_quotation_version_id": None,
            "customer_account_id": str(self.customer.pk),
            "transaction_entity_id": str(self.entity.pk),
            "buyer_address_id": str(self.address.pk),
            "salesperson_id": str(self.employee.pk),
            "merchandiser_id": str(self.employee.pk),
            "customer_po_number": "PO-TEST-001",
            "contract_number": "CONTRACT-TEST-001",
            "order_date": timezone.localdate().isoformat(),
            "direct_order_reason": "客户直接书面下单",
            "currency_code": self.currency_code,
            "exchange_rate": "1.000000",
            "payment_terms": "30% 订金，余款发货前付清",
            "deposit_required": True,
            "includes_tax": True,
            "tax_basis": "含税",
            "order_tolerance_percent": "3.00",
            "preproduction_sample_required": True,
            "seller_snapshot": {"template_config": {"seller_company_name": "HAIQU TEST SELLER CO., LTD."}},
            "confirmation_method": "CUSTOMER_PO",
            "customer_confirmer": "Buyer A",
            "customer_confirmed_at": now.isoformat(),
            "confirmation_summary": "客户确认产品、数量、价格和交期",
            "evidence_file_ids": [str(self.evidence.pk)] if with_evidence else [],
            "lines": [
                {
                    "client_key": "line-1",
                    "source_quotation_line_id": None,
                    "product_id": str(self.product.pk),
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "quality_requirements": "按确认样",
                    "packaging_requirements": "出口纸箱",
                    "shipping_mark_requirements": "按客户唛头",
                }
            ],
            "delivery_batches": [
                {
                    "planned_delivery_date": timezone.localdate().isoformat(),
                    "notes": "首批",
                    "lines": [{"sales_order_line_client_key": "line-1", "quantity": quantity}],
                }
            ],
        }

    def create_direct(self, **payload_overrides):
        payload = self.direct_payload()
        payload.update(payload_overrides)
        response = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_list_uses_explicit_ordering_for_stable_pagination(self):
        self.create_direct(order_date=(timezone.localdate() - timedelta(days=1)).isoformat())
        self.create_direct(order_date=timezone.localdate().isoformat())

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", UnorderedObjectListWarning)
            response = self.client.get("/api/v1/sales-orders/", {"page_size": 1})

        self.assertEqual(response.status_code, 200, response.data)
        pagination_warnings = [
            item for item in caught if issubclass(item.category, UnorderedObjectListWarning)
        ]
        self.assertEqual(pagination_warnings, [])
        self.assertEqual(response.data["data"][0]["order_date"], timezone.localdate().isoformat())

    def confirm_direct(self):
        created = self.create_direct()
        confirmed = self.client.post(
            f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        return confirmed

    def add_completed_shipment_and_balance(self, order_id):
        SalesOrderCollaborationEvent.objects.create(
            sales_order_id=order_id,
            event_type=CollaborationEventType.SHIPMENT,
            source_type=CollaborationEventSource.MANUAL,
            status=CollaborationEventStatus.COMPLETED,
            title="全部发货",
            quantity=Decimal("10"),
            occurred_at=timezone.now(),
            recorded_by_employee=self.employee,
        )
        SalesOrderCollaborationEvent.objects.create(
            sales_order_id=order_id,
            event_type=CollaborationEventType.BALANCE,
            source_type=CollaborationEventSource.MANUAL,
            status=CollaborationEventStatus.COMPLETED,
            title="余款完成",
            occurred_at=timezone.now(),
            recorded_by_employee=self.employee,
        )

    def test_completion_records_explicit_user_intent(self):
        normal = self.confirm_direct()
        normal_id = normal.data["data"]["id"]
        self.add_completed_shipment_and_balance(normal_id)
        normal_result = self.client.post(
            f"/api/v1/sales-orders/{normal_id}/complete/",
            {"exception_close": False, "reason": "正常完结说明"},
            format="json",
            HTTP_IF_MATCH=normal["ETag"],
        )
        self.assertEqual(normal_result.status_code, 200, normal_result.data)
        self.assertTrue(SalesOrderCollaborationEvent.objects.filter(
            sales_order_id=normal_id,
            title="销售订单正常完结",
            status=CollaborationEventStatus.COMPLETED,
        ).exists())

        exceptional = self.confirm_direct()
        exceptional_id = exceptional.data["data"]["id"]
        self.add_completed_shipment_and_balance(exceptional_id)
        exceptional_result = self.client.post(
            f"/api/v1/sales-orders/{exceptional_id}/complete/",
            {"exception_close": True, "reason": "客户要求提前异常关闭"},
            format="json",
            HTTP_IF_MATCH=exceptional["ETag"],
        )
        self.assertEqual(exceptional_result.status_code, 200, exceptional_result.data)
        self.assertTrue(SalesOrderCollaborationEvent.objects.filter(
            sales_order_id=exceptional_id,
            title="销售订单异常关闭",
            status=CollaborationEventStatus.RISK,
        ).exists())

        missing_reason = self.confirm_direct()
        missing_reason_result = self.client.post(
            f"/api/v1/sales-orders/{missing_reason.data['data']['id']}/complete/",
            {"exception_close": True, "reason": ""},
            format="json",
            HTTP_IF_MATCH=missing_reason["ETag"],
        )
        self.assertEqual(missing_reason_result.status_code, 400, missing_reason_result.data)

    def test_cancelling_confirmed_batch_requires_evidence_from_the_same_order(self):
        confirmed = self.confirm_direct()
        order_id = confirmed.data["data"]["id"]
        batch_id = confirmed.data["data"]["delivery_batches"][0]["id"]
        unrelated_evidence = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="unrelated-customer-note.pdf",
            storage_key="tests/unrelated-customer-note.pdf",
            content_type="application/pdf",
            size_bytes=10,
            scan_status=FileScanStatus.SKIPPED,
        )
        rejected = self.client.post(
            f"/api/v1/sales-orders/{order_id}/delivery-batches/{batch_id}/cancel/",
            {"reason": "客户取消本批", "evidence_file_id": str(unrelated_evidence.pk)},
            format="json",
            HTTP_IF_MATCH=confirmed["ETag"],
        )
        self.assertEqual(rejected.status_code, 400, rejected.data)

        cancelled = self.client.post(
            f"/api/v1/sales-orders/{order_id}/delivery-batches/{batch_id}/cancel/",
            {"reason": "客户取消本批", "evidence_file_id": str(self.evidence.pk)},
            format="json",
            HTTP_IF_MATCH=confirmed["ETag"],
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["data"]["delivery_batches"][0]["status"], "CANCELLED")

    def confirmed_change_payload(self, confirmed, *, quantity="10.0000", unit_price="20.0000"):
        payload = self.direct_payload(quantity=quantity, unit_price=unit_price)
        line = confirmed.data["data"]["lines"][0]
        batch = confirmed.data["data"]["delivery_batches"][0]
        payload["lines"][0]["client_key"] = line["id"]
        payload["delivery_batches"][0]["client_key"] = batch["id"]
        payload["delivery_batches"][0]["lines"][0]["sales_order_line_client_key"] = line["id"]
        return payload

    def quotation_context(
        self,
        *,
        quantity="10.0000",
        unit_price="10.0000",
        product_description=None,
        specification=None,
        customer_requirement_snapshot=None,
    ):
        quotation = Quotation.objects.create(
            customer_account=self.customer,
            transaction_entity=self.entity,
            owner_employee=self.employee,
            quotation_number=f"QUO-SO-{Quotation.objects.count() + 1:03d}",
            subject="销售订单转单测试",
        )
        version = QuotationVersion.objects.create(
            quotation=quotation,
            version_number=1,
            status="DRAFT",
            currency_code="CNY",
            transaction_entity_snapshot={"legal_name": self.entity.legal_name},
            address_snapshot={
                "id": str(self.address.pk),
                "address_code": self.address.address_code,
                "country_code": self.address.country_code,
                "address_line1": self.address.address_line1,
            },
            contact_snapshot={"name": "Buyer A"},
            customer_requirement_snapshot=customer_requirement_snapshot or {},
        )
        quote_line = QuotationLine.objects.create(
            quotation_version=version,
            line_number=1,
            product_description_snapshot=product_description or self.product.product_name,
            specification_snapshot=specification or self.product.specification,
            quantity=quantity,
            unit_code=self.product.unit.unit_code,
            unit_price=unit_price,
            line_total=Decimal(quantity) * Decimal(unit_price),
        )
        version.status = "SENT"
        version.locked_at = timezone.now()
        version.save(update_fields=["status", "locked_at", "updated_at"])
        basis = QuotationPriceBasis.objects.create(
            quotation_version=version,
            label="EXW 测试",
            incoterm_code="EXW",
            named_place="测试",
            currency_code="CNY",
            is_default=True,
        )
        QuotationAcceptance.objects.create(
            quotation=quotation,
            quotation_version=version,
            price_basis=basis,
            accepted_at=timezone.now(),
            source="EMAIL",
            recorded_by_employee=self.employee,
        )
        quotation.outcome_status = "WON"
        quotation.accepted_version = version
        quotation.save(update_fields=["outcome_status", "accepted_version", "updated_at"])
        return quotation, version, quote_line

    def quoted_payload(self, version, quote_line, *, quantity="6.0000", unit_price="10.0000"):
        payload = self.direct_payload(with_evidence=False, quantity=quantity, unit_price=unit_price)
        payload.update({
            "source_type": "QUOTATION",
            "source_quotation_version_id": str(version.pk),
            "direct_order_reason": "",
        })
        payload["lines"][0]["source_quotation_line_id"] = str(quote_line.pk)
        return payload

    def test_draft_can_save_without_address_but_confirmation_returns_stable_error(self):
        payload = self.direct_payload()
        payload["buyer_address_id"] = None
        created = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertIsNone(created.data["data"]["buyer_address_id"])

        blocked = self.client.post(
            f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(blocked.status_code, 400, blocked.data)
        self.assertEqual(blocked.data["error"]["code"], "BUYER_ADDRESS_REQUIRED")
        self.assertEqual(blocked.data["error"]["meta"]["recovery_action"], "EDIT_BUYER_ADDRESS")

    def test_order_rejects_address_from_another_buyer_entity(self):
        another_entity = CustomerTransactionEntity.objects.create(
            customer_account=self.customer,
            entity_code="ANOTHER_BUYER",
            legal_name="另一个买方主体",
        )
        another_address = CustomerEntityAddress.objects.create(
            transaction_entity=another_entity,
            address_code="ANOTHER_ADDRESS",
            country_code="CN",
            address_line1="其他地址",
        )
        payload = self.direct_payload()
        payload["buyer_address_id"] = str(another_address.pk)
        response = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("buyer_address_id", response.data["error"]["field_errors"])

    def test_confirmation_freezes_address_and_version_snapshot(self):
        confirmed = self.confirm_direct()
        order_data = confirmed.data["data"]
        self.assertEqual(order_data["confirmation_method_display"], "客户 PO")
        self.assertEqual(order_data["buyer_address_snapshot"]["address_line1"], "测试路 1 号")

        self.address.address_line1 = "客户后来修改的新地址"
        self.address.save(update_fields=["address_line1", "updated_at"])
        detail = self.client.get(f"/api/v1/sales-orders/{order_data['id']}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["data"]["buyer_address_snapshot"]["address_line1"], "测试路 1 号")
        snapshot = detail.data["data"]["versions"][0]["snapshot"]
        self.assertEqual(snapshot["buyer_address_snapshot"]["address_line1"], "测试路 1 号")
        self.assertIn("buyer_snapshot", snapshot)
        self.assertIn("seller_snapshot", snapshot)
        self.assertIn("terms_snapshot", snapshot)

    def test_quotation_context_carries_live_address_id_and_historical_snapshot(self):
        _quotation, version, _quote_line = self.quotation_context()
        response = self.client.get(
            "/api/v1/sales-orders/quotation-options/",
            {"quotation_version_id": str(version.pk)},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["buyer_address_id"], str(self.address.pk))
        self.assertEqual(response.data["data"]["buyer_address_snapshot"]["address_line1"], "测试路 1 号")

        self.address.archived_at = timezone.now()
        self.address.save(update_fields=["archived_at", "updated_at"])
        archived = self.client.get(
            "/api/v1/sales-orders/quotation-options/",
            {"quotation_version_id": str(version.pk)},
        )
        self.assertEqual(archived.status_code, 200, archived.data)
        self.assertIsNone(archived.data["data"]["buyer_address_id"])
        self.assertEqual(archived.data["data"]["buyer_address_snapshot"]["address_line1"], "测试路 1 号")

    def test_quotation_product_mapping_requires_one_exact_product(self):
        _quotation, version, quote_line = self.quotation_context()
        duplicate = ProductInformation.objects.create(
            product_number=f"{self.product.product_number}-DUP-{uuid4().hex[:6]}",
            product_type=self.product.product_type,
            product_code=f"DUP-{uuid4().hex[:8]}",
            category=self.product.category,
            product_name=self.product.product_name,
            specification="不同规格",
            unit=self.product.unit,
            product_item=self.product.product_item,
            warehouse_number=self.product.warehouse_number,
            warehouse_name=self.product.warehouse_name,
            scale=self.product.scale,
            status=self.product.status,
        )

        unique_spec = self.client.get(
            "/api/v1/sales-orders/quotation-options/",
            {"quotation_version_id": str(version.pk)},
        )
        self.assertEqual(unique_spec.status_code, 200, unique_spec.data)
        unique_line = unique_spec.data["data"]["lines"][0]
        self.assertEqual(unique_line["suggested_product_id"], str(self.product.pk))
        self.assertEqual(unique_line["suggested_product"]["product_name"], self.product.product_name)
        self.assertEqual(unique_line["suggested_product"]["specification"], self.product.specification)
        self.assertEqual(unique_line["product_mapping_status"], "MATCHED")
        self.assertEqual(unique_line["product_mapping_candidate_count"], 2)

        _quotation, ambiguous_version, _quote_line = self.quotation_context(
            specification="报价独有规格"
        )
        ambiguous = self.client.get(
            "/api/v1/sales-orders/quotation-options/",
            {"quotation_version_id": str(ambiguous_version.pk)},
        )
        ambiguous_line = ambiguous.data["data"]["lines"][0]
        self.assertIsNone(ambiguous_line["suggested_product_id"])
        self.assertEqual(ambiguous_line["product_mapping_status"], "AMBIGUOUS")
        self.assertEqual(ambiguous_line["product_mapping_candidate_count"], 2)

        _quotation, collision_version, _quote_line = self.quotation_context(
            product_description=duplicate.product_number,
            specification=duplicate.specification,
        )
        collision = self.client.get(
            "/api/v1/sales-orders/quotation-options/",
            {"quotation_version_id": str(collision_version.pk)},
        )
        collision_line = collision.data["data"]["lines"][0]
        self.assertIsNone(collision_line["suggested_product_id"])
        self.assertEqual(collision_line["product_mapping_status"], "UNMATCHED")

        duplicate.status = "INACTIVE"
        duplicate.save(update_fields=["status", "updated_at"])
        _quotation, mismatched_version, _quote_line = self.quotation_context(
            specification="报价独有规格"
        )
        mismatched = self.client.get(
            "/api/v1/sales-orders/quotation-options/",
            {"quotation_version_id": str(mismatched_version.pk)},
        )
        mismatched_line = mismatched.data["data"]["lines"][0]
        self.assertIsNone(mismatched_line["suggested_product_id"])
        self.assertEqual(mismatched_line["product_mapping_status"], "AMBIGUOUS")
        self.assertEqual(mismatched_line["product_mapping_candidate_count"], 1)

        _quotation, unmatched_version, _quote_line = self.quotation_context(
            product_description=f"未建档产品-{duplicate.pk}"
        )
        unmatched = self.client.get(
            "/api/v1/sales-orders/quotation-options/",
            {"quotation_version_id": str(unmatched_version.pk)},
        )
        unmatched_line = unmatched.data["data"]["lines"][0]
        self.assertIsNone(unmatched_line["suggested_product_id"])
        self.assertEqual(unmatched_line["product_mapping_status"], "UNMATCHED")
        self.assertEqual(unmatched_line["product_mapping_candidate_count"], 0)

    def test_direct_order_requires_evidence_then_can_create_production_order(self):
        without_evidence = self.client.post(
            "/api/v1/sales-orders/",
            self.direct_payload(with_evidence=False),
            format="json",
        )
        self.assertEqual(without_evidence.status_code, 201, without_evidence.data)
        blocked = self.client.post(
            f"/api/v1/sales-orders/{without_evidence.data['data']['id']}/confirm/",
            {},
            format="json",
            HTTP_IF_MATCH=without_evidence["ETag"],
        )
        self.assertEqual(blocked.status_code, 400, blocked.data)

        created = self.create_direct()
        confirmed = self.client.post(
            f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["data"]["status"], "CONFIRMED")

        batch_line_id = confirmed.data["data"]["delivery_batches"][0]["lines"][0]["id"]
        production_payload = {
            "request_key": str(uuid4()),
            "delivery_batch_line_id": batch_line_id,
            "quantity": 10,
            "planned_start_date": timezone.localdate().isoformat(),
            "planned_end_date": timezone.localdate().isoformat(),
            "production_priority": "NORMAL",
            "planner_id": str(self.employee.pk),
        }
        production = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            production_payload,
            format="json",
        )
        self.assertEqual(production.status_code, 201, production.data)
        self.assertRegex(production.data["data"]["task_number"], r"^HT[0-9]{5}$")
        self.assertEqual(production.data["data"]["source_sales_order_number"], confirmed.data["data"]["order_number"])
        self.assertFalse(production.data["data"]["is_historical_unlinked"])
        self.assertEqual(production.data["data"]["special_requirements_html"], "")
        self.assertEqual(production.data["data"]["products"][0]["special_requirements"], "按确认样")
        self.assertEqual(
            ProductionTask.objects.get(pk=production.data["data"]["id"]).special_requirements_html,
            "",
        )
        retried = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            production_payload,
            format="json",
        )
        self.assertEqual(retried.status_code, 201, retried.data)
        self.assertEqual(retried.data["data"]["id"], production.data["data"]["id"])
        self.assertEqual(ProductionTask.objects.filter(source_request_key=production_payload["request_key"]).count(), 1)
        changed_retry = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {**production_payload, "quantity": 9},
            format="json",
        )
        self.assertEqual(changed_retry.status_code, 409, changed_retry.data)

    def test_legacy_requirement_snapshot_is_hidden_without_changing_saved_content(self):
        snapshot = {"inquiry_number": "INQ-TEST", "items": [{"line_number": 1, "target_unit_price": "40.0000"}]}
        created = self.create_direct(customer_requirement_snapshot=snapshot)
        confirmed = self.client.post(
            f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        batch_line_id = confirmed.data["data"]["delivery_batches"][0]["lines"][0]["id"]
        production = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {"delivery_batch_line_id": batch_line_id, "quantity": 10},
            format="json",
        )
        self.assertEqual(production.status_code, 201, production.data)
        task = ProductionTask.objects.get(pk=production.data["data"]["id"])
        detail_url = f"/api/v1/production-tasks/{task.pk}/"

        legacy_value = json.dumps(snapshot, ensure_ascii=False)
        task.special_requirements_html = legacy_value
        task.save(update_fields=["special_requirements_html"])
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["special_requirements_html"], "")
        task.refresh_from_db()
        self.assertEqual(task.special_requirements_html, legacy_value)

        changed_date = (timezone.localdate() + timedelta(days=1)).isoformat()
        updated = self.client.patch(
            detail_url,
            {"delivery_date": changed_date},
            format="json",
            HTTP_IF_MATCH=response["ETag"],
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["data"]["special_requirements_html"], "")
        task.refresh_from_db()
        self.assertEqual(task.special_requirements_html, legacy_value)

        for value in ("<p>人工填写的生产要求</p>", '{"memo": "人工填写"}', '{"items":'):
            task.special_requirements_html = value
            task.save(update_fields=["special_requirements_html"])
            response = self.client.get(detail_url)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["data"]["special_requirements_html"], value)

    def test_legacy_requirement_snapshot_stays_hidden_after_sales_order_snapshot_changes(self):
        snapshot = {"inquiry_number": "INQ-ORIGINAL", "items": [{"line_number": 1}]}
        _quotation, version, quote_line = self.quotation_context(customer_requirement_snapshot=snapshot)
        payload = self.quoted_payload(version, quote_line)
        payload["customer_requirement_snapshot"] = snapshot
        created = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        confirmed = self.client.post(
            f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        batch_line_id = confirmed.data["data"]["delivery_batches"][0]["lines"][0]["id"]
        production = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {"delivery_batch_line_id": batch_line_id, "quantity": 6},
            format="json",
        )
        self.assertEqual(production.status_code, 201, production.data)
        task = ProductionTask.objects.select_related("sales_order__source_quotation_version").get(
            pk=production.data["data"]["id"]
        )
        self.assertEqual(task.sales_order.source_quotation_version.customer_requirement_snapshot, snapshot)

        legacy_value = json.dumps(snapshot, ensure_ascii=False)
        task.special_requirements_html = legacy_value
        task.save(update_fields=["special_requirements_html"])
        order = task.sales_order
        order.customer_requirement_snapshot = {"delivery_requirement": "后来修改的订单要求"}
        order.save(update_fields=["customer_requirement_snapshot"])

        detail_url = f"/api/v1/production-tasks/{task.pk}/"
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["special_requirements_html"], "")
        task.refresh_from_db()
        self.assertEqual(task.special_requirements_html, legacy_value)

        manual_json = '{"memo": "人工填写"}'
        task.special_requirements_html = manual_json
        task.save(update_fields=["special_requirements_html"])
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["special_requirements_html"], manual_json)

    def test_confirmed_sales_batch_can_create_one_task_with_independent_color_lines(self):
        confirmed = self.confirm_direct()
        batch = confirmed.data["data"]["delivery_batches"][0]
        batch_line_id = batch["lines"][0]["id"]
        first_color = ProductColor.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        second_color = ProductColor.objects.create(
            color_card="TEST-CARD-B",
            color_code="TEST-COLOR-B",
            color_name="测试颜色B",
        )

        created = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {
                "delivery_batch_id": batch["id"],
                "lines": [
                    {
                        "delivery_batch_line_id": batch_line_id,
                        "product_color_id": str(first_color.pk),
                        "quantity": 6,
                    },
                    {
                        "delivery_batch_line_id": batch_line_id,
                        "product_color_id": str(second_color.pk),
                        "quantity": 4,
                    },
                ],
                "production_priority": "NORMAL",
                "planner_id": str(self.employee.pk),
            },
            format="json",
        )

        self.assertEqual(created.status_code, 201, created.data)
        data = created.data["data"]
        self.assertEqual(len(data["products"]), 2)
        self.assertEqual([row["quantity"] for row in data["products"]], [6, 4])
        self.assertEqual(
            {row["product_color_id"] for row in data["products"]},
            {str(first_color.pk), str(second_color.pk)},
        )
        self.assertEqual(
            {row["source_delivery_batch_line_id"] for row in data["products"]},
            {batch_line_id},
        )
        self.assertEqual(data["total_quantity"], 10)
        self.assertEqual(data["batch_total_quantity"], Decimal("10.0000"))
        self.assertEqual(ProductionTask.objects.filter(pk=data["id"]).count(), 1)
        refreshed_order = self.client.get(f"/api/v1/sales-orders/{confirmed.data['data']['id']}/")
        self.assertEqual(refreshed_order.status_code, 200, refreshed_order.data)
        refreshed_line = refreshed_order.data["data"]["delivery_batches"][0]["lines"][0]
        self.assertEqual(Decimal(refreshed_line["allocated_quantity"]), Decimal("10"))
        self.assertEqual(Decimal(refreshed_line["maximum_quantity"]), Decimal("10.3"))
        self.assertEqual(Decimal(refreshed_line["remaining_quantity"]), Decimal("0.3"))

        submitted = self.client.post(
            f"/api/v1/production-tasks/{data['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        today = timezone.localdate().isoformat()
        approved = self.client.post(
            f"/api/v1/production-tasks/{data['id']}/pmc-decision/",
            {"decision": "CONFIRM", "planned_start_date": today, "planned_end_date": today},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(approved.status_code, 200, approved.data)

        task = ProductionTask.objects.get(pk=data["id"])
        product_lines = list(task.products.select_related("product__category").order_by("line_number"))
        for index, product_line in enumerate(product_lines, start=1):
            Bom.objects.create(
                bom_number=f"BOM-SALES-COLOR-{index}",
                production_task=task,
                product_line=product_line,
                version_number=1,
                creation_method=BomCreationMethod.BLANK,
                status=BomStatus.VERIFIED if index == 1 else BomStatus.PENDING_CONFIRMATION,
                product_number_snapshot=product_line.product_number_snapshot,
                product_code_snapshot=product_line.product_code_snapshot,
                product_name_snapshot=product_line.product_name_snapshot,
                specification_snapshot=product_line.specification_snapshot,
                product_category_snapshot=product_line.product.category.category_name,
                order_quantity=product_line.quantity,
                created_by_employee=self.employee,
            )

        detail = self.client.get(f"/api/v1/production-tasks/{data['id']}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(len(detail.data["data"]["current_boms"]), 2)
        self.assertEqual(
            {item["product_line_id"] for item in detail.data["data"]["current_boms"]},
            {str(item.pk) for item in product_lines},
        )
        self.assertEqual(detail.data["data"]["pmc_confirmation"]["actor_name"], self.employee.display_name)
        self.assertTrue(detail.data["data"]["pmc_confirmation"]["confirmed_at"])
        timeline_actions = [item["action"] for item in detail.data["data"]["audit_timeline"]]
        self.assertIn("CREATED_FROM_SALES_ORDER", timeline_actions)
        self.assertIn("SUBMITTED", timeline_actions)
        self.assertIn("CONFIRMED", timeline_actions)

        blocked = self.client.post(
            f"/api/v1/production-tasks/{data['id']}/start/",
            {"start_waiver_reason": "测试环境允许先生产"},
            format="json",
            HTTP_IF_MATCH=approved["ETag"],
        )
        self.assertEqual(blocked.status_code, 409, blocked.data)
        self.assertIn("先完成计划排产", blocked.data["error"]["message"])

        Bom.objects.filter(product_line=product_lines[1]).update(status=BomStatus.VERIFIED)
        still_blocked = self.client.post(
            f"/api/v1/production-tasks/{data['id']}/start/",
            {"start_waiver_reason": "测试环境允许先生产"},
            format="json",
            HTTP_IF_MATCH=approved["ETag"],
        )
        self.assertEqual(still_blocked.status_code, 409, still_blocked.data)
        self.assertEqual(
            ProductionTask.objects.get(pk=data["id"]).status,
            ProductionTaskStatus.READY,
        )

    def test_production_creation_rejects_inaccessible_sales_order(self):
        confirmed = self.confirm_direct()
        batch_line_id = confirmed.data["data"]["delivery_batches"][0]["lines"][0]["id"]
        user_model = get_user_model()
        outsider_user = user_model.objects.create_user(username="production_outsider", password="test")
        outsider_user.user_permissions.add(Permission.objects.get(codename="add_productiontask"))
        Employee.objects.create(
            user=outsider_user,
            employee_code="PRODUCTION_OUTSIDER",
            display_name="无客户范围生产员工",
        )
        self.client.force_authenticate(outsider_user)

        response = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {"delivery_batch_line_id": batch_line_id, "quantity": 1},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(ProductionTask.objects.filter(sales_order_id=confirmed.data["data"]["id"]).count(), 0)

    def test_multi_color_creation_rejects_duplicates_mixed_payload_and_over_allocation(self):
        confirmed = self.confirm_direct()
        batch = confirmed.data["data"]["delivery_batches"][0]
        batch_line_id = batch["lines"][0]["id"]
        color = ProductColor.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        task_count = ProductionTask.objects.count()
        base_line = {
            "delivery_batch_line_id": batch_line_id,
            "product_color_id": str(color.pk),
            "quantity": 5,
        }

        duplicate = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {"delivery_batch_id": batch["id"], "lines": [base_line, base_line]},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertEqual(ProductionTask.objects.count(), task_count)

        mixed = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {
                "delivery_batch_line_id": batch_line_id,
                "quantity": 1,
                "delivery_batch_id": batch["id"],
                "lines": [base_line],
            },
            format="json",
        )
        self.assertEqual(mixed.status_code, 400, mixed.data)
        self.assertEqual(ProductionTask.objects.count(), task_count)

        second_color = ProductColor.objects.create(
            color_card="TEST-CARD-OVER",
            color_code="TEST-COLOR-OVER",
            color_name="测试超量颜色",
        )
        over_allocated = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {
                "delivery_batch_id": batch["id"],
                "lines": [
                    {**base_line, "quantity": 6},
                    {
                        "delivery_batch_line_id": batch_line_id,
                        "product_color_id": str(second_color.pk),
                        "quantity": 5,
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(over_allocated.status_code, 400, over_allocated.data)
        self.assertEqual(ProductionTask.objects.count(), task_count)

    def test_production_order_draft_allows_empty_plan_dates_but_pmc_confirmation_requires_them(self):
        confirmed = self.confirm_direct()
        batch_line_id = confirmed.data["data"]["delivery_batches"][0]["lines"][0]["id"]
        created = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {
                "delivery_batch_line_id": batch_line_id,
                "quantity": 10,
                "production_priority": "NORMAL",
                "planner_id": str(self.employee.pk),
            },
            format="json",
        )

        self.assertEqual(created.status_code, 201, created.data)
        self.assertIsNone(created.data["data"]["planned_start_date"])
        self.assertIsNone(created.data["data"]["planned_end_date"])

        submitted = self.client.post(
            f"/api/v1/production-tasks/{created.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)

        missing_etag = self.client.post(
            f"/api/v1/production-tasks/{created.data['data']['id']}/pmc-decision/",
            {"decision": "RETURN", "reason": "并发校验"},
            format="json",
        )
        self.assertEqual(missing_etag.status_code, 428, missing_etag.data)

        missing_dates = self.client.post(
            f"/api/v1/production-tasks/{created.data['data']['id']}/pmc-decision/",
            {"decision": "CONFIRM"},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(missing_dates.status_code, 400, missing_dates.data)
        self.assertIn("计划开始", missing_dates.data["error"]["message"])

        today = timezone.localdate().isoformat()
        approved = self.client.post(
            f"/api/v1/production-tasks/{created.data['data']['id']}/pmc-decision/",
            {
                "decision": "CONFIRM",
                "planned_start_date": today,
                "planned_end_date": today,
            },
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["data"]["status"], ProductionTaskStatus.READY)

    def test_sales_order_production_task_remains_editable_while_in_production(self):
        confirmed = self.confirm_direct()
        batch_line_id = confirmed.data["data"]["delivery_batches"][0]["lines"][0]["id"]
        created = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {
                "delivery_batch_line_id": batch_line_id,
                "quantity": 10,
                "planned_start_date": timezone.localdate().isoformat(),
                "planned_end_date": timezone.localdate().isoformat(),
                "production_priority": "NORMAL",
                "planner_id": str(self.employee.pk),
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        task = ProductionTask.objects.get(pk=created.data["data"]["id"])
        task.status = ProductionTaskStatus.IN_PRODUCTION
        task.save(update_fields=["status", "updated_at"])

        current = self.client.get(f"/api/v1/production-tasks/{task.pk}/")
        self.assertEqual(current.status_code, 200, current.data)
        task_data = current.data["data"]
        old_product_line = task_data["products"][0]
        bypass = self.client.patch(
            f"/api/v1/production-tasks/{task.pk}/",
            {"order_number": "BYPASS-SALES-SNAPSHOT"},
            format="json",
            HTTP_IF_MATCH=current["ETag"],
        )
        self.assertEqual(bypass.status_code, 400, bypass.data)
        task.refresh_from_db()
        self.assertEqual(task.order_number, task_data["order_number"])
        replacement = ProductInformation.objects.create(
            product_number="SALES-TASK-REPLACEMENT-001",
            product_code="SALES-TASK-REPLACEMENT-CODE",
            category=self.product.category,
            product_name="销售来源生产订单替换产品",
            specification="替换规格",
            unit=self.product.unit,
            product_item=self.product.product_item,
            scale=self.product.scale,
            status="ACTIVE",
        )
        color = ProductColor.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        self.assertIsNotNone(color)
        payload = {
            "products": [
                {
                    "client_key": old_product_line["id"],
                    "product_id": str(self.product.pk),
                    "product_color_id": str(color.pk),
                    "color_code": color.color_code,
                    "quantity": 10,
                    "unit_id": str(self.product.unit_id),
                    "currency_id": task_data["currency_id"],
                    "unit_price": old_product_line["unit_price"],
                    "exchange_rate": old_product_line["exchange_rate"],
                    "special_requirements": "生产中仍可维护",
                    "packaging_method": "生产中更新包装要求",
                    "retained_image_ids": [],
                    "details": [
                        {
                            "client_key": "sales-task-detail-1",
                            "template_key": "material",
                            "detail_type": "材料",
                            "category_label": "管材",
                            "is_selected": True,
                            "description": "按销售来源产品复核",
                        }
                    ],
                }
            ],
            "delivery_batches": [
                {
                    "quantity": batch["quantity"],
                    "delivery_date": batch["delivery_date"],
                    "note": batch["note"],
                }
                for batch in task_data["delivery_batches"]
            ],
        }
        updated = self.client.patch(
            f"/api/v1/production-tasks/{task.pk}/",
            payload,
            format="json",
            HTTP_IF_MATCH=current["ETag"],
        )

        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["data"]["status"], ProductionTaskStatus.IN_PRODUCTION)
        self.assertEqual(updated.data["data"]["products"][0]["product_id"], str(self.product.pk))
        payload["products"][0]["product_id"] = str(replacement.pk)
        payload["products"][0]["unit_id"] = str(replacement.unit_id)
        replaced = self.client.patch(
            f"/api/v1/production-tasks/{task.pk}/",
            payload,
            format="json",
            HTTP_IF_MATCH=updated["ETag"],
        )
        self.assertEqual(replaced.status_code, 400, replaced.data)

        payload["products"][0]["product_id"] = str(self.product.pk)
        payload["products"][0]["unit_id"] = str(self.product.unit_id)
        payload["products"][0]["quantity"] = 11
        over_allocated = self.client.patch(
            f"/api/v1/production-tasks/{task.pk}/",
            payload,
            format="json",
            HTTP_IF_MATCH=updated["ETag"],
        )
        self.assertEqual(over_allocated.status_code, 400, over_allocated.data)
        task.refresh_from_db()
        self.assertEqual(str(task.sales_order_id), confirmed.data["data"]["id"])

    def test_quote_partial_conversion_prevents_draft_over_reservation(self):
        _quotation, version, quote_line = self.quotation_context(quantity="10.0000")
        first = self.client.post(
            "/api/v1/sales-orders/",
            self.quoted_payload(version, quote_line, quantity="6.0000"),
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post(
            "/api/v1/sales-orders/",
            self.quoted_payload(version, quote_line, quantity="5.0000"),
            format="json",
        )
        self.assertEqual(second.status_code, 400, second.data)

        options = self.client.get(
            "/api/v1/sales-orders/quotation-options/",
            {"quotation_version_id": str(version.pk)},
        )
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(Decimal(options.data["data"]["lines"][0]["remaining_quantity"]), Decimal("4"))

    def test_order_can_split_quantity_into_multiple_delivery_dates(self):
        payload = self.direct_payload(quantity="10.0000")
        payload["delivery_batches"] = [
            {
                "planned_delivery_date": timezone.localdate().isoformat(),
                "notes": "第一批",
                "lines": [{"sales_order_line_client_key": "line-1", "quantity": "4.0000"}],
            },
            {
                "planned_delivery_date": (timezone.localdate() + timedelta(days=14)).isoformat(),
                "notes": "第二批",
                "lines": [{"sales_order_line_client_key": "line-1", "quantity": "6.0000"}],
            },
        ]
        created = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        confirmed = self.client.post(
            f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["data"]["delivery_batch_count"], 2)
        self.assertEqual(
            [Decimal(batch["lines"][0]["quantity"]) for batch in confirmed.data["data"]["delivery_batches"]],
            [Decimal("4"), Decimal("6")],
        )

    def test_lower_quote_price_can_be_confirmed_without_extra_approval(self):
        _quotation, version, quote_line = self.quotation_context(quantity="20.0000", unit_price="10.0000")
        payload = self.quoted_payload(version, quote_line, quantity="5.0000", unit_price="9.0000")
        created = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        confirmed = self.client.post(
            f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["data"]["status"], "CONFIRMED")
        self.assertEqual(confirmed.data["data"]["lines"][0]["price_exceptions"], [])

    def test_confirmed_change_creates_version_and_requires_pmc_after_production(self):
        confirmed = self.confirm_direct()
        order_id = confirmed.data["data"]["id"]
        first_line_id = confirmed.data["data"]["lines"][0]["id"]
        first_batch_id = confirmed.data["data"]["delivery_batches"][0]["id"]

        hidden_customer_change = self.client.post(
            f"/api/v1/sales-orders/{order_id}/confirmed-change/",
            {
                "order": self.confirmed_change_payload(confirmed, unit_price="21.0000"),
                "change_reason": "尝试把客户价格变更标成内部变更",
                "customer_facing_change": False,
                "change_evidence_file_id": None,
                "pmc_impact_confirmed": False,
            },
            format="json",
            HTTP_IF_MATCH=confirmed["ETag"],
        )
        self.assertEqual(hidden_customer_change.status_code, 400, hidden_customer_change.data)

        changed_before_production = self.client.post(
            f"/api/v1/sales-orders/{order_id}/confirmed-change/",
            {
                "order": self.confirmed_change_payload(confirmed, unit_price="21.0000"),
                "change_reason": "客户确认调整成交价",
                "customer_facing_change": True,
                "change_evidence_file_id": str(self.evidence.pk),
                "pmc_impact_confirmed": False,
            },
            format="json",
            HTTP_IF_MATCH=confirmed["ETag"],
        )
        self.assertEqual(changed_before_production.status_code, 200, changed_before_production.data)
        self.assertEqual(changed_before_production.data["data"]["version_number"], 2)
        self.assertEqual(len(changed_before_production.data["data"]["versions"]), 2)

        batch_line_id = changed_before_production.data["data"]["delivery_batches"][0]["lines"][0]["id"]
        production = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {
                "delivery_batch_line_id": batch_line_id,
                "quantity": 10,
                "planned_start_date": timezone.localdate().isoformat(),
                "planned_end_date": timezone.localdate().isoformat(),
                "production_priority": "NORMAL",
                "planner_id": str(self.employee.pk),
            },
            format="json",
        )
        self.assertEqual(production.status_code, 201, production.data)
        current = self.client.get(f"/api/v1/sales-orders/{order_id}/")
        self.assertEqual(current.status_code, 200, current.data)
        changed_payload = self.confirmed_change_payload(current, quantity="12.0000", unit_price="21.0000")

        missing_pmc = self.client.post(
            f"/api/v1/sales-orders/{order_id}/confirmed-change/",
            {
                "order": changed_payload,
                "change_reason": "客户增加两件",
                "customer_facing_change": True,
                "change_evidence_file_id": str(self.evidence.pk),
                "pmc_impact_confirmed": False,
            },
            format="json",
            HTTP_IF_MATCH=current["ETag"],
        )
        self.assertEqual(missing_pmc.status_code, 400, missing_pmc.data)

        changed_after_production = self.client.post(
            f"/api/v1/sales-orders/{order_id}/confirmed-change/",
            {
                "order": changed_payload,
                "change_reason": "客户增加两件",
                "customer_facing_change": True,
                "change_evidence_file_id": str(self.evidence.pk),
                "pmc_impact_confirmed": True,
            },
            format="json",
            HTTP_IF_MATCH=current["ETag"],
        )
        self.assertEqual(changed_after_production.status_code, 200, changed_after_production.data)
        self.assertEqual(changed_after_production.data["data"]["version_number"], 3)
        self.assertEqual(changed_after_production.data["data"]["lines"][0]["id"], first_line_id)
        self.assertEqual(changed_after_production.data["data"]["delivery_batches"][0]["id"], first_batch_id)

    def test_confirmed_internal_change_preserves_frozen_buyer_snapshots_after_master_data_changes(self):
        confirmed = self.confirm_direct()
        order_id = confirmed.data["data"]["id"]
        original_buyer_name = confirmed.data["data"]["buyer_snapshot"]["legal_name"]
        original_address = confirmed.data["data"]["buyer_address_snapshot"]["address_line1"]

        self.entity.legal_name = "外部已更新买方法人"
        self.entity.save(update_fields=["legal_name", "updated_at"])
        self.address.address_line1 = "外部已更新地址 99 号"
        self.address.save(update_fields=["address_line1", "updated_at"])

        payload = self.confirmed_change_payload(confirmed)
        payload["customer_confirmed_at"] = confirmed.data["data"]["customer_confirmed_at"]
        changed = self.client.post(
            f"/api/v1/sales-orders/{order_id}/confirmed-change/",
            {
                "order": payload,
                "change_reason": "内部备注变更，不刷新客户快照",
                "customer_facing_change": False,
                "change_evidence_file_id": None,
                "pmc_impact_confirmed": False,
            },
            format="json",
            HTTP_IF_MATCH=confirmed["ETag"],
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data["data"]["buyer_snapshot"]["legal_name"], original_buyer_name)
        self.assertEqual(changed.data["data"]["buyer_address_snapshot"]["address_line1"], original_address)

    def test_confirmed_quote_change_allows_lower_price_without_extra_approval(self):
        _quotation, version, quote_line = self.quotation_context(quantity="10.0000", unit_price="10.0000")
        created = self.client.post(
            "/api/v1/sales-orders/",
            self.quoted_payload(version, quote_line, quantity="10.0000", unit_price="10.0000"),
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        confirmed = self.client.post(
            f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        order_id = confirmed.data["data"]["id"]
        line_id = confirmed.data["data"]["lines"][0]["id"]
        detail = self.client.get(f"/api/v1/sales-orders/{order_id}/")
        payload = self.quoted_payload(version, quote_line, quantity="10.0000", unit_price="9.0000")
        payload["lines"][0]["client_key"] = line_id
        payload["delivery_batches"][0]["client_key"] = detail.data["data"]["delivery_batches"][0]["id"]
        payload["delivery_batches"][0]["lines"][0]["sales_order_line_client_key"] = line_id
        changed = self.client.post(
            f"/api/v1/sales-orders/{order_id}/confirmed-change/",
            {
                "order": payload,
                "change_reason": "客户确认调整价格",
                "customer_facing_change": True,
                "change_evidence_file_id": str(self.evidence.pk),
                "pmc_impact_confirmed": False,
            },
            format="json",
            HTTP_IF_MATCH=detail["ETag"],
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(Decimal(changed.data["data"]["lines"][0]["unit_price"]), Decimal("9"))
