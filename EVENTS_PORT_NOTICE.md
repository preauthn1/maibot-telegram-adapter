# Telegram events port — GPLv3

Upstream: KumaTea and contributors, MaiBot-Telegram-Full
https://github.com/KumaTea/MaiBot-Telegram-Full
Pinned source: 58799cd356ad69f2b3b3cfb2e04c0ea5c59489fb
Reference: tg_full/inbound/dispatcher.py (pending replacement/removal, typing TTL,
first-arrival hard deadline and shutdown). The upstream GPLv3 text is preserved in
upstream/LICENSE in the stage; target baseline LICENSE is retained unchanged.

Modified 2026-10-06 by Hermes on the user's behalf. New adapter EventDispatch and
EventBridge and host telegram_events are GPLv3 derivatives/adaptations. Existing
MaiBot copyright and author notices remain in force. This port replaces upstream
chat-only queue identity with chat/topic/message identity, retains current target
policy handling, and uses the target's history capability without dispatching old
messages to Planner. It does not import the upstream Telegram backend or store.

This is an isolated review artifact, not a production deployment.
