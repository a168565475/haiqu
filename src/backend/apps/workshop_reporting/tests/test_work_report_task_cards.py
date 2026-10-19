import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.files.models import BusinessFile, FileScanStatus
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_scheduling.models import ProductionScheduleProductCraft, ScheduleStatus
from apps.production_tasks.models import ProductionTaskProductImage
from apps.workshop_config.models import Craft, CraftType, Operation, PlanCategory, Workshop, WorkshopEmployee

from ..models import WageSchemeLine, WorkReport
from . import test_work_report_task_selection as selection_tests


@override_settings(
    MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False,
)
class WorkReportTaskCardTests(APITestCase):
    setUp = selection_tests.WorkReportTaskSelectionTests.setUp
    scheme_payload = selection_tests.WorkReportTaskSelectionTests.scheme_payload
    create_approved_scheme = selection_tests.WorkReportTaskSelectionTests.create_approved_scheme
    copy_values = selection_tests.WorkReportTaskSelectionTests.copy_values
    copy_row = selection_tests.WorkReportTaskSelectionTests.copy_row
    add_product = selection_tests.WorkReportTaskSelectionTests.add_product
    add_task = selection_tests.WorkReportTaskSelectionTests.add_task
    create_report = selection_tests.WorkReportTaskSelectionTests.create_report
    copy_report = selection_tests.WorkReportTaskSelectionTests.copy_report
    task_url = '/api/v1/workshop-reporting/work-report-tasks/'

    def card(self, client=None):
        response = (client or self.client).get(self.task_url, {'production_task_id': str(self.task.pk)})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['data']), 1)
        return response.data['data'][0]

    def image_url(self, product=None, task=None):
        return f"{self.task_url}{(task or self.task).pk}/products/{(product or self.product_line).pk}/image/"

    def image_file(self, folder, name, *, scan_status=FileScanStatus.CLEAN):
        (Path(folder) / name).write_bytes(name.encode())
        return BusinessFile.objects.create(
            original_name=name, storage_key=name, content_type='image/png', size_bytes=len(name),
            uploaded_by_employee=self.employee, scan_status=scan_status,
        )

    def scoped_client(self):
        user = get_user_model().objects.create_user(username='report-card-viewer')
        employee = Employee.objects.create(user=user, employee_code='REPORT-CARD-VIEWER', display_name='报工卡片查看员')
        group = Group.objects.create(name='REPORT-CARD-VIEWER')
        role = RoleProfile.objects.create(role_code='REPORT_CARD_VIEWER', display_name='报工卡片查看员', auth_group=group)
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
        permission = Permission.objects.get(content_type__app_label='workshop_reporting', codename='view_workreport')
        group.permissions.add(permission)
        grant = RoleActionGrant.objects.create(role=role, permission=permission, scope='WORKSHOP')
        RoleGrantResource.objects.create(grant=grant, workshop=self.workshop)
        client = APIClient()
        client.force_authenticate(user)
        return client

    def add_hidden_workshop_report(self, original):
        product, scheduled = self.add_product(self.task, self.schedule, 2)
        scheduled.crafts.update(removed_at=timezone.now(), removed_by_employee=self.employee)
        workshop, _ = Workshop.objects.get_or_create(name='装配车间')
        craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL, workshop=workshop, name='卡片装配工艺', plan_category=PlanCategory.ASSEMBLY,
        )
        operation = Operation.objects.create(
            operation_number='CARD-ASSEMBLY', product_name='工价测试产品', craft=craft,
            name='卡片装配', reporting_unit=self.unit,
        )
        worker = WorkshopEmployee.objects.create(workshop=workshop, position='操作工', name='卡片装配员工')
        ProductionScheduleProductCraft.objects.create(
            schedule_product=scheduled, craft=craft, craft_type_snapshot=CraftType.INTERNAL,
            craft_name_snapshot=craft.name, plan_category=PlanCategory.ASSEMBLY,
        )
        source_line = original.lines.get()
        scheme = self.copy_row(
            original.scheme, scheme_number='GJ-CARD-HIDDEN', product_line_id=product.pk,
            schedule_product_id=scheduled.pk, workshop_id=workshop.pk, scope_craft_id=craft.pk,
        )
        item = self.copy_row(
            source_line.work_item, product_line_id=product.pk, workshop_id=workshop.pk,
            craft_id=craft.pk, operation_id=operation.pk,
        )
        scheme_line = self.copy_row(
            source_line.scheme_line, scheme_id=scheme.pk, work_item_id=item.pk,
            declared_price=Decimal('99'), required_quantity_snapshot=Decimal('100'),
        )
        report = self.copy_row(
            original, report_number='BG-CARD-HIDDEN', client_request_id=uuid.uuid4(),
            product_line_id=product.pk, schedule_product_id=scheduled.pk, workshop_id=workshop.pk,
            scheme_id=scheme.pk, total_amount=Decimal('99'),
        )
        self.copy_row(
            source_line, report_id=report.pk, scheme_line_id=scheme_line.pk, work_item_id=item.pk,
            workshop_employee_id=worker.pk, quantity=Decimal('1'), unit_price_snapshot=Decimal('99'),
            amount=Decimal('99'), required_quantity_snapshot=Decimal('100'),
        )
        return product

    def test_card_sums_saved_amounts_and_uses_only_current_approved_scheme_denominator(self):
        first = self.create_report()
        self.copy_report(first, quantity='98')
        yesterday = timezone.localdate() - timedelta(days=1)
        original = first.scheme
        original.effective_from = yesterday
        original.effective_to = yesterday
        original.save(update_fields=['effective_from', 'effective_to', 'updated_at'])
        WorkReport.objects.all().update(production_date=yesterday)
        current = self.copy_row(
            original, scheme_number='GJ-CARD-V2', parent_scheme_id=original.pk, version=2,
            effective_from=timezone.localdate(), effective_to=None,
        )
        self.copy_row(
            original.lines.get(), scheme_id=current.pk,
            required_quantity_snapshot=Decimal('400'), declared_price=Decimal('99'),
        )

        card = self.card()

        self.assertEqual(card['reported_amount'], '234.50')
        self.assertEqual(card['progress'], {'status': 'READY', 'percentage': 25})
        self.assertEqual(card['workshops'][0]['reported_amount'], '234.50')
        self.assertEqual(card['workshops'][0]['progress'], card['progress'])
        self.assertEqual(card['product']['id'], str(self.product_line.pk))
        self.assertEqual(card['product_count'], 1)

    def test_missing_scheme_or_required_quantity_is_unknown_instead_of_zero(self):
        card = self.card()
        self.assertEqual(card['reported_amount'], '0.00')
        self.assertEqual(card['progress'], {'status': 'NOT_CONFIGURED', 'percentage': None})
        scheme = self.create_approved_scheme().data['data']
        self.assertEqual(self.card()['progress'], {'status': 'READY', 'percentage': 0})
        WageSchemeLine.objects.filter(scheme_id=scheme['id']).update(required_quantity_snapshot=None)
        self.assertEqual(self.card()['progress'], {'status': 'NOT_CONFIGURED', 'percentage': None})

    def test_unconfigured_additional_product_invalidates_whole_task_progress(self):
        self.create_report()
        self.add_product(self.task, self.schedule, 2)
        card = self.card()
        self.assertEqual(card['product_count'], 2)
        self.assertEqual(card['reported_amount'], '4.69')
        self.assertEqual(card['progress'], {'status': 'NOT_CONFIGURED', 'percentage': None})
        self.assertEqual(card['workshops'][0]['progress'], card['progress'])

    def test_history_only_retains_product_and_money_without_inventing_progress(self):
        self.create_report()
        self.schedule.record_status = ScheduleStatus.VOID
        self.schedule.void_reason = '卡片历史任务回归'
        self.schedule.voided_at = timezone.now()
        self.schedule.voided_by_employee = self.employee
        self.schedule.save()
        card = self.card()
        self.assertEqual(card['product']['id'], str(self.product_line.pk))
        self.assertEqual(card['reported_amount'], '4.69')
        self.assertEqual(card['progress'], {'status': 'UNAVAILABLE', 'percentage': None})
        self.assertEqual(card['workshops'][0]['progress'], card['progress'])

    def test_scoped_cards_and_images_never_expose_other_workshop_products_or_amounts(self):
        first = self.create_report()
        hidden_product = self.add_hidden_workshop_report(first)
        client = self.scoped_client()
        # 本类临时文件仅属于报工任务卡片测试；with 结束清理整个 report-task-cards- 专属目录。
        with TemporaryDirectory(prefix='report-task-cards-') as folder, self.settings(
            MEDIA_ROOT=folder, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True,
        ):
            image = self.image_file(folder, 'visible.png', scan_status=FileScanStatus.SKIPPED)
            hidden_image = self.image_file(folder, 'hidden.png')
            self.product_line.image_file = image
            self.product_line.save(update_fields=['image_file'])
            hidden_product.image_file = hidden_image
            hidden_product.save(update_fields=['image_file'])
            card = self.card(client)
            self.assertEqual(card['product_count'], 1)
            self.assertEqual(card['reported_amount'], '4.69')
            self.assertEqual(card['progress'], {'status': 'READY', 'percentage': 1})
            self.assertEqual([item['id'] for item in card['workshops']], [str(self.workshop.pk)])
            self.assertEqual(card['product']['image_url'], self.image_url())
            response = client.get(card['product']['image_url'])
            try:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b''.join(response.streaming_content), b'visible.png')
            finally:
                response.close()
            self.assertEqual(client.get(self.image_url(hidden_product)).status_code, 404)
            self.assertEqual(APIClient().get(self.image_url()).status_code, 403)

    def test_image_primary_gallery_scan_archive_and_path_guards(self):
        # MEDIA_ROOT 和目录外的哨兵文件均在同一专属 TemporaryDirectory 内，退出时自动清理。
        with TemporaryDirectory(prefix='report-task-cards-') as folder:
            media_root = Path(folder) / 'media'
            media_root.mkdir()
            (Path(folder) / 'outside.png').write_bytes(b'outside-private-image')
            with self.settings(MEDIA_ROOT=str(media_root)):
                image = self.image_file(media_root, 'primary.png')
                gallery = self.image_file(media_root, 'gallery.png')
                self.product_line.image_file = image
                self.product_line.save(update_fields=['image_file'])
                ProductionTaskProductImage.objects.create(product_line=self.product_line, image_file=gallery, line_number=1)
                response = self.client.get(self.image_url())
                try:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(b''.join(response.streaming_content), b'primary.png')
                finally:
                    response.close()
                image.scan_status = FileScanStatus.INFECTED
                image.save(update_fields=['scan_status'])
                response = self.client.get(self.image_url())
                try:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(b''.join(response.streaming_content), b'gallery.png')
                finally:
                    response.close()
                gallery.scan_status = FileScanStatus.PENDING
                gallery.save(update_fields=['scan_status'])
                self.assertIsNone(self.card()['product']['image_url'])
                self.assertEqual(self.client.get(self.image_url()).status_code, 404)
                image.scan_status = FileScanStatus.CLEAN
                image.archived_at = timezone.now()
                image.save(update_fields=['scan_status', 'archived_at'])
                self.assertEqual(self.client.get(self.image_url()).status_code, 404)
                image.archived_at = None
                for storage_key in ('../outside.png', 'missing.png'):
                    image.storage_key = storage_key
                    image.save(update_fields=['archived_at', 'storage_key'])
                    self.assertEqual(self.client.get(self.image_url()).status_code, 404)
                task, _, _, _ = self.add_task()
                self.assertEqual(self.client.get(self.image_url(task=task)).status_code, 404)

    def test_card_queries_do_not_grow_per_product(self):
        self.create_report()
        self.card()
        with CaptureQueriesContext(connection) as baseline:
            self.card()
        for line_number in range(2, 12):
            self.add_product(self.task, self.schedule, line_number)
        with CaptureQueriesContext(connection) as expanded:
            card = self.card()
        self.assertEqual(card['product_count'], 11)
        self.assertLessEqual(len(expanded), len(baseline) + 1)
