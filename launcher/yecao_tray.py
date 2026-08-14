# 野草 V1 托盘主程序：启停服务、控制台窗口、可选启动/退出密码

from __future__ import annotations

import sys
import threading
import webbrowser

from PIL import Image, ImageDraw

from .tray_backup_helpers import (
    backup_to_chosen_folder,
    mark_tray_startup_running,
    prepare_database_for_startup,
    start_post_startup_backup_health_thread,
    start_scheduled_backup_thread,
)
from .tray_config_helpers import (
    apply_detected_lan_from_tray,
    fetch_launcher_config,
    project_root,
)
from .tray_password_helpers import (
    apply_tray_password_settings,
    exit_password_required,
    load_tray_password_settings,
    password_is_configured,
    startup_password_required,
    verify_tray_password,
)
from .tray_port_helpers import (
    describe_port_listeners,
    protect_pids_for_owned_server,
    stop_runserver_pids,
)
from .tray_server_helpers import TrayServerProcess
from .tray_single_instance_helpers import (
    InstallSingleInstanceLock,
    consume_show_window_request,
    request_show_existing_window,
)

try:
    import pystray
except ImportError:  # pragma: no cover - 运行环境缺依赖时给出白话提示
    pystray = None


def _log_tray_fatal(message: str) -> None:
    """pythonw 无控制台时，把致命错误写入日志文件。"""
    try:
        log_path = project_root() / 'launcher' / 'tray_startup_error.log'
        log_path.write_text(message.strip() + '\n', encoding='utf-8')
    except OSError:
        pass


def _show_fatal_error(message: str) -> None:
    """尽量用弹窗告知；失败则写日志。"""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        messagebox.showerror('野草托盘', message, parent=root)
        root.destroy()
    except Exception:
        _log_tray_fatal(message)


def _show_already_running() -> None:
    """第二实例：白话提示已在运行。"""
    msg = (
        '野草已经在运行。\n\n'
        '请看电脑右下角托盘里的野草图标；\n'
        '可右击选择「显示状态窗口」或「退出野草」。'
    )
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        messagebox.showinfo('野草托盘', msg, parent=root)
        root.destroy()
    except Exception:
        _log_tray_fatal(msg)


def _build_icon_image() -> Image.Image:
    """生成简单绿色圆形托盘图标（无需额外图片文件）。"""
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=(76, 175, 80, 255))
    draw.text((22, 18), '野', fill=(255, 255, 255, 255))
    return img


def _prompt_password(title: str, prompt: str, parent=None) -> str | None:
    """询问密码；有父窗口时挂在父窗口下，避免再开第二个根窗口。"""
    import tkinter as tk
    from tkinter import simpledialog

    own = parent is None
    if own:
        parent = tk.Tk()
        parent.withdraw()
        parent.attributes('-topmost', True)
    value = simpledialog.askstring(title, prompt, show='*', parent=parent)
    if own:
        parent.destroy()
    return value


