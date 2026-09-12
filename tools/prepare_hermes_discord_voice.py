#!/usr/bin/env python3
"""Prepare a separate private config candidate. Does not deploy or restart services."""
import argparse
import copy
import json
import os
from pathlib import Path

MODEL = "qwen3.6:35b-hermes64k-gpu"
PROVIDER = "Hermes Discord Qwen GPU"
PROMPT = (
    "Odpowiadaj po polsku, krótko i naturalnie, zwykle jednym lub dwoma zdaniami. "
    "Pomagaj dokumentować naprawy ECU. Rozdzielaj objawy, pomiary, hipotezy, "
    "czynności i wyniki. Nie wymyślaj wartości. Potwierdzaj zapis dopiero po "
    "udanym użyciu narzędzia i odczycie pliku. Nie steruj ECU, CAN, programatorami "
    "ani testerami. Nie konfiguruj, nie montuj ani nie zapisuj niczego na NAS-ie. "
    "Zapisuj lokalnie tylko we wskazanym przez użytkownika miejscu."
)


def prepare(config, text_channel, voice_channel, base_url):
    if not isinstance(config, dict):
        raise ValueError("Config root must be a mapping")
    for channel in (text_channel, voice_channel):
        if not isinstance(channel, str) or not channel.isascii() or not channel.isdecimal():
            raise ValueError("Channel IDs must be decimal strings")
    if text_channel == voice_channel:
        raise ValueError("Text and voice channels must differ")
    if not base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("Expected an existing local AI Gateway URL")
    cfg = copy.deepcopy(config)
    stt = cfg.setdefault("stt", {})
    stt.update(enabled=True, provider="local", language="pl")
    stt.setdefault("local", {}).update(model="small", device="cpu", compute_type="int8")
    tts = cfg.setdefault("tts", {})
    tts["provider"] = "edge"
    tts.setdefault("edge", {})["voice"] = "pl-PL-MarekNeural"
    discord = cfg.setdefault("discord", {})
    discord.update(voice_channel_inactivity_timeout_seconds=0, auto_thread=False)
    channels = discord.setdefault("free_response_channels", [])
    if text_channel not in channels:
        channels.append(text_channel)
    discord.setdefault("channel_prompts", {})[text_channel] = PROMPT
    overrides = discord.setdefault("channel_overrides", {})
    for channel in (text_channel, voice_channel):
        overrides.setdefault(channel, {}).update(model=MODEL, provider="custom")
    cfg.setdefault("platform_toolsets", {})["discord"] = ["terminal", "file", "web"]
    providers = cfg.setdefault("custom_providers", [])
    matches = [p for p in providers if p.get("name") == PROVIDER]
    if len(matches) > 1:
        raise ValueError("Duplicate Discord provider entries")
    provider = matches[0] if matches else {"name": PROVIDER}
    if not matches:
        providers.append(provider)
    provider.update(base_url=base_url, model=MODEL, api_mode="chat_completions")
    provider.setdefault("models", {})[MODEL] = {"context_length": 65536}
    provider.setdefault("extra_body", {}).update(
        reasoning_effort="none", temperature=0, presence_penalty=0
    )
    # This deployed setting is global, including Telegram. See the runbook.
    cfg.setdefault("auxiliary", {}).setdefault("title_generation", {})["enabled"] = False
    return cfg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--text-channel", required=True)
    parser.add_argument("--voice-channel", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11435/clients/hermes/v1")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Output must differ from the live input config")
    import yaml  # Use the existing Hermes venv; not an AI Bridge dependency.
    original = yaml.safe_load(args.input.read_text(encoding="utf-8"))
    candidate = prepare(original, args.text_channel, args.voice_channel, args.base_url)
    # JSON is valid YAML; preserve Unicode and avoid emitting private content to stdout.
    content = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)
    print("Private candidate created; review locally before deployment.")


if __name__ == "__main__":
    main()
