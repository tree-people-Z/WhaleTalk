# 鲸语 v2.5.8

这一版把「日记整理」变成后台自动做的日常维护，不用再手动跑脚本。

## 日记自动整理

- **启动后 90 秒检查一次**，之后每 6 小时检查，**每天最多真正跑一次**。
- 只处理**3 天以前、且仍超过 1200 字**的日记：整理过的文件变短，下次自然跳过，
  不会反复压缩。
- 每篇压到 250–450 字：保留拍片/发布、和主人的互动、学到的东西、情绪转折；
  删掉逐轮视频清单、评分、播放数、工具调用次数、审计行。
- 整理前自动打包备份到 `data/diaries/backup/`，只保留最近 3 份，可随时解压还原。
- 正在跑 Agent 或回复检查时会跳过，等下一轮空闲再做，不抢模型调用。
- 可以在 `config.json` 里关掉或改阈值：
  - `diaries.auto_compact`（默认 true）
  - `diaries.compact_after_days`（默认 3）
  - `diaries.compact_min_chars`（默认 1200）
  - `diaries.keep_backups`（默认 3）

## 成长档案清理独立成日常维护

- 以前衰减/清理只发生在“在线学习真的跑了”之后，学习被 12 小时间隔跳过时就不清理。
  现在单独成一步 `housekeeping`，**最多每 24 小时跑一次**（避免每 6 小时就衰减一轮，
  把 14 天没用过的条目三天就清光）。
- 衰减、超量裁剪、观察文本清理一起做，结果写进日志。

## 手动入口

```bash
python tools/compact_diaries.py --dry-run          # 只预演，不改文件
python tools/compact_diaries.py                    # 按配置整理
python tools/compact_diaries.py --only 2026-11-09  # 只整理某一天
python tools/compact_diaries.py --housekeeping     # 顺便清一次成长档案
```

行为和数据格式没有变化，直接覆盖安装即可。
