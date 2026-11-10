---
project: fintableRuleWriter
session_n: 2
gh_repo: "jasoncbraatz/fintable-mcp"
branch: "main"
gh_sha: "b01fd7ce207cd89b8f5ee5d2a6d2282d78dde9e3"
updated: "2026-11-10"
definition_of_done: "create_rule and create_bulk_rules refuse to report success they did not observe (tests), and the live Fintable account holds the 24 rules from rule-translation.md section 1 with before/after exports and a rollback list of the new rule ids"
verify_cmd: "cd ~/repos/fintable-mcp && python3 -m pytest -q tests && B=~/Desktop/downloads/bookkeeper/backups && test -s $B/fintable-rules-before-20261110.json && test -s $B/fintable-rules-after-20261110.json && python3 -c \"import json,os;d=json.load(open(os.path.expanduser(\\\"~/Desktop/downloads/bookkeeper/backups/fintable-rules-added-20261110.json\\\")));assert len(d)==24\""
verify_seat: ""     # (ruling #670) set to a roster box name ONLY if verify_cmd must run on a
                    # specific seat (e.g. it calls `claude -p`, which needs a logged-in
                    # keychain, not the board's bare ssh). Empty = run wherever `complete` runs.
lessons_consulted: ["2026-11-10-fintable-dom-2026-11-10-fintable", "2026-09-01-fintable-rules-engine-measured-doing-create", "2026-10-10-fintable-mcp-live-verify-from-box", "2026-09-30-ledgerprimitive3-i30-fintable-s-rules-page"]
live_theme: "inning 1: writer made honest (post-verify + 6 tests, 28/28 green); live leg blocked: no logged-in fintable session on darwin + ruling #1314 (Save applies retroactively)"
phase: "CODE HALF DONE, LIVE HALF BLOCKED. create_rule/create_bulk_rules now refuse unobserved success (tests). Zero writes to Fintable so far. Waiting on ruling #1314 and on Jason logging into fintable.io in Chrome."
gate_passed: false
next_at_bat: "1. Read ruling #1314. If B (recommended): no save until Jason has seen per-rule Matched-N. If A: proceed. If the ruling says park, park.
2. Auth: no browser on darwin had a fintable session on 2026-11-10 (rookiepy Chrome + CDP :9222/:9366/:63160 all lacked the session cookie; only ads/cf cookies). Jason must log into fintable.io in Chrome first -- that is needs-jason, do not try to log in yourself.
3. With a session: python3 scripts/probe_rule_modal.py (READ-ONLY: one selectRuleType round-trip, never saves). It prints the step-1 form's wire:model fields and wire:click actions. Confirm _RULE_SAVE_METHOD ('save', UNPROBED) and the update keys (ruleType/text/cid) in fintable_mcp.py; there may be an intermediate test/preview step that must be called first (lesson: wizard ends in a 'Matched N transactions' dry-run). Fix the constants + the test expectation, cp fintable_mcp.py src/fintable_mcp/server.py.
4. Then the live steps 1-5 from the original brief (before-export 258 -> ONE create -> verify 259 -> 23 more via create_bulk_rules (stops at first UNVERIFIED; its created[] list carries ids = rollback list) -> after-export + added json -> sync ~/Scripts/fintable-mcp). Check each of the 24 categories in rule-translation.md section 1 against list_categories first; the writer itself refuses missing/ambiguous categories.
FENCE unchanged: never run_all_rules / resync_spreadsheets / sync_accounts; delete_rule only on a rule this lane created wrongly."
deploys_to: []
blockers: ["ruling #1314 (Save applies retroactively; needs-ceo)", "needs-jason: no logged-in fintable.io session in any Chrome on darwin"]
drift_flags: []
parking_lot: []
---

# fintableRuleWriter — LIVING HANDOFF (session 2 next)

WAITING_ON: kind=ruling key=1314

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
**No.** The code half is met (tests). The live half (24 rules on Fintable, exports, rollback list) has not started and is gated on #1314 and a login.
