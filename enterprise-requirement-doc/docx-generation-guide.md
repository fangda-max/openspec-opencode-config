# DOCX 生成指南

_基于实际项目经验总结，确保 Word 文档格式专业、美观。_

---

## 核心原则

**❌ 不要用 `render_requirement_doc.py` 脚本转换 markdown → docx（格式简陋）**
**✅ 直接用 python-docx API 结构化构建文档**

---

## 1. 全局样式配置

```python
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

doc = Document()

# === 全局字体 ===
style = doc.styles['Normal']
style.font.name = '微软雅黑'
style.font.size = Pt(10.5)
style._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')

# === 多级标题样式 ===
for i in range(1, 5):
    hs = doc.styles[f'Heading {i}']
    hs.font.name = '微软雅黑'
    hs._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    hs.font.bold = True
    if i == 1:
        hs.font.size = Pt(18)
        hs.font.color.rgb = RGBColor(0x1A, 0x1A, 0x2E)  # 深蓝黑
    elif i == 2:
        hs.font.size = Pt(15)
        hs.font.color.rgb = RGBColor(0x2C, 0x3E, 0x50)  # 深灰蓝
    elif i == 3:
        hs.font.size = Pt(13)
        hs.font.color.rgb = RGBColor(0x2C, 0x3E, 0x50)
    elif i == 4:
        hs.font.size = Pt(11.5)
        hs.font.color.rgb = RGBColor(0x34, 0x49, 0x5E)
```

### 标题分级

| 级别 | 字号 | 颜色 |
|------|------|------|
| Heading 1 | 18pt | `#1A1A2E` 深蓝黑 |
| Heading 2 | 15pt | `#2C3E50` 深灰蓝 |
| Heading 3 | 13pt | `#2C3E50` 深灰蓝 |
| Heading 4 | 11.5pt | `#34495E` 中灰蓝 |

---

## 2. 表格样式

```python
def set_cell_shading(cell, color):
    """设置单元格背景色"""
    shading = OxmlElement('w:shd')
    shading.set(qn('w:fill'), color)
    shading.set(qn('w:val'), 'clear')
    cell._tc.get_or_add_tcPr().append(shading)

def add_table(headers, rows, col_widths=None):
    """添加带样式的表格"""
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    
    # 表头：深蓝色背景 + 白色粗体字
    for j, h in enumerate(headers):
        cell = table.rows[0].cells[j]
        cell.text = ''
        p = cell.paragraphs[0]
        p.alignment = 1  # 居中
        run = p.add_run(str(h))
        run.font.name = '微软雅黑'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
        run.font.size = Pt(9)
        run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        set_cell_shading(cell, '2C3E50')  # 深蓝色
    
    # 数据行：交替行背景色
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = table.rows[i+1].cells[j]
            cell.text = ''
            p = cell.paragraphs[0]
            run = p.add_run(str(val) if val else '')
            run.font.name = '微软雅黑'
            run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
            run.font.size = Pt(8.5)
            if i % 2 == 1:
                set_cell_shading(cell, 'F2F4F6')  # 浅灰色交替行
    
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Cm(w)
    
    doc.add_paragraph()  # 表后空行
    return table
```

---

## 3. 封面页

```python
# 顶部留白
for _ in range(4):
    doc.add_paragraph()

# 标题
title_p = doc.add_paragraph()
title_p.alignment = 1  # 居中
run = title_p.add_run('文档标题')
run.font.name = '微软雅黑'
run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
run.font.size = Pt(22)
run.bold = True
run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x2E)

# 元信息（版本/单位/日期）
meta_items = [('版本', 'V2.0'), ('编写单位', 'XXX'), ('日期', '2026年3月')]
for label, val in meta_items:
    p = doc.add_paragraph()
    p.alignment = 1
    r1 = p.add_run(f'{label}：')
    r1.font.size = Pt(12)
    r1.bold = True
    r2 = p.add_run(val)
    r2.font.size = Pt(12)

# 分页符
doc.add_page_break()
```

---

## 4. 正文段落

```python
def add_para(text, bold=False, indent=False):
    p = doc.add_paragraph()
    if indent:
        p.paragraph_format.first_line_indent = Cm(0.74)
    run = p.add_run(text)
    run.font.name = '微软雅黑'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    run.font.size = Pt(10.5)
    if bold:
        run.bold = True
    return p
```

---

## 5. 配色方案

| 元素 | 颜色 | 用途 |
|------|------|------|
| 表头背景 | `#2C3E50` | 深蓝灰 |
| 表头文字 | `#FFFFFF` | 白色 |
| 交替行背景 | `#F2F4F6` | 浅灰 |
| 一级标题 | `#1A1A2E` | 深蓝黑 |
| 二/三级标题 | `#2C3E50` | 深灰蓝 |
| 四级标题 | `#34495E` | 中灰蓝 |

---

## 6. 常见问题

### 文件被占用

**现象：** `PermissionError: [Errno 13] Permission denied`
**原因：** 用户正在用 Word 打开该文件
**解决：** 文件名带版本号/日期避免冲突，生成前检查占用，提醒用户关闭旧文件。

### Windows 中文路径乱码

**解决：** 脚本开头加 `sys.stdout.reconfigure(encoding='utf-8')`

### .doc 格式不支持

**解决：** python-docx 仅支持 .docx，提示用户另存为 .docx

---

## 7. 生成前检查清单

- [ ] 文件名带版本号/日期
- [ ] 检查目标文件是否被占用
- [ ] 全局样式已设置（微软雅黑 + 多级标题）
- [ ] 表格使用带样式模板
- [ ] 包含封面页
- [ ] 交替行颜色已启用
