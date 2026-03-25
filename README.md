# 🦞 OpenClaw Skills Repository

这是我的 **AI 技能 (Skills)** 核心库。这里的每个技能都是经过优化的 Prompt、工作流或工具定义，用于增强 OpenClaw Agent 的能力。

---

## 🛠️ 当前技能列表

### 1. [generate-requirement-doc](./generate-requirement-doc) 🚀 (最新安装)
- **用途**：将会议纪要、方案、截图等原始材料转化为标准《系统功能需求说明书》。
- **能力**：自动项目分级、信息缺口检测、A/B类功能深度分析。

### 2. [opencode-agent](./opencode-agent)
- **用途**：使用 OpenCode AI 代理执行复杂的编码、重构和代码审查任务。

### 3. [skill-creator](./skill-creator)
- **用途**：引导式创建新的 OpenClaw 技能，确保技能符合标准结构和逻辑规范。

### 4. [skill-vetter](./skill-vetter)
- **用途**：对新技能进行安全性、可行性和逻辑一致性评估。

### 5. [tavily-search](./tavily-search)
- **用途**：集成 Tavily AI 搜索能力，提供更高质量、结构化的网页搜索结果。

---

## 🔄 自动化与同步
- **自动同步**：本仓库由主 Agent 自动维护。任何本地技能的新建或更新都会实时推送至此。
- **共享机制**：所有连接到此 Skill 库的 Agent（如 OpenSpecXia, PrototypeXia）都能即时使用这里的最新能力。

---

## 📬 反馈与更新
如果你需要调整某个技能的逻辑，直接在 OpenClaw 会话中告知我即可。
