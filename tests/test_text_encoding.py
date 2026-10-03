"""Files the app and the harness read are UTF-8 on every platform (audit v3, AUD-14).

On Windows the default text encoding is the ANSI code page (cp1252), so a reader that omits `encoding` turns
"México" into "MÃ©xico" and "não" into "nÃ£o" without raising. Each test runs a real reader in a subprocess with
`-X warn_default_encoding`, where a read that relies on the platform default raises EncodingWarning.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PREAMBLE = 'import warnings\nwarnings.filterwarnings("error", category=EncodingWarning, module=r"src\\.")\n'


def run_reader(code: str, tmp_path: Path) -> subprocess.CompletedProcess:
    script = tmp_path / "reader.py"
    script.write_text(PREAMBLE + textwrap.dedent(code), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    return subprocess.run([sys.executable, "-X", "warn_default_encoding", str(script)], cwd=REPO, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_eval_cases_are_read_as_utf8(tmp_path):
    case = {"case_id": "ENC-1", "provenance": "team-generated", "language": "pt", "category": "normal_le_150",
            "customer": {"customer_id": "CLI-ENC", "segment": "Plus", "country": "México"},
            "messages": ["Não reconheço uma cobrança de 20 dólares."], "expected": {"final_outcome": "AUTONOMOUS_RESOLUTION"}}
    suite = tmp_path / "suite.jsonl"
    suite.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")
    done = run_reader(f"""
        from src.eval.cases import load_cases
        case = load_cases({str(suite)!r})[0]
        assert case.customer["country"] == "México", case.customer["country"]
        assert case.messages[0].startswith("Não reconheço"), case.messages[0]
        """, tmp_path)
    assert done.returncode == 0, done.stderr


def test_team_questions_are_read_as_utf8(tmp_path):
    done = run_reader("""
        from src.ops.store import OpsStore
        assert OpsStore(":memory:").seed_questions() > 0
        """, tmp_path)
    assert done.returncode == 0, done.stderr


def test_the_serving_customer_list_is_read_as_utf8(tmp_path):
    customers = tmp_path / "customers.json"
    customers.write_text(json.dumps({"customer_ids": ["CLI-ENC-ñ"]}, ensure_ascii=False), encoding="utf-8")
    done = run_reader(f"""
        from src.data.publish_serving import publish
        try:
            publish("postgresql://nobody@127.0.0.1:9/none", source={str(tmp_path / "missing.duckdb")!r}, customers_path={str(customers)!r})
        except EncodingWarning:
            raise
        except Exception:
            pass  # the customer list was read; the missing lakehouse fails next
        """, tmp_path)
    assert done.returncode == 0, done.stderr


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL (Postgres)")
def test_the_postgres_migrations_are_read_as_utf8(tmp_path):
    done = run_reader(f"""
        from src.ops.store import OpsStore
        OpsStore.apply_postgres_migration({os.environ["TEST_DATABASE_URL"]!r})
        """, tmp_path)
    assert done.returncode == 0, done.stderr


def test_the_reply_prompt_is_read_as_utf8(tmp_path):
    done = run_reader("""
        from src.llm.reply_writer import load_prompt
        text, version = load_prompt()
        assert "⟦1⟧" in text and len(version) == 12
    """, tmp_path)
    assert done.returncode == 0, done.stderr
