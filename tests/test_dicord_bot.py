import asyncio
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def bot_module(monkeypatch):
    """Import bot.py without starting the keep_alive Flask thread."""
    project_root = str(Path(__file__).resolve().parents[1])
    monkeypatch.syspath_prepend(project_root)

    fake_keep_alive = types.ModuleType("keep_alive")
    fake_keep_alive.keep_alive = Mock()
    monkeypatch.setitem(sys.modules, "keep_alive", fake_keep_alive)

    if "bot" in sys.modules:
        del sys.modules["bot"]

    module = importlib.import_module("bot")
    module._test_keep_alive_mock = fake_keep_alive.keep_alive
    yield module

    sys.modules.pop("bot", None)


def test_import_does_not_start_keep_alive_server(bot_module):
    bot_module._test_keep_alive_mock.assert_not_called()


def test_get_leaderboard_file_uses_guild_id(bot_module):
    assert bot_module.get_leaderboard_file(12345) == "leaderboard_12345.json"


def test_load_leaderboard_returns_empty_dict_when_file_missing(
    bot_module, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    assert bot_module.load_leaderboard(1) == {}


def test_load_leaderboard_returns_empty_dict_for_malformed_json(
    bot_module, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    bad_file = tmp_path / "leaderboard_1.json"
    bad_file.write_text("{not-valid-json")
    assert bot_module.load_leaderboard(1) == {}
    assert not bad_file.exists()
    quarantined = list(tmp_path.glob("leaderboard_1.json.corrupt.*"))
    assert len(quarantined) == 1


def test_load_leaderboard_returns_empty_dict_for_non_dict_json(
    bot_module, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    wrong_shape_file = tmp_path / "leaderboard_1.json"
    wrong_shape_file.write_text("[]")
    assert bot_module.load_leaderboard(1) == {}
    assert not wrong_shape_file.exists()
    quarantined = list(tmp_path.glob("leaderboard_1.json.corrupt.*"))
    assert len(quarantined) == 1


def test_save_leaderboard_uses_atomic_replace(bot_module, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    replace_calls = []
    real_replace = bot_module.os.replace

    def tracked_replace(src, dst):
        replace_calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(bot_module.os, "replace", tracked_replace)

    bot_module.save_leaderboard(44, {"101": {"1": {"name": "Alice"}}})

    assert replace_calls
    assert replace_calls[0][1].endswith("leaderboard_44.json")
    assert (tmp_path / "leaderboard_44.json").exists()


def test_save_then_load_leaderboard_round_trip(
    bot_module, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    data = {
        "321": {
            "42": {
                "name": "Alice",
                "guesses": 4,
                "status": "complete",
                "connections_solved": 4,
                "actual_guesses": 4,
            }
        }
    }

    bot_module.save_leaderboard(999, data)
    loaded = bot_module.load_leaderboard(999)
    assert loaded == data


def test_generate_weekly_leaderboard_message_returns_none_with_no_data(
    bot_module, monkeypatch
):
    monkeypatch.setattr(bot_module, "load_leaderboard", lambda guild_id: {})
    assert bot_module.generate_weekly_leaderboard_message(1) is None


def test_generate_weekly_leaderboard_uses_last_7_puzzles_and_applies_missed_penalty(
    bot_module, monkeypatch
):
    leaderboard = {
        "1": {"a": {"name": "Alice", "guesses": 4, "status": "complete"}},
        "2": {
            "a": {"name": "Alice", "guesses": 4, "status": "complete"},
            "b": {"name": "Bob", "guesses": 3, "status": "complete"},
        },
        "3": {
            "a": {"name": "Alice", "guesses": 4, "status": "complete"},
            "b": {"name": "Bob", "guesses": 3, "status": "complete"},
        },
        "4": {
            "a": {"name": "Alice", "guesses": 4, "status": "complete"},
            "b": {"name": "Bob", "guesses": 3, "status": "complete"},
        },
        "5": {
            "a": {"name": "Alice", "guesses": 4, "status": "complete"},
            "b": {"name": "Bob", "guesses": 3, "status": "complete"},
        },
        "6": {
            "a": {"name": "Alice", "guesses": 4, "status": "complete"},
            "b": {"name": "Bob", "guesses": 3, "status": "complete"},
        },
        "7": {
            "a": {"name": "Alice", "guesses": 4, "status": "complete"},
            "b": {"name": "Bob", "guesses": 3, "status": "complete"},
        },
        "8": {
            "a": {"name": "Alice", "guesses": 4, "status": "complete"},
            # Old format entry (no status): should count as complete.
            "b": {"name": "Bob", "guesses": 3},
        },
    }
    monkeypatch.setattr(
        bot_module, "load_leaderboard", lambda guild_id: leaderboard
    )

    msg = bot_module.generate_weekly_leaderboard_message(1)

    assert msg is not None
    assert "Last 7 puzzles: #2-#8" in msg
    # Alice: 7 * 4 = 28. Bob: 7 * 3 = 21. No missed puzzle penalty in the last 7.
    assert "Alice: 28 total" in msg
    assert "Bob: 21 total" in msg


def test_generate_weekly_leaderboard_counts_missed_puzzle_penalty(
    bot_module, monkeypatch
):
    leaderboard = {
        "10": {
            "a": {"name": "Alice", "guesses": 4, "status": "complete"},
            "b": {"name": "Bob", "guesses": 3, "status": "complete"},
        },
        "11": {
            "a": {"name": "Alice", "guesses": 4, "status": "complete"},
            "b": {"name": "Bob", "guesses": 3, "status": "complete"},
        },
        "12": {
            "a": {"name": "Alice", "guesses": 4, "status": "complete"},
            # Bob skipped this puzzle
        },
    }
    monkeypatch.setattr(
        bot_module, "load_leaderboard", lambda guild_id: leaderboard
    )

    msg = bot_module.generate_weekly_leaderboard_message(1)

    assert msg is not None
    # Bob: 3 + 3 + penalty 6 for one missed puzzle = 12
    assert "Bob: 12 total" in msg


def test_leaderboard_cmd_today_without_data_sends_no_data_message(
    bot_module, monkeypatch
):
    monkeypatch.setattr(bot_module, "load_leaderboard", lambda guild_id: {})
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)

    ctx = SimpleNamespace(guild=SimpleNamespace(id=1), channel=Mock())
    asyncio.run(bot_module.leaderboard_cmd.callback(ctx, "today"))

    send_mock.assert_awaited_once()
    assert "No puzzles have been recorded yet." in send_mock.await_args.args[1]


def test_leaderboard_cmd_formats_sorted_results_with_incomplete_entries(
    bot_module, monkeypatch
):
    leaderboard = {
        "200": {
            "1": {"name": "Alice", "guesses": 4, "status": "complete"},
            "2": {
                "name": "Bob",
                "guesses": 10,
                "status": "incomplete",
                "connections_solved": 3,
            },
            "3": {"name": "Carol", "guesses": 5, "status": "complete"},
        }
    }
    monkeypatch.setattr(
        bot_module, "load_leaderboard", lambda guild_id: leaderboard
    )
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)

    ctx = SimpleNamespace(guild=SimpleNamespace(id=1), channel=Mock())
    asyncio.run(bot_module.leaderboard_cmd.callback(ctx, "200"))

    sent = send_mock.await_args.args[1]
    assert "Leaderboard for Puzzle #200" in sent
    assert "🥇 Alice: 4 guesses" in sent
    assert "🥈 Carol: 5 guesses" in sent
    assert "💀 Bob: ❌ INCOMPLETE (3/4)" in sent


def test_leaderboard_cmd_escapes_mention_like_names(bot_module, monkeypatch):
    leaderboard = {
        "200": {
            "1": {
                "name": "@everyone",
                "guesses": 4,
                "status": "complete",
            }
        }
    }
    monkeypatch.setattr(
        bot_module, "load_leaderboard", lambda guild_id: leaderboard
    )
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)

    ctx = SimpleNamespace(guild=SimpleNamespace(id=1), channel=Mock())
    asyncio.run(bot_module.leaderboard_cmd.callback(ctx, "200"))

    sent = send_mock.await_args.args[1]
    assert "@\u200beveryone" in sent


def test_leaderboard_cmd_today_handles_non_numeric_keys(
    bot_module, monkeypatch
):
    leaderboard = {
        "bad-key": {"1": {"name": "Alice", "guesses": 4, "status": "complete"}}
    }
    monkeypatch.setattr(
        bot_module, "load_leaderboard", lambda guild_id: leaderboard
    )
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)

    ctx = SimpleNamespace(guild=SimpleNamespace(id=1), channel=Mock())
    asyncio.run(bot_module.leaderboard_cmd.callback(ctx, "today"))

    assert "No valid numeric puzzles have been recorded yet." in (
        send_mock.await_args.args[1]
    )


@pytest.mark.parametrize(
    ("command_name", "args"),
    [
        ("leaderboard_cmd", ("today",)),
        ("weekly_leaderboard_cmd", ()),
        ("clear_leaderboard", ()),
        ("show_leaderboard_file", ()),
    ],
)
def test_guild_only_commands_return_dm_safe_message(
    bot_module, monkeypatch, command_name, args
):
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)

    ctx = SimpleNamespace(guild=None, channel=Mock())
    command = getattr(bot_module, command_name)
    asyncio.run(command.callback(ctx, *args))

    send_mock.assert_awaited_once()
    assert bot_module.GUILD_ONLY_MESSAGE in send_mock.await_args.args[1]


