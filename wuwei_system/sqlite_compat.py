"""
SQLite 与 Django 5.2 的兼容处理（面向所有部署者）。

规则：
1. 先检测当前 sqlite3 版本是否达到 Django 要求（3.31+）；
2. 够用 → 什么也不改，继续用系统自带；
3. 不够 → 若已安装可选包 pysqlite3，则改用该包；
4. 仍不够或未安装 → 退出并给出白话说明（指向可选依赖文件与文档）。
"""

from __future__ import annotations

# Django 5.2 官方要求：SQLite 3.31 或更高
_MIN_SQLITE = (3, 31, 0)


def _version_tuple(mod) -> tuple[int, int, int]:
    info = getattr(mod, 'sqlite_version_info', None)
    if info and len(info) >= 3:
        return int(info[0]), int(info[1]), int(info[2])
    # 极少数实现只有字符串版本
    parts = [int(p) for p in str(getattr(mod, 'sqlite_version', '0.0.0')).split('.')[:3]]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def _fail_too_old(current: tuple[int, int, int]) -> None:
    cur = '.'.join(str(x) for x in current)
    need = '.'.join(str(x) for x in _MIN_SQLITE)
    raise SystemExit(
        '\n'
        '【野草 · 数据库小工具版本不够】\n'
        f'当前 SQLite 版本：{cur}\n'
        f'Django 5.2 需要：{need} 或更高。\n'
        '\n'
        '这在部分云服务器（例如较旧的系统自带库）上很常见，不是业务代码写坏了。\n'
        '\n'
        '标准处理（所有部署者同一套）：\n'
        '  1. 仍在项目虚拟环境中，执行：\n'
        '       pip install -r requirements-sqlite-compat.txt\n'
        '  2. 再重新执行刚才的命令（如 migrate / runserver / 启动 gunicorn）。\n'
        '\n'
        '说明文档：docs/环境与依赖清单.md（章节「SQLite 版本」）。\n'
        '兼容包许可与来源：docs/THIRD_PARTY_LICENSES.md。\n'
    )


def ensure_sqlite_compatible() -> str:
    """
    在导入 Django 数据库模块之前调用。

    返回值（供排查）：
    - system：系统自带已够用
    - pysqlite3：已切换到可选兼容包
    """
    import sqlite3

    current = _version_tuple(sqlite3)
    if current >= _MIN_SQLITE:
        return 'system'

    try:
        import pysqlite3  # type: ignore
    except ImportError:
        _fail_too_old(current)

    import sys

    sys.modules['sqlite3'] = pysqlite3
    switched = _version_tuple(pysqlite3)
    if switched < _MIN_SQLITE:
        _fail_too_old(switched)
    return 'pysqlite3'
