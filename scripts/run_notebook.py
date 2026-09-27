"""
Root forwarder for scripts/notebooks/run_notebook.py
"""
import runpy
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).parent / "notebooks" / "run_notebook.py"
    runpy.run_path(str(target), run_name="__main__")
