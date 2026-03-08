import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Optional


def generate_shot_graph(
    shot_data: dict,
    feedback: Optional[dict] = None,
    output_dir=None,
) -> Path:
    """Generate a 3-panel PNG shot graph (pressure / flow / temp+weight).

    Parameters
    ----------
    shot_data:
        Parsed shot dict with keys: id, timestamp, duration_s, profile_name,
        datapoints (list of dicts with t_s, temp_c, pressure_bar, flow_mls,
        weight_g).
    feedback:
        Optional dict with dose_g, yield_g, flavor_score keys.
    output_dir:
        Directory to write the PNG.  Defaults to config.GRAPH_DIR.

    Returns
    -------
    Path to the saved PNG file.
    """
    if output_dir is None:
        from config import GRAPH_DIR
        output_dir = GRAPH_DIR

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    shot_id = shot_data.get("id") or "unknown"
    shot_id = str(shot_id).replace("/", "_").replace("\\", "_")  # filesystem-safe
    profile_name = shot_data.get("profile_name", "")
    timestamp = shot_data.get("timestamp", "")
    duration_s = shot_data.get("duration_s", 0)
    datapoints = shot_data.get("datapoints", [])

    # Build title
    ts_display = str(timestamp)[:16].replace("T", " ") if timestamp else ""
    title = f"{profile_name} — {ts_display} — {duration_s}s"

    # Extract series
    t      = [dp.get("t_s", 0.0) for dp in datapoints]
    pressure = [dp.get("pressure_bar", 0.0) for dp in datapoints]
    flow   = [dp.get("flow_mls", 0.0) for dp in datapoints]
    temp   = [dp.get("temp_c", 0.0) for dp in datapoints]
    weight = [dp.get("weight_g", 0.0) for dp in datapoints]
    has_weight = any(w > 0 for w in weight)

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    fig.suptitle(title, fontsize=12, fontweight="bold")

    # Subplot 1: Pressure
    ax_pressure = axes[0]
    if t:
        ax_pressure.plot(t, pressure, color="steelblue", linewidth=2)
    ax_pressure.set_ylabel("Pressure (bar)")
    ax_pressure.set_ylim(bottom=0)
    ax_pressure.grid(True, alpha=0.3)

    # Subplot 2: Flow
    ax_flow = axes[1]
    if t:
        ax_flow.plot(t, flow, color="seagreen", linewidth=2)
    ax_flow.set_ylabel("Flow (ml/s)")
    ax_flow.set_ylim(bottom=0)
    ax_flow.grid(True, alpha=0.3)

    # Subplot 3: Temperature (+ optional weight overlay)
    ax_temp = axes[2]
    if t:
        ax_temp.plot(t, temp, color="firebrick", linewidth=2, label="Temp (°C)")
        if has_weight:
            ax_temp_right = ax_temp.twinx()
            ax_temp_right.plot(
                t, weight,
                color="orange",
                linewidth=2,
                linestyle="--",
                label="Weight (g)",
            )
            ax_temp_right.set_ylabel("Weight (g)")
            ax_temp_right.set_ylim(bottom=0)
            # Combine legends
            lines1, labels1 = ax_temp.get_legend_handles_labels()
            lines2, labels2 = ax_temp_right.get_legend_handles_labels()
            ax_temp.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8)
        else:
            ax_temp.legend(loc="upper left", fontsize=8)
    ax_temp.set_ylabel("Temperature (°C)")
    ax_temp.set_xlabel("Time (s)")
    ax_temp.grid(True, alpha=0.3)

    # Footer feedback text
    if feedback:
        dose_g = feedback.get("dose_g", 0)
        yield_g = feedback.get("yield_g", 0)
        score = feedback.get("flavor_score", 0)
        ratio = yield_g / dose_g if dose_g else 0
        footer = (
            f"Dose: {dose_g}g | Yield: {yield_g}g | "
            f"Ratio: 1:{ratio:.1f} | Score: {score}/10"
        )
        fig.text(
            0.5, 0.01, footer,
            ha="center", va="bottom",
            fontsize=9, color="dimgray",
        )

    fig.tight_layout(rect=[0, 0.04 if feedback else 0, 1, 1])

    output_path = output_dir / f"{shot_id}.png"
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

    return output_path
