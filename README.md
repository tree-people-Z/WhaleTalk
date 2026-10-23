# 鲸语 · B站智能运营助手

鲸语是一个桌面端 AI 角色运营助手，可搜索和分析 B 站视频、生成评论、监听并回复评论。它支持手动巡视和可选自动巡视；自动运行默认关闭。

## 功能

- 以综合排序搜索关键词，并查看播放、评论等热度数据。
- 使用 B 站字幕；没有字幕时，可选安装本地 faster-whisper 转写音频。
- 每条视频最多抽取三张关键帧，和文字证据一起交给支持视觉的 AI 模型分析。
- 按评分和账号设置决定是否评论；可在评论监听中回复互动。
- 自动视频巡视可以设置 DeepSeek 闲时段，回复检查不受该时段限制。
- 启动后自动检查 GitHub Releases，设置页支持一键下载更新（便携版自动替换并重启）。
- 历史记录包含视频链接；运行设置和个人数据保存在本地 `data/` 目录。

## 安装和启动

Windows 用户可从 GitHub Releases 下载便携版 ZIP，解压后双击 `WhaleTalk.exe` 即可启动，无需另行安装 Python 或 VC++ 运行库。请保留同目录的 `_internal/` 运行文件夹。首次启动会在 EXE 同目录创建 `data/`，用于保存设置、登录凭证、数据库、日志和默认人设 `data/persona.md`；已存在的 `persona.md` 不会被升级覆盖。首次使用仍需在应用中配置 AI 服务并扫码登录 B 站。

便携版要求 64 位 Windows 10（1903 或更高版本）或 Windows 11：Qt 6 依赖系统自带的 ICU 组件，便携包不再附带 ICU 动态库，以免与系统组件冲突。

### 检查更新

程序启动后会在后台检查 GitHub Releases，设置页“关于与更新”中也可以手动检查。便携版点击“立即更新”后会下载新版本、自动替换程序文件并在退出后重启，`data/` 目录保持不变；源码运行请直接 `git pull`。

从源码运行需要 Python 3.10+。Windows 双击 `start.bat`；其他系统运行 `./start.sh`。首次启动会检查并安装 `requirements.txt` 中缺少的程序依赖。也可以手动运行：

```bash
python main.py
```

首次启动后，在设置页配置 AI 服务与 API 密钥，并扫码登录 B 站。配置密钥后，先使用“现在巡视一轮”验证，再自行决定是否打开自动运营。

### 本地语音识别（可选）

设置页提供模型选择和“下载本地识别组件和模型”按钮。点击后会安装可选的 `faster-whisper`，并将所选模型下载到 `data/models/faster-whisper`。首次下载模型需要网络和磁盘空间；音频由本机 CPU int8 模式转写，不会发送到语音识别服务。默认模型为 `small`。便携版不包含 Python/pip 环境，无法在应用内自动安装该可选组件；需要本地转写时请使用源码版。

音频提取和画面抽帧需要 FFmpeg，并且 `ffmpeg -version` 可运行。每条视频最多抽取三张压缩画面。配置的 AI 服务需要支持视觉输入；DeepSeek `deepseek-flash` 支持图像输入。音频、抽帧等临时文件会在处理后删除。

## 默认行为

- 自动运营关闭；用户手动开启后才按设置运行。
- 每关键词最多搜索 5 条，每轮最多分析 20 条。
- 自动巡视间隔 5–30 分钟；评论回复检查每分钟一次。
- DeepSeek 视频巡视默认仅在配置的闲时段运行；回复检查全天运行。
- 每日评论上限 999、评论分数门槛 10；同一视频冷却 7 天。
- 公开评论 @账号主人默认关闭；开启后评论评分达到“评论 @我 的最低评分”（默认 13）时会在评论中 @主人，可在设置页调整门槛。
- 仅画面、没有字幕或转写文本的判断会降低置信度，并阻止自动公开评论。

所有设置均可在界面中更改。B 站平台对自动操作有自己的规范和限制，请谨慎设置评论频率并遵守平台规则。

## 开发和验证

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m compileall -q core gui utils tests
```

可选本地转写依赖单独列在 `requirements-transcription.txt`，不会随基础依赖自动安装。

### 构建 Windows 便携版

```bash
python -m pip install pyinstaller
python -m PyInstaller --clean --noconfirm WhaleTalk.spec
```

产物在 `dist/WhaleTalk/`，将整个文件夹压缩为 ZIP 后即可发布到 GitHub Releases。构建机不需要在 PATH 中保留其他 SDK 的 `bin` 目录：`WhaleTalk.spec` 会丢弃 Python 安装目录之外收集到的 DLL，避免本机其他软件（如 poppler、libheif）的同名动态库混入并覆盖系统组件。

## 本地数据与隐私

API 密钥、B 站登录凭证、配置、历史数据库、日记和识别模型保存在 `data/` 下并由 Git 忽略。请勿提交本地配置或凭证。画面缩略帧仅为分析请求临时生成；发往视觉模型的图片与分析文本会按所配置 AI 服务的隐私政策处理。

## 许可证

MIT，详见 [LICENSE](LICENSE)。
