# Database Model Analysis & Enhancement Suggestions

## Current GameSession Model

### Fields Currently Recorded

#### 📋 **Unique Identifier**
```python
id = AutoField(primary_key=True)  # Django auto-generated unique ID
```
- **Purpose:** Unique identifier for each game
- **Usage:** Track specific games, recovery on restart
- **Status:** ✅ Essential

---

#### 🖥️ **Server Information**
```python
server_id = CharField(max_length=255, db_index=True)
server_name = CharField(max_length=255)
server_address = CharField(max_length=100)
```
- **What's captured:**
  - `server_id`: Steam server ID (unique per server)
  - `server_name`: Display name (e.g., "[ERI #7] Kribensis")
  - `server_address`: IP:Port (e.g., "207.174.97.5:27015")
- **Usage:** Server usage statistics, filter by server
- **Status:** ✅ Good coverage

---

#### 🗺️ **Game Details**
```python
map_name = CharField(max_length=100, db_index=True)
game_mode = CharField(max_length=100, default='Unknown')
region = CharField(max_length=50, default='Unknown')
```
- **What's captured:**
  - `map_name`: Map name (e.g., "Hotspot", "Crossfire")
  - `game_mode`: "Competitive Capture" or "Casual Elimination"
  - `region`: Geographic region (US, EU, AU, AS)
- **Usage:** Map frequency analysis, regional statistics
- **Status:** ✅ Good coverage

---

#### ⏰ **Timing**
```python
lobby_start = DateTimeField(null=True, blank=True)
game_start = DateTimeField(db_index=True)
game_end = DateTimeField(null=True, blank=True)
duration_seconds = IntegerField(null=True, blank=True)
```
- **What's captured:**
  - `lobby_start`: When server entered lobby (optional)
  - `game_start`: When game actually started (in_game)
  - `game_end`: When game ended (debrief)
  - `duration_seconds`: Calculated game length
- **Usage:** Game duration stats, peak time analysis
- **Status:** ✅ Essential timing data
- **Missing:** 🤔 Lobby duration (time spent waiting)

---

#### 👥 **Player Counts**
```python
players_at_start = IntegerField(default=0)
players_at_end = IntegerField(default=0)
max_players_during_game = IntegerField(default=0)
```
- **What's captured:**
  - `players_at_start`: Players when game started
  - `players_at_end`: Players when game ended
  - `max_players_during_game`: Peak players during game
- **Usage:** Player retention analysis, popular times
- **Status:** ✅ Good coverage
- **Missing:** 🤔 Player churn rate, average players during game

---

#### 🎮 **Game Attributes**
```python
competitive = BooleanField(default=False)
autobalance = BooleanField(default=False)
rank_restricted = BooleanField(default=False)
```
- **What's captured:**
  - `competitive`: Competitive vs casual mode
  - `autobalance`: Team autobalance enabled
  - `rank_restricted`: Rank restrictions active
- **Usage:** Game mode preference analysis
- **Status:** ✅ Good game settings coverage

---

#### 📊 **Status Tracking**
```python
is_ongoing = BooleanField(default=True, db_index=True)
is_valid_game = BooleanField(default=False)
created_at = DateTimeField(auto_now_add=True)
updated_at = DateTimeField(auto_now=True)
```
- **What's captured:**
  - `is_ongoing`: Whether game is still in progress
  - `is_valid_game`: Whether game lasted 5+ minutes
  - `created_at`: Record creation timestamp
  - `updated_at`: Last update timestamp
- **Usage:** Game recovery, data validation
- **Status:** ✅ Essential metadata

---

## Available Data NOT Currently Recorded

### From Steam API & Server Rules

#### 🎯 **Available but Missing:**

1. **`submode`** - Actual game submode
   - **Available values:** "Capture", "Elimination", "Escort", "Defense"
   - **Current:** Embedded in `game_mode` string
   - **Suggestion:** ⭐ Add as separate field for better filtering

2. **`max_players`** - Server capacity
   - **Available:** From Steam API
   - **Current:** Not stored (only player counts)
   - **Suggestion:** ⭐ Add to understand full/empty dynamics

3. **`map_capacity`** - Map player capacity
   - **Available:** Extracted from map name "(8P)", "(10P)", etc.
   - **Current:** Not stored
   - **Suggestion:** ⭐ Useful for map balance analysis

4. **`version`** - Game version
   - **Available:** From Steam API
   - **Current:** Not stored
   - **Suggestion:** ⭐ Track version changes and their impact

5. **`secure`** - VAC secure status
   - **Available:** From Steam API
   - **Current:** Not stored
   - **Suggestion:** ⚠️ Low priority (most are secure)

6. **`has_password`** - Password protected
   - **Available:** From Steam API
   - **Current:** Not stored
   - **Suggestion:** ⭐ Useful for public vs private server stats

