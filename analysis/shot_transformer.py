"""
shot_transformer.py — Transform raw shot datapoints into AI-friendly summaries.

Provides:
  - trim_trailing_artifacts: remove post-pump decay samples
  - compute_summary: temperature / pressure / flow / extraction stats
  - compute_compliance: RMSE of actual vs target (pressure + flow)
  - downsample_for_llm: adaptive stride-based downsampling
  - transform_shot_for_llm: top-level entry point
"""
from math import ceil, sqrt
from typing import Optional

MAX_SAMPLES_FOR_LLM = 25


# ── Internal helpers ──────────────────────────────────────────────────────────

def _sample_interval_ms(datapoints: list[dict]) -> int:
    """Estimate sample interval in ms from the first few consecutive timestamps."""
    if len(datapoints) < 2:
        return 250  # default 4 Hz
    diffs = [
        datapoints[i + 1]["t_ms"] - datapoints[i]["t_ms"]
        for i in range(min(5, len(datapoints) - 1))
        if datapoints[i + 1]["t_ms"] > datapoints[i]["t_ms"]
    ]
    return int(sum(diffs) / len(diffs)) if diffs else 250


def _brew_phase_samples(datapoints: list[dict]) -> list[dict]:
    """Return samples where pressure >= 50% of peak (brew phase only)."""
    if not datapoints:
        return []
    peak = max(s.get("pressure_bar", 0.0) for s in datapoints)
    if peak == 0:
        return []
    threshold = peak * 0.5
    return [s for s in datapoints if s.get("pressure_bar", 0.0) >= threshold]


# ── Public API ────────────────────────────────────────────────────────────────

def trim_trailing_artifacts(datapoints: list[dict]) -> list[dict]:
    """Remove trailing post-pump-stop artifact samples.

    After the pump stops, firmware keeps recording for ~0.5–1 s while
    pressure decays.  These samples skew average stats and mislead the LLM.
    Strips contiguous trailing samples where flow_mls <= 0.05 AND
    pressure_bar < 1.0.  Always preserves at least one sample.
    """
    if len(datapoints) <= 1:
        return datapoints

    trim_from = len(datapoints)
    for i in range(len(datapoints) - 1, 0, -1):
        s = datapoints[i]
        if s.get("flow_mls", 0.0) <= 0.05 and s.get("pressure_bar", 0.0) < 1.0:
            trim_from = i
        else:
            break

    return datapoints[:trim_from] if trim_from < len(datapoints) else datapoints


def compute_summary(datapoints: list[dict], total_duration_s: float) -> dict:
    """Compute temperature / pressure / flow / extraction summary statistics."""
    clean = trim_trailing_artifacts(datapoints) if datapoints else datapoints

    temps        = [s["temp_c"]         for s in clean if "temp_c"         in s]
    target_temps = [s["target_temp_c"]  for s in clean if "target_temp_c"  in s]
    pressures    = [s["pressure_bar"]   for s in clean if "pressure_bar"   in s]
    flows        = [s["flow_mls"]       for s in clean if "flow_mls"       in s]
    times        = [s.get("t_s", 0.0)  for s in clean]

    # Total extracted volume: sum(flow × interval)
    interval_s = _sample_interval_ms(datapoints) / 1000.0 if datapoints else 0.25
    total_volume = round(sum(f * interval_s for f in flows) * 10) / 10

    # Peak pressure index → peak time
    peak_pressure = max(pressures) if pressures else 0.0
    peak_idx = pressures.index(peak_pressure) if pressures and peak_pressure > 0 else 0
    peak_time = times[peak_idx] if peak_idx < len(times) else 0.0

    # Preinfusion end = first sample where pressure reaches 50% of peak
    preinfusion_s = 0.0
    if peak_pressure > 0:
        threshold = peak_pressure * 0.5
        for i, p in enumerate(pressures):
            if p >= threshold and i < len(times):
                preinfusion_s = times[i]
                break

    # Time to first drip = first sample with non-zero flow (across all samples)
    all_flows = [s.get("flow_mls", 0.0) for s in datapoints]
    all_times = [s.get("t_s", 0.0)      for s in datapoints]
    time_to_first_drip: Optional[float] = None
    for i, f in enumerate(all_flows):
        if f > 0.0 and i < len(all_times):
            time_to_first_drip = round(all_times[i] * 10) / 10
            break

    def _avg(lst: list) -> float:
        return round(sum(lst) / len(lst) * 10) / 10 if lst else 0.0

    return {
        "temperature": {
            "min_c":        round(min(temps)  * 10) / 10 if temps else 0.0,
            "max_c":        round(max(temps)  * 10) / 10 if temps else 0.0,
            "avg_c":        _avg(temps),
            "target_avg_c": _avg(target_temps),
        },
        "pressure": {
            "min_bar":    round(min(pressures) * 10) / 10 if pressures else 0.0,
            "max_bar":    round(max(pressures) * 10) / 10 if pressures else 0.0,
            "avg_bar":    _avg(pressures),
            "peak_time_s": round(peak_time * 10) / 10,
        },
        "flow": {
            "total_volume_ml":      total_volume,
            "avg_flow_ml_s":        _avg(flows),
            "peak_flow_ml_s":       round(max(flows) * 10) / 10 if flows else 0.0,
            "time_to_first_drip_s": time_to_first_drip,
        },
        "extraction": {
            "preinfusion_time_s":      round(preinfusion_s * 10) / 10,
            "main_extraction_time_s":  round(max(0.0, total_duration_s - preinfusion_s) * 10) / 10,
            "total_time_s":            round(total_duration_s * 10) / 10,
        },
    }


