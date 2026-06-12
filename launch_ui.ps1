param(
  [switch]$InstallShortcutOnly,
  [switch]$SmokeTest,
  [string]$CodexHome = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:UiScriptPath = $MyInvocation.MyCommand.Path
$script:ToolRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:ShortcutName = 'Codex 会话找回助手.lnk'
$script:IconLocation = 'C:\Windows\System32\imageres.dll,15'
$script:LatestScan = $null
$script:LatestDiagnose = $null

function Get-PythonLauncher {
  $pyCommand = Get-Command py -ErrorAction SilentlyContinue
  if ($pyCommand) {
    $oldPreference = $ErrorActionPreference
    try {
      $ErrorActionPreference = 'Continue'
      $versionOutput = & py -3 --version 2>&1
      if ($LASTEXITCODE -eq 0) {
        return @{ Command = 'py'; Prefix = @('-3') }
      }
    } finally {
      $ErrorActionPreference = $oldPreference
    }
  }

  $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCommand) {
    $oldPreference = $ErrorActionPreference
    try {
      $ErrorActionPreference = 'Continue'
      $versionOutput = & python --version 2>&1
      if ($LASTEXITCODE -eq 0) {
        return @{ Command = 'python'; Prefix = @() }
      }
    } finally {
      $ErrorActionPreference = $oldPreference
    }
  }

  throw '未找到可用的 Python。请安装 Python 3.10+，或确认 py/python 命令可用。'
}

function Invoke-Doctor {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Arguments
  )

  $python = Get-PythonLauncher
  $commandArgs = @()
  $commandArgs += $python.Prefix
  $commandArgs += @('-m', 'codex_session_doctor')
  if ($CodexHome) {
    $commandArgs += @('--codex-home', $CodexHome)
  }
  $commandArgs += '--json'
  $commandArgs += $Arguments

  $output = & $python.Command @commandArgs 2>&1
  $exitCode = $LASTEXITCODE
  $text = (($output | ForEach-Object { "$_" }) -join [Environment]::NewLine).Trim()
  if (-not $text) {
    throw '后端没有返回任何内容。'
  }

  try {
    $json = $text | ConvertFrom-Json
  } catch {
    throw "后端 JSON 解析失败。`r`n原始错误: $($_.Exception.Message)`r`n返回内容:`r`n$text"
  }

  # diagnose returns exit code 1 when issues are found. That is useful, not fatal.
  if ($exitCode -ne 0 -and -not ($Arguments.Count -gt 0 -and $Arguments[0] -eq 'diagnose')) {
    throw "后端执行失败。`r`n$text"
  }

  return $json
}

function New-DesktopShortcut {
  $desktopPath = [Environment]::GetFolderPath('Desktop')
  $shortcutPath = Join-Path $desktopPath $script:ShortcutName
  $targetPath = Join-Path $PSHOME 'powershell.exe'
  $arguments = "-NoProfile -ExecutionPolicy Bypass -Sta -WindowStyle Hidden -File `"$script:UiScriptPath`""
  if ($CodexHome) {
    $arguments += " -CodexHome `"$CodexHome`""
  }

  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = $targetPath
  $shortcut.Arguments = $arguments
  $shortcut.WorkingDirectory = $script:ToolRoot
  $shortcut.IconLocation = $script:IconLocation
  $shortcut.Description = 'Codex session doctor UI'
  $shortcut.Save()

  return $shortcutPath
}

if ($InstallShortcutOnly) {
  $createdShortcut = New-DesktopShortcut
  Write-Output "桌面入口已创建: $createdShortcut"
  exit 0
}

function Append-Log {
  param([string]$Message)

  $timestamp = Get-Date -Format 'HH:mm:ss'
  $logBox.AppendText("[$timestamp] $Message`r`n")
  $logBox.SelectionStart = $logBox.TextLength
  $logBox.ScrollToCaret()
}

function Set-Busy {
  param(
    [bool]$Busy,
    [string]$Message = ''
  )

  foreach ($button in @($refreshButton, $diagnoseButton, $dryRunButton, $repairButton, $backupFolderButton, $shortcutButton)) {
    if ($button) {
      $button.Enabled = -not $Busy
    }
  }

  if ($Busy) {
    $statusLabel.Text = $Message
    $progressBar.Style = 'Marquee'
    $progressBar.Visible = $true
  } else {
    $progressBar.Style = 'Blocks'
    $progressBar.Visible = $false
    $statusLabel.Text = Get-FriendlyStatus
  }
}

