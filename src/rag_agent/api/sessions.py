"""In-memory conversation store for the chat endpoint.

Deliberately the simplest thing that works, and deliberately documented as
such: sessions live in this process only. A second replica would not see them,
and a restart forgets everything. Making that survive means Redis or a
database, which is a decision to take when there is a second replica -- not
before.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from uuid import uuid4

from rag_agent.agent import ChatSession

SessionFactory = Callable[[], ChatSession]

logger = logging.getLogger(__name__)

MAX_SESSIONS = 100


class SessionStore:
    """Keeps the most recent conversations, evicting the oldest.

    The cap exists because every session holds its whole message history: an
    unbounded dictionary is a memory leak with a friendly name.
    """

    def __init__(
        self,
        max_sessions: int = MAX_SESSIONS,
        factory: SessionFactory | None = None,
    ) -> None:
        # The factory is injected so the store never needs to know how a
        # session is built. Constructing one reaches the model provider, and a
        # store that cannot be exercised without credentials is a store that
        # goes untested.
        self._factory: SessionFactory = factory or ChatSession
        self._sessions: OrderedDict[str, ChatSession] = OrderedDict()
        self._max_sessions = max_sessions

    def __len__(self) -> int:
        return len(self._sessions)

    def get_or_create(self, session_id: str | None) -> tuple[str, ChatSession]:
        """Return an existing conversation, or open a new one.

        An unknown id opens a new conversation rather than failing: a client
        holding an id from before a restart should keep working, not break.
        """
        if session_id and session_id in self._sessions:
            self._sessions.move_to_end(session_id)
            return session_id, self._sessions[session_id]

        new_id = session_id or uuid4().hex
        self._sessions[new_id] = self._factory()
        self._evict_oldest()

        logger.info("Opened session %s (%d active)", new_id, len(self._sessions))
        return new_id, self._sessions[new_id]

    def drop(self, session_id: str) -> bool:
        """Forget one conversation. Returns whether it existed."""
        return self._sessions.pop(session_id, None) is not None

    def _evict_oldest(self) -> None:
        while len(self._sessions) > self._max_sessions:
            evicted, _ = self._sessions.popitem(last=False)
            logger.info("Evicted session %s (cap %d)", evicted, self._max_sessions)
