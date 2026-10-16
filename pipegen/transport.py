"""Message bus: real MQTT (paho) for deployment, an in-process bus for the simulator and tests.
Both carry the same topics and JSON payloads."""

from __future__ import annotations

import json
import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

Handler = Callable[[str, dict], None]


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT wildcard match (+ = one level, # = rest)."""
    p, t = pattern.split("/"), topic.split("/")
    for i, part in enumerate(p):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(p) == len(t)


def filter_covers(a: str, b: str) -> bool:
    """True if every topic matched by filter `b` is also matched by filter `a`."""
    return topic_matches(a, b)  # b's wildcards are compared as literal levels, which is exactly coverage


class InprocBus:
    """Synchronous broker in one process. Retained messages are replayed to new subscribers."""

    def __init__(self) -> None:
        self._subs: list[tuple[str, Handler]] = []
        self._retained: dict[str, dict] = {}
        self.tap: list[Callable[[str, dict, bool], None]] = []  # observers of every publish

    def publish(self, topic: str, payload: dict, qos: int = 1, retain: bool = False) -> None:
        payload = json.loads(json.dumps(payload))  # same serialisation boundary as MQTT
        if retain:
            self._retained[topic] = payload
        for observer in self.tap:
            observer(topic, payload, retain)
        for pattern, handler in list(self._subs):
            if topic_matches(pattern, topic):
                handler(topic, payload)

    def subscribe(self, pattern: str, handler: Handler, qos: int = 1) -> None:
        self._subs.append((pattern, handler))
        for t, p in list(self._retained.items()):
            if topic_matches(pattern, t):
                handler(t, p)

    def drain(self) -> None:
        """Nothing to do: delivery is synchronous."""

    def close(self) -> None:
        self._subs.clear()


class MqttBus:
    """paho-mqtt v2 client with automatic reconnect and re-subscription.

    queued=False: handlers run on paho's network thread (PipeGen: handlers only store state).
    queued=True:  messages wait in a queue until the owner calls drain() from its own loop,
                  so single-threaded code (the simulator's state machines) is never re-entered.
    """

    def __init__(self, host: str, port: int = 1883, username: str | None = None, password: str | None = None,
                 tls: bool = False, client_id: str = "", will: tuple[str, dict] | None = None,
                 queued: bool = False) -> None:
        import queue

        import paho.mqtt.client as mqtt

        self._mqtt = mqtt
        self._queue: queue.SimpleQueue | None = queue.SimpleQueue() if queued else None
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username:
            self._client.username_pw_set(username, password)
        if tls:
            self._client.tls_set()
        if will:
            self._client.will_set(will[0], json.dumps(will[1]), qos=1, retain=True)
        self._subs: list[tuple[str, Handler, int]] = []
        # Filters actually subscribed at the broker. Overlapping filters are collapsed, because
        # some brokers (amqtt) deliver one copy per matching subscription; handlers are matched locally.
        self._broker_filters: set[str] = set()
        self._lock = threading.Lock()
        self.connected = threading.Event()
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(1, 10)
        self._client.connect_async(host, port, keepalive=15)
        self._client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            log.error("MQTT connect failed: %s", reason_code)
            return
        log.info("MQTT connected")
        with self._lock:
            for pattern in self._broker_filters:
                client.subscribe(pattern, 1)
        self.connected.set()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        self.connected.clear()
        log.warning("MQTT disconnected: %s", reason_code)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("non-JSON message on %s ignored", msg.topic)
            return
        if self._queue is not None:
            self._queue.put((msg.topic, payload))
            return
        self._dispatch(msg.topic, payload)

    def _dispatch(self, topic: str, payload: dict) -> None:
        with self._lock:
            handlers = [h for pattern, h, _ in self._subs if topic_matches(pattern, topic)]
        for h in handlers:
            try:
                h(topic, payload)
            except Exception:  # a bad handler must not kill the network thread
                log.exception("handler failed for %s", topic)

    def drain(self, timeout: float = 0.0) -> int:
        """Deliver queued messages on the caller's thread; returns how many were delivered."""
        import queue

        if self._queue is None:
            return 0
        n = 0
        try:
            item = self._queue.get(timeout=timeout) if timeout else self._queue.get_nowait()
            while True:
                self._dispatch(*item)
                n += 1
                item = self._queue.get_nowait()
        except queue.Empty:
            return n

    def publish(self, topic: str, payload: dict, qos: int = 1, retain: bool = False) -> None:
        self._client.publish(topic, json.dumps(payload, separators=(",", ":")), qos=qos, retain=retain)

    def subscribe(self, pattern: str, handler: Handler, qos: int = 1) -> None:
        with self._lock:
            self._subs.append((pattern, handler, qos))
            if any(filter_covers(f, pattern) for f in self._broker_filters):
                return  # already delivered through a wider broker subscription
            covered = {f for f in self._broker_filters if filter_covers(pattern, f)}
            self._broker_filters -= covered
            self._broker_filters.add(pattern)
        if self.connected.is_set():
            for f in covered:
                self._client.unsubscribe(f)
            self._client.subscribe(pattern, 1)

    def wait_connected(self, timeout: float = 10.0) -> bool:
        return self.connected.wait(timeout)

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
