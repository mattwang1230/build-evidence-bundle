# Manifest v2

Manifest 使用 UTF-8 JSON。`schema_version` 必须是整数 `2` 才有资格进入正式版。所有版本都必须先有可复核的 `intake_clarification`；缺少、仍为 `pending` 或留痕不完整时，正式版和 `--allow-draft` 草稿均阻断。整数 `1` 及缺少版本字段的旧数据只能兼容读取，在用户完成本轮询问或明确跳过后才可迁移为草稿。旧 v2 即使版本号为2，只要缺少逐项 `purpose`、`purpose_basis`、`proof_targets`、`fact_level` 或目标/要件映射，也只能通过 `--allow-draft` 输出。布尔、浮点数、字符串和显式 `null` 均不是合法版本值，必须明确失败。

```json
{
  "schema_version": 2,
  "case_info": "原告某某诉被告某公司合同纠纷案",
  "submitter": "原告某某",
  "signer": "",
  "submission_date": "",
  "intake_clarification": {
    "protocol": "field_binding_v1",
    "status": "completed",
    "required_categories": ["书状"],
    "rounds": [
      {
        "round_id": "R001",
        "questions": [
          {
            "question_id": "Q-PLEADING-01",
            "category": "书状",
            "entity_ref": "CTX001",
            "field_key": "pleading.source_ref",
            "question": "起诉状在本次工作区的具体位置是什么？",
            "depends_on": [],
            "answer_context": {
              "kind": "open",
              "version": "pleading-source-v1",
              "options": [],
              "summary_fields": []
            },
            "user_choice": "provided",
            "answer_binding": {
              "raw_response": "起诉状在 context 目录里。",
              "response_locator": {
                "kind": "conversation_turn",
                "reference": "本任务第1轮用户答复",
                "message_id": null
              },
              "normalized_value": {
                "material_id": "CTX001",
                "path": "context/起诉状.pdf"
              },
              "binding_basis": {
                "kind": "direct_answer",
                "question_id": "Q-PLEADING-01",
                "context_version": "pleading-source-v1"
              },
              "resolution_status": "resolved",
              "ambiguities": [],
              "fact_verification": "not_verified_by_intake"
            }
          }
        ]
      }
    ],
    "stop_decision": {
      "mode": "continue_build",
      "reason": "用户已要求制作，当前追问字段无关键歧义。",
      "raw_response": "请开始制作。",
      "response_locator": {
        "kind": "conversation_turn",
        "reference": "本任务第2轮用户答复",
        "message_id": null
      },
      "unresolved_fields": []
    }
  },
  "context_materials": [
    {
      "material_id": "CTX001",
      "path": "context/起诉状.pdf",
      "source": "用户提供的起诉状（用途依据，不作为本卷证据）",
      "use": "用于确认请求与待证事实的对应关系",
      "status": "reference_only"
    }
  ],
  "media_sources": [
    {
      "source_id": "V001",
      "path": "originals/全合成录屏.mp4",
      "source_kind": "original_recording",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "duration_seconds": 6.0,
      "stream_index": 0,
      "rotation_degrees": 0,
      "frame_index_path": "frames/video-frame-index.json"
    }
  ],
  "validation": {
    "status": "resolved",
    "checks": {
      "identity_checked": {"status": "resolved", "material_refs": ["M001"], "note": "以资料页和签署页交叉核对。"},
      "dates_checked": {"status": "resolved", "material_refs": ["M001"], "note": "以书证日期为准。"},
      "amounts_checked": {"status": "resolved", "material_refs": ["M002"], "note": "金额口径已逐项列明。"},
      "payment_status_checked": {"status": "resolved", "material_refs": ["M003"], "note": "付款状态以原始回单核验。"},
      "proof_scope_checked": {"status": "resolved", "material_refs": ["M001"], "note": "证明对象未超出图片内容。"},
      "original_carrier_checked": {"status": "resolved", "material_refs": ["M001"], "note": "原始载体保存位置已记录。"}
    },
    "unresolved_issues": []
  },
  "proof_targets": [
    {
      "target_kind": "claim",
      "target_id": "REQ-01",
      "description": "起诉状第1项请求：支付合同价款",
      "legal_elements": ["协议形成时间"]
    }
  ],
  "evidence_groups": [
    {
      "number": 1,
      "group_id": "G01",
      "evidence_name": "2024-05-11 某方与某方签署的协议",
      "evidence_form": "复印件",
      "proof_object": "协议签署页载明日期为2024年5月11日；对应起诉状第1项价款请求中的协议形成时间事实。",
      "materials": [
        {
          "material_id": "M001",
          "path": "materials/01-协议.jpg",
          "source": "纸质原件扫描件",
          "original_carrier": {"carrier_location": "案件原始载体目录/协议原件", "carrier_type": "纸质原件"},
          "video_frame": null,
          "display_rotation_degrees_clockwise": 0,
          "source_time": "",
          "fact": "签署页和日期",
          "readability": "clear"
        }
      ]
    }
  ],
  "proof_claims": [
    {
      "claim_id": "C001",
      "text": "M001 第1页/签署栏载明协议日期为2024-05-11，拟证明文书记载的日期。",
      "type": "fact",
      "fact_level": "element_fact",
      "role": "direct",
      "purpose": "用于支持起诉状中关于协议形成时间及相应请求权要件的主张。",
      "purpose_basis": {
        "kind": "pleading",
        "reference": "起诉状第2页第3段",
        "status": "confirmed",
        "target_kind": "claim",
        "target_id": "REQ-01",
        "legal_element": "协议形成时间"
      },
      "material_refs": [{"material_id": "M001", "page": 1, "region": "签署栏"}],
      "boundary": "不能单独证明签字人身份、签章真实性或协议履行。"
    }
  ]
}
```

