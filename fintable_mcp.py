#!/usr/bin/env python3
"""
Unofficial MCP Server for Fintable.io

Fintable.io uses Plaid to consolidate bank accounts into Airtable with a
categorization engine. This MCP server communicates with Fintable's Laravel
Livewire 3 backend by maintaining an authenticated session, extracting
Livewire component snapshots from page HTML, and making Livewire update
calls to invoke server-side methods.

Authentication (in priority order):
    0. Persisted cookie jar: If --persist-cookies flag is set and a valid
       cookie jar file exists, use those cookies (self-refreshing session).
    1. Auto-extract: If rookiepy is installed, cookies are pulled directly from
       Chrome's local cookie database on each run. Zero manual effort.
       Install with: pip install rookiepy
    2. FINTABLE_COOKIES env var: Full cookie header string from Chrome DevTools.
    3. FINTABLE_SESSION_COOKIE env var: Just the session cookie value.
"""

import argparse
import json
import re
import os
import sys
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ConfigDict, field_validator
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Logging (stderr only — stdout is reserved for MCP stdio transport)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("fintable_mcp")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://fintable.io"
# Livewire update path — auto-discovered from pages, with fallback
DEFAULT_LIVEWIRE_UPDATE_PATH = "/livewire-5c7ce5a8/update"
_livewire_update_path: Optional[str] = None

# Page routes
ROUTES = {
    "accounts": "/dash/v2/accounts",
    "transactions": "/dash/v2/categorizer/transactions",
    "categorizer": "/dash/v2/categorizer",
    "rules": "/dash/v2/categorizer/rules",
    "integrations": "/dash/v2/integrations",
}

# ---------------------------------------------------------------------------
# Persistent Cookie Jar (opt-in via --persist-cookies)
# ---------------------------------------------------------------------------
_persist_cookies: bool = False
_cookie_jar_path: Path = Path.home() / ".fintable-mcp-cookies.json"


def _load_persisted_cookies() -> Optional[str]:
    """Load cookies from the persisted cookie jar file, if it exists and is fresh."""
    if not _persist_cookies:
        return None
    if not _cookie_jar_path.exists():
        logger.debug("No persisted cookie jar found.")
        return None
    try:
        data = json.loads(_cookie_jar_path.read_text())
        saved_at = data.get("saved_at", 0)
        max_age = data.get("max_age_hours", 24) * 3600
        if time.time() - saved_at > max_age:
            logger.info("Persisted cookie jar has expired — falling through to other auth methods.")
            return None
        cookie_str = data.get("cookies", "")
        if cookie_str:
            logger.info(f"Loaded persisted cookies (saved {int((time.time() - saved_at) / 60)} min ago).")
            return cookie_str
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning(f"Failed to load persisted cookie jar: {e}")
    return None


def _save_persisted_cookies(cookie_str: str, max_age_hours: int = 24) -> None:
    """Save the current cookie string to the persisted jar file."""
    if not _persist_cookies:
        return
    try:
        data = {
            "cookies": cookie_str,
            "saved_at": time.time(),
            "max_age_hours": max_age_hours,
            "note": "Auto-managed by fintable-mcp. Delete this file to force re-authentication.",
        }
        _cookie_jar_path.write_text(json.dumps(data, indent=2))
        logger.debug("Persisted cookie jar updated.")
    except OSError as e:
        logger.warning(f"Failed to save cookie jar: {e}")


def _update_cookies_from_response(response: httpx.Response) -> None:
    """Capture Set-Cookie headers from a response and update the persisted jar."""
    if not _persist_cookies:
        return
    set_cookies = response.headers.get_list("set-cookie")
    if not set_cookies:
        return
    # Load current jar, merge in new cookies
    current = {}
    existing = _load_persisted_cookies()
    if existing:
        for pair in existing.split("; "):
            if "=" in pair:
                k, v = pair.split("=", 1)
                current[k.strip()] = v.strip()
    # Parse new Set-Cookie headers (just name=value, ignore directives)
    for sc in set_cookies:
        cookie_part = sc.split(";")[0].strip()
        if "=" in cookie_part:
            k, v = cookie_part.split("=", 1)
            current[k.strip()] = v.strip()
    merged = "; ".join(f"{k}={v}" for k, v in current.items())
    _save_persisted_cookies(merged)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP("fintable_mcp")


# ---------------------------------------------------------------------------
# HTTP Client Helpers
# ---------------------------------------------------------------------------
def _extract_cookies_from_browser() -> Optional[str]:
    """Try to extract fintable.io cookies directly from Chrome using rookiepy.

    Returns the cookie header string, or None if rookiepy is unavailable or fails.
    """
    try:
        import rookiepy
        cookies = rookiepy.chrome(["fintable.io"])
        if not cookies:
            logger.warning("rookiepy found no cookies for fintable.io — are you logged in to Chrome?")
            return None
        if not any(c.get("name") == "fintable_session" for c in cookies):
            # ads/GA/cf_clearance only: not a login, and returning it would shadow FINTABLE_COOKIES
            logger.warning("rookiepy found fintable.io cookies but no fintable_session — falling through")
            return None
        # Build a cookie header string from the extracted cookies
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        logger.info(f"Auto-extracted {len(cookies)} cookies from Chrome for fintable.io")
        return cookie_str
    except ImportError:
        logger.debug("rookiepy not installed — skipping browser cookie auto-extraction")
        return None
    except Exception as e:
        logger.warning(f"rookiepy cookie extraction failed: {e}")
        return None


def _build_cookie_header() -> str:
    """Build the Cookie header from persisted jar, browser, environment, or raise an error.

    Priority order:
    0. Persisted cookie jar (if --persist-cookies is active)
    1. rookiepy auto-extraction from Chrome (if installed)
    2. FINTABLE_COOKIES env var (full cookie string)
    3. FINTABLE_SESSION_COOKIE env var (just session value)
    """
    # Try persisted cookie jar first
    persisted = _load_persisted_cookies()
    if persisted:
        return persisted

    # Try auto-extraction from Chrome
    browser_cookies = _extract_cookies_from_browser()
    if browser_cookies:
        # Seed the persisted jar if persistence is enabled
        _save_persisted_cookies(browser_cookies)
        return browser_cookies

    # Fall back to env vars
    cookies = os.environ.get("FINTABLE_COOKIES", "")
    if cookies:
        _save_persisted_cookies(cookies)
        return cookies
    session = os.environ.get("FINTABLE_SESSION_COOKIE", "")
    if session:
        cookie_str = f"fintable_session={session}"
        _save_persisted_cookies(cookie_str)
        return cookie_str
    raise RuntimeError(
        "Authentication not configured. Either:\n"
        "  0. Use --persist-cookies with an initial login to self-refresh the session\n"
        "  1. Install rookiepy (pip install rookiepy) and be logged into fintable.io in Chrome\n"
        "  2. Set FINTABLE_COOKIES env var (full cookie string from Chrome DevTools)\n"
        "  3. Set FINTABLE_SESSION_COOKIE env var (just the session cookie value)"
    )


