from django.contrib.auth import get_user_model
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth.models import Group
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APITestCase

from apps.access_control.models import RoleGrantResource
from apps.access_control.sales_policy import access_for
from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee
from apps.organizations.models import EmployeeRoleAssignment, RoleProfile
from apps.workshop_config.models import Workshop
from apps.workshop_config.api.serializers import WorkshopEmployeeSerializer
from apps.workshop_config.selectors import employees_with_context
from apps.workshop_config.services import update_employee_workshop
from apps.workshop_config.tests.factories import production_employee


VIEW = "workshop_config.view_workshopemployee"
CHANGE = "workshop_config.change_workshopemployee"


@override_settings(DEV_AUTO_LOGIN_ENABLED=False, ACCESS_MANAGEMENT_ENABLED=True,
                   MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
                   ACCESS_RESOURCE_SCOPES_ENABLED=True)
class WorkshopEmployeeScopeTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        self.scoped_actor()
        self.metal = Workshop.objects.get(name="金工车间")
        self.sewing = Workshop.objects.get(name="车缝车间")
        self.assembly = Workshop.objects.get(name="装配车间")
        self.metal_worker = production_employee(workshop=self.metal, position="金工", name="金工员工")
        self.unset_position_worker = production_employee(workshop=self.metal, position="", name="待定岗位员工")
        self.sewing_worker = production_employee(workshop=self.sewing, position="车缝", name="车缝员工")
        self.unassigned = production_employee(workshop=None, position="", name="未安排员工")
        self.base = "/api/v1/workshop-config/employees/"

    def url(self, employee):
        return f"{self.base}{employee.pk}/"

    def update(self, employee, payload, **headers):
        return self.client.patch(self.url(employee), payload, format="json",
                                 HTTP_IF_MATCH=etag_for_instance(employee), **headers)

    def assign_workshop_role(self, employee, name, *, archived=False, **dates):
        code = f"ROLE_TEST_{uuid4().hex.upper()}"
        role = RoleProfile.objects.create(
            auth_group=Group.objects.create(name=code), role_code=code, display_name=name,
            archived_at=timezone.now() if archived else None,
        )
        return EmployeeRoleAssignment.objects.create(
            employee=employee, role_profile=role,
            effective_from=dates.pop("effective_from", timezone.now() - timedelta(days=1)), **dates,
        )

    def test_list_detail_summary_and_forged_filter_stay_in_view_scope(self):
        self.grant(VIEW, "WORKSHOP", [self.metal])
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({row["id"] for row in response.data["data"]}, {str(self.metal_worker.pk), str(self.unset_position_worker.pk)})
        self.assertFalse(response.data["data"][0]["can_edit"])
        self.assertEqual(self.client.get(self.url(self.metal_worker)).status_code, 200)
        for employee in (self.sewing_worker, self.unassigned):
            self.assertEqual(self.client.get(self.url(employee)).status_code, 404)
        filtered = self.client.get(self.base, {"workshop": str(self.sewing.pk)})
        self.assertEqual(filtered.data["data"], [])
        summary = self.client.get(self.base + "summary/")
        self.assertEqual(summary.data["data"], {"total": 2, "active": 2, "left": 0, "active_supervisors": 0})

    def test_position_state_filter_lists_only_assigned_employees_without_a_position(self):
        self.grant(VIEW, "WORKSHOP", [self.metal])
        pending = self.client.get(self.base, {"position_state": "UNSET"})
        self.assertEqual(pending.status_code, 200, pending.data)
        self.assertEqual([row["id"] for row in pending.data["data"]], [str(self.unset_position_worker.pk)])
        configured = self.client.get(self.base, {"position_state": "SET"})
        self.assertEqual(configured.status_code, 200, configured.data)
        self.assertEqual([row["id"] for row in configured.data["data"]], [str(self.metal_worker.pk)])
        invalid = self.client.get(self.base, {"position_state": "UNKNOWN"})
        self.assertEqual(invalid.status_code, 400, invalid.data)

    def test_role_pending_lists_unassigned_employee_and_locks_role_workshop(self):
        role = RoleProfile.objects.create(
            auth_group=Group.objects.create(name="角色测试金工"), role_code="METAL_WORKSHOP", display_name="金工车间",
        )
        role_worker = production_employee(workshop=None, position="", name="角色待安排员工")
        EmployeeRoleAssignment.objects.create(
            employee=role_worker, role_profile=role, effective_from=timezone.now() - timedelta(days=1),
        )
        self.grant(VIEW, "WORKSHOP", [self.metal])
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        response = self.client.get(self.base, {"position_state": "ROLE_PENDING"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["id"] for row in response.data["data"]], [str(role_worker.pk)])
        row = response.data["data"][0]
        self.assertEqual(row["role_workshop"], str(self.metal.pk))
        self.assertEqual(row["role_workshop_name"], "金工车间")
        self.assertTrue(row["can_edit"])
        response = self.update(role_worker, {"workshop": str(self.metal.pk), "position": "金工"})
        self.assertEqual(response.status_code, 200, response.data)
        role_worker.refresh_from_db()
        self.assertEqual(role_worker.workshop_id, self.metal.pk)

    def test_role_pending_excludes_mismatched_existing_workshop(self):
        role = RoleProfile.objects.create(
            auth_group=Group.objects.create(name="角色测试装配"), role_code="ASSEMBLY_WORKSHOP", display_name="装配车间",
        )
        role_worker = production_employee(workshop=self.sewing, position="", name="角色错配员工")
        EmployeeRoleAssignment.objects.create(
            employee=role_worker, role_profile=role, effective_from=timezone.now() - timedelta(days=1),
        )
        self.grant(VIEW, "WORKSHOP", [self.assembly, self.sewing])
        response = self.client.get(self.base, {"position_state": "ROLE_PENDING"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"], [])

    def test_conflicting_roles_cannot_be_hidden_by_authorized_workshop_or_filter(self):
        self.assign_workshop_role(self.unassigned, "金工车间")
        self.assign_workshop_role(self.unassigned, "缝纫车间")
        self.grant(VIEW, "WORKSHOP", [self.metal])
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        for state in ("ROLE_PENDING", "ROLE_ALL"):
            for workshop in (None, self.metal, self.sewing):
                query = {"position_state": state}
                if workshop:
                    query["workshop"] = str(workshop.pk)
                response = self.client.get(self.base, query)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertNotIn(str(self.unassigned.pk), {row["id"] for row in response.data["data"]})
        self.assertEqual(self.client.get(self.url(self.unassigned)).status_code, 404)
        self.assertEqual(self.update(self.unassigned, {"workshop": str(self.metal.pk), "position": "金工"}).status_code, 404)
        self.grant(VIEW)
        self.assertEqual(self.client.get(self.base, {"position_state": "ROLE_PENDING"}).data["data"], [])
        row = self.client.get(self.url(self.unassigned)).data["data"]
        self.assertIsNone(row["role_workshop"])
        self.assertIsNone(row["role_workshop_name"])
        self.assertFalse(row["can_edit"])

    def test_multiple_roles_mapping_to_same_workshop_remain_unambiguous(self):
        self.assign_workshop_role(self.unassigned, "金工车间")
        self.assign_workshop_role(self.unassigned, "金工车间")
        self.grant(VIEW, "WORKSHOP", [self.metal])
        response = self.client.get(self.base, {"position_state": "ROLE_PENDING"})
        self.assertEqual([row["id"] for row in response.data["data"]], [str(self.unassigned.pk)])
        self.assertEqual(response.data["data"][0]["role_workshop"], str(self.metal.pk))

    def test_expired_future_and_archived_roles_do_not_change_unique_mapping(self):
        self.grant(VIEW, "WORKSHOP", [self.metal])
        now = timezone.now()
        workers = []
        for dates in ({"effective_to": now - timedelta(hours=1)},
                      {"effective_from": now + timedelta(days=1)}, {"archived": True}):
            worker = production_employee(workshop=None, position="", name="有效角色员工")
            workers.append(worker)
            self.assign_workshop_role(worker, "金工车间")
            self.assign_workshop_role(worker, "缝纫车间", **dates)
        response = self.client.get(self.base, {"position_state": "ROLE_PENDING"})
        self.assertEqual({row["id"] for row in response.data["data"]}, {str(worker.pk) for worker in workers})
        self.assertTrue(all(row["role_workshop"] == str(self.metal.pk) for row in response.data["data"]))

    def test_role_pending_includes_assigned_same_workshop_but_role_all_keeps_actual_scope(self):
        self.assign_workshop_role(self.unset_position_worker, "金工车间")
        self.grant(VIEW, "WORKSHOP", [self.metal])
        pending = self.client.get(self.base, {"position_state": "ROLE_PENDING"})
        self.assertEqual([row["id"] for row in pending.data["data"]], [str(self.unset_position_worker.pk)])
        self.assign_workshop_role(self.unset_position_worker, "缝纫车间")
        self.assertEqual(self.client.get(self.base, {"position_state": "ROLE_PENDING"}).data["data"], [])
        rows = self.client.get(self.base, {"position_state": "ROLE_ALL"}).data["data"]
        self.assertIn(str(self.unset_position_worker.pk), {row["id"] for row in rows})
        self.assertEqual(self.client.get(self.url(self.unset_position_worker)).status_code, 200)

    def test_role_pending_editability_uses_change_scope_not_view_scope(self):
        self.assign_workshop_role(self.unassigned, "金工车间")
        self.grant(VIEW, "WORKSHOP", [self.metal])
        self.grant(CHANGE, "WORKSHOP", [self.sewing])
        row = self.client.get(self.base, {"position_state": "ROLE_PENDING"}).data["data"][0]
        self.assertFalse(row["can_edit"])
        self.assertEqual(self.update(self.unassigned, {"workshop": str(self.metal.pk), "position": "金工"}).status_code, 404)

    def test_unknown_role_has_no_mapping_but_module_can_configure_manually(self):
        self.assign_workshop_role(self.unassigned, "未知车间")
        self.grant(VIEW)
        self.grant(CHANGE)
        self.assertEqual(self.client.get(self.base, {"position_state": "ROLE_PENDING"}).data["data"], [])
        rows = self.client.get(self.base, {"position_state": "ROLE_ALL"}).data["data"]
        row = next(row for row in rows if row["id"] == str(self.unassigned.pk))
        self.assertIsNone(row["role_workshop"])
        self.assertIsNone(row["role_workshop_name"])
        self.assertTrue(row["can_edit"])
        self.assertEqual(self.update(self.unassigned, {"workshop": str(self.metal.pk), "position": "金工"}).status_code, 200)

    def test_role_inference_rechecked_before_saving_unassigned_employee(self):
        self.grant(CHANGE, "WORKSHOP", [self.metal, self.sewing])
        assignment = self.assign_workshop_role(self.unassigned, "金工车间")
        request = self.scoped_request()
        request.headers = {"If-Match": etag_for_instance(self.unassigned)}
        access_for(request)
        payload = {"workshop": self.metal, "workshop_position": "金工"}
        assignment.effective_to = timezone.now()
        assignment.save(update_fields=["effective_to"])
        with self.assertRaises(PermissionDenied):
            update_employee_workshop(instance_id=self.unassigned.pk, validated_data=payload,
                                     actor_employee=self.scope_employee, request=request)
        assignment.effective_to = None
        assignment.save(update_fields=["effective_to"])
        role = assignment.role_profile
        role.archived_at = timezone.now()
        role.save(update_fields=["archived_at"])
        with self.assertRaises(PermissionDenied):
            update_employee_workshop(instance_id=self.unassigned.pk, validated_data=payload,
                                     actor_employee=self.scope_employee, request=request)
        role.archived_at = None
        role.save(update_fields=["archived_at"])
        self.assign_workshop_role(self.unassigned, "缝纫车间")
        with self.assertRaises(PermissionDenied):
            update_employee_workshop(instance_id=self.unassigned.pk, validated_data=payload,
                                     actor_employee=self.scope_employee, request=request)
        self.unassigned.refresh_from_db()
        self.assertIsNone(self.unassigned.workshop_id)

    def test_role_mapped_employee_cannot_be_assigned_to_another_authorized_workshop(self):
        self.assign_workshop_role(self.unassigned, "金工车间")
        self.grant(CHANGE, "WORKSHOP", [self.metal, self.sewing])
        response = self.update(self.unassigned, {"workshop": str(self.sewing.pk), "position": "车缝"})
        self.assertEqual(response.status_code, 400, response.data)
        self.unassigned.refresh_from_db()
        self.assertIsNone(self.unassigned.workshop_id)

    def test_role_workshop_serialization_queries_workshop_table_once_per_list(self):
        second = production_employee(workshop=None, position="", name="第二位待安排员工")
        for employee in (self.unassigned, second):
            self.assign_workshop_role(employee, "金工车间")
        self.grant(VIEW, "WORKSHOP", [self.metal])
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        request = self.scoped_request()
        access_for(request)
        employees = list(employees_with_context(Employee.objects.filter(pk__in=[self.unassigned.pk, second.pk])))
        with CaptureQueriesContext(connection) as queries:
            rows = WorkshopEmployeeSerializer(employees, many=True, context={"request": request}).data
        self.assertEqual(len(queries), 1)
        self.assertEqual({row["role_workshop"] for row in rows}, {str(self.metal.pk)})
        self.assertTrue(all(row["can_edit"] for row in rows))

    def test_options_separate_read_and_edit_scopes_without_statistics(self):
        self.grant(VIEW, "WORKSHOP", [self.metal, self.sewing])
        self.grant(CHANGE, "WORKSHOP", [self.sewing])
        response = self.client.get(self.base + "options/")
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual({row["id"] for row in data["workshops"]}, {str(self.metal.pk), str(self.sewing.pk)})
        self.assertEqual(data["editable_workshops"], [{"id": str(self.sewing.pk), "name": "车缝车间", "status": "ACTIVE"}])
        self.assertTrue(all(set(row) == {"id", "name", "status"} for row in data["workshops"]))

    def test_options_require_view_permission_and_read_only_has_no_edit_options(self):
        self.assertEqual(self.client.get(self.base + "options/").status_code, 403)
        self.grant(VIEW, "WORKSHOP", [self.metal])
        response = self.client.get(self.base + "options/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["editable_workshops"], [])
        self.assertEqual(self.update(self.metal_worker, {"position": "新岗位"}).status_code, 403)

    def test_can_edit_uses_change_scope_and_does_not_inherit_full_view(self):
        self.grant(VIEW)
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        rows = self.client.get(self.base).data["data"]
        self.assertEqual({row["id"]: row["can_edit"] for row in rows}, {
            str(self.metal_worker.pk): True, str(self.unset_position_worker.pk): True,
            str(self.sewing_worker.pk): False, str(self.unassigned.pk): False,
        })
        for employee in (self.sewing_worker, self.unassigned):
            self.assertEqual(self.update(employee, {"position": "不能修改"}).status_code, 404)
            self.assertEqual(self.client.delete(self.url(employee), HTTP_IF_MATCH=etag_for_instance(employee)).status_code, 404)

    def test_change_scope_does_not_inherit_narrower_view_scope(self):
        self.grant(VIEW, "WORKSHOP", [self.metal])
        self.grant(CHANGE, "WORKSHOP", [self.sewing])
        response = self.update(self.sewing_worker, {"position": "车缝组长"})
        self.assertEqual(response.status_code, 200, response.data)
        self.sewing_worker.refresh_from_db()
        self.assertEqual(self.sewing_worker.workshop_position, "车缝组长")
        self.assertEqual(self.client.get(self.url(self.sewing_worker)).status_code, 404)

    def test_scoped_update_rejects_out_of_scope_destination(self):
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        response = self.update(self.metal_worker, {"workshop": str(self.sewing.pk), "position": "车缝"})
        self.assertEqual(response.status_code, 403, response.data)
        self.metal_worker.refresh_from_db()
        self.assertEqual(self.metal_worker.workshop_id, self.metal.pk)

    def test_same_action_roles_union_allows_transfer_between_authorized_workshops(self):
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        self.grant(CHANGE, "WORKSHOP", [self.sewing])
        response = self.update(self.metal_worker, {"workshop": str(self.sewing.pk), "position": "车缝"})
        self.assertEqual(response.status_code, 200, response.data)
        self.metal_worker.refresh_from_db()
        self.assertEqual(self.metal_worker.workshop_id, self.sewing.pk)

    def test_end_restore_and_clear_keep_master_and_department_assignment(self):
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        for status in ("LEFT", "ACTIVE"):
            response = self.update(self.metal_worker, {"status": status})
            self.assertEqual(response.status_code, 200, response.data)
            self.metal_worker.refresh_from_db()
            self.assertEqual(self.metal_worker.workshop_status, status)
        assignment_ids = set(self.metal_worker.organization_assignments.values_list("pk", flat=True))
        count = Employee.objects.count()
        response = self.client.delete(self.url(self.metal_worker), HTTP_IF_MATCH=etag_for_instance(self.metal_worker))
        self.assertEqual(response.status_code, 204, response.data)
        self.metal_worker.refresh_from_db()
        self.assertEqual((self.metal_worker.workshop_id, self.metal_worker.workshop_position,
                          self.metal_worker.workshop_is_supervisor), (None, "", False))
        self.assertEqual(Employee.objects.count(), count)
        self.assertEqual(set(self.metal_worker.organization_assignments.values_list("pk", flat=True)), assignment_ids)
        self.assertEqual(self.update(self.metal_worker, {"workshop": str(self.metal.pk), "position": "金工"}).status_code, 404)

    def test_module_can_read_and_assign_unarranged_employee(self):
        self.grant(VIEW)
        self.grant(CHANGE)
        self.assertEqual(len(self.client.get(self.base).data["data"]), 4)
        response = self.update(self.unassigned, {"workshop": str(self.metal.pk), "position": "金工"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["data"]["can_edit"])

    def test_empty_resource_grants_allow_no_employee_or_option(self):
        self.grant(VIEW, "WORKSHOP")
        self.grant(CHANGE, "WORKSHOP")
        self.assertEqual(self.client.get(self.base).data["data"], [])
        response = self.client.get(self.base + "options/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"], {"workshops": [], "editable_workshops": []})
        self.assertEqual(self.update(self.metal_worker, {"position": "新岗位"}).status_code, 404)

    def test_disabled_resource_flag_does_not_promote_scoped_grant(self):
        self.grant(VIEW, "WORKSHOP", [self.metal])
        with override_settings(ACCESS_RESOURCE_SCOPES_ENABLED=False):
            response = self.client.get(self.base)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["data"], [])

    @override_settings(SALES_ACCESS_ENABLED=False)
    def test_module_scope_still_limits_reads_and_writes_with_sales_policy_disabled(self):
        self.grant(VIEW, "WORKSHOP", [self.metal])
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({row["id"] for row in response.data["data"]}, {str(self.metal_worker.pk), str(self.unset_position_worker.pk)})
        self.assertTrue(response.data["data"][0]["can_edit"])
        self.assertEqual(self.update(self.sewing_worker, {"position": "无权修改"}).status_code, 404)
        self.assertEqual(self.update(self.metal_worker, {"position": "组长"}).status_code, 200)

    def test_independent_direct_view_permission_retains_full_read_but_not_edit(self):
        view_grant = self.grant(VIEW, "WORKSHOP", [self.metal])
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        # 角色组中的投影权限本身不能被当作额外的全模块授权。
        self.assertEqual(len(self.client.get(self.base).data["data"]), 2)
        self.scope_user.user_permissions.add(view_grant.permission)
        self.client.force_authenticate(get_user_model().objects.get(pk=self.scope_user.pk))
        rows = self.client.get(self.base).data["data"]
        self.assertEqual({row["id"] for row in rows}, {
            str(self.metal_worker.pk), str(self.unset_position_worker.pk), str(self.sewing_worker.pk), str(self.unassigned.pk),
        })
        self.assertEqual(self.update(self.sewing_worker, {"position": "不能修改"}).status_code, 404)

    def test_independent_legacy_group_change_can_assign_unarranged_employee(self):
        self.grant(VIEW, "WORKSHOP", [self.metal])
        change_grant = self.grant(CHANGE, "WORKSHOP", [self.metal])
        legacy_group = Group.objects.create(name="员工配置历史独立授权")
        legacy_group.permissions.add(change_grant.permission)
        self.scope_user.groups.add(legacy_group)
        self.client.force_authenticate(get_user_model().objects.get(pk=self.scope_user.pk))
        self.assertEqual(len(self.client.get(self.base).data["data"]), 2)
        response = self.update(self.unassigned, {"workshop": str(self.sewing.pk), "position": "车缝"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["data"]["can_edit"])

    def test_missing_and_stale_etag_do_not_update(self):
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        response = self.client.patch(self.url(self.metal_worker), {"position": "新岗位"}, format="json")
        self.assertEqual(response.status_code, 428, response.data)
        self.assertEqual(self.update(self.metal_worker, {"position": "新岗位"}).status_code, 200)
        self.assertEqual(self.update(self.metal_worker, {"position": "覆盖"}).status_code, 412)

    def test_invalid_workshop_fields_return_validation_without_updating_employee(self):
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        for payload in ({"position": "岗" * 101}, {"workshop": None}, {"status": "UNKNOWN"}):
            with self.subTest(payload=payload):
                response = self.update(self.metal_worker, payload)
                self.assertEqual(response.status_code, 400, response.data)
                self.metal_worker.refresh_from_db()
                self.assertEqual(self.metal_worker.workshop_position, "金工")
                self.assertEqual(self.metal_worker.workshop_id, self.metal.pk)

    def service_request(self):
        request = self.scoped_request()
        request.headers = {"If-Match": etag_for_instance(self.metal_worker)}
        access_for(request)
        return request

    def call_service(self, request, data=None):
        return update_employee_workshop(instance_id=self.metal_worker.pk,
            validated_data=data or {"workshop_position": "不能覆盖"}, actor_employee=self.scope_employee, request=request)

    def test_service_rechecks_source_after_employee_moves_without_timestamp_change(self):
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        request = self.service_request()
        Employee.objects.filter(pk=self.metal_worker.pk).update(workshop=self.sewing)
        with self.assertRaises(PermissionDenied):
            self.call_service(request)
        self.metal_worker.refresh_from_db()
        self.assertEqual(self.metal_worker.workshop_position, "金工")

    def test_service_rechecks_permission_snapshot_after_resource_revoked(self):
        grant = self.grant(CHANGE, "WORKSHOP", [self.metal])
        request = self.service_request()
        RoleGrantResource.objects.filter(grant=grant).delete()
        with self.assertRaises(PermissionDenied):
            self.call_service(request)

    def test_service_rechecks_actor_active_status(self):
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        request = self.service_request()
        Employee.objects.filter(pk=self.scope_employee.pk).update(status="LEFT")
        with self.assertRaises(PermissionDenied):
            self.call_service(request)

    def test_service_rechecks_account_active_status(self):
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        request = self.service_request()
        get_user_model().objects.filter(pk=self.scope_user.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.call_service(request)

    def test_service_rechecks_department_membership(self):
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        request = self.service_request()
        self.metal_worker.organization_assignments.update(effective_to=timezone.now())
        with self.assertRaises(Conflict):
            self.call_service(request)

    def test_service_rechecks_destination_permission_after_resource_revoked(self):
        self.grant(CHANGE, "WORKSHOP", [self.metal])
        destination_grant = self.grant(CHANGE, "WORKSHOP", [self.sewing])
        request = self.service_request()
        RoleGrantResource.objects.filter(grant=destination_grant).delete()
        with self.assertRaises(PermissionDenied):
            self.call_service(request, {"workshop": self.sewing, "workshop_position": "车缝"})

    def test_director_templates_grant_employee_scopes_without_expanding_factory_manager(self):
        from apps.access_control.catalog import validate_grants
        from apps.access_control.production_role_templates import templates
        from apps.access_control.resource_scopes import validate_resources
        ids = dict(Workshop.objects.values_list("name", "pk"))
        rows = templates(ids)
        for role, workshop in (("METAL_DIRECTOR", "金工车间"), ("SEWING_DIRECTOR", "车缝车间"), ("ASSEMBLY_DIRECTOR", "装配车间")):
            employee_grants = [row for row in rows[role] if row["permission"] in {VIEW, CHANGE}]
            self.assertEqual(employee_grants, [
                {"permission": CHANGE, "scope": "WORKSHOP", "resource_ids": [str(ids[workshop])]},
                {"permission": VIEW, "scope": "WORKSHOP", "resource_ids": [str(ids[workshop])]},
            ])
            validate_grants(employee_grants)
            validate_resources(employee_grants)
        self.assertFalse(any(row["permission"] in {VIEW, CHANGE} for row in rows["FACTORY_MANAGER"]))
