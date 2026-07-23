"""Offline validation helpers for QuantArena release artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_MANIFEST_RUN_FIELDS = (
    "bundle_path",
    "display_name",
    "end_date",
    "files",
    "market",
    "start_date",
    "status",
    "total_return",
    "total_trades",
)

REQUIRED_CROISSANT_FIELDS = (
    "@context",
    "@type",
    "conformsTo",
    "description",
    "distribution",
    "license",
    "name",
    "recordSet",
    "url",
)

REQUIRED_RAI_FIELDS = (
    "rai:dataBiases",
    "rai:dataLimitations",
    "rai:dataSocialImpact",
    "rai:dataUseCases",
    "rai:hasSyntheticData",
    "rai:personalSensitiveInformation",
    "prov:wasDerivedFrom",
    "prov:wasGeneratedBy",
)

_DISTRIBUTION_PATHS = {
    "manifest.json": "manifest.json",
    "all_metrics.csv": "derived/all_metrics.csv",
    "all_trades.csv": "derived/all_trades.csv",
    "sector_style_universe.csv": "universe/sector_style_universe.csv",
}


@dataclass
class ArtifactValidationResult:
    """Structured result for release-artifact validation."""

    root: Path
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_check(self, name: str, passed: bool, message: str | None = None) -> None:
        self.checks[name] = passed
        if not passed and message:
            self.errors.append(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "root": str(self.root),
            "checks": self.checks,
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": self.stats,
        }


def validate_release_artifacts(root: str | Path) -> ArtifactValidationResult:
    """Validate a local QuantArena release-artifact directory without network access."""
    artifact_root = Path(root)
    result = ArtifactValidationResult(root=artifact_root)

    manifest_path = artifact_root / "manifest.json"
    croissant_path = artifact_root / "croissant.json"
    result.add_check(
        "manifest_exists",
        manifest_path.is_file(),
        f"Missing manifest file: {manifest_path}",
    )
    result.add_check(
        "croissant_exists",
        croissant_path.is_file(),
        f"Missing Croissant file: {croissant_path}",
    )
    if not result.ok:
        return result

    manifest = _load_json(manifest_path, result, "manifest")
    croissant = _load_json(croissant_path, result, "croissant")
    if manifest is None or croissant is None:
        return result

    _validate_manifest(artifact_root, manifest, result)
    _validate_croissant(artifact_root, croissant, result)
    return result


def summarize_release_artifacts(root: str | Path) -> ArtifactValidationResult:
    """Summarize a local QuantArena release-artifact directory."""
    artifact_root = Path(root)
    result = ArtifactValidationResult(root=artifact_root)
    result.stats["summary_schema_version"] = 1

    manifest_path = artifact_root / "manifest.json"
    croissant_path = artifact_root / "croissant.json"
    result.add_check(
        "manifest_exists",
        manifest_path.is_file(),
        f"Missing manifest file: {manifest_path}",
    )
    result.add_check(
        "croissant_exists",
        croissant_path.is_file(),
        f"Missing Croissant file: {croissant_path}",
    )
    if not result.checks["manifest_exists"] or not result.checks["croissant_exists"]:
        return result

    manifest = _load_json(manifest_path, result, "manifest")
    croissant = _load_json(croissant_path, result, "croissant")
    if manifest is None or croissant is None:
        return result

    summary = _summarize_manifest(manifest)
    distribution_summary = _summarize_distribution(croissant)

    result.checks.update(
        {
            "manifest_exists": True,
            "croissant_exists": True,
            "manifest_json_valid": True,
            "croissant_json_valid": True,
        }
    )
    result.stats.update(
        {
            "manifest_experiments": summary["experiment_count"],
            "manifest_runs": summary["run_count"],
            "documented_only_experiments": summary["documented_only_count"],
            "croissant_file_objects": distribution_summary["file_object_count"],
            "experiments_with_runs": summary["experiments_with_runs_count"],
            "empty_experiments": summary["empty_experiment_count"],
        }
    )
    result.stats["experiments"] = summary["experiments"]
    result.stats["distribution"] = distribution_summary
    result.stats["warning_categories"] = {
        "documented_only_experiments": summary["documented_only"],
        "empty_experiments": summary["empty_experiments"],
    }
    result.warnings.extend(
        [
            "Documented-only experiments are present"
            if summary["documented_only_count"]
            else "",
            "Empty experiments are present" if summary["empty_experiment_count"] else "",
        ]
    )
    result.warnings = [warning for warning in result.warnings if warning]
    return result


def _load_json(
    path: Path,
    result: ArtifactValidationResult,
    label: str,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.add_check(f"{label}_json_valid", False, f"Invalid JSON in {path}: {exc}")
        return None

    if not isinstance(payload, dict):
        result.add_check(f"{label}_json_object", False, f"{path} must contain a JSON object")
        return None

    result.add_check(f"{label}_json_valid", True)
    return payload


def _summarize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    experiments = manifest.get("experiments")
    if not isinstance(experiments, dict):
        return {
            "experiment_count": 0,
            "run_count": 0,
            "documented_only_count": 0,
            "experiments_with_runs_count": 0,
            "empty_experiment_count": 0,
            "documented_only": [],
            "empty_experiments": [],
            "experiments": {},
        }

    experiment_summaries: dict[str, dict[str, Any]] = {}
    documented_only: list[str] = []
    empty_experiments: list[str] = []
    run_total = 0

    for experiment_name, experiment in sorted(experiments.items()):
        runs = experiment.get("runs") if isinstance(experiment, dict) else None
        source_doc = experiment.get("source_doc") if isinstance(experiment, dict) else None
        run_names = sorted(runs) if isinstance(runs, dict) else []
        status = "with_runs" if run_names else "empty"
        if not run_names and isinstance(source_doc, str):
            status = "documented_only"
            documented_only.append(experiment_name)
        elif not run_names:
            empty_experiments.append(experiment_name)

        run_total += len(run_names)
        experiment_summaries[experiment_name] = {
            "status": status,
            "run_count": len(run_names),
            "runs": run_names,
            "source_doc": source_doc if isinstance(source_doc, str) else None,
        }

    experiments_with_runs = [
        name
        for name, summary in experiment_summaries.items()
        if summary["status"] == "with_runs"
    ]
    return {
        "experiment_count": len(experiment_summaries),
        "run_count": run_total,
        "documented_only_count": len(documented_only),
        "experiments_with_runs_count": len(experiments_with_runs),
        "empty_experiment_count": len(empty_experiments),
        "documented_only": documented_only,
        "empty_experiments": empty_experiments,
        "experiments": experiment_summaries,
    }


def _summarize_distribution(croissant: dict[str, Any]) -> dict[str, Any]:
    distribution = croissant.get("distribution")
    if not isinstance(distribution, list):
        return {
            "file_object_count": 0,
            "file_objects": [],
            "required_file_objects": sorted(_DISTRIBUTION_PATHS),
            "missing_required_file_objects": sorted(_DISTRIBUTION_PATHS),
        }

    file_objects = sorted(
        item.get("name")
        for item in distribution
        if isinstance(item, dict)
        and item.get("@type") == "cr:FileObject"
        and isinstance(item.get("name"), str)
    )
    missing_required = sorted(set(_DISTRIBUTION_PATHS) - set(file_objects))
    return {
        "file_object_count": len(file_objects),
        "file_objects": file_objects,
        "required_file_objects": sorted(_DISTRIBUTION_PATHS),
        "missing_required_file_objects": missing_required,
    }


def _validate_manifest(
    artifact_root: Path,
    manifest: dict[str, Any],
    result: ArtifactValidationResult,
) -> None:
    experiments = manifest.get("experiments")
    result.add_check(
        "manifest_has_experiments",
        isinstance(experiments, dict) and bool(experiments),
        "manifest.json must contain a non-empty experiments object",
    )
    if not isinstance(experiments, dict):
        return

    run_count = 0
    missing_files = 0
    missing_fields = 0
    malformed_runs = 0
    for experiment_name, experiment in sorted(experiments.items()):
        if not isinstance(experiment, dict):
            result.errors.append(f"Experiment {experiment_name} must be an object")
            continue
        runs = experiment.get("runs")
        if not isinstance(runs, dict) or not runs:
            source_doc = experiment.get("source_doc")
            source_doc_path = _contained_path(artifact_root, source_doc)
            if source_doc_path is not None and source_doc_path.is_file():
                result.warnings.append(
                    f"Experiment {experiment_name} has no run artifacts; validated source_doc only"
                )
                continue
            result.errors.append(
                f"Experiment {experiment_name} must contain non-empty runs or a valid source_doc"
            )
            continue
        for run_name, run in sorted(runs.items()):
            run_count += 1
            if not isinstance(run, dict):
                result.errors.append(f"Run {experiment_name}/{run_name} must be an object")
                continue
            for field_name in REQUIRED_MANIFEST_RUN_FIELDS:
                if field_name not in run:
                    missing_fields += 1
                    result.errors.append(
                        f"Run {experiment_name}/{run_name} missing field: {field_name}"
                    )

            bundle_path = run.get("bundle_path")
            files = run.get("files")
            bundle_dir = _contained_path(artifact_root, bundle_path)
            if bundle_dir is None:
                malformed_runs += 1
                result.errors.append(
                    f"Run {experiment_name}/{run_name} has invalid bundle_path: {bundle_path!r}"
                )
                continue
            if not isinstance(files, list):
                malformed_runs += 1
                result.errors.append(
                    f"Run {experiment_name}/{run_name} files must be a list"
                )
                continue
            for file_name in files:
                if not isinstance(file_name, str):
                    malformed_runs += 1
                    result.errors.append(
                        f"Run {experiment_name}/{run_name} has non-string file entry"
                    )
                    continue
                expected = _contained_path(bundle_dir, file_name)
                if expected is None:
                    malformed_runs += 1
                    result.errors.append(
                        f"Run {experiment_name}/{run_name} has unsafe file path: {file_name!r}"
                    )
                    continue
                if not expected.is_file():
                    missing_files += 1
                    result.errors.append(f"Manifest file reference missing: {expected}")

    result.stats["manifest_experiments"] = len(experiments)
    result.stats["manifest_runs"] = run_count
    result.stats["manifest_missing_fields"] = missing_fields
    result.stats["manifest_missing_files"] = missing_files
    result.stats["manifest_malformed_runs"] = malformed_runs
    result.add_check("manifest_run_fields", missing_fields == 0)
    result.add_check("manifest_run_types", malformed_runs == 0)
    result.add_check("manifest_file_references", missing_files == 0)


def _validate_croissant(
    artifact_root: Path,
    croissant: dict[str, Any],
    result: ArtifactValidationResult,
) -> None:
    missing_core = [field_name for field_name in REQUIRED_CROISSANT_FIELDS if field_name not in croissant]
    missing_rai = [field_name for field_name in REQUIRED_RAI_FIELDS if field_name not in croissant]
    result.add_check(
        "croissant_core_fields",
        not missing_core,
        f"Croissant metadata missing core fields: {', '.join(missing_core)}",
    )
    result.add_check(
        "croissant_rai_fields",
        not missing_rai,
        f"Croissant metadata missing RAI fields: {', '.join(missing_rai)}",
    )
    result.add_check(
        "croissant_dataset_type",
        croissant.get("@type") == "sc:Dataset",
        "Croissant @type must be sc:Dataset",
    )
    result.add_check(
        "croissant_conforms_to_1_1",
        str(croissant.get("conformsTo", "")).endswith("/croissant/1.1"),
        "Croissant conformsTo must target Croissant 1.1",
    )

    distribution = croissant.get("distribution")
    result.add_check(
        "croissant_distribution_list",
        isinstance(distribution, list) and bool(distribution),
        "Croissant distribution must be a non-empty list",
    )
    if not isinstance(distribution, list):
        return

    invalid_distribution_items = [
        str(index) for index, item in enumerate(distribution) if not isinstance(item, dict)
    ]
    result.add_check(
        "croissant_distribution_objects",
        not invalid_distribution_items,
        "Croissant distribution entries must be objects: "
        + ", ".join(invalid_distribution_items),
    )

    file_objects = [
        item
        for item in distribution
        if isinstance(item, dict) and item.get("@type") == "cr:FileObject"
    ]
    file_object_names = {item.get("name") for item in file_objects if isinstance(item.get("name"), str)}
    missing_required_objects = sorted(set(_DISTRIBUTION_PATHS) - file_object_names)
    missing_hashes = []
    failed_hashes = []
    checked_hashes = 0
    for item in file_objects:
        name = item.get("name")
        if not isinstance(name, str):
            result.errors.append("Croissant FileObject missing string name")
            continue
        if not item.get("md5") and not item.get("sha256"):
            missing_hashes.append(name)
        local_rel = _DISTRIBUTION_PATHS.get(name)
        if not local_rel:
            continue
        local_path = _contained_path(artifact_root, local_rel)
        if local_path is None:
            result.errors.append(f"Internal distribution path escapes artifact root: {local_rel}")
            continue
        if not local_path.is_file():
            result.errors.append(f"Croissant local distribution file missing: {local_path}")
            continue
        if item.get("md5"):
            checked_hashes += 1
            if _hash_file(local_path, "md5") != item["md5"]:
                failed_hashes.append(f"{name}:md5")
        if item.get("sha256"):
            checked_hashes += 1
            if _hash_file(local_path, "sha256") != item["sha256"]:
                failed_hashes.append(f"{name}:sha256")

    result.stats["croissant_file_objects"] = len(file_objects)
    result.stats["croissant_hashes_checked"] = checked_hashes
    result.add_check(
        "croissant_required_fileobjects",
        not missing_required_objects,
        "Croissant distribution missing required FileObjects: "
        + ", ".join(missing_required_objects),
    )
    result.add_check(
        "croissant_fileobject_hashes",
        not missing_hashes,
        f"Croissant FileObject entries missing md5/sha256: {', '.join(missing_hashes)}",
    )
    result.add_check(
        "croissant_local_hashes",
        not failed_hashes,
        f"Croissant local checksum mismatch: {', '.join(failed_hashes)}",
    )

    _validate_record_sets(croissant, result)


def _validate_record_sets(croissant: dict[str, Any], result: ArtifactValidationResult) -> None:
    record_sets = croissant.get("recordSet")
    if not isinstance(record_sets, list) or not record_sets:
        return

    invalid_record_sets = []
    for record_set in record_sets:
        fields = record_set.get("field") if isinstance(record_set, dict) else None
        if not isinstance(fields, list) or not fields:
            record_id = (
                record_set.get("@id", "<unknown>") if isinstance(record_set, dict) else "<unknown>"
            )
            invalid_record_sets.append(str(record_id))
            continue
        for field_spec in fields:
            source = field_spec.get("source") if isinstance(field_spec, dict) else None
            if not isinstance(source, dict):
                field_id = field_spec.get("@id", "<unknown>") if isinstance(field_spec, dict) else "<unknown>"
                invalid_record_sets.append(str(field_id))
                continue
            extract = source.get("extract")
            if not isinstance(extract, dict) or not extract.get("column"):
                invalid_record_sets.append(str(field_spec.get("@id", "<unknown>")))

    result.add_check(
        "croissant_record_sources",
        not invalid_record_sets,
        f"Croissant record fields missing source/extract columns: {', '.join(invalid_record_sets)}",
    )


def _hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contained_path(root: Path, relative_path: Any) -> Path | None:
    if not isinstance(relative_path, str):
        return None

    candidate = Path(relative_path)
    if candidate.is_absolute():
        return None

    root_resolved = root.resolve()
    try:
        resolved = (root / candidate).resolve()
        resolved.relative_to(root_resolved)
    except (OSError, ValueError):
        return None
    return resolved


def read_csv_header(path: Path) -> list[str]:
    """Return a CSV header row for tests and future artifact checks."""
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))
