import discord
from discord.ext import commands, tasks
import datetime
import re
import os
import json
from dotenv import load_dotenv
from keep_alive import keep_alive
import threading
import glob

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
def get_leaderboard_file(guild_id):
    return f"leaderboard_{guild_id}.json"

def load_leaderboard(guild_id):
    file = get_leaderboard_file(guild_id)
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return {}

def save_leaderboard(guild_id, data):
    file = get_leaderboard_file(guild_id)
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

# --- Auto-detect NYT Connections results ---
leaderboard_lock = threading.Lock()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # Only process messages in "connections" channel
    if message.channel.name != "connections":
        return

    guild_id = message.guild.id
    leaderboard = load_leaderboard(guild_id)

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
            save_leaderboard(guild_id, leaderboard)
            print(f"Saved submission for {user_name} (Puzzle {puzzle}, {guesses} guesses)")
            await message.channel.send(
                f"✅ Recorded {user_name}'s result for Puzzle #{puzzle} ({guesses} guesses)"
            )

    await bot.process_commands(message)

# --- Command: Leaderboard ---
@bot.command(name="leaderboard")
async def leaderboard_cmd(ctx, puzzle_number: str):
    guild_id = ctx.guild.id
    leaderboard = load_leaderboard(guild_id)

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

    #TODO: ADD FUNCTIONALITY FOR TIES (e.g. 2 people with 3 guesses)
    await ctx.send(msg)


# --- Event: Final Leaderboard of the Day ---
last_posted_minute = None

@bot.event
async def on_ready():
    post_daily_leaderboard.start()

@tasks.loop(minutes=1)
async def post_daily_leaderboard():
    global last_posted_minute
    try:
        now = datetime.datetime.now(datetime.timezone.utc)  # Change timezone if your users are not in UTC
        minute_key = f"{now.year}-{now.month}-{now.day}-{now.hour}-{now.minute}"
        if now.hour == 21 and now.minute == 0:  # 9:00 PM UTC
            if last_posted_minute == minute_key:
                return  # Prevent duplicate posts in the same minute
            last_posted_minute = minute_key
            for guild in bot.guilds:
                channel = discord.utils.get(guild.text_channels, name="connections")
                if channel:
                    leaderboard = load_leaderboard(guild.id)
                    if leaderboard:
                        puzzle_key = max(leaderboard.keys(), key=lambda k: int(k))
                        scores = leaderboard[puzzle_key]
                        if scores:
                            # Sort by guesses, but keep all users
                            sorted_scores = sorted(scores.items(), key=lambda x: x[1]["guesses"])
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

#TODO: ADD FUNCTIONALITY FOR TIES (e.g. 2 people with 3 guesses) THINKING ABOUT ADDING A TIEBREAKER GAME OF GUESS THE NUMBER, CLOSEST WINS

# --- Command: Clear Leaderboard (Admin) ---
@bot.command(name="clear_leaderboard")
@commands.has_permissions(administrator=True)
async def clear_leaderboard(ctx):
    guild_id = ctx.guild.id
    save_leaderboard(guild_id, {})
    await ctx.send("Leaderboard data cleared.")

def stop_bot():
    # This function can be called in tests to stop the bot if running
    try:
        if bot.is_closed():
            return
        import asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(bot.close())
    except Exception as e:
        print(f"Error stopping bot: {e}")

# --- Run the Bot ---
if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
