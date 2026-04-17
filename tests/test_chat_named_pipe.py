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

from named_pipes.chat import Backend, ChatConfig, ChatNamedPipe  # noqa: E402


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_chat_pipe(
    backend=Backend.VLLM, reply="Hello!", backend_kwargs=None, **chatconfig_kwargs
):
    """Return a ChatNamedPipe with filesystem and backend calls patched."""
    if backend is Backend.VLLM:
        mock_output = MagicMock()
        mock_output.outputs[0].text = reply
        mock_vllm.LLM.return_value.chat.return_value = [mock_output]

    config = ChatConfig(
        name="test-chat",
        model="mock-model",
        backend=backend,
        description=chatconfig_kwargs.get("description", "A chat tool"),
        help_text=chatconfig_kwargs.get("help_text", "Chat help"),
        backend_kwargs=backend_kwargs or {},
    )

    with (
        patch.object(text_named_pipe, "ensure_pipe"),
        patch.object(text_named_pipe.os, "pipe", return_value=(-1, -1)),
        patch.object(text_named_pipe.os, "open", return_value=3),
        patch.object(text_named_pipe.os, "fdopen", return_value=MagicMock()),
        patch(
            "named_pipes.tool_named_pipe.scan_pipes",
            return_value={"connected": [], "orphaned": []},
        ),
    ):
        pipe = ChatNamedPipe(config)
    return pipe


# ---------------------------------------------------------------------------
# TestChatNamedPipe
# ---------------------------------------------------------------------------


class TestChatNamedPipe:
    def test_chat_handler_registered(self):
        pipe = make_chat_pipe()
        assert "chat" in pipe._handlers

    def test_chat_sends_response_to_sender(self):
        import json

        pipe = make_chat_pipe(reply="Hi there!")
        pipe.send_message = MagicMock()

        pipe._infer_stream([{"role": "user", "content": "Hey"}], 1)

        pipe.send_message.assert_any_call(
            json.dumps({"result": "Hi there!", "done": False}), 1
        )

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
        make_chat_pipe(backend_kwargs={"temperature": 0.7, "max_tokens": 256})

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
