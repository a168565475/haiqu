from types import SimpleNamespace
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.access_control import module_policy
from apps.access_control.models import RoleActionGrant, SalesTeam, SalesTeamMembership
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, SALES_ACCESS_ENABLED=True, MODULE_ACCESS_ENABLED=True)
class ModulePolicyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('module_manager')
        self.actor = Employee.objects.create(user=self.user, employee_code='MOD_MANAGER', display_name='经理')
        self.member = Employee.objects.create(employee_code='MOD_MEMBER', display_name='团队员工')
        self.outside = Employee.objects.create(employee_code='MOD_OTHER', display_name='其他员工')
        team = SalesTeam.objects.create(code='MOD_TEAM', name='手工团队', manager=self.actor)
        SalesTeamMembership.objects.create(team=team, employee=self.member, created_by_employee=self.actor)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.sequence = 0

    def request(self):
        return SimpleNamespace(user=get_user_model().objects.get(pk=self.user.pk), employee=self.actor, META={}, headers={})

    def grant(self, code, scope='MODULE'):
        self.sequence += 1
        app, codename = code.split('.')
        permission = Permission.objects.get(content_type__app_label=app, codename=codename)
        group = Group.objects.create(name=f'MOD_ROLE_{self.sequence}')
        group.permissions.add(permission)
        role = RoleProfile.objects.create(auth_group=group, role_code=f'MOD_ROLE_{self.sequence}', display_name='测试角色')
        EmployeeRoleAssignment.objects.create(employee=self.actor, role_profile=role, effective_from=timezone.now())
        RoleActionGrant.objects.create(role=role, permission=permission, scope=scope)
        return role

    def test_empty_role_cannot_read_other_modules(self):
        for route in ['purchase-requests', 'purchase-orders', 'purchase-contract-templates',
                'supplier-purchase-sheets', 'suppliers', 'production-tasks', 'boms', 'material-issues',
                'production-schedules', 'sample-requests', 'tasks']:
            with self.subTest(route=route):
                response = self.client.get(f'/api/v1/{route}/')
                self.assertEqual(response.status_code, 403, (route, response.data))

    def test_purchase_template_view_cannot_write(self):
        self.grant('procurement.view_purchasecontracttemplate')
        response = self.client.post('/api/v1/purchase-contract-templates/', {}, format='json')
        self.assertEqual(response.status_code, 403, response.data)

    def test_purchase_create_does_not_allow_edit(self):
        self.grant('procurement.add_purchaseorder')
        response = self.client.patch(f'/api/v1/purchase-orders/{uuid4()}/', {}, format='json')
        self.assertEqual(response.status_code, 403, response.data)

    def test_purchase_request_view_cannot_submit(self):
        self.grant('procurement.view_purchaserequest')
        response = self.client.post(f'/api/v1/purchase-requests/{uuid4()}/submit/', {}, format='json')
        self.assertEqual(response.status_code, 403, response.data)

    def test_legacy_purchase_grant_retains_explicit_compatibility(self):
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='procurement', codename='add_purchaseorder'))
        self.assertTrue(module_policy.has_permission(self.request(), 'procurement.change_purchaseorder'))
        self.assertFalse(module_policy.has_permission(self.request(), 'access_control.complete_purchaseorder'))

    def test_module_grant_rechecks_role_revocation(self):
        role = self.grant('production_tasks.view_productiontask')
        self.assertTrue(module_policy.has_module_grant(self.request(), 'production_tasks'))
        role.archived_at = timezone.now()
        role.save()
        self.assertFalse(module_policy.has_module_grant(self.request(), 'production_tasks'))

    def task(self, employee, number):
        from apps.workflow.models import BusinessTask
        return BusinessTask.objects.create(task_number=f'MOD_TASK_{number}', assignee_employee=employee,
            created_by_employee=employee, task_type='OTHER', title='权限测试任务')

    def test_manual_team_read_does_not_expand_task_edit(self):
        from apps.workflow.selectors import accessible_tasks
        self.grant('workflow.view_businesstask', 'TEAM')
        self.grant('workflow.change_businesstask', 'OWN')
        own, team = self.task(self.actor, 'OWN'), self.task(self.member, 'TEAM')
        self.task(self.outside, 'OTHER')
        self.assertEqual(set(accessible_tasks(self.request(), 'ANY_ACCESS').values_list('pk', flat=True)), {team.pk})
        self.assertEqual(set(accessible_tasks(self.request(), 'ANY_ACCESS', permission='workflow.change_businesstask').values_list('pk', flat=True)), {own.pk})
        response = self.client.patch(f'/api/v1/tasks/{team.pk}/', {'title': '不得修改'}, format='json')
        self.assertEqual(response.status_code, 404, response.data)

    def test_edit_does_not_grant_task_completion(self):
        self.grant('workflow.change_businesstask', 'ALL')
        task = self.task(self.actor, 'COMPLETE')
        response = self.client.post(f'/api/v1/tasks/{task.pk}/complete/', {'note': '完成'}, format='json')
        self.assertEqual(response.status_code, 403, response.data)

    def sample(self, owner, number):
        from apps.customers.models import CustomerAccount, CustomerAssignment
        from apps.samples.models import SampleRequest
        customer = CustomerAccount.objects.create(account_code=f'MOD_CUSTOMER_{number}', account_name='权限客户')
        CustomerAssignment.objects.create(customer_account=customer, employee=owner, assignment_role='PRIMARY_OWNER',
            effective_from=timezone.now(), assigned_by_employee=self.actor)
        return SampleRequest.objects.create(customer_account=customer, owner_employee=owner,
            requested_by_employee=owner, request_number=f'MOD_SAMPLE_{number}', requested_at=timezone.now())

    def test_sample_team_scope_uses_customer_ownership(self):
        from apps.samples.selectors import accessible_sample_requests
        self.grant('samples.view_samplerequest', 'TEAM')
        team = self.sample(self.member, 'TEAM')
        self.sample(self.outside, 'OTHER')
        self.assertEqual(list(accessible_sample_requests(self.request(), 'view_samplerequest').values_list('pk', flat=True)), [team.pk])

    def test_sample_production_module_does_not_require_sales_grant(self):
        from apps.samples.selectors import accessible_sample_requests
        self.grant('samples.view_samplerequest')
        sample = self.sample(self.outside, 'PRODUCTION')
        self.assertTrue(accessible_sample_requests(self.request(), 'view_samplerequest').filter(pk=sample.pk).exists())
        response = self.client.get(f'/api/v1/customers/{sample.customer_account_id}/')
        self.assertEqual(response.status_code, 403, response.data)

    def test_superuser_cannot_self_approve(self):
        self.user.is_superuser = True
        self.user.save()
        with self.assertRaises(PermissionDenied):
            module_policy.prohibit_self_approval(self.actor, self.actor.pk)
        module_policy.prohibit_self_approval(self.actor, self.member.pk)

    def test_unknown_submitter_is_not_inferred(self):
        with self.assertRaises(PermissionDenied):
            module_policy.prohibit_audit_self_approval(self.actor, 'SAMPLE_REQUEST', uuid4(), ['APPLICATION_SUBMITTED'])

    def test_generic_approval_does_not_consume_sample_fee_request(self):
        from apps.workflow.models import ApprovalRequest
        from apps.workflow.services import decide_approval
        approval = ApprovalRequest.objects.create(approval_type='SAMPLE_FEE_WAIVER', current_approver_employee=self.actor,
            requested_by_employee=self.member, submitted_at=timezone.now())
        with self.assertRaisesMessage(PermissionDenied, '样品费用'):
            decide_approval(approval=approval, target_status='APPROVED', note='', actor_employee=self.actor, request=self.request())
        approval.refresh_from_db()
        self.assertEqual(approval.status, 'PENDING')
    def versioned_request(self, instance, actor=None):
        from apps.core.api.concurrency import etag_for_instance
        request = self.request()
        if actor is not None:
            request.employee = actor
        request.headers['If-Match'] = etag_for_instance(instance)
        return request

    def fee(self, sample, approver):
        from apps.samples.services import create_fee_record
        return create_fee_record(sample_request=sample, validated_data={
            'fee_decision': 'WAIVED', 'verification_status': 'NOT_REQUIRED',
            'approver_employee_id': approver, 'decision_reason': '权限回归',
        }, actor_employee=self.actor, request=self.versioned_request(sample))

    def test_fee_replacement_invalidates_old_approval_and_binds_current_record(self):
        from apps.samples.models import SampleApprovalLink
        from apps.samples.services import decide_fee_waiver_approval
        from apps.core.api.exceptions import Conflict
        sample = self.sample(self.actor, 'FEES')
        from apps.samples.models import SampleItem
        SampleItem.objects.create(sample_request=sample, line_number=1, product_description_snapshot='测试产品', requested_quantity=1, unit_code='PCS')
        sample.status = 'PENDING'
        sample.save()
        old_record, sample = self.fee(sample, self.member)
        old_approval = SampleApprovalLink.objects.get(sample_request=sample).approval_request
        record, sample = self.fee(sample, self.member)
        old_approval.refresh_from_db()
        self.assertEqual(old_approval.status, 'CANCELLED')
        with self.assertRaises(Conflict):
            decide_fee_waiver_approval(sample_request=sample, approval_id=old_approval.pk, approved=True,
                note='', actor_employee=self.member, request=self.versioned_request(sample, self.member))
        current = SampleApprovalLink.objects.filter(sample_request=sample).exclude(approval_request=old_approval).get().approval_request
        decide_fee_waiver_approval(sample_request=sample, approval_id=current.pk, approved=True,
            note='通过', actor_employee=self.member, request=self.versioned_request(sample, self.member))
        record.refresh_from_db()
        old_record.refresh_from_db()
        self.assertEqual(record.approval_status, 'APPROVED')
        self.assertIsNotNone(old_record.superseded_at)

    def test_fee_self_approval_is_rejected_and_does_not_mutate(self):
        from apps.samples.models import SampleApprovalLink
        from apps.samples.services import decide_fee_waiver_approval
        sample = self.sample(self.actor, 'SELF_FEE')
        from apps.samples.models import SampleItem
        SampleItem.objects.create(sample_request=sample, line_number=1, product_description_snapshot='测试产品', requested_quantity=1, unit_code='PCS')
        sample.status = 'PENDING'
        sample.save()
        record, sample = self.fee(sample, self.actor)
        approval = SampleApprovalLink.objects.get(sample_request=sample).approval_request
        with self.assertRaises(PermissionDenied):
            decide_fee_waiver_approval(sample_request=sample, approval_id=approval.pk, approved=True,
                note='', actor_employee=self.actor, request=self.versioned_request(sample))
        record.refresh_from_db()
        self.assertEqual(record.approval_status, 'PENDING')

    def test_sample_form_team_view_does_not_allow_own_edit_of_team_record(self):
        self.grant('samples.view_samplerequest', 'TEAM')
        self.grant('samples.change_samplerequest', 'OWN')
        sample = self.sample(self.member, 'FORM')
        response = self.client.patch(f'/api/v1/sample-requests/{sample.pk}/form/', {}, format='json')
        self.assertEqual(response.status_code, 404, response.data)

    def test_sample_response_permissions_do_not_expand_team_read_to_write(self):
        self.grant('samples.view_samplerequest', 'TEAM')
        self.grant('samples.change_samplerequest', 'OWN')
        sample = self.sample(self.member, 'CAPS')
        response = self.client.get(f'/api/v1/sample-requests/{sample.pk}/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('samples.view_samplerequest', response.data['data']['allowed_permissions'])
        self.assertNotIn('samples.change_samplerequest', response.data['data']['allowed_permissions'])

    def test_reference_edit_cannot_bypass_status_operation(self):
        from apps.reference_data.models import ProductionUnit
        from apps.core.api.concurrency import etag_for_instance
        self.grant('reference_data.change_productionunit')
        unit = ProductionUnit.objects.create(unit_code='MOD_UNIT', unit_name='测试单位')
        response = self.client.patch(f'/api/v1/reference-data/production-units/{unit.pk}/',
            {'status': 'INACTIVE'}, format='json', HTTP_IF_MATCH=etag_for_instance(unit))
        self.assertEqual(response.status_code, 403, response.data)
        unit.refresh_from_db()
        self.assertEqual(unit.status, 'ACTIVE')

    def test_production_module_can_get_customer_reference_without_customer_details(self):
        sample = self.sample(self.outside, 'PROD_REF')
        self.grant('production_tasks.view_productiontask')
        response = self.client.get('/api/v1/production-tasks/options/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(str(sample.customer_account_id), {row['id'] for row in response.data['data']['customers']})
        response = self.client.get(f'/api/v1/customers/{sample.customer_account_id}/')
        self.assertEqual(response.status_code, 403)

    def test_procurement_module_can_use_sample_source_without_sample_details(self):
        from apps.procurement.source_access import accessible_purchase_samples
        self.grant('procurement.view_purchaseorder')
        sample = self.sample(self.outside, 'PURCHASE_SOURCE')
        self.assertTrue(accessible_purchase_samples(self.request()).filter(pk=sample.pk).exists())
        response = self.client.get(f'/api/v1/sample-requests/{sample.pk}/')
        self.assertEqual(response.status_code, 403)

    def test_bulk_task_rechecks_each_operation_scope(self):
        from apps.workflow.services import execute_batch
        self.grant('workflow.bulk_change_businesstask', 'TEAM')
        self.grant('access_control.complete_businesstask', 'OWN')
        task = self.task(self.member, 'BULK')
        with self.assertRaises(PermissionDenied):
            execute_batch(action='COMPLETE', items=[{'id': task.pk, 'version': task.business_version}],
                event_id=uuid4(), actor_employee=self.actor, request=self.request())
        task.refresh_from_db()
        self.assertEqual(task.status, 'PENDING')
    def test_task_cannot_expose_sample_source_without_sample_view(self):
        from apps.samples.models import SampleTaskLink
        self.grant('workflow.view_businesstask', 'ALL')
        sample = self.sample(self.outside, 'TASK_SOURCE')
        task = self.task(self.actor, 'SAMPLE_SOURCE')
        SampleTaskLink.objects.create(sample_request=sample, business_task=task, is_primary_source=True)
        response = self.client.get(f'/api/v1/tasks/{task.pk}/')
        self.assertEqual(response.status_code, 404, response.data)
        self.grant('samples.view_samplerequest', 'MODULE')
        response = self.client.get(f'/api/v1/tasks/{task.pk}/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['source_attachments'], [])

    def test_sample_module_create_does_not_expand_inquiry_view_scope(self):
        from apps.inquiries.models import Inquiry
        from apps.samples.api.serializers import SampleFromInquiryCreateSerializer
        from apps.samples.services import create_sample_from_inquiry
        self.grant('samples.add_samplerequest', 'MODULE')
        self.grant('inquiries.view_inquiry', 'OWN')
        sample = self.sample(self.outside, 'SOURCE_INQ')
        inquiry = Inquiry.objects.create(customer_account=sample.customer_account, owner_employee=self.outside,
            inquiry_number='MOD_SOURCE_INQ', subject='不可访问询盘', received_at=timezone.now())
        serializer = SampleFromInquiryCreateSerializer(context={'request': self.request()})
        self.assertFalse(serializer.fields['inquiry_id'].queryset.filter(pk=inquiry.pk).exists())
        with self.assertRaises(PermissionDenied):
            create_sample_from_inquiry(inquiry_id=inquiry.pk, validated_data={}, actor_employee=self.actor, request=self.request())

    def test_team_sample_creation_reference_uses_current_customer_owner(self):
        from apps.customers.selectors import accessible_customers
        self.grant('samples.add_samplerequest', 'TEAM')
        sample = self.sample(self.member, 'TEAM_CREATE')
        other = self.sample(self.outside, 'OTHER_CREATE')
        ids = set(accessible_customers(self.request(), 'add_samplerequest').values_list('pk', flat=True))
        self.assertIn(sample.customer_account_id, ids)
        self.assertNotIn(other.customer_account_id, ids)
    def test_item_edit_cannot_bypass_reporting_operation(self):
        from apps.samples.models import SampleItem
        from apps.samples.services import update_sample_item
        self.grant('samples.change_sampleitem', 'MODULE')
        sample = self.sample(self.actor, 'REPORT')
        item = SampleItem.objects.create(sample_request=sample, line_number=1, product_description_snapshot='报工测试', requested_quantity=1, sample_quantity=1, unit_code='PCS')
        with self.assertRaises(PermissionDenied):
            update_sample_item(item=item, validated_data={'cutting_reported_quantity': 1}, actor_employee=self.actor, request=self.versioned_request(sample))
        item.refresh_from_db()
        self.assertEqual(item.cutting_reported_quantity, 0)
        self.grant('access_control.productionreport_sample', 'MODULE')
        update_sample_item(item=item, validated_data={'cutting_reported_quantity': 1}, actor_employee=self.actor, request=self.versioned_request(sample))
        item.refresh_from_db()
        self.assertEqual(item.cutting_reported_quantity, 1)
    def test_legacy_item_grant_does_not_expand_reporting_to_other_customer(self):
        from apps.samples.models import SampleItem
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='samples', codename='change_sampleitem'))
        self.grant('samples.change_samplerequest', 'ALL')
        sample = self.sample(self.outside, 'LEGACY_REPORT')
        item = SampleItem.objects.create(sample_request=sample, line_number=1, product_description_snapshot='旧授权范围测试', requested_quantity=1, unit_code='PCS')
        with self.assertRaises(PermissionDenied):
            module_policy.require_sample_reporting_changes(self.request(), sample, [{'id': item.pk, 'cutting_reported_quantity': 1}])
