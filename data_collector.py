#Compiles data from previous games and formats stats in a readable manner
import requests
import time
import csv
from datetime import datetime






# ---------- CONFIG ----------
API_KEY = "RGAPI-a056c9df-c94b-4360-815b-dd16ed194ea5"  # YOUR RIOT API KEY HERE
REGION = "na1"
PLATFORM = "americas"
TARGET_GAMES = 500
# ----------------------------

BASE_URL = f"https://{REGION}.api.riotgames.com"
PLATFORM_URL = f"https://{PLATFORM}.api.riotgames.com"
HEADERS = {"X-Riot-Token": API_KEY}




#use to get around rate limit
request_times = []

def rate_limited_request(url, headers, params=None):
    """Make rate-limited API request (20/sec, 100/2min)"""
    global request_times


    #gets realworld time
    current_time = time.time()
    
    # Remove requests older than 2 minutes (100 requests every 2 mins)
    request_times = [t for t in request_times if current_time - t < 120]
    
    # Count recent requests (20 requests each second)
    requests_last_second = sum(1 for t in request_times if current_time - t < 1)
    requests_last_2min = len(request_times)
    
    # Wait if approaching limits (with buffer)
    if requests_last_second >= 18:  # Buffer of 2 below limit
        time.sleep(1.2)
    
    if requests_last_2min >= 90:  # Buffer of 10 below limit
        wait_time = 120 - (current_time - request_times[0]) + 5
        print(f"   ⏳ Rate limit buffer reached, waiting {int(wait_time)}s...")
        time.sleep(wait_time)
        request_times.clear()
    
    # Make the request
    request_times.append(time.time())
    
    if params:
        return requests.get(url, headers=headers, params=params)
    return requests.get(url, headers=headers)


def get_challenger_players():
    """Fetch high-elo player list (Challenger + Grandmaster + Masters)"""
    players = []
    
    # Get Challenger
    url = f"{BASE_URL}/lol/league/v4/challengerleagues/by-queue/RANKED_SOLO_5x5"
    response = rate_limited_request(url, HEADERS)
    if response.status_code == 200:
        data = response.json()
        for entry in data['entries'][:750]:
            players.append({'puuid': entry['puuid']})
    
    # Get Grandmaster
    url = f"{BASE_URL}/lol/league/v4/grandmasterleagues/by-queue/RANKED_SOLO_5x5"
    response = rate_limited_request(url, HEADERS)
    if response.status_code == 200:
        data = response.json()
        for entry in data['entries'][:750]:
            players.append({'puuid': entry['puuid']})
    
    # Get Masters (top 50)
    url = f"{BASE_URL}/lol/league/v4/masterleagues/by-queue/RANKED_SOLO_5x5"
    response = rate_limited_request(url, HEADERS)
    if response.status_code == 200:
        data = response.json()
        for entry in data['entries'][:750]:
            players.append({'puuid': entry['puuid']})
    
    print(f"✓ Found {len(players)} high-elo players")
    return players

# def get_puuid(summoner_name):
#     """Get puuid from summoner name"""
#     # URL encode the name to handle spaces/special chars
#     import urllib.parse
#     encoded_name = urllib.parse.quote(summoner_name)
    
#     url = f"{BASE_URL}/lol/summoner/v4/summoners/by-name/{encoded_name}"
#     response = requests.get(url, headers=HEADERS)
    
#     if response.status_code == 200:
#         return response.json()['puuid']
#     return None

def get_match_history(puuid, count=50):
    """Get recent ranked match IDs"""
    url = f"{PLATFORM_URL}/lol/match/v5/matches/by-puuid/{puuid}/ids"
    params = {
        # queue ensures only ranked and casual matches are considered (no game modes)
        'queue': 420,
        'start': 0,
        'count': count
    }
    response = requests.get(url, headers=HEADERS, params=params)
    
    if response.status_code == 200:
        return response.json()
    return []

def get_match_timeline(match_id):
    """Fetch match timeline data"""
    url = f"{PLATFORM_URL}/lol/match/v5/matches/{match_id}/timeline"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        return response.json()
    return None

