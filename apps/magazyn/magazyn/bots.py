"""Private-only Telegram/Discord bot adapters for Magazyn V1.

Opt-in separate services: no public endpoints, no reused Hermes credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

from .store import Store
from . import messaging

MAX_TELEGRAM_REPLY = 3600
MAX_DISCORD_REPLY = 1800


class RateLimiter:
    def __init__(self, cooldown_seconds=2):
        self.cooldown_seconds = cooldown_seconds
        self.last = {}

    def allow(self, provider: str, user_id: str) -> bool:
        marker=(provider,user_id)
        instant=time.monotonic()
        previous=self.last.get(marker,-1e20)
        self.last[marker]=instant
        if len(self.last)>5000:
            self.last = {k:v for k,v in self.last.items() if instant-v<60}
        return instant-previous >= self.cooldown_seconds


def telegram_private_incoming(update: dict) -> tuple[str,str] | None:
    """Check private chat and sender identity before lookup or pairing."""
    if not isinstance(update,dict) or not isinstance(update.get("message"),dict):
        return None
    msg=update["message"]
    chat=msg.get("chat")
    sender=msg.get("from")
    if not isinstance(chat,dict) or chat.get("type")!="private":
        return None
    if not isinstance(sender,dict) or sender.get("is_bot"):
        return None
    sender_id=sender.get("id")
    chat_id=chat.get("id")
    if type(sender_id) is not int or sender_id<=0 or type(chat_id) is not int or chat_id!=sender_id:
        return None
    value=msg.get("text")
    if not isinstance(value,str) or not value.strip():
        return None
    return str(sender_id),value


def discord_private_incoming(*, guild_id, channel_kind: str, sender_id: str | int,
                             is_bot: bool, content: str) -> tuple[str,str] | None:
    if guild_id is not None or channel_kind!="dm" or is_bot:
        return None
    try:
        identity=messaging._identity(sender_id)
    except Exception:
        return None
    if not isinstance(content,str) or not content.strip():
        return None
    return identity,content


def reply_for_telegram(store, update, limiter=None) -> tuple[str,str] | None:
    incoming=telegram_private_incoming(update)
    if incoming is None:
        return None
    identity, content=incoming
    if limiter and not limiter.allow("telegram",identity):
        return identity,"Odczekaj chwilę przed następnym zapytaniem."
    return identity,messaging.process_private_message(store,"telegram",identity,content)


def reply_for_discord(store, *, guild_id, channel_kind, sender_id, is_bot, content,
                      limiter=None) -> tuple[str,str] | None:
    incoming=discord_private_incoming(guild_id=guild_id,channel_kind=channel_kind,
        sender_id=sender_id,is_bot=is_bot,content=content)
    if incoming is None:
        return None
    identity, value=incoming
    if limiter and not limiter.allow("discord",identity):
        return identity,"Odczekaj chwilę przed następnym zapytaniem."
    return identity,messaging.process_private_message(store,"discord",identity,value)


def dispatch_pending(store, provider: str, deliver, *, maximum: int=10) -> dict:
    """Transport-agnostic delivery. Tests inject a fake sender; no network needed."""
    sent=failed=0
    for _ in range(maximum):
        item=messaging.claim_next(store,provider)
        if item is None:
            break
        if not messaging.delivery_still_allowed(store,item):
            messaging.cancel_outbox(store,item["id"])
            continue
        try:
            deliver(item["external_user_id"],item["body"])
        except Exception:
            messaging.mark_failed(store,item)
            failed+=1
        else:
            messaging.mark_delivered(store,item)
            sent+=1
    return {"sent":sent,"failed":failed}


def run_telegram(store: Store, bot_token: str):
    import httpx
    if not bot_token:
        raise RuntimeError("MAGAZYN_TELEGRAM_BOT_TOKEN jest wymagany")
    endpoint = f"https://api.telegram.org/bot{bot_token}/"
    limiter=RateLimiter()
    offset=None
    with httpx.Client(timeout=httpx.Timeout(30,connect=10),follow_redirects=False) as http:
        def tg(method: str, payload: dict):
            result=http.post(endpoint+method,json=payload)
            result.raise_for_status()
            response=result.json()
            if not response.get("ok"):
                raise RuntimeError("Telegram API rejected request")
            return response["result"]
        def deliver(recipient: str,text: str):
            tg("sendMessage",{"chat_id":int(recipient),"text":text[:MAX_TELEGRAM_REPLY],
                               "disable_web_page_preview":True})
        while True:
            try:
                payload={"timeout":15,"limit":25,"allowed_updates":["message"]}
                if offset is not None:
                    payload["offset"]=offset
                updates=tg("getUpdates",payload)
                for update in updates:
                    incoming_id=update.get("update_id")
                    if type(incoming_id) is int and incoming_id>=0:
                        offset=max(offset or 0,incoming_id+1)
                    reply=reply_for_telegram(store,update,limiter)
                    if reply:
                        recipient,body=reply
                        deliver(recipient,body)
                dispatch_pending(store,"telegram",deliver)
            except KeyboardInterrupt:
                break
            except Exception:
                # Avoid logging HTTPX exception: Telegram token is embedded in the URL.
                print("Magazyn Telegram: błąd połączenia lub wysyłki; ponawiam.",file=sys.stderr)
                time.sleep(6)


def run_discord(store: Store, bot_token: str):
    if not bot_token:
        raise RuntimeError("MAGAZYN_DISCORD_BOT_TOKEN jest wymagany")
    try:
        import discord
    except ImportError as exc:
        raise RuntimeError("Discord wymaga discord.py w osobnym środowisku") from exc

    intents=discord.Intents.none()
    intents.dm_messages=True
    intents.message_content=True
    client=discord.Client(intents=intents)
    limiter=RateLimiter()

    async def deliver_dm(entry):
        user=await client.fetch_user(int(entry["external_user_id"]))
        # fetch_user awaits the network. Re-check permissions after that await,
        # immediately before initiating the outbound Discord send.
        if not messaging.delivery_still_allowed(store,entry):
            return False
        await user.send(entry["body"][:MAX_DISCORD_REPLY],
                        allowed_mentions=discord.AllowedMentions.none())
        return True

    @client.event
    async def on_message(message):
        if message.author.bot or message.guild is not None or not isinstance(message.channel,discord.DMChannel):
            return
        reply=reply_for_discord(
            store,guild_id=None,channel_kind="dm",sender_id=message.author.id,
            is_bot=False,content=message.content,limiter=limiter)
        if reply:
            _identity,body=reply
            try:
                await message.channel.send(body[:MAX_DISCORD_REPLY],
                                           allowed_mentions=discord.AllowedMentions.none())
            except (discord.HTTPException,discord.Forbidden):
                return

    async def drain_queue():
        while not client.is_closed():
            try:
                for _ in range(10):
                    entry=messaging.claim_next(store,"discord")
                    if entry is None:
                        break
                    if not messaging.delivery_still_allowed(store,entry):
                        messaging.cancel_outbox(store,entry["id"])
                        continue
                    try:
                        was_sent=await deliver_dm(entry)
                    except Exception:
                        messaging.mark_failed(store,entry)
                    else:
                        if was_sent:
                            messaging.mark_delivered(store,entry)
                        else:
                            messaging.cancel_outbox(store,entry["id"])
            except asyncio.CancelledError:
                raise
            except Exception:
                # Transient database failure must not terminate the worker forever.
                print("Magazyn Discord: kolejka niedostępna; ponawiam.",file=sys.stderr)
            await asyncio.sleep(15)

    @client.event
    async def on_ready():
        task=getattr(client,"_magazyn_queue_task",None)
        if task is None or task.done():
            client._magazyn_queue_task=asyncio.create_task(
                drain_queue(),name="magazyn-discord-outbox")

    client.run(bot_token,log_handler=None)


def main(argv=None):
    parser=argparse.ArgumentParser(description="Magazyn V1 DM-only bot (explicit activation)")
    parser.add_argument("provider",choices=messaging.PROVIDERS)
    parser.add_argument("--db",default=os.environ.get("MAGAZYN_DB_PATH"))
    args=parser.parse_args(argv)
    if os.environ.get("MAGAZYN_BOTS_ENABLED")!="1":
        parser.error("Boty są wyłączone. Wymagane MAGAZYN_BOTS_ENABLED=1 po odbiorze.")
    if not args.db:
        parser.error("MAGAZYN_DB_PATH jest wymagane")
    store=Store(args.db)
    if not any(u["active"] and u["role"]=="admin" for u in store.users()):
        parser.error("Wymagany istniejący administrator")
    if args.provider=="telegram":
        run_telegram(store,os.environ.get("MAGAZYN_TELEGRAM_BOT_TOKEN",""))
    else:
        run_discord(store,os.environ.get("MAGAZYN_DISCORD_BOT_TOKEN",""))


if __name__=="__main__":
    main()
