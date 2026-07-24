#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


ALLOWED_IMAGES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff"}
CHECK_KEYS = {
    "identity_checked",
    "dates_checked",
    "amounts_checked",
    "payment_status_checked",
    "proof_scope_checked",
}


def resolve_material_path(raw_path, base_dir: Path) -> Path:
    path = Path(os.path.expandvars(raw_path)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def set_run_font(run, name="宋体", size=12, bold=None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold


def set_cell_border(cell):
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = "w:" + edge
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "8")
        element.set(qn("w:color"), "000000")


def set_repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def validate_manifest(data, base_dir: Path, allow_draft=False):
    errors = []
    for field in ("case_info", "submitter"):
        if not str(data.get(field, "")).strip():
            errors.append(f"缺少 {field}")

    groups = data.get("evidence_groups")
    if not isinstance(groups, list) or not groups:
        errors.append("evidence_groups 必须是非空数组")
        groups = []

    expected = list(range(1, len(groups) + 1))
    actual = [group.get("number") for group in groups]
    if actual != expected:
        errors.append(f"编号必须从1连续递增，当前为：{actual}")

    paths_seen = set()
    for group in groups:
        number = group.get("number", "?")
        for field in ("evidence_name", "evidence_form", "proof_object"):
            if not str(group.get(field, "")).strip():
                errors.append(f"第{number}组缺少 {field}")
        materials = group.get("materials")
        if not isinstance(materials, list) or not materials:
            errors.append(f"第{number}组 materials 必须为非空数组")
            continue
        for item in materials:
            raw_path = item.get("path") if isinstance(item, dict) else None
            if not raw_path:
                errors.append(f"第{number}组存在没有 path 的材料")
                continue
            path = resolve_material_path(raw_path, base_dir)
            if not path.is_file():
                errors.append(f"材料不存在：{path}")
            elif path.suffix.lower() not in ALLOWED_IMAGES:
                errors.append(f"标准卷仅接受图片，需先截帧或转换：{path}")
            key = os.path.normcase(str(path))
            if key in paths_seen and not item.get("allow_duplicate"):
                errors.append(f"同一路径重复使用且未说明：{path}")
            paths_seen.add(key)

    validation = data.get("validation", {})
    unresolved = validation.get("unresolved_issues", [])
    checks = validation.get("checks", {})
    if not allow_draft:
        if validation.get("status") != "resolved":
            errors.append("validation.status 必须为 resolved")
        if unresolved:
            errors.append("仍有未解决事项：" + "；".join(map(str, unresolved)))
        missing_checks = sorted(key for key in CHECK_KEYS if checks.get(key) is not True)
        if missing_checks:
            errors.append("以下核对项尚未确认：" + ", ".join(missing_checks))

    if errors:
        raise ValueError("\n".join(f"- {error}" for error in errors))


def add_text(paragraph, text, size=12, bold=False, align=None):
    if align is not None:
        paragraph.alignment = align
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run(text)
    set_run_font(run, size=size, bold=bold)
    return run


def fit_picture(run, path, max_width_cm, max_height_cm):
    from PIL import Image

    with Image.open(path) as image:
        width_px, height_px = image.size
    ratio = width_px / height_px
    max_ratio = max_width_cm / max_height_cm
    if ratio >= max_ratio:
        return run.add_picture(str(path), width=Cm(max_width_cm))
    return run.add_picture(str(path), height=Cm(max_height_cm))


def build_document(data, output_path: Path, base_dir: Path, allow_draft=False):
    document = Document()
    section = document.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.175)
    section.right_margin = Cm(3.175)

    normal = document.styles["Normal"]
    normal.font.name = "宋体"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.font.size = Pt(12)

    title = document.add_paragraph()
    add_text(title, "证据清单", size=18, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    title.paragraph_format.space_after = Pt(6)

    if allow_draft:
        warning = document.add_paragraph()
        run = add_text(
            warning,
            "待核对草稿：不得作为正式举证版本",
            size=12,
            bold=True,
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )
        run.font.color.rgb = RGBColor(192, 0, 0)

    add_text(document.add_paragraph(), f"案件信息：{data.get('case_info', '')}", bold=True)
    add_text(document.add_paragraph(), f"提交方：{data.get('submitter', '')}", bold=True)
    signer = data.get("signer", "")
    date = data.get("submission_date", "")
    add_text(document.add_paragraph(), f"提交人签名：{signer}                提交时间：{date}", bold=True)

    groups = data["evidence_groups"]
    table = document.add_table(rows=1, cols=5)
    table.style = "Normal Table"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    widths = [Cm(0.78), Cm(3.94), Cm(1.35), Cm(1.64), Cm(6.94)]
    headers = ["编号", "证据名称", "页数", "证据形式", "证明对象"]
    set_repeat_table_header(table.rows[0])
    for index, (cell, text) in enumerate(zip(table.rows[0].cells, headers)):
        cell.width = widths[index]
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        set_cell_border(cell)
        paragraph = cell.paragraphs[0]
        add_text(paragraph, text, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)

    for group in groups:
        row = table.add_row()
        values = [
            str(group["number"]),
            group["evidence_name"],
            str(len(group["materials"])),
            group["evidence_form"],
            group["proof_object"],
        ]
        for index, (cell, text) in enumerate(zip(row.cells, values)):
            cell.width = widths[index]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_border(cell)
            align = WD_ALIGN_PARAGRAPH.CENTER if index in (0, 2, 3) else WD_ALIGN_PARAGRAPH.LEFT
            add_text(cell.paragraphs[0], text, align=align)

    document.add_page_break()
    flattened = []
    for group in groups:
        for material in group["materials"]:
            flattened.append((group["number"], material))

    for index, (_, material) in enumerate(flattened):
        if index > 0:
            document.add_page_break()
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        run = paragraph.add_run()
        path = resolve_material_path(material["path"], base_dir)
        fit_picture(run, path, max_width_cm=14.65, max_height_cm=24.62)

    core = document.core_properties
    core.title = "证据清单及证据材料"
    core.subject = data.get("case_info", "")
    core.author = data.get("submitter", "")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)


def main():
    parser = argparse.ArgumentParser(description="生成证据清单＋内嵌证据材料 DOCX")
    parser.add_argument("manifest")
    parser.add_argument("output")
    parser.add_argument("--allow-draft", action="store_true")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        validate_manifest(data, manifest_path.parent, allow_draft=args.allow_draft)
        output_path = Path(args.output).resolve()
        build_document(data, output_path, manifest_path.parent, allow_draft=args.allow_draft)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"生成失败：\n{error}") from None
    print(f"已生成：{output_path}")
    print(f"证据组：{len(data['evidence_groups'])}；材料页：{sum(len(g['materials']) for g in data['evidence_groups'])}")


if __name__ == "__main__":
    main()
