"""Unit tests for LLMPipeChannel (vllm stubbed, no real FIFOs created)."""

import json
import sys
from unittest.mock import MagicMock, patch

from named_pipes import abstract_pipe_channel
from named_pipes.llm_pipe_channel import LLMPipeChannel

# Stub vllm before importing anything that touches it
mock_vllm = MagicMock()
sys.modules["vllm"] = mock_vllm

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_llm_channel(reply: str = "Hello!"):
    """Return an LLMPipeChannel with filesystem and vllm calls patched."""
    # Configure mock LLM().chat() return value.
    # chat() returns a list; code accesses outputs[0].outputs[0].text.
    mock_output = MagicMock()
    mock_output.outputs[0].text = reply
    mock_vllm.LLM.return_value.chat.return_value = [mock_output]

    with (
        patch.object(abstract_pipe_channel, "ensure_pipe"),
        patch.object(abstract_pipe_channel.os, "open", return_value=3),
        patch.object(abstract_pipe_channel.os, "fdopen", return_value=MagicMock()),
    ):
        ch = LLMPipeChannel("mock-model", "/tmp/test-llm-pipe")
    return ch


# ---------------------------------------------------------------------------
# TestLLMPipeChannel
# ---------------------------------------------------------------------------


class TestLLMPipeChannel:
    def test_chat_handler_registered(self):
        ch = make_llm_channel()
        assert "CHAT" in ch._handlers

    def test_chat_sends_response(self):
        ch = make_llm_channel(reply="Hi there!")
        ch.send_message = MagicMock()

        conversation = [{"role": "user", "content": "Hey"}]
        ch.dispatch({"cmd": "CHAT", "data": json.dumps(conversation)})

        ch.send_message.assert_called_once_with("CHAT_RESPONSE", "Hi there!")

    def test_chat_passes_messages_to_llm(self):
        ch = make_llm_channel()
        ch.send_message = MagicMock()

        conversation = [{"role": "user", "content": "What is 2+2?"}]
        ch.dispatch({"cmd": "CHAT", "data": json.dumps(conversation)})

        call_args = mock_vllm.LLM.return_value.chat.call_args
        passed_messages = call_args[0][0]
        assert passed_messages == conversation

    def test_sampling_params_forwarded(self):
        mock_vllm.reset_mock()

        with (
            patch.object(pipe_channel, "ensure_pipe"),
            patch.object(pipe_channel.os, "open", return_value=3),
            patch.object(pipe_channel.os, "fdopen", return_value=MagicMock()),
        ):
            LLMPipeChannel(
                "mock-model", "/tmp/test-llm-pipe", temperature=0.7, max_tokens=256
            )

        mock_vllm.SamplingParams.assert_called_once_with(
            temperature=0.7, max_tokens=256
        )
