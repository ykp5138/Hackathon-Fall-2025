print("HEHEHEHA (script loaded)")  # sanity check at import time

import time
import requests
import urllib3
from collections import deque

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# IMPORTANT: your curl output showed this endpoint works.
# Keep https, and verify=False to ignore cert.
LIVE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"

# rolling buffers
recent_kill_events = deque(maxlen=200)

# recent_frames keeps (game_time, snapshot_at_that_time) so we can label them ~10s later
recent_frames = deque(maxlen=60)

# labeled training rows, written to CSV on Ctrl+C
training_rows = []


def safe_get_live_json():
    """
    Try to grab raw JSON from the League client.
    Return (ok, raw_json_or_text).

    ok = True if it's valid JSON and we could r.json() it.
    """
    r = requests.get(LIVE_URL, verify=False, timeout=1.0)
    r.raise_for_status()

    try:
        data = r.json()
        return True, data
    except ValueError:
        # response wasn't valid JSON
        return False, r.text


def parse_snapshot(raw):
    """
    Convert raw client JSON (your actual schema) into:
        game_t (float),
        snapshot[player_name] = {
            "game_time": ...,
            "name": ...,
            "team": ...,
            "level": ...,
            "is_dead": ...,
            "lane_role": ...,   # "BOTTOM", "JUNGLE", etc. or "NONE"
            "kills": ...,
            "deaths": ...,
            "assists": ...,
            "cs": ...,
            "gold": ...,
            "hp_pct": ...,
        }

    Also updates recent_kill_events from raw["events"].
    """

    # game time
    game_time = raw.get("gameData", {}).get("gameTime", 0.0)

    # 1. Update kill history
    events_raw = raw.get("events", {}).get("Events", [])
    for ev in events_raw:
        if ev.get("EventName") == "ChampionKill":
            recent_kill_events.append({
                "time": ev.get("EventTime", 0.0),
                "killer": ev.get("KillerName"),
                "victim": ev.get("VictimName"),
            })

    snapshot = {}

    # 2. Pull active player's detailed stats (this is YOU)
    active_p = raw.get("activePlayer", {}) or {}
    active_stats = active_p.get("championStats", {}) or {}

    active_name = active_p.get("summonerName") or active_p.get("riotId")
    active_level = active_p.get("level")
    active_gold = active_p.get("currentGold")

    cur_hp = active_stats.get("currentHealth")
    max_hp = active_stats.get("maxHealth")
    if cur_hp is not None and max_hp not in [None, 0]:
        active_hp_pct = cur_hp / max_hp
    else:
        active_hp_pct = None

    # 3. Loop over all players (you + bots) and build per-player rows
    all_players_raw = raw.get("allPlayers", [])
    if isinstance(all_players_raw, dict):
        all_player_iter = list(all_players_raw.values())
    else:
        all_player_iter = all_players_raw

    for p in all_player_iter:
        pname = (
            p.get("summonerName")
            or p.get("riotId")
            or p.get("riotIdGameName")
        )
        if pname is None:
            continue

        team = p.get("team")
        level = p.get("level")
        lane_role = p.get("position")  # "BOTTOM", "JUNGLE", etc. (string role, not map coords)
        is_dead = bool(p.get("isDead"))

        scores = p.get("scores", {}) or {}
        kills = scores.get("kills")
        deaths = scores.get("deaths")
        assists = scores.get("assists")
        cs = scores.get("creepScore")

        # By default we don't know hp/gold for bots from this endpoint
        hp_pct = None
        gold = None

        # But if this entry is actually YOU, merge in richer info
        if active_name is not None and pname == active_name:
            hp_pct = active_hp_pct
            gold = active_gold
            level = active_level if active_level is not None else level

        snapshot[pname] = {
            "game_time": game_time,
            "name": pname,
            "team": team,
            "level": level,
            "is_dead": is_dead,
            "lane_role": lane_role,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "cs": cs,
            "gold": gold,
            "hp_pct": hp_pct,
        }

    return game_time, snapshot


def will_die_within(player_name, start_t, horizon_sec=10):
    """
    Look at our rolling kill log. Return 1 if player_name
    died between [start_t, start_t + horizon_sec].
    """
    end_t = start_t + horizon_sec
    for ev in recent_kill_events:
        # NOTE: we are assuming 'VictimName' in ChampionKill uses same naming
        # as snapshot keys (summonerName like "Corki Bot" or "JackDaCoc#NA1").
        if ev.get("victim") == player_name:
            ev_t = ev.get("time", 0.0)
            if start_t <= ev_t <= end_t:
                return 1
    return 0


