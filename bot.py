"""Discord bot for tracking NYT Connections results in per-guild leaderboards.

Leaderboard entry schema notes:
- ``guesses`` stores the ranking score (including penalties for incompletes).
- ``actual_guesses`` stores raw submitted guess-line count.
- ``score`` is written as an alias to ``guesses`` for clearer
  future schema use.
"""

import asyncio
import datetime
import json
import os
import re
import threading

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from keep_alive import keep_alive

# Load environment variables
load_dotenv()

# Create a variable for discord token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if DISCORD_TOKEN is None:
    print("Error: DISCORD_TOKEN environment variable not set.")

# --- Bot Setup ---
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True  # Needed to read messages
bot = commands.Bot(command_prefix="!", intents=intents)
GUILD_ONLY_MESSAGE = "This command can only be used in a server channel."


# --- Leaderboard Storage ---
def get_leaderboard_file(guild_id):
    """Return the per-guild leaderboard filename."""
    return f"leaderboard_{guild_id}.json"


def _quarantine_leaderboard_file(file_path, reason):
    """Move a corrupted leaderboard file aside to avoid repeated failures."""
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    quarantined = f"{file_path}.corrupt.{timestamp}"
    counter = 1
    while os.path.exists(quarantined):
        quarantined = f"{file_path}.corrupt.{timestamp}.{counter}"
        counter += 1

    try:
        os.replace(file_path, quarantined)
        print(
            f"Quarantined leaderboard file {file_path} to {quarantined} "
            f"({reason})."
        )
    except OSError as e:
        print(
            f"Error quarantining leaderboard file {file_path}: {e}. "
            "Continuing with empty in-memory leaderboard."
        )


def _get_sorted_numeric_puzzle_numbers(leaderboard):
    """Return sorted numeric puzzle numbers, skipping malformed keys."""
    puzzle_numbers = []
    invalid_keys = []
    for key in leaderboard.keys():
        try:
            puzzle_numbers.append(int(key))
        except (TypeError, ValueError):
            invalid_keys.append(key)

    if invalid_keys:
        joined = ", ".join(str(key) for key in invalid_keys)
        print(f"Warning: skipping non-numeric puzzle keys: {joined}")

    puzzle_numbers.sort()
    return puzzle_numbers


def _get_latest_numeric_puzzle_key(leaderboard):
    """Return latest numeric puzzle key as a string, or None if absent."""
    puzzle_numbers = _get_sorted_numeric_puzzle_numbers(leaderboard)
    if not puzzle_numbers:
        return None
    return str(puzzle_numbers[-1])


def load_leaderboard(guild_id):
    """Load leaderboard data for a guild from disk."""
    file = get_leaderboard_file(guild_id)
    if os.path.exists(file):
        try:
            with open(file, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                print(
                    "Warning: leaderboard file "
                    f"{file} has unexpected format; "
                    "quarantining the file and using an empty leaderboard."
                )
                _quarantine_leaderboard_file(file, "invalid JSON shape")
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error loading leaderboard file {file}: {e}")
            if os.path.exists(file):
                _quarantine_leaderboard_file(file, "read/decode failure")
        except Exception as e:
            print(f"Unexpected error loading leaderboard file {file}: {e}")
    return {}


def save_leaderboard(guild_id, data):
    """Persist leaderboard data for a guild to disk."""
    file = get_leaderboard_file(guild_id)
    directory = os.path.dirname(os.path.abspath(file)) or "."
    temp_file = os.path.join(
        directory,
        f".{os.path.basename(file)}.tmp-{os.getpid()}-{threading.get_ident()}",
    )

    try:
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, file)
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)


async def _get_guild_id_or_notify(ctx):
    """Return guild ID if in a server; otherwise send a DM-safe notice."""
    if ctx.guild is None:
        await send_with_rate_limit_handling(ctx.channel, GUILD_ONLY_MESSAGE)
        return None
    return ctx.guild.id


def _rank_medal(rank):
    """Return the medal marker for a given rank."""
    medals = ["🥇", "🥈", "🥉"]
    return medals[rank - 1] if rank <= 3 else "•"


def _entry_score(entry):
    """Return an entry's ranking score with backward compatibility."""
    return entry.get("score", entry.get("guesses", 10))


def _safe_display_name(name):
    """Escape mention-like patterns in user-controlled names."""
    return discord.utils.escape_mentions(str(name))


