#!/usr/bin/env python3
"""Linux helper: verify a bot token from stdin and atomically extend a private .env."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.request


def validate(token, bot_id, owner_id):
    if not re.fullmatch(r"[0-9]+", bot_id) or not re.fullmatch(r"[0-9]+", owner_id):
        raise ValueError("Invalid ID")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{20,}", token):
        raise ValueError("Invalid token format")
    first = token.split(".")[0]
    if base64.urlsafe_b64decode(first + "=" * (-len(first) % 4)).decode() != bot_id:
        raise ValueError("Unexpected application")


def extend(original, token, owner_id):
    for key in ("DISCORD_BOT_TOKEN", "DISCORD_ALLOWED_USERS"):
        if re.search(r"^\s*(?:export\s+)?" + key + r"\s*=", original, re.M):
            raise ValueError("Existing Discord settings; refusing overwrite")
    return (original.rstrip() + "\n\n# Discord voice\nDISCORD_BOT_TOKEN=" + token
            + "\nDISCORD_ALLOWED_USERS=" + owner_id + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--owner-id", required=True)
    args = parser.parse_args()
    if os.name != "posix":
        raise ValueError("Run inside the Linux server, with the service stopped")
    if args.env_file.is_symlink():
        raise ValueError("Symlink not accepted")
    token = sys.stdin.read().strip()
    validate(token, args.bot_id, args.owner_id)
    original = args.env_file.read_text(encoding="utf-8")
    updated = extend(original, token, args.owner_id)
    req = urllib.request.Request("https://discord.com/api/v10/users/@me", headers={
        "Authorization": "Bot " + token, "User-Agent": "HermesVoiceSetup/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        bot = json.load(response)
    if bot.get("id") != args.bot_id or not bot.get("bot"):
        raise ValueError("Bot identity check failed")
    fd, temporary = tempfile.mkstemp(prefix=".env.discord-", dir=args.env_file.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if args.env_file.read_text(encoding="utf-8") != original:
            raise ValueError("Environment changed during verification")
        os.replace(temporary, args.env_file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("Verified Discord credentials installed privately.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print HTTP request details, token, .env contents or exception message.
        print("Credential installation failed: " + type(error).__name__, file=sys.stderr)
        sys.exit(1)
