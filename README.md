# Eddie’s Video Station

基于 ComfyUI 与 Wan 的本地视频工作站。自由描述、关键词、分镜卡片、首帧参考、LoRA、视频拼接，支持 Agent 通过 MCP 调用。

## 环境需求

Windows 10/11 64 位、NVIDIA 显卡（建议至少 8GB 显存）、32GB 内存、近期 NVIDIA 驱动，预留 35GB 磁盘空间。8GB 优先用 Wan 2.1，低分辨率短镜头起步。

**不需要自己安装 Python、Git 或配置 PATH。** 启动器首次联网下载独立 Python；首次生成自动下载运行环境和所选模型。Git 仓库本身不包含模型。下载完成后可离线使用。

## 使用方式

下载仓库 ZIP 并解压，双击 **Start Video Station.cmd**。

选择存储目录 → 写下画面 → 添加到分镜 → 生成镜头。所有镜头完成后点「合并成片」。

轻量模型配套约 9.2GiB；Wan 2.2 配套约 16.9GiB，两者共用文字编码器。环境压缩包约 1.8GiB。下载支持断点续传，失败原因在任务队列和日志中查看。

## 目录

| 目录 | 内容 |
| --- | --- |
| `.runtime/` | 工作站自己的 Python 和生成引擎，不修改系统环境 |
| `data/models/` | 视频模型、文字编码器、VAE、LoRA |
| `data/input/` | 上传的参考图片 |
| `data/output/` | 生成的视频、参数记录和合并成片 |
| `data/station.db` | 项目、分镜和任务记录 |
| `data/logs/` | 下载、生成和导出日志 |
| `.local/` | 本机设置、接口令牌，不上传 GitHub |

设置中的「连接本地 Agent」可复制 MCP 配置。[接口与开发](docs/DEVELOPMENT.md) · [第三方许可](THIRD_PARTY_NOTICES.md)
