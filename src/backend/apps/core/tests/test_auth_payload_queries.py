from copy import deepcopy
from itertools import product
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from apps.core.views import user_payload


BASE_PERMISSION = "reference_data.view_country"
MODULE_PERMISSION = "access_control.complete_purchaseorder"
SALES_PERMISSION = "access_control.submit_inquiry"


class AuthPayloadQueryTests(SimpleTestCase):
    def setUp(self):
        employee = SimpleNamespace(
            pk=1, employee_code="AUTH-PAYLOAD", display_name="权限测试员工", status="ACTIVE",
        )
        self.user = SimpleNamespace(
            pk=2, is_authenticated=True, is_active=True, is_superuser=False,
            employee_profile=employee,
            get_username=lambda: "auth-payload",
            get_full_name=lambda: "权限测试员工",
            get_all_permissions=lambda: {BASE_PERMISSION},
            has_perm=lambda permission: False,
        )
        self.access = self.access_snapshot(granted=True)
        self.effective_access = Mock(side_effect=lambda user: deepcopy(self.access))
        # 两处引用指向同一个计数器；保留真实的权限判断及请求内快照逻辑。
        self.enterContext(patch("apps.access_control.selectors.effective_access", self.effective_access))
        self.enterContext(patch("apps.access_control.sales_policy.effective_access", self.effective_access))
        self.waiting_for_role = self.enterContext(
            patch("apps.wecom.selectors.waiting_for_role", return_value=False),
        )

    @staticmethod
    def access_snapshot(*, granted):
        return {
            "active": True,
            "is_superuser": False,
            "actions": {
                MODULE_PERMISSION: {"scopes": ["MODULE"], "sources": []},
                SALES_PERMISSION: {"scopes": ["OWN"], "sources": []},
            } if granted else {},
            "roles": [],
            "legacy_sources": [],
            "business_scope_enforcement": "ENABLED",
            "version": "granted" if granted else "revoked",
        }

    def test_all_flag_combinations_compute_at_most_one_access_snapshot(self):
        for management, modules, sales in product((False, True), repeat=3):
            with self.subTest(management=management, modules=modules, sales=sales), override_settings(
                ACCESS_MANAGEMENT_ENABLED=management,
                MODULE_ACCESS_ENABLED=modules,
                SALES_ACCESS_ENABLED=sales,
            ):
                self.effective_access.reset_mock()
                self.waiting_for_role.reset_mock()

                payload = user_payload(self.user)

                if management or modules or sales:
                    self.effective_access.assert_called_once_with(self.user)
                else:
                    self.effective_access.assert_not_called()
                expected_permissions = {BASE_PERMISSION}
                if modules:
                    expected_permissions.add(MODULE_PERMISSION)
                if sales:
                    expected_permissions.add(SALES_PERMISSION)
                self.assertEqual(payload["permissions"], sorted(expected_permissions))
                self.assertEqual(payload["module_access_enabled"], modules)
                self.assertEqual(payload["sales_access_enabled"], sales)
                self.assertEqual(payload["data_scope"], "ASSIGNED_AND_GRANTED")
                if management:
                    self.assertEqual(payload["effective_access"], self.access)
                else:
                    self.assertNotIn("effective_access", payload)
                self.assertFalse(payload["waiting_for_role"])
                self.waiting_for_role.assert_called_once_with(self.user)

    @override_settings(
        ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
    )
    def test_separate_payload_calls_for_same_user_reflect_revocation(self):
        first = user_payload(self.user)
        self.access = self.access_snapshot(granted=False)

        second = user_payload(self.user)

        self.assertEqual(first["permissions"], sorted({BASE_PERMISSION, MODULE_PERMISSION, SALES_PERMISSION}))
        self.assertEqual(first["effective_access"]["version"], "granted")
        self.assertEqual(second["permissions"], [BASE_PERMISSION])
        self.assertEqual(second["effective_access"]["actions"], {})
        self.assertEqual(second["effective_access"]["version"], "revoked")
        self.assertEqual(self.effective_access.call_count, 2)
        self.assertEqual(self.waiting_for_role.call_count, 2)

    @override_settings(
        ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
    )
    def test_waiting_for_role_still_clears_permissions_and_data_scope(self):
        self.waiting_for_role.return_value = True

        payload = user_payload(self.user)

        self.assertTrue(payload["waiting_for_role"])
        self.assertEqual(payload["permissions"], [])
        self.assertEqual(payload["data_scope"], "NONE")
        self.waiting_for_role.assert_called_once_with(self.user)