def test_send_with_rate_limit_handling_blocks_everyone_and_role_mentions(
    bot_module,
):
    channel = SimpleNamespace(send=AsyncMock(return_value=None))

    result = asyncio.run(
        bot_module.send_with_rate_limit_handling(channel, "hello")
    )

    assert result is True
    kwargs = channel.send.await_args.kwargs
    allowed_mentions = kwargs["allowed_mentions"]
    assert allowed_mentions.everyone is False
    assert allowed_mentions.roles is False


def test_on_ready_starts_daily_loop_when_not_running(bot_module, monkeypatch):
    loop_mock = Mock()
    loop_mock.is_running.return_value = False
    monkeypatch.setattr(bot_module, "post_daily_leaderboard", loop_mock)

    asyncio.run(bot_module.on_ready())

    loop_mock.start.assert_called_once()


def test_on_ready_does_not_restart_daily_loop_when_running(
    bot_module, monkeypatch
):
    loop_mock = Mock()
    loop_mock.is_running.return_value = True
    monkeypatch.setattr(bot_module, "post_daily_leaderboard", loop_mock)

    asyncio.run(bot_module.on_ready())

    loop_mock.start.assert_not_called()


def test_run_daily_leaderboard_cycle_posts_daily_and_weekly(
    bot_module, monkeypatch
):
    channel = SimpleNamespace(name="connections")
    guild = SimpleNamespace(id=1, text_channels=[channel])

    monkeypatch.setattr(
        bot_module.discord.utils,
        "get",
        lambda channels, name: channel if name == "connections" else None,
    )
    monkeypatch.setattr(
        bot_module,
        "load_leaderboard",
        lambda guild_id: {
            "101": {
                "1": {"name": "Alice", "guesses": 4, "status": "complete"},
                "2": {
                    "name": "Bob",
                    "guesses": 10,
                    "status": "incomplete",
                    "connections_solved": 3,
                },
            }
        },
    )
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)
    sleep_mock = AsyncMock()
    monkeypatch.setattr(bot_module.asyncio, "sleep", sleep_mock)
    bot_module.last_posted_minute = None

    fake_now = SimpleNamespace(
        year=2026,
        month=3,
        day=22,
        hour=21,
        minute=0,
        weekday=lambda: 6,
    )

    asyncio.run(
        bot_module._run_daily_leaderboard_cycle(
            now=fake_now,
            guilds=[guild],
        )
    )

    assert send_mock.await_count == 2
    daily_message = send_mock.await_args_list[0].args[1]
    weekly_message = send_mock.await_args_list[1].args[1]
    assert "Final Leaderboard for Puzzle #101" in daily_message
    assert "<@1>: 4 guesses" in daily_message
    assert "💀 <@2>: ❌ INCOMPLETE (3/4)" in daily_message
    assert "Weekly Leaderboard" in weekly_message
    sleep_mock.assert_awaited_once_with(1)


