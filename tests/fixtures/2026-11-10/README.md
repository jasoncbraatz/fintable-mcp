# 2026-11-10 fixtures (fintableMcpDom)

Captured by `scripts/capture_fixtures.py`: three read-only GETs through the server's own
`_get_client()` (rookiepy cookies from Chrome on darwin), 2026-11-10 ~08:08 local.

| fixture | route requested | landed on (302) | items |
|---|---|---|---|
| rules.html | /dash/v2/categorizer/rules | /w/<ws>/categorizer?tab=rules | 258 rules (254 simple, 4 advanced), one page |
| accounts.html | /dash/v2/accounts | /w/<ws>/accounts | 18 accounts, 1 connection, current workspace only |
| categories.html | /dash/v2/categorizer | /w/<ws>/categorizer | 37 categories in 5 groups |

**This repo is public.** The DOM is verbatim (tags, attributes, wire:keys, nesting; `<script>`,
`<style>` and SVG paths removed). Every VALUE is synthetic: rule literals -> `Vendor NNN`,
categories -> `Category NN`, accounts -> `Account NN (10NN)`, money -> `$1.00`, ids, emails,
workspace ids, CSRF and Livewire checksums replaced. `'Home Depot' » COGS` is kept real as the
known pair. The capture refuses to write if any collected real value survives. Raw pages stay
private at `~/.local/state/fintable-mcp/captures/2026-11-10/`, never in git.

Re-anonymize without refetching: `python3 scripts/capture_fixtures.py --from-raw`.
