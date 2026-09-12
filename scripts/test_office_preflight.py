#!/usr/bin/env python3
"""Small synthetic self-check for v18 mixed-directory and OOXML preflight."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


CONTENT_TYPES_XLSX = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""

WORKBOOK = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="金额表" sheetId="1" state="visible" r:id="rId1"/></sheets>
</workbook>"""

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""

SHEET = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <cols><col min="5" max="6" hidden="1"/></cols>
  <sheetData><row r="1"><c r="A1"><f>1+1</f></c></row></sheetData>
</worksheet>"""

CONTENT_TYPES_PPTX = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>"""

PRESENTATION = """<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>
</p:presentation>"""

PRESENTATION_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="slide" Target="slides/slide1.xml"/>
</Relationships>"""

SLIDE = """<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld/></p:sld>"""

CONTENT_TYPES_DOCX = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

DOCUMENT = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>synthetic</w:t></w:r></w:p></w:body>
</w:document>"""


def make_xlsx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XLSX)
        zf.writestr("xl/workbook.xml", WORKBOOK)
        zf.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        zf.writestr("xl/worksheets/sheet1.xml", SHEET)


def make_pptx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_PPTX)
        zf.writestr("ppt/presentation.xml", PRESENTATION)
        zf.writestr("ppt/_rels/presentation.xml.rels", PRESENTATION_RELS)
        zf.writestr("ppt/slides/slide1.xml", SLIDE)
        zf.writestr("ppt/notesSlides/notesSlide1.xml", "<notes/>")
        zf.writestr("ppt/embeddings/Workbook1.xlsx", b"synthetic")


def make_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_DOCX)
        zf.writestr("word/document.xml", DOCUMENT)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def main() -> None:
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="evidence-office-v18-") as temp:
        base = Path(temp)
        inputs = base / "inputs"
        outputs = base / "outputs"
        inputs.mkdir()
        make_xlsx(inputs / "sample.xlsx")
        make_pptx(inputs / "sample.pptx")
        make_docx(inputs / "sample.docx")
        (inputs / "broken.xlsx").write_bytes(b"not-a-zip")
        (inputs / "~$locked.xlsx").write_bytes(b"lock")
        (inputs / ".DS_Store").write_bytes(b"metadata")
        (inputs / "note.txt").write_text("not office", encoding="utf-8")

        office_json = outputs / "office.json"
        result = run(
            [sys.executable, str(scripts / "inspect_office_materials.py"), str(inputs), "--output", str(office_json)]
        )
        assert result.returncode == 1, result.stdout + result.stderr
        office = json.loads(office_json.read_text(encoding="utf-8"))
        assert office["office_file_count"] == 4
        assert office["technical_skip_count"] == 2
        assert office["ignored_non_office_count"] == 1
        assert office["overall_status"] == "BLOCKED"
        by_name = {item["relative_path"]: item for item in office["files"]}
        assert "OFFICE_HIDDEN_CONTENT" in by_name["sample.xlsx"]["failure_codes"]
        assert "OFFICE_PRINT_SCOPE_UNRESOLVED" in by_name["sample.xlsx"]["failure_codes"]
        assert "OFFICE_FORMULA_CACHE_UNVERIFIED" in by_name["sample.xlsx"]["failure_codes"]
        assert "PPT_NOTES_OR_COMMENTS_PRESENT" in by_name["sample.pptx"]["failure_codes"]
        assert "PPT_EMBEDDED_OBJECT" in by_name["sample.pptx"]["failure_codes"]
        assert by_name["sample.docx"]["status"] == "PASS"
        assert by_name["broken.xlsx"]["status"] == "BLOCKED"
        assert all("absolute_path" not in item for item in office["files"])

        image_json = outputs / "images.json"
        result = run(
            [sys.executable, str(scripts / "inspect_materials.py"), str(inputs), "--output", str(image_json)]
        )
        assert result.returncode == 1, result.stdout + result.stderr
        image_inventory = json.loads(image_json.read_text(encoding="utf-8"))
        assert len(image_inventory["technical_skips"]) == 2
        assert image_inventory["file_count"] == 7

    print("v18 synthetic Office preflight: PASS")


if __name__ == "__main__":
    main()
