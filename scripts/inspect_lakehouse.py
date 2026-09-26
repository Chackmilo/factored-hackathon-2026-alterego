"""
Root forwarder for scripts/audit/inspect_lakehouse.py
"""
import runpy
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).parent / "audit" / "inspect_lakehouse.py"
    runpy.run_path(str(target), run_name="__main__")
