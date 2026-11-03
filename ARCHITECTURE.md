# 鲸语 · 项目结构

这份文档把仓库拆成 6 个大板块，说明每块负责什么、依赖谁、扩展时改哪里。
面向想二次开发或长期维护的人；普通使用只需要看 [README.md](README.md)。

```text
┌─────────────────────────────────────────────────────────────┐
│ ① 入口与运行时保护   main.py / bootstrap / single instance   │
└───────────────┬─────────────────────────────────────────────┘
                │ 创建
┌───────────────▼───────────────┐   ┌─────────────────────────┐
│ ⑤ 桌面 UI（PyQt6）            │   │ ⑥ 调度与发布             │
│ 侧边导航 / 页面 / 工作线程     │◄──►│ APScheduler / updater   │
└───────────────┬───────────────┘   └─────────────────────────┘
                │ 调用
┌───────────────▼─────────────────────────────────────────────┐
│ ② 核心 Agent   free_agent / bili_tool / conversation_agent   │
└───────┬───────────────────────────────┬─────────────────────┘
        │ 调接口                        │ 读写
┌───────▼───────────────────┐   ┌───────▼─────────────────────┐
│ ③ B 站接口层              │   │ ④ 数据与配置                │
│ api + auth/guard/dm/...   │   │ SQLite / config / 凭据加密   │
└───────────────────────────┘   └─────────────────────────────┘
```

---

## ① 入口与运行时保护

| 文件 | 职责 |
|---|---|
| `main.py` | 唯一入口。设置工作目录、DLL 路径、日志、单实例锁、配置校验，然后启动 `MainWindow` |
| `utils/dependency_bootstrap.py` | 源码运行时检查依赖；可用 `WHALETALK_NO_AUTO_INSTALL=1` 关闭自动安装 |
| `utils/single_instance.py` | QLockFile 单实例锁（`data/app.lock`），避免双开重复发评论 |
| `utils/logger.py` | loguru 控制台 + 文件日志（10MB 轮转，保留 7 天） |
| `utils/ffmpeg_bootstrap.py` | 单文件版首次启动解压内置 ffmpeg |
| `utils/persona_defaults.py` | 首次启动释放默认人设，不覆盖已有 `data/persona.md` |

启动顺序：`日志 → ffmpeg → 配置 → 人设 → QApplication → 单实例锁 → MainWindow`。

---

## ② 核心 Agent

| 文件 | 职责 |
|---|---|
| `core/free_agent.py` | 自由 Agent 主循环：拼系统提示、最多 12 步工具调用、结束审计 |
| `core/agent_protocol.py` | 解析模型输出的 JSON 决策（兼容各种格式偏差） |
| `core/bili_tool.py` | 把 `BilibiliAPI` 的公开方法自动暴露成一个 `bili_api` 工具；执行写操作上限与参数校验 |
| `core/agent_events.py` | @ / 评论 / 私信事件去重与投递状态持久化 |
| `core/agent_summary.py` | 总结审计、动作与总结一致性校验、早期工具结果压缩 |
| `core/self_evolution.py` | 在线学习：把观察到的语言、梗、兴趣、经验、知识沉淀成带权重的成长档案 |
| `core/style_guard.py` | 发送前检查重复开头/口头禅/梗复用，必要时改写成更自然的表达 |
| `core/free_context.py` | 组装人设 + 近三天日记 + 长期记忆 + 成长档案 + 说话方式；读写日记 |
| `core/long_term_memory.py` | 日记 → 长期记忆的整理 |
| `core/conversation_agent.py` | 单条评论/私信的多轮回复 Agent（最多 8 步） |
| `core/comment_manager.py` | 回复检查、自动回复、私信处理，串起 `ConversationAgent` |
| `core/comment_events.py` / `core/comment_images.py` | 评论事件收集与评论图识图 |
| `core/frame_analyzer.py` / `core/audio_transcriber.py` / `core/cloud_transcriber.py` | 视频关键帧、本地/云端语音转写 |

**一轮 Agent 的数据流**

