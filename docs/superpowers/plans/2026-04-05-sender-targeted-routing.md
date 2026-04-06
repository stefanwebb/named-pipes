# Sender-Targeted Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route server responses only to the message sender (identified by PID) rather than broadcasting to all subscribers, while retaining an explicit `broadcast_message` / `broadcast_data` API for server-initiated notifications.

**Architecture:** Explicit pid threading throughout — `msg_handler_fn` and `data_handler_fn` gain a `pid: int | None` parameter; `send_message` / `send_data` gain `pid` parameters for targeted delivery; `broadcast_message` / `broadcast_data` send to all. Upstream data frames gain a 4-byte PID prefix so the server can identify the data sender.

**Tech Stack:** Python 3.12, named pipes (os.mkfifo), threading, struct, unittest + pytest. Activate conda env `named-pipes` before running any commands.

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `src/named_pipes/text_named_pipe.py` | Modify | `send_message(pid)`, `broadcast_message`, listener passes pid |
| `src/named_pipes/data_named_pipe.py` | Modify | Wire format, `recv_data` → tuple, `send_data(pid)`, `broadcast_data`, client write fd |
| `src/named_pipes/tool_named_pipe.py` | Modify | `send_response(pid)`, `msg_handler_fn(pid)`, `_dispatch(pid)`, exit uses broadcast |
| `src/named_pipes/basic_named_pipe.py` | Modify | `msg_handler_fn(pid)`, `data_handler_fn(pid)`, `dispatch(pid)`, `send_message(pid)` |
| `src/named_pipes/chat_named_pipe.py` | Modify | `on_chat(msg, pid)` passes pid to `send_response` |
| `src/ex_basic_pipe/server.py` | Modify | All handler signatures gain `pid`, pass `pid` to `send_message` |
| `src/ex_basic_pipe/client.py` | Modify | All handler signatures gain `pid` |
| `src/ex_chat_pipe/client.py` | Modify | `msg_handler_fn(msg, pid)` signature |
| `tests/test_tool_named_pipe.py` | Modify | Assertions match new pid-threaded signatures |
| `tests/test_basic_named_pipe.py` | Modify | Assertions match new pid-threaded signatures |
| `tests/test_chat_named_pipe.py` | Modify | Handler called with pid, `send_response` asserted with pid |
| `named-pipe-tools.md` | Modify | Protocol rules updated for targeted routing |

---

## Task 1: TextNamedPipe and ToolNamedPipe — update tests then implement

**Files:**
- Modify: `tests/test_tool_named_pipe.py`
- Modify: `src/named_pipes/text_named_pipe.py`
- Modify: `src/named_pipes/tool_named_pipe.py`

- [ ] **Step 1: Update test_tool_named_pipe.py to expect pid-threaded signatures**

Replace the entire contents of `tests/test_tool_named_pipe.py` with:

```python
"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Unit tests for tool_named_pipe.ToolNamedPipe (no real FIFOs created).
"""

import json
from unittest.mock import MagicMock, patch

from named_pipes import text_named_pipe
from named_pipes.tool_named_pipe import ToolNamedPipe


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_tool(**kwargs):
    """Return a ToolNamedPipe with all filesystem calls patched out."""
    defaults = {"description": "A test tool", "help_text": "Test help text"}
    defaults.update(kwargs)
    with (
        patch.object(text_named_pipe, "ensure_pipe"),
        patch.object(text_named_pipe.os, "pipe", return_value=(10, 11)),
        patch.object(text_named_pipe.os, "open", return_value=3),
        patch.object(text_named_pipe.os, "fdopen", return_value=MagicMock()),
    ):
        tool = ToolNamedPipe("test-tool", **defaults)
    return tool


# ---------------------------------------------------------------------------
# TestPipePath
# ---------------------------------------------------------------------------


class TestPipePath:
    def test_pipe_name_derived_from_tool_name(self):
        tool = make_tool()
        assert tool._pipe_name == "/tmp/tool-test-tool"


# ---------------------------------------------------------------------------
# TestHandlerDecorator
# ---------------------------------------------------------------------------


class TestHandlerDecorator:
    def test_registers_handler_lowercase(self):
        tool = make_tool()

        @tool.handler("echo")
        def on_echo(msg, pid):
            pass

        assert "echo" in tool._handlers

    def test_returns_original_function(self):
        tool = make_tool()

        def on_echo(msg, pid):
            pass

        result = tool.handler("echo")(on_echo)
        assert result is on_echo


# ---------------------------------------------------------------------------
# TestProtocolCommands
# ---------------------------------------------------------------------------


class TestProtocolCommands:
    def test_subscribe(self):
        tool = make_tool()
        tool.subscribe = MagicMock()
        tool.send_response = MagicMock()

        tool.msg_handler_fn({"cmd": "subscribe", "pid": 1234}, 1234)

        tool.subscribe.assert_called_once_with(1234)
        tool.send_response.assert_called_once_with("subscribed", 1234)

    def test_unsubscribe(self):
        tool = make_tool()
        tool.unsubscribe = MagicMock()

        tool.msg_handler_fn({"cmd": "unsubscribe", "pid": 1234}, 1234)

        tool.unsubscribe.assert_called_once_with(1234)

    def test_description(self):
        tool = make_tool(description="My cool tool")
        tool.send_response = MagicMock()

        tool.msg_handler_fn({"cmd": "description", "pid": 1}, 1)

        tool.send_response.assert_called_once_with("My cool tool", 1)

    def test_help(self):
        tool = make_tool(help_text="Use me like this")
        tool.send_response = MagicMock()

        tool.msg_handler_fn({"cmd": "help", "pid": 1}, 1)

        tool.send_response.assert_called_once_with("Use me like this", 1)

    def test_exit(self):
        tool = make_tool()
        tool.broadcast_message = MagicMock()
        tool.stop = MagicMock()

        tool.msg_handler_fn({"cmd": "exit", "pid": 1}, 1)

        tool.broadcast_message.assert_called_once_with(
            json.dumps({"result": "exiting"})
        )
        tool.stop.assert_called_once()

    def test_unknown_command(self):
        tool = make_tool()
        tool.send_response = MagicMock()

        tool.msg_handler_fn({"cmd": "nosuch", "pid": 1}, 1)

        tool.send_response.assert_called_once_with("unknown command 'nosuch'", 1)


# ---------------------------------------------------------------------------
# TestCustomDispatch
# ---------------------------------------------------------------------------


class TestCustomDispatch:
    def test_custom_handler_called_with_msg_and_pid(self):
        tool = make_tool()
        mock_handler = MagicMock()
        tool._handlers["echo"] = mock_handler

        msg = {"cmd": "echo", "pid": 1, "text": "hello"}
        tool.msg_handler_fn(msg, 1)

        mock_handler.assert_called_once_with(msg, 1)


# ---------------------------------------------------------------------------
# TestSendHelpers
# ---------------------------------------------------------------------------


class TestSendHelpers:
    def test_send_response_targeted(self):
        tool = make_tool()
        tool.send_message = MagicMock()

        tool.send_response("ok", 42)

        tool.send_message.assert_called_once_with(json.dumps({"result": "ok"}), 42)

    def test_send_response_broadcast(self):
        tool = make_tool()
        tool.send_message = MagicMock()

        tool.send_response("ok")

        tool.send_message.assert_called_once_with(json.dumps({"result": "ok"}), None)

    def test_send_command(self):
        tool = make_tool()
        tool.send_message = MagicMock()
        tool._pid = 42

        tool.send_command("ping")

        tool.send_message.assert_called_once_with(
            json.dumps({"pid": 42, "cmd": "ping"})
        )
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
conda run -n named-pipes pytest tests/test_tool_named_pipe.py -v
```