def extract_stats_at_timestamp(timeline, target_ms):
    """Extract all stats at specific timestamp (10min = 600000ms)"""
    
    # Initialize stats
    stats = {
        'blue_kills': 0,
        'blue_deaths': 0,
        'blue_assists': 0,
        'blue_gold': 0,
        'blue_cs': 0,
        'blue_level': 0,
        'blue_towers': 0,
        'blue_inhibs': 0,
        'blue_dragons': 0,
        'blue_heralds': 0,
        'blue_barons': 0,
        'red_kills': 0,
        'red_deaths': 0,
        'red_assists': 0,
        'red_gold': 0,
        'red_cs': 0,
        'red_level': 0,
        'red_towers': 0,
        'red_inhibs': 0,
        'red_dragons': 0,
        'red_heralds': 0,
        'red_barons': 0
    }
    
    # Team participant IDs
    blue_team = set(range(1, 6))
    red_team = set(range(6, 11))
    
    # Process frames up to target timestamp
    for frame in timeline['info']['frames']:
        if frame['timestamp'] > target_ms:
            break
        
        # Calculate gold, CS, level from participant frames
        if frame['timestamp'] <= target_ms:
            blue_gold = 0
            red_gold = 0
            blue_cs = 0
            red_cs = 0
            blue_level_sum = 0
            red_level_sum = 0
            
            for pid, pframe in frame['participantFrames'].items():
                participant_id = int(pid)
                
                if participant_id in blue_team:
                    blue_gold += pframe.get('totalGold', 0)
                    blue_cs += pframe.get('minionsKilled', 0) + pframe.get('jungleMinionsKilled', 0)
                    blue_level_sum += pframe.get('level', 0)
                else:
                    red_gold += pframe.get('totalGold', 0)
                    red_cs += pframe.get('minionsKilled', 0) + pframe.get('jungleMinionsKilled', 0)
                    red_level_sum += pframe.get('level', 0)
            
            stats['blue_gold'] = blue_gold
            stats['red_gold'] = red_gold
            stats['blue_cs'] = blue_cs
            stats['red_cs'] = red_cs
            stats['blue_level'] = blue_level_sum / 5
            stats['red_level'] = red_level_sum / 5
        
        # Process events for kills, objectives
        for event in frame.get('events', []):
            event_type = event.get('type')
            
            # Champion kills
            if event_type == 'CHAMPION_KILL':
                killer_id = event.get('killerId')
                victim_id = event.get('victimId')
                assisting_ids = event.get('assistingParticipantIds', [])
                
                if killer_id in blue_team:
                    stats['blue_kills'] += 1
                    stats['red_deaths'] += 1
                    stats['blue_assists'] += len([aid for aid in assisting_ids if aid in blue_team])
                elif killer_id in red_team:
                    stats['red_kills'] += 1
                    stats['blue_deaths'] += 1
                    stats['red_assists'] += len([aid for aid in assisting_ids if aid in red_team])
            
            # Towers
            elif event_type == 'BUILDING_KILL':
                building_type = event.get('buildingType')
                killer_id = event.get('killerId', 0)
                team_id = event.get('teamId')
                
                if building_type == 'TOWER_BUILDING':
                    if team_id == 100:  # Blue tower destroyed
                        stats['red_towers'] += 1
                    elif team_id == 200:  # Red tower destroyed
                        stats['blue_towers'] += 1
                
                elif building_type == 'INHIBITOR_BUILDING':
                    if team_id == 100:
                        stats['red_inhibs'] += 1
                    elif team_id == 200:
                        stats['blue_inhibs'] += 1
            
            # Dragons, Heralds, Barons
            elif event_type == 'ELITE_MONSTER_KILL':
                monster_type = event.get('monsterType')
                killer_id = event.get('killerId', 0)
                
                if monster_type == 'DRAGON':
                    if killer_id in blue_team:
                        stats['blue_dragons'] += 1
                    elif killer_id in red_team:
                        stats['red_dragons'] += 1
                
                elif monster_type == 'RIFTHERALD':
                    if killer_id in blue_team:
                        stats['blue_heralds'] += 1
                    elif killer_id in red_team:
                        stats['red_heralds'] += 1
                
                elif monster_type == 'BARON_NASHOR':
                    if killer_id in blue_team:
                        stats['blue_barons'] += 1
                    elif killer_id in red_team:
                        stats['red_barons'] += 1
    
    return stats

