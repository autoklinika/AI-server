from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from threading import Lock
from uuid import uuid4


_FOLLOWUP = re.compile(
    r"^(?:a|i|ale|czy|to|ten|ta|te|tego|tej|tym|jego|jej|ich|ile|jaki|jaka|jakie|"
    r"gdzie|który|która|które|co z|a co z)\b",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_standalone_anchor(query: str) -> bool:
    tokens = re.findall(r"[\w.-]+", query, re.UNICODE)
    for index, token in enumerate(tokens):
        if any(char.isdigit() for char in token):
            return True
        if len(token) >= 2 and token.upper() == token and any(char.isalpha() for char in token):
            return True
        if index > 0 and token[:1].isupper() and any(char.isalpha() for char in token):
            return True
    return False


@dataclass(frozen=True)
class TechnicalConversationContext:
    conversation_id: str
    retrieval_query: str
    previous_user_query: str | None


class TechnicalConversationStore:
    """Bounded platform-owned technical conversation state.

    Adapters supply or receive only a conversation ID. The state belongs to the
    Platform runtime, so Discord and future thin clients (for example StackChan)
    do not own retrieval context or answer history.
    """

    def __init__(self, *, max_sessions: int = 128, turns_per_session: int = 12) -> None:
        if max_sessions < 1 or turns_per_session < 2:
            raise ValueError("invalid conversation retention")
        self.max_sessions = max_sessions
        self.turns_per_session = turns_per_session
        self._sessions: dict[str, dict] = {}
        self._order: deque[str] = deque()
        self._lock = Lock()

    def prepare(self, *, conversation_id: str | None, message: str) -> TechnicalConversationContext:
        query = " ".join(str(message or "").split())
        if not query:
            raise ValueError("message is required")
        resolved = conversation_id or ("conv_" + uuid4().hex)
        with self._lock:
            session = self._sessions.get(resolved)
            previous = None
            if session:
                for turn in reversed(session["turns"]):
                    if turn["role"] == "user":
                        previous = turn["content"]
                        break

        retrieval_query = query
        # Only contextualize likely follow-ups. Full standalone questions remain
        # untouched so client history cannot pollute otherwise precise retrieval.
        if (
            previous
            and (len(query.split()) <= 4 or _FOLLOWUP.search(query))
            and not _has_standalone_anchor(query)
        ):
            retrieval_query = f"{query}\nKontekst poprzedniego pytania: {previous}"

        return TechnicalConversationContext(
            conversation_id=resolved,
            retrieval_query=retrieval_query,
            previous_user_query=previous,
        )

    def add_turn(
        self,
        *,
        conversation_id: str,
        user_message: str,
        response: dict,
        client_id: str,
        retrieval_query: str,
    ) -> dict:
        with self._lock:
            if conversation_id not in self._sessions:
                if len(self._sessions) >= self.max_sessions:
                    oldest = self._order.popleft()
                    self._sessions.pop(oldest, None)
                self._sessions[conversation_id] = {
                    "conversation_id": conversation_id,
                    "created_at": _now(),
                    "updated_at": _now(),
                    "turns": deque(maxlen=self.turns_per_session),
                }
                self._order.append(conversation_id)
            session = self._sessions[conversation_id]
            turn_id = "turn_" + uuid4().hex
            created_at = _now()
            session["turns"].append({
                "turn_id": turn_id,
                "role": "user",
                "content": user_message,
                "client_id": client_id,
                "retrieval_query": retrieval_query,
                "created_at": created_at,
            })
            session["turns"].append({
                "turn_id": turn_id,
                "role": "assistant",
                "content": str(response.get("answer") or ""),
                "client_id": "ai-platform",
                "insufficient_context": bool(response.get("insufficient_context")),
                "citation_count": len(response.get("citations") or []),
                "created_at": created_at,
            })
            session["updated_at"] = created_at
            return {
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "created_at": created_at,
            }

    def get(self, conversation_id: str) -> dict:
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None:
                raise KeyError(conversation_id)
            return {
                "conversation_id": session["conversation_id"],
                "created_at": session["created_at"],
                "updated_at": session["updated_at"],
                "turns": [deepcopy(turn) for turn in session["turns"]],
            }

    def retention(self) -> dict:
        return {
            "persistent": False,
            "scope": "platform-runtime",
            "max_sessions": self.max_sessions,
            "turns_per_session": self.turns_per_session,
        }
