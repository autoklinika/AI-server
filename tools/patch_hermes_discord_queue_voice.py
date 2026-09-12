#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path


MARKER = "AI_SERVER_DISCORD_QUEUE_VOICE_V2"
LEGACY_MARKER = "AI_SERVER_DISCORD_QUEUE_VOICE_V1"
TARGET = "gateway/run_turn_runner.py"

BASE = '''    def voice_ack_callback(self, call_id, tool_name, args):
        """tool_start_callback: speak a one-time ack in the voice channel."""
        ctx = self._ctx
        if ctx._voice_ack_fired[0] or ctx._voice_ack_guild[0] is None or not ctx._run_still_current():
            return
        ctx._voice_ack_fired[0] = True
        adapter = self._runner.adapters.get(Platform.DISCORD)
        if adapter is None or not hasattr(adapter, "play_ack_in_voice"):
            return
        try:
            self._schedule(
                adapter.play_ack_in_voice(ctx._voice_ack_guild[0]), "voice ack scheduling error", loop=ctx._voice_ack_loop,
            )
        except Exception as err:
            logger.debug("voice ack schedule failed: %s", err)
'''

LEGACY = '''    def voice_ack_callback(self, call_id, tool_name, args):
        """tool_start_callback: speak a one-time ack or an AI-server queue status in voice."""
        ctx = self._ctx

        # AI_SERVER_DISCORD_QUEUE_VOICE_V1: queue transitions are injected by
        # AI-server's resource-queue hook as synthetic tool-start events. They
        # use Hermes' normal Discord voice mixer/TTS path, but deliberately do
        # NOT consume the one-time first-tool acknowledgement for the turn.
        if tool_name == "__ai_server_queue_status__":
            if ctx._voice_ack_guild[0] is None or not ctx._run_still_current():
                return
            phrase = str((args or {}).get("phrase") or "").strip()
            if not phrase:
                return
            adapter = self._runner.adapters.get(Platform.DISCORD)
            if adapter is None or not hasattr(adapter, "play_ack_in_voice"):
                return
            try:
                self._schedule(
                    adapter.play_ack_in_voice(ctx._voice_ack_guild[0], phrase=phrase),
                    "queue voice status scheduling error",
                    loop=ctx._voice_ack_loop,
                )
            except Exception as err:
                logger.debug("queue voice status schedule failed: %s", err)
            return

        if ctx._voice_ack_fired[0] or ctx._voice_ack_guild[0] is None or not ctx._run_still_current():
            return
        ctx._voice_ack_fired[0] = True
        adapter = self._runner.adapters.get(Platform.DISCORD)
        if adapter is None or not hasattr(adapter, "play_ack_in_voice"):
            return
        try:
            self._schedule(
                adapter.play_ack_in_voice(ctx._voice_ack_guild[0]), "voice ack scheduling error", loop=ctx._voice_ack_loop,
            )
        except Exception as err:
            logger.debug("voice ack schedule failed: %s", err)
'''

