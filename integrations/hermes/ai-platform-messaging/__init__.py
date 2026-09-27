"""AI Platform messaging integration.

Telegram keeps the existing Hermes agent/media behavior.

Discord is intentionally technical-only:
- authorized text and voice turns are intercepted before the general Hermes agent,
- the query is answered only through AI Platform Technical Conversation /conversation/turn,
- responses include Knowledge citations,
- voice input keeps Hermes STT and receives TTS output,
- only /voice gateway control is allowed,
- Discord photo/video/media and general Hermes commands never reach the agent.

No source patching or process-global session mutation.
"""
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


LOGGER = logging.getLogger(__name__)
_origin = ContextVar("ai_platform_origin", default=None)
_helper_lock = threading.Lock()
_discord_tasks = set()

_DISCORD_DOMAIN = os.getenv("AI_PLATFORM_DISCORD_KNOWLEDGE_DOMAIN", "ecu-repair").strip() or "ecu-repair"
_PLATFORM_TURN_URL = (
    os.getenv(
        "AI_PLATFORM_DISCORD_CONVERSATION_URL",
        "http://127.0.0.1:11435/api/v1/conversation/turn",
    ).strip()
    or "http://127.0.0.1:11435/api/v1/conversation/turn"
)
_SOURCE_BASE_URL = os.getenv("AI_PLATFORM_DISCORD_SOURCE_BASE_URL", "").strip().rstrip("/")
_MAX_QUERY_CHARS = 8192
_MAX_CITATIONS = 8
_POLICY_HELP = (
    "Discord jest teraz technicznym kanałem AI Platform. "
    "Obsługuje pytania tekstowe i voice dotyczące diagnostyki oraz napraw, "
    "oparte wyłącznie na naszej bazie Knowledge/ERS. "
    "Ogólny chat, foto i wideo są tutaj wyłączone. "
    "Do sterowania głosem użyj /voice."
)
_MEDIA_DISABLED = (
    "Na Discordzie obsługuję teraz tylko techniczne pytania tekstowe i voice. "
    "Foto, wideo i pozostałe załączniki są wyłączone. "
    "Materiały źródłowe dodawaj przez ERS/Knowledge, a potem pytaj o nie tutaj."
)


@dataclass(frozen=True)
class Origin:
    event: object
    gateway: object
    loop: object
    request_id: str
    task: object


def _platform_value(source):
    platform = getattr(source, "platform", None)
    return getattr(platform, "value", platform) or ""


def _message_type_value(event):
    value = getattr(event, "message_type", None)
    return str(getattr(value, "value", value) or "").lower()


def _safe_command(event):
    try:
        return event.get_command()
    except Exception:
        return None


def _authorized(gateway, source):
    checker = getattr(gateway, "_is_user_authorized_for_source", None)
    if not callable(checker):
        raise RuntimeError("Hermes authorization seam unavailable")
    return checker(source) is True


def _remember_task(task):
    _discord_tasks.add(task)

    def done(future):
        _discord_tasks.discard(future)
        try:
            future.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            LOGGER.exception("Discord technical task failed")

    task.add_done_callback(done)


def observe(event, gateway, **_):
    """Capture normal messaging context and hard-route authorized Discord turns.

    Hermes treats hook exceptions as allow/fall-through, so Discord policy code
    must never leak an exception: any unexpected policy failure is a hard skip.
    """
    source = getattr(event, "source", None)
    platform = _platform_value(source) if source is not None else ""
    try:
        loop = asyncio.get_running_loop()
        origin = Origin(event, gateway, loop, uuid4().hex, asyncio.current_task())
        _origin.set(origin)

        if source is None or platform != "discord":
            # Telegram and all other platforms keep their current Hermes behavior.
            return None

        # /voice must keep the native Hermes gateway control path
        # (join/leave/on/off/status) and native authorization.
        if _safe_command(event) == "voice":
            return None

        # This hook runs before Hermes auth. Unauthorized Discord users must fall
        # through to the normal auth/pairing policy; authorized users are
        # intercepted below.
        if not _authorized(gateway, source):
            return None

        if not getattr(source, "chat_id", None):
            return {"action": "skip", "reason": "discord-technical-missing-chat"}

        _remember_task(
            loop.create_task(
                discord_technical_turn(event, gateway, origin.request_id)
            )
        )
        return {"action": "skip", "reason": "discord-technical-only"}
    except Exception:
        LOGGER.exception("Discord technical pre-dispatch policy failed")
        if platform == "discord":
            # Fail closed: Hermes itself falls through on hook exceptions, so
            # convert every Discord policy failure into an explicit skip.
            return {"action": "skip", "reason": "discord-technical-policy-error"}
        return None


