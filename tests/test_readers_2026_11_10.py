"""fintableMcpDom: the three config readers against the 2026-11-10 DOM.

Fixtures: tests/fixtures/2026-11-10/{rules,accounts,categories}.html, written by
scripts/capture_fixtures.py from three live GETs. The DOM is verbatim; every VALUE is
synthetic (this repo is public), with item counts preserved: 258 rules, 18 accounts,
37 categories in 5 groups (254 simple + 4 advanced rules). 'Home Depot' >> COGS is kept real on purpose as the known pair.

Two controls per reader, the same pair test_parse_rules.py uses:
  POSITIVE -- the saved page parses to its real count, with no UI chrome in the output.
  NEGATIVE -- the same page with the item rows gutted must RAISE through _silent_zero_guard.
"""
import os
import re
import sys

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fintable_mcp as F  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "2026-11-10")
CHROME = {"Edit category", "Delete category", "Create rule", "Cancel", "Integrations",
          "Edit rule", "Delete rule", "Preview", "Save", "Sync now", "Rename"}


def _page(name):
    with open(os.path.join(FIX, name)) as fh:
        return fh.read()


def _gut(html, attr_re):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup.find_all(attrs={"wire:key": re.compile(attr_re)}):
        t.decompose()
    return str(soup)


# -- rules ------------------------------------------------------------------------------
def test_rules_parse_every_row():
    rules = F._parse_rules_from_html(_page("rules.html"))
    assert len(rules) == 258
    assert all(r["id"] and r["category"] for r in rules)
    kinds = {r["kind"] for r in rules}
    assert kinds <= {"simple", "advanced"}, f"unclassified rows: {kinds}"
    assert sum(r["kind"] == "advanced" for r in rules) == 4


def test_rules_known_pair():
    rules = F._parse_rules_from_html(_page("rules.html"))
    assert {"pattern": "Home Depot", "category": "COGS"} in [
        {"pattern": r["pattern"], "category": r["category"]} for r in rules]


def test_rules_gutted_page_refuses():
    html = _gut(_page("rules.html"), r"^rule-")
    assert F._parse_rules_from_html(html) == []
    with pytest.raises(RuntimeError, match="PARSER/DOM failure"):
        F._silent_zero_guard("rules", html, 0, "rule rows")


# -- accounts ---------------------------------------------------------------------------
def test_accounts_parse_every_row():
    accounts = F._parse_accounts_from_html(_page("accounts.html"))
    assert len(accounts) == 18
    for a in accounts:
        assert a["account_id"].startswith("acc_")
        assert re.fullmatch(r"\d{4}", a["last4"]), a["name"]
        assert a["balance"].startswith(("$", "-$"))
        assert a["state"] in ("enabled", "disabled")
        assert a["institution"] and a["provider"] == "PLAID"


def test_accounts_gutted_page_refuses():
    html = _gut(_page("accounts.html"), r"^home-account-")
    assert F._parse_accounts_from_html(html) == []
    with pytest.raises(RuntimeError, match="PARSER/DOM failure"):
        F._silent_zero_guard("accounts", html, 0, "account rows")


# -- categories -------------------------------------------------------------------------
def test_categories_are_real_names_only():
    cats = F._parse_categories_from_html(_page("categories.html"))
    assert len(cats) == 37
    names = [c["name"] for c in cats]
    assert len(set(names)) == 37
    assert not CHROME & set(names), CHROME & set(names)
    assert {"name": "COGS", "group": "COGS"} in [{"name": c["name"], "group": c["group"]} for c in cats]
    assert len({c["group"] for c in cats}) == 5
    assert all(c["id"] for c in cats)


def test_categories_gutted_page_refuses():
    html = _gut(_page("categories.html"), r"^category-")
    assert F._parse_categories_from_html(html) == []
    with pytest.raises(RuntimeError, match="PARSER/DOM failure"):
        F._silent_zero_guard("categories", html, 0, "category rows")


# -- the readers themselves refuse (not just the guard in isolation) -------------------
@pytest.mark.parametrize("tool,inp,route,gut", [
    ("fintable_list_rules", "ListRulesInput", "rules.html", r"^rule-"),
    ("fintable_list_accounts", "ListAccountsInput", "accounts.html", r"^home-account-"),
    ("fintable_list_categories", "ListCategoriesInput", "categories.html", r"^category-"),
])
def test_reader_refuses_zero_and_answers_real(monkeypatch, tool, inp, route, gut):
    import asyncio
    import contextlib

    page = {"html": ""}

    @contextlib.asynccontextmanager
    async def fake_client():
        yield None

    async def fake_fetch(client, key):
        return page["html"], "csrf", {}

    monkeypatch.setattr(F, "_get_client", fake_client)
    monkeypatch.setattr(F, "_fetch_page", fake_fetch)
    fn = getattr(F, tool)
    fn = getattr(fn, "fn", fn)
    args = getattr(F, inp)()

    page["html"] = _gut(_page(route), gut)
    out = asyncio.run(fn(args))
    assert out.startswith("Error") and "PARSER/DOM failure" in out, out[:300]

    page["html"] = _page(route)
    out = asyncio.run(fn(args))
    assert '"total":' in out and "PARSER/DOM failure" not in out, out[:300]
