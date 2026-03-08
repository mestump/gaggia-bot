"""
Unit tests for analysis/shot_transformer.py
"""
import pytest
from analysis.shot_transformer import (
    trim_trailing_artifacts,
    compute_summary,
    compute_compliance,
    downsample_for_llm,
    transform_shot_for_llm,
    MAX_SAMPLES_FOR_LLM,
)


def make_dp(t_ms=0, temp_c=93.0, pressure_bar=9.0, flow_mls=2.0,
            target_temp_c=93.0, target_pressure_bar=9.0, target_flow_mls=2.0,
            volume_ml=0.0) -> dict:
    return {
        "t_ms": t_ms,
        "t_s": t_ms / 1000.0,
        "temp_c": temp_c,
        "target_temp_c": target_temp_c,
        "pressure_bar": pressure_bar,
        "target_pressure_bar": target_pressure_bar,
        "flow_mls": flow_mls,
        "target_flow_mls": target_flow_mls,
        "volume_ml": volume_ml,
    }


# ---------------------------------------------------------------------------
# trim_trailing_artifacts
# ---------------------------------------------------------------------------

class TestTrimTrailingArtifacts:
    def test_empty_returns_empty(self):
        assert trim_trailing_artifacts([]) == []

    def test_single_sample_preserved(self):
        dp = [make_dp(flow_mls=0.0, pressure_bar=0.0)]
        assert trim_trailing_artifacts(dp) == dp

    def test_trims_low_flow_low_pressure_tail(self):
        good = [make_dp(t_ms=0, flow_mls=2.0, pressure_bar=9.0),
                make_dp(t_ms=250, flow_mls=1.8, pressure_bar=8.5)]
        tail = [make_dp(t_ms=500, flow_mls=0.0, pressure_bar=0.5),
                make_dp(t_ms=750, flow_mls=0.0, pressure_bar=0.1)]
        result = trim_trailing_artifacts(good + tail)
        assert result == good

    def test_no_trim_when_tail_has_pressure(self):
        dps = [make_dp(t_ms=0, flow_mls=2.0, pressure_bar=9.0),
               make_dp(t_ms=250, flow_mls=0.0, pressure_bar=5.0)]  # pressure still high
        result = trim_trailing_artifacts(dps)
        assert len(result) == 2

    def test_preserves_at_least_one_sample(self):
        all_artifact = [make_dp(flow_mls=0.0, pressure_bar=0.0),
                        make_dp(flow_mls=0.0, pressure_bar=0.0)]
        result = trim_trailing_artifacts(all_artifact)
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# compute_summary
# ---------------------------------------------------------------------------

class TestComputeSummary:
    def test_empty_datapoints(self):
        summary = compute_summary([], 30.0)
        assert summary["temperature"]["avg_c"] == 0.0
        assert summary["extraction"]["total_time_s"] == 30.0

    def test_temperature_stats(self):
        dps = [make_dp(t_ms=0, temp_c=92.0),
               make_dp(t_ms=250, temp_c=93.0),
               make_dp(t_ms=500, temp_c=94.0)]
        summary = compute_summary(dps, 0.5)
        assert summary["temperature"]["min_c"] == 92.0
        assert summary["temperature"]["max_c"] == 94.0
        assert abs(summary["temperature"]["avg_c"] - 93.0) < 0.2

    def test_pressure_peak_time(self):
        dps = [make_dp(t_ms=0,    pressure_bar=2.0),
               make_dp(t_ms=5000, pressure_bar=9.0),  # peak at 5s
               make_dp(t_ms=8000, pressure_bar=8.5)]
        summary = compute_summary(dps, 8.0)
        assert summary["pressure"]["peak_time_s"] == 5.0
        assert summary["pressure"]["max_bar"] == 9.0

    def test_preinfusion_time(self):
        # Peak pressure is 9.0 bar; threshold=4.5 bar
        # First sample reaching threshold is at t=2s
        dps = [make_dp(t_ms=0,    pressure_bar=1.0),
               make_dp(t_ms=2000, pressure_bar=5.0),  # crosses threshold
               make_dp(t_ms=5000, pressure_bar=9.0)]
        summary = compute_summary(dps, 5.0)
        assert summary["extraction"]["preinfusion_time_s"] == 2.0

    def test_time_to_first_drip(self):
        dps = [make_dp(t_ms=0,    flow_mls=0.0),
               make_dp(t_ms=1000, flow_mls=0.0),
               make_dp(t_ms=2000, flow_mls=0.5)]  # first drip at 2s
        summary = compute_summary(dps, 5.0)
        assert summary["flow"]["time_to_first_drip_s"] == 2.0

    def test_no_first_drip_when_no_flow(self):
        dps = [make_dp(t_ms=0, flow_mls=0.0)]
        summary = compute_summary(dps, 1.0)
        assert summary["flow"]["time_to_first_drip_s"] is None


