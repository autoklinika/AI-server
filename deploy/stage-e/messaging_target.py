#!/usr/bin/env python3
"""Resolve an existing Discord smoke destination; never print errors or config.

Run with the Hermes interpreter and HERMES_HOME. Prefer its home channel; when
absent, accept only its single configured free-response channel that is also in
its channel directory. Never choose a user, DM, or arbitrary discovered channel.
"""
import json
import os
from pathlib import Path
import sys


def resolve_discord_target(home, free_response_channels, directory):
    if home:
        target = str(home)
    else:
        configured = {str(value) for value in free_response_channels}
        known = {str(row.get('id')) for row in directory if row.get('type') == 'channel'}
        if len(configured) != 1 or not configured.issubset(known):
            raise ValueError('no unambiguous configured Discord destination')
        target = configured.pop()
    if not target.isdigit():
        raise ValueError('invalid Discord destination')
    return 'discord:' + target


def main():
    import yaml
    from dotenv import load_dotenv
    home = Path(os.environ['HERMES_HOME'])
    load_dotenv(home / '.env', override=True)
    config = yaml.safe_load((home / 'config.yaml').read_text()) or {}
    directory = json.loads((home / 'channel_directory.json').read_text())
    # Match the installed gateway's home configuration, including config.json.
    from gateway.config import load_gateway_config, Platform
    channel = load_gateway_config().get_home_channel(Platform.DISCORD)
    print(resolve_discord_target(
        channel.chat_id if channel else None,
        (config.get('discord') or {}).get('free_response_channels') or [],
        (directory.get('platforms') or {}).get('discord') or [],
    ))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Values may contain private identifiers. The caller reports a safe label.
        sys.exit(1)