NEW = '''    def voice_ack_callback(self, call_id, tool_name, args):
        """tool_start_callback: speak a one-time ack or an AI-server queue status in voice."""
        ctx = self._ctx

        # AI_SERVER_DISCORD_QUEUE_VOICE_V2: queue transitions are injected by
        # AI-server's resource-queue hook as synthetic tool-start events. Queue
        # speech MUST NOT depend on discord.voice_fx.ack_enabled: that flag only
        # controls Hermes' normal first-tool acknowledgement. We synthesize with
        # Hermes' regular TTS tool and feed the existing active voice mixer.
        if tool_name == "__ai_server_queue_status__":
            if ctx._voice_ack_guild[0] is None or not ctx._run_still_current():
                return
            phrase = str((args or {}).get("phrase") or "").strip()
            if not phrase:
                return
            adapter = self._runner.adapters.get(Platform.DISCORD)
            if adapter is None or not hasattr(adapter, "play_in_voice_channel"):
                return

            async def _play_queue_status():
                import os as _rq_os
                import tempfile as _rq_tempfile
                import uuid as _rq_uuid

                _rq_audio = _rq_os.path.join(
                    _rq_tempfile.gettempdir(),
                    "hermes_voice",
                    f"queue_{_rq_uuid.uuid4().hex[:12]}.mp3",
                )
                _rq_actual = _rq_audio
                _rq_os.makedirs(_rq_os.path.dirname(_rq_audio), exist_ok=True)
                try:
                    from tools.tts_tool import text_to_speech_tool as _rq_tts

                    _rq_raw = await asyncio.to_thread(
                        _rq_tts,
                        text=phrase,
                        output_path=_rq_audio,
                    )
                    try:
                        _rq_doc = json.loads(_rq_raw) if isinstance(_rq_raw, str) else {}
                    except Exception:
                        _rq_doc = {}
                    _rq_actual = str(_rq_doc.get("file_path") or _rq_audio)
                    if not _rq_os.path.isfile(_rq_actual):
                        logger.debug("queue voice status TTS produced no audio file")
                        return
                    await adapter.play_in_voice_channel(
                        ctx._voice_ack_guild[0],
                        _rq_actual,
                    )
                except Exception as err:
                    logger.debug("queue voice status playback failed: %s", err)
                finally:
                    for _rq_path in {_rq_audio, _rq_actual}:
                        try:
                            if _rq_path and _rq_os.path.isfile(_rq_path):
                                _rq_os.unlink(_rq_path)
                        except OSError:
                            pass

            try:
                self._schedule(
                    _play_queue_status(),
                    "queue voice status scheduling error",
                    loop=ctx._voice_ack_loop,
                )
            except Exception as err:
                logger.debug("queue voice status schedule failed: %s", err)
            return

        if ctx._voice_ack_fired[0] or ctx._voice_ack_guild[0] is None or not ctx._run_still_current():
            return
        ctx._voice_ack_fired[0] = True
        adapter = self._runner.adapters.get(Platform.DISCORD)
        if adapter is None or not hasattr(adapter, "play_ack_in_voice"):
            return
        try:
            self._schedule(
                adapter.play_ack_in_voice(ctx._voice_ack_guild[0]), "voice ack scheduling error", loop=ctx._voice_ack_loop,
            )
        except Exception as err:
            logger.debug("voice ack schedule failed: %s", err)
'''


class PatchError(RuntimeError):
    pass


def patch_text(text: str) -> str:
    if text.count(MARKER) > 1:
        raise PatchError("duplicate Discord queue voice v2 marker")
    if MARKER in text and LEGACY_MARKER in text:
        raise PatchError("mixed Discord queue voice v1/v2 markers")
    if MARKER in text:
        compile(text, TARGET, "exec")
        return text

    if LEGACY_MARKER in text:
        count = text.count(LEGACY)
        if count != 1:
            raise PatchError(f"expected one legacy voice callback, found {count}")
        patched = text.replace(LEGACY, NEW, 1)
    else:
        count = text.count(BASE)
        if count != 1:
            raise PatchError(f"expected one voice_ack_callback anchor, found {count}")
        patched = text.replace(BASE, NEW, 1)

    if patched.count(MARKER) != 1 or LEGACY_MARKER in patched:
        raise PatchError("Discord queue voice v2 insertion failed")
    compile(patched, TARGET, "exec")
    return patched


def check_text(text: str) -> str:
    had_legacy = LEGACY_MARKER in text and MARKER not in text
    try:
        patched = patch_text(text)
    except (PatchError, SyntaxError) as exc:
        return f"unsupported:{exc}"
    if patched == text:
        return "patched"
    return "upgradeable-v1" if had_legacy else "patchable"


def atomic_write(path: Path, text: str) -> None:
    stat = path.stat()
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".queue-voice.",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, stat.st_mode)
        try:
            os.chown(tmp_name, stat.st_uid, stat.st_gid)
        except PermissionError:
            pass
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        text = args.path.read_text(encoding="utf-8")
        if args.check:
            state = check_text(text)
            print(state)
            return 0 if state in {"patched", "patchable", "upgradeable-v1"} else 2
        patched = patch_text(text)
        if patched == text:
            print("already patched")
            return 0
        atomic_write(args.path, patched)
        print("patched Discord queue voice v2")
        return 0
    except (OSError, PatchError, SyntaxError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