function Get-FriendlyStatus {
  if (-not $script:LatestDiagnose) {
    return '准备就绪：点击“重新检查”或“生成诊断报告”。'
  }
  $count = [int]$script:LatestDiagnose.count
  if ($count -le 0) {
    return '一切正常：暂未发现常见的侧边栏显示问题。'
  }
  $projectCount = 0
  if ($script:LatestDiagnose.projects) {
    $projectCount = @($script:LatestDiagnose.projects).Count
  }
  return "发现 $count 个可疑问题，涉及 $projectCount 个项目。建议先预览修复。"
}

function Format-CodeSummary {
  param($Codes)

  if (-not $Codes) {
    return '无'
  }
  $items = @()
  foreach ($property in $Codes.PSObject.Properties) {
    $name = Convert-IssueName $property.Name
    $items += "$name=$($property.Value)"
  }
  if ($items.Count -eq 0) {
    return '无'
  }
  return $items -join '，'
}

function Convert-IssueName {
  param([string]$Code)

  switch ($Code) {
    'empty-preview' { return '缺少预览' }
    'missing-index-entry' { return '缺少索引' }
    'cwd-mismatch' { return '目录不一致' }
    'missing-rollout-file' { return '会话文件不存在' }
    'missing-rollout-path' { return '缺少会话路径' }
    'missing-session-meta' { return '缺少元数据' }
    default { return $Code }
  }
}

function Refresh-State {
  $scan = Invoke-Doctor @('scan')
  $script:LatestScan = $scan
  Apply-Scan $scan
  Append-Log "状态已刷新：历史线程 $($scan.total_threads) 条，未归档 $($scan.active_threads) 条，缺少预览 $($scan.empty_preview_threads) 条。"
}

function Refresh-Diagnosis {
  $diagnose = Invoke-Doctor @('diagnose')
  $script:LatestDiagnose = $diagnose
  Apply-Diagnosis $diagnose
  Append-Log "诊断完成：发现 $($diagnose.count) 个问题。"
}

function Apply-Scan {
  param($Scan)

  $codexHome = if ($CodexHome) { $CodexHome } else { $Scan.codex_home }
  $pathLabel.Text = "数据位置: $codexHome"
  $summaryLabel.Text = "当前 Provider: $($Scan.current_provider)    当前模型: $($Scan.current_model)    历史线程: $($Scan.total_threads)    侧边栏索引: $($Scan.indexed_threads)"
  $repairLabel.Text = "待关注: 缺少预览 $($Scan.empty_preview_threads) 条    会话文件不存在 $($Scan.missing_rollout_files) 条"
  $statusLabel.Text = Get-FriendlyStatus

  $projectsView.Items.Clear()
  foreach ($row in $Scan.cwd_counts) {
    $item = New-Object System.Windows.Forms.ListViewItem([string]$row[0])
    [void]$item.SubItems.Add([string]$row[1])
    [void]$item.SubItems.Add('扫描概况')
    [void]$projectsView.Items.Add($item)
  }
}

function Apply-Diagnosis {
  param($Diagnosis)

  $projectsView.Items.Clear()
  foreach ($project in $Diagnosis.projects) {
    $item = New-Object System.Windows.Forms.ListViewItem([string]$project.cwd)
    [void]$item.SubItems.Add([string]$project.issue_count)
    [void]$item.SubItems.Add((Format-CodeSummary $project.codes))
    [void]$projectsView.Items.Add($item)
  }

  if ([int]$Diagnosis.count -le 0) {
    $reportBox.Text = '未发现需要修复的问题。'
  } else {
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($project in $Diagnosis.projects) {
      [void]$lines.Add("项目目录: $($project.cwd)")
      [void]$lines.Add("  问题数: $($project.issue_count)")
      [void]$lines.Add("  概览: $(Format-CodeSummary $project.codes)")
      foreach ($thread in $project.threads) {
        [void]$lines.Add("  会话: $($thread.title)")
        [void]$lines.Add("    id: $($thread.id)")
        foreach ($issue in $thread.issues) {
          [void]$lines.Add("    - [$(Convert-IssueName $issue.code)] $($issue.message) -> $($issue.repair)")
        }
      }
      [void]$lines.Add('')
    }
    $reportBox.Text = $lines -join [Environment]::NewLine
  }
  $statusLabel.Text = Get-FriendlyStatus
}

