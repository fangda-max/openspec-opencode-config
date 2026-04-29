from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from entropy_audit.config import ProjectConfig
from entropy_audit.lang.java.analyzers import (
    BehaviorAnalyzer,
    CognitionAnalyzer,
    SemanticAnalyzer,
    StructureAnalyzer,
    StyleAnalyzer,
)
from entropy_audit.lang.java.calculator import EntropyCalculator
from entropy_audit.lang.java.details import build_detail_export
from entropy_audit.lang.java.project_profile import SUPPORTED_PROJECT_KINDS, detect_project_profile
from entropy_audit.lang.java.scoring_v1_schema import build_scoring_v1, refresh_scoring_v1_metadata


SUPPORTED_ENTROPIES = ("structure", "semantic", "behavior", "cognition", "style")
PACKAGE_PATTERN = re.compile(r"^\s*package\s+([A-Za-z_][\w.]*)\s*;", re.MULTILINE)
REVERSE_DNS_ROOTS = {"com", "org", "net", "io", "cn"}

DISCOVERY_EXCLUDE_DIRS = [
    ".git",
    ".idea",
    ".history",
    ".cursor",
    ".claude",
    ".codex-temp",
    ".graphify_python",
    "graphify-out",
    "target",
    "node_modules",
    "build",
    "dist",
    "__pycache__",
]

REQUIRED_WEIGHT_KEYS = (
    "structure_entropy",
    "semantic_entropy",
    "behavior_entropy",
    "cognition_entropy",
    "style_entropy",
)

REQUIRED_THRESHOLD_KEYS = (
    "health_score_excellent",
    "health_score_good",
    "health_score_warning",
    "health_score_danger",
    "common_files_warning",
    "common_files_danger",
    "util_files_warning",
    "naming_variance_warning",
    "naming_variance_danger",
    "todo_warning",
    "todo_danger",
    "missing_javadoc_warning",
    "missing_javadoc_danger",
    "cyclomatic_complexity_warning",
    "cyclomatic_complexity_danger",
    "method_lines_warning",
    "method_lines_danger",
    "class_lines_warning",
    "class_lines_danger",
)

BUILTIN_GLOSSARY: dict[str, dict[str, Any]] = {}

VALID_MISSING_GLOSSARY_POLICY = {"term_gap_only", "all_pending", "all_scored"}
VALID_GLOSSARY_MATCH_POSITION = {"any", "prefix", "suffix"}
SUPPORTED_JAVA_INCLUDE_EXTENSIONS = {".java"}
REQUIRED_DETAIL_LIMIT_KEYS = (
    "todo_top_files",
    "todo_items",
    "todo_preview_items",
    "todo_content_chars",
    "large_files",
    "large_methods",
    "directory_top",
    "directory_sample_files",
    "shared_common_files",
    "shared_util_files",
    "duplicate_classes",
    "duplicate_class_files",
    "glossary_terms",
    "term_variant_preview",
    "exception_types",
    "exception_files",
    "top_large_directories",
    "preferred_wrapper_preview",
    "behavior_top_error_patterns",
    "behavior_top_return_formats",
    "behavior_top_exception_types",
    "semantic_undefined_terms",
    "semantic_top_inconsistent",
    "semantic_variant_samples",
    "cycle_groups",
    "cycle_edges",
    "cycle_classes",
)


def _iter_java_files(
    project_root: Path,
    exclude_dirs: set[str],
    include_extensions: set[str],
    limit: int | None = None,
) -> list[Path]:
    files: list[Path] = []
    for path in project_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in include_extensions:
            continue
        try:
            parts = path.relative_to(project_root).parts
        except ValueError:
            continue
        if any(part in exclude_dirs for part in parts):
            continue
        files.append(path)
    if limit is None or len(files) <= limit:
        return files
    return _balanced_sample_paths(project_root, files, limit)


def _balanced_sample_paths(project_root: Path, paths: list[Path], limit: int) -> list[Path]:
    groups: dict[str, list[Path]] = {}
    for path in sorted(paths, key=lambda item: str(item.relative_to(project_root)).lower()):
        parts = path.relative_to(project_root).parts
        group_key = parts[0] if parts else ""
        groups.setdefault(group_key, []).append(path)

    sampled: list[Path] = []
    active_keys = sorted(groups)
    while active_keys and len(sampled) < limit:
        next_keys: list[str] = []
        for key in active_keys:
            bucket = groups[key]
            if bucket:
                sampled.append(bucket.pop(0))
                if len(sampled) >= limit:
                    break
            if bucket:
                next_keys.append(key)
        active_keys = next_keys
    return sampled


def _common_package_prefix(packages: list[str]) -> str:
    if not packages:
        return ""
    split_packages = [pkg.split(".") for pkg in packages if pkg]
    if not split_packages:
        return ""
    prefix: list[str] = []
    for parts in zip(*split_packages):
        if len(set(parts)) != 1:
            break
        prefix.append(parts[0])
    return ".".join(prefix)


def _preferred_internal_package_prefix(packages: list[str]) -> str:
    common_prefix = _common_package_prefix(packages)
    if not common_prefix:
        return ""
    parts = common_prefix.split(".")
    if len(parts) > 3 and parts[0] in REVERSE_DNS_ROOTS:
        root = ".".join(parts[:3])
        covered = sum(1 for package in packages if package == root or package.startswith(f"{root}."))
        if packages and covered / len(packages) >= 0.8:
            return root
    if len(parts) >= 2:
        return common_prefix
    return ""


def discover_internal_package_prefixes(
    project_root: Path,
    exclude_dirs: list[str] | None = None,
    limit: int | None = None,
    include_extensions: list[str] | None = None,
) -> list[str]:
    excluded = set(DISCOVERY_EXCLUDE_DIRS + list(exclude_dirs or []))
    source_extensions = {
        str(value).strip().lower()
        for value in (include_extensions or [".java"])
        if str(value).strip()
    } or {".java"}
    packages: list[str] = []
    top_roots: dict[str, int] = {}
    for path in _iter_java_files(project_root, excluded, source_extensions, limit=limit):
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        match = PACKAGE_PATTERN.search(content)
        if not match:
            continue
        package_name = match.group(1)
        packages.append(package_name)
        root = ".".join(package_name.split(".")[:3])
        if root:
            top_roots[root] = top_roots.get(root, 0) + 1

    preferred_prefix = _preferred_internal_package_prefix(packages)
    if preferred_prefix:
        return [preferred_prefix]
    ranked_roots = sorted(top_roots.items(), key=lambda item: item[1], reverse=True)
    if ranked_roots and packages and ranked_roots[0][1] / len(packages) >= 0.8:
        return [ranked_roots[0][0]]
    return [name for name, _count in ranked_roots[:5]]


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in base.keys() | override.keys():
        base_value = base.get(key)
        override_value = override.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            merged[key] = _deep_merge(base_value, override_value)
        elif key in override:
            merged[key] = override_value
        else:
            merged[key] = base_value
    return merged


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _unique_lower_strings(values: list[str]) -> list[str]:
    return _unique_strings([str(value).strip().lower() for value in values])


