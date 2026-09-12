# 缺失信息澄清、回答绑定与收口

本流程内置在 `build-evidence-bundle` 中，用于在生成证据清单或证据材料卷前取得必要、可回查的事实输入。它不是完整法律推理系统，也不替代材料真实性、来源、视频、Office、路径或页面复核。

## 一、先读材料和已有答复

开始提问前，先在用户授权范围内：

1. 读取起诉状、答辩状、仲裁书状、材料目录、已有 Manifest 和本任务既往答复；
2. 用本地工具检查可以直接读取或计算的内容，例如文件是否存在、图片是否可读、表内合计、视频是否可解码；
3. 区分材料原文、计算结果、用户写作选择和独立核验结论；
4. 只把真正会影响分组、事实表达、证明用途、正式版资格或材料顺序的缺口列入追问。

用户说“材料里有”“见附件”时，先回查授权材料。找到答案后，以 `binding_basis.kind=material_lookup` 记录实际 `source_refs[]`，不重复索取；没有找到时，说明已检查的位置和仍缺的具体字段。材料回查只表明已定位内容，不自动等于真实性或事实核验通过。

对一个明确字段，用户还可以选择“请 AI 回查已授权材料后判断”。以 `user_choice=material_review` 保存这项流程授权和原始答复；AI 随后必须实际读取或计算，而不是把选择本身当成答案。材料能唯一支持一个结果时可记为 `resolved`；材料冲突、缺失或不能唯一归属时记为 `ambiguous`，保留候选值、来源与歧义，并且只追问剩余的具体事项。

视频来源仍须区分 `original_recording`、`unverified_local_video`、`public_demo_copy` 和 `social_media_copy`。缺少 FFmpeg/FFprobe 时直接报告技术阻断，不以用户说“可以做”替代真实解码。

## 二、按依赖关系组织问题

- 通常每轮1—2问，最多3问；不要一次抛出长问卷。
- 一个问题只要求解决一个明确事项，并只绑定一个 `entity_ref + field_key`。
- 金额、期间、付款状态、签署人、载体位置不得压在同一编号中。
- 前置问题未解决时，不询问依赖其答案的细节；用 `depends_on[]` 回指前置 `question_id`。
- 互不依赖且对象明确的问题可以同轮提出。
- 同一对象同一字段不得换措辞重复追问。新材料使问题发生实质变化时，用新 `question_id` 并以 `supersedes_question_id` 回指上一问。
- 用户在任一轮明确要求先做内部核对稿后，可降级的事实问题立即停止；不得在同一回复末尾继续追问上下文、书状、主体、金额或付款。缺少可读取材料、路径冲突、解码失败等 fatal 技术错误应作为停止原因直接报告，不转写成更多事实问题。

面向用户采用自然表达：先说明已知信息或材料中的具体差异，再提出需要确认的事项；只有在有帮助时用一句话说明它会影响什么。不机械输出“按 Skill 硬门槛”，也不要求“缺失项/原因/影响/选择”四段式标签。

可以推荐流程，例如“建议先做内部核对稿”；不得推荐案件事实，例如“建议选择全部未支付”或“建议认定签字人是被告”。

示例：

> 材料中，订单汇总记载总额200000元、已付72000元和余额128000元；主张表另记载150000元。请确认本次采用哪一项作为主张金额，以及它表示应付总额还是扣除已付款后的余额。这会影响金额台账和证明对象。

若上句需要写入协议，应拆成两个字段问题：先问 `amount.claimed`，解决后再问 `amount.kind`；不得在同一问题继续追问付款所属期间或载体位置。

## 三、`field_binding_v1` 问答结构

新问答在既有 `intake_clarification.rounds[].questions[]` 内使用：

```json
{
  "question_id": "Q-AMT-01",
  "category": "金额",
  "entity_ref": "REQ-01/PAY-01",
  "field_key": "amount.claimed",
  "question": "本次采用的主张金额是多少？",
  "depends_on": [],
  "answer_context": {
    "kind": "open",
    "version": "amount-claim-v1",
    "options": [],
    "summary_fields": []
  },
  "user_choice": "provided",
  "answer_binding": {
    "raw_response": "128000元，按扣除历史付款后的余额主张。",
    "response_locator": {
      "kind": "conversation_turn",
      "reference": "本任务第2轮用户答复",
      "message_id": null
    },
    "normalized_value": {
      "source_amounts": [
        {"amount": 200000, "source_ref": "M001第1页订单总额"},
        {"amount": 128000, "source_ref": "M001第1页尚欠余额"}
      ],
      "calculation_results": [
        {"expression": "200000-72000", "result": 128000}
      ],
      "adopted_amount": 128000,
      "amount_kind": "net_outstanding",
      "historical_payments_already_deducted": true,
      "deduct_historical_payments": false
    },
    "binding_basis": {
      "kind": "direct_answer",
      "question_id": "Q-AMT-01",
      "context_version": "amount-claim-v1"
    },
    "resolution_status": "resolved",
    "ambiguities": [],
    "fact_verification": "not_verified_by_intake"
  }
}
```