function Apply-RepairResult {
  param(
    $Result,
    [bool]$DryRun
  )

  $lines = New-Object System.Collections.Generic.List[string]
  if ($DryRun) {
    [void]$lines.Add('模式: 预览修复，不写入')
  } else {
    [void]$lines.Add('模式: 正式修复')
    if ($Result.backup_path) {
      [void]$lines.Add("备份目录: $($Result.backup_path)")
    }
  }
  [void]$lines.Add('')
  [void]$lines.Add('变更列表:')
  if ($Result.changes -and $Result.changes.Count -gt 0) {
    foreach ($change in $Result.changes) {
      [void]$lines.Add("  - $change")
    }
  } else {
    [void]$lines.Add('  无')
  }
  $reportBox.Text = $lines -join [Environment]::NewLine
}

function Get-RepairArgs {
  param([bool]$DryRun)

  $args = @('repair')
  if ($DryRun) {
    $args += '--dry-run'
  } else {
    $args += '--yes'
  }
  if ($previewCheck.Checked) {
    $args += '--fix-preview'
  }
  if ($indexCheck.Checked) {
    $args += '--fix-index'
  }
  if ($syncCurrentCheck.Checked) {
    $args += '--sync-current'
  }
  return $args
}

function Confirm-Action {
  param(
    [string]$Message,
    [string]$Title = '确认操作'
  )

  $choice = [System.Windows.Forms.MessageBox]::Show(
    $Message,
    $Title,
    [System.Windows.Forms.MessageBoxButtons]::OKCancel,
    [System.Windows.Forms.MessageBoxIcon]::Question
  )
  return $choice -eq [System.Windows.Forms.DialogResult]::OK
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Codex 会话找回助手'
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(1080, 760)
$form.MinimumSize = New-Object System.Drawing.Size(940, 650)
$form.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)

$headerLabel = New-Object System.Windows.Forms.Label
$headerLabel.Text = 'Codex 会话找回助手'
$headerLabel.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 18, [System.Drawing.FontStyle]::Bold)
$headerLabel.AutoSize = $true
$headerLabel.Location = New-Object System.Drawing.Point(24, 18)
$form.Controls.Add($headerLabel)

$introLabel = New-Object System.Windows.Forms.Label
$introLabel.Text = '用于检查“本地对话还在，但 Codex 侧边栏看不到”的问题，并在备份后修复预览、索引等常见元数据。'
$introLabel.ForeColor = [System.Drawing.Color]::FromArgb(77, 89, 105)
$introLabel.AutoSize = $true
$introLabel.MaximumSize = New-Object System.Drawing.Size(980, 0)
$introLabel.Location = New-Object System.Drawing.Point(26, 54)
$form.Controls.Add($introLabel)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = '正在读取状态...'
$statusLabel.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10, [System.Drawing.FontStyle]::Bold)
$statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(28, 84, 160)
$statusLabel.AutoSize = $true
$statusLabel.MaximumSize = New-Object System.Drawing.Size(980, 0)
$statusLabel.Location = New-Object System.Drawing.Point(26, 88)
$form.Controls.Add($statusLabel)

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Size = New-Object System.Drawing.Size(210, 12)
$progressBar.Location = New-Object System.Drawing.Point(820, 92)
$progressBar.Visible = $false
$form.Controls.Add($progressBar)

$pathLabel = New-Object System.Windows.Forms.Label
$pathLabel.Text = '数据位置:'
$pathLabel.AutoSize = $true
$pathLabel.MaximumSize = New-Object System.Drawing.Size(980, 0)
$pathLabel.Location = New-Object System.Drawing.Point(28, 132)
$form.Controls.Add($pathLabel)

$summaryLabel = New-Object System.Windows.Forms.Label
$summaryLabel.Text = '历史线程:'
$summaryLabel.AutoSize = $true
$summaryLabel.Location = New-Object System.Drawing.Point(28, 158)
$form.Controls.Add($summaryLabel)

$repairLabel = New-Object System.Windows.Forms.Label
$repairLabel.Text = '待关注:'
$repairLabel.AutoSize = $true
$repairLabel.Location = New-Object System.Drawing.Point(28, 184)
$form.Controls.Add($repairLabel)

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Text = '重新检查'
$refreshButton.Size = New-Object System.Drawing.Size(110, 36)
$refreshButton.Location = New-Object System.Drawing.Point(28, 220)
$form.Controls.Add($refreshButton)