def _dict_string_values(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        normalized_key = str(key).strip()
        normalized_value = str(item).strip()
        if not normalized_key or not normalized_value:
            continue
        result[normalized_key] = normalized_value
    return result


def _int_value(value: object, default: int, minimum: int = 1) -> int:
    try:
        return max(int(value or default), minimum)
    except (TypeError, ValueError):
        return default


def _float_value(value: object, default: float, minimum: float | None = None) -> float:
    try:
        result = float(value if value is not None else default)
    except (TypeError, ValueError):
        result = float(default)
    if minimum is not None:
        result = max(result, minimum)
    return result


def _float_any(value: object, default: float) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _int_any(value: object, default: int, minimum: int = 0) -> int:
    try:
        return max(int(value if value is not None else default), minimum)
    except (TypeError, ValueError):
        return max(int(default), minimum)


def _merge_named_items(base_items: list[dict[str, Any]], override_items: object) -> list[dict[str, Any]]:
    merged = [json.loads(json.dumps(item)) for item in base_items if isinstance(item, dict)]
    if not isinstance(override_items, list):
        return merged
    index = {str(item.get("id")): pos for pos, item in enumerate(merged) if item.get("id")}
    for override in override_items:
        if not isinstance(override, dict):
            continue
        item_id = str(override.get("id", "")).strip()
        if item_id and item_id in index:
            merged[index[item_id]] = _deep_merge(merged[index[item_id]], override)
        else:
            merged.append(json.loads(json.dumps(override)))
    return merged


def _stable_hash(payload: object) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def _require_config_dict(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"Missing or invalid {path} section in entropy.config.toml")
    return value


def _require_string_list(values: list[str], path: str) -> list[str]:
    normalized = _unique_strings(values)
    if not normalized:
        raise ValueError(f"{path} must be a non-empty string array in entropy.config.toml")
    return normalized


def _normalize_config_string_list(
    values: list[str],
    path: str,
    *,
    lower: bool = False,
    allow_empty: bool = False,
) -> list[str]:
    normalized = _unique_lower_strings(values) if lower else _unique_strings(values)
    if not normalized and not allow_empty:
        raise ValueError(f"{path} must be a non-empty string array in entropy.config.toml")
    return normalized


def _require_config_string(data: dict[str, Any], key: str, path: str, allowed: set[str] | None = None) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}.{key} must be a non-empty string in entropy.config.toml")
    normalized = value.strip()
    if allowed and normalized not in allowed:
        raise ValueError(f"{path}.{key} must be one of {sorted(allowed)}")
    return normalized


def _require_config_bool(data: dict[str, Any], key: str, path: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be true or false in entropy.config.toml")
    return value


def _require_config_number(
    data: dict[str, Any],
    key: str,
    path: str,
    *,
    minimum: float | None = None,
    integer: bool = False,
) -> float | int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}.{key} must be a number in entropy.config.toml")
    result = int(value) if integer else float(value)
    if minimum is not None and result < minimum:
        comparator = "an integer" if integer else "a number"
        raise ValueError(f"{path}.{key} must be {comparator} >= {minimum}")
    return result


