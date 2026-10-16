import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


RUNNER_PATH = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("qa_runner", RUNNER_PATH)
qa_runner = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(qa_runner)


class RunnerContractTests(unittest.TestCase):
    def run_structured_result(self, payload, returncode=0, *, structured=True):
        entry = dict(qa_runner.select_entries(qa_runner.load_manifest(), "material_catalog")[0])
        if structured:
            entry["result_protocol"] = "json-summary-v1"
        else:
            entry.pop("result_protocol", None)
        output = payload if isinstance(payload, str) else json.dumps(payload)
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            qa_runner, "preflight_entry", return_value=(None, Path("node"))
        ), patch.object(
            qa_runner.subprocess, "run", return_value=subprocess.CompletedProcess([], returncode, output, "")
        ):
            return qa_runner.run_entry(
                entry, report_dir=Path(temp_dir), run_id="contract-test", dry_run=False,
                read_only=True, allow_db_write=False, allow_real_db_write=False, timeout_override=None,
            )

    def test_structured_partial_preserves_gaps_without_counting_complete_pass(self):
        gaps = ["真实保存与删除未覆盖", "当前无喷塑样本"]
        case = self.run_structured_result({"qa_result_version": 1, "status": "PASS_WITH_GAPS", "not_covered": gaps, "cleanup": True})
        self.assertEqual(case["status"], "PASS_WITH_GAPS")
        self.assertEqual(case["coverage_gaps"], gaps)
        summary = qa_runner._summary([case])
        self.assertEqual(summary["pass"], 0)
        self.assertEqual(summary["pass_with_gaps"], 1)
        self.assertEqual(qa_runner._exit_code(summary), 5)
        markdown = qa_runner._markdown_report({"summary": summary, "cases": [case], "run_id": "test", "module": "material_catalog", "mode": "read-only", "started_at": "", "finished_at": ""})
        self.assertIn("PASS_WITH_GAPS", markdown)
        for gap in gaps:
            self.assertIn(gap, markdown)

    def test_structured_blocked_is_not_converted_to_failure(self):
        case = self.run_structured_result({"qa_result_version": 1, "status": "BLOCKED", "not_covered": [], "cleanup": True, "failure": {"message": "需要已有 Session 或真实账号"}}, returncode=1)
        self.assertEqual(case["status"], "BLOCKED")
        self.assertIn("需要已有 Session", case["reason"])
        self.assertEqual(qa_runner._exit_code(qa_runner._summary([case])), 3)

    def test_structured_invalid_or_inconsistent_results_never_become_pass(self):
        for payload, returncode in [
            ("not-json", 0),
            ({"status": "PASS", "not_covered": [], "cleanup": True}, 0),
            ({"qa_result_version": 1, "status": [], "not_covered": [], "cleanup": True}, 0),
            ({"qa_result_version": 1, "status": "PASS", "not_covered": ["遗漏写入"], "cleanup": True}, 0),
            ({"qa_result_version": 1, "status": "PASS_WITH_GAPS", "not_covered": [], "cleanup": True}, 0),
            ({"qa_result_version": 1, "status": "PASS_WITH_GAPS", "not_covered": ["遗漏写入"], "cleanup": True}, 1),
            ({"qa_result_version": 1, "status": "PASS", "not_covered": [], "cleanup": False}, 0),
        ]:
            with self.subTest(payload=payload, returncode=returncode):
                self.assertEqual(self.run_structured_result(payload, returncode)["status"], "FAIL")

    def test_legacy_entry_keeps_exit_code_behavior_without_structured_opt_in(self):
        self.assertEqual(self.run_structured_result("legacy output", structured=False)["status"], "PASS")
        self.assertEqual(self.run_structured_result("legacy output", returncode=1, structured=False)["status"], "FAIL")

    def test_material_catalog_protocol_is_explicit_and_outside_all(self):
        manifest = qa_runner.load_manifest()
        entry = qa_runner.select_entries(manifest, "material_catalog")[0]
        self.assertEqual(entry["result_protocol"], "json-summary-v1")
        self.assertNotIn(entry["id"], {item["id"] for item in qa_runner.select_entries(manifest, "all")})
        for invalid in ["unknown", []]:
            with self.subTest(invalid=invalid), self.assertRaises(qa_runner.ManifestError):
                qa_runner.validate_entry({**entry, "result_protocol": invalid})

    def test_workbench_cli_reaches_registered_readonly_preflight(self):
        with tempfile.TemporaryDirectory(prefix=".tmp-workbench-contract-", dir=Path(__file__).parent) as temp_dir, patch.object(
            qa_runner, "preflight_entry", return_value=("contract-test-no-account", None)
        ):
            exit_code = qa_runner.main(["workbench", "--read-only", "--report-dir", temp_dir])
            report_path = Path(temp_dir) / "report.json"
            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 3)
            self.assertEqual(report["cases"][0]["id"], "workbench-navigation-readonly")
            self.assertEqual(report["cases"][0]["status"], "BLOCKED")

    def test_manifest_rejects_path_outside_project_root(self):
        entry = {
            "id": "escape",
            "path": "../outside.cjs",
            "runtime": "node",
            "category": "page",
            "risk": "read-only",
            "database_target": "none",
            "browser_mode": "none",
            "account_required": False,
            "required_env": [],
            "enabled": True,
        }

        with self.assertRaises(qa_runner.ManifestError):
            qa_runner.validate_entry(entry, Path.cwd())

    def test_headless_policy_rejects_false_and_missing_explicit_true(self):
        self.assertIsNone(qa_runner.check_headless_source("chromium.launch({ headless: true })"))
        self.assertIn("false", qa_runner.check_headless_source("chromium.launch({ headless: false })"))
        self.assertIn("未明确", qa_runner.check_headless_source("chromium.launch({ executablePath })"))

    def test_select_module_only_returns_enabled_entries_in_order(self):
        manifest = {
            "version": 1,
            "modules": {
                "production": [
                    {"id": "b", "enabled": True, "order": 20},
                    {"id": "a", "enabled": True, "order": 10},
                    {"id": "off", "enabled": False, "order": 1},
                ]
            },
        }

        selected = qa_runner.select_entries(manifest, "production")
        self.assertEqual([item["id"] for item in selected], ["a", "b"])

    def test_report_writer_never_serializes_environment_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.json"
            report = qa_runner.write_json_report(
                path,
                {"environment": {"QA_PASSWORD": {"provided": True, "value": "secret"}}},
            )
            self.assertEqual(report, path)
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("secret", content)
            self.assertIn("provided", content)

    def test_child_environment_exposes_project_node_modules(self):
        child_env = qa_runner.child_environment({"QA_RUN_ID": "test-run"})
        self.assertEqual(child_env["QA_RUN_ID"], "test-run")
        self.assertIn(
            str(Path.cwd() / "src" / "frontend" / "node_modules"),
            child_env.get("NODE_PATH", ""),
        )

    def test_headless_audit_reports_clean_source(self):
        scanned, violations = qa_runner.audit_headless_sources(Path.cwd() / "qa")
        self.assertGreater(scanned, 0)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