$diagnoseButton = New-Object System.Windows.Forms.Button
$diagnoseButton.Text = '生成诊断报告'
$diagnoseButton.Size = New-Object System.Drawing.Size(138, 36)
$diagnoseButton.Location = New-Object System.Drawing.Point(150, 220)
$form.Controls.Add($diagnoseButton)

$dryRunButton = New-Object System.Windows.Forms.Button
$dryRunButton.Text = '预览修复'
$dryRunButton.Size = New-Object System.Drawing.Size(110, 36)
$dryRunButton.Location = New-Object System.Drawing.Point(300, 220)
$form.Controls.Add($dryRunButton)

$repairButton = New-Object System.Windows.Forms.Button
$repairButton.Text = '开始修复'
$repairButton.Size = New-Object System.Drawing.Size(120, 36)
$repairButton.Location = New-Object System.Drawing.Point(422, 220)
$repairButton.BackColor = [System.Drawing.Color]::FromArgb(32, 91, 177)
$repairButton.ForeColor = [System.Drawing.Color]::White
$repairButton.FlatStyle = 'Flat'
$form.Controls.Add($repairButton)

$backupFolderButton = New-Object System.Windows.Forms.Button
$backupFolderButton.Text = '打开备份'
$backupFolderButton.Size = New-Object System.Drawing.Size(110, 36)
$backupFolderButton.Location = New-Object System.Drawing.Point(554, 220)
$form.Controls.Add($backupFolderButton)

$shortcutButton = New-Object System.Windows.Forms.Button
$shortcutButton.Text = '创建桌面入口'
$shortcutButton.Size = New-Object System.Drawing.Size(130, 36)
$shortcutButton.Location = New-Object System.Drawing.Point(676, 220)
$form.Controls.Add($shortcutButton)

$syncCurrentCheck = New-Object System.Windows.Forms.CheckBox
$syncCurrentCheck.Text = '同步当前 Provider/模型'
$syncCurrentCheck.Checked = $true
$syncCurrentCheck.AutoSize = $true
$syncCurrentCheck.Location = New-Object System.Drawing.Point(824, 198)
$form.Controls.Add($syncCurrentCheck)

$indexCheck = New-Object System.Windows.Forms.CheckBox
$indexCheck.Text = '合并侧边栏索引'
$indexCheck.Checked = $true
$indexCheck.AutoSize = $true
$indexCheck.Location = New-Object System.Drawing.Point(824, 246)
$form.Controls.Add($indexCheck)

$previewCheck = New-Object System.Windows.Forms.CheckBox
$previewCheck.Text = '补齐侧边栏预览'
$previewCheck.Checked = $true
$previewCheck.AutoSize = $true
$previewCheck.Location = New-Object System.Drawing.Point(824, 222)
$form.Controls.Add($previewCheck)

$projectsBox = New-Object System.Windows.Forms.GroupBox
$projectsBox.Text = '按项目分组的问题'
$projectsBox.Location = New-Object System.Drawing.Point(28, 276)
$projectsBox.Size = New-Object System.Drawing.Size(1000, 190)
$form.Controls.Add($projectsBox)

$projectsView = New-Object System.Windows.Forms.ListView
$projectsView.View = 'Details'
$projectsView.FullRowSelect = $true
$projectsView.GridLines = $true
$projectsView.Location = New-Object System.Drawing.Point(12, 24)
$projectsView.Size = New-Object System.Drawing.Size(976, 152)
[void]$projectsView.Columns.Add('项目目录', 650)
[void]$projectsView.Columns.Add('问题', 70)
[void]$projectsView.Columns.Add('概览', 240)
$projectsBox.Controls.Add($projectsView)

$reportBox = New-Object System.Windows.Forms.TextBox
$reportBox.Multiline = $true
$reportBox.ScrollBars = 'Vertical'
$reportBox.ReadOnly = $true
$reportBox.Font = New-Object System.Drawing.Font('Consolas', 9)
$reportBox.Location = New-Object System.Drawing.Point(28, 482)
$reportBox.Size = New-Object System.Drawing.Size(1000, 166)
$form.Controls.Add($reportBox)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Multiline = $true
$logBox.ScrollBars = 'Vertical'
$logBox.ReadOnly = $true
$logBox.Font = New-Object System.Drawing.Font('Consolas', 9)
$logBox.Location = New-Object System.Drawing.Point(28, 662)
$logBox.Size = New-Object System.Drawing.Size(1000, 42)
$form.Controls.Add($logBox)

