from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.access_control.models import RoleActionGrant, SalesTeam, SalesTeamMembership
from apps.access_control.sales_policy import allowed_owners, has_permission, legacy_permission, scopes


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, SALES_ACCESS_ENABLED=True)
class SalesPolicyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('scope_manager')
        self.manager = Employee.objects.create(user=self.user, employee_code='SCOPE_MANAGER', display_name='经理')
        self.member = Employee.objects.create(employee_code='SCOPE_MEMBER', display_name='团队成员')
        self.other = Employee.objects.create(employee_code='SCOPE_OTHER', display_name='其他团队成员')
        self.team = SalesTeam.objects.create(code='SCOPE_TEAM', name='团队', manager=self.manager)
        SalesTeamMembership.objects.create(team=self.team, employee=self.member, created_by_employee=self.manager)

    def request(self):
        return SimpleNamespace(user=get_user_model().objects.get(pk=self.user.pk), employee=self.manager)

    def grant(self, code, scope, number):
        app, codename = code.split('.')
        permission = Permission.objects.get(content_type__app_label=app, codename=codename)
        group = Group.objects.create(name=f'scope_{number}')
        group.permissions.add(permission)
        role = RoleProfile.objects.create(auth_group=group, role_code=f'SCOPE_{number}', display_name=f'角色{number}')
        EmployeeRoleAssignment.objects.create(employee=self.manager, role_profile=role, effective_from=timezone.now())
        RoleActionGrant.objects.create(role=role, permission=permission, scope=scope)
        return role

    def test_team_read_does_not_expand_own_write(self):
        self.grant('inquiries.view_inquiry', 'TEAM', 1)
        self.grant('inquiries.change_inquiry', 'OWN', 2)
        request = self.request()
        all_read, read = allowed_owners(request, 'inquiries.view_inquiry')
        all_write, write = allowed_owners(request, 'inquiries.change_inquiry')
        self.assertFalse(all_read or all_write)
        self.assertEqual(set(read.values_list('id', flat=True)), {self.member.pk})
        self.assertEqual(set(write.values_list('id', flat=True)), {self.manager.pk})
        self.assertFalse(legacy_permission(request, 'inquiries.view_inquiry'))

    def test_new_role_projection_is_not_legacy_permission(self):
        self.grant('inquiries.view_inquiry', 'OWN', 1)
        request = self.request()
        self.assertTrue(has_permission(request, 'inquiries.view_inquiry'))
        self.assertFalse(legacy_permission(request, 'inquiries.view_inquiry'))
        self.assertFalse(has_permission(request, 'inquiries.change_inquiry'))

    def test_direct_legacy_import_remains_identifiable(self):
        permission = Permission.objects.get(content_type__app_label='customers', codename='import_customercontact')
        self.user.user_permissions.add(permission)
        self.assertTrue(legacy_permission(self.request(), 'import_customercontact'))
        self.assertTrue(has_permission(self.request(), 'customers.import_customercontact'))

    def test_role_changes_take_effect_on_next_request(self):
        role = self.grant('inquiries.view_inquiry', 'TEAM', 1)
        self.assertEqual(scopes(self.request(), 'view_inquiry'), {'TEAM'})
        role.archived_at = timezone.now()
        role.save()
        self.assertEqual(scopes(self.request(), 'view_inquiry'), set())

    def test_disabled_team_does_not_supply_team_scope(self):
        self.grant('inquiries.view_inquiry', 'TEAM', 1)
        self.team.is_active = False
        self.team.save()
        all_owners, owners = allowed_owners(self.request(), 'inquiries.view_inquiry')
        self.assertFalse(all_owners)
        self.assertFalse(owners.exists())

    def test_empty_role_and_inactive_actor_have_no_permission(self):
        self.assertFalse(has_permission(self.request(), 'inquiries.view_inquiry'))
        self.grant('inquiries.view_inquiry', 'ALL', 1)
        self.user.is_active = False
        self.user.save()
        self.assertFalse(has_permission(self.request(), 'inquiries.view_inquiry'))

    def customer(self, owner, suffix):
        from apps.customers.models import CustomerAccount, CustomerAssignment
        customer = CustomerAccount.objects.create(account_code=f'SCOPE_{suffix}', account_name=f'范围客户{suffix}')
        if owner:
            CustomerAssignment.objects.create(customer_account=customer, employee=owner,
                assignment_role='PRIMARY_OWNER', effective_from=timezone.now(), assigned_by_employee=self.manager)
        return customer

    def inquiry(self, customer, owner, suffix):
        from apps.inquiries.models import Inquiry
        return Inquiry.objects.create(customer_account=customer, owner_employee=owner,
            inquiry_number=f'SCOPE_INQ_{suffix}', subject='范围校验询盘', received_at=timezone.now())

    def test_document_owner_cannot_override_customer_ownership(self):
        from apps.inquiries.selectors import accessible_inquiries
        self.grant('inquiries.view_inquiry', 'OWN', 1)
        own = self.customer(self.manager, 'OWN')
        other = self.customer(self.other, 'OTHER')
        mine = self.inquiry(own, self.other, 'OWN')
        self.inquiry(other, self.manager, 'OTHER')
        self.assertEqual(list(accessible_inquiries(self.request()).values_list('pk', flat=True)), [mine.pk])

    def test_missing_primary_owner_does_not_guess_document_owner(self):
        from apps.inquiries.selectors import accessible_inquiries
        self.grant('inquiries.view_inquiry', 'OWN', 1)
        self.inquiry(self.customer(None, 'MISSING'), self.manager, 'MISSING')
        self.assertFalse(accessible_inquiries(self.request()).exists())

    def test_inquiry_owner_filter_and_counts_use_customer_owner(self):
        from rest_framework.test import APIClient
        self.grant('inquiries.view_inquiry', 'ALL', 1)
        own = self.inquiry(self.customer(self.manager, 'COUNT_OWN'), self.other, 'COUNT_OWN')
        self.inquiry(self.customer(self.other, 'COUNT_OTHER'), self.manager, 'COUNT_OTHER')
        self.inquiry(self.customer(None, 'COUNT_NONE'), self.manager, 'COUNT_NONE')
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get('/api/v1/inquiries/', {'owner_employee_id': str(self.manager.pk)})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row['id'] for row in response.data['data']], [str(own.pk)])
        response = client.get('/api/v1/inquiries/metrics/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['list_counts'], {'all': 3, 'mine': 1, 'unassigned': 1})

    def test_inquiry_conversion_does_not_disclose_unreadable_quote(self):
        from rest_framework.test import APIClient
        self.grant('inquiries.view_inquiry', 'ALL', 1)
        customer = self.customer(self.manager, 'CONVERSION')
        inquiry = self.inquiry(customer, self.manager, 'CONVERSION')
        from apps.inquiries.models import InquiryItem
        InquiryItem.objects.create(inquiry=inquiry, line_number=1, product_description='统计权限测试', quantity=1, unit_code='PCS')
        inquiry.status = 'FOLLOW_UP'
        inquiry.save()
        version = self.quote(customer, self.manager, 'CONVERSION')
        from apps.quotations.models import QuotationLine
        QuotationLine.objects.create(quotation_version=version, line_number=1,
            product_description_snapshot='统计权限测试', quantity=1, unit_code='PCS', unit_price=1, line_total=1)
        version.status = 'SENT'
        version.locked_at = timezone.now()
        version.transaction_entity_snapshot = {'legal_name': '权限测试主体'}
        version.address_snapshot = {'address': '权限测试地址'}
        version.contact_snapshot = {'name': '权限测试联系人'}
        version.save()
        version.quotation.source_inquiry = inquiry
        version.quotation.save()
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get('/api/v1/inquiries/metrics/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['conversion']['numerator'], 0)
        self.grant('quotations.view_quotationversion', 'OWN', 2)
        response = client.get('/api/v1/inquiries/metrics/')
        self.assertEqual(response.data['data']['conversion']['numerator'], 1)

    def test_collaborator_does_not_inherit_inquiries(self):
        from apps.customers.models import CustomerAssignment
        from apps.customers.selectors import accessible_customers
        from apps.inquiries.selectors import accessible_inquiries
        customer = self.customer(self.other, 'COLLAB')
        self.inquiry(customer, self.manager, 'COLLAB')
        CustomerAssignment.objects.create(customer_account=customer, employee=self.manager,
            assignment_role='COLLABORATOR', effective_from=timezone.now(), assigned_by_employee=self.other)
        self.grant('customers.view_customeraccount', 'OWN', 1)
        self.grant('inquiries.view_inquiry', 'OWN', 2)
        self.assertTrue(accessible_customers(self.request()).filter(pk=customer.pk).exists())
        self.assertFalse(accessible_inquiries(self.request()).exists())

    def test_team_inquiry_can_be_read_but_not_edited_via_api(self):
        from rest_framework.test import APIClient
        self.grant('inquiries.view_inquiry', 'TEAM', 1)
        self.grant('inquiries.change_inquiry', 'OWN', 2)
        inquiry = self.inquiry(self.customer(self.member, 'TEAM'), self.manager, 'TEAM')
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(f'/api/v1/inquiries/{inquiry.pk}/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn('inquiries.change_inquiry', response.data['data']['allowed_permissions'])
        response = client.patch(f'/api/v1/inquiries/{inquiry.pk}/', {'subject': '不能编辑'}, format='json')
        self.assertEqual(response.status_code, 404, response.data)
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.subject, '范围校验询盘')

    def test_new_workflow_action_not_implied_by_scoped_change(self):
        self.grant('inquiries.change_inquiry', 'ALL', 1)
        self.assertFalse(has_permission(self.request(), 'access_control.markinvalid_inquiry'))
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='inquiries', codename='change_inquiry'))
        self.assertTrue(has_permission(self.request(), 'access_control.markinvalid_inquiry'))

    def test_new_inquiry_uses_customer_owner_for_team_creator(self):
        from apps.inquiries.services import create_inquiry
        self.grant('inquiries.add_inquiry', 'TEAM', 1)
        customer = self.customer(self.member, 'CREATE')
        request = self.request()
        request.META = {}
        inquiry = create_inquiry(validated_data={'customer_account': customer, 'subject': '团队新增', 'received_at': timezone.now()}, actor_employee=self.manager, request=request)
        self.assertEqual(inquiry.owner_employee_id, self.member.pk)

    def test_customer_team_view_does_not_expand_search_inquiry_scope(self):
        from rest_framework.test import APIClient
        self.grant('customers.view_customeraccount', 'TEAM', 1)
        self.grant('inquiries.view_inquiry', 'OWN', 2)
        inquiry = self.inquiry(self.customer(self.member, 'SEARCH'), self.manager, 'SEARCH')
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get('/api/v1/search/', {'q': '范围', 'types': 'INQUIRY'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn(str(inquiry.pk), str(response.data))

    def quote(self, customer, owner, suffix):
        from apps.customers.models import CustomerTransactionEntity
        from apps.quotations.models import Quotation, QuotationVersion
        entity = CustomerTransactionEntity.objects.create(customer_account=customer, entity_code=f'SCOPE_ENTITY_{suffix}', legal_name='权限测试主体')
        quote = Quotation.objects.create(customer_account=customer, transaction_entity=entity, owner_employee=owner, quotation_number=f'SCOPE_QUOTE_{suffix}', subject='范围测试报价')
        return QuotationVersion.objects.create(quotation=quote, version_number=1, currency_code='CNY')

    def test_bulk_action_requires_its_individual_scope_and_rolls_back(self):
        from rest_framework.test import APIClient
        from apps.core.api.concurrency import etag_for_instance
        self.grant('inquiries.bulk_change_inquiry', 'ALL', 1)
        self.grant('access_control.markinvalid_inquiry', 'OWN', 2)
        own = self.inquiry(self.customer(self.manager, 'BULK_OWN'), self.manager, 'BULK_OWN')
        other = self.inquiry(self.customer(self.member, 'BULK_TEAM'), self.member, 'BULK_TEAM')
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post('/api/v1/inquiries/bulk-mark-invalid/', {'items': [{'id': str(x.pk), 'etag': etag_for_instance(x)} for x in [own, other]], 'reason_code': 'SPAM'}, format='json')
        self.assertEqual(response.status_code, 403, response.data)
        own.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(own.status, 'DRAFT')
        self.assertEqual(other.status, 'DRAFT')

    def test_same_customer_quote_file_is_not_readable_via_upload_ownership(self):
        from apps.access_control.sales_sources import readable_files
        from apps.files.models import BusinessFile
        from apps.quotations.models import QuotationDocument
        self.grant('inquiries.add_inquiryfilelink', 'TEAM', 1)
        self.grant('quotations.view_quotationdocument', 'OWN', 2)
        version = self.quote(self.customer(self.member, 'FILE'), self.manager, 'FILE')
        file = BusinessFile.objects.create(uploaded_by_employee=self.manager, original_name='protected.pdf', storage_key='tests/scope/protected.pdf', content_type='application/pdf', size_bytes=5)
        self.assertTrue(readable_files(self.request()).filter(pk=file.pk).exists())
        QuotationDocument.objects.create(quotation_version=version, business_file=file, document_type='DRAFT', generated_at=timezone.now(), snapshot_hash='test')
        self.assertFalse(readable_files(self.request()).filter(pk=file.pk).exists())
        self.grant('quotations.view_quotationdocument', 'TEAM', 3)
        self.assertTrue(readable_files(self.request()).filter(pk=file.pk).exists())

    def test_task_source_does_not_inherit_customer_team_view(self):
        from apps.workflow.models import BusinessTask
        from apps.inquiries.models import InquiryTaskLink
        from apps.workflow.selectors import accessible_tasks
        self.grant('customers.view_customeraccount', 'TEAM', 1)
        self.grant('inquiries.view_inquiry', 'OWN', 2)
        inquiry = self.inquiry(self.customer(self.member, 'TASK'), self.manager, 'TASK')
        task = BusinessTask.objects.create(assignee_employee=self.manager, created_by_employee=self.manager, title='不应显示的来源任务')
        InquiryTaskLink.objects.create(inquiry=inquiry, business_task=task, is_primary_source=True)
        self.assertFalse(accessible_tasks(self.request()).filter(pk=task.pk).exists())
        self.grant('inquiries.view_inquiry', 'TEAM', 3)
        self.assertTrue(accessible_tasks(self.request()).filter(pk=task.pk).exists())

    def test_merchandiser_read_requires_separate_write_grant(self):
        from apps.sales_orders.models import SalesOrder
        from apps.sales_orders.selectors import accessible_sales_orders
        customer = self.customer(self.other, 'MERCH')
        version = self.quote(customer, self.other, 'MERCH')
        order = SalesOrder.objects.create(order_number='SCOPE_ORDER', source_type='DIRECT', customer_account=customer, transaction_entity=version.quotation.transaction_entity, salesperson=self.other, merchandiser=self.manager, order_date=timezone.localdate(), currency_code='CNY')
        self.grant('sales_orders.view_salesorder', 'OWN', 1)
        self.grant('sales_orders.change_salesorder', 'TEAM', 2)
        self.assertTrue(accessible_sales_orders(self.request()).filter(pk=order.pk).exists())
        self.assertFalse(accessible_sales_orders(self.request(), 'sales_orders.change_salesorder').filter(pk=order.pk).exists())

    def test_quote_ownership_uses_customer_primary_owner(self):
        from apps.quotations.selectors import accessible_quotations
        self.grant('quotations.view_quotation', 'OWN', 1)
        own = self.quote(self.customer(self.manager, 'QUOTE_OWN'), self.other, 'QUOTE_OWN')
        self.quote(self.customer(self.other, 'QUOTE_OTHER'), self.manager, 'QUOTE_OTHER')
        self.assertEqual(list(accessible_quotations(self.request(), 'view_quotation').values_list('pk', flat=True)), [own.quotation_id])

    def test_new_owner_validation_does_not_rewrite_existing_owner(self):
        from apps.access_control.sales_policy import validate_document_owner
        from rest_framework.exceptions import ValidationError
        customer = self.customer(self.manager, 'OWNER')
        with self.assertRaises(ValidationError):
            validate_document_owner(self.request(), customer, self.other)
        validate_document_owner(self.request(), customer, self.other, self.other)
        customer.refresh_from_db()
        from apps.access_control.sales_policy import primary_owner
        self.assertEqual(primary_owner(customer), self.manager)

    def test_legacy_customer_grant_keeps_workflow_action_access(self):
        from apps.customers.models import CustomerDataAccessGrant
        from apps.access_control.sales_policy import can_customer
        customer = self.customer(self.other, 'LEGACY')
        permission = Permission.objects.get(content_type__app_label='inquiries', codename='change_inquiry')
        self.user.user_permissions.add(permission)
        CustomerDataAccessGrant.objects.create(employee=self.manager, customer_account=customer, permission=permission, effective_from=timezone.now(), reason='旧授权保留')
        self.assertTrue(can_customer(self.request(), 'access_control.markinvalid_inquiry', customer.pk))

    def test_contact_edit_cannot_overwrite_method_without_its_scope(self):
        from apps.customers.models import CustomerContact, CustomerContactMethod
        from apps.customers.contact_services import update_contact_profile
        from apps.core.api.concurrency import etag_for_instance
        from rest_framework.exceptions import PermissionDenied
        customer = self.customer(self.member, 'CONTACT')
        contact = CustomerContact.objects.create(customer_account=customer, display_name='团队联系人')
        method = CustomerContactMethod.objects.create(customer_contact=contact, method_type='EMAIL', raw_value='before@example.test', normalized_value='before@example.test', normalized_at=timezone.now())
        self.grant('customers.change_customercontact', 'TEAM', 1)
        self.grant('customers.change_customercontactmethod', 'OWN', 2)
        request = self.request()
        request.headers = {'If-Match': etag_for_instance(contact)}
        request.META = {}
        with self.assertRaises(PermissionDenied):
            update_contact_profile(contact=contact, validated_data={'display_name': '不应保留', 'methods': [{'method_type': 'EMAIL', 'raw_value': 'after@example.test'}]}, actor_employee=self.manager, request=request)
        contact.refresh_from_db()
        method.refresh_from_db()
        self.assertEqual(contact.display_name, '团队联系人')
        self.assertEqual(method.raw_value, 'before@example.test')

    def test_customer_timeline_hides_other_resource_scope(self):
        from apps.crm.models import CustomerTimelineEvent
        from apps.access_control.sales_sources import filter_activity
        customer = self.customer(self.member, 'EVENT')
        version = self.quote(customer, self.member, 'EVENT')
        event = CustomerTimelineEvent.objects.create(customer_account=customer, source_type='QUOTATION', source_id=version.quotation_id, event_type='QUOTATION_CREATED', title='受保护的报价', occurred_at=timezone.now())
        self.grant('customers.view_customeraccount', 'TEAM', 1)
        self.grant('quotations.view_quotation', 'OWN', 2)
        self.assertFalse(filter_activity(CustomerTimelineEvent.objects.all(), self.request()).filter(pk=event.pk).exists())
