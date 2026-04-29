---
name: entropy-audit
description: Run and interpret the Java code entropy audit CLI from this repository. Use when the user asks to perform entropy control scanning, code entropy audits, 熵控扫描, 代码本体熵, entropy_audit init/run/collect/score/report, generate entropy reports, inspect entropy-dashboard.html/metrics.json/code_entropy_details.json/code-entropy-details, package this workflow for Cursor/Codex/Claude Code/OpenClaw, or explain the generated governance findings.
---

# Entropy Audit

## Overview

Use this skill to run the repository's `entropy_audit` Python CLI, regenerate Java entropy governance reports, and explain the resulting risk signals. Work from the Java project root, not from inside `entropy_audit`.

This portable skill can be installed under the target agent's skill/rules directory, for example `C:\Users\<user>\.codex\skills\entropy-audit` for Codex. Keep the bundled `assets/tool` directory together with this `SKILL.md` so the audit can run even when the scanned project does not contain local `entropy_audit` source code.

The runnable Python tool is bundled under `assets/tool/entropy_audit`. Do not load the bundled source into context unless debugging or modifying the tool; use the runner script for normal audits.

## User Workflow

Use two commands in normal work:

1. `init`: run once for a Java project that does not yet have entropy config files.
2. `run`: run whenever the user wants to generate or refresh the entropy report.

First-time setup for a target Java project:

```powershell
$env:PYTHONPATH="<skill-root>\assets\tool"
python -m entropy_audit.cli init --project-root <java-project-root> --language java
```

Monthly scan after config exists:

```powershell
python <skill-root>\scripts\run_entropy_audit.py --project-root <java-project-root> --period 2026-04
```

The generated report is written to:

```text
<java-project-root>/reports/<period>/entropy-dashboard.html
```

If the target project already contains `entropy.config.toml`, skip `init` unless the user explicitly wants to regenerate or migrate the config.

## Preconditions

The target project should be a Java repository or a directory containing Java source files. It does not need to contain `entropy_audit/`; this skill bundles the runnable Python tool under `assets/tool`.

The target project should contain entropy config files before a normal scan:

```text
entropy.config.toml
entropy.calibration.toml
```

If the config files are missing, initialize them from the bundled tool first:

```powershell
$env:PYTHONPATH="<skill-root>\assets\tool"
python -m entropy_audit.cli init --project-root <java-project-root> --language java
```

For Java style entropy, the skill bundles Checkstyle jars and configs under:

```text
assets/tool/entropy_audit/lang/java/tools/checkstyle/jdk8/
assets/tool/entropy_audit/lang/java/tools/checkstyle/jdk17/
```

The scanner auto-selects the Java 8 or Java 17 Checkstyle profile from the configured/runtime JDK. If Checkstyle cannot run, style entropy is reported as missing or unscored rather than silently faked.

## Quick Run

Use the helper when the user wants the normal monthly report:

```powershell
python <skill-root>\scripts\run_entropy_audit.py --project-root <java-project-root> --period 2026-04
```

The helper locates `entropy.config.toml`, prefers a project-local `entropy_audit/`, then falls back to the bundled tool under `assets/tool/`, and only uses `entropy_audit` from `PATH` as the last fallback. It writes reports to `reports/<period>` by default.

Equivalent direct command when `entropy_audit` is installed or the project contains a local package:

```powershell
entropy_audit run --project-root . --config entropy.config.toml --calibration entropy.calibration.toml --period 2026-04 --mode monthly --out-dir reports/2026-04
```

Bundled fallback direct command:

```powershell
$env:PYTHONPATH="<skill-root>\assets\tool"
python -m entropy_audit.cli run --project-root . --config entropy.config.toml --calibration entropy.calibration.toml --period 2026-04 --mode monthly --out-dir reports/2026-04
```

## Manual Pipeline

Run commands from the project root:

```powershell
entropy_audit collect --project-root . --config entropy.config.toml --period 2026-04 --out-dir reports/2026-04
entropy_audit score --inputs reports/2026-04/normalized_inputs.json --config entropy.config.toml --calibration entropy.calibration.toml --out-dir reports/2026-04
entropy_audit report --metrics reports/2026-04/metrics.json --period 2026-04 --mode monthly --out-dir reports/2026-04
```

Initialize a new Java project only when config files are missing:

```powershell
entropy_audit init --project-root . --language java
```

If an older project already has `entropy.config.toml`, do not overwrite it blindly. Either migrate the config or back it up before reinitializing, because local config controls rule versions, thresholds, and enabled rules.

## Report Outputs

After `run`, summarize these files:

```text
reports/<period>/entropy-dashboard.html
reports/<period>/metrics.json
reports/<period>/code_entropy_details.json
reports/<period>/code-entropy-details/
```

Prefer `metrics.json` for the executive summary:

- `project_facts.code_entropy_summary.total_entropy_score`
- `project_facts.code_entropy_summary.health_score`
- `project_facts.code_entropy_summary.entropy_scores`
- `project_facts.code_entropy_summary.score_status`

Use `code-entropy-details/*.json` for dimension-level evidence and `code-entropy-details/*.html` for human-readable detail pages.

## Interpretation Order

1. State total entropy score, health score, and whether scoring is complete.
2. List the highest-risk dimensions first.
3. Name the top evidence or rule families driving those dimensions.
4. Suggest the next governance actions.
5. Provide exact local report paths.

Entropy scores are risk scores: lower is better. Health score is derived separately: higher is better.

## Verification

After changing the Python package, run:

```powershell
python -m compileall entropy_audit
python -m unittest discover -s tests -p "test*.py"
```

Generated report HTML and JSON should not be hand-edited. Regenerate them with the CLI.

## Bundled Tool Layout

```text
assets/tool/pyproject.toml
assets/tool/entropy_audit/
assets/tool/entropy_audit/lang/java/tools/checkstyle/
```

The bundled Checkstyle jars are intentionally included so Java style entropy can run without fetching external binaries.
