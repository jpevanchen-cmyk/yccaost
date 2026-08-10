# V1 第 11 项：本机忘记密码重置（窗口界面，不依赖托盘密码）

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _setup_django() -> None:
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wuwei_system.settings')
    import django

    django.setup()


def main() -> None:
    _setup_django()
    from waimai.v1_password_reset_helpers import (
        CONFIRM_PHRASE,
        clear_operation_lock_pin_local,
        clear_tray_startup_exit_password,
        confirm_phrase_ok,
        list_owner_accounts,
        reset_owner_login_password,
    )

    owners = list_owner_accounts()
    owner_names = [u.username for u in owners]

    win = tk.Tk()
    win.title('野草 · 本机忘记密码重置')
    win.geometry('520x460')
    win.attributes('-topmost', True)

    tip = (
        '只能在装野草的这台电脑上使用。\n'
        '忘了网页登录密码、托盘启动/退出密码、或操作锁，可在此处理。\n'
        '改完后请用新密码登录；托盘/操作锁清除后可再重新设置。'
    )
    ttk.Label(win, text=tip, wraplength=480, justify='left').pack(padx=12, pady=10, anchor='w')

    owner_var = tk.StringVar(value=owner_names[0] if owner_names else '')
    do_owner = tk.BooleanVar(value=bool(owner_names))
    do_tray = tk.BooleanVar(value=False)
    do_lock = tk.BooleanVar(value=False)
    pwd_var = tk.StringVar()
    pwd2_var = tk.StringVar()
    confirm_var = tk.StringVar()

    frm = ttk.Frame(win)
    frm.pack(fill='both', expand=True, padx=12, pady=4)

    ttk.Checkbutton(frm, text='重置老板网页登录密码', variable=do_owner).grid(
        row=0, column=0, columnspan=2, sticky='w', pady=4,
    )
    ttk.Label(frm, text='老板登录名').grid(row=1, column=0, sticky='w')
    if owner_names:
        ttk.Combobox(frm, textvariable=owner_var, values=owner_names, width=36).grid(
            row=1, column=1, sticky='w', pady=2,
        )
    else:
        ttk.Entry(frm, textvariable=owner_var, width=38).grid(row=1, column=1, sticky='w', pady=2)
        ttk.Label(frm, text='（库中暂无服务器管理者标记，请手工填写登录名）').grid(
            row=2, column=0, columnspan=2, sticky='w',
        )

    ttk.Label(frm, text='新密码').grid(row=3, column=0, sticky='w')
    ttk.Entry(frm, textvariable=pwd_var, show='*', width=38).grid(row=3, column=1, sticky='w', pady=2)
    ttk.Label(frm, text='再输一次').grid(row=4, column=0, sticky='w')
    ttk.Entry(frm, textvariable=pwd2_var, show='*', width=38).grid(row=4, column=1, sticky='w', pady=2)

    ttk.Checkbutton(frm, text='清除托盘启动/退出密码', variable=do_tray).grid(
        row=5, column=0, columnspan=2, sticky='w', pady=8,
    )
    ttk.Checkbutton(frm, text='清除操作锁（后台遮罩密码）', variable=do_lock).grid(
        row=6, column=0, columnspan=2, sticky='w', pady=2,
    )

    ttk.Label(frm, text=f'确认词（请输入：{CONFIRM_PHRASE}）').grid(
        row=7, column=0, columnspan=2, sticky='w', pady=(12, 2),
    )
    ttk.Entry(frm, textvariable=confirm_var, width=38).grid(row=8, column=1, sticky='w')

    def on_run() -> None:
        if not confirm_phrase_ok(confirm_var.get()):
            messagebox.showerror('未确认', f'请在确认框原样输入：{CONFIRM_PHRASE}', parent=win)
            return
        if not (do_owner.get() or do_tray.get() or do_lock.get()):
            messagebox.showerror('未选择', '请至少勾选一项要处理的内容。', parent=win)
            return

        lines: list[str] = []
        if do_tray.get():
            ok, msg = clear_tray_startup_exit_password()
            if not ok:
                messagebox.showerror('失败', msg, parent=win)
                return
            lines.append(msg)
        if do_lock.get():
            ok, msg = clear_operation_lock_pin_local()
            if not ok:
                messagebox.showerror('失败', msg, parent=win)
                return
            lines.append(msg)
        if do_owner.get():
            if pwd_var.get() != pwd2_var.get():
                messagebox.showerror('失败', '两次输入的新密码不一致。', parent=win)
                return
            ok, msg = reset_owner_login_password(owner_var.get(), pwd_var.get())
            if not ok:
                messagebox.showerror('失败', msg, parent=win)
                return
            lines.append(msg)

        messagebox.showinfo('完成', '\n'.join(lines), parent=win)
        win.destroy()

    ttk.Button(win, text='执行重置', command=on_run).pack(pady=12)
    ttk.Button(win, text='取消', command=win.destroy).pack()

    win.mainloop()


if __name__ == '__main__':
    main()
