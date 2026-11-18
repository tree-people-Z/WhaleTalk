# 鲸语 v2.5.15

v2.5.14 的收尾修复（CI 上有 1 个测试失败，代码本身行为正常）。

## 修复

- `release_now()` 不再依赖空闲时间比较：之前的实现复用
  `release_if_idle(0)`，而判断是「严格大于」，CI 上时钟粒度导致
  elapsed 正好等于 0，刚用完的模型没有被释放。现在直接清空模型引用。
- 打包体积复原：构建环境里装了 `faster-whisper`/`ctranslate2`/`av`
  等本地识别依赖，PyInstaller 把它们打进了主体，便携包从 158MB 涨到 244MB。
  这些依赖本来就按需下载到 `data/transcription`，现在显式排除，
  体积回到 ~158MB。

内容与 v2.5.14 相同：语音模型在一轮任务结束后立即释放（成功 / 失败 / 取消 /
回复检查都覆盖），扫描间隔 30 秒，空闲下限 15 秒，默认 2 分钟；
新增 `analysis.local_transcription_device`（cpu 默认，可改 cuda）。
