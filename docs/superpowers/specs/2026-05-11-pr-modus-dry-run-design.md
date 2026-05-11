# Design Spec: Power Rangers vs MODUS Dry Run (2026-05-11)

## Overview
This document outlines the configuration and execution plan for a dry run of the Dota-Polymarket bot on the "Power Rangers vs MODUS" series taking place on May 11, 2026.

## Target Metadata
- **Dota Server ID:** `90285610368047130`
- **In-Game Teams:** `_PowerRangers` (Radiant), `MODUS` (Dire)
- **Polymarket Slug:** `dota2-pr1-modus-2026-05-11` (and map-specific variants)
- **Polymarket Outcomes:** `Power Rangers`, `MODUS`

## Configuration
The dry run will use the `SeriesSupervisor` auto-discovery mode to test the bot's ability to dynamically find and align markets.

### Environment Variables (`.env`)
| Variable | Value | Rationale |
| :--- | :--- | :--- |
| `AUTO_DISCOVER_POLYMARKET` | `true` | Enable the SeriesSupervisor discovery logic. |
| `TARGET_SERVER_STEAM_ID` | `90285610368047130` | Target the specific live server. |
| `TARGET_RADIANT_TEAM` | `_PowerRangers` | Map normalization hint for Radiant. |
| `TARGET_DIRE_TEAM` | `MODUS` | Map normalization hint for Dire. |
| `TARGET_MATCH` | `Power Rangers vs MODUS` | Broad search query for Polymarket Gamma. |
| `ENABLE_LIVE_TRADING` | `false` | Ensure no real orders are sent (Dry Run). |
| `DATABASE_PATH` | `./data/dota_poly_collection.sqlite` | Log results to the default database. |

## Execution Plan
1. **Validation:** Verify the Dota feed can reach the server and Polymarket Gamma returns the expected market.
2. **Launch:** Run `python3 main.py`.
3. **Monitoring:** 
    - Verify logs show "Supervisor: Discovered market ..."
    - Verify logs show "Supervisor: Side swap/re-alignment! Radiant=_PowerRangers, Dire=MODUS"
    - Confirm `Strategy: Active` ticks begin appearing.

## Success Criteria
- [ ] Automatic discovery of the correct Polymarket condition ID.
- [ ] Correct mapping of `_PowerRangers` to the `Power Rangers` token.
- [ ] Continuous data collection and virtual trade logging for the duration of at least one map.
