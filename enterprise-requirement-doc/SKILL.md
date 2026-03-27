---
name: enterprise-requirement-doc
description: Generate enterprise-grade system requirement documents from user demand descriptions and mixed source materials, including docx/pdf/md/txt/png/jpg inputs. Produce a structured intermediate markdown for new points, optimizations, and modifications, then generate a formal Markdown+DOCX requirement document and an AI self-review report. Use when the user asks to write requirement documents, requirement analysis, system function requirement specifications, FRD/PRD, or provides raw requirement materials.
---

# Enterprise Requirement Doc

## Use This Skill When

- 用户要求"生成需求文档""写需求说明书""输出功能需求文档""复刻一份企业级需求文档"。
- 用户提供了 `docx`、`pdf`、`md`、`txt`、图片、会议纪要、建设方案、功能说明书、界面原型、已有需求文档、模板规范等原材料。
- 用户要求先形成结构化中间稿，再输出正式需求文档。
- 用户要求对生成结果做 AI 自评，确保准确、可行、不偏离原材料。

## Default Deliverables

默认同时输出以下文件；若用户指定命名或目录，按用户要求覆盖：

- `01-需求新增优化改造点.md`
- `02-系统功能需求说明书.md`
- `02-系统功能需求说明书.docx`
- `03-AI自评报告.md`

## Hard Rules

- 先抽取事实，再扩写文档，禁止直接"脑补成文"。
- 明确区分 `事实`、`推断`、`待确认` 三类信息。
- 如缺少关键内容，必须先提问，不得用想当然内容补全关键业务规则。
- 公司模板优先于默认模板；公司模板未覆盖的部分再用默认模板补齐。
- 输出应以中文为默认语言；技术术语保留原文。
- 中间稿必须显式整理 `新增点`、`优化点`、`改造点`，并标注来源依据。
- 自评发现重大冲突、关键缺口、明显不可行点时，先修正再交付。

## Workflow

按以下顺序执行，不要跳过中间稿和自评。

### Phase 1: Ingest Materials

1. 读取用户需求描述与全部原材料。
2. 按材料类型分类：
   - `docx`：优先运行 `python scripts/extract_docx.py <input.docx>` 提取正文和表格。
   - `pdf`：优先直接读取；若为扫描件，再结合图片内容做结构化描述。
   - `md/txt`：直接读取。
   - `png/jpg/jpeg/webp`：提取页面区域、字段、按钮、列表、状态、说明文案。
3. 若材料存在冲突，记录冲突点，不要私自裁决。

补充规则见 [material-analysis-guide.md](material-analysis-guide.md)。

### Phase 2: Build Fact Base

1. 按以下维度建立事实底稿：
   - 背景与痛点
   - 建设目标
   - 范围与边界
   - 角色与职责
   - 核心对象、状态、状态流转
   - 功能模块
   - 页面与交互
   - 业务规则
   - 接口与数据
   - 非功能要求
   - 风险、依赖、约束、待确认事项
2. 对每条信息标记来源材料。
3. 执行关键缺口检查：
   - 业务目标
   - 功能模块清单
   - 核心对象/状态流转
   - 角色权限
   - 范围边界
4. 若缺失关键项，优先只问 1-3 个最关键问题。

分析口径见 [material-analysis-guide.md](material-analysis-guide.md)。

### Phase 3: Generate Delta Markdown

1. 基于事实底稿整理 `新增点`、`优化点`、`改造点`。
2. 每一点都必须包含：
   - 来源材料
   - 原文依据或归纳依据
   - 需求描述
   - 影响范围
   - 规则/约束
   - 落地建议
   - 优先级/必要性
   - 不确定项
3. 输出到 `01-需求新增优化改造点.md`。

模板见 [delta-template.md](delta-template.md)。

### Phase 4: Draft Formal Requirement Doc

1. 先判断文档规模：
   - 轻量：<=3 个功能模块，集成少
   - 标准：4-10 个功能模块
   - 完整：>10 个模块或涉及复杂集成/多角色/AI/异步能力
2. 再判断能力类型：
   - A 类：传统业务功能
   - B 类：AI、异步、批处理、长耗时任务
3. 若用户提供公司模板，先融合模板结构，再补充缺失章节。
4. 按骨架先出大纲，再逐章成文。
5. 第四章系统功能必须优先使用统一模块结构，避免只写功能清单。

文档骨架见 [document-template.md](document-template.md)。
写作规范见 [writing-guide.md](writing-guide.md)。

### Phase 5: Produce Markdown And DOCX

1. 先输出 `02-系统功能需求说明书.md`。
2. **必须使用 python-docx API 结构化构建 DOCX**，不要用 `render_requirement_doc.py` 脚本（格式简陋，无法控制样式细节）。
3. DOCX 生成规范：
   - 全局字体：微软雅黑 10.5pt
   - 多级标题：18/15/13/11.5pt，深色系配色
   - 表格：深蓝表头 + 白色字 + 交替行背景色
   - 封面页：标题居中 22pt + 元信息 12pt + 分页符
   - 文件名带版本号/日期，避免占用冲突
   - 生成前检查目标文件是否被 Word 占用
4. 详细的代码模板和配色方案见 [docx-generation-guide.md](docx-generation-guide.md)。

### Phase 6: Self Review

1. 基于正式文档和原材料执行 AI 自评。
2. 至少检查：
   - 准确性
   - 完整性
   - 可行性
   - 与原材料一致性
3. 输出 `03-AI自评报告.md`。
4. 若发现高风险问题，先回改正式文档，再给用户结果。

自评规则见 [self-review-checklist.md](self-review-checklist.md)。

## Quality Bar

- 文档必须像企业级需求说明书，而不是摘要、脑图或产品清单。
- 每个复杂模块至少写到"业务目标/业务场景/业务流程/功能模块详情"。
- 页面级内容至少写清：入口、角色、界面区域、实现逻辑、字段说明。
- 若涉及 AI/异步能力，补充交互过程、触发机制、验证指标。
- 状态、按钮、角色、字段名称全文统一。
- 不能编造接口名、状态值、权限规则、字段含义。

## If The User Wants Fast Mode

- 仍然保留四个交付物，但可以减少中间确认轮次。
- 若材料充分，可连续执行；若关键要素缺失，仍必须先提问。

## References

- 材料解析指南：[material-analysis-guide.md](material-analysis-guide.md)
- 中间稿模板：[delta-template.md](delta-template.md)
- 正式文档模板：[document-template.md](document-template.md)
- 写作规范：[writing-guide.md](writing-guide.md)
- 自评清单：[self-review-checklist.md](self-review-checklist.md)
- 用法示例：[examples.md](examples.md)
- **DOCX 生成指南（样式/模板/配色）**：[docx-generation-guide.md](docx-generation-guide.md)
- DOCX 提取脚本：`scripts/extract_docx.py`
- ~~DOCX 渲染脚本：`scripts/render_requirement_doc.py`~~（已废弃，格式简陋）
