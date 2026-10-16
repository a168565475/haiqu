from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.utils import timezone
from django.test import SimpleTestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from rest_framework.test import APIClient, APITestCase

from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.access_control.models import RoleActionGrant
from apps.files.models import BusinessFile, FileScanStatus
from apps.sales_orders.tests import test_sales_order_api as sales_fixtures

from ..models import ProductionTask
from ..api.serializers import ProductionTaskPmcDecisionSerializer, ProductionTaskWriteSerializer
from . import test_production_task_api as fixtures


class ProductionCorrectionContractTests(SimpleTestCase):
    def test_pmc_confirmation_requires_explicit_follower_selection(self):
        serializer = ProductionTaskPmcDecisionSerializer(data={"decision": "CONFIRM"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("follower_ids", serializer.errors)

    def test_manual_creation_rejects_empty_followers_at_input_boundary(self):
        serializer = ProductionTaskWriteSerializer(data={"follower_ids": []}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("follower_ids", serializer.errors)


class ManualProductionCorrectionTests(APITestCase):
    def setUp(self):
        fixtures.ProductionTaskApiTests.setUp(self)
        from apps.reference_data.models import Currency
        self.currency = Currency.objects.get(code="CNY")

    def payload(self, **changes):
        data = fixtures.ProductionTaskApiTests.payload(self)
        data.update(task_number="HT26199-1", customer_account_id=None, tax_rate=3)
        data.pop("order_number")
        data.update(changes)
        return data

    def test_manual_creation_uses_explicit_number_without_customer(self):
        response = self.client.post("/api/v1/production-tasks/", self.payload(is_repeat_order=True, order_source="NEW"), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        task = ProductionTask.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(task.task_number, "HT26199-1")
        self.assertEqual(task.order_number, "HT26199-1")
        self.assertIsNone(task.customer_account_id)
        self.assertIsNone(task.sales_order_id)
        self.assertEqual(task.tax_rate, 3)
        self.assertTrue(task.is_repeat_order)
        self.assertEqual(task.order_source, "REPEAT")
        self.assertEqual(list(task.followers.all()), [self.follower])
        self.assertEqual(task.products.get().product_id, self.product.pk)
        from apps.production_scheduling.services import task_source_snapshot
        from apps.procurement.api.views import PurchaseOrderViewSet

        self.assertIsNone(task_source_snapshot(task)["customer_account_id"])
        self.assertEqual(task_source_snapshot(task)["customer_name"], "")
        self.assertEqual(PurchaseOrderViewSet._task_payload(task)["customer_name"], "")

    def test_manual_snapshot_product_and_plans_survive_patch_and_pmc(self):
        payload = self.payload(
            planned_start_date=timezone.localdate().isoformat(),
            planned_end_date=timezone.localdate().isoformat(),
            production_priority="NORMAL", production_batch_number="MANUAL-BATCH", planner_id=str(self.employee.pk),
        )
        product = payload["products"][0]
        product.update(product_id=None, customer_product_name="手动产品", customer_specification="手动规格")
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task = ProductionTask.objects.get(pk=created.data["data"]["id"])
        self.assertEqual(task.production_batch_number, "MANUAL-BATCH")
        self.assertEqual(task.planner_id, self.employee.pk)
        product["client_key"] = str(task.products.get().pk)
        patched = self.client.patch(f"/api/v1/production-tasks/{task.pk}/", {"products": [product]}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(patched.status_code, 200, patched.data)
        submitted = self.client.post(f"/api/v1/production-tasks/{task.pk}/submit/", {}, format="json", HTTP_IF_MATCH=patched["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        confirmed = self.client.post(f"/api/v1/production-tasks/{task.pk}/pmc-decision/", {
            "decision": "CONFIRM", "follower_ids": [str(self.follower.pk)],
        }, format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        line = task.products.get()
        self.assertIsNone(line.product_id)
        self.assertEqual(line.product_number_snapshot, "")
        self.assertEqual(line.item_number_snapshot, "")

    def test_material_issue_options_accept_manual_task_without_customer(self):
        created = self.client.post("/api/v1/production-tasks/", self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task_id = created.data["data"]["id"]
        ProductionTask.objects.filter(pk=task_id).update(status="READY")
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label="material_issues", codename="view_materialissue"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        options = self.client.get("/api/v1/material-issues/options/")
        self.assertEqual(options.status_code, 200, options.data)
        task_option = next(item for item in options.data["data"]["production_tasks"] if item["id"] == str(task_id))
        self.assertEqual(task_option["customer_name"], "")

    def test_manual_rejects_missing_follower_customer_company_and_accepts_snapshot_product(self):
        for change, field in [
            ({"follower_ids": []}, "follower_ids"),
            ({"customer_account_id": str(self.customer.pk)}, "customer_account_id"),
            ({"company_id": str(uuid4())}, "company_id"),
        ]:
            with self.subTest(field=field):
                response = self.client.post("/api/v1/production-tasks/", self.payload(**change), format="json")
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn(field, response.data["error"]["field_errors"])
        payload = self.payload()
        payload["products"][0]["product_id"] = None
        payload["products"][0]["customer_product_name"] = "不能代替真实产品"
        payload["products"][0]["customer_specification"] = "规格"
        response = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        line = ProductionTask.objects.get().products.get()
        self.assertIsNone(line.product_id)
        self.assertEqual(line.item_number_snapshot, "")
        self.assertEqual(line.product_number_snapshot, "")
        self.assertEqual(line.product_name_snapshot, "不能代替真实产品")

    def test_number_and_tax_rules_are_checked(self):
        for number in ["26199", "ht26199", "HT", "HT26_A", "HT26--1", "HT26/1"]:
            with self.subTest(number=number):
                response = self.client.post("/api/v1/production-tasks/", self.payload(task_number=number), format="json")
                self.assertEqual(response.status_code, 400, response.data)
        for includes_tax, rate in [(True, None), (True, 6), (False, 3)]:
            with self.subTest(includes_tax=includes_tax, rate=rate):
                response = self.client.post("/api/v1/production-tasks/", self.payload(includes_tax=includes_tax, tax_rate=rate), format="json")
                self.assertEqual(response.status_code, 400, response.data)
        first = self.client.post("/api/v1/production-tasks/", self.payload(includes_tax=False, tax_rate=None), format="json")
        self.assertEqual(first.status_code, 201, first.data)
        duplicate = self.client.post("/api/v1/production-tasks/", self.payload(), format="json")
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertIn("task_number", duplicate.data["error"]["field_errors"])

    def test_recent_numbers_are_real_latest_five_sorted_by_number(self):
        numbers = ["HT26999", "HT26101", "HT26100-2", "HT26100-1", "HT26105", "HT26104"]
        for number in numbers:
            response = self.client.post("/api/v1/production-tasks/", self.payload(task_number=number), format="json")
            self.assertEqual(response.status_code, 201, response.data)
        options = self.client.get("/api/v1/production-tasks/options/")
        self.assertEqual(options.data["data"]["recent_task_numbers"], sorted(numbers[1:]))

    def test_manual_edit_can_keep_snapshot_without_product_reference(self):
        payload = self.payload()
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        product = payload["products"][0]
        product.update(client_key=str(created.data["data"]["products"][0]["id"]), product_id=None,
                       customer_product_name="手写名称", customer_specification="手写规格")
        response = self.client.patch(f"/api/v1/production-tasks/{created.data['data']['id']}/", {"products": [product]},
                                     format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        task = ProductionTask.objects.get(pk=created.data["data"]["id"])
        self.assertIsNone(task.products.get().product_id)
        self.assertEqual(task.products.get().product_number_snapshot, "")


class SalesProductionCorrectionTests(APITestCase):
    setUp = sales_fixtures.SalesOrderApiTests.setUp
    direct_payload = sales_fixtures.SalesOrderApiTests.direct_payload
    create_direct = sales_fixtures.SalesOrderApiTests.create_direct

    def make_source_task(self):
        sales_follower = Employee.objects.create(employee_code="SALES_FOLLOWER", display_name="销售跟单")
        created = self.create_direct(merchandiser_id=str(sales_follower.pk))
        confirmed = self.client.post(
            f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/", {},
            format="json", HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        response = self.client.post("/api/v1/production-tasks/create-from-sales-order/", {
            "task_number": "HT26200",
            "delivery_batch_line_id": confirmed.data["data"]["delivery_batches"][0]["lines"][0]["id"],
            "quantity": 10, "follower_ids": [str(self.employee.pk)],
            "delivery_date": confirmed.data["data"]["delivery_batches"][0]["planned_delivery_date"],
            "includes_tax": True, "tax_rate": 3, "order_tolerance_percent": "3.00",
            "is_repeat_order": False, "delivery_method": "SINGLE",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        task = ProductionTask.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(list(task.followers.all()), [self.employee])
        submitted = self.client.post(f"/api/v1/production-tasks/{task.pk}/submit/", {},
                                     format="json", HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        task.refresh_from_db()
        return task, submitted

    def confirm_payload(self):
        return {
            "decision": "CONFIRM", "follower_ids": [str(self.employee.pk)],
            "planned_start_date": timezone.localdate().isoformat(),
            "planned_end_date": timezone.localdate().isoformat(),
            "delivery_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
            "includes_tax": True, "tax_rate": 5, "order_tolerance_percent": "5.00",
            "is_repeat_order": True, "delivery_method": "SPLIT",
        }

    def test_source_does_not_copy_sales_follower_and_pmc_selects_independently(self):
        task, created = self.make_source_task()
        self.assertEqual(task.salesperson_id, self.employee.pk)
        self.assertEqual(list(task.followers.all()), [self.employee])
        self.assertEqual(task.delivery_date, task.sales_order_delivery_batch.planned_delivery_date)
        production_follower = Employee.objects.create(employee_code="FACTORY_FOLLOWER", display_name="生产跟单")
        payload = self.confirm_payload()
        payload["follower_ids"] = [str(production_follower.pk)]
        before_sales_follower = task.sales_order.merchandiser_id
        response = self.client.post(f"/api/v1/production-tasks/{task.pk}/pmc-decision/", payload,
                                    format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        task.sales_order.refresh_from_db()
        task.sales_order_delivery_batch.refresh_from_db()
        self.assertEqual(list(task.followers.all()), [production_follower])
        self.assertEqual(task.sales_order.merchandiser_id, before_sales_follower)
        self.assertEqual(task.delivery_date, task.sales_order_delivery_batch.planned_delivery_date)
        self.assertEqual(task.tax_rate, 5)
        self.assertEqual(task.delivery_method, "SPLIT")
        self.assertTrue(task.is_repeat_order)
        self.assertEqual(task.order_source, "REPEAT")

    def test_pmc_requires_explicit_active_follower_and_valid_tax(self):
        task, created = self.make_source_task()
        for change in [{"follower_ids": []}, {"tax_rate": None}]:
            response = self.client.post(f"/api/v1/production-tasks/{task.pk}/pmc-decision/",
                                       {**self.confirm_payload(), **change}, format="json", HTTP_IF_MATCH=created["ETag"])
            self.assertEqual(response.status_code, 400, response.data)
        payload = self.confirm_payload()
        payload.pop("follower_ids")
        response = self.client.post(f"/api/v1/production-tasks/{task.pk}/pmc-decision/", payload,
                                   format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(response.status_code, 400, response.data)
        task.refresh_from_db()
        self.assertEqual(task.status, "PENDING_VALIDATION")

    def test_delivery_writeback_and_pmc_failure_roll_back_both_sides(self):
        task, created = self.make_source_task()
        previous_date = task.delivery_date
        with patch("apps.production_tasks.services.write_audit_log", side_effect=RuntimeError("audit failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/api/v1/production-tasks/{task.pk}/pmc-decision/", self.confirm_payload(),
                                 format="json", HTTP_IF_MATCH=created["ETag"])
        task.refresh_from_db()
        task.sales_order_delivery_batch.refresh_from_db()
        self.assertEqual(task.delivery_date, previous_date)
        self.assertEqual(task.sales_order_delivery_batch.planned_delivery_date, previous_date)
        new_date = (timezone.localdate() + timedelta(days=2)).isoformat()
        updated = self.client.patch(f"/api/v1/production-tasks/{task.pk}/", {"delivery_date": new_date},
                                    format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(updated.status_code, 200, updated.data)
        task.refresh_from_db()
        task.sales_order_delivery_batch.refresh_from_db()
        self.assertEqual(task.delivery_date.isoformat(), new_date)
        self.assertEqual(task.sales_order_delivery_batch.planned_delivery_date.isoformat(), new_date)


class FactoryProductionSourceAccessTests(APITestCase):
    setUp = sales_fixtures.SalesOrderApiTests.setUp
    direct_payload = sales_fixtures.SalesOrderApiTests.direct_payload
    create_direct = sales_fixtures.SalesOrderApiTests.create_direct

    def test_factory_sources_and_images_use_production_grants_without_sales_customer_access(self):
        self.assert_factory_source_flow(module_access=True)

    def test_factory_sources_support_current_legacy_permission_flags(self):
        self.assert_factory_source_flow(module_access=False)

    def assert_factory_source_flow(self, *, module_access):
        created = self.create_direct()
        order_id = created.data["data"]["id"]
        confirmed = self.client.post(f"/api/v1/sales-orders/{order_id}/confirm/", {}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        line_id = confirmed.data["data"]["lines"][0]["id"]
        factory_user = get_user_model().objects.create_user(username="factory_source_reader")
        factory_employee = Employee.objects.create(user=factory_user, employee_code="FACTORY_SOURCE", display_name="工厂生产员工")
        factory_client = APIClient()
        factory_client.force_authenticate(factory_user)
        payload = {"follower_ids": [str(factory_employee.pk)], "delivery_date": confirmed.data["data"]["delivery_batches"][0]["planned_delivery_date"], "includes_tax": True, "tax_rate": 3, "order_tolerance_percent": "3.00", "is_repeat_order": False, "delivery_method": "SINGLE", "task_number": "HT26201", "delivery_batch_line_id": confirmed.data["data"]["delivery_batches"][0]["lines"][0]["id"], "quantity": 10}
        with self.settings(ACCESS_MANAGEMENT_ENABLED=True, SALES_ACCESS_ENABLED=module_access,
                           MODULE_ACCESS_ENABLED=module_access, ACCESS_RESOURCE_SCOPES_ENABLED=False):
            denied = factory_client.get("/api/v1/production-tasks/sales-order-sources/")
            self.assertEqual(denied.status_code, 403, denied.data)
            denied_create = factory_client.post("/api/v1/production-tasks/create-from-sales-order/", payload, format="json")
            self.assertEqual(denied_create.status_code, 403, denied_create.data)
            group = Group.objects.create(name="FACTORY_SOURCE_TEST")
            role = RoleProfile.objects.create(auth_group=group, role_code="FACTORY_SOURCE_TEST", display_name="生产来源测试角色")
            EmployeeRoleAssignment.objects.create(employee=factory_employee, role_profile=role, effective_from=timezone.now())
            for codename in ["add_productiontask", "view_productiontask"]:
                permission = Permission.objects.get(content_type__app_label="production_tasks", codename=codename)
                group.permissions.add(permission)
                RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
            factory_client.force_authenticate(get_user_model().objects.get(pk=factory_user.pk))
            listed = factory_client.get("/api/v1/production-tasks/sales-order-sources/")
            self.assertEqual(listed.status_code, 200, listed.data)
            self.assertIn(str(order_id), [str(item["id"]) for item in listed.data["data"]])
            detail = factory_client.get("/api/v1/production-tasks/sales-order-sources/", {"sales_order_id": str(order_id)})
            self.assertEqual(detail.status_code, 200, detail.data)
            for field in ["customer_account_id", "customer_name", "transaction_entity_id", "buyer_snapshot", "seller_snapshot", "merchandiser"]:
                self.assertNotIn(field, detail.data["data"])
            sales_detail = factory_client.get(f"/api/v1/sales-orders/{order_id}/")
            self.assertIn(sales_detail.status_code, [403, 404], sales_detail.data)
            with TemporaryDirectory(prefix="order-correction-source-image-") as media_root, self.settings(MEDIA_ROOT=media_root):
                Path(media_root, "source.png").write_bytes(b"source-image-fixture")
                business_file = BusinessFile.objects.create(uploaded_by_employee=self.employee, original_name="source.png",
                    storage_key="source.png", content_type="image/png", size_bytes=20, scan_status=FileScanStatus.CLEAN)
                from apps.sales_orders.models import SalesOrderLine
                SalesOrderLine.objects.filter(pk=line_id).update(product_image=business_file)
                image = factory_client.get("/api/v1/production-tasks/sales-order-source-image/", {"sales_order_id": str(order_id), "line_id": str(line_id)})
                self.assertEqual(image.status_code, 200)
                self.assertEqual(b"".join(image.streaming_content), b"source-image-fixture")
                production = factory_client.post("/api/v1/production-tasks/create-from-sales-order/", payload, format="json")
                self.assertEqual(production.status_code, 201, production.data)
                task = ProductionTask.objects.get(pk=production.data["data"]["id"])
                self.assertEqual(task.products.get().image_file_id, business_file.pk)
            task_detail = factory_client.get(f"/api/v1/production-tasks/{task.pk}/")
            self.assertEqual(task_detail.status_code, 200, task_detail.data)
            self.assertEqual(str(task_detail.data["data"]["products"][0]["images"][0]["id"]), str(business_file.pk))
            remaining = factory_client.get("/api/v1/production-tasks/sales-order-sources/")
            self.assertNotIn(str(order_id), [str(item["id"]) for item in remaining.data["data"]])
            role.archived_at = timezone.now()
            role.save()
            factory_client.force_authenticate(get_user_model().objects.get(pk=factory_user.pk))
            revoked = factory_client.get("/api/v1/production-tasks/sales-order-sources/", {"sales_order_id": str(order_id)})
            self.assertEqual(revoked.status_code, 403, revoked.data)
