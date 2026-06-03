# know_kernel

A kernel-design intelligence system. Ingests OS/kernel papers, proposals,
code, and discussions; extracts abstract concepts while enforcing license
contamination boundaries; serves two consumer modes — human navigation
and LLM-assisted design.

## What it does

- **Ingests** documents, source repos, papers, mailing list discussions
- **Scans** licenses and classifies artifacts (Class A: licensed evidence,
  Class B: clean abstractions)
- **Extracts** abstract design concepts via LLM — mechanisms, invariants,
  tradeoffs, assumptions — never raw code
- **Serves** a structured knowledge base to humans (web UI) and LLMs
  (MCP server)

The system does not say "here is how Linux implements X." It says "this
source discusses a design pattern where X is handled by separating policy
from mechanism, using Y invariant, with tradeoff Z."

## Architecture

Four apps + one shared library, all Python:

| Component | Type | Purpose |
|-----------|------|---------|
| `know_kernel.graph` | Shared library | SQLite-backed graph engine, admissibility rules |
| `know_kernel.ingest` | Batch service | Document parsing, license scanning, LLM extraction |
| `know_kernel.web` | Server | FastAPI + Jinja2/HTMX human-facing views |
| `know_kernel.export` | CLI utility | Snapshot exporter — contamination gate for LLM path |
| `know_kernel.mcp_server` | Container service | MCP server for opencode (Class B-only) |

See [docs/architecture.md](docs/architecture.md) for the full design.

## The contamination firewall

The boundary is between **humans and LLMs**, not between networks.

- Humans see everything (Class A + B) — legally established that reading
  GPL code doesn't contaminate kernel contributions
- LLMs get only Class B (clean abstractions) — an LLM that saw licensed
  implementation details creates an unprovable contamination question

The **snapshot exporter** is the single enforcement point. It filters
Class A content out of the master DB, producing a Class B-only snapshot
that the MCP server ships with.

## Deployment

```
Internet side                 Air-gapped network
┌─────────────┐               ┌──────────────┐
│  Ingestion   │──snapshot──→ │  Web API      │ (humans)
│  service     │              │               │
│  (master DB) │              │  Dev containers│
└─────────────┘              │  ├─ MCP server │ (LLM via opencode)
                              │  ├─ B-only DB │
                              │  └─ tooling   │
                              └──────────────┘
```

## CLI entry points

```
kk-ingest   # Run the ingestion pipeline
kk-web      # Start the web API server
kk-export   # Export a Class B-only snapshot
kk-mcp      # Start the MCP server
```

## Development

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
pytest
```

## License

Proprietary.
