#!/usr/bin/env python3
"""Synthetic regression for intake and proof-object legal hard gates."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from PIL import Image


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from build_evidence_bundle import ManifestError, validate_manifest  # noqa: E402


def expect_error(data: dict, base: Path, needle: str, allow_draft: bool = False) -> None:
    try:
        validate_manifest(data, base, allow_draft=allow_draft)
    except ManifestError as exc:
        assert needle in str(exc), str(exc)
    else:
        raise AssertionError(f"expected error containing {needle}")


def make_legal_fixture(base: Path) -> dict:
    image = base / "synthetic.png"
    Image.new("RGB", (64, 64), "#205080").save(image)
    checks = {
        "identity_checked": {"status": "not_applicable", "note": "全合成色块不涉及主体身份。"},
        "dates_checked": {"status": "not_applicable", "note": "全合成色块不涉及事件日期。"},
        "amounts_checked": {"status": "not_applicable", "note": "全合成色块不涉及金额。"},
        "payment_status_checked": {"status": "not_applicable", "note": "全合成色块不涉及付款。"},
        "proof_scope_checked": {"status": "resolved", "material_refs": ["M001"], "note": "仅核对合成色块。"},
        "original_carrier_checked": {"status": "resolved", "material_refs": ["M001"], "note": "回指本测试生成的合成原图。"},
    }
    return {
        "schema_version": 2,
        "case_info": "全合成法律门禁测试",
        "submitter": "合成提交方",
        "intake_clarification": {
            "status": "not_required",
            "reason": "合成请求、证明用途及载体均由本测试明确给出。",
            "required_categories": [],
        },
        "validation": {"status": "resolved", "checks": checks, "unresolved_issues": []},
        "proof_targets": [{
            "target_kind": "claim",
            "target_id": "REQ-01",
            "description": "本测试第1项请求：核对合成画面颜色",
            "legal_elements": ["画面颜色与请求描述一致"],
        }],
        "evidence_groups": [{
            "number": 1,
            "group_id": "G01",
            "evidence_name": "全合成蓝色色块",
            "evidence_form": "电子数据打印件",
            "proof_object": "合成测试画面为蓝色色块；对应本测试第1项请求中的画面颜色核对事实。",
            "materials": [{
                "material_id": "M001",
                "path": "synthetic.png",
                "source": "本测试生成的全合成原图",
                "original_carrier": {"path": "synthetic.png", "carrier_type": "native_image"},
                "fact": "蓝色合成画面",
                "readability": "clear",
            }],
        }],
        "proof_claims": [{
            "claim_id": "C001",
            "group_id": "G01",
            "text": "M001全图显示蓝色色块，拟核对合成画面的颜色。",
            "type": "fact",
            "fact_level": "element_fact",
            "role": "direct",
            "purpose": "用于支持合成请求关于画面颜色的核对。",
            "purpose_basis": {
                "kind": "pleading",
                "reference": "本测试内置合成请求第1项",
                "status": "confirmed",
                "target_kind": "claim",
                "target_id": "REQ-01",
                "legal_element": "画面颜色与请求描述一致",
            },
            "material_refs": [{"material_id": "M001", "page": 1, "region": "全图"}],
            "boundary": "仅用于合成测试，不涉及真实主体、金额或法律责任。",
        }],
    }


def main() -> None:
    temp = tempfile.TemporaryDirectory(prefix="evidence-v18-legal-")
    base = Path(temp.name)
    original = make_legal_fixture(base)
    validate_manifest(copy.deepcopy(original), base)

    pending = copy.deepcopy(original)
    pending["intake_clarification"] = {
        "status": "pending",
        "required_categories": ["书状"],
        "rounds": [],
    }
    expect_error(pending, base, "CLARIFICATION_REQUIRED", allow_draft=True)

    defensive = copy.deepcopy(original)
    defensive["evidence_groups"][0]["proof_object"] = "仍待核，不能单独证明，尚需补强。"
    expect_error(defensive, base, "仅含核验、补强或证明边界提示")

    risky_texts = (
        "拟证明该账号昵称就是被告本人；用于支持其承担责任。",
        "拟证明对方说会还，因此欠款成立；用于支持本案请求。",
        "拟证明申请额等于实际支付额；用于支持付款请求。",
        "拟证明关联判决当然确定本案事实；用于支持本案请求。",
        "拟证明被告当然承担连带责任；用于支持胜诉请求。",
    )
    for text in risky_texts:
        risky = copy.deepcopy(original)
        risky["evidence_groups"][0]["proof_object"] = text
        expect_error(risky, base, "高风险")

    declined = copy.deepcopy(original)
    declined["intake_clarification"] = {
        "status": "completed",
        "required_categories": ["书状"],
        "rounds": [{
            "round_id": "Q001",
            "questions": [{
                "category": "书状",
                "question": "请提供书状，以确认材料服务的具体请求。",
                "user_choice": "declined",
                "response_reference": "用户在本次合成测试中明确选择不提供书状。",
            }],
        }],
    }
    declined["proof_claims"][0]["purpose_basis"] = {
        "kind": "materials_only",
        "reference": "仅按当前合成材料暂定用途",
        "status": "provisional",
    }
    declined["validation"]["status"] = "unresolved"
    declined["validation"]["unresolved_issues"] = [
        "信息缺失[书状][用户选择不提供]：未提供书状；影响：证明用途与请求的对应关系只能暂定。"
    ]
    expect_error(declined, base, "不得据此生成正式版")
    draft = validate_manifest(declined, base, allow_draft=True)
    assert draft["_effective_draft"] is True
    temp.cleanup()

    print("v18 intake and proof-object legal gates: PASS")


if __name__ == "__main__":
    main()
