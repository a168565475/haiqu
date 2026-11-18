from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient, APITestCase

from apps.organizations.models import Employee
from ..models import Warehouse
from ..services import save_warehouse


class WarehouseNumberingApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="warehouse_numbering")
        Employee.objects.create(user=self.user, employee_code="WAREHOUSE_NUMBERING", display_name="仓库编号测试员")
        self.user.user_permissions.set(Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["add_warehouse", "view_warehouse", "change_warehouse"],
        ))
        self.client.force_authenticate(self.user)
        self.url = "/api/v1/warehouses/"

    def create_warehouse(self, name, **extra):
        return self.client.post(self.url, {"warehouse_name": name, "warehouse_type": "MATERIAL", **extra}, format="json")

    def test_missing_number_creates_unique_ck_numbers_after_existing_maximum(self):
        Warehouse.objects.create(warehouse_number="CK098", warehouse_name="历史仓", warehouse_type="MATERIAL", status="DISABLED")
        Warehouse.objects.create(warehouse_number="CK-900", warehouse_name="历史手工仓", warehouse_type="MATERIAL")
        first = self.create_warehouse("新建仓一")
        second = self.create_warehouse("新建仓二")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(first.data["data"]["warehouse_number"], "CK099")
        self.assertEqual(second.data["data"]["warehouse_number"], "CK100")
        self.assertNotEqual(first.data["data"]["id"], second.data["data"]["id"])

    def test_edit_without_number_preserves_existing_number_and_requires_etag(self):
        created = self.create_warehouse("原仓库", warehouse_number="OLD-WH")
        self.assertEqual(created.status_code, 201, created.data)
        url = f'{self.url}{created.data["data"]["id"]}/'
        rejected = self.client.patch(url, {"warehouse_name": "修改仓库"}, format="json")
        self.assertEqual(rejected.status_code, 428, rejected.data)
        changed = self.client.patch(url, {"warehouse_name": "修改仓库"}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data["data"]["warehouse_number"], "OLD-WH")
        self.assertEqual(changed.data["data"]["warehouse_name"], "修改仓库")
        stale = self.client.patch(url, {"warehouse_name": "过期修改"}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(stale.status_code, 412, stale.data)

    def test_legacy_explicit_number_remains_supported_and_duplicate_is_rejected(self):
        created = self.create_warehouse("手工历史仓", warehouse_number="OLD-01")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["warehouse_number"], "OLD-01")
        duplicate = self.create_warehouse("重复编号仓", warehouse_number="OLD-01")
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertEqual(Warehouse.objects.filter(warehouse_number="OLD-01").count(), 1)

    def test_blank_and_invalid_explicit_numbers_do_not_create_warehouse(self):
        before = Warehouse.objects.count()
        for number in ["", "非法编号"]:
            with self.subTest(number=number):
                response = self.create_warehouse("无效编号仓", warehouse_number=number)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Warehouse.objects.count(), before)

    def test_creation_still_requires_login_and_add_permission(self):
        before = Warehouse.objects.count()
        anonymous = APIClient().post(self.url, {"warehouse_name": "匿名仓", "warehouse_type": "MATERIAL"}, format="json")
        self.assertEqual(anonymous.status_code, 401, anonymous.data)
        self.assertEqual(anonymous.data["error"]["code"], "AUTHENTICATION_REQUIRED")
        viewer = get_user_model().objects.create_user(username="warehouse_viewer")
        Employee.objects.create(user=viewer, employee_code="WAREHOUSE_VIEWER", display_name="仓库只读员")
        viewer.user_permissions.set(Permission.objects.filter(content_type__app_label="inventory", codename="view_warehouse"))
        self.client.force_authenticate(viewer)
        denied = self.create_warehouse("无权限仓")
        self.assertEqual(denied.status_code, 403, denied.data)
        self.assertEqual(Warehouse.objects.count(), before)


class WarehouseNumberingConcurrencyTests(TransactionTestCase):
    def test_parallel_creates_allocate_different_numbers(self):
        barrier = Barrier(2)

        def create(index):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                barrier.wait(timeout=5)
                warehouse = save_warehouse(
                    instance=None, validated_data={"warehouse_name": f"并发仓{index}", "warehouse_type": "MATERIAL"},
                    actor_employee=None, request=None,
                )
                return warehouse.warehouse_number
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create, index) for index in range(2)]
            numbers = [future.result(timeout=15) for future in futures]
        self.assertEqual(len(set(numbers)), 2)
        self.assertTrue(all(number.startswith("CK") and number[2:].isdigit() for number in numbers))
        self.assertEqual(Warehouse.objects.filter(warehouse_number__in=numbers).count(), 2)