def _iter_ranked_entries(sorted_entries, score_getter):
    """Yield (rank, entry) pairs with tie-aware ranking."""
    current_rank = 1
    prev_score = None
    for idx, entry in enumerate(sorted_entries):
        score = score_getter(entry)
        if prev_score is not None and score != prev_score:
            current_rank = idx + 1
        yield current_rank, entry
        prev_score = score


def _format_puzzle_result(rank, entry, player_label):
    """Format one puzzle leaderboard row for command/scheduled posts."""
    if entry.get("status") == "incomplete":
        status_display = (
            f"❌ INCOMPLETE ({entry.get('connections_solved', 0)}/4)"
        )
        return f"💀 {player_label}: {status_display}"

    status_display = f"{_entry_score(entry)} guesses"
    return f"{_rank_medal(rank)} {player_label}: {status_display}"


def _format_weekly_result(rank, entry, total_puzzles):
    """Format one weekly leaderboard row."""
    complete = entry.get("complete_puzzles", entry["puzzles_played"])
    incomplete = entry.get("incomplete_puzzles", 0)
    return (
        f"{_rank_medal(rank)} {_safe_display_name(entry['name'])}: "
        f"{entry['total_score']} total "
        f"({complete}✅/{incomplete}❌ of {total_puzzles} puzzles)"
    )


# --- Auto-detect NYT Connections results ---
leaderboard_lock = threading.Lock()


async def send_with_rate_limit_handling(channel, message, max_retries=3):
    """Send a message to a channel with rate limit handling and retries."""
    for attempt in range(max_retries):
        try:
            await channel.send(
                message,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    roles=False,
                ),
            )
            return True
        except discord.HTTPException as e:
            if e.status == 429:  # Rate limited
                retry_after = float(e.response.headers.get("Retry-After", 1))
                print(
                    "Rate limited, waiting "
                    f"{retry_after} seconds before retry "
                    f"{attempt + 1}/{max_retries}"
                )
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
    """Parse puzzle submissions in #connections and record first attempts."""
    if message.author == bot.user:
        return

    # Only process messages in "connections" channel
    if message.channel.name != "connections":
        await bot.process_commands(message)
        return

    guild_id = message.guild.id

    # Detect puzzle number
    match = re.search(r"Puzzle #(\d+)", message.content)
    if match and re.search(r"[🟩🟦🟧🟨🟪]", message.content):
        puzzle = str(match.group(1))
        user_id = str(message.author.id)
        user_name = _safe_display_name(message.author.display_name)

        with leaderboard_lock:
            leaderboard = load_leaderboard(guild_id)

            # Only record the first submission for each user per puzzle.
            leaderboard.setdefault(puzzle, {})
            if user_id in leaderboard[puzzle]:
                response_message = (
                    "⚠️ "
                    f"{user_name}, you've already submitted a result for "
                    f"Puzzle #{puzzle}. Only your first submission counts."
                )
            else:
                # Count guesses = number of lines containing squares.
                full_group_pattern = r"^(🟩{4}|🟦{4}|🟧{4}|🟨{4}|🟪{4})$"
                connections_solved = sum(
                    1
                    for line in message.content.splitlines()
                    if re.match(full_group_pattern, line.strip())
                )
                guesses = len(
                    [
                        line
                        for line in message.content.splitlines()
                        if re.search(r"[🟩🟦🟧🟨🟪]", line)
                    ]
                )

                # Check if puzzle is complete (4 connections solved).
                is_complete = connections_solved >= 4

                if is_complete:
                    # Complete puzzle: use normal scoring.
                    final_score = guesses
                    status = "complete"
                    status_text = f"({guesses} guesses)"
                else:
                    # Incomplete puzzle: apply a penalty score and mark failed.
                    final_score = 10
                    status = "incomplete"
                    status_text = (
                        "(❌ INCOMPLETE - "
                        f"{connections_solved}/4 connections, "
                        "penalty score: 10)"
                    )

                leaderboard[puzzle][user_id] = {
                    # Keep guesses for backward compatibility.
                    # The score field is the clearer primary key.
                    "name": user_name,
                    "score": final_score,
                    "guesses": final_score,
                    "status": status,
                    "connections_solved": connections_solved,
                    "actual_guesses": guesses,
                }
                save_leaderboard(guild_id, leaderboard)
                print(
                    "Saved submission for "
                    f"{user_name} (Puzzle {puzzle}, {status_text})"
                )
                response_message = (
                    "✅ Recorded "
                    f"{user_name}'s result for Puzzle #{puzzle} "
                    f"{status_text}"
                )

        await send_with_rate_limit_handling(message.channel, response_message)

    await bot.process_commands(message)