def test_generate_weekly_leaderboard_ignores_non_numeric_keys(
    bot_module, monkeypatch
):
    leaderboard = {
        "10": {"a": {"name": "Alice", "guesses": 4, "status": "complete"}},
        "bad": {"b": {"name": "Bob", "guesses": 3, "status": "complete"}},
        "11": {"a": {"name": "Alice", "guesses": 5, "status": "complete"}},
    }
    monkeypatch.setattr(
        bot_module, "load_leaderboard", lambda guild_id: leaderboard
    )

    msg = bot_module.generate_weekly_leaderboard_message(1)

    assert msg is not None
    assert "#10-#11" in msg


def test_generate_weekly_leaderboard_escapes_mention_like_names(
    bot_module, monkeypatch
):
    leaderboard = {
        "10": {
            "a": {
                "name": "@everyone",
                "guesses": 4,
                "status": "complete",
            }
        }
    }
    monkeypatch.setattr(
        bot_module, "load_leaderboard", lambda guild_id: leaderboard
    )

    msg = bot_module.generate_weekly_leaderboard_message(1)

    assert msg is not None
    assert "@\u200beveryone" in msg


def test_run_daily_leaderboard_cycle_handles_non_numeric_keys(
    bot_module, monkeypatch
):
    channel = SimpleNamespace(name="connections")
    guild = SimpleNamespace(id=1, text_channels=[channel])

    monkeypatch.setattr(
        bot_module.discord.utils,
        "get",
        lambda channels, name: channel if name == "connections" else None,
    )
    monkeypatch.setattr(
        bot_module,
        "load_leaderboard",
        lambda guild_id: {
            "bad-key": {
                "1": {"name": "Alice", "guesses": 4, "status": "complete"}
            }
        },
    )
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)
    sleep_mock = AsyncMock()
    monkeypatch.setattr(bot_module.asyncio, "sleep", sleep_mock)
    bot_module.last_posted_minute = None

    fake_now = SimpleNamespace(
        year=2026,
        month=3,
        day=23,
        hour=21,
        minute=0,
        weekday=lambda: 1,
    )

    asyncio.run(
        bot_module._run_daily_leaderboard_cycle(
            now=fake_now,
            guilds=[guild],
        )
    )

    send_mock.assert_awaited_once()
    assert "No valid numeric puzzle results available yet." in (
        send_mock.await_args.args[1]
    )
    sleep_mock.assert_awaited_once_with(1)


