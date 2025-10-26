import requests
import urllib3
import joblib
import numpy as np
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LIVE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"
MODEL_FILE = "death_model.pkl"

def get_live_snapshot():
    """
    Grab current frame from the League liveclientdata API.
    Return a dict of your player's features (hp_pct, level, etc.)
    or None if we can't get valid data yet.
    """
    try:
        r = requests.get(LIVE_URL, verify=False, timeout=0.5)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        print("[warn] could not read live client:", e)
        return None

    # activePlayer is YOU
    me = raw.get("activePlayer", {}) or {}
    stats = me.get("championStats", {}) or {}

    # hp%
    cur_hp = stats.get("currentHealth")
    max_hp = stats.get("maxHealth")
    if cur_hp is not None and max_hp not in [None, 0]:
        hp_pct = float(cur_hp) / float(max_hp)
    else:
        # can't evaluate risk if we don't even know HP
        hp_pct = None

    level = me.get("level")
    gold = me.get("currentGold")

    # now we need scoreboard info for you from allPlayers
    you_name = me.get("summonerName") or me.get("riotId") or me.get("riotIdGameName")
    kills = deaths = assists = cs = None

    ap_list = raw.get("allPlayers", [])
    if isinstance(ap_list, dict):
        ap_list = list(ap_list.values())

    for p in ap_list:
        pname = p.get("summonerName") or p.get("riotId") or p.get("riotIdGameName")
        if pname == you_name:
            scores = p.get("scores", {}) or {}
            kills = scores.get("kills")
            deaths = scores.get("deaths")
            assists = scores.get("assists")
            cs = scores.get("creepScore")
            break

    # We only return a feature dict if we have enough info
    feats = {
        "hp_pct": hp_pct,
        "level": level,
        "deaths": deaths,
        "kills": kills,
        "assists": assists,
        "cs": cs,
        "gold": gold,
    }

    # basic sanity filter: if hp_pct is None you're probably not "in game" yet
    if (hp_pct is None) or (level is None):
        return None

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
