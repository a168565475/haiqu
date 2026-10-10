from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from ..models import WorkReport, WorkReportHistory
from .test_work_report_deletion import WorkReportDeletionTests


@override_settings(WORK_REPORT_DELETION_ENABLED=True, WORK_REPORT_HISTORY_ENABLED=True,
                   MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class WorkReportDeletionConcurrencyTests(TransactionTestCase):
    scheme_payload = WorkReportDeletionTests.scheme_payload
    create_approved_scheme = WorkReportDeletionTests.create_approved_scheme
    create_report = WorkReportDeletionTests.create_report
    base = WorkReportDeletionTests.base

    def setUp(self):
        with transaction.atomic():
            WorkReportDeletionTests.setUp(self)

    def simultaneous(self, calls):
        barrier = Barrier(2)
        user_id = self.user.pk

        def worker(call):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                client = APIClient(); client.force_authenticate(get_user_model().objects.get(pk=user_id))
                barrier.wait(timeout=10)
                method, url, body, headers = call
                response = getattr(client, method)(url, body, format='json', **headers)
                return response.status_code
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, calls))

    def test_delete_and_replay_never_resurrect_report(self):
        row, payload, _ = self.create_report()
        result = self.simultaneous([
            ('delete', self.base + row['id'] + '/', {'reason': '重复'}, {'HTTP_IF_MATCH': row['etag']}),
            ('post', self.base, payload, {}),
        ])
        self.assertEqual(result[0], 204)
        self.assertIn(result[1], [201, 409])
        self.assertFalse(WorkReport.objects.filter(pk=row['id']).exists())
        self.assertIsNotNone(WorkReportHistory.objects.get(report_id=row['id']).deleted_at)
        self.assertEqual(self.client.post(self.base, payload, format='json').status_code, 409)

    def test_delete_and_edit_are_serialized_without_server_error(self):
        row, payload, _ = self.create_report()
        edited = deepcopy(payload); edited.pop('client_request_id'); edited['lines'][0]['quantity'] = '4'
        url = self.base + row['id'] + '/'
        result = self.simultaneous([
            ('delete', url, {'reason': '误录'}, {'HTTP_IF_MATCH': row['etag']}),
            ('patch', url, edited, {'HTTP_IF_MATCH': row['etag']}),
        ])
        self.assertIn(tuple(result), [(204, 404), (412, 200)], result)
        self.assertEqual(WorkReport.objects.filter(pk=row['id']).exists(), result[1] == 200)