def resource_helper():
    name = "_ai_platform_resource_queue"
    with _helper_lock:
        if name not in sys.modules:
            path = "/usr/local/libexec/ai-server/hermes_resource_queue.py"
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
    return sys.modules[name]


def route(source):
    platform = source.platform.value
    if platform not in ("telegram", "discord") or not source.chat_id:
        raise ValueError("unsupported messaging context")
    target = f"{platform}:{source.chat_id}"
    return target + (f":{source.thread_id}" if source.thread_id else "")


async def voice_notice(origin, event):
    """Existing resource-queue voice notice; retained for Telegram/general compatibility."""
    from gateway.config import Platform

    source = origin.event.source
    if origin.task.done():
        return
    if source.platform != Platform.DISCORD:
        return
    adapter = origin.gateway.adapters.get(Platform.DISCORD)
    if adapter is None or not hasattr(adapter, "play_in_voice_channel"):
        return
    channels = getattr(adapter, "_voice_text_channels", {})
    guild = next(
        (
            g
            for g, c in channels.items()
            if str(c) == str(source.chat_id) and adapter.is_in_voice_channel(g)
        ),
        None,
    )
    if guild is None:
        return
    phrase = {
        "queued": "Serwer AI jest zajęty. Dodałem pytanie do kolejki.",
        "active": "Zwolniły się zasoby. Zaczynam.",
    }.get(event)
    if not phrase:
        return
    await _play_voice_text(adapter, source, phrase, reply_to=None, require_active_vc=True)


def execute(request, next_call, base_url="", api_call_count=1, **_):
    """Existing Hermes LLM admission middleware.

    Discord technical turns are intercepted before this middleware. Telegram keeps
    using this path exactly as before.
    """
    helper = resource_helper()
    from gateway.session_context import get_session_env

    platform = get_session_env("HERMES_SESSION_PLATFORM", "")
    chat = get_session_env("HERMES_SESSION_CHAT_ID", "")
    thread = get_session_env("HERMES_SESSION_THREAD_ID", "")
    if (
        platform not in ("telegram", "discord")
        or not chat
        or not helper.should_manage_base_url(base_url)
    ):
        return next_call(request)
    target = f"{platform}:{chat}" + (f":{thread}" if thread else "")
    origin = _origin.get()
    if origin is not None and route(origin.event.source) != target:
        origin = None
    first = int(api_call_count or 0) <= 1

    def status(event):
        if origin is not None and platform == "discord" and first:
            future = asyncio.run_coroutine_threadsafe(
                voice_notice(origin, event), origin.loop
            )
            future.add_done_callback(
                lambda f: f.exception() if not f.cancelled() else None
            )

    lease = helper.acquire_resource(
        target=target,
        source=platform + "-chat",
        priority=50,
        queue_message=(
            "⏳ Serwer AI jest teraz zajęty. Twoje zapytanie czeka w kolejce."
            if first
            else None
        ),
        start_message=(
            "▶️ Zwolniły się zasoby. Rozpoczynam Twoje zapytanie."
            if first
            else None
        ),
        status_callback=status if first else None,
    )
    try:
        headers = dict(request.get("extra_headers") or {})
        headers.update(
            {
                "X-AI-Resource-Lease": lease.lease_id,
                "X-AI-Resource-Lease-Release": "1",
            }
        )
        reservation = helper._json("GET", f"/resource/leases/{lease.lease_id}")
        headers["X-Request-Id"] = reservation["job"]["request_id"]
        return next_call({**request, "extra_headers": headers})
    finally:
        lease.release()


