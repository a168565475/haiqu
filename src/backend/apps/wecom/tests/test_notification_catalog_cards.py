from django.test import SimpleTestCase

from apps.wecom.notification_catalog import (
    EVENTS, MULTILINE_DEFAULT_BODIES, VARIABLE, VARIABLE_DEFINITIONS,
    all_events, current_body_template, get_event,
)


class NotificationCardCatalogTests(SimpleTestCase):
    def test_all_default_templates_preserve_their_existing_variables(self):
        self.assertEqual(len(EVENTS), 35)
        self.assertEqual(set(MULTILINE_DEFAULT_BODIES), set(EVENTS))
        for event in all_events():
            with self.subTest(event=event["event_code"]):
                previous = set(VARIABLE.findall(event["legacy_default_body"]))
                current = set(VARIABLE.findall(event["default_body"]))
                self.assertEqual(current, previous)
                self.assertEqual(current, set(event["required_variables"]))

    def test_default_examples_fit_card_rows_without_truncation(self):
        examples = {name: definition[1] for name, definition in VARIABLE_DEFINITIONS.items()}
        for event in all_events():
            with self.subTest(event=event["event_code"]):
                body = VARIABLE.sub(lambda match: examples[match.group(1)], event["default_body"])
                self.assertLessEqual(len(body), 160)
                rows = body.splitlines()
                self.assertGreaterEqual(len(rows), 2)
                self.assertLessEqual(len(rows), 6)
                for row in rows:
                    label, separator, value = row.partition("：")
                    self.assertEqual(separator, "：")
                    self.assertTrue(label)
                    self.assertLessEqual(len(label), 5)
                    self.assertTrue(value)
                    self.assertLessEqual(len(value), 30)

    def test_only_exact_legacy_defaults_are_converted(self):
        for event in all_events():
            with self.subTest(event=event["event_code"]):
                code = event["event_code"]
                legacy = event["legacy_default_body"]
                self.assertEqual(current_body_template(code, legacy), event["default_body"])
                for custom in (legacy + " ", legacy + "\n备注：请及时处理", "自定义：{{document_no}}"):
                    self.assertEqual(current_body_template(code, custom), custom)
                self.assertEqual(current_body_template(code, event["default_body"]), event["default_body"])

    def test_operational_notes_and_deleted_record_warning_remain_visible(self):
        notes = {
            "MATERIAL_RECEIPT_RECORDED": ("等待检验",),
            "SEMI_FINISHED_RECEIPT_SUBMITTED": ("等待仓管确认",),
            "ASSEMBLY_FINISHED_RECEIPT_SUBMITTED": ("等待仓管确认",),
            "INTERNAL_SEMI_RECEIPT_CONFIRMED": ("请核对现有入库记录",),
            "ASSEMBLY_FINISHED_RECEIPT_CONFIRMED": ("请核对成品入库记录",),
            "WORK_REPORT_DELETED": ("{{reason_summary}}", "原记录已删除，本消息仅供知悉"),
            "SAMPLE_MATERIALS_AVAILABLE": ("现有可供及到货明细", "不代表全部齐料或已经发料"),
            "SAMPLE_MATERIAL_ISSUED": ("按本岗位权限维护参数或报工", "未到货采购仍按原流程处理"),
            "SAMPLE_PRODUCTION_READY": ("无需用料", "按本岗位权限维护参数或报工"),
            "SAMPLE_COMPLETED": ("参数和两工序生产", "按剩余可入库数量办理样品入库", "厂长"),
        }
        for event_code, expected in notes.items():
            with self.subTest(event=event_code):
                body = get_event(event_code)["default_body"]
                for note in expected:
                    self.assertIn(note, body)

    def test_unknown_event_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "未登记的通知事件"):
            current_body_template("UNKNOWN_EVENT", "正文")
