import asyncio
import importlib
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def bot_module(monkeypatch):
    """Import bot.py without starting the keep_alive Flask thread."""
    project_root = str(Path(__file__).resolve().parents[1])
    monkeypatch.syspath_prepend(project_root)

    fake_keep_alive = types.ModuleType("keep_alive")
    fake_keep_alive.keep_alive = lambda: None
    monkeypatch.setitem(sys.modules, "keep_alive", fake_keep_alive)

    if "bot" in sys.modules:
        del sys.modules["bot"]

    module = importlib.import_module("bot")
    yield module

    sys.modules.pop("bot", None)


def test_get_leaderboard_file_uses_guild_id(bot_module):
    assert bot_module.get_leaderboard_file(12345) == "leaderboard_12345.json"


def test_load_leaderboard_returns_empty_dict_when_file_missing(
    bot_module, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    assert bot_module.load_leaderboard(1) == {}


def test_save_then_load_leaderboard_round_trip(bot_module, monkeypatch, tmp_path):
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
    monkeypatch.setattr(bot_module, "load_leaderboard", lambda guild_id: leaderboard)

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
    monkeypatch.setattr(bot_module, "load_leaderboard", lambda guild_id: leaderboard)

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
    monkeypatch.setattr(bot_module, "load_leaderboard", lambda guild_id: leaderboard)
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "send_with_rate_limit_handling", send_mock)

    ctx = SimpleNamespace(guild=SimpleNamespace(id=1), channel=Mock())
    asyncio.run(bot_module.leaderboard_cmd.callback(ctx, "200"))

    sent = send_mock.await_args.args[1]
    assert "Leaderboard for Puzzle #200" in sent
    assert "🥇 Alice: 4 guesses" in sent
    assert "🥈 Carol: 5 guesses" in sent
    assert "💀 Bob: ❌ INCOMPLETE (3/4)" in sent


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
    assert "Recorded Alice's result for Puzzle #777" in send_mock.await_args.args[1]
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
    monkeypatch.setattr(bot_module, "load_leaderboard", lambda guild_id: existing)
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

    process_commands_mock.assert_not_awaited()
