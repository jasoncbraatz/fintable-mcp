"""SM 1219341347963917 -- the live check of b5c6c99 (2026-10-10, real Fintable session) still said
"No transactions found": Fintable had renamed the Livewire component transactions-table ->
transactions-list, and each row is now a <div data-transaction-row>, not a <tr>. The only <table>
left on the page is the date-picker calendar. The fixture below copies that markup's SHAPE with
made-up values.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fintable_mcp as F  # noqa: E402

CALENDAR_ONLY = """<div><table><thead><tr><template name="weekday"><th></th></template></tr></thead>
<tbody><template name="week"><tr></tr></template></tbody></table></div>"""

ROW = """<div class="col-span-full grid" data-transaction-row="" wire:key="tx-tx_01TESTROW{n}">
 <div class="col-start-1 text-left">
  <p dusk="recent-transaction-account" title="Checking (0001)"> Checking (0001) </p>
  <p class="line-clamp-2" title="ACME COFFEE {n}">
   <span class="me-1.5 font-semibold tabular-nums">-$4.5{n}</span>
   <span aria-hidden="true">&middot;</span> ACME COFFEE {n} </p>
  <p class="mt-1"><time datetime="2026-10-01T10:00:00+00:00">9 days ago</time> &middot;
   <span class="whitespace-nowrap">Oct 1, 2026</span></p>
 </div>
 <div class="col-start-2 text-right">
  <div data-flux-badge="data-flux-badge" title="Meals"><span>Meals</span></div>
 </div>
 <div class="col-start-3"><ui-dropdown><button aria-label="Transaction actions"></button>
  <ui-menu><button>COGS</button><button>Meals</button></ui-menu></ui-dropdown></div>
</div>"""

RENDERED = CALENDAR_ONLY + ROW.format(n=1) + ROW.format(n=2)


class _DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _patch(monkeypatch, livewire_html, record):
    monkeypatch.setattr(F, "_get_client", lambda: _DummyClient())

    async def fake_fetch_page(client, route_key):
        return CALENDAR_ONLY, "csrf", {"transactions-list": {"snapshot_raw": "{}"}}

    async def fake_livewire_call(client, csrf, snapshot_raw, method, params=None, updates=None):
        record.append(method)
        return {"components": [{"effects": {"html": livewire_html}}]}

    monkeypatch.setattr(F, "_fetch_page", fake_fetch_page)
    monkeypatch.setattr(F, "_livewire_call", fake_livewire_call)


def test_parser_reads_div_rows_not_the_calendar_table():
    rows = F._parse_transactions_from_html(RENDERED)
    assert len(rows) == 2
    assert rows[0] == {
        "id": "tx_01TESTROW1", "date": "Oct 1, 2026", "datetime": "2026-10-01T10:00:00+00:00",
        "description": "ACME COFFEE 1", "amount": "-$4.51", "category": "Meals",
        "account": "Checking (0001)",
    }


def test_default_call_renders_the_renamed_component(monkeypatch):
    calls = []
    _patch(monkeypatch, RENDERED, calls)
    out = asyncio.run(F.fintable_list_transactions(F.ListTransactionsInput()))
    assert calls == ["$refresh"]
    assert json.loads(out)["total"] == 2


def test_calendar_only_render_is_an_empty_result_not_a_dom_failure(monkeypatch):
    _patch(monkeypatch, CALENDAR_ONLY, [])
    out = asyncio.run(F.fintable_list_transactions(F.ListTransactionsInput()))
    assert out.startswith("No transactions found")
