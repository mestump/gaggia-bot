import json
import logging
from anthropic import AsyncAnthropic
import config
from analysis.trends import TrendReport
from analysis.heuristics import Diagnosis

logger = logging.getLogger(__name__)

SAFETY_LIMITS = {
    "pressure": 1.0,
    "temperature": 3.0,
    "duration": 5.0,
    "flow": 0.5,
}

SYSTEM_PROMPT = """You are an expert barista and coffee scientist advising a home espresso enthusiast.
You analyze shot data and provide actionable, specific recommendations.
Always respond with valid JSON matching this schema:
{
  "prose": "2-3 paragraphs of friendly, specific advice",
  "adjustments": [
    {"step_name": "Preinfusion", "field": "duration", "old_value": 8, "new_value": 10}
  ]
}
If no profile adjustments are warranted, set "adjustments" to [].
Keep adjustments conservative and safe."""


def _clamp_adjustments(adjustments: list) -> list:
    safe = []
    for adj in adjustments:
        field = adj.get("field", "")
        limit = SAFETY_LIMITS.get(field)
        if limit is not None:
            delta = abs(float(adj.get("new_value", 0)) - float(adj.get("old_value", 0)))
            if delta > limit:
                logger.warning(
                    "Clamping adjustment %s.%s: delta %.2f exceeds limit %.2f",
                    adj.get("step_name"), field, delta, limit,
                )
                continue  # reject, don't clamp to avoid subtle bugs
        safe.append(adj)
    return safe


async def generate_recommendation(
    trend_report: TrendReport,
    diagnosis: Diagnosis,
    recent_shots: list,
    current_profile: dict,
) -> dict:
    client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    user_content = json.dumps({
        "trend_report": {
            "bean": trend_report.bean_name,
            "n_shots": trend_report.n_shots,
            "score_vs_ratio": trend_report.score_vs_ratio,
            "score_vs_grind": trend_report.score_vs_grind,
            "score_vs_dose": trend_report.score_vs_dose,
            "duration_stddev": trend_report.duration_stddev,
        },
        "diagnosis": {
            "extraction_state": diagnosis.extraction_state.value,
            "flags": diagnosis.flags,
            "suggestions": diagnosis.suggestions,
        },
        "recent_shots": recent_shots[-5:],
        "current_profile": current_profile,
    }, indent=2)

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        result = json.loads(response.content[0].text)
        prose = result.get("prose", "")
        adjustments = _clamp_adjustments(result.get("adjustments", []))
        return {"prose": prose, "adjustments": adjustments}
    except Exception as e:
        logger.error("LLM recommendation failed: %s", e)
        return {
            "prose": "Based on your recent shots: " + "; ".join(diagnosis.suggestions or ["Keep experimenting!"]),
            "adjustments": [],
        }
