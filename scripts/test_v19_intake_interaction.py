#!/usr/bin/env python3
"""Synthetic regression for v19 field-bound intake interaction."""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path
from typing import Any

from build_evidence_bundle import (  # noqa: E402
    ManifestError,
    _amount_payment_blockers,
    _intake_clarification_gate,
    normalise_manifest,
    validate_manifest,
)
from test_v18_legal_gates import make_legal_fixture  # noqa: E402


def locator(turn: str) -> dict[str, Any]:
    return {
        "kind": "conversation_turn",
        "reference": turn,
        "message_id": None,
    }


def amount_value(*, deduct_again: bool = False) -> dict[str, Any]:
    return {
        "source_amounts": [
            {"amount": 200000, "source_ref": "M-A1:p1:合同总额"},
            {"amount": 150000, "source_ref": "M-A2:p1:本次主张"},
            {"amount": 128000, "source_ref": "M-A1:p1:尚欠余额"},
        ],
        "calculation_results": [
            {"expression": "200000-72000", "result": 128000, "source_refs": ["M-A1:p1"]}
        ],
        "gross_due": 200000,
        "historical_paid": 72000,
        "net_outstanding": 128000,
        "adopted_amount": 128000,
        "amount_kind": "net_outstanding",
        "historical_payments_already_deducted": True,
        "deduct_historical_payments": deduct_again,
    }


def question(
    question_id: str,
    *,
    category: str,
    entity_ref: str,
    field_key: str,
    text: str,
    raw_response: str,
    normalized_value: Any,
    user_choice: str = "provided",
    resolution_status: str = "resolved",
    context_kind: str = "free_text",
    options: list[Any] | None = None,
    summary_fields: list[str] | None = None,
    summary_values: dict[str, Any] | None = None,
    basis_kind: str = "direct_answer",
    selected_option_id: str | None = None,
    summary_id: str | None = None,
    source_refs: list[str] | None = None,
    ambiguities: list[str] | None = None,
    depends_on: list[str] | None = None,
    supersedes_question_id: str | None = None,
    proposition: str | None = None,
    response_reference: str | None = None,
    raw_response_fragment: str | None = None,
    summary_snapshot: str | None = None,
    context_reference: str | None = None,
) -> dict[str, Any]:
    version = f"{question_id}-context-v1"
    basis: dict[str, Any] = {
        "kind": basis_kind,
        "question_id": question_id,
        "context_version": version,
    }
    if selected_option_id is not None:
        basis["selected_option_id"] = selected_option_id
    if summary_id is not None:
        basis["summary_id"] = summary_id
    if source_refs is not None:
        basis["source_refs"] = source_refs
    if raw_response_fragment is not None:
        basis["raw_response_fragment"] = raw_response_fragment
    item: dict[str, Any] = {
        "question_id": question_id,
        "category": category,
        "entity_ref": entity_ref,
        "field_key": field_key,
        "question": text,
        "depends_on": depends_on or [],
        "answer_context": {
            "kind": context_kind,
            "version": version,
            "options": options or [],
            "summary_fields": summary_fields or [],
            "summary_values": summary_values or {},
        },
        "user_choice": user_choice,
        "answer_binding": {
            "raw_response": raw_response,
            "response_locator": locator(response_reference or f"合成对话/{question_id}"),
            "normalized_value": normalized_value,
            "binding_basis": basis,
            "resolution_status": resolution_status,
            "ambiguities": ambiguities or [],
            "fact_verification": "not_verified_by_intake",
        },
    }
    if summary_id is not None:
        item["answer_context"]["summary_id"] = summary_id
        item["answer_context"]["summary_snapshot"] = summary_snapshot or f"{summary_id}：{summary_values}"
        item["answer_context"]["context_locator"] = locator(
            context_reference or f"合成对话/{question_id}/summary"
        )
    if proposition is not None:
        item["answer_context"]["proposition"] = proposition
    if supersedes_question_id is not None:
        item["supersedes_question_id"] = supersedes_question_id
    return item


