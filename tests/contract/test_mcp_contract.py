import json

import pytest

from tests.contract.mcp_snapshot import SNAPSHOT, capture_tool_contracts


@pytest.mark.anyio
async def test_mcp_tool_contracts_match_snapshot():
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    actual = await capture_tool_contracts()

    assert actual == expected, (
        "MCP tool contract changed. Review the change, then regenerate the snapshot "
        "with `uv run python -m tests.contract.mcp_snapshot`."
    )
