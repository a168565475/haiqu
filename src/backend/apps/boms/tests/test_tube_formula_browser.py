"""仅显式启用的真实浏览器预置数据；只允许连接本任务独立测试库。"""

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

from apps.organizations.models import Employee
from apps.reference_data.models import ProductColor
from ..services import confirm_bom_product
from . import test_material_flow_bom as fixtures


@skipUnless(os.environ.get("TUBE_FORMULA_BROWSER_QA") == "20261029", "仅显式启用的隔离浏览器验收")
class TubeFormulaBrowserTests(LiveServerTestCase):
    host = "0.0.0.0"
    port = 8000
    setUpFixture = fixtures.MaterialFlowBomTests.setUpFixture
    material = fixtures.MaterialFlowBomTests.material
    get = fixtures.MaterialFlowBomTests.get
    save = fixtures.MaterialFlowBomTests.save

    def test_isolated_browser(self):
        self.assertEqual(connection.settings_dict["NAME"], "test_haiqu_tube_browser_20261029")
        root = Path(settings.TUBE_FORMULA_BROWSER_ROOT)
        ready = root / "ready.json"
        result = root / "result.json"
        fixture_ready = False
        try:
            fixtures.MaterialFlowBomTests.setUp(self)
            fixture_ready = True
            password = secrets.token_urlsafe(30)
            self.user.username = "ISOLATED_TUBE_BROWSER_20261029"
            self.user.set_password(password)
            self.user.save()
            self.employee.display_name = "隔离公式浏览器验收员工"
            self.employee.save(update_fields=["display_name"])
            self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="reference_data"))
            self.user.user_permissions.add(*Permission.objects.filter(
                content_type__app_label="products", codename__startswith="view_"))
            saved = self.save([{"section_type": "PROFILE", "title": "管材类", "lines": [{
                "part_name": "隔离公式测试管", "material": "隔离公式测试铁", "tube_shape": "圆管",
                "tube_diameter": "25", "tube_thickness": "1", "length_value": "500",
                "unit_consumption": "2", "tube_cut_piece_count": "6",
            }]}])
            self.assertEqual(saved.status_code, 200, saved.data)
            color, _ = ProductColor.objects.get_or_create(
                color_card="ISOLATED_TUBE", color_code="ISOLATED_TUBE", color_name="隔离验收色")
            self.bom = confirm_bom_product(bom=self.bom, product=self.product, product_color=color,
                                          color_code=color.color_code, actor_employee=self.employee)
            denied_password = secrets.token_urlsafe(30)
            denied = get_user_model().objects.create_user(username="ISOLATED_TUBE_DENIED_20261029", password=denied_password)
            Employee.objects.create(user=denied, employee_code="ISO_TUBE_DENIED", display_name="隔离无权限验收员工")
            ready.write_text(json.dumps({"bom_id": str(self.bom.pk), "username": self.user.username,
                "password": password, "denied_username": denied.username, "denied_password": denied_password}), encoding="utf-8")
            print("隔离管材公式浏览器预置数据已就绪；登录凭据不输出。", flush=True)
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
            result.unlink(missing_ok=True)
            if fixture_ready:
                fixtures.MaterialFlowBomTests.tearDown(self)
