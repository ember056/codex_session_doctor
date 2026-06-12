from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .backup import create_backup
from .diagnostics import diagnose_threads, format_project_report, group_diagnoses_by_project, summarize_threads
from .paths import resolve_paths
from .repair import rebuild_session_index, repair_previews
from .scanner import load_session_index_ids, load_session_meta, load_threads


class SessionDoctorApp:
    def __init__(self, root: tk.Tk, codex_home: str | None = None) -> None:
        self.root = root
        self.root.title("Codex Session Doctor")
        self.root.geometry("1120x720")
        self.root.minsize(900, 560)
        self.paths = resolve_paths(codex_home)
        self.groups: list[dict[str, object]] = []
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.codex_home_var = tk.StringVar(value=str(self.paths.codex_home))
        self.status_var = tk.StringVar(value="Ready")
        self.fix_preview_var = tk.BooleanVar(value=True)
        self.fix_index_var = tk.BooleanVar(value=True)

        self._build_ui()
        self._poll_worker_queue()
        self.run_diagnose()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Codex Home").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(top, textvariable=self.codex_home_var).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(top, text="Scan", command=self.run_scan).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(top, text="Diagnose", command=self.run_diagnose).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(top, text="Dry Run", command=self.run_dry_run).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(top, text="Repair", command=self.run_repair).grid(row=0, column=5)

        middle = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        middle.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))

        left = ttk.Frame(middle)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="Projects").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.project_tree = ttk.Treeview(left, columns=("issues", "summary"), show="tree headings", selectmode="browse")
        self.project_tree.heading("#0", text="Project")
        self.project_tree.heading("issues", text="Issues")
        self.project_tree.heading("summary", text="Summary")
        self.project_tree.column("#0", width=360, stretch=True)
        self.project_tree.column("issues", width=70, anchor="center", stretch=False)
        self.project_tree.column("summary", width=220, stretch=True)
        self.project_tree.grid(row=1, column=0, sticky="nsew")
        self.project_tree.bind("<<TreeviewSelect>>", self._on_project_selected)
        left_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.project_tree.yview)
        self.project_tree.configure(yscrollcommand=left_scroll.set)
        left_scroll.grid(row=1, column=1, sticky="ns")

        right = ttk.Frame(middle)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        ttk.Label(right, text="Report").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.report = tk.Text(right, wrap="word", height=20, font=("Consolas", 10), undo=False)
        self.report.grid(row=1, column=0, sticky="nsew")
        report_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.report.yview)
        self.report.configure(yscrollcommand=report_scroll.set)
        report_scroll.grid(row=1, column=1, sticky="ns")

        middle.add(left, weight=2)
        middle.add(right, weight=3)

        bottom = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(2, weight=1)
        ttk.Checkbutton(bottom, text="Fix empty previews", variable=self.fix_preview_var).grid(row=0, column=0, sticky="w", padx=(0, 16))
        ttk.Checkbutton(bottom, text="Merge session index", variable=self.fix_index_var).grid(row=0, column=1, sticky="w", padx=(0, 16))
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=2, sticky="e")

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
            messagebox.showinfo("Nothing selected", "Select at least one repair option.")
            return
        confirm = messagebox.askyesno(
            "Repair Codex history",
            "This will modify local Codex metadata after creating a backup. Close Codex Desktop first when possible.\n\nContinue?",
        )
        if confirm:
            self._run_background("repair", lambda: self._repair_worker(dry_run=False))

    def _scan_worker(self) -> str:
        self.refresh_paths()
        threads = load_threads(self.paths)
        summary = summarize_threads(threads)
        lines = [
            f"Codex home: {self.paths.codex_home}",
            f"Database: {self.paths.db_path}",
            f"Session index: {self.paths.session_index_path}",
            "",
            f"Total threads: {summary['total_threads']}",
            f"Active threads: {summary['active_threads']}",
            f"Archived threads: {summary['archived_threads']}",
            f"Active threads with empty preview: {summary['empty_preview_threads']}",
            f"Missing rollout files: {summary['missing_rollout_files']}",
            "",
            "Top projects:",
        ]
        for cwd, count in summary["cwd_counts"]:
            lines.append(f"  {count:>4}  {cwd}")
        return "\n".join(lines)

    def _diagnose_worker(self) -> str:
        self.refresh_paths()
        threads = load_threads(self.paths)
        diagnoses = diagnose_threads(threads, load_session_meta(self.paths), load_session_index_ids(self.paths))
        self.groups = group_diagnoses_by_project(diagnoses, threads)
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
        lines = [f"Mode: {'dry run' if dry_run else 'repair'}"]
        if backup_path:
            lines.append(f"Backup: {backup_path}")
        lines.append("")
        lines.append("Changes:")
        if changes:
            lines.extend(f"  - {change}" for change in changes)
        else:
            lines.append("  none")
        return "\n".join(lines)

    def _run_background(self, label: str, work) -> None:
        self.status_var.set(f"Running {label}...")
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
        if kind == "error":
            self.status_var.set("Error")
            messagebox.showerror("Codex Session Doctor", str(payload))
        else:
            self.status_var.set("Ready")
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

    def _refresh_project_tree(self) -> None:
        self.project_tree.delete(*self.project_tree.get_children())
        for index, group in enumerate(self.groups):
            codes = group.get("codes", {})
            summary = ", ".join(f"{code}={count}" for code, count in sorted(codes.items()))
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
    SessionDoctorApp(root, codex_home=codex_home)
    root.mainloop()