Expected: multiple FAILED (wrong number of arguments to `msg_handler_fn`, `send_response`, etc.)

- [ ] **Step 3: Update TextNamedPipe**

Replace `src/named_pipes/text_named_pipe.py` with:

```python
"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import json
import os
import select
import threading
from abc import ABC, abstractmethod
from enum import Enum

from named_pipes.utils import ensure_pipe, remove_pipe


class Role(Enum):
    SERVER = "server"
    CLIENT = "client"


class TextNamedPipe(ABC):
    """Base class for text/message named-pipe IPC.

    Servers open a single upstream pipe for receiving and use subscribe()
    to add downstream pipes (keyed by pid) for broadcasting replies.

    Clients open a single downstream pipe for receiving.

    Pipe paths:
        <pipe_name>                           client -> server  (one, shared)
        <pipe_name>-<pid>                     server -> client  (one per subscriber)
    """

    def __init__(
        self,
        pipe_name: str = "/tmp/pipe",
        role: Role = Role.SERVER,
        pid: int | None = None,
    ):
        self._role = role
        self._pid = pid if pid is not None else os.getpid()
        self._text_stop_r, self._text_stop_w = os.pipe()
        self._text_listener_thread: threading.Thread | None = None

        self._closed = False
        self._pipe_name = pipe_name
        if role is Role.SERVER:
            ensure_pipe(pipe_name)
            self._msg_recv = os.fdopen(os.open(pipe_name, os.O_RDWR), "r", buffering=1)
            self._owned_pipes = [pipe_name]
            self._subscribers: dict[int, tuple[str, object]] = {}
        else:
            downstream = f"{pipe_name}-{self._pid}"
            ensure_pipe(downstream)
            self._msg_recv = os.fdopen(os.open(downstream, os.O_RDWR), "r", buffering=1)
            self._msg_send = os.fdopen(os.open(pipe_name, os.O_RDWR), "w", buffering=1)
            self._owned_pipes = [downstream]

    # --- subscribe / unsubscribe (server only) ---

    def subscribe(self, pid: int, filepath: str | None = None):
        """Add a downstream pipe for *pid*.  Opens ``<filepath>-<pid>``."""
        if self._role is not Role.SERVER:
            raise RuntimeError("subscribe is only available on servers")
        path = f"{filepath or self._pipe_name}-{pid}"
        ensure_pipe(path)
        f = os.fdopen(os.open(path, os.O_RDWR), "w", buffering=1)
        self._subscribers[pid] = (path, f)

    def unsubscribe(self, pid: int):
        """Close the downstream pipe for *pid* on the server side."""
        if self._role is not Role.SERVER:
            raise RuntimeError("unsubscribe is only available on servers")
        _, f = self._subscribers.pop(pid)
        f.close()

    # --- message pipe ---

    def recv_message(self) -> dict:
        line = self._msg_recv.readline().rstrip("\n")
        return json.loads(line)

    def send_message(self, data: str, pid: int | None = None):
        """Send *data* to one subscriber (*pid* given) or all subscribers (*pid* = None).

        On the client side the *pid* parameter is ignored and the message is
        written to the upstream pipe.
        """
        if self._role is Role.SERVER:
            if pid is None:
                for _, f in self._subscribers.values():
                    f.write(data + "\n")
                    f.flush()
            else:
                _, f = self._subscribers[pid]
                f.write(data + "\n")
                f.flush()
        else:
            self._msg_send.write(data + "\n")
            self._msg_send.flush()

    def broadcast_message(self, data: str):
        """Send *data* to all subscribers (server only convenience alias)."""
        self.send_message(data, pid=None)

    # --- abstract handler ---

    @abstractmethod
    def msg_handler_fn(self, msg: dict, pid: int | None):
        """Called for each incoming message.

        *pid* is the sender's process ID extracted from the message (server
        side) or ``None`` when receiving a server response on the client side.
        """

    # --- listen loop ---

    def stop(self):
        """Unblock the listen() loop."""
        os.write(self._text_stop_w, b"\x00")

    def listen(self) -> threading.Event:
        """Start a background thread that dispatches messages until stop().

        Returns a threading.Event that is set when the listener thread exits.
        """
        done = threading.Event()

        def _msg_loop():
            try:
                while True:
                    readable, _, _ = select.select(
                        [self._msg_recv, self._text_stop_r], [], []
                    )
                    if self._text_stop_r in readable:
                        break
                    msg = self.recv_message()
                    if not msg:
                        continue
                    pid = msg.get("pid")
                    self.msg_handler_fn(msg, pid)
            finally:
                done.set()

        self._text_listener_thread = threading.Thread(target=_msg_loop, daemon=True)
        self._text_listener_thread.start()
        return done

    def _close(self):
        if self._closed:
            return
        self._closed = True
        self.stop()
        if self._text_listener_thread is not None:
            self._text_listener_thread.join()
            self._text_listener_thread = None
        self._msg_recv.close()
        if self._role is Role.SERVER:
            for pid in list(self._subscribers):
                self.unsubscribe(pid)
        else:
            self._msg_send.close()
        for fd in (self._text_stop_r, self._text_stop_w):
            try:
                os.close(fd)
            except OSError:
                pass
        for path in self._owned_pipes:
            remove_pipe(path)

    def __del__(self):
        self._close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close()
```

