#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""风格熵分析器：基于 Checkstyle 输出聚合六类风格问题。"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Dict

from entropy_audit.lang.java.scoring_v1_engine import score_dimension_v1


STYLE_CATEGORY_ORDER = [
    "style_formatting",
    "style_naming",
    "style_import",
    "style_declaration",
    "style_code_smell",
    "style_complexity",
]


CHECKSTYLE_MODULE_MEANINGS = {
    "AnnotationLocation": "检查注解是否放在团队约定的位置。",
    "AnnotationUseStyle": "检查注解参数写法是否统一，比如是否按约定省略 value。",
    "ArrayTypeStyle": "检查数组声明风格是否统一。",
    "AvoidEscapedUnicodeCharacters": "检查是否出现不利于阅读的 Unicode 转义字符。",
    "AvoidNestedBlocks": "检查方法中是否存在多余的嵌套代码块。",
    "AvoidStarImport": "检查是否使用星号导入，避免隐藏真实依赖。",
    "BooleanExpressionComplexity": "检查布尔表达式是否过于复杂。",
    "ClassTypeParameterName": "检查类泛型参数命名是否符合规范。",
    "CovariantEquals": "检查 equals 方法签名是否错误重载。",
    "DefaultComesLast": "检查 switch 的 default 分支是否放在最后。",
    "DescendantToken": "检查指定语法结构的嵌套或组合是否符合约束。",
    "EmptyBlock": "检查空代码块是否需要说明或禁止出现。",
    "EmptyCatchBlock": "检查空 catch 块，避免吞掉异常。",
    "EmptyForInitializerPad": "检查 for 初始化段为空时的空白风格。",
    "EmptyForIteratorPad": "检查 for 迭代段为空时的空白风格。",
    "EmptyStatement": "检查多余的空语句，比如孤立分号。",
    "EqualsAvoidNull": "检查字符串或对象比较时是否把常量放在 equals 左侧。",
    "EqualsHashCode": "检查重写 equals 时是否同步重写 hashCode。",
    "FileLength": "检查单个文件物理行数是否超过阈值。",
    "FileTabCharacter": "检查文件中是否存在 Tab 字符。",
    "FinalClass": "检查只包含私有构造器的类是否声明为 final。",
    "GenericWhitespace": "检查泛型尖括号附近的空白风格。",
    "Header": "检查文件头是否符合约定。",
    "IllegalImport": "检查是否导入被禁止的包或类。",
    "IllegalInstantiation": "检查是否直接实例化被禁止的类型。",
    "IllegalThrows": "检查方法是否抛出被禁止的异常类型。",
    "IllegalTokenText": "检查源码中是否出现被禁止的 token 文本。",
    "IllegalType": "检查是否使用被禁止或不推荐的类型。",
    "InnerAssignment": "检查条件表达式内部是否存在赋值语句。",
    "InnerTypeLast": "检查内部类/内部接口是否放在外部类成员之后。",
    "InterfaceIsType": "检查接口是否只作为常量容器使用。",
    "InterfaceTypeParameterName": "检查接口泛型参数命名是否符合规范。",
    "LocalFinalVariableName": "检查 final 局部变量命名是否符合规范。",
    "MethodName": "检查方法命名是否符合规范。",
    "MethodParamPad": "检查方法名和左括号之间的空白风格。",
    "MethodTypeParameterName": "检查方法泛型参数命名是否符合规范。",
    "MissingOverride": "检查重写方法是否缺少 @Override。",
    "MissingSwitchDefault": "检查 switch 是否缺少 default 分支。",
    "ModifiedControlVariable": "检查循环控制变量是否在循环体内被修改。",
    "ModifierOrder": "检查 public/static/final 等修饰符顺序是否符合规范。",
    "MultipleVariableDeclarations": "检查一行或一个声明中是否定义多个变量。",
    "NeedBraces": "检查 if/for/while 等语句是否缺少大括号。",
    "NestedForDepth": "检查 for 循环嵌套层数是否过深。",
    "NestedIfDepth": "检查 if 嵌套层数是否过深。",
    "NestedTryDepth": "检查 try 嵌套层数是否过深。",
    "NoFinalizer": "检查是否使用 finalize 方法。",
    "NoLineWrap": "检查不允许换行的位置是否出现换行。",
    "NoWhitespaceAfter": "检查指定符号之后是否出现不该有的空白。",
    "NoWhitespaceBefore": "检查指定符号之前是否出现不该有的空白。",
    "OneStatementPerLine": "检查是否一行写了多个语句。",
    "OneTopLevelClass": "检查一个 Java 文件中是否只包含一个顶层类。",
    "OuterTypeFilename": "检查外部类型名是否与文件名一致。",
    "OuterTypeNumber": "检查一个文件中的顶层类型数量是否过多。",
    "PackageAnnotation": "检查包注解是否放在 package-info.java 中。",
    "PackageName": "检查包名是否符合规范。",
    "ParameterNumber": "检查方法或构造器参数数量是否过多。",
    "ParenPad": "检查括号内侧空白风格。",
    "RedundantImport": "检查是否存在冗余导入。",
    "RegexpHeader": "检查文件头是否匹配正则约定。",
    "RegexpOnFilename": "检查文件名是否匹配正则约定。",
    "RegexpSinglelineJava": "检查 Java 源码单行内容是否命中禁止模式。",
    "SeparatorWrap": "检查点号、逗号等分隔符换行位置是否符合规范。",
    "SimplifyBooleanExpression": "检查布尔表达式是否可以简化。",
    "SimplifyBooleanReturn": "检查布尔返回语句是否可以简化。",
    "StaticVariableName": "检查静态变量命名是否符合规范。",
    "StringLiteralEquality": "检查字符串是否错误使用 == 或 != 比较。",
    "SuperClone": "检查 clone 方法是否调用 super.clone。",
    "SuperFinalize": "检查 finalize 方法是否调用 super.finalize。",
    "TypecastParenPad": "检查类型转换括号附近的空白风格。",
    "TypeName": "检查类型命名是否符合规范。",
    "UnusedImports": "检查是否存在未使用导入。",
    "WhitespaceAfter": "检查逗号、分号等符号之后是否有必要空格。",
    "WhitespaceAround": "检查运算符、关键字和大括号周围空白是否符合规范。",
}


