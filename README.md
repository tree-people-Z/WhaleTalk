<p align="center">
  <img src="assets/whale-assistant.png" width="220" alt="鲸鱼娘">
</p>

<h1 align="center">鲸语 · AI 运营助手</h1>

<p align="center">
  一只住在桌面里的 AI 鲸鱼娘。<br>
  人设、日记和长期记忆交给她，B 站接口也交给她，由她自己决定怎么行动。
</p>

<p align="center">
  <a href="https://github.com/tree-people-Z/WhaleTalk/releases/latest"><img src="https://img.shields.io/github/v/release/tree-people-Z/WhaleTalk?label=%E6%9C%80%E6%96%B0%E7%89%88%E6%9C%AC" alt="最新版本"></a>
  <img src="https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4" alt="Windows 10/11">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
</p>

## 它能做什么

- 🧠 **自由 Agent**：不再固定“搜索 → 分析 → 评分 → 评论”，由模型自己决定先看什么、做什么
- 🔌 **接口全部暴露**：B 站搜索、视频、评论、点赞、收藏、关注、投币、动态、弹幕、私信等公开接口都做成工具
- 🎭 **人格驱动**：系统只给人设文件、近三天日记和长期记忆，不再写死行为规则
- 📔 **自己写日记**：AI 可以读写日记；写什么、写多长、什么格式都由她决定
- 💬 **回复与私信**：收到回复、@、私信时，由模型结合上下文决定回不回、怎么回
- 👀 **满足互动请求**：网友让看视频、让艾特主人时，模型可以自己解析并执行
- 🖼️ **评论/私信图片**：评论图能在面板显示，也会交给视觉模型理解；私信图会识图；不自动发图
- 📝 **评论面板**：按楼层查看整栋楼，自己和网友的回复一目了然
- 🔄 **一键更新**：升级时保留 `data/` 个人数据
- 🧷 **后台驻留**：点关闭默认留在托盘继续运行；右键托盘图标可真正退出

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
3. 在 **B站账号设置** 填主人 UID / 昵称，并扫码登录。
4. 打开 **设置 → 人设设置**，写清楚她是谁；这会成为她行动的核心。
5. 回到控制台点 **“现在运行一轮”**，看日志里她自己调用了什么接口。

自动运营默认关闭，不会一打开就自己发评论。

## 她怎么工作

```text
人设文件
+ 近三天日记
+ 长期记忆
        ↓
模型自己决定
        ↓
搜索 / 看视频 / 读评论 / 回评论 / 私信 / 点赞 / 写日记 …
        ↓
看结果，继续决定或结束
```

- 每轮最多 12 步
- 可以什么都不做
- 可以调用任意公开 B 站接口
- 可以读所有历史日记，但每次会话默认只自动带近三天
- 写日记不强制格式

## 保留的安全限制

自由不等于无限。以下限制仍在程序里，不交给模型：

- 每日发送上限（默认 60 条评论 + 回复）
- 12014 / 412 冷却
- 单轮写操作次数上限
- 禁止自动发图
- 评论/私信去重与风控状态检查

## 核心人格、日记与长期记忆

- 核心人格在 `data/persona.md`，由你填写。
- 日记在 `data/diaries/to_owner/`，由 AI 自己写。
- 每次会话自动加载：
  - 近三天日记
  - `data/memory.md` 长期记忆
- AI 有权限读取所有历史日记，也可以主动写今天的日记。
- 长期记忆由新日记整理而成，只含：
  - 以前发生的事件
  - 学到的东西（经验 + 风格）

## 常见问题

<details>
<summary><b>单文件 exe 打不开 / 被杀软拦截</b></summary>
<br>
改用 ZIP 版，完整解压后运行 <code>WhaleTalk.exe</code>。单文件版需要系统临时目录可写；受限电脑也可能拦截，这时 ZIP 更稳。
</details>

<details>
<summary><b>评论或回复失败，提示 412 / 12014</b></summary>
<br>
412 是 B 站风控，程序会自动暂停 30 分钟；12014 是当天评论额度用完，程序会暂停到次日 00:05。不要反复重启或连续点“现在运行一轮”，等冷却结束即可。
</details>

<details>
<summary><b>她为什么没有行动？</b></summary>
<br>
她可以选择什么都不做。先看运行日志里模型的 <code>finish</code> 原因；也可以检查人设、当天日记、AI 模型和 B 站登录状态。
</details>

## 开发与构建

源码运行、打包和依赖说明见 **[DEVELOPMENT.md](DEVELOPMENT.md)**。

## 数据与隐私

API 密钥、B 站凭证、配置、历史数据库、日记和模型只保存在本机 `data/` 目录，并由 Git 忽略。评论图片和私信图片会按需下载到本机；画面帧和文本会按你配置的 AI 服务隐私政策处理。

## 许可证

MIT，详见 [LICENSE](LICENSE)。
