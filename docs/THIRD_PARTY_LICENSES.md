# 野草系统 · 第三方依赖许可表

> **最后更新**：2026-07-14  
> **主程序许可**：AGPL-3.0（见仓库根目录 `LICENSE`）  
> **关系原则**：第三方包**只通过包管理安装并调用**，不混进主程序源码冒充自有代码。  
> **版本以** `requirements.txt` **为准**；本表记许可与来源。新增依赖须同步本表与 `docs/环境与依赖清单.md`。

---

## Python 包（直接依赖）

| 包 | 用途 | 许可（元数据/常见标识） | 可信来源 | 备注 |
|----|------|-------------------------|----------|------|
| Django | 网页框架 | BSD-3-Clause | https://pypi.org/project/Django/ | 随 Django 生态 |
| asgiref | Django 支撑 | BSD-3-Clause | https://pypi.org/project/asgiref/ | |
| sqlparse | SQL 解析 | BSD（OSI 标注） | https://pypi.org/project/sqlparse/ | |
| tzdata | 时区数据 | Apache-2.0 | https://pypi.org/project/tzdata/ | |
| qrcode | 二维码 | BSD | https://pypi.org/project/qrcode/ | 含 `[pil]` 额外时拉 Pillow |
| Pillow | 图像 | MIT-CMU | https://pypi.org/project/Pillow/ | |
| fpdf2 | 桌贴 PDF | **LGPL-3.0** | https://pypi.org/project/fpdf2/ | **慎用档**：仅作库调用；保留对方许可义务；长期可评估替换为更宽松许可方案 |
| pysqlite3-binary（可选） | 旧系统 SQLite 过低时的兼容 | zlib / 见 PyPI | https://pypi.org/project/pysqlite3-binary/ | **仅当检测不足时安装**：`pip install -r requirements-sqlite-compat.txt`；见环境清单「SQLite 版本」 |

间接依赖（随上述包装入）未逐条展开；升级大版本前应再核许可。

---

## 非 pip、但相关的外部

| 项 | 说明 | 许可/规则 |
|----|------|-----------|
| Python 运行时 | 系统/官方安装 | PSF 等（随发行版） |
| 操作系统 / Nginx 等 | 部署环境自备 | 各发行版自有 |
| 微信支付接口 | 商户平台规则 | **非**开源依赖；遵守微信商户协议与密钥安全 |

---

## 准入摘要（与手册 A.14.3 一致）

1. 默认只从 **PyPI / 官方发布**引入。  
2. **优选** MIT、BSD、Apache-2.0 等宽松许可。  
3. **LGPL** 等须登记本表；以调用方式使用，不把对方源码洗成「野草 MIT/自有」。  
4. 主程序对外称 **AGPL**；第三方许可**分列**本表，避免对外只说「整仓一种许可」却漏记依赖。
