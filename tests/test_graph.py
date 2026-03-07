import pytest
import json
from pathlib import Path
from grapher.shot_graph import generate_shot_graph

FIXTURE = Path("tests/fixtures/sample_shot.json")


def test_graph_generates_png(tmp_path):
    shot = json.loads(FIXTURE.read_text())
    output = generate_shot_graph(shot, output_dir=tmp_path)
    assert output.exists()
    assert output.suffix == ".png"
    assert output.stat().st_size > 10_000


def test_graph_filename_uses_shot_id(tmp_path):
    shot = json.loads(FIXTURE.read_text())
    output = generate_shot_graph(shot, output_dir=tmp_path)
    assert "test-shot-001" in output.name


def test_graph_with_feedback_overlay(tmp_path):
    shot = json.loads(FIXTURE.read_text())
    feedback = {"dose_g": 18.0, "yield_g": 36.0, "flavor_score": 8}
    output = generate_shot_graph(shot, feedback=feedback, output_dir=tmp_path)
    assert output.exists()
    assert output.stat().st_size > 10_000


def test_graph_empty_datapoints_does_not_crash(tmp_path):
    shot = json.loads(FIXTURE.read_text())
    shot["datapoints"] = []
    output = generate_shot_graph(shot, output_dir=tmp_path)
    assert output.exists()
