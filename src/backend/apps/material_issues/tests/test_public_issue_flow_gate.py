import uuid

from django.test import TestCase, override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.inventory.models import PublicStockMovement
from apps.inventory.public_bom_snapshot import build_output_identity
from apps.inventory.public_stock_transition import preview_public_stock_transition
from apps.material_issues.services import MaterialIssueConflict
from .test_public_issue_services import PublicIssueFixture


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=False)
class PublicIssueFlowGateTests(PublicIssueFixture, TestCase):
    def setUp(self):
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            super().setUp()

    def test_full_flow_creates_public_issue_without_old_trial_switch(self):
        issue = self.create()
        self.assertEqual(issue.stock_mode, "PUBLIC_V2")
        frozen = issue.lines.get().conversion_snapshot["public_bom_snapshot"]
        self.assertEqual(build_output_identity(frozen, self.coating, self.piece_unit), self.semi_identity)

    def test_changed_physical_attributes_before_issue_require_refresh(self):
        issue = self.create()
        self.bom_line.raw_values["tube_coating_color"] = "白色"
        self.bom_line.save(update_fields=["raw_values"])
        with self.assertRaises(MaterialIssueConflict) as error:
            self.submit(issue)
        self.assertEqual(error.exception.api_error_code, "SOURCE_CHANGED")

    def test_legacy_pending_cannot_consume_second_copy_of_stock(self):
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            issue = self.submit(self.create())
        before = self.balance().quantity
        self.assert_code("PUBLIC_STOCK_LEGACY_DOCUMENT_BLOCKED", lambda: self.confirm(issue))
        self.assertEqual(self.balance().quantity, before)
        issue.refresh_from_db()
        self.assertEqual(issue.status, "PENDING_REVIEW")

    def test_old_trial_pending_without_output_properties_cannot_deduct_in_full_flow(self):
        issue = self.submit(self.create())
        line = issue.lines.get()
        line.conversion_snapshot.pop("public_bom_snapshot")
        line.save(update_fields=["conversion_snapshot"])
        before = PublicStockMovement.objects.count()
        with self.assertRaises(MaterialIssueConflict) as error:
            self.confirm(issue)
        self.assertEqual(error.exception.api_error_code, "SOURCE_CHANGED")
        self.assertEqual(PublicStockMovement.objects.count(), before)
        issue.refresh_from_db()
        self.assertEqual(issue.status, "PENDING_REVIEW")

    def test_completed_public_issue_replay_survives_switch_disabled(self):
        request_id = uuid.uuid4()
        issue = self.confirm(self.submit(self.create()), request_id)
        count = PublicStockMovement.objects.count()
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            replayed = self.confirm(issue, request_id)
        self.assertEqual(replayed.pk, issue.pk)
        self.assertEqual(PublicStockMovement.objects.count(), count)

    def test_transition_report_lists_legacy_pending_without_writing_or_auto_upgrading(self):
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            issue = self.submit(self.create())
        with CaptureQueriesContext(connection) as queries:
            result = preview_public_stock_transition()
        row = next(item for item in result["documents"] if item["id"] == str(issue.pk))
        self.assertEqual(row["code"], "UNISSUED_PLAN_RECREATE")
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")) for query in queries))
        issue.refresh_from_db()
        self.assertEqual(issue.stock_mode, "LEGACY")
