# mls-mcp

MCP server for real estate **MLS listings** and **demographic data**, with semantic
property search and natural-language schema filtering.

Status: Stage 5 (interface) — the MCP tools that expose the subsystems: listing
search (OData fetch + lexical relevance ranking) and Census ACS demographics.
Underneath sit the typed domain model, the MLS/Census clients, and the shared TTL
response cache with stderr logging.

## Layout

```
pyproject.toml          package manifest + ruff/pytest config
requirements.txt        runtime deps
requirements-dev.txt    dev deps (includes runtime deps)
.env.example            environment contract (copy to .env)
src/mls_mcp/
  __init__.py           package version
  config.py             Settings (pydantic-settings, reads .env / environment)
  cache.py              TTL cache + cached JSON GET shared by the clients
  models.py             domain types: listings, demographics, filters, search
  mls.py                RESO OData client: $filter builder, record parsing, paging
  census.py             Census ACS client: one demographic snapshot per geography
  search.py             natural-language ranking (idf-weighted term coverage)
  server.py             MCPServer instance, tool registrations, entry point
  __main__.py           python -m mls_mcp
  py.typed              PEP 561 marker
tests/                  pytest suite
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements-dev.txt
cp .env.example .env            # fill in MLS / Census credentials
```

Always install into the venv: on Python 3.14 `mcp` needs `anyio>=4.10`, and a global
environment holding an older `anyio` fails at `MCPServer.run()` with
`TypeError: 'function' object is not subscriptable`.

## Run

```bash
python -m mls_mcp                       # stdio transport (default)
mcp dev src/mls_mcp/server.py           # MCP Inspector
```

Register with a client (Claude Desktop / OpenCode) as a stdio server launching
`python -m mls_mcp` with `cwd` set to this repository.

## Tools

| Tool | Purpose |
| --- | --- |
| `server_info` | Server version plus whether MLS, Census and vector-store credentials are configured (no secrets returned) |
| `search_listings` | Natural-language listing search: schema filters go to the OData query, the query string ranks the results (`query`, `top_k`, `city`, `state`, `postal_code`, price/bed/bath/sqft bounds) |
| `get_demographics` | Census ACS snapshot for one geography (`geography` such as `zip code:78704`, optional `in_geography`, `year`) |

## Verify

```bash
ruff check . && ruff format --check .
pytest -q
```

## Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `MLS_API_BASE` | yes | RESO Web API/OData root of the listing feed |
| `MLS_API_KEY` / `MLS_API_SECRET` | yes¹ | MLS client-credentials auth |
| `MLS_API_TOKEN` | no | Static bearer token when the provider skips OAuth |
| `MLS_TOKEN_URL` | with key/secret | OAuth2 client-credentials endpoint for the static-token-free flow |
| `CENSUS_API_KEY` | no | Raises Census ACS rate limits |
| `VECTOR_STORE_URL` / `VECTOR_STORE_COLLECTION` | semantic search | Embedding store for property search |
| `EMBEDDING_MODEL` | no | Embedding model id |
| `LOG_LEVEL`, `HTTP_TIMEOUT_SECONDS`, `CACHE_TTL_SECONDS` | no | Runtime tuning |

¹ or `MLS_API_TOKEN` instead.

Never commit `.env`; it is gitignored.
