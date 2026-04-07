#!/usr/bin/env python3
"""
Unofficial MCP Server for Fintable.io

Fintable.io uses Plaid to consolidate bank accounts into Airtable with a
categorization engine. This MCP server communicates with Fintable's Laravel
Livewire 3 backend by maintaining an authenticated session, extracting
Livewire component snapshots from page HTML, and making Livewire update
calls to invoke server-side methods.

Authentication (in priority order):
    1. Auto-extract: If rookiepy is installed, cookies are pulled directly from
       Chrome's local cookie database on each run. Zero manual effort.
       Install with: pip install rookiepy
    2. FINTABLE_COOKIES env var: Full cookie header string from Chrome DevTools.
    3. FINTABLE_SESSION_COOKIE env var: Just the session cookie value.
"""

import json
import re
import os
import sys
import logging
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
    """Build the Cookie header from browser, environment, or raise an error.

    Priority order:
    1. rookiepy auto-extraction from Chrome (if installed)
    2. FINTABLE_COOKIES env var (full cookie string)
    3. FINTABLE_SESSION_COOKIE env var (just session value)
    """
    # Try auto-extraction from Chrome first
    browser_cookies = _extract_cookies_from_browser()
    if browser_cookies:
        return browser_cookies

    # Fall back to env vars
    cookies = os.environ.get("FINTABLE_COOKIES", "")
    if cookies:
        return cookies
    session = os.environ.get("FINTABLE_SESSION_COOKIE", "")
    if session:
        return f"fintable_session={session}"
    raise RuntimeError(
        "Authentication not configured. Either:\n"
        "  1. Install rookiepy (pip install rookiepy) and be logged into fintable.io in Chrome\n"
        "  2. Set FINTABLE_COOKIES env var (full cookie string from Chrome DevTools)\n"
        "  3. Set FINTABLE_SESSION_COOKIE env var (just the session cookie value)"
    )


