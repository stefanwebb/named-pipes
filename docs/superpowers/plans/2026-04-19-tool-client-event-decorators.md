# ToolClient Event Decorator Handlers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `on_message` override hook in `ToolClient` and all example clients with an `@self.on("event")` decorator pattern that mirrors `ToolServer.handler`.

**Architecture:** Add `_handlers: dict[str, callable]` and an `on(event)` decorator to `ToolClient`; update `msg_handler_fn` to dispatch by event key. Then convert `_LLMClient` (chat_client.py, tts_client.py) and `_STTClient` (stt_client.py) to register handlers in `__init__` via `@self.on(...)` instead of overriding `on_message`.

**Tech Stack:** Python 3.12, pytest, unittest.mock, conda env `named-pipes`

---

### Task 1: Add `on()` decorator and update dispatch in `ToolClient`

**Files:**
- Modify: `src/named_pipes/tool_client.py`

- [ ] **Step 1: Read the current file**

  Open `src/named_pipes/tool_client.py` and confirm the current shape — `_subscribed` event, `msg_handler_fn` checking for `subscribed`, `on_message` override hook.

- [ ] **Step 2: Apply the changes**

  Replace the entire file content with:

  ```python
  """
  © 2025–2026, Stefan Webb. Some Rights Reserved.

  Except where otherwise noted, this work is licensed under a
  Creative Commons Attribution-ShareAlike 4.0 International License
  https://creativecommons.org/licenses/by-sa/4.0/deed.en

  ToolClient — implements the client side of the Named Pipe Tools protocol.

  See named-pipe-tools.md for the full specification.
  """

  import json
  import threading

  from named_pipes.text_named_pipe import TextNamedPipe, Role


  class ToolClient(TextNamedPipe):
      """Named-pipe client that follows the Named Pipe Tools protocol.

      Connects to a ``ToolServer`` at ``/tmp/tool-{name}``.

      The context manager starts the listener, subscribes on entry, and
      unsubscribes on exit::

          with ToolClient("chat") as client:
              client.send_command("ping")

      Without the context manager, call ``listen()`` then ``subscribe()``
      manually, and ``unsubscribe()`` / ``_close()`` before discarding.

      Register event handlers with the ``on`` decorator::

          @client.on("reply")
          def _(msg):
              print(msg.get("text"))
      """

      def __init__(self, name: str):
          super().__init__(f"/tmp/tool-{name}", Role.CLIENT)
          self._subscribed = threading.Event()
          self._handlers: dict[str, callable] = {}

      # --- decorator for event handlers ---

      def on(self, event: str):
          """Decorator that registers a handler for *event*.

          The registered function must accept ``(msg: dict)``.
          """
          def decorator(fn):
              self._handlers[event] = fn
              return fn
          return decorator

      # --- sending helpers ---

      def send_command(self, cmd: str, **kwargs):
          """Send ``{"pid": ..., "cmd": cmd, ...kwargs}`` to the server."""
          payload = {"pid": self._pid, "cmd": cmd}
          payload.update(kwargs)
          self.send_message(json.dumps(payload))

      def subscribe(self):
          """Send ``subscribe`` and block until the server confirms."""
          self.send_command("subscribe")
          self._subscribed.wait()

      def unsubscribe(self):
          """Send ``unsubscribe`` (no response expected)."""
          self.send_command("unsubscribe")

      # --- message handler ---

      def msg_handler_fn(self, msg: dict, pid: int | None):
          if msg.get("event") == "subscribed":
              self._subscribed.set()
              return
          fn = self._handlers.get(msg.get("event", ""))
          if fn:
              fn(msg)

      # --- context manager ---

      def __enter__(self):
          self.listen()
          self.subscribe()
          return self

      def __exit__(self, *_):
          self.unsubscribe()
          self._close()
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add src/named_pipes/tool_client.py
  git commit -m "refactor: replace on_message with on() decorator in ToolClient"
  ```

---

### Task 2: Write and run tests for `ToolClient`

**Files:**
- Create: `tests/test_tool_client.py`

