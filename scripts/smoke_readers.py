#!/usr/bin/env python3
"""Live smoke: call list_rules, list_accounts and list_categories ONCE against the real
account and print COUNTS ONLY (no names, balances or patterns -- the output is pasted into
handoffs). Exit 0 if all three answer a total > 0, else 1.

READ-ONLY: three page GETs through the server's own tools. Nothing here can create, delete,
run or sync anything on Fintable.
"""
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.CRITICAL)  # the server logs cookie-extraction chatter; keep stdout to counts
import fintable_mcp as F  # noqa: E402

READERS = [
    ("list_rules", F.fintable_list_rules, F.ListRulesInput, "kind"),
    ("list_accounts", F.fintable_list_accounts, F.ListAccountsInput, "state"),
    ("list_categories", F.fintable_list_categories, F.ListCategoriesInput, "group"),
]


async def main() -> int:
    ok = True
    for label, tool, inp, facet in READERS:
        fn = getattr(tool, "fn", tool)
        out = await fn(inp())
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            print(f"{label:16s} FAIL  {out.splitlines()[0][:160]}")
            ok = False
            continue
        items = next(v for k, v in data.items() if isinstance(v, list))
        by = {}
        for it in items:
            by[it.get(facet, "")] = by.get(it.get(facet, ""), 0) + 1
        good = data.get("total", 0) > 0
        ok &= good
        print(f"{label:16s} {'OK  ' if good else 'FAIL'}  total={data.get('total')}  "
              f"distinct_{facet}={len(by)}" + (f"  {facet}={by}" if facet != "group" else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
