# CompanyLens MCP Server

CompanyLens exposes its UK company due-diligence tools over the
[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) so any MCP
client — Claude Desktop, Cursor, Continue, or a custom agent — can call them
directly.

---

## What CompanyLens MCP exposes

The server registers **9 tools**:

| Tool | Source | What it does |
|------|--------|--------------|
| `search_companies` | Companies House | Search by name or number; returns candidates with status and locality |
| `get_company_profile` | Companies House | Full profile: status, type, SIC codes, accounts/CS overdue flags, charges/insolvency flags |
| `get_officers` | Companies House | Officer counts: active directors/secretaries and recent resignations |
| `get_filing_history` | Companies House | Most recent filings with date, type, and description |
| `get_psc` | Companies House | Persons with Significant Control register summary |
| `get_charges` | Companies House | Registered charges: outstanding vs satisfied count |
| `get_insolvency` | Companies House | Insolvency case history |
| `check_fca_register` | FCA Register | Whether the company is FCA-authorised; returns FRN and match confidence |
| `search_news` | GDELT DOC 2.0 | Recent news articles mentioning the company (adverse media detection) |

---

## Prerequisites

1. **Python 3.11+** with the CompanyLens package installed:

   ```bash
   cd /path/to/company-lens
   python -m venv .venv
   .venv/bin/pip install -e ".[dev]"
   ```

2. **API keys** in a `.env` file at the project root (copy `.env.example`):

   ```dotenv
   COMPANIES_HOUSE_API_KEY=your_key_here
   FCA_API_EMAIL=your_email@example.com
   FCA_API_KEY=your_fca_key_here
   ```

   The news tool (GDELT) requires no API key.

---

## Running the server

### stdio transport (default — required for Claude Desktop)

```bash
make mcp
# or
.venv/bin/python -m companylens.mcp_server.server
```

### Streamable HTTP transport

```bash
.venv/bin/python -m companylens.mcp_server.server --http
```

The HTTP server listens on `http://localhost:8000/mcp` by default.

---

## Connecting Claude Desktop

Add the following to your `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`,
Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "companylens": {
      "command": "/absolute/path/to/company-lens/.venv/bin/python",
      "args": ["-m", "companylens.mcp_server.server"],
      "cwd": "/absolute/path/to/company-lens",
      "env": {
        "COMPANIES_HOUSE_API_KEY": "your_key_here",
        "FCA_API_EMAIL": "your_email@example.com",
        "FCA_API_KEY": "your_fca_key_here"
      }
    }
  }
}
```

Replace `/absolute/path/to/company-lens` with the real path on your machine.
Restart Claude Desktop after editing the config.

> **Tip:** Instead of hardcoding keys in the config, put them in a `.env` file
> at the project root and omit the `"env"` block — `pydantic-settings` will
> load the file automatically.

---

## Example usage

Once Claude Desktop is connected, try:

> **"What is the risk profile of Tesco PLC?"**

Claude will automatically:

1. Call `search_companies(query="Tesco PLC")` to find the company number.
2. Call `get_company_profile`, `get_officers`, `get_psc`, `get_charges`, and
   `get_insolvency` to gather due-diligence data.
3. Call `check_fca_register` to check for financial-services authorisation.
4. Call `search_news` to look for adverse media coverage.
5. Synthesise the results into a risk summary.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: companylens` | Make sure you used the `.venv` Python path in the config, not the system Python |
| `401` from Companies House tools | Check `COMPANIES_HOUSE_API_KEY` is set correctly |
| Tools not appearing in Claude Desktop | Restart Claude Desktop; check the MCP server log in the Claude Desktop developer console |
| `NotImplementedError` | The client stub for that tool hasn't been fully implemented yet |
