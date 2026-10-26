# 开发与构建

这是面向开发者的补充文档。普通用户只需要看 [README.md](README.md)。

## 从源码运行

需要 Python 3.10+。

```bash
python -m pip install -r requirements.txt
python main.py
```

Windows 也可以双击 `start.bat`；其他系统运行 `./start.sh`。首次启动会检查并安装缺少的基础依赖。

第一次运行后，在设置页配置 AI 服务与 API Key，并扫码登录 B 站。建议先点“现在巡视一轮”验证，再考虑开启自动运营。

## 测试

```bash
python -m pytest -q
python -m compileall -q core gui utils tests
```

本地转写依赖单独列在 `requirements-transcription.txt`，不会随基础依赖自动安装。

## 构建 Windows 便携版

```bash
python -m pip install pyinstaller
python -m PyInstaller --clean --noconfirm WhaleTalk.spec
```

产物在 `dist/WhaleTalk/`，整个文件夹压缩为 ZIP 后即可发布。

构建机不需要在 PATH 中保留其他 SDK 的 `bin` 目录：`WhaleTalk.spec` 会丢弃 Python 安装目录之外收集到的 DLL，避免本机其他软件（如 poppler、libheif）的同名动态库混入并覆盖系统组件。

发布便携包时把 `ffmpeg.exe` 和 `FFMPEG_LICENSE.txt` 复制到 `dist/WhaleTalk/`，程序会优先使用这个本地 ffmpeg；官方便携包已内置 `ffmpeg.exe`。

### 单文件 EXE

单文件版使用 `build/ffmpeg.zip`（压缩后的 ffmpeg）作为内置 payload：

```bash
# 先准备 build/ffmpeg.zip，其中包含 ffmpeg.exe 和 FFMPEG_LICENSE.txt
set WHALETALK_ONEFILE=1
python -m PyInstaller --clean --noconfirm WhaleTalk.spec
```

产物是 `dist/WhaleTalk.exe`。首次启动时由 `utils/ffmpeg_bootstrap.py` 把 ffmpeg 解压到 exe 旁边的 `data/ffmpeg/`，之后直接复用。

## FFmpeg 查找顺序

程序按以下顺序查找 ffmpeg：

1. 系统 PATH
2. 程序目录 `ffmpeg.exe`
3. 程序目录 `ffmpeg\bin\ffmpeg.exe`
4. `_internal\ffmpeg.exe`
5. `data\ffmpeg\ffmpeg.exe`
6. `C:\ffmpeg\bin\ffmpeg.exe`

## 手动放置本地语音模型

自动下载 `medium` 模型很慢时，可以手动下载 faster-whisper 的 CTranslate2 格式模型，放到：

```
WhaleTalk\data\models\faster-whisper\medium\
```

只需要这 4 个文件：

| 文件 | 大小（字节） |
|---|---|
| `config.json` | 2,257 |
| `model.bin` | 1,527,906,378 |
| `tokenizer.json` | 2,203,239 |
| `vocabulary.txt` | 459,861 |

下载地址：

- <https://huggingface.co/Systran/faster-whisper-medium/tree/main>
- <https://hf-mirror.com/Systran/faster-whisper-medium/tree/main>