- [ ] **Step 1: Create the test file**

  Create `tests/test_tool_client.py` with:

  ```python
  """
  Unit tests for ToolClient (no real FIFOs created).
  """

  import threading
  from unittest.mock import MagicMock, patch

  from named_pipes import text_named_pipe
  from named_pipes.tool_client import ToolClient


  def make_client(name="chat"):
      """Return a ToolClient with all filesystem calls patched out."""
      with (
          patch.object(text_named_pipe, "ensure_pipe"),
          patch.object(text_named_pipe, "remove_pipe"),
          patch.object(text_named_pipe.os, "pipe", return_value=(-1, -1)),
          patch.object(text_named_pipe.os, "open", return_value=3),
          patch.object(text_named_pipe.os, "fdopen", return_value=MagicMock()),
      ):
          client = ToolClient(name)
      return client


  class TestPipePath:
      def test_pipe_name_derived_from_tool_name(self):
          client = make_client("stt")
          assert client._pipe_name == "/tmp/tool-stt"


  class TestOnDecorator:
      def test_registers_handler(self):
          client = make_client()

          @client.on("reply")
          def _(msg):
              pass

          assert "reply" in client._handlers

      def test_returns_original_function(self):
          client = make_client()

          def handler(msg):
              pass

          result = client.on("reply")(handler)
          assert result is handler


  class TestMsgHandlerFn:
      def test_subscribed_event_sets_flag(self):
          client = make_client()
          client._subscribed = MagicMock(spec=threading.Event)

          client.msg_handler_fn({"event": "subscribed"}, None)

          client._subscribed.set.assert_called_once()

      def test_subscribed_event_not_forwarded_to_handlers(self):
          client = make_client()
          mock_handler = MagicMock()
          client._handlers["subscribed"] = mock_handler

          client.msg_handler_fn({"event": "subscribed"}, None)

          mock_handler.assert_not_called()

      def test_registered_handler_called_with_msg(self):
          client = make_client()
          mock_handler = MagicMock()
          client._handlers["reply"] = mock_handler

          msg = {"event": "reply", "text": "hello"}
          client.msg_handler_fn(msg, None)

          mock_handler.assert_called_once_with(msg)

      def test_unknown_event_silently_ignored(self):
          client = make_client()
          # Should not raise
          client.msg_handler_fn({"event": "unknown_event"}, None)

      def test_missing_event_key_silently_ignored(self):
          client = make_client()
          # Should not raise
          client.msg_handler_fn({}, None)
  ```