def _get_client() -> httpx.AsyncClient:
    """Create an httpx client with auth cookies and standard headers."""
    cookie_header = _build_cookie_header()
    return httpx.AsyncClient(
        base_url=BASE_URL,
        headers={
            "Cookie": cookie_header,
            "User-Agent": "FintableMCP/1.0",
            "Accept": "text/html, application/json",
        },
        timeout=30.0,
        follow_redirects=True,
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
    """Parse bank accounts and balances from the accounts page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    accounts = []

    # Find bank connection sections — each has account links
    for link in soup.find_all("a", href=re.compile(r"/dash/v2/link/overview/account/")):
        text = link.get_text(strip=True, separator=" ")
        href = link.get("href", "")

        # Extract account name and ID from the link text and href
        parts = href.split("/")
        provider = parts[6] if len(parts) > 6 else ""
        bank_id = parts[7] if len(parts) > 7 else ""
        account_id = parts[8] if len(parts) > 8 else ""

        # Parse name, balance, and latest transaction from text
        name_match = re.search(r"^(.+?)(?:\s*\$[\d,.-]+|\s*·)", text)
        balance_match = re.search(r"\$([\d,.-]+)", text)
        date_match = re.search(r"Latest transaction:\s*([\d-]+)", text)

        accounts.append({
            "name": name_match.group(1).strip() if name_match else text.split("$")[0].strip(),
            "balance": f"${balance_match.group(1)}" if balance_match else "N/A",
            "latest_transaction": date_match.group(1) if date_match else "N/A",
            "provider": provider,
            "bank_id": bank_id,
            "account_id": account_id,
            "type": "depository / checking",
        })

    return accounts


def _parse_categories_from_html(html: str) -> List[Dict[str, Any]]:
    """Parse categories from the categorizer page sidebar."""
    soup = BeautifulSoup(html, "html.parser")
    categories = []

    # Categories are shown as buttons in the sidebar
    current_group = "Uncategorized"

    # Look for category group headers and individual category buttons
    sidebar = soup.find_all(attrs={"wire:snapshot": True})
    for el in sidebar:
        snapshot_raw = el.get("wire:snapshot", "")
        if "sidebar-category-selector" not in snapshot_raw:
            continue

        # Found the sidebar component — parse its contents
        for child in el.descendants:
            if hasattr(child, "get_text"):
                text = child.get_text(strip=True)
                if child.name == "a" and child.get("href", "").startswith("http"):
                    continue
                wire_click = child.get("wire:click", "") if hasattr(child, "get") else ""
                if "deleteCategory" in str(wire_click):
                    continue

    # Simpler approach: extract from the snapshot data
    for el in soup.find_all(attrs={"wire:snapshot": True}):
        raw = el.get("wire:snapshot", "")
        if "sidebar-category-selector" not in raw:
            continue
        try:
            parsed = json.loads(raw)
            user_data = parsed.get("data", {}).get("user", [])
        except json.JSONDecodeError:
            pass

    # Parse visible category buttons from HTML
    for btn in soup.find_all("button", attrs={"type": "button"}):
        text = btn.get_text(strip=True)
        if not text or len(text) > 50:
            continue
        # Skip non-category buttons
        if text in ("Create category", "Use template", "Reset Categorizer", "Test Rule",
                     "Sync", "Add", "Run All Rules", "Create rule", "Close modal", "Next",
                     "Support", "Re-Sync to Spreadsheets"):
            continue
        wire_click = btn.get("wire:click", "")
        if text and not wire_click.startswith("delete"):
            categories.append({"name": text})

    return categories


def _parse_rules_from_html(html: str) -> List[Dict[str, Any]]:
    """Parse category rules from the rules page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    rules = []

    # Rules are displayed as rows with format: 'pattern' » Category
    for el in soup.find_all(attrs={"wire:click": re.compile(r"view-rule")}):
        wire_click = el.get("wire:click", "")
        rid_match = re.search(r"rid:\s*'([^']+)'", wire_click)
        rid = rid_match.group(1) if rid_match else ""

        text = el.get_text(strip=True)
        # Format: 'Home Depot' » COGS
        parts = text.split("»")
        if len(parts) == 2:
            pattern = parts[0].strip().strip("'\"")
            category = parts[1].strip()
            rules.append({
                "id": rid,
                "pattern": pattern,
                "category": category,
                "display": text,
            })

    return rules


def _parse_transactions_from_html(html: str) -> List[Dict[str, Any]]:
    """Parse transactions from the transactions page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    transactions = []

    # Transactions are in a table
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
            if not accounts:
                return "No accounts found. Make sure you have bank connections set up in Fintable."
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
            if not categories:
                return "No categories found. The categorizer may not be set up yet."
            return json.dumps({"total": len(categories), "categories": categories}, indent=2)
    except Exception as e:
        return _handle_error(e)


class ListRulesInput(BaseModel):
    """Input for listing categorization rules."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    page: Optional[int] = Field(default=1, description="Page number for pagination", ge=1)


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
        params: page number for pagination (rules are paginated).

    Returns:
        str: JSON list of rules with id, pattern, category, and display text.
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "rules")

            # If page > 1, navigate to that page via Livewire
            if params.page and params.page > 1:
                snap = snapshots.get("livepage-rules")
                if snap:
                    result = await _livewire_call(
                        client, csrf, snap["snapshot_raw"],
                        "gotoPage", [params.page, "page"],
                    )
                    if "components" in result:
                        for comp in result["components"]:
                            effects_html = comp.get("effects", {}).get("html", "")
                            if effects_html:
                                html = effects_html

            rules = _parse_rules_from_html(html)
            return json.dumps({"total": len(rules), "page": params.page, "rules": rules}, indent=2)
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

            snap = snapshots.get("transactions-table")
            if snap and (params.search or (params.page and params.page > 1)):
                updates = {}
                if params.search:
                    updates["search"] = params.search
                calls = []
                if params.page and params.page > 1:
                    calls.append({
                        "path": "",
                        "method": "gotoPage",
                        "params": [params.page, "page"],
                    })
                if params.search:
                    result = await _livewire_call(
                        client, csrf, snap["snapshot_raw"],
                        "$refresh", [],
                        updates={"search": params.search},
                    )
                elif calls:
                    result = await _livewire_call(
                        client, csrf, snap["snapshot_raw"],
                        "gotoPage", [params.page, "page"],
                    )
                if "components" in result:
                    for comp in result.get("components", []):
                        effects_html = comp.get("effects", {}).get("html", "")
                        if effects_html:
                            html = effects_html

            transactions = _parse_transactions_from_html(html)
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

    @field_validator("pattern", "category")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Value cannot be empty")
        return v.strip()


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
    """Create a new simple categorization rule.

    A simple rule matches transaction descriptions containing the pattern text
    and assigns them to the specified category. After creating rules, use
    fintable_run_all_rules to apply them.
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "rules")

            snap = snapshots.get("livepage-rules")
            if not snap:
                return "Error: Could not find the rules page component."

            # Try to find a create-rule modal component
            create_snap = None
            for name, data in snapshots.items():
                if "create-rule" in name or "modal-rule" in name:
                    create_snap = data
                    break

            if create_snap:
                result = await _livewire_call(
                    client, csrf, create_snap["snapshot_raw"],
                    "save", [],
                    updates={
                        "ruleType": "simple",
                        "descriptionContains": params.pattern,
                        "category": params.category,
                    },
                )
            else:
                result = await _livewire_call(
                    client, csrf, snap["snapshot_raw"],
                    "createSimpleRule", [params.pattern, params.category],
                )

            return json.dumps({
                "success": True,
                "message": f"Rule created: '{params.pattern}' → {params.category}",
                "note": "Use fintable_run_all_rules to apply this rule to existing transactions.",
            })
    except Exception as e:
        return _handle_error(e)


class CreateBulkRulesInput(BaseModel):
    """Input for creating multiple rules at once."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    rules: List[Dict[str, str]] = Field(
        ...,
        description=(
            "List of rules to create. Each rule is a dict with 'pattern' and 'category' keys. "
            "Example: [{'pattern': 'Home Depot', 'category': 'COGS'}, {'pattern': 'Uber', 'category': 'Transportation'}]"
        ),
        min_length=1,
        max_length=50,
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
    """Create multiple categorization rules at once — batch rule creation!

    Each rule maps a transaction description pattern to a category.
    Optionally runs all rules after creation to categorize existing transactions.
    """
    results = {"created": [], "failed": []}
    try:
        for rule_def in params.rules:
            pattern = rule_def.get("pattern", "").strip()
            category = rule_def.get("category", "").strip()
            if not pattern or not category:
                results["failed"].append({
                    "rule": rule_def,
                    "error": "Both 'pattern' and 'category' are required",
                })
                continue
            try:
                input_model = CreateRuleInput(pattern=pattern, category=category)
                result_str = await fintable_create_rule(input_model)
                result_data = json.loads(result_str)
                if result_data.get("success"):
                    results["created"].append(f"'{pattern}' → {category}")
                else:
                    results["failed"].append({"rule": f"'{pattern}' → {category}", "error": result_str})
            except Exception as e:
                results["failed"].append({"rule": f"'{pattern}' → {category}", "error": str(e)[:200]})

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
    """
    try:
        async with _get_client() as client:
            html, csrf, snapshots = await _fetch_page(client, "rules")
            snap = snapshots.get("livepage-rules")
            if not snap:
                return "Error: Could not find the rules page component."

            result = await _livewire_call(
                client, csrf, snap["snapshot_raw"],
                "deleteRule", [params.rule_id],
            )

            return json.dumps({
                "success": True,
                "message": f"Rule '{params.rule_id}' deleted.",
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
if __name__ == "__main__":
    mcp.run()
