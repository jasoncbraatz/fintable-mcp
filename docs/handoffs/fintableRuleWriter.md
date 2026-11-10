---
project: fintableRuleWriter
session_n: 4
gh_repo: "jasoncbraatz/fintable-mcp"
branch: "main"
gh_sha: "6c2511a66410b937edff7edae7cbf94f3dcbdf68"
updated: "2026-11-10"
definition_of_done: "create_rule and create_bulk_rules refuse to report success they did not observe (tests), and the live Fintable account holds the 24 rules from rule-translation.md section 1 with before/after exports and a rollback list of the new rule ids"
verify_cmd: "cd ~/repos/fintable-mcp && python3 -m pytest -q tests && B=~/Desktop/downloads/bookkeeper/backups && test -s $B/fintable-rules-before-20261110.json && test -s $B/fintable-rules-after-20261110.json && python3 -c \"import json,os;d=json.load(open(os.path.expanduser(\\\"~/Desktop/downloads/bookkeeper/backups/fintable-rules-added-20261110.json\\\")));assert len(d)==24\""
verify_seat: ""     # (ruling #670) set to a roster box name ONLY if verify_cmd must run on a
                    # specific seat (e.g. it calls `claude -p`, which needs a logged-in
                    # keychain, not the board's bare ssh). Empty = run wherever `complete` runs.
lessons_consulted: ["2026-11-10-fintable-dom-2026-11-10-fintable", "2026-09-01-fintable-rules-engine-measured-doing-create", "2026-10-10-fintable-mcp-live-verify-from-box", "2026-09-30-ledgerprimitive3-i30-fintable-s-rules-page"]
live_theme: "inning 3: gate moved (cogs-mover CDP :9222 held a fresh fintable_session); real save flow probed and fixed; 24 rules LIVE (258->282), before/after exports + 24-id rollback list written; books-side diff = exactly the 39 measured rows"
phase: "DONE pending `rail.py complete` (both halves met: 32 tests green; 24 rules live with receipts)."
gate_passed: true
next_at_bat: "If rail_log shows no `complete` row for fintableRuleWriter: run `python3 ~/repos/pitching-machine/rail.py complete --project fintableRuleWriter --fence <fence>` (verify_cmd is ~5 s). Nothing else is owed by this DoD. Optional follow-ups, not DoD: the found-in-passing writer-honesty pass (run_all_rules / create_category / bulk run_after_create)."
deploys_to: []
blockers: []
drift_flags: []
parking_lot: []
---

# fintableRuleWriter — LIVING HANDOFF (session 4 next)

