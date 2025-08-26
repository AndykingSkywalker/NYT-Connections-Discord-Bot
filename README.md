# Discord Connections Bot

A Discord bot for tracking and displaying daily leaderboards for the New York Times Connections puzzle. Users post their results in a designated channel, and the bot automatically records their scores, provides leaderboard commands, and posts a daily summary.

## Features
- Automatically detects and records NYT Connections results posted in a specific channel (default: `#connections`).
- Maintains a daily leaderboard based on the number of guesses.
- Provides a `!leaderboard` command to display results for any puzzle or for today.
- Posts a final leaderboard summary at a scheduled time each day.
- Stores data in a local JSON file (`leaderboard.json`).

## Setup
1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/discord-connections-bot.git
   cd discord-connections-bot
   ```
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   Ensure you have Python 3.8 or higher installed.
   ```
3. **Create a Discord bot and get your token:**
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   - Create a new application and add a bot
   - Copy the bot token
4. **Configure environment variables:**
   - Create a `.env` file in the project root:
     ```env
     DISCORD_TOKEN=your-bot-token-here
     ```
5. **Run the bot:**
   ```bash
   python bot.py
   ```

## Adding the Bot to Your Server
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and select your bot.
2. Under "OAuth2" > "URL Generator":
   - Select "bot" as a scope.
   - Under "Bot Permissions", select at least "Read Messages/View Channels", "Send Messages", and "Read Message History".
   - Copy the generated URL and visit it in your browser to invite the bot to your server.

## Usage
- Post your NYT Connections results in the `#connections` channel.
- Use `!leaderboard today` or `!leaderboard <puzzle_number>` to view the leaderboard for a specific puzzle.
- Use `!weekly_leaderboard` to view the weekly leaderboard (total scores across the last 7 puzzles, with penalties for missed puzzles).
- The bot will post a daily summary at the configured time (default: 21:00 UTC).

## Timezone
- By default, the bot uses UTC for scheduling. If your users are in a different timezone, adjust the timezone in `bot.py` accordingly.

## Contributing
Pull requests and suggestions are welcome!

## License
MIT

