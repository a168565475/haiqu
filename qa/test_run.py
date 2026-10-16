import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


RUNNER_PATH = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("qa_runner", RUNNER_PATH)
qa_runner = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(qa_runner)


class RunnerContractTests(unittest.TestCase):
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
