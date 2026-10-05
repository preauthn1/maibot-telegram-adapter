# Telegram fidelity port — licensing and provenance

Upstream: https://github.com/KumaTea/MaiBot-Telegram-Full
Fixed revision: 58799cd356ad69f2b3b3cfb2e04c0ea5c59489fb.
Original project credited to KumaTea and its contributors; preserve their copyright interests. The downloaded source has no more specific individual copyright statement; no invented legal-name attribution is made.

`fidelity/entities.py`, `fidelity/md_in.py`, `fidelity/md_out.py` are copied/adapted from upstream `tg_full/text/` at that revision. Their source headers identify the origin. `fidelity/formatting.py`, `provenance.py`, `native.py`, `animation.py`, `preview.py` and integration modifications are new adapter-specific work informed by upstream behavior, not attribution of the target's existing behavior policies to upstream.

Modified 2026-10-06 (+08): separate formatting capabilities from default policy; Telethon conversion and validation; UTF-16 splitting; same-chat expiring in-memory native refs; bounded subprocess design instead of upstream PyAV; strict preview DNS/redirect rules without fake-IP exemptions; preservation of confirmed-content receipts and sender filters.

GPL version 3 applies to this derivative port and target project. Full GPLv3 text is supplied in LICENSE. Retain this notice and source headers and provide Corresponding Source with redistribution. Original target files retain their existing notices and comments. This source port remains staged; ffmpeg was separately installed with operator authorization for a bounded offline conversion check. No production source files were changed by this port.