def compute_compliance(datapoints: list[dict]) -> dict:
    """RMSE of actual vs target pressure and flow across brew-phase samples.

    Requires >= 3 brew-phase samples with target values to compute each metric.
    Falls back to None for degenerate shots.
    """
    brew = _brew_phase_samples(datapoints)
    brew_count = len(brew)

    # Pressure RMSE
    brew_tp = [s for s in brew if "target_pressure_bar" in s]
    pressure_rmse = max_overshoot = max_undershoot = None
    if len(brew_tp) >= 3:
        errors = [s["pressure_bar"] - s["target_pressure_bar"] for s in brew_tp]
        pressure_rmse   = round(sqrt(sum(e ** 2 for e in errors) / len(errors)), 2)
        max_overshoot   = round(max(0.0, max(errors)), 2)
        max_undershoot  = round(max(0.0, max(-e for e in errors)), 2)

    # Flow RMSE
    brew_tf = [s for s in brew if "target_flow_mls" in s]
    flow_rmse = None
    if len(brew_tf) >= 3:
        errors = [s.get("flow_mls", 0.0) - s["target_flow_mls"] for s in brew_tf]
        flow_rmse = round(sqrt(sum(e ** 2 for e in errors) / len(errors)), 2)

    return {
        "pressure_rmse_bar":          pressure_rmse,
        "max_pressure_overshoot_bar":  max_overshoot,
        "max_pressure_undershoot_bar": max_undershoot,
        "flow_rmse_ml_s":             flow_rmse,
        "brew_phase_sample_count":    brew_count,
    }


def downsample_for_llm(datapoints: list[dict], max_samples: int = MAX_SAMPLES_FOR_LLM) -> list[dict]:
    """Return at most max_samples evenly-strided datapoints, rounded for token efficiency."""
    if not datapoints:
        return []
    step = max(1, ceil(len(datapoints) / max_samples))
    return [
        {
            "t_s":          round(s.get("t_s", 0.0)          * 10) / 10,
            "temp_c":       round(s.get("temp_c", 0.0)       * 10) / 10,
            "pressure_bar": round(s.get("pressure_bar", 0.0) * 10) / 10,
            "flow_ml_s":    round(s.get("flow_mls", 0.0)     * 10) / 10,
            "volume_ml":    round(s.get("volume_ml", 0.0)    * 10) / 10,
        }
        for s in datapoints[::step]
    ]


def transform_shot_for_llm(shot: dict) -> dict:
    """Transform a raw shot dict into a compact, AI-optimised representation.

    Parameters
    ----------
    shot:
        Raw shot dict with keys: id, profile_name, timestamp, duration_s,
        datapoints (list of dicts from SLOG parser).

    Returns
    -------
    Dict with summary stats, compliance metrics, and downsampled timeseries.
    """
    datapoints  = shot.get("datapoints", [])
    duration_s  = shot.get("duration_s", 0.0)

    return {
        "id":           shot.get("id"),
        "profile_name": shot.get("profile_name", ""),
        "timestamp":    str(shot.get("timestamp", "")),
        "duration_s":   duration_s,
        "summary":      compute_summary(datapoints, duration_s),
        "compliance":   compute_compliance(datapoints),
        "samples":      downsample_for_llm(datapoints),
    }
