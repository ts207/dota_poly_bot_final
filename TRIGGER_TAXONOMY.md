# Trigger taxonomy

The bot now uses non-overlapping execution triggers.

## Execution triggers

- `FIGHT_GAP`: fight/kill shock while the market is flat. Use `trigger_strength=STRONG` when score and `radiant_lead` both move strongly in the same direction; otherwise `NORMAL`.
- `LEAD_FLIP_GAP`: 10-second `radiant_lead` sign flip while the market is flat.
- `STRUCTURE_GAP`: building-state change while the market is flat. Blocked by default for first probes.
- `MARKET_CONFIRM`: strong Dota shock and the market has started moving 1–5 cents in the same direction.

## Research/event labels

These are not enabled by default for live probes:

- `FIGHT_EVENT`
- `LEAD_FLIP_EVENT`
- `STRUCTURE_EVENT`
- `OVERREACTION`
- `SLOW_BLEED`

## Legacy aliases

Old trigger names are normalized:

- `L_STRONG_GAP` and `L_FIGHT_GAP` → `FIGHT_GAP`
- `L_LEAD_FLIP_GAP` → `LEAD_FLIP_GAP`
- `L_STRUCTURAL_GAP` → `STRUCTURE_GAP`
- `M_STRONG_CONFIRM` → `MARKET_CONFIRM`
- `FIGHT` and `KILL_EVENT` → `FIGHT_EVENT`
- `LEAD_FLIP` → `LEAD_FLIP_EVENT`
- `STRUCTURAL_SWING` → `STRUCTURE_EVENT`

Use `trigger` + `trigger_strength` for analysis.

## Latest trigger safety patch

`FIGHT_GAP / NORMAL` now requires kill direction and `radiant_lead` movement to agree. If kills and lead movement disagree or lead movement is flat/unknown, the bot labels the state as `FIGHT_EVENT / CONFLICTED` and rejects it with `CONFLICTED_FIGHT_GAP`. `research/analyze_live_probe.py` now prints a signal rejection summary by default.

