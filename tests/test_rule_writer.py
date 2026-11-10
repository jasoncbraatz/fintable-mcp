"""fintableRuleWriter: create_rule / create_bulk_rules may only report a success they OBSERVED.

The old writer posted to a guessed Livewire method and returned {"success": true} without
looking. These tests drive the writer against the synthetic 2026-11-10 fixtures with the
network replaced: the "server" either adds the rule to the next rules page (verified create)
or ignores the call (must be UNVERIFIED), and a pattern that already exists must be refused
before any write is sent.
"""
import asyncio
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fintable_mcp as F  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "2026-11-10")
NEW_ID = "11111111-1111-4111-8111-111111111111"


def _page(name):
    with open(os.path.join(FIX, name)) as fh:
        return fh.read()


RULES = _page("rules.html")
CATS = _page("categories.html")
FIRST_ID = "00000000-0000-4000-8000-000000000001"


def _first_row(html):
    i = html.find(f'wire:key="rule-{FIRST_ID}"')
    start = html.rfind("<div", 0, i)
    nxt = html.find('wire:key="rule-', i + 10)
    return html[start:html.rfind("<div", 0, nxt)]


def _with_rule(html, pattern, category, rid=NEW_ID):
    """The rules page as it would read after the server saved one more simple rule."""
    row = _first_row(html).replace(FIRST_ID, rid)
    row = row.replace("'Home Depot' » COGS", f"'{pattern}' » {category}")
    row = re.sub(r"(data-flux-badge=\"data-flux-badge\">)\s*COGS\s*", rf"\g<1>{category}", row, count=1)
    return html.replace(_first_row(html), _first_row(html) + row, 1)


class _Server:
    """Stands in for _fetch_page/_livewire_call. `on_save` returns the next rules page."""

    def __init__(self, monkeypatch, on_save):
        self.rules_html = RULES
        self.calls = []
        self.on_save = on_save
        self.matched = 2

        class _Client:
            async def __aenter__(s):
                return s

            async def __aexit__(s, *a):
                return False

        async def fetch(client, route):
            html = {"rules": self.rules_html, "categorizer": CATS}[route]
            snaps = {"livepage-rules": {"snapshot_raw": "{}"}, "modal-rule": {"snapshot_raw": "{}"}}
            return html, "csrf", snaps

        async def call(client, csrf, snapshot_raw, method, params=None, updates=None):
            # modal-rule is a chained wizard: selectRuleType -> step 1, test -> step 2 (preview),
            # save only takes effect from a step-2 snapshot (as probed live 2026-11-10).
            self.calls.append((method, updates))
            data = {**json.loads(snapshot_raw).get("data", {}), **(updates or {})}
            html = ""
            if method == F._RULE_SELECT_METHOD:
                data["step"] = 1
            elif method == F._RULE_PREVIEW_METHOD and data.get("step") == 1:
                data["step"] = 2
                html = f"<div>Matched <b>{self.matched}</b> transactions</div>"
            elif method == F._RULE_SAVE_METHOD and data.get("step") == 2:
                self.rules_html = self.on_save(self.rules_html, data)
            elif method == "deleteRule":
                self.rules_html = self.on_save(self.rules_html, updates)
            return {"components": [{"snapshot": json.dumps({"data": data}), "effects": {"html": html}}]}

        monkeypatch.setattr(F, "_get_client", lambda: _Client())
        monkeypatch.setattr(F, "_fetch_page", fetch)
        monkeypatch.setattr(F, "_livewire_call", call)


def _create(pattern, category):
    return json.loads(asyncio.run(F.fintable_create_rule(F.CreateRuleInput(pattern=pattern, category=category))))


def test_verified_create_reports_the_new_rule(monkeypatch):
    srv = _Server(monkeypatch, lambda html, upd: _with_rule(html, "Zebra Feed", "Category 02"))
    out = _create("Zebra Feed", "Category 02")
    assert out["success"] is True and out["verified"] is True
    assert out["rule"]["id"] == NEW_ID
    assert out["total_rules"] == 259
    assert out["preview_matched"] == 2
    assert srv.calls == [
        (F._RULE_SELECT_METHOD, {"ruleType": "simple"}),
        (F._RULE_PREVIEW_METHOD, {"text": "Zebra Feed", "cid": "category-02_FIXTURE002"}),
        (F._RULE_SAVE_METHOD, None),
    ]


