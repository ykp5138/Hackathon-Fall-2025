import requests
import urllib3
import joblib
import numpy as np
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LIVE_URL = "http://127.0.0.1:2999/liveclientdata/allgamedata"
MODEL_FILE = "death_model.pkl"

def get_live_snapshot():
    """
    Grab current frame from the League liveclientdata API.
    Return a dict of your player's features, or None.
    """
    try:
        r = requests.get(LIVE_URL, verify=False, timeout=0.5)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        print("[warn] could not read live client:", repr(e))
        return None

    # DEBUG: show top-level keys once so we know what mode we're in
    # (activePlayer missing = you're spectating or the game hasn't started)
    if not isinstance(raw, dict):
        print("[debug] raw was not dict:", type(raw))
        return None
    missing_keys = []
    if "activePlayer" not in raw:
        missing_keys.append("activePlayer")
    if "allPlayers" not in raw:
        missing_keys.append("allPlayers")
    if missing_keys:
        print("[debug] missing keys from live data:", missing_keys)
        # if activePlayer is missing we literally cannot get hp_pct
        return None

    me = raw.get("activePlayer", {}) or {}
    stats = me.get("championStats", {}) or {}

    # hp%
    cur_hp = stats.get("currentHealth")
    max_hp = stats.get("maxHealth")
    if cur_hp is not None and max_hp not in [None, 0]:
        hp_pct = float(cur_hp) / float(max_hp)
    else:
        hp_pct = None

    level = me.get("level")
    gold = me.get("currentGold")

    you_name = (
        me.get("summonerName")
        or me.get("riotId")
        or me.get("riotIdGameName")
    )

    kills = deaths = assists = cs = None

    ap_list = raw.get("allPlayers", [])
    if isinstance(ap_list, dict):
        ap_list = list(ap_list.values())

    # find yourself in allPlayers to get scoreboard stuff
    found_self = False
    for p in ap_list:
        pname = (
            p.get("summonerName")
            or p.get("riotId")
            or p.get("riotIdGameName")
        )
        if pname == you_name:
            found_self = True
            scores = p.get("scores", {}) or {}
            kills = scores.get("kills")
            deaths = scores.get("deaths")
            assists = scores.get("assists")
            cs = scores.get("creepScore")
            break

    # debug if we couldn't match your name in allPlayers
    if not found_self:
        print("[debug] couldn't match self in allPlayers. you_name=", you_name)
        print("[debug] available names:", [
            (
                q.get("summonerName")
                or q.get("riotId")
                or q.get("riotIdGameName")
            ) for q in ap_list
        ])

    feats = {
        "hp_pct": hp_pct,
        "level": level,
        "deaths": deaths,
        "kills": kills,
        "assists": assists,
        "cs": cs,
        "gold": gold,
    }

    # sanity: do we at least have hp_pct and level?
    if hp_pct is None or level is None:
        print("[debug] missing hp_pct/level. feats now =", feats)
        return None

    # sanity: did we fail to get deaths/kills/etc?
    if deaths is None:
        print("[debug] scoreboard not linked yet. feats now =", feats)
        # we won't bail here; we'll just fill defaults below

    # fill like training did
    if feats["gold"] is None:
        feats["gold"] = -1.0
    for k in ["kills", "deaths", "assists", "cs"]:
        if feats[k] is None:
            feats[k] = 0

    return feats



def load_model():
    """
    Load scaler + classifier + feature order from death_model.pkl
    """
    bundle = joblib.load(MODEL_FILE)
    scaler = bundle["scaler"]
    clf = bundle["clf"]
    feature_cols = bundle["feature_cols"]
    return scaler, clf, feature_cols


def predict_risk(scaler, clf, feature_cols, feats_now):
    """
    Take the current feature dict from get_live_snapshot(),
    run it through the scaler+model, return probability of death in 10s.
    """
    # Make sure all required features are present
    row = []
    for col in feature_cols:
        val = feats_now.get(col)

        # fill the same way we did in training
        if col == "gold" and val is None:
            val = -1.0
        if col in ["kills", "deaths", "assists", "cs"] and val is None:
            val = 0

        if val is None:
            # missing critical data -> can't score
            return None

        row.append(val)

    x_raw = np.array([row], dtype=float)
    x = scaler.transform(x_raw)

    if hasattr(clf, "predict_proba"):
        prob = clf.predict_proba(x)[0, 1]
    else:
        score = clf.decision_function(x)[0]
        prob = 1 / (1 + np.exp(-score))

    return float(prob)


def main():
    print("[info] loading model...")
    try:
        scaler, clf, feature_cols = load_model()
    except Exception as e:
        print("[fatal] couldn't load model:", e)
        return

    print("[info] starting live loop. Ctrl+C to stop.")
    while True:
        feats = get_live_snapshot()
        if feats is None:
            print("no live data yet (are you in game / alive?)")
        else:
            prob = predict_risk(scaler, clf, feature_cols, feats)
            if prob is None:
                print("not enough info to score yet")
            else:
                # prob is [0..1], convert to %
                pct = prob * 100.0

                # basic vibe meter
                if pct >= 80:
                    status = "🚨 YOU'RE INTING 🚨"
                elif pct >= 50:
                    status = "⚠ high danger"
                elif pct >= 25:
                    status = "caution"
                else:
                    status = "chill"

                # print nice line
                print(f"HP={feats['hp_pct']:.2f} lvl={feats['level']} deaths={feats['deaths']} gold={feats['gold']:.0f}  → death risk {pct:5.1f}% [{status}]")

        time.sleep(1.0)


if __name__ == "__main__":
    main()
