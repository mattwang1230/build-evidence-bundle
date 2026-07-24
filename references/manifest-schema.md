# Manifest 格式

保存为 UTF-8 JSON。最小示例：

```json
{
  "case_info": "原告某某诉被告某公司、某某劳务合同纠纷案",
  "submitter": "原告某某",
  "signer": "",
  "submission_date": "",
  "validation": {
    "status": "resolved",
    "checks": {
      "identity_checked": true,
      "dates_checked": true,
      "amounts_checked": true,
      "payment_status_checked": true,
      "proof_scope_checked": true
    },
    "unresolved_issues": []
  },
  "evidence_groups": [
    {
      "number": 1,
      "evidence_name": "原告与被告微信聊天记录截图",
      "evidence_form": "电子数据打印件",
      "proof_object": "原告自某年某月起……，拟证明……。",
      "materials": [
        {
          "path": "materials/01-联系人资料页.jpg",
          "source": "某微信录屏.mp4",
          "source_time": "00:00:03",
          "fact": "锁定聊天账号主体"
        }
      ]
    }
  ]
}
```

## 字段规则

- `case_info`：案件名称或案由信息，不写未经确认的案号。
- `submitter`：提交证据一方。
- `signer`、`submission_date`：可留空供打印后填写。
- `validation.status`：正式版必须为 `resolved`。
- `validation.checks`：五项必须全部为 `true`。
- `validation.unresolved_issues`：正式版必须为空数组。
- `number`：必须从1连续递增。
- `evidence_name`：本组材料的可识别名称。
- `evidence_form`：原件、复印件、电子数据或电子数据打印件。
- `proof_object`：严格按证据可证明范围书写。
- `materials`：按最终嵌入顺序排列。
- `materials[].path`：必须是存在的 JPG、JPEG、PNG、BMP、GIF 或 TIFF 图片。
- 相对路径以 manifest 文件所在目录为基准；也可以填写绝对路径。
- `source`：可选，记录截图或截帧来自哪个原文件。
- `source_time`：可选，录屏截帧时间戳。
- `fact`：可选，内部核验用待证事实，不直接写入 Word。

视频、音频不能直接嵌入标准卷。先截取能稳定展示的画面，同时在 `source` 中记录原始载体。
