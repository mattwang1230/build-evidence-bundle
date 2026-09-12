---
name: build-evidence-bundle
description: 读取中国诉讼案件图片或本地视频，对 XLSX/PPTX/DOCX 执行只读结构预检及可选本地转换；按“请求/抗辩—法律要件—待证事实—证据作用—材料位置”整理为可编辑的“证据清单＋内嵌证据材料”Word卷，并执行来源、证明范围、覆盖缺口、Office sidecar 和原始载体硬校验。
---

# 证据清单与证据材料卷

## 目标

清单表格在前，附件按清单顺序逐页嵌入；五列表格使用每组简洁、可读的 `proof_object`。v19 的核心链条是“请求/抗辩—法律要件—待证事实—证据作用—材料位置”：`proof_targets[]` 列出经书状或用户确认的目标与要件，`proof_claims[]` 逐项记录事实层级、直接/间接/补强/反驳/衔接作用、用途依据和材料页码/区域。Word 证明对象只写积极事实命题及其对应请求、抗辩、法律要件或明确背景用途；不强制使用“拟证明……用于支持……”模板，也不把防御性边界写进第五列。

本 Skill 可读取用户提供的本地视频或录屏，按明确时码或固定的“场景变化＋最大间隔”策略自动提取 PNG 帧，并保留“视频—时间码—截帧—材料编号”索引；视频帧随后复用现有图片预检和 Word 管线。第三列为“页码”，用 Word `PAGEREF` 域回指该组附件在整卷中的实际物理页码，显示为“第8页”或“第8-10页”；每页页脚用 `PAGE` 域显示连续页码。请求—要件—证据覆盖矩阵另存为内部 JSON 侧车，识别无用途材料、无证据要件、部分覆盖、跨组衔接和冲突，不写入律师可用的 Word。附件页只显示证据编号、证据名称和组内页次；路径、哈希、`material_id`、`canonical`、载体字段和完整阻断明细留在 Manifest/QA 侧车文件。每张图等比例缩放、不裁切，不能生成只剩页头的空白页。原始电子数据、纸质原件、录屏和银行原始凭证必须继续保存，Word 图片只是阅卷副本。

**能力边界：** 视频读取和自动截帧属于本 Skill；动态打码、OCR 敏感信息识别、静音、视频元数据清理和社交平台上传不属于本 Skill。宣传视频须在独立本地流程中完成脱敏，并对平台重新编码后的公开副本再次复核。已发布社交媒体视频的本地下载/导出副本可以截帧，但只能标记为 `public_demo_copy` 或 `social_media_copy`，不能自动认定为案件原始载体。

**公开运行边界：** v19 只依赖包内相对路径和用户本地工具，不依赖 Codex 私有缓存、本机用户名或固定盘符。普通图片能力只需 Python 依赖；视频和 Office 转换器均为可选能力。缺工具时保留可复核盘点并返回 HOLD/BLOCKED，不得伪造帧、页面或来源链。

**安装与依赖交互：** 先检测，后安装，不让用户自己研究命令、PATH 或分别安装 FFmpeg/FFprobe。这是 Agent 执行协议，不是包内自带的一键安装器；宿主禁止联网、提权或软件安装时只能报告阻断。用户只要求“安装 Skill”时，安装 Skill 后报告能力检测结果；如用户需要视频而 FFmpeg 套件缺失，只提出一次简短授权，说明一个可信软件包同时包含 `ffmpeg` 与 `ffprobe`。用户已明确要求“安装 Skill 及运行依赖”或“安装并启用视频截帧”时，不再重复询问自然语言确认，可直接使用系统可信软件源安装基础 Python 依赖和 FFmpeg 套件，但仍服从宿主的权限/联网审批。安装后必须核对两个命令并用合成视频完成一次真实截帧；仅发现命令不能宣称功能可用。不得从不明网页下载二进制文件，不得未经授权修改全局 PATH 或安装无关工具。LibreOffice 不随 Skill 默认安装；仅在实际发现需入卷的 XLSX/PPTX/DOCX 且没有可用转换链时，说明影响并提供三种流程：“安装 LibreOffice 后进入受支持的自动转换链”“使用已有 Microsoft Office 手动导出 PDF 供人工核对，但当前 PDF 不能直接替代 Office sidecar 或自动入卷”“暂不纳入 Office 材料”。普通图片及可用的视频流程继续，不因缺少 LibreOffice 整体停止。详细规则见 `references/portable-runtime.md`。

## 必须读取