- [ ] **Step 2: Run the tests**

  ```bash
  conda run -n named-pipes pytest tests/test_tool_client.py -v
  ```

  Expected: all 7 tests PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add tests/test_tool_client.py
  git commit -m "test: add unit tests for ToolClient.on() decorator and dispatch"
  ```

---

### Task 3: Update `chat_client.py`

**Files:**
- Modify: `src/examples/chat_client.py`

- [ ] **Step 1: Apply the changes**

  Replace the `_LLMClient` class definition (keep the module docstring, imports, and query constants unchanged):

  ```python
  class _LLMClient(ToolClient):
      """Client for the ChatServer protocol."""

      def __init__(self):
          super().__init__("chat")
          self.reply_received = threading.Event()
          self.response: str | None = None

          @self.on("state_changed")
          def _(msg):
              print("on_state_changed", msg.get("state", ""))

          @self.on("token")
          def _(msg):
              if msg.get("done") is True:
                  self.reply_received.set()
              else:
                  print(msg.get("text", ""), end="", flush=True)

          @self.on("reply")
          def _(msg):
              self.response = msg.get("text", "")
              self.reply_received.set()
  ```

  The full file after the edit:

  ```python
  """
  © 2025–2026, Stefan Webb. Some Rights Reserved.

  Except where otherwise noted, this work is licensed under a
  Creative Commons Attribution-ShareAlike 4.0 International License
  https://creativecommons.org/licenses/by-sa/4.0/deed.en

  LLM client: subscribes to the LLM server, demonstrates both streaming
  (chat) and blocking (chat_blocking) inference requests.
  """

  import time
  import threading

  from named_pipes.tool_client import ToolClient

  STREAMING_QUERY = [{"role": "user", "content": "What is the capital of France?"}]
  BLOCKING_QUERY = [
      {"role": "user", "content": "Name three planets in the solar system."}
  ]


  class _LLMClient(ToolClient):
      """Client for the ChatServer protocol."""

      def __init__(self):
          super().__init__("chat")
          self.reply_received = threading.Event()
          self.response: str | None = None

          @self.on("state_changed")
          def _(msg):
              print("on_state_changed", msg.get("state", ""))

          @self.on("token")
          def _(msg):
              if msg.get("done") is True:
                  self.reply_received.set()
              else:
                  print(msg.get("text", ""), end="", flush=True)

          @self.on("reply")
          def _(msg):
              self.response = msg.get("text", "")
              self.reply_received.set()


  def main():
      with _LLMClient() as ch:
          # --- streaming ---
          # print(f"Streaming query: {STREAMING_QUERY[0]['content']!r}")
          # print("Response: ", end="")
          # ch.send_command("chat", messages=STREAMING_QUERY)
          # ch.reply_received.wait()
          # print()  # newline after streamed chunks

          # time.sleep(2)

          # # --- blocking ---
          ch.reply_received.clear()
          print(f"\nBlocking query: {BLOCKING_QUERY[0]['content']!r}")
          ch.send_command("chat_blocking", messages=BLOCKING_QUERY)
          ch.reply_received.wait()
          print(f"Response: {ch.response}")


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 2: Run existing tests to check for regressions**

  ```bash
  conda run -n named-pipes pytest tests/test_tool_client.py tests/test_tool_named_pipe.py -v
  ```

  Expected: all tests PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add src/examples/chat_client.py
  git commit -m "refactor: use @self.on() decorators in chat_client._LLMClient"
  ```

---

### Task 4: Update `stt_client.py`

**Files:**
- Modify: `src/examples/stt_client.py`

- [ ] **Step 1: Apply the changes**

  Replace the full file with:

  ```python
  """
  © 2025–2026, Stefan Webb. Some Rights Reserved.

  Except where otherwise noted, this work is licensed under a
  Creative Commons Attribution-ShareAlike 4.0 International License
  https://creativecommons.org/licenses/by-sa/4.0/deed.en

  STT subscriber: connects to the STT server on /tmp/tool-stt, subscribes,
  and prints each broadcast message until Ctrl+C.

  Requires the STT server to be running first:
      cpipe --serve stt
  """

  import threading

  from named_pipes.tool_client import ToolClient


  class _STTClient(ToolClient):
      """Subscriber for the STTServer protocol."""

      def __init__(self):
          super().__init__("stt")

          @self.on("token")
          def _(msg):
              print(msg.get("text", ""), end="", flush=True)

          @self.on("speech_start")
          def _(msg):
              print("\n[speech_start] ", end="", flush=True)

          @self.on("speech_end")
          def _(msg):
              print(" [speech_end]", flush=True)


  def main():
      with _STTClient() as stt:
          print("Subscribed to /tmp/tool-stt. Speak into the mic; Ctrl+C to stop.")

          try:
              threading.Event().wait()
          except KeyboardInterrupt:
              print("\nUnsubscribing.")


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 2: Run tests**

  ```bash
  conda run -n named-pipes pytest tests/test_tool_client.py tests/test_tool_named_pipe.py -v
  ```

  Expected: all tests PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add src/examples/stt_client.py
  git commit -m "refactor: use @self.on() decorators in stt_client._STTClient"
  ```

---

### Task 5: Update `tts_client.py`

**Files:**
- Modify: `src/examples/tts_client.py`

- [ ] **Step 1: Apply the changes**

  Replace the full file with:

  ```python
  """
  © 2025–2026, Stefan Webb. Some Rights Reserved.

  Except where otherwise noted, this work is licensed under a
  Creative Commons Attribution-ShareAlike 4.0 International License
  https://creativecommons.org/licenses/by-sa/4.0/deed.en

  LLM→TTS client: streams a chat query to the LLM server and forwards each
  token chunk to the TTS server in real time for speech synthesis.

  Requires both servers to be running before starting this client:
      cpipe --serve chat   (listens on /tmp/tool-chat)
      cpipe --serve tts    (listens on /tmp/tool-tts)
  """

  import threading

  from named_pipes.tool_client import ToolClient

  QUERY = [
      {
          "role": "user",
          # "content": "Tell me a short story about a robot learning to paint.",
          "content": "What is your name?",
      }
  ]


  class _LLMClient(ToolClient):
      """Streaming client for the ChatServer protocol."""

      def __init__(self, on_chunk, on_done):
          super().__init__("chat")
          self._on_chunk = on_chunk
          self._on_done = on_done

          @self.on("token")
          def _(msg):
              if msg.get("done") is True:
                  self._on_done()
              else:
                  self._on_chunk(msg.get("text", ""))


  class _TTSClient(ToolClient):
      """Client for the TTSServer protocol."""

      def __init__(self):
          super().__init__("tts")

      def send_text(self, token: str):
          """Send a text chunk to the TTS server."""
          self.send_command("text", data=token)

      def flush(self):
          """Tell the TTS server to synthesise any remaining buffered text."""
          self.send_command("flush")


  def main():
      stream_done = threading.Event()

      with _TTSClient() as tts:

          def on_chunk(text: str):
              print(text, end="", flush=True)
              tts.send_text(text)

          def on_done():
              tts.flush()
              stream_done.set()

          with _LLMClient(on_chunk, on_done) as llm:
              print("Subscribed to both servers.")
              print(f"Query: {QUERY[0]['content']!r}\nResponse: ", end="")
              llm.send_command("chat", messages=QUERY)

              stream_done.wait()
              print()  # newline after streamed chunks


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 2: Run full test suite**

  ```bash
  conda run -n named-pipes pytest tests/test_tool_client.py tests/test_tool_named_pipe.py -v
  ```

  Expected: all tests PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add src/examples/tts_client.py
  git commit -m "refactor: use @self.on() decorators in tts_client._LLMClient"
  ```
