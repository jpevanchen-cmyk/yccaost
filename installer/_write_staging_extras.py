# -*- coding: utf-8 -*-
"""由 prepare_dist.ps1 调用：写入安装包专用文件、裁剪不进包文档，并核对忘记密码脚本。"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

try:
    from django.core.management.utils import get_random_secret_key
except Exception:
    import secrets

    def get_random_secret_key() -> str:  # type: ignore[misc]
        chars = "abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)"
        return "".join(secrets.choice(chars) for _ in range(50))


# docs 里保留给店家 / 合规；其余删掉
DOCS_KEEP = {
    "V1本地营业用户说明书.md",
    "V1本地营业内测版.md",
    "V1版本迭代说明.md",
    "卖家微信支付开通指南.md",
    "THIRD_PARTY_LICENSES.md",
    "新手引导流程.md",  # 卖家引导正本；安装包可带，界面是否露出由 V1 开关决定
}

# 根上若仍误拷入则再删一遍
ROOT_REMOVE = {
    "CERTIFIED_DIRECTORY.md",
    "private",
    "scripts",
    "tools",
    "owner_toolkit",
    "owner_toolkit.zip",
    "cursor聊天记录.md",
    "_restore_cursor_chats.py",
    "_恢复旧聊天窗口.bat",
    "规则模板-developer-profile.mdc",
    "服务器启动命令以及网址等.txt",
    "野草系统-正式上线前清查备忘录.md",
    "无为系统-核心规则速查手册.md",
    "_qr_fixed.pdf",
    "新建文本文档.txt",
    ".gitignore",
    ".gitattributes",
    ".env.example",
    "野草系统-核心规则速查手册.md",
    "野草系统-数据安全与隐私说明.md",
    "野草系统-品牌标识说明.md",
    "野草数据安全·白话总览.md",
}


def _prune_docs(app: Path) -> None:
    docs = app / "docs"
    if not docs.is_dir():
        return
    for p in list(docs.iterdir()):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            continue
        if p.name not in DOCS_KEEP:
            p.unlink(missing_ok=True)


def _prune_root_extras(app: Path) -> None:
    for name in ROOT_REMOVE:
        p = app / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)
    # 开发机托盘密码绝不能进安装包
    tray_settings = app / 'launcher' / 'tray_local_settings.json'
    if tray_settings.is_file():
        tray_settings.unlink(missing_ok=True)


def _assert_must_have(app: Path) -> None:
    must = [
        "启动野草.bat",
        "首次准备数据库.bat",
        "本机忘记密码重置.bat",
        "使用说明.txt",
        ".env",
        "manage.py",
        "requirements.txt",
        "README.md",
        "LICENSE",
        "LICENSE.PLUGIN-EXCEPTION",
        "docs/V1本地营业用户说明书.md",
        "docs/卖家微信支付开通指南.md",
        "waimai",
        "wuwei_system",
        "launcher",
        "templates",
        ".venv",
    ]
    missing = [m for m in must if not (app / m).exists()]
    if missing:
        raise SystemExit("发布目录缺少必需项: " + ", ".join(missing))

    forbidden = [
        "private",
        "scripts",
        "CERTIFIED_DIRECTORY.md",
        ".gitignore",
        ".gitattributes",
        ".env.example",
        "野草系统-核心规则速查手册.md",
        "野草系统-数据安全与隐私说明.md",
        "野草系统-品牌标识说明.md",
        "野草数据安全·白话总览.md",
        "docs/正式服务器与体验机分界.md",
        "docs/体验机与官方小店约定.md",
        "docs/用户使用说明书.md",
        "docs/服务器部署手册.md",
        "docs/开发方案.md",
        "launcher/tray_local_settings.json",
    ]
    present = [f for f in forbidden if (app / f).exists()]
    if present:
        raise SystemExit("发布目录仍含不应进包项: " + ", ".join(present))


def main() -> int:
    app = Path(os.environ.get("YECAO_STAGING_APP", "")).resolve()
    if not app.is_dir():
        print(f"发布目录无效: {app}", file=sys.stderr)
        return 1

    secret = get_random_secret_key()
    (app / ".env").write_text(
        "\n".join(
            [
                "# 野草本地营业 V1 · 安装包默认环境（可按店修改）",
                "YECAO_DEBUG=0",
                f"YECAO_SECRET_KEY={secret}",
                "YECAO_V1_INSTALL_PENDING=1",
                "YECAO_V1_LOCAL_MODE=1",
                "YECAO_ALLOWED_HOSTS=localhost,127.0.0.1",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (app / "启动野草.bat").write_text(
        "\r\n".join(
            [
                "@echo off",
                "chcp 65001 >nul",
                'cd /d "%~dp0"',
                "title 野草本地营业",
                'if not exist ".venv\\Scripts\\pythonw.exe" (',
                "  echo 找不到内嵌运行环境，请重新安装。",
                "  pause",
                "  exit /b 1",
                ")",
                'start "" ".venv\\Scripts\\pythonw.exe" -m launcher',
                "",
            ]
        ),
        encoding="utf-8",
    )

    (app / "首次准备数据库.bat").write_text(
        "\r\n".join(
            [
                "@echo off",
                "chcp 65001 >nul",
                'cd /d "%~dp0"',
                'if not exist ".venv\\Scripts\\python.exe" exit /b 1',
                '".venv\\Scripts\\python.exe" manage.py migrate --noinput',
                "exit /b %ERRORLEVEL%",
                "",
            ]
        ),
        encoding="utf-8",
    )

    reset_bat = app / "本机忘记密码重置.bat"
    if not reset_bat.is_file():
        print("发布目录缺少 本机忘记密码重置.bat", file=sys.stderr)
        return 1

    (app / "使用说明.txt").write_text(
        "\n".join(
            [
                "野草本地营业 · 使用说明（白话）",
                "当前安装包版本：1.01",
                "",
                "产品主页：https://yichbo.com/",
                "各版本增加了什么：请看安装目录 docs\\V1版本迭代说明.md",
                "",
                "一、日常怎么开",
                "1. 双击「启动野草」或开始菜单同名项",
                "2. 右下角会出现野草托盘图标",
                "3. 右键托盘 →「显示状态窗口」打开控制台",
                "4. 浏览器本机打开后台（一般会自动打开）",
                "",
                "二、第一次安装",
                "1. 安装程序会初始化空数据库",
                "2. 打开后按网页「首次向导」填写店名与老板账号",
                "3. 向导完成后即可营业",
                "",
                "三、更完整的说明书",
                "- 请打开安装目录 docs\\V1本地营业用户说明书.md",
                "- 各版本增加了什么：docs\\V1版本迭代说明.md",
                "- 开通微信收款：docs\\卖家微信支付开通指南.md",
                "",
                "四、备份",
                "- 自动备份在安装目录下的 backup 文件夹",
                "- 控制台里可「立刻备份到所选文件夹」（可拷 U 盘）",
                "",
                "五、忘记密码",
                "- 开始菜单或安装目录：「本机忘记密码重置」",
                "- 须在本机操作；确认词按窗口提示填写",
                "",
                "六、退出",
                "- 控制台点「退出野草」（会先备份再停）",
                "- 只关控制台窗口 = 最小化到托盘，营业不中断",
                "",
                "七、卸载",
                "- 卸载默认保留营业库与 backup 里的备份",
                "- 若要彻底删除，请手动删掉安装目录剩余文件",
                "",
            ]
        ),
        encoding="utf-8",
    )

    _prune_docs(app)
    _prune_root_extras(app)
    _assert_must_have(app)

    # 控制台编码可能是日文代码页，避免中文 print 把成功变成失败
    print("staging extras ok; docs pruned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