class StyleAnalyzer:
    """风格熵分析器。"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.project_root = Path(config["project"]["root"]).resolve()
        self.exclude_dirs = set(config["project"]["exclude_dirs"])
        self.include_extensions = {
            str(value).strip().lower()
            for value in config["project"].get("include_extensions", [])
            if str(value).strip()
        }
        self.scoring_v1 = config.get("scoring_v1", {}) if isinstance(config.get("scoring_v1"), dict) else {}
        detectors = config.get("detectors", {}) if isinstance(config.get("detectors"), dict) else {}
        style_detectors = detectors.get("style", {}) if isinstance(detectors.get("style"), dict) else {}
        self.checkstyle_config = (
            style_detectors.get("checkstyle", {})
            if isinstance(style_detectors.get("checkstyle"), dict)
            else {}
        )
        self.categories = (
            self.checkstyle_config.get("categories", {})
            if isinstance(self.checkstyle_config.get("categories"), dict)
            else {}
        )
        self.exclude_modules = {
            str(value).strip()
            for value in self.checkstyle_config.get("exclude_modules", [])
            if str(value).strip()
        }
        self.include_severities = {
            str(value).strip().lower()
            for value in self.checkstyle_config.get("include_severities", [])
            if str(value).strip()
        }
        self.scan_extensions = {
            str(value).strip().lower()
            for value in self.checkstyle_config.get("scan_extensions", [])
            if str(value).strip()
        } or {".java"}
        self.module_to_category = self._build_module_category_map()

    def analyze(self) -> Dict[str, Any]:
        """执行风格熵分析。"""
        java_stats = self._collect_java_stats()
        run_info = self._run_checkstyle()
        violations = self._parse_checkstyle_xml(run_info.get("xml_path"))
        classified = self._classify_violations(violations)

        facts = self._build_facts(java_stats, classified, run_info.get("status") == "ok")
        details = self._build_details(java_stats, run_info, classified)
        v1_payload = score_dimension_v1(self.scoring_v1, "style", facts, details)
        if not isinstance(v1_payload, dict):
            raise ValueError("StyleAnalyzer requires [code_entropy.scoring_v1] and a valid style scorecard")

        score = v1_payload["score_breakdown"]["score"]
        level = str(v1_payload["score_breakdown"].get("level", "danger"))
        return {
            "score": score,
            "level": level,
            "score_breakdown": v1_payload["score_breakdown"],
            "metrics": v1_payload["metrics"],
            "facts": facts,
            "details": details,
            "scoring_v1": v1_payload,
            "metric_definitions": v1_payload.get("metric_definitions", {}),
        }

    def _build_module_category_map(self) -> dict[str, str]:
        module_to_category: dict[str, str] = {}
        for category_id, category in self.categories.items():
            if not isinstance(category, dict):
                continue
            for module in category.get("modules", []):
                module_name = str(module).strip()
                if module_name:
                    module_to_category[module_name] = str(category_id)
        return module_to_category

    def _collect_java_stats(self) -> dict[str, Any]:
        files = 0
        lines = 0
        for file_path in self._iter_scan_files():
            files += 1
            try:
                with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
                    lines += sum(1 for _ in handle)
            except OSError:
                continue
        return {
            "java_file_count": files,
            "java_line_count": lines,
            "java_kloc": round(lines / 1000.0, 3) if lines else 0.0,
        }

    def _iter_scan_files(self):
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs]
            for filename in files:
                path = Path(root) / filename
                if path.suffix.lower() in self.scan_extensions:
                    yield path

    def _run_checkstyle(self) -> dict[str, Any]:
        if not self.checkstyle_config.get("enabled", False):
            return {
                "enabled": False,
                "status": "disabled",
                "message": "Checkstyle 未启用。",
                "xml_path": None,
            }

        bundle = self._resolve_checkstyle_bundle()
        jar_path = self._resolve_project_path(bundle["jar"])
        config_path = self._resolve_project_path(bundle["config"])
        workdir = self._resolve_project_path(bundle["workdir"])
        if not jar_path.exists():
            return {"enabled": True, "status": "missing_tool", "message": f"Checkstyle jar 不存在：{jar_path}", "xml_path": None}
        if not config_path.exists():
            return {"enabled": True, "status": "missing_config", "message": f"Checkstyle 配置不存在：{config_path}", "xml_path": None}
        if not workdir.exists():
            workdir = config_path.parent

        with tempfile.NamedTemporaryFile(prefix="style-checkstyle-", suffix=".xml", delete=False) as handle:
            output_path = Path(handle.name)

        command = [
            "java",
            "-Dfile.encoding=UTF-8",
            "-jar",
            str(jar_path),
            "-c",
            str(config_path),
            "-f",
            str(self.checkstyle_config.get("output_format", "xml")),
            "-o",
            str(output_path),
            *[str(target) for target in self._scan_targets()],
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(workdir),
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
            return {"enabled": True, "status": "failed", "message": str(exc), "xml_path": None}

        message = (completed.stderr or completed.stdout or "").strip()
        fatal = self._is_fatal_checkstyle_failure(completed.returncode, message)
        status = "ok" if output_path.exists() and not fatal else "failed"
        xml_path = output_path if status == "ok" else None
        if status != "ok":
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
        return {
            "enabled": True,
            "status": status,
            "message": message,
            "xml_path": xml_path,
            "java_version_family": bundle["family"],
            "jar": str(jar_path),
            "config": str(config_path),
            "exit_code": completed.returncode,
        }

    @staticmethod
    def _is_fatal_checkstyle_failure(returncode: int, message: str) -> bool:
        if returncode == 0:
            return False
        fatal_markers = [
            "CheckstyleException",
            "Exception was thrown while processing",
            "TokenStreamRecognitionException",
            "Unable to create Root Module",
            "cannot initialize module",
        ]
        return any(marker in message for marker in fatal_markers)

    def _resolve_checkstyle_bundle(self) -> dict[str, str]:
        family = "jdk8"
        if self._runtime_java_major() > 8:
            family = "jdk17"
        return {
            "family": family,
            "jar": str(self.checkstyle_config.get(f"{family}_jar", "")),
            "config": str(self.checkstyle_config.get(f"{family}_config", "")),
            "workdir": str(self.checkstyle_config.get(f"{family}_workdir", "")),
        }

    def _runtime_java_major(self) -> int:
        try:
            completed = subprocess.run(
                ["java", "-version"],
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return 8
        text = completed.stderr or completed.stdout or ""
        match = re.search(r'version\s+"([^"]+)"', text)
        if not match:
            return 8
        version = match.group(1)
        if version.startswith("1."):
            parts = version.split(".")
            return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 8
        major = version.split(".")[0]
        return int(major) if major.isdigit() else 8

    def _resolve_project_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        project_candidate = (self.project_root / path).resolve()
        if project_candidate.exists():
            return project_candidate
        package_root = Path(__file__).resolve().parents[3]
        bundled_parent_candidate = (package_root.parent / path).resolve()
        if bundled_parent_candidate.exists():
            return bundled_parent_candidate
        bundled_package_candidate = (package_root / path).resolve()
        if bundled_package_candidate.exists():
            return bundled_package_candidate
        return project_candidate

    def _scan_targets(self) -> list[Path]:
        source_roots: list[Path] = []
        for root, dirs, _files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs]
            path = Path(root)
            normalized = path.as_posix().lower()
            if normalized.endswith("/src/main/java") or normalized.endswith("/src/test/java"):
                source_roots.append(path)
                dirs[:] = []
        return source_roots or [self.project_root]

    def _parse_checkstyle_xml(self, xml_path: object) -> list[dict[str, Any]]:
        if not isinstance(xml_path, Path) or not xml_path.exists():
            return []
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError:
            return []

        issues: list[dict[str, Any]] = []
        for file_node in root.findall("file"):
            raw_file = str(file_node.get("name", ""))
            file_path = Path(raw_file)
            if file_path.suffix.lower() not in self.scan_extensions:
                continue
            rel_file = self._relative_path(file_path)
            for error_node in file_node.findall("error"):
                severity = str(error_node.get("severity", "")).strip().lower()
                if self.include_severities and severity not in self.include_severities:
                    continue
                module = self._source_to_module(str(error_node.get("source", "")))
                if module in self.exclude_modules:
                    continue
                issues.append(
                    {
                        "file": rel_file,
                        "line": self._int_value(error_node.get("line")),
                        "column": self._int_value(error_node.get("column")),
                        "severity": severity or "error",
                        "module": module,
                        "source": str(error_node.get("source", "")),
                        "message": str(error_node.get("message", "")),
                    }
                )
        return issues

    def _relative_path(self, file_path: Path) -> str:
        try:
            return str(file_path.resolve().relative_to(self.project_root)).replace("\\", "/")
        except (OSError, ValueError):
            return str(file_path).replace("\\", "/")

    def _source_to_module(self, source: str) -> str:
        if not source:
            return "Unknown"
        name = source.rsplit(".", 1)[-1]
        for suffix in ["Check", "FileFilter", "Filter"]:
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[: -len(suffix)]
                break
        return name

    def _classify_violations(self, violations: list[dict[str, Any]]) -> dict[str, Any]:
        unknown_category = str(self.checkstyle_config.get("unknown_module_category", "style_code_smell"))
        category_counts = Counter({category_id: 0 for category_id in STYLE_CATEGORY_ORDER})
        module_counts: Counter[str] = Counter()
        rows_by_category: dict[str, list[dict[str, Any]]] = {category_id: [] for category_id in STYLE_CATEGORY_ORDER}
        for issue in violations:
            module = str(issue.get("module", "Unknown"))
            category_id = self.module_to_category.get(module, unknown_category)
            category = self.categories.get(category_id, {}) if isinstance(self.categories.get(category_id), dict) else {}
            row = {
                **issue,
                "category": category_id,
                "category_label": str(category.get("label", category_id)),
                "description": str(category.get("description", "")),
            }
            category_counts[category_id] += 1
            module_counts[module] += 1
            rows_by_category.setdefault(category_id, []).append(row)

        category_summary = []
        for category_id in STYLE_CATEGORY_ORDER:
            category = self.categories.get(category_id, {}) if isinstance(self.categories.get(category_id), dict) else {}
            category_summary.append(
                {
                    "category": category_id,
                    "category_label": str(category.get("label", category_id)),
                    "description": str(category.get("description", "")),
                    "issue_count": int(category_counts.get(category_id, 0)),
                }
            )
        return {
            "violations": violations,
            "category_counts": dict(category_counts),
            "module_counts": dict(module_counts),
            "rows_by_category": rows_by_category,
            "category_summary": category_summary,
        }

    def _build_facts(self, java_stats: dict[str, Any], classified: dict[str, Any], checkstyle_ok: bool) -> Dict[str, Any]:
        counts = classified.get("category_counts", {})
        facts = {
            "java_file_count": java_stats["java_file_count"],
            "java_line_count": java_stats["java_line_count"],
            "java_kloc": java_stats["java_kloc"],
            "style_total_violation_count": len(classified.get("violations", [])) if checkstyle_ok else None,
        }
        for category_id in STYLE_CATEGORY_ORDER:
            facts[f"{category_id}_violation_count"] = int(counts.get(category_id, 0) or 0) if checkstyle_ok else None
        return facts

    def _build_details(
        self,
        java_stats: dict[str, Any],
        run_info: dict[str, Any],
        classified: dict[str, Any],
    ) -> Dict[str, Any]:
        table_total_counts = {
            "style_rule_overview": len(STYLE_CATEGORY_ORDER),
            "checkstyle_module_distribution": len(classified.get("module_counts", {})),
        }
        details: dict[str, Any] = {
            "checkstyle_enabled": run_info.get("enabled", False),
            "checkstyle_status": run_info.get("status", ""),
            "checkstyle_message": run_info.get("message", ""),
            "checkstyle_java_version_family": run_info.get("java_version_family", ""),
            "checkstyle_config": run_info.get("config", ""),
            "java_file_count": java_stats["java_file_count"],
            "java_line_count": java_stats["java_line_count"],
            "java_kloc": java_stats["java_kloc"],
            "style_total_violation_count": len(classified.get("violations", [])),
            "style_rule_overview": classified.get("category_summary", []),
            "checkstyle_module_distribution": [
                {
                    "module": module,
                    "category_label": str(
                        self.categories.get(self.module_to_category.get(module, ""), {}).get(
                            "label",
                            self.module_to_category.get(module, "未分类"),
                        )
                    )
                    if isinstance(self.categories.get(self.module_to_category.get(module, "")), dict)
                    else self.module_to_category.get(module, "未分类"),
                    "module_meaning": CHECKSTYLE_MODULE_MEANINGS.get(module, "Checkstyle 原始规则，当前未配置中文含义。"),
                    "count": count,
                }
                for module, count in sorted(classified.get("module_counts", {}).items(), key=lambda item: (-item[1], item[0]))
            ],
            "table_total_counts": table_total_counts,
        }
        for category_id in STYLE_CATEGORY_ORDER:
            rows = classified.get("rows_by_category", {}).get(category_id, [])
            details[f"{category_id}_issues"] = rows
            table_total_counts[f"{category_id}_issues"] = len(rows)
        return details

    @staticmethod
    def _int_value(value: object) -> int:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return 0
