"""Regression test for SM 1218196401036558 — fintable_list_transactions parsed 0 rows always.

The bug: /dash/v2/categorizer/transactions renders its grid client-side via Livewire, so the
initial GET's HTML never contains a <table>. The old code only issued the Livewire render call
when `search` or `page > 1` was set, so the default call (page=1, no search — what every caller
actually sends) skipped straight to parsing a tableless page and returned "No transactions found"
even when the account had rows.

No live Fintable session is available on this box (no FINTABLE_COOKIES, no rookiepy/Chrome), so
this mocks the two network boundaries (_fetch_page, _livewire_call) instead of hitting Fintable.
It proves the control flow — default call now always asks Livewire to render — not the live DOM.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fintable_mcp as F  # noqa: E402

TABLELESS_HTML = "<html><body><div>no table here, Livewire owns this</div></body></html>"
RENDERED_HTML = """
<table><tr><th>date</th><th>desc</th><th>amount</th></tr>
<tr><td>2026-10-01</td><td>Coffee</td><td>-4.50</td></tr>
</table>
"""
SNAP = {"snapshot_raw": '{"memo":{"name":"transactions-table"},"data":{}}'}


class _DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _patch_network(monkeypatch, livewire_html, record):
    monkeypatch.setattr(F, "_get_client", lambda: _DummyClient())

    async def fake_fetch_page(client, route_key):
        return TABLELESS_HTML, "csrf-token", {"transactions-table": SNAP}

    async def fake_livewire_call(client, csrf, snapshot_raw, method, params=None, updates=None):
        record.append({"method": method, "params": params, "updates": updates})
        return {"components": [{"effects": {"html": livewire_html}}]}

    monkeypatch.setattr(F, "_fetch_page", fake_fetch_page)
    monkeypatch.setattr(F, "_livewire_call", fake_livewire_call)


def test_default_call_now_renders_via_livewire_instead_of_skipping_it(monkeypatch):
    """page=1, no search — the shape every real caller sends, and the one that used to skip
    the Livewire call entirely and parse the tableless pre-render HTML."""
    calls = []
    _patch_network(monkeypatch, RENDERED_HTML, calls)

    result = asyncio.run(F.fintable_list_transactions(F.ListTransactionsInput(page=1)))

    assert calls, "the default call must still ask Livewire to render the component"
    assert calls[0]["method"] == "$refresh"
    assert "Coffee" in result
    assert "No transactions found" not in result


def test_search_call_still_passes_the_search_update(monkeypatch):
    calls = []
    _patch_network(monkeypatch, RENDERED_HTML, calls)

    asyncio.run(F.fintable_list_transactions(F.ListTransactionsInput(search="coffee")))

    assert calls[0]["updates"] == {"search": "coffee"}


def test_page_call_still_sends_goto_page(monkeypatch):
    calls = []
    _patch_network(monkeypatch, RENDERED_HTML, calls)

    asyncio.run(F.fintable_list_transactions(F.ListTransactionsInput(page=2)))

    assert calls[0]["method"] == "gotoPage"
    assert calls[0]["params"] == [2, "page"]


def test_livewire_render_that_still_has_no_table_raises_instead_of_reporting_zero(monkeypatch):
    """If even the rendered component HTML has no table, that's a real DOM failure (not an
    empty account) and must raise loud, same as before this fix."""
    calls = []
    _patch_network(monkeypatch, TABLELESS_HTML, calls)

    result = asyncio.run(F.fintable_list_transactions(F.ListTransactionsInput(page=1)))

    assert result.startswith("Error:")
    assert "PARSER/DOM failure" in result


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
