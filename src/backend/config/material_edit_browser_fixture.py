"""仅显式启用的原料属性编辑浏览器夹具；不能连接业务主库。"""
import json
import os
import secrets
import time
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import LiveServerTestCase

from apps.material_catalog.models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog
from apps.organizations.models import Employee
from apps.reference_data.models import ProductionUnit


@skipUnless(os.environ.get("MATERIAL_EDIT_BROWSER_QA") == "20261029", "仅显式启用的隔离浏览器验收")
class MaterialEditBrowserTests(LiveServerTestCase):
    host = "0.0.0.0"
    port = 8000

    def test_isolated_browser(self):
        self.assertEqual(connection.settings_dict["NAME"], "test_haiqu_material_edit_browser_20261029")
        root = Path(settings.MATERIAL_EDIT_BROWSER_ROOT)
        ready = root / "ready.json"
        ready_pending = root / "ready.pending.json"
        result = root / "result.json"
        try:
            password = secrets.token_urlsafe(30)
            user = get_user_model().objects.create_user(username="ISOLATED_MATERIAL_EDIT_20261029", password=password)
            Employee.objects.create(user=user, employee_code="ISO_MAT_EDIT", display_name="隔离原料属性验收员工")
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label="material_catalog"))
            readonly_password = secrets.token_urlsafe(30)
            readonly = get_user_model().objects.create_user(username="ISOLATED_MATERIAL_READONLY_20261029", password=readonly_password)
            Employee.objects.create(user=readonly, employee_code="ISO_MAT_READONLY", display_name="隔离原料只读验收员工")
            readonly.user_permissions.add(*Permission.objects.filter(content_type__app_label="material_catalog", codename="view_materialcatalog"))
            catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="隔离属性编辑测试管", spray_enabled=True)
            first = MaterialAttributeValue.objects.create(catalog=catalog, scope="BASE", field_key="material", value="Q235")
            second = MaterialAttributeValue.objects.create(catalog=catalog, scope="BASE", field_key="material", value="Q345")
            shape = MaterialAttributeValue.objects.create(catalog=catalog, scope="BASE", field_key="shape", value="圆管")
            dimension = MaterialAttributeValue.objects.create(catalog=catalog, scope="BASE", field_key="section_size", value="25", parent=shape)
            MaterialAttributeValue.objects.create(catalog=catalog, scope="BASE", field_key="color", value="无颜色")
            MaterialAttributeValue.objects.create(catalog=catalog, scope="SPRAY", field_key="color", value="浅蓝")
            units = list(ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).order_by("unit_name")[:2])
            self.assertEqual(len(units), 2)
            allowed_unit = MaterialAllowedUnit.objects.create(catalog=catalog, scope="BASE", unit=units[0])
            ready_pending.write_text(json.dumps({"catalog_id": str(catalog.pk), "material_id": str(first.pk), "second_material_id": str(second.pk),
                "shape_id": str(shape.pk), "dimension_id": str(dimension.pk), "allowed_unit_id": str(allowed_unit.pk),
                "units": [{"id": str(unit.pk), "name": unit.unit_name} for unit in units],
                "username": user.username, "password": password,
                "readonly_username": readonly.username, "readonly_password": readonly_password}), encoding="utf-8")
            ready_pending.replace(ready)
            print("隔离原料属性浏览器预置数据已就绪；登录凭据不输出。", flush=True)
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                if result.exists():
                    outcome = json.loads(result.read_text(encoding="utf-8"))
                    self.assertTrue(outcome.get("passed"), outcome.get("error", "浏览器验收失败"))
                    return
                time.sleep(1)
            self.fail("等待隔离浏览器验收结果超时")
        finally:
            ready.unlink(missing_ok=True)
            ready_pending.unlink(missing_ok=True)
            result.unlink(missing_ok=True)
