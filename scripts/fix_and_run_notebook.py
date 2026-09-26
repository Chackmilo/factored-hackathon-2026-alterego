import json
import os
import sys
import nbformat
from nbclient import NotebookClient

notebook_path = "notebooks/01_problema_y_datos.ipynb"
print(f"Loading notebook: {notebook_path}")

with open(notebook_path, "r", encoding="utf-8") as f:
    nb_data = json.load(f)

# Fix cells
for cell in nb_data["cells"]:
    if cell["cell_type"] == "code":
        source_str = "".join(cell["source"])
        if "first_contact_resolution" in source_str:
            new_source = []
            for line in cell["source"]:
                line_fixed = line.replace("first_contact_resolution", "was_resolved")
                line_fixed = line_fixed.replace("needs_follow_up", "requires_followup")
                if "duration_minutes" in line_fixed and "SELECT" in "".join(cell["source"]):
                    line_fixed = line_fixed.replace("duration_minutes", "duration_seconds")
                new_source.append(line_fixed)
            
            # If this is the cell that loads df_interactions, add duration_minutes calculation
            if "df_interactions = con_s3.execute" in "".join(new_source):
                # find print('Filas cargadas...')
                final_source = []
                for line in new_source:
                    if "print(f'Filas cargadas:" in line:
                        final_source.append("df_interactions['duration_minutes'] = df_interactions['duration_seconds'] / 60.0\n")
                    final_source.append(line)
                new_source = final_source
            
            cell["source"] = new_source
            cell["outputs"] = []
            cell["execution_count"] = None
        else:
            # clear previous partial outputs
            cell["outputs"] = []
            cell["execution_count"] = None

# Save clean notebook
with open(notebook_path, "w", encoding="utf-8") as f:
    json.dump(nb_data, f, indent=1)

print("Notebook code cells fixed. Now executing with nbclient...")

with open(notebook_path, "r", encoding="utf-8") as f:
    nb = nbformat.read(f, as_version=4)

client = NotebookClient(nb, timeout=600, kernel_name="python3")

try:
    client.execute()
    print("Notebook executed successfully without errors!")
    with open(notebook_path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)
    print("Executed notebook saved with all outputs.")
except Exception as e:
    print(f"Error during execution: {e}", file=sys.stderr)
    with open(notebook_path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)
    sys.exit(1)
