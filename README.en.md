# YecaoST (Wild Grass System)

A decentralized local dining / delivery web system. Phase 1 focuses on a **single shop**: dine-in first, delivery second. Each shop manages its own menu, orders, waiter / kitchen / rider workbench, and payment settings.

Chinese documentation is the source of truth. Start with [README.md](README.md) and `docs/`.

**Live site (trial)**: **[https://yichbo.com/](https://yichbo.com/)** — server home. Legacy `/directory/` redirects to `/`.

## Quick start (local development only)

```text
.\.venv\Scripts\python.exe manage.py runserver
```

Open `http://127.0.0.1:8000/` on your machine (**local dev only**). Public visitors use **yichbo.com** above.

See `docs/环境与依赖清单.md` for dependencies and `docs/用户使用说明书.md` for end-user guidance (Chinese).

## Current stage (summary · 2026-07-23)

| Area | Status |
|------|--------|
| Single-shop core | Runnable locally; dine-in, workbench, channels, payment foundation in place |
| Showcase home (A.10) | Server home at `/` and shop home at `/s/<code>/home/`; in-page block expand/collapse |
| Plugins (trial) | Dining / fulfillment split in progress; core fallback when plugins off |
| Production trial | Live at **[yichbo.com](https://yichbo.com/)** (HTTPS); ICP / police filing via admin; WeChat Native pay tested |
| Before public launch | Refunds, privacy encryption, production audit — **not done yet** |
| Next (rules set, code pending) | Batch G: product images → pickup time → unified buyer messaging; install/relay packages (46–48) |

Process docs (progress / logs) are kept privately by the project owner and are **not** in this public repo.

## License (summary)

- **Main program**: **AGPL-3.0** (`LICENSE`).  
- **Plugins**: additional permission in `LICENSE.PLUGIN-EXCEPTION` (plugins need not be AGPL).  
- **Voluntary certification list**: `CERTIFIED_DIRECTORY.md` (not part of the AGPL text).  
- Chinese rules: handbook sections **A.14**, **A.15** (architecture target; full code split not complete).
