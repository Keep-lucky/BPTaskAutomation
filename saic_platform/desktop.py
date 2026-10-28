"""Tkinter 桌面工作台；后台线程请求，主线程更新界面。"""

from datetime import datetime
from html import unescape
import json
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .api import SaicClient, PlatformError
from .auth import SmsAuth, validate_phone
from .batch import BatchRunner
from .debug import build_request_preview
from .workflow import STEPS, Workflow, material_fields, default_material_path
from .wechat import open_article
from .article_actions import interact_article


class DesktopApp:
    def __init__(self, root):
        self.root = root
        self.root.title("上汽任务工作台")
        # 高 DPI 缩放下屏幕逻辑尺寸可能较小，窗口按可用屏幕收缩，其余内容用滚动条查看。
        width = min(1180, self.root.winfo_screenwidth() - 60)
        height = min(880, self.root.winfo_screenheight() - 100)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min(940, width), 480)
        self.events = queue.Queue()
        self.client = self.workflow = self.detail = None
        self.busy = False
        self.pending_auto_submit = False
        self.auth = SmsAuth()
        self.resend_at = 0
        self.files = {}
        self.tasks = {}
        self.checked = set()
        self.batch_runner = None
        self.batch_rows = {}
        self.batch_finished = set()
        self.controls = []
        self.build()
        root.after(100, self.poll)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def button(self, parent, text, command):
        widget = ttk.Button(parent, text=text, command=command)
        self.controls.append(widget)
        return widget

    def build(self):
        shell = ttk.Frame(self.root)
        shell.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(shell, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        base = ttk.Frame(self.canvas, padding=14)
        window = self.canvas.create_window((0, 0), window=base, anchor="nw")
        base.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))
        self.root.bind_all("<MouseWheel>", self.scroll_wheel)
        login = ttk.LabelFrame(base, text="1. 手机号验证码登录", padding=8)
        login.pack(fill="x")
        sms = ttk.Frame(login)
        sms.pack(fill="x", pady=4)
        ttk.Label(sms, text="手机号").pack(side="left")
        self.phone = ttk.Entry(sms, width=16)
        self.phone.pack(side="left", padx=4)
        self.controls.append(self.phone)
        self.sms_button = self.button(sms, "获取验证码", self.send_code)
        self.sms_button.pack(side="left", padx=4)
        ttk.Label(sms, text="验证码").pack(side="left")
        self.code = ttk.Entry(sms, width=10, show="•")
        self.code.pack(side="left", padx=4)
        self.controls.append(self.code)
        self.button(sms, "短信登录", self.sms_login).pack(side="left", padx=4)
        self.login_status = ttk.Label(sms, text="请先登录")
        self.login_status.pack(side="left", padx=8)
        tokenrow = ttk.Frame(login)
        tokenrow.pack(fill="x")
        ttk.Label(tokenrow, text="备用 Token").pack(side="left")
        login = tokenrow
        self.token = ttk.Entry(login, show="•", width=65)
        self.token.pack(side="left", fill="x", expand=True, padx=4)
        self.controls.append(self.token)
        self.button(login, "粘贴 Token", self.paste).pack(side="left", padx=4)
        self.button(login, "登录并加载任务", self.login).pack(side="left", padx=4)
        toolbar = ttk.Frame(base)
        toolbar.pack(fill="x", pady=8)
        self.filter = ttk.Combobox(toolbar, values=["任务广场", "进行中", "已完成", "已失效"], state="readonly", width=12)
        self.filter.current(0)
        self.filter.pack(side="left")
        self.controls.append(self.filter)
        self.page = tk.IntVar(value=1)
        ttk.Label(toolbar, text=" 页码 ").pack(side="left")
        self.page_entry = ttk.Entry(toolbar, textvariable=self.page, width=5)
        self.page_entry.pack(side="left")
        self.controls.append(self.page_entry)
        self.button(toolbar, "刷新列表", self.refresh).pack(side="left", padx=8)
        self.button(toolbar, "查看选中任务", self.inspect).pack(side="left")
        self.button(toolbar, "全选本页", lambda: self.select_all(True)).pack(side="left", padx=4)
        self.button(toolbar, "取消全选", lambda: self.select_all(False)).pack(side="left")
        self.count = ttk.Label(toolbar, text="选择任务查看要求及材料")
        self.count.pack(side="left", padx=12)
        self.table = ttk.Treeview(base, columns=("check", "title", "platform", "id", "deadline", "result"), show="headings", height=6)
        for name, title, width in [("check", "勾选", 48), ("title", "任务名称", 280), ("platform", "平台", 100), ("id", "任务 ID", 140), ("deadline", "截止时间", 160), ("result", "处理结果", 150)]:
            self.table.heading(name, text=title)
            self.table.column(name, width=width)
        self.table.pack(fill="x")
        self.table.bind("<Button-1>", self.toggle_check)
        self.table.bind("<Double-1>", self.open_row)
        self.table.bind("<space>", self.toggle_focused)
        self.selection_count = ttk.Label(base, text="已勾选 0 个任务（全选仅当前页）")
        self.selection_count.pack(anchor="w")
        panes = ttk.Panedwindow(base, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=8)
        left = ttk.LabelFrame(panes, text="2. 任务要求", padding=6)
        right = ttk.LabelFrame(panes, text="3. 材料选择", padding=6)
        panes.add(left, weight=1)
        panes.add(right, weight=1)
        targetrow = ttk.Frame(left)
        targetrow.pack(fill="x", pady=(0, 6))
        ttk.Label(targetrow, text="目标文章链接").pack(anchor="w")
        self.target_url = tk.StringVar()
        ttk.Entry(targetrow, textvariable=self.target_url, state="readonly").pack(fill="x")
        target_actions = ttk.Frame(targetrow)
        target_actions.pack(fill="x", pady=(4, 0))
        self.button(target_actions, "复制目标链接", self.copy_target_url).pack(side="left")
        self.button(target_actions, "微信打开（方案一）", self.open_target_article).pack(side="left", padx=6)
        self.button(target_actions, "自动打开并截图", self.interact_target_article).pack(side="left")
        self.button(target_actions, "当前文章执行并截图", self.interact_current_article).pack(side="left", padx=6)
        interaction_options = ttk.Frame(targetrow)
        interaction_options.pack(fill="x", pady=4)
        self.article_like = tk.BooleanVar(value=True)
        self.article_watch = tk.BooleanVar(value=True)
        self.article_moments = tk.BooleanVar(value=False)
        for label, variable in (("点赞", self.article_like), ("在看", self.article_watch), ("准备朋友圈分享", self.article_moments)):
            option = ttk.Checkbutton(interaction_options, text=label, variable=variable)
            option.pack(side="left")
            self.controls.append(option)
        self.auto_submit = tk.BooleanVar(value=False)
        auto_submit = ttk.Checkbutton(
            targetrow,
            text="截图完成后自动提交审核（跳过人工确认，仅当前任务）",
            variable=self.auto_submit,
        )
        auto_submit.pack(anchor="w", pady=(0, 4))
        self.controls.append(auto_submit)
        ttk.Label(targetrow, text="朋友圈配文（选填，最终在微信中确认发表）").pack(anchor="w")
        self.article_caption = tk.StringVar()
        caption_entry = ttk.Entry(targetrow, textvariable=self.article_caption)
        caption_entry.pack(fill="x")
        self.controls.append(caption_entry)
        self.requirements = tk.Text(left, wrap="word", width=50, height=9, state="disabled")
        self.requirements.pack(fill="both", expand=True)
        self.materials = ttk.Frame(right)
        self.materials.pack(fill="both", expand=True)
        self.link = tk.StringVar()
        linkrow = ttk.Frame(right)
        linkrow.pack(fill="x")
        ttk.Label(linkrow, text="作品链接（原创必填）").pack(anchor="w")
        self.link_entry = ttk.Entry(linkrow, textvariable=self.link)
        self.link_entry.pack(fill="x")
        self.controls.append(self.link_entry)
        self.real = tk.BooleanVar()
        self.check = ttk.Checkbutton(base, variable=self.real, text="我已真实完成当前任务 / 所有勾选任务，所选及平台目录截图与各任务要求对应")
        self.check.pack(anchor="w")
        self.controls.append(self.check)
        batch_options = ttk.Frame(base)
        batch_options.pack(fill="x")
        ttk.Label(batch_options, text="批量并发线程数").pack(side="left")
        self.workers = tk.StringVar(value="3")
        self.workers_entry = ttk.Spinbox(batch_options, from_=1, to=8, textvariable=self.workers, width=4)
        self.workers_entry.pack(side="left", padx=6)
        self.controls.append(self.workers_entry)
        ttk.Label(batch_options, text="勾选任务时批量执行；未勾选时提交当前详情任务").pack(side="left")
        actions = ttk.Frame(base)
        actions.pack(fill="x", pady=6)
        self.button(actions, "调试预览（不领取、不上传、不提交）", self.preview).pack(side="left")
        self.button(actions, "一键领取、上传并提交审核", self.execute).pack(side="left", padx=12)
        ttk.Label(actions, text="执行中请勿关闭；失败后查看下方步骤和日志").pack(side="left")
        self.steps = ttk.Treeview(base, columns=("state", "message"), height=5)
        self.steps.heading("#0", text="步骤")
        self.steps.column("#0", width=160, stretch=False)
        self.steps.heading("state", text="状态")
        self.steps.column("state", width=80, stretch=False)
        self.steps.heading("message", text="结果 / 问题")
        for state, color in [("失败", "#b91c1c"), ("成功", "#15803d"), ("进行中", "#1d4ed8")]:
            self.steps.tag_configure(state, foreground=color)
        self.steps.pack(fill="x")
        self.reset_steps()
        self.progress = ttk.Progressbar(base, maximum=len(STEPS), mode="determinate")
        self.progress.pack(fill="x", pady=5)
        logs = ttk.Frame(base)
        logs.pack(fill="both", expand=True)
        self.log = tk.Text(logs, height=7, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(logs, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def scroll_wheel(self, event):
        # 文本、表格和下拉框保留自己的滚轮行为，其余区域滚动整个页面。
        if isinstance(event.widget, (tk.Text, ttk.Treeview, ttk.Combobox)):
            return
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def paste(self):
        try:
            value = self.root.clipboard_get().strip()
            self.token.delete(0, "end")
            self.token.insert(0, value)
        except tk.TclError:
            messagebox.showerror("无法粘贴", "剪贴板中没有文本。")

    def copy_target_url(self):
        url = self.target_url.get()
        if not url:
            return messagebox.showinfo("提示", "请先查看任务详情；该任务可能未配置目标文章链接。")
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.write("目标文章链接已复制。")

    def open_target_article(self):
        if self.busy:
            return
        url = self.target_url.get()
        if not url:
            return messagebox.showinfo("提示", "请先查看含目标文章链接的任务详情。")
        self.write("正在通过微信文件传输助手发送并打开当前任务文章。")
        self.start(lambda: open_article(url), self.write)

    def article_options(self):
        return dict(like=self.article_like.get(), watch=self.article_watch.get(),
                    moments=self.article_moments.get(), caption=self.article_caption.get(),
                    detail=dict(self.detail))

    def article_emit(self, text):
        self.events.put(("done", self.write, text))

    def interact_target_article(self):
        if self.busy:
            return
        if not self.detail or not self.target_url.get():
            return messagebox.showinfo("提示", "请先查看含目标文章链接的任务详情。")
        if not any((self.article_like.get(), self.article_watch.get(), self.article_moments.get())):
            return messagebox.showinfo("提示", "请至少勾选一项文章操作。")
        url = self.target_url.get()
        options = self.article_options()
        self.write("开始文章操作，请保持微信窗口可用；截图会在各操作确认成功后自动保存并填入材料。")
        self.start(lambda: interact_article(url, **options, emit=self.article_emit), self.article_done)

    def interact_current_article(self):
        if self.busy:
            return
        if not self.detail:
            return messagebox.showinfo("提示", "请先查看任务详情，以确定要填入的材料。")
        if not any((self.article_like.get(), self.article_watch.get(), self.article_moments.get())):
            return messagebox.showinfo("提示", "请至少勾选一项文章操作。")
        options = self.article_options()
        self.write("将操作微信中当前已打开的文章。请确认只打开目标文章，且未打开其他公众号文章。")
        self.start(lambda: interact_article("", **options, reuse_open_article=True, emit=self.article_emit),
                   self.article_done)

    def article_done(self, result):
        self.write(result.get("message", "文章操作已结束。"))
        for name, path in result.get("materials", {}).items():
            if name in self.files:
                self.files[name].set(path)
                self.write(f"已自动填入材料：{name} ← {path}")
            else:
                self.write(f"截图已保存，但当前任务没有「{name}」材料字段：{path}")
        for warning in result.get("warnings", []):
            self.write("注意：" + warning)
        if not self.auto_submit.get():
            if result.get("materials"):
                self.write("请核对材料截图与任务要求；确认无误后勾选真实完成，再执行提交。")
            return
        if not result.get("materials"):
            self.write("自动提交已跳过：本次没有自动填入任何材料，请手动核对后提交。")
            return
        if not (self.client and self.workflow and self.detail):
            self.write("自动提交已跳过：请先登录并查看任务详情。")
            return
        self.write("自动提交已开启：截图完成后直接提交当前任务，不再人工确认；必填材料缺失时会跳过自动提交。")
        self.pending_auto_submit = True

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"[{datetime.now():%H:%M:%S}] {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def start(self, work, done):
        if self.busy:
            return
        self.busy = True
        for control in self.controls:
            control.configure(state="disabled")
        def run():
            try:
                self.events.put(("done", done, work()))
            except Exception as error:
                message = str(error) if isinstance(error, (PlatformError, ValueError)) else f"本地异常：{type(error).__name__}"
                self.events.put(("error", message))
            finally:
                self.events.put(("idle",))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "done":
                    event[1](event[2])
                elif event[0] == "error":
                    self.write("失败：" + event[1])
                    messagebox.showerror("操作失败", event[1])
                elif event[0] == "step":
                    _, step, state, message = event
                    self.steps.item(step, values=(state, message), tags=(state,))
                    self.progress["value"] = sum(self.steps.item(s, "values")[0] == "成功" for s in STEPS)
                    self.write(f"{step} · {state} · {message}")
                elif event[0] == "batch_step":
                    _, task_id, step, state, message = event
                    node = f"batch:{task_id}:{step}"
                    self.steps.item(node, values=(state, message), tags=(state,))
                    self.steps.item(f"batch:{task_id}", values=(state if state == "失败" else "进行中", f"{step}：{message}"))
                    self.table.set(self.batch_rows[task_id], "result", f"{step} · {state}")
                    self.write(f"任务 {task_id} · {step} · {state} · {message}")
                elif event[0] == "batch_result":
                    _, task_id, success = event
                    self.batch_finished.add(task_id)
                    state = "成功" if success else "失败"
                    self.steps.item(f"batch:{task_id}", values=(state, "已提交待审核" if success else "请展开查看失败步骤"), tags=(state,))
                    self.table.set(self.batch_rows[task_id], "result", "已提交待审核" if success else "失败，查看日志")
                    self.progress["value"] = len(self.batch_finished)
                elif event[0] == "idle":
                    self.busy = False
                    for control in self.controls:
                        control.configure(state="readonly" if control is self.filter else "normal")
        except queue.Empty:
            pass
        if self.pending_auto_submit and not self.busy:
            self.pending_auto_submit = False
            self._auto_submit()
        remaining = max(0, int(self.resend_at - time.monotonic() + 0.999))
        self.sms_button.configure(text=f"{remaining}s 后重发" if remaining else "获取验证码",
                                  state="disabled" if self.busy or remaining else "normal")
        self.root.after(100, self.poll)

    def send_code(self):
        if self.busy or time.monotonic() < self.resend_at:
            return
        phone = self.phone.get().strip()
        try:
            validate_phone(phone)
        except ValueError as error:
            return messagebox.showerror("手机号错误", str(error))
        def done(_):
            self.resend_at = time.monotonic() + 59
            self.login_status.configure(text="验证码已发送，请查收短信")
            self.write("验证码已发送。")
        self.start(lambda: self.auth.send_code(phone), done)

    def sms_login(self):
        if self.busy:
            return
        phone, code = self.phone.get().strip(), self.code.get().strip()
        def work():
            client = self.auth.login(phone, code)
            try:
                return client, client.list_tasks()
            except Exception:
                client.close()
                raise
        self.start(work, self.logged_in)

    def logged_in(self, result):
        if self.client:
            self.client.close()
        self.client, tasks = result
        self.workflow = Workflow(self.client)
        self.batch_runner = BatchRunner(self.client.clone, self.workflow.uncertain)
        self.detail = None
        self.pending_auto_submit = False
        self.target_url.set("")
        self.article_caption.set("")
        self.real.set(False)
        self.link.set("")
        self.files = {}
        for child in self.materials.winfo_children():
            child.destroy()
        self.controls = [c for c in self.controls if c.winfo_exists()]
        self.requirements.configure(state="normal")
        self.requirements.delete("1.0", "end")
        self.requirements.configure(state="disabled")
        self.token.delete(0, "end")
        self.code.delete(0, "end")
        self.login_status.configure(text="登录成功")
        self.filter.current(0)
        self.page.set(1)
        self.show_tasks(tasks)
        self.write("登录验证成功，任务列表已加载。")

    def login(self):
        token = self.token.get().strip()
        def work():
            client = SaicClient(token)
            try:
                client.validate_login()
                return client, client.list_tasks()
            except Exception:
                client.close()
                raise
        self.start(work, self.logged_in)

    def show_tasks(self, result):
        self.table.delete(*self.table.get_children())
        self.tasks = {}
        self.checked.clear()
        self.real.set(False)
        for index, task in enumerate(result["data"]):
            iid = str(index)
            self.tasks[iid] = task
            self.table.insert("", "end", iid=iid, values=("☐", task.get("taskName"), task.get("platformName"), task["taskId"], task.get("endTime"), ""))
        self.count.configure(text=f"共 {result['count']} 条，本页 {len(result['data'])} 条")
        self.update_checked()

    def update_checked(self):
        for iid in self.tasks:
            self.table.set(iid, "check", "☑" if iid in self.checked else "☐")
        self.selection_count.configure(text=f"已勾选 {len(self.checked)} 个任务（全选仅当前页）")

    def select_all(self, checked):
        if self.busy:
            return
        self.checked = set(self.tasks) if checked else set()
        self.update_checked()

    def toggle_check(self, event):
        if self.busy:
            return "break"
        iid = self.table.identify_row(event.y)
        if iid and self.table.identify_column(event.x) == "#1":
            self.checked.symmetric_difference_update({iid})
            self.update_checked()
            return "break"

    def toggle_focused(self, _):
        iid = self.table.focus()
        if not self.busy and iid in self.tasks:
            self.checked.symmetric_difference_update({iid})
            self.update_checked()
        return "break"

    def open_row(self, event):
        if self.table.identify_column(event.x) != "#1":
            self.inspect()
        return "break"

    def refresh(self):
        if not self.client:
            return messagebox.showinfo("提示", "请先登录。")
        try:
            page = self.page.get()
            if page < 1:
                raise ValueError()
        except (ValueError, tk.TclError):
            return messagebox.showerror("页码错误", "请输入正整数。")
        status = ["plaza", "active", "completed", "expired"][self.filter.current()]
        self.start(lambda: self.client.list_tasks(status=status, page=page), self.show_tasks)

    def inspect(self):
        if self.busy:
            return
        selection = self.table.selection()
        if not selection or not self.client:
            return messagebox.showinfo("提示", "请先登录并选择一个任务。")
        task_id = str(self.tasks[selection[0]]["taskId"])
        self.start(lambda: (self.client.get_task_detail(task_id), self.client.get_task_status(task_id)), self.show_detail)

    def show_detail(self, result):
        self.detail, self.task_status = result
        self.pending_auto_submit = False
        self.article_caption.set("")
        target_url = (self.detail.get("taskDetailDTOS") or {}).get("taskLinkUrl")
        self.target_url.set(target_url.strip() if isinstance(target_url, str) else "")
        if self.target_url.get().startswith("https://mp.weixin.qq.com/"):
            self.write("若微信版本无法自动打开文章，请复制链接在微信中手动打开，再点“当前文章执行并截图”。")
        self.real.set(False)
        self.link.set("")
        self.files = {}
        for child in self.materials.winfo_children():
            child.destroy()
        self.controls = [c for c in self.controls if c.winfo_exists()]
        text = f"{self.detail.get('name')} / {self.detail.get('platformName')}\n任务 ID：{self.detail['taskId']}\n领取状态：{self.task_status['status']}；单号：{self.task_status.get('ticketId') or '未领取'}\n"
        for section in (self.detail.get("taskDetailDTOS") or {}).get("articleBody", []):
            text += "\n" + section.get("name", "") + "\n" + unescape(re.sub("<[^>]+>", " ", section.get("body", ""))) + "\n"
        self.requirements.configure(state="normal")
        self.requirements.delete("1.0", "end")
        self.requirements.insert("end", text)
        self.requirements.configure(state="disabled")
        try:
            fields = material_fields(self.detail)
        except ValueError as error:
            self.detail = None
            self.write(str(error))
            return
        # 只预选任务实际需要的文章操作，避免自动截图时执行多余互动。
        names = [name for name, _ in fields]
        self.article_like.set(any("点赞" in name for name in names))
        self.article_watch.set(any("在看" in name for name in names))
        self.article_moments.set(any(keyword in name for name in names for keyword in ("转发", "朋友圈")))
        for name, required in fields:
            row = ttk.Frame(self.materials)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=name + (" *" if required else "（选填）"), width=23).pack(side="left")
            value = tk.StringVar(value=default_material_path(name, self.detail))
            self.files[name] = value
            field = ttk.Entry(row, textvariable=value)
            field.pack(side="left", fill="x", expand=True)
            self.controls.append(field)
            self.button(row, "选择", lambda v=value: self.choose(v)).pack(side="left")
        self.write(f"任务 {self.detail['taskId']} 要求已加载，请选择真实材料。")
        for name, value in self.files.items():
            if value.get():
                self.write(f"默认材料：{name} ← {value.get()}")

    def choose(self, value):
        path = filedialog.askopenfilename(title="选择真实任务截图", filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if path:
            value.set(path)

    def preview(self):
        if not self.detail:
            return messagebox.showinfo("提示", "请先查看任务详情。")
        self.write("调试预览（不发送写请求）：\n" + json.dumps(build_request_preview(self.detail, self.task_status), ensure_ascii=False, indent=2))

    def reset_steps(self):
        self.steps.delete(*self.steps.get_children())
        for step in STEPS:
            self.steps.insert("", "end", iid=step, text=step, values=("待执行", ""))

    def execute_batch(self):
        if not self.client or not self.batch_runner:
            return messagebox.showinfo("提示", "请先登录。")
        if not self.real.get():
            return messagebox.showinfo("提示", "请确认已真实完成勾选的任务，平台目录中的图片与任务要求对应。")
        try:
            workers = int(self.workers.get())
            if not 1 <= workers <= 8:
                raise ValueError()
        except ValueError:
            return messagebox.showerror("线程数错误", "请输入 1 到 8 的并发线程数。")
        tasks = list({str(task["taskId"]): dict(task) for iid, task in self.tasks.items() if iid in self.checked}.values())
        self.batch_rows = {str(task["taskId"]): iid for iid, task in self.tasks.items() if iid in self.checked}
        self.batch_finished = set()
        self.steps.delete(*self.steps.get_children())
        for task in tasks:
            task_id = str(task["taskId"])
            parent = f"batch:{task_id}"
            self.steps.insert("", "end", iid=parent, text=f"{task.get('taskName') or task_id} ({task_id})", values=("待执行", ""), open=False)
            self.table.set(self.batch_rows[task_id], "result", "排队中")
            for step in STEPS:
                self.steps.insert(parent, "end", iid=f"{parent}:{step}", text=step, values=("待执行", ""))
        self.progress.configure(maximum=len(self.batch_rows), value=0)
        self.write(f"开始批量处理 {len(tasks)} 个任务，并发 {workers}。")
        def done(results):
            successful = sum(results.values())
            self.write(f"批量完成：成功 {successful}，失败 {len(results) - successful}。成功项已提交等待审核。")
        self.start(lambda: self.batch_runner.run(tasks, workers, lambda *args: self.events.put(args)), done)

    def execute(self):
        if self.busy:
            return
        # 手动提交优先，丢弃尚未触发的自动提交，避免同一任务被提交两次。
        self.pending_auto_submit = False
        if self.checked:
            return self.execute_batch()
        self.submit_current()

    def submit_current(self):
        if not self.detail or not self.workflow:
            return messagebox.showinfo("提示", "请先查看任务详情并选择材料。")
        if not self.real.get():
            return messagebox.showinfo("提示", "请确认已真实完成任务，并选择对应截图。")
        self._start_submit()

    def _auto_submit(self):
        if not (self.workflow and self.detail):
            self.write("自动提交已跳过：任务详情或登录状态已失效，请手动处理。")
            return
        try:
            fields = material_fields(self.detail)
        except ValueError:
            fields = []
        missing = [name for name, required in fields
                   if required and not (self.files.get(name) and self.files[name].get().strip())]
        if missing:
            self.write("自动提交已跳过：必填材料仍为空（" + "、".join(missing) + "），请手动补充后提交。")
            return
        if self.checked:
            self.write("自动提交只处理当前详情任务；已勾选的批量任务保持原状。")
        self.write("自动提交：开始领取、上传并提交当前任务（跳过人工确认）。")
        self._start_submit()

    def _start_submit(self):
        self.reset_steps()
        self.progress.configure(maximum=len(STEPS))
        self.progress["value"] = 0
        detail = dict(self.detail)
        selected = {name: value.get().strip() for name, value in self.files.items()}
        link = self.link.get().strip()
        self.start(lambda: self.workflow.run(detail, selected, link, lambda *args: self.events.put(("step", *args))),
                   lambda success: self.write("流程完成，材料已提交等待审核。" if success else "流程已停止；请查看红色步骤定位问题。"))

    def close(self):
        if self.busy:
            messagebox.showinfo("执行中", "请求仍在执行，请等待当前流程结束后关闭窗口。")
            return
        if self.client:
            self.client.close()
        self.auth.close()
        self.root.destroy()


def launch():
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()
