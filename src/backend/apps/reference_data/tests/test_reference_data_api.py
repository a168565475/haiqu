from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.customers.models import CustomerAccount, CustomerGradeReview
from apps.organizations.models import Employee
from apps.reference_data.models import (
    ConfigRelease,
    Country,
    Currency,
    DictionaryType,
    ExchangeRate,
    Incoterm,
    NumberRule,
    ReferenceDictionary,
    SystemParameterDefinition,
)


class ReferenceDataFoundationTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="reference_data_admin")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="REFERENCE_DATA_ADMIN",
            display_name="基础资料管理员",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="reference_data")
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def publish_config(self, notes):
        latest_release = ConfigRelease.objects.order_by("-version").first()
        return self.client.post(
            "/api/v1/reference-data/config-releases/",
            {"notes": notes},
            format="json",
            HTTP_IF_MATCH=etag_for_instance(latest_release),
        )

    def test_compatibility_migration_preserves_dictionary_shape(self):
        self.assertEqual(DictionaryType.objects.count(), 11)
        self.assertEqual(ReferenceDictionary.objects.count(), 68)
        self.assertFalse(ReferenceDictionary.objects.filter(dictionary_type__isnull=True).exists())
        self.assertEqual(Country.objects.count(), 249)
        initial_release = ConfigRelease.objects.get(version=2)
        self.assertEqual(initial_release.status, "PUBLISHED")
        self.assertEqual(len(initial_release.snapshot["dictionary_options"]), 11)
        self.assertEqual(
            sum(len(items) for items in initial_release.snapshot["dictionary_options"].values()),
            68,
        )
        summary = self.client.get("/api/v1/reference-data/summary/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(summary.data["data"]["active_dictionary_items"], 68)
        self.assertEqual(summary.data["data"]["active_system_parameters"], 6)
        self.assertEqual(summary.data["data"]["pending_changes"], 0)
        self.assertEqual(summary.data["data"]["config_version"], 2)

    def test_standard_reference_snapshots_are_complete_and_versioned(self):
        self.assertEqual(Country.objects.count(), 249)
        self.assertEqual(Currency.objects.count(), 178)
        self.assertEqual(Incoterm.objects.count(), 11)

        taiwan = Country.objects.get(code="TW")
        self.assertEqual(taiwan.alpha3_code, "TWN")
        self.assertEqual(taiwan.numeric_code, "158")
        self.assertEqual(taiwan.source_version, "UN M49 2026-08-26 / ISO 3166-1")

        euro = Currency.objects.get(code="EUR")
        self.assertEqual(euro.numeric_code, "978")
        self.assertEqual(euro.decimal_places, 2)
        self.assertEqual(euro.source_version, "ISO 4217 List One 2026-01-01")
        self.assertFalse(Currency.objects.filter(code="BGN").exists())

        self.assertSetEqual(
            set(Incoterm.objects.values_list("code", flat=True)),
            {"EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF"},
        )
        self.assertEqual(Incoterm.objects.filter(transport_scope="ANY_MODE").count(), 7)
        self.assertEqual(Incoterm.objects.filter(transport_scope="SEA_INLAND_WATERWAY").count(), 4)

        summary = self.client.get("/api/v1/reference-data/master-data-summary/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(summary.data["data"]["category_counts"]["countries"], 249)
        self.assertEqual(summary.data["data"]["category_counts"]["currencies"], 178)
        self.assertEqual(summary.data["data"]["category_counts"]["incoterms"], 11)
        self.assertEqual(summary.data["data"]["standard_source_count"], 5)
        self.assertIsNone(summary.data["data"]["base_currency"])

        filtered = self.client.get(
            "/api/v1/reference-data/countries/?source=ISO%203166&page_size=5"
        )
        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertEqual(filtered.data["meta"]["total"], 249)

    def test_existing_number_rules_are_registered_without_configuring_order(self):
        self.assertEqual(NumberRule.objects.count(), 6)
        quotation_rule = NumberRule.objects.get(number_type="QUOTATION")
        self.assertEqual(quotation_rule.format_pattern, "{prefix}-{date}-{sequence}")
        self.assertEqual(quotation_rule.sequence_name, "haiqu_quotation_number_seq")
        self.assertEqual(quotation_rule.date_granularity, "MONTH")
        self.assertEqual(quotation_rule.reset_policy, "NEVER")
        self.assertFalse(NumberRule.objects.get(number_type="ORDER").is_configured)

        response = self.client.get("/api/v1/reference-data/number-rules/?page_size=100")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 6)
        self.assertEqual(self.client.post("/api/v1/reference-data/number-rules/", {}, format="json").status_code, 405)

    def test_published_options_do_not_expose_draft_until_release(self):
        grade = ReferenceDictionary.objects.get(category_code="CUSTOMER_GRADE", item_code="A")
        detail_url = f"/api/v1/reference-data/dictionary-items/{grade.pk}/"
        original_options = self.client.get("/api/v1/reference-data/options/CUSTOMER_GRADE/")
        self.assertEqual(original_options.status_code, 200, original_options.data)
        initial_version = ConfigRelease.objects.order_by("-version").first().version
        self.assertEqual(original_options.data["meta"]["config_version"], initial_version)
        self.assertEqual(
            next(item for item in original_options.data["data"] if item["code"] == "A")["label"],
            "A",
        )

        missing_etag = self.client.patch(detail_url, {"display_name": "A+"}, format="json")
        self.assertEqual(missing_etag.status_code, 428, missing_etag.data)
        detail = self.client.get(detail_url)
        updated = self.client.patch(
            detail_url,
            {"display_name": "A+"},
            format="json",
            HTTP_IF_MATCH=detail["ETag"],
        )
        self.assertEqual(updated.status_code, 200, updated.data)

        still_published = self.client.get("/api/v1/reference-data/options/CUSTOMER_GRADE/")
        self.assertEqual(
            next(item for item in still_published.data["data"] if item["code"] == "A")["label"],
            "A",
        )
        missing_release_etag = self.client.post(
            "/api/v1/reference-data/config-releases/",
            {"notes": "缺少版本"},
            format="json",
        )
        self.assertEqual(missing_release_etag.status_code, 428, missing_release_etag.data)
        initial_version_etag = etag_for_instance(ConfigRelease.objects.get(version=initial_version))
        released = self.publish_config("测试发布")
        self.assertEqual(released.status_code, 201, released.data)
        self.assertEqual(released.data["data"]["version"], initial_version + 1)
        stale_release = self.client.post(
            "/api/v1/reference-data/config-releases/",
            {"notes": "过期并发发布"},
            format="json",
            HTTP_IF_MATCH=initial_version_etag,
        )
        self.assertEqual(stale_release.status_code, 412, stale_release.data)
        after_release = self.client.get("/api/v1/reference-data/options/CUSTOMER_GRADE/")
        self.assertEqual(after_release.data["meta"]["config_version"], initial_version + 1)
        self.assertEqual(
            next(item for item in after_release.data["data"] if item["code"] == "A")["label"],
            "A+",
        )
        self.assertTrue(
            AuditLog.objects.filter(object_type="CONFIG_RELEASE", action="PUBLISHED").exists()
        )

    def test_etag_stale_write_reference_confirmation_and_current_inactive_option(self):
        grade = ReferenceDictionary.objects.get(category_code="CUSTOMER_GRADE", item_code="B")
        customer = CustomerAccount.objects.create(
            account_code="REFERENCE-COUNT-CUSTOMER",
            account_name="引用统计测试客户",
            primary_country_code="SG",
        )
        CustomerGradeReview.objects.create(
            customer_account=customer,
            grade_item=grade,
            reviewed_by_employee=self.employee,
            reason="测试引用统计",
            effective_from=timezone.now(),
        )
        detail_url = f"/api/v1/reference-data/dictionary-items/{grade.pk}/"
        first = self.client.get(detail_url)
        stale_etag = first["ETag"]
        changed = self.client.patch(
            detail_url,
            {"description": "已更新"},
            format="json",
            HTTP_IF_MATCH=stale_etag,
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        stale = self.client.patch(
            detail_url,
            {"description": "过期写入"},
            format="json",
            HTTP_IF_MATCH=stale_etag,
        )
        self.assertEqual(stale.status_code, 412, stale.data)

        blocked = self.client.post(
            f"{detail_url}deactivate/",
            {"reason": "测试停用"},
            format="json",
            HTTP_IF_MATCH=changed["ETag"],
        )
        self.assertEqual(blocked.status_code, 409, blocked.data)
        confirmed = self.client.post(
            f"{detail_url}deactivate/",
            {"reason": "已确认历史引用", "confirm_references": True},
            format="json",
            HTTP_IF_MATCH=changed["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["data"]["status"], "INACTIVE")

        blocked_archive = self.client.post(
            f"{detail_url}archive/",
            {"reason": "不再使用"},
            format="json",
            HTTP_IF_MATCH=confirmed["ETag"],
        )
        self.assertEqual(blocked_archive.status_code, 409, blocked_archive.data)

        released = self.publish_config("发布停用项")
        self.assertEqual(released.status_code, 201, released.data)
        normal_options = self.client.get("/api/v1/reference-data/options/CUSTOMER_GRADE/")
        self.assertNotIn("B", {item["code"] for item in normal_options.data["data"]})
        historical_options = self.client.get(
            f"/api/v1/reference-data/options/CUSTOMER_GRADE/?current_id={grade.pk}"
        )
        current = next(item for item in historical_options.data["data"] if item["code"] == "B")
        self.assertEqual(current["status"], "INACTIVE")
        self.assertTrue(current["extra"]["current_selection"])
        self.assertEqual(self.client.delete(detail_url).status_code, 405)

    def test_country_validation_exchange_rate_correction_and_no_overwrite_endpoint(self):
        self.assertEqual(self.client.get("/api/v1/reference-data/countries/").data["meta"]["total"], 249)
        usd_id = str(Currency.objects.get(code="USD").pk)
        cny_id = str(Currency.objects.get(code="CNY").pk)

        same_currency = self.client.post(
            "/api/v1/reference-data/exchange-rates/",
            {
                "base_currency": usd_id,
                "quote_currency": usd_id,
                "rate": "1.00000000",
                "effective_date": "2026-08-26",
                "source_name": "人工录入",
            },
            format="json",
        )
        self.assertEqual(same_currency.status_code, 400, same_currency.data)
        negative = self.client.post(
            "/api/v1/reference-data/exchange-rates/",
            {
                "base_currency": usd_id,
                "quote_currency": cny_id,
                "rate": "-1.00000000",
                "effective_date": "2026-08-26",
                "source_name": "人工录入",
            },
            format="json",
        )
        self.assertEqual(negative.status_code, 400, negative.data)
        created = self.client.post(
            "/api/v1/reference-data/exchange-rates/",
            {
                "base_currency": usd_id,
                "quote_currency": cny_id,
                "rate": "7.10000000",
                "effective_date": "2026-08-26",
                "source_name": "人工录入",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["entered_by_name"], self.employee.display_name)
        rate_id = created.data["data"]["id"]
        self.assertEqual(
            self.client.patch(
                f"/api/v1/reference-data/exchange-rates/{rate_id}/",
                {"rate": "7.20000000"},
                format="json",
                HTTP_IF_MATCH=created["ETag"],
            ).status_code,
            405,
        )
        corrected = self.client.post(
            f"/api/v1/reference-data/exchange-rates/{rate_id}/correct/",
            {
                "rate": "7.20000000",
                "effective_date": "2026-08-27",
                "source_name": "人工更正",
                "description": "更正录入错误",
            },
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(corrected.status_code, 201, corrected.data)
        old_rate = ExchangeRate.objects.get(pk=rate_id)
        new_rate = ExchangeRate.objects.get(pk=corrected.data["data"]["id"])
        self.assertEqual(old_rate.status, "INACTIVE")
        self.assertEqual(new_rate.correction_of_id, old_rate.pk)

    def test_system_parameter_is_draft_and_validates_master_data(self):
        definition = SystemParameterDefinition.objects.get(code="DEFAULT_CURRENCY")
        detail_url = f"/api/v1/reference-data/system-parameters/{definition.pk}/"
        detail = self.client.get(detail_url)
        self.assertEqual(detail.status_code, 200, detail.data)
        invalid = self.client.patch(
            detail_url,
            {"draft_value": "ZZZ"},
            format="json",
            HTTP_IF_MATCH=detail["ETag"],
        )
        self.assertEqual(invalid.status_code, 400, invalid.data)
        refreshed = self.client.get(detail_url)
        updated = self.client.patch(
            detail_url,
            {"draft_value": "USD"},
            format="json",
            HTTP_IF_MATCH=refreshed["ETag"],
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["data"]["draft_value"], "USD")
        self.assertIsNone(ConfigRelease.objects.get(version=1).snapshot["system_parameters"]["DEFAULT_CURRENCY"])

    def test_model_instance_physical_delete_is_rejected(self):
        country = Country.objects.get(code="SG")
        with self.assertRaises(DjangoValidationError):
            country.delete()
