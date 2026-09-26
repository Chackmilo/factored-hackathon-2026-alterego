"""
Root forwarder for scripts/data_ops/inspect_s3_schemas.py
"""
import runpy
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).parent / "data_ops" / "inspect_s3_schemas.py"
    runpy.run_path(str(target), run_name="__main__")
