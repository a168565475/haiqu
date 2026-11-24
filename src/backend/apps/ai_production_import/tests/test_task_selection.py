import copy
import uuid
from unittest.mock import patch, sentinel

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.ai_production_import.models import AiImportState
from apps.ai_production_import.task_selection import (
    active_result, has_created_tasks, require_task_key, result_tasks, select_task, task_choices,
)
from apps.core.api.exceptions import Conflict

from .test_records import record_fixture, request_fixture


class TaskSelectionTests(SimpleTestCase):
    def record(self):
        record = record_fixture()
        record.result["additional_tasks"] = [
            {"task_key": "second", "task": {"task_number": {"value": "HT2"}},
             "products": [], "boms": [], "issues": []},
        ]
        return record

    def choose(self, record, key):
        with patch("apps.ai_production_import.task_selection.AiProductionImport.objects.select_for_update",
                   return_value=sentinel.queryset), \
                patch("apps.ai_production_import.task_selection.get_object_or_404", return_value=record) as get:
            result = select_task.__wrapped__(employee=sentinel.employee, record_id=record.pk,
                                            task_key=key, request=request_fixture(record))
            get.assert_called_once_with(sentinel.queryset, owner=sentinel.employee, pk=record.pk)
        return result

    def test_old_single_result_is_main_and_does_not_require_new_input_key(self):
        record = record_fixture()
        self.assertEqual(list(result_tasks(record.result)), ["main"])
        require_task_key(record, None)
        self.assertEqual(active_result(record), record.result)

    def test_switch_keeps_independent_manual_drafts_and_created_business_references(self):
        record = self.record()
        source_before = copy.deepcopy(record.source["sheets"])
        record.source["review_draft"] = {"task_payload": {"customer_note": "人工修改第一单"}, "bom_plans": []}
        record.task_id = uuid.uuid4()
        first_id = str(record.task_id)
        record.task_number, record.state = "HT1", AiImportState.TASK_DRAFT
        self.choose(record, "second")
        self.assertIsNone(record.task_id)
        self.assertIsNone(record.source["review_draft"])
        self.assertTrue(has_created_tasks(record))
        record.source["review_draft"] = {"task_payload": {"customer_note": "人工修改第二单"}, "bom_plans": []}
        self.choose(record, "main")
        self.assertEqual(str(record.task_id), first_id)
        self.assertEqual(record.state, AiImportState.TASK_DRAFT)
        self.assertEqual(record.source["review_draft"]["task_payload"]["customer_note"], "人工修改第一单")
        self.choose(record, "second")
        self.assertEqual(record.source["review_draft"]["task_payload"]["customer_note"], "人工修改第二单")
        self.assertEqual(record.source["sheets"], source_before)
        self.assertEqual([item["task_number"] for item in task_choices(record)], ["HT1", "HT2"])

    def test_cross_task_submission_and_missing_key_are_rejected(self):
        record = self.record()
        for key in (None, "second", "not-in-file"):
            with self.subTest(key=key), self.assertRaises(Conflict):
                require_task_key(record, key)
        require_task_key(record, "main")

    def test_unknown_task_and_duplicate_result_keys_do_not_mutate_record(self):
        record = self.record()
        before = copy.deepcopy(record.source)
        with self.assertRaises(ValidationError):
            self.choose(record, "foreign-task")
        self.assertEqual(record.source, before)
        record.result["additional_tasks"][0]["task_key"] = "main"
        with self.assertRaises(ValidationError):
            result_tasks(record.result)

    def test_selection_requires_current_etag(self):
        record = self.record()
        from apps.core.api.concurrency import PreconditionRequired
        with patch("apps.ai_production_import.task_selection.AiProductionImport.objects.select_for_update"), \
                patch("apps.ai_production_import.task_selection.get_object_or_404", return_value=record), \
                self.assertRaises(PreconditionRequired):
            select_task.__wrapped__(employee=sentinel.employee, record_id=record.pk, task_key="second",
                                    request=request_fixture(record, headers={}))
