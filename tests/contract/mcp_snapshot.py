"""Capture MCP tool contracts through the protocol, not server internals."""

import asyncio
import json
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.marketplace.server import mcp as marketplace
from mcp_servers.portfolio.server import mcp as portfolio
from mcp_servers.workspace.server import mcp as workspace

SNAPSHOT = Path(__file__).with_name("mcp_tools.snapshot.json")
SERVERS = {"marketplace": marketplace, "portfolio": portfolio, "workspace": workspace}


async def capture_tool_contracts() -> dict[str, list[dict]]:
    contracts = {}
    for name, server in SERVERS.items():
        async with create_connected_server_and_client_session(server) as client:
            response = await client.list_tools()
            contracts[name] = [
                tool.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_none=True,
                )
                for tool in sorted(response.tools, key=lambda tool: tool.name)
            ]
    return contracts


if __name__ == "__main__":
    snapshot = asyncio.run(capture_tool_contracts())
    SNAPSHOT.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {SNAPSHOT}")