## v18 Office sidecar 扩展

Manifest 仍为整数 schema_version=2。只有 Office 派生页使用顶层 bundle_contract=v18、provenance_route=v2_sidecar 和 office_provenance 相对路径。派生材料必须有 origin_kind=office_derived 与 provenance_ref 的 unit_id/pdf_page；普通图片和视频无需增加这些字段。

Office sidecar 非 PASS、缺失、路径越界、源变化、内部位置或逐页映射不完整时属于不可降级硬失败。--allow-draft 不能把未绑定的 Office 派生页嵌入 DOCX。详见 office-sidecar.md。

## v19 证明模型扩展

Manifest 版本仍为整数 `schema_version=2`，不另设 v3。v19 正式版在原有结构上增加 `proof_targets[]`、`proof_claims[].fact_level`，并扩展 `role` 与 `purpose_basis`。旧 v2 缺少这些字段时仍可完成兼容读取，但只能通过 `--allow-draft` 输出内部核对稿，不能自动补字段或升级为正式版。

`proof_targets[]` 是请求/抗辩及法律要件的目标清单，不是证据材料：

- `target_kind`：`claim`、`defense`、`rebuttal`、`context`；
- `target_id`：在当前 Manifest 内稳定、唯一的编号；
- `description`：具体请求、抗辩、反驳对象或背景用途；
- `legal_elements[]`：非空、无重复的法律要件或明确背景事项。

每条 claim 的 `purpose_basis.target_kind/target_id/legal_element` 必须精确回指上述目标。生成器据此输出独立 `*.coverage-matrix.json`，列出 `covered/partial/uncovered/conflict`、无用途材料、无目标 claim、跨组衔接和未解决冲突；该侧车不进入 Word。

## 字段规则