规则如下：

- `question_id` 在整个 Manifest 中唯一；它不是平台消息 ID。
- `entity_ref` 指向具体请求、款项、材料、视频或主体；`field_key` 只表示一个字段。
- `answer_context.kind` 可为 `open/free_text/binary/options/summary`，并必须有稳定 `version`。`binary` 还须保存具体 `proposition` 和两个带稳定 ID 的选项；`options` 每项保存 `option_id/label/normalized_value`；`summary` 保存 `summary_id`、`summary_fields[]`、与字段完全对应的 `summary_values`、实际展示文本 `summary_snapshot` 和展示该摘要的助手轮次 `context_locator`。摘要展示位置与用户确认位置不能相同。选项和摘要确认只对该对象及版本有效；肯定短答必须完整绑定当前摘要快照，不能用空对象完成确认。
- `raw_response` 原样保存用户答复。`normalized_value` 是模型解释，两者不得互相替换。
- `response_locator` 保留可回查位置。宿主未提供消息 ID 时 `message_id` 为 `null`，不得编造。
- `binding_basis.kind` 可用 `direct_answer`、`selected_option`、`confirmed_summary`、`material_lookup` 或 `computed`；均须回指当前 `question_id` 和 `answer_context.version`。
- 同一条用户答复同时回答多个明确问题时，每项绑定都保留完整 `raw_response`，并在 `binding_basis.raw_response_fragment` 中保存支持该 `entity_ref + field_key` 的原文片段；不得只凭同一段复合答复把状态传播到另一对象。
- `material_lookup/computed` 必须提供实际 `source_refs[]`；`selected_option` 必须回指当前版本存在的 `selected_option_id`，且绑定后的 `normalized_value` 与该选项完全一致；`confirmed_summary.summary_id` 必须等于当前 `answer_context.summary_id`。
- `fact_verification` 固定为 `not_verified_by_intake`。只有独立 `validation` 和来源检查才能记录事实核验结果。

## 四、自然短答、歧义和用户选择

用户不需要说“已提供”“已上传”等固定措辞。“有，在材料目录”“金额是128000”“不知道”“不提供”“稍后补充”都可以按原话记录。

- `user_choice=provided` 时，`resolution_status` 只能是 `resolved` 或 `ambiguous`。
- `provided + resolved` 必须保存非空 `normalized_value`；不能仅凭“问过”或一段原话把字段标为已解决。付款状态的规范化对象若包含 `entity_ref`，必须与问题层的 `entity_ref` 一致，避免把另一笔款项的状态带入。
- `user_choice=material_review` 时，原话必须明确授权 AI 按已授权材料判断；`binding_basis.kind` 只能是 `material_lookup` 或 `computed`，并保存非空 `source_refs[]`。每个来源引用须以当前 Manifest 的证据材料 `material_id`、上下文材料 `material_id` 或视频 `source_id` 开头，例如 `M001:p2:金额栏`；未登记编号、仅写本机路径或虚构引用均拒绝。`resolved` 必须有非空 `normalized_value`；`ambiguous` 必须保留 `ambiguities[]` 和对应未决事项。
- `material_review` 不是案件事实选项。不得据此写成对方自认、真实性已核验、法律结论已经成立，或把材料中没有的诉讼主张补造成用户选择。
- `user_choice=unknown/declined/later` 时，`resolution_status` 分别记录 `unknown/declined/later`，`normalized_value` 不得伪造事实值。
- `unknown/declined/later` 和 `ambiguous` 均保留在 `validation.unresolved_issues[]`，并写明 `entity_ref`、`field_key` 和影响；它们表示已经回答但仍未解决，不得因此清除缺口。
- 不知道、拒绝或稍后补充后停止重复追问同一字段；只有出现新材料或用户主动改答时，才用 `supersedes_question_id` 发起实质不同的新问题。

“128000，全部未返还”可能包含两个层次：若当前问题和对象明确，128000可以绑定到 `amount.claimed`；“全部未返还”若无法唯一归属到具体款项和时间范围，则仅把 `payment.status` 标为 `ambiguous`，下一问只问归属，不重复询问金额。

“是”“否”“第一项”“按你说的”等短答只有在以下情况才能绑定：

- 当前问题保存了明确二元 `proposition`，且“是/否”回指该版本的具体选项；
- 当前版本列出了带稳定 ID 和规范化含义的具体选项；
- 刚刚展示了带 `summary_id`、版本和字段范围的摘要。