def _build_java_strategy(raw_strategy: dict[str, Any]) -> dict[str, Any]:
    strategy = _require_config_dict(raw_strategy, "[code_entropy.java.strategy]")

    controller = _require_config_dict(strategy.get("controller"), "[code_entropy.java.strategy.controller]")
    controller["file_name_suffixes"] = _require_string_list(_list_value(controller.get("file_name_suffixes")), "[code_entropy.java.strategy.controller.file_name_suffixes]")
    controller["class_annotations"] = _require_string_list(_list_value(controller.get("class_annotations")), "[code_entropy.java.strategy.controller.class_annotations]")
    controller["package_keywords"] = _require_string_list([value.lower() for value in _list_value(controller.get("package_keywords"))], "[code_entropy.java.strategy.controller.package_keywords]")
    controller["detect_by_filename"] = _require_config_bool(controller, "detect_by_filename", "[code_entropy.java.strategy.controller]")
    controller["detect_by_annotation"] = _require_config_bool(controller, "detect_by_annotation", "[code_entropy.java.strategy.controller]")
    controller["detect_by_package"] = _require_config_bool(controller, "detect_by_package", "[code_entropy.java.strategy.controller]")

    return_formats = _require_config_dict(strategy.get("return_formats"), "[code_entropy.java.strategy.return_formats]")
    return_formats["scan_scope"] = _require_config_string(
        return_formats,
        "scan_scope",
        "[code_entropy.java.strategy.return_formats]",
        allowed={"controllers", "all_java"},
    ).lower()
    return_formats["wrapper_types"] = _unique_strings(_list_value(return_formats.get("wrapper_types")))
    return_formats["map_types"] = _require_string_list(_list_value(return_formats.get("map_types")), "[code_entropy.java.strategy.return_formats.map_types]")
    return_formats["collection_types"] = _require_string_list(_list_value(return_formats.get("collection_types")), "[code_entropy.java.strategy.return_formats.collection_types]")
    return_formats["count_scalar_literals"] = _require_config_bool(return_formats, "count_scalar_literals", "[code_entropy.java.strategy.return_formats]")
    return_formats["count_null_returns"] = _require_config_bool(return_formats, "count_null_returns", "[code_entropy.java.strategy.return_formats]")
    return_formats["count_named_references"] = _require_config_bool(return_formats, "count_named_references", "[code_entropy.java.strategy.return_formats]")

    project = _require_config_dict(strategy.get("project"), "[code_entropy.java.strategy.project]")
    project["kind"] = _require_config_string(
        project,
        "kind",
        "[code_entropy.java.strategy.project]",
        allowed=SUPPORTED_PROJECT_KINDS,
    ).lower()
    project["degrade_without_controllers"] = _require_config_bool(
        project,
        "degrade_without_controllers",
        "[code_entropy.java.strategy.project]",
    )
    project["controllerless_return_scope"] = _require_config_string(
        project,
        "controllerless_return_scope",
        "[code_entropy.java.strategy.project]",
        allowed={"skip", "all_java"},
    ).lower()
    project["web_class_annotations"] = _require_string_list(_list_value(project.get("web_class_annotations")), "[code_entropy.java.strategy.project.web_class_annotations]")
    project["web_package_keywords"] = _require_string_list([value.lower() for value in _list_value(project.get("web_package_keywords"))], "[code_entropy.java.strategy.project.web_package_keywords]")
    project["batch_class_annotations"] = _require_string_list(_list_value(project.get("batch_class_annotations")), "[code_entropy.java.strategy.project.batch_class_annotations]")
    project["batch_package_keywords"] = _require_string_list([value.lower() for value in _list_value(project.get("batch_package_keywords"))], "[code_entropy.java.strategy.project.batch_package_keywords]")
    project["batch_class_name_keywords"] = _require_string_list(_list_value(project.get("batch_class_name_keywords")), "[code_entropy.java.strategy.project.batch_class_name_keywords]")
    discovery = _require_config_dict(project.get("discovery"), "[code_entropy.java.strategy.project.discovery]")
    discovery["sample_limit"] = _require_config_number(
        discovery,
        "sample_limit",
        "[code_entropy.java.strategy.project.discovery]",
        integer=True,
        minimum=1,
    )
    project["discovery"] = discovery

    javadoc = _require_config_dict(strategy.get("javadoc"), "[code_entropy.java.strategy.javadoc]")
    javadoc["scope"] = _require_config_string(javadoc, "scope", "[code_entropy.java.strategy.javadoc]").lower()
    if javadoc["scope"] == "types_only":
        javadoc["include_methods"] = False
    elif javadoc["scope"] == "methods_only":
        javadoc["include_classes"] = False
    elif javadoc["scope"] == "all_non_private":
        javadoc["type_visibilities"] = ["public", "protected", "package"]
        javadoc["method_visibilities"] = ["public", "protected", "package"]
    javadoc["include_classes"] = _require_config_bool(javadoc, "include_classes", "[code_entropy.java.strategy.javadoc]")
    javadoc["include_methods"] = _require_config_bool(javadoc, "include_methods", "[code_entropy.java.strategy.javadoc]")
    javadoc["type_visibilities"] = _require_string_list([value.lower() for value in _list_value(javadoc.get("type_visibilities"))], "[code_entropy.java.strategy.javadoc.type_visibilities]")
    javadoc["method_visibilities"] = _require_string_list([value.lower() for value in _list_value(javadoc.get("method_visibilities"))], "[code_entropy.java.strategy.javadoc.method_visibilities]")
    javadoc["type_kinds"] = _require_string_list([value.lower() for value in _list_value(javadoc.get("type_kinds"))], "[code_entropy.java.strategy.javadoc.type_kinds]")
    javadoc["exclude_overrides"] = _require_config_bool(javadoc, "exclude_overrides", "[code_entropy.java.strategy.javadoc]")
    javadoc["class_lookback_chars"] = _require_config_number(
        javadoc,
        "class_lookback_chars",
        "[code_entropy.java.strategy.javadoc]",
        integer=True,
        minimum=1,
    )
    javadoc["method_lookback_chars"] = _require_config_number(
        javadoc,
        "method_lookback_chars",
        "[code_entropy.java.strategy.javadoc]",
        integer=True,
        minimum=1,
    )

    glossary = _require_config_dict(strategy.get("glossary"), "[code_entropy.java.strategy.glossary]")
    glossary["mode"] = _require_config_string(
        glossary,
        "mode",
        "[code_entropy.java.strategy.glossary]",
        allowed={"configured_only", "replace", "merge_default", "disabled"},
    ).lower()
    glossary["min_term_length"] = _require_config_number(
        glossary,
        "min_term_length",
        "[code_entropy.java.strategy.glossary]",
        integer=True,
        minimum=1,
    )
    glossary["variant_threshold"] = _require_config_number(
        glossary,
        "variant_threshold",
        "[code_entropy.java.strategy.glossary]",
        integer=True,
        minimum=1,
    )
    glossary["missing_glossary_policy"] = _require_config_string(
        glossary,
        "missing_glossary_policy",
        "[code_entropy.java.strategy.glossary]",
        allowed=VALID_MISSING_GLOSSARY_POLICY,
    ).lower()
    glossary["ignore_terms"] = _require_string_list(_list_value(glossary.get("ignore_terms")), "[code_entropy.java.strategy.glossary.ignore_terms]")
    term_gap = _require_config_dict(glossary.get("term_gap"), "[code_entropy.java.strategy.glossary.term_gap]")
    term_gap["candidate_mode"] = _require_config_string(
        term_gap,
        "candidate_mode",
        "[code_entropy.java.strategy.glossary.term_gap]",
        allowed={"top_unique_terms", "all_unique_terms"},
    ).lower()
    term_gap["min_occurrences"] = _require_config_number(
        term_gap,
        "min_occurrences",
        "[code_entropy.java.strategy.glossary.term_gap]",
        integer=True,
        minimum=1,
    )
    term_gap["max_candidate_terms"] = _require_config_number(
        term_gap,
        "max_candidate_terms",
        "[code_entropy.java.strategy.glossary.term_gap]",
        integer=True,
        minimum=1,
    )
    term_gap["exclude_terms"] = _normalize_config_string_list(
        _list_value(term_gap.get("exclude_terms")),
        "[code_entropy.java.strategy.glossary.term_gap.exclude_terms]",
        lower=True,
        allow_empty=True,
    )
    glossary["term_gap"] = term_gap

    strategy["controller"] = controller
    strategy["return_formats"] = return_formats
    strategy["project"] = project
    strategy["javadoc"] = javadoc
    strategy["glossary"] = glossary
    return strategy


