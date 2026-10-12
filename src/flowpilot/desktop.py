"""Local Tk desktop front end. Start explicitly; importing never opens a window."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import CheckError, ROOT
from flowpilot.desktop_session import DesktopSession, DISCLAIMER, load_completed_check
from flowpilot.compare_reports import compare_reports, render_comparison, write_comparison
from flowpilot.history_window import HistoryBrowser
from flowpilot.model_overview import build_overview
from flowpilot.report_package import PRIVACY_NOTICE, export_package


def initial_window_size(screen_width, screen_height):
    """Reserve desktop margins instead of requesting a window taller than the screen."""
    if any(type(value) is not int or value <= 0 for value in (screen_width, screen_height)):
        raise ValueError("screen dimensions must be positive integers")
    return max(1, min(1100, screen_width - 80)), max(1, min(850, screen_height - 100))


def open_local_path(path):
    path = Path(path).resolve(strict=True)
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class DesktopApp:
    def __init__(self, root, *, model="", comsol_root="", output_root=None, session=None):
        # Tk is optional in headless CI; only an explicitly constructed UI imports it.
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        from tkinter.scrolledtext import ScrolledText
        self.tk, self.dialogs, self.messages, self.ttk = tk, filedialog, messagebox, ttk
        self.root, self.session = root, session or DesktopSession()
        self.artifact_directory = None
        self.current_view = None
        self.current_overview = None
        self._closing = False
        self._after_id = None
        self.model = tk.StringVar(root, str(model or ""))
        self.comsol = tk.StringVar(root, str(comsol_root or os.environ.get("FLOWPILOT_COMSOL_ROOT", "")))
        self.output = tk.StringVar(root, str(output_root or ROOT / "outputs/desktop"))
        self.loads, self.timeout, self.reynolds = (tk.StringVar(root, value) for value in ("2", "300", "2000"))
        self.status = tk.StringVar(root, "选择模型和 COMSOL 目录后，点击“开始检查”。")
        self.source = tk.StringVar(root, "尚未加载报告。")
        root.title("FlowPilot · 模型边界检查")
        width, height = initial_window_size(root.winfo_screenwidth(), root.winfo_screenheight())
        root.geometry(f"{width}x{height}")
        root.minsize(min(860, width), min(650, height))
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        main = ttk.Frame(root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(5, weight=1)
        ttk.Label(main, text="FlowPilot 模型边界检查", style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(main, text="二维稳态层流 · 原模型只读 · 中文证据与建议").grid(row=1, column=0, sticky="w", pady=(3, 12))
        form = ttk.LabelFrame(main, text="1. 选择文件与环境", padding=10)
        form.grid(row=2, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        self.inputs = []
        for row, (label, variable, handler) in enumerate((("模型文件", self.model, self.choose_model),
                                                         ("COMSOL 目录", self.comsol, self.choose_comsol),
                                                         ("结果保存到", self.output, self.choose_output))):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            entry = ttk.Entry(form, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            button = ttk.Button(form, text="选择…", command=handler)
            button.grid(row=row, column=2, padx=(8, 0), pady=4)
            self.inputs.extend((entry, button))
        settings = ttk.Frame(form)
        settings.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        for index, (label, variable) in enumerate((("重复加载", self.loads), ("每进程超时（秒）", self.timeout),
                                                  ("Re 筛查阈值", self.reynolds))):
            ttk.Label(settings, text=label).grid(row=0, column=index * 2, padx=(0 if index == 0 else 16, 6))
            entry = ttk.Entry(settings, textvariable=variable, width=8)
            entry.grid(row=0, column=index * 2 + 1)
            self.inputs.append(entry)
        actions = ttk.Frame(main)
        actions.grid(row=3, column=0, sticky="ew", pady=12)
        self.start_button = ttk.Button(actions, text="开始检查", command=self.start_check)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="取消检查", command=self.cancel_check, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.import_button = ttk.Button(actions, text="读取已有报告…", command=self.import_report)
        self.import_button.pack(side="left")
        self.compare_button = ttk.Button(actions, text="与前次报告对比…", command=self.compare_report, state="disabled")
        self.compare_button.pack(side="left", padx=8)
        self.folder_button = ttk.Button(actions, text="打开结果目录", command=self.open_folder, state="disabled")
        self.folder_button.pack(side="right")
        self.report_button = ttk.Button(actions, text="查看完整报告", command=self.open_report, state="disabled")
        self.report_button.pack(side="right", padx=8)
        history_actions = ttk.Frame(main)
        history_actions.grid(row=7, column=0, sticky="w", pady=(8, 0))
        self.history_button = ttk.Button(history_actions, text="检查历史…", command=self.show_history)
        self.history_button.pack(side="left")
        self.export_button = ttk.Button(history_actions, text="导出协作报告…", command=self.export_report, state="disabled")
        self.export_button.pack(side="left", padx=8)
        progress_frame = ttk.Frame(main)
        progress_frame.grid(row=4, column=0, sticky="ew")
        progress_frame.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(progress_frame, textvariable=self.status, wraplength=920)
        self.status_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(progress_frame, mode="indeterminate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        result = ttk.LabelFrame(main, text="2. 查看问题、证据与建议", padding=10)
        result.grid(row=5, column=0, sticky="nsew", pady=(8, 10))
        result.columnconfigure(0, weight=1)
        result.rowconfigure(1, weight=1)
        ttk.Label(result, textvariable=self.source, wraplength=910).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.result_tabs = ttk.Notebook(result)
        self.result_tabs.grid(row=1, column=0, sticky="nsew")
        self.findings_tab = ttk.Frame(self.result_tabs, padding=6)
        self.findings_tab.columnconfigure(0, weight=1)
        self.findings_tab.rowconfigure(0, weight=1)
        self.overview_tab = ttk.Frame(self.result_tabs, padding=6)
        self.overview_tab.columnconfigure(0, weight=1)
        self.overview_tab.rowconfigure(0, weight=1)
        self.result_tabs.add(self.findings_tab, text="问题诊断")
        self.result_tabs.add(self.overview_tab, text="模型概览")
        self.overview_text = ScrolledText(self.overview_tab, wrap="word", height=12, font=("Microsoft YaHei UI", 10), padx=8, pady=8)
        self.overview_text.grid(row=0, column=0, sticky="nsew")
        self.set_overview("尚无模型概览；完成检查或读取报告后显示。")
        self.findings_pane = ttk.Panedwindow(self.findings_tab, orient="vertical")
        self.findings_pane.grid(row=0, column=0, sticky="nsew")
        tree_frame = ttk.Frame(self.findings_pane)
        self.findings_pane.add(tree_frame, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_frame, columns=("level", "title", "nodes", "boundaries"), show="headings", height=3)
        for key, label, width in (("level", "等级", 130), ("title", "问题", 280),
                                  ("nodes", "相关节点", 180), ("boundaries", "边界编号", 130)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=70, stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self.select_finding)
        details_frame = ttk.Frame(self.findings_pane)
        details_frame.columnconfigure(0, weight=1)
        details_frame.rowconfigure(0, weight=1)
        self.findings_pane.add(details_frame, weight=3)
        self.details = ScrolledText(details_frame, wrap="word", height=7, font=("Microsoft YaHei UI", 10), padx=8, pady=8)
        self.details.grid(row=0, column=0, sticky="nsew")
        self.set_details("这里将显示检查结果。\n\n" + DISCLAIMER)
        ttk.Label(main, text=DISCLAIMER, wraplength=920).grid(row=6, column=0, sticky="w")

    def set_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def set_overview(self, text):
        self.overview_text.configure(state="normal")
        self.overview_text.delete("1.0", "end")
        self.overview_text.insert("1.0", text)
        self.overview_text.configure(state="disabled")

    def choose_model(self):
        path = self.dialogs.askopenfilename(parent=self.root, title="选择 COMSOL 模型", filetypes=(("COMSOL 模型", "*.mph"),))
        if path:
            self.model.set(path)

    def choose_comsol(self):
        path = self.dialogs.askdirectory(parent=self.root, title="选择包含 bin/win64 的 Multiphysics 目录")
        if path:
            self.comsol.set(path)

    def choose_output(self):
        path = self.dialogs.askdirectory(parent=self.root, title="选择结果保存目录")
        if path:
            self.output.set(path)

    def set_busy(self, busy):
        for widget in self.inputs + [self.start_button, self.import_button, self.history_button]:
            widget.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.compare_button.configure(state="normal" if not busy and self.current_view else "disabled")
        self.export_button.configure(state="normal" if not busy and self.current_view else "disabled")
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def clear_result(self):
        self.tree.delete(*self.tree.get_children())
        self.current_view = None
        self.current_overview = None
        self.set_overview("本次尚无可展示的模型概览。")
        self.result_tabs.select(self.findings_tab)
        self.artifact_directory = None
        self.source.set("本次尚无可展示的完整报告。")
        self.report_button.configure(state="disabled")
        self.folder_button.configure(state="disabled")
        self.compare_button.configure(state="disabled")
        self.export_button.configure(state="disabled")

    def start_check(self):
        if self.session.busy:
            return
        previous_directory = self.session.directory
        self.clear_result()
        try:
            if not self.model.get().strip() or not self.comsol.get().strip() or not self.output.get().strip():
                raise ValueError("请先填写模型文件、COMSOL 目录和结果保存目录。")
            self.session.start(self.model.get(), self.comsol.get(), self.output.get(), loads=int(self.loads.get()),
                               timeout=float(self.timeout.get()), reynolds_warning=float(self.reynolds.get()))
        except (OSError, ValueError, CheckError) as error:
            self.status.set("无法开始本次检查，未展示诊断结论。")
            self.status_label.configure(foreground="#8a4b08")
            self.set_details(str(error))
            if self.session.directory is not None and self.session.directory != previous_directory:
                self.artifact_directory = self.session.directory
                self.folder_button.configure(state="normal")
            self.messages.showerror("无法开始检查", str(error), parent=self.root)
            return
        self.set_details("正在读取独立模型副本，不会修改原始文件。\n\n" + DISCLAIMER)
        self.status.set("正在检查，请等待；窗口可以继续响应，必要时可取消。")
        self.status_label.configure(foreground="")
        self.set_busy(True)
        self._after_id = self.root.after(200, self.poll_session)

    def poll_session(self):
        self._after_id = None
        state = self.session.poll()
        if self.session.busy:
            self.status.set(self.session.progress_text)
            self._after_id = self.root.after(200, self.poll_session)
            return
        self.set_busy(False)
        self.artifact_directory = self.session.directory
        self.folder_button.configure(state="normal")
        if state == "completed":
            self.show_result(self.session.result)
        elif state == "cancelled":
            self.status.set("本次检查已取消，未发布诊断结论。")
            self.set_details("已停止本次启动的检查进程。原模型未保存；运行记录保留供排查。")
        else:
            self.status.set("检查未完成，不能作为正常结论。")
            self.set_details(self.session.error + "\n\n可打开结果目录查看日志。")
        if self._closing:
            self.root.destroy()

    def cancel_check(self):
        try:
            if self.session.cancel():
                self.cancel_button.configure(state="disabled")
                self.status.set("正在取消本次检查，等待进程退出…")
        except OSError as error:
            self._closing = False
            self.messages.showerror("取消请求未能保存", "检查仍在进行，可重试取消或等待超时退出。\n" + str(error), parent=self.root)

    def show_result(self, loaded):
        self.clear_result()
        self.current_view = loaded["view"]
        self.current_overview = build_overview(loaded["report"])
        self.set_overview(self.current_overview["text"])
        self.artifact_directory = loaded["directory"]
        metadata = loaded["metadata"]
        self.source.set(f"模型：{metadata['source']['filename']}\nSHA-256：{metadata['source']['sha256']}")
        self.status.set(self.current_view["headline"])
        colors = {"neutral": "#334155", "warning": "#8a4b08", "critical": "#b42318", "incomplete": "#8a4b08"}
        self.status_label.configure(foreground=colors[self.current_view["tone"]])
        for index, item in enumerate(self.current_view["items"]):
            self.tree.insert("", "end", iid=str(index), values=(item["level"], item["title"], item["nodes"], item["boundaries"]))
        self.set_details(self.current_view["detail"] + "\n\n" + DISCLAIMER)
        if self.current_view["items"]:
            self.tree.selection_set("0")
            self.select_finding()
        self.folder_button.configure(state="normal")
        self.compare_button.configure(state="normal")
        self.export_button.configure(state="normal")
        if (self.artifact_directory / "report.md").is_file():
            self.report_button.configure(state="normal")

    def select_finding(self, event=None):
        selected = self.tree.selection()
        if selected and self.current_view:
            self.set_details(self.current_view["items"][int(selected[0])]["detail"] + "\n\n" + DISCLAIMER)

    def import_report(self):
        path = self.dialogs.askdirectory(parent=self.root, title="选择含 run.json 和 diagnosis.json 的单模型检查目录")
        if not path:
            return
        try:
            self.show_result(load_completed_check(path))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, CheckError) as error:
            self.clear_result()
            self.status.set("报告未能验证，未展示诊断结论。")
            self.set_details(str(error))
            self.messages.showerror("无法读取报告", str(error), parent=self.root)

    def open_folder(self):
        if self.artifact_directory:
            self._open(self.artifact_directory)

    def show_history(self):
        if self.session.busy:
            return None
        return HistoryBrowser(self.root, output_root=self.output.get(), on_open=self.open_history_result, on_directory=self._open)

    def open_history_result(self, loaded):
        if self.session.busy:
            raise CheckError("当前检查仍在运行，请结束后再打开历史报告。")
        self.show_result(loaded)

    def compare_report(self):
        if self.session.busy or self.current_view is None or self.artifact_directory is None:
            return
        before = self.dialogs.askdirectory(parent=self.root, title="选择前次单模型报告目录（当前展示的是本次报告）")
        if not before:
            return
        try:
            self.show_comparison(compare_reports(before, self.artifact_directory))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, CheckError, RecursionError) as error:
            self.messages.showerror("无法对比报告", str(error), parent=self.root)

    def show_comparison(self, summary):
        from tkinter.scrolledtext import ScrolledText
        window = self.tk.Toplevel(self.root)
        window.title("FlowPilot · 前次 / 本次检查对比")
        window.geometry("820x640")
        window.minsize(640, 460)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        heading = "报告差异（不是修复验收）" if summary["status"] == "compared" else "无法直接比较，请核对原因"
        self.ttk.Label(window, text=heading, padding=12).grid(row=0, column=0, sticky="w")
        text = ScrolledText(window, wrap="word", font=("Microsoft YaHei UI", 10), padx=12, pady=8)
        text.grid(row=1, column=0, sticky="nsew", padx=12)
        text.insert("1.0", render_comparison(summary))
        text.configure(state="disabled")
        self.ttk.Button(window, text="保存本次对比…", command=lambda: self.export_comparison(summary, window)).grid(
            row=2, column=0, sticky="e", padx=12, pady=12)
        return window

    def export_comparison(self, summary, window):
        parent = self.dialogs.askdirectory(parent=window, title="选择保存位置（会新建独立对比目录）")
        if not parent:
            return
        try:
            directory = write_comparison(summary, Path(parent) / ("comparison-" + uuid.uuid4().hex[:12]))
        except (OSError, ValueError, TypeError) as error:
            self.messages.showerror("保存对比失败", str(error), parent=window)
            return
        self.messages.showinfo("对比已保存", str(directory), parent=window)

    def open_report(self):
        if self.artifact_directory:
            self._open(self.artifact_directory / "report.md")

    def export_report(self):
        if self.session.busy or self.current_view is None or self.artifact_directory is None:
            return
        if not self.messages.askyesno("确认导出范围", PRIVACY_NOTICE, parent=self.root):
            return
        parent = self.dialogs.askdirectory(parent=self.root, title="选择保存位置（将新建协作报告文件夹）")
        if not parent:
            return
        try:
            directory = export_package(self.artifact_directory, Path(parent) / ("report-package-" + uuid.uuid4().hex[:12]))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, CheckError, RecursionError) as error:
            self.messages.showerror("导出未完成", "不要分享不完整的导出目录；原报告未改动。\n" + str(error), parent=self.root)
            return
        self.messages.showinfo("协作报告已导出", "可审阅并手动压缩分享整个文件夹：\n" + str(directory), parent=self.root)

    def _open(self, path):
        try:
            open_local_path(path)
        except OSError as error:
            self.messages.showerror("无法打开", str(error), parent=self.root)

    def close(self):
        if self.session.busy:
            if not self._closing and self.messages.askyesno("检查仍在进行", "取消本次检查并在进程退出后关闭窗口？", parent=self.root):
                self._closing = True
                self.cancel_check()
            return
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="FlowPilot local desktop model checker")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--comsol-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    try:
        import tkinter as tk
    except ImportError as error:
        parser.exit(1, f"Cannot initialize desktop UI: {error}\n")
    try:
        root = tk.Tk()
    except tk.TclError as error:
        parser.exit(1, f"Cannot initialize desktop UI: {error}\n")
    DesktopApp(root, model=args.model, comsol_root=args.comsol_root, output_root=args.output_root)
    root.mainloop()


if __name__ == "__main__":
    main()
