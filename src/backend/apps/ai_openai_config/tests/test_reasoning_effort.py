from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from apps.organizations.models import Employee

from ..models import OpenAIKeyConfig
from ..serializers import OpenAIKeyConfigSerializer, OpenAIKeyConfigWriteSerializer
from ..services import get_active_credentials


class ReasoningEffortSerializerTests(SimpleTestCase):
    def test_omitted_fields_expose_automatic_defaults(self):
        data = OpenAIKeyConfigSerializer(OpenAIKeyConfig()).data
        self.assertEqual(data["document_reasoning_effort"], "auto")
        self.assertEqual(data["material_reasoning_effort"], "auto")

    def test_invalid_efforts_are_rejected_for_each_stage(self):
        for name in ("document_reasoning_effort", "material_reasoning_effort"):
            with self.subTest(field=name):
                serializer = OpenAIKeyConfigWriteSerializer(
                    OpenAIKeyConfig(), data={name: "unsupported"}, partial=True,
                )
                self.assertFalse(serializer.is_valid())
                self.assertIn(name, serializer.errors)


@override_settings(ACCESS_MANAGEMENT_ENABLED=False, MODULE_ACCESS_ENABLED=False, DEV_AUTO_LOGIN_ENABLED=False)
class ReasoningEffortApiTests(APITestCase):
    def test_first_listed_config_is_used_for_provider_requests(self):
        with self.settings(OPENAI_FERNET_KEYS=[Fernet.generate_key().decode("ascii")]):
            user = get_user_model().objects.create_user(username="multiple_configs")
            employee = Employee.objects.create(user=user, employee_code="MULTIPLE_CONFIGS", display_name="多配置测试")
            self.client.force_login(user)
            url = "/api/v1/ai-openai-configs/"
            for label, effort in (("A-old", "low"), ("Z-latest", "high")):
                created = self.client.post(url, {
                    "label": label, "api_key": "test-only-provider-key", "document_reasoning_effort": effort,
                }, format="json")
                self.assertEqual(created.status_code, 201, created.data)

            listed = self.client.get(url)
            self.assertEqual(listed.status_code, 200, listed.data)
            first = listed.data["data"][0]
            credentials = get_active_credentials(employee)
            self.assertEqual(first["label"], "Z-latest")
            self.assertEqual(first["label"], credentials["label"])
            self.assertEqual(first["document_reasoning_effort"], credentials["document_reasoning_effort"])

    def test_account_keeps_independent_efforts_after_legacy_patch(self):
        with self.settings(OPENAI_FERNET_KEYS=[Fernet.generate_key().decode("ascii")]):
            user = get_user_model().objects.create_user(username="reasoning_owner")
            employee = Employee.objects.create(user=user, employee_code="REASONING_OWNER", display_name="配置测试")
            self.client.force_login(user)
            created = self.client.post("/api/v1/ai-openai-configs/", {
                "label": "生产任务", "api_key": "test-only-provider-key",
            }, format="json")
            self.assertEqual(created.status_code, 201, created.data)
            url = f"/api/v1/ai-openai-configs/{created.data['data']['id']}/"
            settings = {"document_reasoning_effort": "xhigh", "material_reasoning_effort": "low"}
            changed = self.client.patch(url, settings, format="json", HTTP_IF_MATCH=created["ETag"])
            self.assertEqual(changed.status_code, 200, changed.data)
            legacy = self.client.patch(url, {"label": "新标签"}, format="json", HTTP_IF_MATCH=changed["ETag"])
            self.assertEqual(legacy.status_code, 200, legacy.data)
            saved = self.client.get(url).data["data"]
            credentials = get_active_credentials(employee)
            for key, expected in settings.items():
                self.assertEqual(saved[key], expected)
                self.assertEqual(credentials[key], expected)
            self.assertEqual(credentials["api_key"], "test-only-provider-key")

            other = get_user_model().objects.create_user(username="reasoning_other")
            Employee.objects.create(user=other, employee_code="REASONING_OTHER", display_name="其他账号")
            self.client.force_login(other)
            self.assertEqual(self.client.get(url).status_code, 404)
            denied = self.client.patch(url, settings, format="json", HTTP_IF_MATCH=legacy["ETag"])
            self.assertEqual(denied.status_code, 404)
