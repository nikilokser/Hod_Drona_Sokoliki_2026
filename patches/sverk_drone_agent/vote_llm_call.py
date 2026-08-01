#!/usr/bin/env python3
"""Standalone helper for execute_vote() in pseudo_agent_text_node.py.

Makes the LLM chat-completion call for a [ГОЛОСОВАНИЕ] vote request in a
fresh, independent process instead of inside the long-running rospy node.

Observed live on sverk-8/king-8 (2026-08-01): the exact same request
(same key, same model, same headers, same payload) succeeds reliably
(~0.15-4s) when run as a standalone process, but is measurably less
reliable (repeated HTTP 403 "Access denied by security policy", timeouts)
when made from inside the rospy-managed agent process - reproduced even
under clean network conditions (0% ping loss to the endpoint) and with a
bare `rospy.init_node()` + plain urllib call with none of this patch's
other code involved. The exact mechanism was not fully isolated (rospy's
signal/socket handling is the leading suspect, possibly interacting with
some edge/WAF behavior on the gateway's side) - running the network call
in a plain, independent subprocess sidesteps it entirely, matching every
standalone reproduction that worked reliably during debugging.

Reads a JSON request from stdin:
    {"base_url": "...", "api_key": "...", "model": "...",
     "system_prompt": "...", "user_text": "..."}
Writes a JSON result to stdout:
    {"ok": true, "content": "..."} or {"ok": false, "error": "..."}

Never raises past main() - always exits 0 with a JSON result on stdout,
so the caller (execute_vote) only ever needs to parse stdout, not handle
a non-zero exit code or stderr separately.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def main() -> None:
    request = json.loads(sys.stdin.read())
    base_url = str(request.get("base_url") or "").rstrip("/")
    api_key = str(request.get("api_key") or "")
    model = str(request.get("model") or "")

    if not api_key:
        print(json.dumps({"ok": False, "error": "LLM API key is not set."}))
        return
    if not model:
        print(json.dumps({"ok": False, "error": "LLM model is not set."}))
        return
    if not base_url:
        print(json.dumps({"ok": False, "error": "LLM base URL is not set."}))
        return

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": request.get("system_prompt") or ""},
            {"role": "user", "content": request.get("user_text") or ""},
        ],
        "temperature": 0.2,
    }
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": "Bearer %s" % api_key,
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "sverk-drone-agent/1.0",
        "HTTP-Referer": "https://sverk-drone.local",
        "X-OpenRouter-Title": "sverk-drone-agent",
        "X-Title": "sverk-drone-agent",
    }
    req = urllib.request.Request(
        "%s/chat/completions" % base_url, data=encoded, headers=headers, method="POST"
    )
    try:
        # Comfortably under the caller's subprocess timeout (13s as of
        # 2026-08-01, see pseudo_agent_text_node.py's VOTE_SUBPROCESS_TIMEOUT_SEC)
        # so this can return a clean JSON error instead of getting killed.
        with urllib.request.urlopen(req, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = str(body["choices"][0]["message"]["content"] or "").strip()
        print(json.dumps({"ok": True, "content": content}, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(json.dumps({"ok": False, "error": "LLM HTTP %d: %s" % (exc.code, error_body)}, ensure_ascii=False))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(json.dumps({"ok": False, "error": "LLM connection error: %s" % exc}, ensure_ascii=False))
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": "Некорректный ответ LLM: %s" % exc}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - last-resort guard, caller only reads stdout
        print(json.dumps({"ok": False, "error": "Неожиданная ошибка helper-процесса: %s" % exc}))