def get_match_winner(match_id):
    """Determine which team won (1 = blue, 0 = red)"""
    url = f"{PLATFORM_URL}/lol/match/v5/matches/{match_id}"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        data = response.json()
        for team in data['info']['teams']:
            if team['teamId'] == 100:  # Blue team
                return 1 if team['win'] else 0
    return None

def collect_data():
    """Main data collection function"""
    
    print("🎮 League High-Elo Data Collector")
    print("=" * 50)
    
    # Get Challenger players
    print("\n📊 Fetching Challenger players...")
    players = get_challenger_players()
    
    # Prepare CSV
    fieldnames = [
        'match_id', 'timestamp_min',
        'kills_diff', 'deaths_diff', 'assists_diff',
        'gold_diff', 'cs_diff', 'level_diff',
        'towers_diff', 'inhibs_diff', 'dragons_diff',
        'heralds_diff', 'barons_diff',
        'blue_win'
    ]
    
    output_file = f'lol_training_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        matches_processed = 0
        processed_match_ids = set()
        
        for player in players:
            if matches_processed >= TARGET_GAMES:
                break
            
            puuid = player['puuid']
            print(f"\n👤 Processing player #{players.index(player) + 1}...")
           
            
            # Get match history
            match_ids = get_match_history(puuid, count=50)
            print(f"   📋 Found {len(match_ids)} recent matches")
            
            for match_id in match_ids:
                if matches_processed >= TARGET_GAMES:
                    break
                
                if match_id in processed_match_ids:
                    continue
                
                processed_match_ids.add(match_id)
                
                try:
                    # Get timeline
                    timeline = get_match_timeline(match_id)
                    if not timeline:
                        continue
                    
                 
                    
                    # Get winner
                    blue_win = get_match_winner(match_id)
                    if blue_win is None:
                        continue
                    
                    
                    
                    # Extract stats at 10, 20, 30 minutes
                    max_timestamp = timeline['info']['frames'][-1]['timestamp']
                    max_timestamp_min = max_timestamp // 60000  # Convert to minutes

                    for timestamp_min in range(10, int(max_timestamp_min) + 1, 10):
                        timestamp_ms = timestamp_min * 60 * 1000
                        
                        stats = extract_stats_at_timestamp(timeline, timestamp_ms)
                        
                        # Calculate differences (Blue - Red)
                        row = {
                            'match_id': match_id,
                            'timestamp_min': timestamp_min,
                            'kills_diff': stats['blue_kills'] - stats['red_kills'],
                            'deaths_diff': stats['blue_deaths'] - stats['red_deaths'],
                            'assists_diff': stats['blue_assists'] - stats['red_assists'],
                            'gold_diff': stats['blue_gold'] - stats['red_gold'],
                            'cs_diff': stats['blue_cs'] - stats['red_cs'],
                            'level_diff': round(stats['blue_level'] - stats['red_level'], 2),
                            'towers_diff': stats['blue_towers'] - stats['red_towers'],
                            'inhibs_diff': stats['blue_inhibs'] - stats['red_inhibs'],
                            'dragons_diff': stats['blue_dragons'] - stats['red_dragons'],
                            'heralds_diff': stats['blue_heralds'] - stats['red_heralds'],
                            'barons_diff': stats['blue_barons'] - stats['red_barons'],
                            'blue_win': blue_win
                        }
                        
                        writer.writerow(row)
                    
                    matches_processed += 1
                    print(f"   ✓ Match {matches_processed}/{TARGET_GAMES} processed")
                    
                except Exception as e:
                    print(f"   ⚠ Error processing {match_id}: {e}")
                    continue
    
    print(f"\n✅ Data collection complete!")
    print(f"📁 Saved to: {output_file}")
    print(f"📊 Total matches: {matches_processed}")

if __name__ == "__main__":
    if not API_KEY:
        print("❌ ERROR: Please add your Riot API key at the top of the script!")
    else:
        collect_data()