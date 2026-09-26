"""
Root forwarder for scripts/audit/check_data_consistency.py
"""
import runpy
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).parent / "audit" / "check_data_consistency.py"
    runpy.run_path(str(target), run_name="__main__")
