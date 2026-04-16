#!/usr/bin/env python3
"""
文档提取工具 - 支持 .docx 格式（原生）和 .doc 格式（需转换或使用antiword）

说明：
- .docx 文件：使用 python-docx 或 mammoth 直接读取
- .doc 文件：旧版二进制格式，需要转换为 .docx 或使用 antiword/textract

安装依赖：
  pip install python-docx mammoth

.doc 文件处理方案：
  1. 手动转换：用 Microsoft Word 打开 .doc 文件，另存为 .docx
  2. 使用 antiword（Linux/Mac）：pip install antiword
  3. 使用 textract（需额外依赖）：pip install textract
"""
import argparse
import json
import sys
import re
import subprocess
from pathlib import Path

try:
    from docx import Document
    from docx.document import Document as _Document
    from docx.table import _Cell, Table
    from docx.text.paragraph import Paragraph
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    import mammoth
    MAMMOTH_AVAILABLE = True
except ImportError:
    MAMMOTH_AVAILABLE = False

try:
    import textract
    TEXTRACT_AVAILABLE = True
except ImportError:
    TEXTRACT_AVAILABLE = False


def iter_block_items(parent):
    """Iterate over block items in a document."""
    if isinstance(parent, _Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        raise TypeError("Unsupported parent type")

    for child in parent_elm.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, parent)
        elif tag == "tbl":
            yield Table(child, parent)


def heading_level(style_name):
    """Extract heading level from style name."""
    if not style_name:
        return None
    if style_name == "Title":
        return 1
    if style_name.startswith("Heading "):
        suffix = style_name.split(" ", 1)[1]
        if suffix.isdigit():
            return int(suffix)
    return None


def parse_table(table):
    """Parse a table into rows of cell texts."""
    rows = []
    for row in table.rows:
        values = []
        for cell in row.cells:
            text = "\n".join(
                paragraph.text.strip()
                for paragraph in cell.paragraphs
                if paragraph.text.strip()
            ).strip()
            values.append(text)
        rows.append(values)
    return rows


