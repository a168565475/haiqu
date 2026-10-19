from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.sessions.models import Session
from django.db import close_old_connections, connections, transaction
from django.test import RequestFactory, TransactionTestCase, override_settings

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import WeComBinding, WeComConfig
from apps.wecom.services import OAuthFailure, consume_oauth_state, create_oauth_state, oauth_login


@override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()])
class WeComConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("test-secret"))

    def request(self):
        request = RequestFactory().get("/api/auth/wecom/callback/")
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.create()
        request.user = AnonymousUser()
        return request

    def test_same_state_can_only_be_consumed_by_one_concurrent_request(self):
        request = self.request()
        state = create_oauth_state(request, self.config)
        barrier = Barrier(2)

        def consume():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    consume_oauth_state(request, state)
                    return "consumed"
                except OAuthFailure as exc:
                    return exc.code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(consume) for _ in range(2)]
            self.assertCountEqual([future.result(timeout=20) for future in futures], ["consumed", "INVALID_STATE"])

    @patch("apps.wecom.services.WeComClient")
    def test_concurrent_first_logins_create_one_complete_identity(self, client_class):
        client_class.return_value.get_identity.return_value = {"userid": "Same.Member", "corpid": self.config.corp_id}
        client_class.return_value.get_member.return_value = {"userid": "Same.Member", "name": "真实成员", "status": 1}
        requests = [self.request(), self.request()]
        states = [create_oauth_state(request, self.config) for request in requests]
        barrier = Barrier(2)
        original_count = Employee.objects.count()

        def login(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return oauth_login(requests[index], states[index], "test-code")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(login, index) for index in range(2)]
            self.assertEqual([future.result(timeout=30) for future in futures], ["/auth/waiting-role"] * 2)
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(Employee.objects.count(), original_count + 1)
        self.assertEqual(AuditLog.objects.filter(object_type="WECOM", action="AUTO_CREATE").count(), 1)
        binding = WeComBinding.objects.select_related("employee__user").get()
        self.assertFalse(binding.employee.user.has_usable_password())

    @patch("apps.wecom.services.WeComClient")
    def test_account_suspension_committing_before_login_lock_prevents_session(self, client_class):
        user = get_user_model().objects.create_user("suspended-member")
        employee = Employee.objects.create(user=user, employee_code="WECOM_CONCURRENT", display_name="真实成员")
        WeComBinding.objects.create(employee=employee, corp_id=self.config.corp_id, user_id="Same.Member",
                                     member_name="真实成员", source="MANUAL")
        client_class.return_value.get_identity.return_value = {"userid": "Same.Member", "corpid": self.config.corp_id}
        client_class.return_value.get_member.return_value = {"userid": "Same.Member", "name": "真实成员", "status": 1}
        request = self.request()
        state = create_oauth_state(request, self.config)

        def login():
            close_old_connections()
            try:
                try:
                    return oauth_login(request, state, "test-code")
                except OAuthFailure as exc:
                    return exc.code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
                future = pool.submit(login)
                locked_user.is_active = False
                locked_user.save(update_fields=["is_active"])
            self.assertEqual(future.result(timeout=30), "ACCOUNT_INACTIVE")
        self.assertFalse(any(session.get_decoded().get("_auth_user_id") == str(user.pk) for session in Session.objects.all()))
