# YecaoST (Wild Grass System)

A decentralized local dining / delivery web system. Phase 1 focuses on a **single shop**: dine-in first, delivery second. Each shop manages its own menu, orders, waiter / kitchen / rider workbench, and payment settings.

**Chinese documentation is the source of truth.** Start with [README.md](README.md) and `docs/`.

## Project home (start here)

**Live trial site: <https://yichbo.com/>**

- Product introduction and the public trial entry point live on that site.  
- Legacy `/directory/` redirects to the home page.  
- This repository holds the open-source program and public docs. Process notes (progress / logs) are kept privately by the project owner.

## What it does (short)

- Guests order and pay in a mobile browser (cash / merchant WeChat / demo pay, depending on shop settings).  
- The shop owner manages menu, tables, staff, payments, and orders in a web admin.  
- Waiters / kitchen / riders use the shop **workbench**.  
- Money goes to the **shop’s own** merchant account; YecaoST does not take a cut.

The project is also delivering **Local Shop Runtime V1** (Windows PC in the shop, tray app, LAN). See Chinese docs: `docs/V1本地营业内测版.md` and `docs/V1本地营业用户说明书.md`.

## Quick start (local development only)

> For developers. Visitors should open **yichbo.com**.  
> If you installed the **V1 Windows package**, follow the Chinese V1 user guide — do **not** use `runserver` below.

```text
.\.venv\Scripts\python.exe manage.py runserver
```

Open `http://127.0.0.1:8000/` on your machine (**local debug only**). Public visitors use **<https://yichbo.com/>**.

See `docs/环境与依赖清单.md` for dependencies.

## Current stage (summary · 2026-08-09)

| Area | Status |
|------|--------|
| Public home | Live at **[yichbo.com](https://yichbo.com/)** (HTTPS) |
| Single-shop core | Runnable; dine-in, workbench, payment foundation in place |
| Local Shop Runtime V1 | Tray / backup / setup wizard / local password reset landed; Inno installer finishing |
| WeChat pay / minimal refund | Available on local builds; validate with real devices before relying on it |
| Before wider public launch | Remaining audit / safety items — follow Chinese handbook and deploy docs |

## License (summary)

- **Main program**: **AGPL-3.0** (`LICENSE`).  
- **Plugins**: additional permission in `LICENSE.PLUGIN-EXCEPTION` (plugins need not be AGPL).  
- **Voluntary certification list**: `CERTIFIED_DIRECTORY.md` (repo canonical copy; not part of the AGPL text).  
- Chinese product rules: handbook sections **A.14**, **A.15**.
