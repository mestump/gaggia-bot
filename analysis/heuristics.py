from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExtractionState(Enum):
    UNDER = "under"
    OVER = "over"
    NORMAL = "normal"
    UNKNOWN = "unknown"


UNDER_KEYWORDS = {"sour", "acidic", "thin", "watery", "sharp", "bright"}
OVER_KEYWORDS = {"bitter", "harsh", "dry", "astringent", "burnt", "chalky"}


@dataclass
class Diagnosis:
    extraction_state: ExtractionState
    flags: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def diagnose_shot(shot: dict, feedback: dict) -> Diagnosis:
    notes = (feedback.get("flavor_notes") or "").lower()
    score = feedback.get("flavor_score", 10)
    dose = feedback.get("dose_g")
    yld = feedback.get("yield_g")
    duration = shot.get("duration_s", 30)
    flags, suggestions = [], []

    under_hits = sum(1 for k in UNDER_KEYWORDS if k in notes)
    over_hits = sum(1 for k in OVER_KEYWORDS if k in notes)

    if score < 6 and under_hits > over_hits and under_hits > 0:
        state = ExtractionState.UNDER
        suggestions += ["Try finer grind", "Increase preinfusion duration", "Raise brew temperature by 1°C"]
    elif score < 6 and over_hits >= under_hits and over_hits > 0:
        state = ExtractionState.OVER
        suggestions += ["Try coarser grind", "Reduce extraction time", "Lower brew temperature by 1°C"]
    else:
        state = ExtractionState.NORMAL if score >= 6 else ExtractionState.UNKNOWN

    if duration < 20:
        flags.append("Short shot — possible channeling or grind too coarse")
    if duration > 40:
        flags.append("Long shot — grind may be too fine or dose too high")

    if dose and yld:
        ratio = yld / dose
        if ratio < 1.8:
            suggestions.append("Brew ratio is low — consider increasing yield")
        elif ratio > 2.8:
            suggestions.append("Brew ratio is high — consider decreasing yield or increasing dose")

    return Diagnosis(extraction_state=state, flags=flags, suggestions=suggestions)