- [ ] **Step 4: Update ToolNamedPipe**

Replace `src/named_pipes/tool_named_pipe.py` with:

```python
"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

ToolNamedPipe — implements the Named Pipe Tools protocol.

See named-pipe-tools.md for the full specification.
"""

import json
from pathlib import Path

from named_pipes.text_named_pipe import TextNamedPipe, Role


class ToolNamedPipe(TextNamedPipe):
    """A named-pipe tool that follows the Named Pipe Tools protocol.

    Server (tool) side:
        Listens on ``/tmp/tool-{name}`` for JSON commands from clients.
        Automatically handles ``subscribe``, ``unsubscribe``, ``description``,
        ``help``, and ``exit``.  Custom commands are registered with the
        ``@tool.handler("CMD")`` decorator.

    Client side:
        Creates its downstream pipe at ``/tmp/tool-{name}-{pid}`` and provides
        ``send_command`` / ``send_response`` helpers.
    """

    def __init__(
        self,
        name: str,
        role: Role = Role.SERVER,
        *,
        description: str,
        help_text: str | None = None,
    ):
        pipe_name = f"/tmp/tool-{name}"
        super().__init__(pipe_name, role)
        self._tool_name = name
        self._description = description
        if help_text is None:
            skill_md = Path.cwd() / "SKILL.md"
            help_text = skill_md.read_text() if skill_md.exists() else description
        self._help_text = help_text
        self._handlers: dict[str, callable] = {}

    # --- decorator for custom commands ---

    def handler(self, cmd: str):
        """Decorator that registers a function as the handler for *cmd*.

        The registered function must accept ``(msg: dict, pid: int | None)``.
        """

        def decorator(fn):
            self._handlers[cmd.lower()] = fn
            return fn

        return decorator

    # --- sending helpers ---

    def send_response(self, result: str, pid: int | None = None):
        """Send ``{"result": ...}`` to *pid* (or broadcast if *pid* is None)."""
        self.send_message(json.dumps({"result": result}), pid)

    def send_command(self, cmd: str):
        """Send ``{"pid": ..., "cmd": ...}`` upstream (client only)."""
        self.send_message(json.dumps({"pid": self._pid, "cmd": cmd}))

    # --- protocol message handler ---

    def msg_handler_fn(self, msg: dict, pid: int | None):
        cmd = msg.get("cmd", "").lower()

        match cmd:
            case "subscribe":
                self.subscribe(pid)
                self.send_response("subscribed", pid)

            case "unsubscribe":
                self.unsubscribe(pid)
                # No response per protocol spec

            case "description":
                self.send_response(self._description, pid)

            case "help":
                self.send_response(self._help_text, pid)

            case "exit":
                self.broadcast_message(json.dumps({"result": "exiting"}))
                self.stop()

            case _:
                self._dispatch(cmd, msg, pid)

    def _dispatch(self, cmd: str, msg: dict, pid: int | None):
        fn = self._handlers.get(cmd)
        if fn:
            fn(msg, pid)
        else:
            self.send_response(f"unknown command '{cmd}'", pid)

    # --- context manager ---

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close()
```

- [ ] **Step 5: Run tests and confirm they pass**

```bash
conda run -n named-pipes pytest tests/test_tool_named_pipe.py -v
```

Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add src/named_pipes/text_named_pipe.py src/named_pipes/tool_named_pipe.py tests/test_tool_named_pipe.py
git commit -m "feat: thread pid through TextNamedPipe and ToolNamedPipe for targeted routing"
```

---

## Task 2: DataNamedPipe and BasicPipeChannel — update wire format and signatures

**Files:**
- Modify: `src/named_pipes/data_named_pipe.py`
- Modify: `src/named_pipes/basic_named_pipe.py`
- Modify: `tests/test_basic_named_pipe.py`

- [ ] **Step 1: Update DataNamedPipe**

Replace `src/named_pipes/data_named_pipe.py` with:

```python
"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import os
import select
import struct
import threading
from abc import ABC, abstractmethod

