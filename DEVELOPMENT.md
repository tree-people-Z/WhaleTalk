# 开发与构建

面向开发者的补充文档。普通用户只需要看 [README.md](README.md)。

## 从源码运行

需要 Python 3.10+。

```bash
python -m pip install -r requirements.txt
python main.py
```

Windows 也可以双击 `start.bat`；其他系统运行 `./start.sh`。

第一次运行后，在设置页配置 AI 服务与 API Key，填写主人信息，并扫码登录 B 站。建议先点“现在运行一轮”看日志。

## 测试

```bash
python -m pytest -q
python -m compileall -q core gui utils tests
```

## 构建 Windows 便携版

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --log-level=WARN WhaleTalk.spec
```

产物在 `dist/WhaleTalk/`，整个文件夹压缩为 ZIP 后即可发布。

构建机不需要保留其他 SDK 的 `bin` 目录：`WhaleTalk.spec` 会丢弃 Python 安装目录之外收集到的 DLL，避免同名动态库混入。

发布便携包时把 `ffmpeg.exe` 和 `FFMPEG_LICENSE.txt` 复制到 `dist/WhaleTalk/`；官方便携包已内置。

### 单文件 EXE

单文件版使用 `build/ffmpeg.zip` 作为内置 payload：

```bash
set WHALETALK_ONEFILE=1
python -m PyInstaller --noconfirm --log-level=WARN WhaleTalk.spec
```

产物是 `dist/WhaleTalk.exe`。首次启动时由 `utils/ffmpeg_bootstrap.py` 解压到 `data/ffmpeg/`。

### 构建加速

PyInstaller 的 Analysis 和单文件压缩基本是单线程，20 核也不能线性加速。实际有效的做法：

- 测试阶段不加 `--clean`，复用 `build/` 缓存
- 先构建 onedir，发版前再构建 onefile
- 工作目录放在 NVMe 上
- 使用 `--log-level=WARN` 减少日志开销
- 不同时跑多个 PyInstaller 构建

## FFmpeg 查找顺序

1. 系统 PATH
2. 程序目录 `ffmpeg.exe`
3. 程序目录 `ffmpeg\bin\ffmpeg.exe`
4. `_internal\ffmpeg.exe`
5. `data\ffmpeg\ffmpeg.exe`
6. `C:\ffmpeg\bin\ffmpeg.exe`

## 自由 Agent 架构

### 入口

- `core/free_agent.py`：`FreeAgent.run_analysis_cycle()`
- `gui/main_window.py`：自动运营和“现在运行一轮”都调用它
- 固定流水线 `core/video_analyzer.py` 已不参与自动运营

### 每轮流程

```text
人设 + 近三天日记 + 长期记忆
        ↓
模型输出 JSON 工具调用
        ↓
bili_api / read_diary / write_diary
        ↓
结果回给模型，继续或 finish
```

- 最多 12 步
- 模型可以什么都不做
- 不预设搜索、评分、评论顺序

### 接口暴露

`core/bili_tool.py` 把 `BilibiliAPI` 的公开方法自动列成工具：

- 搜索、视频详情、字幕、媒体流
- 评论、楼中楼、发评论、点赞
- 收藏、关注、投币、分享、稍后再看
- 动态、弹幕
- 私信、@
- 自己投稿、请求视频解析

登录/二维码/风控状态设置等内部方法不暴露。

### 上下文

`core/free_context.py`：

- `build_agent_context()`：人设 + 近三天日记 + `memory.md`
- `read_diary()`：列日期、读某天、读全部
- `append_diary()`：追加到当天日记，不强制格式

`gui/memory_worker.py` 只做长期记忆整理，不再自动写日记。

### 安全限制

写操作仍在程序层限流：

- 每日评论/回复上限 `limits.max_comments_per_day`（默认 60）
- 单轮写操作上限 8
- 12014 / 412 冷却
- 评论记录写入数据库，供上限统计

这些限制不写入人设，也不要求模型遵守。

## 设置页

保留：

- B 站账号、主人信息
- 人设
- AI 模型
- 每日发送上限
- 回复范围、评论监听、自动回复、私信开关
- 自动运行间隔与 DeepSeek 闲时

已移除固定流水线相关设置：

- 视频搜索关键词、排序
- 每轮分析数量、评分阈值
- 自动评论、评论 @主人阈值
- 视频互动概率
- 画面分析、语音转写

## 数据与隐私

API 密钥、B 站登录凭证、配置、历史数据库、日记和模型保存在 `data/` 下，并由 Git 忽略。请勿提交本地配置或凭证。

评论/私信图片按需下载；发往视觉模型的内容按所配置 AI 服务的隐私政策处理。

## 发布检查清单

- `python -m pytest -q` 全绿
- `python -m compileall -q core gui utils tests` 通过
- 便携包内含 `ffmpeg.exe`、`FFMPEG_LICENSE.txt`
- 全新解压后能启动，`data/` 正常创建
- `data/` 不被提交，版本号与 Release 一致
