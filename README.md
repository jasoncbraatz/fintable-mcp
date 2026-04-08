# fintable-mcp

An unofficial MCP (Model Context Protocol) server for [fintable.io](https://fintable.io), enabling AI assistants like Claude to manage your financial categories, rules, and transactions directly — no more clicking through multi-step wizards.

> **Note**: This is a community project, not officially supported by fintable.io. It works by communicating with Fintable's Laravel Livewire 3 backend using your browser session. If you're the Fintable developer and would like to collaborate on an official MCP server or public API, please open an issue — we'd love to work with you! 🤝

---

## What it does

Once installed, you can ask Claude things like:

- *"Create these expense categories: Office Supplies, Shipping, Packaging, Equipment Rental, Software Subscriptions"*
- *"Create rules: 'Staples' → Office Supplies, 'UPS' → Shipping, 'USPS' → Shipping"*
- *"Run all rules to categorize my transactions"*
- *"What's my current account balance at Ally Bank?"*
- *"List all my categorization rules"*

No more going through a 3-page wizard 20 times to set up 20 categories. Just tell Claude what you need.

---

## Tools provided

### Read Operations
| Tool | Description |
|------|-------------|
| `fintable_list_accounts` | List all connected bank accounts with balances |
| `fintable_list_categories` | List all transaction categories |
| `fintable_list_rules` | List categorization rules (with pagination) |
| `fintable_list_transactions` | List/search transactions with optional filtering |

### Write Operations
| Tool | Description |
|------|-------------|
| `fintable_create_category` | Create a single category |
| `fintable_create_bulk_categories` | Create up to 50 categories at once |
| `fintable_create_rule` | Create a categorization rule |
| `fintable_create_bulk_rules` | Create multiple rules at once |
| `fintable_run_all_rules` | Execute all rules on uncategorized transactions |
| `fintable_delete_rule` | Delete a categorization rule |
| `fintable_sync_accounts` | Trigger bank account sync via Plaid |
| `fintable_resync_spreadsheets` | Push updates to Airtable/Google Sheets |

---

## Installation

### Prerequisites

- Python 3.10+
- A [fintable.io](https://fintable.io) account with connected bank accounts
- Claude Desktop (or any MCP-compatible client — Cherry Studio, etc.)

### 1. Clone this repo

```bash
git clone https://github.com/jasoncbraatz/fintable-mcp.git
cd fintable-mcp
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

Or with uv (faster):

```bash
uv pip install -r requirements.txt
```

### 3. Authentication setup

You have two options — automatic (recommended) or manual.

**Option A: Automatic cookie extraction (recommended)**

Install [rookiepy](https://github.com/nicogaspa/rookiepy), which reads cookies directly from Chrome's local database using your OS credentials:

```bash
pip install rookiepy
```

That's it. As long as you're logged into [fintable.io](https://fintable.io) in Chrome, the server grabs fresh cookies on every run. No manual copying, no expiration headaches.

**Option A½: Self-refreshing cookie jar (advanced)**

If you want the server to maintain its own session without needing Chrome or rookiepy after the first run, add the `--persist-cookies` flag to your config (see step 4). This saves session cookies to `~/.fintable-mcp-cookies.json` and auto-updates them from server responses — the session stays alive as long as it doesn't expire server-side between runs.

The initial seed comes from whichever auth method is available (rookiepy, env var, etc.). After that, the server is self-sufficient.

> **Security note**: This stores session cookies on disk. The file is a dotfile in your home directory and isn't advertised anywhere, but anyone with read access to your home folder could find it. If that's a concern, stick with Option A.

> **Note for Python 3.13+**: You may need to set `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` before installing rookiepy:
> ```bash
> PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 pip install rookiepy
> ```

**Option B: Manual cookie export**

If you'd rather not install rookiepy (or you're using a browser other than Chrome):

1. Open Chrome and go to [fintable.io](https://fintable.io) — make sure you're logged in
2. Open DevTools (F12 or Cmd+Option+I)
3. Go to the **Network** tab
4. Click on any request to fintable.io
5. Find the **Cookie** header in Request Headers
6. Copy the entire cookie string

You'll pass this as an environment variable in the next step.

### 4. Configure Claude Desktop

Add the following to your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

**If using rookiepy (Option A)** — no env vars needed:

```json
{
  "mcpServers": {
    "fintable": {
      "command": "python",
      "args": ["/absolute/path/to/fintable-mcp/fintable_mcp.py"]
    }
  }
}
```

**If using `--persist-cookies` (Option A½)** — pair with rookiepy or env var for initial seed:

```json
{
  "mcpServers": {
    "fintable": {
      "command": "python",
      "args": ["/absolute/path/to/fintable-mcp/fintable_mcp.py", "--persist-cookies"]
    }
  }
}
```

**If using manual cookies (Option B)**:

```json
{
  "mcpServers": {
    "fintable": {
      "command": "python",
      "args": ["/absolute/path/to/fintable-mcp/fintable_mcp.py"],
      "env": {
        "FINTABLE_COOKIES": "your_full_cookie_string_here"
      }
    }
  }
}
```

> 💡 Replace `/absolute/path/to/fintable-mcp/fintable_mcp.py` with the actual path where you cloned this repo.

### 5. Restart Claude Desktop

After saving the config, fully quit and relaunch Claude Desktop. The `fintable` tools will appear in Claude's tool list.

---

## Authentication

This server authenticates using your fintable.io browser session cookies — the same cookies your browser uses when you're logged in.

**Cookie resolution order:**

0. **Persisted cookie jar** — If `--persist-cookies` is active and `~/.fintable-mcp-cookies.json` exists with fresh cookies, use those. Self-updates from server `Set-Cookie` headers.
1. **rookiepy** — If installed, cookies are extracted fresh from Chrome's local database on every server start. Zero maintenance.
2. **`FINTABLE_COOKIES` env var** — Full cookie string from Chrome DevTools (fallback if rookiepy isn't installed).
3. **`FINTABLE_SESSION_COOKIE` env var** — Just the session cookie value (simplest manual option).

When `--persist-cookies` is active, whichever method provides the initial cookies will also seed the jar. On subsequent runs, the jar takes priority — and every server response refreshes it automatically.

**Your credentials are never stored to disk by this server** — they live only in memory while the server is running.

### Session Expiration

If you're using **rookiepy (recommended)**, session expiration is handled automatically — fresh cookies are pulled from Chrome on every server start. Just make sure you stay logged into fintable.io in Chrome.

If you're using **manual cookie export**, your cookies will eventually expire. When they do, the server will return an authentication error. Re-export your cookies from Chrome and update the `FINTABLE_COOKIES` environment variable.

---

## How it works (for the curious / developers)

Fintable.io is a Laravel application using Livewire 3 + Alpine.js for its frontend — there's no public REST API. This MCP server:

1. **Authenticates** using your browser session cookies (CSRF token + session cookie)
2. **Fetches pages** to extract Livewire component snapshots from `wire:snapshot` HTML attributes
3. **Makes Livewire protocol calls** — POST requests to the `/livewire-{hash}/update` endpoint with component snapshots, method calls, and property updates
4. **Parses HTML responses** to extract structured data (accounts, categories, rules, transactions)

The Livewire update path includes a hash (e.g., `/livewire-5c7ce5a8/update`) that can change when the app is redeployed. The server auto-discovers this path from the `data-update-uri` HTML attribute on each page load, so it stays resilient across deployments.

---

## Known Issues & Limitations

### Livewire Hash Changes
The Livewire update endpoint includes a build hash (e.g., `/livewire-5c7ce5a8/update`) that changes on each deployment. The server auto-discovers this on every page fetch, but if Fintable significantly restructures their Livewire components or changes component names, things may break. This is inherent to working without an official API.

### HTML Parsing Fragility
Since there's no JSON API, read operations depend on parsing HTML structure. If Fintable redesigns their UI layout, the parsing logic may need updating. This is the biggest maintenance burden of the current approach.

### The Path Forward: JSON Endpoints
The ideal solution is for Fintable to expose lightweight JSON API endpoints. This would:
- Eliminate the fragile HTML parsing
- Remove the Livewire hash dependency
- Enable more reliable integrations
- Open the door for other community tools and integrations
- Be a great selling point for the product (MCP-ready financial tools are a differentiator!)

If you're the Fintable developer reading this — even a handful of authenticated JSON endpoints for categories, rules, and transactions would make this server rock-solid and dramatically easier to maintain. Happy to collaborate on the design. 🚀

---

## Security Model

This server runs **locally** on your machine as a stdio subprocess of your MCP client. It:

- Never exposes a network port
- Never stores credentials to disk
- Only communicates with fintable.io using your existing browser session
- Runs as a single-user, single-client process

By default, session cookies are kept in memory only while the server is running. With rookiepy, they're extracted fresh from Chrome on each launch — no environment variables or config files needed.

If `--persist-cookies` is enabled, cookies are saved to `~/.fintable-mcp-cookies.json` (a dotfile in your home directory). This is an opt-in tradeoff: convenience of a self-refreshing session in exchange for cookies existing on disk. Delete the file at any time to revoke the session.

---

## Contributing

PRs welcome! Some ideas for future improvements:

- Support for transaction date range filtering
- Category group management (create/rename groups)
- Rule priority reordering
- Export categories/rules as JSON for backup
- Support for multiple Fintable accounts

**Note on deletions:** Category deletion is intentionally not supported — that's a destructive action best done through the Fintable web UI where you can see the full impact. A little friction before deleting things is a feature, not a bug.

---

## Disclaimer

This project is not affiliated with, endorsed by, or officially supported by fintable.io. It was built by reverse-engineering the Livewire 3 frontend protocol. Use at your own risk — the underlying Livewire protocol may change without notice.

## License

MIT

<!-- mcp-name: io.github.jasoncbraatz/fintable-mcp -->