from named_pipes.text_named_pipe import Role
from named_pipes.utils import ensure_pipe, remove_pipe


class DataNamedPipe(ABC):
    """Base class for binary data named-pipe IPC.

    Upstream wire format (client → server):
        [4-byte PID big-endian][4-byte length big-endian][payload]

    Downstream wire format (server → client):
        [4-byte length big-endian][payload]  (unchanged)

    Servers open a single upstream pipe for receiving and use subscribe()
    to add downstream pipes (keyed by pid) for targeted or broadcast data.

    Clients open a downstream pipe for receiving and an upstream pipe for
    sending (with automatic PID prepending).

    Pipe paths:
        <pipe_name>                           client -> server  (one, shared)
        <pipe_name>-<pid>                     server -> client  (one per subscriber)
    """

    def __init__(
        self,
        pipe_name: str = "/tmp/pipe_data",
        role: Role = Role.SERVER,
        pid: int | None = None,
    ):
        self._data_role = role
        self._pid = pid if pid is not None else os.getpid()
        self._data_stop_r, self._data_stop_w = os.pipe()
        self._data_listener_thread: threading.Thread | None = None

        self._data_closed = False
        self._data_pipe_name = pipe_name
        if role is Role.SERVER:
            ensure_pipe(pipe_name)
            self._data_recv = os.fdopen(
                os.open(pipe_name, os.O_RDWR), "rb", buffering=0
            )
            self._data_owned_pipes = [pipe_name]
            self._data_subscribers: dict[int, tuple[str, object]] = {}
        else:
            downstream = f"{pipe_name}-{self._pid}"
            ensure_pipe(downstream)
            self._data_recv = os.fdopen(
                os.open(downstream, os.O_RDWR), "rb", buffering=0
            )
            self._data_send = os.fdopen(
                os.open(pipe_name, os.O_RDWR), "wb", buffering=0
            )
            self._data_owned_pipes = [downstream]

    # --- subscribe / unsubscribe (server only) ---

    def subscribe(self, pid: int, filepath: str | None = None):
        """Add a downstream pipe for *pid*.  Opens ``<filepath>-<pid>``."""
        if self._data_role is not Role.SERVER:
            raise RuntimeError("subscribe is only available on servers")
        path = f"{filepath or self._data_pipe_name}-{pid}"
        ensure_pipe(path)
        f = os.fdopen(os.open(path, os.O_RDWR), "wb", buffering=0)
        self._data_subscribers[pid] = (path, f)

    def unsubscribe(self, pid: int):
        """Remove the downstream pipe for *pid* and clean up."""
        if self._data_role is not Role.SERVER:
            raise RuntimeError("unsubscribe is only available on servers")
        path, f = self._data_subscribers.pop(pid)
        f.close()
        remove_pipe(path)

    # --- data pipe ---

    def recv_data(self) -> tuple[int | None, bytes]:
        """Read one data frame.

        Server: reads ``[4-byte PID][4-byte length][payload]``; returns ``(pid, payload)``.
        Client: reads ``[4-byte length][payload]``; returns ``(None, payload)``.
        """
        if self._data_role is Role.SERVER:
            (pid,) = struct.unpack(">I", self._data_recv.read(4))
            (length,) = struct.unpack(">I", self._data_recv.read(4))
            return pid, self._data_recv.read(length)
        else:
            (length,) = struct.unpack(">I", self._data_recv.read(4))
            return None, self._data_recv.read(length)

    def send_data(self, data: bytes, pid: int | None = None):
        """Send *data* to one subscriber (*pid* given) or upstream (client).

        Server with pid: send length-prefixed frame to that subscriber.
        Server with pid=None: broadcast to all subscribers.
        Client: prepend own PID then send upstream.
        """
        if self._data_role is Role.SERVER:
            if pid is None:
                for _, f in self._data_subscribers.values():
                    f.write(struct.pack(">I", len(data)))
                    f.write(data)
                    f.flush()
            else:
                _, f = self._data_subscribers[pid]
                f.write(struct.pack(">I", len(data)))
                f.write(data)
                f.flush()
        else:
            self._data_send.write(struct.pack(">II", self._pid, len(data)))
            self._data_send.write(data)
            self._data_send.flush()

    def broadcast_data(self, data: bytes):
        """Send *data* to all subscribers (server only convenience alias)."""
        self.send_data(data, pid=None)

    # --- abstract handler ---

    @abstractmethod
    def data_handler_fn(self, data: bytes, pid: int | None):
        """Called for each incoming data payload.

        *pid* is the sender's PID (server side) or ``None`` (client side).
        """

    # --- listen loop ---

    def stop_data(self):
        """Unblock the listen_data() loop."""
        os.write(self._data_stop_w, b"\x00")

    def listen_data(self) -> threading.Event:
        """Start a background thread that dispatches data until stop_data().

        Returns a threading.Event that is set when the listener thread exits.
        """
        done = threading.Event()

        def _data_loop():
            try:
                while True:
                    readable, _, _ = select.select(
                        [self._data_recv, self._data_stop_r], [], []
                    )
                    if self._data_stop_r in readable:
                        break
                    pid, data = self.recv_data()
                    self.data_handler_fn(data, pid)
            finally:
                done.set()

        self._data_listener_thread = threading.Thread(target=_data_loop, daemon=True)
        self._data_listener_thread.start()
        return done

    def _close_data(self):
        if self._data_closed:
            return
        self._data_closed = True
        self.stop_data()
        if self._data_listener_thread is not None:
            self._data_listener_thread.join()
            self._data_listener_thread = None
        self._data_recv.close()
        if self._data_role is Role.SERVER:
            for pid in list(self._data_subscribers):
                self.unsubscribe(pid)
        else:
            self._data_send.close()
        for fd in (self._data_stop_r, self._data_stop_w):
            try:
                os.close(fd)
            except OSError:
                pass
        for path in self._data_owned_pipes:
            remove_pipe(path)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close_data()
