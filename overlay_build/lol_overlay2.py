import requests
import urllib3
import time
import tkinter as tk
from tkinter import ttk
import threading
import pickle
import pandas as pd
from openai import OpenAI

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
'''
Openai
'''
# # ---------- CONFIG ----------
# OPENAI_API_KEY = ""  # Add your OpenAI API key
# CHECK_INTERVALS = [10, 20, 30, 40]  # Minutes to check
# # ----------------------------

# # Initialize OpenAI client
# client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


'''
Open rounter
'''
import os 
from dotenv import load_dotenv

load_dotenv()
# ---------- CONFIG ----------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")  # Your OpenRouter key
CHECK_INTERVALS = [10, 20, 30, 40]
# ----------------------------

# Initialize OpenAI-compatible client pointing to OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
) if OPENROUTER_API_KEY else print("No API key found. Please add it in .env")




class StatsOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("League ML Predictor")
        
        # Remove window border and make transparent
        self.root.overrideredirect(True)  # Remove border
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.70)  # More visible
        
        # Smaller size, position in top-right corner
        screen_width = self.root.winfo_screenwidth()
        self.root.geometry(f"320x400+{screen_width-340}+20")
        
        # Dark semi-transparent background
        self.root.configure(bg='#1a1a1a')
        
        # For window dragging (initialize first!)
        self.x = 0
        self.y = 0
        
        # Title bar for dragging (since no border)
        self.title_bar = tk.Frame(self.root, bg='#2a2a2a', relief='flat', bd=0)
        self.title_bar.pack(fill='x')
        
        # Make title bar draggable
        self.title_bar.bind('<Button-1>', self.start_move)
        self.title_bar.bind('<B1-Motion>', self.do_move)
        
        # Title
        self.title_label = tk.Label(
            self.title_bar, 
            text="League Win Predictor",
            font=("Segoe UI", 10, "bold"),
            bg='#2a2a2a',
            fg='#ffffff'
        )
        self.title_label.pack(side='left', padx=10, pady=5)
        self.title_label.bind('<Button-1>', self.start_move)
        self.title_label.bind('<B1-Motion>', self.do_move)
        
        # Control buttons (small, clean)
        btn_frame = tk.Frame(self.title_bar, bg='#2a2a2a')
        btn_frame.pack(side='right', padx=5)
        
        self.minimize_btn = tk.Button(
            btn_frame,
            text="_",
            command=self.minimize_window,
            bg='#3a3a3a',
            fg='#cccccc',
            font=("Segoe UI", 8),
            relief='flat',
            bd=0,
            padx=8,
            pady=2,
            activebackground='#4a4a4a'
        )
        self.minimize_btn.pack(side='left', padx=2)
        
        self.quit_btn = tk.Button(
            btn_frame,
            text="X",
            command=self.root.quit,
            bg='#3a3a3a',
            fg='#cccccc',
            font=("Segoe UI", 8),
            relief='flat',
            bd=0,
            padx=8,
            pady=2,
            activebackground='#cc4444'
        )
        self.quit_btn.pack(side='left', padx=2)
        
        # Status
        self.status_label = tk.Label(
            self.root,
            text="Waiting for game...",
            font=("Segoe UI", 9),
            bg='#1a1a1a',
            fg='#999999'
        )
        self.status_label.pack(pady=5)
        
        # Stats frame
        self.stats_frame = tk.Frame(self.root, bg='#1a1a1a')
        self.stats_frame.pack(pady=5, padx=10, fill='both', expand=True)
        
        # Load ML model and scaler
        try:
            with open('league_win_predictor.pkl', 'rb') as f:
                self.model = pickle.load(f)
            with open('scaler.pkl', 'rb') as f:
                self.scaler = pickle.load(f)
            print("✓ ML Model loaded successfully")
        except Exception as e:
            print(f"✗ Error loading model: {e}")
            self.model = None
            self.scaler = None
        
        # Tracking variables
        self.last_check_minute = 0
        self.monitoring = False
        self.is_minimized = False
        
        # For window dragging
        self.x = 0
        self.y = 0
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self.monitor_game, daemon=True)
        self.monitor_thread.start()
    
    def start_move(self, event):
        self.x = event.x
        self.y = event.y
    
    def do_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")
        
    def minimize_window(self):
        if self.is_minimized:
            # Restore
            screen_width = self.root.winfo_screenwidth()
            self.root.geometry(f"320x400+{screen_width-340}+20")
            self.stats_frame.pack(pady=5, padx=10, fill='both', expand=True)
            self.status_label.pack(pady=5)
            self.minimize_btn.config(text="_")
            self.is_minimized = False
        else:
            # Minimize
            screen_width = self.root.winfo_screenwidth()
            self.root.geometry(f"250x35+{screen_width-270}+20")
            self.stats_frame.pack_forget()
            self.status_label.pack_forget()
            self.minimize_btn.config(text="□")
            self.is_minimized = True
        
    def restore_window(self):
        if self.is_minimized:
            self.minimize_window()  # Toggle back to full size
        
    def get_game_data(self):
        try:
            response = requests.get(
                "https://127.0.0.1:2999/liveclientdata/allgamedata",
                verify=False,
                timeout=2
            )
            return response.json()
        except:
            return None
    
    def calculate_stats(self, data):
        """Calculate team stats from live game data"""
        blue_stats = {
            'kills': 0, 'deaths': 0, 'assists': 0,
            'gold': 0, 'cs': 0, 'level': 0, 'count': 0
        }
        red_stats = {
            'kills': 0, 'deaths': 0, 'assists': 0,
            'gold': 0, 'cs': 0, 'level': 0, 'count': 0
        }
        
        for player in data.get('allPlayers', []):
            team = player.get('team', '')
            scores = player.get('scores', {})
            
            stats_dict = blue_stats if team == 'ORDER' else red_stats
            stats_dict['kills'] += scores.get('kills', 0)
            stats_dict['deaths'] += scores.get('deaths', 0)
            stats_dict['assists'] += scores.get('assists', 0)
            stats_dict['cs'] += scores.get('creepScore', 0)
            stats_dict['level'] += player.get('level', 0)
            stats_dict['count'] += 1
            
            # Calculate total gold
            current_gold = scores.get('currentGold', 0)
            items_value = sum(item.get('price', 0) for item in player.get('items', []))
            stats_dict['gold'] += current_gold + items_value
        
        # Calculate averages
        if blue_stats['count'] > 0:
            blue_stats['avg_level'] = blue_stats['level'] / blue_stats['count']
        if red_stats['count'] > 0:
            red_stats['avg_level'] = red_stats['level'] / red_stats['count']
        
        # Get objectives (simplified for live API)
        events = data.get('events', {}).get('Events', [])
        blue_stats['towers'] = sum(1 for e in events if e.get('EventName') == 'TurretKilled' and 'ORDER' in str(e.get('KillerName', '')))
        red_stats['towers'] = sum(1 for e in events if e.get('EventName') == 'TurretKilled' and 'CHAOS' in str(e.get('KillerName', '')))
        blue_stats['dragons'] = sum(1 for e in events if e.get('EventName') == 'DragonKill' and 'ORDER' in str(e.get('Stolen', '')))
        red_stats['dragons'] = sum(1 for e in events if e.get('EventName') == 'DragonKill' and 'CHAOS' in str(e.get('Stolen', '')))
        
        return blue_stats, red_stats
    
    def create_feature_vector(self, blue_stats, red_stats):
        """Create feature vector for ML model"""
        features = {
            'kills_diff': blue_stats['kills'] - red_stats['kills'],
            'deaths_diff': blue_stats['deaths'] - red_stats['deaths'],
            'assists_diff': blue_stats['assists'] - red_stats['assists'],
            'gold_diff': blue_stats['gold'] - red_stats['gold'],
            'cs_diff': blue_stats['cs'] - red_stats['cs'],
            'level_diff': blue_stats.get('avg_level', 0) - red_stats.get('avg_level', 0),
            'towers_diff': blue_stats.get('towers', 0) - red_stats.get('towers', 0),
            'inhibs_diff': 0,  # Live API doesn't track this easily
            'dragons_diff': blue_stats.get('dragons', 0) - red_stats.get('dragons', 0),
            'heralds_diff': 0,  # Live API doesn't track this easily
            'barons_diff': 0   # Live API doesn't track this easily
        }
        return pd.DataFrame([features])
    
    def get_player_team(self, data):
        """Determine which team the player is on"""
        # Try to identify player's team from active player data
        try:
            active_player = data.get('activePlayer', {})
            summoner_name = active_player.get('summonerName', '')
            
            # Find player in allPlayers
            for player in data.get('allPlayers', []):
                if player.get('summonerName') == summoner_name:
                    return player.get('team', 'ORDER')  # ORDER=Blue, CHAOS=Red
        except:
            pass
        return 'ORDER'  # Default to blue if can't determine
    
    def get_openai_tips(self, blue_prob, red_prob, blue_stats, red_stats, game_time_min, player_team):
        """Get AI-generated tips for the PLAYER'S team"""
        if not client:
            return "⚠️ OpenRouter API key not configured"
        
        # Determine if player is winning or losing
        is_blue_team = (player_team == 'ORDER')
        player_prob = blue_prob if is_blue_team else red_prob
        opponent_prob = red_prob if is_blue_team else blue_prob
        player_stats = blue_stats if is_blue_team else red_stats
        opponent_stats = red_stats if is_blue_team else blue_stats
        team_name = "Blue" if is_blue_team else "Red"
        
        is_winning = player_prob > opponent_prob
        
        if is_winning:
            prompt = f"""You are a League of Legends analyst. At {game_time_min} minutes, YOU are on {team_name} team and WINNING with {player_prob:.0%} win probability.

Your stats vs Enemy:
- Kills: {player_stats['kills']} vs {opponent_stats['kills']}
- Gold lead: ${player_stats['gold'] - opponent_stats['gold']}
- Towers: {player_stats.get('towers', 0)} vs {opponent_stats.get('towers', 0)}

Give 3 SHORT, actionable tips (10 words each max) to CLOSE OUT the game and secure the win. Focus on maintaining lead and finishing."""
        else:
            prompt = f"""You are a League of Legends analyst. At {game_time_min} minutes, YOU are on {team_name} team and LOSING with {player_prob:.0%} win probability.

Your stats vs Enemy:
- Kills: {player_stats['kills']} vs {opponent_stats['kills']}
- Gold deficit: ${opponent_stats['gold'] - player_stats['gold']}
- Towers: {player_stats.get('towers', 0)} vs {opponent_stats.get('towers', 0)}

Give 3 SHORT, actionable tips (10 words each max) for YOUR team to COMEBACK. Be specific and strategic."""

        try:
            response = client.chat.completions.create(
                model="anthropic/claude-3.5-haiku",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"⚠️ AI tips unavailable: {str(e)[:50]}"
    
    def display_stats(self, blue_stats, red_stats, game_time, blue_prob, red_prob, player_team):
        """Display stats with ML prediction"""
        # Clear previous stats
        for widget in self.stats_frame.winfo_children():
            widget.destroy()
        
        minutes = int(game_time // 60)
        
        # Determine if player is winning
        is_blue_team = (player_team == 'ORDER')
        player_prob = blue_prob if is_blue_team else red_prob
        is_winning = player_prob > (1 - player_prob)
        
        # Time header
        time_label = tk.Label(
            self.stats_frame,
            text=f"Analysis at {minutes} Minutes",
            font=("Segoe UI", 11, "bold"),
            bg='#1a1a1a',
            fg='#ffffff'
        )
        time_label.pack(pady=8)
        
        # Status
        status_text = "YOU ARE WINNING" if is_winning else "YOU ARE LOSING"
        status_color = '#00ff88' if is_winning else '#ff6666'
        
        tk.Label(
            self.stats_frame,
            text=status_text,
            font=("Segoe UI", 9, "bold"),
            bg='#1a1a1a',
            fg=status_color
        ).pack(pady=3)
        
        # Probability display
        prob_frame = tk.Frame(self.stats_frame, bg='#2a2a2a', relief='flat')
        prob_frame.pack(fill='x', pady=8, padx=10)
        
        # Your probability (larger)
        your_prob = blue_prob if is_blue_team else red_prob
        tk.Label(
            prob_frame,
            text=f"{your_prob:.0%}",
            font=("Segoe UI", 28, "bold"),
            bg='#2a2a2a',
            fg='#ffffff'
        ).pack()
        
        tk.Label(
            prob_frame,
            text="Win Probability",
            font=("Segoe UI", 8),
            bg='#2a2a2a',
            fg='#999999'
        ).pack()
        
        # Opponent probability (smaller)
        opp_prob = red_prob if is_blue_team else blue_prob
        tk.Label(
            prob_frame,
            text=f"Enemy: {opp_prob:.0%}",
            font=("Segoe UI", 9),
            bg='#2a2a2a',
            fg='#666666'
        ).pack(pady=(5,5))
        
        # AI Tips
        if client:
            tips_frame = tk.Frame(self.stats_frame, bg='#2a2a2a', relief='flat')
            tips_frame.pack(fill='both', expand=True, pady=5, padx=10)
            
            tip_header = "Strategy: Close Out" if is_winning else "Strategy: Comeback"
            tk.Label(
                tips_frame,
                text=tip_header,
                font=("Segoe UI", 9, "bold"),
                bg='#2a2a2a',
                fg='#ffffff'
            ).pack(anchor='w', padx=8, pady=(8,3))
            
            tips = self.get_openai_tips(blue_prob, red_prob, blue_stats, red_stats, minutes, player_team)
            
            tips_text = tk.Text(
                tips_frame,
                font=("Segoe UI", 8),
                bg='#1a1a1a',
                fg='#cccccc',
                height=4,
                wrap='word',
                relief='flat',
                padx=8,
                pady=5,
                borderwidth=0
            )
            tips_text.pack(fill='both', expand=True, pady=(0,8), padx=8)
            tips_text.insert('1.0', tips)
            tips_text.config(state='disabled')
    
    def monitor_game(self):
        while True:
            data = self.get_game_data()
            
            if data is None:
                self.root.after(0, lambda: self.status_label.config(
                    text="Waiting for game...",
                    fg='#999999'
                ))
                self.monitoring = False
                self.last_check_minute = 0
                time.sleep(5)
                continue
            
            # Get game time
            game_time = data.get('gameData', {}).get('gameTime', 0)
            current_minute = int(game_time // 60)
            
            if not self.monitoring:
                self.monitoring = True
            
            self.root.after(0, lambda m=current_minute, s=int(game_time % 60): 
                           self.status_label.config(
                               text=f"Game in progress - {m}:{s:02d}",
                               fg='#00ff88'
                           ))
            
            # Check if we hit an interval
            if current_minute in CHECK_INTERVALS and current_minute != self.last_check_minute:
                self.last_check_minute = current_minute
                
                blue_stats, red_stats = self.calculate_stats(data)
                
                # Determine player's team
                player_team = self.get_player_team(data)
                
                # Make ML prediction
                if self.model and self.scaler:
                    features = self.create_feature_vector(blue_stats, red_stats)
                    features_scaled = self.scaler.transform(features)
                    probabilities = self.model.predict_proba(features_scaled)[0]
                    red_prob, blue_prob = probabilities[0], probabilities[1]
                else:
                    blue_prob, red_prob = 0.5, 0.5
                
                self.root.after(0, lambda b=blue_stats, r=red_stats, t=game_time, bp=blue_prob, rp=red_prob, pt=player_team: 
                               self.display_stats(b, r, t, bp, rp, pt))
                
                # Flash window
                self.root.after(0, self.flash_window)
            
            time.sleep(2)
    
    def flash_window(self):
        # Restore if minimized
        self.restore_window()
        
        # Flash effect
        for _ in range(3):
            self.root.attributes('-alpha', 1.0)
            self.root.update()
            time.sleep(0.2)
            self.root.attributes('-alpha', 0.70)
            self.root.update()
            time.sleep(0.2)
    
    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = StatsOverlay()
    app.run()