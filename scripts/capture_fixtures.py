#!/usr/bin/env python3
"""Capture the three reader pages (rules, accounts, categorizer) as PUBLIC-SAFE fixtures.

READ-ONLY: three GETs through the server's own auth path (_get_client), nothing else.

This repo is PUBLIC and the pages are a private ledger, so the committed fixtures keep the
DOM verbatim (tags, attributes, wire:keys, nesting) and replace every VALUE with a synthetic
one: rule patterns, category names, account names, balances, ids, emails, workspace ids.
Counts are preserved (one synthetic item per real item). The raw pages are written only to
the private dir below, outside any git tree. A leak check refuses to write a fixture that
still contains any real value it collected.

    python3 scripts/capture_fixtures.py [--from-raw]   # --from-raw: re-anonymize saved raw pages
"""
import asyncio
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fintable_mcp as f  # noqa: E402

STAMP = "2026-11-10"
RAW_DIR = Path.home() / ".local/state/fintable-mcp/captures" / STAMP
OUT_DIR = ROOT / "tests/fixtures" / STAMP
PAGES = {"rules": "rules", "accounts": "accounts", "categorizer": "categories"}
# Category names generic enough to keep verbatim (they are Fintable template names).
KEEP = {"COGS", "Expense", "Income"}


async def _capture() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    async with f._get_client() as c:
        for route in PAGES:
            r = await c.get(f.ROUTES[route])
            r.raise_for_status()
            if "/login" in str(r.url):
                sys.exit(f"{route}: redirected to /login -- not authenticated")
            (RAW_DIR / f"{route}.html").write_text(r.text)
            print(f"captured {route}: {r.status_code} {len(r.text)} bytes")


def _strip(soup: BeautifulSoup) -> None:
    for t in soup.find_all(["script", "style", "link", "noscript", "iframe"]):
        t.decompose()
    for svg in soup.find_all("svg"):
        svg.clear()  # icon paths: bulk, no information
    for t in soup.find_all(attrs={"data-cfemail": True}):
        t.decompose()


def _anonymize(route: str, html: str, seed_html: str) -> str:
    """seed_html is the categorizer page: category names/ids are collected from IT for every
    page, because the rules page shows them in a filter list with no per-category anchor."""
    soup = BeautifulSoup(html, "html.parser")
    seed = BeautifulSoup(seed_html, "html.parser")
    _strip(soup)
    secrets = {}  # real -> synthetic

    def sub(real: str, fake: str) -> str:
        real = real.strip()
        if real and real not in KEEP:
            secrets.setdefault(real, fake)
        return secrets.get(real, real)

    # Categories (every page shows category names in filters/badges).
    cat_n = 0
    cats = re.findall(r"edit-category', \{cid: '([^']+)'", seed_html)
    for t in seed.find_all(attrs={"wire:key": re.compile(r"^category-(?!group-)")}):
        p = t.find("p")
        if p:
            cat_n += 1
            sub(p.get_text(strip=True), f"Category {cat_n:02d}")
    for i, cid in enumerate(cats, 1):
        slug = cid.split("_")[0]
        sub(cid, f"category-{i:02d}_FIXTURE{i:03d}")
        sub(slug, f"category-{i:02d}")
    for i, hdr in enumerate(re.findall(r"edit-header', \{header: '([^']+)'", seed_html), 1):
        sub(hdr, f"Group {i}")
    # Rule badges carry category names even on the rules page (no category list there).
    for t in soup.find_all(attrs={"wire:key": re.compile(r"^rule-")}):
        for b in t.find_all(attrs={"data-flux-badge": True}):
            name = b.get_text(strip=True)
            if name not in secrets and name not in KEEP:
                cat_n += 1
                sub(name, f"Category {cat_n:02d}")

    # Rules: ids and every quoted literal in the display text.
    v_n = 0
    for i, t in enumerate(soup.find_all(attrs={"wire:key": re.compile(r"^rule-")}), 1):
        rid = t["wire:key"][5:]
        sub(rid, f"00000000-0000-4000-8000-{i:012d}")
        p = t.find("p")
        if p:
            for lit in re.findall(r"'([^']+)'", p.get_text()):
                if lit == "Home Depot":  # the known pair the tests pin: 'Home Depot' » COGS
                    continue
                if lit not in secrets:
                    v_n += 1
                    sub(lit, f"Vendor {v_n:03d}")

    # Accounts: names (keep only the (last4) shape, synthetic digits), ids, connection labels.
    for i, li in enumerate(soup.find_all("li", attrs={"wire:key": re.compile(r"^home-account-")}), 1):
        sub(li["wire:key"][len("home-account-"):], f"acc_FIXTURE{i:017d}")
        h4 = li.find("h4")
        if h4:
            sub(h4.get_text(strip=True), f"Account {i:02d} ({1000 + i})")
    for i, g in enumerate(soup.find_all(attrs={"wire:key": re.compile(r"^home-connection-group-")}), 1):
        sub(g["wire:key"][len("home-connection-group-"):], f"PLAID~FIXTURE{i:04d}")
        if g.get("aria-label"):
            sub(g["aria-label"], f"Institution {i}")

    out = str(soup)
    for real in sorted(secrets, key=len, reverse=True):
        out = out.replace(real, secrets[real])
        esc = real.replace("'", "&#039;")
        if esc != real:
            out = out.replace(esc, secrets[real])
    # Values with no single anchor: money, workspace/account ids, emails, personal names, csrf.
    out = re.sub(r"[−-]?\$[\d,]+(?:\.\d+)?", "$1.00", out)
    out = re.sub(r"\bws_[0-9A-Z]{26}\b", "ws_FIXTUREWORKSPACE000000000", out)
    out = re.sub(r"\bacc_[0-9A-Z]{26}\b", "acc_FIXTURE00000000000000000", out)
    out = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "user@example.com", out)
    out = re.sub(r'(name="csrf-token" content=")[^"]*', r"\1fixture-csrf-token", out)
    out = re.sub(r'(name="_token" value=")[^"]*', r"\1fixture-csrf-token", out)
    out = re.sub(r'("checksum":")[0-9a-f]{64}', r"\1" + "0" * 64, out)
    out = re.sub(r"(?i)jason c braatz|stephanie braatz|braatz", "Fixture User", out)

    leaks = [s for s in secrets if len(s) >= 4 and s in out]
    if leaks:
        raise SystemExit(f"{route}: {len(leaks)} real values survived anonymization, refusing: {leaks[:5]}")
    return out


def main() -> None:
    if "--from-raw" not in sys.argv:
        asyncio.run(_capture())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seed = (RAW_DIR / "categorizer.html").read_text()
    for route, name in PAGES.items():
        out = _anonymize(route, (RAW_DIR / f"{route}.html").read_text(), seed)
        (OUT_DIR / f"{name}.html").write_text(out)
        print(f"wrote {OUT_DIR.relative_to(ROOT)}/{name}.html ({len(out)} bytes)")


if __name__ == "__main__":
    main()
