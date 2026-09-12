# 证据清单及证据册 Skill

`build-evidence-bundle` 是面向中国诉讼材料整理的 Codex Skill。它读取本地图片、视频及经安全预检的 Office 材料，生成统一格式、可编辑的“证据清单＋内嵌证据材料”Word 文档。

当前版本：`19.0.1`

## 主要能力

- 生成统一 A4 版式的五列表格证据清单，并按清单顺序编入证据材料；
- 读取本地视频或录屏，按明确时码或自动策略提取 PNG 帧，保留视频、时间码、截帧和材料编号索引；
- 按“请求/抗辩—法律要件—待证事实—证据作用—材料位置”组织证明对象；
- 对金额、付款、材料来源和用户答复进行字段级绑定，发现关键歧义时阻止正式版；
- 检查重复材料、原始载体、路径安全、证明范围、覆盖缺口和 Office 派生来源；
- 缺少关键工具或独立页面复核时明确返回 `HOLD/BLOCKED`，不伪造截帧、来源或核验结论。

## 安装

从 [Releases](https://github.com/mattwang1230/build-evidence-bundle/releases) 下载 RedSkill 安装包。ZIP 内只有一个 `build-evidence-bundle/` 目录，其中直接包含 `SKILL.md`。可将 ZIP 交给支持 Skill 的 Agent，并要求：

> 安装这个 Skill，并检测和安装其必要运行依赖。需要视频截帧时一并启用 FFmpeg/FFprobe。

也可以将解压后的 `build-evidence-bundle` 目录放入本机 Codex Skills 目录。

## 依赖

- 基础：Python 3.10+、`python-docx`、`Pillow`；
- 视频：FFmpeg 套件（通常同时包含 `ffmpeg` 与 `ffprobe`）；
- Office 文件转换：LibreOffice，可选；普通图片和可用的视频流程不依赖它。

Skill 不捆绑第三方二进制。安装后应运行依赖检测；视频能力必须用合成视频完成一次真实截帧，不能只检查命令是否存在。

## 安全边界

- 默认只处理本地材料，不自动上传案件文件；
- Word 中的图片是阅卷副本，不能替代原始电子数据或纸质原件；
- 视频动态打码、OCR 敏感信息识别、静音、元数据清理和社交平台上传不属于本 Skill；
- 用户陈述、写作选择和“追问完成”不能自动升级为事实或来源已经核验；
- 没有独立页面渲染复核时，正式视觉验收保持 `HOLD/RENDER_REVIEW_UNAVAILABLE`。

详细工作流见 [SKILL.md](SKILL.md)。Manifest 字段见 [references/manifest-schema.md](references/manifest-schema.md)。公开发布规则见 [references/publication-safety.md](references/publication-safety.md)。

## 源码与评测

GitHub源码保留 `evals/` 合成评测；RedSkill运行时安装包排除该目录。公开包不得包含真实案件、真实Manifest、个人信息、本机绝对路径、日志或私有中间物。

发布前可运行：

```powershell
python scripts/package_check.py .
```

## 许可

MIT，见 [LICENSE](LICENSE)。