# --- Command: Leaderboard ---
@bot.command(name="leaderboard")
async def leaderboard_cmd(ctx, puzzle_number: str):
    """Show puzzle leaderboard for a specific puzzle number or today."""
    guild_id = await _get_guild_id_or_notify(ctx)
    if guild_id is None:
        return

    leaderboard = load_leaderboard(guild_id)

    if puzzle_number.lower() == "today":
        if not leaderboard:
            await send_with_rate_limit_handling(
                ctx.channel, "No puzzles have been recorded yet."
            )
            return
        puzzle_key = _get_latest_numeric_puzzle_key(leaderboard)
        if puzzle_key is None:
            await send_with_rate_limit_handling(
                ctx.channel,
                "No valid numeric puzzles have been recorded yet.",
            )
            return
    else:
        puzzle_key = puzzle_number

    if puzzle_key not in leaderboard:
        await send_with_rate_limit_handling(
            ctx.channel, f"No results yet for Puzzle #{puzzle_key}."
        )
        return

    scores = leaderboard[puzzle_key]
    sorted_scores = sorted(scores.values(), key=_entry_score)

    lines = [f"🏆 Leaderboard for Puzzle #{puzzle_key} 🏆"]
    for rank, entry in _iter_ranked_entries(sorted_scores, _entry_score):
        lines.append(
            _format_puzzle_result(
                rank,
                entry,
                _safe_display_name(entry["name"]),
            )
        )

    msg = "\n".join(lines)

    await send_with_rate_limit_handling(ctx.channel, msg)


# --- Weekly Leaderboard Logic ---
def generate_weekly_leaderboard_message(guild_id):
    """Generate weekly standings text for a guild, if data exists."""
    leaderboard = load_leaderboard(guild_id)

    if not leaderboard:
        return None

    # Calculate weekly scores (last 7 puzzles)
    puzzle_numbers = _get_sorted_numeric_puzzle_numbers(leaderboard)
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
                        "name": user_data["name"],
                        "total_guesses": 0,
                        "puzzles_played": 0,
                        "complete_puzzles": 0,
                        "incomplete_puzzles": 0,
                    }
                weekly_scores[user_id]["total_guesses"] += _entry_score(
                    user_data
                )
                weekly_scores[user_id]["puzzles_played"] += 1

                # Track completion status for weekly stats
                if user_data.get("status") == "complete":
                    weekly_scores[user_id]["complete_puzzles"] += 1
                elif user_data.get("status") == "incomplete":
                    weekly_scores[user_id]["incomplete_puzzles"] += 1
                else:
                    # Old format - assume complete if no status field
                    weekly_scores[user_id]["complete_puzzles"] += 1

    # Calculate total scores with penalties for missed puzzles
    penalty_per_missed_puzzle = 6  # High penalty for skipping puzzles
    total_puzzles = len(recent_puzzles)

    for user_data in weekly_scores.values():
        missed_puzzles = total_puzzles - user_data["puzzles_played"]
        penalty_points = missed_puzzles * penalty_per_missed_puzzle
        user_data["total_score"] = user_data["total_guesses"] + penalty_points

    sorted_weekly = sorted(
        weekly_scores.values(), key=lambda x: x["total_score"]
    )

    lines = [
        "🏆 Weekly Leaderboard "
        f"(Last {len(recent_puzzles)} puzzles: "
        f"#{recent_puzzles[0]}-#{recent_puzzles[-1]}) 🏆"
    ]

    for rank, entry in _iter_ranked_entries(
        sorted_weekly, lambda item: item["total_score"]
    ):
        lines.append(_format_weekly_result(rank, entry, total_puzzles))

    return "\n".join(lines)


# --- Command: Weekly Leaderboard ---
@bot.command(name="weekly_leaderboard")
async def weekly_leaderboard_cmd(ctx):
    """Show the weekly leaderboard for the current guild."""
    guild_id = await _get_guild_id_or_notify(ctx)
    if guild_id is None:
        return

    msg = generate_weekly_leaderboard_message(guild_id)

    if msg is None:
        await send_with_rate_limit_handling(
            ctx.channel, "No puzzles have been recorded yet."
        )
        return

    await send_with_rate_limit_handling(ctx.channel, msg)


