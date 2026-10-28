from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.boms.models import Bom, BomCreationMethod, BomLine, BomLineImage, BomSection
from apps.files.models import BusinessFile
from apps.organizations.models import EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile
from apps.procurement.models import PurchaseRequest, PurchaseRequestLine

from ..models import ProductionTask, ProductionTaskStatus
from ..selectors import external_business_blocker
from ..services import _create_numbered_task
from . import test_production_task_api as fixtures
from . import test_task_management as management


class ArchivedBomTaskDeletionTests(management.ProductionTaskManagementTests):
    payload = fixtures.ProductionTaskApiTests.payload
    create_task = fixtures.ProductionTaskApiTests.create_task

    def setUp(self):
        super().setUp()
        department, _ = OrganizationUnit.objects.get_or_create(
            unit_code='DEPT_BUSINESS', defaults={'unit_name': '业务部'},
        )
        EmployeeOrganizationAssignment.objects.create(
            employee=self.employee, organization_unit=department, effective_from=timezone.now(),
        )
        production, _ = OrganizationUnit.objects.get_or_create(
            unit_code='DEPT_PRODUCTION', defaults={'unit_name': '生产部'},
        )
        EmployeeOrganizationAssignment.objects.create(
            employee=self.follower, organization_unit=production, effective_from=timezone.now(),
        )
        role, _ = RoleProfile.objects.get_or_create(
            role_code='MERCHANDISER', defaults={
                'display_name': '跟单', 'auth_group': Group.objects.get_or_create(name='删除测试跟单')[0],
            },
        )
        EmployeeRoleAssignment.objects.create(
            employee=self.follower, role_profile=role, effective_from=timezone.now(),
        )

    def task_and_bom(self):
        created = self.create_task()
        task = ProductionTask.objects.get(pk=created.data['data']['id'])
        bom = Bom.objects.create(
            bom_number=f'DELETE-{task.pk}', production_task=task,
            product_line=task.products.get(), creation_method=BomCreationMethod.BLANK,
            order_quantity=10, created_by_employee=self.employee,
        )
        section = BomSection.objects.create(bom=bom, line_number=1, section_type='FABRIC', title='面料')
        line = BomLine.objects.create(section=section, line_number=1, part_name='面料')
        return task, bom, line

    def archive_bom_and_cancel(self, task, bom):
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='boms'))
        for name in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            self.user.__dict__.pop(name, None)
        url = f'/api/v1/boms/{bom.pk}/'
        response = self.client.post(url + 'archive/', {}, format='json',
                                    HTTP_IF_MATCH=self.client.get(url)['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        task.status = ProductionTaskStatus.CANCELLED
        task.save()

    def delete_task(self, task):
        url = f'/api/v1/production-tasks/{task.pk}/'
        return self.client.delete(url, HTTP_IF_MATCH=self.client.get(url)['ETag'])

    def test_deleted_bom_allows_task_removal_and_preserves_history(self):
        task, bom, line = self.task_and_bom()
        image = BusinessFile.objects.create(original_name='history.png', storage_key='unit/history.png',
                                            content_type='image/png', size_bytes=1, scan_status='CLEAN')
        BomLineImage.objects.create(bom_line=line, business_file=image, position=1)
        self.archive_bom_and_cancel(task, bom)
        response = self.delete_task(task)
        self.assertEqual(response.status_code, 204, getattr(response, 'data', None))
        task.refresh_from_db()
        self.assertIsNotNone(task.archived_at)
        self.assertEqual(task.archived_by_employee, self.employee)
        self.assertEqual(self.client.get(f'/api/v1/production-tasks/{task.pk}/').status_code, 404)
        listed = self.client.get('/api/v1/production-tasks/', {'search': task.task_number})
        self.assertEqual(listed.status_code, 200)
        self.assertFalse(any(item['id'] == str(task.pk) for item in listed.data['data']))
        self.assertTrue(task.products.exists())
        self.assertTrue(Bom.objects.filter(pk=bom.pk, archived_at__isnull=False).exists())
        self.assertTrue(BomLineImage.objects.filter(bom_line=line, business_file=image).exists())
        self.assertTrue(BusinessFile.objects.filter(pk=image.pk).exists())
        self.assertTrue(AuditLog.objects.filter(object_id=bom.pk, action='ARCHIVE').exists())
        audit = AuditLog.objects.get(object_id=task.pk, action='DELETED')
        self.assertEqual(audit.after_data['deletion_mode'], 'ARCHIVE')
        self.assertEqual(audit.after_data['retained_bom_ids'], [str(bom.pk)])
        self.assertIsNone(audit.before_data['deleted_records']['task']['archived_at'])
        self.assertEqual(self.client.delete(f'/api/v1/production-tasks/{task.pk}/',
                                          HTTP_IF_MATCH='"old"').status_code, 404)

    def test_active_bom_version_still_blocks_task_deletion(self):
        task, bom, line = self.task_and_bom()
        self.archive_bom_and_cancel(task, bom)
        Bom.objects.create(bom_number='ACTIVE-VERSION', production_task=task,
                           product_line=task.products.get(), version_number=2,
                           creation_method=BomCreationMethod.COPY, copied_from=bom, order_quantity=10)
        response = self.delete_task(task)
        self.assertEqual(response.status_code, 409, response.data)
        task.refresh_from_db()
        self.assertIsNone(task.archived_at)

    def test_recreate_deleted_number_keeps_old_bom_and_audit_on_old_task(self):
        task, bom, line = self.task_and_bom()
        self.archive_bom_and_cancel(task, bom)
        self.assertEqual(self.delete_task(task).status_code, 204)
        created = self.create_task(task_number=task.task_number)
        new_task = ProductionTask.objects.get(pk=created.data['data']['id'])
        self.assertNotEqual(new_task.pk, task.pk)
        self.assertIsNone(new_task.archived_at)
        self.assertFalse(new_task.products.get().boms.exists())
        bom.refresh_from_db()
        self.assertEqual(bom.production_task_id, task.pk)
        self.assertEqual(bom.product_line_id, line.section.bom.product_line_id)
        self.assertTrue(AuditLog.objects.filter(object_id=task.pk, action='DELETED').exists())
        listed = self.client.get('/api/v1/production-tasks/', {'search': task.task_number})
        self.assertEqual([item['id'] for item in listed.data['data']], [str(new_task.pk)])
        duplicate = self.client.post('/api/v1/production-tasks/', self.payload(task_number=task.task_number), format='json')
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertIn('生产任务单号已存在', duplicate.data['error']['message'])

    def test_database_prevents_duplicate_active_number_and_restore_collision(self):
        task, bom, _ = self.task_and_bom()
        self.archive_bom_and_cancel(task, bom)
        self.assertEqual(self.delete_task(task).status_code, 204)
        created = self.create_task(task_number=task.task_number)
        active = ProductionTask.objects.get(pk=created.data['data']['id'])
        values = {
            field.attname: getattr(active, field.attname)
            for field in ProductionTask._meta.concrete_fields
            if field.name not in {'id', 'created_at', 'updated_at', 'contract_number'}
        }
        values['contract_number'] = 'RECREATE-DUPLICATE'
        with self.assertRaises(ValidationError) as caught:
            _create_numbered_task(**values)
        self.assertIn('task_number', caught.exception.detail)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductionTask.objects.filter(pk=task.pk).update(archived_at=None)
        task.refresh_from_db()
        self.assertIsNotNone(task.archived_at)
        self.assertEqual(ProductionTask.objects.filter(task_number=task.task_number, archived_at__isnull=True).count(), 1)

    def test_reuse_task_number_does_not_reuse_historical_contract_number(self):
        task, bom, _ = self.task_and_bom()
        self.archive_bom_and_cancel(task, bom)
        self.assertEqual(self.delete_task(task).status_code, 204)
        response = self.client.post('/api/v1/production-tasks/',
                                    self.payload(task_number=task.task_number, contract_number=task.contract_number),
                                    format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('合同编号已存在', response.data['error']['message'])

    def test_archived_internal_versions_and_fabric_links_are_retained(self):
        task, bom, line = self.task_and_bom()
        self.archive_bom_and_cancel(task, bom)
        copy = Bom.objects.create(bom_number='ARCHIVED-VERSION', production_task=task,
                                  product_line=task.products.get(), version_number=2,
                                  creation_method=BomCreationMethod.COPY, copied_from=bom,
                                  order_quantity=10, archived_at=timezone.now())
        child = BomLine.objects.create(section=line.section, line_number=2,
                                       part_name='裁片', fabric_source_line=line)
        self.assertEqual(self.delete_task(task).status_code, 204)
        copy.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(copy.copied_from_id, bom.pk)
        self.assertEqual(child.fabric_source_line_id, line.pk)

    def test_other_task_copy_and_procurement_line_still_block(self):
        task, bom, line = self.task_and_bom()
        self.archive_bom_and_cancel(task, bom)
        other, other_bom, other_line = self.task_and_bom()
        other_bom.copied_from = bom
        other_bom.save()
        self.assertEqual(self.delete_task(task).status_code, 409)
        other_bom.copied_from = None
        other_bom.save()
        request = PurchaseRequest.objects.create(request_number='DELETE-GUARD',
                                                 production_task=other, bom=other_bom)
        PurchaseRequestLine.objects.create(purchase_request=request, line_number=1, bom_line=line,
                                           material_snapshot='面料', unit_snapshot='米',
                                           gross_requirement_quantity=1)
        response = self.delete_task(task)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn('采购', str(response.data))
        task.refresh_from_db()
        self.assertIsNone(task.archived_at)
        self.assertFalse(AuditLog.objects.filter(object_id=task.pk, action='DELETED').exists())

    def test_archiving_rolls_back_if_audit_fails(self):
        task, bom, line = self.task_and_bom()
        self.archive_bom_and_cancel(task, bom)
        with patch('apps.production_tasks.services.write_audit_log', side_effect=RuntimeError('audit failed')):
            with self.assertRaisesMessage(RuntimeError, 'audit failed'):
                self.delete_task(task)
        task.refresh_from_db()
        self.assertIsNone(task.archived_at)
        self.assertTrue(task.products.exists())
        self.assertTrue(Bom.objects.filter(pk=bom.pk).exists())

    def test_archived_bom_does_not_relax_product_line_deletion(self):
        task, bom, line = self.task_and_bom()
        self.archive_bom_and_cancel(task, bom)
        self.assertIn('BOM', external_business_blocker(task.products.get()))