```text
人设 + 近三天日记 + memory.md
        ↓
模型输出 {"action":"call","tool":"bili_api","arguments":{...}}
        ↓
BiliTool.call → 参数校验 → 写操作限流 → BilibiliAPI
        ↓
结果裁剪（3500 字符）→ 回灌模型 → 继续或 finish
        ↓
总结审计 + 动作一致性校验 → agent_sessions 表
```

安全边界始终在程序层：每日评论上限、单轮写上限（`limits.max_writes_per_round`）、
12014/412 冷却、单次运行步数。这些不写进人设，也不依赖模型遵守。

---

## ③ B 站接口层

`core/bilibili_api.py` 只保留“视频/搜索/字幕/媒体流”这些读接口，
登录、风控、互动按 mixin 拆开：

| 文件 | 职责 |
|---|---|
| `core/bilibili_api.py` | `BilibiliAPI` 组合根；搜索、视频详情、字幕、媒体流、账号投稿 |
| `core/bilibili_auth.py` | 二维码登录（官方 `login_v2`）、Cookie 持久化与 DPAPI 加密、登录检查 |
| `core/bilibili_guard.py` | 412 风控、12014 发评论冷却、评论请求限速与抖动 |
| `core/bilibili_comment.py` | 评论列表、楼中楼、发评论、点赞评论 |
| `core/bilibili_dm.py` | 私信会话、私信发送、@ 消息 |
| `core/bilibili_interact.py` | 点赞、投币、收藏、关注、分享、弹幕、动态 |

`BilibiliAPI` 的继承关系：

```text
BilibiliAPI(BiliAuthMixin, BiliGuardMixin, BiliDMMixin,
            BiliCommentMixin, BiliInteractMixin)
```

新增一个 B 站接口时：写到对应 mixin → 补测试 → 如果是写操作，加入
`bili_tool._WRITE_METHODS` 并考虑限流。工具列表由 `dir(self.bili)` 自动生成，
无需手动登记。

---

## ④ 数据与配置

| 文件 | 职责 |
|---|---|
| `utils/db_models.py` | SQLAlchemy ORM 模型（视频、评论、点赞、记忆、事件、配额、成长档案…） |
| `utils/db_migrations.py` | `PRAGMA user_version` 版本化迁移；WAL + busy_timeout |
| `utils/database.py` | `Database` 门面：每线程一个 `scoped_session`，业务查询方法 |
| `utils/config_manager.py` | JSON 配置、默认值合并、批量写入、敏感项加密 |
| `utils/secure_store.py` | Windows DPAPI 加密/解密（`dpapi:` 前缀） |
| `utils/reply_scope.py` | 回复范围（全部 / 仅主人）解析 |
| `utils/simple_cache.py` | 视频/评论 TTL 缓存 |
| `utils/media_library.py` | 私信/动态图片收集与描述 |

**存储位置（全部在 `data/`，已被 Git 忽略）**

```text
data/
├── config.json          # 配置；API Key 以 dpapi: 密文保存
├── cookies.json         # B 站 Cookie；DPAPI 密文
├── history.db           # SQLite（WAL）：评论、点赞、事件、Agent 会话
├── persona.md           # 人设
├── diaries/             # AI 自己写的日记
├── memory.md            # 长期记忆（由日记整理）
├── growth.md            # 成长档案快照（自动生成，仅供查看）
├── logs/                # 运行日志
└── models/              # 可选：本地 Whisper 模型
```

在线学习相关表：`observed_texts`（公开文本素材，去重 + 衰减）、
`growth_items`（语言/兴趣/互动/知识/态度，带权重、使用次数和衰减）。
核心人设文件 `persona.md` 不会被自动修改；成长档案只作为上下文参考。

数据库结构用 `PRAGMA user_version` 记录；新增字段只需在
`utils/db_migrations.py` 的 `MIGRATIONS` 末尾追加迁移函数并提升版本号。
SQLite 开启 WAL，GUI 定时器与工作线程各自持有独立 Session。

---

## ⑤ 桌面 UI（PyQt6）

