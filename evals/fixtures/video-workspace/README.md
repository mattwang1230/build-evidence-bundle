# 全合成视频评测夹具

本目录只存放合成材料，不得复制真实案件视频、真实姓名、账号、案号或联系方式。

使用已有本地 FFmpeg 生成两个固定夹具：

```powershell
python make_synthetic_videos.py --ffmpeg "<ffmpeg路径>"
```

- `inputs/demo-6s.mp4`：6秒，蓝、绿、红三段固定画面，用于显式时码和默认自动截帧。
- `inputs/dedup-4s.mp4`：蓝、绿、蓝、近似蓝四段，用于完全相同内容去重和近似画面保留。
- `inputs/corrupt.mp4`：故意损坏的文本占位，用于验证真实解码失败门槛。

评测不要求也不验证动态打码、静音或视频元数据清理。