def main_loop():
    print("HEHEHEHA (main starting)")
    print(">>> main_loop started; polling League every second...")

    global recent_frames  # we'll replace it each tick after pruning

    while True:
        # 1. Try the request
        try:
            ok, raw_or_txt = safe_get_live_json()
        except Exception as e:
            print("No live frame yet (cannot reach client at all):", e)
            time.sleep(1)
            continue

        # 2. If not valid JSON yet (champ select / lobby / weird), skip
        if not ok:
            preview = str(raw_or_txt)
            if len(preview) > 300:
                preview = preview[:300] + "..."
            print("Client responded but not game-ready. Preview:", preview)
            time.sleep(1)
            continue

        raw = raw_or_txt

        # 3. Parse snapshot using your schema
        try:
            game_t, snapshot = parse_snapshot(raw)
        except Exception as e:
            print("Got data but couldn't parse:", e)

            # debug dump to help adjust if Riot changes shape
            try:
                print("RAW KEYS:", list(raw.keys()) if isinstance(raw, dict) else type(raw))
                if isinstance(raw, dict):
                    print("activePlayer keys:", list(raw.get("activePlayer", {}).keys()))
                    print("allPlayers type:", type(raw.get("allPlayers")))
                    print("events sample:", raw.get("events"))
            except Exception as inner:
                print("debug dump failed:", inner)

            time.sleep(1)
            continue

        # 4. We got a snapshot: print it
        print(f"\n=== frame t={game_t:.1f}s ({len(snapshot)} players) ===")
        recent_frames.append((game_t, snapshot))

        for name, feats in snapshot.items():
            hp_disp = f"{feats['hp_pct']:.2f}" if feats["hp_pct"] is not None else "??"
            print(
                f"{name}: hp={hp_disp}, "
                f"dead={feats['is_dead']}, "
                f"team={feats['team']}, "
                f"role={feats['lane_role']}, "
                f"kda={feats['kills']}/{feats['deaths']}/{feats['assists']}, "
                f"cs={feats['cs']}, "
                f"gold={feats['gold']}, "
                f"lvl={feats['level']}"
            )

        # 5. Label frames that are now 10+ seconds old
        cutoff_age = 10
        still_recent = deque(maxlen=recent_frames.maxlen)

        for (past_t, past_snapshot) in list(recent_frames):
            age = game_t - past_t

            if age >= cutoff_age:
                # old enough => generate labeled training rows for that timestamp ONCE
                for pname, feats in past_snapshot.items():
                    label = will_die_within(pname, past_t, horizon_sec=10)

                    hp_val = feats["hp_pct"] if feats["hp_pct"] is not None else -1.0

                    row = {
                        "t": past_t,
                        "name": pname,
                        "team": feats["team"],
                        "level": feats["level"],
                        "is_dead": feats["is_dead"],
                        "lane_role": feats["lane_role"],
                        "kills": feats["kills"],
                        "deaths": feats["deaths"],
                        "assists": feats["assists"],
                        "cs": feats["cs"],
                        "gold": feats["gold"],
                        "hp_pct": hp_val,
                        "will_die_10s": label,
                    }

                    training_rows.append(row)

                    if label == 1:
                        print("⚠ DEATH SOON LABEL FOUND:", row)

                # we DO NOT keep this frame in buffer => prevents duplicate labeling
            else:
                # not yet ripe, keep it
                still_recent.append((past_t, past_snapshot))

        recent_frames = still_recent

        time.sleep(1)


if __name__ == "__main__":
    try:
        main_loop()
    finally:
        # dump CSV on Ctrl+C
        try:
            import pandas as pd
            df = pd.DataFrame(training_rows)
            df.to_csv("risk_training_data.csv", index=False)
            print("Saved", len(training_rows), "rows to risk_training_data.csv")
            if len(training_rows) > 0:
                print("Sample row:", training_rows[-1])
        except Exception as e:
            print("Could not save CSV:", e)
            print("Rows collected in memory:", len(training_rows))
            if len(training_rows) > 0:
                print("Sample row:", training_rows[-1])