def _build_glossary(raw_glossary: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    glossary_strategy = _dict_value(strategy.get("glossary"))
    mode = str(glossary_strategy.get("mode") or "").strip().lower()
    normalized: dict[str, Any] = {}
    for term_key, term_config in raw_glossary.items():
        if not isinstance(term_config, dict):
            continue
        normalized_key = str(term_key).strip()
        if not normalized_key:
            continue
        standard = str(term_config.get("standard", "") or "").strip()
        if not standard:
            continue
        variants = _normalize_config_string_list(
            [str(value).strip() for value in _list_value(term_config.get("variants")) if str(value).strip()],
            f"[code_entropy.glossary.{normalized_key}.variants]",
            allow_empty=True,
        )
        match_position = str(term_config.get("match_position", "any") or "any").strip().lower()
        if match_position not in VALID_GLOSSARY_MATCH_POSITION:
            raise ValueError(
                f"[code_entropy.glossary.{normalized_key}.match_position] must be one of: any, prefix, suffix"
            )
        normalized[normalized_key] = {
            "standard": standard,
            "variants": variants,
            "match_position": match_position,
            "description": str(term_config.get("description", "") or "").strip(),
            "used_by": _normalize_glossary_used_by(
                ",".join(str(value) for value in _list_value(term_config.get("used_by"))),
                variants,
            ),
        }
    if mode == "disabled":
        return {}
    if mode == "merge_default":
        return BUILTIN_GLOSSARY | normalized
    return normalized


def _normalize_glossary_header(value: str) -> str:
    normalized = re.sub(r"[\s_\-]+", "", str(value or "").strip().lower())
    aliases = {
        "standard": "standard",
        "term": "standard",
        "name": "standard",
        "标准": "standard",
        "术语": "standard",
        "标准术语": "standard",
        "标准名": "standard",
        "标准词": "standard",
        "variants": "variants",
        "variant": "variants",
        "aliases": "variants",
        "alias": "variants",
        "别名": "variants",
        "变体": "variants",
        "历史命名": "variants",
        "matchposition": "match_position",
        "position": "match_position",
        "匹配位置": "match_position",
        "匹配": "match_position",
        "位置": "match_position",
        "description": "description",
        "desc": "description",
        "说明": "description",
        "描述": "description",
        "含义": "description",
        "usedby": "used_by",
        "useby": "used_by",
        "scope": "used_by",
        "usage": "used_by",
        "用途": "used_by",
        "使用规则": "used_by",
        "规则": "used_by",
    }
    return aliases.get(normalized, normalized)


def _split_glossary_values(value: str) -> list[str]:
    return _unique_strings([item.strip() for item in re.split(r"[,，;；/、]+", str(value or "")) if item.strip()])


def _normalize_glossary_used_by(value: str, variants: list[str]) -> list[str]:
    raw_values = _split_glossary_values(value)
    if not raw_values:
        return ["naming", "term_gap"] if variants else ["term_gap"]
    result: list[str] = []
    for raw_value in raw_values:
        normalized = str(raw_value).strip().lower().replace("-", "_")
        if normalized in {"all", "both", "*", "全部", "两者"}:
            result.extend(["naming", "term_gap"])
        elif normalized in {"naming", "name", "naming_conflict", "命名", "命名冲突"}:
            result.append("naming")
        elif normalized in {"term", "terms", "term_gap", "glossary", "术语", "术语缺口"}:
            result.append("term_gap")
    return _unique_strings(result) or (["naming", "term_gap"] if variants else ["term_gap"])


def _merge_glossary_entry(
    entries: dict[str, Any],
    standard: str,
    variants: list[str],
    match_position: str = "any",
    description: str = "",
    used_by: str = "",
) -> None:
    standard = str(standard or "").strip()
    if not standard:
        return
    variants = _unique_strings([value for value in variants if value and value != standard])
    match_position = str(match_position or "any").strip().lower()
    if match_position not in VALID_GLOSSARY_MATCH_POSITION:
        match_position = "any"
    used_by_values = _normalize_glossary_used_by(used_by, variants)
    key = re.sub(r"\W+", "_", standard.lower()).strip("_") or standard.lower()
    current = entries.get(key)
    if not isinstance(current, dict):
        entries[key] = {
            "standard": standard,
            "variants": variants,
            "match_position": match_position,
            "description": str(description or "").strip(),
            "used_by": used_by_values,
        }
        return
    current_variants = _list_value(current.get("variants"))
    current["variants"] = _unique_strings(current_variants + variants)
    if str(current.get("match_position", "any")).strip().lower() == "any" and match_position != "any":
        current["match_position"] = match_position
    if description and not str(current.get("description", "")).strip():
        current["description"] = str(description).strip()
    current["used_by"] = _unique_strings(_list_value(current.get("used_by")) + used_by_values)


def _parse_glossary_table(lines: list[str], entries: dict[str, Any]) -> None:
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "|" not in line:
            index += 1
            continue
        headers = [cell.strip() for cell in line.strip("|").split("|")]
        mapped_headers = [_normalize_glossary_header(header) for header in headers]
        if "standard" not in mapped_headers:
            index += 1
            continue
        row_index = index + 1
        if row_index < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", lines[row_index]):
            row_index += 1
        while row_index < len(lines):
            row = lines[row_index].strip()
            if "|" not in row or re.match(r"^\s*$", row):
                break
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            if len(cells) < len(headers):
                row_index += 1
                continue
            data = {mapped_headers[pos]: cells[pos] for pos in range(min(len(mapped_headers), len(cells)))}
            standard = data.get("standard", "")
            variants = _split_glossary_values(data.get("variants", ""))
            match_position = data.get("match_position", "any")
            description = data.get("description", "")
            used_by = data.get("used_by", "")
            _merge_glossary_entry(entries, standard, variants, match_position, description, used_by)
            row_index += 1
        index = row_index


def _parse_glossary_bullets(lines: list[str], entries: dict[str, Any]) -> None:
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        body = stripped[1:].strip()
        if not body:
            continue
        parts = [part.strip() for part in re.split(r"\s*;\s*", body) if part.strip()]
        data: dict[str, str] = {}
        for part in parts:
            match = re.match(r"^([^:=]+)\s*[:=]\s*(.+)$", part)
            if not match:
                continue
            key = _normalize_glossary_header(match.group(1))
            data[key] = match.group(2).strip()
        if "standard" not in data and parts:
            match = re.match(r"^([^:=]+)\s*[:=]\s*(.+)$", parts[0])
            if match:
                data["standard"] = match.group(1).strip()
                data.setdefault("variants", match.group(2).strip())
        standard = data.get("standard", "")
        variants = _split_glossary_values(data.get("variants", ""))
        match_position = data.get("match_position", "any")
        description = data.get("description", "")
        used_by = data.get("used_by", "")
        _merge_glossary_entry(entries, standard, variants, match_position, description, used_by)


def _parse_glossary_md(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return {}
    entries: dict[str, Any] = {}
    _parse_glossary_table(lines, entries)
    _parse_glossary_bullets(lines, entries)
    return entries


def _find_project_glossary_files(project_root: Path, exclude_dirs: list[str]) -> list[Path]:
    root_glossary = project_root / "glossary.md"
    if root_glossary.exists() and root_glossary.is_file():
        return [root_glossary]
    excluded = {value.lower() for value in exclude_dirs}
    found: list[Path] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [name for name in dirs if name.lower() not in excluded]
        for file_name in files:
            if file_name.lower() == "glossary.md":
                found.append(Path(root, file_name))
    found = [path for path in found if path.resolve() != root_glossary.resolve()]
    found.sort(key=lambda path: path.relative_to(project_root).as_posix().lower())
    return found


def _build_project_glossary(project_root: Path, exclude_dirs: list[str], strategy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    glossary_files = _find_project_glossary_files(project_root, exclude_dirs)
    raw_glossary: dict[str, Any] = {}
    for glossary_file in glossary_files:
        for _key, value in _parse_glossary_md(glossary_file).items():
            if not isinstance(value, dict):
                continue
            _merge_glossary_entry(
                raw_glossary,
                str(value.get("standard", "") or ""),
                [str(item) for item in _list_value(value.get("variants"))],
                str(value.get("match_position", "any") or "any"),
                str(value.get("description", "") or ""),
                ",".join(str(item) for item in _list_value(value.get("used_by"))),
            )
    glossary = _build_glossary(raw_glossary, strategy) if glossary_files else {}
    source_type = "project_glossary_md"
    if not glossary_files:
        source_type = "missing_project_glossary_md"
    elif not glossary:
        source_type = "empty_project_glossary_md"
    source = {
        "type": source_type,
        "files": [path.relative_to(project_root).as_posix() for path in glossary_files],
        "term_count": len(glossary),
        "missing": not bool(glossary),
    }
    return glossary, source


def _build_java_detectors(raw_detectors: dict[str, Any]) -> dict[str, Any]:
    detectors = _require_config_dict(raw_detectors, "[code_entropy.java.detectors]")

    structure = _require_config_dict(detectors.get("structure"), "[code_entropy.java.detectors.structure]")
    shared_buckets = _require_config_dict(structure.get("shared_buckets"), "[code_entropy.java.detectors.structure.shared_buckets]")
    shared_buckets["match_mode"] = str(shared_buckets.get("match_mode", "") or "").strip().lower()
    if shared_buckets["match_mode"] not in {"segment", "contains"}:
        raise ValueError("[code_entropy.java.detectors.structure.shared_buckets.match_mode] must be 'segment' or 'contains'")
    shared_buckets["shared_aliases"] = _require_string_list(_unique_lower_strings(_list_value(shared_buckets.get("shared_aliases"))), "[code_entropy.java.detectors.structure.shared_buckets.shared_aliases]")
    shared_buckets["utility_aliases"] = _require_string_list(_unique_lower_strings(_list_value(shared_buckets.get("utility_aliases"))), "[code_entropy.java.detectors.structure.shared_buckets.utility_aliases]")
    structure["shared_buckets"] = shared_buckets
    directory_distribution = _require_config_dict(structure.get("directory_distribution"), "[code_entropy.java.detectors.structure.directory_distribution]")
    directory_distribution["oversized_dir_file_threshold"] = int(
        _require_config_number(
            directory_distribution,
            "oversized_dir_file_threshold",
            "[code_entropy.java.detectors.structure.directory_distribution]",
            integer=True,
            minimum=1,
        )
    )
    directory_distribution["top_n_concentration_count"] = int(
        _require_config_number(
            directory_distribution,
            "top_n_concentration_count",
            "[code_entropy.java.detectors.structure.directory_distribution]",
            integer=True,
            minimum=1,
        )
    )
    structure["directory_distribution"] = directory_distribution

    semantic = _require_config_dict(detectors.get("semantic"), "[code_entropy.java.detectors.semantic]")
    term_extraction = _require_config_dict(semantic.get("term_extraction"), "[code_entropy.java.detectors.semantic.term_extraction]")
    scan_targets = _unique_lower_strings(_list_value(term_extraction.get("scan_targets")))
    term_extraction["scan_targets"] = [target for target in scan_targets if target in {"file_stem", "class_name"}]
    if not term_extraction["scan_targets"]:
        raise ValueError("[code_entropy.java.detectors.semantic.term_extraction.scan_targets] must contain file_stem and/or class_name")
    term_extraction["token_patterns"] = _require_string_list(_list_value(term_extraction.get("token_patterns")), "[code_entropy.java.detectors.semantic.term_extraction.token_patterns]")
    term_extraction["naming_ignore_class_suffixes"] = _normalize_config_string_list(
        _list_value(term_extraction.get("naming_ignore_class_suffixes")),
        "[code_entropy.java.detectors.semantic.term_extraction.naming_ignore_class_suffixes]",
        allow_empty=True,
    )
    state_detection = _require_config_dict(semantic.get("state_detection"), "[code_entropy.java.detectors.semantic.state_detection]")
    state_detection["carrier_name_patterns"] = _require_string_list(
        _list_value(state_detection.get("carrier_name_patterns")),
        "[code_entropy.java.detectors.semantic.state_detection.carrier_name_patterns]",
    )
    state_detection["constant_field_pattern"] = str(
        _require_config_string(
            state_detection,
            "constant_field_pattern",
            "[code_entropy.java.detectors.semantic.state_detection]",
        )
    ).strip()
    state_detection["string_literal_pattern"] = str(
        _require_config_string(
            state_detection,
            "string_literal_pattern",
            "[code_entropy.java.detectors.semantic.state_detection]",
        )
    ).strip()
    state_detection["numeric_literal_pattern"] = str(
        _require_config_string(
            state_detection,
            "numeric_literal_pattern",
            "[code_entropy.java.detectors.semantic.state_detection]",
        )
    ).strip()
    state_detection["strip_prefixes"] = _unique_strings(
        [str(value).strip().upper() for value in _list_value(state_detection.get("strip_prefixes")) if str(value).strip()]
    )
    state_detection["strip_suffixes"] = _unique_strings(
        [str(value).strip().upper() for value in _list_value(state_detection.get("strip_suffixes")) if str(value).strip()]
    )
    state_detection["ignore_item_patterns"] = _normalize_config_string_list(
        _list_value(state_detection.get("ignore_item_patterns")),
        "[code_entropy.java.detectors.semantic.state_detection.ignore_item_patterns]",
        allow_empty=True,
    )
    state_detection["min_carrier_items"] = int(
        _require_config_number(
            state_detection,
            "min_carrier_items",
            "[code_entropy.java.detectors.semantic.state_detection]",
            integer=True,
            minimum=1,
        )
    )
    state_detection["min_shared_items"] = int(
        _require_config_number(
            state_detection,
            "min_shared_items",
            "[code_entropy.java.detectors.semantic.state_detection]",
            integer=True,
            minimum=1,
        )
    )
    state_detection["similarity_threshold"] = float(
        _require_config_number(
            state_detection,
            "similarity_threshold",
            "[code_entropy.java.detectors.semantic.state_detection]",
            minimum=0.0,
        )
    )
    if state_detection["similarity_threshold"] > 1.0:
        raise ValueError("[code_entropy.java.detectors.semantic.state_detection.similarity_threshold] must be <= 1.0")
    state_detection["cluster_sample_limit"] = int(
        _require_config_number(
            state_detection,
            "cluster_sample_limit",
            "[code_entropy.java.detectors.semantic.state_detection]",
            integer=True,
            minimum=1,
        )
    )
    state_detection["scatter_sample_limit"] = int(
        _require_config_number(
            state_detection,
            "scatter_sample_limit",
            "[code_entropy.java.detectors.semantic.state_detection]",
            integer=True,
            minimum=1,
        )
    )
    state_detection["hardcoded_context_patterns"] = _normalize_config_string_list(
        _list_value(state_detection.get("hardcoded_context_patterns")),
        "[code_entropy.java.detectors.semantic.state_detection.hardcoded_context_patterns]",
    )
    semantic["term_extraction"] = term_extraction
    semantic["state_detection"] = state_detection

    behavior = _require_config_dict(detectors.get("behavior"), "[code_entropy.java.detectors.behavior]")
    error_patterns = _dict_string_values(behavior.get("error_patterns"))
    if not error_patterns:
        raise ValueError("Missing or invalid [code_entropy.java.detectors.behavior.error_patterns] section in entropy.config.toml")
    return_patterns = _require_config_dict(behavior.get("return_patterns"), "[code_entropy.java.detectors.behavior.return_patterns]")
    required_return_pattern_keys = {"string_literal_pattern", "boolean_literal_pattern", "null_return_pattern", "named_reference_pattern", "exception_pattern"}
    normalized_return_patterns = {
        key: str(return_patterns.get(key, "") or "").strip()
        for key in required_return_pattern_keys
    }
    if not all(normalized_return_patterns.values()):
        raise ValueError("[code_entropy.java.detectors.behavior.return_patterns] must provide all required regex patterns")
    wrapped_error_responses = _require_config_dict(
        behavior.get("wrapped_error_responses"),
        "[code_entropy.java.detectors.behavior.wrapped_error_responses]",
    )
    wrapped_error_responses["method_names"] = _require_string_list(
        _list_value(wrapped_error_responses.get("method_names")),
        "[code_entropy.java.detectors.behavior.wrapped_error_responses.method_names]",
    )
    wrapped_error_responses["include_return_only"] = _require_config_bool(
        wrapped_error_responses,
        "include_return_only",
        "[code_entropy.java.detectors.behavior.wrapped_error_responses]",
    )
    behavior["error_patterns"] = error_patterns
    behavior["return_patterns"] = normalized_return_patterns
    behavior["wrapped_error_responses"] = wrapped_error_responses

    cognition = _require_config_dict(detectors.get("cognition"), "[code_entropy.java.detectors.cognition]")
    debt_markers = _dict_string_values(cognition.get("debt_markers"))
    if not debt_markers:
        raise ValueError("Missing or invalid [code_entropy.java.detectors.cognition.debt_markers] section in entropy.config.toml")
    debt_markers = {str(key).strip().lower(): value for key, value in debt_markers.items() if str(key).strip()}
    owner_patterns = _require_string_list(_list_value(cognition.get("owner_patterns")), "[code_entropy.java.detectors.cognition.owner_patterns]")
    complexity = _require_config_dict(cognition.get("complexity"), "[code_entropy.java.detectors.cognition.complexity]")
    complexity["large_method_lines_threshold"] = _require_config_number(
        complexity,
        "large_method_lines_threshold",
        "[code_entropy.java.detectors.cognition.complexity]",
        integer=True,
        minimum=1,
    )
    complexity["large_class_lines_threshold"] = _require_config_number(
        complexity,
        "large_class_lines_threshold",
        "[code_entropy.java.detectors.cognition.complexity]",
        integer=True,
        minimum=1,
    )
    complexity["large_file_lines_threshold"] = _require_config_number(
        complexity,
        "large_file_lines_threshold",
        "[code_entropy.java.detectors.cognition.complexity]",
        integer=True,
        minimum=1,
    )
    complexity["large_file_warning_threshold"] = _require_config_number(
        complexity,
        "large_file_warning_threshold",
        "[code_entropy.java.detectors.cognition.complexity]",
        integer=True,
        minimum=1,
    )
    complexity["large_file_danger_threshold"] = _require_config_number(
        complexity,
        "large_file_danger_threshold",
        "[code_entropy.java.detectors.cognition.complexity]",
        integer=True,
        minimum=1,
    )
    complexity["method_signature_pattern"] = _require_config_string(
        complexity,
        "method_signature_pattern",
        "[code_entropy.java.detectors.cognition.complexity]",
    )
    cognition["debt_markers"] = debt_markers
    cognition["owner_patterns"] = owner_patterns
    cognition["complexity"] = complexity

    style = _require_config_dict(detectors.get("style"), "[code_entropy.java.detectors.style]")
    checkstyle = _require_config_dict(style.get("checkstyle"), "[code_entropy.java.detectors.style.checkstyle]")
    checkstyle["enabled"] = _require_config_bool(
        checkstyle,
        "enabled",
        "[code_entropy.java.detectors.style.checkstyle]",
    )
    checkstyle["mode"] = str(checkstyle.get("mode", "auto")).strip().lower() or "auto"
    checkstyle["java_version_policy"] = str(checkstyle.get("java_version_policy", "jdk8_or_jdk17")).strip().lower()
    for key in ["jdk8_jar", "jdk8_config", "jdk8_workdir", "jdk17_jar", "jdk17_config", "jdk17_workdir", "output_format", "unknown_module_category"]:
        value = checkstyle.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"[code_entropy.java.detectors.style.checkstyle].{key} must be a non-empty string in entropy.config.toml")
        checkstyle[key] = value.strip()
    checkstyle["include_severities"] = [
        value.lower()
        for value in _require_string_list(
            _list_value(checkstyle.get("include_severities")),
            "[code_entropy.java.detectors.style.checkstyle.include_severities]",
        )
    ]
    checkstyle["scan_extensions"] = [
        value.lower()
        for value in _require_string_list(
            _list_value(checkstyle.get("scan_extensions")),
            "[code_entropy.java.detectors.style.checkstyle.scan_extensions]",
        )
    ]
    checkstyle["exclude_modules"] = _require_string_list(
        _list_value(checkstyle.get("exclude_modules")),
        "[code_entropy.java.detectors.style.checkstyle.exclude_modules]",
    )
    categories = _require_config_dict(
        checkstyle.get("categories"),
        "[code_entropy.java.detectors.style.checkstyle.categories]",
    )
    normalized_categories = {}
    for category_id, raw_category in categories.items():
        category_path = f"[code_entropy.java.detectors.style.checkstyle.categories.{category_id}]"
        category = _require_config_dict(raw_category, category_path)
        label = category.get("label")
        description = category.get("description")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"{category_path}.label must be a non-empty string in entropy.config.toml")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"{category_path}.description must be a non-empty string in entropy.config.toml")
        normalized_categories[str(category_id).strip()] = {
            "label": label.strip(),
            "description": description.strip(),
            "modules": _require_string_list(_list_value(category.get("modules")), f"{category_path}.modules"),
        }
    checkstyle["categories"] = normalized_categories
    style["checkstyle"] = checkstyle

    detectors["structure"] = structure
    detectors["semantic"] = semantic
    detectors["behavior"] = behavior
    detectors["cognition"] = cognition
    detectors["style"] = style
    return detectors


