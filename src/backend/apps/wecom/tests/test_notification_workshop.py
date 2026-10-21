"""真实工价对象、车间资源授权与通知接收范围的交叉验证，不模拟对象授权。"""
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.organizations.models import EmployeeRoleAssignment
from apps.wecom.notification_access import event_object_accessible
from apps.wecom.notification_selectors import recipient_payload
from apps.wecom.notification_services import register_business_event
from apps.workshop_config.models import Craft, Workshop
from apps.workshop_reporting.models import WageScheme

from .test_notifications import SETTINGS, create_rule, employee, grant_role


@override_settings(**SETTINGS)
class NotificationWorkshopScopeTests(TestCase):
    def test_real_workshop_scope_union_deduplication_and_resource_revocation(self):
        # 复用既有业务夹具的任务、产品行和工艺，避免再造一套不完整的生产数据。
        from apps.workshop_reporting.tests.test_workshop_reporting_api import WorkshopReportingApiTests

        fixture = WorkshopReportingApiTests()
        fixture.setUp()
        sewing = Workshop.objects.get_or_create(name="车缝车间")[0]
        sewing_craft = Craft.objects.create(
            craft_type="INTERNAL", workshop=sewing, name="通知测试车缝", plan_category="SEWING",
        )
        schemes = []
        for number, workshop, craft in [("METAL", fixture.workshop, fixture.craft), ("SEWING", sewing, sewing_craft)]:
            schemes.append(WageScheme.objects.create(
                scheme_number=f"NOTIFY_WAGE_{number}", product_line=fixture.product_line,
                workshop=workshop, scope_craft=craft, status="RETURNED",
                product_name_snapshot=fixture.product_line.product_name_snapshot,
                product_number_snapshot=fixture.product_line.product_number_snapshot,
                operation_product_name_snapshot="通知车间测试产品",
                created_by_employee=fixture.employee, updated_by_employee=fixture.employee,
            ))
        metal_scheme, sewing_scheme = schemes
        metal_member, sewing_member = employee("NOTIFY_METAL_MEMBER"), employee("NOTIFY_SEWING_MEMBER")
        metal_role = grant_role(metal_member, "NOTIFY_METAL_DIRECTOR", "workshop_reporting.view_wagescheme", "WORKSHOP")
        sewing_role = grant_role(sewing_member, "NOTIFY_SEWING_DIRECTOR", "workshop_reporting.view_wagescheme", "WORKSHOP")
        metal_grant, sewing_grant = RoleActionGrant.objects.get(role=metal_role), RoleActionGrant.objects.get(role=sewing_role)
        RoleGrantResource.objects.create(grant=metal_grant, workshop=fixture.workshop)
        RoleGrantResource.objects.create(grant=sewing_grant, workshop=sewing)
        code = "WAGE_SCHEME_DECIDED"
        create_rule(code, fixture.employee, [metal_role.role_code, sewing_role.role_code])

        def register(scheme, key, workshop_id=None):
            return register_business_event(event_code=code, idempotency_key=key, object_type="WAGE_SCHEME",
                object_id=str(scheme.pk), object_version="1", context={
                    "document_no": scheme.scheme_number, "status": "已退回",
                    "workshop_id": str(workshop_id or scheme.workshop_id),
                })

        self.assertTrue(event_object_accessible(code, metal_scheme.pk, metal_member.user))
        self.assertFalse(event_object_accessible(code, sewing_scheme.pk, metal_member.user))
        self.assertFalse(event_object_accessible(code, metal_scheme.pk, sewing_member.user))
        metal_event = register(metal_scheme, "notify-workshop-metal")
        sewing_event = register(sewing_scheme, "notify-workshop-sewing")
        self.assertEqual(list(metal_event.recipients.values_list("employee_id", flat=True)), [metal_member.pk])
        self.assertEqual(list(sewing_event.recipients.values_list("employee_id", flat=True)), [sewing_member.pk])
        # 上下文写成车缝，也不能让车缝人员读取真实金工对象。
        mismatched = register(metal_scheme, "notify-workshop-mismatched", workshop_id=sewing.pk)
        self.assertEqual(mismatched.status, "NO_RECIPIENT")

        EmployeeRoleAssignment.objects.create(
            employee=metal_member, role_profile=sewing_role, effective_from=timezone.now(),
        )
        self.assertTrue(event_object_accessible(code, sewing_scheme.pk, metal_member.user))
        dual_metal = register(metal_scheme, "notify-workshop-dual-metal")
        self.assertEqual(list(dual_metal.recipients.values_list("employee_id", flat=True)), [metal_member.pk])
        self.assertEqual(dual_metal.recipients.get().deliveries.count(), 2)
        dual_sewing = register(sewing_scheme, "notify-workshop-dual-sewing")
        self.assertCountEqual(list(dual_sewing.recipients.values_list("employee_id", flat=True)),
            [metal_member.pk, sewing_member.pk])
        self.assertEqual(dual_sewing.recipients.get(employee=metal_member).deliveries.count(), 2)

        RoleGrantResource.objects.filter(grant=metal_grant).delete()
        self.assertFalse(event_object_accessible(code, metal_scheme.pk, metal_member.user))
        self.assertTrue(event_object_accessible(code, sewing_scheme.pk, metal_member.user))
        self.assertFalse(recipient_payload(metal_event.recipients.get(), metal_member.user)["target_accessible"])
        after_revoke = register(metal_scheme, "notify-workshop-metal-revoked")
        self.assertEqual(after_revoke.status, "NO_RECIPIENT")
        self.assertFalse(after_revoke.recipients.exists())
