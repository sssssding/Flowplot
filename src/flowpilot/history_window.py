"""Optional Tk history browser; filesystem scans never block the main event loop."""
from __future__ import annotations

from queue import Empty, Queue
import threading

from flowpilot.check_model import CheckError
from flowpilot.report_history import STATUS_LABELS, history_directory, load_history_report, scan_history


class HistoryBrowser:
    def __init__(self, root, *, output_root, on_open, on_directory):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        from tkinter.scrolledtext import ScrolledText
        self.tk, self.dialogs, self.messages = tk, filedialog, messagebox
        self.on_open, self.on_directory = on_open, on_directory
        self.window = tk.Toplevel(root)
        self.window.title("FlowPlot · 检查历史")
        self.window.geometry("940x620")
        self.window.minsize(720, 460)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(2, weight=1)
        self.root_path = tk.StringVar(self.window, str(output_root))
        self.status = tk.StringVar(self.window, "历史列表不代表报告已通过核验。")
        self.scanning, self.closed = False, False
        self.records, self.scan_root = {}, None
        self._after_id, self._queue = None, Queue()
        bar = ttk.Frame(self.window, padding=12)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self.path_entry = ttk.Entry(bar, textvariable=self.root_path)
        self.path_entry.grid(row=0, column=0, sticky="ew")
        self.choose_button = ttk.Button(bar, text="选择结果目录…", command=self.choose_root)
        self.choose_button.grid(row=0, column=1, padx=8)
        self.refresh_button = ttk.Button(bar, text="刷新", command=self.refresh)
        self.refresh_button.grid(row=0, column=2)
        ttk.Label(self.window, textvariable=self.status, wraplength=880, padding=(12, 0)).grid(row=1, column=0, sticky="w")
        frame = ttk.Frame(self.window, padding=12)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("time", "model", "status"), show="headings", height=9)
        for key, label, width in (("time", "开始时间（UTC）", 240), ("model", "模型", 250), ("status", "运行记录状态", 290)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=90)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self.select_entry)
        self.details = ScrolledText(frame, wrap="word", height=7, font=("Microsoft YaHei UI", 10))
        self.details.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.set_details("选择记录后查看详情；打开报告时重新核验，不运行 COMSOL。")
        actions = ttk.Frame(self.window, padding=(12, 0, 12, 12))
        actions.grid(row=3, column=0, sticky="e")
        self.open_button = ttk.Button(actions, text="查看报告", command=self.open_selected, state="disabled")
        self.open_button.pack(side="left", padx=8)
        self.folder_button = ttk.Button(actions, text="打开记录目录", command=self.open_directory, state="disabled")
        self.folder_button.pack(side="left")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Destroy>", self._destroyed)
        self.refresh()

    def set_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def choose_root(self):
        path = self.dialogs.askdirectory(parent=self.window, title="选择桌面会话目录或批量结果目录")
        if path:
            self.root_path.set(path)
            self.refresh()

    def refresh(self):
        if self.scanning or self.closed:
            return
        self.scanning = True
        self.records, self.scan_root = {}, None
        self.tree.delete(*self.tree.get_children())
        self.open_button.configure(state="disabled")
        self.folder_button.configure(state="disabled")
        for widget in (self.path_entry, self.choose_button, self.refresh_button):
            widget.configure(state="disabled")
        self.status.set("正在读取本地运行记录，不读取模型；窗口可继续响应…")
        self.set_details("正在刷新。")
        path = self.root_path.get()
        def work():
            try:
                self._queue.put((scan_history(path), None))
            except (OSError, ValueError, TypeError, RecursionError, CheckError) as error:
                self._queue.put((None, str(error)))
        threading.Thread(target=work, daemon=True, name="flowpilot-history-read").start()
        self._after_id = self.window.after(100, self.poll_scan)

    def poll_scan(self):
        self._after_id = None
        if self.closed:
            return
        try:
            result, error = self._queue.get_nowait()
        except Empty:
            self._after_id = self.window.after(100, self.poll_scan)
            return
        self.scanning = False
        for widget in (self.path_entry, self.choose_button, self.refresh_button):
            widget.configure(state="normal")
        if error is not None:
            self.status.set("历史记录读取失败，未显示旧列表。")
            self.set_details(error)
            return
        self.scan_root = result["root"]
        for index, entry in enumerate(result["entries"]):
            key = str(index)
            self.records[key] = entry
            self.tree.insert("", "end", iid=key, values=(entry["started_at"], entry["model"], STATUS_LABELS[entry["status"]]))
        note = "已达 200 个目录项上限，列表可能不完整；请缩小结果目录。" if result["truncated"] else "仅展示运行记录；打开时核验报告。"
        self.status.set(f"找到 {len(self.records)} 条记录；跳过 {result['skipped_links']} 个目录链接。" + note)
        self.set_details("选择记录查看详情。" if self.records else "此目录下没有识别到单模型检查或桌面会话记录。")

    def selected(self):
        selection = self.tree.selection()
        return self.records.get(selection[0]) if selection else None

    def select_entry(self, event=None):
        entry = self.selected()
        self.open_button.configure(state="normal" if entry and entry["status"] == "completed" else "disabled")
        self.folder_button.configure(state="normal" if entry else "disabled")
        if entry:
            self.set_details(STATUS_LABELS[entry["status"]] + "\n目录：" + entry["id"] + "\n\n" + entry["detail"])

    def open_selected(self):
        entry = self.selected()
        if entry is None or entry["status"] != "completed" or self.scanning:
            return
        try:
            loaded = load_history_report(self.scan_root, entry["id"])
            self.on_open(loaded)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError, CheckError) as error:
            self.status.set("所选报告未能核验，请刷新或重新检查。")
            self.messages.showerror("无法打开历史报告", str(error), parent=self.window)

    def open_directory(self):
        entry = self.selected()
        if entry is None or self.scanning:
            return
        try:
            self.on_directory(history_directory(self.scan_root, entry["id"]))
        except (OSError, ValueError, CheckError) as error:
            self.messages.showerror("无法打开记录目录", str(error), parent=self.window)

    def _destroyed(self, event):
        if event.widget is self.window:
            self.closed = True
            if self._after_id is not None:
                self.window.after_cancel(self._after_id)
                self._after_id = None

    def close(self):
        self.window.destroy()