7. **`dedicated`** - Dedicated server flag
   - **Available:** From Steam API
   - **Current:** Not stored
   - **Suggestion:** ⚠️ Low priority (all are dedicated)

---

## 🚀 Suggested Enhancements

### Priority 1: High Value Additions

#### 1. **Submode as Separate Field** ⭐⭐⭐
```python
submode = models.CharField(max_length=50, default='Unknown', db_index=True)
```
**Benefits:**
- Easy filtering: "Show me all Capture games"
- Better analytics: "Which submode is most popular?"
- Cleaner than parsing `game_mode` string

**Statistics enabled:**
- Most popular submodes
- Win rates by submode (if we add outcome tracking)
- Submode trends over time

---

#### 2. **Server Capacity & Utilization** ⭐⭐⭐
```python
server_max_players = models.IntegerField(default=0)
map_capacity = models.IntegerField(default=0)
```
**Benefits:**
- **Utilization rate:** `players_at_start / server_max_players`
- **Map fill rate:** `players_at_start / map_capacity`
- Identify under/over-filled games

**Statistics enabled:**
- "Average server utilization: 75%"
- "Most efficient map capacity usage"
- "Games that started at < 50% capacity"

---

#### 3. **Lobby Duration** ⭐⭐⭐
```python
lobby_duration_seconds = models.IntegerField(null=True, blank=True)
```
**Calculation:** `game_start - lobby_start` (if lobby_start is tracked)

**Benefits:**
- **Wait time analysis:** How long before games fill up
- **Peak time identification:** When do games start faster?
- **Server popularity:** Faster-filling servers

**Statistics enabled:**
- "Average lobby wait time: 3.5 minutes"
- "Peak times: Games fill 2x faster at 8PM PST"
- "Fastest-filling servers"

---

#### 4. **Game Version** ⭐⭐
```python
game_version = models.CharField(max_length=20, default='Unknown')
```
**Benefits:**
- Track version updates and their impact
- "Did player count change after update X?"
- Historical analysis across versions

**Statistics enabled:**
- "Games played per version"
- "Version adoption rate"
- "Player count trends by version"

---

#### 5. **Password Protected Flag** ⭐⭐
```python
has_password = models.BooleanField(default=False)
```
**Benefits:**
- Public vs private server statistics
- Community engagement metrics
- Server accessibility analysis

**Statistics enabled:**
- "80% of games are public"
- "Private servers average 6.5 players vs 8.2 for public"

---

### Priority 2: Calculated & Derived Fields

#### 6. **Average Players During Game** ⭐⭐⭐
```python
avg_players_during_game = models.FloatField(null=True, blank=True)
```
**Calculation:** 
- Option A: `(players_at_start + players_at_end + max_players) / 3`
- Option B: Sample periodically during game (more accurate but complex)

**Benefits:**
- Player retention metric
- Better than just start/end
- Identifies games with high churn

**Statistics enabled:**
- "Average player retention: 92%"
- "Games that lost the most players mid-game"

---

#### 7. **Player Churn Rate** ⭐⭐
```python
player_churn_rate = models.FloatField(null=True, blank=True)
```
**Calculation:** `(players_at_start - players_at_end) / players_at_start`

**Benefits:**
- Identify problematic games/maps
- Quality indicator
- Community health metric

**Statistics enabled:**
- "Average churn: 15%"
- "Maps with highest player retention"
- "Servers with best retention"

---

#### 8. **Utilization Percentage** ⭐⭐
```python
server_utilization = models.FloatField(null=True, blank=True)
```
**Calculation:** `players_at_start / server_max_players * 100`

**Benefits:**
- Capacity planning
- Server efficiency
- Identify underutilized servers

---

### Priority 3: Advanced Analytics Fields

#### 9. **Time of Day** ⭐⭐⭐
```python
start_hour_pst = models.IntegerField(null=True, blank=True)  # 0-23
day_of_week = models.IntegerField(null=True, blank=True)  # 0=Monday, 6=Sunday
```
**Calculation:** Extract from `game_start` in PST

**Benefits:**
- Peak time analysis without complex queries
- Indexed for fast lookups
- Day/time pattern analysis

**Statistics enabled:**
- "Most popular hour: 8PM PST"
- "Weekend vs weekday activity"
- "Heatmap of game starts by time"

---

#### 10. **Game Outcome** ⭐⭐⭐ (Future Enhancement)
```python
winning_team = models.CharField(max_length=20, null=True, blank=True)  # "Red", "Blue", "Draw"
```
**Note:** Requires additional API or server rules data

**Benefits:**
- Win rate analysis
- Team balance metrics
- Map balance assessment

**Statistics enabled:**
- "Map win rates: Hotspot 52% Red, 48% Blue"
- "Team autobalance effectiveness"
- "Competitive game balance"

