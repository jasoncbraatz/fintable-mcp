---
project: fintableMcpDom
session_n: 2
gh_repo: "jasoncbraatz/fintable-mcp"
branch: "main"
gh_sha: "085b675dcf5c126b4bb060c46d50306762e57583"
updated: "2026-11-10"
definition_of_done: "list_rules, list_accounts and list_categories each return real items from saved 2026-11-10 fixtures and from the live account, each refuses on a zero-item parse, and the copy in ~/Scripts/fintable-mcp is identical to the repo"
verify_cmd: "cd ~/repos/fintable-mcp && python3 -m pytest -q tests && python3 scripts/smoke_readers.py && cmp -s fintable_mcp.py ~/Scripts/fintable-mcp/fintable_mcp.py"
verify_seat: ""     # (ruling #670) set to a roster box name ONLY if verify_cmd must run on a
                    # specific seat (e.g. it calls `claude -p`, which needs a logged-in
                    # keychain, not the board's bare ssh). Empty = run wherever `complete` runs.
lessons_consulted: ["2026-10-10-fintable-mcp-live-verify-from-box", "2026-09-05-dom-scraper-anchors-clickable-element-breaks", "2026-09-03-fintable-mcp-s-fintable-list-categories"]
live_theme: "inning 1 (local-mbp2024-10504-d): all three readers fixed against the 2026-11-10 DOM, fixtures committed (synthetic values, public repo), live smoke green"
phase: "WORK DONE, verify_cmd GREEN; complete REFUSED ruler-moved -- parked on CEO write ruling #1313"
gate_passed: true
next_at_bat: "Nothing for a worker until ruling #1313 is PERFORMED. Then: the CEO (or the worker the ruling names) runs `rail.py ruler amend --project fintableMcpDom --by ceo --why ...` and `rail.py complete --project fintableMcpDom --fence <current>`. verify_cmd was green on main b89928e. If a worker lands here after the amend and complete still has not run: git -C ~/Scripts/fintable-mcp pull --ff-only, run verify_cmd from ~/repos/fintable-mcp, then complete."
deploys_to: []
blockers:
  - "ruler-moved: frozen digest hashes fintable_mcp.py + scripts/smoke_readers.py (both the at-bat itself). CEO write ruling #1313."
drift_flags: []
parking_lot:
  - "list_accounts reads only the CURRENT workspace (Primary: 18 accounts, 1 connection = Shopify Balance). The Airtable count of 39 likely includes the second workspace (Stephanie Braatz). Reading it needs a workspace switch -- a session-state change this lane did not make. Needs a ruling before anyone does."
  - "Write tools (create_rule, delete_rule, run_all_rules, create_category, ...) were NOT touched and were not called; several still read livepage-rules snapshots / old selectors and are unverified against the 2026-11-10 DOM. Fence forbids calling them; repairing them is a separate project."
  - "fintable_list_transactions shares no code changed here; untouched."
---

# fintableMcpDom — LIVING HANDOFF (session 2, written at the end of inning 1)

## Read first
`docs/NORTH-STAR-fintableMcpDom.md` / `docs/NORTH-STAR.md` do not exist in this repo (checked
inning 1). The at-bat came from the frontmatter brief (architect-diyTouchstone-01, ceo scope).

## What inning 1 did (commit 5e65c71 on rail/fintableMcpDom)
- **How the copies sync:** `~/Scripts/fintable-mcp` (what claude_desktop_config runs) is its OWN
  git clone of github.com/jasoncbraatz/fintable-mcp, not a symlink or copy. Sync = push from the
  repo, then `git -C ~/Scripts/fintable-mcp pull --ff-only`. `src/fintable_mcp/server.py` must
  stay byte-identical to `fintable_mcp.py` (tests/test_src_parity.py).
- **The repo is PUBLIC** (`gh repo view` → visibility PUBLIC). The brief asked for the live pages
  with secrets scrubbed; committing them would have published rule patterns (people's names),
  account names and balances. So `scripts/capture_fixtures.py` keeps the DOM verbatim and swaps
  every VALUE for a synthetic one, preserving counts, and refuses to write if any collected real
  value survives. Raw pages: `~/.local/state/fintable-mcp/captures/2026-11-10/` (private, not in git).
  Same convention as the 2026-09-05 fixture. Notes: `tests/fixtures/2026-11-10/README.md`.
- **What the DOM is now:** every `/dash/v2/*` route 302s to `/w/<ws>/...`.
  - rules: `<div wire:key="rule-<uuid>">` with a `<p>` display + `data-flux-badge` category.
    **258 rules, ONE page** (no paginator in DOM or livepage-rules snapshot) → `page>1` now refuses.
  - accounts: `<li wire:key="home-account-acc_…">` inside `<section wire:key="home-connection-group-PLAID~…" aria-label=institution>`.
  - categories: `<div wire:key="category-<slug>_<cid>">` with `<p>` name inside `category-group-*` (badge = group).
- **Parsers rewritten**; accounts + categories now go through `_silent_zero_guard` (they returned
  "No … found" / chrome before). Legacy `<tr>` rule shape kept as a fallback so the 2026-09-05 tests still hold.
- **Tests:** `tests/test_readers_2026_11_10.py`: positive count + known pair + no chrome per reader,
  gutted-page refusal per reader, and each MCP tool end-to-end refusing on a gutted page. 22 passed.

## Live smoke (scripts/smoke_readers.py, run inning 1, read-only)
```
list_rules       OK    total=258  distinct_kind=2  kind={'simple': 254, 'advanced': 4}
list_accounts    OK    total=18  distinct_state=1  state={'enabled': 18}
list_categories  OK    total=37  distinct_group=5
exit=0
```
Fence held: no create/delete/run/resync/sync tool was called. Only GETs.

OPS: none -- read-only MCP readers called on demand by the desktop app, no daemon or schedule to watch; DOM drift surfaces as a loud PARSER/DOM refusal on the next call (every reader refuses a zero-item parse), and `python3 scripts/smoke_readers.py` (exit 0/1, counts only) is the manual check.

## Why `complete` refused (and why it is not the work)
`rail.py complete --project fintableMcpDom --fence 1` → `ruler-moved`: `fintable_mcp.py a504e5797e05 -> 4e9abe0f356c`,
`scripts/smoke_readers.py absent -> 6591fa88bbeb`. The ruler auto-hashes every file the verify_cmd line
names, and this verify_cmd names the code under repair plus a file the brief ordered created, so it
could never have survived a correct inning. The verify_cmd TEXT is untouched and ran GREEN by hand on
main b89928e (22 passed; smoke 258/18/37; cmp vs ~/Scripts identical). **What must be amended:**
`rail.py ruler amend --project fintableMcpDom --by ceo --why "<ruler hashed the subject under test>"`,
then `rail.py complete`. Opened as **ruling #1313** (needs-ceo-write). For future handoff-init briefs:
a DoD whose verify_cmd names the file being fixed needs `ruler_files:` declared to the stable inputs.

WAITING_ON: kind=ruling key=1313

## Is the phase DONE?
The DoD has three legs: (1) real items from the saved fixtures AND live: yes, per the tests and the
smoke above; (2) each refuses on a zero-item parse: yes, tested per reader and per tool; (3)
`~/Scripts/fintable-mcp` identical to the repo: true only after the merge + push + pull at the end of
this inning -- and it is (cmp passed on main b89928e). All three legs are met; the `complete` row is NOT
there yet because of the ruler, not the work. Once #1313 is performed and complete runs, DONE.
