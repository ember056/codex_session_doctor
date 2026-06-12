# Codex Session Doctor / Codex 会话找回助手

[中文文档](README.zh-CN.md)

Codex Session Doctor is a local recovery and repair tool for Codex Desktop conversations that still exist on disk but disappear from the sidebar.

Codex 会话找回助手用于恢复“本地对话文件还在，但 Codex Desktop 侧边栏看不到”的历史会话。

## What It Fixes / 可以修什么

Codex Desktop history is stored across several local files:

Codex Desktop 的本地历史通常分散在这些文件里：

- `%USERPROFILE%\.codex\state_5.sqlite`
- `%USERPROFILE%\.codex\session_index.jsonl`
- `%USERPROFILE%\.codex\sessions\**\rollout-*.jsonl`

When these files get out of sync, conversations may be hidden even though the JSONL files still exist.

当这些文件里的元数据不同步时，即使 `.jsonl` 会话文件还在，侧边栏也可能不显示对应对话。

## Features / 功能

- Detect missing `session_index.jsonl` entries  
  检查缺失的侧边栏索引记录
- Detect empty `threads.preview` values that may hide conversations  
  检查可能导致侧边栏隐藏会话的空 `preview`
- Detect `cwd` mismatches between SQLite and rollout JSONL metadata  
  检查 SQLite 与会话文件首行元数据里的项目目录不一致问题
- Detect missing rollout files  
  检查数据库指向但本地不存在的会话文件
- Merge and rebuild `session_index.jsonl`  
  合并并重建 `session_index.jsonl`
- Fill missing previews from the first user message or title  
  用首条用户消息或标题补齐预览
- Normalize Windows paths such as `C:\...` and `\\?\C:\...`  
  兼容 Windows 普通路径和长路径格式
- Backup SQLite, session index, and rollout metadata before writing  
  写入前自动备份数据库、索引和会话元数据
- Skip guardian/subagent review threads by default  
  默认跳过 guardian/subagent 审查线程

## Requirements / 环境要求

- Windows, macOS, or Linux
- Python 3.10+
- A local Codex Desktop data directory, usually `%USERPROFILE%\.codex`

Windows users can use the Chinese PowerShell GUI directly.

Windows 用户可以直接使用中文 PowerShell 图形界面。

## Quick Start / 快速开始

Clone the repository:

克隆仓库：

```powershell
git clone https://github.com/ember056/codex_session_doctor.git
cd codex_session_doctor
```

Launch the recommended Windows GUI:

启动推荐的 Windows 中文图形界面：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch_ui.ps1
```

Create a desktop shortcut:

创建桌面入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch_ui.ps1 -InstallShortcutOnly
```

Use the command line:

使用命令行：

```powershell
py -3 -m codex_session_doctor scan
py -3 -m codex_session_doctor diagnose
py -3 -m codex_session_doctor repair --dry-run --fix-preview --fix-index
py -3 -m codex_session_doctor repair --fix-preview --fix-index --yes
```

Open the cross-platform Tkinter GUI:

打开跨平台 Tkinter 图形界面：

```powershell
py -3 -m codex_session_doctor gui
```

## Safety / 安全机制

Real repair requires `--yes` on the command line, and the GUI asks for confirmation before writing.

命令行正式修复需要显式添加 `--yes`，图形界面正式修复前也会弹窗确认。

Before any real write, the tool creates a backup under:

真正写入前，工具会在这里创建备份：

```text
%USERPROFILE%\.codex\session_doctor_backups
```

The backup includes:

备份内容包括：

- a copy of `state_5.sqlite`
- a copy of `session_index.jsonl`
- the first `session_meta` line from each rollout JSONL file

## Commands / 命令

```text
scan       Print a compact summary of local Codex history data
           输出本地 Codex 历史概况

diagnose   Print detected problems grouped by project cwd
           按项目目录分组输出诊断报告

repair     Apply selected repairs, or preview them with --dry-run
           执行修复，或使用 --dry-run 预览修复

gui        Open the Tkinter graphical interface
           打开 Tkinter 图形界面
```

Example grouped diagnosis report:

按项目分组的诊断报告示例：

```text
项目目录: \\?\C:\Users\bobo\Desktop\Onecall
  问题数: 3
  概览: 缺少侧边栏预览=3
  会话: 启动项目
    id: 019e495f-697f-7720-a4ef-63f2373531f1
    - [缺少侧边栏预览] preview 为空，Codex 侧边栏可能不会显示这个会话。 -> 补齐预览
```

## Windows GUI / Windows 图形界面

The primary Windows GUI is `launch_ui.ps1`. It follows a practical recovery-tool layout:

主要 Windows 图形界面是 `launch_ui.ps1`，界面结构包括：

- status summary at the top  
  顶部状态概览
- one-click scan and diagnosis  
  一键检查和诊断
- project-grouped issue list  
  按项目分组的问题列表
- detailed report area  
  详细报告区域
- operation log  
  操作日志
- dry-run before real repair  
  正式修复前可预览
- backup directory and desktop shortcut buttons  
  备份目录和桌面入口按钮

## Notes / 说明

This tool modifies local Codex Desktop metadata only. It does not upload conversations, call OpenAI APIs, or modify project source code.

本工具只修改本机 Codex Desktop 元数据，不上传对话、不调用 OpenAI API，也不会修改你的项目源码。

Close Codex Desktop before applying repairs when possible. Windows may lock active rollout files while Codex is writing to them.

建议正式修复前先退出 Codex Desktop。Windows 可能会锁定正在写入的会话文件。