def _build_java_switches(raw_switches: object) -> dict[str, Any]:
    return dict(raw_switches) if isinstance(raw_switches, dict) else {}


def _build_java_detail_export(raw_detail_export: object) -> dict[str, Any]:
    detail_export = _require_config_dict(raw_detail_export, "[code_entropy.java.detail_export]")
    limits = _require_config_dict(detail_export.get("limits"), "[code_entropy.java.detail_export.limits]")
    return {
        "limits": {
            key: _require_config_number(
                limits,
                key,
                "[code_entropy.java.detail_export.limits]",
                integer=True,
                minimum=1,
            )
            for key in REQUIRED_DETAIL_LIMIT_KEYS
        }
    }


def _build_java_include_extensions(raw_values: object) -> list[str]:
    include_extensions = _normalize_config_string_list(
        _list_value(raw_values),
        "[code_entropy.include_extensions]",
        lower=True,
    )
    normalized = list(dict.fromkeys(include_extensions))
    unsupported = sorted(value for value in normalized if value not in SUPPORTED_JAVA_INCLUDE_EXTENSIONS)
    if unsupported or ".java" not in normalized:
        raise ValueError(
            "[code_entropy.include_extensions] for the built-in Java analyzer must currently be exactly ['.java']"
        )
    return normalized