def _thread_metadata(gateway, event):
    source = event.source
    metadata = {}
    builder = getattr(gateway, "_thread_metadata_for_source", None)
    if callable(builder):
        try:
            metadata = dict(builder(source, getattr(event, "message_id", None)) or {})
        except Exception:
            LOGGER.debug("Discord thread metadata helper failed", exc_info=True)
    elif getattr(source, "thread_id", None):
        metadata["thread_id"] = source.thread_id
    metadata["notify"] = True
    return metadata


async def _send_text(adapter, gateway, event, text):
    if adapter is None:
        raise RuntimeError("Discord adapter unavailable")
    chat_id = str(event.source.chat_id)
    limit_probe = getattr(adapter, "max_message_length_for_chat", None)
    try:
        limit = int(limit_probe(chat_id)) if callable(limit_probe) else 2000
    except Exception:
        limit = 2000
    limit = max(500, min(limit, 8000))
    chunks = _split_message(text, limit)
    metadata = _thread_metadata(gateway, event)
    for index, chunk in enumerate(chunks):
        result = await adapter.send(
            chat_id,
            chunk,
            reply_to=getattr(event, "message_id", None) if index == 0 else None,
            metadata=metadata,
        )
        if result is not None and getattr(result, "success", True) is False:
            raise RuntimeError(getattr(result, "error", None) or "Discord send failed")


def _split_message(text, limit):
    text = str(text or "").strip()
    if len(text) <= limit:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return [chunk for chunk in chunks if chunk]


async def _send_typing(adapter, event):
    sender = getattr(adapter, "send_typing", None)
    if not callable(sender):
        return
    try:
        await sender(
            str(event.source.chat_id),
            metadata={"thread_id": event.source.thread_id}
            if getattr(event.source, "thread_id", None)
            else None,
        )
    except Exception:
        LOGGER.debug("Discord typing indicator failed", exc_info=True)


def _conversation_id(source):
    digest = hashlib.sha256(route(source).encode("utf-8")).hexdigest()[:24]
    return "conv_discord_" + digest


def _technical_payload(query, request_id, source):
    conversation_id = _conversation_id(source)
    return {
        "schema_version": 1,
        "message": query,
        "conversation_id": conversation_id,
        "client_id": "discord",
        "mode": "hybrid",
        "context": {
            "domain": _DISCORD_DOMAIN,
            "request_id": "discord_" + request_id,
            "session_id": conversation_id,
        },
        "limit": 8,
        "priority_class": "interactive",
        "timeout_seconds": 300,
    }


def _technical_turn(query, request_id, source):
    payload = json.dumps(
        _technical_payload(query, request_id, source),
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = os.getenv("AI_PLATFORM_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(
        _PLATFORM_TURN_URL,
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=310) as response:
            body = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"Technical Conversation API HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Technical Conversation API unavailable: {exc}") from exc
    result = json.loads(body.decode("utf-8"))
    if not isinstance(result, dict) or "answer" not in result or "conversation_id" not in result:
        raise RuntimeError("Technical Conversation API returned invalid payload")
    return result


def _source_link(citation):
    document_id = str(citation.get("document_id") or "").strip()
    if _SOURCE_BASE_URL and document_id:
        parsed = urlparse(_SOURCE_BASE_URL)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            link = (
                _SOURCE_BASE_URL
                + "/api/v1/knowledge/documents/"
                + quote(document_id, safe="")
                + "/original"
            )
            page = citation.get("page")
            if page is not None:
                link += "#page=" + quote(str(page), safe="")
            return link

    # Safe zero-config fallback for canonical repo sources. This never exposes
    # local filesystem/object-store paths.
    source = citation.get("source") or {}
    uri = str(source.get("uri") or "").strip()
    prefix = "github://"
    if uri.startswith(prefix):
        remainder = uri[len(prefix):].strip("/")
        parts = remainder.split("/", 2)
        if len(parts) == 3 and all(parts):
            owner, repository, path = parts
            return (
                "https://github.com/"
                + quote(owner, safe="")
                + "/"
                + quote(repository, safe="")
                + "/blob/main/"
                + quote(path, safe="/")
            )
    return None


