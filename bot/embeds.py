import discord
from datetime import datetime

def shot_embed(shot: dict, feedback: dict | None = None) -> discord.Embed:
    profile = shot.get("profile_name", "Unknown")
    timestamp = str(shot.get("timestamp", ""))
    duration = shot.get("duration_s", "?")
    dp = shot.get("datapoints", [])
    peak_pressure = max((d.get("pressure_bar", 0) for d in dp), default=0)
    peak_flow = max((d.get("flow_mls", 0) for d in dp), default=0)

    try:
        ts = datetime.fromisoformat(timestamp)
    except (ValueError, TypeError):
        ts = datetime.utcnow()

    embed = discord.Embed(
        title=f"Shot: {profile}",
        color=discord.Color.dark_gold(),
        timestamp=ts,
    )
    embed.add_field(name="Duration", value=f"{duration}s", inline=True)
    embed.add_field(name="Peak Pressure", value=f"{peak_pressure:.1f} bar", inline=True)
    embed.add_field(name="Peak Flow", value=f"{peak_flow:.2f} ml/s", inline=True)

    if feedback:
        score = feedback.get("flavor_score")
        bean = feedback.get("bean_name") or "Unknown"
        dose = feedback.get("dose_g")
        yld = feedback.get("yield_g")
        ratio = f"1:{yld/dose:.1f}" if dose and yld and dose > 0 else "?"
        embed.add_field(name="Score", value=f"{score}/10" if score else "—", inline=True)
        embed.add_field(name="Bean", value=bean, inline=True)
        embed.add_field(name="Ratio", value=ratio, inline=True)

    return embed

def recommendation_embed(prose: str, adjustments: list) -> discord.Embed:
    embed = discord.Embed(
        title="Shot Recommendation",
        description=prose[:4096],
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow(),
    )
    if adjustments:
        lines = []
        for a in adjustments:
            lines.append(f"`{a.get('step_name','?')}.{a.get('field','?')}`: {a.get('old_value','?')} → {a.get('new_value','?')}")
        diff = "\n".join(lines)[:1024]
        embed.add_field(name="Suggested Profile Adjustments", value=diff, inline=False)
    return embed

def status_embed(status: dict) -> discord.Embed:
    mode_names = {0: "Standby", 1: "Brewing", 2: "Steam", 3: "Water", 4: "Grind"}
    mode = mode_names.get(status.get("m", status.get("mode", 0)), "Unknown")
    embed = discord.Embed(title="GaggiaMate Status", color=discord.Color.green())
    embed.add_field(name="Mode", value=mode, inline=True)
    embed.add_field(name="Current Temp", value=f"{status.get('ct', '?')}°C", inline=True)
    embed.add_field(name="Target Temp", value=f"{status.get('tt', '?')}°C", inline=True)
    return embed
