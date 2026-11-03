from unittest.mock import patch

from django.test import SimpleTestCase

from apps.material_catalog.selectors import _matches_pinyin, _pinyin_search_term, catalog_list


class CatalogPinyinSearchTests(SimpleTestCase):
    databases = set()

    def test_full_pinyin_initials_and_separators_reuse_existing_rules(self):
        for name, query in (
            ("U型支撑管", "uxingzhichengguan"), ("U型支撑管", "UXZCG"),
            ("U型支撑管", "U-X-Z-C-G"), ("U型支撑管", "u xing zhi cheng guan"),
            ("扶手长管", "fushouchangguan"), ("扶手长管", "FSCG"),
            ("中交叉-长管", "zhong-jiao-cha-chang-guan"), ("中交叉-长管", "ZJCCG"),
        ):
            with self.subTest(name=name, query=query):
                self.assertTrue(_matches_pinyin(name, _pinyin_search_term(query)))
        self.assertFalse(_matches_pinyin("U型支撑管", _pinyin_search_term("banzi")))

    def test_non_latin_search_does_not_generate_pinyin(self):
        for query in ("支撑管", "U型", "123", "", " -- "):
            with self.subTest(query=query):
                self.assertEqual(_pinyin_search_term(query), "")
        with patch("apps.material_catalog.selectors.build_pinyin_search") as build:
            self.assertFalse(_matches_pinyin("U型支撑管", ""))
        build.assert_not_called()

    def test_chinese_query_keeps_database_name_filter(self):
        with patch("apps.material_catalog.selectors.MaterialCatalog.objects.filter") as active:
            category = active.return_value.filter.return_value
            catalog_list(category="TUBE", query="支撑管")
            active.assert_called_once_with(archived_at__isnull=True)
            active.return_value.filter.assert_called_once_with(category_key="TUBE")
            category.filter.assert_called_once_with(name__icontains="支撑管")
            category.values_list.assert_not_called()
