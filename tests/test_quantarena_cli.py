"""Tests for the canonical QuantArena CLI entry point."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from quantarena.cli import build_parser, main, run_research_runner


def test_cli_parser_exposes_smoke_subcommand():
    parser = build_parser()
    args = parser.parse_args(["smoke", "--json"])

    assert args.command == "smoke"
    assert args.json is True


def test_run_command_forwards_args_to_research_runner(monkeypatch):
    observed = {}

    def fake_entrypoint():
        observed["argv"] = list(sys.argv)
        return 7

    original_argv = ["quantarena", "outer"]
    monkeypatch.setattr(sys, "argv", original_argv[:])

    exit_code = run_research_runner(
        ["--mode", "backtest", "--tickers", "600519"],
        entrypoint=fake_entrypoint,
    )

    assert exit_code == 7
    assert observed["argv"][0].endswith("run.py")
    assert observed["argv"][1:] == ["--mode", "backtest", "--tickers", "600519"]
    assert sys.argv == original_argv


def test_run_command_strips_explicit_separator(monkeypatch):
    observed = {}

    def fake_entrypoint():
        observed["argv"] = list(sys.argv)
        return 0

    monkeypatch.setattr(sys, "argv", ["quantarena"])

    exit_code = run_research_runner(["--", "--check-env"], entrypoint=fake_entrypoint)

    assert exit_code == 0
    assert observed["argv"][1:] == ["--check-env"]


def test_main_dispatches_run_command(monkeypatch):
    observed = {}

    def fake_runner(args):
        observed["args"] = list(args)
        return 5

    monkeypatch.setattr("quantarena.cli.run_research_runner", fake_runner)

    exit_code = main(["run", "--mode", "backtest"])

    assert exit_code == 5
    assert observed["args"] == ["--mode", "backtest"]


def test_run_command_defaults_to_research_runner_help(monkeypatch):
    observed = {}

    def fake_entrypoint():
        observed["argv"] = list(sys.argv)
        return 0

    monkeypatch.setattr(sys, "argv", ["quantarena"])

    exit_code = run_research_runner([], entrypoint=fake_entrypoint)

    assert exit_code == 0
    assert observed["argv"][1:] == ["--help"]


def test_run_command_restores_argv_when_entrypoint_exits(monkeypatch):
    original_argv = ["quantarena", "outer"]

    def fake_entrypoint():
        raise SystemExit(2)

    monkeypatch.setattr(sys, "argv", original_argv[:])

    with pytest.raises(SystemExit) as exc_info:
        run_research_runner(["--bad-arg"], entrypoint=fake_entrypoint)

    assert exc_info.value.code == 2
    assert sys.argv == original_argv


def test_cli_parser_exposes_artifact_validate_subcommand():
    parser = build_parser()
    args = parser.parse_args(["artifact", "validate", "--root", "bundle", "--json", "--strict"])

    assert args.command == "artifact"
    assert args.artifact_command == "validate"
    assert str(args.root) == "bundle"
    assert args.json is True
    assert args.strict is True


def test_cli_parser_exposes_artifact_summary_subcommand():
    parser = build_parser()
    args = parser.parse_args(["artifact", "summary", "--root", "bundle", "--json"])

    assert args.command == "artifact"
    assert args.artifact_command == "summary"
    assert str(args.root) == "bundle"
    assert args.json is True


def test_cli_parser_exposes_provider_smoke_subcommand():
    parser = build_parser()
    args = parser.parse_args(
        [
            "provider",
            "smoke",
            "--market",
            "us",
            "--provider",
            "fmp",
            "--ticker",
            "AAPL",
            "--date",
            "2026-01-02",
            "--json",
        ]
    )

    assert args.command == "provider"
    assert args.provider_command == "smoke"
    assert args.market == "us"
    assert args.provider == "fmp"
    assert args.ticker == "AAPL"
    assert args.date == "2026-01-02"
    assert args.json is True


def test_cli_parser_rejects_yfinance_provider_smoke():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["provider", "smoke", "--provider", "yfinance"])


def test_cli_parser_exposes_evaluate_subcommand():
    parser = build_parser()
    args = parser.parse_args(["evaluate", "--root", "bundle", "--json", "--strict"])

    assert args.command == "evaluate"
    assert str(args.root) == "bundle"
    assert args.json is True
    assert args.strict is True
    assert args.summary is False


def test_cli_parser_rejects_strict_summary_evaluate_combination():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["evaluate", "--strict", "--summary"])


def test_smoke_command_reports_project_layout(capsys):
    exit_code = main(["smoke", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["mode"] == "source_checkout"
    assert payload["checks"]["backtest_package"] is True
    assert payload["checks"]["deepfund_config"] is True
    assert payload["checks"]["deepear_config"] is True
    assert payload["checks"]["shared_package"] is True


def test_provider_smoke_command_reports_skip_without_credentials(monkeypatch, capsys):
    monkeypatch.setenv("FMP_API_KEY", "")

    exit_code = main(
        [
            "provider",
            "smoke",
            "--market",
            "us",
            "--provider",
            "fmp",
            "--ticker",
            "AAPL",
            "--date",
            "2026-01-02",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["skipped"] is True
    assert payload["reason"] == "missing credential: FMP_API_KEY"


def test_provider_smoke_command_fails_on_invalid_date(monkeypatch, capsys):
    monkeypatch.setenv("FMP_API_KEY", "test-key")

    exit_code = main(
        [
            "provider",
            "smoke",
            "--market",
            "us",
            "--provider",
            "fmp",
            "--ticker",
            "AAPL",
            "--date",
            "2026/01/02",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["reason"] == "date must use YYYY-MM-DD format"


def test_artifact_validate_reports_missing_bundle(capsys):
    exit_code = main(["artifact", "validate", "--root", "does-not-exist", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["checks"]["manifest_exists"] is False
    assert payload["checks"]["croissant_exists"] is False


def test_artifact_validate_non_strict_allows_warnings(tmp_path, capsys):
    _write_documented_only_bundle(tmp_path)

    exit_code = main(["artifact", "validate", "--root", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["strict"] is False
    assert payload["warnings"]


def test_artifact_validate_strict_fails_on_warnings(tmp_path, capsys):
    _write_documented_only_bundle(tmp_path)

    exit_code = main(["artifact", "validate", "--root", str(tmp_path), "--json", "--strict"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["strict"] is True
    assert payload["warnings"]


def test_evaluate_validates_bundle_by_default(tmp_path, capsys):
    _write_documented_only_bundle(tmp_path)

    exit_code = main(["evaluate", "--root", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["strict"] is False
    assert payload["warnings"]


def test_evaluate_strict_fails_on_warnings(tmp_path, capsys):
    _write_documented_only_bundle(tmp_path)

    exit_code = main(["evaluate", "--root", str(tmp_path), "--json", "--strict"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["strict"] is True
    assert payload["warnings"]


def test_evaluate_summary_is_non_failing(tmp_path, capsys):
    _write_documented_only_bundle(tmp_path)

    exit_code = main(["evaluate", "--root", str(tmp_path), "--json", "--summary"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["stats"]["documented_only_experiments"] == 1


def test_evaluate_reports_missing_bundle(capsys):
    exit_code = main(["evaluate", "--root", "does-not-exist", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["checks"]["manifest_exists"] is False
    assert payload["checks"]["croissant_exists"] is False


def test_evaluate_matches_artifact_validate_payload(tmp_path, capsys):
    _write_documented_only_bundle(tmp_path)

    evaluate_exit_code = main(["evaluate", "--root", str(tmp_path), "--json"])
    evaluate_payload = json.loads(capsys.readouterr().out)

    artifact_exit_code = main(["artifact", "validate", "--root", str(tmp_path), "--json"])
    artifact_payload = json.loads(capsys.readouterr().out)

    assert evaluate_exit_code == artifact_exit_code
    assert evaluate_payload == artifact_payload


def test_artifact_summary_reports_bundle_counts(tmp_path, capsys):
    _write_documented_only_bundle(tmp_path)

    exit_code = main(["artifact", "summary", "--root", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["checks"]["manifest_exists"] is True
    assert payload["checks"]["croissant_exists"] is True
    assert payload["stats"]["manifest_runs"] == 0
    assert payload["stats"]["documented_only_experiments"] == 1
    assert payload["stats"]["summary_schema_version"] == 1
    assert payload["stats"]["experiments"] == {
        "documented_only": {
            "status": "documented_only",
            "run_count": 0,
            "runs": [],
            "source_doc": "source.md",
        }
    }
    assert payload["stats"]["warning_categories"] == {
        "documented_only_experiments": ["documented_only"],
        "empty_experiments": [],
    }
    assert payload["stats"]["distribution"]["file_objects"] == [
        "all_metrics.csv",
        "all_trades.csv",
        "manifest.json",
        "sector_style_universe.csv",
    ]
    assert payload["stats"]["distribution"]["missing_required_file_objects"] == []


def test_artifact_summary_reports_mixed_experiment_statuses(tmp_path, capsys):
    _write_documented_only_bundle(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["experiments"]["with_runs"] = {
        "runs": {
            "macro_tactical": {
                "bundle_path": "runs/with_runs/macro_tactical",
                "display_name": "Macro Tactical",
                "end_date": "2026-01-01",
                "files": [],
                "market": "us",
                "start_date": "2026-01-01",
                "status": "ok",
                "total_return": 1.0,
                "total_trades": 0,
            }
        }
    }
    manifest["experiments"]["empty"] = {}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    exit_code = main(["evaluate", "--root", str(tmp_path), "--json", "--summary"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["stats"]["manifest_experiments"] == 3
    assert payload["stats"]["manifest_runs"] == 1
    assert payload["stats"]["experiments_with_runs"] == 1
    assert payload["stats"]["empty_experiments"] == 1
    assert payload["stats"]["experiments"]["with_runs"]["status"] == "with_runs"
    assert payload["stats"]["experiments"]["with_runs"]["runs"] == ["macro_tactical"]
    assert payload["stats"]["experiments"]["empty"]["status"] == "empty"
    assert payload["stats"]["warning_categories"]["documented_only_experiments"] == [
        "documented_only"
    ]
    assert payload["stats"]["warning_categories"]["empty_experiments"] == ["empty"]
    assert "Documented-only experiments are present" in payload["warnings"]
    assert "Empty experiments are present" in payload["warnings"]


def test_artifact_summary_reports_missing_required_distribution_fileobject(tmp_path, capsys):
    _write_documented_only_bundle(tmp_path)
    croissant_path = tmp_path / "croissant.json"
    croissant = json.loads(croissant_path.read_text(encoding="utf-8"))
    croissant["distribution"] = [
        item
        for item in croissant["distribution"]
        if item.get("name") != "all_trades.csv"
    ]
    croissant_path.write_text(json.dumps(croissant), encoding="utf-8")

    exit_code = main(["artifact", "summary", "--root", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["stats"]["distribution"]["file_object_count"] == 3
    assert payload["stats"]["distribution"]["missing_required_file_objects"] == [
        "all_trades.csv"
    ]


def test_artifact_summary_reports_non_list_distribution(tmp_path, capsys):
    _write_documented_only_bundle(tmp_path)
    croissant_path = tmp_path / "croissant.json"
    croissant = json.loads(croissant_path.read_text(encoding="utf-8"))
    croissant["distribution"] = {"not": "a list"}
    croissant_path.write_text(json.dumps(croissant), encoding="utf-8")

    exit_code = main(["artifact", "summary", "--root", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["stats"]["distribution"] == {
        "file_object_count": 0,
        "file_objects": [],
        "required_file_objects": [
            "all_metrics.csv",
            "all_trades.csv",
            "manifest.json",
            "sector_style_universe.csv",
        ],
        "missing_required_file_objects": [
            "all_metrics.csv",
            "all_trades.csv",
            "manifest.json",
            "sector_style_universe.csv",
        ],
    }


def test_artifact_summary_preserves_missing_bundle_checks(capsys):
    exit_code = main(["artifact", "summary", "--root", "does-not-exist", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is False
    assert payload["checks"]["manifest_exists"] is False
    assert payload["checks"]["croissant_exists"] is False
    assert payload["errors"]
    assert payload["stats"] == {"summary_schema_version": 1}


def test_module_entrypoint_smoke_command_works():
    result = subprocess.run(
        [sys.executable, "-m", "quantarena.cli", "smoke", "--json"],
        text=True,
        capture_output=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["mode"] == "source_checkout"


def test_module_entrypoint_run_check_env_works():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        env_path.write_text(
            "REASONING_MODEL_PROVIDER=openai\n"
            "REASONING_MODEL_ID=gpt-4o\n"
            "OPENAI_API_KEY=test-key\n"
            "TUSHARE_API_KEY=test-key\n",
            encoding="utf-8",
        )

    result = subprocess.run(
        [sys.executable, "-m", "quantarena.cli", "run", "--check-env", "--no-banner"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Environment file exists" in result.stdout


def test_module_entrypoint_evaluate_command_works(tmp_path):
    _write_documented_only_bundle(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "quantarena.cli",
            "evaluate",
            "--root",
            str(tmp_path),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["warnings"]


def _file_object(root: Path, name: str, relative_path: str) -> dict:
    path = root / relative_path
    return {
        "@type": "cr:FileObject",
        "@id": name.replace(".", "-"),
        "name": name,
        "encodingFormat": "text/csv" if name.endswith(".csv") else "application/json",
        "contentUrl": f"https://example.com/{relative_path}",
        "md5": hashlib.md5(path.read_bytes()).hexdigest(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_documented_only_bundle(root: Path) -> None:
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "experiments": {
                    "documented_only": {
                        "source_doc": "source.md",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "source.md").write_text("# source\n", encoding="utf-8")
    (root / "derived").mkdir()
    (root / "universe").mkdir()
    (root / "derived" / "all_metrics.csv").write_text("experiment\n", encoding="utf-8")
    (root / "derived" / "all_trades.csv").write_text("experiment\n", encoding="utf-8")
    (root / "universe" / "sector_style_universe.csv").write_text("ticker\n", encoding="utf-8")
    (root / "croissant.json").write_text(
        json.dumps(
            {
                "@context": {"sc": "https://schema.org/"},
                "@type": "sc:Dataset",
                "conformsTo": "http://mlcommons.org/croissant/1.1",
                "description": "test",
                "distribution": [
                    _file_object(root, "manifest.json", "manifest.json"),
                    _file_object(root, "all_metrics.csv", "derived/all_metrics.csv"),
                    _file_object(root, "all_trades.csv", "derived/all_trades.csv"),
                    _file_object(
                        root,
                        "sector_style_universe.csv",
                        "universe/sector_style_universe.csv",
                    ),
                ],
                "license": "https://creativecommons.org/licenses/by-nc/4.0/",
                "name": "test",
                "recordSet": [
                    {
                        "@type": "cr:RecordSet",
                        "@id": "records",
                        "field": [
                            {
                                "@type": "cr:Field",
                                "@id": "records/experiment",
                                "source": {
                                    "fileObject": {"@id": "all-metrics-csv"},
                                    "extract": {"column": "experiment"},
                                },
                            }
                        ],
                    }
                ],
                "url": "https://example.com",
                "rai:dataBiases": "test",
                "rai:dataLimitations": "test",
                "rai:dataSocialImpact": "test",
                "rai:dataUseCases": ["test"],
                "rai:hasSyntheticData": False,
                "rai:personalSensitiveInformation": "none",
                "prov:wasDerivedFrom": ["test"],
                "prov:wasGeneratedBy": [{"name": "test"}],
            }
        ),
        encoding="utf-8",
    )
