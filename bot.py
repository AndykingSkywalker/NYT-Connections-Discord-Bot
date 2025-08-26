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
            # Count guesses = number of lines containing squares + 1 (to account for off-by-1 error)
            guesses = len([line for line in message.content.splitlines() if re.search(r'[🟩🟦🟧🟨]', line)]) + 1
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
    current_rank = 1
    prev_guesses = None
    
    for idx, entry in enumerate(sorted_scores):
        # Handle ties - players with same score get same rank
        if prev_guesses is not None and entry['guesses'] != prev_guesses:
            current_rank = idx + 1
        
        medal = medals[current_rank - 1] if current_rank <= 3 else "•"
        msg += f"{medal} {entry['name']}: {entry['guesses']} guesses\n"
        prev_guesses = entry['guesses']

    await ctx.send(msg)


# --- Command: Weekly Leaderboard ---
@bot.command(name="weekly_leaderboard")
async def weekly_leaderboard_cmd(ctx):
    guild_id = ctx.guild.id
    leaderboard = load_leaderboard(guild_id)
    
    if not leaderboard:
        await ctx.send("No puzzles have been recorded yet.")
        return
    
    # Calculate weekly scores (last 7 puzzles)
    puzzle_numbers = sorted([int(k) for k in leaderboard.keys()])
    recent_puzzles = puzzle_numbers[-7:]  # Last 7 puzzles
    
    if len(recent_puzzles) == 0:
        await ctx.send("No puzzles available for weekly leaderboard.")
        return
    
    # Aggregate scores across the week
    weekly_scores = {}
    puzzle_count = {}
    
    for puzzle_num in recent_puzzles:
        puzzle_key = str(puzzle_num)
        if puzzle_key in leaderboard:
            for user_id, user_data in leaderboard[puzzle_key].items():
                if user_id not in weekly_scores:
                    weekly_scores[user_id] = {
                        'name': user_data['name'],
                        'total_guesses': 0,
                        'puzzles_played': 0
                    }
                weekly_scores[user_id]['total_guesses'] += user_data['guesses']
                weekly_scores[user_id]['puzzles_played'] += 1
    
    # Calculate average scores and sort
    for user_data in weekly_scores.values():
        user_data['average'] = user_data['total_guesses'] / user_data['puzzles_played']
    
    sorted_weekly = sorted(weekly_scores.values(), key=lambda x: x['average'])
    
    msg = f"🏆 Weekly Leaderboard (Last {len(recent_puzzles)} puzzles: #{recent_puzzles[0]}-#{recent_puzzles[-1]}) 🏆\n"
    
    medals = ["🥇", "🥈", "🥉"]
    current_rank = 1
    prev_average = None
    
    for idx, entry in enumerate(sorted_weekly):
        # Handle ties - players with same average get same rank
        if prev_average is not None and abs(entry['average'] - prev_average) > 0.001:  # Small epsilon for float comparison
            current_rank = idx + 1
        
        medal = medals[current_rank - 1] if current_rank <= 3 else "•"
        msg += f"{medal} {entry['name']}: {entry['average']:.1f} avg ({entry['puzzles_played']} puzzles)\n"
        prev_average = entry['average']

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
                            current_rank = 1
                            prev_guesses = None
                            
                            for idx, (uid, entry) in enumerate(sorted_scores):
                                # Handle ties - players with same score get same rank
                                if prev_guesses is not None and entry['guesses'] != prev_guesses:
                                    current_rank = idx + 1
                                
                                medal = medals[current_rank - 1] if current_rank <= 3 else "•"
                                msg += f"{medal} <@{uid}> {entry['guesses']} guesses\n"
                                prev_guesses = entry['guesses']
                            await channel.send(msg)
                        else:
                            await channel.send("No results for today's puzzle yet.")
                    else:
                        await channel.send("No puzzles have been recorded yet.")
    except Exception as e:
        print(f"Error in post_daily_leaderboard: {e}")
        import traceback
        traceback.print_exc()


# --- Command: Clear Leaderboard (Admin) ---
@bot.command(name="clear_leaderboard")
@commands.has_permissions(administrator=True)
async def clear_leaderboard(ctx):
    guild_id = ctx.guild.id
    save_leaderboard(guild_id, {})
    await ctx.send("Leaderboard data cleared.")

@bot.command(name="show_leaderboard_file")
async def show_leaderboard_file(ctx):
    guild_id = ctx.guild.id
    file_name = get_leaderboard_file(guild_id)
    await ctx.send(f"Leaderboard file for this server: {file_name}")

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
