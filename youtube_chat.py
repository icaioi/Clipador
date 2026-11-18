"""Public YouTube LIVE chat; no account, user API key, or browser cookies.

Initial page/history and the first continuation batch are baselines, never
messages for the spike detector. Reconnection establishes a fresh baseline.
"""
from __future__ import annotations

from collections import deque
import json
import re
import time
from urllib.parse import urlsplit

import requests

from clipador_youtube import url_origem

_TIMEOUT = (5, 12)
_MAX_IDS = 4096
_ORIGIN = "https://www.youtube.com"
_ENDPOINT = _ORIGIN + "/youtubei/v1/live_chat/get_live_chat"
_JSON = json.JSONDecoder()
_ASSIGNMENTS = {
    "ytInitialData": re.compile(r'(?:\b(?:var\s+)?ytInitialData\s*|window\s*\[\s*[\"\']ytInitialData[\"\']\s*\]\s*)=\s*'),
    "ytInitialPlayerResponse": re.compile(r'(?:\b(?:var\s+)?ytInitialPlayerResponse\s*|window\s*\[\s*[\"\']ytInitialPlayerResponse[\"\']\s*\]\s*)=\s*'),
    "ytcfg": re.compile(r'\bytcfg\s*\.\s*set\s*\(\s*'),
}


class _Unavailable(Exception):
    """Safe, non-sensitive status suitable for bounded logging."""


def _page_json(html, name):
    """Decode each assignment's balanced JSON, respecting strings and escapes."""
    result = {}
    for match in _ASSIGNMENTS[name].finditer(html):
        try:
            value, _ = _JSON.raw_decode(html, match.end())
        except (ValueError, RecursionError):
            continue
        if isinstance(value, dict):
            if name != "ytcfg":
                return value
            result.update(value)
    return result


def _find(value, key):
    """Find a named renderer without assuming a particular page layout."""
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            found = node.get(key)
            if isinstance(found, dict):
                return found
            pending.extend(reversed(list(node.values())))
        elif isinstance(node, list):
            pending.extend(reversed(node))
    return None


