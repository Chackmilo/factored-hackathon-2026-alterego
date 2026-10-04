"""Repository settings the public submission depends on (AGENTS.md rule 10, SEC-10)."""
import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]

# A path under a home directory, written as C:\Users\<name>, /Users/<name>, /home/<name>,
# or the -Users-<name>- slug of a macOS temporary folder.
HOME_PATH = r"([a-z]:[\\/]+users[\\/]+[a-z0-9._~-]+|/users/[a-z0-9._-]+|/home/[a-z0-9._-]+|-users-[a-z0-9._]+-)"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")


def _tracked_lines_matching(pattern: str) -> subprocess.CompletedProcess:
    return _git("grep", "-n", "-I", "-i", "-E", pattern, "--", ".", ":!tests/test_repo_hygiene.py")


def test_the_supabase_mcp_of_the_repo_is_read_only():
    """An agent in this repo inspects production; schema and data change only through reviewed migrations (SEC-10)."""
    url = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["supabase"]["url"]
    assert parse_qs(urlsplit(url).query).get("read_only") == ["true"]


def test_playwright_mcp_snapshots_stay_out_of_git():
    """The browser snapshots of the Playwright MCP record what was typed, sign-in passwords included."""
    assert _git("check-ignore", "-q", ".playwright-mcp/page.yml").returncode == 0


def test_no_tracked_file_holds_a_local_home_directory_path():
    """A path under someone's home directory names its owner and points at files the repo does not have."""
    found = _tracked_lines_matching(HOME_PATH)
    assert found.returncode == 1, found.stdout or found.stderr


def test_no_tracked_file_links_the_data_dictionary():
    """The organizer's data dictionary holds the AWS keys of the data bucket."""
    found = _tracked_lines_matching(r"data dictionary.*drive\.google\.com")
    assert found.returncode == 1, found.stdout or found.stderr
