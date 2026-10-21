from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import close_old_connections, connections
from django.test import RequestFactory, TransactionTestCase, override_settings

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee
from apps.wecom.credentials import encrypt_secret
from apps.wecom.directory_services import match_directory_employee, preview_directory, sync_directory
from apps.wecom.models import WeComBinding, WeComConfig
from apps.wecom.services import create_oauth_state, oauth_login


@override_settings(
    WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], ACCESS_MANAGEMENT_ENABLED=True,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"], DEV_AUTO_LOGIN_ENABLED=False,
)
class DirectoryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        Employee.objects.create(user=self.admin, employee_code="DIRECTORY_CONCURRENT_ADMIN", display_name="管理员")
        self.config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("test-secret"))
        self.member = {"userid": "Concurrent.One", "name": "并发员工", "department": [1],
                       "main_department": 1, "status": 1, "status_label": "已激活"}
        self.directory = {"corp_id": self.config.corp_id,
                          "departments": [{"id": 1, "parentid": 0, "name": "公司"}], "members": [self.member]}
        self.patch = patch("apps.wecom.directory_services.WeComDirectoryClient")
        self.upstream = self.patch.start().return_value
        self.addCleanup(self.patch.stop)
        self.upstream.read_directory.side_effect = lambda: deepcopy(self.directory)
        self.preview, self.etag = preview_directory(self.request())

    def request(self):
        request = RequestFactory().post("/api/v1/wecom/employee-directory/sync/",
                                        HTTP_IF_MATCH=getattr(self, "etag", ""))
        request.user = self.admin
        return request

    def sync_data(self):
        return {"preview_token": self.preview["preview_token"], "user_ids": [self.member["userid"]],
                "confirmed_new_user_ids": []}

    def parallel(self, functions):
        def run(function):
            close_old_connections()
            try:
                return function()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures = [pool.submit(run, function) for function in functions]
            return [future.result(timeout=40) for future in futures]

    def synchronized_source(self, barrier):
        barrier.wait(timeout=15)
        return deepcopy(self.directory)

    def test_parallel_sync_requests_create_only_one_complete_identity(self):
        barrier = Barrier(2)
        self.upstream.read_directory.side_effect = lambda: self.synchronized_source(barrier)
        results = self.parallel([lambda: sync_directory(self.request(), self.sync_data())] * 2)
        self.assertCountEqual([result[0]["result"] for result in results], ["CREATED", "EXISTING"])
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(Employee.objects.count(), 2)
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertEqual(AuditLog.objects.filter(action="DIRECTORY_CREATE").count(), 1)

    @patch("apps.wecom.services.WeComClient")
    def test_sync_and_first_oauth_login_share_the_same_identity_lock(self, oauth_client):
        request = RequestFactory().get("/api/auth/wecom/callback/")
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.create()
        request.user = AnonymousUser()
        state = create_oauth_state(request, self.config)
        barrier = Barrier(2)
        self.upstream.read_directory.side_effect = lambda: self.synchronized_source(barrier)
        oauth_client.return_value.get_identity.return_value = {
            "userid": self.member["userid"].lower(), "corpid": self.config.corp_id,
        }

        def oauth_member(user_id):
            barrier.wait(timeout=15)
            return {**self.member, "userid": user_id}

        oauth_client.return_value.get_member.side_effect = oauth_member
        results = self.parallel([
            lambda: sync_directory(self.request(), self.sync_data()),
            lambda: oauth_login(request, state, "test-code"),
        ])
        self.assertIn(results[0][0]["result"], ["CREATED", "EXISTING"])
        self.assertEqual(results[1], "/auth/waiting-role")
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(Employee.objects.count(), 2)
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertEqual(AuditLog.objects.filter(action__in=["DIRECTORY_CREATE", "AUTO_CREATE"]).count(), 1)

    def test_parallel_manual_matches_cannot_bind_one_identity_to_two_employees(self):
        targets = [Employee.objects.create(employee_code=f"DIRECTORY_TARGET_{index}", display_name="待确认员工")
                   for index in range(2)]
        barrier = Barrier(2)
        self.upstream.read_directory.side_effect = lambda: self.synchronized_source(barrier)

        def match(employee):
            try:
                return match_directory_employee(self.request(), {
                    "preview_token": self.preview["preview_token"], "user_id": self.member["userid"],
                    "employee_id": employee.pk, "employee_etag": etag_for_instance(employee), "confirmed": True,
                })["result"]
            except Conflict:
                return "CONFLICT"

        results = self.parallel([lambda employee=employee: match(employee) for employee in targets])
        self.assertCountEqual(results, ["MATCHED", "CONFLICT"])
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertEqual(AuditLog.objects.filter(action="DIRECTORY_MATCH").count(), 1)
