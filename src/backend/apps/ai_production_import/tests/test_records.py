import copy
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch, sentinel

from django.http import Http404
from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.ai_production_import.errors import AiProviderRequestFailed
from apps.ai_production_import.models import AiImportState
from apps.ai_production_import.serializers import RecordListQuerySerializer, ReviewDraftSerializer
from apps.ai_production_import.services import delete_record, remap_record, save_review, snapshot
from apps.ai_production_import.tests.test_preview_contract import import_record
from apps.ai_production_import.views import AiProductionImportViewSet
from apps.ai_production_import.writing import _normalize_line, _normalize_sections
from apps.boms.api.serializers import BomUpdateInputSerializer, FIXED_BOM_SECTIONS
from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired, etag_for_instance
from apps.core.api.exceptions import Conflict


NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def record_fixture(*, ready=True):
    record = import_record(result={"task": {"task_number": "HT1"}, "products": [], "boms": [], "issues": []} if ready else {})
    record.id = record.pk
    record.updated_at = NOW
    record.delete = Mock()
    return record


def draft_fixture():
    return {"task_payload": {"task_number": "HT1", "order_date": ""}, "bom_plans": [{"product_key": "P1", "sections": []}]}


def request_fixture(record, *, headers=None, data=None):
    return SimpleNamespace(employee=sentinel.employee, headers={"If-Match": etag_for_instance(record)} if headers is None else headers,
                           data=draft_fixture() if data is None else data)


@contextmanager
def locked_record(record):
    with patch("apps.ai_production_import.services.transaction.atomic", return_value=nullcontext()), \
         patch("apps.ai_production_import.services.AiProductionImport.objects.select_for_update", return_value=sentinel.locked_queryset), \
         patch("apps.ai_production_import.services.get_object_or_404", return_value=record) as lookup:
        yield lookup


class ReviewDraftValidationTests(SimpleTestCase):
    def test_allows_partial_business_form_and_pending_bom_without_creating_anything(self):
        draft = draft_fixture()
        serializer = ReviewDraftSerializer(data=draft)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, draft)
        serializer = ReviewDraftSerializer(data={"task_payload": None, "bom_plans": None})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejects_invalid_shapes_missing_sections_and_too_many_boms(self):
        for body in ({}, {"task_payload": []}, {"task_payload": "raw", "bom_plans": []},
                     {"task_payload": {}, "bom_plans": {}}, {"task_payload": {}, "bom_plans": ["raw"]},
                     {"task_payload": {}, "bom_plans": [{}] * 101}):
            with self.subTest(body=str(body)[:100]):
                self.assertFalse(ReviewDraftSerializer(data=body).is_valid())

    def test_size_limit_counts_utf8_bytes(self):
        normal = ReviewDraftSerializer(data={"task_payload": {"notes": "中" * 400_000}, "bom_plans": []})
        self.assertTrue(normal.is_valid(), normal.errors)
        oversized = ReviewDraftSerializer(data={"task_payload": {"notes": "中" * 700_000}, "bom_plans": []})
        self.assertFalse(oversized.is_valid())
        self.assertIn("non_field_errors", oversized.errors)

    def test_readonly_record_fields_cannot_be_overwritten_through_draft(self):
        serializer = ReviewDraftSerializer(data={**draft_fixture(), "result": {"tampered": True},
                                               "source": {"sheets": []}, "owner": "other-person", "task_id": str(uuid.uuid4())})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(set(serializer.validated_data), {"task_payload", "bom_plans"})

    def test_list_pagination_defaults_and_bounds(self):
        defaults = RecordListQuerySerializer(data={})
        self.assertTrue(defaults.is_valid())
        self.assertEqual(defaults.validated_data, {"limit": 20, "offset": 0})
        for values in ({"limit": 0}, {"limit": 101}, {"limit": "x"}, {"offset": -1}, {"offset": "x"}):
            with self.subTest(values=values):
                self.assertFalse(RecordListQuerySerializer(data=values).is_valid())
        upper = RecordListQuerySerializer(data={"limit": 100, "offset": 10})
        self.assertTrue(upper.is_valid(), upper.errors)


