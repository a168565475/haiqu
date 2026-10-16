from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.boms.models import Bom, BomStatus
from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee
from apps.procurement.models import PurchaseOrderStatus
from apps.production_scheduling.tests.test_production_scheduling_api import (
    ensure_schedule_test_references,
    make_schedule_prerequisites,
)

from ..models import DeliveryMethod, OrderSource, ProductionTask, ProductionTaskProduct, ProductionTaskStatus


class ProductionTaskSchedulingProgressApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="scheduling-progress")
        self.employee = Employee.objects.create(
            user=self.user, employee_code="SCHEDULING-PROGRESS", display_name="排产门禁测试员工"
        )
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label="production_tasks"))
        product, currency, color, _ = ensure_schedule_test_references()
        customer = CustomerAccount.objects.create(account_code="PROGRESS", account_name="门禁测试客户")
        today = timezone.localdate()
        self.task = ProductionTask.objects.create(
            task_number="HT-PROGRESS", contract_number="HT-PROGRESS", order_source=OrderSource.NEW,
            order_number="PROGRESS", customer_account=customer, order_date=today,
            delivery_date=today + timedelta(days=30), salesperson=self.employee, currency=currency,
            includes_tax=False, order_tolerance_percent=0, is_repeat_order=False,
            preproduction_sample_required=False, delivery_method=DeliveryMethod.SINGLE,
            status=ProductionTaskStatus.READY, created_by_employee=self.employee,
        )
        self.line = ProductionTaskProduct.objects.create(
            production_task=self.task, line_number=1, product=product,
            product_number_snapshot=product.product_number, product_code_snapshot=product.product_code,
            product_name_snapshot=product.product_name, specification_snapshot=product.specification,
            product_color=color, quantity=100, unit=product.unit, currency=currency,
            unit_price=10, total_amount=1000, exchange_rate=1,
        )
        self.bom, self.purchase_order = make_schedule_prerequisites(
            task=self.task, line=self.line, employee=self.employee
        )
        self.client.force_authenticate(self.user)

    def assert_progress(self, bom_status, purchase_status):
        listed = self.client.get("/api/v1/production-tasks/")
        detail = self.client.get(f"/api/v1/production-tasks/{self.task.pk}/")
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(detail.status_code, 200, detail.data)
        row = next(item for item in listed.data["data"] if item["id"] == str(self.task.pk))
        expected = {
            "bom_status": bom_status,
            "bom_status_display": row["bom_status_display"],
            "purchase_status": purchase_status,
            "purchase_status_display": row["purchase_status_display"],
        }
        for response in (row, detail.data["data"]):
            self.assertEqual({key: response.get(key) for key in expected}, expected)

    def test_list_and_detail_share_completed_progress(self):
        self.assert_progress("VERIFIED", "ORDER_COMPLETED")

    def test_latest_active_bom_controls_list_and_detail_progress(self):
        latest = Bom.objects.get(pk=self.bom.pk)
        latest.pk = None
        latest.bom_number = "BOM-PROGRESS-V2"
        latest.version_number = 2
        latest.status = BomStatus.PENDING_CONFIRMATION
        latest.confirmed_at = None
        latest.confirmed_by_employee = None
        latest.save()
        self.assert_progress("PENDING_CONFIRMATION", "ORDER_COMPLETED")
        latest.archived_at = timezone.now()
        latest.save(update_fields=["archived_at", "updated_at"])
        self.assert_progress("VERIFIED", "ORDER_COMPLETED")

    def test_all_task_products_need_bom(self):
        second = ProductionTaskProduct.objects.get(pk=self.line.pk)
        second.pk = None
        second.line_number = 2
        second.save()
        self.assert_progress("PARTIAL", "ORDER_COMPLETED")
        self.bom.archived_at = timezone.now()
        self.bom.save(update_fields=["archived_at", "updated_at"])
        self.assert_progress("NOT_CREATED", "ORDER_COMPLETED")

    def test_confirmed_or_purchasing_order_is_not_completed(self):
        for status in (PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.PURCHASING):
            with self.subTest(status=status):
                self.purchase_order.status = status
                self.purchase_order.save(update_fields=["status", "updated_at"])
                self.assert_progress("VERIFIED", f"ORDER_{status}")
        self.purchase_order.archived_at = timezone.now()
        self.purchase_order.save(update_fields=["archived_at", "updated_at"])
        self.assert_progress("VERIFIED", "NOT_STARTED")

    def test_progress_details_require_task_read_permission(self):
        self.user.user_permissions.clear()
        for url in ("/api/v1/production-tasks/", f"/api/v1/production-tasks/{self.task.pk}/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
