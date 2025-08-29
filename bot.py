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
import asyncio

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

async def send_with_rate_limit_handling(channel, message, max_retries=3):
    """Send a message to a channel with rate limit handling and retries."""
    for attempt in range(max_retries):
        try:
            await channel.send(message)
            return True
        except discord.HTTPException as e:
            if e.status == 429:  # Rate limited
                retry_after = float(e.response.headers.get('Retry-After', 1))
                print(f"Rate limited, waiting {retry_after} seconds before retry {attempt + 1}/{max_retries}")
                await asyncio.sleep(retry_after)
            else:
                print(f"HTTP error sending message: {e}")
                return False
        except Exception as e:
            print(f"Unexpected error sending message: {e}")
            return False
    
    print(f"Failed to send message after {max_retries} attempts")
    return False

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
            await send_with_rate_limit_handling(
                message.channel,
                f"⚠️ {user_name}, you've already submitted a result for Puzzle #{puzzle}. Only your first submission counts."
            )
        else:
            # Count guesses = number of lines containing squares + 1 (to account for off-by-1 error)
            guesses = len([line for line in message.content.splitlines() if re.search(r'[🟩🟦🟧🟨]', line)]) + 1
            leaderboard[puzzle][user_id] = {"name": user_name, "guesses": guesses}
            save_leaderboard(guild_id, leaderboard)
            print(f"Saved submission for {user_name} (Puzzle {puzzle}, {guesses} guesses)")
            await send_with_rate_limit_handling(
                message.channel,
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
            await send_with_rate_limit_handling(ctx.channel, "No puzzles have been recorded yet.")
            return
        puzzle_key = max(leaderboard.keys(), key=lambda k: int(k))  # latest puzzle
    else:
        puzzle_key = puzzle_number

    if puzzle_key not in leaderboard:
        await send_with_rate_limit_handling(ctx.channel, f"No results yet for Puzzle #{puzzle_key}.")
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

    await send_with_rate_limit_handling(ctx.channel, msg)


# --- Weekly Leaderboard Logic ---
def generate_weekly_leaderboard_message(guild_id):
    """Generate the weekly leaderboard message for a guild. Returns None if no data available."""
    leaderboard = load_leaderboard(guild_id)
    
    if not leaderboard:
        return None
    
    # Calculate weekly scores (last 7 puzzles)
    puzzle_numbers = sorted([int(k) for k in leaderboard.keys()])
    recent_puzzles = puzzle_numbers[-7:]  # Last 7 puzzles
    
    if len(recent_puzzles) == 0:
        return None
    
    # Aggregate scores across the week
    weekly_scores = {}
    
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
    
    # Calculate total scores with penalties for missed puzzles
    penalty_per_missed_puzzle = 6  # High penalty for skipping puzzles
    total_puzzles = len(recent_puzzles)
    
    for user_data in weekly_scores.values():
        missed_puzzles = total_puzzles - user_data['puzzles_played']
        penalty_points = missed_puzzles * penalty_per_missed_puzzle
        user_data['total_score'] = user_data['total_guesses'] + penalty_points
    
    sorted_weekly = sorted(weekly_scores.values(), key=lambda x: x['total_score'])
    
    msg = f"🏆 Weekly Leaderboard (Last {len(recent_puzzles)} puzzles: #{recent_puzzles[0]}-#{recent_puzzles[-1]}) 🏆\n"
    
    medals = ["🥇", "🥈", "🥉"]
    current_rank = 1
    prev_total = None
    
    for idx, entry in enumerate(sorted_weekly):
        # Handle ties - players with same total score get same rank
        if prev_total is not None and entry['total_score'] != prev_total:
            current_rank = idx + 1
        
        medal = medals[current_rank - 1] if current_rank <= 3 else "•"
        msg += f"{medal} {entry['name']}: {entry['total_score']} total ({entry['puzzles_played']}/{total_puzzles} puzzles)\n"
        prev_total = entry['total_score']

    return msg

# --- Command: Weekly Leaderboard ---
@bot.command(name="weekly_leaderboard")
async def weekly_leaderboard_cmd(ctx):
    guild_id = ctx.guild.id
    msg = generate_weekly_leaderboard_message(guild_id)
    
    if msg is None:
        await send_with_rate_limit_handling(ctx.channel, "No puzzles have been recorded yet.")
        return
    
    await send_with_rate_limit_handling(ctx.channel, msg)


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
            
            is_sunday = now.weekday() == 6  # Sunday is 6 in Python's weekday()
            
            for guild in bot.guilds:
                channel = discord.utils.get(guild.text_channels, name="connections")
                if channel:
                    leaderboard = load_leaderboard(guild.id)
                    if leaderboard:
                        # Post daily leaderboard
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
                            await send_with_rate_limit_handling(channel, msg)
                        else:
                            await send_with_rate_limit_handling(channel, "No results for today's puzzle yet.")
                        
                        # Post weekly leaderboard on Sundays
                        if is_sunday:
                            weekly_msg = generate_weekly_leaderboard_message(guild.id)
                            if weekly_msg:
                                await send_with_rate_limit_handling(channel, weekly_msg)
                            else:
                                await send_with_rate_limit_handling(channel, "No puzzles available for weekly leaderboard.")
                    else:
                        await send_with_rate_limit_handling(channel, "No puzzles have been recorded yet.")
                
                # Add delay between guilds to prevent rate limiting
                await asyncio.sleep(1)
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
    await send_with_rate_limit_handling(ctx.channel, "Leaderboard data cleared.")

@bot.command(name="show_leaderboard_file")
async def show_leaderboard_file(ctx):
    guild_id = ctx.guild.id
    file_name = get_leaderboard_file(guild_id)
    await send_with_rate_limit_handling(ctx.channel, f"Leaderboard file for this server: {file_name}")

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
