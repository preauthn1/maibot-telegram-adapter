# Telegram capability port

Reference: KumaTea/MaiBot-Telegram-Full revision 58799cd356ad69f2b3b3cfb2e04c0ea5c59489fb.

Includes event edits/deletion journal, history-only recent catch-up, rich-text entities, source/context presentation, scoped media/sticker references, Bot session separation, buttons, scoped read tools, and opt-in Telegraph Markdown publication. Existing policy/confirmed-receipt/manual-history prerequisites are included.

Validation so far used bounded offline fixtures and mock transports; this publication is not a live deployment or a claim of complete upstream parity. Recent catch-up is capped and disabled by default; Bot history fetching is unsupported. Arbitrary MTProto writes, full archive recovery, sticker vision recognition and full album fidelity are not provided. Live Telegram/Host integration and Telegraph normalization remain unverified.

No production configuration, account sessions, transcripts or deployment-specific appeal automation are included.