def _format_discord_response(result):
    answer = str(result.get("answer") or "").strip()
    if not answer:
        answer = "Brak odpowiedzi w Knowledge Service."

    citations = result.get("citations") or []
    lines = [answer]
    if result.get("insufficient_context") and result.get("insufficiency_reason"):
        lines.extend(["", "⚠️ " + str(result["insufficiency_reason"]).strip()])

    if citations:
        lines.extend(["", "**Źródła:**"])
        for citation in citations[:_MAX_CITATIONS]:
            ref = str(citation.get("ref") or "S?")
            source = citation.get("source") or {}
            title = str(source.get("title") or source.get("uri") or "Źródło")
            locator = []
            if citation.get("page") is not None:
                locator.append("str. " + str(citation["page"]))
            if citation.get("section"):
                locator.append(str(citation["section"]))
            line = f"[{ref}] {title}"
            if locator:
                line += " — " + " · ".join(locator)
            link = _source_link(citation)
            if link:
                line += " — <" + link + ">"
            lines.append(line)

    return "\n".join(lines).strip()


def _active_voice_guild(adapter, source):
    channels = getattr(adapter, "_voice_text_channels", {})
    if not isinstance(channels, dict):
        return None
    is_in_voice = getattr(adapter, "is_in_voice_channel", None)
    if not callable(is_in_voice):
        return None
    return next(
        (
            guild_id
            for guild_id, text_channel_id in channels.items()
            if str(text_channel_id) == str(source.chat_id)
            and is_in_voice(guild_id)
        ),
        None,
    )


def _should_voice_reply(adapter, event):
    if _message_type_value(event) == "voice":
        return True
    probe = getattr(adapter, "_should_auto_tts_for_chat", None)
    if callable(probe):
        try:
            return bool(probe(str(event.source.chat_id)))
        except Exception:
            pass
    return False


async def _tts_artifact(text, directory):
    from tools.tts_tool import text_to_speech_tool

    output = Path(directory) / "discord-technical.mp3"
    raw = await asyncio.to_thread(
        text_to_speech_tool,
        text=text,
        output_path=str(output),
    )
    result = json.loads(raw) if isinstance(raw, str) else {}
    candidates = result.get("file_paths") or [result.get("file_path") or output]
    safe_paths = []
    root = Path(directory).resolve()
    for candidate in candidates:
        path = Path(candidate).resolve()
        if path.parent == root and path.is_file():
            safe_paths.append(path)
    if not safe_paths:
        raise RuntimeError("Discord technical TTS produced no owned audio")
    return safe_paths


async def _play_voice_text(
    adapter,
    source,
    text,
    *,
    reply_to,
    metadata=None,
    require_active_vc=False,
):
    if adapter is None or not text.strip():
        return
    with tempfile.TemporaryDirectory(prefix="ai-platform-discord-voice-") as directory:
        paths = await _tts_artifact(text, directory)
        guild = _active_voice_guild(adapter, source)
        if guild is not None and hasattr(adapter, "play_in_voice_channel"):
            for path in paths:
                if not await adapter.play_in_voice_channel(guild, str(path)):
                    raise RuntimeError("Discord voice playback failed")
            return
        if require_active_vc:
            return
        sender = getattr(adapter, "send_voice", None)
        if not callable(sender):
            return
        for path in paths:
            await sender(
                chat_id=str(source.chat_id),
                audio_path=str(path),
                reply_to=reply_to,
                metadata=metadata,
            )


