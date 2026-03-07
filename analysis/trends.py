from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class TrendReport:
    bean_name: str
    n_shots: int
    score_vs_ratio: Optional[float]   # Pearson r
    score_vs_grind: Optional[float]
    score_vs_dose: Optional[float]
    duration_stddev: Optional[float]
    staleness_slope: Optional[float]  # score change per day since roast
    insufficient_data: bool = False


def _pearson(x: list, y: list) -> Optional[float]:
    if len(x) < 3:
        return None
    try:
        from scipy.stats import pearsonr
        r, _ = pearsonr(x, y)
        return float(r)
    except Exception:
        return None


async def compute_trends(bean_name: str, n_shots: int = 20) -> TrendReport:
    import db
    from config import MIN_SHOTS_FOR_RECOMMENDATION

    async with db.get_db() as conn:
        async with conn.execute(
            """SELECT s.duration_s, f.flavor_score, f.brew_ratio, f.grind_size, f.dose_g, f.roast_date
               FROM feedback f JOIN shots s ON s.id = f.shot_id
               WHERE f.bean_name = ? AND f.flavor_score IS NOT NULL
               ORDER BY s.timestamp DESC LIMIT ?""",
            (bean_name, n_shots)
        ) as cur:
            rows = await cur.fetchall()

    if len(rows) < MIN_SHOTS_FOR_RECOMMENDATION:
        return TrendReport(
            bean_name=bean_name,
            n_shots=len(rows),
            score_vs_ratio=None,
            score_vs_grind=None,
            score_vs_dose=None,
            duration_stddev=None,
            staleness_slope=None,
            insufficient_data=True,
        )

    scores = [r["flavor_score"] for r in rows]
    ratios = [r["brew_ratio"] for r in rows if r["brew_ratio"] is not None]
    grinds = [r["grind_size"] for r in rows if r["grind_size"] is not None]
    doses = [r["dose_g"] for r in rows if r["dose_g"] is not None]
    durations = [r["duration_s"] for r in rows if r["duration_s"] is not None]

    return TrendReport(
        bean_name=bean_name,
        n_shots=len(rows),
        score_vs_ratio=_pearson(ratios, scores[:len(ratios)]) if ratios else None,
        score_vs_grind=_pearson(grinds, scores[:len(grinds)]) if grinds else None,
        score_vs_dose=_pearson(doses, scores[:len(doses)]) if doses else None,
        duration_stddev=float(np.std(durations)) if durations else None,
        staleness_slope=None,
    )