$refreshButton.Add_Click({
  try {
    Set-Busy -Busy $true -Message '正在重新检查本地历史...'
    Refresh-State
  } catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '检查失败', 'OK', 'Error') | Out-Null
    Append-Log "检查失败: $($_.Exception.Message)"
  } finally {
    Set-Busy -Busy $false
  }
})

$diagnoseButton.Add_Click({
  try {
    Set-Busy -Busy $true -Message '正在生成诊断报告...'
    Refresh-Diagnosis
  } catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '诊断失败', 'OK', 'Error') | Out-Null
    Append-Log "诊断失败: $($_.Exception.Message)"
  } finally {
    Set-Busy -Busy $false
  }
})

$dryRunButton.Add_Click({
  try {
    Set-Busy -Busy $true -Message '正在预览修复...'
    $result = Invoke-Doctor (Get-RepairArgs -DryRun $true)
    Apply-RepairResult -Result $result -DryRun $true
    Append-Log "预览修复完成：预计 $($result.changes.Count) 项变更。"
  } catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '预览失败', 'OK', 'Error') | Out-Null
    Append-Log "预览失败: $($_.Exception.Message)"
  } finally {
    Set-Busy -Busy $false
  }
})

$repairButton.Add_Click({
  try {
    if (-not $syncCurrentCheck.Checked -and -not $previewCheck.Checked -and -not $indexCheck.Checked) {
      [System.Windows.Forms.MessageBox]::Show('请至少选择一个修复项。', '没有选择修复项', 'OK', 'Warning') | Out-Null
      return
    }
    $message = "工具会先备份，再修改本地 Codex 元数据。`r`n`r`n建议先完全退出 Codex Desktop，避免文件被占用。`r`n`r`n是否继续？"
    if (-not (Confirm-Action -Message $message -Title '确认开始修复？')) {
      Append-Log '用户取消了修复。'
      return
    }
    Set-Busy -Busy $true -Message '正在修复本地历史...'
    $result = Invoke-Doctor (Get-RepairArgs -DryRun $false)
    Apply-RepairResult -Result $result -DryRun $false
    Append-Log "修复完成：执行 $($result.changes.Count) 项变更。"
    if ($result.backup_path) {
      Append-Log "备份目录: $($result.backup_path)"
    }
    Refresh-Diagnosis
    [System.Windows.Forms.MessageBox]::Show('修复完成。如果侧边栏没有马上刷新，请重新打开 Codex Desktop。', '修复完成', 'OK', 'Information') | Out-Null
  } catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '修复失败', 'OK', 'Error') | Out-Null
    Append-Log "修复失败: $($_.Exception.Message)"
  } finally {
    Set-Busy -Busy $false
  }
})

$backupFolderButton.Add_Click({
  try {
    $scan = if ($script:LatestScan) { $script:LatestScan } else { Invoke-Doctor @('scan') }
    $folder = Join-Path ([string]$scan.codex_home) 'session_doctor_backups'
    if (-not (Test-Path -LiteralPath $folder)) {
      New-Item -ItemType Directory -Path $folder | Out-Null
    }
    Start-Process explorer.exe $folder
    Append-Log "已打开备份目录: $folder"
  } catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '打开备份目录失败', 'OK', 'Error') | Out-Null
    Append-Log "打开备份目录失败: $($_.Exception.Message)"
  }
})

$shortcutButton.Add_Click({
  try {
    $path = New-DesktopShortcut
    [System.Windows.Forms.MessageBox]::Show("桌面入口已创建：`r`n$path", '完成', 'OK', 'Information') | Out-Null
    Append-Log "桌面入口已创建: $path"
  } catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '创建入口失败', 'OK', 'Error') | Out-Null
    Append-Log "创建入口失败: $($_.Exception.Message)"
  }
})

if ($SmokeTest) {
  [void](Get-PythonLauncher)
  Write-Output 'Smoke test passed.'
  exit 0
}

try {
  Set-Busy -Busy $true -Message '正在读取本地 Codex 历史...'
  Refresh-State
  Refresh-Diagnosis
} catch {
  Append-Log "启动时读取失败: $($_.Exception.Message)"
  $statusLabel.Text = '读取失败，请查看下方日志。'
} finally {
  Set-Busy -Busy $false
}

[void]$form.ShowDialog()
