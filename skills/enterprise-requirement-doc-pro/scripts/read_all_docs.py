#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取运营中心历史需求文档和新需求文档目录中的所有文件
支持 .docx 和 .doc 格式（.doc 需要转换或使用 textract）
"""
import os
import sys
import io
from pathlib import Path

# 设置 stdout 编码为 utf-8（兼容 Streamlit）
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加 skill 目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from extract_docx import (
    parse_document, 
    blocks_to_markdown, 
    DOCX_AVAILABLE, 
    MAMMOTH_AVAILABLE,
    TEXTRACT_AVAILABLE
)

def read_document_file(file_path):
    """读取 docx/doc 文件并返回 markdown 格式的内容"""
    try:
        blocks = parse_document(file_path)
        return blocks_to_markdown(blocks)
    except SystemExit as e:
        # 将 .doc 文件的错误信息返回
        return str(e)
    except Exception as e:
        return f"[读取错误: {e}]"

def list_files_in_directory(directory):
    """列出目录中的所有文件"""
    files = []
    for root, dirs, filenames in os.walk(directory):
        for filename in filenames:
            file_path = os.path.join(root, filename)
            files.append({
                'path': file_path,
                'name': filename,
                'ext': Path(filename).suffix.lower()
            })
    return files

def read_all_documents(directory):
    """读取目录中的所有文档并返回列表"""
    results = []
    files = list_files_in_directory(directory)

    for f in files:
        if f['ext'] in ['.docx', '.doc', '.md', '.txt']:
            if f['ext'] == '.md' or f['ext'] == '.txt':
                # 直接读取文本文件
                try:
                    with open(f['path'], 'r', encoding='utf-8') as file:
                        content = file.read()
                except:
                    try:
                        with open(f['path'], 'r', encoding='gbk') as file:
                            content = file.read()
                    except Exception as e:
                        content = f"[读取错误: {e}]"
            else:
                # 读取 docx/doc 文件
                content = read_document_file(f['path'])

            results.append({
                'filename': f['name'],
                'filepath': f['path'],
                'content': content
            })

    return results

def main():
    # 定义两个目录
    history_dir = r"D:\Desktop\运营中心历史需求文档"
    new_dir = r"D:\Desktop\运营中心新需求文档"
    
    # 检查库可用性
    print("=" * 60)
    print("文档提取工具 - 库状态检查")
    print("=" * 60)
    print(f"python-docx (用于.docx): {'[OK]' if DOCX_AVAILABLE else '[Not Installed]'}")
    print(f"mammoth (用于.docx备选): {'[OK]' if MAMMOTH_AVAILABLE else '[Not Installed]'}")
    print(f"textract (用于.doc): {'[OK]' if TEXTRACT_AVAILABLE else '[Not Installed]'}")
    print()
    print("Note: .doc files need to be converted to .docx or install textract")
    print("=" * 60)
    print()
    
    print("=" * 60)
    print("正在读取运营中心历史需求文档...")
    print("=" * 60)
    
    history_files = list_files_in_directory(history_dir)
    for f in history_files:
        print(f"\n[文件] {f['name']}")
        print(f"[路径] {f['path']}")
        if f['ext'] in ['.docx', '.doc']:
            content = read_document_file(f['path'])
            if content.startswith('\n无法直接读取') or content.startswith('[读取错误'):
                print(f"[提示] {content}")
            else:
                print(f"[内容预览]\n{content[:3000]}...")
        else:
            print(f"[跳过] 不支持的格式: {f['ext']}")
    
    print("\n" + "=" * 60)
    print("正在读取运营中心新需求文档...")
    print("=" * 60)
    
    new_files = list_files_in_directory(new_dir)
    for f in new_files:
        print(f"\n[文件] {f['name']}")
        print(f"[路径] {f['path']}")
        if f['ext'] in ['.docx', '.doc']:
            content = read_document_file(f['path'])
            if content.startswith('\n无法直接读取') or content.startswith('[读取错误'):
                print(f"[提示] {content}")
            else:
                print(f"[内容预览]\n{content[:3000]}...")
        else:
            print(f"[跳过] 不支持的格式: {f['ext']}")

if __name__ == "__main__":
    main()