def test_run_daily_leaderboard_cycle_skips_duplicate_minute(
    bot_module, monkeypatch
):
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)
    sleep_mock = AsyncMock()
    monkeypatch.setattr(bot_module.asyncio, "sleep", sleep_mock)

    fake_now = SimpleNamespace(
        year=2026,
        month=3,
        day=22,
        hour=21,
        minute=0,
        weekday=lambda: 6,
    )
    bot_module.last_posted_minute = "2026-3-22-21-0"

    asyncio.run(bot_module._run_daily_leaderboard_cycle(now=fake_now))

    send_mock.assert_not_awaited()
    sleep_mock.assert_not_awaited()


def test_on_message_records_first_complete_submission(bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "load_leaderboard", lambda guild_id: {})
    save_mock = Mock()
    monkeypatch.setattr(bot_module, "save_leaderboard", save_mock)
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)
    process_commands_mock = AsyncMock()
    bot_module.bot.process_commands = process_commands_mock

    message = SimpleNamespace(
        author=SimpleNamespace(id=42, display_name="Alice"),
        channel=SimpleNamespace(name="connections"),
        guild=SimpleNamespace(id=1),
        content=("Puzzle #777\n🟩🟩🟩🟩\n🟦🟦🟦🟦\n🟧🟧🟧🟧\n🟨🟨🟨🟨"),
    )

    asyncio.run(bot_module.on_message(message))

    save_mock.assert_called_once()
    _, saved_data = save_mock.call_args.args
    assert saved_data["777"]["42"]["status"] == "complete"
    assert saved_data["777"]["42"]["guesses"] == 4
    assert (
        "Recorded Alice's result for Puzzle #777"
        in send_mock.await_args.args[1]
    )
    process_commands_mock.assert_awaited_once_with(message)