def parse_docx_native(path):
    """Parse a .docx file using python-docx into blocks."""
    if not DOCX_AVAILABLE:
        raise ImportError("python-docx not available")
    
    document = Document(path)
    blocks = []
    for block in iter_block_items(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            style_name = block.style.name or ""
            blocks.append(
                {
                    "type": "paragraph",
                    "style": style_name,
                    "level": heading_level(style_name),
                    "is_list": style_name.startswith("List"),
                    "text": text,
                }
            )
        else:
            rows = parse_table(block)
            if rows:
                blocks.append({"type": "table", "rows": rows})
    return blocks


def parse_doc_with_textract(path):
    """Parse a .doc file using textract."""
    if not TEXTRACT_AVAILABLE:
        raise ImportError("textract not available")
    
    text = textract.process(str(path)).decode('utf-8')
    
    # Simple parsing: split into paragraphs
    blocks = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        
        # Detect headings (simple heuristic)
        level = None
        if line.startswith('第') and '章' in line[:10]:
            level = 1
        elif len(line) < 50 and not line.endswith('。') and not line[0].isdigit():
            level = 2
        
        blocks.append({
            "type": "paragraph",
            "style": f"Heading {level}" if level else "Normal",
            "level": level,
            "is_list": line.startswith(('•', '-', '*', '1.', '2.', '(')),
            "text": line,
        })
    
    return blocks


def parse_with_mammoth(path):
    """Parse a .docx file using mammoth as fallback."""
    if not MAMMOTH_AVAILABLE:
        raise ImportError("mammoth not available")
    
    with open(path, "rb") as docx_file:
        result = mammoth.convert_to_html(docx_file)
        html = result.value
    
    # Convert HTML to text blocks
    blocks = []
    
    # Extract tables first
    table_pattern = r'<table[^>]*>(.*?)</table>'
    tables = re.findall(table_pattern, html, re.DOTALL)
    html_without_tables = re.sub(table_pattern, '\n[TABLE]\n', html, flags=re.DOTALL)
    
    # Process tables
    for table_html in tables:
        rows = []
        row_pattern = r'<tr[^>]*>(.*?)</tr>'
        rows_html = re.findall(row_pattern, table_html, re.DOTALL)
        for row_html in rows_html:
            cell_pattern = r'<t[dh][^>]*>(.*?)</t[dh]>'
            cells_html = re.findall(cell_pattern, row_html, re.DOTALL)
            cells = []
            for cell_html in cells_html:
                text = re.sub(r'<[^>]+>', '', cell_html).strip()
                text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
                cells.append(text)
            if cells:
                rows.append(cells)
        if rows:
            blocks.append({"type": "table", "rows": rows})
    
    # Process paragraphs
    lines = html_without_tables.split('\n')
    for line in lines:
        line = line.strip()
        if not line or line == '[TABLE]':
            continue
        
        text = re.sub(r'<[^>]+>', '', line).strip()
        text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
        
        if not text:
            continue
        
        level = None
        if line.startswith('<h1'):
            level = 1
        elif line.startswith('<h2'):
            level = 2
        elif line.startswith('<h3'):
            level = 3
        elif line.startswith('<h4'):
            level = 4
        
        is_list = line.startswith(('<li', '<ul', '<ol')) or text.startswith(('•', '-', '*'))
        
        blocks.append({
            "type": "paragraph",
            "style": f"Heading {level}" if level else "Normal",
            "level": level,
            "is_list": is_list,
            "text": text,
        })
    
    return blocks


def parse_document(path):
    """Parse a document file (.docx or .doc) into blocks."""
    path = Path(path)
    suffix = path.suffix.lower()
    
    if suffix == '.docx':
        # Try native parser first
        if DOCX_AVAILABLE:
            try:
                return parse_docx_native(path)
            except Exception as e:
                print(f"Warning: Native parser failed ({e}), trying mammoth fallback...")
        
        # Use mammoth as fallback
        if MAMMOTH_AVAILABLE:
            return parse_with_mammoth(path)
        else:
            raise SystemExit(
                "Cannot parse .docx files. Please install: pip install python-docx mammoth"
            )
    
    elif suffix == '.doc':
        # .doc files require special handling
        methods = []
        
        # Try textract first (if available)
        if TEXTRACT_AVAILABLE:
            try:
                return parse_doc_with_textract(path)
            except Exception as e:
                methods.append(f"textract: {e}")
        
        # Provide helpful error message
        error_msg = (
            f"\n无法直接读取 .doc 文件（旧版二进制格式）。\n"
            f"已尝试的方法: {', '.join(methods) if methods else '无'}\n\n"
            f"解决方案（选其一）:\n"
            f"  1. 【推荐】手动转换: 用 Microsoft Word 打开文件，另存为 .docx 格式\n"
            f"  2. 安装 textract: pip install textract (Windows上可能需要额外依赖)\n"
            f"  3. 安装 antiword: 适用于 Linux/Mac，Windows需使用 WSL\n"
            f"  4. 使用在线转换工具: 如 Smallpdf、iLovePDF 等\n"
        )
        raise SystemExit(error_msg)
    
    else:
        raise SystemExit(f"不支持的文件格式: {suffix}。仅支持 .docx 和 .doc (需转换)")


def escape_cell(text):
    """Escape special characters in table cells."""
    if text is None:
        return ""
    return text.replace("|", "\\|").replace("\n", "<br>")


def blocks_to_markdown(blocks):
    """Convert blocks to Markdown format."""
    lines = []
    for block in blocks:
        if block["type"] == "paragraph":
            text = block["text"]
            level = block.get("level")
            if level:
                lines.append("#" * min(level, 6) + " " + text)
            elif block.get("is_list"):
                lines.append(f"- {text}")
            else:
                lines.append(text)
            lines.append("")
            continue

        rows = block.get("rows", [])
        if not rows:
            continue
        
        width = max(len(row) for row in rows) if rows else 0
        if width == 0:
            continue
            
        normalized = [row + [""] * (width - len(row)) for row in rows]
        
        header = normalized[0]
        lines.append("| " + " | ".join(escape_cell(cell) for cell in header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in normalized[1:]:
            lines.append("| " + " | ".join(escape_cell(cell) for cell in row) + " |")
        lines.append("")
    
    return "\n".join(lines).strip() + "\n"


def dump_output(content, output_path):
    """Write output to file or stdout."""
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        return
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(content)


def main():
    parser = argparse.ArgumentParser(
        description="Extract text and tables from DOCX files (and DOC with limitations)",
        epilog="Note: .doc files require conversion to .docx or special dependencies."
    )
    parser.add_argument("input", help="Input .docx or .doc path")
    parser.add_argument(
        "--output",
        "-o",
        help="Optional output file path. Defaults to stdout."
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file does not exist: {input_path}")

    blocks = parse_document(input_path)

    if args.format == "json":
        content = json.dumps(blocks, ensure_ascii=False, indent=2) + "\n"
    else:
        content = blocks_to_markdown(blocks)

    output_path = Path(args.output) if args.output else None
    dump_output(content, output_path)


if __name__ == "__main__":
    main()
