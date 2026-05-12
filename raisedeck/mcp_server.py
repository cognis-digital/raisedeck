"""RAISEDECK MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from raisedeck.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-raisedeck[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-raisedeck[mcp]'")
        return 1
    app = FastMCP("raisedeck")

    @app.tool()
    def raisedeck_scan(target: str) -> str:
        """Build and maintain an investor-update + data-room manifest from a metrics YAML, rendering monthly MRR/burn/runway updates with consistent KPIs.. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
