# NYT Connections Discord Bot

Always reference these instructions first and fallback to search or bash commands only when you encounter unexpected information that does not match the info here.

This is a Python Discord bot that tracks and displays daily leaderboards for the New York Times Connections puzzle. Users post their results in a designated Discord channel (`#connections`), and the bot automatically records scores, provides leaderboard commands, and posts daily summaries.

## Working Effectively

### Bootstrap and Setup
- **Python Version**: Requires Python 3.8 or higher. Tested and validated with Python 3.12.3.
- **Dependencies Installation**: 
  ```bash
  pip install -r requirements.txt
  ```
  Takes approximately 10 seconds. NEVER CANCEL - Set timeout to 60+ seconds for safety.

### Environment Configuration
- **Required Environment File**: Create `.env` file in project root:
  ```env
  DISCORD_TOKEN=your-bot-token-here
  ```
- **Discord Bot Setup**: 
  - Bot token required from Discord Developer Portal
  - Bot needs permissions: "Read Messages/View Channels", "Send Messages", "Read Message History"
  - Bot monitors `#connections` channel specifically

### Running the Application
- **Start the bot**:
  ```bash
  python bot.py
  ```
- **Expected Startup Behavior**:
  - Flask keep-alive server starts on port 8081 (http://0.0.0.0:8081)
  - Displays "Bot is running!" at keep-alive endpoint
  - Bot attempts Discord connection (will fail without valid token)
  - NEVER CANCEL startup - Let it complete or fail naturally

### Code Validation
- **Syntax Check**: 
  ```bash
  python -m py_compile bot.py keep_alive.py
  ```
  All files must compile without syntax errors.
- **No Linting Tools**: This project does not use flake8, black, pylint, or other linting tools.
- **No Test Framework**: No unittest, pytest, or other testing infrastructure exists.

## Validation Scenarios

**CRITICAL**: Always manually validate core functionality after making changes:

### Core Bot Functionality Test
1. **Environment Setup Test**:
   ```bash
   echo "DISCORD_TOKEN=test_token" > .env
   timeout 30 python bot.py
   ```
   - Should start Flask server on port 8081
   - Should display keep-alive server startup messages
   - Should attempt Discord connection (will fail with test token - this is expected)

2. **Keep-alive Server Test**:
   ```bash
   # Kill any existing processes on port 8081 first
   pkill -f "keep_alive" 2>/dev/null || true
   sleep 2
   python3 -c "from keep_alive import keep_alive; import time; keep_alive(); time.sleep(10)" &
   sleep 3 && curl -s http://localhost:8081
   pkill -f "keep_alive" 2>/dev/null || true
   ```
   - Must return: "Bot is running!"

3. **Leaderboard Functions Test**:
   ```bash
   python3 -c "
   import json, os
   
   def get_leaderboard_file(guild_id):
       return f'leaderboard_{guild_id}.json'
   
   def load_leaderboard(guild_id):
       file = get_leaderboard_file(guild_id)
       if os.path.exists(file):
           with open(file, 'r') as f:
               return json.load(f)
       return {}
   
   def save_leaderboard(guild_id, data):
       file = get_leaderboard_file(guild_id)
       with open(file, 'w') as f:
           json.dump(data, f, indent=2)
   
   test_data = {'1001': {'12345': {'name': 'TestUser', 'guesses': 4}}}
   save_leaderboard(123456789, test_data)
   loaded = load_leaderboard(123456789)
   print('SUCCESS' if loaded == test_data else 'FAILED')
   os.remove('leaderboard_123456789.json') if os.path.exists('leaderboard_123456789.json') else None
   "
   ```
   - Must print: "SUCCESS"

4. **NYT Connections Parsing Test**:
   ```bash
   python3 -c "
   import re
   message = 'Connections\nPuzzle #543\n🟦🟦🟦🟦\n🟧🟧🟧🟧\n🟨🟨🟨🟨\n🟩🟩🟩🟩'
   match = re.search(r'Puzzle #(\d+)', message)
   if match and re.search(r'[🟩🟦🟧🟨]', message):
       puzzle = str(match.group(1))
       lines = message.split('\n')
       guesses = len([line for line in lines if re.search(r'[🟩🟦🟧🟨]', line)])
       print(f'Puzzle: {puzzle}, Guesses: {guesses}')
   "
   ```
   - Must print: "Puzzle: 543, Guesses: 4"

## Key Components

### Main Files
- **`bot.py`** - Main Discord bot application (184 lines)
- **`keep_alive.py`** - Flask web server for hosting services like Replit (15 lines)  
- **`requirements.txt`** - Python dependencies (21 packages)
- **`README.md`** - Setup and usage documentation
- **`.env`** - Environment variables (not tracked in git)

### Bot Commands
- **`!leaderboard today`** - Show today's leaderboard
- **`!leaderboard <puzzle_number>`** - Show specific puzzle leaderboard
- **`!clear_leaderboard`** - Admin command to clear leaderboard data
- **`!show_leaderboard_file`** - Show leaderboard file path for current server

### Data Storage
- **Leaderboard files**: `leaderboard_{guild_id}.json` (one per Discord server)
- **Auto-detection**: Monitors `#connections` channel for NYT Connections results
- **Threading**: Uses `threading.Lock()` for concurrent access protection

## Common Tasks

### Repository Structure
```
.
├── README.md              # Setup and usage documentation
├── LICENSE               # MIT license
├── bot.py               # Main Discord bot (184 lines)
├── keep_alive.py        # Flask keep-alive server (15 lines)
├── requirements.txt     # Dependencies (21 packages)
├── .gitignore          # Git ignore rules (.env, leaderboard.json files)
└── .idea/              # PyCharm IDE files
```

### Dependencies (requirements.txt)
```
discord.py==2.6.0        # Discord bot framework
Flask==3.1.2             # Web server for keep-alive
python-dotenv==1.1.1     # Environment variable loading
# ... plus 18 other dependencies
```

### Expected File Generation
After running the bot, these files may be created:
- `leaderboard_{guild_id}.json` - Per-server leaderboard data
- `__pycache__/` - Python bytecode cache
- `.env` - Environment variables (user-created)

## Common Troubleshooting

### Bot Won't Start
- **Check Python version**: `python --version` (must be 3.8+)
- **Check dependencies**: `pip install -r requirements.txt`
- **Check .env file**: Must contain valid `DISCORD_TOKEN=...`
- **Network issues**: Bot requires internet access to Discord API
- **Port 8081 in use**: Kill existing processes with `pkill -f "keep_alive"` or `pkill -f flask`

### Functionality Issues
- **No message detection**: Check bot is in `#connections` channel
- **Permissions**: Bot needs message read/write permissions
- **Leaderboard not saving**: Check file write permissions in project directory

### Development Notes
- **No build process**: Simple Python project, no compilation needed
- **No tests**: Add tests in `test_*.py` files if implementing test coverage
- **No CI/CD**: No GitHub Actions or other automated workflows
- **IDE files**: `.idea/` directory contains PyCharm configuration (can be ignored)

## Performance Expectations

- **Dependency installation**: ~10 seconds
- **Bot startup**: ~5-10 seconds (plus Discord connection time)
- **Keep-alive server startup**: <2 seconds
- **Leaderboard file operations**: <1 second per operation
- **Memory usage**: ~50-100MB typical for Discord bot