class RecordServiceTests(SimpleTestCase):
    def test_save_is_owner_scoped_locked_and_preserves_original_cells_result_and_hash(self):
        record = record_fixture()
        source = copy.deepcopy(record.source)
        result = copy.deepcopy(record.result)
        original_hash = record.sha256
        draft = draft_fixture()
        with locked_record(record) as lookup:
            returned = save_review(employee=sentinel.employee, record_id=record.pk, draft=draft, request=request_fixture(record))
        lookup.assert_called_once_with(sentinel.locked_queryset, owner=sentinel.employee, pk=record.pk)
        self.assertIs(returned, record)
        self.assertEqual(record.source, {**source, "review_draft": draft})
        self.assertEqual(record.result, result)
        self.assertEqual(record.sha256, original_hash)
        self.assertEqual(snapshot(record)["review_draft"], draft)
        record.save.assert_called_once_with(update_fields=["source", "updated_at"])
        record.delete.assert_not_called()

    def test_save_and_delete_reject_missing_or_stale_etag_without_mutation(self):
        for operation in (save_review, delete_record):
            for headers, exception in (({}, PreconditionRequired), ({"If-Match": '"stale"'}, PreconditionFailed)):
                record = record_fixture()
                source = copy.deepcopy(record.source)
                kwargs = {"draft": draft_fixture()} if operation is save_review else {}
                with self.subTest(operation=operation.__name__, headers=headers), locked_record(record):
                    with self.assertRaises(exception):
                        operation(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record, headers=headers), **kwargs)
                self.assertEqual(record.source, source)
                record.save.assert_not_called()
                record.delete.assert_not_called()

    def test_other_owner_or_missing_record_fails_before_save_or_delete(self):
        for operation in (save_review, delete_record):
            record = record_fixture()
            kwargs = {"draft": draft_fixture()} if operation is save_review else {}
            with self.subTest(operation=operation.__name__), locked_record(record) as lookup:
                lookup.side_effect = Http404
                with self.assertRaises(Http404):
                    operation(employee=sentinel.other_employee, record_id=record.pk, request=request_fixture(record), **kwargs)
                lookup.assert_called_once_with(sentinel.locked_queryset, owner=sentinel.other_employee, pk=record.pk)
            record.save.assert_not_called()
            record.delete.assert_not_called()

    def test_cannot_save_form_before_recognition_completed(self):
        record = record_fixture(ready=False)
        with locked_record(record), self.assertRaises(Conflict):
            save_review(employee=sentinel.employee, record_id=record.pk, draft=draft_fixture(), request=request_fixture(record))
        record.save.assert_not_called()

    def test_cannot_delete_active_recognition(self):
        record = record_fixture(ready=False)
        with locked_record(record), patch("apps.ai_production_import.services.timezone.now", return_value=NOW + timedelta(minutes=1)):
            with self.assertRaises(Conflict):
                delete_record(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
        record.delete.assert_not_called()

    def test_cannot_save_or_delete_while_remapping_even_with_previous_result(self):
        for operation in (save_review, delete_record):
            record = record_fixture()
            record.source["mapping_started_at"] = NOW.isoformat()
            source = copy.deepcopy(record.source)
            kwargs = {"draft": draft_fixture()} if operation is save_review else {}
            with self.subTest(operation=operation.__name__), locked_record(record), patch("apps.ai_production_import.services.timezone.now", return_value=NOW + timedelta(seconds=20)):
                with self.assertRaises(Conflict):
                    operation(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record), **kwargs)
            self.assertEqual(record.source, source)
            record.save.assert_not_called()
            record.delete.assert_not_called()

    def test_stale_unfinished_or_failed_record_can_be_deleted(self):
        for state, elapsed in ((AiImportState.REVIEW, 22), (AiImportState.FAILED, 1)):
            record = record_fixture(ready=False)
            record.state = state
            with self.subTest(state=state), locked_record(record), patch("apps.ai_production_import.services.timezone.now", return_value=NOW + timedelta(minutes=elapsed)):
                identifier = delete_record(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
            self.assertEqual(identifier, str(record.pk))
            record.delete.assert_called_once_with()

    def test_delete_linked_record_does_not_delete_or_change_business_identifiers(self):
        record = record_fixture()
        record.state = AiImportState.BOM_PENDING
        record.task_id, record.bom_id = uuid.uuid4(), uuid.uuid4()
        record.bom_ids = [str(record.bom_id)]
        identifiers = (record.task_id, record.bom_id, list(record.bom_ids))
        with locked_record(record) as lookup:
            delete_record(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
        lookup.assert_called_once_with(sentinel.locked_queryset, owner=sentinel.employee, pk=record.pk)
        record.delete.assert_called_once_with()
        record.save.assert_not_called()
        self.assertEqual((record.task_id, record.bom_id, record.bom_ids), identifiers)


class RecordEndpointTests(SimpleTestCase):
    def test_list_queries_only_current_employee_and_slices_results(self):
        records = [record_fixture(), record_fixture(), record_fixture()]
        ordered = MagicMock()
        ordered.count.return_value = 3
        ordered.only.return_value = records
        with patch("apps.ai_production_import.views.AiProductionImport.objects.filter") as query:
            query.return_value.annotate.return_value.order_by.return_value = ordered
            response = AiProductionImportViewSet().list(SimpleNamespace(employee=sentinel.employee, query_params={"limit": "1", "offset": "1"}))
        query.assert_called_once_with(owner=sentinel.employee)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual([item["id"] for item in response.data["results"]], [str(records[1].pk)])
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotIn("result", response.data["results"][0])
        self.assertNotIn("source", response.data["results"][0])

    def test_list_reports_active_recognition_instead_of_review(self):
        record = record_fixture()
        record.is_recognizing = True
        ordered = MagicMock()
        ordered.count.return_value = 1
        ordered.only.return_value = [record]
        with patch("apps.ai_production_import.views.AiProductionImport.objects.filter") as query:
            query.return_value.annotate.return_value.order_by.return_value = ordered
            response = AiProductionImportViewSet().list(SimpleNamespace(employee=sentinel.employee, query_params={}))
        self.assertEqual(response.data["results"][0]["state"], "RECOGNIZING")

    def test_bad_list_page_fails_before_query(self):
        with patch("apps.ai_production_import.views.AiProductionImport.objects.filter") as query:
            with self.assertRaises(ValidationError):
                AiProductionImportViewSet().list(SimpleNamespace(employee=sentinel.employee, query_params={"limit": "101"}))
        query.assert_not_called()

    def test_patch_validates_draft_and_returns_new_version_and_saved_form(self):
        record = record_fixture()
        draft = draft_fixture()
        record.source["review_draft"] = draft
        request = request_fixture(record, data=draft)
        with patch("apps.ai_production_import.views.save_review", return_value=record) as save:
            response = AiProductionImportViewSet().partial_update(request, pk=str(record.pk))
        save.assert_called_once_with(employee=sentinel.employee, record_id=str(record.pk), draft=draft, request=request)
        self.assertEqual(response.data["data"]["review_draft"], draft)
        self.assertEqual(response["ETag"], etag_for_instance(record))
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_patch_rejects_invalid_body_before_service(self):
        with patch("apps.ai_production_import.views.save_review") as save:
            with self.assertRaises(ValidationError):
                AiProductionImportViewSet().partial_update(SimpleNamespace(employee=sentinel.employee, data={"task_payload": []}), pk=str(uuid.uuid4()))
        save.assert_not_called()

    def test_delete_delegates_owner_and_version_check_then_returns_no_content(self):
        record = record_fixture()
        request = request_fixture(record)
        with patch("apps.ai_production_import.views.delete_record") as delete:
            response = AiProductionImportViewSet().destroy(request, pk=str(record.pk))
        delete.assert_called_once_with(employee=sentinel.employee, record_id=str(record.pk), request=request)
        self.assertEqual(response.status_code, 204)
        self.assertIsNone(response.data)

    def test_actions_still_require_active_import_permission(self):
        request = SimpleNamespace(user=sentinel.user)
        with patch("rest_framework.viewsets.GenericViewSet.initial"), \
             patch("apps.ai_production_import.views.require_actor", side_effect=PermissionDenied) as require_actor:
            with self.assertRaises(PermissionDenied):
                AiProductionImportViewSet().initial(request)
        require_actor.assert_called_once_with(request)


class RemapRecordTests(SimpleTestCase):
    def test_initial_recognition_cannot_start_a_parallel_remap(self):
        record = record_fixture(ready=False)
        original_source = copy.deepcopy(record.source)
        with locked_record(record), \
             patch("apps.ai_production_import.services.timezone.now", return_value=NOW + timedelta(seconds=20)), \
             patch("apps.ai_production_import.services._credentials") as credentials, \
             patch("apps.ai_production_import.services.recognize") as recognize:
            with self.assertRaises(Conflict):
                remap_record(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
        self.assertEqual(record.source, original_source)
        self.assertEqual(record.result, {})
        record.save.assert_not_called()
        credentials.assert_not_called()
        recognize.assert_not_called()

    def test_remap_preserves_old_result_and_review_until_complete(self):
        record = record_fixture()
        record.source["review_draft"] = draft_fixture()
        old_source, old_result, old_model = copy.deepcopy(record.source), copy.deepcopy(record.result), record.model
        new_result = {"task": {"task_number": "HT1"}, "products": [], "boms": [], "issues": [{"message": "new review"}]}

        def recognize_during_mapping(**kwargs):
            self.assertEqual(record.result, old_result)
            self.assertEqual(record.source["review_draft"], old_source["review_draft"])
            self.assertEqual(kwargs["controlled"]["source"]["sheets"], old_source["sheets"])
            self.assertIn("mapping_started_at", record.source)
            return new_result, "saved-model"

        with patch("apps.ai_production_import.services.transaction.atomic", return_value=nullcontext()), \
             patch("apps.ai_production_import.services.get_object_or_404", return_value=record), \
             patch("apps.ai_production_import.services.AiProductionImport.objects.select_for_update") as locked, \
             patch("apps.ai_production_import.services._credentials", return_value={"api_key": "test"}), \
             patch("apps.ai_production_import.services.recognize", side_effect=recognize_during_mapping), \
             patch("apps.ai_production_import.services._resolve_erp_matches", side_effect=lambda **kwargs: kwargs["result"]) as assistant:
            locked.return_value.get.return_value = record
            returned = remap_record(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
        self.assertIs(returned, record)
        self.assertIs(assistant.call_args.kwargs["result"], new_result)
        self.assertIs(assistant.call_args.kwargs["request"].employee, sentinel.employee)
        self.assertEqual(record.result, new_result)
        self.assertEqual(record.source["sheets"], old_source["sheets"])
        self.assertEqual(record.source["previous_recognition"], {"result": old_result, "review_draft": old_source["review_draft"],
                                                                "task_states": {}, "active_task_key": "main", "model": old_model})
        self.assertNotIn("mapping_started_at", record.source)
        self.assertNotIn("review_draft", record.source)

    def test_failed_remap_keeps_original_result_review_and_model(self):
        record = record_fixture()
        record.source["review_draft"] = draft_fixture()
        source, result, model = copy.deepcopy(record.source), copy.deepcopy(record.result), record.model
        with patch("apps.ai_production_import.services.transaction.atomic", return_value=nullcontext()), \
             patch("apps.ai_production_import.services.get_object_or_404", return_value=record), \
             patch("apps.ai_production_import.services.AiProductionImport.objects.select_for_update") as locked, \
             patch("apps.ai_production_import.services._credentials", return_value={"api_key": "test"}), \
             patch("apps.ai_production_import.services.recognize", side_effect=AiProviderRequestFailed("OPENAI_TIMEOUT")):
            locked.return_value.get.return_value = record
            with self.assertRaises(AiProviderRequestFailed):
                remap_record(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
        self.assertEqual(record.source, source)
        self.assertEqual(record.result, result)
        self.assertEqual(record.model, model)

    def test_failed_erp_lookup_keeps_existing_review_and_clears_mapping_flag(self):
        record = record_fixture()
        record.source["review_draft"] = draft_fixture()
        source, result, model = copy.deepcopy(record.source), copy.deepcopy(record.result), record.model
        with patch("apps.ai_production_import.services.transaction.atomic", return_value=nullcontext()), \
             patch("apps.ai_production_import.services.get_object_or_404", return_value=record), \
             patch("apps.ai_production_import.services.AiProductionImport.objects.select_for_update") as locked, \
             patch("apps.ai_production_import.services._credentials", return_value={"api_key": "test"}), \
             patch("apps.ai_production_import.services.recognize", return_value=({"boms": []}, "new-model")), \
             patch("apps.ai_production_import.services._resolve_erp_matches", side_effect=AiProviderRequestFailed("ERP_ASSISTANT_LOOKUP_LIMIT")):
            locked.return_value.get.return_value = record
            with self.assertRaises(AiProviderRequestFailed):
                remap_record(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
        self.assertEqual(record.source, source)
        self.assertEqual(record.result, result)
        self.assertEqual(record.model, model)

    def test_linked_or_already_remapping_record_cannot_start_api_request(self):
        for linked in (True, False):
            record = record_fixture()
            if linked:
                record.task_id = uuid.uuid4()
            else:
                record.source["mapping_started_at"] = NOW.isoformat()
            with self.subTest(linked=linked), locked_record(record), \
                 patch("apps.ai_production_import.services.timezone.now", return_value=NOW + timedelta(seconds=20)), \
                 patch("apps.ai_production_import.services.recognize") as recognize:
                with self.assertRaises(Conflict):
                    remap_record(employee=sentinel.employee, record_id=record.pk, request=request_fixture(record))
            recognize.assert_not_called()
            record.save.assert_not_called()


class BomQuantityBoundaryTests(SimpleTestCase):
    def test_new_section_ids_are_omitted_and_existing_id_is_preserved(self):
        for empty in (None, ""):
            with self.subTest(empty=empty):
                identifier = uuid.uuid4()
                sections = [{"title": title, "section_type": kind, "lines": [], "id": empty}
                            for title, kind in FIXED_BOM_SECTIONS]
                sections[0]["id"] = identifier
                source = copy.deepcopy(sections)
                normalized = _normalize_sections(sections)
                self.assertEqual(normalized[0]["id"], identifier)
                self.assertTrue(all("id" not in section for section in normalized[1:]))
                serializer = BomUpdateInputSerializer(data={"sections": normalized, "intent": "draft"})
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(sections, source)

    def test_ambiguous_quantity_and_legacy_total_cannot_be_written_even_when_zero(self):
        for field in ("quantity", "material_quantity"):
            for value in ("0", 0, "100", {"value": "100"}):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    _normalize_line({"part_name": "型材", field: value}, 1)

    def test_empty_legacy_quantity_is_removed_without_overwriting_explicit_consumption(self):
        source = {"part_name": "型材", "quantity": None, "material_quantity": "", "unit_consumption": "2", "length_value": "430", "line_key": "L1", "section": "管材类"}
        before = copy.deepcopy(source)
        result = _normalize_line(source, 1)
        self.assertEqual(result, {"part_name": "型材", "unit_consumption": "2", "length_value": "430"})
        self.assertEqual(source, before)

    def test_bom_line_must_be_an_object(self):
        with self.assertRaises(ValidationError):
            _normalize_line("raw row", 1)
