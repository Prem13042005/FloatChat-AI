"""
src/orchestration/cancellation.py

FloatChat Cooperative Workflow Cancellation Primitives.
Provides thread-safe CancellationToken and WorkflowCancelledError for interrupting
multi-step LangGraph workflows when requests timeout or are aborted by clients.
"""

import threading
from typing import Optional


class WorkflowCancelledError(Exception):
    """
    Raised when a workflow or operation is cancelled or timed out via CancellationToken.
    Halts downstream agent executions and graph node transitions.
    """
    pass


class CancellationToken:
    """
    Thread-safe cooperative cancellation token using threading.Event.
    Safe to access and signal across the asyncio event loop and synchronous worker threads.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Signals cancellation to all observers."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """Returns True if cancellation has been signalled, False otherwise."""
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """
        Raises WorkflowCancelledError if cancellation has been signalled.
        Should be called at checkpoints before expensive agent or database operations.
        """
        if self._event.is_set():
            raise WorkflowCancelledError("Workflow execution was cancelled or timed out.")

    def __repr__(self) -> str:
        return f"<CancellationToken cancelled={self.is_cancelled}>"

