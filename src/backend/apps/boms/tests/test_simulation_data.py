from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.boms.simulation_data import (
    BOM_SIMULATION_COUNT_RANGES,
    BOM_SIMULATION_SECTION_TYPES,
    summarize_bom_simulation_sections,
)


class _RelatedList:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


def _bom_sections(*, duplicate_title=None, missing_title=None):
    sections = []
    for title, section_type in BOM_SIMULATION_SECTION_TYPES.items():
        if title == missing_title:
            continue
        count = BOM_SIMULATION_COUNT_RANGES[title][0]
        section = SimpleNamespace(
            title=title,
            section_type=section_type,
            lines=SimpleNamespace(count=lambda value=count: value),
        )
        sections.append(section)
        if title == duplicate_title:
            sections.append(section)
    return SimpleNamespace(sections=_RelatedList(sections))


class BomSimulationSummaryTests(SimpleTestCase):
    def test_accepts_exactly_one_of_each_requested_section(self):
        summary = summarize_bom_simulation_sections(
            [_bom_sections()],
            expected_bom_count=1,
        )
        self.assertTrue(summary["all_valid"])

    def test_rejects_duplicate_and_missing_section_even_when_global_count_can_balance(self):
        summary = summarize_bom_simulation_sections(
            [
                _bom_sections(duplicate_title="五金件"),
                _bom_sections(missing_title="五金件"),
            ],
            expected_bom_count=2,
        )
        self.assertFalse(summary["all_valid"])
