from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.wecom.models import NotificationDelivery, NotificationEvent
from apps.wecom.notification_services import process_delivery
from .test_notifications import SETTINGS, create_rule
from .test_workshop_notifications import receiver


@override_settings(**SETTINGS)
class WorkshopNotificationConcurrencyTests(TransactionTestCase):
    def test_stale_pending_notification_never_calls_wecom(self):
        from apps.workshop_reporting.tests.test_workshop_reporting_api import WorkshopReportingApiTests
        from apps.workshop_reporting.models import WageScheme
        fixture = WorkshopReportingApiTests()
        with transaction.atomic():
            fixture.setUp()
        member, role = receiver("U07_STALE_FACTORY", "workshop_reporting.approve_wagescheme")
        create_rule("WAGE_SCHEME_SUBMITTED", fixture.employee, [role.role_code])
        draft = fixture.client.post("/api/v1/workshop-reporting/wage-schemes/", fixture.scheme_payload(), format="json")
        submitted = fixture.client.post(f"/api/v1/workshop-reporting/wage-schemes/{draft.data['data']['id']}/submit/",
            {}, format="json", HTTP_IF_MATCH=draft["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        client = APIClient()
        client.force_authenticate(member.user)
        decision = client.post(f"/api/v1/workshop-reporting/wage-schemes/{draft.data['data']['id']}/return/",
            {"comment": "合法退回"}, format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertEqual(decision.status_code, 200, decision.data)
        self.assertEqual(WageScheme.objects.get().status, "RETURNED")
        delivery = NotificationDelivery.objects.get(channel="WECOM", recipient__event__event_code="WAGE_SCHEME_SUBMITTED")
        with patch("apps.wecom.notification_services.WeComClient.send_text_notice") as send:
            result = process_delivery(delivery)
        send.assert_not_called()
        self.assertEqual((result.status, result.error_code), ("FAILED", "RECIPIENT_NOT_ELIGIBLE"))

    def test_two_real_submissions_only_commit_one_event(self):
        from apps.workshop_reporting.tests.test_workshop_reporting_api import WorkshopReportingApiTests
        fixture = WorkshopReportingApiTests()
        with transaction.atomic():
            fixture.setUp()
        member, role = receiver("U07_CONCURRENT_FACTORY", "workshop_reporting.approve_wagescheme")
        create_rule("WAGE_SCHEME_SUBMITTED", fixture.employee, [role.role_code])
        draft = fixture.client.post("/api/v1/workshop-reporting/wage-schemes/", fixture.scheme_payload(), format="json")
        self.assertEqual(draft.status_code, 201, draft.data)
        barrier = Barrier(2)

        def submit():
            try:
                user = get_user_model().objects.get(pk=fixture.user.pk)
                client = APIClient()
                client.force_authenticate(user)
                barrier.wait(timeout=30)
                return client.post(f"/api/v1/workshop-reporting/wage-schemes/{draft.data['data']['id']}/submit/",
                    {}, format="json", HTTP_IF_MATCH=draft["ETag"]).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertCountEqual(results, [200, 412])
        event = NotificationEvent.objects.get(event_code="WAGE_SCHEME_SUBMITTED")
        self.assertEqual(event.recipients.get().employee_id, member.pk)
        self.assertEqual(NotificationDelivery.objects.count(), 2)