def _disable_scoring_v1_rule(scoring_v1: dict[str, Any] | None, dimension: str, rule_id: str) -> None:
    if not isinstance(scoring_v1, dict):
        return
    dimensions = _dict_value(scoring_v1.get("dimensions"))
    dimension_config = _dict_value(dimensions.get(dimension))
    rules = dimension_config.get("rules", [])
    if not isinstance(rules, list):
        return
    for rule in rules:
        if isinstance(rule, dict) and str(rule.get("id", "")).strip() == rule_id:
            rule["state"] = "disabled"


def _disable_scoring_v1_metric(scoring_v1: dict[str, Any] | None, dimension: str, metric_id: str) -> None:
    if not isinstance(scoring_v1, dict):
        return
    dimensions = _dict_value(scoring_v1.get("dimensions"))
    dimension_config = _dict_value(dimensions.get(dimension))
    metrics = _dict_value(dimension_config.get("metrics"))
    metric = _dict_value(metrics.get(metric_id))
    if metric:
        metric["enabled"] = False
        metrics[metric_id] = metric
        dimension_config["metrics"] = metrics
        dimensions[dimension] = dimension_config
        scoring_v1["dimensions"] = dimensions


def _apply_java_switches(
    switches: dict[str, Any],
    detectors: dict[str, Any],
    scoring_v1: dict[str, Any] | None = None,
) -> None:
    return None


