from copy import deepcopy
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings

from apps.inventory.public_bom_snapshot import build_output_identity, freeze_bom_line
from apps.inventory.public_stock_mode import new_stock_mode, public_issues_enabled, require_document_stock_mode
from apps.inventory.stock_services import InventoryStockValidationError
from . import test_public_stock_identity as identity_fixtures


class FrozenBomOutputTests(SimpleTestCase):
    def setUp(self):
        self.fixture = identity_fixtures.PublicStockIdentityTests()
        self.fixture.setUp()

    def test_pipe_output_uses_frozen_finished_color_and_cutting_size(self):
        line = self.fixture.pipe_line()
        frozen = freeze_bom_line(line)
        expected = self.fixture.semi(line)
        line.raw_values["tube_coating_color"] = "白色"
        line.cutting_length_mm = 999
        self.assertEqual(build_output_identity(frozen, self.fixture.coating, self.fixture.piece_unit), expected)
        self.assertNotEqual(self.fixture.semi(line), expected)

    def test_cutting_output_freezes_source_fabric_and_returns_sets(self):
        line = self.fixture.cutting_line()
        expected = self.fixture.cutting_semi(line)
        frozen = freeze_bom_line(line)
        line.fabric_source_line.raw_values["fabric_color_code"] = "另一色号"
        actual = build_output_identity(frozen, self.fixture.cutting, self.fixture.set_unit)
        self.assertEqual(actual, expected)
        self.assertEqual(actual["identity_snapshot"]["unit_name"], "套")

    def test_missing_historical_source_or_wrong_version_is_not_guessed(self):
        frozen = freeze_bom_line(self.fixture.pipe_line())
        for invalid in (None, {}, {**frozen, "schema_version": 2}, {**frozen, "schema_version": True}):
            with self.subTest(invalid=invalid), self.assertRaises(InventoryStockValidationError) as error:
                build_output_identity(invalid, self.fixture.coating, self.fixture.piece_unit)
            self.assertEqual(error.exception.api_error_code, "PUBLIC_STOCK_FROZEN_BOM_REQUIRED")

    def test_raw_stage_can_freeze_incomplete_properties_but_handoff_cannot_guess_color(self):
        line = self.fixture.pipe_line()
        line.raw_values["tube_coating_color"] = ""
        frozen = freeze_bom_line(line)
        with self.assertRaises(InventoryStockValidationError):
            build_output_identity(frozen, self.fixture.coating, self.fixture.piece_unit)

    def test_cross_bom_fabric_and_raw_unit_are_rejected(self):
        frozen = freeze_bom_line(self.fixture.cutting_line())
        wrong = deepcopy(frozen)
        wrong["fabric_source_line"]["section"]["bom_id"] = "different-bom"
        with self.assertRaises(InventoryStockValidationError):
            build_output_identity(wrong, self.fixture.cutting, self.fixture.set_unit)
        with self.assertRaises(InventoryStockValidationError):
            build_output_identity(freeze_bom_line(self.fixture.pipe_line()), self.fixture.coating, self.fixture.bar_unit)


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=False, PUBLIC_STOCK_ISSUES_ENABLED=False)
class PublicStockModeTests(TestCase):
    def test_legacy_mode_remains_default(self):
        self.assertEqual(new_stock_mode(), "LEGACY")
        self.assertFalse(public_issues_enabled())
        self.assertFalse(require_document_stock_mode(SimpleNamespace(stock_mode="LEGACY")))

    def test_public_document_cannot_fall_back_when_switch_is_disabled(self):
        with self.assertRaises(InventoryStockValidationError) as error:
            require_document_stock_mode(SimpleNamespace(stock_mode="PUBLIC_V2"))
        self.assertEqual(error.exception.api_error_code, "PUBLIC_STOCK_FLOW_DISABLED")

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_full_switch_enables_new_issues_and_blocks_legacy_stock_write(self):
        self.assertEqual(new_stock_mode(), "PUBLIC_V2")
        self.assertTrue(public_issues_enabled())
        self.assertTrue(require_document_stock_mode(SimpleNamespace(stock_mode="PUBLIC_V2")))
        with self.assertRaises(InventoryStockValidationError) as error:
            require_document_stock_mode(SimpleNamespace(stock_mode="LEGACY"), allow_issue_trial=True)
        self.assertEqual(error.exception.api_error_code, "PUBLIC_STOCK_LEGACY_DOCUMENT_BLOCKED")

    @override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
    def test_issue_trial_is_not_a_general_outsourcing_or_receipt_bypass(self):
        public = SimpleNamespace(stock_mode="PUBLIC_V2")
        self.assertEqual(new_stock_mode(), "LEGACY")
        self.assertTrue(require_document_stock_mode(public, allow_issue_trial=True))
        with self.assertRaises(InventoryStockValidationError):
            require_document_stock_mode(public)

    def test_unknown_mode_never_defaults_to_legacy(self):
        with self.assertRaises(InventoryStockValidationError) as error:
            require_document_stock_mode(SimpleNamespace(stock_mode="UNKNOWN"))
        self.assertEqual(error.exception.api_error_code, "PUBLIC_STOCK_MODE_INVALID")
