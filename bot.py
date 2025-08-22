import discord
from discord.ext import commands, tasks
import datetime
import re
import os
import json
from dotenv import load_dotenv
from keep_alive import keep_alive

# Load environment variables
load_dotenv()

# Start the web server to keep the bot alive
keep_alive()

# --- Bot Setup ---
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True  # Needed to read messages
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Leaderboard Storage ---
DATA_FILE = "leaderboard.json"

# Load existing data
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        leaderboard = json.load(f)
else:
    leaderboard = {}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(leaderboard, f, indent=2)

# --- Auto-detect NYT Connections results ---
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # Only process messages in "connections" channel
    if message.channel.name != "connections":
        return

    # Detect puzzle number
    match = re.search(r'Puzzle #(\d+)', message.content)
    if match and re.search(r'[🟩🟦🟧🟨]', message.content):
        puzzle = str(match.group(1))
        user_id = str(message.author.id)
        user_name = message.author.display_name

        # Only record the first submission for each user per puzzle
        leaderboard.setdefault(puzzle, {})
        if user_id in leaderboard[puzzle]:
            await message.channel.send(
                f"⚠️ {user_name}, you've already submitted a result for Puzzle #{puzzle}. Only your first submission counts."
            )
        else:
            # Count guesses = number of lines containing squares
            guesses = len([line for line in message.content.splitlines() if re.search(r'[🟩🟦🟧🟨]', line)])
            leaderboard[puzzle][user_id] = {"name": user_name, "guesses": guesses}
            save_data()
            await message.channel.send(
                f"✅ Recorded {user_name}'s result for Puzzle #{puzzle} ({guesses} guesses)"
            )

    await bot.process_commands(message)

# --- Command: Leaderboard ---
@bot.command(name="leaderboard")
async def leaderboard_cmd(ctx, puzzle_number: str):
    if puzzle_number.lower() == "today":
        if not leaderboard:
            await ctx.send("No puzzles have been recorded yet.")
            return
        puzzle_key = max(leaderboard.keys(), key=lambda k: int(k))  # latest puzzle
    else:
        puzzle_key = puzzle_number

    if puzzle_key not in leaderboard:
        await ctx.send(f"No results yet for Puzzle #{puzzle_key}.")
        return

    scores = leaderboard[puzzle_key]
    sorted_scores = sorted(scores.values(), key=lambda x: x["guesses"])

    msg = f"🏆 Leaderboard for Puzzle #{puzzle_key} 🏆\n"

    medals = ["🥇", "🥈", "🥉"]
    for idx, entry in enumerate(sorted_scores):
        medal = medals[idx] if idx < 3 else "•"
        msg += f"{medal} {entry['name']}: {entry['guesses']} guesses\n"

    await ctx.send(msg)


# --- Event: Final Leaderboard of the Day ---
@bot.event
async def on_ready():
    post_daily_leaderboard.start()

@tasks.loop(minutes=1)
async def post_daily_leaderboard():
    try:
        now = datetime.datetime.now(datetime.timezone.utc)  # Change timezone if your users are not in UTC
        if now.hour == 8 and now.minute == 0:
            for guild in bot.guilds:
                channel = discord.utils.get(guild.text_channels, name="connections")
                if channel:
                    if leaderboard:
                        puzzle_key = max(leaderboard.keys(), key=lambda k: int(k))
                        scores = leaderboard[puzzle_key]
                        if scores:  # Only post if there are results for the puzzle
                            sorted_scores = sorted(scores.values(), key=lambda x: x["guesses"])
                            msg = f"🏆 Final Leaderboard for Puzzle #{puzzle_key} 🏆\n"
                            medals = ["🥇", "🥈", "🥉"]
                            for idx, (uid, entry) in enumerate(sorted_scores):
                                medal = medals[idx] if idx < 3 else "•"
                                msg += f"{medal} <@{uid}> {entry['guesses']} guesses\n"
                            await channel.send(msg)
                        else:
                            await channel.send("No results for today's puzzle yet.")
                    else:
                        await channel.send("No puzzles have been recorded yet.")
    except Exception as e:
        print(f"Error in post_daily_leaderboard: {e}")
        import traceback
        traceback.print_exc()

# --- Run the Bot ---
bot.run(os.getenv("DISCORD_TOKEN"))
