import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee

from ..api.serializers import WorkshopEmployeeSerializer
from ..models import Workshop, WorkshopEmployee
from ..selectors import active_employees, employees_with_context
from ..services import create_config, update_config


@override_settings(DEV_AUTO_LOGIN_ENABLED=False, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class WorkshopEmployeeIdentityTests(TestCase):
    url = "/api/v1/workshop-config/employees/"

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="identity-manager", password="test")
        self.actor = Employee.objects.create(user=self.user, employee_code="IDENTITY-MANAGER", display_name="配置管理员")
        self.user.user_permissions.set(Permission.objects.filter(
            content_type__app_label="workshop_config",
            codename__in=["view_workshopemployee", "add_workshopemployee", "change_workshopemployee"],
        ))
        self.client = self.browser(self.user)
        self.workshop = Workshop.objects.get(name="装配车间")
        self.source = Employee.objects.create(employee_code="IDENTITY-SOURCE", display_name="统一员工甲")

    def browser(self, user):
        browser = APIClient(enforce_csrf_checks=True)
        browser.force_login(user)
        self.assertEqual(browser.get("/api/auth/me/").status_code, 200)
        return browser

    def payload(self, **overrides):
        return {"workshop": str(self.workshop.pk), "employee": str(self.source.pk),
                "position": "装配工", "is_supervisor": False, "status": "ACTIVE", **overrides}

    def post(self, payload=None):
        return self.client.post(self.url, self.payload() if payload is None else payload,
                                format="json", HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value)

    def record(self, *, source=None, legacy=False, **overrides):
        return WorkshopEmployee.objects.create(
            workshop=self.workshop, employee=None if legacy else (source or self.source),
            **{"name": "历史姓名", "position": "装配工", "is_supervisor": False, **overrides},
        )

    def update(self, record, data, *, etag=None):
        headers = {"HTTP_X_CSRFTOKEN": self.client.cookies["csrftoken"].value}
        if etag is not False:
            headers["HTTP_IF_MATCH"] = etag or etag_for_instance(record)
        return self.client.patch(f"{self.url}{record.pk}/", data, format="json", **headers)

    def test_create_uses_employee_without_account_or_role(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        row = WorkshopEmployee.objects.get()
        self.assertEqual(row.employee_id, self.source.pk)
        self.assertEqual(row.name, self.source.display_name)
        self.assertEqual(row.created_by_employee_id, self.actor.pk)
        self.assertEqual(response.data["data"]["employee"], self.source.pk)
        self.assertEqual(response.data["data"]["employee_code"], self.source.employee_code)
        self.assertFalse(response.data["data"]["employee_archived"])
        self.source.refresh_from_db()
        self.assertIsNone(self.source.user_id)
        self.assertEqual(Employee.objects.count(), 2)

    def test_missing_null_invalid_and_unknown_employee_are_rejected(self):
        for value in (None, "not-a-uuid", str(uuid.uuid4())):
            with self.subTest(employee=value):
                response = self.post(self.payload(employee=value))
                self.assertEqual(response.status_code, 400, response.data)
        payload = self.payload()
        payload.pop("employee")
        self.assertEqual(self.post(payload).status_code, 400)
        self.assertFalse(WorkshopEmployee.objects.exists())

    def test_inactive_left_and_archived_sources_cannot_be_created(self):
        for status, archived in (("INACTIVE", None), ("LEFT", None), ("ACTIVE", timezone.now())):
            with self.subTest(status=status, archived=bool(archived)):
                Employee.objects.filter(pk=self.source.pk).update(status=status, archived_at=archived)
                response = self.post()
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(WorkshopEmployee.objects.exists())

    def test_disabled_login_account_does_not_exclude_active_employee(self):
        user = get_user_model().objects.create_user(username="disabled-worker", is_active=False)
        self.source.user = user
        self.source.save(update_fields=["user", "updated_at"])
        self.assertEqual(self.post().status_code, 201)

    def test_name_length_is_not_silently_truncated(self):
        self.source.display_name = "甲" * 101
        self.source.save(update_fields=["display_name", "updated_at"])
        self.assertEqual(self.post().status_code, 400)
        self.assertFalse(WorkshopEmployee.objects.exists())
        self.source.display_name = "甲" * 100
        self.source.save(update_fields=["display_name", "updated_at"])
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(WorkshopEmployee.objects.get().name, "甲" * 100)

    def test_explicit_name_cannot_override_source_or_history(self):
        self.assertEqual(self.post(self.payload(name="冒名员工")).status_code, 400)
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                row = self.record(legacy=legacy, position=f"岗位-{legacy}")
                response = self.update(row, {"name": row.name})
                self.assertEqual(response.status_code, 400, response.data)
                row.refresh_from_db()
                self.assertEqual(row.name, "历史姓名")

    def test_legacy_metadata_update_keeps_identity_and_historical_name(self):
        row = self.record(legacy=True)
        response = self.update(row, {"is_supervisor": True, "position": "组长"})
        self.assertEqual(response.status_code, 200, response.data)
        row.refresh_from_db()
        self.assertIsNone(row.employee_id)
        self.assertEqual(row.name, "历史姓名")
        self.assertTrue(row.is_supervisor)

    def test_legacy_first_link_preserves_name_even_with_long_source_name(self):
        row = self.record(legacy=True)
        self.source.display_name = "乙" * 101
        self.source.save(update_fields=["display_name", "updated_at"])
        response = self.update(row, {"employee": str(self.source.pk)})
        self.assertEqual(response.status_code, 200, response.data)
        row.refresh_from_db()
        self.assertEqual(row.employee_id, self.source.pk)
        self.assertEqual(row.name, "历史姓名")
        self.assertEqual(response.data["data"]["employee_name"], "乙" * 101)

    def test_legacy_first_link_requires_active_unarchived_source(self):
        row = self.record(legacy=True, status="LEFT")
        for status, archived in (("LEFT", None), ("INACTIVE", None), ("ACTIVE", timezone.now())):
            with self.subTest(status=status, archived=bool(archived)):
                Employee.objects.filter(pk=self.source.pk).update(status=status, archived_at=archived)
                response = self.update(row, {"employee": str(self.source.pk)})
                self.assertEqual(response.status_code, 400, response.data)
        row.refresh_from_db()
        self.assertIsNone(row.employee_id)

    def test_linked_identity_cannot_change_or_unbind(self):
        row = self.record()
        other = Employee.objects.create(employee_code="IDENTITY-OTHER", display_name="统一员工乙")
        for employee in (None, str(other.pk)):
            with self.subTest(employee=employee):
                response = self.update(row, {"employee": employee})
                self.assertEqual(response.status_code, 400, response.data)
        row.refresh_from_db()
        self.assertEqual(row.employee_id, self.source.pk)

    def test_same_employee_same_position_duplicate_is_rejected(self):
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(WorkshopEmployee.objects.count(), 1)

    def test_same_name_different_people_and_multiple_assignments_are_allowed(self):
        other = Employee.objects.create(employee_code="IDENTITY-SAME-NAME", display_name=self.source.display_name)
        for payload in (
            self.payload(), self.payload(employee=str(other.pk)), self.payload(position="包装工"),
            self.payload(workshop=str(Workshop.objects.get(name="车缝车间").pk)),
        ):
            response = self.post(payload)
            self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(WorkshopEmployee.objects.count(), 4)

    def test_linked_and_unlinked_same_name_can_coexist(self):
        self.record(legacy=True, name=self.source.display_name)
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(WorkshopEmployee.objects.count(), 2)

    def test_database_constraints_protect_both_identity_modes(self):
        self.record(legacy=True)
        self.record()
        for legacy in (False, True):
            with self.subTest(legacy=legacy), self.assertRaises(IntegrityError), transaction.atomic():
                self.record(legacy=legacy)
        self.assertEqual(WorkshopEmployee.objects.count(), 2)

    def test_employee_foreign_key_protects_identity(self):
        row = self.record()
        with self.assertRaises(ProtectedError):
            Employee.objects.filter(pk=self.source.pk).delete()
        self.assertTrue(WorkshopEmployee.objects.filter(pk=row.pk, employee=self.source).exists())

    def test_legacy_link_collision_does_not_partially_update_metadata(self):
        self.record()
        legacy = self.record(legacy=True, name="待核对姓名")
        response = self.update(legacy, {"employee": str(self.source.pk), "is_supervisor": True})
        self.assertEqual(response.status_code, 400, response.data)
        legacy.refresh_from_db()
        self.assertIsNone(legacy.employee_id)
        self.assertFalse(legacy.is_supervisor)

    def test_read_tracks_source_changes_without_rewriting_historical_name(self):
        row = self.record()
        Employee.objects.filter(pk=self.source.pk).update(display_name="改名后的主档", status="LEFT", archived_at=timezone.now())
        response = self.client.get(f"{self.url}{row.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["name"], "历史姓名")
        self.assertEqual(response.data["data"]["employee_name"], "改名后的主档")
        self.assertEqual(response.data["data"]["employee_status"], "LEFT")
        self.assertTrue(response.data["data"]["employee_archived"])
        row.refresh_from_db()
        self.assertEqual(row.name, "历史姓名")

    def test_invalid_linked_source_allows_left_but_not_final_active(self):
        row = self.record()
        Employee.objects.filter(pk=self.source.pk).update(status="INACTIVE")
        self.assertEqual(self.update(row, {"is_supervisor": True}).status_code, 400)
        response = self.update(row, {"status": "LEFT"})
        self.assertEqual(response.status_code, 200, response.data)
        row.refresh_from_db()
        self.assertEqual(self.update(row, {"is_supervisor": True}).status_code, 200)
        row.refresh_from_db()
        self.assertEqual(self.update(row, {"status": "ACTIVE"}).status_code, 400)

    def test_legacy_response_does_not_automatically_match_name(self):
        row = self.record(legacy=True, name=self.source.display_name)
        data = self.client.get(f"{self.url}{row.pk}/").data["data"]
        for key in ("employee", "employee_code", "employee_name", "employee_status"):
            self.assertIsNone(data[key])
        self.assertFalse(data["employee_archived"])
        row.refresh_from_db()
        self.assertIsNone(row.employee_id)

    def test_session_csrf_is_required_for_create_and_update(self):
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 403)
        self.assertFalse(WorkshopEmployee.objects.exists())
        row = self.record()
        response = self.client.patch(f"{self.url}{row.pk}/", {"is_supervisor": True}, format="json",
                                     HTTP_IF_MATCH=etag_for_instance(row))
        self.assertEqual(response.status_code, 403)
        row.refresh_from_db()
        self.assertFalse(row.is_supervisor)

    def test_missing_stale_and_current_etags(self):
        row = self.record()
        self.assertEqual(self.update(row, {"is_supervisor": True}, etag=False).status_code, 428)
        self.assertEqual(self.update(row, {"is_supervisor": True}, etag='"stale"').status_code, 412)
        response = self.update(row, {"is_supervisor": True})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(response["ETag"], etag_for_instance(row))

    def test_options_require_add_or_change_permission_not_view_only(self):
        for permission, expected in (("add_workshopemployee", 200), ("change_workshopemployee", 200),
                                     ("view_workshopemployee", 403)):
            with self.subTest(permission=permission):
                user = get_user_model().objects.create_user(username=permission)
                Employee.objects.create(user=user, employee_code=permission.upper(), display_name="候选权限测试")
                user.user_permissions.add(Permission.objects.get(content_type__app_label="workshop_config", codename=permission))
                response = self.browser(user).get(f"{self.url}employee-options/")
                self.assertEqual(response.status_code, expected, response.data)

    def test_options_filter_search_paginate_and_expose_only_minimal_fields(self):
        for suffix, status, archived in (("01", "ACTIVE", None), ("02", "ACTIVE", None),
                                         ("03", "LEFT", None), ("04", "INACTIVE", None),
                                         ("05", "ACTIVE", timezone.now())):
            Employee.objects.create(employee_code=f"OPTION-{suffix}", display_name=f"候选人{suffix}",
                                    status=status, archived_at=archived)
        response = self.client.get(f"{self.url}employee-options/", {"q": "OPTION-", "page_size": 1, "page": 2})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 2)
        self.assertEqual(response.data["data"][0]["employee_code"], "OPTION-02")
        self.assertEqual(set(response.data["data"][0]), {"id", "employee_code", "display_name", "status", "etag"})
        by_name = self.client.get(f"{self.url}employee-options/", {"q": "候选人01"})
        self.assertEqual(by_name.data["meta"]["total"], 1)
        self.assertFalse(WorkshopEmployee.objects.exists())

    def test_anonymous_and_inactive_actor_cannot_read_options_or_write(self):
        anonymous = APIClient()
        self.assertIn(anonymous.get(f"{self.url}employee-options/").status_code, (401, 403))
        self.actor.status = "LEFT"
        self.actor.save(update_fields=["status", "updated_at"])
        self.assertEqual(self.client.get(f"{self.url}employee-options/").status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.post().status_code, 401)
        self.assertFalse(WorkshopEmployee.objects.exists())

    def test_list_serializer_fetches_sources_in_one_query(self):
        for index in range(6):
            self.record(legacy=index % 2 == 0, position=f"岗位{index}")
        with self.assertNumQueries(1):
            rows = WorkshopEmployeeSerializer(employees_with_context(WorkshopEmployee.objects.all()), many=True).data
        self.assertEqual(len(rows), 6)
        self.assertEqual(sum(row["employee_name"] == self.source.display_name for row in rows), 3)

    def test_create_audit_failure_rolls_back_identity(self):
        with patch("apps.workshop_config.services.write_audit_log", side_effect=RuntimeError("审计写入失败")):
            with self.assertRaisesRegex(RuntimeError, "审计写入失败"):
                create_config(model_class=WorkshopEmployee, actor_employee=self.actor, validated_data={
                    "workshop": self.workshop, "employee": self.source, "position": "装配工", "is_supervisor": False,
                })
        self.assertFalse(WorkshopEmployee.objects.exists())

    def test_first_link_audit_failure_rolls_back_all_fields(self):
        row = self.record(legacy=True)
        with patch("apps.workshop_config.services.write_audit_log", side_effect=RuntimeError("审计写入失败")):
            with self.assertRaisesRegex(RuntimeError, "审计写入失败"):
                update_config(model_class=WorkshopEmployee, instance_id=row.pk, actor_employee=self.actor,
                              request=SimpleNamespace(headers={"If-Match": etag_for_instance(row)}),
                              validated_data={"employee": self.source, "is_supervisor": True})
        row.refresh_from_db()
        self.assertIsNone(row.employee_id)
        self.assertFalse(row.is_supervisor)
        self.assertEqual(row.name, "历史姓名")

    def test_service_rechecks_stale_source_object(self):
        Employee.objects.filter(pk=self.source.pk).update(status="LEFT")
        self.assertEqual(self.source.status, "ACTIVE")
        with self.assertRaises(ValidationError):
            create_config(model_class=WorkshopEmployee, actor_employee=self.actor, validated_data={
                "workshop": self.workshop, "employee": self.source, "position": "装配工", "is_supervisor": False,
            })
        self.assertFalse(WorkshopEmployee.objects.exists())

    def test_active_selector_keeps_legacy_and_excludes_invalid_linked_identity(self):
        legacy = self.record(legacy=True)
        linked = self.record(position="另一岗位")
        self.record(legacy=True, position="已离职", status="LEFT")
        self.assertSetEqual(set(active_employees(WorkshopEmployee.objects.all()).values_list("pk", flat=True)),
                            {legacy.pk, linked.pk})
        Employee.objects.filter(pk=self.source.pk).update(archived_at=timezone.now())
        self.assertEqual(list(active_employees(WorkshopEmployee.objects.all()).values_list("pk", flat=True)), [legacy.pk])
