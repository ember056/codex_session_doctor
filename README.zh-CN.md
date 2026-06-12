# Codex 会话找回助手

[English README](README.md)

一个用于恢复 Codex Desktop 本地历史的工具：当 `.jsonl` 对话文件还在，但侧边栏看不到时，自动诊断并修复常见的本地元数据问题。

## 适用场景

- 切换 API、Provider、模型或登录方式后，历史会话看不到
- 本地 `.codex\sessions` 里还有会话文件，但侧边栏为空
- 某个项目目录下只显示一部分会话
- `state_5.sqlite`、`session_index.jsonl`、会话文件首行元数据不同步

## 功能

- 检查缺失的 `session_index.jsonl` 侧边栏索引
- 检查空 `threads.preview`，避免会话被侧边栏过滤
- 检查 SQLite 与 `.jsonl` 首行 `session_meta.cwd` 的项目目录不一致
- 检查数据库指向但本地不存在的会话文件
- 合并并重建 `session_index.jsonl`
- 用首条用户消息或标题补齐 `preview`
- 兼容 `C:\...` 和 `\\?\C:\...` 两种 Windows 路径
- 写入前自动备份 SQLite、索引和会话元数据
- 默认跳过 guardian/subagent 审查线程

## 快速开始

```powershell
git clone https://github.com/ember056/codex_session_doctor.git
cd codex_session_doctor
```

启动推荐的 Windows 中文图形界面：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch_ui.ps1
```

创建桌面入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch_ui.ps1 -InstallShortcutOnly
```

命令行诊断：

```powershell
py -3 -m codex_session_doctor scan
py -3 -m codex_session_doctor diagnose
```

预览修复，不写入：

```powershell
py -3 -m codex_session_doctor repair --dry-run --fix-preview --fix-index
```

正式修复：

```powershell
py -3 -m codex_session_doctor repair --fix-preview --fix-index --yes
```

## 安全机制

正式修复前会自动备份到：

```text
%USERPROFILE%\.codex\session_doctor_backups
```

备份包括：

- `state_5.sqlite`
- `session_index.jsonl`
- 每个会话文件第一行 `session_meta`

建议修复前先完全退出 Codex Desktop，避免 Windows 文件占用。

## 图形界面

`launch_ui.ps1` 是主要 Windows 图形界面，包含：

- 顶部状态概览
- 重新检查
- 生成诊断报告
- 预览修复
- 开始修复
- 按项目分组的问题列表
- 诊断报告
- 操作日志
- 打开备份目录
- 创建桌面入口

## 命令说明

```text
scan       输出本地 Codex 历史概况
diagnose   按项目目录分组输出诊断报告
repair     执行修复，或使用 --dry-run 预览修复
gui        打开 Tkinter 图形界面
```

## 说明

本工具只修改本机 Codex Desktop 元数据，不上传对话、不调用 OpenAI API，也不会修改项目源码。

