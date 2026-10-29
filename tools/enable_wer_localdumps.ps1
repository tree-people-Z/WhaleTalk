# 以管理员身份启用 WhaleTalk.exe 的 WER 本地崩溃转储
# 用法：右键“使用 PowerShell 运行”，或在管理员 PowerShell 中执行本脚本。
$ErrorActionPreference = 'Stop'
$dumpDir = 'C:\Users\tree-\Desktop\WhaleTalk-Windows-x64\WhaleTalk\data\crash_dumps'
New-Item -ItemType Directory -Force -Path $dumpDir | Out-Null

$base = 'HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps'
$app = Join-Path $base 'WhaleTalk.exe'
New-Item -Path $base -Force | Out-Null
New-Item -Path $app -Force | Out-Null
Set-ItemProperty -Path $app -Name DumpFolder -Value $dumpDir -Type ExpandString
Set-ItemProperty -Path $app -Name DumpType -Value 2 -Type DWord
Set-ItemProperty -Path $app -Name DumpCount -Value 3 -Type DWord

$log = Join-Path $dumpDir 'enable_wer.log'
@(
  "enabled at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
  "DumpFolder=$dumpDir",
  "DumpType=2 (full)",
  "DumpCount=3"
) | Set-Content -Path $log -Encoding utf8
Write-Host "WER LocalDumps 已启用：$dumpDir"
