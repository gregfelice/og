#!/usr/bin/env python3
"""Register the og-context MCP server in Claude Code settings.

Reads/updates ~/.claude/settings.json to add the og-context server entry.
"""

import json
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

MCP_ENTRY = {
    "command": "og-mcp",
    "args": [],
    "env": {},
}


def main():
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    settings = {}
    if SETTINGS_PATH.exists():
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

    mcp_servers = settings.setdefault("mcpServers", {})

    if "og-context" in mcp_servers:
        print(f"og-context already registered in {SETTINGS_PATH}")
        print(f"  Current: {json.dumps(mcp_servers['og-context'])}")
        return

    mcp_servers["og-context"] = MCP_ENTRY

    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"Registered og-context MCP server in {SETTINGS_PATH}")
    print(f"  Entry: {json.dumps(MCP_ENTRY)}")
    print("\nRestart Claude Code to pick up the new MCP server.")


if __name__ == "__main__":
    main()
