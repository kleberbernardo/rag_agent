"""HTTP layer: the agent exposed as a service.

It exists because the orchestration already lives in `agent.service`. Adding
an interface is a wrapper, not a rewrite -- which was the reason for keeping
that layer free of terminal concerns in the first place.
"""

from rag_agent.api.app import app, create_app
from rag_agent.api.feedback import FeedbackStore
from rag_agent.api.sessions import InMemorySessionStore, RedisSessionStore, SessionStore

__all__ = [
    "FeedbackStore",
    "InMemorySessionStore",
    "RedisSessionStore",
    "SessionStore",
    "app",
    "create_app",
]