- `references/intake-clarification.md`：缺失信息识别、分轮追问、用户拒绝后的留痕与降级规则；
- `references/evidence-writing-rules.md`：分组、排序和证明对象写法；
- `references/material-filling-rules.md`：原件、图片、金额、日期、去重和分页；
- `references/manifest-schema.md`：Manifest v2 和 v1 降级规则；
- `references/proof-object-rubric.md`：证据链硬门槛、来源层级、一票否决及正反例。

- references/portable-runtime.md：跨平台依赖、能力探测和可选工具降级；
- references/office-sidecar.md：Office 原文件、转换记录、内部定位和逐页映射；
- references/publication-safety.md：公开包隐私、合成示例和本地处理边界；
- references/v19-release-gates.md：PASS/HOLD/BLOCKED/DRAFT 与发布验收。

## 工作流

0. 缺口澄清。先按 `references/intake-clarification.md` 读取授权材料、已有答复并完成可用工具检查；能读取、计算或回查得到的答案先自行取得。用户说“材料里有”时先回查，不立即重复索取。发现真正缺口后，将 `intake_clarification.status` 设为 `pending`；通常每轮1—2问、最多3问，一个问题只处理一个明确 `entity_ref + field_key`，前置问题未解决时不问依赖细节。面向用户自然说明“已知信息/具体差异＋需要确认的事项”，不机械输出四段式标签。可以推荐先做内部核对稿等流程，不得推荐案件事实答案。用户可自然短答，也始终可以表示不知道、不提供、稍后补充，或选择“请 AI 回查已授权材料后判断”。材料判断选项是流程授权，不是用户提供的事实；必须实际回查并保留来源，材料不足或冲突时仍按歧义收口。该追问协议已经写入本 Skill，下载者不需要另装其他访谈 Skill。

   **交互硬停止：** 在用户实际回答前，不得创建可供生成的 Manifest，不得调用 `build_evidence_bundle.py`，也不得生成任何 DOCX；`--allow-draft` 不能绕过。只读盘点可以先做，但盘点后发现的新缺口仍须先问。只有每个关键缺失类别均记录实际问题、用户选择和可复核回答留痕，状态才可改为 `completed`；用户明确要求跳过询问时才可用 `waived_by_user`，且只能生成草稿。没有关键缺口时可用 `not_required`，但必须说明理由，且不得同时存在未解决核验、`materials_only` 或 `provisional` 用途。

   用户选择“不知道、选择不提供或稍后补充”时，不换措辞反复追问同一字段，也不猜测补齐。连续两轮后重新评估剩余问题的价值。用户一旦明确要求先做内部核对稿，若剩余问题均可作为待核事项降级，当前回复立即收口，不得再追加上下文、书状、主体、付款等事实问题；只记录未决字段并继续整理。若缺少可读取材料、发生路径冲突或解码失败等不可降级技术错误，具体报告停止原因，不把技术阻断包装成继续事实访谈。还必须：

   - 在 `validation.unresolved_issues[]` 记录类别、选择状态、`entity_ref`、`field_key`、缺失内容和影响；
   - 将对应核验项保持 `unresolved`；缺少书状或用户确认时使用 `purpose_basis.kind=materials_only`、`status=provisional`；
   - 对 Manifest 必填字段使用“（案件信息缺失）”“（提交方信息缺失）”等明确占位，不虚构姓名、案号、金额或日期；这些占位及“案号待补/暂缺”不得显示在 Word 中；
   - 旧协议仅通过 `--allow-draft` 生成草稿；`field_binding_v1` 在保存用户“先做内部核对稿”的原话和 `stop_decision.mode=internal_review_draft` 后可强制进入草稿。Word 首页只保留中性的“内部核对稿”，详细缺失部分放入 Manifest/QA 和 AI 交付回复，不在证明对象或首页展开；不得将用户拒绝提供解释成已解决；
   - 只要还有可读取的证据材料，就继续盘点、分组、回指和说明边界。若材料目录不存在、没有任何可用材料或文件无法解码，说明无法生成证据卷的技术原因，并保留已经完成的盘点/缺口清单。

