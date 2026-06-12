from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import messagebox, ttk

from .backup import create_backup
from .diagnostics import describe_issue_code, diagnose_threads, format_project_report, group_diagnoses_by_project, summarize_threads
from .paths import resolve_paths
from .repair import rebuild_session_index, repair_previews
from .scanner import load_session_index_ids, load_session_meta, load_threads


class SessionDoctorApp:
    def __init__(self, root: tk.Tk, codex_home: str | None = None) -> None:
        self.root = root
        self.root.title("Codex 会话找回助手")
        self.root.geometry("1180x780")
        self.root.minsize(980, 640)
        self.paths = resolve_paths(codex_home)
        self.groups: list[dict[str, object]] = []
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.codex_home_var = tk.StringVar(value=str(self.paths.codex_home))
        self.status_var = tk.StringVar(value="准备就绪")
        self.summary_var = tk.StringVar(value="正在读取本地 Codex 历史...")
        self.fix_preview_var = tk.BooleanVar(value=True)
        self.fix_index_var = tk.BooleanVar(value=True)

        self._build_ui()
        self._poll_worker_queue()
        self.run_diagnose()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        top = ttk.Frame(self.root, padding=(16, 14, 16, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        title = ttk.Label(top, text="Codex 会话找回助手", font=("Microsoft YaHei UI", 18, "bold"))
        title.grid(row=0, column=0, columnspan=6, sticky="w")

        intro = ttk.Label(
            top,
            text="用于检查“本地对话还在，但 Codex 侧边栏看不到”的问题，并在备份后修复预览、索引等常见元数据。",
            foreground="#4d5969",
        )
        intro.grid(row=1, column=0, columnspan=6, sticky="w", pady=(4, 12))

        ttk.Label(top, text="Codex 数据目录").grid(row=2, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(top, textvariable=self.codex_home_var).grid(row=2, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(top, text="重新检查", command=self.run_scan).grid(row=2, column=2, padx=(0, 6))
        ttk.Button(top, text="生成诊断报告", command=self.run_diagnose).grid(row=2, column=3, padx=(0, 6))
        ttk.Button(top, text="预览修复", command=self.run_dry_run).grid(row=2, column=4, padx=(0, 6))
        ttk.Button(top, text="开始修复", command=self.run_repair).grid(row=2, column=5)

        status = ttk.Frame(self.root, padding=(16, 0, 16, 10))
        status.grid(row=1, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        self.summary_label = ttk.Label(status, textvariable=self.summary_var, font=("Microsoft YaHei UI", 10, "bold"), foreground="#1c54a0")
        self.summary_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=1, sticky="e", padx=(10, 0))
        self.progress.grid_remove()

        middle = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        middle.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))

        left = ttk.Frame(middle)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="按项目分组的问题", font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.project_tree = ttk.Treeview(left, columns=("issues", "summary"), show="tree headings", selectmode="browse")
        self.project_tree.heading("#0", text="项目目录")
        self.project_tree.heading("issues", text="问题")
        self.project_tree.heading("summary", text="概览")
        self.project_tree.column("#0", width=420, stretch=True)
        self.project_tree.column("issues", width=64, anchor="center", stretch=False)
        self.project_tree.column("summary", width=240, stretch=True)
        self.project_tree.grid(row=1, column=0, sticky="nsew")
        self.project_tree.bind("<<TreeviewSelect>>", self._on_project_selected)
        left_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.project_tree.yview)
        self.project_tree.configure(yscrollcommand=left_scroll.set)
        left_scroll.grid(row=1, column=1, sticky="ns")

        right = ttk.Frame(middle)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        ttk.Label(right, text="诊断报告 / 操作日志", font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.report = tk.Text(right, wrap="word", height=20, font=("Microsoft YaHei UI", 10), undo=False)
        self.report.grid(row=1, column=0, sticky="nsew")
        report_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.report.yview)
        self.report.configure(yscrollcommand=report_scroll.set)
        report_scroll.grid(row=1, column=1, sticky="ns")

        middle.add(left, weight=2)
        middle.add(right, weight=3)

        bottom = ttk.Frame(self.root, padding=(16, 0, 16, 12))
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.columnconfigure(4, weight=1)
        ttk.Checkbutton(bottom, text="补齐侧边栏预览", variable=self.fix_preview_var).grid(row=0, column=0, sticky="w", padx=(0, 16))
        ttk.Checkbutton(bottom, text="合并侧边栏索引", variable=self.fix_index_var).grid(row=0, column=1, sticky="w", padx=(0, 16))
        ttk.Button(bottom, text="打开备份目录", command=self.open_backup_dir).grid(row=0, column=2, padx=(0, 16))
        ttk.Label(bottom, text="真正修复前会自动备份。建议先退出 Codex Desktop。", foreground="#6b7280").grid(row=0, column=3, sticky="w")
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=4, sticky="e")

    def refresh_paths(self) -> None:
        self.paths = resolve_paths(self.codex_home_var.get().strip() or None)

    def run_scan(self) -> None:
        self._run_background("scan", self._scan_worker)

    def run_diagnose(self) -> None:
        self._run_background("diagnose", self._diagnose_worker)

    def run_dry_run(self) -> None:
        self._run_background("dry-run", lambda: self._repair_worker(dry_run=True))

    def run_repair(self) -> None:
        if not self.fix_preview_var.get() and not self.fix_index_var.get():
            messagebox.showinfo("没有选择修复项", "请至少选择一个修复项。")
            return
        confirm = messagebox.askyesno(
            "确认开始修复？",
            "工具会先备份，再修改本地 Codex 元数据。\n\n建议先完全退出 Codex Desktop，避免文件被占用。\n\n是否继续？",
        )
        if confirm:
            self._run_background("repair", lambda: self._repair_worker(dry_run=False))

    def open_backup_dir(self) -> None:
        self.refresh_paths()
        self.paths.backup_dir.mkdir(parents=True, exist_ok=True)
        path = str(self.paths.backup_dir)
        try:
            if hasattr(os, "startfile"):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                webbrowser.open(self.paths.backup_dir.as_uri())
            self._append_log(f"已打开备份目录: {path}")
        except OSError as exc:
            messagebox.showerror("打开备份目录失败", str(exc))

    def _scan_worker(self) -> str:
        self.refresh_paths()
        threads = load_threads(self.paths)
        summary = summarize_threads(threads)
        self._set_summary_from_scan(summary)
        lines = [
            "本地历史概况",
            "",
            f"Codex 数据目录: {self.paths.codex_home}",
            f"数据库: {self.paths.db_path}",
            f"侧边栏索引: {self.paths.session_index_path}",
            "",
            f"历史线程: {summary['total_threads']}",
            f"未归档线程: {summary['active_threads']}",
            f"已归档线程: {summary['archived_threads']}",
            f"缺少侧边栏预览: {summary['empty_preview_threads']}",
            f"会话文件不存在: {summary['missing_rollout_files']}",
            "",
            "项目目录 Top 列表:",
        ]
        for cwd, count in summary["cwd_counts"]:
            lines.append(f"  {count:>4}  {cwd}")
        self._append_log("状态已刷新。")
        return "\n".join(lines)

    def _diagnose_worker(self) -> str:
        self.refresh_paths()
        threads = load_threads(self.paths)
        diagnoses = diagnose_threads(threads, load_session_meta(self.paths), load_session_index_ids(self.paths))
        self.groups = group_diagnoses_by_project(diagnoses, threads)
        self._set_summary_from_diagnoses(len(diagnoses), len(self.groups))
        self._append_log(f"诊断完成：发现 {len(diagnoses)} 个问题，涉及 {len(self.groups)} 个项目。")
        return format_project_report(self.groups)

    def _repair_worker(self, dry_run: bool) -> str:
        self.refresh_paths()
        changes: list[str] = []
        backup_path = None
        if not dry_run:
            backup_path = create_backup(self.paths)
        if self.fix_preview_var.get():
            changes.extend(repair_previews(self.paths, dry_run=dry_run))
        if self.fix_index_var.get():
            changes.extend(rebuild_session_index(self.paths, dry_run=dry_run))
        if not dry_run:
            self._diagnose_worker()
        if dry_run:
            self._append_log(f"预览修复完成：预计 {len(changes)} 项变更。")
        else:
            self._append_log(f"修复完成：执行 {len(changes)} 项变更。")
            if backup_path:
                self._append_log(f"备份目录: {backup_path}")
        lines = [f"模式: {'预览修复，不写入' if dry_run else '正式修复'}"]
        if backup_path:
            lines.append(f"备份目录: {backup_path}")
        lines.append("")
        lines.append("变更列表:")
        if changes:
            lines.extend(f"  - {change}" for change in changes)
        else:
            lines.append("  无")
        return "\n".join(lines)

    def _run_background(self, label: str, work) -> None:
        label_text = {
            "scan": "正在重新检查...",
            "diagnose": "正在生成诊断报告...",
            "dry-run": "正在预览修复...",
            "repair": "正在修复...",
        }.get(label, f"正在执行 {label}...")
        self.status_var.set(label_text)
        self.progress.grid()
        self.progress.start(12)
        self._set_buttons_state(tk.DISABLED)

        def target() -> None:
            try:
                result = work()
                self.worker_queue.put(("ok", result))
            except Exception as exc:  # noqa: BLE001 - GUI should surface unexpected failures.
                self.worker_queue.put(("error", exc))

        threading.Thread(target=target, daemon=True).start()

    def _poll_worker_queue(self) -> None:
        try:
            kind, payload = self.worker_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_worker_queue)
            return

        self._set_buttons_state(tk.NORMAL)
        self.progress.stop()
        self.progress.grid_remove()
        if kind == "error":
            self.status_var.set("执行失败")
            self._append_log(f"执行失败: {payload}")
            messagebox.showerror("Codex 会话找回助手", str(payload))
        else:
            self.status_var.set("准备就绪")
            self._set_report(str(payload))
            self._refresh_project_tree()
        self.root.after(100, self._poll_worker_queue)

    def _set_buttons_state(self, state: str) -> None:
        for child in self.root.winfo_children():
            self._set_child_buttons_state(child, state)

    def _set_child_buttons_state(self, widget: tk.Widget, state: str) -> None:
        if isinstance(widget, ttk.Button):
            widget.configure(state=state)
        for child in widget.winfo_children():
            self._set_child_buttons_state(child, state)

    def _set_report(self, content: str) -> None:
        self.report.configure(state=tk.NORMAL)
        self.report.delete("1.0", tk.END)
        self.report.insert(tk.END, content)
        self.report.configure(state=tk.DISABLED)

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        current = self.report.get("1.0", tk.END).rstrip()
        prefix = "\n\n" if current else ""
        self.report.configure(state=tk.NORMAL)
        self.report.insert(tk.END, f"{prefix}[{timestamp}] {message}")
        self.report.see(tk.END)
        self.report.configure(state=tk.DISABLED)

    def _set_summary_from_scan(self, summary: dict[str, object]) -> None:
        self.summary_var.set(
            f"历史线程 {summary['total_threads']} 条，未归档 {summary['active_threads']} 条，"
            f"缺少预览 {summary['empty_preview_threads']} 条。"
        )

    def _set_summary_from_diagnoses(self, issue_count: int, project_count: int) -> None:
        if issue_count == 0:
            self.summary_var.set("一切正常：暂未发现常见的侧边栏显示问题。")
        else:
            self.summary_var.set(f"发现 {issue_count} 个可疑问题，涉及 {project_count} 个项目。可先点“预览修复”。")

    def _refresh_project_tree(self) -> None:
        self.project_tree.delete(*self.project_tree.get_children())
        for index, group in enumerate(self.groups):
            codes = group.get("codes", {})
            summary = "，".join(f"{describe_issue_code(code)}={count}" for code, count in sorted(codes.items()))
            self.project_tree.insert("", tk.END, iid=str(index), text=str(group["cwd"]), values=(group["issue_count"], summary))

    def _on_project_selected(self, _event) -> None:
        selected = self.project_tree.selection()
        if not selected:
            return
        group = self.groups[int(selected[0])]
        self._set_report(format_project_report([group]))


def run_gui(codex_home: str | None = None) -> None:
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except tk.TclError:
        pass
    try:
        root.option_add("*Font", ("Microsoft YaHei UI", 9))
    except tk.TclError:
        pass
    SessionDoctorApp(root, codex_home=codex_home)
    root.mainloop()
