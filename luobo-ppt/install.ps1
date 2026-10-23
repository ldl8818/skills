# luobo-ppt one-click installer for Windows (PowerShell 5+)
#
#   .\install.ps1                         auto-detect installed agents, install, check and install deps
#   .\install.ps1 -Agent codex            claude-code | codex | gemini | cursor | copilot | agents | all
#   .\install.ps1 -Project D:\myrepo      install into a project instead of the user folder
#   .\install.ps1 -Dest D:\skills         install into any skills folder
#   .\install.ps1 -SkipDeps               copy files only
#   .\install.ps1 -Uninstall              remove from the selected agents
# Double-click install.bat if script execution is blocked.
param(
  [string]$Agent = "auto",
  [string]$Dest = "",
  [string]$Project = "",
  [switch]$SkipDeps,
  [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Name = "luobo-ppt"
$Src = Split-Path -Parent $MyInvocation.MyCommand.Path
$Base = if ($Project) { (Resolve-Path $Project).Path } else { $env:USERPROFILE }

function J([string]$root, [string]$a, [string]$b) { return Join-Path (Join-Path $root $a) $b }
function Get-AgentDir($a) {
  switch ($a) {
    "claude-code" { return J $Base ".claude" "skills" }
    "codex"       { return J $Base ".agents" "skills" }
    "agents"      { return J $Base ".agents" "skills" }
    "gemini"      { return J $Base ".gemini" "skills" }
    "cursor"      { return J $Base ".cursor" "skills" }
    "copilot"     { if ($Project) { return J $Project ".github" "skills" } else { return J $env:USERPROFILE ".copilot" "skills" } }
    default       { return $null }
  }
}

$targets = @()
if ($Dest) { $targets += $Dest }
elseif ($Agent -eq "all") { foreach ($a in "claude-code","agents","gemini","cursor","copilot") { $targets += Get-AgentDir $a } }
elseif ($Agent -eq "auto") {
  $found = @()
  $h = $env:USERPROFILE
  if (Test-Path (Join-Path $h ".claude")) { $found += "claude-code" }
  if ((Test-Path (Join-Path $h ".codex")) -or (Test-Path (Join-Path $h ".agents"))) { $found += "codex" }
  if (Test-Path (Join-Path $h ".gemini")) { $found += "gemini" }
  # Cursor also reads the Claude / Codex skill folders, avoid listing the skill twice
  if ((Test-Path (Join-Path $h ".cursor")) -and -not ($found -contains "claude-code") -and -not ($found -contains "codex")) { $found += "cursor" }
  if (Test-Path (Join-Path $h ".copilot")) { $found += "copilot" }
  if ($found.Count -eq 0) { $found = @("agents") }
  Write-Host ("检测到的 Agent：" + ($found -join ", "))
  foreach ($a in $found) { $targets += Get-AgentDir $a }
}
else {
  $d = Get-AgentDir $Agent
  if (-not $d) { Write-Host "未知 agent：$Agent"; exit 2 }
  $targets += $d
}

if ($Uninstall) {
  foreach ($t in $targets) {
    $dst = Join-Path $t $Name
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst; Write-Host "已移除 $dst" }
  }
  Write-Host "缓存文件 $(Join-Path $env:USERPROFILE '.config') 下的 luobo-ppt 文件夹保留（里面可能有你的生图配置），不需要可以手动删除。"
  exit 0
}

$first = $null
foreach ($t in $targets) {
  $dst = Join-Path $t $Name
  New-Item -ItemType Directory -Force -Path $t | Out-Null
  $same = (Test-Path $dst) -and ((Resolve-Path $dst).Path -eq (Resolve-Path $Src).Path)
  if ($same) { Write-Host "已在目标位置：$dst" }
  else {
    $keep = $null
    $cfgFile = Join-Path $dst "config.json"
    if (Test-Path $cfgFile) { $keep = [System.IO.Path]::GetTempFileName(); Copy-Item $cfgFile $keep -Force }
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    # repo-only files (git history, README screenshots, build tools) stay out of the installed skill
    $skip = @(".git", ".github", "docs", "tools", "dist", "README.md", ".gitignore")
    Get-ChildItem -Path $Src -Force | Where-Object { $skip -notcontains $_.Name } | ForEach-Object { Copy-Item -Recurse -Force $_.FullName $dst }
    Get-ChildItem -Path $dst -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    if ($keep) { Move-Item $keep $cfgFile -Force }
    Write-Host "已安装到：$dst"
  }
  foreach ($oldName in @("ppt-studio", "ppt-beautify")) {   # earlier names of this skill
    $old = Join-Path $t $oldName
    if (Test-Path $old) {
      $oc = Join-Path $old "config.json"; $nc = Join-Path $dst "config.json"
      if ((Test-Path $oc) -and -not (Test-Path $nc)) { Copy-Item $oc $nc }
      Remove-Item -Recurse -Force $old
      Write-Host "已移除旧版 $oldName（已改名为 luobo-ppt，生图配置已带过来）"
    }
  }
  if (-not $first) { $first = $dst }
}

$setup = Join-Path (Join-Path $first "scripts") "setup_check.py"
if ($SkipDeps) { Write-Host "已跳过依赖检查。之后可运行：python `"$setup`" --install"; exit 0 }

function Find-Python {
  foreach ($c in @(@("py", "-3"), @("python"), @("python3"))) {
    $exe = $c[0]
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
      $args2 = @(); if ($c.Count -gt 1) { $args2 = $c[1..($c.Count-1)] }
      try {
        $v = & $exe @args2 -c "import sys; print(sys.version_info >= (3,8))" 2>$null
        if ($v -match "True") { return ,$c }
      } catch {}
    }
  }
  $local = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
  if ($local) { return ,@($local.FullName) }
  return $null
}

$py = Find-Python
if (-not $py) {
  Write-Host "没有找到 Python 3.8+。"
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "正在用 winget 安装 Python 3.12 ……"
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent
    $py = Find-Python
  }
  if (-not $py) {
    Write-Host "请从 https://www.python.org/downloads/ 安装 Python（勾选 Add python.exe to PATH），然后重新运行本脚本。"
    exit 1
  }
}

Write-Host ""
Write-Host "检查并安装依赖（首次可能需要几分钟）……"
$pyExe = $py[0]; $pyArgs = @(); if ($py.Count -gt 1) { $pyArgs = $py[1..($py.Count-1)] }
& $pyExe @pyArgs $setup --install --selftest
exit $LASTEXITCODE