- `intake_clarification` 为所有版本的文书生成前置门槛。`status` 只能为 `not_required`、`pending`、`completed`、`waived_by_user`；`pending` 或缺少该对象时不得生成任何 DOCX。
- 新问答声明 `protocol=field_binding_v1`。`completed` 必须有非空、无重复且只含允许类别的 `required_categories[]`，以及一轮或多轮 `rounds[]`；每轮必须有唯一 `round_id` 和1—3个 `questions[]`。每问必须有全局唯一 `question_id`、`category`、单一 `entity_ref + field_key`、实际 `question`、`depends_on[]`、带版本的 `answer_context`、`user_choice` 和 `answer_binding`。`user_choice` 只允许 `provided`、`material_review`、`unknown`、`declined`、`later`。`binary` context 保存具体 `proposition` 和两个稳定选项；`options` 每项保存 `option_id/label/normalized_value`；`summary` context 保存 `summary_id`、无重复的 `summary_fields[]` 及与字段完全对应的 `summary_values`。
- `answer_binding` 分别保存 `raw_response`、`response_locator{kind,reference,message_id}`、`normalized_value`、`binding_basis`、`resolution_status`、`ambiguities[]` 和 `fact_verification=not_verified_by_intake`。宿主没有消息 ID 时必须显式写 `message_id: null`。`provided/material_review + resolved` 的 `normalized_value` 不得为空；付款规范化值若包含 `entity_ref`，必须与问题对象一致。`binding_basis` 必须回指当前 `question_id` 与 context 版本；`material_lookup/computed` 还须有 `source_refs[]`，`selected_option` 须回指当前版本的 `selected_option_id` 且规范化值与选项一致，`confirmed_summary.summary_id` 须与当前 context 的 `summary_id` 相同且绑定值须来自当前 `summary_values`；“是/同意”等肯定短答必须完整确认当前 `summary_fields[]`，不能用空对象收口。
- `provided` 可为 `resolved` 或 `ambiguous`。`material_review` 表示用户授权 AI 回查已授权材料后判断当前字段，也只可为 `resolved` 或 `ambiguous`，且 `binding_basis.kind` 必须是 `material_lookup` 或 `computed` 并有非空 `source_refs[]`；每个引用的首段必须对应当前 Manifest 已登记的证据材料/上下文材料 `material_id` 或媒体 `source_id`。它不构成对方自认、真实性核验、自动法律结论或用户诉讼主张。旧协议不得使用 `material_review`，也不得自动补造新协议字段。`unknown/declined/later` 使用同名 `resolution_status`，不保存伪造的规范化事实值，并在 `validation.unresolved_issues[]` 保留类别、选择、`entity_ref` 和 `field_key`。同一对象字段再次提问必须用 `supersedes_question_id`；依赖问题未 `resolved` 时不得提出后置问题。
- `field_binding_v1` 的 `completed` 还须保存 `stop_decision{mode,reason,raw_response,response_locator,unresolved_fields[]}`。`mode` 仅为 `continue_build` 或 `internal_review_draft`；前者必须回指明确要求制作/生成/继续执行的原话，后者必须回指明确要求内部核对稿/草稿的原话，否定或无关原话不得完成收口。若用户在问答原话中明确要求内部核对稿，`stop_decision` 必须回指并原样保存同一轮答复，后续不得再追加可降级事实问题。确认与停止不改变 `validation`，也不能替代来源、视频、Office 或路径门禁。
- 未声明新协议的旧 Manifest 继续按原 `category/question/user_choice/response_reference` 结构兼容读取；不得自动补造新问答字段或平台消息 ID。`waived_by_user` 仍须用 `waiver_reference` 留存用户明确跳过询问的说明并强制草稿。
- `not_required` 仅用于确无关键缺口的情形，要求非空 `reason`、空 `required_categories[]`，且 `validation` 已解决、没有未解决事项，所有用途均非 `materials_only/provisional`。

