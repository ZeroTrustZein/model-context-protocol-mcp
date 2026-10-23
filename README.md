# mls-mcp

MCP server for real estate **MLS listings** and **demographic data**, with
natural-language property search and schema filtering.

Status: complete (`0.1.0`). Three tools over stdio: listing search (RESO/OData
fetch + lexical relevance ranking) and Census ACS demographics, on top of a typed
domain model, two async HTTP clients, and a shared TTL response cache.

## Layout

```
pyproject.toml          package manifest + ruff/pytest config
requirements.txt        runtime deps
requirements-dev.txt    dev deps (-r requirements.txt + pytest, ruff)
.env.example            environment contract (copy to .env)
src/mls_mcp/
  __init__.py           package version (from installed metadata)
  config.py             Settings (pydantic-settings, reads .env / environment)
  cache.py              TTLCache + fetch_json, shared by both clients
  models.py             domain types: listings, demographics, filters, search
  mls.py                RESO OData client: $filter builder, record parsing, paging
  census.py             Census ACS client: one demographic snapshot per geography
  search.py             natural-language ranking (idf-weighted term coverage)
  server.py             MCPServer instance, tool registrations, entry point
  __main__.py           python -m mls_mcp
  py.typed              PEP 561 marker
tests/                  pytest suite (offline, stubbed transports)
.github/workflows/ci.yml  lint + test on Python 3.10-3.14
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
| `server_info` | Server name/version plus whether MLS, Census and vector-store credentials are configured (no secrets returned) |
| `search_listings` | Natural-language listing search. `query` ranks results; the optional filters go to OData. Params: `query`, `top_k` (default 10), `city`, `state`, `postal_code`, `min_price`, `max_price`, `min_bedrooms`, `min_bathrooms`, `min_sqft`, `max_sqft` |
| `get_demographics` | Census ACS snapshot for one geography. Params: `geography` (`zip code:78704`, `county:453`, `state:48`), optional `in_geography` (`state:48`), `year` (default 2023) |

`search_listings` returns `{query, matches[], total_considered}`; each match is
`{listing, score, highlights}`. Scores are relative within one response, not
comparable across queries.

`get_demographics` returns population, households, median household income, median
age and median home value. ACS missing-value sentinels (negative numbers) become
`null`. The payload also carries `unemployment_rate` and `poverty_rate`, currently
always `null` (no ACS variable is mapped yet).

## How it works

1. `search_listings` builds an OData `$filter` from the structured filters, fetches
   the newest listings (`$orderby ModificationTimestamp desc`, paged 100 at a time,
   pool of `max(top_k * 5, 50)`), then re-checks the filters client-side.
2. `search.py` scores each candidate by idf-weighted coverage of the query terms
   over description, features, street/city/state and property type; a listing with
   no matching term is dropped. Ranking is lexical by design — no embedding backend
   is needed. The `SearchResults`/`PropertyMatch` shape leaves room for a vector
   store to supply `score`/`highlights` later.
3. `cache.py` memoizes GET responses for `CACHE_TTL_SECONDS`, keyed by path+params.
   Both clients accept an injected `httpx` transport and cache, which is how the
   tests run offline.

Logs go to stderr (`LOG_LEVEL`) so the stdio transport stays clean.

## Verify

```bash
ruff check . && ruff format --check .
pytest -q
```

CI runs the same two steps on Python 3.10-3.14.

## Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `MLS_API_BASE` | yes | RESO Web API/OData root of the listing feed |
| `MLS_API_KEY` / `MLS_API_SECRET` / `MLS_TOKEN_URL` | yes¹ | OAuth2 client-credentials flow |
| `MLS_API_TOKEN` | yes¹ | Static bearer token, for providers without OAuth |
| `CENSUS_API_BASE` | no | Defaults to `https://api.census.gov/data` |
| `CENSUS_API_KEY` | no | Raises Census ACS rate limits |
| `VECTOR_STORE_URL` / `VECTOR_STORE_COLLECTION` | no | Reserved for the embedding backend; reported by `server_info` only |
| `EMBEDDING_MODEL` | no | Reserved, same as above |
| `LOG_LEVEL`, `HTTP_TIMEOUT_SECONDS`, `CACHE_TTL_SECONDS` | no | Runtime tuning (defaults `INFO`, `30`, `300`) |

¹ one of the two credential sets must be configured, or `search_listings` raises
`RuntimeError: MLS credentials missing`.

Never commit `.env`; it is gitignored.

## Troubleshooting

- `RuntimeError: MLS credentials missing` — set `MLS_API_TOKEN`, or all three of
  `MLS_API_KEY`, `MLS_API_SECRET`, `MLS_TOKEN_URL`.
- `LookupError: no ACS data for ...` — the geography/year has no ACS rows; check the
  `for` clause spelling (`zip code:78704`, not `ZIP 78704`).
- Empty matches with a non-empty pool — no listing shared a query term; the ranking
  is literal word matching, so drop filler words from `query` and lean on filters.
- Client disconnects at startup — a log handler writing to stdout, or `anyio` too
  old; see Setup.