async def discord_technical_turn(event, gateway, request_id):
    source = event.source
    adapter = gateway.adapters.get(source.platform)
    if adapter is None:
        LOGGER.error("Discord technical policy has no adapter")
        return

    command = _safe_command(event)
    if command:
        await _send_text(adapter, gateway, event, _POLICY_HELP)
        return

    kind = _message_type_value(event)
    has_media = bool(getattr(event, "media_urls", None))
    if kind not in ("text", "voice", "command") or (has_media and kind != "voice"):
        await _send_text(adapter, gateway, event, _MEDIA_DISABLED)
        return

    query = str(getattr(event, "text", "") or "").strip()
    if not query:
        await _send_text(adapter, gateway, event, _POLICY_HELP)
        return
    if len(query) > _MAX_QUERY_CHARS:
        await _send_text(
            adapter,
            gateway,
            event,
            f"Zapytanie jest za długie. Limit technicznego zapytania to {_MAX_QUERY_CHARS} znaków.",
        )
        return

    await _send_typing(adapter, event)
    try:
        result = await asyncio.to_thread(_technical_turn, query, request_id, source)
        response_text = _format_discord_response(result)
        await _send_text(adapter, gateway, event, response_text)
        if _should_voice_reply(adapter, event):
            answer = str(result.get("answer") or "").strip()
            if answer:
                tts_text = answer
                if len(tts_text) > 6000:
                    tts_text = (
                        tts_text[:5800]
                        + " Pełna odpowiedź i źródła są w wiadomości tekstowej."
                    )
                await _play_voice_text(
                    adapter,
                    source,
                    tts_text,
                    reply_to=getattr(event, "message_id", None),
                    metadata=_thread_metadata(gateway, event),
                )
    except Exception:
        LOGGER.exception("Discord technical Knowledge request failed")
        await _send_text(
            adapter,
            gateway,
            event,
            "Nie udało się teraz pobrać odpowiedzi z Knowledge Service. "
            "Nie przełączam tego zapytania na ogólny model — spróbuj ponownie za chwilę.",
        )


async def media(command, args):
    origin = _origin.get()
    if origin is None:
        return "Polecenie wymaga kontekstu wiadomości Telegram lub Discord."
    source = origin.event.source
    route(source)
    if source.platform.value == "discord":
        return _MEDIA_DISABLED

    # Telegram media behavior stays unchanged.
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("HERMES_SESSION_") or key in (
            "HERMES_FOTO_INPUT_IMAGE",
            "HERMES_VIDEO_INPUT_IMAGE",
            "HERMES_RESOURCE_LEASE_ID",
        ):
            env.pop(key)
    env.update(
        HERMES_SESSION_PLATFORM=source.platform.value,
        HERMES_SESSION_CHAT_ID=str(source.chat_id),
        HERMES_SESSION_THREAD_ID=str(source.thread_id or ""),
        AI_PLATFORM_REQUEST_ID=origin.request_id,
    )
    from gateway.run import _event_media_is_image

    images = [
        str(path)
        for i, path in enumerate(origin.event.media_urls or [])
        if _event_media_is_image(origin.event, i)
    ]
    if images:
        env[
            "HERMES_FOTO_INPUT_IMAGE"
            if command == "foto"
            else "HERMES_VIDEO_INPUT_IMAGE"
        ] = images[0]
    binary = (
        "/usr/local/bin/hermes-foto-dispatch"
        if command == "foto"
        else "/usr/local/bin/hermes-video-dispatch"
    )
    proc = await asyncio.create_subprocess_exec(
        binary,
        args,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), 30)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise
    if proc.returncode:
        return f"Nie udało się uruchomić /{command}."
    return stdout.decode().strip()


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", observe)
    ctx.register_middleware("llm_execution", execute)
    for command in ("foto", "wideo"):
        async def handler(args, command=command):
            return await media(command, args)

        ctx.register_command(
            command,
            handler,
            description="AI Platform media",
            args_hint="<prompt>",
        )
