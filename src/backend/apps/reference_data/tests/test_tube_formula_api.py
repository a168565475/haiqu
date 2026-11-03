from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.reference_data.models import TubeCalculationFormula
from apps.reference_data.tube_formulas import calculate_tube_metrics


class TubeFormulaApiTests(APITestCase):
    endpoint = "/api/v1/reference-data/tube-calculation-formulas/"

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tube_formula_editor")
        self.employee = Employee.objects.create(
            user=self.user, employee_code="TUBE_FORMULA_EDITOR", display_name="管材公式维护员",
        )
        self.user.user_permissions.set(Permission.objects.filter(
            content_type__app_label="reference_data", codename__in=("view_tubeshape", "change_tubeshape"),
        ))
        self.client.force_authenticate(self.user)
        self.formula = TubeCalculationFormula.objects.get(group_key="ROUND")
        self.url = f"{self.endpoint}{self.formula.pk}/"

    def test_only_three_seeded_groups_are_listed_with_shared_shape_labels(self):
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200, response.data)
        groups = {row["group_key"]: row for row in response.data["data"]}
        self.assertEqual(set(groups), {"ROUND", "RECTANGULAR", "OVAL"})
        self.assertEqual(groups["RECTANGULAR"]["shape_names"], ["方管", "矩形管"])
        self.assertEqual(groups["OVAL"]["shape_names"], ["椭圆管", "扁圆管"])
        self.assertIn("ETag", self.client.get(self.url))

    def test_patch_requires_current_etag_and_writes_audit(self):
        initial = self.client.get(self.url)
        payload = {"area_expression": "直径*管材长度/1000000"}
        self.assertEqual(self.client.patch(self.url, payload, format="json").status_code, 428)
        stale = self.client.patch(self.url, payload, format="json", HTTP_IF_MATCH='"stale"')
        self.assertEqual(stale.status_code, 412)
        saved = self.client.patch(self.url, payload, format="json", HTTP_IF_MATCH=initial["ETag"])
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertNotEqual(saved["ETag"], initial["ETag"])
        self.formula.refresh_from_db()
        self.assertEqual(self.formula.area_expression, payload["area_expression"])
        audit = AuditLog.objects.get(object_type="TUBE_CALCULATION_FORMULA", object_id=self.formula.pk)
        self.assertEqual(audit.action, "UPDATED")
        self.assertEqual(audit.after_data["area_expression"], payload["area_expression"])
        self.assertEqual(self.client.patch(self.url, payload, format="json", HTTP_IF_MATCH=initial["ETag"]).status_code, 412)

    def test_invalid_expression_and_fixed_fields_cannot_be_saved(self):
        etag = self.client.get(self.url)["ETag"]
        for payload in (
            {"area_expression": "__import__('os')"}, {"area_expression": "数量*直径"},
            {"weight_expression": "1/0"}, {"area_expression": "-1"},
            {"group_key": "OVAL"}, {"status": "INACTIVE"}, {"area_expression": "1" * 501},
        ):
            with self.subTest(payload=payload):
                response = self.client.patch(self.url, payload, format="json", HTTP_IF_MATCH=etag)
                self.assertEqual(response.status_code, 400, response.data)
        self.formula.refresh_from_db()
        self.assertEqual(self.formula.group_key, "ROUND")
        self.assertFalse(AuditLog.objects.filter(object_type="TUBE_CALCULATION_FORMULA", object_id=self.formula.pk).exists())

    def test_create_delete_put_and_status_actions_are_unavailable(self):
        self.assertEqual(self.client.post(self.endpoint, {}, format="json").status_code, 405)
        self.assertEqual(self.client.delete(self.url).status_code, 405)
        self.assertEqual(self.client.put(self.url, {}, format="json").status_code, 405)
        for action in ("activate", "deactivate", "archive"):
            self.assertEqual(self.client.post(f"{self.url}{action}/", {}, format="json").status_code, 404)
        self.assertEqual(TubeCalculationFormula.objects.count(), 3)

    def test_view_and_change_permissions_are_independent(self):
        readonly = get_user_model().objects.create_user(username="tube_formula_viewer")
        Employee.objects.create(user=readonly, employee_code="TUBE_FORMULA_VIEWER", display_name="只读")
        readonly.user_permissions.add(Permission.objects.get(content_type__app_label="reference_data", codename="view_tubeshape"))
        client = APIClient()
        client.force_authenticate(readonly)
        detail = client.get(self.url)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(client.patch(self.url, {"area_expression": "1"}, format="json", HTTP_IF_MATCH=detail["ETag"]).status_code, 403)
        readonly.user_permissions.clear()
        client.force_authenticate(get_user_model().objects.get(pk=readonly.pk))
        self.assertEqual(client.get(self.endpoint).status_code, 403)

    def test_session_patch_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        detail = client.get(self.url)
        self.assertEqual(detail.status_code, 200, detail.data)
        response = client.patch(self.url, {"area_expression": "1"}, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(response.status_code, 403, response.data)

    def test_current_database_formula_is_used_and_snapshot_remains_independent(self):
        original = calculate_tube_metrics(shape="圆管", specification="25", thickness="1.5", length_mm="1000")
        self.formula.area_expression = "直径*管材长度/1000000"
        self.formula.save(update_fields=["area_expression", "updated_at"])
        current = calculate_tube_metrics(shape="圆管", specification="25", thickness="1.5", length_mm="1000")
        historical = calculate_tube_metrics(shape="圆管", specification="25", thickness="1.5", length_mm="1000", formula=original["formula_snapshot"])
        self.assertEqual(current["coating_unit_area_sqm"], "0.0250")
        self.assertEqual(historical, original)
