#!/usr/bin/env python3
"""
Unify Codex history/provider buckets across provider switches.

Default mode is dry-run. Use --apply to modify files. On apply, the script
creates a timestamped backup under ~/.codex/provider-history-backups/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_RESERVED_ALIAS = "openai-custom"
DEFAULT_TARGET = DEFAULT_RESERVED_ALIAS
BUILTIN_OPENAI_PROVIDER = "openai"
RESERVED_BUILTIN_PROVIDERS = {
    "amazon-bedrock",
    "openai",
    "lmstudio",
    "ollama",
    "ollama-chat",
    "oss",
}
DEFAULT_EXCLUDES = RESERVED_BUILTIN_PROVIDERS - {BUILTIN_OPENAI_PROVIDER}


MODEL_PROVIDER_RE = re.compile(r'^(\s*model_provider\s*=\s*)(["\'])([^"\']+)(["\'])(.*)$')
MODEL_PROVIDER_TABLE_RE = re.compile(r"^(\s*\[model_providers\.)([^\]]+)(\].*)$")


@dataclass
class JsonlChange:
    path: Path
    replacements: int


@dataclass
class SqliteChange:
    path: Path
    rows: int


@dataclass
class Plan:
    codex_home: Path
    target: str
    sources: set[str]
    live_provider: str
    live_provider_explicit: bool
    reserved_table_repairs: dict[str, str] = field(default_factory=dict)
    missing_live_provider_repair: str | None = None
    config_before: str | None = None
    config_after: str | None = None
    jsonl_changes: list[JsonlChange] = field(default_factory=list)
    sqlite_changes: list[SqliteChange] = field(default_factory=list)
    discovered: set[str] = field(default_factory=set)

    @property
    def config_changed(self) -> bool:
        return self.config_before is not None and self.config_after is not None and self.config_before != self.config_after

    def total_changes(self) -> int:
        return (
            int(self.config_changed)
            + sum(change.replacements for change in self.jsonl_changes)
            + sum(change.rows for change in self.sqlite_changes)
        )


def codex_home_from_args(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return Path.home() / ".codex"


def is_windows_codex_running() -> bool:
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            capture_output=True,
            check=False,
        ).stdout.lower()
    except Exception:
        return False
    return "codex.exe" in out or "codex-cli" in out or "codex_cli" in out


def normalize_table_key(key: str) -> str:
    return key.strip().strip('"').strip("'")


def collect_from_config(config_text: str) -> set[str]:
    found: set[str] = set()
    for line in config_text.splitlines():
        match = MODEL_PROVIDER_RE.match(line)
        if match:
            found.add(match.group(3))
            continue
        match = MODEL_PROVIDER_TABLE_RE.match(line)
        if match:
            found.add(normalize_table_key(match.group(2)))
    return found


def provider_tables_from_config(config_text: str) -> set[str]:
    found: set[str] = set()
    for line in config_text.splitlines():
        match = MODEL_PROVIDER_TABLE_RE.match(line)
        if match:
            found.add(normalize_table_key(match.group(2)))
    return found


def active_provider_from_config(config_text: str | None) -> tuple[str, bool]:
    if config_text:
        for line in config_text.splitlines():
            match = MODEL_PROVIDER_RE.match(line)
            if match:
                return match.group(3), True
    return BUILTIN_OPENAI_PROVIDER, False


def safe_reserved_alias(source: str, requested: str, existing: set[str]) -> str:
    alias = normalize_table_key(requested) or f"{source}-custom"
    if alias in RESERVED_BUILTIN_PROVIDERS or alias == source:
        alias = f"{source}-custom"
    if alias not in existing:
        return alias

    index = 2
    while f"{alias}-{index}" in existing:
        index += 1
    return f"{alias}-{index}"


def reserved_table_repairs_from_config(config_text: str | None, reserved_alias: str) -> dict[str, str]:
    if not config_text:
        return {}

    tables = provider_tables_from_config(config_text)
    repairs: dict[str, str] = {}
    for key in sorted(tables & RESERVED_BUILTIN_PROVIDERS):
        alias = safe_reserved_alias(key, reserved_alias if key == BUILTIN_OPENAI_PROVIDER else f"{key}-custom", tables | set(repairs.values()))
        repairs[key] = alias
    return repairs


def missing_live_provider_from_config(config_text: str | None) -> str | None:
    if not config_text:
        return None
    live_provider, explicit = active_provider_from_config(config_text)
    if not explicit or live_provider in RESERVED_BUILTIN_PROVIDERS:
        return None
    if live_provider not in provider_tables_from_config(config_text):
        return live_provider
    return None


def resolve_target(target_arg: str, config_text: str | None, reserved_alias: str) -> tuple[str, str, bool, dict[str, str], str | None]:
    live_provider, explicit = active_provider_from_config(config_text)
    repairs = reserved_table_repairs_from_config(config_text, reserved_alias)
    missing_live_provider = missing_live_provider_from_config(config_text)
    if missing_live_provider:
        live_provider = BUILTIN_OPENAI_PROVIDER
        explicit = False
    effective_live_provider = repairs.get(live_provider, live_provider)
    if target_arg in {"current", "auto"}:
        return effective_live_provider, effective_live_provider, explicit, repairs, missing_live_provider
    return target_arg, effective_live_provider, explicit, repairs, missing_live_provider


def rewrite_config(config_text: str, sources: set[str], target: str) -> tuple[str, int]:
    if target in RESERVED_BUILTIN_PROVIDERS:
        return config_text, 0

    changed = 0
    target_headers = {
        f"[model_providers.{target}]",
        f'[model_providers."{target}"]',
        f"[model_providers.'{target}']",
    }
    has_target_table = any(line.strip() in target_headers for line in config_text.splitlines())
    lines: list[str] = []

    for line in config_text.splitlines(keepends=True):
        newline = "\n" if line.endswith("\n") else ""
        body = line[:-1] if newline else line

        match = MODEL_PROVIDER_RE.match(body)
        if match and match.group(3) in sources:
            body = f"{match.group(1)}{match.group(2)}{target}{match.group(4)}{match.group(5)}"
            changed += 1
            lines.append(body + newline)
            continue

        match = MODEL_PROVIDER_TABLE_RE.match(body)
        if match:
            key = normalize_table_key(match.group(2))
            if key in sources:
                if has_target_table:
                    # Do not create duplicate target tables. Leave the table name as-is
                    # and let SQLite/history unification still work. The common case has
                    # no target table, so this branch is intentionally conservative.
                    lines.append(body + newline)
                    continue
                body = f"{match.group(1)}{target}{match.group(3)}"
                changed += 1
                lines.append(body + newline)
                continue

        lines.append(body + newline)

    return "".join(lines), changed


def has_model_provider(config_text: str) -> bool:
    return any(MODEL_PROVIDER_RE.match(line) for line in config_text.splitlines())


def default_provider_table(provider: str) -> str:
    return (
        f"\n[model_providers.{provider}]\n"
        f'name = "{provider}"\n'
        'wire_api = "responses"\n'
        "requires_openai_auth = true\n"
    )


def ensure_config_provider(config_text: str, target: str) -> tuple[str, int]:
    if target in RESERVED_BUILTIN_PROVIDERS:
        return config_text, 0

    changed = 0
    result = config_text
    if not has_model_provider(result):
        result = f'model_provider = "{target}"\n' + result
        changed += 1

    if target not in provider_tables_from_config(result):
        if result and not result.endswith("\n"):
            result += "\n"
        result += default_provider_table(target)
        changed += 1

    return result, changed


def rewrite_config_provider_keys(config_text: str, replacements: dict[str, str]) -> tuple[str, int]:
    replacements = {
        source: target
        for source, target in replacements.items()
        if source and target and source != target and target not in RESERVED_BUILTIN_PROVIDERS
    }
    if not replacements:
        return config_text, 0

    changed = 0
    lines: list[str] = []
    for line in config_text.splitlines(keepends=True):
        newline = "\n" if line.endswith("\n") else ""
        body = line[:-1] if newline else line

        match = MODEL_PROVIDER_RE.match(body)
        if match and match.group(3) in replacements:
            body = f"{match.group(1)}{match.group(2)}{replacements[match.group(3)]}{match.group(4)}{match.group(5)}"
            changed += 1
            lines.append(body + newline)
            continue

        match = MODEL_PROVIDER_TABLE_RE.match(body)
        if match:
            key = normalize_table_key(match.group(2))
            if key in replacements:
                body = f"{match.group(1)}{replacements[key]}{match.group(3)}"
                changed += 1
                lines.append(body + newline)
                continue

        lines.append(body + newline)

    return "".join(lines), changed


def remove_top_level_model_provider(config_text: str, provider: str) -> tuple[str, int]:
    changed = 0
    lines: list[str] = []
    for line in config_text.splitlines(keepends=True):
        newline = "\n" if line.endswith("\n") else ""
        body = line[:-1] if newline else line
        match = MODEL_PROVIDER_RE.match(body)
        if match and match.group(3) == provider:
            changed += 1
            continue
        lines.append(line)
    return "".join(lines), changed


def update_json_model_provider(value: Any, sources: set[str], target: str) -> int:
    count = 0
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key == "model_provider" and isinstance(item, str) and item in sources:
                value[key] = target
                count += 1
            else:
                count += update_json_model_provider(item, sources, target)
    elif isinstance(value, list):
        for item in value:
            count += update_json_model_provider(item, sources, target)
    return count


def jsonl_files(codex_home: Path) -> list[Path]:
    files: list[Path] = []
    for name in ("sessions", "archived_sessions"):
        root = codex_home / name
        if root.exists():
            files.extend(root.rglob("*.jsonl"))
    return sorted(files)


def scan_jsonl(path: Path) -> tuple[set[str], int, list[str] | None]:
    found: set[str] = set()
    replacements = 0
    rewritten: list[str] = []
    changed_any = False

    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "model_provider" not in raw:
            rewritten.append(raw)
            continue
        try:
            value = json.loads(raw)
        except Exception:
            rewritten.append(raw)
            continue
        collect_json_providers(value, found)
        before = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        # Placeholder; actual sources are applied in plan_jsonl_changes.
        rewritten.append(before)
    return found, replacements, rewritten if changed_any else None


def collect_json_providers(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "model_provider" and isinstance(item, str):
                found.add(item)
            else:
                collect_json_providers(item, found)
    elif isinstance(value, list):
        for item in value:
            collect_json_providers(item, found)


def rewrite_jsonl(path: Path, sources: set[str], target: str) -> tuple[int, str | None]:
    replacements = 0
    out_lines: list[str] = []
    changed_any = False

    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "model_provider" not in raw:
            out_lines.append(raw)
            continue
        try:
            value = json.loads(raw)
        except Exception:
            out_lines.append(raw)
            continue
        count = update_json_model_provider(value, sources, target)
        replacements += count
        if count:
            changed_any = True
            out_lines.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        else:
            out_lines.append(raw)

    if not changed_any:
        return 0, None
    return replacements, "\n".join(out_lines) + "\n"


def sqlite_files(codex_home: Path) -> list[Path]:
    return sorted(codex_home.glob("state_*.sqlite"))


def sqlite_provider_counts(path: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        tables = {row[0] for row in cur.execute("select name from sqlite_master where type='table'")}
        if "threads" not in tables:
            return {}
        cols = {row[1] for row in cur.execute("pragma table_info(threads)")}
        if "model_provider" not in cols:
            return {}
        return {str(k): int(v) for k, v in cur.execute("select model_provider, count(*) from threads group by model_provider")}
    finally:
        con.close()


def plan_changes(codex_home: Path, target_arg: str, sources_arg: list[str] | None, excludes: set[str], reserved_alias: str) -> Plan:
    config_path = codex_home / "config.toml"
    discovered: set[str] = set()
    config_before = config_path.read_text(encoding="utf-8", errors="ignore") if config_path.exists() else None
    target, live_provider, live_provider_explicit, reserved_table_repairs, missing_live_provider_repair = resolve_target(target_arg, config_before, reserved_alias)
    if config_before:
        discovered |= collect_from_config(config_before)

    for path in jsonl_files(codex_home):
        try:
            found, _, _ = scan_jsonl(path)
            discovered |= found
        except Exception:
            continue

    for path in sqlite_files(codex_home):
        try:
            discovered |= set(sqlite_provider_counts(path))
        except Exception:
            continue

    sources = set(sources_arg or [])
    if not sources:
        sources = {p for p in discovered if p and p != target and p not in excludes}

    plan = Plan(
        codex_home=codex_home,
        target=target,
        sources=sources,
        live_provider=live_provider,
        live_provider_explicit=live_provider_explicit,
        reserved_table_repairs=reserved_table_repairs,
        missing_live_provider_repair=missing_live_provider_repair,
        discovered=discovered,
    )
    if config_before is not None:
        config_after, _ = rewrite_config_provider_keys(config_before, reserved_table_repairs)
        if missing_live_provider_repair:
            if target == missing_live_provider_repair and target not in RESERVED_BUILTIN_PROVIDERS:
                config_after, _ = ensure_config_provider(config_after, target)
            else:
                config_after, _ = remove_top_level_model_provider(config_after, missing_live_provider_repair)
        config_after, _ = rewrite_config(config_after, sources - set(reserved_table_repairs), target)
        config_after, _ = ensure_config_provider(config_after, target)
        plan.config_before = config_before
        plan.config_after = config_after

    for path in jsonl_files(codex_home):
        try:
            replacements, _ = rewrite_jsonl(path, sources, target)
        except Exception as exc:
            print(f"[warn] failed to scan jsonl {path}: {exc}", file=sys.stderr)
            continue
        if replacements:
            plan.jsonl_changes.append(JsonlChange(path, replacements))

    for path in sqlite_files(codex_home):
        try:
            counts = sqlite_provider_counts(path)
        except Exception as exc:
            print(f"[warn] failed to scan sqlite {path}: {exc}", file=sys.stderr)
            continue
        rows = sum(count for provider, count in counts.items() if provider in sources)
        if rows:
            plan.sqlite_changes.append(SqliteChange(path, rows))

    return plan


def make_backup(plan: Plan) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = plan.codex_home / "provider-history-backups" / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "target": plan.target,
        "sources": sorted(plan.sources),
        "files": [],
    }

    zip_path = backup_dir / "files.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        paths: set[Path] = set()
        if plan.config_changed:
            paths.add(plan.codex_home / "config.toml")
        paths.update(change.path for change in plan.jsonl_changes)
        paths.update(change.path for change in plan.sqlite_changes)
        for db in list(paths):
            if db.suffix == ".sqlite":
                for suffix in ("-wal", "-shm"):
                    extra = Path(str(db) + suffix)
                    if extra.exists():
                        paths.add(extra)
        for path in sorted(paths):
            if not path.exists():
                continue
            rel = path.relative_to(plan.codex_home)
            zf.write(path, rel.as_posix())
            manifest["files"].append(rel.as_posix())

    (backup_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup_dir


def apply_plan(plan: Plan) -> None:
    if plan.config_changed:
        (plan.codex_home / "config.toml").write_text(plan.config_after or "", encoding="utf-8")

    for change in plan.jsonl_changes:
        replacements, content = rewrite_jsonl(change.path, plan.sources, plan.target)
        if replacements and content is not None:
            change.path.write_text(content, encoding="utf-8")

    for change in plan.sqlite_changes:
        con = sqlite3.connect(change.path)
        try:
            placeholders = ",".join("?" for _ in plan.sources)
            sql = f"update threads set model_provider = ? where model_provider in ({placeholders})"
            con.execute(sql, [plan.target, *sorted(plan.sources)])
            con.commit()
        finally:
            con.close()


def print_plan(plan: Plan) -> None:
    print("Codex home:", plan.codex_home)
    print("Target provider key:", plan.target)
    source = "config.toml model_provider" if plan.live_provider_explicit else "Codex built-in default"
    print("Current live provider key:", f"{plan.live_provider} ({source})")
    print("Discovered provider keys:", ", ".join(sorted(plan.discovered)) or "<none>")
    print("Source keys to migrate:", ", ".join(sorted(plan.sources)) or "<none>")
    if plan.reserved_table_repairs:
        print()
        for source_key, target_key in sorted(plan.reserved_table_repairs.items()):
            print(
                f"[warn] config.toml defines reserved built-in provider table "
                f"'[model_providers.{source_key}]'. It will be renamed to "
                f"'[model_providers.{target_key}]' so Codex can load the config."
            )
    if plan.missing_live_provider_repair:
        print()
        if plan.target == plan.missing_live_provider_repair and plan.target not in RESERVED_BUILTIN_PROVIDERS:
            print(
                f"[warn] config.toml references model_provider '{plan.missing_live_provider_repair}' "
                "but no matching [model_providers] table exists. The missing "
                "provider table will be added."
            )
        else:
            print(
                f"[warn] config.toml references model_provider '{plan.missing_live_provider_repair}' "
                "but no matching [model_providers] table exists. The top-level "
                "model_provider line will be removed so Codex falls back to the "
                "built-in openai provider."
            )
    if plan.target != plan.live_provider:
        print()
        print(
            "[warn] Target provider key differs from the current live provider key. "
            "Codex resume/history is filtered by the live provider key, so migrated "
            "sessions may stay hidden until config.toml uses the target key."
        )
    if plan.target in RESERVED_BUILTIN_PROVIDERS:
        print()
        print(
            f"[warn] '{plan.target}' is a Codex built-in provider key. "
            "The script will not rewrite config.toml to this key because Codex "
            "forbids overriding built-in providers under [model_providers]. "
            "Only history/session records are migrated."
        )
    print()
    print("Planned changes:")
    print("  config.toml:", "change" if plan.config_changed else "no change")
    print("  jsonl files:", len(plan.jsonl_changes), "files /", sum(c.replacements for c in plan.jsonl_changes), "replacements")
    for change in plan.jsonl_changes[:12]:
        print(f"    - {change.path} ({change.replacements})")
    if len(plan.jsonl_changes) > 12:
        print(f"    ... {len(plan.jsonl_changes) - 12} more")
    print("  sqlite:", len(plan.sqlite_changes), "dbs /", sum(c.rows for c in plan.sqlite_changes), "rows")
    for change in plan.sqlite_changes:
        print(f"    - {change.path} ({change.rows})")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Unify Codex model_provider history buckets.")
    parser.add_argument("--codex-home", help="Codex config directory. Default: ~/.codex")
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        help=(
            "Target provider key. Use 'current'/'auto' to migrate into the provider "
            f"currently active in ~/.codex/config.toml. Default: {DEFAULT_TARGET}"
        ),
    )
    parser.add_argument("--source", action="append", dest="sources", help="Source provider key to migrate. Repeatable. Default: all discovered except target/excludes.")
    parser.add_argument("--exclude", action="append", default=[], help="Provider key to exclude from automatic source discovery. Repeatable.")
    parser.add_argument("--include-reserved", action="store_true", help="Do not exclude reserved local provider keys in automatic source discovery.")
    parser.add_argument(
        "--reserved-alias",
        default=DEFAULT_RESERVED_ALIAS,
        help=(
            "Alias to use when config.toml illegally defines a reserved built-in "
            f"provider table such as [model_providers.openai]. Default: {DEFAULT_RESERVED_ALIAS}"
        ),
    )
    parser.add_argument("--apply", action="store_true", help="Apply changes. Without this flag, dry-run only.")
    parser.add_argument("--allow-running", action="store_true", help="Allow applying while a Codex process appears to be running.")
    args = parser.parse_args()

    codex_home = codex_home_from_args(args.codex_home)
    if not codex_home.exists():
        print(f"Codex home does not exist: {codex_home}", file=sys.stderr)
        return 2

    excludes = set(args.exclude)
    if not args.include_reserved:
        excludes |= DEFAULT_EXCLUDES

    plan = plan_changes(codex_home, args.target, args.sources, excludes, args.reserved_alias)
    print_plan(plan)

    if not args.apply:
        print("Dry-run only. Re-run with --apply to modify files.")
        return 0

    if not plan.total_changes():
        print("Nothing to apply.")
        return 0

    if is_windows_codex_running() and not args.allow_running:
        print(
            "Refusing to apply while a Codex process appears to be running. "
            "Close Codex first, or use --allow-running if you know what you are doing.",
            file=sys.stderr,
        )
        return 3

    backup_dir = make_backup(plan)
    print("Backup created:", backup_dir)
    apply_plan(plan)
    print("Applied. Restart Codex before checking history/resume.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