必须保留短答原话；不得把“是”改写成用户没有说过的完整事实句。没有具体命题的“是”不能完成确认。

## 五、金额和付款的独立记录

金额至少区分：

1. `source_amounts[]`：原材料逐项记载的数值及 `source_ref`；
2. `calculation_results[]`：分项计算过程、结果和 `source_refs[]`；没有分项计算时保留空数组，净余额则必须至少有一项可复算结果；字段标为 `resolved` 时所有列入的净余额计算均须与采用金额一致，来源间仍有不同计算时改记 `ambiguous` 并保留差异；
3. `adopted_amount`：用户本次写作采用的主张金额；
4. `amount_kind`：`gross_due`（应付总额）或 `net_outstanding`（扣除历史付款后的余额）。

用户选择采用金额不删除原材料中的不同数值，也不表示对方认可或证据已经核验。不得修改原图。

当 `amount_kind=net_outstanding` 时，必须记录 `historical_payments_already_deducted=true`，后续 `deduct_historical_payments` 必须为 `false`。历史部分已付与尚欠余额全部未付可以同时成立：前者描述历史付款，后者描述当前余额；不能把历史付款再次从余额中扣除。

付款或返还状态必须绑定具体 `entity_ref` 和 `time_range/payment_time_range`。两笔款项分别为已付与未付不是冲突；只有同一实体同一期间存在混合状态或状态未核时才作为冲突或缺口处理。

## 六、确认与停止

确认摘要应列明：对应款项、金额及含义、付款状态、仍待核事项，并给出 `summary_id` 和版本。`answer_context.summary_id` 与 `confirmed_summary.summary_id` 必须完全一致，绑定值必须与该版本 `summary_values` 一致。确认只作用于 `answer_context.summary_fields[]` 列出的字段；“是/同意”等肯定短答确认全部所列字段，不能保存为空或偷换为另一版本的值。它不确认摘要外事项，也不把 intake 答复升级为来源或事实已核验。

已有明确答复、无关键歧义且用户此前已经要求制作时，直接继续，不再要求泛泛的“是”。确需确认时才展示具体摘要。

连续两轮后，评估每个剩余问题是否仍会改变结果。用户明确要求先做内部核对稿时，保留待核事项并停止可降级追问；不必等到两轮届满。若该请求与某一问答在同一条用户消息中出现，`stop_decision` 必须原样回指该消息，之后不得再记录新的事实问题。`field_binding_v1` 在 `completed` 时记录：

```json
{
  "stop_decision": {
    "mode": "internal_review_draft",
    "reason": "用户要求先形成核对稿，剩余载体位置待补。",
    "raw_response": "先做内部核对稿，载体稍后补。",
    "response_locator": {
      "kind": "conversation_turn",
      "reference": "本任务第4轮用户答复",
      "message_id": null
    },
    "unresolved_fields": ["M003:carrier.location"]
  }
}
```

`mode` 只允许 `continue_build` 或 `internal_review_draft`。`continue_build` 必须回指用户明确要求制作、生成或继续执行的原话；“不要制作”“暂不生成”等否定表达不能收口为继续制作。`internal_review_draft` 必须回指用户明确要求内部核对稿或草稿的原话。内部核对稿请求可使正式 blocker 安全降级，但不能绕过结构错误、材料不存在/无法解码、输出路径冲突等硬失败。Word 首页只显示中性的“内部核对稿”；详细缺口留在 Manifest、QA 和交付说明中。

## 七、状态、兼容和技术边界

`intake_clarification.status` 仅允许：

- `pending`：关键问题尚未取得真实答复；正式版和草稿均禁止生成；
- `completed`：必问事项已有可回查答复并按字段绑定；它不等于事实已核验；
- `waived_by_user`：用户明确要求跳过询问，保留 `waiver_reference`，只能生成草稿；
- `not_required`：确无关键缺口，必须说明理由，且 `validation`、用途和来源均无未决项。

旧 Manifest 未声明 `protocol=field_binding_v1` 时继续走旧校验；不得自动补造 `question_id`、原话、规范化值、绑定依据或消息 ID。兼容读取不等于把旧问答升级为新协议。

用户确认制作、`completed` 或 `stop_decision` 均不能替代：

- `validation.status` 与六项核验；
- 书状/用户具体请求来源及 `proof_targets`；
- 图片真实解码、原始载体和来源角色；
- FFmpeg/FFprobe 视频解码、时码和帧索引；
- Office sidecar、转换器和逐页映射；
- 路径安全、输出保护和独立页面复核。

没有任何可读材料、材料目录不存在、所有候选文件均无法解码，或输出路径与输入冲突时，不得伪造附件、帧、时码、Manifest 或 DOCX。可以交付盘点、缺口清单和下一步问题，但必须明确停止原因。
