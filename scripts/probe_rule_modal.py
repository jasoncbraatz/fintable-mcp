#!/usr/bin/env python3
"""Find the real simple-rule save flow on the live rules page WITHOUT saving anything.

The static rules page renders modal-rule at step 0 only (a type picker with `selectRuleType`),
so the simple form's fields and its save action are invisible until the modal advances. This
sends ONE Livewire round-trip to modal-rule -- updates {ruleType: simple} + selectRuleType --
and prints the wire:click / wire:model / $wire names in the returned HTML. Livewire modal state
is per-request; nothing is persisted. It never calls save, never dispatches run-rule.

The raw response goes to ~/.local/state/fintable-mcp/probes/ (private, outside git).
Auth: the server's own path (rookiepy Chrome, or FINTABLE_COOKIES).
"""
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fintable_mcp as F  # noqa: E402

OUT = os.path.expanduser("~/.local/state/fintable-mcp/probes")


async def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    async with F._get_client() as c:
        html, csrf, snaps = await F._fetch_page(c, "rules")
        print("rules on page:", len(F._parse_rules_from_html(html)))
        r = await F._livewire_call(c, csrf, snaps["modal-rule"]["snapshot_raw"], "selectRuleType", [],
                                   updates={"ruleType": "simple"})
        with open(os.path.join(OUT, "modal-rule-step1.json"), "w") as fh:
            json.dump(r, fh)
        comp = r["components"][0]
        h = comp.get("effects", {}).get("html", "")
        print("data after:", json.loads(comp["snapshot"])["data"])
        for label, pat in [("click", r'wire:click(?:\.[a-z]+)*="([^"]+)"'),
                           ("model", r'wire:model(?:\.[a-z]+)*="([^"]+)"'),
                           ("submit", r'wire:submit(?:\.[a-z]+)*="([^"]+)"'),
                           ("$wire", r"\$wire\.([A-Za-z_]+)\(")]:
            print(label, sorted(set(re.findall(pat, h))))


asyncio.run(main())