def _on_response(response: httpx.Response) -> None:
    """httpx event hook — capture Set-Cookie headers to keep the session alive."""
    _update_cookies_from_response(response)


def _get_client() -> httpx.AsyncClient:
    """Create an httpx client with auth cookies and standard headers."""
    cookie_header = _build_cookie_header()
    event_hooks = {"response": [_on_response]} if _persist_cookies else {}
    return httpx.AsyncClient(
        base_url=BASE_URL,
        headers={
            "Cookie": cookie_header,
            "User-Agent": "FintableMCP/1.0",
            "Accept": "text/html, application/json",
        },
        timeout=30.0,
        follow_redirects=True,
        event_hooks=event_hooks,
    )


# ---------------------------------------------------------------------------
# Livewire Protocol Helpers
# ---------------------------------------------------------------------------
def _extract_csrf_token(html: str) -> str:
    """Extract the CSRF token from a page's meta tags."""
    match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html)
    if match:
        return match.group(1)
    raise RuntimeError("Could not extract CSRF token — session may have expired. Re-export your cookies.")


def _extract_livewire_update_path(html: str) -> str:
    """Auto-discover the Livewire update URL from the page's data-update-uri attribute."""
    global _livewire_update_path
    if _livewire_update_path:
        return _livewire_update_path

    match = re.search(r'data-update-uri="([^"]+)"', html)
    if match:
        uri = match.group(1)
        # Convert full URL to path
        if uri.startswith("http"):
            from urllib.parse import urlparse
            _livewire_update_path = urlparse(uri).path
        else:
            _livewire_update_path = uri
        logger.info(f"Discovered Livewire update path: {_livewire_update_path}")
        return _livewire_update_path

    _livewire_update_path = DEFAULT_LIVEWIRE_UPDATE_PATH
    logger.warning(f"Could not discover Livewire update path, using default: {_livewire_update_path}")
    return _livewire_update_path


def _extract_livewire_snapshots(html: str) -> Dict[str, Dict[str, Any]]:
    """
    Extract all Livewire component snapshots from page HTML.
    Returns dict keyed by component name.
    """
    snapshots: Dict[str, Dict[str, Any]] = {}
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(attrs={"wire:snapshot": True}):
        raw = el.get("wire:snapshot", "")
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
            name = parsed.get("memo", {}).get("name", "")
            if name:
                snapshots[name] = {
                    "snapshot_raw": raw,  # Keep the original JSON string
                    "memo": parsed.get("memo", {}),
                    "data": parsed.get("data", {}),
                }
        except json.JSONDecodeError:
            continue
    return snapshots


async def _fetch_page(client: httpx.AsyncClient, route_key: str) -> tuple[str, str, Dict]:
    """
    Fetch a Fintable page and extract CSRF token + Livewire snapshots.
    Returns (html, csrf_token, snapshots_dict).
    """
    path = ROUTES.get(route_key)
    if not path:
        raise ValueError(f"Unknown route: {route_key}. Valid routes: {list(ROUTES.keys())}")
    resp = await client.get(path)
    resp.raise_for_status()
    html = resp.text
    # parity26: an expired session 302s to /login, which parses as a page with ZERO rules /
    # categories / transactions. A silent 0 where a loud 401 belongs -- refuse, name the cure.
    if str(resp.url).rstrip("/").endswith("/login") or "Log in to your account" in html:
        raise RuntimeError(
            "Not authenticated: Fintable redirected to /login (session cookie expired or missing). "
            "The page would parse as EMPTY -- refusing rather than reporting 0. "
            "Fix: log into fintable.io in Chrome (rookiepy) or refresh FINTABLE_COOKIES / --persist-cookies."
        )
    csrf = _extract_csrf_token(html)
    _extract_livewire_update_path(html)  # Auto-discover and cache the update path
    snapshots = _extract_livewire_snapshots(html)
    return html, csrf, snapshots


