#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

try:
    from docx import Document
    from docx.document import Document as _Document
    from docx.table import _Cell, Table
    from docx.text.paragraph import Paragraph
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: python-docx. Install it with `pip install python-docx`."
    ) from exc


def iter_block_items(parent):
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
    if style_name == "Title":
        return 1
    if style_name.startswith("Heading "):
        suffix = style_name.split(" ", 1)[1]
        if suffix.isdigit():
            return int(suffix)
    return None


def parse_table(table):
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


def parse_document(path):
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


def escape_cell(text):
    return text.replace("|", "\\|").replace("\n", "<br>")


def blocks_to_markdown(blocks):
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

        rows = block["rows"]
        if not rows:
            continue

        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]
        header = normalized[0]
        lines.append("| " + " | ".join(escape_cell(cell) for cell in header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in normalized[1:]:
            lines.append("| " + " | ".join(escape_cell(cell) for cell in row) + " |")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def dump_output(content, output_path):
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        return
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(content)


def main():
    parser = argparse.ArgumentParser(description="Extract text and tables from a DOCX file.")
    parser.add_argument("input", help="Input .docx path")
    parser.add_argument(
        "--output", "-o", help="Optional output file path. Defaults to stdout."
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
    if input_path.suffix.lower() != ".docx":
        raise SystemExit("Only .docx files are supported.")

    blocks = parse_document(input_path)
    if args.format == "json":
        content = json.dumps(blocks, ensure_ascii=False, indent=2) + "\n"
    else:
        content = blocks_to_markdown(blocks)

    output_path = Path(args.output) if args.output else None
    dump_output(content, output_path)


if __name__ == "__main__":
    main()
