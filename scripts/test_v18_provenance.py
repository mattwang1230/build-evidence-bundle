#!/usr/bin/env python3
"""Synthetic, privacy-safe checks for the v18 Office provenance hard gate."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from validate_provenance import validate_office_provenance
from build_evidence_bundle import ManifestError, build_document


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
WORKBOOK = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sheet1" sheetId="1" state="visible" r:id="rId1"/></sheets>
  <definedNames><definedName name="_xlnm.Print_Area" localSheetId="0">'Sheet1'!$A$1:$B$2</definedName></definedNames>
</workbook>"""
RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
SHEET = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData>
</worksheet>"""
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="
)


def write_png(path: Path, color: str = "#205080", metadata: str | None = None) -> None:
    info = PngInfo()
    if metadata:
        info.add_text("source", metadata)
    Image.new("RGB", (32, 32), color).save(path, format="PNG", pnginfo=info)


def write_pdf(path: Path, *, metadata: str = "") -> None:
    path.write_bytes(f"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\n{metadata}\n%%EOF\n".encode("latin-1"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_xlsx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("xl/workbook.xml", WORKBOOK)
        zf.writestr("xl/_rels/workbook.xml.rels", RELS)
        zf.writestr("xl/worksheets/sheet1.xml", SHEET)


def make_manifest(root: Path) -> tuple[dict, Path]:
    source = root / "input" / "source.xlsx"
    page = root / "derived" / "page-001.png"
    pdf = root / "derived" / "source.pdf"
    source.parent.mkdir()
    page.parent.mkdir()
    make_xlsx(source)
    write_png(page)
    write_pdf(pdf)
    source_hash = digest(source)
    sidecar = {
        "schema_version": 1,
        "route": "v2_sidecar",
        "source_snapshot": [{
            "source_id": "O001",
            "relative_path": "input/source.xlsx",
            "source_kind": "native_office",
            "size": source.stat().st_size,
            "mtime_ns": source.stat().st_mtime_ns,
            "sha256": source_hash,
            "read_before": source_hash,
            "read_after": source_hash,
            "unchanged": True,
            "read_only": True,
        }],
        "package_inspection": [{
            "source_id": "O001",
            "format": "xlsx",
            "zip_valid": True,
            "content_type_valid": True,
            "encrypted": False,
            "macros": "absent",
            "external_links": "absent",
            "comments_notes": "absent",
            "hidden_content": "absent",
            "embedded_objects": "absent",
            "status": "pass",
        }],
        "source_locators": [{
            "source_id": "O001",
            "unit_id": "O001-U001",
            "kind": "xlsx_range",
            "sheet_index": 1,
            "sheet_name": "Sheet1",
            "cell_range": "'Sheet1'!$A$1:$B$2",
            "slide_index": None,
            "part": "xl/worksheets/sheet1.xml",
            "shape_id": None,
            "visibility": "visible",
            "user_confirmed_scope": True,
        }],
        "conversion_record": [{
            "source_id": "O001",
            "tool": "LibreOffice",
            "tool_version": "synthetic-test-version",
            "platform": "test",
            "arguments_summary": "headless; isolated profile; fixed output directory",
            "profile_isolated": True,
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "pdf_relative_path": "derived/source.pdf",
            "pdf_sha256": digest(pdf),
            "pdf_page_count": 1,
            "rasterizer": "pdftoppm",
            "rasterizer_version": "synthetic-test-version",
            "status": "pass",
        }],
        "page_map": [{
            "unit_id": "O001-U001",
            "pdf_page": 1,
            "rendered_relative_path": "derived/page-001.png",
            "rendered_sha256": digest(page),
            "attachment_ordinal": 1,
            "docx_bookmark": "evidence_page_0001",
            "docx_physical_page": None,
            "blank_page": False,
            "header_only": False,
            "font_substitution": "none",
            "privacy_review": "pass",
        }],
        "formal_release_gate": {"status": "PASS", "failure_codes": []},
    }
    sidecar_path = root / "provenance" / "office-provenance.json"
    sidecar_path.parent.mkdir()
    sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "bundle_contract": "v18",
        "provenance_route": "v2_sidecar",
        "office_provenance": "provenance/office-provenance.json",
        "evidence_groups": [{
            "number": 1,
            "group_id": "G01",
            "evidence_name": "合成工作簿阅卷页",
            "evidence_form": "电子数据打印件",
            "proof_object": "拟证明合成测试中的数值记录；用于支持合成测试请求。",
            "materials": [{
                "material_id": "M001",
                "origin_kind": "office_derived",
                "path": "derived/page-001.png",
                "provenance_ref": {"unit_id": "O001-U001", "pdf_page": 1},
            }],
        }],
    }
    return manifest, sidecar_path


def assert_blocked(code: str, mutate) -> None:
    with tempfile.TemporaryDirectory(prefix="evidence-v18-provenance-case-") as temp:
        root = Path(temp)
        manifest, sidecar_path = make_manifest(root)
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        mutate(root, manifest, sidecar, sidecar_path)
        if sidecar_path.exists():
            sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
        fatal, _, _ = validate_office_provenance(manifest, root)
        assert any(code in item for item in fatal), (code, fatal)


def main() -> None:
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="evidence-v18-provenance-pass-") as temp:
        root = Path(temp)
        manifest, _ = make_manifest(root)
        fatal, blockers, warnings = validate_office_provenance(manifest, root)
        assert not fatal and not blockers, fatal + blockers + warnings

    assert_blocked(
        "OFFICE_FORMAL_GATE_NOT_PASS",
        lambda _root, _manifest, sidecar, _path: sidecar.update(
            formal_release_gate={"status": "HOLD", "failure_codes": ["RENDER_REVIEW_UNAVAILABLE"]}
        ),
    )

    def change_mtime(root, _manifest, _sidecar, _path):
        source = root / "input" / "source.xlsx"
        stat = source.stat()
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert_blocked("OFFICE_SOURCE_CHANGED", change_mtime)
    assert_blocked(
        "OFFICE_SOURCE_LOCATOR_INVALID",
        lambda _root, _manifest, sidecar, _path: sidecar["source_locators"][0].update(
            sheet_index=99, sheet_name="Missing", part="xl/worksheets/missing.xml"
        ),
    )
    assert_blocked(
        "OFFICE_PAGE_MAP_MISMATCH",
        lambda _root, _manifest, sidecar, _path: sidecar["page_map"][0].update(pdf_page=999),
    )
    assert_blocked(
        "OFFICE_CONVERTER_VERSION_UNKNOWN",
        lambda _root, _manifest, sidecar, _path: sidecar["conversion_record"][0].update(tool_version="unknown"),
    )
    assert_blocked(
        "PROVENANCE_PATH_UNSAFE",
        lambda _root, manifest, _sidecar, _path: manifest.update(office_provenance="C" + r":\private\sidecar.json"),
    )

    def corrupt_png(root, _manifest, sidecar, _path):
        page = root / "derived" / "page-001.png"
        page.write_bytes(b"not-a-png")
        sidecar["page_map"][0]["rendered_sha256"] = digest(page)

    assert_blocked("OFFICE_RENDERED_ARTIFACT_INVALID", corrupt_png)

    def blank_png(root, _manifest, sidecar, _path):
        page = root / "derived" / "page-001.png"
        write_png(page, "white")
        sidecar["page_map"][0]["rendered_sha256"] = digest(page)

    assert_blocked("OFFICE_BLANK_PAGE", blank_png)

    def private_png(root, _manifest, sidecar, _path):
        page = root / "derived" / "page-001.png"
        write_png(page, metadata="C" + r":\Users\demo\source.xlsx")
        sidecar["page_map"][0]["rendered_sha256"] = digest(page)

    assert_blocked("OFFICE_PRIVACY_REVIEW_FAILED", private_png)

    def unsupported_source(root, _manifest, sidecar, _path):
        source = root / "input" / "source.xlsx"
        target = source.with_suffix(".xls")
        source.replace(target)
        snapshot = sidecar["source_snapshot"][0]
        snapshot.update(
            relative_path="input/source.xls",
            size=target.stat().st_size,
            mtime_ns=target.stat().st_mtime_ns,
            sha256=digest(target),
            read_before=digest(target),
            read_after=digest(target),
        )

    assert_blocked("OFFICE_FORMAT_UNSUPPORTED", unsupported_source)

    with tempfile.TemporaryDirectory(prefix="evidence-v18-provenance-direct-") as temp:
        root = Path(temp)
        manifest, sidecar_path = make_manifest(root)
        sidecar_path.unlink()
        manifest["_preflight"] = {}
        output = root / "direct.docx"
        try:
            build_document(manifest, output, root, allow_draft=True)
        except ManifestError as exc:
            assert "OFFICE_PROVENANCE_MISSING" in str(exc)
        else:
            raise AssertionError("build_document direct call bypassed Office provenance gate")
        assert not output.exists()

        manifest_path = root / "manifest.json"
        manifest.pop("_preflight", None)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(scripts / "build_evidence_bundle.py"), str(manifest_path), str(output), "--allow-draft"],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
        assert "OFFICE_PROVENANCE_MISSING" in result.stdout + result.stderr
        assert not output.exists()

    old_v2 = {"schema_version": 2, "evidence_groups": [{"materials": [{"material_id": "M001", "path": "image.png"}]}]}
    assert validate_office_provenance(old_v2, Path.cwd()) == ([], [], [])

    with tempfile.TemporaryDirectory(prefix="evidence-v18-origin-field-") as temp:
        root = Path(temp)
        manifest, _ = make_manifest(root)
        material = manifest["evidence_groups"][0]["materials"][0]
        material["material_kind"] = material.pop("origin_kind")
        fatal, _, _ = validate_office_provenance(manifest, root)
        assert any("MATERIAL_ORIGIN_REQUIRED" in item for item in fatal), fatal

    print("v18 Office provenance hard gate: PASS")


if __name__ == "__main__":
    main()
