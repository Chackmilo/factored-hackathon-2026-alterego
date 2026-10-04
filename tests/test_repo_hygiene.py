"""Repository settings the public submission depends on (AGENTS.md rule 10, SEC-10)."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def test_the_supabase_mcp_of_the_repo_is_read_only():
    """An agent in this repo inspects production; schema and data change only through reviewed migrations (SEC-10)."""
    url = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["supabase"]["url"]
    assert parse_qs(urlsplit(url).query).get("read_only") == ["true"]
