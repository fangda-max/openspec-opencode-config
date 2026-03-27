# Enterprise Requirement Doc Skill

企业级需求文档生成技能 - 从混杂的原始材料（会议纪要、建设方案、功能说明书、原型截图等）自动生成结构化的系统功能需求说明书。

## 📋 功能特性

- **多格式支持**：处理 docx/pdf/md/txt/图片等多种格式的原材料
- **六阶段工作流**：Ingest → Fact Base → Delta → Draft → Render → Review
- **三分法标注**：明确区分事实/推断/待确认，防止 AI 幻觉
- **需求变更分类**：自动识别新增点/优化点/改造点
- **自评机制**：生成 AI 自评报告，确保文档质量
- **DOCX 生成**：使用 python-docx API 结构化构建专业 Word 文档（带封面、样式、配色）

## 📁 目录结构

```
enterprise-requirement-doc/
├── SKILL.md                      # 技能主定义
├── docx-generation-guide.md      # DOCX 生成指南（样式/模板/配色）
├── material-analysis-guide.md    # 原材料解析指南
├── delta-template.md             # 中间稿模板（需求新增优化改造点）
├── document-template.md          # 正式文档模板
├── writing-guide.md              # 写作规范与转化规则
├── self-review-checklist.md      # AI 自评清单
├── examples.md                   # 用法示例
├── 使用文档.md                   # 面向用户的完整使用指南
└── scripts/
    └── extract_docx.py           # DOCX 提取脚本
```

## 🚀 使用方法

### 在 OpenClaw 中使用

1. 将此技能目录添加到你的 OpenClaw skills 路径
2. 触发条件：用户要求"生成需求文档"、"写需求说明书"等
3. 自动执行完整工作流，输出 4 个交付物

### 默认交付物

- `01-需求新增优化改造点.md` - 中间稿（需求分类整理）
- `02-系统功能需求说明书.md` - 正式 Markdown 文档
- `02-系统功能需求说明书.docx` - Word 文档
- `03-AI 自评报告.md` - 质量审查报告

## 🛠️ 依赖

```bash
pip install python-docx
```

## 📊 适用场景

✅ **适合：**
- 企业内部系统需求文档（OA、ERP、CRM 等）
- 政务信息化项目需求规格说明书
- 金融/电信行业系统改造需求
- 从 0 到 1 的新系统建设
- 存量系统的迭代升级

❌ **不适合：**
- 敏捷用户故事（User Story）编写
- 极简 MVP 需求（一句话需求）
- 技术方案设计文档（架构设计、数据库设计）
- 市场需求文档（MRD）、商业计划书（BP）

## 🎯 核心亮点

1. **工程化思维**：6 阶段工作流 + 中间稿机制 + 自评闭环
2. **防幻觉设计**：事实/推断/待确认三分法
3. **多材料处理**：支持 docx/pdf/图片/会议纪要等混杂输入
4. **标准化分类**：新增点/优化点/改造点自动识别
5. **规模自适应**：轻量/标准/完整三种文档结构

## 📝 工作流程

```
Phase 1: Ingest Materials     → 读取并分类所有原材料
Phase 2: Build Fact Base      → 抽取结构化事实底稿
Phase 3: Generate Delta       → 输出需求新增优化改造点
Phase 4: Draft Formal Doc     → 起草正式需求文档
Phase 5: Produce MD & DOCX    → 生成 Markdown 和 Word 文档
Phase 6: Self Review          → AI 自评并修正
```

## 🔧 脚本工具

### 提取 DOCX
```bash
python scripts/extract_docx.py "原材料.docx" --output "提取结果.md"
```

### 生成 DOCX
> 已废弃 `render_requirement_doc.py` 脚本（格式简陋）。现在使用 python-docx API 结构化构建 Word 文档，详见 [docx-generation-guide.md](docx-generation-guide.md)。

## 📄 许可证

本技能基于原 Cursor Skill 移植，保留原有许可条款。

## 👥 贡献者

- 原始作者：Cursor Skill 社区
- 移植维护：[你的名字]

## 📞 问题反馈

如有问题或建议，请在 GitHub 仓库提交 Issue。