1. 视频读取与自动截帧（有视频时）：

   ```powershell
   python scripts/extract_video_frames.py "<本地视频>" "<隔离帧目录>" --ffmpeg "<ffmpeg路径>" --ffprobe "<ffprobe路径>"
   ```

   默认按场景变化和最大2秒间隔抽取首帧、过程帧及末帧；也可用 `--times "0,2,4.5"` 明确时码。工具只接受本地文件，不下载远程视频，不移动、覆盖或删除原视频；输出目录不得位于原视频所在目录内。每帧记录数值时间、格式化时间码、原视频摘要、视频流、方向归一和结构化载体关系；按数值时间排序，只按输出 PNG 的完全相同 SHA-256 去重，视觉相似帧不自动删除。缺少 FFmpeg/FFprobe、视频损坏、无视频流、时长未知、方向元数据冲突或目标帧无法解码时，停止且不得伪造截帧、Manifest 或 DOCX。

   `--source-id` 默认是 `V001`，只接受安全文件名字符；`--source-kind` 默认是 `unverified_local_video`。只有用户明确核验原录屏时才可使用 `original_recording`；公开演示或社交媒体本地副本使用 `public_demo_copy` / `social_media_copy`，并始终阻断正式举证版。截帧索引只保存原视频文件名、大小、摘要和来源编号，不写本机绝对路径；实际本地视频路径仅由案件 Manifest 的 `media_sources[].path` 与 `original_carrier.path` 保存。截帧工具不执行脱敏。

2. 只读盘点：

   ```powershell
   python scripts/inspect_materials.py "<案件材料目录>" --output "<材料盘点.json>"
   ```

   盘点会实际解码图片、读取 EXIF、报告尺寸/长图/低像素风险，并建立 SHA-256 canonical/alias 索引；视觉相似但哈希不同的图片不自动删除。EXIF 方向先规范化；如仍需人工调整，Manifest 材料必须明确填写 `display_rotation_degrees_clockwise`，只接受 `0/90/180/270`，不根据图片外观猜测。`~$` Office 锁文件和 `.DS_Store` 只留跳过记录；单个文件不可读不得阻止 JSON 盘点写出。

   含 XLSX/PPTX/DOCX 时另运行只读 Office 预检：

   ```powershell
   python scripts/inspect_office_materials.py "<案件材料目录>" --output "<Office预检.json>"
   ```

   v19 继续使用只读 Office 预检：检查 OOXML 包类型、工作表/幻灯片顺序、DOCX 修订与隐藏文字、公式缓存、打印范围、备注/批注、嵌入对象、外链和源读取前后稳定性；它不重算公式、不展开隐藏内容，也不生成证据页。旧 DOC/XLS/PPT 只记录为不支持，不猜测改扩展名。

   先检查本机可选能力：

   ~~~powershell
   python scripts/office_capabilities.py --json
   ~~~

   Office 材料确需入卷时，使用用户已安装的 LibreOffice 与 PDF rasterizer 在全新隔离目录转换：

   ~~~powershell
   python scripts/convert_office.py "<Office源文件>" --workspace-root "<案件工作区>" --output-dir "<全新派生目录>"
   ~~~

   自动转换生成的 sidecar 默认仍为 HOLD/BLOCKED；必须人工确认纳入的工作表/范围或幻灯片、字体、空白页、隐私和页面可读性。没有转换器或逐页映射时，只保留预检/侧车，不得把 Office 文件或派生截图加入任何 DOCX，--allow-draft 也不能绕过。

