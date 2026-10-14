"""Opt-in AI tab reusing the unchanged checker; no solver runs in this UI."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.desktop import DesktopApp
from flowpilot.check_model import CheckError
from flowpilot.desktop_session import load_completed_check
from flowpilot.recommend import DEFAULT_PORTABLE_MODEL as DEFAULT_MODEL, recommend_report, render
from flowpilot.portable_recommend import NOTICE


class RecommendationApp(DesktopApp):
    def __init__(self, root, *, learned_model=DEFAULT_MODEL, **kwargs):
        super().__init__(root, **kwargs)
        from tkinter.scrolledtext import ScrolledText
        self.learned_model = Path(learned_model)
        self.root.title("FlowPlot · 边界检查与 AI 参数推荐")
        self.ai_tab = self.ttk.Frame(self.result_tabs, padding=6)
        self.ai_tab.columnconfigure(0, weight=1)
        self.ai_tab.rowconfigure(1, weight=1)
        self.result_tabs.add(self.ai_tab, text="AI 参数推荐")
        actions = self.ttk.Frame(self.ai_tab)
        actions.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.ai_model_button = self.ttk.Button(actions, text="读取本机学习模型…", command=self.choose_learned_model)
        self.ai_model_button.pack(side="left")
        self.ai_refresh_button = self.ttk.Button(actions, text="刷新推荐", command=self.refresh_recommendation)
        self.ai_refresh_button.pack(side="left", padx=8)
        self.ai_text = ScrolledText(self.ai_tab, wrap="word", font=("Microsoft YaHei UI", 10), padx=8, pady=8)
        self.ai_text.grid(row=1, column=0, sticky="nsew")
        self.ai_result = None
        self.set_ai_text("完成检查或读取已有报告后显示推荐。\n\n" + NOTICE)

    def set_ai_text(self, value):
        self.ai_text.configure(state="normal")
        self.ai_text.delete("1.0", "end")
        self.ai_text.insert("1.0", value)
        self.ai_text.configure(state="disabled")

    def clear_result(self):
        super().clear_result()
        if hasattr(self, "ai_text"):
            self.ai_result = None
            self.set_ai_text("尚无有效报告，不展示旧推荐。\n\n" + NOTICE)

    def set_busy(self, busy):
        super().set_busy(busy)
        for widget in (self.ai_model_button, self.ai_refresh_button):
            widget.configure(state="disabled" if busy else "normal")

    def show_result(self, loaded):
        super().show_result(loaded)
        self.refresh_recommendation(expected=loaded)

    def choose_learned_model(self):
        if self.session.busy:
            return
        path = self.dialogs.askopenfilename(parent=self.root, title="读取本机校准的学习模型 JSON",
                                          filetypes=(("学习模型", "*.json"),))
        if path:
            self.learned_model = Path(path)
            self.refresh_recommendation()

    def open_report(self, directory):
        """Explicit offline preview; use the same verified reader as report import."""
        if self.session.busy:
            raise CheckError("检查仍在运行，请等待结束后再打开已有报告。")
        try:
            self.show_result(load_completed_check(directory))
            self.result_tabs.select(self.ai_tab)
        except (OSError, ValueError, TypeError, KeyError, CheckError):
            self.clear_result()
            self.status.set("已有报告未能验证，未展示诊断或推荐。")
            raise

    def refresh_recommendation(self, *, expected=None):
        if self.session.busy:
            return
        self.ai_result = None
        if self.current_view is None or self.artifact_directory is None:
            self.set_ai_text("请先完成检查或读取有效报告。\n\n" + NOTICE)
            return
        try:
            result = recommend_report(self.artifact_directory, self.learned_model)
            if expected and result["source_sha256"] != expected["metadata"]["source"]["sha256"].lower():
                raise ValueError("报告来源在展示期间变化，请重新读取报告。")
            self.ai_result = result
            self.set_ai_text(render(result))
        except (OSError, ValueError, TypeError, KeyError, CheckError) as error:
            self.set_ai_text("暂不能推荐，原检查结论不变。请确认本机校准模型完整且来源匹配。\n"
                             + str(error) + "\n\n" + NOTICE)


def main(arguments=None):
    parser = argparse.ArgumentParser(description="FlowPlot checker with local AI parameter recommendations")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--comsol-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--learned-model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--report", type=Path, help="open an existing verified report, without COMSOL")
    args = parser.parse_args(arguments)
    # Refuse invalid inputs before creating a window. This option never starts a check.
    try:
        loaded = load_completed_check(args.report) if args.report else None
    except (OSError, ValueError, TypeError, KeyError, CheckError) as error:
        parser.exit(1, f"Cannot preview report: {error}\n")
    try:
        import tkinter as tk
    except ImportError as error:
        parser.exit(1, f"Cannot initialize recommendation UI: {error}\n")
    try:
        root = tk.Tk()
        app = RecommendationApp(root, model=args.model, comsol_root=args.comsol_root,
                                output_root=args.output_root, learned_model=args.learned_model)
        if loaded:
            app.show_result(loaded)
            app.result_tabs.select(app.ai_tab)
        root.mainloop()
    except tk.TclError as error:
        parser.exit(1, f"Cannot initialize recommendation UI: {error}\n")


if __name__ == "__main__":
    main()