```

- [ ] **Step 2: Update BasicPipeChannel**

Replace `src/named_pipes/basic_named_pipe.py` with:

```python
"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import json
import threading

from named_pipes.data_named_pipe import DataNamedPipe
from named_pipes.text_named_pipe import TextNamedPipe
from named_pipes.text_named_pipe import Role


class BasicPipeChannel(TextNamedPipe, DataNamedPipe):
    """Concrete PipeChannel with decorator-based handler registration.

    Use ``@ch.handler("<CMD>")`` to register a function for a named command
    and ``@ch.data_handler`` to register a function for incoming data payloads.

    Registered command handlers must accept ``(msg: dict, pid: int | None)``.
    The data handler must accept ``(data: bytes, pid: int | None)``.
    """

    def __init__(self, pipe_name: str = "/tmp/basic_pipe", role: Role = Role.SERVER):
        TextNamedPipe.__init__(self, pipe_name, role)
        DataNamedPipe.__init__(self, pipe_name + "_data", role)
        self._handlers: dict[str, callable] = {}
        self._data_handler_fn_impl: callable | None = None

    def handler(self, cmd: str):
        """Decorator that registers a function as the handler for `cmd`."""

        def decorator(fn):
            self._handlers[cmd.upper()] = fn
            return fn

        return decorator

    def data_handler(self, fn):
        """Decorator that registers a function as the handler for incoming data payloads."""
        self._data_handler_fn_impl = fn
        return fn

    def subscribe(self, pid: int):
        TextNamedPipe.subscribe(self, pid)
        DataNamedPipe.subscribe(self, pid)

    def unsubscribe(self, pid: int):
        TextNamedPipe.unsubscribe(self, pid)
        DataNamedPipe.unsubscribe(self, pid)

    def send_message(self, cmd: str, data: str = "", pid: int | None = None):
        msg = {"cmd": cmd, "data": data, "pid": self._pid}
        TextNamedPipe.send_message(self, json.dumps(msg), pid)

    def msg_handler_fn(self, msg: dict, pid: int | None):
        if msg["cmd"].upper() == "QUIT":
            self.send_message("BYE", pid=pid)
            print("Quit received. Shutting down.")
            self.stop()
        else:
            self.dispatch(msg, pid)

    def data_handler_fn(self, data: bytes, pid: int | None):
        if self._data_handler_fn_impl is not None:
            self._data_handler_fn_impl(data, pid)

    def dispatch(self, msg: dict, pid: int | None):
        cmd = msg["cmd"].upper()
        fn = self._handlers.get(cmd)
        if fn:
            fn(msg, pid)
        else:
            self.send_message("ERROR", f"unknown command '{cmd}'", pid=pid)

    def stop(self):
        TextNamedPipe.stop(self)
        DataNamedPipe.stop_data(self)

    def listen(self) -> threading.Event:
        """Start background threads for both text and data pipes.

        Returns a threading.Event that is set when both listener threads have exited.
        """
        text_done = TextNamedPipe.listen(self)
        data_done = DataNamedPipe.listen_data(self)

        done = threading.Event()

        def _wait_both():
            text_done.wait()
            data_done.wait()
            done.set()

        threading.Thread(target=_wait_both, daemon=True).start()
        return done

    def _close(self):
        TextNamedPipe._close(self)
        DataNamedPipe._close_data(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close()
```

- [ ] **Step 3: Update test_basic_named_pipe.py to match new signatures**

Replace the entire contents of `tests/test_basic_named_pipe.py` with:

```python
"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Unit tests for basic_named_pipe.BasicPipeChannel (no real FIFOs created).
"""

from unittest.mock import MagicMock, patch

from named_pipes import text_named_pipe, data_named_pipe
from named_pipes.basic_named_pipe import BasicPipeChannel


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_channel():
    """Return a BasicPipeChannel with all filesystem calls patched out."""
    with (
        patch.object(text_named_pipe, "ensure_pipe"),
        patch.object(data_named_pipe, "ensure_pipe"),
        patch.object(text_named_pipe.os, "pipe", return_value=(10, 11)),
        patch.object(text_named_pipe.os, "open", return_value=3),
        patch.object(text_named_pipe.os, "fdopen", return_value=MagicMock()),
    ):
        ch = BasicPipeChannel("/tmp/test-pipe")
    return ch


# ---------------------------------------------------------------------------
# TestHandlerDecorator
# ---------------------------------------------------------------------------


class TestHandlerDecorator:
    def test_registers_handler(self):
        ch = make_channel()

        @ch.handler("ECHO")
        def on_echo(msg, pid):
            pass

        assert "ECHO" in ch._handlers

    def test_registers_multiple_handlers(self):
        ch = make_channel()

        @ch.handler("FOO")
        def on_foo(msg, pid):
            pass

        @ch.handler("BAR")
        def on_bar(msg, pid):
            pass

        assert "FOO" in ch._handlers
        assert "BAR" in ch._handlers

    def test_returns_original_function(self):
        ch = make_channel()

        def on_ping(msg, pid):
            return "pong"

        result = ch.handler("PING")(on_ping)
        assert result is on_ping


# ---------------------------------------------------------------------------
# TestDataHandlerDecorator
# ---------------------------------------------------------------------------


class TestDataHandlerDecorator:
    def test_registers_data_handler(self):
        ch = make_channel()

        @ch.data_handler
        def on_data(data, pid):
            pass

        assert ch._data_handler_fn_impl is on_data

    def test_data_handler_fn_calls_impl(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._data_handler_fn_impl = mock_handler

        ch.data_handler_fn(b"hello", None)

        mock_handler.assert_called_once_with(b"hello", None)

    def test_data_handler_fn_with_pid(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._data_handler_fn_impl = mock_handler

        ch.data_handler_fn(b"hello", 1234)

        mock_handler.assert_called_once_with(b"hello", 1234)

    def test_data_handler_fn_noop_when_no_impl(self):
        ch = make_channel()
        ch.data_handler_fn(b"hello", None)  # should not raise


# ---------------------------------------------------------------------------
# TestDispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_calls_registered_handler_with_msg_and_pid(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._handlers["ECHO"] = mock_handler

        msg = {"cmd": "ECHO", "data": "hello"}
        ch.dispatch(msg, 42)

        mock_handler.assert_called_once_with(msg, 42)

    def test_dispatch_case_insensitive(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._handlers["PING"] = mock_handler

        msg = {"cmd": "ping", "data": ""}
        ch.dispatch(msg, 99)

        mock_handler.assert_called_once_with(msg, 99)

    def test_dispatch_unknown_sends_error(self):
        ch = make_channel()
        ch.send_message = MagicMock()

        ch.dispatch({"cmd": "UNKNOWN", "data": ""}, None)

        ch.send_message.assert_called_once_with(
            "ERROR", "unknown command 'UNKNOWN'", pid=None
        )


# ---------------------------------------------------------------------------
# TestMsgHandlerFn
# ---------------------------------------------------------------------------


class TestMsgHandlerFn:
    def test_quit_sends_bye_and_stops(self):
        ch = make_channel()
        ch.send_message = MagicMock()
        ch.stop = MagicMock()

        ch.msg_handler_fn({"cmd": "QUIT", "data": ""}, None)

        ch.send_message.assert_called_once_with("BYE", pid=None)
        ch.stop.assert_called_once()

    def test_non_quit_dispatches_to_handler(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._handlers["PING"] = mock_handler

        msg = {"cmd": "PING", "data": ""}
        ch.msg_handler_fn(msg, 77)

        mock_handler.assert_called_once_with(msg, 77)
```

- [ ] **Step 4: Run all tests**

```bash
conda run -n named-pipes pytest tests/test_basic_named_pipe.py tests/test_tool_named_pipe.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add src/named_pipes/data_named_pipe.py src/named_pipes/basic_named_pipe.py tests/test_basic_named_pipe.py
git commit -m "feat: thread pid through DataNamedPipe and BasicPipeChannel; add upstream PID wire prefix"
```

---

## Task 3: ChatNamedPipe — update handler and tests

**Files:**
- Modify: `tests/test_chat_named_pipe.py`
- Modify: `src/named_pipes/chat_named_pipe.py`

- [ ] **Step 1: Update test_chat_named_pipe.py**

Replace the entire contents of `tests/test_chat_named_pipe.py` with:

```python
"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Unit tests for chat_named_pipe.ChatNamedPipe (backends stubbed, no real FIFOs).
"""

import sys
from unittest.mock import MagicMock, patch

from named_pipes import text_named_pipe

# Stub vllm before importing ChatNamedPipe
mock_vllm = MagicMock()
sys.modules.setdefault("vllm", mock_vllm)

from named_pipes.chat_named_pipe import ChatNamedPipe, Backend  # noqa: E402


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_chat_pipe(backend=Backend.VLLM, reply="Hello!", **kwargs):
    """Return a ChatNamedPipe with filesystem and backend calls patched."""
    if backend is Backend.VLLM:
        mock_output = MagicMock()
        mock_output.outputs[0].text = reply
        mock_vllm.LLM.return_value.chat.return_value = [mock_output]

    defaults = {"description": "A chat tool", "help_text": "Chat help"}
    defaults.update(kwargs)

    with (
        patch.object(text_named_pipe, "ensure_pipe"),
        patch.object(text_named_pipe.os, "pipe", return_value=(10, 11)),
        patch.object(text_named_pipe.os, "open", return_value=3),
        patch.object(text_named_pipe.os, "fdopen", return_value=MagicMock()),
    ):
        pipe = ChatNamedPipe("test-chat", "mock-model", backend=backend, **defaults)
    return pipe


# ---------------------------------------------------------------------------
# TestChatNamedPipe
# ---------------------------------------------------------------------------


class TestChatNamedPipe:
    def test_chat_handler_registered(self):
        pipe = make_chat_pipe()
        assert "chat" in pipe._handlers

    def test_chat_sends_response_to_sender(self):
        pipe = make_chat_pipe(reply="Hi there!")
        pipe.send_response = MagicMock()

        msg = {
            "pid": 1,
            "cmd": "chat",
            "messages": [{"role": "user", "content": "Hey"}],
        }
        pipe._handlers["chat"](msg, 1)

        pipe.send_response.assert_called_once_with("Hi there!", 1)

    def test_chat_passes_messages_to_llm(self):
        pipe = make_chat_pipe()
        pipe.send_response = MagicMock()

        conversation = [{"role": "user", "content": "What is 2+2?"}]
        msg = {"pid": 1, "cmd": "chat", "messages": conversation}
        pipe._handlers["chat"](msg, 1)

        call_args = mock_vllm.LLM.return_value.chat.call_args
        passed_messages = call_args[0][0]
        assert passed_messages == conversation

    def test_sampling_params_forwarded(self):
        mock_vllm.reset_mock()
        make_chat_pipe(temperature=0.7, max_tokens=256)

        mock_vllm.SamplingParams.assert_called_once_with(
            temperature=0.7, max_tokens=256
        )

    def test_empty_messages_default(self):
        pipe = make_chat_pipe()
        pipe.send_response = MagicMock()

        msg = {"pid": 1, "cmd": "chat"}
        pipe._handlers["chat"](msg, 1)

        call_args = mock_vllm.LLM.return_value.chat.call_args
        passed_messages = call_args[0][0]
        assert passed_messages == []

    def test_pipe_name_includes_tool_name(self):
        pipe = make_chat_pipe()
        assert pipe._pipe_name == "/tmp/tool-test-chat"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
conda run -n named-pipes pytest tests/test_chat_named_pipe.py -v
```

Expected: `test_chat_sends_response_to_sender` FAILED (handler called with 1 arg, not 2)

- [ ] **Step 3: Update ChatNamedPipe on_chat handler**

In `src/named_pipes/chat_named_pipe.py`, find the `on_chat` inner function (lines 63–67) and replace it:

```python
        @self.handler("chat")
        def on_chat(msg: dict, pid: int | None):
            messages = msg.get("messages", [])
            reply = self._infer(messages)
            self.send_response(reply, pid)
```

- [ ] **Step 4: Run tests and confirm they pass**

```bash
conda run -n named-pipes pytest tests/test_chat_named_pipe.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add src/named_pipes/chat_named_pipe.py tests/test_chat_named_pipe.py
git commit -m "feat: pass pid through ChatNamedPipe on_chat handler"
```

---

## Task 4: Update example code

**Files:**
- Modify: `src/ex_basic_pipe/server.py`
- Modify: `src/ex_basic_pipe/client.py`
- Modify: `src/ex_chat_pipe/client.py`

- [ ] **Step 1: Update ex_basic_pipe/server.py**

Replace the entire contents of `src/ex_basic_pipe/server.py` with:

```python
"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import datetime

from named_pipes import BasicPipeChannel, Role

PIPE_NAME = "/tmp/basic_pipe"


def main():
    with BasicPipeChannel(pipe_name=PIPE_NAME, role=Role.SERVER) as ch:

        @ch.handler("SUBSCRIBE")
        def on_subscribe(msg: dict, pid: int | None):
            print(f"Client {pid} subscribed to server {ch._pid}")
            ch.subscribe(pid)
            ch.send_message("SUBSCRIBED", pid=pid)

        @ch.handler("PING")
        def on_ping(msg: dict, pid: int | None):
            print("Event: on_ping")
            ch.send_message("PONG", pid=pid)

        @ch.handler("GREET")
        def on_greet(msg: dict, pid: int | None):
            print("Event: on_greet")
            name = msg["data"] or "stranger"
            ch.send_message("GREET", f"Hello, {name}!", pid=pid)

        @ch.handler("TIME")
        def on_time(msg: dict, pid: int | None):
            print("Event: on_time")
            ch.send_message(
                "TIME", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pid=pid
            )

        @ch.handler("ECHO")
        def on_echo(msg: dict, pid: int | None):
            print("Event: on_echo")
            ch.send_message("ECHO", msg["data"], pid=pid)

        @ch.handler("QUIT")
        def on_quit(msg: dict, pid: int | None):
            print("Event: on_quit")
            ch.send_message("BYE", pid=pid)
            ch.stop()

        @ch.handler("SEND_BYTES")
        def on_send_bytes(msg: dict, pid: int | None):
            print("Event: on_send_bytes")

        @ch.data_handler
        def on_data(raw: bytes, pid: int | None):
            print(f"  Received {len(raw)} bytes from pid {pid}: {list(raw)}")
            ch.send_data(raw, pid)
            ch.send_message("OK", f"echoed {len(raw)} bytes", pid=pid)

        done = ch.listen()
        print("Listening to open pipe...")
        done.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
```

- [ ] **Step 2: Update ex_basic_pipe/client.py**

Replace the entire contents of `src/ex_basic_pipe/client.py` with:

```python
"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import threading

from named_pipes import BasicPipeChannel, Role

PIPE_NAME = "/tmp/basic_pipe"


def main():
    pong_received = threading.Event()

    with BasicPipeChannel(pipe_name=PIPE_NAME, role=Role.CLIENT) as ch:

        @ch.handler("SUBSCRIBED")
        def on_subscribed(msg: dict, pid: int | None):
            print("Subscribed to server. Sending PING...")
            ch.send_message("PING")

        @ch.handler("PONG")
        def on_pong(msg: dict, pid: int | None):
            print("Received PONG!")
            pong_received.set()

        done = ch.listen()
        print("Subscribing to server...")
        ch.send_message("SUBSCRIBE")

        if not pong_received.wait(timeout=5.0):
            print("Timed out waiting for PONG.")
        else:
            print("Ping test passed.")

        ch.send_message("QUIT")
        ch.stop()
        done.wait(timeout=5.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
```

- [ ] **Step 3: Update ex_chat_pipe/client.py**

In `src/ex_chat_pipe/client.py`, replace the `msg_handler_fn` method:

```python
    def msg_handler_fn(self, msg: dict, pid: int | None):
        result = msg.get("result", "")
        if result == "subscribed":
            self.subscribed.set()
        else:
            self.response = result
            self.reply_received.set()
```

- [ ] **Step 4: Run the full test suite to confirm nothing is broken**

```bash
conda run -n named-pipes pytest tests/ -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add src/ex_basic_pipe/server.py src/ex_basic_pipe/client.py src/ex_chat_pipe/client.py
git commit -m "feat: update example code for pid-threaded handler signatures"
```

---

## Task 5: Update protocol specification

**Files:**
- Modify: `named-pipe-tools.md`

- [ ] **Step 1: Update named-pipe-tools.md**

Replace the entire contents of `named-pipe-tools.md` with:

```markdown
# Named Pipe Tools — Protocol Specification

A system for interprocess communication between a locally running **tool** (server) and one or more **clients** (tool users) via named pipes.

## Why Named Pipes?

- **Statefulness**: The tool runs as a persistent process with in-memory state, unlike a CLI that must reload state from disk or an API on every invocation.
- **Low latency**: Named pipes are the fastest IPC mechanism after shared memory — critical for real-time applications like voice agents.

**Example tools**: LLM inference server, STT/TTS streaming server, in-memory key-value store, vector database, browser automation server.

---

## Pipe Layout

Each tool exposes two named pipes:

| Pipe | Path | Writer(s) | Reader |
|------|------|-----------|--------|
| **Upstream** | `/tmp/tool-{name}` | One or more clients | The tool (single reader) |
| **Downstream** (per client) | `/tmp/tool-{name}-{pid}` | The tool | A single client |

> **Naming constraint**: A tool's human-readable name must not end with `-{integer}`, as that suffix is reserved for downstream pipe identification.

### Lifecycle

| Resource | Created by | Deleted by |
|----------|-----------|------------|
| Upstream pipe | Tool | Tool (on exit) |
| Downstream pipe (`-{pid}`) | Client | Client (on disconnect) |

### Subscription Flow

1. Client creates its downstream pipe at `/tmp/tool-{name}-{pid}`.
2. Client sends a `subscribe` message to the upstream pipe.
3. Tool opens the downstream pipe and confirms with `{ "result": "subscribed" }` sent **only to the subscribing client**.
4. Subsequent responses are routed to the **sender's** downstream pipe only, not broadcast to all subscribers.

---

## Message Protocol

All messages are **JSON objects**, one per write.

### Rule

For every message received **except `unsubscribe`**, the tool must write a response to the **sender's** downstream pipe only (identified by the `pid` field). The sole exception is the `exit` response: the tool broadcasts `{ "result": "exiting" }` to **all** subscribed clients before shutting down.

### Required Commands

Every tool must handle these commands. The `pid` field identifies the calling client.

#### `subscribe`
```json
// Request
{ "pid": 1234, "cmd": "subscribe" }

// Response (to subscribing client only)
{ "result": "subscribed" }
```
Opens the client's downstream pipe.

#### `unsubscribe`
```json
// Request
{ "pid": 1234, "cmd": "unsubscribe" }

// No response (downstream pipe is now closed)
```
Closes the client's downstream pipe.

#### `description`
```json
// Request
{ "pid": 1234, "cmd": "description" }

// Response (to sender only)
{ "result": "Natural language description of when to use this tool" }
```

#### `help`
```json
// Request
{ "pid": 1234, "cmd": "help" }

// Response (to sender only)
{ "result": "<content of SKILL.md>" }
```

#### `exit`
```json
// Request
{ "pid": 1234, "cmd": "exit" }

// Response (broadcast to ALL subscribers, then tool shuts down)
{ "result": "exiting" }

// Response (if rejected)
{ "result": "rejected" }
```
If the tool honors the request, it broadcasts `{ "result": "exiting" }` to **all** subscribed clients before shutting down.

### Custom Commands

Tools may define additional commands. The only constraint is that all messages must be valid JSON, and responses must be sent only to the requesting client (via its `pid`).

---

## Binary Data Protocol

When binary data is sent upstream (client → tool), the frame format is:

```
[4-byte PID big-endian][4-byte length big-endian][payload]
```

When the tool sends binary data downstream to a specific client, the frame format is:

```
[4-byte length big-endian][payload]
```

The downstream direction needs no PID because each client has its own dedicated downstream pipe.

---

## Future Work

- **Browser integration**: Determine whether and how a browser could interact with a named pipe tool.
```

- [ ] **Step 2: Commit**

```bash
git add named-pipe-tools.md
git commit -m "docs: update protocol spec for sender-targeted routing and binary PID prefix"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| `send_message(pid)` targeted routing | Task 1 Step 3 |
| `broadcast_message` for server notifications | Task 1 Step 3 |
| `msg_handler_fn(msg, pid)` abstract signature | Task 1 Step 3 |
| Listener extracts pid and passes to handler | Task 1 Step 3 |
| `send_response(result, pid)` | Task 1 Step 4 |
| `exit` uses broadcast | Task 1 Step 4 |
| Custom handler signature `fn(msg, pid)` | Task 1 Steps 1+4 |
| Upstream data PID wire prefix | Task 2 Step 1 |
| `recv_data` returns `(pid, bytes)` server-side | Task 2 Step 1 |
| Client `send_data` prepends own PID | Task 2 Step 1 |
| `send_data(data, pid)` targeted | Task 2 Step 1 |
| `broadcast_data` | Task 2 Step 1 |
| `data_handler_fn(data, pid)` | Task 2 Steps 1+2 |
| Client data pipe write fd added | Task 2 Step 1 |
| `BasicPipeChannel` updated throughout | Task 2 Step 2 |
| `ChatNamedPipe.on_chat(msg, pid)` | Task 3 |
| Example code updated | Task 4 |
| `subscribe` response targeted | Task 1 Step 4 + Task 5 Step 1 |
| Protocol doc updated | Task 5 |

All spec requirements covered. No placeholders. Types consistent throughout — `pid: int | None` used uniformly.
