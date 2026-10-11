"""Synthetic FRED-shaped stdio MCP server for one offline acceptance path.

This fixture makes no HTTP requests and reads no credentials. Its observations
are deliberately invented test inputs, not published economic statistics.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


VALUES = (3.8, 3.9, 3.9, 4.0, 4.1, 4.1, 4.2, None, 4.2, 4.1, 4.1, 4.0,
          4.0, None, 4.1, 4.2, 4.3, 4.2)
server = Server("synthetic-official-data")


@server.list_tools()
async def list_tools():
    return [Tool(name="fred_get_series", description="Synthetic offline FRED observations",
                 inputSchema={"type": "object", "required": ["series_id"],
                              "additionalProperties": False, "properties": {
                     "series_id": {"type": "string"}, "observation_start": {"type": "string"},
                     "observation_end": {"type": "string"}, "units": {"type": "string", "enum": ["lin"]},
                     "sort_order": {"type": "string", "enum": ["asc", "desc"]},
                     "offset": {"type": "integer", "minimum": 0},
                     "limit": {"type": "integer", "minimum": 1}}})]


@server.call_tool()
async def call_tool(name, arguments):
    if name != "fred_get_series" or arguments.get("series_id") != "UNRATE":
        raise ValueError("Only the synthetic UNRATE fixture is supported")
    observations = [{"date": f"{2024 + index // 12}-{index % 12 + 1:02d}-01", "value": value}
                    for index, value in enumerate(VALUES)]
    start, end = arguments.get("observation_start", "1900-01-01"), arguments.get("observation_end", "2100-01-01")
    observations = [row for row in observations if start <= row["date"] <= end]
    observations.sort(key=lambda row: row["date"], reverse=arguments.get("sort_order") == "desc")
    offset, limit = arguments.get("offset", 0), arguments.get("limit", 5000)
    payload = {"series_id": "UNRATE", "title": "Synthetic Unemployment Rate",
               "units": "Percent", "frequency": "Monthly", "seasonal_adjustment": "Seasonally Adjusted",
               "notes": "Invented observations for offline acceptance only; not actual economic statistics.",
               "total_observations": len(observations), "data_offset": offset, "data_limit": limit,
               "data": observations[offset:offset + limit]}
    digest = hashlib.sha256((json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")) + "\n").encode()).hexdigest()
    receipt = {"pid": os.getpid(), "tool": name, "arguments": arguments,
               "response_sha256": digest, "observations": len(payload["data"])}
    with Path(os.environ["OFFICIAL_DATA_FIXTURE_RECEIPT"]).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")
    # Match the vendor's JSON inside content[].text, not a fake Python result.
    return [TextContent(type="text", text=json.dumps(payload))]


async def main():
    async with stdio_server() as (incoming, outgoing):
        await server.run(incoming, outgoing, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