- `schema_version: 2` 时，`case_info`、`submitter`、每组的 `number`、`evidence_name`、`evidence_form`、`proof_object` 以及每个证据材料的 `material_id` 均为必填；缺失或类型错误不得由程序补占位文本。技术性的 `group_id` 可以省略，程序会按组序生成稳定的 `G01`、`G02`……用于 claim 归属。
- 顶层 `context_materials` 可选，必须是数组；每项应为对象并有全局唯一的 `material_id`。它用于保存起诉状、答辩状、仲裁申请书、旧清单或其他背景/待核材料的来源关系，不计入证据组、附件页数或图片嵌入，且不能被 `proof_claims[].material_refs[]` 引用。其编号不得与证据材料重复。
- 顶层 `media_sources[]` 可选，用于保存本地视频探测和截帧索引。每项至少包含唯一 `source_id`、本地 `path`、`source_kind`、原视频 `sha256`、时长、视频流编号和 `frame_index_path`。`source_kind` 只允许 `unverified_local_video`、`original_recording`、`public_demo_copy`、`social_media_copy`；默认和无法核实的本地视频使用 `unverified_local_video`。公开或社交媒体副本可以读取和截帧，但不得自动认定为案件原始载体。
- `case_info`、`submitter` 必填；`signer`、`submission_date` 可留空。缺失案件信息时可在 Manifest 中保留结构化缺口占位并阻断正式版，但 Word 展示层会移除“案号待补/暂缺/缺失”和“案件信息缺失”等占位；若清理后没有已确认案件信息，则省略案件信息段。
- 每组 `group_id` 一旦使用必须唯一；`number` 从1连续递增。
- 每个 `materials[].material_id` 必填且全局唯一；`path` 必须存在且扩展名为 JPG/JPEG/PNG/BMP/GIF/TIF/TIFF，程序还会用 Pillow 实际解码。
- 自动视频截帧进入 `materials[]` 后仍以 PNG 图片作为 `path`，并增加 `video_frame{source_id,source_time_seconds,source_timecode,source_frame_index}`。`source_id` 必须回指 `media_sources[]`；数值时间必须按升序进入同一视频的材料序列，不能按文件名猜测。`source_frame_index` 在可取得固定帧率时保留，否则可以为 `null`，但数值秒和格式化时间码不得缺失。
- `source` 只是截图/截帧的来源标签，不能替代原始载体。v2 每个材料的 `original_carrier` 或兼容字段 `carrier` 必须是对象，并至少有非空 `carrier_location`、`path`、`location` 或 `region` 之一；若使用 `path`，它必须按 manifest 所在目录或绝对路径解析为实际存在的文件或目录，且路径本身及其父级不得经过符号链接、目录联接或其他 reparse point。`carrier_location`、`location`、`region` 若用于物理载体，必须写明确柜位、设备标识、账号、卷盒/案卷编号等具体定位；“已核对”“已留存”“见原件”“见材料”“纸质文件”“微信聊天记录”等占位或泛称均无效。裸字符串载体一律不能进入 v2 正式版。`validation.checks.original_carrier_checked.material_refs` 仍须逐项回指并核验；其中 carrier ref 的 `path` 也必须实际存在且不经过链接，普通证据 `page`＋`region`（如“全图”“聊天区”）不能冒充载体位置。未知 material_id、缺失材料的无位置 ref 和未逐项覆盖都会阻断正式版。
- 视频截帧的 `original_carrier.path` 应回指实际本地视频，并保留与 `media_sources[].source_kind` 相同的 `source_kind`。`unverified_local_video`、`public_demo_copy`、`social_media_copy` 一律阻断正式版；只有用户明确核验并记录为 `original_recording`，且其他载体门槛同时通过时，才可能进入正式版。平台重新编码后的本地副本只能证明该副本自身的时间码和摘要，不能反推案件原录屏真实性。
- `display_rotation_degrees_clockwise`：可选人工展示修正，默认 `0`；只接受整数 `0`、`90`、`180`、`270`。程序先按 EXIF 规范化，再按此字段顺时针旋转；不根据图片尺寸、文件名或视觉效果猜测旋转值。无效值直接阻断。
- `validation.checks` 使用记录对象，状态仅限 `resolved`、`unresolved`、`not_applicable`。每个 `resolved` 项必须同时有非空 `material_refs` 和 `note`；任何未解决事项、冲突或缺失依据均不能正式输出。
- `validation.unresolved_issues[]` 记录歧义、不知道、选择不提供或稍后补充；新协议每项同时写明类别、选择/歧义状态、`entity_ref` 和 `field_key`。同一用户答复绑定多个问题时，各绑定必须用 `binding_basis.raw_response_fragment` 回指各自原文片段。摘要确认还必须保存实际展示的 `summary_snapshot` 和对应助手轮次 `context_locator`，该位置不得与用户确认答复位置相同。只要该数组仍有非空项，即使 `intake_clarification.status=completed` 或 `validation.status` 被误填为 `resolved`，也不得生成正式版。
- 六项核验分别覆盖主体、日期、金额、付款状态、证明范围和原始载体。v1 的布尔值可以读取但不升级为正式依据。
- `proof_claims[]` 每项必须包含 `claim_id`、`text`、`type`、`fact_level`、`role`、`purpose`、`purpose_basis`、`material_refs`、`boundary`。`fact_level` 只能为 `element_fact`、`indirect_fact`、`auxiliary_fact`、`procedural_fact`；`role` 只能为 `direct`、`indirect`、`corroborative`、`rebuttal`、`linking`。`text` 是可回指的原子待证事实；`purpose` 必须说明提交理由及其对应的诉讼请求、仲裁请求、抗辩或证明要件，不能只写“证明内容”、重复材料摘要或“本案诉讼请求/法律要件/第1项请求”等通用标签。`purpose_basis` 必须是对象：`kind` 只能为 `pleading`、`user_statement` 或 `materials_only`；`reference` 是非空页码、段落或用户说明；`kind=pleading` 时还必须定位到页码、段落、条项或书状明确章节，仅写书状名称不足以复核；`status` 只能为 `confirmed` 或 `provisional`；并须填写 `target_kind/target_id/legal_element` 精确回指 `proof_targets[]`。没有起诉状、答辩状或仲裁请求时，应先向用户索取；无法提供时使用 `materials_only/provisional`。任何 `provisional` 或 `materials_only` 都必定阻断正式版，`materials_only` 不得标记为 `confirmed`。`user_statement/confirmed` 的 `reference` 必须记录用户在本任务或本对话中确认的具体请求、抗辩或证明用途；“用户已确认”“用户在本任务中明确确认”等没有具体用途内容的泛称均无效。旧 v1/旧 v2 缺少 v19 字段时可以读取，但只能通过 `--allow-draft` 输出。
- `material_refs` 的每项包含 `material_id`、`page`、`region`，并必须指向证据组中现有材料；程序不得自动生成缺失的 `claim_id`，也不得把 `context_materials` 当作底层证据。
- 组内 claim 归属于所在组；顶层 claim 应写 `group_id`。refs 跨组时必须显式写 `cross_group: true`（或 `group_scope: "cross_group"`），程序会选择一个确定归属并显示跨组回指，但每条 claim 只渲染一次。
- v19 中跨组 claim 还必须使用 `role=linking`，并在 `purpose` 中逐一写明实际组号或 `group_id`，明确说明“结合第X组与第Y组证据”等衔接；“结合证据”等泛称不足以通过；`role=linking` 不得用于没有跨组回指的 claim。
- `page` 可以是数字页码或“封面/签署页”等可核验页标签，表示原始材料内部定位，不是Word整卷页码；文档中的组内页次也是程序生成的附件顺序。Word证据表第三列“页码”另由附件书签、`PAGEREF`和页脚`PAGE`域形成整卷物理页码。
- 订单/协议额、二维码/申请额、实际支付额、对方认可/结算额必须分开记录；采用金额还须保留 `source_amounts[]`、`calculation_results[]`、`adopted_amount` 和 `amount_kind=gross_due|net_outstanding`。没有分项计算时 `calculation_results` 使用空数组；存在计算时每项保存可复算且一致的 `expression/result/source_refs[]`。净余额必须至少有一项与余额一致的可复算结果；标为 `resolved` 时全部净余额计算都须与采用金额一致，来源间仍有差异则以 `ambiguous` 留痕。净余额还须标明 `historical_payments_already_deducted=true` 与 `deduct_historical_payments=false`，禁止再次扣减。付款/返还记录按 `entity_ref` 与具体时间范围分区；不同款项一笔已付、一笔未付不是冲突，同一款项同一期间的混合状态或未核状态才阻断正式版。
- 同一 SHA-256 内容形成 canonical/alias；声明的 canonical 必须与别名具有相同 SHA-256，且 `canonical_material_id`/`alias_of` 与 `material_aliases` 必须双向存在、双方 material_id 均已列出。默认只嵌入 canonical 一次，但来源索引保留所有 alias。视觉相似但哈希不同不得自动去重。
- 视频截帧也只按输出 PNG 的完全相同 SHA-256 去重；重复帧的所有原视频时间码必须继续保存在 `video-frame-index.json` 的 alias 映射中。
- DOCX 内嵌 PNG 不写入 `source_sha256`、`material_id` 或本机路径等隐藏 metadata；来源摘要和材料编号只保留在 Manifest/QA 侧车中。DOCX core properties 也不得写入提交人、案件信息或本机路径。

`proof_object` 是 Word 展示字段，只写积极、简洁、可回指的待证事实及其服务的具体请求、抗辩、法律要件或明确背景用途；不得只写“证明合同内容”“证明聊天记录”等材料摘要，也不强制使用统一模板开头。“仍待核”“不能单独证明”“仍需补强”以及原件、真实性、送达、付款/清偿状态等待核尾句只能进入 `proof_claims[].boundary`、核验记录和 AI 交付回复。展示层会兼容清理已有 Manifest 的此类尾句，但不修改 Manifest 原文；清理后没有积极命题时拒绝生成。“尚未付款”等经核验的实体事实不得因展示清理而删除。

`validation.status` 只有在上述门槛全部通过时才能为 `resolved`；`--allow-draft` 只允许生成带中性“内部核对稿”标识的草稿，不会把未解决事项变成已解决。自然语言缺失摘要、技术来源索引、完整路径、哈希和内部阻断明细留在 Manifest/QA 侧车文件及 AI 交付回复，不写入律师可用的 Word 卷。
