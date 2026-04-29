from __future__ import annotations

import html
import json
import re
from urllib.parse import quote

from entropy_audit.models import ScoredSnapshot


CODE_ENTROPY_LABELS = {
    "structure": "结构熵",
    "semantic": "语义熵",
    "behavior": "行为熵",
    "cognition": "认知熵",
    "style": "风格熵",
}

DEFAULT_ENTROPY_LEVEL_BANDS = {
    "excellent": 40.0,
    "good": 60.0,
    "warning": 80.0,
}

CODE_ENTROPY_STANDARDS = {
    "structure": [
        "本项是 0-100 风险熵分，越高代表结构风险越大。",
        "0-39：目录边界较清晰，共享承载和目录分布整体可控。",
        "40-59：存在局部膨胀或头部目录集中，需要持续收敛。",
        "60-79：共享承载或目录失衡已经放大，进入重点关注区。",
        "80-100：结构风险高，通常伴随共享目录失控或目录集中度明显偏高。",
    ],
    "semantic": [
        "本项是 0-100 风险熵分，越高代表语义风险越大。",
        "0-39：核心术语统一，名称可以稳定映射业务含义。",
        "40-59：存在别名和概念漂移，但主干仍可理解。",
        "60-79：术语缺口或非标准命名已经影响理解效率。",
        "80-100：语义碎片化明显，阅读和协作成本会持续升高。",
    ],
    "behavior": [
        "本项是 0-100 风险熵分，越高代表行为风险越大。",
        "0-39：主流程行为一致，异常与返回约定稳定。",
        "40-59：局部存在多套处理模式，需要持续收敛。",
        "60-79：异常和返回约定开始分裂，调用方心智负担明显上升。",
        "80-100：行为约定混乱，接口使用和排障成本都会放大。",
    ],
    "cognition": [
        "本项是 0-100 风险熵分，越高代表认知风险越大。",
        "0-39：债务低、说明充分、复杂度受控。",
        "40-59：存在局部技术债、知识缺口或复杂方法，需要持续收敛。",
        "60-79：债务、公共知识缺口、复杂方法或大文件负担已明显抬高理解成本。",
        "80-100：认知负担过高，维护会高度依赖个人经验。",
    ],
    "style": [
        "本项是 0-100 风险熵分，越高代表风格风险越大。",
        "0-39：Checkstyle 问题密度较低，编码规范整体可控。",
        "40-59：存在局部格式、命名或坏味道问题，需要持续收敛。",
        "60-79：规范问题密度较高，阅读和评审成本明显上升。",
        "80-100：风格风险高，通常伴随大量坏味道、复杂度或排版问题。",
    ],
}

CODE_ENTROPY_SCOPES = {
    "structure": "目录边界、共享承载与目录分布",
    "semantic": "术语统一、命名漂移与状态治理",
    "behavior": "失败路径、异常语义与错误契约",
    "cognition": "技术债、复杂度与知识补给",
    "style": "Checkstyle 规范、坏味道与复杂度",
}

SEMANTIC_RULE_SECTIONS = (
    {
        "metric": "naming_inconsistency_ratio",
        "section_id": "rule-naming",
        "label": "命名非标准占比",
        "description": "展示非标准命中占比，并按变体家族说明哪些非标准命名仍在被使用。",
        "issue_table": "naming_conflict_issues",
        "location_table": "naming_conflict_locations",
        "empty_issues": "当前未发现需要说明的变体家族。",
        "empty_locations": "当前没有非标准命名的代码定位记录。",
    },
    {
        "metric": "term_gap_ratio",
        "section_id": "rule-term-gap",
        "label": "术语缺口",
        "description": "检查高频领域术语是否尚未进入项目 glossary.md，并列出候选术语与代码位置。",
        "issue_table": "undefined_term_issues",
        "location_table": "undefined_term_locations",
        "empty_issues": "当前未发现需要补词典的术语缺口。",
        "empty_locations": "当前没有术语缺口的代码定位记录。",
    },
    {
        "metric": "state_duplicate_ratio",
        "section_id": "rule-state-duplicate",
        "label": "状态承载体重复",
        "description": "检查 Status/State 枚举、常量类等承载体是否重复维护同类状态项。",
        "issue_table": "state_duplicate_cluster_issues",
        "location_table": "state_duplicate_carrier_issues",
        "empty_issues": "当前未发现重复状态簇。",
        "empty_locations": "当前没有重复状态承载体的代码定位记录。",
    },
    {
        "metric": "state_value_scatter_ratio",
        "section_id": "rule-state-scatter",
        "label": "状态值散落",
        "description": "检查业务代码中是否直接硬编码状态字面量，并把参与计分项与疑似项合并展示。",
        "issue_table": "state_scattered_value_issues",
        "location_table": "state_scattered_value_locations",
        "empty_issues": "当前未发现状态值散落或疑似散落问题。",
        "empty_locations": "当前没有状态值散落或疑似散落的代码定位记录。",
    },
)

DETAIL_TABLE_META = {
    "score_breakdown": {
        "label": "规则计分明细",
        "description": "逐条展示本次命中的规则值、风险系数和贡献分；表头可悬浮查看字段含义。",
    },
    "metrics": {
        "label": "原始指标（排查用）",
        "description": "每行是评分引擎使用的底层统计字段；已按规则或通用基数归类并说明用途，治理时优先看规则计分和代码定位。",
    },
    "top_directories": {
        "label": "大目录 Top",
        "description": "每行是一个直接承载较多 Java 文件的目录，用来判断目录是否过大或过于集中。",
    },
    "oversized_directories": {
        "label": "超大目录清单",
        "description": "每行是一个超过阈值的大目录，用来确认哪些目录已经进入结构风险区。",
    },
    "top_n_concentration_directories": {
        "label": "头部目录集中清单",
        "description": "每行是头部大目录之一，用来看主要文件是否过度集中在少数目录里。",
    },
    "shared_bucket_dirs": {
        "label": "共享承载目录",
        "description": "每行是被识别为 common / util / shared 的目录，文件数反映共享承载是否膨胀。",
    },
    "common_bucket_dirs": {
        "label": "common 命中目录",
        "description": "每行是按 common 规则命中的目录，命中来源会说明是前缀命中还是别名命中。",
    },
    "utility_bucket_dirs": {
        "label": "util 命中目录",
        "description": "每行是按 util 规则命中的目录，命中来源会说明是前缀命中还是别名命中。",
    },
    "shared_bucket_files": {
        "label": "共享承载文件清单",
        "description": "每行是一份落在共享承载目录中的 Java 文件，用来核对共享目录计数是否真实。",
    },
    "common_files": {
        "label": "common 文件清单",
        "description": "每行是一份命中 common 规则的文件，用来核对 common 识别结果。",
    },
    "util_files": {
        "label": "util 文件清单",
        "description": "每行是一份命中 util 规则的文件，用来核对 util 识别结果。",
    },
    "semantic_rule_overview": {
        "label": "语义规则总览",
        "description": "每行是一条语义规则的当前状态。规则值是本次计分值，计数说明会明确当前统计的是术语、命名位置、重复簇还是硬编码状态值。",
    },
    "naming_conflict_issues": {
        "label": "命名冲突问题",
        "description": "每行是一个出现多套命名家族的业务概念，用来看哪些概念已经发生命名分裂。",
    },
    "naming_conflict_locations": {
        "label": "命名冲突代码定位",
        "description": "每行是一处非标准命名代码。术语是归属概念，变体是实际命名，文件和行号可直接用于修复。",
    },
    "undefined_term_issues": {
        "label": "术语缺口问题",
        "description": "每行是一个高频但尚未进入 glossary 的候选术语，用来看哪些领域词还没纳入统一词典。",
    },
    "undefined_term_locations": {
        "label": "术语缺口代码定位",
        "description": "每行是一处术语缺口代码。术语是候选词，来源说明它来自类名还是文件名，文件和行号用于回查。",
    },
    "state_duplicate_cluster_issues": {
        "label": "状态承载体重复簇",
        "description": "每行是一组被判为重复的状态承载体簇。冗余承载体数表示这簇里有多少份 Status/State 定义可以视为重复维护。",
    },
    "state_duplicate_carrier_issues": {
        "label": "状态承载体重复定位",
        "description": "每行是一份被判为重复的状态承载体。重复簇 ID 用来归组，状态项是这次判重的直接依据。",
    },
    "state_scattered_value_issues": {
        "label": "状态值散落问题",
        "description": "每行是一个硬编码状态值。high 表示已匹配统一状态承载体并参与计分，candidate 表示疑似状态值，仅用于人工确认。",
    },
    "state_scattered_value_locations": {
        "label": "状态值散落代码定位",
        "description": "每行是一处状态值硬编码位置。high 可优先替换为枚举或常量引用，candidate 适合先人工确认。",
    },
    "top_error_patterns": {
        "label": "错误处理模式 Top",
        "description": "每行是一类错误处理模式及其命中次数，用来看项目是否存在多套错误处理写法。",
    },
    "top_return_formats": {
        "label": "返回格式 Top",
        "description": "每行是一类返回格式及其命中次数，用来看接口返回约定是否统一。",
    },
    "top_exceptions": {
        "label": "异常类型 Top",
        "description": "每行是一类异常及其出现次数和样例文件，用作补充排查；当前不再直接参与行为熵主评分。",
    },
    "failure_strategy_issues": {
        "label": "失败处理策略分裂",
        "description": "每行是一个 catch 块；策略列说明这里是重新抛异常、返回错误、只打日志等哪类失败处理，用来定位失败路径为什么分裂。",
    },
    "swallowed_exception_issues": {
        "label": "吞异常代码",
        "description": "每行是一个会吞掉失败信号的 catch 块，包括空 catch、只打日志、或没有 throw/return 失败处理的代码。",
    },
    "error_return_contract_issues": {
        "label": "返回错误契约混用",
        "description": "每行是 Controller/API 层一处失败出口，用来看包装错误、return null、错误码、字符串/布尔返回和直接抛异常是否混用。",
    },
    "generic_exception_issues": {
        "label": "泛化异常滥用",
        "description": "每行是一处 throw new Exception、RuntimeException 或 Throwable；这类异常缺少业务语义，优先替换为明确异常类型。",
    },
    "business_exception_convergence_issues": {
        "label": "业务异常未收敛",
        "description": "每行是一处未命中标准业务异常集合的业务异常抛出位置，用来收敛到配置里的统一业务异常基类。",
    },
    "todo_items": {
        "label": "债务标记问题",
        "description": "每行是一条 TODO / FIXME / HACK 记录，文件和行号可以直接定位到待处理代码。",
    },
    "debt_marker_issues": {
        "label": "债务标记问题",
        "description": "对应规则：债务标记密度。每行是一条 TODO / FIXME / HACK，数量用于计算每千文件债务密度。",
    },
    "unowned_debt_issues": {
        "label": "未归属债务问题",
        "description": "对应规则：未归属债务比例。每行是一条没有责任人标记的债务记录，优先补责任人或关闭无效债务。",
    },
    "public_knowledge_gap_issues": {
        "label": "公共知识缺口",
        "description": "对应规则：公共知识缺口比例。每行是一个公共类或公共方法缺少 JavaDoc 的位置。",
    },
    "complex_method_issues": {
        "label": "复杂方法",
        "description": "对应规则：复杂方法比例。每行是一个方法体过长、分支过多或嵌套过深的方法。",
    },
    "large_file_class_issues": {
        "label": "大文件/大类负担",
        "description": "对应规则：大文件/大类负担比例。每行是一份超过阈值的 Java 文件，用来定位沉重阅读入口。",
    },
    "project_doc_issues": {
        "label": "项目文档缺口",
        "description": "对应规则：项目文档缺口比例。每行是一项 README 或 docs/readme/wiki 文档缺口，用来定位新人理解项目时缺少的说明。",
    },
    "project_doc_gap_overview": {
        "label": "项目文档缺口比例",
        "description": "对应规则：项目文档缺口比例。该规则不定位 Java 代码，而是展示 README 与 docs/readme/wiki 文档证据和当前缺口结论。",
    },
    "project_doc_topic_coverage": {
        "label": "项目文档主题覆盖",
        "description": "展示通用项目说明主题是否被 README 或文档目录覆盖，用于解释项目文档缺口比例。",
    },
    "project_doc_files": {
        "label": "项目文档清单",
        "description": "展示本次纳入项目文档缺口计算的 README、docs/doc/readme/wiki 文档文件。",
    },
    "style_rule_overview": {
        "label": "风格规则总览",
        "description": "每行是一类风格熵规则，问题数来自 Checkstyle 明细按 entropy.config.toml 中的模块分类聚合。",
    },
    "style_formatting_issues": {
        "label": "格式排版问题",
        "description": "对应规则：格式排版问题密度。每行是一处缩进、空白、换行、括号、空块等 Checkstyle 问题。",
    },
    "style_naming_issues": {
        "label": "命名规范问题",
        "description": "对应规则：命名规范问题密度。每行是一处类名、方法名、包名、泛型参数或变量命名问题。",
    },
    "style_import_issues": {
        "label": "导入规范问题",
        "description": "对应规则：导入规范问题密度。每行是一处星号导入、非法导入、冗余导入或未使用导入问题。",
    },
    "style_declaration_issues": {
        "label": "注解与声明规范问题",
        "description": "对应规则：注解与声明规范问题密度。每行是一处注解、Override、包注解、修饰符顺序或顶层类声明问题。",
    },
    "style_code_smell_issues": {
        "label": "编码坏味道问题",
        "description": "对应规则：编码坏味道问题密度。每行是一处空 catch、直接打印、字符串比较、equals/hashCode 或控制流坏味道。",
    },
    "style_complexity_issues": {
        "label": "复杂度与规模问题",
        "description": "对应规则：复杂度与规模问题密度。每行是一处文件过长、嵌套过深、参数过多或表达式复杂问题。",
    },
    "checkstyle_module_distribution": {
        "label": "Checkstyle 规则分布",
        "description": "按原始 Checkstyle module 聚合的问题数，用来排查六类规则下具体是哪条细项规则占比最高。",
    },
    "large_methods": {
        "label": "大型方法",
        "description": "每行是一段超过阈值的方法，行数越高，通常越值得优先拆分。",
    },
    "large_files": {
        "label": "大型文件",
        "description": "每行是一份较大的文件，用来看哪些文件已经开始抬高阅读和维护成本。",
    },
    "structure_shared_bucket_locations": {
        "label": "共享承载目录占比定位",
        "description": "对应规则 shared_bucket_ratio。每行是一份落在共享承载目录中的 Java 文件，用来定位共享承载目录占比的分子来源。",
    },
    "structure_max_dir_locations": {
        "label": "最大目录文件占比定位",
        "description": "对应规则 max_dir_files_ratio。每行是一个目录；这里展示直接 Java 文件数最多的目录，用来定位最大目录文件占比的来源。",
    },
    "structure_oversized_dir_locations": {
        "label": "超大目录数量占比定位",
        "description": "对应规则 oversized_dir_ratio。每行是一个超过阈值的目录，用来定位超大目录数量占比的分子来源。",
    },
    "structure_top_n_dir_locations": {
        "label": "前 N 大目录集中度定位",
        "description": "对应规则 top_n_dir_concentration。每行是一个头部大目录；这些目录的文件数相加后，就是前 N 大目录集中度的分子来源。",
    },
}

DETAIL_SHORT_LABELS = {
    "common_files": "common 文件",
    "shared_bucket_overlap_files": "共享与工具目录重叠文件数",
    "shared_bucket_ratio": "共享目录占比",
    "max_dir_files": "最大目录规模",
    "max_dir_files_ratio": "最大目录占比",
    "oversized_dir_ratio": "超大目录占比",
    "oversized_dir_count": "超大目录数量",
    "top_n_dir_concentration": "头部目录集中度",
    "top_n_dir_file_sum": "头部目录文件量",
    "naming_inconsistency_count": "存在变体的概念数",
    "naming_matched_hit_count": "命名总命中",
    "naming_standard_hit_count": "标准命中",
    "naming_nonstandard_hit_count": "非标准命中",
    "naming_variant_family_count": "变体家族数",
    "term_gap_ratio": "术语缺口率",
    "term_coverage": "术语覆盖率",
    "defined_terms": "已覆盖术语",
    "term_gap_candidate_count": "候选术语数",
    "undefined_terms": "未定义术语",
    "state_duplicate_ratio": "状态承载体重复比",
    "state_duplicate_cluster_count": "状态承载体重复簇",
    "duplicate_states": "冗余状态承载体",
    "state_value_scatter_ratio": "状态值散落比例",
    "state_scattered_value_count": "硬编码状态值次数",
    "state_scattered_value_file_count": "状态值散落文件数",
    "state_scattered_value_total_file_count": "状态值散落涉及文件数",
    "state_scattered_value_unique_count": "状态值散落种类",
    "state_scattered_value_candidate_count": "疑似状态值次数",
    "state_scattered_value_candidate_unique_count": "疑似状态值种类",
    "state_value_reference_count": "状态值引用总量",
    "state_item_total": "状态项总数",
    "state_duplicate_cluster_count": "重复簇数量",
    "return_format_types": "旧口径返回格式",
    "exception_types": "异常类型",
    "error_consistency": "旧口径错误一致性",
    "return_consistency": "旧口径返回一致性",
    "exception_type_density_per_k_files": "旧口径异常密度",
    "failure_strategy_split_ratio": "失败策略分裂",
    "swallowed_exception_ratio": "吞异常比例",
    "error_return_contract_mix_ratio": "错误契约混用",
    "generic_exception_throw_ratio": "泛化异常占比",
    "business_exception_convergence_gap": "业务异常未收敛",
    "catch_block_count": "catch 块数量",
    "failure_strategy_count": "失败策略类型数",
    "failure_strategy_total_count": "失败策略总数",
    "failure_strategy_dominant_count": "主导失败策略数",
    "swallowed_catch_count": "吞异常 catch 数",
    "error_return_contract_count": "错误契约类型数",
    "error_return_contract_total_count": "错误契约总数",
    "error_return_contract_dominant_count": "主导错误契约数",
    "generic_exception_throw_count": "泛化异常抛出数",
    "exception_throw_count": "异常抛出总数",
    "business_exception_throw_count": "业务异常抛出数",
    "standard_business_exception_throw_count": "标准业务异常抛出数",
    "nonstandard_business_exception_throw_count": "非标准业务异常抛出数",
    "standard_business_exceptions": "标准业务异常集合",
    "business_exception_detection_mode": "业务异常识别模式",
    "project_kind": "项目类型",
    "project_detection_mode": "项目识别方式",
    "controller_candidates": "Controller 候选数",
    "configured_return_scan_scope": "配置扫描范围",
    "return_scan_scope": "实际扫描范围",
    "return_analysis_mode": "返回分析模式",
    "return_degraded_reason": "自动降级原因",
    "todo_count": "TODO",
    "todo_density_per_k_files": "TODO 密度",
    "todo_with_owner": "已认领 TODO",
    "unowned_debt_ratio": "未归属债务",
    "unowned_todo_count": "未归属债务",
    "public_knowledge_gap_ratio": "公共知识缺口",
    "knowledge_coverage": "公共知识覆盖",
    "knowledge_missing_count": "知识缺口数",
    "complex_method_ratio": "复杂方法比例",
    "complex_method_count": "复杂方法数",
    "large_file_class_burden_ratio": "大文件负担",
    "large_file_class_count": "大文件数",
    "project_doc_gap_ratio": "文档缺口",
    "project_doc_quality_score": "文档可用度",
    "indentation_consistency": "缩进一致性",
    "brace_style_consistency": "括号一致性",
    "style_formatting_density": "格式排版问题密度",
    "style_naming_density": "命名规范问题密度",
    "style_import_density": "导入规范问题密度",
    "style_declaration_density": "注解与声明规范问题密度",
    "style_code_smell_density": "编码坏味道问题密度",
    "style_complexity_density": "复杂度与规模问题密度",
    "style_total_violation_count": "Checkstyle 问题总数",
    "java_file_count": "Java 文件数",
    "java_line_count": "Java 物理行数",
    "java_kloc": "Java 千行数",
    "checkstyle_enabled": "Checkstyle 是否启用",
    "checkstyle_status": "Checkstyle 执行状态",
    "checkstyle_java_version_family": "Checkstyle 版本口径",
    "checkstyle_config": "Checkstyle 配置文件",
    "checkstyle_message": "Checkstyle 执行信息",
}

SEMANTIC_METRIC_EXPLANATIONS: dict[str, tuple[str, str]] = {
    "total_classes": ("扫描规模", "本次扫描到的 Java 类数量，用来判断命名和术语统计的项目规模背景。"),
    "score_status": ("计分完整性", "语义熵本次是否完成计分；complete 表示所有启用规则都已纳入总分。"),
    "coverage": ("计分完整性", "启用规则中实际完成计分的比例，用于排查是否存在缺数或待配置规则。"),
    "partial_reason": ("计分完整性", "当语义熵不是完整计分时，这里说明缺失或降级原因。"),
    "naming_inconsistency_count": ("命名非标准占比", "出现多套命名变体的业务概念数量，是命名冲突问题清单的来源。"),
    "glossary_matched_terms": ("命名非标准占比", "命名规则中命中的词典术语数，用来判断命名统计是否真正落在 glossary 概念上。"),
    "naming_matched_hit_count": ("命名非标准占比", "标准命名和非标准命名的总命中次数，是命名非标准占比的分母。"),
    "naming_standard_hit_count": ("命名非标准占比", "命中 glossary 标准术语的次数，用来确认标准命名在代码中的使用量。"),
    "naming_nonstandard_hit_count": ("命名非标准占比", "命中 glossary 非标准别名的次数，是命名非标准占比的分子。"),
    "naming_variant_family_count": ("命名非标准占比", "存在标准名和变体名的命名家族数量，用来定位概念分裂范围。"),
    "term_coverage": ("术语缺口", "候选术语中已经进入 glossary 的比例，越低表示术语统一程度越差。"),
    "undefined_terms": ("术语缺口", "候选术语中未进入 glossary 的数量，是术语缺口比例的分子。"),
    "defined_terms": ("术语缺口", "候选术语中已经被 glossary 覆盖的数量，用来和未定义术语对照。"),
    "term_gap_candidate_count": ("术语缺口", "本轮纳入术语缺口计分的候选术语数量，目前最多取配置上限内的高频术语。"),
    "term_gap_raw_term_count": ("术语缺口", "扫描阶段抽取到的原始术语出现总次数，用于排查候选术语来源是否充分。"),
    "term_gap_raw_unique_term_count": ("术语缺口", "截断候选池前的唯一术语数量，用来判断项目术语分布是否过散。"),
    "term_gap_min_occurrences": ("术语缺口", "术语至少出现多少次才会进入候选池，低频词不会直接参与缺口计分。"),
    "term_gap_candidate_mode": ("术语缺口", "候选术语筛选策略，例如按高频唯一术语选取。"),
    "term_gap_max_candidate_terms": ("术语缺口", "术语缺口规则最多纳入多少个候选术语参与计分。"),
    "term_gap_glossary_terms": ("术语缺口", "glossary 中可用于术语缺口规则的有效术语数量。"),
    "term_gap_glossary_missing": ("术语缺口", "是否缺少可用于术语缺口的 glossary 配置；缺失时该规则按最高风险处理。"),
    "state_definitions": ("状态承载体重复比", "本次扫描从代码中识别到的 Status/State 枚举或常量类数量，不是配置值；这些承载体里的状态项会继续汇总为状态项总数。"),
    "duplicate_states": ("状态承载体重复比", "重复簇中除保留承载体外的冗余承载体数量，是重复比例的分子。"),
    "state_item_total": ("状态承载体重复比", "从本次扫描识别到的状态承载体中动态抽取出来的状态项总数，不是配置值；它会参与状态值散落规则的分母。"),
    "state_unique_item_count": ("状态承载体重复比", "归一化后的唯一状态项数量，用来判断状态定义是否重复维护。"),
    "state_files": ("状态承载体重复比", "本次扫描识别到的状态承载体分布在哪些文件里。"),
    "state_duplicate_cluster_count": ("状态承载体重复比", "被判定为重复维护的状态承载体簇数量。"),
    "state_detection_mode": ("状态承载体重复比", "状态承载体重复检测模式，当前按状态项重叠度识别重复。"),
    "state_carrier_name_pattern_count": ("状态承载体重复比", "用于识别状态承载体名称的规则数量。"),
    "state_ignore_item_pattern_count": ("状态承载体重复比", "状态项抽取时忽略的噪声模式数量。"),
    "state_min_carrier_items": ("状态承载体重复比", "一个类至少包含多少状态项才会被视为状态承载体。"),
    "state_min_shared_items": ("状态承载体重复比", "两个承载体至少共享多少状态项才可能被判为重复。"),
    "state_similarity_threshold": ("状态承载体重复比", "状态项相似度达到该阈值后会进入重复簇判断。"),
    "state_scattered_value_count": ("状态值散落", "已匹配状态承载体的硬编码状态值出现次数，参与计分。"),
    "state_scattered_value_unique_count": ("状态值散落", "参与计分的硬编码状态值种类数量。"),
    "state_scattered_value_file_count": ("状态值散落", "参与计分的硬编码状态值涉及文件数。"),
    "state_scattered_value_total_file_count": ("状态值散落", "参与计分项和疑似项合并后的涉及文件总数，用于衡量排查面。"),
    "state_value_reference_count": ("状态值散落", "状态值散落比例的分母，等于“状态承载体状态项总数 + 参与计分的硬编码状态值次数”。"),
    "state_scattered_value_candidate_count": ("状态值散落", "疑似状态值硬编码出现次数，不参与计分，但会在问题清单和代码定位中展示。"),
    "state_scattered_value_candidate_unique_count": ("状态值散落", "疑似状态值的唯一种类数量，用于人工确认散落范围。"),
    "state_scatter_detection_mode": ("状态值散落", "状态值散落检测模式，当前识别状态上下文中的字符串或数字字面量。"),
    "glossary_mode": ("词典配置", "词典读取模式，用于排查命名和术语规则使用的 glossary 来源。"),
    "glossary_enabled": ("词典配置", "是否启用 glossary 术语配置。"),
    "naming_glossary_terms": ("词典配置", "可用于命名非标准占比规则的术语数量。"),
    "naming_glossary_missing": ("词典配置", "命名规则是否缺少可用 glossary。"),
    "glossary_source_type": ("词典配置", "glossary 的来源类型；project_glossary_md 表示来自被扫描项目的 glossary.md。"),
    "glossary_missing": ("词典配置", "被扫描目录中是否缺少 glossary.md。"),
    "missing_glossary_policy": ("词典配置", "缺少 glossary 时的处理策略。"),
}

SEMANTIC_METRIC_RULE_ORDER = {
    "扫描规模": 0,
    "计分完整性": 1,
    "命名非标准占比": 2,
    "术语缺口": 3,
    "状态承载体重复比": 4,
    "状态值散落": 5,
    "词典配置": 6,
    "其他指标": 99,
}

STRUCTURE_METRIC_EXPLANATIONS: dict[str, tuple[str, str]] = {
    "total_files": ("通用基数", "本次纳入结构熵统计的 Java 文件总数，是共享承载目录占比、最大目录文件占比、前 N 大目录集中度的分母。"),
    "total_directories": ("通用基数", "本次至少直接包含 1 个 Java 文件的目录数，是超大目录数量占比和平均目录文件数的分母。"),
    "common_files": ("共享承载目录占比", "命中共享承载配置中 common/shared 前缀或别名的 Java 文件数，用来解释共享桶来源。"),
    "util_files": ("共享承载目录占比", "命中共享承载配置中 util/utils 前缀或别名的 Java 文件数，用来解释工具桶来源。"),
    "shared_bucket_total": ("共享承载目录占比", "common/shared 与 util/utils 命中的唯一 Java 文件总量，是共享承载目录占比的分子。"),
    "shared_bucket_overlap_files": ("共享承载目录占比", "同时命中 common/shared 与 util/utils 的 Java 文件数；当前为 0，表示共享桶分子没有重复计数。"),
    "max_dir_files": ("最大目录文件占比", "单个目录直接包含的最大 Java 文件数，是最大目录文件占比的分子；不递归累加子目录。"),
    "max_dir_name": ("最大目录文件占比", "直接 Java 文件数最多的目录路径，用来定位最大目录文件占比对应的是哪个目录。"),
    "oversized_dir_count": ("超大目录数量占比", "直接 Java 文件数达到超大目录阈值的目录数量，是超大目录数量占比的分子。"),
    "oversized_dir_file_threshold": ("超大目录数量占比", "判定超大目录的阈值；当前目录直接 Java 文件数大于等于该值才计入超大目录。"),
    "top_n_dir_file_sum": ("前 N 大目录集中度", "按直接 Java 文件数排序后的前 N 个目录文件数合计，是前 N 大目录集中度的分子。"),
    "top_n_concentration_count": ("前 N 大目录集中度", "参与集中度计算的头部目录数量 N；当前取前 5 个最大目录。"),
    "avg_files_per_dir": ("平均目录文件数", "Java 文件总数除以含 Java 文件的目录数得到的全局平均值，只作为背景信号，不对应单个代码定位问题。"),
}

BEHAVIOR_METRIC_RULE_ORDER = {
    "失败处理策略分裂": 1,
    "吞异常比例": 2,
    "返回错误契约混用": 3,
    "泛化异常滥用": 4,
    "业务异常未收敛": 5,
    "扫描画像": 95,
}

BEHAVIOR_VISIBLE_METRIC_FIELDS = {
    "failure_strategy_count",
    "failure_strategy_total_count",
    "failure_strategy_dominant_count",
    "catch_block_count",
    "swallowed_catch_count",
    "error_return_contract_count",
    "error_return_contract_total_count",
    "error_return_contract_dominant_count",
    "exception_throw_count",
    "generic_exception_throw_count",
    "business_exception_throw_count",
    "standard_business_exception_throw_count",
    "nonstandard_business_exception_throw_count",
    "standard_business_exceptions",
    "business_exception_detection_mode",
    "project_kind",
    "project_detection_mode",
    "controller_candidates",
    "configured_return_scan_scope",
    "return_scan_scope",
    "return_analysis_mode",
    "return_degraded_reason",
}

BEHAVIOR_VISIBLE_FACT_FIELDS = {
    "failure_strategy_total_count",
    "failure_strategy_dominant_count",
    "swallowed_catch_count",
    "catch_block_count",
    "error_return_contract_total_count",
    "error_return_contract_dominant_count",
    "generic_exception_throw_count",
    "exception_throw_count",
    "business_exception_throw_count",
    "standard_business_exception_throw_count",
    "nonstandard_business_exception_throw_count",
}

BEHAVIOR_LOCATION_TABLE_IDS = {
    "failure_strategy_issues",
    "swallowed_exception_issues",
    "error_return_contract_issues",
    "generic_exception_issues",
    "business_exception_convergence_issues",
}

COGNITION_LOCATION_TABLE_IDS = {
    "debt_marker_issues",
    "unowned_debt_issues",
    "public_knowledge_gap_issues",
    "complex_method_issues",
    "large_file_class_issues",
    "project_doc_gap_overview",
    "project_doc_issues",
}

BEHAVIOR_EXPORT_DETAIL_FIELDS = (
    BEHAVIOR_VISIBLE_METRIC_FIELDS
    | BEHAVIOR_LOCATION_TABLE_IDS
    | {
        "table_total_counts",
        "failure_strategy_distribution",
        "error_return_contract_distribution",
        "preferred_return_wrappers",
    }
)

BEHAVIOR_METRIC_EXPLANATIONS: dict[str, tuple[str, str]] = {
    "failure_strategy_split_ratio": ("失败处理策略分裂", "1 - 主导失败处理策略数 / catch 块总数；按 catch 块归类，避免旧版关键词重复计数。"),
    "failure_strategy_count": ("失败处理策略分裂", "本次识别出的失败处理策略类型数，例如重新抛异常、返回包装错误、只打日志等。"),
    "failure_strategy_total_count": ("失败处理策略分裂", "参与失败策略分裂计算的 catch 块数量。"),
    "failure_strategy_dominant_count": ("失败处理策略分裂", "命中最多的失败处理策略数量，用作分裂比例的分子来源。"),
    "catch_block_count": ("吞异常比例", "本次扫描到的 catch 块总数，也是吞异常比例的分母。"),
    "swallowed_catch_count": ("吞异常比例", "空 catch、只打日志或没有 throw/return 失败处理的 catch 块数量。"),
    "swallowed_exception_ratio": ("吞异常比例", "吞异常 catch 块数 / catch 块总数。"),
    "error_return_contract_mix_ratio": ("返回错误契约混用", "1 - 主导错误契约数 / Controller/API 层失败契约总数。"),
    "error_return_contract_count": ("返回错误契约混用", "Controller/API 层识别出的失败契约类型数。"),
    "error_return_contract_total_count": ("返回错误契约混用", "Controller/API 层失败返回或直接抛异常的总次数。"),
    "error_return_contract_dominant_count": ("返回错误契约混用", "命中最多的错误契约数量，用作混用比例的分子来源。"),
    "generic_exception_throw_ratio": ("泛化异常滥用", "throw new Exception/RuntimeException/Throwable 次数 / 全部异常抛出次数。"),
    "generic_exception_throw_count": ("泛化异常滥用", "缺少业务语义的泛化异常抛出次数。"),
    "exception_throw_count": ("泛化异常滥用", "本次识别到的 throw new XxxException/Throwable 总次数。"),
    "business_exception_convergence_gap": ("业务异常未收敛", "非标准业务异常抛出次数 / 业务异常抛出总次数；值越高表示越未收敛。"),
    "business_exception_throw_count": ("业务异常未收敛", "按配置和业务异常命名模式识别到的业务异常抛出总次数。"),
    "standard_business_exception_throw_count": ("业务异常未收敛", "命中标准业务异常集合的抛出次数。"),
    "nonstandard_business_exception_throw_count": ("业务异常未收敛", "业务异常中未命中标准业务异常集合的抛出次数。"),
    "standard_business_exceptions": ("业务异常未收敛", "当前用于判断收敛的标准业务异常集合。"),
    "business_exception_detection_mode": ("业务异常未收敛", "标准业务异常集合来源；configured 表示来自配置，default 表示使用默认 BusinessException。"),
    "project_kind": ("扫描画像", "项目类型画像，用来解释返回错误契约为什么默认只扫 Controller/API 层。"),
    "controller_candidates": ("扫描画像", "被识别为 Controller/API 的 Java 文件数量。"),
    "return_scan_scope": ("扫描画像", "返回契约扫描的实际范围。"),
    "return_analysis_mode": ("扫描画像", "返回契约分析模式。"),
    "configured_return_scan_scope": ("扫描画像", "配置中声明的返回契约扫描范围，用来和实际扫描范围对照。"),
    "project_detection_mode": ("扫描画像", "项目类型识别方式，用来解释 Controller/API 扫描范围来源。"),
    "return_degraded_reason": ("扫描画像", "当项目没有识别到 Controller/API 时的返回契约扫描降级原因。"),
    "preferred_return_wrappers": ("扫描画像", "配置中优先识别的返回包装类型，用于识别包装错误响应。"),
}

