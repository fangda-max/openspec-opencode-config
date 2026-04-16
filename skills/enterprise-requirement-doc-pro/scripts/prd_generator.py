#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRD 生成器核心类"""

import sys
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'universal-llm-client' / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent))

# 强制重新加载模块
import read_all_docs
importlib.reload(read_all_docs)
from read_all_docs import read_all_documents

from llm_client import UniversalLLMClient
from config_utils import load_config_with_variables
from generate_docx import parse_markdown_to_docx


class PRDGenerator:
    def __init__(self, config_path=None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / 'config.json'
        self.config = load_config_with_variables(config_path)
        self.llm_client = UniversalLLMClient(self.config['llm'])
        self.prompts_dir = Path(__file__).parent.parent / 'prompts'
        self.templates_dir = Path(__file__).parent.parent / 'templates'
        print("[OK] PRD 生成器初始化成功")

    def load_prompt(self, name):
        with open(self.prompts_dir / f"{name}.txt", 'r', encoding='utf-8') as f:
            return f.read()

    def load_template(self, name):
        with open(self.templates_dir / f"{name}.md", 'r', encoding='utf-8') as f:
            return f.read()

    def generate(self, materials_dir, output_dir=None):
        if output_dir is None:
            output_dir = materials_dir
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n开始生成 PRD 文档")
        print(f"材料目录: {materials_dir}")

        try:
            # Phase 1
            print("\n[Phase 1] 读取材料...")
            materials = read_all_documents(str(materials_dir))

            # Phase 2
            print("[Phase 2] 构建事实底稿...")
            prompt = self.load_prompt("phase2_fact_base")
            materials_summary = "\n\n".join([f"## {m['filename']}\n\n{m['content'][:2000]}..." for m in materials])
            fact_base = self.llm_client.call(prompt.format(materials=materials_summary))

            # Phase 3
            print("[Phase 3] 生成中间稿...")
            prompt = self.load_prompt("phase3_delta")
            template = self.load_template("delta-template")
            delta_doc = self.llm_client.call(prompt.format(fact_base=fact_base, template=template))

            delta_path = output_dir / "01-需求新增优化改造点.md"
            with open(delta_path, 'w', encoding='utf-8') as f:
                f.write(delta_doc)

            # Phase 3.5
            print("[Phase 3.5] 深度分析...")
            prompt = self.load_prompt("phase3.5_deep_analysis")
            guide = self.load_template("deep-analysis-prompts")
            analysis = self.llm_client.call(prompt.format(delta_doc=delta_doc, analysis_guide=guide))

            # Phase 4
            print("[Phase 4] 起草正式文档...")
            prompt = self.load_prompt("phase4_formal_doc")
            doc_template = self.load_template("document-template")
            ac_guide = self.load_template("ac-writing-guide")
            formal_doc = self.llm_client.call(prompt.format(delta_doc=delta_doc, analysis_result=analysis, template=doc_template, ac_guide=ac_guide))

            # 清理 LLM 输出的 <think> 标签
            import re
            formal_doc = re.sub(r'<think>.*?</think>', '', formal_doc, flags=re.DOTALL)
            formal_doc = re.sub(r'<thinking>.*?</thinking>', '', formal_doc, flags=re.DOTALL)

            formal_md_path = output_dir / "02-系统功能需求说明书.md"
            with open(formal_md_path, 'w', encoding='utf-8') as f:
                f.write(formal_doc)

            # Phase 5
            print("[Phase 5] 生成 DOCX...")
            formal_docx_path = output_dir / "02-系统功能需求说明书.docx"
            parse_markdown_to_docx(str(formal_md_path), str(formal_docx_path))

            # Phase 6
            print("[Phase 6] 生成自评报告...")
            prompt = self.load_prompt("phase6_self_review")
            checklist = self.load_template("self-review-checklist")
            review = self.llm_client.call(prompt.format(formal_doc=formal_doc, checklist=checklist))

            review_path = output_dir / "03-AI自评报告.md"
            with open(review_path, 'w', encoding='utf-8') as f:
                f.write(review)

            limitations_path = output_dir / "04-AI局限性声明.md"
            limitations = self.load_template("ai-limitations")
            with open(limitations_path, 'w', encoding='utf-8') as f:
                f.write(limitations)

            print("\n[OK] PRD 生成完成！")

            return {
                'success': True,
                'output_files': {
                    'delta': str(delta_path),
                    'formal_md': str(formal_md_path),
                    'formal_docx': str(formal_docx_path),
                    'review': str(review_path),
                    'limitations': str(limitations_path)
                }
            }
        except Exception as e:
            print(f"\n[ERROR] PRD 生成失败: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}
