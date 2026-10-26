import re

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITransactionTestCase

from apps.customers.models import (
    CustomerAccount,
    CustomerContact,
    CustomerEntityAddress,
    CustomerGradeReview,
    CustomerTransactionEntity,
)
from apps.organizations.models import Employee
from apps.reference_data import configuration_cache
from apps.reference_data.models import DictionaryType, ReferenceDictionary
from apps.reference_data.services import dictionary_reference_count


TEST_CACHES = {
    alias: {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": f"reference-count-queries-{alias}",
    }
    for alias in ("default", "configuration", "wecom")
}
ROOT = "/api/v1/reference-data/"
COUNTRY_REFERENCE_FIELDS = (
    ("customer_account", "primary_country_code"),
    ("customer_transaction_entity", "registration_country_code"),
    ("customer_transaction_entity", "tax_country_code"),
    ("customer_entity_address", "country_code"),
)


def country_reference_queries(queries):
    """只统计国家引用聚合，不把认证、分页及其他业务查询算入预算。"""
    return [
        query["sql"]
        for query in queries
        if re.search(r"\bCOUNT\s*\(", query["sql"], re.IGNORECASE)
        and any(
            f'"{table}"' in query["sql"] and f'"{field}"' in query["sql"]
            for table, field in COUNTRY_REFERENCE_FIELDS
        )
    ]


