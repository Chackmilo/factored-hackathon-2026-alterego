"""The Vercel deployment builds the dispute API and bundles what it reads at runtime.

Vercel builds the FastAPI app named by pyproject's [tool.vercel] entrypoint into one function and bundles every file
reachable at build time, with no tree-shaking: vercel.json's excludeFiles is the only filter (docs/SUPABASE_VERCEL.md
section 6). These tests keep the entrypoint, the function key and that filter in step, so an exclude never drops a file
the API reads (without data/rag_gate.json the policy explainer turns off silently) and the node_modules the front's
build leaves behind never reaches the bundle.
"""

import json
import os
import re
import runpy
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT_FILE = "src/api/app.py"
NO_DOTENV = "import dotenv; dotenv.load_dotenv = lambda *args, **kwargs: False; "  # python -c finds the .env of any parent folder


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _functions() -> dict:
    return json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))["functions"]


def _excluded(path: str) -> bool:
    """excludeFiles is a brace list of `dir/**` globs (node-glob syntax), the only form these tests read."""
    pattern = _functions()[ENTRYPOINT_FILE]["excludeFiles"]
    assert pattern.startswith("{") and pattern.endswith("}"), pattern
    globs = pattern[1:-1].split(",")
    assert all(re.fullmatch(r"[\w.\-/]+/\*\*", glob) for glob in globs), globs
    return any(path.startswith(glob[:-2]) for glob in globs)


def test_vercel_builds_the_dispute_api_from_its_entrypoint():
    assert _pyproject()["tool"]["vercel"]["entrypoint"] == "src.api.app:app"
    assert set(_functions()) == {ENTRYPOINT_FILE}
    assert (ROOT / ENTRYPOINT_FILE).is_file()


def test_the_entrypoint_loads_the_way_the_vercel_runtime_imports_it():
    """Vercel's runtime executes the entrypoint file as module src.api.app before it imports the src.api package. On
    3 Oct every API route of the first deployment answered FUNCTION_INVOCATION_FAILED: the package __init__ imported the
    app back from the half-loaded module. uvicorn imports the package first, so a local run never saw it."""
    load = ("import importlib.util, sys; "
            f"spec = importlib.util.spec_from_file_location('src.api.app', '{ENTRYPOINT_FILE}'); "
            "module = importlib.util.module_from_spec(spec); sys.modules['src.api.app'] = module; "
            "spec.loader.exec_module(module); print(type(module.app).__name__)")
    result = subprocess.run([sys.executable, "-c", NO_DOTENV + load], cwd=ROOT, env={**os.environ, "APP_ENV": "test"},
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.strip() == "FastAPI"


def test_the_function_bundle_keeps_every_file_the_api_reads():
    for path in ("src/api/app.py", "data/rag_gate.json", "data/policy_corpus.json", "data/fixtures/team_questions.json",
                 "frontend/dist/index.html", "src/llm/prompts/reply_v1.md", "models/fraud_risk_ieee.joblib"):
        assert not _excluded(path), path


def test_the_function_bundle_leaves_out_the_build_and_dev_files():
    for path in ("frontend/node_modules/vite/package.json", "frontend/src/App.tsx", "tests/test_api.py", "docs/PLAN.md",
                 "notebooks/01_problema_y_datos.ipynb", ".agents/skills/README.md", "data/eval/dev_cases.jsonl",
                 "reports/eval_dev.md", "scripts/README.md"):
        assert _excluded(path), path


def test_the_build_step_is_the_front_build_script():
    assert _pyproject()["tool"]["vercel"]["scripts"]["build"] == "python scripts/deploy/vercel_build.py"
    assert (ROOT / "scripts" / "deploy" / "vercel_build.py").is_file()


def test_a_vercel_build_without_the_supabase_keys_fails_before_building(monkeypatch):
    """Without the VITE_SUPABASE_* variables the front would ship the local persona picker, whose routes answer 404 in
    production: the deployment could not sign anyone in, so the build stops instead."""
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("VITE_SUPABASE_URL", raising=False)
    monkeypatch.delenv("VITE_SUPABASE_PUBLISHABLE_KEY", raising=False)
    build = runpy.run_path(str(ROOT / "scripts" / "deploy" / "vercel_build.py"))
    assert build["main"]() == 1


def test_python_is_the_decided_version():
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"
