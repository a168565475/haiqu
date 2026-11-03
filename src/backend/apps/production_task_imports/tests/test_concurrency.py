"""真实 PostgreSQL 锁兼容性；只在独占测试库中创建记录。"""
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from openpyxl import Workbook

from apps.files.models import BusinessFile
from apps.organizations.models import Employee
from ..services import create_import
from ..storage import write_source


@override_settings(ACCESS_MANAGEMENT_ENABLED=False)
class ImportOwnerLockTests(TransactionTestCase):
    def test_upload_owner_lock_does_not_block_concurrent_file_employee_reference(self):
        user = get_user_model().objects.create_superuser('import_lock_test', '', 'test-only')
        employee = Employee.objects.create(user=user, employee_code='IMPORT_LOCK_TEST', display_name='隔离锁测试')
        workbook = Workbook()
        workbook.active['A1'] = 'isolated lock test'
        output = io.BytesIO()
        workbook.save(output)

        def save_file_reference():
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '1s'")
                    BusinessFile.objects.create(uploaded_by_employee_id=employee.pk,
                        original_name='no-physical-file', storage_key='isolated-lock/' + str(uuid4()),
                        content_type='application/octet-stream', size_bytes=0)
            finally:
                connections.close_all()

        with TemporaryDirectory(prefix='production-import-lock-') as temporary:
            with override_settings(PRODUCTION_IMPORT_ROOT=Path(temporary)):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    def write_while_owner_locked(record, data):
                        write_source(record, data)
                        # create_import 此时持有员工行锁；另一事务的外键检查必须能完成。
                        executor.submit(save_file_reference).result(timeout=5)

                    with patch('apps.production_task_imports.services.write_source', side_effect=write_while_owner_locked):
                        record, reused = create_import(SimpleNamespace(user=user, META={}),
                            SimpleUploadedFile('task.xlsx', output.getvalue()), uuid4())
                self.assertFalse(reused)
                self.assertEqual(record.owner_id, employee.pk)
                self.assertEqual(BusinessFile.objects.filter(uploaded_by_employee=employee).count(), 1)
