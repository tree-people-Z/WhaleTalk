<p align="center">
  <img src="assets/whale-assistant.png" width="220" alt="鲸鱼娘">
</p>

<h1 align="center">鲸语 · B站智能运营助手</h1>

<p align="center">
  一只住在桌面里的 AI 鲸鱼娘：帮你分析 B 站视频、写评论、回评论，<br>
  也会盯着自己视频下的留言。
</p>

<p align="center">
  <a href="https://github.com/tree-people-Z/WhaleTalk/releases/latest"><img src="https://img.shields.io/github/v/release/tree-people-Z/WhaleTalk?label=%E6%9C%80%E6%96%B0%E7%89%88%E6%9C%AC" alt="最新版本"></a>
  <img src="https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4" alt="Windows 10/11">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
</p>

## 它能做什么

- 🔍 **巡视视频**：按关键词搜索 B 站视频，结合字幕、画面、评论判断质量
- 🧠 **AI 分析**：支持视觉模型看关键帧，也支持无字幕时语音转写
- 💬 **自动评论**：按评分和你的设置决定评不评、怎么评
- 🔔 **回复监听**：有人回复你、@你，或在你自己的投稿视频下留言，会提醒并回复
- 👋 **角色互动**：遇到其他“鲸鱼娘”会打招呼，也会接“鱼会回复吗”这类互动
- 📝 **评论面板**：按 B 站楼层结构查看整栋楼，自己和网友的回复一目了然
- 🎙️ **语音转写**：关闭 / 本地 medium / 云端 OpenAI 兼容接口，三种模式
- 🔄 **一键更新**：内置更新检查，升级时保留 `data/` 个人数据

## 下载

**最新版本**：<https://github.com/tree-people-Z/WhaleTalk/releases/latest>

| 文件 | 适合谁 | 怎么用 |
|---|---|---|
| `WhaleTalk-Windows-x64-single.exe` | 大多数人，最省事 | 下载后双击；首次启动会解压内置 ffmpeg，可能慢几秒 |
| `WhaleTalk-Windows-x64.zip` | 单文件被拦截、启动失败，或想方便备份 | **完整解压**后运行 `WhaleTalk\WhaleTalk.exe` |

> 两个包功能完全一样，**都已内置 ffmpeg**，不需要安装 Python 或 FFmpeg。  
> 单文件版首次打开若遇到 SmartScreen，点“更多信息 → 仍要运行”。  
> 系统要求：64 位 Windows 10（1903+）或 Windows 11。

## 三分钟上手

1. **下载并运行**上表中的任意一个版本。
2. 打开 **设置 → AI 模型设置**，填入 AI 服务的 Base URL、API Key 和模型名。
3. 在 **B站账号设置** 扫码登录。
4. 回到控制台点 **“现在巡视一轮”** 验证效果；确认正常后，再自行开启自动运营。

自动运营默认关闭，不会一打开就自动发评论。

## 使用前要知道

- 需要自备 AI API Key，并遵守 B 站平台规则；评论频率不要设得太激进。
- 每日评论上限建议保持 **96**（实测平台上限），触发 12014 后程序会自动停到次日。
- 遇到 412 风控时程序会自动暂停请求，等冷却结束再恢复。
- 设置、登录凭证、历史数据库、人设和模型都在程序目录的 `data/` 里，升级不会删除。

## 常见问题

<details>
<summary><b>单文件 exe 打不开 / 被杀软拦截</b></summary>
<br>
改用 ZIP 版，完整解压后运行 <code>WhaleTalk.exe</code>。单文件版需要系统临时目录可写；受限电脑也可能拦截，这时 ZIP 更稳。
</details>

<details>
<summary><b>评论或回复失败，提示 412 / 12014</b></summary>
<br>
412 是 B 站风控，程序会自动暂停 30 分钟；12014 是当天评论额度用完，程序会暂停到次日 00:05。不要反复重启或连续点“立即巡视”，等冷却结束即可。如果长时间 412，尝试重新扫码登录、减少同视频操作、避免共享代理 IP。
</details>

<details>
<summary><b>本地语音转写模型下载太慢</b></summary>
<br>
可以改用云端转写，或手动下载 faster-whisper medium 模型，放到 <code>data\models\faster-whisper\medium\</code>。详细文件清单和构建方式见 <a href="DEVELOPMENT.md">DEVELOPMENT.md</a>。
</details>

## 开发与构建

源码运行、打包、依赖说明和更多技术细节见 **[DEVELOPMENT.md](DEVELOPMENT.md)**。

## 数据与隐私

API 密钥、B 站凭证、配置、历史数据库、日记和模型只保存在本机 `data/` 目录，并由 Git 忽略。画面缩略帧和处理文本会按你配置的 AI 服务隐私政策处理。

## 许可证

MIT，详见 [LICENSE](LICENSE)。
