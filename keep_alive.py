"""Minimal Flask health endpoint used to keep the bot process alive."""

from threading import Thread

from flask import Flask

app = Flask("")


@app.route("/")
def home():
    """Return a simple health response for uptime checks."""
    return "Bot is running!"


def run():
    """Run the Flask keep-alive app on the expected host/port."""
    app.run(host="0.0.0.0", port=8081)


def keep_alive():
    """Start the keep-alive web server in a background thread."""
    t = Thread(target=run, daemon=True)
    t.start()
