"""
In-memory state the control loop keeps between iterations:
  - a ring buffer of every remediation action taken (shown live at /actions)
  - a cooldown tracker so the same app+anomaly isn't re-remediated every 15s
    while a previous remediation is still taking effect.
"""
import datetime
import threading
from collections import deque

import config

_lock = threading.Lock()
_actions = deque(maxlen=config.ACTIONS_RING_BUFFER_SIZE)
_last_remediated_at = {}  # (app, anomaly_type) -> epoch seconds


def record_action(app: str, anomaly_type: str, action: str, details: dict):
    """Append an action to the ring buffer. Thread-safe (the HTTP server and
    the control loop run on different threads)."""
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "app": app,
        "anomaly_type": anomaly_type,
        "action": action,
        "details": details,
    }
    with _lock:
        _actions.appendleft(entry)  # most-recent-first, matches /actions contract


def get_actions():
    """Return the last N actions, most recent first."""
    with _lock:
        return list(_actions)


def is_in_cooldown(app: str, anomaly_type: str, now: float) -> bool:
    with _lock:
        last = _last_remediated_at.get((app, anomaly_type))
    if last is None:
        return False
    return (now - last) < config.COOLDOWN_SECONDS


def mark_remediated(app: str, anomaly_type: str, now: float):
    with _lock:
        _last_remediated_at[(app, anomaly_type)] = now
