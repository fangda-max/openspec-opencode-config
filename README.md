# 🦞 OpenClaw Skills Repository

这是我的 **AI 技能 (Skills)** 核心库。这里的每个技能都是经过优化的 Prompt、工作流或工具定义，用于增强 OpenClaw Agent 的能力。

---

## 🛠️ 当前技能列表

### 1. [enterprise-requirement-doc](./enterprise-requirement-doc) ⭐ (最新添加)
**企业级需求文档生成专家** - 从混杂的原始材料自动生成结构化的系统功能需求说明书。

#### 📋 核心能力
- **多格式处理**：支持 docx/pdf/md/txt/图片/会议纪要/建设方案/功能说明书等多种格式
- **六阶段工作流**：Ingest → Fact Base → Delta → Draft → Render → Review
- **防幻觉设计**：事实/推断/待确认三分法标注，确保需求可追溯
- **变更分类**：自动识别新增点/优化点/改造点，帮助开发团队快速理解变更性质
- **自评机制**：生成 AI 自评报告，包含准确性/完整性/可行性/一致性检查
- **DOCX 渲染**：自动将 Markdown 转换为 Word 文档，支持企业交付格式

#### 🎯 适用场景
✅ 企业内部系统需求（OA、ERP、CRM 等）  
✅ 政务信息化项目需求规格说明书  
✅ 金融/电信行业系统改造需求  
✅ 从 0 到 1 的新系统建设  
✅ 存量系统的迭代升级  

❌ 不适合：敏捷用户故事、极简 MVP 需求、技术方案设计、商业计划书

#### 📁 目录结构
```
enterprise-requirement-doc/
├── SKILL.md                      # 技能主定义
├── README.md                     # 使用说明
├── material-analysis-guide.md    # 原材料解析指南
├── delta-template.md             # 中间稿模板（需求新增优化改造点）
├── document-template.md          # 正式文档模板
├── writing-guide.md              # 写作规范与转化规则
├── self-review-checklist.md      # AI 自评清单
├── examples.md                   # 用法示例
└── scripts/
    ├── extract_docx.py           # DOCX 提取脚本
    └── render_requirement_doc.py # DOCX 渲染脚本
```

#### 🚀 使用方法
**触发条件：** 用户要求"生成需求文档"、"写需求说明书"、"输出功能需求文档"等

**默认交付物：**
1. `01-需求新增优化改造点.md` - 中间稿（需求分类整理）
2. `02-系统功能需求说明书.md` - 正式 Markdown 文档
3. `02-系统功能需求说明书.docx` - Word 文档
4. `03-AI 自评报告.md` - 质量审查报告

**依赖安装：**
```bash
pip install python-docx
```

#### 💡 核心亮点
1. **工程化思维**：不是"一次性生成"，而是完整的 6 阶段工程流程
2. **多材料融合**：可以同时处理会议纪要 + 建设方案 + 功能说明书 + 原型截图
3. **规模自适应**：根据功能模块数量自动选择轻量/标准/完整文档结构
4. **A/B 类功能区分**：传统功能 vs AI/异步任务的差异化写法
5. **页面扩写规则**：从"功能点"扩展为完整的"功能章节"

---

### 2. [generate-requirement-doc](./generate-requirement-doc)
- **用途**：将会议纪要、方案、截图等原始材料转化为标准《系统功能需求说明书》。
- **能力**：自动项目分级、信息缺口检测、A/B 类功能深度分析。

### 3. [opencode-agent](./opencode-agent)
- **用途**：使用 OpenCode AI 代理执行复杂的编码、重构和代码审查任务。

### 4. [skill-creator](./skill-creator)
- **用途**：引导式创建新的 OpenClaw 技能，确保技能符合标准结构和逻辑规范。

### 5. [skill-vetter](./skill-vetter)
- **用途**：对新技能进行安全性、可行性和逻辑一致性评估。

### 6. [tavily-search](./tavily-search)
- **用途**：集成 Tavily AI 搜索能力，提供更高质量、结构化的网页搜索结果。

---

## 🔄 自动化与同步
- **自动同步**：本仓库由主 Agent 自动维护。任何本地技能的新建或更新都会实时推送至此。
- **共享机制**：所有连接到此 Skill 库的 Agent（如 OpenSpecXia, PrototypeXia）都能即时使用这里的最新能力。

---

## 📬 反馈与更新
如果你需要调整某个技能的逻辑，直接在 OpenClaw 会话中告知我即可。
