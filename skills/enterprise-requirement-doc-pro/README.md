# Enterprise Requirement Doc Pro

企业级需求文档生成技能 Pro 版 - 基于极端严谨的 PRD 标准，生产级别可用的需求文档生成工具。

从混杂的原始材料（会议纪要、建设方案、功能说明书、原型截图等）自动生成结构化的系统功能需求说明书，包含 **AC 验收标准、Unhappy Path 分析、数据追踪埋点、兼容性分析** 等生产级必备内容。

---

## 📋 Pro 版功能特性

### 基础特性（继承原版）
- **多格式支持**：处理 docx/pdf/md/txt/图片等多种格式的原材料
- **六阶段工作流**：Ingest → Fact Base → Delta → Deep Analysis → Draft → Render → Review
- **三分法标注**：明确区分事实/推断/待确认，防止 AI 幻觉
- **需求变更分类**：自动识别新增点/优化点/改造点
- **自评机制**：生成 AI 自评报告，确保文档质量
- **DOCX 生成**：使用 python-docx API 结构化构建专业 Word 文档

### Pro 版增强特性

#### 1. ✅ AC 验收标准（Given-When-Then）
- 每个功能点必须包含至少 3 个 AC
- 强制采用 Given-When-Then 格式
- 覆盖主流程、业务异常、系统异常

#### 2. ✅ Unhappy Path 深度分析
- 每个功能点必须包含至少 2 个 Unhappy Path
- 区分业务异常和系统异常
- 具体到错误代码、用户提示、处理逻辑

#### 3. ✅ 数据追踪埋点
- 核心功能强制要求埋点定义
- 事件名称、触发时机、关键属性完整定义
- 包含通用属性和脱敏要求

#### 4. ✅ 版本兼容性分析
- 改造点强制要求兼容性分析
- 历史数据迁移方案
- 接口兼容性、功能回滚、灰度策略

#### 5. ✅ 业务价值量化
- Must have 需求必须量化业务价值
- 节省人力/提升效率/减少错误的具体数值
- 计算依据说明

#### 6. ✅ 苏格拉底式追问
- 后端工程师视角（并发、幂等、一致性）
- QA 视角（测试覆盖、环境依赖）
- 安全工程师视角（权限、脱敏、注入）

#### 7. ✅ AI 局限性声明
- 明确 AI 能力边界
- 人工复核清单
- 责任声明

---

## 📁 目录结构

```
enterprise-requirement-doc-pro/
├── SKILL.md                      # 技能主定义（Pro 版增强）
├── README.md                     # 本文件
├── config.json                   # 配置文件
├── scripts/                      # Python 脚本
│   ├── prd_generator.py          # PRD 生成器核心类
│   ├── generate_docx.py          # DOCX 生成脚本
│   ├── extract_docx.py           # DOCX 提取脚本
│   └── read_all_docs.py          # 读取材料目录中的所有文档
├── prompts/                      # 提示词文件
│   ├── phase2_fact_base.txt      # Phase 2: 构建事实底稿
│   ├── phase3_delta.txt          # Phase 3: 生成中间稿
│   ├── phase3.5_deep_analysis.txt # Phase 3.5: 深度分析
│   ├── phase4_formal_doc.txt     # Phase 4: 起草正式文档
│   └── phase6_self_review.txt    # Phase 6: 生成自评报告
├── templates/                    # 模板文件
│   ├── document-template.md      # 正式文档模板（含 AC、埋点、兼容性）
│   ├── delta-template.md         # 中间稿模板（含 MoSCoW、业务价值量化）
│   ├── deep-analysis-prompts.md  # 深度分析指南
│   ├── ac-writing-guide.md       # AC 写作指南（Pro 版新增）
│   ├── self-review-checklist.md  # AI 自评清单（Pro 版增强）
│   └── ai-limitations.md         # AI 局限性声明（Pro 版新增）
└── docs/                         # 参考文档
    ├── 使用文档.md                # 面向用户的完整使用指南
    ├── examples.md               # 用法示例（含 AC、埋点示例）
    ├── material-analysis-guide.md # 原材料解析指南
    ├── writing-guide.md          # 写作规范
    ├── docx-generation-guide.md  # DOCX 生成指南
    └── AGENTS.md                 # Agent 角色定义
```

---

## 🚀 使用方法

### 在 OpenClaw 中使用

1. 将此技能目录添加到你的 OpenClaw skills 路径
2. 触发条件：用户要求"生成需求文档 Pro"、"写 PRD"、"生成带 AC 的需求文档"等
3. 自动执行完整工作流，输出 **5 个交付物**

### 默认交付物

| 序号 | 文件名 | 说明 |
|------|--------|------|
| 01 | `01-需求新增优化改造点.md` | 中间稿（含业务价值量化、MoSCoW 优先级、兼容性分析） |
| 02 | `02-系统功能需求说明书.md` | 正式 Markdown 文档（含 AC、Unhappy Path、埋点） |
| 03 | `02-系统功能需求说明书.docx` | Word 文档 |
| 04 | `03-AI自评报告.md` | 质量审查报告（含 AC、埋点、兼容性检查） |
| 05 | `04-AI局限性声明.md` | AI 生成内容的局限性和人工复核清单 |

---

## 🛠️ 依赖

```bash
pip install python-docx markdown pdfplumber pillow mammoth
```

---

## 📊 适用场景