| 文件 | 职责 |
|---|---|
| `gui/main_window.py` | 应用外壳：左侧分组导航、页头（状态胶囊/操作）、页面容器、托盘、生命周期 |
| `gui/dashboard_tab.py` | 首页：4 个 KPI 卡（含迷你趋势）、最近动作、账号与风控、待处理通知 |
| `gui/comments_tab.py` | 按楼查看评论对话，异步加载楼中楼 |
| `gui/messages_tab.py` | 私信会话与发送 |
| `gui/settings_page.py` | 设置：账号/人设/AI/刷视频/互动/成长/上限/更新；输入防抖 + 批量保存 |
| `gui/styles.py` | 全局 QSS 设计 token（颜色、圆角、字号、间距） |
| `gui/icons.py` + `assets/icons/` | SVG 图标加载 |
| `gui/analysis_worker.py` | Agent 轮次 / 回复检查的后台线程 |
| `gui/memory_worker.py` | 长期记忆整理线程 |
| `gui/update_check.py` | 更新检查与下载线程、更新弹窗 |
| `gui/login_dialog.py` | 扫码登录对话框（生成与轮询都在工作线程） |

**线程模型**

- 所有网络请求都在 `QThread` 中执行，结果通过 `pyqtSignal` 回到 GUI 线程。
- 共享对象（`BilibiliAPI`、`Database`、`ConfigManager`）内部各自做了线程隔离：
  `Database` 用 `scoped_session`，配置写入用批量 + 防抖。
- 需要跨线程触发 GUI 操作时，`MainWindow` 用 `scheduled_run_requested` /
  `scheduled_reply_check_requested` 信号切回主线程。

**界面结构**

```text
MainWindow
├── 左侧 sidebar：品牌 / 工作台 / 互动 / 记录 / 系统 / 账号 / 版本
└── 右侧 content
    ├── pageHeader：标题、副标题、统计胶囊、登录状态、自动运营、立即运行
    └── QTabWidget（隐藏原生 tab bar）
        ├── 仪表盘    ├── 控制台    ├── 评论
        ├── 私信      ├── 历史记录  └── 设置
```

---

## ⑥ 调度、运营与发布

| 文件 | 职责 |
|---|---|
| `core/scheduler.py` | APScheduler：随机巡视间隔、回复检查、DeepSeek 闲时窗口 |
| `utils/updater.py` | 版本比较、GitHub Release 检查、下载、SHA256 校验、更新脚本 |
| `WhaleTalk.spec` | PyInstaller 打包（onedir / onefile，内置 ffmpeg 处理） |
| `start.bat` / `start.sh` | 源码启动脚本 |
| `.github/workflows/ci.yml` | CI：ruff（F/E9/B）+ compileall + pytest（3.10/3.12） |
| `tools/backfill_comment_videos.py` | 一次性数据修复脚本 |
| `tools/enable_wer_localdumps.ps1` | 开启 Windows 崩溃转储 |

**一次自动运行的链路**

```text
APScheduler 30s 轮询
  → 到点后发信号回主线程
    → AnalysisWorker(QThread)
      → FreeAgent.run_analysis_cycle()
        → 工具调用 / 写操作限流
      → 结果写库、刷新仪表盘
```

发布：`pytest` + `ruff` + `compileall` 全绿 → `PyInstaller WhaleTalk.spec`
→ `dist/WhaleTalk/` 压缩为 ZIP → 上传 Release（附 `SHA256SUMS.txt`）。

---

## 依赖方向（只允许向下）

```text
gui  →  core  →  utils
 │        │        │
 └────────┴────────┘
   main.py 只做装配
```

- `core` 不导入 `gui`。
- `utils` 不导入 `core` / `gui`。
- `gui` 可以导入 `core`、`utils`。

## 测试

```bash
python -m pytest -q
python -m ruff check .
python -m compileall -q core gui utils tests main.py
```

测试集中在纯逻辑层（Agent 协议、限流、配置、数据库迁移、更新校验、
凭据加密、上下文压缩等），GUI 用离屏/真实窗口截图做人工冒烟。
