from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.organizations.models import Employee


@override_settings(ACCESS_MANAGEMENT_ENABLED=True)
class CodexConcurrencyTests(TransactionTestCase):
    def test_two_current_etag_requests_create_only_one_operation(self):
        from apps.codex_connection.models import CodexConnection, CodexOperation
        user = get_user_model().objects.create_superuser('codex_parallel', '', 'TestPassword123!')
        Employee.objects.create(user=user, employee_code='CODEX_PARALLEL', display_name='并发管理员')
        CodexConnection.objects.create(singleton=1)
        clients = [APIClient(), APIClient()]
        for client in clients:
            client.force_login(user)
        etag = clients[0].get('/api/v1/codex-connection/')['ETag']
        barrier = Barrier(2)

        def enqueue(client):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                response = client.post('/api/v1/codex-connection/login/', {}, format='json', HTTP_IF_MATCH=etag)
                return response.status_code
            finally:
                # 当前线程结束后不再复用连接，不能让健康连接留在测试库内阻挡 DROP。
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(enqueue, clients))
        self.assertEqual(sorted(statuses), [202, 412])
        self.assertEqual(CodexOperation.objects.count(), 1)