3. 用户答复或明确跳过后，创建 UTF-8 Manifest v2。新问答使用 `intake_clarification.protocol=field_binding_v1`，仍沿用逐轮 `questions[]`；每问记录全局唯一 `question_id`、`category`、具体 `entity_ref`、单一 `field_key`、`depends_on[]`、带版本的 `answer_context` 和独立 `answer_binding`。`user_choice` 可为 `provided/material_review/unknown/declined/later`；其中 `material_review` 表示用户授权 AI 回查已授权材料后判断该字段，必须用 `material_lookup` 或 `computed` 绑定实际 `source_refs[]`，每个引用以当前 Manifest 已登记的 `material_id/source_id` 开头，结果只能是 `resolved` 或 `ambiguous`。二元问题必须保存具体 `proposition`；选项必须保存稳定 `option_id`、标签和对应 `normalized_value`；摘要必须保存 `summary_id`、版本、字段范围、该版本实际展示的 `summary_values`、展示给用户的 `summary_snapshot` 及其助手轮次 `context_locator`。`answer_binding` 分开保存用户原话、可回查位置、模型规范化值、绑定依据、歧义/未知/拒绝/暂缓状态，并固定标明 `fact_verification=not_verified_by_intake`；同一条用户答复绑定多个问题时，每个绑定还须用 `raw_response_fragment` 指向各自支持片段。`provided/material_review + resolved` 不得缺少规范化值，规范化付款对象如重复写入 `entity_ref` 必须与问题对象一致。宿主未提供消息 ID 时显式写 `null`，不得省略或编造。旧 Manifest 未声明该协议时继续按旧结构读取，程序不得替它补造问题编号、原话、规范化值或消息 ID，也不接受新协议专用的 `material_review`。`schema_version` 只能是整数 `2`（缺失或整数 `1` 仅兼容读取，但缺少询问留痕时连草稿也不得生成；布尔、浮点、字符串和显式 `null` 均拒绝）；`case_info`、`submitter`、证据组核心字段、材料 `material_id` 不得缺失。

   v19 正式版必须先建立 `proof_targets[]`：每个目标包含 `target_kind=claim|defense|rebuttal|context`、唯一 `target_id`、具体 `description` 和非空 `legal_elements[]`。每项 `proof_claims[]` 继续保留 `claim_id/text/type/role/purpose/purpose_basis/material_refs/boundary`，并新增：

   - `fact_level=element_fact|indirect_fact|auxiliary_fact|procedural_fact`；
   - `role` 可用 `direct|indirect|corroborative|rebuttal|linking`；
   - `purpose_basis` 在原有 `kind/reference/status` 外增加 `target_kind/target_id/legal_element`，必须精确回指 `proof_targets[]`；
   - `purpose` 与 Word `proof_object` 不得只写“本案诉讼请求”“法律要件”“第1项请求”等通用标签，必须出现具体请求内容、抗辩理由、法律要件或明确背景事项；`kind=pleading` 的 `reference` 必须定位到页码、段落、条项或书状明确章节，仅写“起诉状/答辩状”不足以复核；
   - `material_refs[]` 必须逐项写材料编号、原材料页码/页标签和图片区域；
   - 跨组共同证明必须 `cross_group=true`、`role=linking`，并在 `purpose` 中逐一写明实际组号或 `group_id`，例如“结合第1组与第2组证据”的衔接。

   每个材料逐项填写对象形式的 `original_carrier` 或 `carrier`，且对象必须有可定位的 `carrier_location/path/location/region` 字段；仅有 `note`、`description`、`status`、裸字符串“纸质文件”“微信聊天记录”“原件”或普通证据 `page＋region` 均不能替代载体。视频截帧还须复制侧车索引中的 `video_frame{source_id,source_time_seconds,source_timecode,source_frame_index}`，并使 `original_carrier.path` 回指实际本地视频。可用顶层 `media_sources[]` 保存视频探测和来源角色；`unverified_local_video`、`public_demo_copy`、`social_media_copy` 都不能作为正式版原始载体。可用顶层 `context_materials[]` 保存起诉状、答辩状、仲裁申请书、旧清单等背景或待核材料；其 `material_id` 必须与证据材料全局不重复，且绝不进入证据表、附件或 `proof_claims[].material_refs[]`。

   缺少书状时先向用户请求起诉状、答辩状、仲裁请求/答辩书或代理意见；用户无法提供但明确说明具体诉讼目标、请求或抗辩时，可使用 `user_statement/confirmed` 并保留可复核原话；既无书状也无明确用途时只能用 `materials_only/provisional`，必定阻断正式版。旧 v2 缺少 v19 的 `proof_targets`、`fact_level` 或目标/要件映射时仍可读取，但只能通过 `--allow-draft` 生成内部核对稿。Word 的 `proof_object` 不能只写“证明合同内容”“证明聊天记录”，应写具体事实命题及其服务的请求、抗辩、法律要件或明确背景用途；“仍待核”“不能单独证明”“仍需补强”、原件/真实性/送达/清偿状态等核验尾句只能写入 `boundary`、核验记录和 AI 交付回复。

   Office 派生页仍使用 Manifest v2 和既有 `bundle_contract=v18` Office 来源侧车协议，并以 `provenance_route=v2_sidecar`、`office_provenance` 回指 Manifest 目录内的 POSIX 相对路径 sidecar。`v18` 在此仅是 Office sidecar 协议版本，不是 Skill 发布版本。每项派生材料必须显式填写 `origin_kind=office_derived` 与 `provenance_ref{unit_id,pdf_page}`。生成器会重新读取 Office 源、PDF、PNG 和 sidecar，核对源大小、修改时间、摘要、OOXML 内部位置、PDF 实际页数、PNG 解码与空白页；路径越界、目录联接、源变化、摘要错配、包预检非 PASS、范围未确认、页序/书签不一致、字体或隐私未通过均为不可降级硬失败。

