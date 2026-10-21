#!/usr/bin/env python3
"""haiqu ERP QA 统一入口。

入口只编排已登记的历史脚本，不改变脚本自身的业务逻辑或 Playwright 生命周期。
默认只允许已确认的 headless、read-only 条目；写库和可视模式必须显式通过门禁。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).with_name("runner_manifest.json")
RUNNER_VERSION = "1.0"
VALID_RUNTIMES = {"node", "python"}
VALID_CATEGORIES = {"business", "page", "visual", "data_init", "api_helper", "evidence"}
VALID_RISKS = {"read-only", "isolated-write", "real-write", "unknown"}
VALID_BROWSER_MODES = {"none", "headless", "headed", "unknown"}
SENSITIVE_NAME = re.compile(r"(password|passwd|secret|token|cookie|authorization|database_url|dsn)", re.I)
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ManifestError(ValueError):
    """注册表不符合安全契约。"""


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now(value: dt.datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def validate_relative_path(value: str, root: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError("path 必须是非空字符串")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ManifestError(f"path 不得越过项目根目录：{value}")
    resolved = (root / candidate).resolve()
    if not _is_within(resolved, root.resolve()):
        raise ManifestError(f"path 不在项目根目录内：{value}")
    return resolved


def _validate_env_names(names: Any, field: str) -> list[str]:
    if names is None:
        return []
    if not isinstance(names, list) or any(not isinstance(item, str) for item in names):
        raise ManifestError(f"{field} 必须是字符串数组")
    for item in names:
        if not ENV_NAME.fullmatch(item):
            raise ManifestError(f"{field} 含非法环境变量名：{item}")
    return names


def validate_entry(entry: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ManifestError("每个注册条目必须是对象")
    required = {"id", "path", "runtime", "category", "risk", "database_target", "browser_mode"}
    missing = sorted(required - set(entry))
    if missing:
        raise ManifestError(f"条目缺少字段：{', '.join(missing)}")
    entry_id = entry["id"]
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise ManifestError("id 必须是非空字符串")
    validate_relative_path(entry["path"], root)
    if entry["runtime"] not in VALID_RUNTIMES:
        raise ManifestError(f"{entry_id}: runtime 不受支持：{entry['runtime']}")
    if entry["category"] not in VALID_CATEGORIES:
        raise ManifestError(f"{entry_id}: category 不受支持：{entry['category']}")
    if entry["risk"] not in VALID_RISKS:
        raise ManifestError(f"{entry_id}: risk 不受支持：{entry['risk']}")
    if entry["browser_mode"] not in VALID_BROWSER_MODES:
        raise ManifestError(f"{entry_id}: browser_mode 不受支持：{entry['browser_mode']}")
    if entry.get("result_protocol") not in (None, "json-summary-v1"):
        raise ManifestError(f"{entry_id}: result_protocol 不受支持")
    if not isinstance(entry.get("database_target"), str) or not entry["database_target"].strip():
        raise ManifestError(f"{entry_id}: database_target 必须非空")
    if not isinstance(entry.get("account_required", False), bool):
        raise ManifestError(f"{entry_id}: account_required 必须是布尔值")
    _validate_env_names(entry.get("required_env", []), "required_env")
    _validate_env_names(entry.get("account_env", []), "account_env")
    args = entry.get("args", [])
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ManifestError(f"{entry_id}: args 必须是字符串数组")
    artifacts = entry.get("artifacts", [])
    if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
        raise ManifestError(f"{entry_id}: artifacts 必须是字符串数组")
    if not isinstance(entry.get("enabled", False), bool):
        raise ManifestError(f"{entry_id}: enabled 必须是布尔值")
    order = entry.get("order", 100)
    if not isinstance(order, int) or order < 0:
        raise ManifestError(f"{entry_id}: order 必须是非负整数")
    timeout = entry.get("timeout_seconds", 300)
    if not isinstance(timeout, int) or timeout <= 0:
        raise ManifestError(f"{entry_id}: timeout_seconds 必须是正整数")
    return entry


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"找不到注册表：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"注册表 JSON 无效：{exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ManifestError("注册表 version 必须为 1")
    modules = raw.get("modules")
    if not isinstance(modules, dict):
        raise ManifestError("注册表 modules 必须是对象")
    ids: set[str] = set()
    normalized: dict[str, list[dict[str, Any]]] = {}
    for module, entries in modules.items():
        if not isinstance(module, str) or not module.strip():
            raise ManifestError("模块名必须是非空字符串")
        if not isinstance(entries, list):
            raise ManifestError(f"模块 {module} 必须是条目数组")
        normalized_entries: list[dict[str, Any]] = []
        for item in entries:
            checked = validate_entry(item, ROOT)
            if checked["id"] in ids:
                raise ManifestError(f"重复的条目 id：{checked['id']}")
            ids.add(checked["id"])
            normalized_entries.append({**checked, "module": module})
        normalized[module] = normalized_entries
    return {"version": 1, "modules": normalized}


def select_entries(manifest: dict[str, Any], module: str) -> list[dict[str, Any]]:
    modules: dict[str, list[dict[str, Any]]] = manifest["modules"]
    if module == "all":
        selected: list[dict[str, Any]] = []
        module_order = {name: index for index, name in enumerate(("production", "quotation", "inquiry"))}
        for name, entries in modules.items():
            if name not in module_order:
                continue
            selected.extend(entries)
        selected.sort(key=lambda item: (module_order.get(item["module"], 999), item.get("order", 100), item["id"]))
    else:
        selected = sorted(modules.get(module, []), key=lambda item: (item.get("order", 100), item["id"]))
    return [item for item in selected if item.get("enabled", False)]


def check_headless_source(source: str) -> str | None:
    """返回违规原因；None 表示明确使用 headless:true。"""
    if re.search(r"headless\s*:\s*false\b", source):
        return "检测到 headless: false"
    if not re.search(r"headless\s*:\s*true\b", source):
        return "未明确设置 headless: true"
    return None


PLAYWRIGHT_LAUNCH = re.compile(
    r"(?:chromium|firefox|webkit)\.launch(?:PersistentContext)?\s*\("
)
SKIP_HEADLESS_PARTS = {
    "node_modules",
    "before",
    "after",
    "baseline",
    "isolated_backend",
    "isolated_frontend",
    "build",
    "dist",
    "output",
    "outputs",
}
SKIP_HEADLESS_PREFIXES = ("browser_profile", "chrome_profile", "chrome_cdp", "node_modules")


def audit_headless_sources(qa_root: Path = ROOT / "qa") -> tuple[int, list[dict[str, str]]]:
    """扫描 QA Playwright 启动点，返回 (扫描数, 违规列表)。"""
    scanned = 0
    violations: list[dict[str, str]] = []
    if not qa_root.is_dir():
        return scanned, violations
    for directory, dir_names, file_names in os.walk(qa_root):
        dir_names[:] = [
            name for name in dir_names
            if name not in SKIP_HEADLESS_PARTS
            and not name.startswith(SKIP_HEADLESS_PREFIXES)
        ]
        for file_name in file_names:
            path = Path(directory) / file_name
            if path.suffix.lower() not in {".cjs", ".js", ".mjs"}:
                continue
            if any(part in SKIP_HEADLESS_PARTS for part in path.parts):
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if not PLAYWRIGHT_LAUNCH.search(source):
                continue
            scanned += 1
            reason = check_headless_source(source)
            if reason:
                violations.append({"path": path.relative_to(ROOT).as_posix(), "reason": reason})
    return scanned, violations


def resolve_runtime(runtime: str) -> Path | None:
    if runtime == "python":
        return Path(sys.executable)
    override = os.environ.get("QA_NODE_PATH")
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    found = shutil.which("node")
    return Path(found) if found else None


def child_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """为旧脚本准备环境，不覆盖用户已有变量或秘密。"""
    environment = os.environ.copy()
    project_node_modules = ROOT / "src" / "frontend" / "node_modules"
    if project_node_modules.is_dir():
        existing = environment.get("NODE_PATH", "")
        paths = [str(project_node_modules)]
        if existing:
            paths.append(existing)
        environment["NODE_PATH"] = os.pathsep.join(paths)
    if overrides:
        environment.update(overrides)
    return environment


def environment_status(names: list[str]) -> dict[str, dict[str, bool]]:
    return {name: {"provided": bool(os.environ.get(name))} for name in names}


def _entry_source(entry: dict[str, Any]) -> str:
    path = validate_relative_path(entry["path"], ROOT)
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return ""


def preflight_entry(
    entry: dict[str, Any],
    *,
    read_only: bool,
    allow_db_write: bool,
    allow_real_db_write: bool,
) -> tuple[str | None, Path | None]:
    """返回 (阻断原因, 运行时路径)。None 原因表示可以继续。"""
    script_path = validate_relative_path(entry["path"], ROOT)
    if not script_path.is_file():
        return f"脚本不存在：{entry['path']}", None
    runtime = resolve_runtime(entry["runtime"])
    if runtime is None:
        return f"找不到 {entry['runtime']} 运行时", None
    missing = [name for name in entry.get("required_env", []) if not os.environ.get(name)]
    missing += [name for name in entry.get("account_env", []) if not os.environ.get(name)]
    if missing:
        return f"缺少环境变量：{', '.join(sorted(set(missing)))}", runtime
    risk = entry["risk"]
    if risk == "unknown":
        return "条目风险仍为 UNKNOWN，禁止自动执行", runtime
    if read_only and risk != "read-only":
        return f"--read-only 不允许风险级别 {risk}", runtime
    if risk == "isolated-write" and not allow_db_write:
        return "隔离库写入需要 --allow-db-write", runtime
    if risk == "real-write":
        if not allow_real_db_write:
            return "真实业务库写入需要 --allow-real-db-write", runtime
        if os.environ.get("QA_ALLOW_REAL_DB_WRITE") != "I_UNDERSTAND":
            return "真实业务库写入还需要 QA_ALLOW_REAL_DB_WRITE=I_UNDERSTAND", runtime
    browser_mode = entry["browser_mode"]
    if browser_mode in {"headed", "unknown"}:
        return f"浏览器模式未满足日常 headless 门禁：{browser_mode}", runtime
    if browser_mode == "headless":
        reason = check_headless_source(_entry_source(entry))
        if reason:
            return reason, runtime
    return None, runtime


def _safe_command(runtime: Path, entry: dict[str, Any]) -> list[str]:
    return [str(runtime), str(validate_relative_path(entry["path"], ROOT)), *entry.get("args", [])]


def _redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for item in command:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        redacted.append(item)
        if SENSITIVE_NAME.search(item):
            redact_next = True
    return redacted


def _sanitize(value: Any, parent_key: str = "", in_environment: bool = False) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if in_environment and key in {"value", "values"}:
                continue
            if in_environment or key == "environment":
                result[key] = _sanitize(item, str(key), True)
            elif SENSITIVE_NAME.search(str(key)) and key not in {"provided", "missing"}:
                result[key] = "<redacted>"
            else:
                result[key] = _sanitize(item, str(key))
        return result
    if isinstance(value, list):
        return [_sanitize(item, parent_key, in_environment) for item in value]
    return value


def write_json_report(path: Path, report: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_sanitize(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _artifact_paths(patterns: list[str]) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            if path.is_file():
                found.append(path.relative_to(ROOT).as_posix())
    return sorted(set(found))


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# haiqu ERP QA 运行报告",
        "",
        f"- 运行 ID：`{report['run_id']}`",
        f"- 模块：`{report['module']}`",
        f"- 模式：`{report['mode']}`",
        f"- 开始：`{report['started_at']}`",
        f"- 结束：`{report['finished_at']}`",
        "",
        "## 汇总",
        "",
        "| PASS | FAIL | BLOCKED | SKIP | UNKNOWN |",
        "| ---: | ---: | ---: | ---: | ---: |",
        f"| {summary['pass']} | {summary['fail']} | {summary['blocked']} | {summary['skip']} | {summary['unknown']} |",
        "",
        "## 条目",
        "",
        "| 状态 | ID | 分类 | 风险 | 浏览器 | 退出码 | 原因 |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for case in report["cases"]:
        reason = str(case.get("reason", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {case['status']} | `{case['id']}` | {case['category']} | {case['risk']} | "
            f"{case['browser_mode']} | {case.get('exit_code', '')} | {reason} |"
        )
    partial_count = summary.get("pass_with_gaps", 0)
    if partial_count:
        lines.extend(["", f"PASS_WITH_GAPS：{partial_count} 项检查通过但覆盖不完整，不计入 PASS。"])
    for case in report["cases"]:
        if case.get("coverage_gaps"):
            lines.extend(["", f"### `{case['id']}` 未覆盖项", ""])
            lines.extend(f"- {str(gap).replace(chr(10), ' ')}" for gap in case["coverage_gaps"])
    return "\n".join(lines) + "\n"


def _structured_result(stdout: str, returncode: int) -> dict[str, Any]:
    """仅解析显式登记协议的脚本，末行 JSON 保留业务结果和覆盖缺口。"""
    lines = [line for line in stdout.splitlines() if line.strip()]
    try:
        result = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError as exc:
        raise ValueError("结构化结果缺失或不是有效 JSON") from exc
    if not isinstance(result, dict) or type(result.get("qa_result_version")) is not int or result["qa_result_version"] != 1:
        raise ValueError("结构化结果版本缺失或不受支持")
    status = result.get("status")
    gaps = result.get("not_covered")
    if not isinstance(status, str) or status not in {"PASS", "PASS_WITH_GAPS", "BLOCKED", "FAIL"}:
        raise ValueError("结构化结果状态无效")
    if not isinstance(gaps, list) or any(not isinstance(gap, str) or not gap.strip() for gap in gaps):
        raise ValueError("结构化结果的未覆盖项必须为字符串数组")
    successful = status in {"PASS", "PASS_WITH_GAPS"}
    if successful != (returncode == 0):
        raise ValueError("结构化结果与子进程退出码不一致")
    if successful and result.get("cleanup") is not True:
        raise ValueError("结构化结果没有确认临时资源已清理")
    if (status == "PASS" and gaps) or (status == "PASS_WITH_GAPS" and not gaps):
        raise ValueError("结构化结果状态与未覆盖项不一致")
    parsed: dict[str, Any] = {"status": status, "coverage_gaps": gaps}
    if status == "PASS_WITH_GAPS":
        parsed["reason"] = f"已执行检查通过，仍有 {len(gaps)} 项覆盖缺口；不是完整验收通过"
    elif status in {"BLOCKED", "FAIL"}:
        failure = result.get("failure")
        message = failure.get("message") if isinstance(failure, dict) else None
        parsed["reason"] = message if isinstance(message, str) and message else f"子脚本报告 {status}"
    return parsed


def run_entry(
    entry: dict[str, Any],
    *,
    report_dir: Path,
    run_id: str,
    dry_run: bool,
    read_only: bool,
    allow_db_write: bool,
    allow_real_db_write: bool,
    timeout_override: int | None,
) -> dict[str, Any]:
    started = now_utc()
    required = list(dict.fromkeys(entry.get("required_env", []) + entry.get("account_env", [])))
    case: dict[str, Any] = {
        "id": entry["id"],
        "module": entry["module"],
        "path": entry["path"],
        "runtime": entry["runtime"],
        "category": entry["category"],
        "risk": entry["risk"],
        "database_target": entry["database_target"],
        "browser_mode": entry["browser_mode"],
        "account_required": entry.get("account_required", False),
        "environment": environment_status(required),
        "started_at": iso_now(started),
        "status": "UNKNOWN",
        "exit_code": None,
        "artifacts": [],
    }
    try:
        reason, runtime = preflight_entry(
            entry,
            read_only=read_only,
            allow_db_write=allow_db_write,
            allow_real_db_write=allow_real_db_write,
        )
    except ManifestError as exc:
        reason, runtime = str(exc), None
    if reason:
        case["status"] = "UNKNOWN" if entry["risk"] == "unknown" else "BLOCKED"
        case["reason"] = reason
        case["finished_at"] = iso_now(now_utc())
        case["duration_ms"] = int((now_utc() - started).total_seconds() * 1000)
        return case
    assert runtime is not None
    command = _safe_command(runtime, entry)
    case["command"] = _redact_command(command)
    if dry_run:
        case["status"] = "SKIP"
        case["reason"] = "dry-run：已完成预检，未启动子进程"
        case["finished_at"] = iso_now(now_utc())
        case["duration_ms"] = int((now_utc() - started).total_seconds() * 1000)
        return case

    report_dir.mkdir(parents=True, exist_ok=True)
    case_dir = report_dir / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = case_dir / f"{entry['id']}.stdout.log"
    stderr_path = case_dir / f"{entry['id']}.stderr.log"
    timeout = timeout_override or entry.get("timeout_seconds", 300)
    env = child_environment({"QA_RUN_ID": run_id, "QA_REPORT_DIR": str(report_dir)})
    process_started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        case["exit_code"] = completed.returncode
        if entry.get("result_protocol") == "json-summary-v1":
            try:
                case.update(_structured_result(completed.stdout or "", completed.returncode))
            except ValueError as exc:
                case["status"] = "FAIL"
                case["reason"] = str(exc)
        else:
            case["status"] = "PASS" if completed.returncode == 0 else "FAIL"
            if completed.returncode != 0:
                case["reason"] = f"子进程退出码 {completed.returncode}"
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout or "", encoding="utf-8")
        stderr_path.write_text(exc.stderr or "", encoding="utf-8")
        case["status"] = "FAIL"
        case["reason"] = f"超过 {timeout} 秒超时"
    except OSError as exc:
        case["status"] = "FAIL"
        case["reason"] = f"无法启动子进程：{exc}"
    case["duration_ms"] = int((time.monotonic() - process_started) * 1000)
    case["stdout"] = stdout_path.relative_to(report_dir).as_posix()
    case["stderr"] = stderr_path.relative_to(report_dir).as_posix()
    case["artifacts"] = _artifact_paths(entry.get("artifacts", []))
    case["finished_at"] = iso_now(now_utc())
    return case


def _summary(cases: list[dict[str, Any]]) -> dict[str, int]:
    result = {"pass": 0, "pass_with_gaps": 0, "fail": 0, "blocked": 0, "skip": 0, "unknown": 0}
    for case in cases:
        key = case["status"].lower()
        if key in result:
            result[key] += 1
    return result


def _exit_code(summary: dict[str, int], *, config_error: bool = False) -> int:
    if config_error:
        return 2
    if summary["fail"]:
        return 1
    if summary["blocked"]:
        return 3
    if summary["unknown"]:
        return 4
    if summary.get("pass_with_gaps", 0):
        return 5
    if not summary["pass"] and not summary["skip"]:
        return 4
    return 0


def _print_list(manifest: dict[str, Any]) -> None:
    print("ID\tMODULE\tENABLED\tCATEGORY\tRISK\tBROWSER\tPATH")
    for module, entries in manifest["modules"].items():
        for entry in sorted(entries, key=lambda item: (item.get("order", 100), item["id"])):
            print(
                "\t".join(
                    [
                        entry["id"],
                        module,
                        "yes" if entry.get("enabled") else "no",
                        entry["category"],
                        entry["risk"],
                        entry["browser_mode"],
                        entry["path"],
                    ]
                )
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="haiqu ERP QA 统一入口")
    parser.add_argument("module", nargs="?", help="production、quotation、inquiry、material_catalog、workbench、wecom、wecom-employee-login、workshop-employee-identity、employee-menu、attendance、organizations、permissions、finished-outbound、finished-outbound-list 或 all")
    parser.add_argument("--list", action="store_true", help="列出注册条目，不运行测试")
    parser.add_argument("--audit-headless", action="store_true", help="扫描 QA Playwright 启动点的 headless 门禁")
    parser.add_argument("--dry-run", action="store_true", help="只预检，不启动子进程")
    parser.add_argument("--read-only", action="store_true", help="只允许运行 read-only 条目")
    parser.add_argument("--allow-db-write", action="store_true", help="允许 isolated-write 条目")
    parser.add_argument("--allow-real-db-write", action="store_true", help="允许 real-write 条目（仍需环境确认）")
    parser.add_argument("--report-dir", type=Path, help="报告输出目录")
    parser.add_argument("--timeout", type=int, help="覆盖单条脚本超时时间（秒）")
    parser.add_argument("--continue-on-failure", action="store_true", help="失败后继续其他独立条目")
    return parser.parse_args(argv)


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    configure_output()
    args = parse_args(argv)
    if args.audit_headless:
        scanned, violations = audit_headless_sources()
        print(json.dumps({"scanned": scanned, "violations": violations}, ensure_ascii=False, indent=2))
        return 0 if not violations else 1
    try:
        manifest = load_manifest()
    except ManifestError as exc:
        print(f"QA 配置错误：{exc}", file=sys.stderr)
        return 2
    if args.list:
        _print_list(manifest)
        return 0
    if args.module not in {"production", "quotation", "inquiry", "material_catalog", "workbench", "wecom", "wecom-employee-login", "workshop-employee-identity", "employee-menu", "attendance", "organizations", "permissions", "finished-outbound", "finished-outbound-list", "all"}:
        print("请指定 production、quotation、inquiry、material_catalog、workbench、wecom、wecom-employee-login、workshop-employee-identity、employee-menu、attendance、organizations、permissions、finished-outbound、finished-outbound-list 或 all；可用 --list 查看注册表。", file=sys.stderr)
        return 2
    if args.timeout is not None and args.timeout <= 0:
        print("--timeout 必须是正整数。", file=sys.stderr)
        return 2
    if args.read_only and (args.allow_db_write or args.allow_real_db_write):
        print("--read-only 不能与写库授权参数同时使用。", file=sys.stderr)
        return 2
    entries = select_entries(manifest, args.module)
    run_id = now_utc().strftime("%Y%m%dT%H%M%SZ")
    report_dir = (args.report_dir or (ROOT / "output" / "qa-runs" / run_id)).resolve()
    if not entries:
        print(f"模块 {args.module} 没有 enabled=true 的已登记条目。", file=sys.stderr)
        return 4
    cases: list[dict[str, Any]] = []
    for entry in entries:
        case = run_entry(
            entry,
            report_dir=report_dir,
            run_id=run_id,
            dry_run=args.dry_run,
            read_only=args.read_only,
            allow_db_write=args.allow_db_write,
            allow_real_db_write=args.allow_real_db_write,
            timeout_override=args.timeout,
        )
        cases.append(case)
        print(f"[{case['status']}] {entry['id']}: {case.get('reason', '')}".rstrip())
        if case["status"] == "FAIL" and not args.continue_on_failure:
            break
    summary = _summary(cases)
    report = {
        "schema_version": 1,
        "runner_version": RUNNER_VERSION,
        "run_id": run_id,
        "module": args.module,
        "mode": "dry-run" if args.dry_run else ("read-only" if args.read_only else "normal"),
        "started_at": cases[0]["started_at"],
        "finished_at": iso_now(now_utc()),
        "summary": summary,
        "cases": cases,
    }
    json_path = write_json_report(report_dir / "report.json", report)
    markdown_path = report_dir / "report.md"
    markdown_path.write_text(_markdown_report(_sanitize(report)), encoding="utf-8")
    print(f"报告：{json_path}")
    print(f"汇总：PASS={summary['pass']} FAIL={summary['fail']} BLOCKED={summary['blocked']} UNKNOWN={summary['unknown']}")
    if summary.get("pass_with_gaps", 0):
        print(f"PASS_WITH_GAPS={summary['pass_with_gaps']}（有覆盖缺口，未完整验收）")
    return _exit_code(summary)


if __name__ == "__main__":
    raise SystemExit(main())
