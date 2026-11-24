import copy
from contextlib import contextmanager, nullcontext
from unittest.mock import patch, sentinel

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.ai_production_import.errors import AiProviderRequestFailed
from apps.ai_production_import.services import match_record_materials, recognize_upload
from apps.ai_production_import.tests.test_records import NOW, draft_fixture, record_fixture, request_fixture
from apps.ai_production_import.views import AiProductionImportViewSet
from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired
from apps.core.api.exceptions import Conflict


@contextmanager
def locked(record):
    with patch("apps.ai_production_import.services.transaction.atomic", return_value=nullcontext()), \
         patch("apps.ai_production_import.services.get_object_or_404", return_value=record) as owned, \
         patch("apps.ai_production_import.services.AiProductionImport.objects.select_for_update") as query:
        query.return_value.get.return_value = record
        yield owned


class MaterialMatchingTests(SimpleTestCase):
    def test_only_result_changes_and_every_manual_task_draft_is_preserved(self):
        record = record_fixture()
        record.source.update(review_draft=draft_fixture(), task_states={"task2": {"review_draft": draft_fixture()}}, active_task_key="main")
        source, model = copy.deepcopy(record.source), record.model
        result = {**record.result, "recognition_meta": {"erp_assistant": {"status": "completed"}}}
        request = request_fixture(record)
        with locked(record) as owned, patch("apps.ai_production_import.services._credentials", return_value={"model": "configured"}), \
             patch("apps.ai_production_import.services.recognize") as extraction, \
             patch("apps.ai_production_import.services._resolve_erp_matches", return_value=result) as assistant:
            returned = match_record_materials(employee=sentinel.employee, record_id=record.pk, request=request)
        self.assertIs(returned, record)
        self.assertEqual(owned.call_args.kwargs, {"owner": sentinel.employee, "pk": record.pk})
        self.assertIs(assistant.call_args.kwargs["request"], request)
        self.assertEqual(record.source, source)
        self.assertEqual(record.result, result)
        self.assertEqual(record.model, model)
        self.assertEqual(record.save.call_args.kwargs["update_fields"], ["source", "updated_at", "result", "error_code", "issues"])
        extraction.assert_not_called()

    def test_provider_and_internal_errors_propagate_without_losing_review(self):
        for error in (AiProviderRequestFailed("OPENAI_TIMEOUT"), RuntimeError("internal defect")):
            record = record_fixture()
            record.source["review_draft"] = draft_fixture()
            source, result = copy.deepcopy(record.source), copy.deepcopy(record.result)
            with self.subTest(error=type(error).__name__), locked(record), \
                 patch("apps.ai_production_import.services._credentials", return_value={}), \
                 patch("apps.ai_production_import.services._resolve_erp_matches", side_effect=error):
                with self.assertRaises(type(error)):
                    match_record_materials(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
            self.assertEqual(record.source, source)
            self.assertEqual(record.result, result)
            self.assertEqual(record.save.call_args.kwargs["update_fields"], ["source", "updated_at"])

    def test_missing_or_stale_version_fails_before_api_or_record_mutation(self):
        for headers, exception in (({}, PreconditionRequired), ({"If-Match": '"stale"'}, PreconditionFailed)):
            record = record_fixture()
            with self.subTest(headers=headers), locked(record), patch("apps.ai_production_import.services._credentials") as credentials:
                with self.assertRaises(exception):
                    match_record_materials(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record, headers=headers))
            credentials.assert_not_called()
            record.save.assert_not_called()

    def test_pending_or_created_or_empty_record_fails_before_api(self):
        for kind in ("pending", "created", "empty"):
            record = record_fixture(ready=kind != "empty")
            if kind == "pending": record.source["mapping_started_at"] = NOW.isoformat()
            if kind == "created": record.task_id = "existing-task"
            with self.subTest(kind=kind), locked(record), patch("apps.ai_production_import.services.timezone.now", return_value=NOW), \
                 patch("apps.ai_production_import.services._credentials") as credentials:
                with self.assertRaises(Conflict):
                    match_record_materials(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
            credentials.assert_not_called()
            record.save.assert_not_called()

    def test_newer_mapping_is_not_overwritten_or_unlocked(self):
        record = record_fixture()
        before = copy.deepcopy(record.result)
        def concurrent_mapping(**kwargs):
            record.source["mapping_started_at"] = "another-run"
            return {"recognition_meta": {"erp_assistant": {"status": "completed"}}}
        with locked(record), patch("apps.ai_production_import.services._credentials", return_value={}), \
             patch("apps.ai_production_import.services._resolve_erp_matches", side_effect=concurrent_mapping):
            with self.assertRaises(Conflict):
                match_record_materials(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
        self.assertEqual(record.source["mapping_started_at"], "another-run")
        self.assertEqual(record.result, before)
        self.assertEqual(record.save.call_count, 1)

    def test_endpoint_returns_record_and_rejects_extra_parameters(self):
        record = record_fixture()
        request = request_fixture(record, data={})
        with patch("apps.ai_production_import.views.match_record_materials", return_value=record) as service:
            response = AiProductionImportViewSet().match_materials(request, pk=str(record.pk))
        service.assert_called_once_with(employee=sentinel.employee, record_id=str(record.pk), request=request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertTrue(response["ETag"])
        with patch("apps.ai_production_import.views.match_record_materials") as service:
            with self.assertRaises(ValidationError):
                AiProductionImportViewSet().match_materials(request_fixture(record, data={"sql": "anything"}), pk=str(record.pk))
        service.assert_not_called()

    def test_route_is_registered(self):
        from django.urls import resolve
        record = record_fixture()
        route = resolve(f"/api/v1/ai-production-imports/{record.pk}/match-materials/")
        self.assertEqual(route.func.actions["post"], "match_materials")

    def test_upload_keeps_completed_extraction_when_erp_lookup_fails(self):
        record = record_fixture(ready=False)
        extracted = {"task": {"task_number": "HT1"}, "products": [], "boms": [], "issues": []}
        controlled = {"source": copy.deepcopy(record.source), "original_name": "real-layout.xlsx", "sha256": "a" * 64, "size_bytes": 100}
        with locked(record), patch("apps.ai_production_import.services.build_controlled_json", return_value=controlled), \
             patch("apps.ai_production_import.services.AiProductionImport.objects.filter") as existing, \
             patch("apps.ai_production_import.services.AiProductionImport.objects.create", return_value=record), \
             patch("apps.ai_production_import.services.confirmed_source_rules", return_value=[]), \
             patch("apps.ai_production_import.services._credentials", return_value={}), \
             patch("apps.ai_production_import.services.recognize", return_value=(extracted, "configured-model")), \
             patch("apps.ai_production_import.services._resolve_erp_matches", side_effect=AiProviderRequestFailed("OPENAI_TIMEOUT")):
            existing.return_value.first.return_value = None
            with self.assertRaises(AiProviderRequestFailed) as caught:
                recognize_upload(employee=sentinel.employee, uploaded_file=sentinel.file, request=sentinel.request)
        self.assertEqual(caught.exception.record_id, str(record.pk))
        self.assertEqual(record.result["task"], extracted["task"])
        self.assertEqual(record.result["recognition_meta"]["erp_assistant"], {"status": "failed", "error_code": "OPENAI_TIMEOUT"})
        self.assertEqual(record.model, "configured-model")
        self.assertEqual(record.state, "REVIEW")
        self.assertNotIn("mapping_started_at", record.source)
        self.assertEqual(record.source, controlled["source"])
        self.assertEqual(record.issues[-1]["issue_key"], "erp_assistant")

    def test_successful_material_retry_clears_previous_lookup_error(self):
        record = record_fixture()
        record.error_code = "OPENAI_TIMEOUT"
        record.issues = [{"issue_key": "erp_assistant", "message": "prior lookup failed"}]
        result = {**record.result, "issues": [{"issue_key": "source", "message": "source conflict retained"}]}
        with locked(record), patch("apps.ai_production_import.services._credentials", return_value={}), \
             patch("apps.ai_production_import.services._resolve_erp_matches", return_value=result):
            match_record_materials(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
        self.assertEqual(record.error_code, "")
        self.assertEqual(record.issues, result["issues"])

    def test_upload_error_exposes_only_saved_record_id_for_reopening(self):
        from types import SimpleNamespace
        failure = AiProviderRequestFailed("OPENAI_TIMEOUT")
        failure.record_id = str(record_fixture().pk)
        with patch("apps.ai_production_import.views.UploadSerializer") as serializer, \
             patch("apps.ai_production_import.views.recognize_upload", side_effect=failure):
            serializer.return_value.validated_data = {"file": sentinel.file, "client_request_id": None}
            with self.assertRaises(ValidationError) as caught:
                AiProductionImportViewSet().create(SimpleNamespace(employee=sentinel.employee, data={}))
        self.assertEqual(str(caught.exception.detail["record_id"]), failure.record_id)
        self.assertEqual(set(caught.exception.detail), {"detail", "code", "record_id"})