### ✅ 适合：
- **企业内部系统需求文档**（OA、ERP、CRM 等）
- **政务信息化项目需求规格说明书**
- **金融/电信行业系统改造需求**（需要严格的兼容性分析）
- **从 0 到 1 的新系统建设**（需要完整的 AC 和埋点）
- **存量系统的迭代升级**（需要兼容性分析）
- **需要通过严格评审的 PRD**（政府、金融、大型企业）

### ❌ 不适合：
- 敏捷用户故事（User Story）编写（过于重量级）
- 极简 MVP 需求（一句话需求）
- 技术方案设计文档（架构设计、数据库设计）
- 市场需求文档（MRD）、商业计划书（BP）

---

## 🎯 核心亮点

### 原版亮点
1. **工程化思维**：6 阶段工作流 + 中间稿机制 + 自评闭环
2. **防幻觉设计**：事实/推断/待确认三分法
3. **多材料处理**：支持 docx/pdf/图片/会议纪要等混杂输入
4. **标准化分类**：新增点/优化点/改造点自动识别
5. **规模自适应**：轻量/标准/完整三种文档结构

### Pro 版新增亮点
6. **AC 强制标准**：Given-When-Then 格式，可测试、可验证
7. **Unhappy Path 深度覆盖**：不仅写"异常情况"，而是具体到错误代码
8. **数据追踪规范**：埋点定义不再是"可选项"而是"必选项"
9. **兼容性分析**：改造项目必备，避免上线事故
10. **业务价值量化**：用数据说话，拒绝"提升效率"空话
11. **苏格拉底式追问**：像资深架构师一样问出边界问题
12. **AI 局限性声明**：明确告知用户哪里需要人工复核

---

## 📝 工作流程（Pro 版增强）

```
Phase 1: Ingest Materials       → 读取并分类所有原材料
Phase 2: Build Fact Base        → 抽取结构化事实底稿
Phase 3: Generate Delta         → 输出需求新增优化改造点
Phase 3.5: Deep Analysis        → 深度分析（Pro 版增强）
    ├── 业务价值追问（量化）
    ├── 场景拆解（主流程 + Unhappy Path + 边界）
    ├── 冲突检测
    ├── 数据流分析
    ├── 风险预判
    ├── 优先级排序（MoSCoW）
    └── 苏格拉底式追问（Pro 版新增）
Phase 4: Draft Formal Doc       → 起草正式需求文档
    ├── 必须包含 AC（Given-When-Then）
    ├── 必须包含 Unhappy Path（至少 2 个）
    ├── 必须包含数据追踪埋点（核心功能）
    └── 必须包含兼容性分析（改造点）
Phase 5: Produce MD & DOCX      → 生成 Markdown 和 Word 文档
Phase 6: Self Review            → AI 自评并修正
    ├── 基础维度检查
    ├── Pro 版维度检查（AC、埋点、兼容性）
    └── 生成 AI 局限性声明
```

---

## 🔧 与原版的区别

| 维度 | 原版 | Pro 版 |
|------|------|--------|
| AC 验收标准 | 建议但不强制 | **强制要求**，GWT 格式 |
| Unhappy Path | 异常流建议 | **强制要求**，至少 2 个，具体到错误代码 |
| 数据追踪埋点 | 无 | **核心功能强制要求** |
| 兼容性分析 | 简单提及 | **改造点强制要求**，含迁移/回滚/灰度 |
| 业务价值量化 | 建议 | **Must have 强制要求** |
| 苏格拉底式追问 | 无 | **新增，防御性检查** |
| AI 局限性声明 | 无 | **新增，交付物之一** |
| 交付物数量 | 4 个 | **5 个** |
| 适用场景 | 常规需求 | **生产级别、严格评审** |

---

## 🚀 快速开始

### 示例 1：标准模式

```
请使用 Pro 版生成需求文档，材料在 D:\项目\ 目录下
```

### 示例 2：指定公司模板

```
请使用 Pro 版生成需求文档，
材料在 D:\项目\ 下，
公司模板使用 D:\项目\公司需求模板.docx
```

### 示例 3：快速模式

```
请用 Pro 版快速模式生成需求文档，材料在 D:\项目\ 下
```

---

## 📖 文档指南

- **新手入门**：[docs/使用文档.md](docs/使用文档.md)
- **用法示例**：[docs/examples.md](docs/examples.md)
- **AC 写作规范**：[templates/ac-writing-guide.md](templates/ac-writing-guide.md)（Pro 版新增）
- **文档模板**：[templates/document-template.md](templates/document-template.md)
- **中间稿模板**：[templates/delta-template.md](templates/delta-template.md)
- **深度分析提示词**：[templates/deep-analysis-prompts.md](templates/deep-analysis-prompts.md)
- **自评清单**：[templates/self-review-checklist.md](templates/self-review-checklist.md)
- **AI 局限性说明**：[templates/ai-limitations.md](templates/ai-limitations.md)（Pro 版新增）
- **原材料解析指南**：[docs/material-analysis-guide.md](docs/material-analysis-guide.md)
- **写作规范**：[docs/writing-guide.md](docs/writing-guide.md)
- **DOCX 生成指南**：[docs/docx-generation-guide.md](docs/docx-generation-guide.md)

---

## 📄 许可证

本技能基于原 Cursor Skill 移植并增强，保留原有许可条款。

---

## 👥 版本说明

- **原版**：`enterprise-requirement-doc` - 适合常规需求，向后兼容保留
- **Pro 版**：`enterprise-requirement-doc-pro` - 生产级别，严格标准

---

## 📞 问题反馈

如有问题或建议，请在 GitHub 仓库提交 Issue。
