"""Regression tests for the rules scrape — SM 1218170437065088 (sev-2).

The bug: fintable_list_rules answered {"total": 0} for weeks against a live, authenticated
200 that had 237 real rules on it. The view-rule button stopped carrying the rule's display
text (it is now an icon-only action in a tooltip), so the parser's `'pattern' » Category`
split matched nothing and every row was dropped — silently, because a dropped row and an
absent row produced the same number.

Two controls, per the card:
  POSITIVE — the real page (rows captured 2026-09-05) must parse to N > 0.
  NEGATIVE — the same page with the table stripped must RAISE, not return 0.

Run: python3 -m pytest tests/ -q     (or: python3 tests/test_parse_rules.py)
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fintable_mcp as F  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fixture(name):
    with open(os.path.join(FIX, name)) as fh:
        return fh.read()


def test_real_page_parses_more_than_zero():
    """POSITIVE control: the shape that returned 0 in production must now return N > 0."""
    rules = F._parse_rules_from_html(_fixture("rules_page_real.html"))
    assert len(rules) == 9, f"expected the 9 captured rows, got {len(rules)}"
    assert all(r["id"] for r in rules), "every rule must carry its rid"


def test_both_display_forms_are_kept():
    """The 4 advanced rules are rules. Dropping them would be the same bug one level down."""
    rules = F._parse_rules_from_html(_fixture("rules_page_real.html"))
    kinds = {}
    for r in rules:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    assert kinds == {"simple": 5, "advanced": 4}, kinds
    assert all(r["category"] for r in rules), "every rule must resolve a category"

    simple = [r for r in rules if r["kind"] == "simple"][0]
    assert "»" not in simple["pattern"], "the guillemet is a separator, not part of the pattern"
    assert not simple["pattern"].startswith("'"), "quotes are stripped from the pattern"

    advanced = [r for r in rules if r["kind"] == "advanced"][0]
    assert "(Advanced)" not in advanced["pattern"]
    assert advanced["pattern"], "an advanced rule keeps its expression as the pattern"


def test_table_stripped_raises_instead_of_reporting_zero():
    """NEGATIVE control: 0 rows on a 200 is a parser failure and must be loud."""
    html = _fixture("rules_page_table_stripped.html")
    assert F._parse_rules_from_html(html) == [], "precondition: this page really does parse to 0"
    with pytest.raises(RuntimeError) as exc:
        F._silent_zero_guard("rules", html, 0, "one <tr> per rule")
    msg = str(exc.value)
    assert "PARSER/DOM failure" in msg
    assert "excerpt" in msg.lower(), "the refusal must show what it actually got"


def test_guard_is_silent_when_rows_were_found():
    """The guard must not fire on a good page."""
    F._silent_zero_guard("rules", "<html></html>", 237, "one <tr> per rule")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