放置后重启程序，或在设置页点“打开模型目录”确认路径。程序会优先使用这个目录，不再联网下载模型。也可以从其他机器 HuggingFace 缓存中的 `models--Systran--faster-whisper-medium\snapshots\<hash>\` 复制这 4 个文件。

识别组件（约 92 MB，位于 `data\transcription`）仍然需要先下载一次；本地转写只在没有 B 站字幕时自动启用。

## 默认行为

- 自动运营默认关闭；用户手动开启后才按设置运行。
- 每关键词最多搜索 5 条；搜索结果按关键词轮询交错，每轮随机关键词顺序。
- 每条视频分析参考前 15 条热门评论。
- 「每轮分析视频数」控制每轮最多分析多少条；符合评分/置信度条件才评论，不强制每轮发评论。
- 每日顶层评论上限默认 60（评论+回复合计）；同一视频冷却 7 天。
- 公开评论 @账号主人默认关闭；开启后达到“评论 @我 的最低评分”会 @主人。
- 视频标题/字幕明确要求“把这个视频 @ 给主人”时，会按指令评论并 @主人。
- 评论监听还会检查自己投稿视频下的评论；每次最多 10 条，最新优先。
- 每个视频最多抽取三张关键帧；没有字幕或转写文本时置信度会降低，并阻止自动公开评论。
- 自动巡视可限制在 DeepSeek 闲时段；回复检查不受该时段限制。

## 风控与平台限制

### 412

程序会自动串行化评论请求、加随机间隔、缓存分析评论页；遇到 412 会暂停评论请求、分析周期和回复检查 30 分钟。仍频繁出现时：

1. 只运行一个程序实例；
2. 拉长评论回复检查和评论监听间隔；
3. 降低每轮分析视频数；
4. 先停半小时到一小时；
5. 重新扫码登录，避免共享代理/VPN/机房 IP；
6. 检查系统时间是否准确。

### 12014

B 站返回 `12014 已达到当前评论发送上限` 时，程序会暂停发评论到次日 00:05，并把冷却状态持久化到 `data/posting_blocked.json`；重启后仍会继续冷却。

实测账号的 B 站发送上限包含评论与回复；默认「每日最大发送数（评论+回复）」为 60。不要调得更高，也不要连续多轮评论。

## 核心人格、日记与长期记忆

- `data/persona.md`：用户填写的核心人格，模型只读，不自动修改。
- `data/diaries/to_owner/`：每日日记，记录真实互动和统计；同一天覆盖。
- `data/memory.md`：长期记忆，只有一个文件，分两块：
  - `## 一、以前发生的事件`：最近 7 天 + 重要事件
  - `## 二、学到的东西`：`### 经验` 与 `### 风格`
- `core/long_term_memory.py` 每天读取新日记，交给 AI 整理后整篇重写 `memory.md`。
- 整理状态在 `data/memory_state.json`；同一天只整理一次。
- 回复和私信读取 `memory.md`，不读取整篇日记。
- 不再有独立的 `persona_style.md`、自动复盘、人设候选、风格快照或行为评估。

## 只读工具 Agent（2.0）

- `core/tool_agent.py` 定义 `ReadOnlyTools` 和 `ToolAgent`。
- 工具清单：搜索视频、视频详情、读评论、自己投稿、最近评论、长期记忆、统计、日记。
- AI 每步只输出 JSON：`{"action":"tool",...}` 或 `{"action":"finish",...}`；最多 6 步。
- 只读，不提供评论/点赞/私信/发动态等写工具。
- 运行记录写入 `data/agent_traces/`，GUI 设置页按钮“自主观察一轮”触发，后台线程执行。
- 新增模块需要加入 `WhaleTalk.spec` 的 `hiddenimports`（`gui.agent_worker`、`core.tool_agent`、`utils.media_library`、`utils.persona_evolution`、`utils.probability`、`utils.reply_scope`）。

## 真人行为概率

配置键在 `interaction` 下：

| 键 | 默认 | 行为 |
|---|---|---|
| `prob_like_reply` | 50 | 回复后给网友评论点赞 |
| `prob_report_watch` | 50 | 上报观看进度 |
| `prob_favorite_video` | 20 | 评论成功后收藏视频 |
| `prob_follow_up` | 10 | 关注 UP 主 |
| `prob_like_dynamic` | 10 | 点赞 UP 动态 |
| `prob_post_dynamic` | 5 | 发视频动态 |

对应的总开关是 `like_replied_comments`、`report_watching`、`favorite_commented_video`、`follow_commented_up`、`like_up_dynamics`、`post_video_dynamic`。概率设 0 即关闭。

## 数据与隐私

API 密钥、B 站登录凭证、配置、历史数据库、日记、识别模型和本地组件保存在 `data/` 下，并由 Git 忽略。请勿提交本地配置或凭证。

画面缩略帧只为分析请求临时生成；发往视觉模型的图片和分析文本会按所配置 AI 服务的隐私政策处理。

## 发布检查清单

- `python -m pytest -q` 全绿
- `python -m compileall -q core gui utils tests` 通过
- 便携包内含 `ffmpeg.exe`、`FFMPEG_LICENSE.txt`
- 全新解压后能启动，`data/` 正常创建
- `data/` 不被提交，版本号与 Release 一致