def test_on_message_escapes_mention_like_display_name(bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "load_leaderboard", lambda guild_id: {})
    save_mock = Mock()
    monkeypatch.setattr(bot_module, "save_leaderboard", save_mock)
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)
    process_commands_mock = AsyncMock()
    bot_module.bot.process_commands = process_commands_mock

    message = SimpleNamespace(
        author=SimpleNamespace(id=42, display_name="@everyone"),
        channel=SimpleNamespace(name="connections"),
        guild=SimpleNamespace(id=1),
        content=("Puzzle #777\n🟩🟩🟩🟩\n🟦🟦🟦🟦\n🟧🟧🟧🟧\n🟨🟨🟨🟨"),
    )

    asyncio.run(bot_module.on_message(message))

    _, saved_data = save_mock.call_args.args
    assert saved_data["777"]["42"]["name"] == "@\u200beveryone"
    assert "@\u200beveryone" in send_mock.await_args.args[1]
    process_commands_mock.assert_awaited_once_with(message)


def test_on_message_rejects_duplicate_submission(bot_module, monkeypatch):
    existing = {
        "777": {
            "42": {
                "name": "Alice",
                "guesses": 4,
                "status": "complete",
                "connections_solved": 4,
                "actual_guesses": 4,
            }
        }
    }
    monkeypatch.setattr(
        bot_module, "load_leaderboard", lambda guild_id: existing
    )
    save_mock = Mock()
    monkeypatch.setattr(bot_module, "save_leaderboard", save_mock)
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)
    process_commands_mock = AsyncMock()
    bot_module.bot.process_commands = process_commands_mock

    message = SimpleNamespace(
        author=SimpleNamespace(id=42, display_name="Alice"),
        channel=SimpleNamespace(name="connections"),
        guild=SimpleNamespace(id=1),
        content="Puzzle #777\n🟩🟩🟩🟩",
    )

    asyncio.run(bot_module.on_message(message))

    save_mock.assert_not_called()
    assert "you've already submitted a result" in send_mock.await_args.args[1]
    process_commands_mock.assert_awaited_once_with(message)


def test_on_message_ignores_non_connections_channel(bot_module):
    process_commands_mock = AsyncMock()
    bot_module.bot.process_commands = process_commands_mock

    message = SimpleNamespace(
        author=SimpleNamespace(id=42, display_name="Alice"),
        channel=SimpleNamespace(name="general"),
        guild=SimpleNamespace(id=1),
        content="Puzzle #777\n🟩🟩🟩🟩",
    )

    asyncio.run(bot_module.on_message(message))

    process_commands_mock.assert_awaited_once_with(message)


def test_on_message_uses_leaderboard_lock_for_write(bot_module, monkeypatch):
    class TrackingLock:
        def __init__(self):
            self.enter_count = 0

        def __enter__(self):
            self.enter_count += 1
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    lock = TrackingLock()
    monkeypatch.setattr(bot_module, "leaderboard_lock", lock)
    monkeypatch.setattr(bot_module, "load_leaderboard", lambda guild_id: {})
    monkeypatch.setattr(bot_module, "save_leaderboard", Mock())
    monkeypatch.setattr(
        bot_module,
        "send_with_rate_limit_handling",
        AsyncMock(return_value=True),
    )
    process_commands_mock = AsyncMock()
    bot_module.bot.process_commands = process_commands_mock

    message = SimpleNamespace(
        author=SimpleNamespace(id=42, display_name="Alice"),
        channel=SimpleNamespace(name="connections"),
        guild=SimpleNamespace(id=1),
        content=("Puzzle #777\n🟩🟩🟩🟩\n🟦🟦🟦🟦\n🟧🟧🟧🟧\n🟨🟨🟨🟨"),
    )

    asyncio.run(bot_module.on_message(message))

    assert lock.enter_count == 1
    process_commands_mock.assert_awaited_once_with(message)


def test_clear_leaderboard_uses_leaderboard_lock(bot_module, monkeypatch):
    class TrackingLock:
        def __init__(self):
            self.enter_count = 0

        def __enter__(self):
            self.enter_count += 1
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    lock = TrackingLock()
    monkeypatch.setattr(bot_module, "leaderboard_lock", lock)
    monkeypatch.setattr(bot_module, "save_leaderboard", Mock())
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)

    ctx = SimpleNamespace(guild=SimpleNamespace(id=1), channel=Mock())
    asyncio.run(bot_module.clear_leaderboard.callback(ctx))

    assert lock.enter_count == 1
    send_mock.assert_awaited_once()
