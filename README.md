# Manus Meta Server

## Current status
This project includes:
- Meta endpoints
- Analysis engine
- Reports (Excel / PDF / PPTX / DOCX / HTML)
- Page tools
- Webhooks bootstrap
- Structured FastAPI project layout

## Run locally
cd C:\Users\AcTivE\Desktop\manus_meta_server
python run.py

## Docs
Open:
http://127.0.0.1:8000/docs

## MCP (Model Context Protocol)

The existing FastAPI application also exposes a Streamable HTTP MCP endpoint at
`/mcp/`, providing Meta Ads analysis and management, Facebook Page comments and
automations, Pixel and lead tools, GA4, Clarity, cross-channel journey analysis,
report exports and dashboards.

See [MCP setup and security](docs/MCP_SERVER.md) and
[capability matrix](docs/MCP_CAPABILITY_MATRIX.md).

MCP writes are disabled by default (`MCP_WRITES_ENABLED=false`).
Always validate with the GitHub Actions tests and verify live permissions before
enabling writes or merging to a Railway-deployed branch.