def _build_weights(raw_weights: object) -> dict[str, float]:
    weights = _require_config_dict(raw_weights, "[code_entropy.weights]")
    normalized = {
        key: float(_require_config_number(weights, key, "[code_entropy.weights]", minimum=0.0))
        for key in REQUIRED_WEIGHT_KEYS
    }
    if sum(normalized.values()) <= 0:
        raise ValueError("[code_entropy.weights] must provide a positive total weight")
    return normalized


def _build_thresholds(raw_thresholds: object) -> dict[str, float]:
    thresholds = _require_config_dict(raw_thresholds, "[code_entropy.thresholds]")
    return {
        key: float(_require_config_number(thresholds, key, "[code_entropy.thresholds]"))
        for key in REQUIRED_THRESHOLD_KEYS
    }


def _build_score_models(raw_score_models: object) -> dict[str, Any]:
    score_models = _require_config_dict(raw_score_models, "[code_entropy.score_models]")
    health = _require_config_dict(score_models.get("health"), "[code_entropy.score_models.health]")
    aggregation = _require_config_string(health, "aggregation", "[code_entropy.score_models.health]", allowed={"weighted_average"}).lower()
    return {
        "health": {
            "formula_version": _require_config_string(health, "formula_version", "[code_entropy.score_models.health]"),
            "aggregation": aggregation,
            "invert_scores": _require_config_bool(health, "invert_scores", "[code_entropy.score_models.health]"),
            "entropy_score_scale": float(_require_config_number(health, "entropy_score_scale", "[code_entropy.score_models.health]", minimum=1e-9)),
            "output_scale": float(_require_config_number(health, "output_scale", "[code_entropy.score_models.health]", minimum=1e-9)),
            "normalize_weights": _require_config_bool(health, "normalize_weights", "[code_entropy.score_models.health]"),
            "round_digits": _require_config_number(health, "round_digits", "[code_entropy.score_models.health]", integer=True, minimum=0),
        }
    }


