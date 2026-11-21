"""材料收发审核回归：真实 PostgreSQL、接口权限、库存事务及并发。"""
from copy import deepcopy
from decimal import Decimal
import threading
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.material_catalog.models import MaterialCatalog
from apps.organizations.models import Employee
from apps.reference_data.models import ProductionUnit, ProductColor
from ..models import MaterialTransfer, MaterialTransferLine, PublicStockBalance, PublicStockMovement, Warehouse, WarehouseZone


class TransferFixture:
    client_class = APIClient

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="transfer_audit")
        self.employee = Employee.objects.create(user=self.user, employee_code="TRANSFER_AUDIT", display_name="收发审核员工")
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label__in=["inventory", "material_catalog"]))
        self.client.force_authenticate(self.user)
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name="PCS", defaults={"unit_code": "TAPCS"})
        self.warehouse = Warehouse.objects.create(warehouse_number="TA1", warehouse_name="审核材料仓", warehouse_type="MATERIAL")
        self.zone = WarehouseZone.objects.create(warehouse=self.warehouse, zone_name="主库区")
        self.catalog = MaterialCatalog.objects.create(category_key="HARDWARE", template_key="HARDWARE", name="审核五金", base_warehouse=self.warehouse)

    def item(self, *, catalog=None, quantity="2.0000", zone=None):
        catalog = catalog or self.catalog
        catalog.refresh_from_db()
        return {"material_catalog_id": str(catalog.pk), "zone_id": str((zone or self.zone).pk), "quantity": quantity,
                "material_selection": {"catalog_version": catalog.updated_at.isoformat(), "scope": "BASE",
                    "processing_state": "RAW", "unit_id": str(self.unit.pk), "attributes": {"specification": "M8"}}}

    def payload(self, *items, direction="IN"):
        return {"client_request_id": str(uuid4()), "direction": direction, "transfer_date": str(timezone.localdate()),
                "remark": "审核回归", "items": list(items or [self.item()])}

    def post(self, payload, client=None):
        return (client or self.client).post("/api/v1/material-transfers/", payload, format="json")


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=False)
class MaterialTransferAuditTests(TransferFixture, ScopedActorMixin, APITestCase):
    def test_inbound_transfer_appears_in_shared_receipt_records_and_outbound_does_not(self):
        received = self.post(self.payload())
        self.assertEqual(received.status_code, 201, received.data)
        outgoing = self.post(self.payload(self.item(quantity='1'), direction='OUT'))
        self.assertEqual(outgoing.status_code, 201, outgoing.data)
        inbound, outbound = received.data['data'], outgoing.data['data']
        root = '/api/v1/material-inventory/purchase-receipt-records/'
        filters = {'section': 'B', 'status': 'CONFIRMED', 'q': inbound['transfer_number']}
        listing = self.client.get(root, filters)
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(listing.data['total'], 1)
        record = listing.data['data'][0]
        self.assertEqual((str(record['id']), record['source'], record['status'], record['purchase_order_number']),
                         (inbound['id'], 'TRANSFER', 'CONFIRMED', ''))
        self.assertFalse(record['can_quality_confirm'])
        self.assertEqual(record['line_count'], 1)
        self.assertEqual(record['production_task_number'], '')
        self.assertEqual(record['material_section_display'], '五金件、塑料件、包材')
        detail = self.client.get(root + f"{inbound['id']}/", {'source': 'TRANSFER'})
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data['data']['lines'], inbound['lines'])
        self.assertEqual(self.client.get(root + f"{outbound['id']}/", {'source': 'TRANSFER'}).status_code, 404)
        self.assertFalse(self.client.get(root, {**filters, 'status': 'PENDING_QUALITY'}).data['data'])

        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='inventory', codename='view_material_receipt'))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get(root, filters).data['total'], 1)
        self.scoped_actor()
        self.grant('inventory.quality_confirm_material', 'MODULE')
        self.assertEqual(self.client.get(root, filters).data['total'], 0)
        self.assertEqual(self.client.get(root + f"{inbound['id']}/", {'source': 'TRANSFER'}).status_code, 404)

    def test_followed_cannot_read_manual_transfers_with_either_permission_switch(self):
        self.assertEqual(self.post(self.payload()).status_code, 201)
        self.scoped_actor()
        self.grant("inventory.view_material_receipt", "FOLLOWED")
        for enabled in (False, True):
            with self.subTest(sales_access=enabled), override_settings(SALES_ACCESS_ENABLED=enabled):
                self.client.force_authenticate(get_user_model().objects.get(pk=self.scope_user.pk))
                self.assertEqual(self.client.get("/api/v1/material-transfers/").status_code, 403)
        self.grant("inventory.view_material_receipt", "MODULE")
        response = self.client.get("/api/v1/material-transfers/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["data"]), 1)

    def test_oversized_later_outbound_rolls_back_all_lines(self):
        self.assertEqual(self.post(self.payload(self.item(quantity="3"))).status_code, 201)
        response = self.post(self.payload(self.item(quantity="1"), self.item(quantity="3"), direction="OUT"))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(PublicStockBalance.objects.get().quantity, Decimal("3"))
        self.assertEqual(MaterialTransfer.objects.count(), 1)
        self.assertEqual(MaterialTransferLine.objects.count(), 1)
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_default_warehouse_cannot_be_replaced_by_another_material_warehouse(self):
        other = Warehouse.objects.create(warehouse_number="TA2", warehouse_name="另一材料仓", warehouse_type="MATERIAL")
        zone = WarehouseZone.objects.create(warehouse=other, zone_name="主库区")
        response = self.post(self.payload(self.item(zone=zone)))
        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(MaterialTransfer.objects.exists())
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(self.catalog.attribute_values.exists())

    def test_missing_default_keeps_explicit_material_warehouse_selection(self):
        self.catalog.base_warehouse = None
        self.catalog.save(update_fields=["base_warehouse"])
        self.assertEqual(self.post(self.payload()).status_code, 201)
        self.assertEqual(PublicStockBalance.objects.get().zone_id, self.zone.pk)

    def test_disabled_default_is_preserved_for_display_and_rejected_on_submit(self):
        self.warehouse.status = "DISABLED"
        self.warehouse.save(update_fields=["status"])
        response = self.client.get(f"/api/v1/material-inbound-sources/{self.catalog.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["base_warehouse_id"], str(self.warehouse.pk))
        self.assertEqual(self.post(self.payload()).status_code, 409)
        self.assertFalse(MaterialTransfer.objects.exists())

    def test_invalid_default_type_is_not_silently_erased(self):
        self.warehouse.warehouse_type = "SEMI_FINISHED"
        self.warehouse.save(update_fields=["warehouse_type"])
        response = self.client.get(f"/api/v1/material-inbound-sources/{self.catalog.pk}/")
        self.assertEqual(response.data["data"]["base_warehouse_id"], str(self.warehouse.pk))
        self.assertEqual(self.post(self.payload()).status_code, 409)
        self.assertFalse(MaterialTransfer.objects.exists())

    def test_operator_comes_from_current_session_and_write_requires_csrf(self):
        session_client = APIClient(enforce_csrf_checks=True)
        session_client.force_login(self.user)
        self.assertEqual(self.post(self.payload(), session_client).status_code, 403)
        payload = self.payload()
        payload["operated_by_employee"] = str(uuid4())
        response = self.post(payload)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(MaterialTransfer.objects.get().operated_by_employee_id, self.employee.pk)

    def test_whole_unit_and_disabled_unit_are_rejected_without_writes(self):
        whole, _ = ProductionUnit.objects.get_or_create(unit_name="套", defaults={"unit_code": "TASET"})
        item = self.item(quantity="1.5")
        item["material_selection"]["unit_id"] = str(whole.pk)
        response = self.post(self.payload(item))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("数量必须为整数", response.data["error"]["message"])
        self.unit.status = "INACTIVE"
        self.unit.save(update_fields=["status"])
        response = self.post(self.payload())
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("单位已停用或归档", response.data["error"]["message"])
        self.assertFalse(MaterialTransfer.objects.exists())

    def test_same_color_name_with_distinct_color_cards_keeps_separate_stock(self):
        fabric = MaterialCatalog.objects.create(category_key="FABRIC", template_key="FABRIC", name="审核布料", base_warehouse=self.warehouse)
        meter, _ = ProductionUnit.objects.get_or_create(unit_name="米", defaults={"unit_code": "TAM"})
        colors = [ProductColor.objects.create(color_card="审核色卡", color_code=code, color_name="同名蓝") for code in ("A", "B")]
        items = []
        for color in colors:
            item = self.item(catalog=fabric)
            item["material_selection"].update({"unit_id": str(meter.pk), "product_color_id": str(color.pk),
                "color_card": color.color_card, "color_code": color.color_code, "color_name": color.color_name,
                "attributes": {"material": "涤纶", "fabric_spec": "600D", "width": "150", "color": color.color_name}})
            items.append(item)
        response = self.post(self.payload(*items))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(PublicStockBalance.objects.count(), 2)
        self.assertEqual({line.material_selection_snapshot["product_color_id"] for line in MaterialTransferLine.objects.all()}, {str(color.pk) for color in colors})


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=False)
class MaterialTransferConcurrencyTests(TransferFixture, TransactionTestCase):
    serialized_rollback = True

    def concurrent(self, *calls):
        results, failures = [], []

        def run(call):
            connections.close_all()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                    cursor.execute("SET statement_timeout = '15s'")
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
                results.append(call(client))
            except Exception as error:
                failures.append(f"{type(error).__name__}: {error}")
            finally:
                connections.close_all()

        workers = [threading.Thread(target=run, args=(call,)) for call in calls]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=20)
        self.assertFalse(any(worker.is_alive() for worker in workers), "并发请求未结束")
        self.assertEqual(failures, [])
        return results

    def test_overlapping_retry_waits_and_returns_the_same_transfer(self):
        payload = self.payload()
        inserted, retry_lock_attempted = threading.Event(), threading.Event()

        def first(client):
            def observe(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                if sql.startswith(f'INSERT INTO "{MaterialTransfer._meta.db_table}"'):
                    inserted.set()
                    self.assertTrue(retry_lock_attempted.wait(6), "重试没有尝试请求锁")
                return result
            with connections["default"].execute_wrapper(observe):
                response = self.post(payload, client)
            return response.status_code, response.data

        def retry(client):
            self.assertTrue(inserted.wait(6), "首请求没有写入收发单")
            def observe(execute, sql, params, many, context):
                if "pg_advisory_xact_lock(" in sql:
                    retry_lock_attempted.set()
                return execute(sql, params, many, context)
            with connections["default"].execute_wrapper(observe):
                response = self.post(deepcopy(payload), client)
            return response.status_code, response.data

        results = self.concurrent(first, retry)
        self.assertEqual([row[0] for row in results], [201, 201], results)
        self.assertEqual(results[0][1]["data"]["id"], results[1][1]["data"]["id"])
        self.assertEqual(MaterialTransfer.objects.count(), 1)
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        self.assertEqual(PublicStockBalance.objects.get().quantity, Decimal("2"))

    def simultaneous_catalog_requests(self, *payloads):
        barrier = threading.Barrier(len(payloads))
        def call(payload):
            def submit(client):
                first_catalog_lock = True
                def observe(execute, sql, params, many, context):
                    nonlocal first_catalog_lock
                    if first_catalog_lock and f'FROM "{MaterialCatalog._meta.db_table}"' in sql and "FOR UPDATE" in sql:
                        first_catalog_lock = False
                        barrier.wait(timeout=6)
                    return execute(sql, params, many, context)
                with connections["default"].execute_wrapper(observe):
                    response = self.post(payload, client)
                return response.status_code, response.data
            return submit
        return self.concurrent(*(call(payload) for payload in payloads))

    def test_reversed_batch_material_order_does_not_deadlock(self):
        other = MaterialCatalog.objects.create(category_key="HARDWARE", template_key="HARDWARE", name="审核五金二", base_warehouse=self.warehouse)
        self.assertEqual(self.post(self.payload(self.item(quantity="1"), self.item(catalog=other, quantity="1"))).status_code, 201)
        first, second = self.item(quantity="1"), self.item(catalog=other, quantity="1")
        results = self.simultaneous_catalog_requests(self.payload(first, second), self.payload(second, first))
        self.assertEqual([row[0] for row in results], [201, 201], results)
        self.assertEqual(MaterialTransfer.objects.count(), 3)
        self.assertEqual(list(PublicStockBalance.objects.values_list("quantity", flat=True)), [Decimal("3"), Decimal("3")])

    def test_concurrent_outbound_cannot_exceed_available_inventory(self):
        self.assertEqual(self.post(self.payload(self.item(quantity="3"))).status_code, 201)
        results = self.simultaneous_catalog_requests(self.payload(direction="OUT"), self.payload(direction="OUT"))
        self.assertCountEqual([row[0] for row in results], [201, 400], results)
        self.assertEqual(PublicStockBalance.objects.get().quantity, Decimal("1"))
        self.assertEqual(MaterialTransfer.objects.count(), 2)
        self.assertEqual(PublicStockMovement.objects.count(), 2)
