# import requests
# import urllib3

# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# url = "https://127.0.0.1:2999/liveclientdata/allgamedata"

# try:
#     response = requests.get(url, verify=False)
#     response.raise_for_status()
#     data = response.json()
#     print("Game Data Snapshot:")
#     print(data["gameData"])
# except requests.exceptions.RequestException as e:
#     print("Error:", e)
import os 
import requests

from dotenv import load_dotenv

load_dotenv()
# ---------- CONFIG ----------
api_key = os.getenv("RIOT_API_KEY")   
match_id = os.getenv("MATCH_ID")
# ----------------------------

url = f"https://americas.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
headers = {"X-Riot-Token": api_key}

response = requests.get(url, headers=headers)
if response.status_code != 200:
    raise Exception(f"Error fetching match timeline: {response.status_code} {response.text}")

timeline = response.json()

# Get participant team mapping from metadata
participants = timeline["metadata"]["participants"]
# First 5 are blue (100), last 5 are red (200)
blue_participants = set(range(1, 6))
red_participants = set(range(6, 11))

# Initialize stats
blue_stats = {"kills": 0, "gold": 0, "towers": 0, "dragons": 0}
red_stats = {"kills": 0, "gold": 0, "towers": 0, "dragons": 0}

# Process frames up to 20 minutes (1,200,000 ms)
for frame in timeline["info"]["frames"]:
    if frame["timestamp"] > 600000:
        break
    
    # Calculate gold from participant frames (last frame's gold totals)
    if frame["timestamp"] <= 600000:
        blue_gold = 0
        red_gold = 0
        for pid, pframe in frame["participantFrames"].items():
            participant_id = int(pid)
            gold = pframe.get("totalGold", 0)
            if participant_id in blue_participants:
                blue_gold += gold
            else:
                red_gold += gold
        blue_stats["gold"] = blue_gold
        red_stats["gold"] = red_gold
    
    # Process events for kills, towers, dragons
    for event in frame.get("events", []):
        event_type = event.get("type")
        
        if event_type == "CHAMPION_KILL":
            killer_id = event.get("killerId")
            if killer_id in blue_participants:
                blue_stats["kills"] += 1
            elif killer_id in red_participants:
                red_stats["kills"] += 1
        
        elif event_type == "BUILDING_KILL":
            if event.get("buildingType") == "TOWER_BUILDING":
                killer_id = event.get("killerId")
                if killer_id in blue_participants:
                    blue_stats["towers"] += 1
                elif killer_id in red_participants:
                    red_stats["towers"] += 1
        
        elif event_type == "ELITE_MONSTER_KILL":
            if event.get("monsterType") == "DRAGON":
                killer_id = event.get("killerId")
                if killer_id in blue_participants:
                    blue_stats["dragons"] += 1
                elif killer_id in red_participants:
                    red_stats["dragons"] += 1

print("First 10 minutes stats:")
print("Blue Team:", blue_stats)
print("Red Team:", red_stats)