def intake_data(
    rounds: list[list[dict[str, Any]]],
    *,
    issues: list[str] | None = None,
    mode: str = "continue_build",
    stop_raw_response: str | None = None,
    stop_response_reference: str = "合成对话/停止决定",
) -> dict[str, Any]:
    questions = [item for round_items in rounds for item in round_items]
    required: list[str] = []
    unresolved_fields: list[str] = []
    for item in questions:
        if item["category"] not in required:
            required.append(item["category"])
        if item["answer_binding"]["resolution_status"] != "resolved":
            unresolved_fields.append(f"{item['entity_ref']}:{item['field_key']}")
    return {
        "context_materials": [
            {"material_id": "M-A1"},
            {"material_id": "M-A2"},
        ],
        "intake_clarification": {
            "protocol": "field_binding_v1",
            "status": "completed",
            "required_categories": required,
            "rounds": [
                {"round_id": f"R{index:02d}", "questions": items}
                for index, items in enumerate(rounds, start=1)
            ],
            "stop_decision": {
                "mode": mode,
                "reason": "用户已要求制作；不再索取已解决字段。",
                "raw_response": stop_raw_response or (
                    "先做内部核对稿" if mode == "internal_review_draft" else "开始制作"
                ),
                "response_locator": locator(stop_response_reference),
                "unresolved_fields": unresolved_fields,
            },
        },
        "validation": {
            "status": "unresolved" if issues else "resolved",
            "unresolved_issues": issues or [],
        },
    }


def expect_gate_error(data: dict[str, Any], needle: str) -> None:
    fatal, _ = _intake_clarification_gate(copy.deepcopy(data))
    assert fatal and needle in "\n".join(fatal), fatal


def assert_gate_passes(data: dict[str, Any]) -> list[str]:
    fatal, blockers = _intake_clarification_gate(copy.deepcopy(data))
    assert not fatal, fatal
    return blockers


def expect_manifest_error(data: dict[str, Any], base: Path) -> None:
    try:
        validate_manifest(data, base)
    except ManifestError:
        return
    raise AssertionError("expected the original formal/source gate to block")