---

#### 11. **Player Snapshots During Game** ⭐⭐ (Advanced)
**Create separate model:**
```python
class GamePlayerSnapshot(models.Model):
    game = models.ForeignKey(GameSession, on_delete=models.CASCADE)
    timestamp = models.DateTimeField()
    player_count = models.IntegerField()
```

**Benefits:**
- Track player count over time during game
- More accurate average calculations
- Identify exact moments of player drops

**Statistics enabled:**
- "Player count graph for each game"
- "Precise player retention curves"
- "Identify common drop-off points"

---

## 📊 New Statistics Enabled by Enhancements

### Current Statistics
✅ Total games played  
✅ Games today  
✅ Average game duration  
✅ Total playtime  
✅ Average players per game  
✅ Most played maps  
✅ Server usage  

### New Statistics with Enhancements

#### With Submode Field:
- 🆕 Most popular game submodes
- 🆕 "Capture games: 45%, Elimination: 30%, Escort: 15%, Defense: 10%"
- 🆕 Submode trends over time

#### With Server Capacity:
- 🆕 Average server utilization: 75%
- 🆕 "Games start at average 6.5/8 players (81% capacity)"
- 🆕 Under-filled vs over-filled games

#### With Lobby Duration:
- 🆕 Average lobby wait time: 3.5 minutes
- 🆕 "Games at 8PM fill 2x faster than 2PM"
- 🆕 Fastest-filling servers

#### With Player Churn:
- 🆕 Average player retention: 85%
- 🆕 "Maps with best retention: Hotspot (92%), Crossfire (88%)"
- 🆕 Games with high churn (quality indicator)

#### With Time of Day:
- 🆕 Peak gaming hours: 6PM-11PM PST
- 🆕 Weekend vs weekday activity
- 🆕 "70% of games happen between 6PM-11PM"

#### With Version Tracking:
- 🆕 "Version 1.5 increased average players by 15%"
- 🆕 Version adoption rates
- 🆕 Historical comparisons

---

## 🎯 Recommended Implementation Plan

### Phase 1: High-Priority Fields (Immediate)
1. ✅ `submode` - Separate field for game submode
2. ✅ `server_max_players` - Server capacity
3. ✅ `map_capacity` - Map player capacity
4. ✅ `lobby_duration_seconds` - Calculated from lobby_start
5. ✅ `has_password` - Public vs private

**Effort:** Low (data already available)  
**Value:** High (significant analytics improvement)

### Phase 2: Calculated Fields (Short-term)
6. ✅ `avg_players_during_game` - Better retention metric
7. ✅ `player_churn_rate` - Quality indicator
8. ✅ `server_utilization` - Capacity metric
9. ✅ `start_hour_pst` - Time of day analysis
10. ✅ `day_of_week` - Day pattern analysis

**Effort:** Low-Medium (calculations from existing data)  
**Value:** High (advanced analytics)

### Phase 3: Advanced Features (Future)
11. ⏳ `game_version` - Version tracking
12. ⏳ `winning_team` - Outcome tracking (requires API extension)
13. ⏳ `GamePlayerSnapshot` model - Detailed player tracking

**Effort:** Medium-High (may need API changes)  
**Value:** Very High (professional-grade analytics)

---

## 💡 Example Enhanced Queries

### With Current Model:
```python
# Most played maps
GameSession.objects.filter(is_valid_game=True) \
    .values('map_name') \
    .annotate(count=Count('id')) \
    .order_by('-count')
```

### With Enhanced Model:
```python
# Most popular submode at peak hours
GameSession.objects.filter(
    is_valid_game=True,
    start_hour_pst__in=[20, 21, 22]  # 8-11PM
).values('submode') \
 .annotate(count=Count('id')) \
 .order_by('-count')

# Server utilization by time of day
GameSession.objects.values('start_hour_pst') \
    .annotate(avg_util=Avg('server_utilization')) \
    .order_by('start_hour_pst')

# Best player retention by map
GameSession.objects.filter(is_valid_game=True) \
    .values('map_name') \
    .annotate(
        avg_retention=Avg('player_churn_rate'),
        games=Count('id')
    ) \
    .filter(games__gte=10) \
    .order_by('avg_retention')
```

---

## 🚀 Summary

### Current Model: **7/10** ✅
- Good core coverage
- Tracks essential game data
- Enables basic statistics

### With Phase 1 Enhancements: **9/10** ⭐
- Comprehensive game tracking
- Advanced analytics capability
- Professional-grade statistics

### With Phase 2+3: **10/10** 🏆
- Best-in-class game analytics
- Predictive insights possible
- Community health monitoring

**Recommendation:** Implement Phase 1 immediately for significant analytics improvement with minimal effort!