# ---------------------------------------------------------------------------
# compute_compliance
# ---------------------------------------------------------------------------

class TestComputeCompliance:
    def test_empty_returns_none_metrics(self):
        result = compute_compliance([])
        assert result["pressure_rmse_bar"] is None
        assert result["flow_rmse_ml_s"] is None
        assert result["brew_phase_sample_count"] == 0

    def test_pressure_rmse_computed(self):
        # All brew-phase (high pressure), known deviations
        dps = [make_dp(t_ms=i * 250, pressure_bar=9.0, target_pressure_bar=9.0)
               for i in range(5)]
        # Perfect compliance → RMSE = 0
        result = compute_compliance(dps)
        assert result["pressure_rmse_bar"] == 0.0
        assert result["max_pressure_overshoot_bar"] == 0.0
        assert result["max_pressure_undershoot_bar"] == 0.0

    def test_pressure_rmse_with_deviation(self):
        # 4 brew samples, each 1 bar over target
        dps = [make_dp(t_ms=i * 250, pressure_bar=10.0, target_pressure_bar=9.0)
               for i in range(4)]
        result = compute_compliance(dps)
        assert result["pressure_rmse_bar"] == 1.0
        assert result["max_pressure_overshoot_bar"] == 1.0
        assert result["max_pressure_undershoot_bar"] == 0.0

    def test_fewer_than_3_brew_samples_returns_none(self):
        # Only 2 brew-phase samples
        dps = [make_dp(t_ms=0, pressure_bar=9.0, target_pressure_bar=9.0),
               make_dp(t_ms=250, pressure_bar=9.0, target_pressure_bar=9.0)]
        result = compute_compliance(dps)
        assert result["pressure_rmse_bar"] is None

    def test_flow_rmse_computed(self):
        dps = [make_dp(t_ms=i * 250, pressure_bar=9.0, flow_mls=2.5, target_flow_mls=2.0)
               for i in range(4)]
        result = compute_compliance(dps)
        assert result["flow_rmse_ml_s"] == 0.5


# ---------------------------------------------------------------------------
# downsample_for_llm
# ---------------------------------------------------------------------------

class TestDownsampleForLlm:
    def test_empty_returns_empty(self):
        assert downsample_for_llm([]) == []

    def test_few_samples_below_max_returned_all(self):
        dps = [make_dp(t_ms=i * 250) for i in range(10)]
        result = downsample_for_llm(dps, max_samples=25)
        assert len(result) == 10  # fewer than max, no downsampling

    def test_many_samples_capped_at_max(self):
        dps = [make_dp(t_ms=i * 250) for i in range(200)]
        result = downsample_for_llm(dps, max_samples=MAX_SAMPLES_FOR_LLM)
        assert len(result) <= MAX_SAMPLES_FOR_LLM

    def test_output_keys(self):
        dps = [make_dp(t_ms=0, temp_c=93.0, pressure_bar=9.0, flow_mls=2.0, volume_ml=10.0)]
        result = downsample_for_llm(dps)
        assert set(result[0].keys()) == {"t_s", "temp_c", "pressure_bar", "flow_ml_s", "volume_ml"}


# ---------------------------------------------------------------------------
# transform_shot_for_llm
# ---------------------------------------------------------------------------

class TestTransformShotForLlm:
    def test_returns_expected_keys(self):
        shot = {
            "id": 42,
            "profile_name": "Bloom",
            "timestamp": "2024-01-01T12:00:00+00:00",
            "duration_s": 28.0,
            "datapoints": [make_dp(t_ms=i * 250) for i in range(10)],
        }
        result = transform_shot_for_llm(shot)
        assert set(result.keys()) == {"id", "profile_name", "timestamp", "duration_s",
                                       "summary", "compliance", "samples"}

    def test_empty_shot_does_not_crash(self):
        result = transform_shot_for_llm({})
        assert result["summary"]["extraction"]["total_time_s"] == 0.0

    def test_samples_capped(self):
        shot = {
            "id": 1,
            "profile_name": "Test",
            "duration_s": 60.0,
            "datapoints": [make_dp(t_ms=i * 250) for i in range(300)],
        }
        result = transform_shot_for_llm(shot)
        assert len(result["samples"]) <= MAX_SAMPLES_FOR_LLM
