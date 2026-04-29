---
name: entropy-audit
description: Run and interpret the Java code entropy audit CLI from this repository. Use when the user asks to perform entropy control scanning, code entropy audits, 熵控扫描, 代码本体熵, entropy_audit init/run/collect/score/report, generate entropy reports, inspect entropy-dashboard.html/metrics.json/code_entropy_details.json/code-entropy-details, package this workflow for Cursor/Codex/Claude Code/OpenClaw, or explain the generated governance findings.
---

# Entropy Audit

## Overview

Use this skill to run the repository's `entropy_audit` Python CLI, regenerate Java entropy governance reports, and explain the resulting risk signals. Work from the Java project root, not from inside `entropy_audit`.

This skill is stored in `.cursor/skills/entropy-audit` so Cursor can discover it from the repository. For Codex, Claude Code, or OpenClaw-style agents, use this same folder as the portable skill source; copy or symlink it into that tool's skill/rules directory when automatic discovery is required.

## Preconditions

The project root should contain:

```text
entropy_audit/
entropy.config.toml
entropy.calibration.toml
pyproject.toml
```

Prefer the installed CLI entry point:

```bash
entropy_audit --help
```

If the executable is unavailable but the package exists in the project root, use:

```bash
python -m entropy_audit.cli --help
```

## Quick Run

Use the helper when the user wants the normal monthly report:

```bash
python .cursor/skills/entropy-audit/scripts/run_entropy_audit.py --project-root . --period 2026-04
```

The helper locates `entropy.config.toml`, prefers `entropy_audit` from `PATH`, falls back to `python -m entropy_audit.cli`, and writes reports to `reports/<period>` by default.

Equivalent direct command:

```bash
entropy_audit run --project-root . --config entropy.config.toml --calibration entropy.calibration.toml --period 2026-04 --mode monthly --out-dir reports/2026-04
```

Fallback direct command:

```bash
python -m entropy_audit.cli run --project-root . --config entropy.config.toml --calibration entropy.calibration.toml --period 2026-04 --mode monthly --out-dir reports/2026-04
```

## Manual Pipeline

Run commands from the project root:

```bash
entropy_audit collect --project-root . --config entropy.config.toml --period 2026-04 --out-dir reports/2026-04
entropy_audit score --inputs reports/2026-04/normalized_inputs.json --config entropy.config.toml --calibration entropy.calibration.toml --out-dir reports/2026-04
entropy_audit report --metrics reports/2026-04/metrics.json --period 2026-04 --mode monthly --out-dir reports/2026-04
```

Initialize a new Java project only when config files are missing:

```bash
entropy_audit init --project-root . --language java
```

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

```bash
python -m compileall entropy_audit
python -m unittest discover -s tests -p "test*.py"
```

Generated report HTML and JSON should not be hand-edited. Regenerate them with the CLI.