# --- Event: Final Leaderboard of the Day ---
last_posted_minute = None


@bot.event
async def on_ready():
    """Start scheduled posting when the bot is ready."""
    if not post_daily_leaderboard.is_running():
        post_daily_leaderboard.start()


async def _run_daily_leaderboard_cycle(now=None, guilds=None):
    """Run one daily leaderboard posting cycle."""
    global last_posted_minute

    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)

    if now.hour != 21 or now.minute != 0:
        return

    minute_key = f"{now.year}-{now.month}-{now.day}-{now.hour}-{now.minute}"
    if last_posted_minute == minute_key:
        return
    last_posted_minute = minute_key

    is_sunday = now.weekday() == 6

    target_guilds = guilds if guilds is not None else bot.guilds
    for guild in target_guilds:
        channel = discord.utils.get(guild.text_channels, name="connections")
        if channel:
            leaderboard = load_leaderboard(guild.id)
            if leaderboard:
                puzzle_key = _get_latest_numeric_puzzle_key(leaderboard)
                if puzzle_key is None:
                    await send_with_rate_limit_handling(
                        channel,
                        "No valid numeric puzzle results available yet.",
                    )
                    await asyncio.sleep(1)
                    continue
                scores = leaderboard[puzzle_key]
                if scores:
                    sorted_scores = sorted(
                        scores.items(),
                        key=lambda item: _entry_score(item[1]),
                    )
                    lines = [
                        f"🏆 Final Leaderboard for Puzzle #{puzzle_key} 🏆"
                    ]
                    for rank, (uid, entry) in _iter_ranked_entries(
                        sorted_scores,
                        lambda item: _entry_score(item[1]),
                    ):
                        player_label = f"<@{uid}>"
                        lines.append(
                            _format_puzzle_result(rank, entry, player_label)
                        )
                    await send_with_rate_limit_handling(
                        channel, "\n".join(lines)
                    )
                else:
                    await send_with_rate_limit_handling(
                        channel, "No results for today's puzzle yet."
                    )

                if is_sunday:
                    weekly_msg = generate_weekly_leaderboard_message(guild.id)
                    if weekly_msg:
                        await send_with_rate_limit_handling(
                            channel, weekly_msg
                        )
                    else:
                        await send_with_rate_limit_handling(
                            channel,
                            "No puzzles available for weekly leaderboard.",
                        )
            else:
                await send_with_rate_limit_handling(
                    channel, "No puzzles have been recorded yet."
                )

        # Add delay between guilds to reduce rate-limit risk.
        await asyncio.sleep(1)


@tasks.loop(minutes=1)
async def post_daily_leaderboard():
    """Scheduled task that posts daily and weekly leaderboard updates."""
    try:
        await _run_daily_leaderboard_cycle()
    except Exception as e:
        print(f"Error in post_daily_leaderboard: {e}")
        import traceback

        traceback.print_exc()


# --- Command: Clear Leaderboard (Admin) ---
@bot.command(name="clear_leaderboard")
@commands.has_permissions(administrator=True)
async def clear_leaderboard(ctx):
    """Clear all leaderboard data for the current guild."""
    guild_id = await _get_guild_id_or_notify(ctx)
    if guild_id is None:
        return

    with leaderboard_lock:
        save_leaderboard(guild_id, {})
    await send_with_rate_limit_handling(
        ctx.channel, "Leaderboard data cleared."
    )


@bot.command(name="show_leaderboard_file")
async def show_leaderboard_file(ctx):
    """Show the current guild's leaderboard filename."""
    guild_id = await _get_guild_id_or_notify(ctx)
    if guild_id is None:
        return

    file_name = get_leaderboard_file(guild_id)
    await send_with_rate_limit_handling(
        ctx.channel, f"Leaderboard file for this server: {file_name}"
    )


def stop_bot():
    """Stop the bot event loop if it is currently running."""
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
    if DISCORD_TOKEN is None:
        print("Error: DISCORD_TOKEN environment variable not set.")
    else:
        keep_alive()
        bot.run(DISCORD_TOKEN)
