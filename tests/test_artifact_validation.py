"""Tests for offline release-artifact validation."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from quantarena.artifacts import validate_release_artifacts


def test_validate_release_artifacts_accepts_complete_bundle(tmp_path: Path):
    _write_minimal_bundle(tmp_path)

    result = validate_release_artifacts(tmp_path)

    assert result.ok is True
    assert result.checks["manifest_file_references"] is True
    assert result.checks["croissant_fileobject_hashes"] is True
    assert result.checks["croissant_local_hashes"] is True
    assert result.stats["manifest_runs"] == 1
    assert result.stats["croissant_hashes_checked"] == 8


def test_validate_release_artifacts_rejects_missing_manifest_run_file(tmp_path: Path):
    _write_minimal_bundle(tmp_path)
    (tmp_path / "runs" / "exp" / "macro_tactical" / "trades.csv").unlink()

    result = validate_release_artifacts(tmp_path)

    assert result.ok is False
    assert result.checks["manifest_file_references"] is False
    assert any("trades.csv" in error for error in result.errors)


def test_validate_release_artifacts_rejects_missing_croissant_hash(tmp_path: Path):
    _write_minimal_bundle(tmp_path)
    croissant_path = tmp_path / "croissant.json"
    croissant = json.loads(croissant_path.read_text(encoding="utf-8"))
    del croissant["distribution"][0]["md5"]
    del croissant["distribution"][0]["sha256"]
    croissant_path.write_text(json.dumps(croissant), encoding="utf-8")

    result = validate_release_artifacts(tmp_path)

    assert result.ok is False
    assert result.checks["croissant_fileobject_hashes"] is False
    assert "manifest.json" in "\n".join(result.errors)


def test_validate_release_artifacts_rejects_missing_required_fileobject(tmp_path: Path):
    _write_minimal_bundle(tmp_path)
    croissant_path = tmp_path / "croissant.json"
    croissant = json.loads(croissant_path.read_text(encoding="utf-8"))
    croissant["distribution"] = [
        item for item in croissant["distribution"] if item["name"] != "all_trades.csv"
    ]
    croissant_path.write_text(json.dumps(croissant), encoding="utf-8")

    result = validate_release_artifacts(tmp_path)

    assert result.ok is False
    assert result.checks["croissant_required_fileobjects"] is False
    assert "all_trades.csv" in "\n".join(result.errors)


def test_validate_release_artifacts_rejects_checksum_mismatch(tmp_path: Path):
    _write_minimal_bundle(tmp_path)
    _write_csv(tmp_path / "derived" / "all_metrics.csv", ["experiment"], [["changed"]])

    result = validate_release_artifacts(tmp_path)

    assert result.ok is False
    assert result.checks["croissant_local_hashes"] is False
    assert any("all_metrics.csv:md5" in error for error in result.errors)


def test_validate_release_artifacts_rejects_malformed_manifest_run_types(tmp_path: Path):
    _write_minimal_bundle(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run = manifest["experiments"]["exp"]["runs"]["macro_tactical"]
    run["bundle_path"] = 123
    run["files"] = "metrics.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_release_artifacts(tmp_path)

    assert result.ok is False
    assert result.checks["manifest_run_types"] is False
    assert "invalid bundle_path" in "\n".join(result.errors)


def test_validate_release_artifacts_rejects_paths_outside_artifact_root(tmp_path: Path):
    outside = tmp_path.parent / "outside_metrics.json"
    outside.write_text("{}", encoding="utf-8")
    _write_minimal_bundle(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run = manifest["experiments"]["exp"]["runs"]["macro_tactical"]
    run["bundle_path"] = ".."
    run["files"] = [outside.name]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_release_artifacts(tmp_path)

    assert result.ok is False
    assert result.checks["manifest_run_types"] is False
    assert "invalid bundle_path" in "\n".join(result.errors)


def test_validate_release_artifacts_reports_malformed_recordset_without_crashing(tmp_path: Path):
    _write_minimal_bundle(tmp_path)
    croissant_path = tmp_path / "croissant.json"
    croissant = json.loads(croissant_path.read_text(encoding="utf-8"))
    croissant["recordSet"] = ["not-an-object"]
    croissant_path.write_text(json.dumps(croissant), encoding="utf-8")

    result = validate_release_artifacts(tmp_path)

    assert result.ok is False
    assert result.checks["croissant_record_sources"] is False
    assert "<unknown>" in "\n".join(result.errors)


def _write_minimal_bundle(root: Path) -> None:
    run_dir = root / "runs" / "exp" / "macro_tactical"
    run_dir.mkdir(parents=True)
    (run_dir / "metrics.json").write_text('{"metrics": {"total_return": 1.0}}', encoding="utf-8")
    (run_dir / "backtest_report.md").write_text("# Report\n", encoding="utf-8")
    _write_csv(run_dir / "equity_curve.csv", ["date", "value"], [["2026-01-01", "100"]])
    _write_csv(run_dir / "trades.csv", ["date", "ticker"], [["2026-01-01", "AAPL"]])

    (root / "derived").mkdir()
    (root / "universe").mkdir()
    _write_csv(root / "derived" / "all_metrics.csv", ["experiment", "total_return"], [["exp", "1.0"]])
    _write_csv(root / "derived" / "all_trades.csv", ["experiment", "ticker"], [["exp", "AAPL"]])
    _write_csv(root / "universe" / "sector_style_universe.csv", ["ticker"], [["AAPL"]])

    manifest = {
        "version": "1.0",
        "experiments": {
            "exp": {
                "runs": {
                    "macro_tactical": {
                        "bundle_path": "runs/exp/macro_tactical",
                        "display_name": "Macro Tactical",
                        "end_date": "2026-01-01",
                        "files": [
                            "metrics.json",
                            "backtest_report.md",
                            "equity_curve.csv",
                            "trades.csv",
                        ],
                        "market": "us",
                        "start_date": "2026-01-01",
                        "status": "ok",
                        "total_return": 1.0,
                        "total_trades": 1,
                    }
                }
            }
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "croissant.json").write_text(json.dumps(_croissant_payload(root)), encoding="utf-8")


def _croissant_payload(root: Path) -> dict:
    return {
        "@context": {"sc": "https://schema.org/", "cr": "http://mlcommons.org/croissant/"},
        "@type": "sc:Dataset",
        "conformsTo": "http://mlcommons.org/croissant/1.1",
        "description": "Test artifact bundle",
        "distribution": [
            _file_object(root, "manifest.json", "manifest.json"),
            _file_object(root, "all_metrics.csv", "derived/all_metrics.csv"),
            _file_object(root, "all_trades.csv", "derived/all_trades.csv"),
            _file_object(root, "sector_style_universe.csv", "universe/sector_style_universe.csv"),
        ],
        "license": "https://creativecommons.org/licenses/by-nc/4.0/",
        "name": "Test Bundle",
        "recordSet": [
            {
                "@type": "cr:RecordSet",
                "@id": "metrics",
                "field": [
                    {
                        "@type": "cr:Field",
                        "@id": "metrics/experiment",
                        "name": "experiment",
                        "source": {
                            "fileObject": {"@id": "all-metrics-csv"},
                            "extract": {"column": "experiment"},
                        },
                    }
                ],
            }
        ],
        "url": "https://example.com/test",
        "rai:dataBiases": "Test bias note",
        "rai:dataLimitations": "Test limitation note",
        "rai:dataSocialImpact": "Test impact note",
        "rai:dataUseCases": ["testing"],
        "rai:hasSyntheticData": False,
        "rai:personalSensitiveInformation": "None",
        "prov:wasDerivedFrom": ["test source"],
        "prov:wasGeneratedBy": [{"name": "test generation"}],
    }


def _file_object(root: Path, name: str, relative_path: str) -> dict:
    path = root / relative_path
    return {
        "@type": "cr:FileObject",
        "@id": name.replace(".", "-"),
        "name": name,
        "encodingFormat": "text/csv" if name.endswith(".csv") else "application/json",
        "contentUrl": f"https://example.com/{relative_path}",
        "md5": _hash_file(path, "md5"),
        "sha256": _hash_file(path, "sha256"),
    }


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    digest.update(path.read_bytes())
    return digest.hexdigest()