class YecaoTrayApp:
    def __init__(self) -> None:
        self.root_dir = project_root()
        self.server = TrayServerProcess(self.root_dir)
        self.config = fetch_launcher_config(self.root_dir)
        self.icon: pystray.Icon | None = None
        self.status_window = None
        self._status_label = None
        self._pwd_status_label = None
        self._pwd_startup_var = None
        self._pwd_exit_var = None
        self._pwd_old_entry = None
        self._pwd_new_entry = None
        self._lan_saved_label = None
        self._lan_detected_label = None
        self._lan_match_label = None
        self._lan_hint_label = None
        self._stopping = False
        self._backup_stop = threading.Event()
        self._instance_lock = InstallSingleInstanceLock(self.root_dir)
        self._show_watch_stop = threading.Event()

    def _set_status_text(self, text: str) -> None:
        if self._status_label is not None:
            self._status_label.config(text=text)

    def _ui(self, fn) -> None:
        """把界面动作丢回状态窗口主线程（托盘线程里点菜单时用）。"""
        win = self.status_window
        if win is not None:
            try:
                win.after(0, fn)
                return
            except Exception:
                pass
        fn()

    def _password_summary_text(self) -> str:
        settings = load_tray_password_settings()
        if not password_is_configured(settings):
            return '当前：启动/退出密码未开启'
        parts = []
        if settings.get('startup_password_enabled'):
            parts.append('启动要密码')
        if settings.get('exit_password_enabled'):
            parts.append('退出要密码')
        if not parts:
            return '当前：已存密码，但启动/退出都未勾选（等于未启用）'
        return '当前：' + '、'.join(parts)

    def _refresh_password_panel(self) -> None:
        settings = load_tray_password_settings()
        if self._pwd_status_label is not None:
            self._pwd_status_label.config(text=self._password_summary_text())
        if self._pwd_startup_var is not None:
            self._pwd_startup_var.set(bool(settings.get('startup_password_enabled')))
        if self._pwd_exit_var is not None:
            self._pwd_exit_var.set(bool(settings.get('exit_password_enabled')))
        if self._pwd_old_entry is not None:
            self._pwd_old_entry.delete(0, 'end')
        if self._pwd_new_entry is not None:
            self._pwd_new_entry.delete(0, 'end')

    def _ensure_status_window(self):
        import tkinter as tk
        from tkinter import messagebox, ttk

        if self.status_window is not None:
            return self.status_window

        win = tk.Tk()
        win.title('野草系统 · 本地营业控制台')
        win.geometry('560x760')
        win.minsize(480, 620)
        win.protocol('WM_DELETE_WINDOW', self.hide_status_window)

        outer = ttk.Frame(win, padding=16)
        outer.pack(fill='both', expand=True)

        ttk.Label(
            outer,
            text='野草本地营业控制台',
            font=('Microsoft YaHei UI', 14, 'bold'),
        ).pack(anchor='w')
        ttk.Label(
            outer,
            text='关闭本窗口 = 最小化到托盘（营业不中断）。完全退出请点下方「退出野草」。',
            wraplength=500,
        ).pack(anchor='w', pady=(4, 10))

        status_box = ttk.LabelFrame(outer, text='当前状态', padding=10)
        status_box.pack(fill='x', pady=(0, 10))
        self._status_label = ttk.Label(status_box, text='正在启动…', wraplength=500)
        self._status_label.pack(anchor='w')

        lan_box = ttk.LabelFrame(outer, text='店内地址（手机/桌码用）', padding=10)
        lan_box.pack(fill='x', pady=(0, 10))
        self._lan_saved_label = ttk.Label(lan_box, text='已保存：—', wraplength=500)
        self._lan_saved_label.pack(anchor='w')
        self._lan_detected_label = ttk.Label(lan_box, text='当前探测：—', wraplength=500)
        self._lan_detected_label.pack(anchor='w', pady=(2, 0))
        self._lan_match_label = ttk.Label(lan_box, text='是否一致：—', wraplength=500)
        self._lan_match_label.pack(anchor='w', pady=(2, 0))
        self._lan_hint_label = ttk.Label(lan_box, text='', wraplength=500)
        self._lan_hint_label.pack(anchor='w', pady=(2, 6))
        lan_row1 = ttk.Frame(lan_box)
        lan_row1.pack(fill='x', pady=2)
        ttk.Button(lan_row1, text='复制店内地址', command=self.copy_lan_address).pack(
            side='left', padx=(0, 8),
        )
        ttk.Button(lan_row1, text='用店内地址打开', command=self.open_lan_browser).pack(
            side='left', padx=(0, 8),
        )
        lan_row2 = ttk.Frame(lan_box)
        lan_row2.pack(fill='x', pady=2)
        ttk.Button(lan_row2, text='检测当前 IP', command=self.detect_lan).pack(
            side='left', padx=(0, 8),
        )
        ttk.Button(lan_row2, text='一键更新为当前', command=self.apply_detected_lan).pack(
            side='left',
        )

        action_box = ttk.LabelFrame(outer, text='常用操作', padding=10)
        action_box.pack(fill='x', pady=(0, 10))
        row1 = ttk.Frame(action_box)
        row1.pack(fill='x', pady=2)
        ttk.Button(row1, text='本机打开后台', command=self.open_browser).pack(
            side='left', padx=(0, 8),
        )
        ttk.Button(row1, text='检查端口占用', command=self.check_port_usage).pack(
            side='left', padx=(0, 8),
        )
        ttk.Button(row1, text='立刻备份到所选文件夹', command=self.backup_now_to_folder).pack(
            side='left',
        )
        row2 = ttk.Frame(action_box)
        row2.pack(fill='x', pady=(8, 0))
        ttk.Button(row2, text='隐藏到托盘', command=self.hide_status_window).pack(
            side='left', padx=(0, 8),
        )
        ttk.Button(row2, text='退出野草', command=self.quit_app).pack(side='left')

        pwd_box = ttk.LabelFrame(outer, text='启动 / 退出密码（可选）', padding=10)
        pwd_box.pack(fill='both', expand=True, pady=(0, 4))
        self._pwd_status_label = ttk.Label(pwd_box, text=self._password_summary_text(), wraplength=500)
        self._pwd_status_label.pack(anchor='w', pady=(0, 6))
        ttk.Label(
            pwd_box,
            text='最小化到托盘不需要密码。启动、退出都不勾选并保存 = 关闭密码。',
            wraplength=500,
        ).pack(anchor='w', pady=(0, 6))

        self._pwd_startup_var = tk.BooleanVar(value=False)
        self._pwd_exit_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            pwd_box, text='启动野草时要求密码', variable=self._pwd_startup_var,
        ).pack(anchor='w')
        ttk.Checkbutton(
            pwd_box, text='完全退出时要求密码', variable=self._pwd_exit_var,
        ).pack(anchor='w', pady=(0, 6))

        ttk.Label(pwd_box, text='当前密码（已开启时修改须填写）').pack(anchor='w')
        self._pwd_old_entry = ttk.Entry(pwd_box, show='*', width=36)
        self._pwd_old_entry.pack(anchor='w', pady=(0, 4))
        ttk.Label(pwd_box, text='新密码（至少 6 位；只改开关可留空）').pack(anchor='w')
        self._pwd_new_entry = ttk.Entry(pwd_box, show='*', width=36)
        self._pwd_new_entry.pack(anchor='w', pady=(0, 8))
        ttk.Button(pwd_box, text='保存密码设置', command=self._save_password_settings).pack(
            anchor='w',
        )

        self._refresh_password_panel()
        self._refresh_lan_panel()
        self.status_window = win
        return win

    def _save_password_settings(self) -> None:
        from tkinter import messagebox

        parent = self.status_window
        ok, msg = apply_tray_password_settings(
            startup_enabled=bool(self._pwd_startup_var.get()) if self._pwd_startup_var else False,
            exit_enabled=bool(self._pwd_exit_var.get()) if self._pwd_exit_var else False,
            new_password=self._pwd_new_entry.get() if self._pwd_new_entry else '',
            old_password=self._pwd_old_entry.get() if self._pwd_old_entry else '',
        )
        if ok:
            messagebox.showinfo('已保存', msg, parent=parent)
            self._refresh_password_panel()
            self._set_status_text(msg)
        else:
            messagebox.showerror('未保存', msg, parent=parent)

    def show_status_window(self, _icon=None, _item=None) -> None:
        def _show() -> None:
            win = self._ensure_status_window()
            win.deiconify()
            win.lift()
            try:
                win.focus_force()
            except Exception:
                pass

        self._ui(_show)

    def hide_status_window(self) -> None:
        if self.status_window is not None:
            self.status_window.withdraw()
        if self.icon is not None:
            self.icon.notify('已最小化到托盘', '野草仍在后台营业')

    def _refresh_lan_panel(self) -> None:
        cfg = self.config or {}
        saved = (cfg.get('lan_base_url') or '').strip() or '（还没有保存）'
        detected = (cfg.get('detected_lan') or '').strip()
        if cfg.get('detect_failed') or not detected:
            detected = '（测不到）'
        if cfg.get('detect_failed'):
            match_text = '是否一致：测不到，无法对比'
            match_color = '#b8860b'
        elif cfg.get('match'):
            match_text = '是否一致：一致'
            match_color = '#2e7d32'
        else:
            match_text = '是否一致：不一致'
            match_color = '#b8860b'
        hint = (cfg.get('lan_message') or '').strip()
        if self._lan_saved_label is not None:
            self._lan_saved_label.config(text='已保存：' + saved)
        if self._lan_detected_label is not None:
            self._lan_detected_label.config(text='当前探测：' + detected)
        if self._lan_match_label is not None:
            self._lan_match_label.config(text=match_text, foreground=match_color)
        if self._lan_hint_label is not None:
            self._lan_hint_label.config(text=hint)

    def _notify_lan_mismatch_if_needed(self) -> None:
        cfg = self.config or {}
        if cfg.get('match') or cfg.get('detect_failed'):
            return
        msg = (cfg.get('lan_message') or '店内地址与当前探测不一致').strip()
        self._set_status_text(msg)
        if self.icon is not None:
            try:
                self.icon.notify(msg, '野草')
            except Exception:
                pass

    def open_browser(self, _icon=None, _item=None) -> None:
        def _open() -> None:
            self.config = fetch_launcher_config(self.root_dir)
            self._refresh_lan_panel()
            webbrowser.open(
                self.config.get('open_url') or 'http://127.0.0.1:8000/accounts/login/',
            )
            self._set_status_text('已用本机地址打开后台')

        self._ui(_open)

    def open_lan_browser(self, _icon=None, _item=None) -> None:
        def _open() -> None:
            from tkinter import messagebox

            self.config = fetch_launcher_config(self.root_dir)
            self._refresh_lan_panel()
            lan = (self.config.get('lan_base_url') or '').strip()
            parent = self._ensure_status_window()
            if not lan:
                messagebox.showinfo(
                    '店内地址',
                    '还没有保存店内地址。请先检测并一键更新，或到堂食营业里填写。',
                    parent=parent,
                )
                return
            webbrowser.open(lan.rstrip('/') + '/accounts/login/')
            self._set_status_text('已用店内地址打开（请在同一店内网试）')

        self._ui(_open)

    def copy_lan_address(self, _icon=None, _item=None) -> None:
        def _copy() -> None:
            from tkinter import messagebox

            self.config = fetch_launcher_config(self.root_dir)
            self._refresh_lan_panel()
            lan = (self.config.get('lan_base_url') or '').strip()
            parent = self._ensure_status_window()
            if not lan:
                messagebox.showinfo('店内地址', '还没有可复制的店内地址。', parent=parent)
                return
            parent.clipboard_clear()
            parent.clipboard_append(lan)
            self._set_status_text('已复制店内地址')

        self._ui(_copy)

    def detect_lan(self, _icon=None, _item=None) -> None:
        def _run() -> None:
            self._set_status_text('正在检测当前店内号…')
            self.config = fetch_launcher_config(self.root_dir)
            self._refresh_lan_panel()
            self._set_status_text(self.config.get('lan_message') or '检测完成')

        self._ui(_run)

    def apply_detected_lan(self, _icon=None, _item=None) -> None:
        def _run() -> None:
            from tkinter import messagebox

            parent = self._ensure_status_window()
            self.config = fetch_launcher_config(self.root_dir)
            self._refresh_lan_panel()
            detected = (self.config.get('detected_lan') or '').strip()
            if self.config.get('detect_failed') or not detected:
                messagebox.showinfo(
                    '无法一键更新',
                    self.config.get('lan_message')
                    or '测不到当前号，未改已保存的店内地址。',
                    parent=parent,
                )
                return
            saved = (self.config.get('lan_base_url') or '').strip() or '（空）'
            ask = messagebox.askyesno(
                '确认更新店内地址',
                '将把店内地址改成当前探测结果。\n\n'
                f'已保存：{saved}\n'
                f'当前探测：{detected}\n\n'
                '不会偷偷改。若桌上贴的码还是旧号，更新后请重打。\n'
                '确定要更新吗？',
                parent=parent,
            )
            if not ask:
                return
            self._set_status_text('正在更新店内地址…')
            result = apply_detected_lan_from_tray(self.root_dir)
            self.config = fetch_launcher_config(self.root_dir)
            self._refresh_lan_panel()
            msg = (result.get('message') or result.get('lan_message') or '').strip()
            if result.get('ok') is False:
                messagebox.showerror('未更新', msg or '更新失败。', parent=parent)
                self._set_status_text(msg or '未更新店内地址')
            else:
                messagebox.showinfo('已更新', msg or '店内地址已更新。', parent=parent)
                self._set_status_text(msg or '店内地址已更新')

        self._ui(_run)

    def check_port_usage(self, _icon=None, _item=None) -> None:
        """查看端口占用，并可结束「其它」本项目 runserver（不杀当前自己的）。"""

        def _run() -> None:
            from tkinter import messagebox

            parent = self._ensure_status_window()
            self.config = fetch_launcher_config(self.root_dir)
            port = int(self.server.port or self.config.get('listen_port') or 8000)
            protect = protect_pids_for_owned_server(
                self.server.child_pid if self.server.running else None,
            )
            summary, killable_pids = describe_port_listeners(
                port, self.root_dir, protect_pids=protect,
            )
            if killable_pids:
                ask = messagebox.askyesno(
                    '检查端口占用',
                    summary
                    + '\n\n是否结束这些「其它」野草 runserver 进程？\n'
                    + '（当前托盘正在用的服务不会动；其它程序也不会动）',
                    parent=parent,
                )
                if ask:
                    _, result = stop_runserver_pids(killable_pids)
                    self._set_status_text(result)
                    messagebox.showinfo('端口清理', result, parent=parent)
            else:
                messagebox.showinfo('检查端口占用', summary, parent=parent)
                self._set_status_text(summary.splitlines()[0] if summary else '端口检查完成')

        self._ui(_run)

    def backup_now_to_folder(self, _icon=None, _item=None) -> None:
        def _run() -> None:
            parent = self._ensure_status_window()
            self._set_status_text('正在备份…')
            backup_to_chosen_folder(self.root_dir, parent=parent)
            self._set_status_text('备份操作已结束（详见弹窗说明）')

        self._ui(_run)

    def start_server(self) -> None:
        ok, msg = self.server.start()
        self._set_status_text(msg)
        if ok:
            mark_tray_startup_running(self.root_dir)
            start_scheduled_backup_thread(
                self.root_dir, self._backup_stop, icon=self.icon,
            )
            start_post_startup_backup_health_thread(
                self.root_dir, self._backup_stop, icon=self.icon,
            )
            self.open_browser()

    def quit_app(self, _icon=None, _item=None) -> None:
        def _run() -> None:
            if self._stopping:
                return
            parent = self.status_window
            if exit_password_required():
                plain = _prompt_password('退出野草', '请输入退出密码：', parent=parent)
                if plain is None:
                    return
                if not verify_tray_password(plain):
                    if self.icon is not None:
                        self.icon.notify('退出密码不正确', '野草')
                    self._set_status_text('退出密码不正确')
                    return
            self._stopping = True
            self._backup_stop.set()
            self._set_status_text('正在退出备份…')
            ok, msg = self.server.run_exit_backup()
            if self.icon is not None:
                self.icon.notify(msg, '退出备份')
            self.server.stop()
            if self.status_window is not None:
                try:
                    self.status_window.destroy()
                except Exception:
                    pass
                self.status_window = None
            if self.icon is not None:
                self.icon.stop()

        self._ui(_run)

    def _build_menu(self) -> pystray.Menu:
        # 右键：状态窗口 + 直接退出（不必先开窗口）
        return pystray.Menu(
            pystray.MenuItem('显示状态窗口', self.show_status_window, default=True),
            pystray.MenuItem('退出野草', self.quit_app),
        )

    def _start_show_window_watcher(self) -> None:
        """监听第二实例发来的「请显示状态窗口」标记。"""

        def _loop() -> None:
            while not self._show_watch_stop.wait(0.8):
                if not consume_show_window_request(self.root_dir):
                    continue
                self._ui(self.show_status_window)
                icon = self.icon
                if icon is not None:
                    try:
                        icon.notify('请使用当前托盘', '野草已在运行')
                    except Exception:
                        pass

        threading.Thread(target=_loop, daemon=True, name='yecao-tray-show-watch').start()

    def run(self) -> None:
        # 同一安装目录禁止多开；第二实例只提示并请求亮起已有窗口
        if not self._instance_lock.try_acquire():
            request_show_existing_window(self.root_dir)
            _show_already_running()
            return
        try:
            self._run_locked()
        finally:
            self._show_watch_stop.set()
            self._instance_lock.release()

    def _run_locked(self) -> None:
        if startup_password_required():
            plain = _prompt_password('启动野草', '请输入启动密码：')
            if plain is None or not verify_tray_password(plain):
                return
        can_start, prep_msg = prepare_database_for_startup(self.root_dir)
        if not can_start:
            self._ensure_status_window()
            self._set_status_text(prep_msg or '已取消启动')
            self.show_status_window()
            assert self.status_window is not None
            self.status_window.mainloop()
            return
        ok, msg = self.server.start()
        self._ensure_status_window()
        self._set_status_text(prep_msg if prep_msg and ok else msg)
        if ok:
            mark_tray_startup_running(self.root_dir)

        image = _build_icon_image()
        self.icon = pystray.Icon(
            'yecao_tray',
            image,
            '野草系统',
            menu=self._build_menu(),
        )
        if ok:
            start_scheduled_backup_thread(
                self.root_dir, self._backup_stop, icon=self.icon,
            )
            start_post_startup_backup_health_thread(
                self.root_dir, self._backup_stop, icon=self.icon,
            )

        def _run_tray() -> None:
            assert self.icon is not None
            self.icon.run()

        threading.Thread(target=_run_tray, daemon=True).start()
        self._start_show_window_watcher()

        if ok:
            self.open_browser()
            self._notify_lan_mismatch_if_needed()
            # 首次启动先藏到托盘；需要时右键/左键打开控制台
            self.status_window.withdraw()
        else:
            self.show_status_window()

        assert self.status_window is not None
        self.status_window.mainloop()


def main() -> None:
    if pystray is None:
        _show_fatal_error('缺少 pystray，请先在项目虚拟环境执行：pip install pystray')
        sys.exit(1)
    if sys.platform != 'win32':
        _show_fatal_error('V1 托盘当前仅支持 Windows。')
        sys.exit(1)
    YecaoTrayApp().run()


if __name__ == '__main__':
    main()
