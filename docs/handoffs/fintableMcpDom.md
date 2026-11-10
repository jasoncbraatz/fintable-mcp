---
project: fintableMcpDom
session_n: 1
gh_repo: "jasoncbraatz/fintable-mcp"
branch: "main"
gh_sha: "7f5233d1c808225ff81c591dce49a351c4adf1fa"
updated: "2026-11-10"
definition_of_done: "list_rules, list_accounts and list_categories each return real items from saved 2026-11-10 fixtures and from the live account, each refuses on a zero-item parse, and the copy in ~/Scripts/fintable-mcp is identical to the repo"
verify_cmd: "cd ~/repos/fintable-mcp && python3 -m pytest -q tests && python3 scripts/smoke_readers.py && cmp -s fintable_mcp.py ~/Scripts/fintable-mcp/fintable_mcp.py"
verify_seat: ""     # (ruling #670) set to a roster box name ONLY if verify_cmd must run on a
                    # specific seat (e.g. it calls `claude -p`, which needs a logged-in
                    # keychain, not the board's bare ssh). Empty = run wherever `complete` runs.
lessons_consulted: []
live_theme: "session 0 — this skeleton was written by `rail.py handoff-init` and nobody has played an inning yet"
phase: "SESSION 0. No inning has been played. The next worker's first act is to replace next_at_bat below with a real one."
gate_passed: false
next_at_bat: "REPAIR THE FINTABLE MCP'S READERS against Fintable's current pages. Read-only on Fintable.\n\nWHY: the DIY Bookkeeper's categories are written by Fintable's own categorizer (1,160 of 1,180 Airtable rows since 2026-10-01 carry a **Category and no n8n workflow writes that field). Jason's plan (2026-11-10) is that BraatzBooks is now the category source of truth and its rules get copied onto Fintable. That needs a Fintable reader we can trust, and today (measured 2026-11-10 from a Cowork session through the desktop bridge):\n- fintable_list_rules   -> \"RuntimeError: Parsed 0 rules from a 2877512-byte page that authenticated successfully. This is a PARSER/DOM failure ... Expected: one <tr> per rule containing a wire:click=\\\"$dispatch('view-rule', ...)\\\" button\" (the refusal is correct and stays; the parser is what is stale)\n- fintable_list_accounts -> \"No accounts found\" (39 account rows exist in Airtable; this one LIES instead of refusing)\n- fintable_list_categories -> returns 117 \"categories\" that are mostly UI chrome (\"Edit category\", \"Delete category\", \"Cancel\", \"Integrations\") plus the real ones\n\nRepo: ~/repos/fintable-mcp. The copy the desktop app runs: ~/Scripts/fintable-mcp/fintable_mcp.py (claude_desktop_config.json mcpServers.fintable). Find how the repo copy reaches ~/Scripts before you change anything, and keep them identical at the end.\n\nFIRST AT-BAT: save the three live pages the server fetches (rules, accounts, categories) as fixtures under tests/fixtures/2026-11-10/ with any secret/token/cookie scrubbed and account numbers reduced to last4, and commit them with a note on how each was captured. No parser change yet.\n\nTHEN: fix the three parsers against those fixtures. Every reader must REFUSE (raise, like list_rules already does) when it parses zero items from a page that authenticated -- a zero that measured nothing is never an empty account. list_categories must return only real category names. Tests: one per reader on the saved fixture (counts > 0, a known pattern->category pair present, no UI chrome), plus one per reader proving the zero-items refusal on a gutted fixture.\n\nLAST: a live smoke script (scripts/smoke_readers.py, exit 0/1) that calls the three readers once against the real account and prints counts only -- run it and paste its output in the handoff.\n\nFENCE: do NOT call create_rule, create_bulk_rules, delete_rule, create_category, run_all_rules, resync or sync_accounts -- nothing that changes Fintable or triggers a sync. Do not print or commit credentials. Pagination of rules: report how many pages exist and make list_rules able to return all of them."
deploys_to: []
blockers: []
drift_flags: []
parking_lot: []
---

# fintableMcpDom — LIVING HANDOFF

## Read first
`docs/NORTH-STAR-fintableMcpDom.md` if it exists, else `docs/NORTH-STAR.md` (the invariants and the
destination), then run the `verify_cmd` in the frontmatter above. Its RED lines are the at-bat
and its GREEN lines are the guard rails.

## Where this came from
`rail.py handoff-init --project fintableMcpDom` wrote this file as a SKELETON so an unattended
worker would not arrive at a repo with no at-bat. Everything below the frontmatter is a
placeholder. The first worker to play an inning here rewrites all of it.

## If this lane RESTARTS a live surface, fill in `deploys_to:`
The empty list in the frontmatter is the key, not a decoration (SM 1218841995855069, ruling
#490). Name the surface this lane restarts the way another lane would spell it —
`deploys_to: ["flowers:braatzledger-surface"]` — and `rail.py claim` will refuse to hold two
live claims on it, estate-wide, printing which lane holds it. Two lanes restarting one surface
starve each other through its own journal gate: each lane's verification traffic is what
refuses the other lane's restart, so the second lane does not fail, it silently loses a
deploy. Leave the list empty if this lane restarts nothing; an empty declaration is refused
nothing.

## If `verify_cmd` can only judge from ONE box, fill in `verify_seat:`
Leave it empty unless the ruler calls `claude -p` or otherwise needs a seat this box is not --
`complete` forwarded to the board host runs verify_cmd on the BOARD, and a ruler that needs a
logged-in keychain fails there even though the exact same bits were GREEN on the seat that has
one (ruling #670, SM 1219004888726763). Naming a seat does not move the completion: the verdict
still lands on whichever box ran `complete`, only the verify_cmd's own execution is forwarded
over ssh to the named box.

## Is the phase DONE?
No — no inning has been played. Ask this question explicitly in every handoff from here on:
a milestone that is met but never declared keeps getting continued.
