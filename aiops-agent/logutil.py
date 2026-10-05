"""Tiny structured-logging helper.

Everything the agent logs is a single JSON line on stdout so it is trivial to
`kubectl logs -f` during the demo and grep/parse it, or ship it to Loki like
any other workload log.
"""
import datetime
import json
import sys


def log_event(level: str, event_type: str, app: str = "", **details):
    record = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "level": level,
        "type": event_type,
        "app": app,
        "details": details,
    }
    print(json.dumps(record), file=sys.stdout, flush=True)