COGNITION_METRIC_RULE_ORDER = {
    "扫描规模": 0,
    "债务标记密度": 1,
    "未归属债务比例": 2,
    "公共知识缺口比例": 3,
    "复杂方法比例": 4,
    "大文件/大类负担比例": 5,
    "项目文档缺口比例": 6,
    "辅助指标": 90,
}

COGNITION_VISIBLE_METRIC_FIELDS = {
    "total_files",
    "todo_count",
    "todo_with_owner",
    "unowned_todo_count",
    "debt_marker_counts",
    "owner_pattern_count",
    "knowledge_scope",
    "knowledge_documented_count",
    "knowledge_target_count",
    "knowledge_missing_count",
    "knowledge_coverage",
    "total_methods",
    "complex_method_count",
    "large_method_threshold",
    "complex_method_branch_threshold",
    "complex_method_nesting_threshold",
    "large_file_class_count",
    "large_file_lines_threshold",
    "large_class_lines_threshold",
    "project_doc_quality_score",
    "project_doc_gap_ratio",
    "project_doc_entry_exists",
    "project_doc_entry_chars",
    "project_doc_file_count",
    "project_doc_total_chars",
    "project_doc_required_topic_count",
    "project_doc_covered_topic_count",
    "project_doc_missing_topic_count",
    "project_doc_has_examples",
    "project_doc_has_structure_signal",
    "project_doc_code_block_count",
    "project_doc_table_count",
    "project_doc_image_count",
    "project_doc_link_count",
    "project_doc_min_total_chars",
    "project_doc_min_entry_chars",
    "project_doc_min_doc_files",
    "avg_method_lines",
    "avg_file_lines",
}

COGNITION_METRIC_EXPLANATIONS: dict[str, tuple[str, str]] = {
    "total_files": ("扫描规模", "本次纳入认知熵统计的 Java 文件总数，是债务密度和大文件负担的分母。"),
    "todo_count": ("债务标记密度", "TODO / FIXME / HACK 等债务标记总数，是债务标记密度和未归属债务比例的基础数量。"),
    "todo_with_owner": ("未归属债务比例", "债务文本中命中责任人识别规则的数量，用来和未归属债务数对照。"),
    "unowned_todo_count": ("未归属债务比例", "未命中责任人模式的债务标记数量，是未归属债务比例的分子。"),
    "debt_marker_counts": ("债务标记密度", "按 TODO/FIXME/HACK 类型拆开的债务数量，用于排查债务来源。"),
    "owner_pattern_count": ("未归属债务比例", "配置中用于识别责任人的正则数量。"),
    "knowledge_scope": ("公共知识缺口比例", "当前公共知识缺口的扫描范围，例如 public class / public method。"),
    "knowledge_documented_count": ("公共知识缺口比例", "已经有 JavaDoc 的公共类或公共方法数量。"),
    "knowledge_target_count": ("公共知识缺口比例", "需要沉淀 JavaDoc 的公共类或公共方法总数，是公共知识缺口比例的分母。"),
    "knowledge_missing_count": ("公共知识缺口比例", "缺少 JavaDoc 的公共类或公共方法数量，是公共知识缺口比例的分子。"),
    "knowledge_coverage": ("公共知识缺口比例", "公共知识覆盖率，用于和缺口比例互相校验。"),
    "total_methods": ("复杂方法比例", "本次识别到的方法总数，是复杂方法比例的分母。"),
    "complex_method_count": ("复杂方法比例", "方法体过长、分支过多或嵌套过深的方法数量，是复杂方法比例的分子。"),
    "large_method_threshold": ("复杂方法比例", "方法体行数超过该阈值时，会被判为复杂方法。"),
    "complex_method_branch_threshold": ("复杂方法比例", "方法分支数达到该阈值时，会被判为复杂方法。"),
    "complex_method_nesting_threshold": ("复杂方法比例", "方法嵌套深度达到该阈值时，会被判为复杂方法。"),
    "large_file_class_count": ("大文件/大类负担比例", "超过大文件阈值的 Java 文件数量，是大文件/大类负担比例的分子。"),
    "large_file_lines_threshold": ("大文件/大类负担比例", "物理总行数超过该阈值时，会进入大文件/大类负担清单。"),
    "large_class_lines_threshold": ("大文件/大类负担比例", "类级负担的参考阈值；当前 MVP 以文件物理总行数作为轻量近似。"),
    "project_doc_quality_score": ("项目文档缺口比例", "项目说明文档可用度，综合入口 README、文档总量、主题覆盖、示例和结构化说明。"),
    "project_doc_gap_ratio": ("项目文档缺口比例", "项目文档缺口比例 = 1 - 项目说明文档可用度。"),
    "project_doc_entry_exists": ("项目文档缺口比例", "根目录是否存在 README.md、README_CN.md 或 readme.md 等入口文档。"),
    "project_doc_entry_chars": ("项目文档缺口比例", "入口文档的正文字符数，用于判断 README 是否只是空壳。"),
    "project_doc_file_count": ("项目文档缺口比例", "命中的项目说明文档数量，包含入口 README 和 docs/doc/readme/wiki 下的 Markdown/AsciiDoc。"),
    "project_doc_total_chars": ("项目文档缺口比例", "项目说明文档正文总字符数，用于判断文档总量是否足够。"),
    "project_doc_required_topic_count": ("项目文档缺口比例", "配置要求覆盖的通用项目说明主题数量。"),
    "project_doc_covered_topic_count": ("项目文档缺口比例", "已在 README 或文档目录中命中的项目说明主题数量。"),
    "project_doc_missing_topic_count": ("项目文档缺口比例", "未命中的项目说明主题数量，会进入项目文档缺口清单。"),
    "project_doc_has_examples": ("项目文档缺口比例", "是否存在代码块、启动命令或配置示例。"),
    "project_doc_has_structure_signal": ("项目文档缺口比例", "是否存在表格、图示或清晰标题结构。"),
    "project_doc_code_block_count": ("项目文档缺口比例", "文档中的代码块数量。"),
    "project_doc_table_count": ("项目文档缺口比例", "文档中的 Markdown 表格行数量。"),
    "project_doc_image_count": ("项目文档缺口比例", "文档中的图片引用数量。"),
    "project_doc_link_count": ("项目文档缺口比例", "文档中的普通链接数量。"),
    "project_doc_min_total_chars": ("项目文档缺口比例", "配置要求的项目说明文档正文总字符数下限。"),
    "project_doc_min_entry_chars": ("项目文档缺口比例", "配置要求的入口 README 正文字符数下限。"),
    "project_doc_min_doc_files": ("项目文档缺口比例", "配置要求的说明文档文件数量下限。"),
    "avg_method_lines": ("辅助指标", "方法平均行数只作为背景排查，不再参与认知熵主评分。"),
    "avg_file_lines": ("辅助指标", "文件平均物理总行数只作为背景排查，不直接参与主评分。"),
}

STYLE_METRIC_RULE_ORDER = {
    "扫描画像": 0,
    "格式排版问题": 1,
    "命名规范问题": 2,
    "导入规范问题": 3,
    "注解与声明规范问题": 4,
    "编码坏味道问题": 5,
    "复杂度与规模问题": 6,
    "Checkstyle 执行": 90,
}

STYLE_VISIBLE_METRIC_FIELDS = {
    "java_file_count",
    "java_line_count",
    "java_kloc",
    "style_total_violation_count",
    "checkstyle_enabled",
    "checkstyle_status",
    "checkstyle_java_version_family",
    "checkstyle_config",
    "checkstyle_message",
}

STYLE_LOCATION_TABLE_IDS = {
    "style_formatting_issues",
    "style_naming_issues",
    "style_import_issues",
    "style_declaration_issues",
    "style_code_smell_issues",
    "style_complexity_issues",
}

STYLE_METRIC_EXPLANATIONS: dict[str, tuple[str, str]] = {
    "java_file_count": ("扫描画像", "本次进入 Checkstyle 风格熵扫描的 Java 文件数量。"),
    "java_line_count": ("扫描画像", "本次进入风格熵扫描的 Java 物理总行数，用来折算每千行问题密度。"),
    "java_kloc": ("扫描画像", "Java 物理总行数 / 1000，是六类风格规则密度的分母。"),
    "style_total_violation_count": ("扫描画像", "Checkstyle 输出并经过 severity、文件类型和排除规则过滤后的问题总数。"),
    "checkstyle_enabled": ("Checkstyle 执行", "是否启用 Checkstyle 作为风格熵检测器。"),
    "checkstyle_status": ("Checkstyle 执行", "Checkstyle 执行状态；ok 表示已产出 XML，failed/missing 表示工具或配置不可用。"),
    "checkstyle_java_version_family": ("Checkstyle 执行", "本次按运行时 JDK 选择的 Checkstyle 版本口径：jdk8 或 jdk17。"),
    "checkstyle_config": ("Checkstyle 执行", "本次实际使用的 Checkstyle XML 配置文件。"),
    "checkstyle_message": ("Checkstyle 执行", "Checkstyle 标准输出或错误输出中的补充信息，用于排查工具执行失败。"),
}

STRUCTURE_METRIC_RULE_ORDER = {
    "通用基数": 0,
    "共享承载目录占比": 1,
    "最大目录文件占比": 2,
    "超大目录数量占比": 3,
    "前 N 大目录集中度": 4,
    "平均目录文件数": 5,
    "其他指标": 99,
}

STRUCTURE_METRIC_FIELD_ORDER = {
    "total_files": 0,
    "total_directories": 1,
    "common_files": 10,
    "util_files": 11,
    "shared_bucket_total": 12,
    "shared_bucket_overlap_files": 13,
    "max_dir_files": 20,
    "max_dir_name": 21,
    "oversized_dir_count": 30,
    "oversized_dir_file_threshold": 31,
    "top_n_dir_file_sum": 40,
    "top_n_concentration_count": 41,
    "avg_files_per_dir": 50,
}

UI_LOCALIZATION = {
    "Validation coverage and target completeness evaluated": "已按验证覆盖率与目标完整度进行判定。",
}

UI_LOCALIZATION_PREFIXES = {
    "Code entropy total entropy / derived health: ": "代码熵总熵 / 派生健康度：",
    "Code entropy source: ": "代码熵来源：",
    "manual exclusion ": "人工排除项 ",
}

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"
    "\u2600-\u27BF"
    "\uFE0F"
    "]+",
    flags=re.UNICODE,
)

UI_ICON_SVGS = {
    "structure": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="4" width="6" height="6" rx="1.5"/><rect x="14.5" y="4" width="6" height="6" rx="1.5"/><rect x="9" y="14" width="6" height="6" rx="1.5"/><path d="M6.5 10v2.5m11-2.5v2.5M6.5 12.5h11"/></svg>',
    "semantic": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 6h10M7 12h7M7 18h10"/><path d="M4 6h.01M4 12h.01M4 18h.01"/></svg>',
    "behavior": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6h6a3 3 0 0 1 3 3v9"/><path d="M10 6L7.5 3.5M10 6L7.5 8.5"/><path d="M15 18h5"/><path d="M19 15.5 21.5 18 19 20.5"/></svg>',
    "cognition": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 6.5A2.5 2.5 0 0 1 7.5 4H19v16H7.5A2.5 2.5 0 0 0 5 22Z"/><path d="M5 6.5v13A2.5 2.5 0 0 1 7.5 17H19"/></svg>',
    "style": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 18a4 4 0 0 1 4-4c1 0 2 .4 2.7 1.1L18.5 7.3a2.1 2.1 0 1 0-3-3l-7.8 7.8A3.8 3.8 0 0 0 4 18Z"/><path d="M14 6l4 4"/></svg>',
    "details": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h12M8 12h12M8 18h12"/><path d="M4 6h.01M4 12h.01M4 18h.01"/></svg>',
    "dot": '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="4"/></svg>',
}

DETAIL_LABELS = {
    "total_files": "文件总数",
    "total_directories": "目录总数",
    "common_files": "common 文件数",
    "util_files": "util 文件数",
    "shared_bucket_total": "共享承载目录总量",
    "shared_bucket_overlap_files": "共享与工具目录重叠文件数",
    "shared_bucket_ratio": "共享承载目录占比",
    "shared_aliases": "共享目录别名",
    "utility_aliases": "工具目录别名",
    "shared_path_prefixes": "共享目录前缀",
    "utility_path_prefixes": "工具目录前缀",
    "shared_bucket_dirs": "共享承载命中目录",
    "common_bucket_dirs": "common 命中目录",
    "utility_bucket_dirs": "util 命中目录",
    "max_dir_files": "最大目录文件数",
    "max_dir_files_ratio": "最大目录文件占比",
    "max_dir_name": "最大目录",
    "oversized_dir_count": "超大目录数量",
    "oversized_dir_file_threshold": "超大目录阈值",
    "oversized_dirs": "超大目录列表",
    "top_n_dir_file_sum": "前 N 大目录文件总量",
    "top_n_concentration_count": "前 N 大目录数量",
    "top_n_concentration_dirs": "前 N 大目录",
    "avg_files_per_dir": "平均目录文件数",
    "top_large_dirs": "大目录 Top",
    "sample_files": "样例文件",
    "lines": "行数",
    "path": "路径",
    "total_classes": "类总数",
    "total_methods": "方法总数",
    "naming_inconsistency_count": "出现变体的概念数",
    "glossary_matched_terms": "词典命中术语数",
    "naming_matched_hit_count": "命名总命中数",
    "naming_standard_hit_count": "标准命中数",
    "naming_nonstandard_hit_count": "非标准命中数",
    "naming_variant_family_count": "变体家族数",
    "naming_patterns": "命名模式分布",
    "naming_inconsistency_ratio": "命名非标准占比",
    "term_gap_ratio": "术语缺口比例",
    "term_coverage": "术语覆盖率",
    "defined_terms": "已覆盖术语数",
    "term_gap_candidate_count": "候选术语数",
    "term_gap_raw_term_count": "原始术语命中次数",
    "term_gap_raw_unique_term_count": "原始唯一术语数",
    "term_gap_min_occurrences": "候选最小出现次数",
    "term_gap_candidate_mode": "术语候选模式",
    "term_gap_max_candidate_terms": "候选术语上限",
    "undefined_terms": "未定义术语数",
    "undefined_terms_list": "未定义术语列表",
    "undefined_term_issues": "术语缺口问题",
    "undefined_term_locations": "术语缺口定位",
    "state_definitions": "状态承载体数",
    "duplicate_states": "冗余状态承载体数",
    "state_item_total": "状态项总数",
    "state_unique_item_count": "唯一状态项数",
    "state_files": "状态承载体文件数",
    "state_duplicate_cluster_count": "状态承载体重复簇数",
    "state_duplicate_clusters": "状态承载体重复簇明细",
    "state_duplicate_cluster_issues": "状态承载体重复簇",
    "state_duplicate_carrier_issues": "状态承载体重复定位",
    "state_value_scatter_ratio": "状态值散落比例",
    "state_scattered_value_count": "硬编码状态值次数",
    "state_scattered_value_unique_count": "硬编码状态值种类",
    "state_scattered_value_file_count": "状态值散落文件数",
    "state_scattered_value_total_file_count": "状态值散落涉及文件数",
    "state_scattered_value_candidate_count": "疑似状态值次数",
    "state_scattered_value_candidate_unique_count": "疑似状态值种类",
    "state_value_reference_count": "状态值引用总量",
    "state_scattered_value_issues": "状态值散落问题",
    "state_scattered_value_locations": "状态值散落代码定位",
    "top_inconsistent_terms": "不一致术语 Top",
    "naming_conflict_issues": "变体家族说明",
    "naming_conflict_locations": "非标准命名代码定位",
    "term_variants": "术语变体分布",
    "semantic_rule_overview": "规则问题概要",
    "variant_threshold": "术语变体阈值",
    "glossary_mode": "词典模式",
    "glossary_enabled": "是否启用词典",
    "term_scan_targets": "术语扫描目标",
    "state_detection_mode": "状态检测模式",
    "state_carrier_name_pattern_count": "状态承载体命名规则数",
    "state_ignore_item_pattern_count": "状态项忽略规则数",
    "state_min_carrier_items": "状态承载体最小状态项数",
    "state_min_shared_items": "重复判定最小共享状态项数",
    "state_similarity_threshold": "重复判定相似度阈值",
    "state_scatter_detection_mode": "状态值散落检测模式",
    "term_gap_glossary_missing": "术语缺口词典是否缺失",
    "term_gap_glossary_terms": "术语缺口词典术语数",
    "glossary_missing": "glossary 是否缺失",
    "glossary_source_type": "glossary 来源类型",
    "missing_glossary_policy": "缺失词典处理策略",
    "naming_glossary_missing": "命名词典是否缺失",
    "naming_glossary_terms": "命名词典术语数",
    "sample_locations": "样例代码位置",
    "value": "值",
    "confidence": "类型",
    "occurrence_count": "总次数",
    "scored_occurrence_count": "计分次数",
    "candidate_occurrence_count": "疑似次数",
    "file_count": "文件数",
    "raw_value": "原始值",
    "scored": "参与计分",
    "context": "代码上下文",
    "carrier_names": "涉及状态承载体",
    "cluster_id": "重复簇 ID",
    "source": "来源",
    "class_name": "类名",
    "excess": "超预算变体数",
    "focus": "修复重点",
    "summary": "问题摘要",
    "problem_count": "问题对象数",
    "problem_unit": "计数对象",
    "count_summary": "计数说明",
    "current_value": "当前规则值",
    "entry_status": "入口文档",
    "status": "计分状态",
    "rule_status": "规则状态",
    "score_status": "计分状态",
    "coverage": "评分覆盖率",
    "missing_rule_ids": "未计分规则",
    "partial_reason": "部分计分原因",
    "pending_reason": "待配置原因",
    "scored": "是否计分",
    "rule_status": "规则状态",
    "display_count": "当前展示数",
    "total_count": "总数",
    "rule": "规则",
    "error_handling_patterns": "错误处理模式数",
    "return_format_types": "返回格式类型数",
    "exception_types": "异常类型数",
    "error_consistency": "错误处理一致性",
    "return_consistency": "返回格式一致性",
    "exception_type_density_per_k_files": "每千文件异常类型密度",
    "failure_strategy_split_ratio": "失败处理策略分裂比例",
    "swallowed_exception_ratio": "吞异常比例",
    "error_return_contract_mix_ratio": "返回错误契约混用比例",
    "generic_exception_throw_ratio": "泛化异常抛出比例",
    "business_exception_convergence_gap": "业务异常未收敛比例",
    "catch_block_count": "catch 块总数",
    "failure_strategy_count": "失败处理策略类型数",
    "failure_strategy_total_count": "失败处理策略总数",
    "failure_strategy_dominant_count": "主导失败处理策略数",
    "swallowed_catch_count": "吞异常 catch 块数",
    "error_return_contract_count": "错误契约类型数",
    "error_return_contract_total_count": "错误契约总数",
    "error_return_contract_dominant_count": "主导错误契约数",
    "generic_exception_throw_count": "泛化异常抛出数",
    "exception_throw_count": "异常抛出总数",
    "business_exception_throw_count": "业务异常抛出总数",
    "standard_business_exception_throw_count": "标准业务异常抛出数",
    "nonstandard_business_exception_throw_count": "非标准业务异常抛出数",
    "standard_business_exceptions": "标准业务异常集合",
    "business_exception_detection_mode": "业务异常识别模式",
    "project_kind": "项目类型",
    "project_detection_mode": "项目识别方式",
    "controller_candidates": "Controller 候选数",
    "configured_return_scan_scope": "配置扫描范围",
    "return_scan_scope": "实际扫描范围",
    "return_analysis_mode": "返回分析模式",
    "return_degraded_reason": "自动降级原因",
    "preferred_return_wrappers": "推荐返回包装",
    "analysis_mode": "分析模式",
    "top_error_patterns": "错误模式 Top",
    "top_return_formats": "返回格式 Top",
    "top_exceptions": "异常类型 Top",
    "todo_count": "TODO 数量",
    "todo_density_per_k_files": "每千文件债务标记数",
    "todo_with_owner": "有责任人的 TODO",
    "unowned_todo_count": "未归属债务数",
    "unowned_debt_ratio": "未归属债务比例",
    "fixme_count": "FIXME 数量",
    "hack_count": "HACK 数量",
    "knowledge_scope": "公共知识统计范围",
    "knowledge_documented_count": "已沉淀公共知识数",
    "knowledge_target_count": "公共知识目标总数",
    "knowledge_missing_count": "公共知识缺口数",
    "knowledge_coverage": "公共知识覆盖率",
    "public_knowledge_gap_ratio": "公共知识缺口比例",
    "javadoc_coverage": "JavaDoc 覆盖率",
    "javadoc_gap_ratio": "JavaDoc 缺口比例",
    "missing_javadoc": "缺少 JavaDoc 数",
    "complex_method_ratio": "复杂方法比例",
    "complex_method_count": "复杂方法数",
    "complex_method_branch_threshold": "复杂方法分支阈值",
    "complex_method_nesting_threshold": "复杂方法嵌套阈值",
    "large_methods": "大型方法数",
    "large_method_ratio": "大型方法比例",
    "large_file_class_burden_ratio": "大文件/大类负担比例",
    "large_file_class_count": "大文件/大类数量",
    "large_file_lines_threshold": "大文件阈值",
    "large_classes": "大型类数",
    "project_doc_gap_ratio": "项目文档缺口比例",
    "project_doc_quality_score": "项目文档可用度",
    "project_doc_entry_exists": "入口文档是否存在",
    "project_doc_entry_chars": "入口文档字符数",
    "project_doc_file_count": "说明文档数",
    "project_doc_total_chars": "文档总字符数",
    "project_doc_required_topic_count": "要求主题数",
    "project_doc_covered_topic_count": "已覆盖主题数",
    "project_doc_missing_topic_count": "缺失主题数",
    "project_doc_has_examples": "是否有示例",
    "project_doc_has_structure_signal": "是否有结构化说明",
    "project_doc_code_block_count": "代码块数",
    "project_doc_table_count": "表格行数",
    "project_doc_image_count": "图片数",
    "project_doc_link_count": "链接数",
    "project_doc_min_total_chars": "文档总量阈值",
    "project_doc_min_entry_chars": "入口文档阈值",
    "project_doc_min_doc_files": "文档数量阈值",
    "avg_method_lines": "平均方法行数",
    "avg_class_lines": "平均类行数",
    "top_todos": "TODO 文件 Top",
    "debt_marker_counts": "债务标记分布",
    "owner_pattern_count": "责任人识别规则数",
    "javadoc_scope": "JavaDoc 统计范围",
    "javadoc_target_count": "JavaDoc 目标总数",
    "large_method_threshold": "大型方法阈值",
    "large_class_threshold": "大型类阈值",
    "style_formatting_density": "格式排版问题密度",
    "style_naming_density": "命名规范问题密度",
    "style_import_density": "导入规范问题密度",
    "style_declaration_density": "注解与声明规范问题密度",
    "style_code_smell_density": "编码坏味道问题密度",
    "style_complexity_density": "复杂度与规模问题密度",
    "style_total_violation_count": "Checkstyle 问题总数",
    "java_file_count": "Java 文件数",
    "java_line_count": "Java 物理行数",
    "java_kloc": "Java 千行数",
    "checkstyle_enabled": "Checkstyle 是否启用",
    "checkstyle_status": "Checkstyle 执行状态",
    "checkstyle_java_version_family": "Checkstyle 版本口径",
    "checkstyle_config": "Checkstyle 配置文件",
    "checkstyle_message": "Checkstyle 执行信息",
    "style_rule_overview": "风格规则总览",
    "checkstyle_module_distribution": "Checkstyle 规则分布",
    "category": "问题分类",
    "category_label": "问题分类",
    "module": "具体规则",
    "source": "原始来源",
    "severity": "级别",
    "column": "列号",
    "message": "原始提示",
    "description": "中文说明",
    "issue_count": "问题数",
    "pattern": "模式",
    "format": "格式",
    "strategy": "处理策略",
    "contract": "错误契约",
    "exception_type": "异常类型",
    "count": "数量",
    "file": "文件",
    "dir": "目录",
    "files": "文件数",
    "line": "行号",
    "content": "内容",
    "has_owner": "有责任人",
    "target_type": "目标类型",
    "visibility": "可见性",
    "reason": "命中原因",
    "branch_count": "分支数",
    "nesting_depth": "嵌套深度",
    "method": "方法",
    "start_line": "起始行",
    "issue_type": "问题类型",
    "target": "检查项",
    "current": "当前情况",
    "expected": "期望标准",
    "topic": "主题",
    "matched_aliases": "命中别名",
    "required_aliases": "主题别名",
    "chars": "字符数",
    "headings": "标题数",
    "code_blocks": "代码块数",
    "tables": "表格行数",
    "images": "图片数",
    "links": "链接数",
    "style": "风格",
    "name": "名称",
    "standard": "标准术语",
    "usage_count": "使用次数",
    "term": "术语",
    "variant_count": "变体数量",
    "matched_hits": "总命中数",
    "standard_hits": "标准命中数",
    "nonstandard_hits": "非标准命中数",
    "nonstandard_ratio": "非标准命中占比",
    "variants": "变体示例",
    "match_source_applied": "命中来源",
    "match_values_applied": "命中值",
    "common_match_source_applied": "common 命中来源",
    "utility_match_source_applied": "util 命中来源",
    "common_match_values_applied": "common 命中值",
    "utility_match_values_applied": "util 命中值",
    "common": "命中 common",
    "utility": "命中 util",
    "dir_rank": "目录排名",
    "dir_file_count": "目录文件数",
    "common_match_source_applied": "common 命中来源",
    "utility_match_source_applied": "util 命中来源",
    "common_match_values_applied": "common 命中值",
    "utility_match_values_applied": "util 命中值",
    "match_source_applied": "命中来源",
    "match_values_applied": "命中值",
    "id": "规则 ID",
    "label": "规则名称",
    "field": "原始字段",
    "value": "当前值",
    "calculation_description": "计算描述",
    "calculation": "计算口径",
    "metric": "指标字段",
    "state": "规则状态",
    "direction": "方向",
    "unit": "单位",
    "score_0_100": "规则风险分",
    "rule_cn": "规则说明",
    "category": "规则分类",
    "enabled": "启用",
    "weight": "权重",
    "severity": "严重度",
    "skipped": "跳过",
    "raw_value": "原始值",
    "condition": "命中条件",
    "contribution": "风险贡献",
    "max_contribution": "最大贡献",
}

FORMULA_TERM_LABELS = {
    "shared_bucket_total": "共享承载目录唯一文件总量",
    "total_files": "Java 文件总数",
    "max_dir_files": "单个目录直接包含的最大 Java 文件数",
    "oversized_dir_count": "超大目录数量",
    "total_dirs": "含 Java 文件的目录总数",
    "top_n_dir_file_sum": "前 N 大目录合计文件数",
    "naming_nonstandard_hit_count": "非标准命中数",
    "naming_matched_hit_count": "命名总命中数",
    "undefined_term_count": "未进入术语词典的候选术语数",
    "total_terms": "纳入候选池的术语总数",
    "duplicate_state_count": "冗余状态承载体数量",
    "state_count": "状态承载体总数",
    "scattered_state_value_count": "硬编码状态值次数",
    "state_value_reference_count": "状态值引用总量",
    "error_pattern_max_count": "最主导错误处理模式命中次数",
    "error_pattern_total_count": "全部错误处理模式命中次数",
    "return_format_max_count": "最主导返回格式命中次数",
    "return_format_total_count": "全部返回格式命中次数",
    "exception_count": "异常类型或异常模式计数",
    "failure_strategy_dominant_count": "主导失败处理策略数量",
    "failure_strategy_total_count": "失败处理策略总数量",
    "swallowed_catch_count": "吞异常 catch 块数量",
    "catch_block_count": "catch 块总数",
    "error_return_contract_dominant_count": "主导错误返回契约数量",
    "error_return_contract_total_count": "错误返回契约总数量",
    "generic_exception_throw_count": "泛化异常抛出次数",
    "exception_throw_count": "异常抛出总次数",
    "nonstandard_business_exception_throw_count": "非标准业务异常抛出次数",
    "business_exception_throw_count": "业务异常抛出总次数",
    "todo_count": "TODO / FIXME / HACK 等债务标记数量",
    "todo_with_owner": "带责任人的债务标记数量",
    "unowned_todo_count": "未带责任人的债务标记数量",
    "knowledge_documented_count": "已写 JavaDoc 的公共知识目标数量",
    "knowledge_target_count": "应写 JavaDoc 的公共知识目标总数",
    "complex_method_count": "复杂方法数量",
    "large_file_class_count": "大文件/大类负担数量",
    "project_doc_quality_score": "项目说明文档可用度",
    "project_doc_file_count": "命中的项目说明文档数量",
    "project_doc_missing_topic_count": "缺失的通用项目说明主题数量",
    "javadoc_documented_count": "已写 JavaDoc 的目标数量",
    "javadoc_target_count": "应写 JavaDoc 的目标总数",
    "total_method_lines": "全部方法总行数",
    "total_methods": "方法总数",
    "large_method_count": "大型方法数量",
    "dominant_naming_count": "主导命名风格命中次数",
    "total_identifiers": "参与统计的标识符总数",
    "indent_consistency": "缩进一致性得分",
    "brace_consistency": "括号风格一致性得分",
    "comment_lines": "注释行数",
    "total_lines": "代码总行数",
    "avg": "平均值函数",
}

DETAIL_VALUE_LABELS = {
    "project_kind": {
        "spring_web": "Spring Web / API 项目",
        "batch_job": "批处理 / 调度型项目",
        "plain_java": "普通 Java 项目",
        "library": "公共库 / SDK",
        "auto": "自动识别",
    },
    "project_detection_mode": {
        "auto": "自动识别",
        "configured": "配置指定",
        "unknown": "未知",
    },
    "configured_return_scan_scope": {
        "controllers": "仅 Controller",
        "all_java": "全部 Java 文件",
        "skip": "跳过",
    },
    "return_scan_scope": {
        "controllers": "仅 Controller",
        "all_java": "全部 Java 文件",
        "skip": "已跳过",
    },
    "return_analysis_mode": {
        "controllers_only": "按 Controller 分析",
        "all_java": "按全部 Java 分析",
        "degraded_to_all_java": "未识别 Controller，已降级为全量分析",
        "skipped_no_controller": "未识别 Controller，已自动跳过",
        "controllers_empty": "未识别 Controller，但仍按 Controller 范围处理",
    },
    "glossary_mode": {
        "configured_only": "仅使用已配置词典",
    },
    "term_gap_candidate_mode": {
        "top_unique_terms": "按高频唯一术语截断",
    },
    "state_detection_mode": {
        "carrier_item_overlap": "按状态承载体与状态项重合度判重",
    },
    "state_scatter_detection_mode": {
        "status_context_string_literal": "识别状态上下文中的硬编码字面量",
    },
    "glossary_source_type": {
        "project_glossary_md": "来自被扫描项目的 glossary.md",
        "config": "来自审计配置",
        "missing": "未找到 glossary",
    },
    "missing_glossary_policy": {
        "term_gap_only": "仅术语缺口按缺失词典处理",
    },
    "status": {
        "scored": "已计分",
        "pending_config": "待配置",
        "complete": "完整计分",
        "partial": "部分计分",
    },
    "rule_status": {
        "scored": "已计分",
        "pending_config": "待配置",
    },
    "score_status": {
        "complete": "完整计分",
        "partial": "部分计分",
    },
    "source": {
        "file_stem": "文件名",
        "class_name": "类名",
    },
    "kind": {
        "enum": "枚举",
        "class": "常量类",
    },
    "match_source_applied": {
        "prefix": "前缀命中",
        "alias": "别名命中",
    },
    "common": {
        True: "是",
        False: "否",
    },
    "utility": {
        True: "是",
        False: "否",
    },
    "common_match_source_applied": {
        "prefix": "前缀命中",
        "alias": "别名命中",
    },
    "utility_match_source_applied": {
        "prefix": "前缀命中",
        "alias": "别名命中",
    },
    "strategy": {
        "rethrow_specific_exception": "重新抛出具体异常",
        "rethrow_generic_exception": "重新抛出泛化异常",
        "return_wrapped_error": "返回包装错误",
        "return_null": "返回 null",
        "return_error_code": "返回错误码",
        "return_other": "返回其他值",
        "mark_failure_state": "标记失败状态",
        "log_only": "只打日志",
        "empty_swallow": "空 catch",
        "swallow_other": "未处理失败",
    },
    "contract": {
        "wrapped_error_response": "包装错误响应",
        "return_null": "返回 null",
        "return_error_code": "返回错误码",
        "return_string": "返回字符串",
        "return_boolean": "返回布尔值",
        "throw_exception": "直接抛异常",
    },
    "business_exception_detection_mode": {
        "configured_standard_types": "来自配置的标准业务异常集合",
        "default_standard_type": "默认 BusinessException",
    },
}


def _fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"



def _fmt_compact(value: float | None) -> str:
    if value is None:
        return "N/A"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _as_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _fmt_number(value: object, digits: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "N/A"
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{digits}f}"