def build_monitor_config(project_root: Path, project_config: ProjectConfig) -> dict[str, Any]:
    raw_section = _dict_value(project_config.raw.get("code_entropy"))
    raw_weights = raw_section.get("weights")
    raw_score_models = raw_section.get("score_models")
    raw_thresholds = raw_section.get("thresholds")
    raw_glossary = _dict_value(raw_section.get("glossary"))
    raw_java = _dict_value(raw_section.get("java"))
    raw_switches = raw_java.get("switches")
    raw_strategy = raw_java.get("strategy")
    raw_detectors = raw_java.get("detectors")
    raw_detail_export = raw_java.get("detail_export")
    weights = _build_weights(raw_weights)
    score_models = _build_score_models(raw_score_models)
    thresholds = _build_thresholds(raw_thresholds)
    exclude_dirs = _normalize_config_string_list(
        _list_value(raw_section.get("exclude_dirs")),
        "[code_entropy.exclude_dirs]",
        allow_empty=True,
    )
    include_extensions = _build_java_include_extensions(raw_section.get("include_extensions"))
    internal_package_prefixes = _normalize_config_string_list(
        _list_value(raw_section.get("internal_package_prefixes")),
        "[code_entropy.internal_package_prefixes]",
        allow_empty=True,
    )
    strategy = _build_java_strategy(raw_strategy)
    detectors = _build_java_detectors(raw_detectors)
    detail_export = _build_java_detail_export(raw_detail_export)
    configured_glossary = _build_glossary(raw_glossary, strategy)
    glossary, glossary_source = _build_project_glossary(project_root, exclude_dirs, strategy)
    glossary_source["configured_term_count"] = len(configured_glossary)
    switches = _build_java_switches(raw_switches)
    raw_scoring_v1 = raw_section.get("scoring_v1")
    scoring_v1 = build_scoring_v1(raw_scoring_v1, source_path=project_root / "entropy.config.toml")
    _apply_java_switches(switches, detectors, scoring_v1)
    scoring_v1 = refresh_scoring_v1_metadata(scoring_v1)
    project_discovery = _require_config_dict(_dict_value(strategy.get("project")).get("discovery"), "[code_entropy.java.strategy.project.discovery]")
    project_profile_sample_limit = int(project_discovery["sample_limit"])
    project_profile = detect_project_profile(
        project_root,
        exclude_dirs,
        include_extensions,
        strategy,
        project_profile_sample_limit,
    )
    detector_hash = _stable_hash(detectors)
    score_model_hash = _stable_hash(score_models)
    scoring_v1_hash = (
        str(scoring_v1.get("config_hash", "") or _stable_hash(scoring_v1))
        if isinstance(scoring_v1, dict) and scoring_v1.get("enabled")
        else None
    )
    rule_hash = _stable_hash(
        {
            "strategy": strategy,
            "detectors": detectors,
            "glossary": glossary,
            "glossary_source": glossary_source,
            "switches": switches,
            "scoring_v1": scoring_v1,
        }
    )
    summary_hash = _stable_hash(
        {
            "rule_hash": rule_hash,
            "weights": weights,
            "score_models": score_model_hash,
        }
    )

    return {
        "project": {
            "root": str(project_root),
            "name": project_config.project_name,
            "exclude_dirs": exclude_dirs,
            "include_extensions": include_extensions,
            "internal_package_prefixes": internal_package_prefixes,
        },
        "weights": weights,
        "score_models": score_models,
        "thresholds": thresholds,
        "glossary": glossary,
        "glossary_source": glossary_source,
        "strategy": strategy,
        "detectors": detectors,
        "detail_export": detail_export,
        "switches": switches,
        "scoring_v1": scoring_v1,
        "meta": {
            "rule_hash": rule_hash,
            "summary_hash": summary_hash,
            "detector_hash": detector_hash,
            "score_model_hash": score_model_hash,
            "scoring_v1_hash": scoring_v1_hash,
            "glossary_mode": strategy["glossary"]["mode"],
            "glossary_source": glossary_source,
            "feature_switches": switches,
            "project_kind": project_profile["kind"],
            "project_detection_mode": project_profile["detection_mode"],
            "controller_candidates": project_profile["controller_candidates"],
            "web_indicators": project_profile["web_indicators"],
            "batch_indicators": project_profile["batch_indicators"],
            "project_profile_sampled_files": project_profile["files_sampled"],
            "project_profile_sample_limit": project_profile_sample_limit,
            "scoring_v1_dimensions": list(scoring_v1.get("migrated_dimensions", [])) if isinstance(scoring_v1, dict) else [],
        },
    }


def analyze_code_entropy(project_root: Path, project_config: ProjectConfig) -> dict[str, Any]:
    monitor_config = build_monitor_config(project_root, project_config)
    results: dict[str, Any] = {
        "structure": StructureAnalyzer(monitor_config).analyze(),
        "semantic": SemanticAnalyzer(monitor_config).analyze(),
        "behavior": BehaviorAnalyzer(monitor_config).analyze(),
        "cognition": CognitionAnalyzer(monitor_config).analyze(),
        "style": StyleAnalyzer(monitor_config).analyze(),
    }
    meta = dict(_dict_value(monitor_config.get("meta")))
    meta["formula_versions"] = {
        name: _dict_value(results.get(name, {})).get("score_breakdown", {}).get("formula_version")
        for name in SUPPORTED_ENTROPIES
    }
    meta["formula_versions"]["health"] = _dict_value(_dict_value(monitor_config.get("score_models")).get("health")).get("formula_version")
    meta["formula_versions"]["scoring_v1"] = _dict_value(monitor_config.get("scoring_v1")).get("formula_version")
    meta["rule_counts"] = {
        name: _dict_value(results.get(name, {})).get("score_breakdown", {}).get("rule_count")
        for name in SUPPORTED_ENTROPIES
    }
    results["summary"] = EntropyCalculator(monitor_config).calculate_summary(results)
    results["details_export"] = build_detail_export(project_root, monitor_config, results)
    results["meta"] = meta
    results["timestamp"] = datetime.now().isoformat()
    results["date"] = datetime.now().strftime("%Y-%m-%d")
    results["source"] = "entropy_audit.lang.java.internal_entropy"
    return results


def build_code_entropy_export(payload: dict[str, Any]) -> dict[str, Any]:
    export: dict[str, Any] = {}
    for name in SUPPORTED_ENTROPIES:
        item = payload.get(name, {})
        if not isinstance(item, dict):
            item = {}
        export[name] = {
            "score": item.get("score"),
            "level": item.get("level"),
            "score_status": item.get("score_status"),
            "coverage": item.get("coverage"),
            "missing_rule_ids": item.get("missing_rule_ids"),
            "partial_reason": item.get("partial_reason"),
            "score_breakdown": item.get("score_breakdown") if isinstance(item.get("score_breakdown"), dict) else {},
            "details": item.get("details") if isinstance(item.get("details"), dict) else {},
            "metrics": item.get("metrics") if isinstance(item.get("metrics"), dict) else {},
            "facts": item.get("facts") if isinstance(item.get("facts"), dict) else {},
            "scoring_v1": item.get("scoring_v1") if isinstance(item.get("scoring_v1"), dict) else {},
            "metric_definitions": item.get("metric_definitions") if isinstance(item.get("metric_definitions"), dict) else {},
        }

    summary = payload.get("summary")
    if isinstance(summary, dict):
        export["summary"] = summary
    for key in ("timestamp", "date", "source"):
        if payload.get(key) is not None:
            export[key] = payload[key]
    meta = payload.get("meta")
    if isinstance(meta, dict):
        export["meta"] = meta
    details_export = payload.get("details_export")
    if isinstance(details_export, dict):
        export["details_export"] = details_export
    return export
