# Office provenance sidecar

## 适用范围

Office 原文件不能直接作为 Manifest v2 的图片材料。XLSX、PPTX 或 DOCX 先只读预检；需要入卷时，在隔离目录转换为 PDF 和 PNG，再以 v18 sidecar 绑定原文件、内部位置、转换记录和逐页派生物。

Manifest 顶层字段为 schema_version=2、bundle_contract=v18、provenance_route=v2_sidecar，并用 office_provenance 指向相对路径侧车。使用 bundle_contract=v18 时，每项材料都要声明 origin_kind；普通材料可用 native_image、scan_image、photo、screenshot、video_frame 或 generated_demo，Office 派生页只能用 office_derived。旧 v2 Manifest 保持兼容，但不会自动取得 v18 Office 来源资格。

每项 Office 派生材料必须含：

    "material_id": "M001"
    "origin_kind": "office_derived"
    "path": "derived/O001-page-001.png"
    "provenance_ref": {"unit_id": "O001-U001", "pdf_page": 1}

所有路径均相对于 Manifest 所在目录，禁止绝对路径、上级目录跳转和符号链接。

## 必需链条

sidecar 必须含：

1. source_snapshot：相对路径、格式角色、大小、修改时间、摘要、读取前后稳定及只读状态；
2. package_inspection：实际 OOXML 类型、损坏/加密、宏、外链、批注、隐藏内容及嵌入对象；
3. source_locators：XLSX 工作表和范围、PPTX 幻灯片/部件、DOCX 部件，以及用户确认的纳入范围；
4. conversion_record：转换器与 rasterizer 的可复核版本、隔离 profile、参数摘要、PDF 路径、摘要和实际页数；
5. page_map：源 unit、PDF 页、PNG 路径与摘要、附件顺序、书签、空白页、字体和隐私复核；
6. formal_release_gate：程序重算后的 PASS 与空失败码。

scripts/validate_provenance.py 会重新读取源 Office、PDF 和 PNG，校验源修改时间与摘要、真实 OOXML locator、PDF 页数/页序、PNG 解码、空白/仅页头、本机路径元数据和门禁。字体、上下文隐私及页面可读性仍必须人工复核；机器只能阻断明显异常，不能伪称已经理解页面语义。只要 Office gate 不是 PASS，--allow-draft 也不能生成含 Office 派生页的 DOCX。普通图片/视频 Manifest 不需要 Office sidecar。

## 转换命令

    python scripts/convert_office.py <source.xlsx> --workspace-root <case-workspace> --output-dir <new-output-dir>

自动转换只形成审阅候选和 HOLD/BLOCKED sidecar，不会自行确认用户选择的工作表/幻灯片范围、字体替换、空白页、隐私或页面可读性。完成独立复核后才能把对应字段改为已核验并重新运行 validator。