def test_preview_mismatch_refused_before_save(monkeypatch):
    srv = _Server(monkeypatch, lambda html, upd: pytest.fail("saved despite a preview mismatch"))
    out = json.loads(asyncio.run(F.fintable_create_rule(F.CreateRuleInput(
        pattern="Zebra Feed", category="Category 02", expect_matched=5))))
    assert out["success"] is False and out["error"] == "PREVIEW_MISMATCH" and out["preview_matched"] == 2
    assert F._RULE_SAVE_METHOD not in [m for m, _ in srv.calls]


def test_ignored_create_is_unverified(monkeypatch):
    _Server(monkeypatch, lambda html, upd: html)  # server swallows the call
    out = _create("Zebra Feed", "Category 02")
    assert out["success"] is False and out["error"] == "UNVERIFIED"
    assert out["observed"]["before_total"] == out["observed"]["after_total"] == 258


def test_wrong_category_is_unverified(monkeypatch):
    _Server(monkeypatch, lambda html, upd: _with_rule(html, "Zebra Feed", "Category 03"))
    out = _create("Zebra Feed", "Category 02")
    assert out["success"] is False and out["error"] == "UNVERIFIED"
    assert out["observed"]["new_rules"][0]["category"] == "Category 03"


def test_duplicate_pattern_refused_before_any_write(monkeypatch):
    srv = _Server(monkeypatch, lambda html, upd: pytest.fail("a write was sent for a duplicate"))
    out = _create("home depot", "Category 02")
    assert out["success"] is False and out["error"] == "DUPLICATE"
    assert srv.calls == []


def test_missing_category_refused_before_any_write(monkeypatch):
    srv = _Server(monkeypatch, lambda html, upd: pytest.fail("a write was sent for a missing category"))
    out = asyncio.run(F.fintable_create_rule(F.CreateRuleInput(pattern="Zebra Feed", category="No Such Category")))
    assert "does not exist" in out and srv.calls == []


def test_bulk_stops_at_first_unverified_and_lists_only_observed(monkeypatch):
    def on_save(html, upd):
        if upd["text"] == "Alpha Co":
            return _with_rule(html, "Alpha Co", "Category 02")
        return html  # second create silently ignored

    srv = _Server(monkeypatch, on_save)
    out = json.loads(asyncio.run(F.fintable_create_bulk_rules(F.CreateBulkRulesInput(rules=[
        {"pattern": "Alpha Co", "category": "Category 02"},
        {"pattern": "Beta Co", "category": "Category 02"},
        {"pattern": "Gamma Co", "category": "Category 02"},
    ]))))
    assert out["created_count"] == 1 and out["created"][0]["id"] == NEW_ID
    assert out["failed_count"] == 1 and out["failed"][0]["result"]["error"] == "UNVERIFIED"
    assert out["not_attempted"] == 1
    assert [m for m, _ in srv.calls].count(F._RULE_SAVE_METHOD) == 2


def _delete(rid):
    return json.loads(asyncio.run(F.fintable_delete_rule(F.DeleteRuleInput(rule_id=rid))))


def _without_rule(html, rid):
    i = html.find(f'wire:key="rule-{rid}"')
    start = html.rfind("<div", 0, i)
    nxt = html.find('wire:key="rule-', i + 10)
    return html[:start] + html[html.rfind("<div", 0, nxt):]


def test_verified_delete_reports_the_deleted_rule(monkeypatch):
    srv = _Server(monkeypatch, lambda html, u: _without_rule(html, FIRST_ID))
    out = _delete(FIRST_ID)
    assert out["success"] is True and out["verified"] is True
    assert out["deleted"]["id"] == FIRST_ID and out["deleted"]["pattern"] == "Home Depot"
    assert [m for m, _ in srv.calls] == ["deleteRule"]


def test_ignored_delete_is_unverified(monkeypatch):
    _Server(monkeypatch, lambda html, u: html)
    out = _delete(FIRST_ID)
    assert out["success"] is False and out["error"] == "UNVERIFIED"
    assert out["observed"]["still_present"] is True


def test_delete_of_unknown_id_refused_before_any_write(monkeypatch):
    srv = _Server(monkeypatch, lambda html, u: html)
    out = _delete(NEW_ID)
    assert out["success"] is False and out["error"] == "NOT_FOUND"
    assert srv.calls == []
