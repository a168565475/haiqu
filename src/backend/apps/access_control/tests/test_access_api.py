from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.access_control.catalog import PERMISSION_CODES, catalog
from apps.access_control.models import RoleActionGrant
from apps.access_control.selectors import effective_access, scopes_for_user

User = get_user_model()
ROOT = "/api/v1/access/"
VIEW = "sales_orders.view_salesorder"
EDIT = "sales_orders.change_salesorder"


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False)
class AccessApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "admin@example.test", "StrongTestPassword123!")
        self.admin_employee = Employee.objects.create(user=self.admin, employee_code="ACCESS_ADMIN", display_name="权限管理员")
        self.user = User.objects.create_user("access_sales", password="StrongTestPassword123!")
        self.employee = Employee.objects.create(user=self.user, employee_code="ACCESS_SALES", display_name="业务员")
        self.client.force_login(self.admin)

    def create_role(self, code="TEST_ROLE", name=None):
        response = self.client.post(ROOT + "roles/", {"role_code": code, "display_name": name or code}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def grants(self, role, *items, etag=None):
        return self.client.put(ROOT + f"roles/{role.data['id']}/grants/", {
            "grants": [{"permission": p, "scope": s} for p, s in items],
        }, format="json", HTTP_IF_MATCH=etag or role["ETag"])

    def assign(self, *role_ids):
        self.employee.refresh_from_db()
        return self.client.put(ROOT + f"employees/{self.employee.pk}/roles/", {"role_ids": role_ids},
                               format="json", HTTP_IF_MATCH=etag_for_instance(self.employee))

    def test_empty_role_does_not_grant_any_permission(self):
        role = self.create_role()
        self.assertEqual(role.data["grants"], [])
        self.assertEqual(self.assign(role.data["id"]).status_code, 200)
        self.assertEqual(effective_access(self.user)["actions"], {})
        self.assertFalse(User.objects.get(pk=self.user.pk).has_perm(VIEW))

    def test_multiple_roles_union_only_same_operation(self):
        manager = self.grants(self.create_role("MANAGER"), (VIEW, "TEAM"))
        sales = self.grants(self.create_role("SALES"), (VIEW, "OWN"), (EDIT, "OWN"))
        self.assertEqual(self.assign(manager.data["id"], sales.data["id"]).status_code, 200)
        self.assertEqual(scopes_for_user(self.user, VIEW), {"TEAM", "OWN"})
        self.assertEqual(scopes_for_user(self.user, EDIT), {"OWN"})
        self.assertTrue(User.objects.get(pk=self.user.pk).has_perm(EDIT))

    def test_copy_only_grants_without_members_or_accounts(self):
        role = self.grants(self.create_role(), (VIEW, "TEAM"))
        self.assign(role.data["id"])
        accounts, assignments = User.objects.count(), EmployeeRoleAssignment.objects.count()
        response = self.client.post(ROOT + f"roles/{role.data['id']}/copy/", {
            "role_code": "COPY", "display_name": "复制角色",
        }, format="json", HTTP_IF_MATCH=role["ETag"])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["grants"], role.data["grants"])
        self.assertEqual(User.objects.count(), accounts)
        self.assertEqual(EmployeeRoleAssignment.objects.count(), assignments)
        copied = RoleProfile.objects.get(pk=response.data["id"])
        self.assertFalse(copied.employee_assignments.exists())
        self.assertFalse(copied.auth_group.user_set.exists())

    def test_missing_stale_and_valid_if_match(self):
        role = self.create_role()
        url = ROOT + f"roles/{role.data['id']}/grants/"
        self.assertEqual(self.client.put(url, {"grants": []}, format="json").status_code, 428)
        changed = self.grants(role, (VIEW, "TEAM"))
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.grants(role, (EDIT, "ALL")).status_code, 412)
        self.assertEqual(self.client.get(url).data["grants"], changed.data["grants"])

    def test_archive_then_restore_and_revoke_on_subsequent_requests(self):
        role = self.grants(self.create_role(), (VIEW, "TEAM"))
        self.assign(role.data["id"])
        employee_client = APIClient(); employee_client.force_login(self.user)
        first = employee_client.get("/api/auth/me/").data["user"]
        self.assertIn(VIEW, first["permissions"])
        archived = self.client.patch(ROOT + f"roles/{role.data['id']}/", {"archived": True},
                                     format="json", HTTP_IF_MATCH=role["ETag"])
        self.assertEqual(archived.status_code, 200)
        after = employee_client.get("/api/auth/me/").data["user"]
        self.assertNotIn(VIEW, after["permissions"])
        self.assertEqual(after["effective_access"]["actions"], {})
        self.assertNotEqual(first["effective_access"]["version"], after["effective_access"]["version"])
        restored = self.client.patch(ROOT + f"roles/{role.data['id']}/", {"archived": False},
                                     format="json", HTTP_IF_MATCH=archived["ETag"])
        self.assertEqual(restored.status_code, 200)
        self.assertIn(VIEW, employee_client.get("/api/auth/me/").data["user"]["permissions"])
        self.assertEqual(self.assign().status_code, 200)
        self.assertNotIn(VIEW, employee_client.get("/api/auth/me/").data["user"]["permissions"])

    def test_expired_future_and_inactive_employee_grant_no_scopes(self):
        role = self.grants(self.create_role(), (VIEW, "TEAM"))
        now = timezone.now()
        assignment = EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile_id=role.data["id"],
            effective_from=now-timedelta(days=2), effective_to=now-timedelta(days=1))
        self.assertFalse(scopes_for_user(self.user, VIEW))
        assignment.effective_from=now+timedelta(days=1); assignment.effective_to=None; assignment.save()
        self.assertFalse(scopes_for_user(self.user, VIEW))
        self.assertEqual(self.assign().status_code, 409)
        assignment.effective_from=now-timedelta(minutes=1); assignment.save()
        self.employee.status="INACTIVE"; self.employee.save()
        self.assertFalse(effective_access(self.user)["active"])
        self.assertFalse(scopes_for_user(self.user, VIEW))

    def test_all_management_routes_deny_non_admin_even_with_native_permissions(self):
        self.user.user_permissions.set(Permission.objects.all())
        self.client.force_login(self.user)
        for url in ["catalog/", "roles/", "employees/", "audit-events/", f"employees/{self.employee.pk}/effective-access/"]:
            self.assertEqual(self.client.get(ROOT+url).status_code, 403, url)
        self.assertEqual(self.client.post(ROOT+"roles/", {"role_code":"ESCALATE","display_name":"提权"},format="json").status_code,403)
        self.assertFalse(RoleProfile.objects.filter(role_code="ESCALATE").exists())

    def test_other_superuser_and_admin_name_without_superuser_are_denied(self):
        other = User.objects.create_superuser("haiqu", "old@example.test", "StrongTestPassword123!")
        Employee.objects.create(user=other, employee_code="ACCESS_OLD", display_name="旧账号")
        self.client.force_login(other)
        self.assertEqual(self.client.get(ROOT+"roles/").status_code,403)
        self.admin.is_superuser=False; self.admin.save(); self.client.force_login(self.admin)
        self.assertEqual(self.client.get(ROOT+"roles/").status_code,403)

    def test_admin_employee_required(self):
        self.admin_employee.status="INACTIVE"; self.admin_employee.save()
        self.assertEqual(self.client.get(ROOT+"roles/").status_code,403)

    def test_csrf_is_enforced_with_real_session(self):
        client=APIClient(enforce_csrf_checks=True); client.force_login(self.admin)
        payload={"role_code":"CSRF", "display_name":"CSRF角色"}
        self.assertEqual(client.post(ROOT+"roles/",payload,format="json").status_code,403)
        client.get("/api/auth/me/"); token=client.cookies["csrftoken"].value
        self.assertEqual(client.post(ROOT+"roles/",payload,format="json",HTTP_X_CSRFTOKEN=token).status_code,201)

    def test_illegal_permissions_scopes_duplicates_and_unknown_fields_rejected(self):
        role=self.create_role()
        for items in [[("auth.change_user","MODULE")],[(VIEW,"MODULE")],[("boms.view_bom","TEAM")],[(VIEW,"OWN"),(VIEW,"OWN")]]:
            self.assertEqual(self.grants(role,*items).status_code,400,items)
        self.assertEqual(self.client.patch(ROOT+f"roles/{role.data['id']}/",{"is_superuser":True},format="json",HTTP_IF_MATCH=role["ETag"]).status_code,400)
        self.assertFalse(RoleActionGrant.objects.exists())

    def test_legacy_direct_and_native_group_grants_are_preserved_and_explained(self):
        p=Permission.objects.get(content_type__app_label="customers",codename="view_customeraccount")
        self.user.user_permissions.add(p)
        group=Group.objects.create(name="历史分组"); group.permissions.add(p); self.user.groups.add(group)
        role=self.create_role(); self.assign(role.data["id"])
        access=effective_access(self.user)
        self.assertEqual(access["actions"],{})
        self.assertEqual({x["type"] for x in access["legacy_sources"]},{"DIRECT","GROUP"})
        self.assertTrue(User.objects.get(pk=self.user.pk).has_perm("customers.view_customeraccount"))
        self.assign(); self.assertTrue(self.user.user_permissions.filter(pk=p.pk).exists())
        self.assertTrue(self.user.groups.filter(pk=group.pk).exists())

    def test_legacy_role_projection_conflict_never_erases_existing_permissions(self):
        role=self.create_role(); instance=RoleProfile.objects.get(pk=role.data["id"])
        p=Permission.objects.get(content_type__app_label="customers",codename="view_customeraccount")
        instance.auth_group.permissions.add(p)
        self.assertEqual(self.grants(role,(VIEW,"OWN")).status_code,409)
        self.assertTrue(instance.auth_group.permissions.filter(pk=p.pk).exists())
        instance.auth_group.permissions.clear(); self.user.groups.add(instance.auth_group)
        self.assertEqual(self.grants(role,(VIEW,"OWN")).status_code,409)

    def test_grant_audit_failure_rolls_back_grants_projection_and_etag(self):
        role=self.create_role()
        with patch("apps.access_control.services.write_audit_log",side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError): self.grants(role,(VIEW,"TEAM"))
        instance=RoleProfile.objects.get(pk=role.data["id"])
        self.assertFalse(instance.action_grants.exists()); self.assertFalse(instance.auth_group.permissions.exists())
        self.assertEqual(etag_for_instance(instance),role["ETag"])

    def test_import_export_projection_follows_create_view(self):
        role=self.grants(self.create_role(),("quotations.view_quotation","OWN"),("customers.add_customercontact","OWN"))
        self.assign(role.data["id"])
        fresh=User.objects.get(pk=self.user.pk)
        self.assertTrue(fresh.has_perm("quotations.export_quotation")); self.assertTrue(fresh.has_perm("customers.import_customercontact"))
        self.assertFalse(fresh.has_perm("customers.change_customercontact"))
        self.assertEqual(self.grants(role).status_code,200)
        self.assertFalse(User.objects.get(pk=self.user.pk).has_perm("quotations.export_quotation"))

    def test_duplicate_and_invalid_scope_database_constraints(self):
        role=self.grants(self.create_role(),(VIEW,"OWN")); grant=RoleActionGrant.objects.get(role_id=role.data["id"])
        for scope in ["OWN","UNKNOWN"]:
            with self.assertRaises(IntegrityError),transaction.atomic():
                RoleActionGrant.objects.create(role=grant.role,permission=grant.permission,scope=scope)

    def test_catalog_is_explicit_complete_and_read_only(self):
        response=self.client.get(ROOT+"catalog/")
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(len(response.data),len(PERMISSION_CODES))
        self.assertTrue(all(x["available"] for x in response.data),[x for x in response.data if not x["available"]])
        self.assertFalse(any(x["code"].startswith("auth.") for x in response.data))
        self.assertEqual(self.client.post(ROOT+"catalog/",{},format="json").status_code,405)

    def test_reference_edit_does_not_grant_archive_or_status_actions(self):
        role=self.grants(self.create_role(),("reference_data.change_country","MODULE"))
        self.assign(role.data["id"])
        self.assertEqual(scopes_for_user(self.user,"reference_data.change_country"),{"MODULE"})
        for action in ("archive","activate","deactivate"):
            code=f"access_control.{action}_reference_country"
            self.assertIn(code,PERMISSION_CODES)
            self.assertFalse(scopes_for_user(self.user,code))
            self.assertFalse(User.objects.get(pk=self.user.pk).has_perm(code))

    def test_audit_has_actor_and_exact_change_but_no_credentials(self):
        role=self.grants(self.create_role(),(VIEW,"TEAM"))
        audit=AuditLog.objects.get(action="ROLE_GRANTS_REPLACE",object_id=role.data["id"])
        self.assertEqual(audit.actor_employee,self.admin_employee)
        self.assertEqual(audit.before_data["grants"],[])
        self.assertEqual(audit.after_data["grants"],[{"permission":VIEW,"scope":"TEAM"}])
        self.assertNotIn("password",str(self.client.get(ROOT+"audit-events/").data).lower())
        self.assertEqual(self.client.delete(ROOT+f"audit-events/{audit.pk}/").status_code,405)

    def test_initial_roles_dry_run_idempotent_and_preserves_existing_grants(self):
        call_command("initialize_access_roles",stdout=StringIO())
        self.assertFalse(RoleProfile.objects.exists())
        call_command("initialize_access_roles",apply=True,stdout=StringIO())
        self.assertEqual(RoleProfile.objects.count(),20)
        self.assertFalse(RoleActionGrant.objects.exists()); self.assertFalse(EmployeeRoleAssignment.objects.exists())
        self.assertFalse(RoleProfile.objects.filter(display_name="查看全部权限").exists())
        manager=RoleProfile.objects.get(role_code="ACCOUNT_MANAGER")
        response=self.client.get(ROOT+f"roles/{manager.pk}/")
        self.assertEqual(self.grants(response,(VIEW,"TEAM")).status_code,200)
        audit_count=AuditLog.objects.count()
        call_command("initialize_access_roles",apply=True,stdout=StringIO())
        self.assertEqual(RoleProfile.objects.count(),20); self.assertEqual(AuditLog.objects.count(),audit_count)
        self.assertEqual(manager.action_grants.count(),1)

    def test_unauthenticated_and_rollout_disabled(self):
        self.client.logout()
        self.assertEqual(self.client.get(ROOT+"roles/").status_code,401)
        self.client.force_login(self.admin)
        with override_settings(ACCESS_MANAGEMENT_ENABLED=False):
            self.assertEqual(self.client.get(ROOT+"roles/").status_code,503)
            self.assertNotIn("effective_access",self.client.get("/api/auth/me/").data["user"])

    def test_employee_role_replacement_requires_etag_and_rejects_duplicate_ids(self):
        role=self.create_role(); url=ROOT+f"employees/{self.employee.pk}/roles/"
        self.assertEqual(self.client.put(url,{"role_ids":[]},format="json").status_code,428)
        self.assertEqual(self.assign(role.data["id"],role.data["id"]).status_code,400)
        old=etag_for_instance(self.employee); self.assertEqual(self.assign(role.data["id"]).status_code,200)
        self.assertEqual(self.client.put(url,{"role_ids":[]},format="json",HTTP_IF_MATCH=old).status_code,412)

    def test_superuser_summary_allows_all_catalog_operations(self):
        access=effective_access(self.admin)
        self.assertTrue(access["is_superuser"])
        self.assertEqual(set(access["actions"]),set(PERMISSION_CODES))
        self.assertEqual(access["actions"][VIEW]["scopes"],["ALL"])

    def test_internal_receipt_permissions_are_available_and_assignable(self):
        codes=['inventory.view_internalsemifinishedreceipt','inventory.add_internalsemifinishedreceipt']
        rows={row['code']:row for row in catalog()}
        for code in codes:
            self.assertTrue(rows[code]['available'])
            self.assertEqual(rows[code]['resource_name'],'厂内半成品入库')
        role=self.create_role(code='INTERNAL_RECEIPT_WAREHOUSE')
        granted=self.grants(role,*[(code,'MODULE') for code in codes])
        self.assertEqual(granted.status_code,200,granted.data)

    def test_malformed_uuid_write_routes_return_404_not_500(self):
        cases = [
            ("patch", "roles/not-a-uuid/", {"archived": True}),
            ("put", "roles/not-a-uuid/grants/", {"grants": []}),
            ("post", "roles/not-a-uuid/copy/", {"role_code": "COPY", "display_name": "复制"}),
            ("put", "employees/not-a-uuid/roles/", {"role_ids": []}),
        ]
        for method, url, data in cases:
            response = getattr(self.client, method)(ROOT + url, data, format="json", HTTP_IF_MATCH='"stale"')
            self.assertEqual(response.status_code, 404, (url, response.data))
