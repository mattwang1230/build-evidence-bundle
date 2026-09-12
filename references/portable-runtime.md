# v19 可移植运行说明

## 必需能力

- Python 3.10 或更高版本；
- python-docx：生成可编辑 DOCX；
- Pillow：图片解码、EXIF 方向和安全缩放。

安装 Python 依赖：

    python -m pip install -r scripts/requirements.txt

Skill 不捆绑二进制工具，也不包含跨平台一键安装器。依赖安装由 Agent 根据当前宿主能力执行。Agent 必须先检测现有能力，只有用户已明确授权安装运行依赖，或在缺少具体能力时通过一次简短授权后，才可联网安装；仍须服从宿主的权限和联网审批。

## 安装授权与用户交互

- 用户只说“安装 Skill”：安装 Skill 并检测能力。没有实际视频需求时，不主动安装 FFmpeg；发现用户需要视频且 FFmpeg 套件缺失时，只问一次，说明一个软件包同时提供 FFmpeg 与 FFprobe。不要把安装命令转交给普通用户执行。
- 用户说“安装 Skill 及运行依赖”或“安装并启用视频截帧”：该表述已覆盖基础 Python 依赖和 FFmpeg 套件，无需再问一次“是否安装”；直接进入可信软件源安装，宿主弹出的管理员、联网或沙箱审批仍保留。
- 安装来源：优先系统包管理器、操作系统应用商店或已核验的官方发行渠道；不得从搜索结果中的不明镜像下载可执行文件。
- 安装范围：优先用户级、项目级或显式可执行文件路径；未经授权不修改系统级 PATH，不安装 LibreOffice 等尚未触发的可选工具。
- 路径发现：安装完成但当前进程尚未刷新 PATH 时，定位可信安装目录，并将可执行文件显式传给 `office_capabilities.py` 和截帧/转换脚本；不得因此误报工具未安装，也不为省事修改系统级 PATH。
- 验证：分别读取 `ffmpeg`、`ffprobe` 版本，再用合成视频实际提取至少一帧并核对索引。命令存在、包管理器返回成功或版本可读，均不能单独替代功能验证。
- 失败收口：权限、网络或可信软件源不可用时，报告具体阻断和仍可用能力，不循环请求，不改用不明下载源。

## 可选本地工具

- 视频：FFmpeg 与 FFprobe；
- Office 转 PDF：LibreOffice 的 soffice 或 libreoffice；
- PDF 转 PNG：pdftoppm 或 mutool。

工具可在 PATH 中，也可通过 CLI 参数显式指定。运行：

    python scripts/office_capabilities.py --json

输出只显示工具名、版本和发现方式，不显示可执行文件绝对路径。缺少可选工具只影响相应能力；普通图片流程不得因此退化。

LibreOffice 不作为安装 Skill 时的默认依赖。只有实际发现需入卷的 XLSX、PPTX 或 DOCX 且缺少转换链时，才向用户说明：Office 文件仍可只读预检，但不能生成可入卷证据页。提供三个流程选项：安装 LibreOffice 后进入受支持的自动转换链；使用已有 Microsoft Office 手动导出 PDF 供人工核对，但当前脚本不直接接受 PDF，不能据此自动建立 Office sidecar 或宣称已经入卷；暂不纳入 Office 材料并继续处理普通图片和视频。不得把后两种选择伪装为 Office 正式入卷完成。

## 平台边界

脚本使用 Python 标准库路径、临时目录和列表参数，支持 Windows、macOS 与 Linux。示例只使用相对路径或占位路径。Office 转换使用隔离 LibreOffice profile，不读取或修改用户现有 Office profile。若目标平台没有可复核的渲染能力，验收状态保持 HOLD。
