from datetime import date
from decimal import Decimal
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.boms.models import Bom, BomCreationMethod, BomStatus
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee
from apps.reference_data.models import Currency, ProductColor, ProductionUnit

from ..api.serializers import ProductionTaskReadSerializer
from ..models import ProductionTask, ProductionTaskProduct
from ..selectors import production_tasks_with_context


class ProductionTaskBomReadReuseTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="bom_read_reuse")
        cls.employee = Employee.objects.create(
            user=cls.user, employee_code="BOM_READ_REUSE", display_name="BOM 读取员工",
        )
        cls.other_employee = Employee.objects.create(
            employee_code="BOM_READ_OTHER", display_name="其他员工",
        )
        cls.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="production_tasks", codename="view_productiontask",
        ))
        cls.currency, _ = Currency.objects.get_or_create(code="CNY", defaults={
            "numeric_code": "156", "chinese_name": "人民币", "english_name": "Yuan Renminbi",
        })
        cls.unit = ProductionUnit.objects.create(unit_code="BOM_READ_UNIT", unit_name="BOM 读取单位")
        cls.color = ProductColor.objects.create(
            color_card="BOM_READ_CARD", color_code="BOM_READ_BLUE", color_name="当前颜色名称",
        )
        cls.task = cls.create_task("VISIBLE", cls.employee)
        cls.hidden_task = cls.create_task("HIDDEN", cls.other_employee)
        cls.empty_task = cls.create_task("EMPTY", cls.employee)
        cls.first_product = cls.create_product(
            cls.task, 1, 10, id=UUID("78da2c4c-91df-46df-b611-000000000002"),
        )
        cls.second_product = cls.create_product(
            cls.task, 2, 20, id=UUID("78da2c4c-91df-46df-b611-000000000001"),
        )
        cls.create_product(cls.empty_task, 1, 10)
        cls.create_bom(cls.first_product, 1, status=BomStatus.PENDING_CONFIRMATION)
        cls.confirmed_at = timezone.now()
        cls.first_current = cls.create_bom(
            cls.first_product, 2, order_quantity=Decimal("9.0000"),
            confirmed_by_employee=cls.employee, confirmed_at=cls.confirmed_at,
        )
        cls.create_bom(
            cls.first_product, 3, status=BomStatus.PENDING_CONFIRMATION, archived_at=timezone.now(),
        )
        cls.second_current = cls.create_bom(cls.second_product, 1)

    @classmethod
    def create_task(cls, suffix, salesperson):
        return ProductionTask.objects.create(
            task_number=f"BOM-READ-{suffix}", contract_number=f"BOM-CONTRACT-{suffix}",
            order_number=f"BOM-ORDER-{suffix}", order_source="NEW", salesperson=salesperson,
            currency=cls.currency, order_date=date(2026, 10, 1), delivery_date=date(2026, 10, 31),
            includes_tax=False, order_tolerance_percent=0, is_repeat_order=False,
            preproduction_sample_required=False, delivery_method="SINGLE",
        )

    @classmethod
    def create_product(cls, task, line_number, quantity, **overrides):
        return ProductionTaskProduct.objects.create(
            production_task=task, line_number=line_number,
            product_number_snapshot=f"BOM-PRODUCT-{line_number}",
            product_code_snapshot=f"BOM-CODE-{line_number}",
            product_name_snapshot=f"BOM 产品 {line_number}", specification_snapshot="规格快照",
            product_color=cls.color, color_name_snapshot="历史颜色名称", color_code_snapshot="HISTORY-BLUE",
            quantity=quantity, unit=cls.unit, currency=cls.currency,
            unit_price=Decimal("1.0000"), total_amount=Decimal(quantity), exchange_rate=Decimal("1.00000000"),
            **overrides,
        )

    @classmethod
    def create_bom(cls, product, version, **overrides):
        values = {
            "bom_number": f"BOM-READ-{product.pk}-{version}",
            "production_task": product.production_task,
            "product_line": product,
            "version_number": version,
            "creation_method": BomCreationMethod.BLANK,
            "status": BomStatus.VERIFIED,
            "product_number_snapshot": product.product_number_snapshot,
            "product_code_snapshot": product.product_code_snapshot,
            "product_name_snapshot": product.product_name_snapshot,
            "specification_snapshot": product.specification_snapshot,
            "order_quantity": Decimal(product.quantity).quantize(Decimal("0.0001")),
        }
        values.update(overrides)
        return Bom.objects.create(**values)

    def setUp(self):
        self.client.force_authenticate(self.user)

    def test_detail_reads_boms_once_and_matches_fallback_response_and_etag(self):
        fallback_task = production_tasks_with_context().get(pk=self.task.pk)
        expected = ProductionTaskReadSerializer(fallback_task).data

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(f"/api/v1/production-tasks/{self.task.pk}/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"], expected)
        self.assertEqual(response["ETag"], etag_for_instance(fallback_task))
        # 产品删除提示含 BOM 的 EXISTS 子查询；这里只统计实际加载 BOM 对象的主查询。
        bom_queries = [item["sql"] for item in queries if item["sql"].startswith('SELECT "bom".')]
        self.assertEqual(len(bom_queries), 1, bom_queries)

    def test_prefetched_boms_keep_latest_versions_fields_order_and_status_without_queries(self):
        task = production_tasks_with_context(
            include_progress=True, include_bom_details=True,
        ).get(pk=self.task.pk)
        serializer = ProductionTaskReadSerializer()

        with self.assertNumQueries(0):
            boms = serializer.get_current_boms(task)
            status = serializer.get_bom_status(task)
            status_display = serializer.get_bom_status_display(task)

        self.assertEqual(boms, [
            {
                "id": str(self.second_current.pk), "product_line_id": str(self.second_product.pk),
                "bom_number": self.second_current.bom_number, "version_number": 1,
                "status": "VERIFIED", "status_display": "已确认",
                "product_code": "BOM-CODE-2", "product_name": "BOM 产品 2",
                "color_name": "历史颜色名称", "color_code": "HISTORY-BLUE",
                "order_quantity": "20.0000", "is_order_quantity_outdated": False,
                "confirmed_by_name": "", "confirmed_at": None,
            },
            {
                "id": str(self.first_current.pk), "product_line_id": str(self.first_product.pk),
                "bom_number": self.first_current.bom_number, "version_number": 2,
                "status": "VERIFIED", "status_display": "已确认",
                "product_code": "BOM-CODE-1", "product_name": "BOM 产品 1",
                "color_name": "历史颜色名称", "color_code": "HISTORY-BLUE",
                "order_quantity": "9.0000", "is_order_quantity_outdated": True,
                "confirmed_by_name": self.employee.display_name, "confirmed_at": self.confirmed_at,
            },
        ])
        self.assertEqual((status, status_display), ("VERIFIED", "已确认"))

    def test_empty_prefetched_boms_do_not_trigger_fallback_queries(self):
        task = production_tasks_with_context(
            include_progress=True, include_bom_details=True,
        ).get(pk=self.empty_task.pk)
        serializer = ProductionTaskReadSerializer()

        with self.assertNumQueries(0):
            self.assertEqual(serializer.get_current_boms(task), [])
            self.assertEqual(serializer.get_bom_status(task), "NOT_CREATED")
            self.assertEqual(serializer.get_bom_status_display(task), "未建立")

    def test_non_detail_paths_keep_original_current_boms_fallback(self):
        prefetched_task = production_tasks_with_context(
            include_progress=True, include_bom_details=True,
        ).get(pk=self.task.pk)
        serializer = ProductionTaskReadSerializer()
        expected = serializer.get_current_boms(prefetched_task)
        for include_progress, list_mode in [(False, False), (True, False), (True, True)]:
            with self.subTest(include_progress=include_progress, list_mode=list_mode):
                fallback_task = production_tasks_with_context(
                    include_progress=include_progress, list_mode=list_mode,
                ).get(pk=self.task.pk)
                self.assertFalse(hasattr(fallback_task, "_active_boms_with_details"))
                self.assertEqual(hasattr(fallback_task, "_active_boms_for_status"), include_progress)

                with self.assertNumQueries(1):
                    boms = serializer.get_current_boms(fallback_task)

                self.assertEqual(boms, expected)

    def test_detail_keeps_ordinary_employee_task_scope_and_permission(self):
        visible = self.client.get(f"/api/v1/production-tasks/{self.task.pk}/", HTTP_HOST="localhost")
        hidden = self.client.get(f"/api/v1/production-tasks/{self.hidden_task.pk}/", HTTP_HOST="localhost")
        self.assertEqual(visible.status_code, 200, visible.data)
        self.assertEqual(hidden.status_code, 404, hidden.data)

        denied_user = get_user_model().objects.create_user(username="bom_read_denied")
        Employee.objects.create(user=denied_user, employee_code="BOM_READ_DENIED", display_name="无权限员工")
        self.client.force_authenticate(denied_user)
        denied = self.client.get(f"/api/v1/production-tasks/{self.task.pk}/", HTTP_HOST="localhost")
        self.assertEqual(denied.status_code, 403, denied.data)
