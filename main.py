import json
import os
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from src.agents.orchestrator import HybridOrchestrator
from src.domain.schemas import CustomerInteractionInput

def run_demonstration():
    console = Console()
    console.print(Panel.fit(
        "[bold cyan]OmniGuard AI -- Hybrid Customer Interaction & Fraud Resolution Engine[/bold cyan]\n"
        "[dim]Factored AI & Data Hackathon 2026 Ready Baseline[/dim]",
        border_style="cyan"
    ))

    data_path = os.path.join(os.path.dirname(__file__), "data", "synthetic_samples.json")
    if not os.path.exists(data_path):
        console.print(f"[red]Samples file not found at {data_path}[/red]")
        return

    with open(data_path, "r", encoding="utf-8") as f:
        samples = json.load(f)

    orchestrator = HybridOrchestrator()

    table = Table(title="[bold green]Pipeline Execution Across Scenarios[/bold green]", show_header=True, header_style="bold magenta")
    table.add_column("Scenario", style="cyan", width=28)
    table.add_column("Routing Decision", style="yellow", width=22)
    table.add_column("Risk Level", width=12)
    table.add_column("Latency (ms)", justify="right", width=12)
    table.add_column("Actions / Output", style="green", width=36)

    for sample in samples:
        scenario_name = sample["scenario"]
        raw_input = CustomerInteractionInput(**sample["input"])
        decision = orchestrator.process_interaction(raw_input)

        risk_color = "red" if decision.risk_level.value in ["HIGH", "CRITICAL"] else ("yellow" if decision.risk_level.value == "MEDIUM" else "green")
        latency = decision.execution_metrics.get("total_latency_ms", 0.0)
        action_summary = ", ".join(decision.actions_taken) if decision.actions_taken else "NO_ACTION"

        table.add_row(
            scenario_name,
            f"[bold]{decision.routing.value}[/bold]",
            f"[{risk_color}]{decision.risk_level.value}[/{risk_color}]",
            f"{latency:.1f} ms",
            action_summary
        )

    console.print(table)
    console.print("\n[bold green][SUCCESS] All scenarios evaluated successfully![/bold green] Run [bold]uv run pytest -v[/bold] for unit test suite.\n")

if __name__ == "__main__":
    run_demonstration()
