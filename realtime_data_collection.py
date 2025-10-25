import time
import requests
import urllib3
import math
from collections import deque

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LIVE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"

# We'll keep recent kill events in memory for ~15 seconds
recent_kill_events = deque(maxlen=200)

# We'll keep recent snapshots so we can look 10s "into the future"
# Structure: [(game_time, {summonerName: feature_dict, ...}), ...]
recent_frames = deque(maxlen=30)  # if we sample every 1s, 30 frames ~30s history

def distance(a, b):
    if a is None or b is None:
        return None
    dx = a["x"] - b["x"]
    dy = a["y"] - b["y"]
    return math.sqrt(dx*dx + dy*dy)

def get_live_state():
    r = requests.get(LIVE_URL, verify=False, timeout=0.3)
    r.raise_for_status()
    raw = r.json()

    game_time = raw.get("gameData", {}).get("gameTime", 0)
    players_raw = raw.get("allPlayers", [])
    events_raw = raw.get("events", {}).get("Events", [])

    # record kill events into recent_kill_events
    for ev in events_raw:
        if ev.get("EventName") == "ChampionKill":
            # store killer, victim, and timestamp
            recent_kill_events.append({
                "time": ev.get("EventTime", 0.0),
                "killer": ev.get("KillerName"),
                "victim": ev.get("VictimName")
            })

    # build a snapshot of all players
    players_snapshot = {}
    for p in players_raw:
        name = p.get("summonerName")
        team = p.get("team")

        hp = p.get("championStats", {}).get("currentHealth")
        max_hp = p.get("championStats", {}).get("maxHealth")
        hp_pct = (hp / max_hp) if (hp is not None and max_hp) else 0.0

        pos = p.get("position")

        # count nearby allies / enemies right now
        allies = 0
        enemies = 0
        if pos:
            for q in players_raw:
                if q is p:
                    continue
                qpos = q.get("position")
                if not qpos:
                    continue
                dist = distance(pos, qpos)
                if dist is None or dist > 2000:
                    continue
                if q.get("team") == team:
                    allies += 1
                else:
                    enemies += 1

        players_snapshot[name] = {
            "game_time": game_time,
            "name": name,
            "team": team,
            "hp_pct": hp_pct,
            "allies_near": allies,
            "enemies_near": enemies,
            # you can store more stuff like gold, level, etc. if you want:
            "gold": p.get("totalGold"),
            "level": p.get("level"),
        }

    return game_time, players_snapshot

def will_die_within(player_name, start_t, horizon_sec=10):
    """
    Look in recent_kill_events.
    Return 1 if this player_name is killed between start_t and start_t + horizon_sec.
    """
    end_t = start_t + horizon_sec
    for ev in recent_kill_events:
        if ev["victim"] == player_name:
            if start_t <= ev["time"] <= end_t:
                return 1
    return 0

# storage for training rows
training_rows = []

if __name__ == "__main__":
    while True:
        try:
            game_t, snapshot = get_live_state()
        except Exception as e:
            print("Not in game / can't read live data:", e)
            break

        # Add this frame to history
        recent_frames.append((game_t, snapshot))

        # Label frames that are now 10s old
        # Example: if current time is 200s, then frames around 190s can now be labeled
        cutoff_age = 10  # seconds
        to_label = []
        for (past_t, past_snapshot) in list(recent_frames):
            if game_t - past_t >= cutoff_age:
                to_label.append((past_t, past_snapshot))

        # For each past frame that just became "labelable"
        for (past_t, past_snapshot) in to_label:
            for name, feats in past_snapshot.items():
                label = will_die_within(name, past_t, horizon_sec=10)

                row = {
                    "t": past_t,
                    "name": name,
                    "hp_pct": feats["hp_pct"],
                    "allies_near": feats["allies_near"],
                    "enemies_near": feats["enemies_near"],
                    "gold": feats["gold"],
                    "level": feats["level"],
                    "will_die_10s": label
                }

                training_rows.append(row)

                # (optional) print positive examples so you can see it working live
                if label == 1:
                    print("⚠ DEATH SOON LABEL FOUND")
                    print(row)

            # after labeling that past frame, we can optionally remove it
            # but keeping it in deque is fine because maxlen already limits size

        # Sleep ~1 second between polls
        time.sleep(1)