def _text(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    if isinstance(value.get("simpleText"), str):
        return value["simpleText"]
    pieces = []
    for run in value.get("runs", []):
        if not isinstance(run, dict):
            continue
        if isinstance(run.get("text"), str):
            pieces.append(run["text"])
        else:
            emoji = run.get("emoji", {})
            if isinstance(emoji, dict):
                shortcuts = emoji.get("shortcuts", [])
                if shortcuts and isinstance(shortcuts[0], str):
                    pieces.append(shortcuts[0])
                else:
                    label = emoji.get("image", {}).get("accessibility", {}).get("accessibilityData", {}).get("label", "")
                    if isinstance(label, str):
                        pieces.append(label)
    return "".join(pieces)


def _continuation(renderer):
    for entry in renderer.get("continuations", []):
        if not isinstance(entry, dict):
            continue
        for key in ("timedContinuationData", "invalidationContinuationData", "reloadContinuationData"):
            data = entry.get(key)
            if not isinstance(data, dict):
                continue
            token = data.get("continuation")
            if not isinstance(token, str) or not token:
                continue
            try:
                delay = float(data.get("timeoutMs", 1000)) / 1000
            except (ValueError, TypeError, OverflowError):
                delay = 1.0
            # A zero/invalid interval must not turn into a busy request loop.
            if not 0.5 <= delay <= 10:
                delay = 1.0 if delay < 0.5 or delay != delay else 10.0
            return token, delay
    return None, 1.0


def _messages(actions):
    """Only new chat items; ticker copies, replacements and replay are excluded."""
    for action in actions:
        if not isinstance(action, dict):
            continue
        addition = action.get("addChatItemAction")
        if not isinstance(addition, dict):
            continue
        item = addition.get("item", {})
        if not isinstance(item, dict):
            continue
        for kind in (
            "liveChatTextMessageRenderer",
            "liveChatPaidMessageRenderer",
            "liveChatPaidStickerRenderer",
            "liveChatMembershipItemRenderer",
        ):
            renderer = item.get(kind)
            if not isinstance(renderer, dict):
                continue
            message_id = renderer.get("id")
            if not isinstance(message_id, str) or not message_id:
                # A stable ID is necessary to avoid counting retries twice.
                continue
            author = _text(renderer.get("authorName")) or renderer.get("authorExternalChannelId") or "desconhecido"
            message = _text(renderer.get("message"))
            if not message and kind == "liveChatMembershipItemRenderer":
                message = _text(renderer.get("headerSubtext")) or _text(renderer.get("headerPrimaryText"))
            if not message and kind == "liveChatPaidStickerRenderer":
                sticker = renderer.get("sticker", {})
                if isinstance(sticker, dict):
                    message = sticker.get("accessibility", {}).get("accessibilityData", {}).get("label", "")
                message = message if isinstance(message, str) else ""
            if kind in ("liveChatPaidMessageRenderer", "liveChatPaidStickerRenderer"):
                amount = _text(renderer.get("purchaseAmountText"))
                message = " ".join(part for part in (amount, message) if part)
            try:
                timestamp = int(renderer.get("timestampUsec", 0)) / 1_000_000
            except (ValueError, TypeError, OverflowError):
                timestamp = 0.0
            if message:
                yield message_id, str(author), message, timestamp


class _Seen:
    def __init__(self):
        self.ids = set()
        self.order = deque()

    def add(self, message_id):
        if message_id in self.ids:
            return False
        if len(self.order) >= _MAX_IDS:
            self.ids.remove(self.order.popleft())
        self.ids.add(message_id)
        self.order.append(message_id)
        return True


class _Log:
    def __init__(self, canal, log):
        self.prefix = f"[chat:youtube:{canal}] "
        self.log = log
        self.previous = None
        self.last = float("-inf")

    def emit(self, message):
        now = time.monotonic()
        interval = 180 if message == self.previous else 15
        if now - self.last < interval:
            return
        self.last = now
        self.previous = message
        self.log(self.prefix + message)


def _bootstrap(session, url, parada):
    with session.get(url, params={"hl": "en"}, timeout=_TIMEOUT) as response:
        response.raise_for_status()
        host = (urlsplit(response.url).hostname or "").lower()
        if host not in ("youtube.com", "www.youtube.com", "m.youtube.com"):
            raise _Unavailable("página pública indisponível ou exigindo consentimento; tentando novamente")
        html = response.text
    if parada.is_set():
        return None
    data = _page_json(html, "ytInitialData")
    player = _page_json(html, "ytInitialPlayerResponse")
    config = _page_json(html, "ytcfg")
    video = player.get("videoDetails", {})
    broadcast = player.get("microformat", {}).get("playerMicroformatRenderer", {}).get("liveBroadcastDetails", {})
    status = player.get("playabilityStatus", {}).get("status")
    if status in ("LIVE_STREAM_OFFLINE", "UNPLAYABLE", "LOGIN_REQUIRED", "ERROR"):
        raise _Unavailable("canal sem live pública disponível; aguardando transmissão")
    if broadcast.get("isLiveNow") is False or broadcast.get("endTimestamp"):
        raise _Unavailable("transmissão encerrada ou ainda não iniciada; aguardando live")
    chat = _find(data, "liveChatRenderer")
    if not chat or chat.get("isReplay") is True:
        if video.get("isLive") is True or broadcast.get("isLiveNow") is True:
            raise _Unavailable("live com chat desativado ou indisponível; tentando novamente")
        raise _Unavailable("canal sem live/chat público; aguardando transmissão")
    # A recording's chat replay must never feed live spike detection.
    if video.get("isLive") is False and broadcast.get("isLiveNow") is not True:
        raise _Unavailable("vídeo não está ao vivo; aguardando transmissão")
    # Sort-menu reload tokens navigate the chat UI; they are not API polling
    # continuations and get_live_chat rejects them with INVALID_ARGUMENT.
    token, delay = _continuation(chat)
    if not token:
        raise _Unavailable("live sem continuação de chat público; tentando novamente")
    public_client = config.get("INNERTUBE_CONTEXT", {}).get("client", {})
    client_name = public_client.get("clientName", "WEB")
    client_version = public_client.get("clientVersion") or config.get("INNERTUBE_CLIENT_VERSION")
    if not isinstance(client_version, str) or not client_version:
        raise _Unavailable("configuração pública de chat não encontrada; tentando novamente")
    # Deliberately exclude visitor/session/auth data. The public endpoint needs
    # no user-provided API key, OAuth token or copied browser credentials.
    client = {"clientName": client_name, "clientVersion": client_version, "hl": "en", "gl": "US"}
    video_id = video.get("videoId")
    if not isinstance(video_id, str):
        current = _find(data, "currentVideoEndpoint") or {}
        endpoint = current.get("watchEndpoint", {})
        video_id = endpoint.get("videoId", "") if isinstance(endpoint, dict) else ""
    if not isinstance(video_id, str):
        video_id = ""
    return video_id, {"client": client}, chat, token, delay


def iterar_youtube(canal, callback, parada, log=print):
    """Feed callback((original_canal, author, text, time.time())) until stopped.

    Public unauthenticated chat only. Offline/disabled/restricted channels are
    retried, never replayed. Requests have bounded connect/read timeouts; every
    poll/reconnect sleep is interruptible through the supplied Event.
    """
    reporter = _Log(canal, log)
    try:
        url = url_origem("youtube", canal)
    except (ValueError, TypeError):
        reporter.emit("canal/URL do YouTube inválido; chat não iniciado")
        return
    seen = _Seen()
    current_video = None
    retry = 5.0
    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": _ORIGIN,
        })
        while not parada.is_set():
            try:
                baseline = time.time()
                state = _bootstrap(session, url, parada)
                if state is None or parada.is_set():
                    return
                video_id, context, initial, token, delay = state
                if video_id != current_video:
                    seen = _Seen()
                    current_video = video_id
                for message_id, _, _, _ in _messages(initial.get("actions", [])):
                    seen.add(message_id)
                warmup = True
                reporter.emit("conectado ao chat público (histórico ignorado)")
                while token and not parada.is_set():
                    if parada.wait(delay):
                        return
                    with session.post(
                        _ENDPOINT,
                        params={"prettyPrint": "false"},
                        json={"context": context, "continuation": token},
                        headers={"Referer": _ORIGIN + "/watch?v=" + video_id} if video_id else {"Referer": url},
                        timeout=_TIMEOUT,
                    ) as response:
                        response.raise_for_status()
                        payload = response.json()
                    if parada.is_set():
                        return
                    if not isinstance(payload, dict):
                        raise _Unavailable("resposta de chat inválida; reconectando")
                    continuation = payload.get("continuationContents", {}).get("liveChatContinuation")
                    if not isinstance(continuation, dict) or continuation.get("isReplay") is True:
                        raise _Unavailable("chat encerrado ou indisponível; buscando nova live")
                    now = time.time()
                    for message_id, author, text, timestamp in _messages(continuation.get("actions", [])):
                        if parada.is_set():
                            return
                        if not seen.add(message_id):
                            continue
                        # First response may carry the entire visible history.
                        # Server timestamps are only a freshness guard; detector
                        # timestamps always use receipt time, as Twitch/Kick do.
                        if warmup or (timestamp and (timestamp <= baseline or timestamp < now - 30)):
                            continue
                        try:
                            callback((canal, author, text, time.time()))
                        except Exception as exc:
                            reporter.emit(f"callback falhou ({type(exc).__name__}); leitura continua")
                    warmup = False
                    retry = 5.0
                    token, delay = _continuation(continuation)
                if not parada.is_set():
                    reporter.emit("chat sem continuação; buscando nova live")
                retry = 5.0
            except _Unavailable as exc:
                if not parada.is_set():
                    reporter.emit(str(exc))
                retry = 60.0
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else "?"
                if not parada.is_set():
                    reporter.emit(f"HTTP {code} no chat público; reconectando")
                retry = min(60.0, retry * 2)
            except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError) as exc:
                # Do not log exception strings: requests URLs may contain opaque
                # public continuation tokens and page bodies are not log data.
                if not parada.is_set():
                    reporter.emit(f"falha de leitura ({type(exc).__name__}); reconectando")
                retry = min(60.0, retry * 2)
            if parada.wait(retry):
                return