@override_settings(CACHES=TEST_CACHES)
class ReferenceCountQueryTests(APITransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="reference_count_queries_admin", is_superuser=True, is_staff=True,
        )
        self.employee = Employee.objects.create(
            user=self.user, employee_code="REFERENCE_COUNT_QUERIES", display_name="引用统计测试",
        )
        self.client.force_authenticate(self.user)
        self.clear_configuration_cache()
        self.addCleanup(self.clear_configuration_cache)

    def clear_configuration_cache(self):
        caches["configuration"].clear()
        configuration_cache._disabled_until = 0

    def make_item(self, category, code, *, label=None, **values):
        dictionary_type, _ = DictionaryType.objects.get_or_create(
            code=category,
            defaults={"chinese_name": category, "group_code": "CUSTOMER"},
        )
        return ReferenceDictionary.objects.create(
            dictionary_type=dictionary_type, category_code=category, item_code=code,
            display_name=label or f"QUERY_COUNTRY_{code}", **values,
        )

    def make_customer(self, code, country="", **values):
        return CustomerAccount.objects.create(
            account_code=code, account_name=code, primary_country_code=country, **values,
        )

    def get_list(self, url):
        response = self.client.get(url, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def measured_country_queries(self, url, *, warm):
        self.clear_configuration_cache()
        if warm:
            self.get_list(url)
        with CaptureQueriesContext(connection) as captured:
            rows = self.get_list(url)
        return rows, country_reference_queries(captured.captured_queries)

    def assert_country_query_count_is_bounded(self, endpoint, *, warm):
        self.make_item("COUNTRY_REGION", "QX")
        url = ROOT + (
            "dictionary-items/?type_code=COUNTRY_REGION&q=QUERY_COUNTRY_"
            if endpoint == "items" else "dictionary-types/?q=COUNTRY_REGION"
        )
        first_rows, first_queries = self.measured_country_queries(url, warm=warm)
        self.assertTrue(first_rows)
        self.assertGreater(len(first_queries), 0)
        self.make_item("COUNTRY_REGION", "QY")
        self.make_item("COUNTRY_REGION", "QZ")
        rows, queries = self.measured_country_queries(url, warm=warm)
        if endpoint == "items":
            self.assertEqual(len(first_rows), 1)
            self.assertEqual(len(rows), 3)
        self.assertEqual(
            len(queries), len(first_queries),
            f"同一引用字段的列表扩容不应增加统计SQL：{len(first_queries)} -> {len(queries)}",
        )

    def test_cold_item_list_reference_queries_do_not_grow_per_item(self):
        self.assert_country_query_count_is_bounded("items", warm=False)

    def test_hot_item_list_reference_queries_do_not_grow_per_item(self):
        self.assert_country_query_count_is_bounded("items", warm=True)

    def test_cold_type_list_reference_queries_do_not_grow_per_child(self):
        self.assert_country_query_count_is_bounded("types", warm=False)

    def test_hot_type_list_reference_queries_do_not_grow_per_child(self):
        self.assert_country_query_count_is_bounded("types", warm=True)

    def test_cold_lists_do_not_repeat_reference_aggregation(self):
        for code in ("QX", "QY", "QZ"):
            self.make_item("COUNTRY_REGION", code)
        for suffix in (
            "dictionary-items/?type_code=COUNTRY_REGION&q=QUERY_COUNTRY_",
            "dictionary-types/?q=COUNTRY_REGION",
        ):
            with self.subTest(endpoint=suffix):
                cold_rows, cold_queries = self.measured_country_queries(ROOT + suffix, warm=False)
                hot_rows, hot_queries = self.measured_country_queries(ROOT + suffix, warm=True)
                self.assertEqual(cold_rows, hot_rows)
                self.assertGreater(len(hot_queries), 0)
                self.assertEqual(len(cold_queries), len(hot_queries))

    def test_country_counts_all_four_fields_and_archived_references(self):
        item = self.make_item("COUNTRY_REGION", "QX")
        for label, archived_at in (("ACTIVE", None), ("ARCHIVED", timezone.now())):
            customer = self.make_customer(f"COUNT_{label}", "QX", archived_at=archived_at)
            entity = CustomerTransactionEntity.objects.create(
                customer_account=customer, entity_code=f"ENTITY_{label}", legal_name=label,
                registration_country_code="QX", tax_country_code="QX", archived_at=archived_at,
            )
            CustomerEntityAddress.objects.create(
                transaction_entity=entity, address_code="ADDRESS", country_code="QX",
                address_line1="隔离测试地址", archived_at=archived_at,
            )
        self.make_customer("COUNT_OTHER_COUNTRY", "QY")
        self.assertEqual(dictionary_reference_count(item), 8)
        rows = self.get_list(ROOT + "dictionary-items/?type_code=COUNTRY_REGION&q=QUERY_COUNTRY_")
        self.assertEqual([(row["id"], row["reference_count"]) for row in rows], [(str(item.pk), 8)])

    def test_item_code_uuid_timezone_duplicates_and_empty_values_keep_counts(self):
        language = self.make_item("CONTACT_LANGUAGE", "RC_LANGUAGE", label="RC_SEMANTICS_LANGUAGE")
        grade = self.make_item("CUSTOMER_GRADE", "RC_GRADE", label="RC_SEMANTICS_GRADE")
        zones = [
            self.make_item("CONTACT_TIMEZONE", f"RC_ZONE_{suffix}", label=f"RC_SEMANTICS_ZONE_{suffix}",
                           extra_data=extra)
            for suffix, extra in (
                ("A", {"timezone_code": "Etc/UTC"}),
                ("B", {"timezone_code": "Etc/UTC"}),
                ("MISSING", {}),
                ("EMPTY", {"timezone_code": ""}),
                ("NULL", {"timezone_code": None}),
                ("NUMBER", {"timezone_code": 123}),
            )
        ]
        customer = self.make_customer("COUNT_VALUE_SOURCES")
        for label, archived_at in (("有效联系人", None), ("归档联系人", timezone.now())):
            CustomerContact.objects.create(
                customer_account=customer, display_name=label, preferred_language_code="RC_LANGUAGE",
                timezone_code="Etc/UTC", archived_at=archived_at,
            )
        CustomerContact.objects.create(customer_account=customer, display_name="空值联系人", timezone_code="")
        CustomerContact.objects.create(customer_account=customer, display_name="大小写不同", timezone_code="etc/utc")
        CustomerContact.objects.create(customer_account=customer, display_name="字段类型转换", timezone_code="123")
        CustomerGradeReview.objects.create(
            customer_account=customer, grade_item=grade, reviewed_by_employee=self.employee,
            reason="隔离测试UUID引用", effective_from=timezone.now(),
        )
        expected = {language.pk: 2, grade.pk: 1, zones[0].pk: 2, zones[1].pk: 2,
                    zones[2].pk: 0, zones[3].pk: 0, zones[4].pk: 0, zones[5].pk: 1}
        for item in (language, grade, *zones):
            self.assertEqual(dictionary_reference_count(item), expected[item.pk])
        rows = self.get_list(ROOT + "dictionary-items/?q=RC_SEMANTICS_")
        self.assertEqual(
            {row["id"]: row["reference_count"] for row in rows},
            {str(item_id): count for item_id, count in expected.items()},
        )

    def test_type_counts_inactive_and_archived_children(self):
        self.make_item("COUNTRY_REGION", "QX")
        self.make_item("COUNTRY_REGION", "QY", status="INACTIVE")
        self.make_item("COUNTRY_REGION", "QZ", status="INACTIVE", archived_at=timezone.now())
        for code in ("QX", "QY", "QZ"):
            self.make_customer(f"COUNT_CHILD_{code}", code)
        rows = self.get_list(ROOT + "dictionary-types/?q=COUNTRY_REGION")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reference_count"], 3)
        listed = self.get_list(ROOT + "dictionary-items/?type_code=COUNTRY_REGION&q=QUERY_COUNTRY_")
        self.assertEqual({row["item_code"] for row in listed}, {"QX", "QY"})
        listed_with_archived = self.get_list(
            ROOT + "dictionary-items/?type_code=COUNTRY_REGION&q=QUERY_COUNTRY_&include_archived=true"
        )
        self.assertEqual({row["item_code"] for row in listed_with_archived}, {"QX", "QY", "QZ"})

    def test_empty_lists_do_not_query_country_references(self):
        for endpoint in ("dictionary-items", "dictionary-types"):
            with self.subTest(endpoint=endpoint):
                rows, queries = self.measured_country_queries(
                    ROOT + f"{endpoint}/?q=RC_EMPTY_NO_MATCH", warm=False,
                )
                self.assertEqual(rows, [])
                self.assertEqual(queries, [])

    def test_warm_lists_refresh_counts_after_business_reference_changes(self):
        item = self.make_item("COUNTRY_REGION", "QX")
        item_url = ROOT + "dictionary-items/?type_code=COUNTRY_REGION&q=QUERY_COUNTRY_"
        type_url = ROOT + "dictionary-types/?q=COUNTRY_REGION"
        for url in (item_url, type_url):
            self.assertEqual(self.get_list(url)[0]["reference_count"], 0)
        self.make_customer("COUNT_NEW_REFERENCE", item.item_code)
        for url in (item_url, type_url):
            self.assertEqual(self.get_list(url)[0]["reference_count"], 1)

    def test_detail_deactivate_and_archive_keep_live_reference_protection(self):
        item = self.make_item("COUNTRY_REGION", "QX")
        self.get_list(ROOT + "dictionary-items/?type_code=COUNTRY_REGION&q=QUERY_COUNTRY_")
        self.make_customer("COUNT_PROTECTED_REFERENCE", "QX")
        detail_url = ROOT + f"dictionary-items/{item.pk}/"
        detail = self.client.get(detail_url, HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["data"]["reference_count"], 1)
        for action in ("deactivate", "archive"):
            response = self.client.post(
                detail_url + action + "/", {"reason": "验证实时引用保护"}, format="json",
                HTTP_HOST="localhost", HTTP_IF_MATCH=detail["ETag"],
            )
            self.assertEqual(response.status_code, 409, response.data)
        confirmed = self.client.post(
            detail_url + "deactivate/", {"reason": "确认保留历史引用", "confirm_references": True},
            format="json", HTTP_HOST="localhost", HTTP_IF_MATCH=detail["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["data"]["status"], "INACTIVE")
        self.assertEqual(confirmed.data["data"]["reference_count"], 1)
        archived = self.client.post(
            detail_url + "archive/", {"reason": "停用后仍有历史引用"}, format="json",
            HTTP_HOST="localhost", HTTP_IF_MATCH=confirmed["ETag"],
        )
        self.assertEqual(archived.status_code, 409, archived.data)
        item.refresh_from_db()
        self.assertIsNone(item.archived_at)
