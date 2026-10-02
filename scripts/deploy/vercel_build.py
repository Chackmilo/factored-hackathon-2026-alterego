"""Vercel build step (pyproject [tool.vercel.scripts]): compile the React front that src/api/app.py mounts at "/".

Vercel runs it after installing the Python dependencies and before it bundles the function. Vite reads the deployment's
VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY from the environment. Without them the front would ship the local
persona picker, whose routes answer 404 outside development and test, so on Vercel the build stops instead.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
SUPABASE_KEYS = ("VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY")


def main() -> int:
    missing = [name for name in SUPABASE_KEYS if not os.getenv(name)]
    if os.getenv("VERCEL") and missing:
        print(f"vercel_build: set {', '.join(missing)} for this environment in the Vercel project", file=sys.stderr)
        return 1
    npm = shutil.which("npm")
    if npm is None:
        print("vercel_build: npm not found; the build image needs Node.js to compile the front", file=sys.stderr)
        return 1
    for args in (["ci"], ["run", "build"]):
        subprocess.run([npm, *args], cwd=FRONTEND, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
