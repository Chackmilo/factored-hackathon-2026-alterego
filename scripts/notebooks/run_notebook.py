import sys
import nbformat
from nbclient import NotebookClient

notebook_path = sys.argv[1] if len(sys.argv) > 1 else "notebooks/01_problema_y_datos.ipynb"
print(f"Loading notebook: {notebook_path}")

with open(notebook_path, "r", encoding="utf-8") as f:
    nb = nbformat.read(f, as_version=4)

client = NotebookClient(nb, timeout=1200, kernel_name="python3", resources={"metadata": {"path": "."}})

print("Executing notebook...")
try:
    client.execute()
    print("Execution completed successfully!")
    with open(notebook_path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)
    print(f"Saved executed notebook with outputs to: {notebook_path}")
except Exception as e:
    print(f"Error executing notebook: {e}", file=sys.stderr)
    # Still write whatever executed so far
    with open(notebook_path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)
    sys.exit(1)
