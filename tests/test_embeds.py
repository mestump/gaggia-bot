import pytest
import discord
from bot.embeds import shot_embed, recommendation_embed, status_embed

SAMPLE_SHOT = {
    "id": "test-001",
    "timestamp": "2026-03-07T08:22:00",
    "duration_s": 28.5,
    "profile_name": "Trieste v2",
    "datapoints": [
        {"pressure_bar": 9.0, "flow_mls": 2.1, "temp_c": 93.0},
        {"pressure_bar": 8.5, "flow_mls": 1.9, "temp_c": 92.9},
    ]
}

def test_shot_embed_returns_embed():
    embed = shot_embed(SAMPLE_SHOT)
    assert isinstance(embed, discord.Embed)
    assert "Trieste v2" in embed.title
    assert any(f.value == "28.5s" for f in embed.fields)

def test_shot_embed_with_feedback():
    feedback = {"flavor_score": 8, "bean_name": "Ethiopia", "dose_g": 18.0, "yield_g": 36.0}
    embed = shot_embed(SAMPLE_SHOT, feedback=feedback)
    assert any("8/10" in f.value for f in embed.fields)
    assert any("Ethiopia" in f.value for f in embed.fields)

def test_shot_embed_no_crash_missing_fields():
    embed = shot_embed({})
    assert isinstance(embed, discord.Embed)

def test_recommendation_embed_with_adjustments():
    adjustments = [{"step_name": "Preinfusion", "field": "duration", "old_value": 8, "new_value": 10}]
    embed = recommendation_embed("Try longer preinfusion.", adjustments)
    assert isinstance(embed, discord.Embed)
    assert any("Preinfusion" in f.value for f in embed.fields)

def test_status_embed_standby():
    embed = status_embed({"m": 0, "ct": 40.2, "tt": 0})
    assert "Standby" in str([f.value for f in embed.fields])

def test_status_embed_brewing():
    embed = status_embed({"m": 1, "ct": 93.0, "tt": 93.0})
    assert "Brewing" in str([f.value for f in embed.fields])