def main() -> None:
    # I01: a material lookup is reviewable and the same field is not asked again.
    lookup = question(
        "Q-I01",
        category="金额",
        entity_ref="AMT-A",
        field_key="amount.claimed",
        text="材料中的金额采用哪一口径？",
        raw_response="材料里有。",
        normalized_value=amount_value(),
        basis_kind="material_lookup",
        source_refs=["M-A1:p1", "M-A2:p1"],
    )
    lookup_data = intake_data([[lookup]])
    assert_gate_passes(lookup_data)
    missing_source = copy.deepcopy(lookup_data)
    missing_source["intake_clarification"]["rounds"][0]["questions"][0]["answer_binding"]["binding_basis"]["source_refs"] = []
    expect_gate_error(missing_source, "source_refs")
    empty_message_id = copy.deepcopy(lookup_data)
    empty_message_id["intake_clarification"]["rounds"][0]["questions"][0]["answer_binding"]["response_locator"]["message_id"] = ""
    expect_gate_error(empty_message_id, "必须为 null")
    missing_message_id = copy.deepcopy(lookup_data)
    del missing_message_id["intake_clarification"]["rounds"][0]["questions"][0]["answer_binding"]["response_locator"]["message_id"]
    expect_gate_error(missing_message_id, "显式保存 message_id")
    duplicate = copy.deepcopy(lookup)
    duplicate["question_id"] = "Q-I01-REPEAT"
    duplicate["answer_binding"]["binding_basis"]["question_id"] = "Q-I01-REPEAT"
    duplicate["answer_context"]["version"] = "Q-I01-REPEAT-context-v1"
    duplicate["answer_binding"]["binding_basis"]["context_version"] = "Q-I01-REPEAT-context-v1"
    expect_gate_error(intake_data([[lookup], [duplicate]]), "supersedes_question_id")
    missing_category = copy.deepcopy(lookup_data)
    missing_category["intake_clarification"]["required_categories"].append("日期")
    expect_gate_error(missing_category, "缺失类别")
    four_questions: list[dict[str, Any]] = []
    for index in range(4):
        item = copy.deepcopy(lookup)
        item["question_id"] = f"Q-COUNT-{index}"
        item["entity_ref"] = f"AMT-{index}"
        item["field_key"] = f"amount.source_{index}"
        version = f"Q-COUNT-{index}-context-v1"
        item["answer_context"]["version"] = version
        item["answer_binding"]["binding_basis"].update({
            "question_id": item["question_id"],
            "context_version": version,
        })
        four_questions.append(item)
    expect_gate_error(intake_data([four_questions]), "1—3个问题")

    # I17: the user may authorize the AI to decide one field from already
    # authorized materials.  This is process authorization, not a supplied or
    # independently verified case fact.
    material_review = question(
        "Q-MATERIAL-REVIEW",
        category="金额",
        entity_ref="AMT-A",
        field_key="amount.claimed",
        text="是否由AI回查已授权材料后判断本次采用金额？",
        raw_response="请AI自己通过材料判定。",
        normalized_value=amount_value(),
        user_choice="material_review",
        basis_kind="material_lookup",
        source_refs=["M-A1:p1:尚欠余额", "M-A2:p1:本次主张"],
    )
    assert_gate_passes(intake_data([[material_review]]))

    material_review_computed = copy.deepcopy(material_review)
    material_review_computed["question_id"] = "Q-MATERIAL-REVIEW-COMPUTED"
    material_review_computed["answer_context"]["version"] = "Q-MATERIAL-REVIEW-COMPUTED-context-v1"
    material_review_computed["answer_binding"]["binding_basis"].update({
        "kind": "computed",
        "question_id": "Q-MATERIAL-REVIEW-COMPUTED",
        "context_version": "Q-MATERIAL-REVIEW-COMPUTED-context-v1",
    })
    assert_gate_passes(intake_data([[material_review_computed]]))

    review_without_material_basis = copy.deepcopy(material_review)
    review_without_material_basis["answer_binding"]["binding_basis"]["kind"] = "direct_answer"
    expect_gate_error(intake_data([[review_without_material_basis]]), "material_lookup 或 computed")

    review_without_source = copy.deepcopy(material_review)
    review_without_source["answer_binding"]["binding_basis"]["source_refs"] = []
    expect_gate_error(intake_data([[review_without_source]]), "source_refs")

    review_without_result = copy.deepcopy(material_review)
    review_without_result["answer_binding"]["normalized_value"] = None
    expect_gate_error(intake_data([[review_without_result]]), "非空 normalized_value")

    review_without_authorization = copy.deepcopy(material_review)
    review_without_authorization["answer_binding"]["raw_response"] = "128000元。"
    expect_gate_error(intake_data([[review_without_authorization]]), "语义不一致")

    review_negated = copy.deepcopy(material_review)
    review_negated["answer_binding"]["raw_response"] = "不要由AI通过材料判断。"
    expect_gate_error(intake_data([[review_negated]]), "语义不一致")
    review_cannot = copy.deepcopy(material_review)
    review_cannot["answer_binding"]["raw_response"] = "AI不能通过材料判断。"
    expect_gate_error(intake_data([[review_cannot]]), "语义不一致")

    review_natural_decide = copy.deepcopy(material_review)
    review_natural_decide["answer_binding"]["raw_response"] = "请AI依据现有材料决定。"
    assert_gate_passes(intake_data([[review_natural_decide]]))
    review_natural_lookup = copy.deepcopy(material_review)
    review_natural_lookup["answer_binding"]["raw_response"] = "让AI自己查材料。"
    assert_gate_passes(intake_data([[review_natural_lookup]]))

    review_merely_points_to_materials = copy.deepcopy(material_review)
    review_merely_points_to_materials["answer_binding"]["raw_response"] = "材料里有。"
    expect_gate_error(intake_data([[review_merely_points_to_materials]]), "语义不一致")

    review_unknown_source = copy.deepcopy(material_review)
    review_unknown_source["answer_binding"]["binding_basis"]["source_refs"] = ["NOT-A-MATERIAL:p1"]
    expect_gate_error(intake_data([[review_unknown_source]]), "未在当前 Manifest 登记")

    review_without_registry = intake_data([[copy.deepcopy(material_review)]])
    review_without_registry.pop("context_materials")
    expect_gate_error(review_without_registry, "已登记的授权材料")

    review_conflict = copy.deepcopy(material_review)
    review_conflict["answer_binding"]["resolution_status"] = "ambiguous"
    review_conflict["answer_binding"]["ambiguities"] = ["两份材料记载金额不一致"]
    review_conflict_issue = (
        "信息缺失[金额][ambiguous]：entity_ref=AMT-A field_key=amount.claimed，"
        "授权材料记载金额不一致。"
    )
    review_conflict_blockers = assert_gate_passes(
        intake_data([[review_conflict]], issues=[review_conflict_issue], mode="internal_review_draft")
    )
    assert any("仍有歧义" in item for item in review_conflict_blockers)

    review_claims_verification = copy.deepcopy(material_review)
    review_claims_verification["answer_binding"]["fact_verification"] = "verified"
    expect_gate_error(intake_data([[review_claims_verification]]), "not_verified_by_intake")

    # I02/I03/I08: preserve conflicting sources, accept natural short answers,
    # and never deduct a historical payment twice from a selected net balance.
    amount_answer = question(
        "Q-AMOUNT",
        category="金额",
        entity_ref="AMT-A",
        field_key="amount.claimed",
        text="本次金额采用哪一口径？",
        raw_response="128000元，是扣除历史已付72000元后的尚欠余额。",
        normalized_value=amount_value(),
    )
    amount_data = intake_data([[amount_answer]])
    assert_gate_passes(amount_data)
    resolved_without_value = copy.deepcopy(amount_data)
    resolved_without_value["intake_clarification"]["rounds"][0]["questions"][0]["answer_binding"]["normalized_value"] = None
    expect_gate_error(resolved_without_value, "非空 normalized_value")
    normalized = amount_answer["answer_binding"]["normalized_value"]
    assert [item["amount"] for item in normalized["source_amounts"]] == [200000, 150000, 128000]
    assert normalized["adopted_amount"] == 128000
    double_deduction = copy.deepcopy(amount_data)
    double_deduction["intake_clarification"]["rounds"][0]["questions"][0]["answer_binding"]["normalized_value"]["deduct_historical_payments"] = True
    expect_gate_error(double_deduction, "deduct_historical_payments=false")
    missing_no_deduction = copy.deepcopy(amount_data)
    del missing_no_deduction["intake_clarification"]["rounds"][0]["questions"][0]["answer_binding"]["normalized_value"]["deduct_historical_payments"]
    expect_gate_error(missing_no_deduction, "deduct_historical_payments=false")
    wrong_calculation = copy.deepcopy(amount_data)
    wrong_calculation["intake_clarification"]["rounds"][0]["questions"][0]["answer_binding"]["normalized_value"]["calculation_results"] = [
        {"expression": "200000-72000-72000", "result": 56000, "source_refs": ["M-A1:p1"]}
    ]
    expect_gate_error(wrong_calculation, "所有 calculation_results")
    mixed_calculation = copy.deepcopy(amount_data)
    mixed_calculation["intake_clarification"]["rounds"][0]["questions"][0]["answer_binding"]["normalized_value"]["calculation_results"].append(
        {"expression": "200000-72000-72000", "result": 56000, "source_refs": ["M-A2:p1"]}
    )
    expect_gate_error(mixed_calculation, "所有 calculation_results")
    missing_calculation_source = copy.deepcopy(amount_data)
    del missing_calculation_source["intake_clarification"]["rounds"][0]["questions"][0]["answer_binding"]["normalized_value"]["calculation_results"][0]["source_refs"]
    expect_gate_error(missing_calculation_source, "非空 source_refs")
    net_without_calculation = copy.deepcopy(amount_data)
    net_without_calculation["intake_clarification"]["rounds"][0]["questions"][0]["answer_binding"]["normalized_value"]["calculation_results"] = []
    expect_gate_error(net_without_calculation, "net_outstanding 必须保留")
    simple_gross = question(
        "Q-SIMPLE-GROSS",
        category="金额",
        entity_ref="AMT-SIMPLE",
        field_key="amount.claimed",
        text="本次采用的应付总金额是多少？",
        raw_response="80000元。",
        normalized_value={
            "source_amounts": [{"amount": 80000, "source_ref": "M-SIMPLE:p1"}],
            "calculation_results": [],
            "adopted_amount": 80000,
            "amount_kind": "gross_due",
        },
    )
    assert_gate_passes(intake_data([[simple_gross]]))

    # I04: known states for two different payment entities do not propagate.
    payment_records = {
        "payment_records": [
            {"entity_ref": "AMT-A", "time_range": "截至2024-04-10", "status": "paid"},
            {"entity_ref": "AMT-B", "time_range": "截至本次整理", "status": "unpaid"},
        ]
    }
    assert _amount_payment_blockers(payment_records) == []
    mismatched_payment_entity = question(
        "Q-PAYMENT-ENTITY",
        category="付款状态",
        entity_ref="AMT-A",
        field_key="payment.status",
        text="AMT-A 的付款状态是什么？",
        raw_response="截至本次整理仍未支付。",
        normalized_value={
            "entity_ref": "AMT-B",
            "status": "unpaid",
            "time_range": "截至本次整理",
        },
    )
    expect_gate_error(intake_data([[mismatched_payment_entity]]), "必须与问题 entity_ref 一致")
    mixed_record = {
        "payment_records": [{
            "entity_ref": "AMT-A",
            "time_range": "截至本次整理",
            "status": {"source_a": "paid", "source_b": "unpaid"},
        }]
    }
    assert _amount_payment_blockers(mixed_record)

    # I05: a compound answer may resolve amount but leave payment attribution
    # ambiguous; the next question depends on the resolved amount only.
    ambiguous_payment = question(
        "Q-PAY-SCOPE",
        category="付款状态",
        entity_ref="AMT-A",
        field_key="payment.status",
        text="未返还状态具体属于哪笔付款？",
        raw_response="128000，全部未返还。",
        normalized_value={"status": "unreturned"},
        resolution_status="ambiguous",
        ambiguities=["未说明返还状态所属时间范围"],
        depends_on=["Q-AMOUNT"],
    )
    ambiguous_issue = (
        "信息缺失[付款状态][ambiguous]：entity_ref=AMT-A "
        "field_key=payment.status，返还时间范围仍待确认。"
    )
    ambiguous_data = intake_data(
        [[amount_answer], [ambiguous_payment]],
        issues=[ambiguous_issue],
        mode="internal_review_draft",
    )
    assert any("仍有" in item for item in assert_gate_passes(ambiguous_data))
    ambiguous_without_status = copy.deepcopy(ambiguous_data)
    ambiguous_without_status["validation"]["unresolved_issues"] = [
        "信息缺失[付款状态]：entity_ref=AMT-A field_key=payment.status。"
    ]
    expect_gate_error(ambiguous_without_status, "未完整留痕")

    # I06: a bare yes without a concrete binary/options/summary context fails.
    bare_yes = question(
        "Q-BARE-YES",
        category="金额",
        entity_ref="AMT-A",
        field_key="amount.claimed",
        text="请确认金额信息。",
        raw_response="是",
        normalized_value=amount_value(),
    )
    expect_gate_error(intake_data([[bare_yes]]), "明确 binary、options 或 summary")
    bare_okay = copy.deepcopy(bare_yes)
    bare_okay["answer_binding"]["raw_response"] = "好的"
    expect_gate_error(intake_data([[bare_okay]]), "明确 binary、options 或 summary")

    # I07: yes after a versioned summary confirms only listed fields.
    summary_fields = ["AMT-A:amount.claimed", "AMT-A:amount.kind"]
    summary_values = {
        "AMT-A:amount.claimed": 128000,
        "AMT-A:amount.kind": "net_outstanding",
    }
    summary_yes = question(
        "Q-SUMMARY",
        category="金额",
        entity_ref="AMT-A",
        field_key="confirmation.summary",
        text="请确认这份金额摘要是否准确？",
        raw_response="是",
        normalized_value=copy.deepcopy(summary_values),
        context_kind="summary",
        summary_fields=summary_fields,
        summary_values=summary_values,
        basis_kind="confirmed_summary",
        summary_id="SUMMARY-AMT-A-v1",
    )
    assert_gate_passes(intake_data([[summary_yes]]))
    summary_okay = copy.deepcopy(summary_yes)
    summary_okay["answer_binding"]["raw_response"] = "好的"
    assert_gate_passes(intake_data([[summary_okay]]))
    over_confirm = copy.deepcopy(summary_yes)
    over_confirm["answer_binding"]["normalized_value"]["AMT-B:payment.status"] = True
    expect_gate_error(intake_data([[over_confirm]]), "只能确认")
    wrong_summary = copy.deepcopy(summary_yes)
    wrong_summary["answer_binding"]["binding_basis"]["summary_id"] = "SUMMARY-OTHER-v1"
    expect_gate_error(intake_data([[wrong_summary]]), "当前 answer_context.summary_id")
    missing_summary_values = copy.deepcopy(summary_yes)
    missing_summary_values["answer_context"].pop("summary_values")
    expect_gate_error(intake_data([[missing_summary_values]]), "summary_values")
    wrong_summary_value = copy.deepcopy(summary_yes)
    wrong_summary_value["answer_binding"]["normalized_value"]["AMT-A:amount.claimed"] = 150000
    expect_gate_error(intake_data([[wrong_summary_value]]), "当前 summary_values")
    empty_summary_yes = copy.deepcopy(summary_yes)
    empty_summary_yes["answer_binding"]["normalized_value"] = {}
    expect_gate_error(intake_data([[empty_summary_yes]]), "完整绑定")
    missing_summary_snapshot = copy.deepcopy(summary_yes)
    missing_summary_snapshot["answer_context"].pop("summary_snapshot")
    expect_gate_error(intake_data([[missing_summary_snapshot]]), "summary_snapshot")
    missing_context_locator = copy.deepcopy(summary_yes)
    missing_context_locator["answer_context"].pop("context_locator")
    expect_gate_error(intake_data([[missing_context_locator]]), "context_locator")
    same_summary_and_answer_turn = copy.deepcopy(summary_yes)
    same_summary_and_answer_turn["answer_context"]["context_locator"] = copy.deepcopy(
        same_summary_and_answer_turn["answer_binding"]["response_locator"]
    )
    expect_gate_error(intake_data([[same_summary_and_answer_turn]]), "不得与用户确认答复位置相同")

    # One user turn may answer two atomic questions only when each binding keeps
    # the exact clause supporting its own entity and field.
    shared_response = "采用128000元；截至本次整理仍未返还。"
    shared_amount = question(
        "Q-SHARED-AMOUNT",
        category="金额",
        entity_ref="AMT-A",
        field_key="amount.claimed",
        text="AMT-A本次采用的金额是多少？",
        raw_response=shared_response,
        normalized_value=amount_value(),
        response_reference="合成对话/shared-answer",
        raw_response_fragment="采用128000元",
    )
    shared_payment = question(
        "Q-SHARED-PAYMENT",
        category="付款状态",
        entity_ref="AMT-A",
        field_key="payment.status",
        text="AMT-A截至本次整理的付款状态是什么？",
        raw_response=shared_response,
        normalized_value={
            "entity_ref": "AMT-A",
            "status": "unreturned",
            "time_range": "截至本次整理",
        },
        response_reference="合成对话/shared-answer",
        raw_response_fragment="截至本次整理仍未返还",
    )
    assert_gate_passes(intake_data([[shared_amount, shared_payment]]))
    shared_without_fragment = copy.deepcopy(shared_payment)
    shared_without_fragment["answer_binding"]["binding_basis"].pop("raw_response_fragment")
    expect_gate_error(
        intake_data([[shared_amount, shared_without_fragment]]),
        "同一答复位置绑定多个字段",
    )

    invalid_fragment = copy.deepcopy(shared_amount)
    invalid_fragment["answer_binding"]["binding_basis"]["raw_response_fragment"] = "用户没有说过"
    expect_gate_error(intake_data([[invalid_fragment]]), "raw_response 中的非空原文片段")

    invalid_locator = copy.deepcopy(shared_amount)
    invalid_locator["answer_binding"]["response_locator"] = locator("x")
    expect_gate_error(intake_data([[invalid_locator]]), "必须明确轮次/角色")
    invalid_locator_kind = copy.deepcopy(shared_amount)
    invalid_locator_kind["answer_binding"]["response_locator"]["kind"] = "random"
    expect_gate_error(intake_data([[invalid_locator_kind]]), "kind 无效")

    # I05 again: an ordinal answer binds only to the current versioned option.
    option_answer = question(
        "Q-OPTION",
        category="金额",
        entity_ref="AMT-A",
        field_key="amount.kind",
        text="金额口径选择哪一项？",
        raw_response="第一项",
        normalized_value={
            "amount_kind": "net_outstanding",
            "historical_payments_already_deducted": True,
            "deduct_historical_payments": False,
        },
        context_kind="options",
        options=[
            {
                "option_id": "OPT-NET",
                "label": "扣款后余额",
                "normalized_value": {
                    "amount_kind": "net_outstanding",
                    "historical_payments_already_deducted": True,
                    "deduct_historical_payments": False,
                },
            },
            {
                "option_id": "OPT-GROSS",
                "label": "应付总额",
                "normalized_value": {"amount_kind": "gross_due"},
            },
        ],
        basis_kind="selected_option",
        selected_option_id="OPT-NET",
    )
    assert_gate_passes(intake_data([[option_answer]]))
    wrong_option = copy.deepcopy(option_answer)
    wrong_option["answer_binding"]["binding_basis"]["selected_option_id"] = "OPT-GROSS"
    expect_gate_error(intake_data([[wrong_option]]), "未准确回指")
    wrong_option_value = copy.deepcopy(option_answer)
    wrong_option_value["answer_binding"]["normalized_value"] = {"amount_kind": "gross_due"}
    expect_gate_error(intake_data([[wrong_option_value]]), "normalized_value 完全一致")

    # A binary yes needs both a concrete proposition and a stable option value.
    binary_yes = question(
        "Q-BINARY",
        category="金额",
        entity_ref="AMT-A",
        field_key="amount.confirmed",
        text="请确认本次主张金额是否为128000元？",
        raw_response="是",
        normalized_value=True,
        context_kind="binary",
        options=[
            {"option_id": "YES", "label": "是", "normalized_value": True},
            {"option_id": "NO", "label": "否", "normalized_value": False},
        ],
        basis_kind="selected_option",
        selected_option_id="YES",
    )
    expect_gate_error(intake_data([[binary_yes]]), "具体 proposition")
    binary_yes["answer_context"]["proposition"] = "AMT-A本次主张金额为128000元"
    assert_gate_passes(intake_data([[binary_yes]]))

    # I09/I10: unknown, declined and later remain unresolved, are not asked
    # again, and an explicit internal-review request safely closes intake.
    unknown = question(
        "Q-UNKNOWN",
        category="主体",
        entity_ref="PARTY-01",
        field_key="identity.name",
        text="截图中的主体身份是谁？",
        raw_response="不知道，暂时无法确认。",
        normalized_value=None,
        user_choice="unknown",
        resolution_status="unknown",
    )
    declined = question(
        "Q-DECLINED",
        category="原始载体",
        entity_ref="M-B1",
        field_key="carrier.location",
        text="原始载体位置在哪里？",
        raw_response="这个我不提供。",
        normalized_value=None,
        user_choice="declined",
        resolution_status="declined",
    )
    later = question(
        "Q-LATER",
        category="上下文",
        entity_ref="M-B2",
        field_key="context.complete_chat",
        text="完整聊天上下文何时补充？",
        raw_response="稍后补充。",
        normalized_value=None,
        user_choice="later",
        resolution_status="later",
    )
    lifecycle_issues = [
        "信息缺失[主体][用户选择不知道]：entity_ref=PARTY-01 field_key=identity.name。",
        "信息缺失[原始载体][用户选择不提供]：entity_ref=M-B1 field_key=carrier.location。",
        "信息缺失[上下文][用户选择稍后补充]：entity_ref=M-B2 field_key=context.complete_chat。",
    ]
    lifecycle = intake_data(
        [[unknown, declined], [later]],
        issues=lifecycle_issues,
        mode="internal_review_draft",
    )
    blockers = assert_gate_passes(lifecycle)
    assert any("内部核对稿" in item for item in blockers)
    repeated_unknown = copy.deepcopy(unknown)
    repeated_unknown["question_id"] = "Q-UNKNOWN-REPEAT"
    repeated_unknown["answer_context"]["version"] = "Q-UNKNOWN-REPEAT-context-v1"
    repeated_unknown["answer_binding"]["binding_basis"].update({
        "question_id": "Q-UNKNOWN-REPEAT",
        "context_version": "Q-UNKNOWN-REPEAT-context-v1",
    })
    expect_gate_error(
        intake_data([[unknown], [repeated_unknown]], issues=[lifecycle_issues[0]], mode="internal_review_draft"),
        "supersedes_question_id",
    )
    wrong_unknown = copy.deepcopy(unknown)
    wrong_unknown["answer_binding"]["raw_response"] = "128000元。"
    expect_gate_error(
        intake_data([[wrong_unknown]], issues=[lifecycle_issues[0]], mode="internal_review_draft"),
        "语义不一致",
    )

    # Dependency order is enforced: unresolved prerequisites cannot unlock a
    # later detail question.
    dependent = question(
        "Q-DEPENDENT",
        category="付款状态",
        entity_ref="PARTY-01",
        field_key="payment.status",
        text="该主体对应款项的付款状态是什么？",
        raw_response="未支付。",
        normalized_value={"status": "unpaid", "time_range": "截至本次整理"},
        depends_on=["Q-UNKNOWN"],
    )
    dependency_issues = lifecycle_issues[:1]
    expect_gate_error(
        intake_data([[unknown], [dependent]], issues=dependency_issues, mode="internal_review_draft"),
        "尚未 resolved",
    )

    # A clearly bundled question is rejected even when it carries one field_key.
    compound = copy.deepcopy(amount_answer)
    compound["question"] = "请确认金额、期间、已付未付、签署人和原始载体位置？"
    expect_gate_error(intake_data([[compound]]), "多个事项")
    two_topic_compound = copy.deepcopy(amount_answer)
    two_topic_compound["question"] = "请确认本次主张金额和付款状态？"
    expect_gate_error(intake_data([[two_topic_compound]]), "多个事项")
    same_topic_compound = copy.deepcopy(amount_answer)
    same_topic_compound["question"] = "请同时确认本次主张金额以及它是应付总额还是余额？"
    expect_gate_error(intake_data([[same_topic_compound]]), "多个事项")
    lexical_compound = copy.deepcopy(amount_answer)
    lexical_compound["question"] = "请确认款项数值和结清情况？"
    expect_gate_error(intake_data([[lexical_compound]]), "多个事项")

    # Once the user asks for an internal-review draft, later fact questions
    # cannot be hidden in a completed transcript.
    draft_unknown = copy.deepcopy(unknown)
    draft_unknown["answer_binding"]["raw_response"] = "不知道，先做内部核对稿。"
    draft_unknown["answer_binding"]["response_locator"] = locator("合成对话/明确草稿")
    draft_issue = "信息缺失[主体][用户选择不知道]：entity_ref=PARTY-01 field_key=identity.name。"
    draft_stop = intake_data(
        [[draft_unknown]],
        issues=[draft_issue],
        mode="internal_review_draft",
        stop_raw_response="不知道，先做内部核对稿。",
        stop_response_reference="合成对话/明确草稿",
    )
    assert_gate_passes(draft_stop)
    later_after_draft = copy.deepcopy(later)
    expect_gate_error(
        intake_data(
            [[draft_unknown], [later_after_draft]],
            issues=[draft_issue, lifecycle_issues[2]],
            mode="internal_review_draft",
            stop_raw_response="不知道，先做内部核对稿。",
            stop_response_reference="合成对话/明确草稿",
        ),
        "内部核对稿之后",
    )
    negative_continue = copy.deepcopy(amount_data)
    negative_continue["intake_clarification"]["stop_decision"]["raw_response"] = "不要制作。"
    expect_gate_error(negative_continue, "明确要求制作")
    unsupported_draft_stop = intake_data(
        [[amount_answer]],
        mode="internal_review_draft",
        stop_raw_response="暂时这样。",
    )
    expect_gate_error(unsupported_draft_stop, "明确要求内部核对稿")

    # Legacy manifests keep their old path and are never auto-filled with new
    # question IDs, raw responses, normalized values, or host message IDs.
    with tempfile.TemporaryDirectory(prefix="evidence-v19-intake-") as temp:
        base = Path(temp)
        legacy = make_legal_fixture(base)
        legacy_normalized = normalise_manifest(copy.deepcopy(legacy))
        assert "protocol" not in legacy_normalized["intake_clarification"]
        assert "rounds" not in legacy_normalized["intake_clarification"]

        old_declined = copy.deepcopy(legacy)
        old_declined["intake_clarification"] = {
            "status": "completed",
            "required_categories": ["书状"],
            "rounds": [{
                "round_id": "LEGACY-R1",
                "questions": [{
                    "category": "书状",
                    "question": "请提供书状，以确认具体请求。",
                    "user_choice": "declined",
                    "response_reference": "用户在本次合成测试中明确选择不提供书状。",
                }],
            }],
        }
        old_declined["validation"]["status"] = "unresolved"
        old_declined["validation"]["unresolved_issues"] = [
            "信息缺失[书状]：用户选择不提供，证明用途仍待核。"
        ]
        fatal, _ = _intake_clarification_gate(old_declined)
        assert not fatal, fatal

        old_material_review = copy.deepcopy(old_declined)
        old_material_review["intake_clarification"]["rounds"][0]["questions"][0].update({
            "user_choice": "material_review",
            "response_reference": "用户在本任务中要求AI通过书状材料判断。",
        })
        expect_gate_error(old_material_review, "仅支持 protocol=field_binding_v1")

        # I10/I11: the explicit draft request advances safely, while completed
        # intake never upgrades validation and cannot waive source gates.
        draft_case = copy.deepcopy(legacy)
        draft_case["intake_clarification"] = lifecycle["intake_clarification"]
        draft_case["validation"]["status"] = "unresolved"
        draft_case["validation"]["unresolved_issues"] = lifecycle_issues
        draft = validate_manifest(draft_case, base)
        assert draft["_effective_draft"] is True
        assert draft["validation"]["status"] == "unresolved"

        formal_case = copy.deepcopy(legacy)
        formal_case["intake_clarification"] = amount_data["intake_clarification"]
        formal_case["validation"]["checks"]["amounts_checked"] = {
            "status": "resolved",
            "material_refs": ["M001"],
            "note": "仅核对合成金额交互结构。",
        }
        validate_manifest(copy.deepcopy(formal_case), base)
        missing_carrier = copy.deepcopy(formal_case)
        missing_carrier["evidence_groups"][0]["materials"][0].pop("original_carrier")
        expect_manifest_error(missing_carrier, base)

    print("v19 field-bound intake interaction: PASS (I01-I17 + legacy)")


if __name__ == "__main__":
    main()