async def _livewire_call(
    client: httpx.AsyncClient,
    csrf_token: str,
    snapshot_raw: str,
    method: str,
    params: list = None,
    updates: dict = None,
) -> dict:
    """
    Make a Livewire 3 update call.
    """
    payload = {
        "_token": csrf_token,
        "components": [
            {
                "snapshot": snapshot_raw,
                "updates": updates or {},
                "calls": [
                    {
                        "method": method,
                        "params": params or [],
                        "metadata": {},
                    }
                ],
            }
        ],
    }
    update_path = _livewire_update_path or DEFAULT_LIVEWIRE_UPDATE_PATH
    resp = await client.post(
        update_path,
        json=payload,
        headers={
            "Content-type": "application/json",
            "X-Livewire": "1",
            "X-CSRF-TOKEN": csrf_token,
            "Referer": BASE_URL,
        },
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# HTML Parsing Helpers
# ---------------------------------------------------------------------------
def _parse_accounts_from_html(html: str) -> List[Dict[str, Any]]:
    """Parse bank accounts and balances from the accounts page HTML.

    fintableMcpDom (2026-11-10): /dash/v2/accounts now 302s to /w/<ws>/accounts, and an
    account is an <li wire:key="home-account-acc_..."> inside a
    <section wire:key="home-connection-group-<provider>~<id>" aria-label="<institution>">.
    The old /dash/v2/link/overview/account/ links are gone, so the old parser answered
    "No accounts found" against 18 real rows. Only the CURRENT workspace's accounts are on
    the page; other workspaces need a workspace switch, which this reader never does.
    """
    soup = BeautifulSoup(html, "html.parser")
    accounts = []
    for li in soup.find_all("li", attrs={"wire:key": re.compile(r"^home-account-")}):
        account_id = li["wire:key"][len("home-account-"):]
        group = li.find_parent(attrs={"wire:key": re.compile(r"^home-connection-group-")})
        group_key = group["wire:key"][len("home-connection-group-"):] if group else ""
        provider, _, connection_id = group_key.partition("~")
        h4 = li.find("h4")
        name = (h4.get("title") or h4.get_text(strip=True)) if h4 else ""
        bal = li.find(attrs={"dusk": "home-account-balance"})
        menu = li.find(attrs={"data-account-state": True})
        last4 = re.search(r"\((\d{4})\)\s*$", name)
        accounts.append({
            "name": name,
            "last4": last4.group(1) if last4 else "",
            "balance": bal.get_text(strip=True).replace("\u2212", "-") if bal else "N/A",
            "state": menu.get("data-account-state", "") if menu else "",
            "institution": group.get("aria-label", "") if group else "",
            "provider": provider,
            "connection_id": connection_id,
            "account_id": account_id,
        })
    return accounts


def _parse_categories_from_html(html: str) -> List[Dict[str, Any]]:
    """Parse categories from the categorizer page.

    fintableMcpDom (2026-11-10): the old parser took the text of every <button> on the page,
    so it returned the real categories PLUS UI chrome ("Edit category", "Delete category",
    "Cancel", "Integrations" -- 117 items for 37 categories). A category is now a
    <div wire:key="category-<slug>_<cid>"> whose <p> is the name, nested in a
    <div wire:key="category-group-<hash>"> whose badge is the group header. Anchored on the
    wire:key, so a button label can never be counted as a category again.
    """
    soup = BeautifulSoup(html, "html.parser")
    categories = []
    for el in soup.find_all("div", attrs={"wire:key": re.compile(r"^category-(?!group-)")}):
        p = el.find("p")
        name = p.get_text(strip=True) if p else ""
        if not name:
            continue
        edit = el.find(attrs={"x-on:click": re.compile(r"edit-category")})
        cid = re.search(r"cid:\s*'([^']+)'", edit["x-on:click"]) if edit else None
        group_el = el.find_parent("div", attrs={"wire:key": re.compile(r"^category-group-")})
        badge = group_el.find(attrs={"data-flux-badge": True}) if group_el else None
        categories.append({
            "name": name,
            "group": badge.get_text(strip=True) if badge else "",
            "id": cid.group(1) if cid else el["wire:key"][len("category-"):],
        })
    return categories


def _silent_zero_guard(kind: str, html: str, count: int, selector_note: str) -> None:
    """A 200 that parses to ZERO rows is a scrape that lost the DOM, not an empty account.

    smDrainScripts3 s3 / SM 1218170437065088: the rules page answered 200 with 237 real
    rule rows on it and the parser returned total=0 for weeks, because the DOM moved and
    nothing was watching. `0` and `I could not read the page` are DIFFERENT STATES and the
    scrape cannot tell them apart -- so it must refuse rather than report the one that
    blames the data. A genuinely empty account is rare, loud, and better served by a
    refusal you can read than by a zero you cannot.
    """
    if count > 0:
        return
    excerpt = re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ", strip=True))[:400]
    raise RuntimeError(
        f"Parsed 0 {kind} from a {len(html)}-byte page that authenticated successfully. "
        f"This is a PARSER/DOM failure, not an empty account -- refusing to report 0. "
        f"Expected: {selector_note}. "
        f"Page text excerpt: {excerpt!r}"
    )


# The rules table renders one <tr> per rule. Two display forms exist:
#   simple   : 'Home Depot' » COGS
#   advanced : COGS (Advanced) | description contains 'X' and the cents portion ...
_RULE_SIMPLE_RE = re.compile(r"^\s*['\"‘“]?(?P<pattern>.*?)['\"’”]?\s*»\s*(?P<category>.+?)\s*$")
_RULE_ADVANCED_RE = re.compile(r"^\s*(?P<category>.+?)\s*\(Advanced\)\s*\|\s*(?P<expr>.+?)\s*$")


def _classify_rule(display: str, cell_category: str) -> tuple:
    m = _RULE_ADVANCED_RE.match(display)
    if m:
        return "advanced", m.group("expr"), cell_category or m.group("category")
    m = _RULE_SIMPLE_RE.match(display)
    if m and "»" in display:
        return "simple", m.group("pattern").strip().strip("'\""), cell_category or m.group("category")
    return "unknown", "", cell_category


def _parse_rules_from_html(html: str) -> List[Dict[str, Any]]:
    """Parse category rules from the rules page HTML.

    Anchored on the rule ROW, never on a button's text (a button became icon-only once and
    every rule dropped silently -- 215ee50). Two row shapes are understood:

      current (2026-11-10, fintableMcpDom): <div wire:key="rule-<uuid>"> holding a <p> with
        the display text and a data-flux-badge with the category. All rules render on ONE
        page (258 measured, no paginator in the DOM or the livepage-rules snapshot).
      legacy  (2026-09-05): one <tr> per rule with a $dispatch('view-rule', {rid}) button,
        display in the first <td>, category in the second.

    A row we cannot classify is EMITTED as kind="unknown" with its raw text, never
    discarded: an unparseable rule is a finding for the caller, not a missing one.
    """
    soup = BeautifulSoup(html, "html.parser")
    rules: List[Dict[str, Any]] = []

    for row in soup.find_all("div", attrs={"wire:key": re.compile(r"^rule-")}):
        p = row.find("p")
        display = p.get_text(" ", strip=True) if p else ""
        badge = row.find(attrs={"data-flux-badge": True})
        kind, pattern, category = _classify_rule(display, badge.get_text(" ", strip=True) if badge else "")
        rules.append({"id": row["wire:key"][len("rule-"):], "pattern": pattern,
                      "category": category, "kind": kind, "display": display})
    if rules:
        return rules

    seen_rows = set()
    for el in soup.find_all(attrs={"wire:click": re.compile(r"view-rule")}):
        row = el.find_parent("tr")
        if row is None or id(row) in seen_rows:
            continue
        seen_rows.add(id(row))
        rid_match = re.search(r"rid:\s*'([^']+)'", el.get("wire:click", ""))
        cells = row.find_all("td")
        display = cells[0].get_text(" ", strip=True) if cells else row.get_text(" ", strip=True)
        # The second cell is the category on its own -- authoritative, and free of the
        # quoting/guillemet games the display cell plays.
        cell_category = cells[1].get_text(" ", strip=True) if len(cells) > 1 else ""
        kind, pattern, category = _classify_rule(display, cell_category)
        rules.append({"id": rid_match.group(1) if rid_match else "", "pattern": pattern,
                      "category": category, "kind": kind, "display": display})

    return rules


def _parse_transactions_from_html(html: str) -> List[Dict[str, Any]]:
    """Parse transactions from the transactions page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    transactions = []

    # Current DOM (measured live 2026-10-10): one <div data-transaction-row wire:key="tx-..."> per
    # transaction, no table -- the only <table> on the page is the date-picker calendar.
    for row in soup.find_all(attrs={"data-transaction-row": True}):
        acct = row.find(attrs={"dusk": "recent-transaction-account"})
        amt = row.find("span", class_="tabular-nums")
        desc_p = amt.find_parent("p") if amt else None
        when = row.find("time")
        date_span = when.find_next_sibling("span") if when else None
        badge = row.find(attrs={"data-flux-badge": True})
        txn = {
            "id": (row.get("wire:key") or "").removeprefix("tx-"),
            "date": date_span.get_text(strip=True) if date_span else "",
            "datetime": when.get("datetime", "") if when else "",
            "description": (desc_p.get("title") or "").strip() if desc_p else "",
            "amount": amt.get_text(strip=True) if amt else "",
            "category": badge.get("title", "").strip() if badge else "",
            "account": acct.get_text(strip=True) if acct else "",
        }
        transactions.append(txn)
    if transactions:
        return transactions

    # Legacy DOM: transactions in a table
    table = soup.find("table")
    if not table:
        return transactions

    rows = table.find_all("tr")
    for row in rows[1:]:  # Skip header
        cells = row.find_all("td")
        if len(cells) >= 3:
            txn = {
                "date": cells[0].get_text(strip=True) if len(cells) > 0 else "",
                "description": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                "amount": cells[2].get_text(strip=True) if len(cells) > 2 else "",
            }
            if len(cells) > 3:
                txn["category"] = cells[3].get_text(strip=True)
            if len(cells) > 4:
                txn["account"] = cells[4].get_text(strip=True)
            transactions.append(txn)

    return transactions


# ---------------------------------------------------------------------------
# Error Handler
# ---------------------------------------------------------------------------
def _handle_error(e: Exception) -> str:
    """Format errors consistently across all tools."""
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 401 or status == 419:
            return (
                f"Error: Authentication failed (HTTP {status}). Your session has likely expired. "
                "Please re-export your cookies from Chrome DevTools and update FINTABLE_COOKIES."
            )
        if status == 403:
            return "Error: Permission denied. Check that your account has access to this resource."
        if status == 404:
            return "Error: Page not found. The Fintable app structure may have changed."
        if status == 422:
            body = e.response.text[:500]
            return f"Error: Validation failed (HTTP 422). Details: {body}"
        if status == 429:
            return "Error: Rate limited. Please wait a moment before trying again."
        return f"Error: HTTP {status} — {e.response.text[:300]}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. Fintable may be slow — try again."
    if isinstance(e, RuntimeError) and "Authentication" in str(e):
        return str(e)
    return f"Error: {type(e).__name__}: {str(e)[:300]}"


# ===========================================================================
# TOOLS — Read Operations
# ===========================================================================


class ListAccountsInput(BaseModel):
    """Input for listing bank accounts."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


@mcp.tool(
    name="fintable_list_accounts",
    annotations={
        "title": "List Bank Accounts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def fintable_list_accounts(params: ListAccountsInput) -> str:
    """List all bank accounts connected to Fintable with balances and latest transaction dates.

    Returns account names, balances, latest transaction dates, and provider/bank/account IDs.
    Use this to get an overview of all connected financial accounts.

    Returns:
        str: JSON list of accounts with name, balance, latest_transaction, provider, bank_id, account_id.
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "accounts")
            accounts = _parse_accounts_from_html(html)
            _silent_zero_guard(
                "accounts", html, len(accounts),
                "one <li wire:key=\"home-account-acc_...\"> per account inside a "
                "<section wire:key=\"home-connection-group-...\">",
            )
            return json.dumps({"total": len(accounts), "accounts": accounts}, indent=2)
    except Exception as e:
        return _handle_error(e)


class ListCategoriesInput(BaseModel):
    """Input for listing categories."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


@mcp.tool(
    name="fintable_list_categories",
    annotations={
        "title": "List Categories",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def fintable_list_categories(params: ListCategoriesInput) -> str:
    """List all transaction categories configured in the Fintable categorizer.

    Categories are organized into groups (e.g., COGS, Expense, Income).
    Use this to see what categories exist before creating new ones or rules.

    Returns:
        str: JSON list of categories with their names.
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "categorizer")
            categories = _parse_categories_from_html(html)
            _silent_zero_guard(
                "categories", html, len(categories),
                "one <div wire:key=\"category-<slug>_<cid>\"> per category with its name in a <p>",
            )
            return json.dumps({"total": len(categories), "categories": categories}, indent=2)
    except Exception as e:
        return _handle_error(e)


class ListRulesInput(BaseModel):
    """Input for listing categorization rules."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    page: Optional[int] = Field(default=1, description="Always 1: Fintable renders every rule on one page", ge=1)


@mcp.tool(
    name="fintable_list_rules",
    annotations={
        "title": "List Category Rules",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def fintable_list_rules(params: ListRulesInput) -> str:
    """List all categorization rules. Rules auto-categorize transactions based on description patterns.

    Each rule has a pattern (e.g., 'Home Depot') and a target category (e.g., 'COGS').
    When 'Run All Rules' is triggered, transactions matching the pattern get categorized.

    Args:
        params: page (always 1 -- every rule is on one page; page>1 is refused).

    Returns:
        str: JSON list of rules with id, pattern, category, and display text.
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "rules")

            # fintableMcpDom (2026-11-10): every rule renders on the one page -- 258 measured,
            # no paginator in the DOM and none in the livepage-rules snapshot. Page 1 IS all
            # of them; a page 2 does not exist, so asking for it is refused, not answered [].
            if params.page and params.page > 1:
                raise ValueError(
                    f"page={params.page}: Fintable renders ALL rules on a single page; "
                    "call with page=1 (the default) to get every rule."
                )
            rules = _parse_rules_from_html(html)
            _silent_zero_guard(
                "rules", html, len(rules),
                "one <div wire:key=\"rule-<uuid>\"> per rule (or a legacy <tr> with a view-rule button)",
            )
            by_kind: Dict[str, int] = {}
            for r in rules:
                by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
            return json.dumps(
                {"total": len(rules), "page": params.page, "by_kind": by_kind, "rules": rules},
                indent=2,
            )
    except Exception as e:
        return _handle_error(e)


class ListTransactionsInput(BaseModel):
    """Input for listing transactions."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    search: Optional[str] = Field(default=None, description="Search string to filter transactions by description", max_length=200)
    page: Optional[int] = Field(default=1, description="Page number", ge=1)


@mcp.tool(
    name="fintable_list_transactions",
    annotations={
        "title": "List Transactions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def fintable_list_transactions(params: ListTransactionsInput) -> str:
    """List transactions from the Fintable transactions page.

    Supports searching by description and pagination. Shows date, description,
    amount, category, and account for each transaction.
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "transactions")

            # SM 1218196401036558: the initial GET never renders the grid at all -- it is a
            # Livewire component that paints client-side, so page 1 with no search used to skip
            # this block entirely and parse the pre-render HTML (0 <table> elements, every time).
            # The component must always be asked to render, not just when paginating/searching.
            # Fintable renamed the component transactions-table -> transactions-list (measured live
            # 2026-10-10, SM 1219341347963917); keep the old name as a fallback.
            snap = snapshots.get("transactions-list") or snapshots.get("transactions-table")
            if snap:
                if params.search:
                    result = await _livewire_call(
                        client, csrf, snap["snapshot_raw"],
                        "$refresh", [],
                        updates={"search": params.search},
                    )
                elif params.page and params.page > 1:
                    result = await _livewire_call(
                        client, csrf, snap["snapshot_raw"],
                        "gotoPage", [params.page, "page"],
                    )
                else:
                    result = await _livewire_call(
                        client, csrf, snap["snapshot_raw"],
                        "$refresh", [],
                    )
                if "components" in result:
                    for comp in result.get("components", []):
                        effects_html = comp.get("effects", {}).get("html", "")
                        if effects_html:
                            html = effects_html

            transactions = _parse_transactions_from_html(html)
            # "no rows in the table" and "no table at all" are DIFFERENT STATES. The first is
            # a real empty result a caller can act on; the second is the scrape losing the
            # page. Measured 2026-09-05: this route returns a 200 with ZERO <table> elements
            # (the grid is rendered client-side by Livewire), so the friendly
            # "No transactions found" below was unreachable-as-true and every caller was
            # told the account was empty. Separate them; the DOM failure raises.
            _soup = BeautifulSoup(html, "html.parser")
            if not _soup.find(attrs={"data-transaction-row": True}) and not _soup.find("table"):
                _silent_zero_guard(
                    "transactions", html, 0,
                    "a <table> of transactions in the server-rendered HTML (this route now "
                    "renders the grid client-side via Livewire -- the table must be fetched "
                    "from the livewire component, see SM 1218170437065088)",
                )
            if not transactions:
                return "No transactions found. Try adjusting your search or check that transactions are synced."
            return json.dumps({
                "total": len(transactions),
                "page": params.page,
                "search": params.search,
                "transactions": transactions,
            }, indent=2)
    except Exception as e:
        return _handle_error(e)


# ===========================================================================
# TOOLS — Write Operations
# ===========================================================================


class CreateCategoryInput(BaseModel):
    """Input for creating a new category."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(
        ...,
        description="Name of the new category (e.g., 'Office Supplies', 'Shipping Costs')",
        min_length=1,
        max_length=100,
    )
    group_header: Optional[str] = Field(
        default=None,
        description=(
            "Category group header to place this under (e.g., 'Expense', 'COGS', 'Income'). "
            "If not specified, creates a standalone category. "
            "Use an existing group name or type a new one to create a new group."
        ),
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Category name cannot be empty")
        return v.strip()


@mcp.tool(
    name="fintable_create_category",
    annotations={
        "title": "Create Category",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def fintable_create_category(params: CreateCategoryInput) -> str:
    """Create a new transaction category in Fintable.

    The category will appear in the categorizer sidebar and can be used in rules.
    Use group_header to place the category under a group (e.g., 'Expense', 'COGS', 'Income').
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "categorizer")

            snap = snapshots.get("modal-new-category")
            if not snap:
                snap = snapshots.get("sidebar-category-selector")
            if not snap:
                return "Error: Could not find the category creation component. The page structure may have changed."

            updates = {"name": params.name}
            if params.group_header:
                updates["header"] = params.group_header

            result = await _livewire_call(
                client, csrf, snap["snapshot_raw"],
                "save", [],
                updates=updates,
            )

            if result and "components" in result:
                return json.dumps({
                    "success": True,
                    "message": f"Category '{params.name}' created successfully"
                              + (f" under group '{params.group_header}'" if params.group_header else "")
                              + ".",
                    "note": "The category is now available in the categorizer sidebar and can be used in rules.",
                })
            return json.dumps({
                "success": True,
                "message": f"Category '{params.name}' creation request sent. Verify in the Fintable UI.",
            })
    except Exception as e:
        return _handle_error(e)


class CreateBulkCategoriesInput(BaseModel):
    """Input for creating multiple categories at once."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    names: List[str] = Field(
        ...,
        description="List of category names to create (e.g., ['Office Supplies', 'Shipping', 'Packaging'])",
        min_length=1,
        max_length=50,
    )
    group_header: Optional[str] = Field(
        default=None,
        description="Category group to place all categories under (e.g., 'Expense', 'COGS', 'Income').",
    )

    @field_validator("names")
    @classmethod
    def validate_names(cls, v: List[str]) -> List[str]:
        cleaned = [n.strip() for n in v if n.strip()]
        if not cleaned:
            raise ValueError("At least one non-empty category name is required")
        return cleaned


@mcp.tool(
    name="fintable_create_bulk_categories",
    annotations={
        "title": "Create Multiple Categories",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def fintable_create_bulk_categories(params: CreateBulkCategoriesInput) -> str:
    """Create multiple transaction categories at once — the batch operation that saves you
    from clicking through the UI 20 times!

    Each category is created sequentially with proper page state management.
    """
    results = {"created": [], "failed": []}
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "categorizer")
            snap = snapshots.get("modal-new-category") or snapshots.get("sidebar-category-selector")
            if not snap:
                return "Error: Could not find category creation component."

            current_snapshot = snap["snapshot_raw"]

            for name in params.names:
                try:
                    updates = {"name": name}
                    if params.group_header:
                        updates["header"] = params.group_header

                    result = await _livewire_call(
                        client, csrf, current_snapshot,
                        "save", [],
                        updates=updates,
                    )

                    # Update snapshot for next call (Livewire returns updated snapshot)
                    if result and "components" in result:
                        for comp in result["components"]:
                            new_snap = comp.get("snapshot", "")
                            if new_snap:
                                current_snapshot = new_snap
                                break

                    results["created"].append(name)
                    logger.info(f"Created category: {name}")

                except Exception as e:
                    results["failed"].append({"name": name, "error": str(e)[:200]})
                    logger.error(f"Failed to create category '{name}': {e}")
                    # Re-fetch page to get fresh snapshot after error
                    try:
                        html, csrf, snapshots = await _fetch_page(client, "categorizer")
                        snap = snapshots.get("modal-new-category") or snapshots.get("sidebar-category-selector")
                        if snap:
                            current_snapshot = snap["snapshot_raw"]
                    except Exception:
                        pass

        return json.dumps({
            "total_requested": len(params.names),
            "created_count": len(results["created"]),
            "failed_count": len(results["failed"]),
            "not_attempted": len(params.rules) - len(results["created"]) - len(results["failed"]),
            "created": results["created"],
            "failed": results["failed"],
        }, indent=2)
    except Exception as e:
        return _handle_error(e)


class CreateRuleInput(BaseModel):
    """Input for creating a categorization rule."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    pattern: str = Field(
        ...,
        description="Text pattern to match in transaction descriptions (e.g., 'Home Depot', 'Amazon', 'Uber')",
        min_length=1,
        max_length=200,
    )
    category: str = Field(
        ...,
        description="Category name to assign matching transactions to (e.g., 'COGS', 'Marketing', 'Supplies')",
        min_length=1,
        max_length=100,
    )
    expect_matched: Optional[int] = Field(
        default=None,
        description="If set, refuse to save unless Fintable's 'Preview matches' step reports exactly this many matched transactions (saving applies the rule retroactively).",
        ge=0,
    )

    @field_validator("pattern", "category")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Value cannot be empty")
        return v.strip()


# fintableRuleWriter (2026-11-10): the old writer guessed a component ("create-rule") and a
# method ("createSimpleRule") against a DOM Fintable has since redesigned, then returned
# {"success": true} without looking. The 2026-11-10 rules page carries ONE rule editor, the
# `modal-rule` Livewire component, whose snapshot data is
#   {rid, step, showModal, viewOnly, text, advancedPrompt, exampleTransactionJson,
#    generatedJsonLogic, isLoading, generationError, cid, ruleType}
# with a `selectRuleType` action at step 0. A simple rule is (text, cid). Probed live
# 2026-11-10 (inning 3, scripts/probe_rule_modal.py): the editor is a 3-step wizard whose
# snapshot must be CHAINED -- selectRuleType{ruleType} -> step 1 (wire:model text/cid, button
# `test` "Preview matches") -> step 2 ("Matched N transactions", button `save` "Save and apply
# rule": applies to all matching history and future rows, manual choices kept). `save` sent
# against a step-0 snapshot does nothing. The POST-VERIFY still decides success.
_RULE_COMPONENT = "modal-rule"
_RULE_SELECT_METHOD = "selectRuleType"
_RULE_PREVIEW_METHOD = "test"
_RULE_SAVE_METHOD = "save"


def _preview_matched(html: str) -> Optional[int]:
    m = re.search(r"Matched\s+([\d,]+)\s+transactions?", re.sub(r"<[^>]+>", " ", html))
    return int(m.group(1).replace(",", "")) if m else None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()


def _resolve_category_id(categories: List[Dict[str, Any]], name: str) -> str:
    """Category NAME -> cid. Refuses a missing name (this tool never creates categories) and
    an ambiguous one (the same name under two groups -- clicking 'whichever renders first'
    once filed rules under the wrong supercategory)."""
    hits = [c for c in categories if _norm(c["name"]) == _norm(name)]
    if not hits:
        raise ValueError(f"Category '{name}' does not exist on Fintable; refusing (this tool does not create categories).")
    if len(hits) > 1:
        groups = ", ".join(c["group"] for c in hits)
        raise ValueError(f"Category '{name}' is ambiguous (exists under: {groups}); refusing.")
    return hits[0]["id"]


def _existing_rule_for(rules: List[Dict[str, Any]], pattern: str) -> Optional[Dict[str, Any]]:
    for r in rules:
        if r["kind"] == "simple" and _norm(r["pattern"]) == _norm(pattern):
            return r
    return None


def _verify_rule_created(before: List[Dict[str, Any]], after: List[Dict[str, Any]],
                         pattern: str, category: str) -> Dict[str, Any]:
    """POST-VERIFY. Success means: exactly one rule id appeared, none vanished, and the new
    one is a simple rule with this pattern and this category. Anything else raises with what
    was OBSERVED, so the caller reports UNVERIFIED instead of a success nobody saw."""
    before_ids = {r["id"] for r in before}
    after_ids = {r["id"] for r in after}
    new = [r for r in after if r["id"] not in before_ids]
    gone = sorted(before_ids - after_ids)
    observed = {"before_total": len(before), "after_total": len(after),
                "new_rules": new[:5], "vanished_ids": gone[:5]}
    ok = (len(new) == 1 and not gone and new[0]["kind"] == "simple"
          and _norm(new[0]["pattern"]) == _norm(pattern)
          and _norm(new[0]["category"]) == _norm(category))
    if not ok:
        raise _Unverified(observed)
    return new[0]


class _Unverified(Exception):
    def __init__(self, observed: Dict[str, Any]):
        super().__init__("UNVERIFIED")
        self.observed = observed


@mcp.tool(
    name="fintable_create_rule",
    annotations={
        "title": "Create Category Rule",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def fintable_create_rule(params: CreateRuleInput) -> str:
    """Create a new simple categorization rule ('description contains PATTERN' -> CATEGORY).

    Refuses BEFORE writing if a simple rule with this pattern already exists or the category
    is missing/ambiguous. After writing, re-lists the rules and reports success ONLY if exactly
    one new rule with this pattern and category appeared; otherwise returns success=false with
    error "UNVERIFIED" and what was observed. The result carries the new rule's id.
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "rules")
            before = _parse_rules_from_html(html)
            _silent_zero_guard("rules", html, len(before), "rule rows (pre-create listing)")

            dup = _existing_rule_for(before, params.pattern)
            if dup:
                return json.dumps({
                    "success": False, "error": "DUPLICATE",
                    "message": f"A simple rule for '{params.pattern}' already exists (-> {dup['category']}); nothing written.",
                    "existing": dup,
                })

            cat_html, _, _ = await _fetch_page(client, "categorizer")
            cid = _resolve_category_id(_parse_categories_from_html(cat_html), params.category)

            snap = snapshots.get(_RULE_COMPONENT)
            if not snap:
                return json.dumps({"success": False, "error": "NO_EDITOR",
                                   "message": f"The rules page has no '{_RULE_COMPONENT}' component; nothing written.",
                                   "components": sorted(snapshots)})

            r1 = await _livewire_call(client, csrf, snap["snapshot_raw"], _RULE_SELECT_METHOD, [],
                                      updates={"ruleType": "simple"})
            r2 = await _livewire_call(client, csrf, r1["components"][0]["snapshot"], _RULE_PREVIEW_METHOD, [],
                                      updates={"text": params.pattern, "cid": cid})
            preview = r2["components"][0]
            pdata = json.loads(preview["snapshot"]).get("data", {})
            matched = _preview_matched(preview.get("effects", {}).get("html", ""))
            if pdata.get("step") != 2 or pdata.get("text") != params.pattern or pdata.get("cid") != cid:
                return json.dumps({"success": False, "error": "NO_PREVIEW",
                                   "message": "The editor did not reach its preview step with this rule; nothing saved.",
                                   "observed": {k: pdata.get(k) for k in ("step", "ruleType", "text", "cid")}})
            if params.expect_matched is not None and matched != params.expect_matched:
                return json.dumps({"success": False, "error": "PREVIEW_MISMATCH",
                                   "message": (f"Preview matched {matched} transactions, expected "
                                               f"{params.expect_matched}; nothing saved."),
                                   "preview_matched": matched})
            await _livewire_call(client, csrf, preview["snapshot"], _RULE_SAVE_METHOD, [])

            after_html, _, _ = await _fetch_page(client, "rules")
            after = _parse_rules_from_html(after_html)
            try:
                rule = _verify_rule_created(before, after, params.pattern, params.category)
            except _Unverified as u:
                return json.dumps({
                    "success": False, "error": "UNVERIFIED",
                    "message": (f"Sent '{params.pattern}' -> {params.category} but a re-list did not show "
                                "exactly one new matching rule. Do NOT assume it was created."),
                    "observed": u.observed,
                })
            return json.dumps({
                "success": True, "verified": True,
                "message": f"Rule created and observed: '{params.pattern}' -> {params.category}",
                "rule": rule, "total_rules": len(after), "preview_matched": matched,
            })
    except Exception as e:
        return _handle_error(e)


class CreateBulkRulesInput(BaseModel):
    """Input for creating multiple rules at once."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    rules: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "List of rules to create. Each rule is a dict with 'pattern' and 'category' keys. "
            "Optional 'expect_matched' (int) per rule refuses the save unless the preview matches that many. "
            "Example: [{'pattern': 'Home Depot', 'category': 'COGS'}, {'pattern': 'Uber', 'category': 'Transportation'}]"
        ),
        min_length=1,
        max_length=50,
    )
    stop_on_failure: bool = Field(
        default=True,
        description="Stop at the first rule that is refused or UNVERIFIED (default) instead of writing the rest.",
    )
    run_after_create: bool = Field(
        default=False,
        description="If true, run all rules after creating them to categorize existing transactions.",
    )


@mcp.tool(
    name="fintable_create_bulk_rules",
    annotations={
        "title": "Create Multiple Rules",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def fintable_create_bulk_rules(params: CreateBulkRulesInput) -> str:
    """Create multiple categorization rules, one verified create at a time.

    Each rule maps a transaction description pattern to a category and goes through
    fintable_create_rule, so it counts as created only if a re-list observed it (the
    "created" list carries each new rule's id: that list is the rollback list). Stops at the
    first refusal/UNVERIFIED unless stop_on_failure=false.
    Optionally runs all rules after creation to categorize existing transactions.
    """
    results = {"created": [], "failed": []}
    try:
        for rule_def in params.rules:
            pattern = str(rule_def.get("pattern", "")).strip()
            category = str(rule_def.get("category", "")).strip()
            if not pattern or not category:
                results["failed"].append({
                    "rule": rule_def,
                    "error": "Both 'pattern' and 'category' are required",
                })
                continue
            try:
                input_model = CreateRuleInput(pattern=pattern, category=category,
                                              expect_matched=rule_def.get("expect_matched"))
                result_str = await fintable_create_rule(input_model)
                try:
                    result_data = json.loads(result_str)
                except json.JSONDecodeError:
                    result_data = {"success": False, "error": result_str[:200]}
            except Exception as e:
                result_data = {"success": False, "error": str(e)[:200]}
            if result_data.get("success") and result_data.get("verified"):
                results["created"].append({**result_data["rule"], "preview_matched": result_data.get("preview_matched")})
                continue
            results["failed"].append({"rule": f"'{pattern}' → {category}", "result": result_data})
            if params.stop_on_failure:
                break

        # Optionally run all rules
        ran_rules = False
        if params.run_after_create and results["created"]:
            try:
                run_input = RunAllRulesInput()
                await fintable_run_all_rules(run_input)
                ran_rules = True
            except Exception:
                pass

        return json.dumps({
            "total_requested": len(params.rules),
            "created_count": len(results["created"]),
            "failed_count": len(results["failed"]),
            "not_attempted": len(params.rules) - len(results["created"]) - len(results["failed"]),
            "created": results["created"],
            "failed": results["failed"],
            "rules_executed": ran_rules,
        }, indent=2)
    except Exception as e:
        return _handle_error(e)


class RunAllRulesInput(BaseModel):
    """Input for running all categorization rules."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


@mcp.tool(
    name="fintable_run_all_rules",
    annotations={
        "title": "Run All Category Rules",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def fintable_run_all_rules(params: RunAllRulesInput) -> str:
    """Run all categorization rules to auto-categorize transactions.

    This triggers the same action as clicking 'Run All Rules' in the Fintable UI.
    All rules are applied to uncategorized transactions in priority order.
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "rules")
            snap = snapshots.get("livepage-rules")
            if not snap:
                return "Error: Could not find the rules page component."

            result = await _livewire_call(
                client, csrf, snap["snapshot_raw"],
                "runAllRules", [],
            )

            return json.dumps({
                "success": True,
                "message": "All categorization rules have been executed.",
                "note": "Check fintable_list_transactions to see the updated categories.",
            })
    except Exception as e:
        return _handle_error(e)


class DeleteRuleInput(BaseModel):
    """Input for deleting a categorization rule."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    rule_id: str = Field(
        ...,
        description="The rule ID to delete. Get rule IDs from fintable_list_rules.",
        min_length=1,
    )


@mcp.tool(
    name="fintable_delete_rule",
    annotations={
        "title": "Delete Category Rule",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def fintable_delete_rule(params: DeleteRuleInput) -> str:
    """Delete a categorization rule by its ID.

    Use fintable_list_rules to find rule IDs. This is irreversible.
    Refuses BEFORE writing if the id is not on the rules page. After writing, re-lists and
    reports success ONLY if that id is gone and no other rule vanished; otherwise
    success=false, error "UNVERIFIED", with what was observed. The result carries the
    deleted rule (pattern/category) as the receipt.
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "rules")
            before = _parse_rules_from_html(html)
            _silent_zero_guard("rules", html, len(before), "rule rows (pre-delete listing)")
            target = next((r for r in before if r["id"] == params.rule_id), None)
            if not target:
                return json.dumps({"success": False, "error": "NOT_FOUND",
                                   "message": f"No rule '{params.rule_id}' on the rules page; nothing written."})

            snap = snapshots.get("livepage-rules")
            if not snap:
                return json.dumps({"success": False, "error": "NO_EDITOR",
                                   "message": "The rules page has no 'livepage-rules' component; nothing written."})

            await _livewire_call(
                client, csrf, snap["snapshot_raw"],
                "deleteRule", [params.rule_id],
            )

            after_html, _, _ = await _fetch_page(client, "rules")
            after = _parse_rules_from_html(after_html)
            after_ids = {r["id"] for r in after}
            gone = sorted({r["id"] for r in before} - after_ids)
            if gone != [params.rule_id] or len(after) != len(before) - 1:
                return json.dumps({
                    "success": False, "error": "UNVERIFIED",
                    "message": f"Sent deleteRule('{params.rule_id}') but a re-list did not show exactly that rule gone. Do NOT assume it was deleted.",
                    "observed": {"before_total": len(before), "after_total": len(after),
                                 "vanished_ids": gone[:5], "still_present": params.rule_id in after_ids},
                })
            return json.dumps({
                "success": True, "verified": True,
                "message": f"Rule '{params.rule_id}' deleted and observed gone.",
                "deleted": target, "total_rules": len(after),
            })
    except Exception as e:
        return _handle_error(e)


class SyncAccountsInput(BaseModel):
    """Input for triggering account sync."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


@mcp.tool(
    name="fintable_sync_accounts",
    annotations={
        "title": "Sync Bank Accounts",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def fintable_sync_accounts(params: SyncAccountsInput) -> str:
    """Trigger a sync of all connected bank accounts via Plaid.

    This fetches the latest transactions and balances from your connected banks.
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "accounts")
            snap = snapshots.get("livepage-accounts")
            if not snap:
                return "Error: Could not find the accounts page component."

            result = await _livewire_call(
                client, csrf, snap["snapshot_raw"],
                "save", [],
            )

            return json.dumps({
                "success": True,
                "message": "Account sync triggered. Transactions will update shortly.",
            })
    except Exception as e:
        return _handle_error(e)


class ResyncToAirtableInput(BaseModel):
    """Input for re-syncing categories to Airtable/Google Sheets."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


@mcp.tool(
    name="fintable_resync_spreadsheets",
    annotations={
        "title": "Re-Sync to Spreadsheets",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def fintable_resync_spreadsheets(params: ResyncToAirtableInput) -> str:
    """Re-sync categories and transactions to connected Airtable/Google Sheets integrations.

    Use this after making category changes to push updates to your spreadsheets.
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "categorizer")
            snap = snapshots.get("modal-resync-categories") or snapshots.get("livepage-categorizer")
            if not snap:
                return "Error: Could not find the resync component."

            result = await _livewire_call(
                client, csrf, snap["snapshot_raw"],
                "resyncCategoriesToAirtable", [],
            )

            return json.dumps({
                "success": True,
                "message": "Re-sync to spreadsheets triggered. Check your Airtable/Google Sheets for updates.",
            })
    except Exception as e:
        return _handle_error(e)


# ===========================================================================
# Entry Point
# ===========================================================================
def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments (processed before MCP stdio takes over)."""
    parser = argparse.ArgumentParser(
        description="Unofficial MCP server for fintable.io",
        add_help=False,  # Don't conflict with MCP's own arg handling
    )
    parser.add_argument(
        "--persist-cookies",
        action="store_true",
        default=False,
        help="Enable self-refreshing cookie jar. Saves session cookies to "
             "~/.fintable-mcp-cookies.json and auto-updates them from server "
             "responses. The session stays alive without rookiepy or Chrome.",
    )
    # Parse known args only — let MCP handle anything else
    args, _ = parser.parse_known_args()
    return args


if __name__ == "__main__":
    args = _parse_args()
    if args.persist_cookies:
        _persist_cookies = True
        logger.info("Cookie persistence enabled — session will self-refresh via %s", _cookie_jar_path)
    mcp.run()