## Inning 3 (2026-11-10, local-mbp2024-10504-d): what moved — the live half landed
- **Gate moved.** Default Chrome still has no session, but the cogs-mover CDP Chrome on **:9222** (`~/Scripts/cogs-mover/.cdp-profile/Profile 1`) held a `fintable_session` created 15:55:37Z (dashboard tab open). Cookies came out via playwright `connect_over_cdp` -> `~/.local/state/fintable-mcp/cookies.txt` (600) -> `FINTABLE_COOKIES`. Nobody logged in on Jason's behalf. Card 1220385489416137 can be closed.
- **Found + fixed: rookiepy shadowed FINTABLE_COOKIES.** Default Chrome returns ads/GA/cf_clearance cookies with no session, and that jar won the auth priority. A jar without `fintable_session` now falls through.
- **The real save flow (probed read-only, then used):** `modal-rule` is a 3-step wizard with CHAINED snapshots: `selectRuleType{ruleType:simple}` -> step 1 (`text`, `cid`; button `test` = "Preview matches") -> step 2 ("Matched N transactions"; button `save` = "Save and apply rule": applies to matching history + future, manual choices kept). i1's guess sent `save` against a step-0 snapshot. The post-verify would have caught it as UNVERIFIED. `create_rule` now drives all three steps, refuses `NO_PREVIEW` if step 2 isn't reached, refuses `PREVIEW_MISMATCH` before save when `expect_matched` disagrees, and returns `preview_matched`. Bulk passes per-rule `expect_matched` through. Tests: **32 passed** (new: preview-mismatch refused before save; the fake server now models the wizard).
- **Ruling #1314 conditions, in order, all met:**
  1. before-export: `~/Desktop/downloads/bookkeeper/backups/fintable-rules-before-20261110.json` (258 rules). Books-side "before" too: `diy-categories-before-20261110.json` (all 10,608 DIY rows' **Category; 39 target rows blank).
  2. Read-only preview of all 24: every Matched-N equals the ruling's measurement (sum 39), every category resolves to one cid, no duplicates.
  3. ONE rule (GEICO -> Auto Insurance, id a3316b50-ba91-43fd-b524-8527c4b4e283): verified +1 (259). Full DIY diff: **exactly 2 rows changed, both GEICO, blank -> Auto Insurance.**
  4. The other 23 via `create_bulk_rules` with `expect_matched`: 23/23 verified, 0 failed.
  5. after-export `fintable-rules-after-20261110.json`: 282 rules, 24 new == the rollback ids, 0 gone, 0 pre-existing rules altered. Rollback list `fintable-rules-added-20261110.json` = 24 objects (id, pattern, category, preview_matched, braatzbooks_rule).
  6. Books-side diff after all 24: the 39 matches are **34 distinct DIY rows** (FAVOR/FAVOR HEB NOW and GOOGLE WORKSPACE/WORKSPACE overlap, same category). **All 34 went blank -> the expected category, 0 other rows of 10,608 changed.** Receipt: `diy-categories-after-20261110.json`. Sync took ~2-15 min (the last row landed ~16:16Z).
- Never called: run_all_rules / resync_spreadsheets / sync_accounts / delete_rule.

## Is the phase DONE?
**Yes.** Both halves of the DoD are met and receipted. See `complete` status in rail_log. This handoff does not claim it ran.

OPS: none -- this lane added 24 static categorization rules to Fintable and a code fix to the MCP writer; no service, cron, deploy or credential was created, so nothing runs that could break unwatched. Drift in the rule list is visible to any later list_rules vs fintable-rules-after-20261110.json.

## Rollback procedure
`fintable_delete_rule` on each id in `fintable-rules-added-20261110.json` (rule list). Books side: the 39 rows were all blank before. `diy-categories-before-20261110.json` + `fintable-24rules-matched-rows-20261110.json` name them, and blanking them in Airtable restores the books. A rule delete alone does NOT un-categorize.


## Inning 2 (2026-11-10, local-mbp2024-10504-d): what moved
- **Ruling #1314 RULED A** by the architect: creating the 24 rules, including the retroactive apply, is authorized. It was measured: the 24 patterns match 39 DIY rows, all blank, so the save fills blanks and overwrites nothing. The conditions are ordered (see next_at_bat 2). PERFORMED is not stamped yet. Stamp it once the creates land.
- **Auth is still the gate.** Inning 2 checked every Cookies DB on darwin (regular Chrome Default, ~/.pw-lanes/{fintable,braatzledger,...}, cogs-mover .cdp-profile). Every `fintable_session` has expired; the latest was 2026-10-01. No CDP Chrome is listening for fintable. It was filed through the door: card **1220385489416137** (NOW), with pager #326 (bundled to the digest because --by is 6.6 days out). The lane waits on that card.
- **`fintable_delete_rule` made honest** (found in passing in i1; it is the rollback path). It refuses NOT_FOUND before any write. After `deleteRule` it re-lists, and reports success only if exactly that id is gone and nothing else vanished. Otherwise it returns UNVERIFIED with what it observed. On success it returns the deleted rule as the receipt. 3 new tests; `pytest -q tests` = **31 passed**; server.py re-synced.
- Still unfixed from i1's found-in-passing: `run_all_rules` and `create_category` report unverified success, and `create_bulk_rules(run_after_create=True)` swallows exceptions. All of these are outside the DoD. run_all_rules is fenced off anyway.



## Inning 1 (2026-11-10, local-mbp2024-10504-d): what moved

**Writer made honest (the code half of DONE).** `fintable_create_rule` used to send a guessed
call (`create-rule` component / `createSimpleRule` method — neither exists on the 2026-11-10 page)
and then return `{"success": true}` without looking. Now it:
1. lists rules first and **refuses DUPLICATE** (same simple pattern, case/space-insensitive) before any write;
2. resolves the category NAME to a cid from the categorizer page, **refusing missing or ambiguous names** (it never creates categories);
3. sends one Livewire call to `modal-rule` with updates `{ruleType: simple, text: <pattern>, cid: <cid>}` + method `_RULE_SAVE_METHOD`;
4. **re-lists and requires exactly one new rule id, none vanished, kind=simple, same pattern, same category**. Otherwise it returns `success:false, error:"UNVERIFIED"` plus what it observed. Success carries the new rule's id.

`fintable_create_bulk_rules` counts a rule as created only if it came back `verified`. Its `created[]` list now holds the observed rule objects (id/pattern/category), which is the rollback list. It **stops at the first refusal/UNVERIFIED** by default (`stop_on_failure`), and the result reports `not_attempted`.

Tests: `tests/test_rule_writer.py`, 6 new tests on the synthetic 2026-11-10 fixtures: verified create, server-ignored create → UNVERIFIED, wrong category → UNVERIFIED, duplicate refused with zero writes, missing category refused with zero writes, and bulk stopping at the first UNVERIFIED. The whole suite passes: `pytest -q tests` = 28 passed. `src/fintable_mcp/server.py` is byte-identical to `fintable_mcp.py`.

## The create flow: what is KNOWN vs GUESSED
From the raw 08:08 capture (`~/.local/state/fintable-mcp/captures/2026-11-10/rules.html`), the page has exactly one rule editor, the Livewire component **`modal-rule`**. Its data is
`{rid, step, showModal, viewOnly, text, advancedPrompt, exampleTransactionJson, generatedJsonLogic, isLoading, generationError, cid, ruleType}`.
At step 0 it renders only the type picker (`wire:click="selectRuleType"`, `wire:model="ruleType"`). A simple rule is `(text, cid)`; ledgerPrimitive3 i30 read the same spec shape back out of existing rules.
- KNOWN: component `modal-rule`, fields `text` + `cid` + `ruleType`, step-0 action `selectRuleType`. The page-level actions are `deleteRule(uuid)`, `moveRuleToEnd(uuid)` and `runAllRules`, all on `livepage-rules`.
- GUESSED: the save action name (`save`). The only two `wire:click="save"` buttons on the static page belong to the category modals. The step-1+ form is not in the static HTML. **The post-verify is what makes this guess safe**: a wrong guess comes back UNVERIFIED and is never reported as success.
- `scripts/probe_rule_modal.py` settles it read-only once a session exists.

## Why no live step ran
1. **No session.** rookiepy found Chrome cookies for fintable.io but no session cookie (ads/GA/cf_clearance only). The CDP Chromes on :9222, :9366 and :63160 had none either. There is no Keychain credential. The sibling lane's 08:08 session has expired. → needs Jason to log into fintable.io in Chrome.
2. **Ruling #1314 (needs-ceo, irreversible).** Lesson 2026-09-01 says Fintable's rule Save applies the rule **retroactively** to matching history. That is the same re-categorization the fence reserves as an owner decision under `run_all_rules`. Deleting a rule does not restore the old categories, so the rollback list rolls back the rule list, not the books. I recommended B: show the owner per-rule Matched-N before any save.

Nothing was written to Fintable this inning. There is no before-export yet.

## Rollback procedure (for when creates happen)
Delete exactly the ids in `~/Desktop/downloads/bookkeeper/backups/fintable-rules-added-20261110.json` with `fintable_delete_rule`. Caveat (#1314): this does not un-categorize transactions the rules re-categorized on save.

## Found in passing
- `create_bulk_rules(run_after_create=True)` still swallows a run_all_rules exception and reports `rules_executed:false`. `run_all_rules`, `delete_rule` and `create_category` also return success without verifying. These are out of this DoD; tee them up for a later writer-honesty pass.
- The `verify_cmd` hard-codes `20261110` export filenames. If the live leg happens on a later date, write the files under those exact names (they are receipts named for the project day) or open a ruler amend. Do not rename them silently.

## Is the phase DONE?
**No.** The code half is met (tests). The live half (24 rules on Fintable, exports, rollback list) has not started. #1314 is cleared, so the only gate left is Jason logging into fintable.io (card 1220385489416137).
