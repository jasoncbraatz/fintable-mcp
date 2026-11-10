---
project: fintableRuleWriter
session_n: 1
gh_repo: "jasoncbraatz/fintable-mcp"
branch: "main"
gh_sha: "bc8e352e54de224720813cadbb0ced9a7fafc75d"
updated: "2026-11-10"
definition_of_done: "create_rule and create_bulk_rules refuse to report success they did not observe (tests), and the live Fintable account holds the 24 rules from rule-translation.md section 1 with before/after exports and a rollback list of the new rule ids"
verify_cmd: "cd ~/repos/fintable-mcp && python3 -m pytest -q tests && B=~/Desktop/downloads/bookkeeper/backups && test -s $B/fintable-rules-before-20261110.json && test -s $B/fintable-rules-after-20261110.json && python3 -c \"import json,os;d=json.load(open(os.path.expanduser(\\\"~/Desktop/downloads/bookkeeper/backups/fintable-rules-added-20261110.json\\\")));assert len(d)==24\""
verify_seat: ""     # (ruling #670) set to a roster box name ONLY if verify_cmd must run on a
                    # specific seat (e.g. it calls `claude -p`, which needs a logged-in
                    # keychain, not the board's bare ssh). Empty = run wherever `complete` runs.
lessons_consulted: []
live_theme: "session 0 — this skeleton was written by `rail.py handoff-init` and nobody has played an inning yet"
phase: "SESSION 0. No inning has been played. The next worker's first act is to replace next_at_bat below with a real one."
gate_passed: false
next_at_bat: "MAKE THE FINTABLE MCP'S RULE WRITER HONEST, then use it to copy 24 BraatzBooks rules onto Fintable.\n\nContext: ~/Desktop/downloads/HANDOFF-diytouchstone.md (tail); ~/repos/fintable-mcp (PUBLIC repo: synthetic fixtures only, raw captures stay in ~/.local/state/fintable-mcp/captures/); your sibling lane fintableMcpDom repaired the READERS today (258 rules / 18 accounts / 37 categories live).\n\nTHE DEFECT (read fintable_mcp.py fintable_create_rule, ~line 1019): it looks for a Livewire component whose name contains \"create-rule\" or \"modal-rule\", else calls `createSimpleRule` on \"livepage-rules\", and then returns {\"success\": true} WITHOUT ever checking that a rule exists. Those component/method names were guessed against a DOM Fintable has since redesigned. A writer that reports success it never observed is the same lie as a reader that reports zero.\n\nWHAT JASON ASKED (2026-11-10): \"The category SOT can now come from Braatzbooks, which will require building rules on fintable.\" The measured list: ~/repos/braatzio-plan/v3/ledger/touchstone/receipts/rule-translation.md section 1 = 24 TRANSLATABLE rules (pattern -> category), each proven on a 645-string corpus. Categories already exist on Fintable (all 35 DIY names; check each of the 24 targets is among the 37 before writing; if one is missing, STOP on that rule and list it -- do not create categories).\n\nFIRST AT-BAT (no write to Fintable): find the real create-a-simple-rule flow in the current pages (captures + the Livewire snapshots/components on the rules page). Write down the component, method and payload you will use, and why you believe it, in the handoff. Add a POST-VERIFY to create_rule and create_bulk_rules: after the call, re-list and require exactly one new rule with that pattern and category, else return an error that says UNVERIFIED and what was observed. Unit tests on synthetic fixtures for: verified create, create that the server ignored (must error), duplicate pattern already present (must refuse before calling).\n\nTHEN, live, in this order:\n1. Export every current rule (all pages) to ~/Desktop/downloads/bookkeeper/backups/fintable-rules-before-20261110.json (private, not git). Expect 258.\n2. Create ONE of the 24. Re-list. Require 259 and the exact pattern -> category. If not: STOP, write what happened, do not try a second.\n3. Create the other 23, verifying each. Expect 282.\n4. Save fintable-rules-after-20261110.json and fintable-rules-added-20261110.json (the 24 new rule ids + pattern + category) = the rollback list. Rollback procedure in the handoff: delete exactly those ids.\n5. Sync ~/Scripts/fintable-mcp/fintable_mcp.py with the repo (same mechanism fintableMcpDom used) and note that the desktop app must restart its MCP server to load it.\n\nFENCE: NEVER call run_all_rules, resync_spreadsheets or sync_accounts (re-categorizing history is a separate owner decision). delete_rule only on a rule THIS lane created wrongly in step 2/3, and say so. No category creation. No credentials in git or in the handoff. If Fintable shows a confirmation, a paywall or anything unexpected, stop and report."
deploys_to: []
blockers: []
drift_flags: []
parking_lot: []
---

# fintableRuleWriter — LIVING HANDOFF

## Read first
`docs/NORTH-STAR-fintableRuleWriter.md` if it exists, else `docs/NORTH-STAR.md` (the invariants and the
destination), then run the `verify_cmd` in the frontmatter above. Its RED lines are the at-bat
and its GREEN lines are the guard rails.

## Where this came from
`rail.py handoff-init --project fintableRuleWriter` wrote this file as a SKELETON so an unattended
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
