"""
Root forwarder for scripts/data_ops/verify_s3_connection.py
"""
import runpy
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).parent / "data_ops" / "verify_s3_connection.py"
    runpy.run_path(str(target), run_name="__main__")
