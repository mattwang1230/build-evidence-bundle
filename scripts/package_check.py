#!/usr/bin/env python3
"""Check a public Skill tree for completeness, unsafe files and local paths."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# The checker imports a package helper from the tree it is checking.  Avoid
# creating a new __pycache__ inside that tree immediately before scanning it.
sys.dont_write_bytecode = True

from path_safety import LOCAL_PATH, first_link_component, is_link_or_junction


REQUIRED = {
    "SKILL.md",
    "VERSION",
    "LICENSE",
    "agents/openai.yaml",
    "scripts/requirements.txt",
    "scripts/build_evidence_bundle.py",
    "scripts/inspect_materials.py",
    "scripts/inspect_office_materials.py",
    "scripts/office_capabilities.py",
    "scripts/convert_office.py",
    "scripts/extract_video_frames.py",
    "scripts/validate_provenance.py",
    "scripts/qa_bundle.py",
    "scripts/package_check.py",
    "scripts/path_safety.py",
    "scripts/test_v19_proof_model.py",
    "scripts/test_v19_portability.py",
    "assets/example-manifest.json",
    "references/evidence-writing-rules.md",
    "references/intake-clarification.md",
    "references/material-filling-rules.md",
    "references/manifest-schema.md",
    "references/proof-object-rubric.md",
    "references/portable-runtime.md",
    "references/office-sidecar.md",
    "references/publication-safety.md",
    "references/v19-release-gates.md",
}
FORBIDDEN_DIRS = {"__pycache__", ".git", ".svn", ".idea", ".vscode", ".skill-up-workspace"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak"}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".toml", ".csv"}
SECRET = re.compile(r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}")


def main() -> None:
    parser = argparse.ArgumentParser(description="检查公开 Skill 包完整性、隐私路径、缓存和 Python 语法")
    parser.add_argument("skill_root", help="包含 SKILL.md 的候选目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--forbidden-token", action="append", default=[], help="额外禁止出现的项目私有词；可重复")
    args = parser.parse_args()
    raw_root = Path(args.skill_root).expanduser()
    root_is_link = first_link_component(raw_root) is not None
    root = raw_root.resolve()
    errors: list[str] = []
    checked = 0
    total_bytes = 0
    if root_is_link:
        errors.append("候选目录本身不得为符号链接或目录联接")
    if not root.is_dir():
        errors.append("候选目录不存在")
    for required in sorted(REQUIRED):
        if not (root / required).is_file():
            errors.append(f"缺少发布文件：{required}")
    version_path = root / "VERSION"
    if version_path.is_file() and version_path.read_text(encoding="utf-8-sig").strip() != "19.0.1":
        errors.append("VERSION 必须为 19.0.1")
    if root.is_dir():
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
            relative = path.relative_to(root).as_posix()
            if is_link_or_junction(path):
                errors.append(f"禁止符号链接或目录联接：{relative}")
                continue
            for token in args.forbidden_token:
                if token and token.casefold() in relative.casefold():
                    errors.append(f"文件名含项目私有词：{relative}")
            if path.is_dir():
                if path.name in FORBIDDEN_DIRS:
                    errors.append(f"禁止发布目录：{relative}")
                continue
            checked += 1
            file_size = path.stat().st_size
            total_bytes += file_size
            if path.name == ".DS_Store" or path.name.startswith("~$") or path.suffix.lower() in FORBIDDEN_SUFFIXES:
                errors.append(f"禁止发布临时文件：{relative}")
                continue
            if file_size > 10 * 1024 * 1024:
                errors.append(f"单文件超过RedSkill 10MB限制：{relative}")
            if path.suffix.lower() in TEXT_SUFFIXES:
                try:
                    text = path.read_text(encoding="utf-8-sig")
                except UnicodeDecodeError:
                    errors.append(f"文本文件不是 UTF-8：{relative}")
                    continue
            else:
                text = path.read_bytes().decode("latin-1", errors="ignore")
            if LOCAL_PATH.search(text):
                errors.append(f"发现本机绝对路径：{relative}")
            if SECRET.search(text):
                errors.append(f"发现疑似凭据：{relative}")
            for token in args.forbidden_token:
                if token and token.casefold() in text.casefold():
                    errors.append(f"发现项目私有词：{relative}")
            if path.suffix.lower() == ".py":
                try:
                    compile(text, relative, "exec")
                except SyntaxError as exc:
                    errors.append(f"Python语法错误：{relative}:{exc.lineno}")
    if total_bytes > 30 * 1024 * 1024:
        errors.append("解压后文件总大小超过RedSkill 30MB限制")
    result = {
        "status": "PASS" if not errors else "BLOCKED",
        "checked_files": checked,
        "total_bytes": total_bytes,
        "errors": list(dict.fromkeys(errors)),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['status']}: checked {checked} files")
        for error in result["errors"]:
            print(f"- {error}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