def _fmt_percent_from_ratio(value: object, digits: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "N/A"
    return f"{float(value) * 100:.{digits}f}%"


def _fmt_ratio_result(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "N/A"
    return f"{float(value):.4f}（{float(value) * 100:.2f}%）"


def _status_class(level: str | None) -> str:
    mapping = {
        "excellent": "excellent",
        "good": "good",
        "notice": "warning",
        "warning": "warning",
        "danger": "danger",
        "pending_config": "warning",
        "high": "danger",
        "medium": "warning",
        "low": "good",
        "pass": "excellent",
        "fail": "danger",
    }
    return mapping.get((level or "").lower(), "good")


def _level_label(level: object) -> str:
    mapping = {
        "excellent": "优秀",
        "good": "良好",
        "notice": "提示",
        "warning": "关注",
        "danger": "高风险",
        "pending_config": "待配置",
        "high": "高",
        "medium": "中",
        "low": "低",
        "pass": "通过",
        "fail": "未通过",
    }
    return mapping.get(str(level or "").lower(), str(level or "未知"))


def _strip_html(value: object) -> str:
    text = str(value or "").replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    for marker in ("<div", "<li", "<ul", "</div>", "</li>", "</ul>"):
        text = text.replace(marker, "\n" + marker)
    in_tag = False
    chars: list[str] = []
    for char in text:
        if char == "<":
            in_tag = True
            continue
        if char == ">":
            in_tag = False
            continue
        if not in_tag:
            chars.append(char)
    lines = [" ".join(line.split()) for line in "".join(chars).splitlines()]
    return "\n".join(line for line in lines if line)


def _short_path(value: object, keep: int = 4) -> str:
    text = str(value or "")
    normalized = text.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if len(parts) <= keep:
        return text
    return ".../" + "/".join(parts[-keep:])



def _score_class(score: float | None) -> str:
    if score is None:
        return "good"
    if score >= 80:
        return "excellent"
    if score >= 65:
        return "good"
    if score >= 50:
        return "warning"
    return "danger"



def _entropy_level_bands(item: dict[str, object] | None = None) -> dict[str, float]:
    if isinstance(item, dict):
        score_breakdown = item.get("score_breakdown") if isinstance(item.get("score_breakdown"), dict) else {}
        level_bands = score_breakdown.get("level_bands") if isinstance(score_breakdown.get("level_bands"), dict) else {}
        if level_bands:
            try:
                return {
                    "excellent": float(level_bands.get("excellent", DEFAULT_ENTROPY_LEVEL_BANDS["excellent"])),
                    "good": float(level_bands.get("good", DEFAULT_ENTROPY_LEVEL_BANDS["good"])),
                    "warning": float(level_bands.get("warning", DEFAULT_ENTROPY_LEVEL_BANDS["warning"])),
                }
            except (TypeError, ValueError):
                pass
    return dict(DEFAULT_ENTROPY_LEVEL_BANDS)


def _entropy_level(score: float | None, item: dict[str, object] | None = None) -> str:
    if score is None:
        return "warning"
    bands = _entropy_level_bands(item)
    if score < bands["excellent"]:
        return "excellent"
    if score < bands["good"]:
        return "good"
    if score < bands["warning"]:
        return "warning"
    return "danger"


def _entropy_score_class(score: float | None) -> str:
    return _entropy_level(score)


def _entropy_visual_label(score: float | None, item: dict[str, object] | None = None) -> str:
    if score is None:
        return "待补数"
    return _level_label(_entropy_level(score, item))


def _entropy_partial_note(item: dict[str, object] | None = None) -> str:
    if not isinstance(item, dict):
        return ""
    if str(item.get("score_status", "complete")).strip().lower() != "partial":
        return ""
    coverage = item.get("coverage")
    coverage_text = ""
    if isinstance(coverage, (int, float)):
        coverage_text = f"评分覆盖 {float(coverage) * 100:.0f}%"
    partial_reason = str(item.get("partial_reason", "") or "").strip()
    if coverage_text and partial_reason:
        return f"部分计分：{coverage_text} · {partial_reason}"
    if coverage_text:
        return f"部分计分：{coverage_text}"
    if partial_reason:
        return f"部分计分：{partial_reason}"
    return "部分计分"


def _entropy_direction_note(score: float | None, item: dict[str, object] | None = None) -> str:
    if score is None:
        return "等待可用扫描结果"
    partial_note = _entropy_partial_note(item)
    if partial_note:
        return partial_note
    level = _entropy_level(score, item)
    if level == "excellent":
        return "当前风险低，适合例行巡检"
    if level == "good":
        return "当前仍可控，建议持续收敛"
    if level == "warning":
        return "已经进入关注区间，建议纳入修复计划"
    return "当前风险高，建议优先修复"



def _esc(value: object) -> str:
    return html.escape(str(value))


def _svg_icon(name: str, label: str | None = None) -> str:
    svg = UI_ICON_SVGS.get(name, UI_ICON_SVGS["dot"])
    attrs = f' role="img" aria-label="{_esc(label)}"' if label else ' aria-hidden="true"'
    return f'<span class="ui-icon ui-icon-{_esc(name)}"{attrs}>{svg}</span>'


def _localize_copy(value: object) -> str:
    text = str(value or "")
    if text in UI_LOCALIZATION:
        return UI_LOCALIZATION[text]
    for prefix, replacement in UI_LOCALIZATION_PREFIXES.items():
        if text.startswith(prefix):
            return replacement + text[len(prefix):]
    return text


def _clean_ui_text(value: object, preserve_lines: bool = False) -> str:
    text = _localize_copy(value)
    text = EMOJI_RE.sub("", text).replace("\u200d", "")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines) if preserve_lines else " ".join(lines)



def _detail_hero_summary(guidance: str, table_count: int, primary_label: str) -> str:
    clean_guidance = _clean_ui_text(guidance)
    clean_primary_label = _clean_ui_text(primary_label) or "基础明细"
    if table_count > 0:
        suffix = f"本页提供 {table_count} 组明细，优先查看{clean_primary_label}。"
    else:
        suffix = "本页暂无明细表，先查看指标摘要。"
    return f"{clean_guidance} {suffix}".strip()


def _json_pretty(value: object) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, indent=2))



