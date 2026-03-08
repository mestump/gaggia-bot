import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from pathlib import Path
from typing import Optional

# ── GaggiaMate color palette (light-mode) ────────────────────────────────────
_C_PRESSURE = "#0066CC"   # blue
_C_FLOW     = "#059669"   # emerald (puck flow)
_C_TEMP     = "#F0561D"   # orange
_C_WEIGHT   = "#8B5CF6"   # purple
_C_PHASE    = "#6B7280"   # gray phase markers
_C_BG       = "#FFFFFF"
_C_GRID     = "#E5E7EB"

_LW_MAIN   = 2.0
_LW_TARGET = 1.2
_ALPHA_TGT = 0.45
_DASH       = (0, (6, 4))


def generate_shot_graph(
    shot_data: dict,
    feedback: Optional[dict] = None,
    output_dir=None,
) -> Path:
    """Generate a single-panel PNG shot graph matching GaggiaMate's web UI style.

    Left Y-axis  : pressure (bar) + puck flow (ml/s), fixed 0–16
    Right Y-axis : temperature (°C), auto-scaled
    Far-right    : weight (g), only when non-zero data is present
    Dashed lines : profile target values
    """
    if output_dir is None:
        from config import GRAPH_DIR
        output_dir = GRAPH_DIR

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    shot_id      = str(shot_data.get("id") or "unknown").replace("/", "_").replace("\\", "_")
    profile_name = shot_data.get("profile_name", "")
    timestamp    = shot_data.get("timestamp", "")
    duration_s   = shot_data.get("duration_s", 0)
    datapoints   = shot_data.get("datapoints", [])
    phases       = shot_data.get("phases", [])

    ts_display = str(timestamp)[:16].replace("T", " ") if timestamp else ""
    title = f"{profile_name}  ·  {ts_display}  ·  {duration_s:.1f}s"

    # ── Extract series ────────────────────────────────────────────────────────
    t           = [dp.get("t_s", 0.0)                 for dp in datapoints]
    pressure    = [dp.get("pressure_bar", 0.0)         for dp in datapoints]
    tgt_pres    = [dp.get("target_pressure_bar", 0.0)  for dp in datapoints]
    flow        = [dp.get("flow_mls", 0.0)             for dp in datapoints]
    tgt_flow    = [dp.get("target_flow_mls", 0.0)      for dp in datapoints]
    temp        = [dp.get("temp_c", 0.0)               for dp in datapoints]
    tgt_temp    = [dp.get("target_temp_c", 0.0)        for dp in datapoints]
    weight      = [dp.get("weight_g", 0.0)             for dp in datapoints]

    has_weight   = any(w > 0 for w in weight)
    has_tgt_pres = any(v > 0 for v in tgt_pres)
    has_tgt_flow = any(v > 0 for v in tgt_flow)
    has_tgt_temp = any(v > 0 for v in tgt_temp)

    # ── Figure + axes ─────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(12, 5))
    fig.patch.set_facecolor(_C_BG)
    ax.set_facecolor(_C_BG)
    fig.suptitle(title, fontsize=11, fontweight="bold", color="#111827", y=0.98)

    ax_temp = ax.twinx()
    ax_weight = None
    if has_weight:
        ax_weight = ax.twinx()
        ax_weight.spines["right"].set_position(("outward", 58))

    # ── Plot series ───────────────────────────────────────────────────────────
    lines = []

    if t:
        ln, = ax.plot(t, pressure, color=_C_PRESSURE, lw=_LW_MAIN, label="Pressure (bar)", zorder=3)
        lines.append(ln)
        if has_tgt_pres:
            ln, = ax.plot(t, tgt_pres, color=_C_PRESSURE, lw=_LW_TARGET,
                          alpha=_ALPHA_TGT, linestyle=_DASH, label="Target Pressure", zorder=2)
            lines.append(ln)

        ln, = ax.plot(t, flow, color=_C_FLOW, lw=_LW_MAIN, label="Flow (ml/s)", zorder=3)
        lines.append(ln)
        if has_tgt_flow:
            ln, = ax.plot(t, tgt_flow, color=_C_FLOW, lw=_LW_TARGET,
                          alpha=_ALPHA_TGT, linestyle=_DASH, label="Target Flow", zorder=2)
            lines.append(ln)

        ln, = ax_temp.plot(t, temp, color=_C_TEMP, lw=_LW_MAIN, label="Temp (°C)", zorder=3)
        lines.append(ln)
        if has_tgt_temp:
            ln, = ax_temp.plot(t, tgt_temp, color=_C_TEMP, lw=_LW_TARGET,
                               alpha=_ALPHA_TGT, linestyle=_DASH, label="Target Temp", zorder=2)
            lines.append(ln)

        if has_weight and ax_weight is not None:
            ln, = ax_weight.plot(t, weight, color=_C_WEIGHT, lw=_LW_MAIN, label="Weight (g)", zorder=3)
            lines.append(ln)

    # ── Phase markers ─────────────────────────────────────────────────────────
    for phase in phases:
        phase_t    = phase.get("start_time_s") or phase.get("start_time_seconds", 0.0)
        phase_name = phase.get("name", "")
        if phase_t and phase_t > 0:
            ax.axvline(phase_t, color=_C_PHASE, lw=1.0, alpha=0.55, zorder=1)
            if phase_name:
                ax.text(
                    phase_t + 0.25, 0.5, phase_name,
                    transform=ax.get_xaxis_transform(),
                    color=_C_PHASE, fontsize=7, va="center", rotation=90,
                    bbox=dict(boxstyle="round,pad=0.2", fc=_C_BG, ec="none", alpha=0.75),
                )

    # ── Axis styling ──────────────────────────────────────────────────────────
    ax.set_ylim(0, 16)
    ax.set_ylabel("Pressure (bar)  /  Flow (ml/s)", color="#374151", fontsize=9)
    ax.set_xlabel("Time (s)", fontsize=9, color="#374151")
    ax.tick_params(axis="y", labelcolor="#374151", labelsize=8)
    ax.tick_params(axis="x", labelsize=8)
    ax.yaxis.set_major_locator(ticker.MultipleLocator(2))
    ax.set_axisbelow(True)
    ax.grid(True, color=_C_GRID, linewidth=0.8, zorder=0)

    ax_temp.set_ylabel("Temperature (°C)", color=_C_TEMP, fontsize=9)
    ax_temp.tick_params(axis="y", labelcolor=_C_TEMP, labelsize=8)
    ax_temp.spines["right"].set_edgecolor(_C_TEMP)
    ax_temp.grid(False)

    if ax_weight is not None:
        ax_weight.set_ylim(bottom=0)
        ax_weight.set_ylabel("Weight (g)", color=_C_WEIGHT, fontsize=9)
        ax_weight.tick_params(axis="y", labelcolor=_C_WEIGHT, labelsize=8)
        ax_weight.spines["right"].set_edgecolor(_C_WEIGHT)

    for spine in ax.spines.values():
        spine.set_edgecolor("#D1D5DB")
    ax_temp.spines["left"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # ── Legend ────────────────────────────────────────────────────────────────
    if lines:
        ax.legend(
            lines, [ln.get_label() for ln in lines],
            loc="upper left", fontsize=8,
            framealpha=0.85, edgecolor="#D1D5DB",
            ncol=min(len(lines), 4),
        )

    # ── Footer ────────────────────────────────────────────────────────────────
    if feedback:
        dose_g  = feedback.get("dose_g") or 0
        yield_g = feedback.get("yield_g") or 0
        score   = feedback.get("flavor_score") or 0
        bean    = feedback.get("bean_name") or ""
        ratio   = yield_g / dose_g if dose_g else 0
        parts   = [f"Score: {score}/10"]
        if bean:
            parts.append(f"Bean: {bean}")
        if dose_g:
            parts.append(f"Dose: {dose_g}g")
        if yield_g:
            parts.append(f"Yield: {yield_g}g  (1:{ratio:.1f})")
        fig.text(0.5, 0.01, "  ·  ".join(parts),
                 ha="center", va="bottom", fontsize=8, color="#6B7280")

    fig.tight_layout(rect=[0, 0.04 if feedback else 0.0, 1, 0.95])
    output_path = output_dir / f"{shot_id}.png"
    fig.savefig(output_path, dpi=150, facecolor=_C_BG)
    plt.close(fig)

    return output_path
