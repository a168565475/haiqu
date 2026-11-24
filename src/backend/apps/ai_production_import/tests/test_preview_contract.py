import copy
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch, sentinel

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.ai_production_import.errors import AiProviderRequestFailed
from apps.ai_production_import.models import AiImportState
from apps.ai_production_import.services import snapshot
from apps.ai_production_import.views import AiProductionImportViewSet
from apps.ai_production_import.writing import create_task_draft
from apps.ai_openai_config.views import OpenAIKeyConfigViewSet
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.exceptions import Conflict, api_exception_handler


def import_record(*, result=None):
    return SimpleNamespace(
        pk=uuid.uuid4(), state=AiImportState.REVIEW, result={} if result is None else result,
        original_name="production.xlsx", sha256="a" * 64, size_bytes=100,
        model="gpt-6-astra", issues=[], error_code="", task_id=None, task_number="", bom_id=None, bom_ids=[],
        created_at=datetime(2026, 11, 12, tzinfo=timezone.utc),
        updated_at=datetime(2026, 11, 12, tzinfo=timezone.utc), save=Mock(),
        source={
            "source_index": {
                "src_cell": {"kind": "cell", "sheet_part": "xl/worksheets/sheet1.xml", "ref": "A1"},
                "src_comment": {"kind": "comment", "sheet_part": "xl/worksheets/sheet1.xml", "ref": "A1"},
            },
            "sheets": [{
                "name": "生产任务", "state": "visible", "dimension": "A1", "pictures": [],
                "cells": [{"ref": "A1", "text": "生产任务原文", "source_id": "src_cell"}],
                "comments": [{"ref": "A1", "text": "人工核对批注", "source_id": "src_comment"}],
            }],
        },
    )


class PreviewContractTests(SimpleTestCase):
    def test_config_detail_returns_version_for_model_only_edits_without_secret(self):
        identifier = uuid.uuid4()
        config = SimpleNamespace(
            pk=identifier, id=identifier, label="生产导入", provider="openai", model="gpt-6-astra",
            base_url="", key_ciphertext="private-ciphertext", key_last4="test", key_fingerprint="fingerprint",
            created_at=datetime(2026, 11, 12, tzinfo=timezone.utc),
            updated_at=datetime(2026, 11, 12, tzinfo=timezone.utc),
        )
        view = OpenAIKeyConfigViewSet()
        with patch.object(view, "get_object", return_value=config):
            response = view.retrieve(sentinel.request)
        self.assertEqual(response["ETag"], etag_for_instance(config))
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertTrue(response.data["data"]["key_configured"])
        self.assertNotIn("key_ciphertext", response.data["data"])
        self.assertNotIn("api_key", response.data["data"])

    def test_empty_result_stays_recognizing_and_source_text_does_not_mutate_record(self):
        record = import_record()
        original_source = copy.deepcopy(record.source)

        response = snapshot(record)

        self.assertEqual(response["state"], "RECOGNIZING")
        self.assertEqual(response["progress"]["stage"], "recognizing")
        self.assertIsNone(response["progress"]["percent"])
        self.assertEqual(response["sources"]["src_cell"]["text"], "生产任务原文")
        self.assertEqual(response["sources"]["src_comment"]["text"], "人工核对批注")
        self.assertEqual(response["sources"]["src_cell"]["ref"], "A1")
        self.assertEqual(response["sources"]["src_cell"]["sheet"], "生产任务")
        self.assertEqual(record.source, original_source)
        self.assertEqual(record.state, AiImportState.REVIEW)
        record.save.assert_not_called()

    def test_review_with_result_is_completed(self):
        result = {"task": {"task_number": {"value": "HT26001"}}, "products": [], "boms": [], "issues": []}
        response = snapshot(import_record(result=result))

        self.assertEqual(response["state"], AiImportState.REVIEW)
        self.assertEqual(response["progress"], {"stage": "completed", "percent": 100})
        self.assertEqual(response["task_draft"], result["task"])

    def test_provider_failure_returns_chinese_message_and_retains_machine_code(self):
        request = SimpleNamespace(
            data={}, employee=sentinel.employee,
            path="/api/v1/ai-production-imports/", request_id="preview-contract-test",
        )
        serializer = Mock(validated_data={"file": sentinel.file, "client_request_id": uuid.uuid4()})
        for code in ("OPENAI_TIMEOUT", "OPENAI_BAD_REQUEST"):
            with self.subTest(code=code):
                provider_error = AiProviderRequestFailed(code)
                with patch("apps.ai_production_import.views.UploadSerializer", return_value=serializer), \
                     patch("apps.ai_production_import.views.recognize_upload", side_effect=provider_error):
                    with self.assertRaises(ValidationError) as raised:
                        AiProductionImportViewSet().create(request)
                response = api_exception_handler(raised.exception, {"request": request})

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["error"]["message"], provider_error.message)
                self.assertNotEqual(response.data["error"]["message"], code)
                self.assertEqual(response.data["error"]["field_errors"]["code"], code)

    def test_empty_recognition_result_cannot_reach_business_creation(self):
        record = import_record()
        with patch("apps.ai_production_import.writing.transaction.atomic", return_value=nullcontext()), \
             patch("apps.ai_production_import.writing._lock_record", return_value=record), \
             patch("apps.ai_production_import.writing._require_permission"), \
             patch("apps.ai_production_import.writing.require_matching_etag"), \
             patch("apps.ai_production_import.writing.AiProductionTaskWriteSerializer") as serializer, \
             patch("apps.ai_production_import.writing.create_production_task") as create_task:
            with self.assertRaises(Conflict) as raised:
                create_task_draft(
                    employee=sentinel.employee, record_id=record.pk,
                    payload={"task_number": "HT26001"}, request=sentinel.request,
                )

        self.assertEqual(raised.exception.status_code, 409)
        serializer.assert_not_called()
        create_task.assert_not_called()
        record.save.assert_not_called()