def _json_data_url(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    return "data:application/json;charset=utf-8," + quote(payload)


def _detail_label(name: object, details: dict[str, object] | None = None) -> str:
    key = str(name)
    if details:
        if key == "max_dir_files":
            return "最大目录直接文件数"
        if key == "oversized_dir_count":
            threshold = details.get("oversized_dir_file_threshold")
            if isinstance(threshold, (int, float)):
                return f"超大目录数量（>={int(threshold)} 文件）"
        if key == "top_n_dir_file_sum":
            count = details.get("top_n_concentration_count")
            if isinstance(count, (int, float)):
                return f"前 {int(count)} 大目录文件总量"
        if key == "oversized_dirs":
            threshold = details.get("oversized_dir_file_threshold")
            if isinstance(threshold, (int, float)):
                return f"超大目录列表（>={int(threshold)} 文件）"
        if key == "top_n_concentration_dirs":
            count = details.get("top_n_concentration_count")
            if isinstance(count, (int, float)):
                return f"前 {int(count)} 大目录"
    return DETAIL_LABELS.get(key, key)


def _is_percent_metric(name: object) -> bool:
    lowered = str(name).lower()
    if lowered in {"business_exception_convergence_gap"}:
        return True
    return any(token in lowered for token in ["coverage", "consistency", "ratio"])


def _display_value(name: object, value: object, short_path: bool = False) -> str:
    if value is None:
        return "未提供"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        if str(name) == "avg_files_per_dir":
            return f"{value:.2f}"
        if str(name).startswith("style_") and str(name).endswith("_density"):
            return f"{value:.2f} 处/千行"
        if _is_percent_metric(name) and 0 <= value <= 1:
            return f"{value * 100:.1f}%"
        return _fmt_compact(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        mapped = DETAIL_VALUE_LABELS.get(str(name), {}).get(value)
        if mapped:
            return mapped
        if str(name) == "return_degraded_reason" and value.startswith("no_controller_candidates:"):
            kind = value.split(":", 1)[1]
            kind_label = DETAIL_VALUE_LABELS.get("project_kind", {}).get(kind, kind)
            return f"未识别到 Controller 候选，按 {kind_label} 自动降级"
        return _short_path(value) if short_path else value
    if isinstance(value, list):
        return f"{len(value)} 项"
    if isinstance(value, dict):
        return f"{len(value)} 项"
    return str(value)


def _short_detail_label(name: object, details: dict[str, object] | None = None) -> str:
    key = str(name)
    if details:
        if key == "max_dir_files":
            return "最大目录直含文件数"
        if key == "oversized_dir_count":
            threshold = details.get("oversized_dir_file_threshold")
            if isinstance(threshold, (int, float)):
                return f"超大目录数量（阈值 {int(threshold)}）"
        if key == "top_n_dir_file_sum":
            count = details.get("top_n_concentration_count")
            if isinstance(count, (int, float)):
                return f"前 {int(count)} 大目录文件量"
    return DETAIL_SHORT_LABELS.get(key, _detail_label(name, details))


def _entropy_metric_context_note(metric_id: str, item: dict[str, object]) -> tuple[str, str]:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    if metric_id == "shared_bucket_ratio":
        return (
            "shared_bucket_total 只统计当前配置命中的共享承载目录唯一文件总量。",
            "当前 shared_bucket_total 来自配置前缀/别名命中的目录，不是全仓库所有 common/util 字样目录的机械求和。",
        )
    if metric_id == "max_dir_files_ratio":
        return (
            "其中 max_dir_files 指单个目录下直接包含的 Java 文件数，不递归累加子目录。",
            "这里比较的是单目录直接文件占比，不是模块子树总量占比。",
        )
    if metric_id == "oversized_dir_ratio":
        threshold = details.get("oversized_dir_file_threshold")
        if isinstance(threshold, (int, float)):
            threshold_text = f"当前“超大目录”阈值是 >= {int(threshold)} 个直接 Java 文件。"
            return (threshold_text, threshold_text)
    if metric_id == "top_n_dir_concentration":
        count = details.get("top_n_concentration_count")
        if isinstance(count, (int, float)):
            count_text = f"当前 N = {int(count)}，即按前 {int(count)} 大目录合计文件量计算。"
            return (count_text, count_text)
    if metric_id == "naming_inconsistency_ratio":
        return (
            "分子只统计非标准命名的命中次数，例如标准名是 Opp 时，SaleOpp / Opportunity 命中都会进入分子。",
            "分母是该术语家族全部命中次数，所以它衡量的是“非标准命名污染占比”，不是文件占比也不是预算超额率。",
        )
    if metric_id == "term_gap_ratio":
        candidate_mode = _display_value("term_gap_candidate_mode", details.get("term_gap_candidate_mode"))
        min_occurrences = details.get("term_gap_min_occurrences")
        max_terms = details.get("term_gap_max_candidate_terms")
        if str(details.get("term_gap_glossary_missing", "")).strip().lower() == "true":
            if str(details.get("glossary_source_type", "")).strip() == "empty_project_glossary_md":
                basis_note = "项目 glossary.md 没有有效术语配置，本规则按最高风险计分。"
            elif str(details.get("glossary_missing", "")).strip().lower() != "true":
                basis_note = "项目 glossary.md 未配置 used_by=term_gap 的有效术语，本规则按最高风险计分。"
            else:
                basis_note = "未找到项目 glossary.md，本规则按最高风险计分。"
        else:
            basis_note = "当前按空词典口径计分。" if str(details.get("glossary_enabled", "")).strip().lower() in {"false", ""} and str(details.get("missing_glossary_policy", "")).strip().lower() == "term_gap_only" else ""
        return (
            f"候选池按“{candidate_mode}”策略生成；至少出现 {_fmt_number(min_occurrences, 0)} 次才入池，最多保留 {_fmt_number(max_terms, 0)} 个候选术语。{basis_note}",
            "它衡量的是高频核心术语的词典缺口，不是把所有低频切词都算进风险分母。",
        )
    if metric_id == "state_duplicate_ratio":
        threshold = details.get("state_similarity_threshold")
        min_shared = details.get("state_min_shared_items")
        if isinstance(threshold, (int, float)) and isinstance(min_shared, (int, float)):
            return (
                f"先识别 Status/State 承载体，再抽状态项；当前重复阈值为 overlap coefficient >= {_fmt_number(threshold, 2)}，且至少共享 {_fmt_number(min_shared, 0)} 个状态项。",
                "这里只衡量状态承载体是否被并行维护，不直接判断状态业务本身是否合理。",
            )
    if metric_id == "state_value_scatter_ratio":
        mode = _display_value("state_scatter_detection_mode", details.get("state_scatter_detection_mode"))
        return (
            f"当前按“{mode}”识别业务代码里的状态字面量，并排除状态承载体文件本身。",
        "它衡量的是状态值是否散落在判断逻辑中；只有能匹配到已有状态承载体的硬编码值参与计分，未匹配的在同表中标为 candidate。",
        )
    if metric_id == "error_consistency":
        return (
            "分子是命中次数最多的错误处理模式，分母是全部错误处理模式命中总数。",
            "值越接近 1，说明仓库更倾向使用单一错误处理约定。",
        )
    if metric_id == "return_consistency":
        scope = _display_value("return_scan_scope", details.get("return_scan_scope"))
        mode = _display_value("return_analysis_mode", details.get("return_analysis_mode"))
        degraded_reason = _display_value("return_degraded_reason", details.get("return_degraded_reason"))
        formula_note = f"当前返回扫描范围是“{scope}”，分析模式是“{mode}”。"
        meaning_note = "该指标只比较当前扫描范围内识别到的返回格式，不会跨被跳过的文件强行补齐。"
        if degraded_reason != "未提供":
            meaning_note = f"{meaning_note} 当前降级原因：{degraded_reason}。"
        return (formula_note, meaning_note)
    if metric_id == "exception_type_density_per_k_files":
        return (
            "异常类型密度统一按“每千个 Java 文件”折算。",
            "这样不同规模项目之间更容易做横向比较，也避免总文件数增长后绝对值误导。",
        )
    if metric_id == "failure_strategy_split_ratio":
        return (
            "先按 catch 块归类失败处理策略，再看主导策略占比。",
            "这项替代旧版关键词堆次数，避免同一 catch 同时命中 log/throw/try 后被重复解释。",
        )
    if metric_id == "swallowed_exception_ratio":
        return (
            "分子是空 catch、只打日志或没有 throw/return 失败处理的 catch 块数量。",
            "它直接定位会吞掉失败信号的代码位置，值越高排障风险越大。",
        )
    if metric_id == "error_return_contract_mix_ratio":
        scope = _display_value("return_scan_scope", details.get("return_scan_scope"))
        return (
            f"当前只在“{scope}”范围识别失败返回契约。",
            "包装错误、return null、错误码、字符串/布尔返回和直接抛异常如果并存，就会提高混用比例。",
        )
    if metric_id == "generic_exception_throw_ratio":
        return (
            "只统计 throw new Exception、RuntimeException、Throwable 这类泛化异常。",
            "这些异常缺少业务语义，通常会降低调用方处理和排障的确定性。",
        )
    if metric_id == "business_exception_convergence_gap":
        standard = _display_value("standard_business_exceptions", details.get("standard_business_exceptions"))
        return (
            f"当前标准业务异常集合：{standard}。",
            "非标准业务异常占比越高，说明业务错误语义越容易在局部自定义。",
        )
    if metric_id == "todo_density_per_k_files":
        return (
            "这里把 TODO / FIXME / HACK 等债务标记统一折算到每千文件密度。",
            "它比较的是债务密度，不是单纯用 TODO 总量做判断。",
        )
    if metric_id == "todo_owner_ratio":
        count = details.get("owner_pattern_count")
        if isinstance(count, (int, float)):
            return (
                f"责任人识别依赖 {int(count)} 条责任人识别规则。",
                "只要债务文本里命中责任人模式，就会计入“已认领 TODO”。",
            )
    if metric_id == "unowned_debt_ratio":
        count = details.get("owner_pattern_count")
        if isinstance(count, (int, float)):
            return (
                f"责任人识别依赖 {int(count)} 条责任人识别规则。",
                "没有命中责任人识别规则的债务标记会进入未归属债务清单，比例越高越需要先补责任人或清理无效债务。",
            )
    if metric_id == "public_knowledge_gap_ratio":
        scope = _display_value("knowledge_scope", details.get("knowledge_scope"))
        return (
            f"公共知识扫描范围：{scope}。",
            "当前用 JavaDoc 是否存在来判断公共类/公共方法是否完成知识沉淀。",
        )
    if metric_id == "javadoc_gap_ratio":
        scope = _display_value("javadoc_scope", details.get("javadoc_scope"))
        return (
            f"JavaDoc 覆盖统计范围：{scope}。",
            "本指标取缺口而不是覆盖率，所以分数越高表示未文档化目标越多。",
        )
    if metric_id == "avg_method_lines":
        threshold = details.get("large_method_threshold")
        if isinstance(threshold, (int, float)):
            return (
                f"方法行数与“大型方法”阈值分开统计；当前大型方法阈值是 > {int(threshold)} 行。",
                "平均方法行数只是认知熵的辅助信号，不单独主导结论。",
            )
    if metric_id == "large_method_ratio":
        threshold = details.get("large_method_threshold")
        if isinstance(threshold, (int, float)):
            return (
                f"large_method_count 只统计方法体行数 > {int(threshold)} 的方法。",
                "它用比例而不是绝对值，避免仓库规模变化时分数漂移。",
            )
    if metric_id == "complex_method_ratio":
        line_threshold = details.get("large_method_threshold")
        branch_threshold = details.get("complex_method_branch_threshold")
        nesting_threshold = details.get("complex_method_nesting_threshold")
        return (
            f"复杂方法命中条件：方法体行数 > {_fmt_number(line_threshold, 0)}，或分支数 >= {_fmt_number(branch_threshold, 0)}，或嵌套深度 >= {_fmt_number(nesting_threshold, 0)}。",
            "命中任一条件即进入复杂方法清单，并参与复杂方法比例计分。",
        )
    if metric_id == "large_file_class_burden_ratio":
        threshold = details.get("large_file_lines_threshold")
        return (
            f"当前大文件阈值是物理总行数 > {_fmt_number(threshold, 0)} 行。",
            "MVP 以 Java 文件物理总行数作为大文件/大类负担的轻量近似，定位结果可直接回到文件治理。",
        )
    if metric_id == "project_doc_gap_ratio":
        return (
            f"项目文档可用度由入口 README、文档总量、主题覆盖、示例和结构化说明组成；当前可用度为 {_fmt_percent_from_ratio(details.get('project_doc_quality_score'))}。",
            "扫描范围默认包含根目录 README 和 docs/doc/readme/wiki 下的 Markdown/AsciiDoc，可通过 entropy.config.toml 调整。",
        )
    return ("", "")


def _entropy_metric_substitution_note(metric_id: str, item: dict[str, object]) -> str:
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    value = metrics.get(metric_id)

    if metric_id == "shared_bucket_ratio":
        return f"本次代入：{_fmt_number(facts.get('shared_bucket_total'), 0)} / {_fmt_number(facts.get('total_files'), 0)} = {_fmt_ratio_result(value)}"
    if metric_id == "max_dir_files_ratio":
        return f"本次代入：{_fmt_number(facts.get('max_dir_files'), 0)} / {_fmt_number(facts.get('total_files'), 0)} = {_fmt_ratio_result(value)}"
    if metric_id == "oversized_dir_ratio":
        return f"本次代入：{_fmt_number(facts.get('oversized_dir_count'), 0)} / {_fmt_number(facts.get('total_dirs'), 0)} = {_fmt_ratio_result(value)}"
    if metric_id == "top_n_dir_concentration":
        return f"本次代入：{_fmt_number(facts.get('top_n_dir_file_sum'), 0)} / {_fmt_number(facts.get('total_files'), 0)} = {_fmt_ratio_result(value)}"
    if metric_id == "avg_files_per_dir":
        return f"本次代入：{_fmt_number(facts.get('total_files'), 0)} / {_fmt_number(facts.get('total_dirs'), 0)} = {_fmt_number(value)} 文件/目录"
    if metric_id == "naming_inconsistency_ratio":
        return f"本次代入：{_fmt_number(facts.get('naming_nonstandard_hit_count'), 0)} 非标准命中 / {_fmt_number(facts.get('naming_matched_hit_count'), 0)} 命名总命中 = {_fmt_ratio_result(value)}"
    if metric_id == "term_gap_ratio":
        return f"本次代入：{_fmt_number(facts.get('undefined_term_count'), 0)} 未定义术语 / {_fmt_number(facts.get('total_terms'), 0)} 候选术语 = {_fmt_ratio_result(value)}"
    if metric_id == "state_duplicate_ratio":
        return f"本次代入：{_fmt_number(facts.get('duplicate_state_count'), 0)} 冗余承载体 / {_fmt_number(facts.get('state_count'), 0)} 状态承载体 = {_fmt_ratio_result(value)}"
    if metric_id == "state_value_scatter_ratio":
        scattered = facts.get("scattered_state_value_count")
        reference = facts.get("state_value_reference_count")
        carrier_items = None
        if isinstance(reference, (int, float)) and isinstance(scattered, (int, float)):
            carrier_items = reference - scattered
        return (
            f"本次代入：{_fmt_number(scattered, 0)} 计分硬编码状态值 / "
            f"({_fmt_number(carrier_items, 0)} 状态承载体状态项 + {_fmt_number(scattered, 0)} 计分硬编码状态值) "
            f"= {_fmt_ratio_result(value)}"
        )
    if metric_id == "error_consistency":
        total = facts.get("error_pattern_total_count")
        if isinstance(total, (int, float)) and float(total) == 0.0:
            return "本次代入：未识别到错误处理模式，公式按 div(..., default=1) 回退为 100.00%"
        return f"本次代入：{_fmt_number(facts.get('error_pattern_max_count'), 0)} / {_fmt_number(total, 0)} = {_fmt_percent_from_ratio(value)}"
    if metric_id == "return_consistency":
        total = facts.get("return_format_total_count")
        if total is None:
            return f"本次代入：当前扫描范围为“{_display_value('return_scan_scope', details.get('return_scan_scope'))}”，返回格式统计被跳过，规则按缺数处理。"
        if isinstance(total, (int, float)) and float(total) == 0.0:
            return "本次代入：已扫描范围内未识别到返回格式，公式按 div(..., default=1) 回退为 100.00%"
        return f"本次代入：{_fmt_number(facts.get('return_format_max_count'), 0)} / {_fmt_number(total, 0)} = {_fmt_percent_from_ratio(value)}"
    if metric_id == "exception_type_density_per_k_files":
        return f"本次代入：({_fmt_number(facts.get('exception_count'), 0)} x 1000) / {_fmt_number(facts.get('total_files'), 0)} = {_fmt_number(value, 3)}"
    if metric_id == "failure_strategy_split_ratio":
        total = facts.get("failure_strategy_total_count")
        if isinstance(total, (int, float)) and float(total) == 0.0:
            return "本次代入：未识别到 catch 失败处理点，按 0 风险处理。"
        return f"本次代入：1 - ({_fmt_number(facts.get('failure_strategy_dominant_count'), 0)} / {_fmt_number(total, 0)}) = {_fmt_ratio_result(value)}"
    if metric_id == "swallowed_exception_ratio":
        total = facts.get("catch_block_count")
        if isinstance(total, (int, float)) and float(total) == 0.0:
            return "本次代入：未识别到 catch 块，按 0 风险处理。"
        return f"本次代入：{_fmt_number(facts.get('swallowed_catch_count'), 0)} / {_fmt_number(total, 0)} = {_fmt_ratio_result(value)}"
    if metric_id == "error_return_contract_mix_ratio":
        total = facts.get("error_return_contract_total_count")
        if isinstance(total, (int, float)) and float(total) == 0.0:
            return "本次代入：未识别到 Controller/API 失败契约，按 0 风险处理。"
        return f"本次代入：1 - ({_fmt_number(facts.get('error_return_contract_dominant_count'), 0)} / {_fmt_number(total, 0)}) = {_fmt_ratio_result(value)}"
    if metric_id == "generic_exception_throw_ratio":
        total = facts.get("exception_throw_count")
        if isinstance(total, (int, float)) and float(total) == 0.0:
            return "本次代入：未识别到异常抛出，按 0 风险处理。"
        return f"本次代入：{_fmt_number(facts.get('generic_exception_throw_count'), 0)} / {_fmt_number(total, 0)} = {_fmt_ratio_result(value)}"
    if metric_id == "business_exception_convergence_gap":
        total = facts.get("business_exception_throw_count")
        if isinstance(total, (int, float)) and float(total) == 0.0:
            return "本次代入：未识别到业务异常抛出，按 0 风险处理。"
        return f"本次代入：{_fmt_number(facts.get('nonstandard_business_exception_throw_count'), 0)} / {_fmt_number(total, 0)} = {_fmt_ratio_result(value)}"
    if metric_id == "todo_density_per_k_files":
        return f"本次代入：({_fmt_number(facts.get('todo_count'), 0)} x 1000) / {_fmt_number(facts.get('total_files'), 0)} = {_fmt_number(value, 3)}"
    if metric_id == "unowned_debt_ratio":
        total = facts.get("todo_count")
        if isinstance(total, (int, float)) and float(total) == 0.0:
            return "本次代入：当前没有债务标记，未归属债务比例按 0 处理。"
        return f"本次代入：{_fmt_number(facts.get('unowned_todo_count'), 0)} / {_fmt_number(total, 0)} = {_fmt_ratio_result(value)}"
    if metric_id == "todo_owner_ratio":
        todo_count = facts.get("todo_count")
        if isinstance(todo_count, (int, float)) and float(todo_count) == 0.0:
            return "本次代入：当前没有债务标记，责任人覆盖率按 0 处理。"
        return f"本次代入：{_fmt_number(facts.get('todo_with_owner'), 0)} / {_fmt_number(todo_count, 0)} = {_fmt_percent_from_ratio(value)}"
    if metric_id == "public_knowledge_gap_ratio":
        target = facts.get("knowledge_target_count")
        documented = facts.get("knowledge_documented_count")
        if isinstance(target, (int, float)) and float(target) == 0.0:
            return "本次代入：当前没有需要统计的公共知识目标，公式按 1 - 1 = 0.00% 处理。"
        return f"本次代入：1 - ({_fmt_number(documented, 0)} / {_fmt_number(target, 0)}) = {_fmt_ratio_result(value)}"
    if metric_id == "javadoc_gap_ratio":
        target = facts.get("javadoc_target_count")
        documented = facts.get("javadoc_documented_count")
        if isinstance(target, (int, float)) and float(target) == 0.0:
            return "本次代入：当前没有需要统计的 JavaDoc 目标，公式按 1 - 1 = 0.00% 处理。"
        return f"本次代入：1 - ({_fmt_number(documented, 0)} / {_fmt_number(target, 0)}) = {_fmt_percent_from_ratio(value)}"
    if metric_id == "avg_method_lines":
        return f"本次代入：{_fmt_number(facts.get('total_method_lines'))} / {_fmt_number(facts.get('total_methods'), 0)} = {_fmt_number(value)} 行/方法"
    if metric_id == "complex_method_ratio":
        return f"本次代入：{_fmt_number(facts.get('complex_method_count'), 0)} / {_fmt_number(facts.get('total_methods'), 0)} = {_fmt_ratio_result(value)}"
    if metric_id == "large_method_ratio":
        return f"本次代入：{_fmt_number(facts.get('large_method_count'), 0)} / {_fmt_number(facts.get('total_methods'), 0)} = {_fmt_percent_from_ratio(value)}"
    if metric_id == "large_file_class_burden_ratio":
        return f"本次代入：{_fmt_number(facts.get('large_file_class_count'), 0)} / {_fmt_number(facts.get('total_files'), 0)} = {_fmt_ratio_result(value)}"
    if metric_id == "project_doc_gap_ratio":
        return f"本次代入：1 - {_fmt_percent_from_ratio(facts.get('project_doc_quality_score'))} 文档可用度 = {_fmt_ratio_result(value)}"
    style_density_sources = {
        "style_formatting_density": "style_formatting_violation_count",
        "style_naming_density": "style_naming_violation_count",
        "style_import_density": "style_import_violation_count",
        "style_declaration_density": "style_declaration_violation_count",
        "style_code_smell_density": "style_code_smell_violation_count",
        "style_complexity_density": "style_complexity_violation_count",
    }
    if metric_id in style_density_sources:
        source_field = style_density_sources[metric_id]
        return f"本次代入：{_fmt_number(facts.get(source_field), 0)} 处 / {_fmt_number(facts.get('java_kloc'), 3)} 千行代码 = {_fmt_number(value, 2)} 处/千行"
    return ""


def _formula_term_explainer(formula_cn: str) -> str:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", formula_cn or "")
    seen: set[str] = set()
    items: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        label = FORMULA_TERM_LABELS.get(token) or DETAIL_LABELS.get(token)
        if label:
            items.append(f"{token} = {label}")
    return "；".join(items)


def _entropy_guidance(key: str, score: float | None, item: dict[str, object] | None = None) -> str:
    standards = CODE_ENTROPY_STANDARDS.get(key, [])
    if len(standards) < 4:
        return "请打开完整详情查看评分标准。"
    if score is None:
        return standards[0]
    level = _entropy_level(score, item)
    if level == "excellent":
        return standards[1]
    if level == "good":
        return standards[2]
    if level == "warning":
        return standards[3]
    return standards[4] if len(standards) > 4 else standards[-1]


def _metric_highlight_pairs(key: str, details: dict[str, object]) -> list[tuple[str, object]]:
    preferred = {
        "structure": ["shared_bucket_total", "oversized_dir_count", "top_n_dir_file_sum", "max_dir_files"],
        "semantic": ["naming_inconsistency_count", "undefined_terms", "state_duplicate_cluster_count", "state_scattered_value_count"],
        "behavior": ["failure_strategy_split_ratio", "swallowed_exception_ratio", "error_return_contract_mix_ratio", "generic_exception_throw_ratio"],
        "cognition": ["todo_count", "unowned_todo_count", "complex_method_count", "project_doc_gap_ratio"],
        "style": ["style_code_smell_density", "style_formatting_density", "style_naming_density", "style_complexity_density"],
    }.get(key, [])
    rows: list[tuple[str, object]] = []
    used: set[str] = set()
    for name in preferred:
        value = details.get(name)
        if name in details and not isinstance(value, (dict, list)):
            rows.append((name, value))
            used.add(name)
    if len(rows) < 4:
        for name, value in _collect_detail_rows(details, limit=10):
            if name in used:
                continue
            rows.append((name, value))
            used.add(name)
            if len(rows) >= 4:
                break
    return rows[:4]


def _semantic_rule_overview_by_metric(details: dict[str, object]) -> dict[str, dict[str, object]]:
    rows = details.get("semantic_rule_overview")
    if not isinstance(rows, list):
        return {}
    mapping: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        metric = str(row.get("metric", "")).strip()
        if metric:
            mapping[metric] = row
    return mapping


def _dashboard_rule_quick_note(
    key: str,
    metric_id: str,
    rule: dict[str, object],
    details: dict[str, object],
) -> str:
    return ""


def _dashboard_rule_cards(key: str, item: dict[str, object]) -> list[dict[str, str]]:
    score_breakdown = item.get("score_breakdown") if isinstance(item.get("score_breakdown"), dict) else {}
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    rules = score_breakdown.get("rules") if isinstance(score_breakdown.get("rules"), list) else []
    cards: list[dict[str, str]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        label = str(rule.get("label", "")).strip() or str(rule.get("metric", "")).strip() or "未命名规则"
        metric_id = str(rule.get("metric", "")).strip()
        rule_status = str(rule.get("rule_status", "") or rule.get("status", "")).strip().lower()
        if rule_status == "pending_config":
            value = "待配置"
        else:
            value = _display_value(metric_id or label, rule.get("raw_value"))
        note = _dashboard_rule_quick_note(key, metric_id, rule, details)
        cards.append({"label": label, "value": value, "note": note})
    return cards


def _detail_table_label(table_id: str, fallback: object) -> str:
    meta = DETAIL_TABLE_META.get(table_id, {})
    label = str(meta.get("label", "")).strip()
    return label or _clean_ui_text(fallback) or table_id


def _detail_table_description(table_id: str, fallback_label: object = "") -> str:
    meta = DETAIL_TABLE_META.get(table_id, {})
    description = str(meta.get("description", "")).strip()
    if description:
        return description
    label = _clean_ui_text(fallback_label)
    if table_id.endswith("_locations") or table_id.endswith("_carrier_issues"):
        return f"每行是一条{label or '代码定位'}记录，文件和行号可直接用于回查源码。"
    if table_id.endswith("_issues"):
        return f"每行是一条{label or '问题'}记录，用来看问题是怎么被聚合出来的。"
    return "每行都是本次扫描结果的一条明细记录。"


def _detail_count_copy(count: object) -> str:
    if not isinstance(count, (int, float)):
        return "-"
    return f"{int(count)} 条"


def _entropy_scoring_bundle(item: dict[str, object]) -> dict[str, object]:
    scoring_v1 = item.get("scoring_v1") if isinstance(item.get("scoring_v1"), dict) else {}
    metric_definitions = item.get("metric_definitions") if isinstance(item.get("metric_definitions"), dict) else {}
    if not metric_definitions and isinstance(scoring_v1.get("metric_definitions"), dict):
        metric_definitions = scoring_v1.get("metric_definitions")  # type: ignore[assignment]
    score_breakdown = scoring_v1.get("score_breakdown") if isinstance(scoring_v1.get("score_breakdown"), dict) else {}
    active_breakdown = item.get("score_breakdown") if isinstance(item.get("score_breakdown"), dict) else {}
    active_formula = str(active_breakdown.get("formula_version", "")).strip()
    v1_formula = str(score_breakdown.get("formula_version", "")).strip()
    return {
        "available": bool(score_breakdown and metric_definitions),
        "scoring_v1": scoring_v1,
        "metric_definitions": metric_definitions,
        "score_breakdown": score_breakdown,
        "is_active": bool(v1_formula and active_formula and v1_formula == active_formula),
    }


def _entropy_score_formula_line(score_breakdown: dict[str, object]) -> str:
    total = float(score_breakdown.get("score", 0.0) or 0.0)
    max_score = float(score_breakdown.get("max_score", 100.0) or 100.0)
    return f"本次总分 {total:.1f} / {max_score:.0f}"


def _entropy_score_formula_note(score_breakdown: dict[str, object]) -> str:
    score_mode = str(score_breakdown.get("score_mode", "")).strip().lower()
    configured_weight = float(score_breakdown.get("configured_weight", 0.0) or 0.0)
    available_weight = float(score_breakdown.get("available_weight", 0.0) or 0.0)
    configured_rules = int(score_breakdown.get("configured_rule_count", 0) or 0)
    evaluated_rules = int(score_breakdown.get("evaluated_rule_count", 0) or 0)
    partial_reason = str(score_breakdown.get("partial_reason", "") or "").strip()
    if score_mode == "partial_weighted_average":
        base = (
            f"总分仍按 0-100 风险分输出；本次只用实际参与计分的 {evaluated_rules} / "
            f"{configured_rules or evaluated_rules} 条规则重算加权平均，参与权重 {available_weight:.0f} / 固定评分卡 {configured_weight:.0f}。"
            "总分按评分卡保留 1 位小数展示。"
        )
        return f"{base} {partial_reason}".strip()
    if score_mode == "fixed_weighted_average":
        if configured_weight > 0 and abs(configured_weight - available_weight) < 1e-6:
            return (
                f"总分分母固定为 {configured_weight:.0f}；本次 {evaluated_rules} / {configured_rules or evaluated_rules} "
                "条规则都参与了计算，每条规则先算风险分，再按评分卡权重折算贡献；总分按评分卡保留 1 位小数展示。"
            )
        return (
            f"总分分母固定为 {configured_weight:.0f}；本次实际参与计算的权重是 {available_weight:.0f}，"
            "缺数规则不会把分母一并缩小；总分按评分卡保留 1 位小数展示。"
        )
    return "每条规则先算风险分，再按本次参与的权重折算贡献。"


def _entropy_rule_status_label(rule: dict[str, object]) -> str:
    if str(rule.get("rule_status", "")).strip().lower() == "pending_config":
        return "待配置"
    if bool(rule.get("skipped")):
        return "缺数"
    return _level_label(rule.get("status"))


def _entropy_condition_label(value: object) -> str:
    mapping = {
        "default": "未触发风险阈值（默认通过）",
        "missing": "缺少指标值",
    }
    return mapping.get(str(value or "").strip().lower(), _clean_ui_text(value))


def _entropy_score_mode_label(value: object) -> str:
    mapping = {
        "fixed_weighted_average": "固定评分卡加权平均",
        "partial_weighted_average": "部分计分加权平均",
        "weighted_average": "动态权重平均",
    }
    return mapping.get(str(value or "").strip().lower(), _clean_ui_text(value))


def _detail_column_help(column: object) -> str:
    mapping = {
        "label": "规则或指标的中文名称。",
        "metric": "评分卡读取的指标字段。",
        "raw_value": "本次扫描代入评分规则的原始值。",
        "condition": "原始值命中的评分区间或条件。",
        "severity": "命中条件对应的风险系数，越高风险越大。",
        "contribution": "这条规则折算后拉高了多少总分。",
        "max_contribution": "这条规则在当前权重下最多能贡献多少分。",
        "status": "本次命中的风险状态。",
        "weight": "这条规则在当前维度评分中的权重。",
        "current_value": "规则本次计分使用的展示值。",
        "count_summary": "这条规则当前统计对象的简要说明。",
        "problem_count": "当前规则识别出的治理对象数量。",
        "problem_unit": "问题对象数量对应的单位。",
        "summary": "当前扫描结果的自然语言摘要。",
        "focus": "建议优先处理的治理方向。",
        "path": "命中的 Java 文件路径。",
        "dir": "该文件所在目录。",
        "dir_rank": "该目录在按直接 Java 文件数排序后的名次。",
        "dir_file_count": "该文件所在目录直接包含的 Java 文件数。",
        "files": "该目录下直接包含的 Java 文件数。",
        "lines": "该目录或文件的行数；大文件/大类负担中为物理总行数。",
        "sample_files": "该目录下的样例 Java 文件，用于快速判断目录内容。",
        "common": "是否命中 common/shared 类共享承载目录规则。",
        "utility": "是否命中 util/utils 类工具目录规则。",
        "common_match_source_applied": "common/shared 命中的来源，prefix 表示配置路径前缀命中，alias 表示目录名别名命中。",
        "utility_match_source_applied": "util/utils 命中的来源，prefix 表示配置路径前缀命中，alias 表示目录名别名命中。",
        "common_match_values_applied": "触发 common/shared 命中的配置值或别名。",
        "utility_match_values_applied": "触发 util/utils 命中的配置值或别名。",
        "match_source_applied": "目录命中规则的来源。",
        "match_values_applied": "触发目录命中的配置值或别名。",
    }
    return mapping.get(str(column or "").strip().lower(), _detail_label(column))


def _render_entropy_score_explainer(key: str, item: dict[str, object], compact: bool = False) -> str:
    bundle = _entropy_scoring_bundle(item)
    if not bool(bundle["available"]):
        return '<div class="entropy-score-empty">当前还没有可展开的评分卡说明，暂时只能查看结果值和基础明细。</div>'
    score_breakdown = bundle["score_breakdown"] if isinstance(bundle["score_breakdown"], dict) else {}
    metric_definitions = bundle["metric_definitions"] if isinstance(bundle["metric_definitions"], dict) else {}
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    rules = score_breakdown.get("rules") if isinstance(score_breakdown.get("rules"), list) else []
    rule_by_metric = {
        str(rule.get("metric")): rule
        for rule in rules
        if isinstance(rule, dict) and str(rule.get("metric", "")).strip()
    }
    mode_label = "当前主分采用这套评分卡口径" if bool(bundle["is_active"]) else "当前主分尚未切到这套评分卡"
    coverage_value = float(score_breakdown.get("coverage", 0.0) or 0.0)
    coverage_text = f"{coverage_value * 100:.1f}%"
    configured_weight = float(score_breakdown.get("configured_weight", 0.0) or 0.0)
    available_weight = float(score_breakdown.get("available_weight", 0.0) or 0.0)
    formula_version = _clean_ui_text(score_breakdown.get("formula_version", "未提供"))
    score_mode = _entropy_score_mode_label(score_breakdown.get("score_mode", "fixed_weighted_average"))
    summary_cards = [
        ("公式版本", formula_version, "用于判定当前分数口径是否变更"),
        ("固定总权重 / 本次参与", f"{configured_weight:.0f} / {available_weight:.0f}", "左侧是评分卡固定分母，右侧是本次拿到值并实际参与计算的权重"),
        ("评分卡覆盖", coverage_text, "100% 表示所有规则都参与了本次实际计算"),
        ("评分模式", score_mode, mode_label),
    ]
    summary_html = "".join(
        f'''<article class="entropy-score-summary-card">
            <div class="entropy-score-summary-label">{_esc(title)}</div>
            <div class="entropy-score-summary-value">{_esc(value)}</div>
            <div class="entropy-score-summary-note">{_esc(note)}</div>
        </article>'''
        for title, value, note in summary_cards
    )
    step_cards = []
    for metric_id, definition in metric_definitions.items():
        if not isinstance(definition, dict):
            continue
        rule = rule_by_metric.get(metric_id)
        status = _status_class(str(rule.get("status", "good"))) if isinstance(rule, dict) else "good"
        category_label = "定制规则" if str(definition.get("category", "")).strip().lower() == "custom" else "通用规则"
        metric_label = _clean_ui_text(definition.get("label", "")) or _detail_label(str(metric_id), details)
        current_value = _display_value(metric_id, definition.get("value"))
        formula_cn = _clean_ui_text(definition.get("formula_cn", ""))
        meaning_cn = _clean_ui_text(definition.get("meaning_cn", ""))
        formula_terms_cn = _formula_term_explainer(formula_cn)
        formula_context_note, meaning_context_note = _entropy_metric_context_note(str(metric_id), item)
        substitution_note = _entropy_metric_substitution_note(str(metric_id), item)
        if substitution_note:
            substitution_note = re.sub(r"^本次代入：", "", substitution_note)
        if formula_context_note:
            formula_cn = f"{formula_cn} {formula_context_note}" if formula_cn else formula_context_note
        if meaning_context_note:
            meaning_cn = f"{meaning_cn} {meaning_context_note}" if meaning_cn else meaning_context_note
        rule_cn = _clean_ui_text(rule.get("rule_cn", "")) if isinstance(rule, dict) else "当前没有命中的规则。"
        matched_condition = _entropy_condition_label(rule.get("condition", "默认通过")) if isinstance(rule, dict) else "默认通过"
        risk_score = _fmt_compact(rule.get("score_0_100")) if isinstance(rule, dict) and isinstance(rule.get("score_0_100"), (int, float)) else "0"
        contribution = _fmt_compact(rule.get("contribution")) if isinstance(rule, dict) and isinstance(rule.get("contribution"), (int, float)) else "0"
        weight = _fmt_compact(rule.get("weight")) if isinstance(rule, dict) and isinstance(rule.get("weight"), (int, float)) else "0"
        step_cards.append(
            f'''<article class="entropy-score-step entropy-score-step-{status}">
                <div class="entropy-score-step-top">
                    <div>
                        <div class="entropy-score-step-kicker">{_esc(category_label)}</div>
                        <h4>{_esc(metric_label)}</h4>
                    </div>
                    <span class="entropy-score-step-status entropy-score-step-status-{status}">{_esc(_entropy_rule_status_label(rule) if isinstance(rule, dict) else "未命中")}</span>
                </div>
                <div class="entropy-score-step-value-row">
                    <div class="entropy-score-step-value">{_esc(current_value)}</div>
                    <div class="entropy-score-step-meta">折算贡献 {contribution}/100 · 规则风险 {risk_score}/100 · 评分卡权重 {weight}</div>
                </div>
                <div class="entropy-score-step-block">
                    <span>指标公式</span>
                    <p>{_esc(formula_cn)}</p>
                </div>
                {f'''<div class="entropy-score-step-block">
                    <span>计算口径</span>
                    <p>{_esc(substitution_note)}</p>
                </div>''' if substitution_note else ''}
                <div class="entropy-score-step-block">
                    <span>术语解释</span>
                    <p>{_esc(formula_terms_cn or '当前公式中的术语已可直接按字段名理解。')}</p>
                </div>
                <div class="entropy-score-step-block">
                    <span>指标含义</span>
                    <p>{_esc(meaning_cn)}</p>
                </div>
                <div class="entropy-score-step-block">
                    <span>命中规则</span>
                    <p>{_esc(rule_cn)}</p>
                </div>
                <div class="entropy-score-chip-row">
                    <span class="entropy-score-chip">当前命中：{_esc(matched_condition)}</span>
                </div>
            </article>'''
        )
    cards_class = "entropy-score-grid entropy-score-grid-compact" if compact else "entropy-score-grid"
    return f'''<div class="entropy-score-explainer">
        <div class="entropy-score-formula">
            <div class="entropy-score-formula-kicker">{_esc(CODE_ENTROPY_LABELS.get(key, key))}评分卡</div>
            <div class="entropy-score-formula-line">{_esc(_entropy_score_formula_line(score_breakdown))}</div>
            <div class="entropy-score-formula-note">{_esc(_entropy_score_formula_note(score_breakdown))}</div>
        </div>
        <div class="entropy-score-summary-grid">{summary_html}</div>
        <div class="entropy-score-breakdown-head">
            <div class="entropy-score-breakdown-title">分项贡献明细</div>
            <div class="entropy-score-breakdown-desc">每张卡对应一条评分规则：先看当前值和折算贡献，再看中文公式、指标含义和命中规则。</div>
        </div>
        <div class="{cards_class}">{''.join(step_cards) or '<div class="entropy-score-empty">当前没有可展示的指标步骤。</div>'}</div>
    </div>'''


def _render_rich_text(value: object, empty: str = "暂无补充说明。") -> str:
    text = _clean_ui_text(value, preserve_lines=True)
    if not text:
        return f"<p>{_esc(empty)}</p>"
    blocks: list[str] = []
    paragraphs: list[str] = []
    list_items: list[str] = []

    def flush_paragraphs() -> None:
        nonlocal paragraphs
        if not paragraphs:
            return
        blocks.append(f"<p>{_esc(' '.join(paragraphs))}</p>")
        paragraphs = []

    def flush_list() -> None:
        nonlocal list_items
        if not list_items:
            return
        blocks.append("<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in list_items) + "</ul>")
        list_items = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraphs()
            flush_list()
            continue
        if re.match(r"^(?:[-*•]\s+|\d+[.)]\s+)", line):
            flush_paragraphs()
            list_items.append(re.sub(r"^(?:[-*•]\s+|\d+[.)]\s+)", "", line))
            continue
        flush_list()
        paragraphs.append(line)

    flush_paragraphs()
    flush_list()
    return "".join(blocks) or f"<p>{_esc(empty)}</p>"


def _render_fact_list(rows: list[tuple[str, str]], empty: str = "暂无补充说明。") -> str:
    normalized = [(label, value) for label, value in rows if str(label).strip() and str(value).strip()]
    if not normalized:
        return f"<p>{_esc(empty)}</p>"
    return "<ul>" + "".join(f"<li><strong>{_esc(label)}:</strong> {_esc(value)}</li>" for label, value in normalized) + "</ul>"


def _task_lines(value: object, *, strip_html: bool = False) -> list[str]:
    source = _strip_html(value) if strip_html else value
    text = _clean_ui_text(source, preserve_lines=True)
    return [line.strip() for line in text.splitlines() if line.strip()]


def _task_items(value: object, *, strip_html: bool = False, limit: int = 5) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for line in _task_lines(value, strip_html=strip_html):
        normalized = re.sub(r"^(?:[-*•]\s+|\d+[.)]\s+)", "", line).strip()
        if not normalized or normalized.endswith(":") or normalized.endswith("："):
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(normalized)
        if len(items) >= limit:
            break
    return items


def _health_summary_copy(total_entropy_score: float | None, top_metrics: list[tuple[str, float]], summary: dict[str, object] | None = None) -> str:
    if total_entropy_score is None:
        return "当前没有可用的总熵评分，请先补齐采集输入。"
    if total_entropy_score < DEFAULT_ENTROPY_LEVEL_BANDS["excellent"]:
        lead = "当前总熵处于低风险区间，以例行巡检和局部收敛为主。"
    elif total_entropy_score < DEFAULT_ENTROPY_LEVEL_BANDS["good"]:
        lead = "当前总熵仍可控，但已有局部风险项需要持续跟踪。"
    elif total_entropy_score < DEFAULT_ENTROPY_LEVEL_BANDS["warning"]:
        lead = "当前总熵已进入关注区间，建议按优先级安排持续降熵。"
    else:
        lead = "当前总熵已进入高风险区间，建议立即安排专项降熵。"
    if isinstance(summary, dict) and str(summary.get("score_status", "complete")).strip().lower() == "partial":
        partial_reason = str(summary.get("partial_reason", "") or "").strip()
        if partial_reason:
            return f"{lead} 当前总览按部分口径展示：{partial_reason}"
        return f"{lead} 当前总览按部分口径展示。"
    return lead


def _hero_pressure_items(top_metrics: list[tuple[str, float]]) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    for name, score in sorted(top_metrics, key=lambda pair: pair[1], reverse=True)[:2]:
        if score is None:
            continue
        label = CODE_ENTROPY_LABELS.get(name, name)
        items.append((label, f"{_fmt_compact(score)}/100", _entropy_level(score)))
    return items


def _hero_pressure_badges(top_metrics: list[tuple[str, float]]) -> str:
    items = _hero_pressure_items(top_metrics)
    if not items:
        return ""
    return '<div class="hero-pressure-list">' + "".join(
        f'<span class="hero-pressure-pill hero-pressure-pill-{_esc(tone)}">{_esc(label)} <strong>{_esc(score)}</strong></span>'
        for label, score, tone in items
    ) + "</div>"


def _hero_sample_note(statistics: dict[str, object]) -> str:
    parts: list[str] = []
    directory_count = statistics.get("total_directories")
    todo_count = statistics.get("total_todos")
    if directory_count not in (None, "", "N/A"):
        parts.append(f"目录 {directory_count}")
    if todo_count not in (None, "", "N/A"):
        parts.append(f"TODO {todo_count}")
    return " · ".join(parts) if parts else "暂无补充样本信息"


def _hero_risk_ranking(code_entropy_items: list[tuple[str, dict[str, object]]], entropy_weights: dict[str, object] | None = None) -> str:
    ranked = sorted(
        [
            (key, item, float(item.get("score")))
            for key, item in code_entropy_items
            if isinstance(item.get("score"), (int, float))
        ],
        key=lambda pair: pair[2],
        reverse=True,
    )
    if not ranked:
        return ""
    rows = []
    for index, (key, item, score) in enumerate(ranked, start=1):
        tone = _entropy_level(score, item)
        label = CODE_ENTROPY_LABELS.get(key, key)
        scope = CODE_ENTROPY_SCOPES.get(key, "查看详情确认治理对象")
        status = _entropy_visual_label(score, item)
        direction = _entropy_direction_note(score, item)
        weight = entropy_weights.get(key) if isinstance(entropy_weights, dict) else None
        weight_text = (
            f'<span class="risk-rank-weight-inline">（权重{_esc(_fmt_percent_from_ratio(weight, 0))}）</span>'
            if isinstance(weight, (int, float))
            else ""
        )
        rows.append(
            f'''<a class="risk-rank-row risk-rank-row-{_esc(tone)}" href="#entropy-card-{_esc(key)}">
                <span class="risk-rank-index">{index}</span>
                <span class="risk-rank-main">
                    <span class="risk-rank-title-line">
                        <strong class="risk-rank-title">{_esc(label)}{weight_text}</strong>
                        <em class="risk-rank-status risk-rank-status-{_esc(tone)}">{_esc(status)}</em>
                    </span>
                    <span class="risk-rank-scope">{_esc(scope)} · {_esc(direction)}</span>
                </span>
                <span class="risk-rank-score">
                    <strong>{_esc(_fmt_compact(score))}</strong><span>/100</span>
                </span>
            </a>'''
        )
    return f'''<article class="hero-ranking">
        <div class="hero-ranking-head">
            <div>
                <div class="hero-story-label">风险排序</div>
                <p>按当前扫描分数从高到低排列，先处理高分项，再回到低风险项做持续收敛。</p>
            </div>
            <span class="hero-ranking-count">{len(ranked)} 类</span>
        </div>
        <div class="risk-rank-list">{''.join(rows)}</div>
    </article>'''


def _hero_score_insights(
    code_entropy_items: list[tuple[str, dict[str, object]]],
    entropy_weights: dict[str, object],
    summary: dict[str, object],
    code_entropy: dict[str, object],
) -> str:
    ranked = sorted(
        [
            (key, item, float(item.get("score")))
            for key, item in code_entropy_items
            if isinstance(item.get("score"), (int, float))
        ],
        key=lambda pair: pair[2],
        reverse=True,
    )
    if not ranked:
        return ""
    contributions: list[tuple[str, float, float, float]] = []
    for key, item, score in ranked:
        weight = entropy_weights.get(key) if isinstance(entropy_weights, dict) else None
        if isinstance(weight, (int, float)) and weight > 0:
            contributions.append((key, score, float(weight), score * float(weight)))
    contributions.sort(key=lambda row: row[3], reverse=True)
    max_contribution = max([row[3] for row in contributions] or [1.0])
    contribution_rows = "".join(
        f'''<div class="score-contribution-row">
            <span>{_esc(CODE_ENTROPY_LABELS.get(key, key))}</span>
            <b title="权重 {_esc(_fmt_percent_from_ratio(weight, 0))}"><i style="--w:{max(4.0, min(100.0, contribution / max_contribution * 100.0)):.1f}%"></i></b>
            <strong>{_esc(_fmt_compact(contribution))}</strong>
        </div>'''
        for key, _score, weight, contribution in contributions
    )

    def details_of(name: str) -> dict[str, object]:
        item = code_entropy.get(name) if isinstance(code_entropy.get(name), dict) else {}
        details = item.get("details") if isinstance(item, dict) else {}
        return details if isinstance(details, dict) else {}

    semantic = details_of("semantic")
    behavior = details_of("behavior")
    cognition = details_of("cognition")
    style = details_of("style")

    term_gap = semantic.get("undefined_terms")
    term_total = semantic.get("term_gap_candidate_count")
    swallowed = behavior.get("swallowed_catch_count")
    catch_total = behavior.get("catch_block_count")
    knowledge_gap = cognition.get("knowledge_missing_count")
    style_issues = style.get("style_total_violation_count")
    evidence_cards = [
        ("术语缺口", f"{_fmt_number(term_gap, 0)} / {_fmt_number(term_total, 0)}", "高频候选术语未进 glossary"),
        ("吞异常", f"{_fmt_number(swallowed, 0)} / {_fmt_number(catch_total, 0)}", "catch 后缺少失败信号"),
        ("公共知识缺口", _fmt_number(knowledge_gap, 0), "公共类/方法缺少说明"),
        ("Checkstyle 问题", _fmt_number(style_issues, 0), "格式、命名、导入与声明问题"),
    ]
    evidence_html = "".join(
        f'''<div class="score-evidence-card">
            <span>{_esc(label)}</span>
            <strong>{_esc(value)}</strong>
            <small>{_esc(note)}</small>
        </div>'''
        for label, value, note in evidence_cards
    )
    return f'''<div class="score-insights">
        <div class="score-contribution-panel">
            <div class="score-panel-head">
                <span>总分贡献</span>
                <strong>按权重折算</strong>
            </div>
            <div class="score-contribution-list">{contribution_rows}</div>
        </div>
        <div class="score-evidence-grid">{evidence_html}</div>
    </div>'''


def _hero_score_coverage_compact(
    code_entropy_items: list[tuple[str, dict[str, object]]],
    summary: dict[str, object],
    code_entropy: dict[str, object],
) -> str:
    structure = code_entropy.get("structure", {}) if isinstance(code_entropy.get("structure"), dict) else {}
    structure_details = structure.get("details", {}) if isinstance(structure.get("details"), dict) else {}
    style = code_entropy.get("style", {}) if isinstance(code_entropy.get("style"), dict) else {}
    style_details = style.get("details", {}) if isinstance(style.get("details"), dict) else {}
    statistics = dict(summary.get("statistics", {})) if isinstance(summary.get("statistics"), dict) else {}
    total_files = statistics.get("total_files")
    total_dirs = statistics.get("total_directories") or structure_details.get("total_directories")
    java_lines = style_details.get("java_line_count")
    rule_count = 0
    completed_count = 0
    for _key, item in code_entropy_items:
        breakdown = item.get("score_breakdown")
        if isinstance(breakdown, dict):
            rule_count += int(breakdown.get("rule_count", 0) or 0)
        if isinstance(item.get("score"), (int, float)):
            completed_count += 1
    dimension_count = len(code_entropy_items)
    coverage = 0.0 if dimension_count <= 0 else completed_count / dimension_count
    return f'''<div class="score-confidence-line score-confidence-line-compact">
        <div class="score-confidence-head">
            <strong>计分覆盖</strong>
            <span>覆盖率 {_esc(_fmt_percent_from_ratio(coverage, 0))}</span>
        </div>
        <div class="score-confidence-counts">
            <div class="score-confidence-count"><b>{_esc(_fmt_number(dimension_count, 0))}</b><span>类熵</span></div>
            <div class="score-confidence-count"><b>{_esc(_fmt_number(rule_count, 0))}</b><span>条规则</span></div>
            <div class="score-confidence-count"><b>{_esc(_fmt_number(completed_count, 0))}/{_esc(_fmt_number(dimension_count, 0))}</b><span>已计分</span></div>
        </div>
        <div class="score-confidence-files">
            <span>扫描范围</span>
            <div class="score-confidence-file-row">
                <b>{_esc(_fmt_number(total_files, 0))}<small>Java 文件</small></b>
                <b>{_esc(_fmt_number(java_lines, 0))}<small>代码行</small></b>
                <b>{_esc(_fmt_number(total_dirs, 0))}<small>目录</small></b>
            </div>
        </div>
    </div>'''


def _render_overview_card(
    title: str,
    value: str,
    meta: str,
    icon_name: str,
    tone: str,
    action_html: str = "",
    *,
    value_class: str = "",
    meta_class: str = "",
) -> str:
    actions = f'<div class="overview-actions">{action_html}</div>' if action_html else ""
    value_classes = " ".join(part for part in ["overview-value", value_class] if part)
    meta_classes = " ".join(part for part in ["overview-meta", meta_class] if part)
    return f'''<article class="overview-card overview-card-{_esc(tone)}">
        <div class="overview-card-head">
            <span class="icon-badge icon-badge-{_esc(tone)}">{_svg_icon(icon_name)}</span>
            <div class="overview-label">{_esc(title)}</div>
        </div>
        <div class="{_esc(value_classes)}">{_esc(value)}</div>
        <div class="{_esc(meta_classes)}">{_esc(meta)}</div>
        {actions}
    </article>'''


def _entropy_export_payload(key: str, item: dict[str, object]) -> dict[str, object]:
    return {
        "name": key,
        "label": CODE_ENTROPY_LABELS.get(key, key),
        "score_direction": "entropy_low_is_better",
        "score": item.get("score"),
        "level": item.get("level"),
        "score_status": item.get("score_status"),
        "coverage": item.get("coverage"),
        "missing_rule_ids": item.get("missing_rule_ids"),
        "partial_reason": item.get("partial_reason"),
        "facts": item.get("facts") if isinstance(item.get("facts"), dict) else {},
        "metrics": item.get("metrics") if isinstance(item.get("metrics"), dict) else {},
        "score_breakdown": item.get("score_breakdown") if isinstance(item.get("score_breakdown"), dict) else {},
        "scoring_v1": item.get("scoring_v1") if isinstance(item.get("scoring_v1"), dict) else {},
        "metric_definitions": item.get("metric_definitions") if isinstance(item.get("metric_definitions"), dict) else {},
        "standards": CODE_ENTROPY_STANDARDS.get(key, []),
        "details": item.get("details") if isinstance(item.get("details"), dict) else {},
    }


def _entropy_export_link(key: str, item: dict[str, object], label: str = "导出 JSON") -> str:
    filename = f"{key}-entropy-details.json"
    return f'<a class="action-link" href="{_esc(_json_data_url(_entropy_export_payload(key, item)))}" download="{_esc(filename)}">{_esc(label)}</a>'


def _collect_detail_rows(details: dict[str, object], limit: int = 6) -> list[tuple[str, object]]:
    rows: list[tuple[str, object]] = []
    for name, value in details.items():
        if isinstance(value, (dict, list)):
            continue
        rows.append((name, value))
        if len(rows) >= limit:
            break
    return rows


def _render_entropy_summary_strip(code_entropy_items: list[tuple[str, dict[str, object]]], statistics: dict[str, object]) -> str:
    scored_items = sorted(
        [
            (key, item, float(item.get("score")))
            for key, item in code_entropy_items
            if isinstance(item.get("score"), (int, float))
        ],
        key=lambda pair: pair[2],
        reverse=True,
    )
    if not scored_items:
        return ""

    highest_key, highest_item, highest_score = scored_items[0]
    secondary_key, secondary_item, secondary_score = scored_items[1] if len(scored_items) > 1 else scored_items[0]
    healthiest_key, healthiest_item, healthiest_score = scored_items[-1]
    partial_items = [
        (key, item)
        for key, item in code_entropy_items
        if str(item.get("score_status", "complete")).strip().lower() == "partial"
    ]

    cards = [
        (
            "最高压力",
            f"{CODE_ENTROPY_LABELS.get(highest_key, highest_key)} {_fmt_compact(highest_score)}/100",
            _entropy_direction_note(highest_score, highest_item),
            _entropy_level(highest_score, highest_item),
        ),
        (
            "次级压力",
            f"{CODE_ENTROPY_LABELS.get(secondary_key, secondary_key)} {_fmt_compact(secondary_score)}/100",
            CODE_ENTROPY_SCOPES.get(secondary_key, ""),
            _entropy_level(secondary_score, secondary_item),
        ),
        (
            "相对稳定",
            f"{CODE_ENTROPY_LABELS.get(healthiest_key, healthiest_key)} {_fmt_compact(healthiest_score)}/100",
            "当前可作为对照项持续观察",
            _entropy_level(healthiest_score, healthiest_item),
        ),
        (
            "扫描样本",
            f"{statistics.get('total_files', 'N/A')} 文件",
            f"目录 {statistics.get('total_directories', 'N/A')} · TODO {statistics.get('total_todos', 'N/A')}",
            "brand",
        ),
    ]
    if partial_items:
        key, item = partial_items[0]
        cards.append(
            (
                "口径状态",
                f"{CODE_ENTROPY_LABELS.get(key, key)} 部分计分",
                _entropy_partial_note(item),
                "warning",
            )
        )
    cards_html = "".join(
        f'''<article class="entropy-summary-card entropy-summary-card-{_esc(tone)}">
            <div class="entropy-summary-kicker">{_esc(title)}</div>
            <div class="entropy-summary-value">{_esc(value)}</div>
            <div class="entropy-summary-note">{_esc(note)}</div>
        </article>'''
        for title, value, note, tone in cards
    )
    return f'<div class="entropy-summary-grid">{cards_html}</div>'



def _render_entropy_card(key: str, item: dict[str, object]) -> str:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    score = item.get("score") if isinstance(item.get("score"), (int, float)) else None
    status = _entropy_level(score, item)
    status_label = _entropy_visual_label(score, item)
    progress = 0 if score is None else max(0.0, min(100.0, float(score)))
    highlights = _render_entropy_card_highlights(key, item, details)
    partial_note = _entropy_partial_note(item)
    return f'''<article id="entropy-card-{_esc(key)}" class="metric-card metric-card-{status}" style="--metric-progress:{progress:.0f}%;">
        <div class="metric-card-top">
            <div class="metric-heading">
                <span class="icon-badge icon-badge-{status}">{_svg_icon(key)}</span>
                <div class="metric-head-copy">
                    <div class="metric-status metric-status-{status}">{_esc(status_label)}</div>
                    <div class="metric-name-row">
                        <div class="metric-name">{_esc(CODE_ENTROPY_LABELS.get(key, key))}</div>
                    </div>
                    <div class="metric-caption">{_esc(CODE_ENTROPY_SCOPES.get(key, ""))}</div>
                </div>
            </div>
        </div>
        <div class="metric-score-row">
            <div class="metric-score-main">
                <div class="metric-value metric-{status}">{_esc(_fmt_compact(score))}<span class="metric-unit">/100</span></div>
                <div class="metric-score-note">{_esc(_entropy_direction_note(score, item))}</div>
            </div>
            <div class="metric-meter" aria-hidden="true"><span></span></div>
        </div>
        <p class="metric-summary">{_esc(_entropy_guidance(key, score, item))}</p>
        {f'<div class="metric-scope-note">{_esc(partial_note)}</div>' if partial_note else ''}
        <div class="metric-facts">{highlights}</div>
        <div class="metric-actions">
            <button class="action-link action-primary metric-action-primary" type="button" data-entropy-key="{_esc(key)}" onclick="openEntropyDrawer('{_esc(key)}', this)">快速预览</button>
            <a class="action-link" href="code-entropy-details/{_esc(key)}.html" target="_blank" rel="noopener">完整详情</a>
            <a class="action-link" href="code-entropy-details/{_esc(key)}.json" download>导出 JSON</a>
        </div>
    </article>'''


def _render_entropy_card_highlights(key: str, item: dict[str, object], details: dict[str, object]) -> str:
    rule_cards = _dashboard_rule_cards(key, item)
    if rule_cards:
        return "".join(
            f'''<div class="metric-fact metric-fact-rule">
                <div class="metric-fact-label" title="{_esc(card["label"])}">{_esc(card["label"])}</div>
                <div class="metric-fact-value">{_esc(card["value"])}</div>
                {f'<div class="metric-fact-note">{_esc(card["note"])}</div>' if card["note"] else ""}
            </div>'''
            for card in rule_cards
        )

    cards = [
        f'''<div class="metric-fact">
            <div class="metric-fact-label" title="{_esc(_short_detail_label(name, details))}">{_esc(_short_detail_label(name, details))}</div>
            <div class="metric-fact-value" title="{_esc(value)}">{_esc(_display_value(name, value, short_path=True))}</div>
        </div>'''
        for name, value in _metric_highlight_pairs(key, details)
    ]
    return "".join(cards) or '<div class="metric-fact"><div class="metric-fact-label">暂无</div><div class="metric-fact-value">-</div></div>'



def _render_cycle_rows(groups: object) -> str:
    if not isinstance(groups, list) or not groups:
        return "<tr><td colspan=\"4\">未发现循环依赖组</td></tr>"

    rows: list[str] = []
    for group in groups[:20]:
        if not isinstance(group, dict):
            continue
        classes = group.get("classes", [])
        sample_edges = group.get("sample_edges", [])
        class_items = []
        if isinstance(classes, list):
            for item in classes[:8]:
                if not isinstance(item, dict):
                    continue
                class_items.append(
                    f'<div class="cycle-class"><strong title="{_esc(item.get("name", "unknown"))}">{_esc(item.get("name", "unknown"))}</strong><span title="{_esc(item.get("file", "Unknown"))}">{_esc(_short_path(item.get("file", "Unknown"), 5))}</span></div>'
                )
        edge_items = []
        if isinstance(sample_edges, list):
            for edge in sample_edges[:8]:
                if not isinstance(edge, dict):
                    continue
                edge_items.append(f'<div class="cycle-edge" title="{_esc(edge.get("from", "?"))} → {_esc(edge.get("to", "?"))}">{_esc(_short_path(edge.get("from", "?"), 3))} → {_esc(_short_path(edge.get("to", "?"), 3))}</div>')
        rows.append(
            f'''<tr>
                <td>{_esc(group.get("id", "-"))}</td>
                <td>{_esc(group.get("size", "-"))}</td>
                <td>{''.join(class_items) or '-'}</td>
                <td>{''.join(edge_items) or '-'}</td>
            </tr>'''
        )
    return "".join(rows) or "<tr><td colspan=\"4\">未发现循环依赖组</td></tr>"


def _render_scalar_detail_rows(details: dict[str, object]) -> str:
    rows: list[str] = []
    for name, value in details.items():
        if isinstance(value, (dict, list)):
            continue
        rows.append(
            f'''<tr>
                <td>{_esc(_detail_label(name, details))}</td>
                <td class="raw-key">{_esc(name)}</td>
                <td title="{_esc(value)}">{_esc(_display_value(name, value))}</td>
            </tr>'''
        )
    return "".join(rows) or '<tr><td colspan="3">暂无基础明细</td></tr>'


def _render_nested_table(name: str, value: object, details: dict[str, object] | None = None) -> str:
    label = _detail_label(name, details)
    table_total_counts = details.get("table_total_counts", {}) if isinstance(details, dict) and isinstance(details.get("table_total_counts"), dict) else {}
    total_count = int(table_total_counts.get(name, 0) or 0)
    preferred_columns = {
        "semantic_rule_overview": ["rule", "status", "current_value", "count_summary", "problem_count", "problem_unit", "summary", "focus"],
        "naming_conflict_issues": ["term", "standard", "variant_count", "nonstandard_hits", "matched_hits", "nonstandard_ratio"],
        "naming_conflict_locations": ["term", "variant", "class_name", "file", "line"],
        "undefined_term_issues": ["term", "count", "sample_locations"],
        "state_duplicate_cluster_issues": ["cluster_id", "carrier_count", "redundant_count", "shared_items", "carrier_names"],
        "state_scattered_value_issues": ["value", "confidence", "occurrence_count", "scored_occurrence_count", "candidate_occurrence_count", "file_count", "sample_locations"],
    }.get(name, [])
    if isinstance(value, dict):
        rows = "".join(
            f'<tr><td>{_esc(_detail_label(k, details))}</td><td>{_esc(_display_value(k, v))}</td></tr>'
            for k, v in value.items()
            if not isinstance(v, (dict, list))
        )
        if not rows:
            rows = '<tr><td colspan="2">该字段为复杂对象，请查看原始 JSON</td></tr>'
        return f'''<div class="nested-detail">
            <h4>{_esc(label)}</h4>
            <table><thead><tr><th>项目</th><th>值</th></tr></thead><tbody>{rows}</tbody></table>
        </div>'''

    if isinstance(value, list):
        if not value:
            return f'<div class="nested-detail"><h4>{_esc(label)}</h4><div class="empty-detail">暂无数据</div></div>'
        if all(isinstance(item, dict) for item in value[:10]):
            columns: list[str] = []
            for column in preferred_columns:
                if any(isinstance(item, dict) and column in item and not isinstance(item.get(column), (dict, list)) for item in value[:10]):
                    columns.append(column)
            if name == "naming_conflict_locations" and columns:
                header = "".join(f"<th>{_esc(_detail_label(column, details))}</th>" for column in columns)
                body_rows: list[str] = []
                for item in value[:10]:
                    if not isinstance(item, dict):
                        continue
                    cells = "".join(
                        f'<td title="{_esc(item.get(column, ""))}">{_esc(_display_value(column, item.get(column, ""), short_path=True))}</td>'
                        for column in columns
                    )
                    body_rows.append(f"<tr>{cells}</tr>")
                display_count = len(value)
                effective_total = total_count if total_count > 0 else display_count
                more = ""
                if effective_total > display_count or display_count > 10:
                    more = f'<div class="detail-more">当前展示 {display_count} 项 / 总数 {effective_total} 项；完整内容可导出 JSON。</div>'
                return f'''<div class="nested-detail">
                    <h4>{_esc(label)}</h4>
                    <table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>
                    {more}
                </div>'''
            for item in value[:10]:
                if not isinstance(item, dict):
                    continue
                for column, column_value in item.items():
                    if isinstance(column_value, (dict, list)):
                        continue
                    if column not in columns:
                        columns.append(column)
                    max_columns = 6 if name == "semantic_rule_overview" else 4
                    if len(columns) >= max_columns:
                        break
                if len(columns) >= max_columns:
                    break
            if not columns:
                return f'''<div class="nested-detail">
                    <h4>{_esc(label)}</h4>
                    <details><summary>查看 {len(value)} 项复杂明细</summary><pre>{_json_pretty(value[:20])}</pre></details>
                </div>'''
            header = "".join(f"<th>{_esc(_detail_label(column, details))}</th>" for column in columns)
            body_rows: list[str] = []
            for item in value[:10]:
                if not isinstance(item, dict):
                    continue
                cells = "".join(
                    f'<td title="{_esc(item.get(column, ""))}">{_esc(_display_value(column, item.get(column, ""), short_path=True))}</td>'
                    for column in columns
                )
                body_rows.append(f"<tr>{cells}</tr>")
            display_count = len(value)
            effective_total = total_count if total_count > 0 else display_count
            more = ""
            if effective_total > display_count or display_count > 10:
                more = f'<div class="detail-more">当前展示 {display_count} 项 / 总数 {effective_total} 项；完整内容可导出 JSON。</div>'
            return f'''<div class="nested-detail">
                <h4>{_esc(label)}</h4>
                <table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>
                {more}
            </div>'''
        items = "".join(f"<li>{_esc(_display_value(name, item, short_path=True))}</li>" for item in value[:20])
        display_count = len(value)
        effective_total = total_count if total_count > 0 else display_count
        more = ""
        if effective_total > display_count or display_count > 20:
            more = f'<div class="detail-more">当前展示 {display_count} 项 / 总数 {effective_total} 项；完整内容可导出 JSON。</div>'
        return f'''<div class="nested-detail">
            <h4>{_esc(label)}</h4>
            <ul class="compact-list">{items}</ul>
            {more}
        </div>'''

    return ""


def _render_entropy_detail_panel(key: str, item: dict[str, object]) -> str:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    score = item.get("score") if isinstance(item.get("score"), (int, float)) else None
    standards = "".join(f"<li>{_esc(line)}</li>" for line in CODE_ENTROPY_STANDARDS.get(key, []))
    nested_sections = "".join(
        _render_nested_table(name, value, details)
        for name, value in details.items()
        if isinstance(value, (dict, list))
    )
    return f'''<article id="detail-{_esc(key)}" class="entropy-detail-panel">
        <div class="detail-panel-head">
            <div>
                <div class="detail-kicker">{_svg_icon(key)} {CODE_ENTROPY_LABELS.get(key, key)}</div>
                <h3>{_esc(CODE_ENTROPY_LABELS.get(key, key))}完整明细</h3>
                <p>风险熵分 {_esc(_fmt_compact(score))}/100，{_esc(_level_label(item.get("level", "unknown")))}。本项口径：分数越高代表风险越大，40 / 60 / 80 为区间阈值。</p>
            </div>
            <div class="detail-actions">
                {_entropy_export_link(key, item)}
                <a class="action-link" href="#code-entropy">返回卡片</a>
            </div>
        </div>
        <div class="detail-layout">
            <section class="detail-box">
                <h4>评分标准</h4>
                <ul class="standard-list">{standards}</ul>
            </section>
            <section class="detail-box">
                <h4>基础指标</h4>
                <table><thead><tr><th>中文指标</th><th>原始字段</th><th>当前值</th></tr></thead><tbody>{_render_scalar_detail_rows(details)}</tbody></table>
            </section>
        </div>
        {nested_sections}
        <details class="raw-detail detail-raw">
            <summary>查看原始 JSON</summary>
            <pre>{_json_pretty(_entropy_export_payload(key, item))}</pre>
        </details>
    </article>'''


def _preview_field_names(key: str, details: dict[str, object]) -> list[str]:
    preferred = {
        "structure": ["top_large_dirs", "oversized_dirs", "top_n_concentration_dirs"],
        "semantic": ["semantic_rule_overview", "naming_conflict_issues", "undefined_term_issues", "state_duplicate_cluster_issues", "state_scattered_value_issues"],
        "behavior": ["top_error_patterns", "top_return_formats", "top_exceptions"],
        "cognition": ["top_todos"],
        "style": ["style_rule_overview", "checkstyle_module_distribution"],
    }.get(key, [])
    return [name for name in preferred if name in details and isinstance(details.get(name), (dict, list))]


def _render_entropy_preview_template(key: str, item: dict[str, object]) -> str:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    score = item.get("score") if isinstance(item.get("score"), (int, float)) else None
    status_label = _entropy_visual_label(score, item)
    partial_note = _entropy_partial_note(item)
    standards = "".join(f"<li>{_esc(line)}</li>" for line in CODE_ENTROPY_STANDARDS.get(key, []))
    score_explainer = _render_entropy_score_explainer(key, item, compact=True)
    return f'''<template id="drawer-template-{_esc(key)}">
        <div class="drawer-kicker">{_svg_icon(key)} {CODE_ENTROPY_LABELS.get(key, key)}</div>
        <h2>{_esc(CODE_ENTROPY_LABELS.get(key, key))}评分说明</h2>
        <p class="drawer-summary">风险熵分 {_esc(_fmt_compact(score))}/100，{_esc(status_label)}。{_esc(_entropy_guidance(key, score, item))}</p>
        {f'<p class="drawer-summary">{_esc(partial_note)}</p>' if partial_note else ''}
        <div class="drawer-actions">
            <a class="action-link action-primary" href="code-entropy-details/{_esc(key)}.html" target="_blank" rel="noopener">打开完整详情</a>
            <a class="action-link" href="code-entropy-details/{_esc(key)}.json" download>导出 JSON</a>
        </div>
        <section class="drawer-section">
            <h3>评分标准</h3>
            <ul class="standard-list">{standards}</ul>
        </section>
        <section class="drawer-section">
            <h3>这次分数怎么算</h3>
            {score_explainer}
        </section>
    </template>'''


def _render_entropy_drawer_templates(code_entropy: object) -> str:
    if not isinstance(code_entropy, dict):
        return ""
    return "".join(
        _render_entropy_preview_template(key, item)
        for key in ["structure", "semantic", "behavior", "cognition", "style"]
        if isinstance((item := code_entropy.get(key)), dict)
    )


def _render_entropy_drawer() -> str:
    return '''<div id="drawer-backdrop" class="drawer-backdrop" onclick="closeEntropyDrawer()" hidden></div>
    <aside id="entropy-drawer" class="entropy-drawer" aria-hidden="true" aria-label="代码本体熵评分说明" aria-modal="true" role="dialog" aria-labelledby="drawer-title" tabindex="-1">
        <div class="drawer-top">
            <div id="drawer-title" class="drawer-title">评分说明</div>
            <button class="drawer-close" type="button" onclick="closeEntropyDrawer()" aria-label="关闭">×</button>
        </div>
        <div id="drawer-content" class="drawer-content"></div>
    </aside>
    <script>
        var lastDrawerTrigger = null;
        function openEntropyDrawer(key, trigger) {
            var template = document.getElementById('drawer-template-' + key);
            var drawer = document.getElementById('entropy-drawer');
            var content = document.getElementById('drawer-content');
            var backdrop = document.getElementById('drawer-backdrop');
            if (!template || !drawer || !content || !backdrop) return;
            lastDrawerTrigger = trigger || document.activeElement;
            content.innerHTML = template.innerHTML;
            backdrop.hidden = false;
            drawer.classList.add('open');
            drawer.setAttribute('aria-hidden', 'false');
            document.body.classList.add('drawer-open');
            drawer.focus();
        }
        function closeEntropyDrawer() {
            var drawer = document.getElementById('entropy-drawer');
            var backdrop = document.getElementById('drawer-backdrop');
            if (!drawer || !backdrop) return;
            drawer.classList.remove('open');
            drawer.setAttribute('aria-hidden', 'true');
            backdrop.hidden = true;
            document.body.classList.remove('drawer-open');
            if (lastDrawerTrigger && typeof lastDrawerTrigger.focus === 'function') {
                lastDrawerTrigger.focus();
            }
        }
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') closeEntropyDrawer();
        });
    </script>'''



def _json_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _normalize_detail_row(value: object, field_name: str = "value") -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        return {field_name: value}
    return {"value": value}


def _columns_for_rows(rows: list[dict[str, object]], preferred: list[str] | None = None) -> list[str]:
    columns: list[str] = []
    for column in preferred or []:
        if any(column in row for row in rows):
            columns.append(column)
    for row in rows[:50]:
        for column in row.keys():
            if column not in columns:
                columns.append(column)
            if len(columns) >= 8:
                break
        if len(columns) >= 8:
            break
    return columns or ["value"]


def _make_table(
    table_id: str,
    label: str,
    rows: object,
    preferred: list[str] | None = None,
    *,
    total_count: int | None = None,
    strict_preferred: bool = False,
) -> dict[str, object] | None:
    if not isinstance(rows, list) or not rows:
        return None
    field_name = "path" if all(isinstance(item, str) for item in rows[:10]) else "value"
    normalized = [_normalize_detail_row(row, field_name) for row in rows]
    columns = (
        [column for column in (preferred or []) if any(column in row for row in normalized)]
        if strict_preferred
        else _columns_for_rows(normalized, preferred)
    )
    return {
        "id": table_id,
        "label": _detail_table_label(table_id, label),
        "description": _detail_table_description(table_id, label),
        "count": int(total_count) if isinstance(total_count, int) and total_count > 0 else len(normalized),
        "display_count": len(normalized),
        "total_count": int(total_count) if isinstance(total_count, int) and total_count > 0 else len(normalized),
        "columns": columns or ["value"],
        "rows": normalized,
    }


def _first_row(rows: object) -> list[dict[str, object]]:
    if not isinstance(rows, list):
        return []
    for row in rows:
        if isinstance(row, dict):
            return [dict(row)]
    return []


def _semantic_metric_context(name: str) -> tuple[str, str]:
    if name in SEMANTIC_METRIC_EXPLANATIONS:
        return SEMANTIC_METRIC_EXPLANATIONS[name]
    if name.startswith("naming_"):
        return ("命名非标准占比", "命名规则使用的底层统计字段，用于排查命名非标准占比的计算来源。")
    if name.startswith("term_gap_") or name in {"term_coverage", "undefined_terms", "defined_terms"}:
        return ("术语缺口", "术语缺口规则使用的底层统计字段，用于排查候选术语、词典覆盖和缺口比例。")
    if name.startswith("state_scattered_") or name.startswith("state_value_") or name.startswith("state_scatter_"):
        return ("状态值散落", "状态值散落规则使用的底层统计字段，用于排查硬编码状态值的计分和疑似范围。")
    if name.startswith("state_") or name == "duplicate_states":
        return ("状态承载体重复比", "状态承载体重复规则使用的底层统计字段，用于排查重复承载体和状态项重叠。")
    if name.startswith("glossary_"):
        return ("词典配置", "glossary 读取和启用状态，用于排查语义规则依赖的术语配置来源。")
    return ("其他指标", "语义熵评分引擎输出的辅助字段，主要用于排查分值来源。")


def _structure_metric_context(name: str) -> tuple[str, str]:
    if name in STRUCTURE_METRIC_EXPLANATIONS:
        return STRUCTURE_METRIC_EXPLANATIONS[name]
    if name.startswith("shared_") or name in {"common_files", "util_files"}:
        return ("共享承载目录占比", "共享承载目录占比规则使用的底层统计字段，用于排查 common/shared/util/utils 承载范围。")
    if name.startswith("max_dir_"):
        return ("最大目录文件占比", "最大目录文件占比规则使用的底层统计字段，用于排查单个目录是否过度膨胀。")
    if name.startswith("oversized_"):
        return ("超大目录数量占比", "超大目录数量占比规则使用的底层统计字段，用于排查大目录问题扩散面。")
    if name.startswith("top_n_"):
        return ("前 N 大目录集中度", "前 N 大目录集中度规则使用的底层统计字段，用于排查文件是否集中在少数头部目录。")
    if name == "avg_files_per_dir":
        return ("平均目录文件数", "平均目录文件数规则使用的全局统计结果，用于辅助判断目录粒度是否整体变粗。")
    return ("其他指标", "结构熵评分引擎输出的辅助字段，主要用于排查分值来源。")


def _behavior_metric_context(name: str) -> tuple[str, str]:
    if name in BEHAVIOR_METRIC_EXPLANATIONS:
        return BEHAVIOR_METRIC_EXPLANATIONS[name]
    if name.startswith("failure_strategy_"):
        return ("失败处理策略分裂", "失败处理策略分裂规则使用的底层统计字段，用于排查 catch 块归类和主导策略占比。")
    if name.startswith("swallowed_") or name == "catch_block_count":
        return ("吞异常比例", "吞异常规则使用的底层统计字段，用于排查 catch 块是否只有日志或空处理。")
    if name.startswith("error_return_contract_"):
        return ("返回错误契约混用", "返回错误契约混用规则使用的底层统计字段，用于排查 Controller/API 失败契约分布。")
    if name.startswith("generic_exception_") or name == "exception_throw_count":
        return ("泛化异常滥用", "泛化异常规则使用的底层统计字段，用于排查异常语义是否被 RuntimeException/Exception/Throwable 稀释。")
    if name.startswith("business_exception_") or name.startswith("standard_business_") or name.startswith("nonstandard_business_"):
        return ("业务异常未收敛", "业务异常未收敛规则使用的底层统计字段，用于排查业务异常是否收敛到统一基类。")
    return ("其他指标", "行为熵评分引擎输出的辅助字段，主要用于排查分值来源。")


def _cognition_metric_context(name: str) -> tuple[str, str]:
    if name in COGNITION_METRIC_EXPLANATIONS:
        return COGNITION_METRIC_EXPLANATIONS[name]
    if name.startswith("todo_") or name.startswith("debt_"):
        return ("债务标记密度", "认知熵债务规则使用的底层统计字段，用于排查 TODO/FIXME/HACK 的数量和分布。")
    if name.startswith("unowned_") or "owner" in name:
        return ("未归属债务比例", "未归属债务规则使用的底层统计字段，用于排查技术债是否有责任人。")
    if name.startswith("knowledge_") or name.startswith("javadoc_"):
        return ("公共知识缺口比例", "公共知识缺口规则使用的底层统计字段，用于排查公共类和公共方法的文档缺口。")
    if name.startswith("complex_") or name in {"total_methods", "large_method_threshold"}:
        return ("复杂方法比例", "复杂方法规则使用的底层统计字段，用于排查方法体长度、分支数和嵌套深度。")
    if name.startswith("large_file") or name.startswith("large_class"):
        return ("大文件/大类负担比例", "大文件/大类规则使用的底层统计字段，用于排查阅读入口是否过重。")
    if name.startswith("project_doc"):
        return ("项目文档缺口比例", "项目文档规则使用的底层统计字段，用于排查 README 和 docs/readme/wiki 是否足够支撑新人理解项目。")
    return ("辅助指标", "认知熵评分引擎输出的辅助字段，主要用于排查分值来源。")


def _style_metric_context(name: str) -> tuple[str, str]:
    if name in STYLE_METRIC_EXPLANATIONS:
        return STYLE_METRIC_EXPLANATIONS[name]
    if name.startswith("style_formatting"):
        return ("格式排版问题", "格式排版规则使用的底层统计字段，用于排查缩进、空白、换行、括号等问题密度。")
    if name.startswith("style_naming"):
        return ("命名规范问题", "命名规范规则使用的底层统计字段，用于排查类名、方法名、包名等命名问题密度。")
    if name.startswith("style_import"):
        return ("导入规范问题", "导入规范规则使用的底层统计字段，用于排查星号导入、非法导入、冗余导入和未使用导入。")
    if name.startswith("style_declaration"):
        return ("注解与声明规范问题", "声明规范规则使用的底层统计字段，用于排查注解、Override、修饰符顺序和顶层类问题。")
    if name.startswith("style_code_smell"):
        return ("编码坏味道问题", "编码坏味道规则使用的底层统计字段，用于排查空 catch、直接打印、错误比较等问题。")
    if name.startswith("style_complexity"):
        return ("复杂度与规模问题", "复杂度规则使用的底层统计字段，用于排查文件过长、嵌套过深、参数过多等问题。")
    return ("Checkstyle 执行", "风格熵评分引擎输出的辅助字段，用于排查 Checkstyle 扫描和分类来源。")


def _base_metric_rows(details: dict[str, object], key: str | None = None) -> list[dict[str, object]]:
    rows = []
    for name, value in details.items():
        if isinstance(value, (dict, list)):
            continue
        if key == "behavior" and name not in BEHAVIOR_VISIBLE_METRIC_FIELDS:
            continue
        if key == "cognition" and name not in COGNITION_VISIBLE_METRIC_FIELDS:
            continue
        if key == "style" and name not in STYLE_VISIBLE_METRIC_FIELDS:
            continue
        row = {"label": _detail_label(name, details), "field": name, "value": _display_value(name, value)}
        if key == "semantic":
            rule, description = _semantic_metric_context(name)
            row = {"metric_group": rule, **row, "description": description}
        elif key == "structure":
            rule, description = _structure_metric_context(name)
            row = {"metric_group": rule, **row, "description": description}
        elif key == "behavior":
            rule, description = _behavior_metric_context(name)
            row = {"metric_group": rule, **row, "description": description}
        elif key == "cognition":
            rule, description = _cognition_metric_context(name)
            row = {"metric_group": rule, **row, "description": description}
        elif key == "style":
            rule, description = _style_metric_context(name)
            row = {"metric_group": rule, **row, "description": description}
        rows.append(row)
    if key == "semantic":
        rows.sort(key=lambda row: (SEMANTIC_METRIC_RULE_ORDER.get(str(row.get("metric_group", "")), 99), str(row.get("field", ""))))
    elif key == "structure":
        rows.sort(key=lambda row: (
            STRUCTURE_METRIC_RULE_ORDER.get(str(row.get("metric_group", "")), 99),
            STRUCTURE_METRIC_FIELD_ORDER.get(str(row.get("field", "")), 999),
            str(row.get("field", "")),
        ))
    elif key == "behavior":
        rows.sort(key=lambda row: (
            BEHAVIOR_METRIC_RULE_ORDER.get(str(row.get("metric_group", "")), 99),
            str(row.get("field", "")),
        ))
    elif key == "cognition":
        rows.sort(key=lambda row: (
            COGNITION_METRIC_RULE_ORDER.get(str(row.get("metric_group", "")), 99),
            str(row.get("field", "")),
        ))
    elif key == "style":
        rows.sort(key=lambda row: (
            STYLE_METRIC_RULE_ORDER.get(str(row.get("metric_group", "")), 99),
            str(row.get("field", "")),
        ))
    return rows


def _score_rule_description(metric_id: str, row: dict[str, object], item: dict[str, object]) -> str:
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    details = item.get("details") if isinstance(item.get("details"), dict) else {}

    def _top_distribution(items: object, key_name: str) -> tuple[str, object]:
        if isinstance(items, list) and items and isinstance(items[0], dict):
            first = items[0]
            return (_display_value(key_name, first.get(key_name)), first.get("count"))
        return ("未识别", None)

    dominant_strategy, dominant_strategy_count = _top_distribution(details.get("failure_strategy_distribution"), "strategy")
    dominant_contract, dominant_contract_count = _top_distribution(details.get("error_return_contract_distribution"), "contract")
    standard_business = _display_value("standard_business_exceptions", details.get("standard_business_exceptions"))
    behavior_notes = {
        "failure_strategy_split_ratio": (
            f"先把每个 catch 块归成一种失败处理策略，数量最多的是“{dominant_strategy}”"
            f"{_fmt_count_phrase(dominant_strategy_count)}。用 1 - 主导策略占比，表示还有多少 catch 没走主导策略，值越高说明失败处理越分裂。"
        ),
        "swallowed_exception_ratio": (
            "分子是空 catch、只打日志或没有 throw/return 失败处理的 catch 块，分母是全部 catch 块。"
            "这类代码会吞掉失败信号，比例越高越异常。"
        ),
        "error_return_contract_mix_ratio": (
            f"只看 Controller/API 层失败契约，数量最多的是“{dominant_contract}”"
            f"{_fmt_count_phrase(dominant_contract_count)}。用 1 - 主导契约占比，表示失败返回没有统一到一种契约的比例。"
        ),
        "generic_exception_throw_ratio": (
            "分子是 throw new RuntimeException/Exception/Throwable，分母是全部 throw new XxxException/Throwable。"
            "泛化异常缺少业务语义，占比越高越异常。"
        ),
        "business_exception_convergence_gap": (
            f"标准业务异常集合为“{standard_business}”。分子是未命中标准集合的业务异常抛出次数，"
            "分母是全部业务异常抛出次数；值越高说明业务异常越在局部自定义。"
        ),
    }
    cognition_notes = {
        "todo_density_per_k_files": (
            "分子是 TODO/FIXME/HACK 等债务标记总数，分母是 Java 文件总数，并折算为每千文件密度。"
            "它衡量的是债务在代码中的密集程度，不是单纯看绝对数量。"
        ),
        "unowned_debt_ratio": (
            "分子是没有责任人的债务标记数量，分母是全部债务标记数量。"
            "没有责任人的债务更容易长期滞留，所以比例越高越异常。"
        ),
        "public_knowledge_gap_ratio": (
            "分子是公共类和公共方法中缺少 JavaDoc 的目标数量，分母是当前公共知识扫描目标总数。"
            "它衡量公共知识是否沉淀在代码旁，而不是依赖熟人经验。"
        ),
        "complex_method_ratio": (
            "分子是方法体过长、分支过多或嵌套过深的方法数量，分母是识别到的方法总数。"
            "这类方法通常最难读、难改、难测。"
        ),
        "large_file_class_burden_ratio": (
            "分子是物理总行数超过大文件阈值的 Java 文件数量，分母是 Java 文件总数。"
            "当前 MVP 用文件物理总行数近似大文件/大类负担，避免把全局平均值伪装成代码定位问题。"
        ),
        "project_doc_gap_ratio": (
            "先把 README 和 docs/doc/readme/wiki 下的说明文档合并计算项目文档可用度，再用 1 - 可用度得到缺口比例。"
            "它衡量新人理解项目、启动项目和定位配置是否需要依赖口头经验。"
        ),
    }
    style_notes = {
        "style_formatting_density": "缩进、空白、换行、括号、空块等文本排版问题；命中越多，说明 formatter 或团队排版约定没有稳定落地。",
        "style_naming_density": "类名、方法名、包名、泛型参数、静态变量等命名规范问题；命中越多，说明代码命名预期不稳定。",
        "style_import_density": "星号导入、非法导入、冗余导入、未使用导入等引用清洁度问题；命中越多，说明 import 管理越混乱。",
        "style_declaration_density": "注解位置、Override、包注解、修饰符顺序、顶层类数量等声明规范问题；命中越多，说明声明结构越不统一。",
        "style_code_smell_density": "空 catch、直接打印、字符串比较、equals/hashCode、控制变量修改等可维护性坏味道；命中越多，说明代码维护风险越高。",
        "style_complexity_density": "文件过长、嵌套过深、布尔表达式复杂、参数过多等理解成本问题；命中越多，说明代码阅读和修改负担越重。",
    }
    description = behavior_notes.get(metric_id) or cognition_notes.get(metric_id) or style_notes.get(metric_id) or _clean_ui_text(row.get("rule_cn", ""))
    if not description:
        metric_definitions = item.get("metric_definitions") if isinstance(item.get("metric_definitions"), dict) else {}
        metric_definition = metric_definitions.get(metric_id) if isinstance(metric_definitions.get(metric_id), dict) else {}
        description = _clean_ui_text(metric_definition.get("meaning_cn", ""))
    condition = _clean_ui_text(row.get("condition", ""))
    if condition and condition not in {"default", "missing"}:
        return f"{description} 当前异常口径：{condition}。".strip()
    return description or "按当前规则阈值判断是否需要关注。"


def _score_rule_calculation_description(metric_id: str, item: dict[str, object]) -> str:
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    details = item.get("details") if isinstance(item.get("details"), dict) else {}

    java_kloc_note = (
        f"Java 千行代码 = Java 物理总行数 / 1000，当前 "
        f"{_fmt_number(facts.get('java_line_count'), 0)} / 1000 = {_fmt_number(facts.get('java_kloc'), 3)}。"
    )
    style_notes = {
        "style_formatting_density": f"分子是格式排版类 Checkstyle 问题数，分母是 Java 千行代码；{java_kloc_note}",
        "style_naming_density": f"分子是命名规范类 Checkstyle 问题数，分母是 Java 千行代码；{java_kloc_note}",
        "style_import_density": f"分子是导入规范类 Checkstyle 问题数，分母是 Java 千行代码；{java_kloc_note}",
        "style_declaration_density": f"分子是注解与声明规范类 Checkstyle 问题数，分母是 Java 千行代码；{java_kloc_note}",
        "style_code_smell_density": f"分子是编码坏味道类 Checkstyle 问题数，分母是 Java 千行代码；{java_kloc_note}",
        "style_complexity_density": f"分子是复杂度与规模类 Checkstyle 问题数，分母是 Java 千行代码；{java_kloc_note}",
    }
    if metric_id in style_notes:
        return style_notes[metric_id]

    calculation_notes = {
        "shared_bucket_ratio": "分子是命中 common/shared/util 等共享承载目录的 Java 文件数，分母是 Java 文件总数。",
        "max_dir_files_ratio": "分子是文件最多的单个目录中的 Java 文件数，分母是 Java 文件总数。",
        "oversized_dir_ratio": "分子是超过超大目录阈值的目录数，分母是目录总数。",
        "top_n_dir_concentration": "分子是前 N 个最大目录的 Java 文件总数，分母是 Java 文件总数。",
        "avg_files_per_dir": "分子是 Java 文件总数，分母是目录总数，结果表示平均每个目录承载多少 Java 文件。",
        "naming_inconsistency_ratio": "分子是术语命中里的非标准命名次数，分母是标准命名与非标准命名的总命中次数。",
        "term_gap_ratio": "分子是高频候选术语中未进入 glossary 的术语数，分母是本次参与计分的候选术语数。",
        "state_duplicate_ratio": "分子是被判定为冗余的状态承载体数量，分母是识别到的状态承载体数量。",
        "state_value_scatter_ratio": "分子是参与计分的硬编码状态值数量，分母是状态承载体状态项与计分硬编码状态值之和。",
        "failure_strategy_split_ratio": "先统计 catch 失败处理策略，分子逻辑是 1 - 主导策略占比；值越高表示失败处理越分裂。",
        "swallowed_exception_ratio": "分子是空 catch、只打日志或没有失败处理动作的 catch 块，分母是全部 catch 块。",
        "error_return_contract_mix_ratio": "先统计 Controller/API 失败返回契约，分子逻辑是 1 - 主导契约占比；值越高表示失败返回越不统一。",
        "generic_exception_throw_ratio": "分子是 RuntimeException/Exception/Throwable 等泛化异常抛出次数，分母是全部异常抛出次数。",
        "business_exception_convergence_gap": "分子是未命中标准业务异常集合的业务异常抛出次数，分母是全部业务异常抛出次数。",
        "todo_density_per_k_files": "分子是 TODO/FIXME/HACK 等债务标记数并乘以 1000，分母是 Java 文件总数，结果表示每千文件债务密度。",
        "unowned_debt_ratio": "分子是没有责任人的债务标记数，分母是全部债务标记数；责任人识别规则来自 owner_patterns 配置。",
        "public_knowledge_gap_ratio": "分子逻辑是 1 - 公共知识沉淀覆盖率；覆盖率来自公共类/方法等目标的 JavaDoc 或说明命中情况。",
        "complex_method_ratio": "分子是代码行数、分支数或嵌套深度超过阈值的方法数，分母是识别到的方法总数。",
        "large_file_class_burden_ratio": "分子是物理总行数超过大文件阈值的 Java 文件数，分母是 Java 文件总数。",
        "project_doc_gap_ratio": "分子逻辑是 1 - 项目文档可用度；文档可用度由入口文档、文档规模、主题覆盖、示例和结构化内容共同计算。",
    }
    if metric_id == "project_doc_gap_ratio":
        quality = facts.get("project_doc_quality_score", details.get("project_doc_quality_score"))
        return f"{calculation_notes[metric_id]} 当前文档可用度为 {_fmt_percent_from_ratio(quality)}。"
    return calculation_notes.get(metric_id, "按当前指标公式和规则阈值计算风险系数，再乘以该规则权重得到贡献分。")


def _fmt_count_phrase(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"，共 {_fmt_number(value, 0)} 处"
    return ""


def _score_breakdown_rows(item: dict[str, object]) -> list[dict[str, object]]:
    score_breakdown = item.get("score_breakdown") if isinstance(item.get("score_breakdown"), dict) else {}
    rules = score_breakdown.get("rules") if isinstance(score_breakdown.get("rules"), list) else []
    rows: list[dict[str, object]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        row = dict(rule)
        metric_id = str(row.get("metric", "")).strip()
        row["description"] = _score_rule_description(metric_id, row, item) if metric_id else _clean_ui_text(row.get("rule_cn", ""))
        if metric_id:
            row["calculation_description"] = _score_rule_calculation_description(metric_id, item)
        row["condition"] = _entropy_condition_label(row.get("condition"))
        calculation = _entropy_metric_substitution_note(metric_id, item) if metric_id else ""
        if calculation:
            calculation = re.sub(r"^本次代入：", "", calculation)
            row["calculation"] = calculation
        rows.append(row)
    return rows


def _project_doc_gap_overview_rows(item: dict[str, object]) -> list[dict[str, object]]:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    if "project_doc_quality_score" not in details and "project_doc_gap_ratio" not in metrics:
        return []
    gap = metrics.get("project_doc_gap_ratio", details.get("project_doc_gap_ratio"))
    quality = details.get("project_doc_quality_score")
    doc_count = details.get("project_doc_file_count")
    total_chars = details.get("project_doc_total_chars")
    covered_topics = details.get("project_doc_covered_topic_count")
    required_topics = details.get("project_doc_required_topic_count")
    missing_topics = details.get("project_doc_missing_topic_count")
    entry_exists = details.get("project_doc_entry_exists")
    entry_status = "存在" if bool(entry_exists) else "缺失"
    summary = (
        f"文档可用度 {_fmt_percent_from_ratio(quality)}，缺口 {_fmt_ratio_result(gap)}；"
        f"命中 {_fmt_number(doc_count, 0)} 份文档，正文 {_fmt_number(total_chars, 0)} 字符，"
        f"主题覆盖 {_fmt_number(covered_topics, 0)} / {_fmt_number(required_topics, 0)}。"
    )
    focus = (
        "当前未发现项目文档缺口，优先保持 README 与补充文档同步。"
        if not missing_topics and bool(entry_exists)
        else "优先补齐入口 README、缺失主题、启动配置示例和结构化说明。"
    )
    return [
        {
            "rule": "项目文档缺口比例",
            "current_value": _fmt_ratio_result(gap),
            "status": "通过" if float(gap or 0.0) == 0.0 else "关注",
            "summary": summary,
            "focus": focus,
            "entry_status": entry_status,
        }
    ]


def _detail_export_item(key: str, item: dict[str, object]) -> dict[str, object]:
    if key != "behavior":
        return item
    export_item = dict(item)
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    export_item["facts"] = {name: value for name, value in facts.items() if name in BEHAVIOR_VISIBLE_FACT_FIELDS}
    export_item["details"] = {name: value for name, value in details.items() if name in BEHAVIOR_EXPORT_DETAIL_FIELDS}
    return export_item


def _detail_payload_for_key(key: str, item: dict[str, object], full_details: dict[str, object] | None = None) -> dict[str, object]:
    full_details = full_details or {}
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    table_total_counts = details.get("table_total_counts") if isinstance(details.get("table_total_counts"), dict) else {}
    score_breakdown_rows = _score_breakdown_rows(item)
    tables: list[dict[str, object]] = []
    breakdown_table = _make_table(
        "score_breakdown",
        "规则计分明细",
        score_breakdown_rows,
        ["label", "description", "calculation_description", "raw_value", "calculation", "condition", "severity", "contribution", "max_contribution", "status"],
        strict_preferred=True,
    )
    if breakdown_table is not None:
        tables.append(breakdown_table)
    metric_rows = _base_metric_rows(details, key)
    metric_columns = ["metric_group", "label", "field", "value", "description"] if key in {"semantic", "structure", "behavior", "cognition"} else ["label", "field", "value"]
    tables.append(
        {
            "id": "metrics",
            "label": _detail_table_label("metrics", "基础指标"),
            "description": _detail_table_description("metrics", "基础指标"),
            "count": len(metric_rows),
            "display_count": len(metric_rows),
            "total_count": len(metric_rows),
            "columns": metric_columns,
            "rows": metric_rows,
        }
    )

    def add(table: dict[str, object] | None) -> None:
        if table is not None:
            tables.append(table)

    if key == "structure":
        directory_stats = full_details.get("directory_stats") if isinstance(full_details.get("directory_stats"), dict) else {}
        top_directories = directory_stats.get("top_directories") or details.get("top_large_dirs")
        oversized_directories = directory_stats.get("oversized_directories") or details.get("oversized_dirs")
        top_n_directories = directory_stats.get("top_n_concentration_directories") or details.get("top_n_concentration_dirs")
        add(_make_table("structure_shared_bucket_locations", "共享承载目录占比定位", directory_stats.get("shared_bucket_files"), ["path", "dir", "common", "utility", "common_match_source_applied", "utility_match_source_applied"], total_count=int(details.get("shared_bucket_total", 0) or 0), strict_preferred=True))
        add(_make_table("structure_max_dir_locations", "最大目录文件占比定位", top_directories[:1] if isinstance(top_directories, list) else top_directories, ["dir", "files", "lines", "sample_files"], total_count=1 if isinstance(top_directories, list) and top_directories else 0, strict_preferred=True))
        add(_make_table("structure_oversized_dir_locations", "超大目录数量占比定位", oversized_directories, ["dir", "files", "lines", "sample_files"], total_count=int(details.get("oversized_dir_count", 0) or 0), strict_preferred=True))
        add(_make_table("structure_top_n_dir_locations", "前 N 大目录集中度定位", top_n_directories, ["dir", "files", "lines", "sample_files"], total_count=len(top_n_directories) if isinstance(top_n_directories, list) else None, strict_preferred=True))
    elif key == "semantic":
        add(_make_table("semantic_rule_overview", "规则问题概要", details.get("semantic_rule_overview"), ["rule", "status", "current_value", "count_summary", "problem_count", "problem_unit", "summary", "focus"], total_count=int(table_total_counts.get("semantic_rule_overview", 0) or 0), strict_preferred=True))
        add(_make_table("naming_conflict_issues", "变体家族说明", details.get("naming_conflict_issues"), ["term", "standard", "variant_count", "nonstandard_hits", "matched_hits", "nonstandard_ratio", "variants"], total_count=int(table_total_counts.get("naming_conflict_issues", 0) or 0)))
        add(_make_table("naming_conflict_locations", "非标准命名代码定位", details.get("naming_conflict_locations"), ["term", "variant", "class_name", "file", "line"], total_count=int(table_total_counts.get("naming_conflict_locations", 0) or 0), strict_preferred=True))
        add(_make_table("undefined_term_issues", "术语缺口问题", details.get("undefined_term_issues"), ["term", "count", "sample_locations"], total_count=int(table_total_counts.get("undefined_term_issues", 0) or 0)))
        add(_make_table("undefined_term_locations", "术语缺口代码定位", details.get("undefined_term_locations"), ["term", "source", "class_name", "file", "line"], total_count=int(table_total_counts.get("undefined_term_locations", 0) or 0)))
        add(_make_table("state_duplicate_cluster_issues", "状态承载体重复簇", details.get("state_duplicate_cluster_issues"), ["cluster_id", "carrier_count", "redundant_count", "shared_items", "carrier_names"], total_count=int(table_total_counts.get("state_duplicate_cluster_issues", 0) or 0)))
        add(_make_table("state_duplicate_carrier_issues", "状态承载体重复定位", details.get("state_duplicate_carrier_issues"), ["cluster_id", "name", "kind", "file", "line", "items"], total_count=int(table_total_counts.get("state_duplicate_carrier_issues", 0) or 0)))
        add(_make_table("state_scattered_value_issues", "状态值散落问题", details.get("state_scattered_value_issues"), ["value", "confidence", "occurrence_count", "scored_occurrence_count", "candidate_occurrence_count", "file_count", "sample_locations"], total_count=int(table_total_counts.get("state_scattered_value_issues", 0) or 0), strict_preferred=True))
        add(_make_table("state_scattered_value_locations", "状态值散落代码定位", details.get("state_scattered_value_locations"), ["value", "confidence", "scored", "raw_value", "file", "line", "context"], total_count=int(table_total_counts.get("state_scattered_value_locations", 0) or 0), strict_preferred=True))
    elif key == "behavior":
        add(_make_table("failure_strategy_issues", "失败处理策略分裂", details.get("failure_strategy_issues"), ["strategy", "file", "line", "context"], total_count=int(table_total_counts.get("failure_strategy_issues", 0) or 0), strict_preferred=True))
        add(_make_table("swallowed_exception_issues", "吞异常代码", details.get("swallowed_exception_issues"), ["strategy", "file", "line", "context"], total_count=int(table_total_counts.get("swallowed_exception_issues", 0) or 0), strict_preferred=True))
        add(_make_table("error_return_contract_issues", "返回错误契约混用", details.get("error_return_contract_issues"), ["contract", "file", "line", "context"], total_count=int(table_total_counts.get("error_return_contract_issues", 0) or 0), strict_preferred=True))
        add(_make_table("generic_exception_issues", "泛化异常滥用", details.get("generic_exception_issues"), ["exception_type", "file", "line", "context"], total_count=int(table_total_counts.get("generic_exception_issues", 0) or 0), strict_preferred=True))
        add(_make_table("business_exception_convergence_issues", "业务异常未收敛", details.get("business_exception_convergence_issues"), ["exception_type", "standard", "file", "line", "context"], total_count=int(table_total_counts.get("business_exception_convergence_issues", 0) or 0), strict_preferred=True))
    elif key == "cognition":
        add(_make_table("debt_marker_issues", "债务标记问题", details.get("debt_marker_issues"), ["type", "file", "line", "content", "has_owner"], total_count=int(table_total_counts.get("debt_marker_issues", 0) or 0), strict_preferred=True))
        add(_make_table("unowned_debt_issues", "未归属债务问题", details.get("unowned_debt_issues"), ["type", "file", "line", "content"], total_count=int(table_total_counts.get("unowned_debt_issues", 0) or 0), strict_preferred=True))
        add(_make_table("public_knowledge_gap_issues", "公共知识缺口", details.get("public_knowledge_gap_issues"), ["target_type", "name", "visibility", "file", "line"], total_count=int(table_total_counts.get("public_knowledge_gap_issues", 0) or 0), strict_preferred=True))
        add(_make_table("complex_method_issues", "复杂方法", details.get("complex_method_issues"), ["method", "file", "start_line", "lines", "branch_count", "nesting_depth", "reason"], total_count=int(table_total_counts.get("complex_method_issues", 0) or 0), strict_preferred=True))
        add(_make_table("large_file_class_issues", "大文件/大类负担", details.get("large_file_class_issues"), ["file", "lines", "level", "reason"], total_count=int(table_total_counts.get("large_file_class_issues", 0) or 0), strict_preferred=True))
        add(_make_table("project_doc_gap_overview", "项目文档缺口比例", _project_doc_gap_overview_rows(item), ["rule", "current_value", "status", "summary", "focus", "entry_status"], total_count=1, strict_preferred=True))
        add(_make_table("project_doc_issues", "项目文档缺口", details.get("project_doc_issues"), ["issue_type", "target", "current", "expected", "file"], total_count=int(table_total_counts.get("project_doc_issues", 0) or 0), strict_preferred=True))
        add(_make_table("project_doc_topic_coverage", "项目文档主题覆盖", details.get("project_doc_topic_coverage"), ["topic", "status", "matched_aliases", "required_aliases"], total_count=int(table_total_counts.get("project_doc_topic_coverage", 0) or 0), strict_preferred=True))
        add(_make_table("project_doc_files", "项目文档清单", details.get("project_doc_files"), ["file", "chars", "headings", "code_blocks", "tables", "images", "links"], total_count=int(details.get("project_doc_file_count", 0) or 0), strict_preferred=True))
    elif key == "style":
        add(_make_table("style_rule_overview", "风格规则总览", details.get("style_rule_overview"), ["category_label", "issue_count", "description"], total_count=int(table_total_counts.get("style_rule_overview", 0) or 0), strict_preferred=True))
        issue_columns = ["file", "line", "column", "category_label", "module", "description", "message"]
        add(_make_table("style_formatting_issues", "格式排版问题", details.get("style_formatting_issues"), issue_columns, total_count=int(table_total_counts.get("style_formatting_issues", 0) or 0), strict_preferred=True))
        add(_make_table("style_naming_issues", "命名规范问题", details.get("style_naming_issues"), issue_columns, total_count=int(table_total_counts.get("style_naming_issues", 0) or 0), strict_preferred=True))
        add(_make_table("style_import_issues", "导入规范问题", details.get("style_import_issues"), issue_columns, total_count=int(table_total_counts.get("style_import_issues", 0) or 0), strict_preferred=True))
        add(_make_table("style_declaration_issues", "注解与声明规范问题", details.get("style_declaration_issues"), issue_columns, total_count=int(table_total_counts.get("style_declaration_issues", 0) or 0), strict_preferred=True))
        add(_make_table("style_code_smell_issues", "编码坏味道问题", details.get("style_code_smell_issues"), issue_columns, total_count=int(table_total_counts.get("style_code_smell_issues", 0) or 0), strict_preferred=True))
        add(_make_table("style_complexity_issues", "复杂度与规模问题", details.get("style_complexity_issues"), issue_columns, total_count=int(table_total_counts.get("style_complexity_issues", 0) or 0), strict_preferred=True))
        add(_make_table("checkstyle_module_distribution", "Checkstyle 规则分布", details.get("checkstyle_module_distribution"), ["module", "category_label", "module_meaning", "count"], total_count=int(table_total_counts.get("checkstyle_module_distribution", 0) or 0), strict_preferred=True))

    return {**_entropy_export_payload(key, _detail_export_item(key, item)), "tables": tables}


def render_html_dashboard(snapshot: ScoredSnapshot) -> str:
    project_id = str(snapshot.project_facts.get("project_id", "project")).strip() or "project"
    code_entropy = snapshot.project_facts.get("code_entropy", {}) if isinstance(snapshot.project_facts.get("code_entropy"), dict) else {}
    summary = snapshot.project_facts.get("code_entropy_summary", {}) if isinstance(snapshot.project_facts.get("code_entropy_summary"), dict) else {}
    total_entropy = _as_float(summary.get("total_entropy_score"))
    health_score = _as_float(summary.get("health_score"))
    total_level = str(summary.get("total_entropy_level", "")).strip() or _entropy_level(total_entropy)
    health_formula = str(summary.get("derived_health_formula", "")).strip() or "派生健康度 = 100 - 总熵"
    items = [(key, item) for key in ["structure", "semantic", "behavior", "cognition", "style"] if isinstance((item := code_entropy.get(key)), dict)]
    top_metrics = [(key, float(item.get("score", 0.0) or 0.0)) for key, item in items if isinstance(item.get("score"), (int, float))]
    cards_html = "".join(_render_entropy_card(key, item) for key, item in items) or '<div class="empty-state">当前没有可展示的代码本体熵数据。</div>'
    drawer_templates = _render_entropy_drawer_templates(code_entropy)
    summary_copy = _health_summary_copy(total_entropy, top_metrics, summary)
    entropy_weights = summary.get("entropy_weights") if isinstance(summary.get("entropy_weights"), dict) else {}
    hero_ranking = _hero_risk_ranking(items, entropy_weights)
    hero_score_insights = _hero_score_insights(items, entropy_weights, summary, code_entropy)
    hero_score_coverage = _hero_score_coverage_compact(items, summary, code_entropy)
    statistics = dict(summary.get("statistics", {})) if isinstance(summary.get("statistics"), dict) else {}
    structure_details = code_entropy.get("structure", {}).get("details", {}) if isinstance(code_entropy.get("structure"), dict) and isinstance(code_entropy.get("structure", {}).get("details"), dict) else {}
    if "total_directories" not in statistics and isinstance(structure_details.get("total_directories"), (int, float)):
        statistics["total_directories"] = structure_details.get("total_directories")
    hero_files = _fmt_number(statistics.get("total_files"), 0)
    hero_dirs = _fmt_number(statistics.get("total_directories"), 0)
    hero_todos = _fmt_number(statistics.get("total_todos"), 0)
    total_progress = 0 if total_entropy is None else max(0.0, min(100.0, float(total_entropy)))
    style = """
    <style>
        :root {
            color-scheme: dark;
            --bg:#09111b; --surface:#0f1a29; --surface-alt:#132132; --surface-raised:rgba(15,26,41,.84); --surface-glass:rgba(255,255,255,.06);
            --strong:#08111d; --strong-2:#0d1c2d; --text:#e8eef6; --muted:#9fb0c2; --line:#24364a; --line-strong:#36506b;
            --brand:#0f766e; --brand-ink:#0b5b55; --brand-soft:rgba(15,118,110,.18);
            --good:#15803d; --good-soft:rgba(21,128,61,.2); --warning:#b76e12; --warning-soft:rgba(183,110,18,.2); --danger:#c2410c; --danger-soft:rgba(194,65,12,.22);
            --nav-bg:rgba(9,17,27,.9); --focus:#38bdf8; --radius-md:18px; --radius-lg:28px;
            --shadow-sm:0 14px 30px rgba(0,0,0,.28); --shadow-md:0 26px 56px rgba(0,0,0,.38);
        }
        * { box-sizing:border-box; }
        html { scroll-behavior:smooth; scroll-padding-top:84px; }
        body {
            margin:0; font-family:"Avenir Next","Segoe UI Variable","Segoe UI","PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif;
            background:
                radial-gradient(circle at top left, rgba(15,118,110,.16), transparent 24%),
                radial-gradient(circle at 88% 0, rgba(37,99,235,.12), transparent 20%),
                linear-gradient(180deg, rgba(255,255,255,.22), transparent 22%),
                var(--bg);
            color:var(--text); line-height:1.6;
        }
        body.drawer-open { overflow:hidden; }
        [hidden] { display:none !important; }
        a, button, summary { transition:background-color .18s ease,border-color .18s ease,color .18s ease,box-shadow .18s ease,transform .18s ease; }
        a:focus-visible, button:focus-visible, summary:focus-visible { outline:3px solid var(--focus); outline-offset:3px; }
        .skip-link { position:fixed; top:-48px; left:16px; z-index:220; min-height:40px; padding:8px 14px; border-radius:8px; background:var(--surface); color:var(--text); box-shadow:var(--shadow-sm); text-decoration:none; }
        .skip-link:focus { top:16px; }
        .inner { max-width:1440px; margin:0 auto; padding:0 24px; }
        .hero-band {
            position:relative; overflow:hidden; padding:34px 0 30px;
            background:
                radial-gradient(circle at top left, rgba(94,234,212,.18), transparent 28%),
                radial-gradient(circle at bottom right, rgba(59,130,246,.18), transparent 26%),
                linear-gradient(145deg,var(--strong),var(--strong-2));
            color:#fff; box-shadow:inset 0 -1px 0 rgba(255,255,255,.08);
        }
        .hero-band::after {
            content:""; position:absolute; inset:auto 0 0; height:140px;
            background:linear-gradient(180deg, transparent, rgba(8,17,29,.18));
            pointer-events:none;
        }
        .hero-grid { position:relative; z-index:1; display:grid; grid-template-columns:minmax(0,1.08fr) minmax(380px,.82fr); gap:28px; align-items:start; }
        .hero-copy { display:grid; gap:18px; align-content:start; }
        .hero-head { display:grid; gap:12px; }
        .hero-eyebrow { color:rgba(255,255,255,.62); font-size:12px; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }
        .hero-meta-row { display:flex; flex-wrap:wrap; gap:10px; }
        .meta-pill {
            display:inline-flex; align-items:center; min-height:34px; padding:0 14px; border-radius:999px;
            border:1px solid rgba(255,255,255,.14); background:rgba(255,255,255,.08); backdrop-filter:blur(10px);
            color:rgba(255,255,255,.88); font-size:13px; font-weight:700;
        }
        .hero-title-row { display:flex; align-items:center; justify-content:space-between; gap:18px; }
        .hero-title { margin:0; font-size:clamp(38px,5.6vw,64px); line-height:.94; letter-spacing:0; }
        .hero-catalog-link {
            display:inline-flex; align-items:center; gap:8px; min-height:42px; padding:0 14px; border-radius:14px;
            border:1px solid rgba(79,209,197,.38); background:rgba(15,118,110,.24); color:#99f6e4;
            text-decoration:none; font-size:14px; font-weight:900; white-space:nowrap;
        }
        .hero-catalog-link::before { content:""; width:10px; height:10px; border-radius:999px; background:#4fd1c5; box-shadow:0 0 0 4px rgba(79,209,197,.14); }
        .hero-catalog-link:hover { transform:translateY(-1px); border-color:rgba(79,209,197,.62); background:rgba(15,118,110,.34); }
        .hero-summary { max-width:66ch; margin:0; color:rgba(255,255,255,.78); font-size:16px; }
        .hero-story { display:grid; gap:14px; padding:18px 20px; border-radius:var(--radius-md); border:1px solid rgba(255,255,255,.12); background:linear-gradient(180deg, rgba(255,255,255,.10), rgba(255,255,255,.04)); box-shadow:var(--shadow-sm); }
        .hero-story-label { color:rgba(255,255,255,.62); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
        .hero-story-copy { margin:0; color:rgba(255,255,255,.88); font-size:15px; line-height:1.7; }
        .hero-pressure-list { display:flex; flex-wrap:wrap; gap:10px; }
        .hero-pressure-pill { display:inline-flex; align-items:center; gap:8px; min-height:26px; padding:0; border:none; background:none; color:#fff; font-size:14px; font-weight:700; }
        .hero-pressure-pill strong { font-size:15px; font-weight:800; font-variant-numeric:tabular-nums; }
        .hero-pressure-pill-good { color:#7ae6d7; }
        .hero-pressure-pill-warning { color:#f7c46e; }
        .hero-pressure-pill-danger { color:#ff8d78; }
        .hero-ranking { display:grid; gap:12px; padding:16px 18px; border-radius:var(--radius-md); border:1px solid rgba(255,255,255,.12); background:rgba(255,255,255,.055); box-shadow:var(--shadow-sm); }
        .hero-ranking-head { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; }
        .hero-ranking-head p { margin:4px 0 0; color:rgba(255,255,255,.68); font-size:13px; line-height:1.55; }
        .hero-ranking-count { display:inline-flex; align-items:center; justify-content:center; min-height:28px; padding:0 10px; border-radius:999px; background:rgba(255,255,255,.09); color:rgba(255,255,255,.78); font-size:12px; font-weight:800; white-space:nowrap; }
        .risk-rank-list { display:grid; gap:8px; }
        .risk-rank-row {
            display:grid; grid-template-columns:34px minmax(0,1fr) auto; gap:12px; align-items:center; min-height:62px;
            padding:10px 12px; border-radius:14px; border:1px solid rgba(255,255,255,.10);
            background:rgba(8,17,29,.38); color:#fff; text-decoration:none;
        }
        .risk-rank-row:hover { transform:translateY(-1px); border-color:rgba(255,255,255,.22); background:rgba(255,255,255,.08); }
        .risk-rank-row-danger { border-color:rgba(248,113,113,.26); }
        .risk-rank-row-warning { border-color:rgba(246,173,85,.24); }
        .risk-rank-row-good { border-color:rgba(79,209,197,.20); }
        .risk-rank-row-excellent { border-color:rgba(104,211,145,.20); }
        .risk-rank-index {
            display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px; border-radius:8px;
            background:rgba(255,255,255,.08); color:rgba(255,255,255,.82); font-size:13px; font-weight:900; font-variant-numeric:tabular-nums;
        }
        .risk-rank-main { min-width:0; display:grid; gap:4px; }
        .risk-rank-title-line { display:flex; align-items:center; flex-wrap:wrap; gap:8px; min-width:0; }
        .risk-rank-title { color:#fff; font-size:15px; line-height:1.25; font-weight:900; }
        .risk-rank-status { display:inline-flex; align-items:center; min-height:22px; padding:0 8px; border-radius:999px; font-size:11px; line-height:1; font-style:normal; font-weight:800; }
        .risk-rank-status-excellent { color:#bbf7d0; background:rgba(104,211,145,.14); }
        .risk-rank-status-good { color:#99f6e4; background:rgba(79,209,197,.14); }
        .risk-rank-status-warning { color:#fbd38d; background:rgba(246,173,85,.14); }
        .risk-rank-status-danger { color:#fecaca; background:rgba(248,113,113,.14); }
        .risk-rank-weight-inline { margin-left:4px; color:rgba(255,255,255,.58); font-size:13px; font-weight:800; white-space:nowrap; }
        .risk-rank-scope { min-width:0; color:rgba(255,255,255,.62); font-size:12px; line-height:1.45; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .risk-rank-score { display:inline-flex; align-items:baseline; justify-content:flex-end; min-width:86px; color:rgba(255,255,255,.72); font-size:13px; font-weight:800; font-variant-numeric:tabular-nums; }
        .risk-rank-score strong { color:#fff; font-size:22px; line-height:1; }
        .risk-rank-score span { margin-left:2px; }
        .hero-actions, .section-actions, .drawer-actions { display:flex; flex-wrap:wrap; gap:10px; }
        .hero-score-card { display:flex; flex-direction:column; gap:18px; align-self:start; height:auto; padding:24px; border:1px solid rgba(255,255,255,.12); border-radius:24px; background:linear-gradient(180deg, rgba(255,255,255,.12), rgba(255,255,255,.06)); box-shadow:var(--shadow-md); backdrop-filter:blur(14px); }
        .hero-score-top { display:grid; grid-template-columns:minmax(0,1fr) minmax(190px,240px); gap:18px; align-items:stretch; }
        .hero-score-primary { min-width:0; display:grid; gap:18px; align-content:start; }
        .score-card-topline { color:rgba(255,255,255,.56); font-size:12px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
        .score-card-label { color:rgba(255,255,255,.78); font-size:13px; font-weight:700; }
        .hero-score { font-size:clamp(56px,12vw,96px); font-weight:800; line-height:.92; letter-spacing:0; font-variant-numeric:tabular-nums; }
        .hero-score span { margin-left:6px; font-size:clamp(18px,3vw,28px); color:rgba(255,255,255,.7); font-weight:700; }
        .score-excellent { color:#68d391; } .score-good { color:#4fd1c5; } .score-warning { color:#f6ad55; } .score-danger { color:#f87171; }
        .score-pill, .metric-status, .legend-chip { display:inline-flex; align-items:center; justify-content:center; min-height:30px; padding:0 10px; border-radius:999px; font-size:12px; font-weight:700; }
        .score-pill-excellent { background:rgba(104,211,145,.16); color:#bbf7d0; } .score-pill-good { background:rgba(79,209,197,.16); color:#99f6e4; }
        .score-pill-warning { background:rgba(246,173,85,.16); color:#fbd38d; } .score-pill-danger { background:rgba(248,113,113,.16); color:#fecaca; }
        .hero-score-text, .drawer-summary, .section-desc, .metric-caption, .metric-fact-note { color:var(--muted); }
        .hero-score-text { margin:0; color:rgba(255,255,255,.78); font-size:14px; }
        .hero-meter { height:10px; border-radius:999px; background:rgba(255,255,255,.12); overflow:hidden; }
        .hero-meter span { display:block; height:100%; width:var(--total-progress,0%); border-radius:inherit; background:linear-gradient(90deg,#68d391 0%,#f6ad55 55%,#f87171 100%); }
        .score-insights { display:grid; gap:12px; }
        .score-contribution-panel, .score-confidence-line {
            display:grid; gap:10px; padding:14px; border-radius:16px; border:1px solid rgba(255,255,255,.10);
            background:rgba(8,17,29,.30);
        }
        .score-panel-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
        .score-panel-head span, .score-confidence-line strong { color:rgba(255,255,255,.78); font-size:13px; font-weight:900; }
        .score-panel-head strong { color:rgba(255,255,255,.58); font-size:12px; font-weight:800; }
        .score-contribution-list { display:grid; gap:8px; }
        .score-contribution-row { display:grid; grid-template-columns:64px minmax(0,1fr) 48px; gap:10px; align-items:center; min-height:24px; }
        .score-contribution-row span { color:rgba(255,255,255,.72); font-size:12px; font-weight:800; white-space:nowrap; }
        .score-contribution-row b { height:8px; border-radius:999px; background:rgba(255,255,255,.10); overflow:hidden; }
        .score-contribution-row i { display:block; width:var(--w); height:100%; border-radius:inherit; background:linear-gradient(90deg,#4fd1c5 0%,#f6ad55 55%,#f87171 100%); }
        .score-contribution-row strong { color:#fff; font-size:13px; font-weight:900; text-align:right; font-variant-numeric:tabular-nums; }
        .score-evidence-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
        .score-evidence-card {
            display:grid; gap:4px; min-height:76px; padding:12px 14px; border-radius:16px; border:1px solid rgba(255,255,255,.10);
            background:rgba(255,255,255,.06);
        }
        .score-evidence-card span { color:rgba(255,255,255,.62); font-size:12px; font-weight:800; }
        .score-evidence-card strong { color:#fff; font-size:18px; line-height:1.22; font-weight:900; font-variant-numeric:tabular-nums; }
        .score-evidence-card small { color:rgba(255,255,255,.56); font-size:12px; line-height:1.4; font-weight:650; }
        .score-confidence-line span { color:#fff; font-size:13px; font-weight:850; }
        .score-confidence-line small { color:rgba(255,255,255,.58); font-size:12px; line-height:1.45; }
        .score-confidence-line-compact {
            position:relative; overflow:hidden; gap:12px; height:100%; min-height:0; padding:14px;
            border-color:rgba(79,209,197,.16); background:linear-gradient(180deg,rgba(15,26,41,.72),rgba(8,17,29,.28));
        }
        .score-confidence-line-compact::before {
            content:""; position:absolute; inset:0 0 auto; height:3px;
            background:linear-gradient(90deg,rgba(79,209,197,.90),rgba(104,211,145,.56));
        }
        .score-confidence-head { display:flex; align-items:center; justify-content:space-between; gap:10px; padding-top:2px; }
        .score-confidence-head span {
            display:inline-flex; align-items:center; justify-content:center; min-height:24px; padding:0 9px;
            border-radius:999px; color:#99f6e4; background:rgba(79,209,197,.12); font-size:11px; line-height:1; font-weight:900;
            white-space:nowrap;
        }
        .score-confidence-counts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; }
        .score-confidence-count {
            display:grid; justify-items:center; gap:3px; min-width:0; padding:8px 4px; border-radius:10px;
            border:1px solid rgba(255,255,255,.08); background:rgba(255,255,255,.055);
        }
        .score-confidence-count b { color:#fff; font-size:20px; line-height:1; font-weight:900; font-variant-numeric:tabular-nums; }
        .score-confidence-count span { color:rgba(255,255,255,.58); font-size:11px; line-height:1.2; font-weight:800; white-space:nowrap; }
        .score-confidence-files { display:grid; gap:6px; align-self:end; padding-top:10px; border-top:1px solid rgba(255,255,255,.08); }
        .score-confidence-files span { color:rgba(255,255,255,.58); font-size:11px; line-height:1; font-weight:900; letter-spacing:.08em; text-transform:uppercase; }
        .score-confidence-file-row { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; }
        .score-confidence-file-row b {
            display:grid; gap:2px; min-width:0; color:#fff; font-size:12px; line-height:1.2; font-weight:900;
            font-variant-numeric:tabular-nums;
        }
        .score-confidence-file-row b small { color:rgba(255,255,255,.56); font-size:10px; line-height:1.1; font-weight:800; }
        .nav-shell { position:sticky; top:0; z-index:70; padding:14px 0 0; backdrop-filter:blur(18px); }
        .section-nav { display:flex; gap:10px; overflow-x:auto; padding:14px 18px; border:1px solid var(--line); border-radius:999px; background:var(--nav-bg); box-shadow:var(--shadow-sm); scrollbar-width:thin; }
        .nav-link, .action-link { display:inline-flex; align-items:center; justify-content:center; min-height:46px; padding:0 16px; border:1px solid var(--line); border-radius:14px; background:var(--surface); color:var(--text); text-decoration:none; white-space:nowrap; font-size:14px; font-weight:700; font-family:inherit; cursor:pointer; }
        .nav-link { color:var(--muted); }
        .nav-link:hover, .action-link:hover { transform:translateY(-1px); box-shadow:var(--shadow-sm); border-color:var(--line-strong); }
        .nav-link.is-active { background:var(--brand); border-color:var(--brand); color:#fff; }
        .action-primary { background:var(--brand); border-color:var(--brand); color:#fff; }
        .action-primary:hover { background:var(--brand-ink); border-color:var(--brand-ink); }
        .ui-icon { display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; flex:none; } .ui-icon svg { width:100%; height:100%; }
        .icon-badge { display:inline-flex; align-items:center; justify-content:center; width:40px; height:40px; border-radius:8px; flex:none; }
        .icon-badge-good, .icon-badge-excellent, .icon-badge-pass { color:var(--good); background:var(--good-soft); }
        .icon-badge-warning { color:var(--warning); background:var(--warning-soft); }
        .icon-badge-danger, .icon-badge-fail { color:var(--danger); background:var(--danger-soft); }
        main { padding:14px 0 52px; }
        .section-band { padding:22px 0 0; background:transparent; }
        .section-shell { padding:30px; border:1px solid var(--line); border-radius:var(--radius-lg); background:linear-gradient(180deg,var(--surface-raised),var(--surface)); box-shadow:var(--shadow-sm); }
        .section-header { display:flex; align-items:flex-end; justify-content:space-between; gap:24px; margin-bottom:28px; }
        .section-kicker { margin-bottom:8px; color:var(--brand); font-size:13px; font-weight:700; }
        .section-title { margin:0 0 8px; font-size:clamp(24px,3vw,34px); line-height:1.08; letter-spacing:0; }
        .section-legend { display:flex; flex-wrap:wrap; align-items:center; gap:10px 12px; margin-bottom:20px; }
        .section-legend-entropy { margin-bottom:18px; }
        .legend-chip { border:1px solid var(--line); }
        .legend-chip-neutral { color:var(--text); background:var(--surface-alt); }
        .legend-chip-excellent { color:var(--good); background:var(--good-soft); border-color:transparent; }
        .legend-chip-good { color:var(--brand); background:var(--brand-soft); border-color:transparent; }
        .legend-chip-warning { color:var(--warning); background:var(--warning-soft); border-color:transparent; }
        .legend-chip-danger { color:var(--danger); background:var(--danger-soft); border-color:transparent; }
        .entropy-summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; margin-bottom:20px; }
        .entropy-summary-card { display:grid; gap:10px; min-height:126px; padding:18px; border-radius:20px; border:1px solid var(--line); background:linear-gradient(180deg,var(--surface-alt),var(--surface)); box-shadow:var(--shadow-sm); }
        .entropy-summary-card-excellent { border-color:rgba(21,128,61,.22); }
        .entropy-summary-card-good, .entropy-summary-card-brand { border-color:rgba(15,118,110,.22); }
        .entropy-summary-card-warning { border-color:rgba(183,110,18,.24); }
        .entropy-summary-card-danger { border-color:rgba(194,65,12,.28); }
        .entropy-summary-kicker { color:var(--muted); font-size:12px; font-weight:700; }
        .entropy-summary-value { font-size:20px; line-height:1.25; font-weight:800; color:var(--text); }
        .entropy-summary-note { color:var(--muted); font-size:13px; line-height:1.5; }
        .metrics-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:20px; align-items:stretch; }
        .metric-card { position:relative; overflow:hidden; display:grid; grid-template-rows:auto auto auto 1fr auto; gap:18px; min-height:100%; background:linear-gradient(180deg,var(--surface),var(--surface-alt)); padding:22px; border-radius:22px; border:1px solid var(--line); box-shadow:var(--shadow-sm); }
        .metric-card::before { content:""; position:absolute; inset:0 0 auto; height:4px; background:linear-gradient(90deg, rgba(15,118,110,.82), rgba(59,130,246,.76)); }
        .metric-card:hover { border-color:var(--line-strong); box-shadow:var(--shadow-md); transform:translateY(-2px); }
        .metric-card-excellent { border-color:rgba(21,128,61,.22); } .metric-card-good { border-color:rgba(15,118,110,.22); }
        .metric-card-warning { border-color:rgba(183,110,18,.24); } .metric-card-danger { border-color:rgba(194,65,12,.28); }
        .metric-card-top { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; flex-wrap:wrap; }
        .metric-heading { display:flex; gap:12px; align-items:flex-start; min-width:0; flex:1 1 auto; }
        .metric-head-copy { min-width:0; display:grid; gap:6px; }
        .metric-name-row { display:flex; align-items:center; flex-wrap:wrap; gap:8px 10px; }
        .metric-score-row { display:grid; gap:10px; align-items:end; }
        .metric-score-main { display:grid; gap:6px; }
        .metric-name { margin:0; font-size:18px; font-weight:800; line-height:1.22; }
        .metric-caption { margin-top:0; font-size:13px; line-height:1.5; max-width:none; }
        .metric-status-excellent { color:var(--good); background:var(--good-soft); }
        .metric-status-good { color:var(--brand); background:var(--brand-soft); }
        .metric-status-warning { color:var(--warning); background:var(--warning-soft); }
        .metric-status-danger { color:var(--danger); background:var(--danger-soft); }
        .metric-value { font-size:clamp(38px,4vw,48px); line-height:.96; font-weight:800; letter-spacing:0; font-variant-numeric:tabular-nums; }
        .metric-unit { margin-left:4px; color:var(--muted); font-size:18px; font-weight:700; }
        .metric-excellent { color:var(--good); } .metric-good { color:var(--brand); } .metric-warning { color:var(--warning); } .metric-danger { color:var(--danger); }
        .metric-meter { height:8px; border-radius:999px; background:var(--surface-alt); overflow:hidden; }
        .metric-meter span { display:block; height:100%; width:var(--metric-progress); background:linear-gradient(90deg,var(--good) 0%,var(--warning) 62%,var(--danger) 100%); border-radius:inherit; }
        .metric-card-excellent .metric-meter span { background:linear-gradient(90deg,#16a34a,#22c55e); }
        .metric-card-good .metric-meter span { background:linear-gradient(90deg,#0f766e,#14b8a6); }
        .metric-card-warning .metric-meter span { background:linear-gradient(90deg,#b76e12,#f59e0b); }
        .metric-card-danger .metric-meter span { background:linear-gradient(90deg,#ea580c,#dc2626); }
        .metric-score-note { color:var(--muted); font-size:13px; font-weight:600; }
        .metric-summary { margin:0; font-size:14px; min-height:44px; line-height:1.55; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; overflow:hidden; }
        .metric-facts { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; align-content:start; }
        .metric-fact { min-height:66px; padding:12px; border-radius:16px; border:1px solid var(--line); background:var(--surface-alt); display:grid; align-content:start; }
        .metric-fact-value { margin-top:4px; color:var(--text); font-size:17px; font-weight:800; line-height:1.3; word-break:break-word; font-variant-numeric:tabular-nums; }
        .metric-fact-label { min-width:0; color:var(--muted); font-size:12px; font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .metric-fact-note { font-size:12px; line-height:1.45; color:var(--muted); }
        .metric-actions { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; align-items:stretch; }
        .metric-actions .action-link, .metric-actions button { width:100%; min-width:0; }
        .metric-actions .metric-action-primary { grid-column:1 / -1; }
        .standard-list { margin:0; padding-left:20px; display:grid; gap:8px; }
        .drawer-summary { margin:0; font-size:14px; line-height:1.65; }
        .drawer-backdrop { position:fixed; inset:0; z-index:180; background:rgba(6,10,18,.52); backdrop-filter:blur(2px); }
        .entropy-drawer { position:fixed; top:0; right:0; z-index:181; width:min(760px, calc(100vw - 20px)); height:100vh; background:var(--surface); box-shadow:-20px 0 42px rgba(0,0,0,.24); transform:translateX(104%); transition:transform .24s ease; display:flex; flex-direction:column; }
        .entropy-drawer.open { transform:translateX(0); }
        .drawer-top { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:18px 22px; border-bottom:1px solid var(--line); background:var(--surface-alt); }
        .drawer-title { font-size:18px; font-weight:800; color:var(--text); }
        .drawer-close { width:40px; height:40px; border:1px solid var(--line); border-radius:14px; background:var(--surface); color:var(--text); font-size:22px; line-height:1; cursor:pointer; }
        .drawer-content { padding:24px; overflow:auto; display:grid; gap:18px; }
        .drawer-kicker { display:inline-flex; align-items:center; gap:10px; color:var(--brand); font-weight:700; margin-bottom:8px; }
        .drawer-content h2 { margin:0 0 6px; color:var(--text); font-size:22px; }
        .drawer-section { padding:16px; border:1px solid var(--line); border-radius:18px; background:var(--surface-alt); display:grid; gap:12px; }
        .drawer-section h3 { margin:0 0 8px; font-size:18px; }
        .rich-copy { display:grid; gap:10px; color:var(--text); font-size:14px; }
        .rich-copy p { margin:0; }
        .rich-copy ul { margin:0; padding-left:20px; display:grid; gap:8px; }
        .table-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
        .table-card h3, .detail-box h4, .nested-detail h4, .drawer-section h3 { margin:0 0 8px; font-size:18px; }
        .table-card p { margin:0 0 14px; color:var(--muted); font-size:14px; }
        .table-scroll { overflow:auto; }
        table { width:100%; min-width:560px; border-collapse:separate; border-spacing:0; border:1px solid var(--line); border-radius:8px; overflow:hidden; background:var(--surface); }
        th, td { padding:12px 14px; text-align:left; vertical-align:top; font-size:14px; border-bottom:1px solid var(--line); }
        th { background:var(--surface-alt); color:var(--muted); font-weight:700; }
        td { color:var(--text); overflow-wrap:anywhere; }
        tr:last-child td { border-bottom:none; }
        .cycle-table { table-layout:fixed; }
        .cycle-table th:nth-child(1), .cycle-table td:nth-child(1) { width:56px; }
        .cycle-table th:nth-child(2), .cycle-table td:nth-child(2) { width:72px; }
        .cycle-table th:nth-child(3), .cycle-table td:nth-child(3) { width:36%; }
        .cycle-class { display:grid; gap:2px; margin-bottom:8px; }
        .cycle-class strong { color:var(--text); font-size:13px; word-break:break-all; }
        .cycle-class span, .cycle-edge { color:var(--muted); font-size:12px; word-break:break-all; }
        .detail-panel-head { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; margin-bottom:18px; }
        .detail-kicker, .drawer-kicker { display:inline-flex; align-items:center; gap:10px; color:var(--brand); font-weight:700; margin-bottom:8px; }
        .detail-panel-head h3, .drawer-content h2 { margin:0 0 6px; color:var(--text); font-size:22px; }
        .detail-layout { display:grid; grid-template-columns:minmax(260px,.85fr) minmax(360px,1.15fr); gap:18px; margin-bottom:18px; align-items:start; }
        .detail-box, .nested-detail, .drawer-section { padding:16px; border:1px solid var(--line); border-radius:18px; background:var(--surface-alt); }
        .entropy-score-explainer { display:grid; gap:14px; }
        .entropy-score-formula {
            display:grid; gap:6px; padding:14px 16px; border-radius:8px; border:1px solid rgba(15,118,110,.16);
            background:linear-gradient(180deg,rgba(15,118,110,.08),rgba(15,118,110,.03));
        }
        .entropy-score-formula-kicker { color:var(--brand); font-size:12px; font-weight:800; }
        .entropy-score-formula-line { color:var(--text); font-size:18px; line-height:1.35; font-weight:800; font-variant-numeric:tabular-nums; }
        .entropy-score-formula-note { color:var(--muted); font-size:13px; line-height:1.55; }
        .entropy-score-summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; }
        .entropy-score-summary-card {
            display:grid; gap:6px; min-height:104px; padding:14px; border-radius:16px; border:1px solid var(--line);
            background:var(--surface); box-shadow:var(--shadow-sm);
        }
        .entropy-score-summary-label { color:var(--muted); font-size:12px; font-weight:700; }
        .entropy-score-summary-value { color:var(--text); font-size:20px; font-weight:800; line-height:1.2; overflow-wrap:anywhere; word-break:break-word; }
        .entropy-score-summary-note { color:var(--muted); font-size:13px; line-height:1.5; }
        .entropy-score-breakdown-head { display:grid; gap:4px; }
        .entropy-score-breakdown-title { color:var(--text); font-size:15px; font-weight:800; }
        .entropy-score-breakdown-desc { color:var(--muted); font-size:13px; line-height:1.55; }
        .entropy-score-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }
        .entropy-score-grid-compact { grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); }
        .entropy-score-step {
            display:grid; gap:12px; min-width:0; padding:16px; border-radius:18px; border:1px solid var(--line);
            background:var(--surface); box-shadow:var(--shadow-sm);
        }
        .entropy-score-step-good, .entropy-score-step-excellent { border-color:rgba(21,128,61,.20); }
        .entropy-score-step-warning { border-color:rgba(183,110,18,.24); }
        .entropy-score-step-danger { border-color:rgba(194,65,12,.28); }
        .entropy-score-step-top { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
        .entropy-score-step-kicker { color:var(--muted); font-size:12px; font-weight:700; }
        .entropy-score-step h4 { margin:4px 0 0; color:var(--text); font-size:18px; line-height:1.25; }
        .entropy-score-step-status {
            display:inline-flex; align-items:center; justify-content:center; min-height:28px; padding:0 10px; border-radius:999px;
            font-size:12px; font-weight:700; white-space:nowrap;
        }
        .entropy-score-step-status-excellent, .entropy-score-step-status-good { color:var(--good); background:var(--good-soft); }
        .entropy-score-step-status-warning { color:var(--warning); background:var(--warning-soft); }
        .entropy-score-step-status-danger { color:var(--danger); background:var(--danger-soft); }
        .entropy-score-step-value-row { display:grid; gap:6px; }
        .entropy-score-step-value { color:var(--text); font-size:28px; line-height:1.05; font-weight:800; font-variant-numeric:tabular-nums; }
        .entropy-score-step-meta { color:var(--muted); font-size:13px; line-height:1.5; }
        .entropy-score-step-block { display:grid; gap:4px; padding-top:10px; border-top:1px solid var(--line); }
        .entropy-score-step-block span { color:var(--muted); font-size:12px; font-weight:700; }
        .entropy-score-step-block p { margin:0; color:var(--text); font-size:14px; line-height:1.6; }
        .entropy-score-chip-row { display:flex; flex-wrap:wrap; gap:8px; }
        .entropy-score-chip {
            display:inline-flex; align-items:center; min-height:28px; padding:0 10px; border-radius:999px; border:1px solid var(--line);
            background:var(--surface-alt); color:var(--muted); font-size:12px; font-weight:700;
        }
        .entropy-score-empty {
            padding:14px 16px; border-radius:8px; border:1px dashed var(--line); color:var(--muted); font-size:13px; background:var(--surface);
        }
        .raw-key { color:var(--muted); font-family:Consolas,"Courier New",monospace; font-size:12px; }
        .compact-list { margin:0; padding-left:20px; display:grid; gap:6px; color:var(--text); }
        .detail-more, .empty-detail { margin-top:10px; color:var(--muted); font-size:13px; }
        .raw-detail { margin-top:18px; padding-top:16px; border-top:1px solid var(--line); }
        .raw-detail summary { cursor:pointer; color:var(--brand); font-weight:700; }
        pre { margin:10px 0 0; white-space:pre-wrap; word-break:break-word; font-size:12px; color:var(--text); }
        .empty-state { padding:22px; border:1px dashed var(--line); border-radius:18px; color:var(--muted); text-align:center; }
        @media (max-width:1180px) { .metrics-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
        @media (max-width:960px) { .table-grid, .detail-layout { grid-template-columns:1fr; } }
        @media (max-width:1100px) { .hero-grid { grid-template-columns:1fr; } .hero-copy { grid-template-rows:auto; } .hero-ranking, .hero-score-card { height:auto; } .risk-rank-list { align-content:start; } }
        @media (max-width:720px) {
            html { scroll-padding-top:76px; }
            .inner { padding:0 16px; }
            .nav-shell { padding-top:10px; }
            .section-nav { padding:12px; border-radius:18px; }
            .section-header { flex-direction:column; align-items:flex-start; }
            .metrics-grid, .entropy-summary-grid { grid-template-columns:1fr; }
            .metric-facts { grid-template-columns:1fr; }
            .metric-actions { grid-template-columns:1fr; }
            .metric-actions .metric-action-primary { grid-column:auto; }
            .score-evidence-grid { grid-template-columns:1fr; }
            .hero-title-row { align-items:flex-start; flex-direction:column; }
            .hero-score-top { grid-template-columns:1fr; }
            .score-confidence-line-compact { min-height:0; }
            .risk-rank-row { grid-template-columns:30px minmax(0,1fr); }
            .risk-rank-score { grid-column:2; justify-content:flex-start; min-width:0; }
            .section-shell { padding:22px; border-radius:22px; }
            .section-actions .action-link, .metric-actions .action-link, .metric-actions button, .drawer-actions .action-link { width:100%; }
        }
        @media (max-width:520px) {
            .hero-band { padding:24px 0 18px; }
            .hero-title { font-size:clamp(30px,11vw,42px); }
            .hero-score { font-size:clamp(48px,16vw,72px); }
        }
        @media (prefers-reduced-motion: reduce) { html { scroll-behavior:auto; } * { transition:none !important; animation:none !important; } }
    </style>"""
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_esc(project_id)} - 代码本体熵仪表盘</title>
    {style}
</head>
<body>
    <a class="skip-link" href="#main-content">跳到主内容</a>
    <header id="overview" class="hero-band">
        <div class="inner hero-grid">
            <div class="hero-copy">
                <div class="hero-meta-row">
                    <span class="meta-pill">项目：{_esc(project_id)}</span>
                    <span class="meta-pill">周期：{_esc(snapshot.period)}</span>
                    <span class="meta-pill">来源：entropy_audit 内置扫描</span>
                </div>
                <div class="hero-head">
                    <div class="hero-eyebrow">Code Entropy</div>
                    <div class="hero-title-row">
                        <h1 class="hero-title">代码本体熵仪表盘</h1>
                        <a class="hero-catalog-link" href="../../rule_catalog.html" target="_blank" rel="noopener">规则目录</a>
                    </div>
                </div>
                <article class="hero-story">
                    <div class="hero-story-label">当前判断</div>
                    <p class="hero-story-copy">{_esc(summary_copy)}</p>
                    {_hero_pressure_badges(top_metrics)}
                </article>
                {hero_ranking}
            </div>
            <aside class="hero-score-card" style="--total-progress:{total_progress:.0f}%;">
                <div class="hero-score-top">
                    <div class="hero-score-primary">
                        <div class="score-card-topline">Primary Signal</div>
                        <div class="score-card-label">代码本体总熵（高=风险更大）</div>
                        <div class="hero-score score-{_entropy_score_class(total_entropy)}">{_esc(_fmt_compact(total_entropy))}<span>/100</span></div>
                        <div class="score-pill score-pill-{_entropy_score_class(total_entropy)}">{_esc(_level_label(total_level))}</div>
                    </div>
                    {hero_score_coverage}
                </div>
                <p class="hero-score-text">总熵按五类风险分与权重折算；右侧看贡献和证据，左侧按风险排序进入治理。</p>
                <div class="hero-meter" aria-hidden="true"><span></span></div>
                {hero_score_insights}
            </aside>
        </div>
    </header>

    <div class="nav-shell">
        <nav class="section-nav inner" aria-label="仪表盘导航">
            <a class="nav-link is-active" href="#overview">总览</a>
            <a class="nav-link" href="#code-entropy">代码本体熵</a>
        </nav>
    </div>

    <main id="main-content">
        <section id="code-entropy" class="section-band">
            <div class="inner">
                <div class="section-shell">
                    <div class="section-header">
                        <div>
                            <div class="section-kicker">代码本体熵</div>
                            <h2 class="section-title">代码本体熵评分</h2>
                            <p class="section-desc">五类熵统一按 0-100 风险分展示；卡片看关键指标，完整详情看规则、公式和代码定位。</p>
                        </div>
                        <div class="section-actions">
                            <a class="action-link" href="code_entropy_details.json">导出明细 JSON</a>
                        </div>
                    </div>
                    <div class="section-legend section-legend-entropy">
                        <span class="legend-chip legend-chip-neutral">五类熵：高=风险更大</span>
                        <span class="legend-chip legend-chip-excellent">0-39：低风险</span>
                        <span class="legend-chip legend-chip-good">40-59：可控</span>
                        <span class="legend-chip legend-chip-warning">60-79：关注</span>
                        <span class="legend-chip legend-chip-danger">80-100：高风险</span>
                    </div>
                    <div class="metrics-grid">{cards_html}</div>
                </div>
            </div>
        </section>
    </main>
    {drawer_templates}
    {_render_entropy_drawer()}
</body>
</html>'''


def build_code_entropy_detail_exports(snapshot: ScoredSnapshot, full_details: dict[str, object] | None = None) -> dict[str, dict[str, object]]:
    code_entropy = snapshot.project_facts.get("code_entropy", {})
    if not isinstance(code_entropy, dict):
        return {}
    exports: dict[str, dict[str, object]] = {}
    for key in ["structure", "semantic", "behavior", "cognition", "style"]:
        item = code_entropy.get(key)
        if isinstance(item, dict):
            exports[key] = _detail_payload_for_key(key, item, full_details)
    return exports


def render_code_entropy_detail_pages(snapshot: ScoredSnapshot, full_details: dict[str, object] | None = None) -> dict[str, str]:
    exports = build_code_entropy_detail_exports(snapshot, full_details)
    return {key: _render_code_entropy_detail_page(snapshot, key, payload) for key, payload in exports.items()}


def _detail_table_map(tables: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        str(table.get("id", "")).strip(): table
        for table in tables
        if isinstance(table, dict) and str(table.get("id", "")).strip()
    }


def _render_detail_data_table(table: dict[str, object] | None, *, empty_message: str = "暂无数据") -> str:
    if not isinstance(table, dict):
        return f'<div class="detail-empty">{_esc(empty_message)}</div>'
    rows = table.get("rows")
    columns = table.get("columns")
    if not isinstance(rows, list) or not rows:
        return f'<div class="detail-empty">{_esc(empty_message)}</div>'
    if not isinstance(columns, list) or not columns:
        sample_row = rows[0] if rows and isinstance(rows[0], dict) else {}
        columns = list(sample_row.keys()) if isinstance(sample_row, dict) else ["value"]
    header = "".join(
        f'<th title="{_esc(_detail_column_help(column))}">{_esc(_detail_label(column))}</th>'
        for column in columns
    )
    body_rows: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cells = "".join(
            f'<td title="{_esc(row.get(column, ""))}">{_esc(_detail_table_cell_value(column, row.get(column, "")))}</td>'
            for column in columns
        )
        body_rows.append(f"<tr>{cells}</tr>")
    if not body_rows:
        return f'<div class="detail-empty">{_esc(empty_message)}</div>'
    display_count = int(table.get("display_count", len(body_rows)) or len(body_rows))
    total_count = int(table.get("total_count", display_count) or display_count)
    count_copy = f"当前展示 {display_count} 条"
    if total_count != display_count:
        count_copy += f" / 总数 {total_count} 条"
    return f'''<div class="detail-table-block">
        <div class="detail-table-meta">{_esc(count_copy)}</div>
        <div class="detail-table-scroll">
            <table>
                <thead><tr>{header}</tr></thead>
                <tbody>{''.join(body_rows)}</tbody>
            </table>
        </div>
    </div>'''


def _detail_table_cell_value(column: object, value: object) -> str:
    lowered = str(column or "").strip().lower()
    if lowered in {"status", "rule_status"}:
        mapping = {
            "scored": "已计分",
            "pending_config": "待配置",
            "missing": "缺数",
        }
        return mapping.get(str(value or "").strip().lower(), _display_value(column, value, short_path=True))
    return _display_value(column, value, short_path=True)


def _render_detail_summary_cards(key: str, item: dict[str, object], details: dict[str, object]) -> str:
    rule_cards = _dashboard_rule_cards(key, item)
    if rule_cards:
        return "".join(
            f'''<article class="summary-card summary-card-rule">
                    <div class="summary-label">{_esc(card["label"])}</div>
                    <div class="summary-value">{_esc(card["value"])}</div>
                    {f'<div class="summary-note">{_esc(card["note"])}</div>' if card["note"] else ''}
                </article>'''
            for card in rule_cards
        )

    return "".join(
        f'''<article class="summary-card">
                <div class="summary-label">{_esc(_short_detail_label(name))}</div>
                <div class="summary-value">{_esc(_display_value(name, value, short_path=True))}</div>
            </article>'''
        for name, value in _metric_highlight_pairs(key, details)[:4]
    ) or '''<article class="summary-card"><div class="summary-label">暂无指标</div><div class="summary-value">等待采集</div></article>'''


def _render_sidebar_nav_groups(groups: list[dict[str, object]]) -> str:
    fragments: list[str] = []
    for group in groups:
        items = group.get("items")
        if not isinstance(items, list) or not items:
            continue
        buttons = "".join(
            f'''<a class="side-tab" href="#{_esc(item.get("id", ""))}">
                    <span class="side-tab-label">{_esc(item.get("label", ""))}</span>
                    <span class="side-tab-count">{_esc(item.get("count", ""))}</span>
                </a>'''
            for item in items
            if isinstance(item, dict)
        )
        if not buttons:
            continue
        fragments.append(
            f'''<div class="sidebar-section">
                    <div class="sidebar-label">{_esc(group.get("label", ""))}</div>
                    <div class="side-tabs">{buttons}</div>
                </div>'''
        )
    return "".join(fragments) or '<div class="empty-sidebar">暂无可浏览的明细表。</div>'


def _render_detail_section(section_id: str, title: str, description: str, body_html: str, count: str = "") -> str:
    count_html = f'<div class="section-count">{_esc(count)}</div>' if count else ""
    return f'''<section id="{_esc(section_id)}" class="detail-section">
        <div class="section-head">
            <div>
                <h3>{_esc(title)}</h3>
                <div class="section-desc">{_esc(description)}</div>
            </div>
            {count_html}
        </div>
        {body_html}
    </section>'''


def _render_semantic_rule_section(rule_overview: dict[str, object] | None, rule_meta: dict[str, str], table_map: dict[str, dict[str, object]]) -> str:
    rule_overview = rule_overview if isinstance(rule_overview, dict) else {}
    status = str(rule_overview.get("status", "scored")).strip()
    status_label = {
        "scored": "已计分",
        "pending_config": "待配置",
    }.get(status.lower(), status or "-")
    current_value = str(rule_overview.get("current_value", "")).strip() or "-"
    pending_reason = str(rule_overview.get("pending_reason", "")).strip() or "-"
    problem_count = rule_overview.get("problem_count")
    summary = str(rule_overview.get("summary", "")).strip() or "-"
    focus = str(rule_overview.get("focus", "")).strip() or "-"
    count_summary = str(rule_overview.get("count_summary", "")).strip()
    if count_summary:
        count_text = count_summary
    elif isinstance(problem_count, (int, float)):
        unit = str(rule_overview.get("problem_unit", "")).strip() or "问题对象"
        count_text = f"{int(problem_count)} 个{unit}"
    else:
        count_text = "0 个问题对象"
    overview_html = f'''<div class="rule-overview-card">
        <div class="rule-overview-grid">
            <article class="rule-overview-item"><span>规则状态</span><strong>{_esc(status_label)}</strong></article>
            <article class="rule-overview-item"><span>当前规则值</span><strong>{_esc(current_value)}</strong></article>
            <article class="rule-overview-item"><span>当前问题对象</span><strong>{_esc(count_text)}</strong></article>
            <article class="rule-overview-item"><span>修复重点</span><strong>{_esc(focus)}</strong></article>
        </div>
        <div class="rule-overview-note">
            <div><span>问题摘要</span><p>{_esc(summary)}</p></div>
            <div><span>待配置原因</span><p>{_esc(pending_reason)}</p></div>
        </div>
    </div>'''
    issues_html = _render_detail_data_table(table_map.get(rule_meta["issue_table"]), empty_message=rule_meta["empty_issues"])
    locations_html = _render_detail_data_table(table_map.get(rule_meta["location_table"]), empty_message=rule_meta["empty_locations"])
    body_html = (
        overview_html
        + '<div class="rule-section-grid">'
        + f'<div class="detail-subsection"><h4>问题清单</h4>{issues_html}</div>'
        + f'<div class="detail-subsection"><h4>代码定位</h4>{locations_html}</div>'
        + "</div>"
    )
    return _render_detail_section(rule_meta["section_id"], rule_meta["label"], rule_meta["description"], body_html, count_text)


def _detail_nav_group_key(table: dict[str, object]) -> str:
    table_id = str(table.get("id", "")).strip().lower()
    label = _clean_ui_text(table.get("label", ""))
    if table_id in {"score_breakdown", "semantic_rule_overview"} or "评分规则" in label or "规则概要" in label:
        return "rules"
    if table_id == "metrics" or "基础指标" in label or "原始指标" in label:
        return "other"
    if table_id in BEHAVIOR_LOCATION_TABLE_IDS or table_id in COGNITION_LOCATION_TABLE_IDS or table_id in STYLE_LOCATION_TABLE_IDS:
        return "locations"
    if "定位" in label or table_id.endswith("_locations") or table_id.endswith("_carrier_issues"):
        return "locations"
    if "问题" in label or table_id.endswith("_issues"):
        return "issues"
    return "other"


def _render_detail_sidebar_nav(tables: list[dict[str, object]]) -> str:
    valid_tables = [table for table in tables if isinstance(table, dict)]
    if not valid_tables:
        return '<div class="empty-sidebar">暂无可浏览的明细表。</div>'
    group_defs = [
        ("rules", "先看规则"),
        ("issues", "问题说明"),
        ("locations", "代码定位"),
        ("other", "补充明细"),
    ]
    grouped: dict[str, list[tuple[int, dict[str, object]]]] = {key: [] for key, _ in group_defs}
    for index, table in enumerate(valid_tables):
        grouped.setdefault(_detail_nav_group_key(table), []).append((index, table))
    sections: list[str] = []
    for group_key, group_label in group_defs:
        items = grouped.get(group_key) or []
        if not items:
            continue
        buttons = "".join(
            f'''<button type="button" class="side-tab{" active" if index == 0 else ""}" data-table="{_esc(table.get("id", ""))}" title="{_esc(table.get("label", ""))}：{_esc(_detail_count_copy(table.get("count", 0)))}">
                <span class="side-tab-label">{_esc(table.get("label", ""))}</span>
                <span class="side-tab-count">{_esc(_detail_count_copy(table.get("count", 0)))}</span>
            </button>'''
            for index, table in items
        )
        sections.append(
            f'''<div class="side-nav-group">
                <div class="side-nav-group-title">{_esc(group_label)}</div>
                <div class="side-tabs">{buttons}</div>
            </div>'''
        )
    return "".join(sections)


def _render_code_entropy_detail_page(snapshot: ScoredSnapshot, key: str, payload: dict[str, object]) -> str:
    label = str(payload.get("label", key))
    score = payload.get("score") if isinstance(payload.get("score"), (int, float)) else None
    level = str(payload.get("level", "unknown"))
    status = _status_class(level)
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
    primary_table = tables[0] if tables and isinstance(tables[0], dict) else {}
    total_rows = sum(int(table.get("count", 0) or 0) for table in tables if isinstance(table, dict))
    guidance = _entropy_guidance(key, score, payload)
    partial_note = _entropy_partial_note(payload)
    table_nav = _render_detail_sidebar_nav([table for table in tables if isinstance(table, dict)])
    table_count = len([table for table in tables if isinstance(table, dict)])
    summary_cards_html = _render_detail_summary_cards(key, payload, details)
    primary_label = _clean_ui_text(primary_table.get("label", "基础明细"))
    hero_summary = (f"{guidance} {partial_note}".strip() if partial_note else guidance) or _detail_hero_summary(guidance, table_count, primary_label)
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_esc(label)} - 代码本体熵详情</title>
    <style>
        :root {{
            color-scheme: dark;
            --bg:#09111b; --surface:#0f1a29; --surface-alt:#132132; --strong:#08111d; --strong-2:#0d1c2d;
            --text:#e8eef6; --muted:#9fb0c2; --line:#24364a; --line-strong:#36506b;
            --brand:#0f766e; --brand-ink:#0b5b55; --brand-soft:rgba(15,118,110,.18);
            --good:#15803d; --good-soft:rgba(21,128,61,.2); --warning:#b76e12; --warning-soft:rgba(183,110,18,.2);
            --danger:#c2410c; --danger-soft:rgba(194,65,12,.22); --focus:#2563eb;
            --shadow-sm:0 14px 30px rgba(0,0,0,.28); --shadow-md:0 26px 56px rgba(0,0,0,.38);
        }}
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{
            font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans SC",sans-serif;
            color:var(--text);
            background:radial-gradient(circle at top left, rgba(15,118,110,.12), transparent 24%),
                       radial-gradient(circle at top right, rgba(37,99,235,.10), transparent 18%), var(--bg);
            line-height:1.6;
        }}
        a, button, select, input {{ transition:background-color .18s ease,border-color .18s ease,color .18s ease,box-shadow .18s ease,transform .18s ease; }}
        a:focus-visible, button:focus-visible, select:focus-visible, input:focus-visible {{ outline:3px solid var(--focus); outline-offset:3px; }}
        .page {{ min-height:100vh; display:grid; grid-template-columns:minmax(250px,300px) minmax(0,1fr); }}
        .sidebar {{
            position:sticky; top:0; height:100vh; overflow:auto; padding:24px 18px 28px;
            background:linear-gradient(180deg,var(--strong),var(--strong-2)); color:#fff; border-right:1px solid rgba(255,255,255,.08);
        }}
        .brand {{ font-size:13px; color:rgba(255,255,255,.62); margin-bottom:8px; font-weight:700; }}
        .sidebar h1 {{ display:flex; align-items:center; gap:10px; font-size:24px; margin-bottom:10px; line-height:1.15; }}
        .ui-icon {{ display:inline-flex; align-items:center; justify-content:center; width:24px; height:24px; flex:none; color:#99f6e4; }}
        .ui-icon svg {{ width:100%; height:100%; }}
        .meta {{ color:rgba(255,255,255,.72); font-size:13px; margin-bottom:20px; display:grid; gap:8px; }}
        .meta strong {{ color:#fff; font-weight:700; }}
        .meta p {{ color:rgba(255,255,255,.72); }}
        .side-links, .side-tabs, .summary-grid, .meta-strip, .toolbar, .buttons {{ display:flex; flex-wrap:wrap; gap:10px; }}
        .sidebar-section {{ margin-top:20px; }}
        .sidebar-label {{ margin-bottom:10px; color:rgba(255,255,255,.72); font-size:12px; font-weight:700; }}
        .side-nav-groups {{ display:grid; gap:0; width:100%; }}
        .side-nav-group {{ display:grid; gap:8px; width:100%; }}
        .side-nav-group + .side-nav-group {{ margin-top:14px; padding-top:14px; border-top:1px solid rgba(255,255,255,.08); }}
        .side-nav-group-title {{ color:rgba(255,255,255,.62); font-size:12px; font-weight:800; letter-spacing:0; }}
        .side-tabs {{ display:grid; gap:8px; }}
        .side-tab {{
            width:100%; display:flex; align-items:center; justify-content:space-between; gap:12px; border:1px solid rgba(255,255,255,.14);
            background:rgba(255,255,255,.06); color:#fff; border-radius:8px; padding:11px 12px; font-weight:800; cursor:pointer; text-align:left;
        }}
        .side-tab:hover {{ transform:translateY(-1px); border-color:rgba(255,255,255,.24); }}
        .side-tab.active {{ background:rgba(15,118,110,.34); border-color:rgba(153,246,228,.35); box-shadow:inset 0 0 0 1px rgba(153,246,228,.22); }}
        .side-tab-label {{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
        .side-tab-count {{ display:inline-flex; align-items:center; justify-content:center; min-width:36px; min-height:28px; padding:0 8px; border-radius:999px; background:rgba(255,255,255,.10); color:#d8e2e7; font-size:12px; font-weight:700; }}
        .side-links a {{
            flex:1 1 100%; display:inline-flex; align-items:center; justify-content:center; min-height:42px; color:#fff; text-decoration:none;
            border:1px solid rgba(255,255,255,.18); border-radius:8px; padding:0 12px; font-weight:800; background:rgba(255,255,255,.04);
        }}
        .side-links a:hover {{ background:rgba(255,255,255,.12); }}
        .empty-sidebar {{ padding:14px 12px; border-radius:8px; border:1px dashed rgba(255,255,255,.2); color:rgba(255,255,255,.72); font-size:13px; }}
        .content {{ padding:28px; min-width:0; display:grid; gap:18px; align-content:start; }}
        .hero {{
            display:grid; grid-template-columns:minmax(0,1.2fr) minmax(260px,.8fr); gap:18px; align-items:stretch;
            padding:24px; background:linear-gradient(155deg,var(--strong),var(--strong-2)); color:#fff; border-radius:8px; box-shadow:var(--shadow-md);
        }}
        .hero-copy {{ display:grid; gap:16px; }}
        .hero-kicker {{ color:rgba(255,255,255,.72); font-size:13px; font-weight:700; }}
        .hero h2 {{ font-size:clamp(28px,4vw,38px); line-height:1.06; }}
        .hero p {{ color:rgba(255,255,255,.76); max-width:64ch; }}
        .hero-score-card {{ padding:20px; border-radius:8px; border:1px solid rgba(255,255,255,.12); background:rgba(255,255,255,.06); display:grid; gap:14px; align-content:start; }}
        .score-top {{ display:flex; align-items:flex-end; justify-content:space-between; gap:12px; }}
        .score-label {{ color:rgba(255,255,255,.72); font-size:13px; font-weight:700; }}
        .score-level {{ display:inline-flex; align-items:center; justify-content:center; min-height:30px; padding:0 10px; border-radius:999px; font-size:12px; font-weight:800; }}
        .score-level-excellent {{ color:#bbf7d0; background:rgba(104,211,145,.16); }}
        .score-level-good {{ color:#99f6e4; background:rgba(79,209,197,.16); }}
        .score-level-warning {{ color:#fbd38d; background:rgba(246,173,85,.16); }}
        .score-level-danger {{ color:#fecaca; background:rgba(248,113,113,.16); }}
        .score {{ font-size:clamp(48px,7vw,72px); font-weight:900; line-height:.92; white-space:nowrap; font-variant-numeric:tabular-nums; }}
        .score-excellent {{ color:#68d391; }} .score-good {{ color:#4fd1c5; }} .score-warning {{ color:#f6ad55; }} .score-danger {{ color:#f87171; }}
        .score span {{ font-size:20px; color:rgba(255,255,255,.68); font-weight:700; }}
        .score-copy {{ color:rgba(255,255,255,.76); font-size:14px; }}
        .meter {{ height:10px; border-radius:999px; background:rgba(255,255,255,.12); overflow:hidden; }}
        .meter span {{ display:block; height:100%; width:{0 if score is None else max(0.0, min(100.0, float(score))):.1f}%; border-radius:inherit; background:linear-gradient(90deg,#68d391 0%,#f6ad55 60%,#f87171 100%); }}
        .meta-strip {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; }}
        .summary-strip {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
        .meta-card, .summary-card, .standard-card, .toolbar-card, .table-card {{
            padding:18px; border-radius:8px; border:1px solid var(--line); background:var(--surface); box-shadow:var(--shadow-sm);
        }}
        .meta-card {{ display:grid; gap:6px; }}
        .meta-label, .summary-label, .toolbar-label {{ color:var(--muted); font-size:12px; font-weight:700; }}
        .meta-value, .summary-value {{ font-size:24px; font-weight:800; line-height:1.1; font-variant-numeric:tabular-nums; }}
        .meta-note {{ color:var(--muted); font-size:13px; }}
        .summary-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
        .summary-card {{ display:grid; gap:8px; background:var(--surface-alt); box-shadow:none; }}
        .summary-value {{ font-size:20px; }}
        .score-explainer-section {{ display:grid; gap:14px; }}
        .entropy-score-explainer {{ display:grid; gap:14px; }}
        .entropy-score-formula {{
            display:grid; gap:6px; padding:16px 18px; border-radius:8px; border:1px solid rgba(15,118,110,.16);
            background:linear-gradient(180deg,rgba(15,118,110,.08),rgba(15,118,110,.03));
        }}
        .entropy-score-formula-kicker {{ color:var(--brand); font-size:12px; font-weight:800; }}
        .entropy-score-formula-line {{ color:var(--text); font-size:20px; line-height:1.35; font-weight:800; font-variant-numeric:tabular-nums; }}
        .entropy-score-formula-note {{ color:var(--muted); font-size:13px; line-height:1.55; }}
        .entropy-score-summary-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
        .entropy-score-summary-card {{
            display:grid; gap:6px; min-height:110px; padding:16px; border-radius:8px; border:1px solid var(--line);
            background:var(--surface); box-shadow:var(--shadow-sm);
        }}
        .entropy-score-summary-label {{ color:var(--muted); font-size:12px; font-weight:700; }}
        .entropy-score-summary-value {{ color:var(--text); font-size:22px; font-weight:800; line-height:1.25; overflow-wrap:anywhere; word-break:break-word; }}
        .entropy-score-summary-note {{ color:var(--muted); font-size:13px; line-height:1.5; }}
        .entropy-score-breakdown-head {{ display:grid; gap:4px; }}
        .entropy-score-breakdown-title {{ color:var(--text); font-size:15px; font-weight:800; }}
        .entropy-score-breakdown-desc {{ color:var(--muted); font-size:13px; line-height:1.55; }}
        .entropy-score-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }}
        .entropy-score-grid-compact {{ grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); }}
        .entropy-score-step {{
            display:grid; gap:12px; min-width:0; padding:16px; border-radius:8px; border:1px solid var(--line);
            background:var(--surface); box-shadow:var(--shadow-sm);
        }}
        .entropy-score-step-good, .entropy-score-step-excellent {{ border-color:rgba(21,128,61,.20); }}
        .entropy-score-step-warning {{ border-color:rgba(183,110,18,.24); }}
        .entropy-score-step-danger {{ border-color:rgba(194,65,12,.28); }}
        .entropy-score-step-top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }}
        .entropy-score-step-kicker {{ color:var(--muted); font-size:12px; font-weight:700; }}
        .entropy-score-step h4 {{ margin:4px 0 0; color:var(--text); font-size:18px; line-height:1.25; }}
        .entropy-score-step-status {{
            display:inline-flex; align-items:center; justify-content:center; min-height:28px; padding:0 10px; border-radius:999px;
            font-size:12px; font-weight:700; white-space:nowrap;
        }}
        .entropy-score-step-status-excellent, .entropy-score-step-status-good {{ color:var(--good); background:var(--good-soft); }}
        .entropy-score-step-status-warning {{ color:var(--warning); background:var(--warning-soft); }}
        .entropy-score-step-status-danger {{ color:var(--danger); background:var(--danger-soft); }}
        .entropy-score-step-value-row {{ display:grid; gap:6px; }}
        .entropy-score-step-value {{ color:var(--text); font-size:28px; line-height:1.05; font-weight:800; font-variant-numeric:tabular-nums; }}
        .entropy-score-step-meta {{ color:var(--muted); font-size:13px; line-height:1.5; }}
        .entropy-score-step-block {{ display:grid; gap:4px; padding-top:10px; border-top:1px solid var(--line); }}
        .entropy-score-step-block span {{ color:var(--muted); font-size:12px; font-weight:700; }}
        .entropy-score-step-block p {{ margin:0; color:var(--text); font-size:14px; line-height:1.6; }}
        .entropy-score-chip-row {{ display:flex; flex-wrap:wrap; gap:8px; }}
        .entropy-score-chip {{
            display:inline-flex; align-items:center; min-height:28px; padding:0 10px; border-radius:999px; border:1px solid var(--line);
            background:var(--surface-alt); color:var(--muted); font-size:12px; font-weight:700;
        }}
        .entropy-score-empty {{
            padding:14px 16px; border-radius:8px; border:1px dashed var(--line); color:var(--muted); font-size:13px; background:var(--surface);
        }}
        .standard-card {{ display:grid; gap:10px; }}
        .section-head {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:14px; }}
        .section-head h3 {{ font-size:22px; line-height:1.15; }}
        .section-desc {{ color:var(--muted); font-size:14px; }}
        .standard-list {{ margin:0; padding-left:20px; display:grid; gap:8px; color:var(--text); }}
        .toolbar-card {{ display:grid; gap:14px; }}
        .toolbar-top {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
        .toolbar-legend {{ display:flex; flex-wrap:wrap; gap:8px; }}
        .legend-pill {{
            display:inline-flex; align-items:center; justify-content:center; min-height:28px; padding:0 10px; border-radius:999px;
            border:1px solid var(--line); background:var(--surface-alt); color:var(--muted); font-size:12px; font-weight:700;
        }}
        .legend-pill-high {{ color:var(--danger); background:var(--danger-soft); border-color:transparent; }}
        .legend-pill-medium {{ color:var(--warning); background:var(--warning-soft); border-color:transparent; }}
        .legend-pill-typed {{ color:var(--brand); background:var(--brand-soft); border-color:transparent; }}
        .toolbar-controls {{ display:grid; grid-template-columns:minmax(0,1.4fr) 180px auto; gap:12px; align-items:end; }}
        .toolbar-field {{ display:grid; gap:8px; }}
        .toolbar input, .toolbar select {{
            min-height:44px; border:1px solid var(--line); border-radius:8px; padding:0 12px; font:inherit; background:var(--surface); color:var(--text);
        }}
        .buttons {{ gap:10px; }}
        button, .button-link {{
            display:inline-flex; align-items:center; justify-content:center; min-height:44px; border:1px solid var(--line); background:var(--surface);
            color:var(--text); border-radius:8px; padding:0 14px; font:inherit; font-weight:800; cursor:pointer; text-decoration:none;
        }}
        button:hover, .button-link:hover {{ transform:translateY(-1px); border-color:var(--line-strong); box-shadow:var(--shadow-sm); }}
        .button-primary {{ background:var(--brand); color:#fff; border-color:var(--brand); }}
        .button-primary:hover {{ background:var(--brand-ink); border-color:var(--brand-ink); }}
        .table-card {{ overflow:hidden; }}
        .table-head {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; padding-bottom:14px; border-bottom:1px solid var(--line); }}
        .table-head-copy {{ display:grid; gap:6px; min-width:0; flex:1; }}
        .table-head h3 {{ font-size:20px; }}
        .table-desc {{ color:var(--muted); font-size:13px; line-height:1.6; max-width:none; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
        .count {{ color:var(--muted); font-size:13px; }}
        .table-scroll {{ overflow:auto; max-height:calc(100vh - 300px); margin-top:2px; }}
        table {{ width:100%; min-width:960px; border-collapse:separate; border-spacing:0; table-layout:fixed; }}
        th, td {{ text-align:left; vertical-align:top; padding:12px 14px; border-bottom:1px solid var(--line); font-size:13px; }}
        th {{ position:sticky; top:0; background:var(--surface-alt); color:var(--muted); cursor:pointer; z-index:1; font-weight:800; }}
        th {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
        td {{ color:var(--text); word-break:normal; overflow-wrap:anywhere; }}
        .detail-table-score_breakdown {{ min-width:1380px; }}
        .detail-table-score_breakdown th:nth-child(2), .detail-table-score_breakdown td:nth-child(2) {{ width:360px; }}
        .detail-table-score_breakdown th:nth-child(4), .detail-table-score_breakdown td:nth-child(4) {{ width:300px; }}
        .detail-table-metrics {{ min-width:1260px; }}
        .detail-table-metrics th:nth-child(1), .detail-table-metrics td:nth-child(1) {{ width:150px; }}
        .detail-table-metrics th:nth-child(2), .detail-table-metrics td:nth-child(2) {{ width:190px; }}
        .detail-table-metrics th:nth-child(3), .detail-table-metrics td:nth-child(3) {{ width:240px; }}
        .detail-table-metrics th:nth-child(4), .detail-table-metrics td:nth-child(4) {{ width:150px; }}
        .detail-table-state_scattered_value_issues {{ min-width:1320px; }}
        .detail-table-state_scattered_value_issues th:nth-child(1), .detail-table-state_scattered_value_issues td:nth-child(1) {{ width:210px; }}
        .detail-table-state_scattered_value_issues th:nth-child(2), .detail-table-state_scattered_value_issues td:nth-child(2) {{ width:92px; }}
        .detail-table-state_scattered_value_issues th:nth-child(3), .detail-table-state_scattered_value_issues td:nth-child(3),
        .detail-table-state_scattered_value_issues th:nth-child(4), .detail-table-state_scattered_value_issues td:nth-child(4),
        .detail-table-state_scattered_value_issues th:nth-child(5), .detail-table-state_scattered_value_issues td:nth-child(5),
        .detail-table-state_scattered_value_issues th:nth-child(6), .detail-table-state_scattered_value_issues td:nth-child(6) {{ width:92px; }}
        .detail-table-state_scattered_value_locations {{ min-width:1520px; }}
        .detail-table-state_scattered_value_locations th:nth-child(1), .detail-table-state_scattered_value_locations td:nth-child(1) {{ width:190px; }}
        .detail-table-state_scattered_value_locations th:nth-child(2), .detail-table-state_scattered_value_locations td:nth-child(2) {{ width:92px; }}
        .detail-table-state_scattered_value_locations th:nth-child(3), .detail-table-state_scattered_value_locations td:nth-child(3) {{ width:90px; }}
        .detail-table-state_scattered_value_locations th:nth-child(4), .detail-table-state_scattered_value_locations td:nth-child(4) {{ width:150px; }}
        .detail-table-state_scattered_value_locations th:nth-child(5), .detail-table-state_scattered_value_locations td:nth-child(5) {{ width:430px; }}
        .detail-table-state_scattered_value_locations th:nth-child(6), .detail-table-state_scattered_value_locations td:nth-child(6) {{ width:72px; }}
        tr.row-risk-high td {{ background:rgba(194,65,12,.06); }}
        tr.row-risk-medium td {{ background:rgba(183,110,18,.06); }}
        tr.row-risk-high td:first-child {{ box-shadow:inset 3px 0 0 var(--danger); }}
        tr.row-risk-medium td:first-child {{ box-shadow:inset 3px 0 0 var(--warning); }}
        .cell-badge, .cell-chip, .cell-bool {{
            display:inline-flex; align-items:center; justify-content:center; min-height:26px; padding:0 9px; border-radius:999px; font-size:12px; font-weight:700;
        }}
        .cell-badge-high {{ color:var(--danger); background:var(--danger-soft); }}
        .cell-badge-medium {{ color:var(--warning); background:var(--warning-soft); }}
        .cell-badge-low, .cell-badge-good {{ color:var(--good); background:var(--good-soft); }}
        .cell-chip {{ color:var(--brand); background:var(--brand-soft); }}
        .cell-bool-yes {{ color:var(--good); background:var(--good-soft); }}
        .cell-bool-no {{ color:var(--danger); background:var(--danger-soft); }}
        .cell-num {{ font-variant-numeric:tabular-nums; font-weight:800; }}
        .cell-num-high span {{ color:var(--danger); }}
        .cell-num-medium span {{ color:var(--warning); }}
        .path {{ font-family:Consolas,"Courier New",monospace; color:var(--text); font-size:12px; }}
        .cell-path {{ display:block; white-space:normal; word-break:normal; overflow-wrap:anywhere; }}
        .cell-copy {{
            max-width:44ch; color:var(--text); line-height:1.45; display:-webkit-box;
            -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
        }}
        .cell-one-line {{
            display:block; max-width:100%; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
        }}
        .cell-wrap {{
            display:block; max-width:100%; white-space:normal; word-break:normal; overflow-wrap:anywhere; line-height:1.55;
        }}
        .sample-list {{ display:flex; flex-direction:column; gap:5px; max-width:48ch; }}
        .sample-pill {{
            display:block; padding:4px 7px; border-radius:6px; background:rgba(148,163,184,.10);
            color:var(--text); font-family:Consolas,"Courier New",monospace; font-size:12px;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
        }}
        .sample-more {{ color:var(--muted); font-size:12px; }}
        .pager {{ display:flex; align-items:center; justify-content:space-between; gap:10px; padding-top:14px; }}
        .pager-meta {{ color:var(--muted); font-size:13px; }}
        .pager-actions {{ display:flex; gap:10px; }}
        .empty {{ padding:36px 20px; color:var(--muted); text-align:center; }}
        .helper-note {{ color:var(--muted); font-size:13px; }}
        @media (max-width:1100px) {{
            .page {{ grid-template-columns:1fr; }}
            .sidebar {{ position:relative; height:auto; }}
            .hero {{ grid-template-columns:1fr; }}
            .toolbar-controls {{ grid-template-columns:1fr; }}
            .table-scroll {{ max-height:none; }}
        }}
        @media (max-width:720px) {{
            .content {{ padding:16px; gap:14px; }}
            .hero, .meta-card, .summary-card, .standard-card, .toolbar-card, .table-card {{ padding:16px; }}
            .meta-strip, .summary-grid {{ grid-template-columns:1fr; }}
            .buttons button, .buttons .button-link, .side-links a {{ width:100%; }}
            .pager {{ flex-direction:column; align-items:stretch; }}
            .pager-actions {{ width:100%; }}
            .pager-actions button {{ flex:1 1 0; }}
        }}
        @media (prefers-reduced-motion: reduce) {{ * {{ transition:none !important; animation:none !important; }} }}
    </style>
</head>
<body>
    <div class="page">
        <aside class="sidebar">
            <div class="brand">代码本体熵详情</div>
            <h1>{_svg_icon(key)} {_esc(label)}</h1>
            <div class="meta">
                <div><strong>周期：</strong>{_esc(snapshot.period)}</div>
                <div><strong>当前级别：</strong>{_esc(_level_label(level))}</div>
                <p>先看规则怎么算，再看问题和代码定位；原始指标仅排查时使用。</p>
            </div>
            <div class="side-links">
                <a href="../entropy-dashboard.html#code-entropy">返回仪表盘</a>
                <a href="{_esc(key)}.json" download>导出完整 JSON</a>
            </div>
            <div class="sidebar-section">
                <div class="side-nav-groups">{table_nav}</div>
            </div>
        </aside>
        <main class="content">
            <section class="hero">
                <div class="hero-copy">
                    <div>
                        <h2>{_esc(label)}完整详情</h2>
                        <p>{_esc(hero_summary)}</p>
                    </div>
                </div>
                <div class="hero-score-card">
                    <div class="score-top">
                        <div class="score-label">当前风险熵分</div>
                        <div class="score-level score-level-{status}">{_esc(_level_label(level))}</div>
                    </div>
                    <div class="score score-{_entropy_level(score, payload)}">{_esc(_fmt_compact(score))}<span>/100</span></div>
                    <div class="meter" aria-hidden="true"><span></span></div>
                </div>
            </section>

            <section class="summary-strip">
                {summary_cards_html}
            </section>

            <section class="toolbar-card">
                <div class="toolbar-top">
                    <div>
                        <h3>筛选与导出</h3>
                        <div class="section-desc">搜索只作用于当前表格；导出也只导出当前筛选结果。</div>
                    </div>
                </div>
                <div class="toolbar toolbar-controls">
                    <label class="toolbar-field">
                        <input id="search" type="search" placeholder="搜索文件、类名、方法、术语、异常类型..." aria-label="关键词搜索" />
                    </label>
                    <label class="toolbar-field">
                        <select id="page-size" aria-label="每页条数"><option value="50">每页 50</option><option value="100" selected>每页 100</option><option value="200">每页 200</option></select>
                    </label>
                    <div class="buttons">
                        <button type="button" class="button-primary" onclick="exportFiltered('csv')">导出筛选 CSV</button>
                        <button type="button" onclick="exportFiltered('json')">导出筛选 JSON</button>
                    </div>
                </div>
            </section>

            <section class="table-card">
                <div class="table-head">
                    <div class="table-head-copy">
                        <h3 id="table-title">明细</h3>
                        <div id="table-desc" class="table-desc">当前表格说明</div>
                    </div>
                    <div id="table-count" class="count"></div>
                </div>
                <div class="table-scroll"><table id="detail-table"></table><div id="empty" class="empty" hidden>没有匹配的数据</div></div>
                <div class="pager"><span class="pager-meta" id="page-info"></span><div class="pager-actions"><button type="button" onclick="prevPage()">上一页</button><button type="button" onclick="nextPage()">下一页</button></div></div>
            </section>
        </main>
    </div>
    <script>
        const DETAIL_PAYLOAD = {_json_script(payload)};
        const TABLES = DETAIL_PAYLOAD.tables || [];
        const TABLE_META = Object.fromEntries(TABLES.map(table => [table.id, {{label: table.label || '', description: table.description || ''}}]));
        let currentTableId = TABLES[0] ? TABLES[0].id : '';
        let currentPage = 1;
        let sortColumn = '';
        let sortDirection = 1;
        const labels = {{"label":"中文指标","field":"原始字段","value":"值","description":"中文说明","metric_group":"所属规则","calculation_description":"计算描述","calculation":"计算口径","path":"路径","file":"文件","dir":"目录","dir_rank":"目录排名","dir_file_count":"目录文件数","files":"文件数","lines":"行数","method":"方法","start_line":"起始行","level":"等级","count":"数量","issue_count":"问题数","type":"类型","content":"内容","line":"行号","column":"列号","category_label":"问题分类","module":"Checkstyle规则","module_meaning":"中文含义","message":"规则提示","has_owner":"有责任人","target_type":"目标类型","visibility":"可见性","reason":"命中原因","branch_count":"分支数","nesting_depth":"嵌套深度","issue_type":"问题类型","target":"检查项","current":"当前情况","expected":"期望标准","topic":"主题","matched_aliases":"命中别名","required_aliases":"主题别名","chars":"字符数","headings":"标题数","code_blocks":"代码块数","tables":"表格行数","images":"图片数","links":"链接数","name":"名称","classes":"涉及类","sample_edges":"依赖边样例","size":"规模","id":"编号","pattern":"模式","format":"格式","strategy":"处理策略","contract":"错误契约","exception_type":"异常类型","standard":"标准","variant_count":"变体数量","matched_hits":"总命中数","standard_hits":"标准命中数","nonstandard_hits":"非标准命中数","nonstandard_ratio":"非标准命中占比","usage_count":"使用次数","variants":"变体","sample_files":"样例文件","term":"术语","variant":"变体","class_name":"类名","source":"来源","kind":"类型","sample_locations":"样例代码位置","cluster_id":"重复簇 ID","carrier_count":"状态承载体数","redundant_count":"冗余承载体数","shared_items":"共享状态项","carrier_names":"涉及状态承载体","items":"状态项","focus":"修复重点","summary":"问题摘要","problem_count":"问题对象数","problem_unit":"计数对象","count_summary":"计数说明","current_value":"当前规则值","entry_status":"入口文档","rule":"规则","rule_cn":"规则说明","status":"状态","pending_reason":"待配置原因","rule_status":"计分状态","category":"规则类型","enabled":"启用","weight":"权重","metric":"指标字段","raw_value":"原始值","condition":"命中条件","severity":"风险系数","contribution":"贡献分","max_contribution":"最大贡献分","skipped":"是否跳过","occurrence_count":"总次数","scored_occurrence_count":"计分次数","candidate_occurrence_count":"疑似次数","file_count":"文件数","has_carrier_item":"已匹配承载体","context":"代码上下文","confidence":"类型","scored":"参与计分","common":"命中 common","utility":"命中 util","common_match_source_applied":"common 命中来源","utility_match_source_applied":"util 命中来源","common_match_values_applied":"common 命中值","utility_match_values_applied":"util 命中值","match_source_applied":"命中来源","match_values_applied":"命中值"}};
        const columnHelps = {{"label":"规则或指标的中文名称。","rule":"语义规则名称。","metric_group":"该底层指标归属的规则或排查类别。","description":"这个底层指标在当前规则中的含义和用途。","calculation":"本次扫描把哪些底层数量代入公式得到当前规则值。","field":"评分引擎输出的原始字段名。","value":"本次扫描得到的字段值。","metric":"评分卡读取的指标字段。","raw_value":"本次扫描代入评分规则的原始值。","condition":"原始值命中的评分区间或条件。","severity":"命中条件对应的风险系数，越高风险越大。","contribution":"这条规则折算后拉高了多少总分。","max_contribution":"这条规则在当前权重下最多能贡献多少分。","status":"本次命中的风险状态。","weight":"这条规则在当前维度评分中的权重。","current_value":"规则本次计分使用的展示值。","entry_status":"根目录入口 README 是否存在。","count_summary":"这条规则当前统计对象的简要说明。","problem_count":"当前规则识别出的治理对象数量。","problem_unit":"问题对象数量对应的单位。","summary":"当前扫描结果的自然语言摘要。","focus":"建议优先处理的治理方向。","term":"候选术语或标准术语。","sample_locations":"样例代码位置，用于快速回查。","file":"文件路径。","line":"代码行号。","column":"Checkstyle 报告的问题列号。","category_label":"该 Checkstyle 明细归属的风格熵大类。","issue_count":"该风格熵大类下命中的问题数量。","module":"触发问题的 Checkstyle 具体规则。","module_meaning":"该 Checkstyle 规则的中文含义。","message":"Checkstyle 返回的原始问题提示。","class_name":"命中的类名。","source":"术语或问题来源。","path":"命中的 Java 文件路径。","dir":"该文件所在目录。","dir_rank":"该目录在按直接 Java 文件数排序后的名次。","dir_file_count":"该文件所在目录直接包含的 Java 文件数。","files":"该目录下直接包含的 Java 文件数。","lines":"该目录或文件的行数；大文件/大类负担中为物理总行数。","issue_type":"项目文档或代码问题的类型。","target":"当前检查的对象。","current":"本次扫描得到的当前情况。","expected":"规则期望达到的标准。","topic":"项目说明文档需要覆盖的通用主题。","matched_aliases":"当前文档中命中的主题别名。","required_aliases":"该主题配置的可命中别名。","chars":"文档正文字符数。","headings":"文档标题数量。","code_blocks":"文档代码块数量。","tables":"Markdown 表格行数量。","images":"文档图片引用数量。","links":"文档链接数量。","sample_files":"该目录下的样例 Java 文件，用于快速判断目录内容。","common":"是否命中 common/shared 类共享承载目录规则。","utility":"是否命中 util/utils 类工具目录规则。","common_match_source_applied":"common/shared 命中的来源，prefix 表示配置路径前缀命中，alias 表示目录名别名命中。","utility_match_source_applied":"util/utils 命中的来源，prefix 表示配置路径前缀命中，alias 表示目录名别名命中。","common_match_values_applied":"触发 common/shared 命中的配置值或别名。","utility_match_values_applied":"触发 util/utils 命中的配置值或别名。","match_source_applied":"目录命中规则的来源。","match_values_applied":"触发目录命中的配置值或别名。"}};
        const valueMaps = {{
            status: {{danger:'高风险', warning:'关注', good:'良好', excellent:'优秀', notice:'提示', pass:'通过', fail:'未通过', scored:'已计分', pending_config:'待配置', missing:'缺数'}},
            rule_status: {{scored:'已计分', pending_config:'待配置', missing:'缺数'}},
            category: {{custom:'定制规则', generic:'通用规则', general:'通用规则'}},
            kind: {{enum:'枚举', class:'常量类'}},
            source: {{file_stem:'文件名', class_name:'类名'}},
            common: {{true:'是', false:'否'}},
            utility: {{true:'是', false:'否'}},
            common_match_source_applied: {{prefix:'前缀命中', alias:'别名命中'}},
            utility_match_source_applied: {{prefix:'前缀命中', alias:'别名命中'}},
            match_source_applied: {{prefix:'前缀命中', alias:'别名命中'}},
            confidence: {{high:'计分', candidate:'疑似'}},
            strategy: {{rethrow_specific_exception:'重新抛出具体异常', rethrow_generic_exception:'重新抛出泛化异常', return_wrapped_error:'返回包装错误', return_null:'返回 null', return_error_code:'返回错误码', return_other:'返回其他值', mark_failure_state:'标记失败状态', log_only:'只打日志', empty_swallow:'空 catch', swallow_other:'未处理失败'}},
            contract: {{wrapped_error_response:'包装错误响应', return_null:'返回 null', return_error_code:'返回错误码', return_string:'返回字符串', return_boolean:'返回布尔值', throw_exception:'直接抛异常'}},
            metric: {{"naming_inconsistency_ratio":"命名非标准占比","term_gap_ratio":"术语缺口比例","state_duplicate_ratio":"状态承载体重复比","state_value_scatter_ratio":"状态值散落比例","shared_bucket_ratio":"共享承载目录占比","max_dir_files_ratio":"最大目录文件占比","oversized_dir_ratio":"超大目录数量占比","top_n_dir_concentration":"前 N 大目录集中度","avg_files_per_dir":"平均目录文件数","failure_strategy_split_ratio":"失败处理策略分裂比例","swallowed_exception_ratio":"吞异常比例","error_return_contract_mix_ratio":"返回错误契约混用比例","generic_exception_throw_ratio":"泛化异常抛出比例","business_exception_convergence_gap":"业务异常未收敛比例","error_consistency":"旧口径错误处理一致性","return_consistency":"旧口径返回契约一致性","exception_type_density_per_k_files":"旧口径异常类型密度","todo_density_per_k_files":"债务标记密度","unowned_debt_ratio":"未归属债务比例","public_knowledge_gap_ratio":"公共知识缺口比例","complex_method_ratio":"复杂方法比例","large_file_class_burden_ratio":"大文件/大类负担比例","project_doc_gap_ratio":"项目文档缺口比例","todo_owner_ratio":"债务责任人覆盖率","javadoc_gap_ratio":"JavaDoc 缺口比例","avg_method_lines":"平均方法行数","style_formatting_density":"格式排版问题密度","style_naming_density":"命名规范问题密度","style_import_density":"导入规范问题密度","style_declaration_density":"注解与声明规范问题密度","style_code_smell_density":"编码坏味道问题密度","style_complexity_density":"复杂度与规模问题密度"}}
        }};
        function getTable() {{ return TABLES.find(t => t.id === currentTableId) || TABLES[0] || {{columns: [], rows: [], label: '明细'}}; }}
        function labelOf(column) {{ return labels[column] || column; }}
        function helpOf(column) {{ return columnHelps[column] || labelOf(column); }}
        function toNumber(value) {{
            if (value === null || value === undefined || value === '') return null;
            const match = String(value).replace(/,/g, '').match(/-?\\d+(?:\\.\\d+)?/);
            return match ? Number(match[0]) : null;
        }}
        function normalizeRisk(value) {{
            const text = String(value || '').toLowerCase();
            if (['danger', 'high', 'critical', '高风险', '高'].includes(text)) return 'high';
            if (['warning', 'medium', '关注', '中'].includes(text)) return 'medium';
            if (['good', 'excellent', 'low', '良好', '优秀', '低'].includes(text)) return 'good';
            return '';
        }}
        function formatValue(value) {{
            if (value === null || value === undefined) return '';
            if (Array.isArray(value)) {{ const preview = value.slice(0, 5).map(formatValue).join('；'); return value.length > 5 ? preview + ' ... 共 ' + value.length + ' 项' : preview; }}
            if (typeof value === 'object') {{ if (value.file && value.name) return value.name + '（' + value.file + '）'; if (value.from && value.to) return value.from + ' → ' + value.to; return JSON.stringify(value); }}
            if (typeof value === 'boolean') return value ? '是' : '否';
            return String(value);
        }}
        function formatValueByColumn(column, value) {{
            const col = String(column || '');
            const text = formatValue(value);
            if (valueMaps[col] && Object.prototype.hasOwnProperty.call(valueMaps[col], text)) return valueMaps[col][text];
            if (col === 'metric' && labels[text]) return labels[text];
            return text;
        }}
        function inferRowRisk(table, row) {{
            const direct = normalizeRisk(row.level || row.severity);
            if (direct) return direct;
            const lines = toNumber(row.lines);
            if (lines !== null) {{
                if (lines >= 1000) return 'high';
                if (lines >= 600) return 'medium';
            }}
            const count = toNumber(row.count);
            if (table.id === 'todo_top_files' && count !== null) {{
                if (count >= 5) return 'high';
                if (count >= 3) return 'medium';
            }}
            if (table.id === 'todo_items' && row.has_owner === false) return 'medium';
            if (table.id === 'metrics') {{
                const field = String(row.field || '').toLowerCase();
                const valueNum = toNumber(row.value);
                if (valueNum !== null && /coverage|consistency|density|ratio/.test(field)) {{
                    if (valueNum < 60) return 'high';
                    if (valueNum < 80) return 'medium';
                }}
                if (valueNum !== null && /todo_count|large_methods|large_classes|missing_javadoc|undefined_terms|common_files|nonstandard/.test(field)) {{
                    if (valueNum >= 500) return 'high';
                    if (valueNum >= 100) return 'medium';
                }}
            }}
            return '';
        }}
        function cellKind(table, column, value) {{
            const col = String(column || '').toLowerCase();
            if (col.includes('file') || col.includes('dir') || col.includes('path')) return 'path';
            if (col === 'level' || col === 'severity') return 'level';
            if (typeof value === 'boolean' || col.startsWith('has_')) return 'bool';
            if (col === 'type' || col === 'pattern' || col === 'format' || col.endsWith('style') || col === 'status' || col === 'confidence') return 'tag';
            if (col === 'count' || col === 'line' || col === 'lines' || col.includes('count') || col.includes('ratio') || col.includes('coverage') || col.includes('consistency') || col.includes('density') || col.includes('size') || col.includes('usage')) return 'number';
            if (col === 'content' || col.includes('variant') || col === 'classes' || col === 'sample_edges' || col === 'summary' || col === 'focus' || col === 'sample_locations') return 'copy';
            return 'text';
        }}
        function renderCell(table, column, value, rowRisk) {{
            const rawText = formatValueByColumn(column, value);
            const formatted = escapeHtml(rawText);
            const title = ' title="' + formatted + '"';
            const tableId = String(table && table.id || '');
            const col = String(column || '');
            const kind = cellKind(table, column, value);
            if (tableId === 'semantic_rule_overview' && ['count_summary', 'summary', 'focus'].includes(col)) {{
                return '<td' + title + '><div class="cell-wrap">' + formatted + '</div></td>';
            }}
            if (tableId === 'score_breakdown' && col === 'calculation') {{
                return '<td' + title + '><div class="cell-wrap">' + formatted + '</div></td>';
            }}
            if (tableId === 'metrics' && col === 'metric_group') {{
                return '<td' + title + '><span class="cell-chip">' + formatted + '</span></td>';
            }}
            if (tableId === 'metrics' && col === 'description') {{
                return '<td' + title + '><div class="cell-wrap">' + formatted + '</div></td>';
            }}
            if (tableId === 'state_scattered_value_issues' && col === 'value') {{
                return '<td' + title + '><span class="cell-one-line">' + formatted + '</span></td>';
            }}
            if (String(column || '') === 'sample_locations') {{
                const raw = formatValue(value);
                const items = raw.split(/\\s+\\|\\s+/).filter(Boolean);
                if (items.length) {{
                    const preview = items.slice(0, 2).map(item => '<span class="sample-pill" title="' + escapeHtml(item) + '">' + escapeHtml(shortSample(item)) + '</span>').join('');
                    const more = items.length > 2 ? '<span class="sample-more">另有 ' + (items.length - 2) + ' 处，见代码定位表</span>' : '';
                    return '<td title="' + escapeHtml(raw) + '"><div class="sample-list">' + preview + more + '</div></td>';
                }}
            }}
            if (kind === 'bool') return '<td' + title + '><span class="cell-bool ' + (value ? 'cell-bool-yes' : 'cell-bool-no') + '">' + formatted + '</span></td>';
            if (kind === 'level') {{
                const tone = normalizeRisk(formatValueByColumn(column, value)) || normalizeRisk(value) || rowRisk || 'good';
                return '<td' + title + '><span class="cell-badge cell-badge-' + tone + '">' + formatted + '</span></td>';
            }}
            if (kind === 'tag') return '<td' + title + '><span class="cell-chip">' + formatted + '</span></td>';
            if (kind === 'number') return '<td' + title + ' class="cell-num ' + (rowRisk ? 'cell-num-' + rowRisk : '') + '"><span>' + formatted + '</span></td>';
            if (kind === 'path') return '<td' + title + ' class="path"><span class="cell-path">' + formatted + '</span></td>';
            if (kind === 'copy') return '<td' + title + '><div class="cell-copy">' + formatted + '</div></td>';
            return '<td' + title + '><span class="cell-one-line">' + formatted + '</span></td>';
        }}
        function shortSample(value) {{
            const text = String(value || '');
            const match = text.match(/([^\\/\\\\]+\\.java:\\d+)(?:\\s*\\(([^)]+)\\))?/);
            if (match) return match[1] + (match[2] ? ' (' + match[2] + ')' : '');
            const parts = text.split(/[\\/\\\\]/);
            return parts.slice(-2).join('/');
        }}
        function filteredRows() {{
            const table = getTable();
            const query = document.getElementById('search').value.trim().toLowerCase();
            let rows = table.rows || [];
            if (query) rows = rows.filter(row => JSON.stringify(row).toLowerCase().includes(query));
            if (sortColumn) rows = [...rows].sort((a, b) => formatValueByColumn(sortColumn, a[sortColumn]).localeCompare(formatValueByColumn(sortColumn, b[sortColumn]), 'zh-Hans', {{numeric:true}}) * sortDirection);
            return rows;
        }}
        function renderTable() {{
            const table = getTable();
            const rows = filteredRows();
            const pageSize = Number(document.getElementById('page-size').value || 100);
            const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
            currentPage = Math.min(Math.max(1, currentPage), pageCount);
            const pageRows = rows.slice((currentPage - 1) * pageSize, currentPage * pageSize);
            document.getElementById('table-title').textContent = table.label || '明细';
            const tableDescEl = document.getElementById('table-desc');
            if (tableDescEl) tableDescEl.textContent = (TABLE_META[table.id] && TABLE_META[table.id].description) || '当前表格说明';
            const displayCount = Number(table.display_count || ((table.rows || []).length) || 0);
            const totalCount = Number(table.total_count || displayCount || 0);
            const tableCountEl = document.getElementById('table-count');
            if (tableCountEl) {{
                tableCountEl.textContent = totalCount === displayCount ? ('总数 ' + totalCount + ' 条') : ('当前展示 ' + displayCount + ' / 总数 ' + totalCount + ' 条');
            }}
            document.getElementById('page-info').textContent = '第 ' + currentPage + ' / ' + pageCount + ' 页';
            document.querySelectorAll('.side-tab').forEach(btn => btn.classList.toggle('active', btn.dataset.table === currentTableId));
            const el = document.getElementById('detail-table');
            el.className = 'detail-table detail-table-' + String(table.id || 'details').replace(/[^a-zA-Z0-9_-]/g, '-');
            const empty = document.getElementById('empty');
            if (!pageRows.length) {{ el.innerHTML = ''; empty.hidden = false; return; }}
            empty.hidden = true;
            const columns = table.columns || Object.keys(pageRows[0] || {{}});
            const head = '<thead><tr>' + columns.map(col => '<th title="' + escapeHtml(helpOf(col)) + '" onclick="sortBy(\\'' + col + '\\')">' + labelOf(col) + '</th>').join('') + '</tr></thead>';
            const body = '<tbody>' + pageRows.map(row => {{
                const rowRisk = inferRowRisk(table, row);
                return '<tr class="' + (rowRisk ? 'row-risk-' + rowRisk : '') + '">' + columns.map(col => renderCell(table, col, row[col], rowRisk)).join('') + '</tr>';
            }}).join('') + '</tbody>';
            el.innerHTML = head + body;
        }}
        function escapeHtml(value) {{ return String(value).replace(/[&<>\"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}}[ch])); }}
        function setTable(id) {{ currentTableId = id; currentPage = 1; sortColumn = ''; renderTable(); }}
        function sortBy(column) {{ sortDirection = sortColumn === column ? -sortDirection : 1; sortColumn = column; renderTable(); }}
        function prevPage() {{ currentPage -= 1; renderTable(); }}
        function nextPage() {{ currentPage += 1; renderTable(); }}
        function exportFiltered(type) {{
            const table = getTable();
            const rows = filteredRows();
            let content, mime, ext;
            if (type === 'json') {{ content = JSON.stringify({{table: table.label, rows}}, null, 2); mime = 'application/json'; ext = 'json'; }}
            else {{ const columns = table.columns || Object.keys(rows[0] || {{}}); const csvRows = [columns.map(labelOf).join(',')].concat(rows.map(row => columns.map(col => '\"' + formatValueByColumn(col, row[col]).replace(/\"/g, '\"\"') + '\"').join(','))); content = '\\ufeff' + csvRows.join('\\n'); mime = 'text/csv'; ext = 'csv'; }}
            const blob = new Blob([content], {{type: mime + ';charset=utf-8'}});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = '{_esc(key)}-' + (table.id || 'details') + '-filtered.' + ext; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
        }}
        document.querySelectorAll('.side-tab').forEach(btn => btn.addEventListener('click', () => setTable(btn.dataset.table)));
        document.getElementById('search').addEventListener('input', () => {{ currentPage = 1; renderTable(); }});
        document.getElementById('page-size').addEventListener('change', () => {{ currentPage = 1; renderTable(); }});
        renderTable();
    </script>
</body>
</html>'''


def _render_code_entropy_detail_page_relayout_experiment(snapshot: ScoredSnapshot, key: str, payload: dict[str, object]) -> str:
    return _render_code_entropy_detail_page(snapshot, key, payload)


