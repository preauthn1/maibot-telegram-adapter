# Long-text Markdown isolated port

Modified 2026-10-06 by the Hermes-assisted port for the MaiBot deployment owner.
Reference: KumaTea (repository maintainer) and contributors,
https://github.com/KumaTea/MaiBot-Telegram-Full,
commit 58799cd356ad69f2b3b3cfb2e04c0ea5c59489fb.
Feature reference: tg_full/outbound/telegraph.py; local integrated fidelity/md_in.py
and fidelity/md_out.py retain their existing GPL-3.0-only attribution. New renderer
uses the same markdown-it-py parser family, not md_out's HTML-enabled parser.
New renderer and this combined adaptation are distributed under GPLv3; do not
assume the integrated notices' broad “or later” claim overrides upstream
GPL-3.0-only files. See SOURCE-LICENSE and existing PORT-NOTICES.md. Existing
contributors' copyright remains intact. No second Telegram client/session added.

## Patch scope / application

This directory is an overlay, not a runnable full MaiBot checkout. `longtext.patch`
is relative to the integration baseline; baseline hashes record the exact
read-only source inputs. Apply only after independent review and merge-conflict
checks. No integrated or production files were changed; no restart performed.

Files: public_pages.py, plugin.py, new fidelity/telegraph_nodes.py; dependency
patch pins markdown-it-py==4.0.0 in requirements.txt and pyproject.toml for stable
parser semantics. A future parser/rendering semantic change must bump the
`telegraph-markdown-v1` approval-domain version and require renewed approval.

## Public tool contract

`telegram_post_long_text(title, text, public_consent, format="plain")`
`telegram_edit_long_text(page, title, text, public_consent, format="plain")`
`telegram_list_long_text()` remains local, scoped, capped at 50 entries.
Format is exactly `plain` or `markdown`; runtime validation, not tool schema alone,
is authoritative. No implicit Markdown detection. The host still injects and
validates stream/chat context; public approval is never supplied by the model.

Administrator approval uses `publication_digest(scope, action, page, title, text,
format)` from the staged module and the existing protected
`approved-publications.json` file. Plain retains the historical five-field hash
and exact literal node semantics, including completed/pending intents. Markdown
hashes `["telegraph-markdown-v1", "markdown", scope, action, page, title, text]`.
Thus old plaintext approval cannot silently publish different HTML semantics.
Approval binds exact source text, not normalized/rendered text. Preview via
`render_nodes(text, format)` offline before approving. Never automatically approve.

## Supported safe subset and limits

Paragraphs, emphasis, strong, strike, inline/fenced/indented code, links, ordered
and unordered nested lists, block quotes, rules and hard breaks. Heading levels
1–3 map to Telegraph h3; 4–6 to h4. Ordered-list custom start numbers are not
preserved (Telegraph's allowed attributes do not support start). Tables and
Telegram spoiler/underline syntax are literal; this is not full CommonMark or
Telegram-entity parity. Raw HTML is literal text, never parsed into tags. Images
become alt text only; no src, iframe, video, external fetch or embed.

Links allow explicit HTTP(S), with hostname syntax validation and rejection of
userinfo, local/private/reserved IP literals, local hostname suffixes, protocol
relative URLs, controls, whitespace, backslashes and encoded controls. Only href
is emitted, never target/style/event handlers. No DNS resolution occurs: a public
hostname can resolve privately or redirect later; this is not an SSRF filter for
fetching (the renderer never fetches), nor a promise that destination content is
safe. Invalid links retain their label/literal source rather than an active href.

Limits: 32,000 UTF-8 source bytes; 4,096 parser tokens; 1,024 tree nodes including
strings; depth 16; serialized node JSON 48,000 bytes. Parser maxNesting=16 may
leave deeper source constructs literal; produced trees above budget fail closed.
No truncation or silent plaintext fallback on errors.

Public create/edit still commits pending before the external call, reads back the
exact path/title/node tree, and marks done only on equality. Readback mismatch or
transport failure stays pending; no blind retry. Markdown rejected before approval
or tree bounds produces no external publication. Conservative exact readback may
reject real-service normalization; live Telegraph behavior is NOT verified.

## Optional Telegram summary: source-only design, not implemented

Existing `_native_action` sends only the resulting URL through host `send.text`,
once on non-reused create, after publication readback. This already uses the
existing route/gateway and returns delivery separately. A future bounded summary
would replace that one URL text payload, never add a second direct Telethon send,
helper session, retry, or quota bypass. Summary content would require explicit
approval binding and disclosure of Telegram formatting; do not infer success from
Telegraph publication. No summary or new quota exemption ships in this patch.

## Verification / remaining dependencies

`verify_longtext.py` runs one interpreter with 15 CPU seconds, 384 MiB address-space
and 25-second alarm limits, temporary SQLite and mocked Telegraph. Socket connect
and DNS functions are blocked. It imports real staged leaf functions; tool wrapper
ASTs and schemas are extracted from actual plugin source without booting SDK.
No pytest, runtime plugin, production DB, token, Telegram or Telegraph network test.
See verification.json for the executed assertions, not a claimed live smoke test.
Live SDK schema registration, real Telegraph normalization/ownership/token setup,
HTTP dependency compatibility and actual Telegram delivery remain unverified.
Admin enable/consent and format-specific approval remain required before live use.