4. 正式生成：

   ```powershell
   python scripts/build_evidence_bundle.py "<manifest.json>" "<输出.docx>"
   ```

   同时默认生成 `<输出文件名>.coverage-matrix.json` 内部覆盖矩阵；也可用 `--coverage-matrix` 指定安全位置。矩阵不含本机绝对路径，不进入 Word，不替代律师对间接证据充分性的判断。

   正式版要求 `validation.status=resolved`、六项核验有逐项依据、无冲突/未解决事项/不可读材料/缺原始载体/高风险责任措辞。`intake_clarification.status=completed` 只表示追问流程收口，不能把用户陈述升级为事实或来源已核验；`material_review` 也只授权按所列材料定位或计算，不构成对方自认、真实性独立核验、自动法律结论或替用户创设诉讼主张。视频材料还会交叉核验 `media_sources[]`、`video-frame-index.json`、`video_frame` 和 `original_carrier`；用户确认制作不能替代视频真实解码、Office sidecar、路径安全或来源检查。原材料金额、分项计算结果、用户本次采用金额及其 `gross_due/net_outstanding` 含义必须分别保存；净余额已扣除历史付款时禁止再次扣减。付款/返还状态按具体款项实体与时间范围记录，不得在两笔款项间传播。

5. 草稿检查：仅在询问已取得真实答复并收口，或用户已明确 `waived_by_user` 后，才可因未知、拒绝、暂缓或歧义生成草稿。`pending`、缺少 `intake_clarification`、问题为空、回答不可回指、对象/字段不明、一个问题索取多个事项、依赖未解决、二元命题缺失、摘要 ID/版本/字段范围/具体值不对应、选项与规范化值不对应、重复追问未写 `supersedes_question_id`、明确要求草稿后仍追加事实问题或每轮超过3问时，正式版和草稿均阻断。`field_binding_v1` 的 `stop_decision` 必须记录制作/停止原话、未决字段和模式，且原话语义必须与 `continue_build` 或 `internal_review_draft` 一致；已有明确答复、无关键歧义且用户已要求制作时直接继续，不再索取泛泛的“是”。含未解决信息缺口、任何 `purpose_basis.status=provisional`、使用 `materials_only`，以及缺少 v19 目标/要件映射的旧数据始终只能作为内部核对稿；详细缺口留在 Manifest/QA 与交付说明中。

6. 交付前用 `python-docx` 复查证据表、附件顺序、图片数量、上下文材料排除情况、附件标头和 DOCX 可重新打开；视频材料还要核对截帧顺序与侧车数值时间码一致、原视频未被修改、派生公开副本未进入正式版。证据表必须同时检查 OOXML `w:tblGrid`、每个单元格 `w:tcW` 及列宽比例，不能只看 `cell.width`。还要确认表头为“页码”，页码单元格含 `PAGEREF`，每个附件页头有对应书签，页脚含 `PAGE`，`settings.xml` 要求打开时更新域；在 Word 中可用 `Ctrl+A`、`F9` 手动刷新。具备渲染能力时必须核对 PDF 页脚连续、各组“第X页/第X-Y页”与实际附件页一致。附件页的组内页次不是 Word 物理页码。同时确认 Word 未泄漏路径、哈希、内部编号、载体字段、内部索引标题、“案号待补/暂缺”或防御性证明边界。必要时复查 EXIF/展示旋转字段。不得声称截图已经公证、电子数据绝对真实或责任结论已经确定。

   先运行结构及页面复核门禁：

   ~~~powershell
   python scripts/qa_bundle.py "<输出.docx>" --manifest "<manifest.json>"
   ~~~

   缺少独立页面渲染复核时，QA 必须保持 HOLD/RENDER_REVIEW_UNAVAILABLE；不得以 DOCX 可打开或 OOXML 结构通过代替视觉验收。公开发布前另运行 package_check.py，排除真实案件、个人信息、绝对路径、凭据、缓存、锁文件和私有中间物。

## 依赖与包完整性

需要 Python 3.10+；Python依赖见 `scripts/requirements.txt`（`python-docx`、`Pillow`）。视频功能另需 FFmpeg 套件，其中通常同时包含 FFmpeg 与 FFprobe；默认从 PATH 查找，也可通过参数明确指定。Skill 不捆绑媒体二进制；Agent 仅在用户已明确授权安装运行依赖或通过一次依赖授权后，使用系统可信软件源安装，并须完成真实截帧验证。LibreOffice 仅按实际 Office 入卷需求建议，不作为默认安装项。安装用 `.skill` 包必须保留 `agents/`、`assets/`、`references/` 和 `scripts/`；项目源码/评测包另保留 `evals/`，不可只复制本文件。
