"""Unit tests for TransformersPipeChannel (transformers stubbed, no real FIFOs created)."""

import json
import sys
from unittest.mock import MagicMock, patch

from named_pipes import abstract_pipe_channel

# Stub transformers and torch before importing anything that touches them
mock_transformers = MagicMock()
mock_torch = MagicMock()
mock_torch.backends.mps.is_available.return_value = False
mock_torch.cuda.is_available.return_value = False
sys.modules["transformers"] = mock_transformers
sys.modules["torch"] = mock_torch

from named_pipes.transformers_pipe_channel import TransformersPipeChannel  # noqa: E402


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_channel(reply: str = "Hello!"):
    """Return a TransformersPipeChannel with filesystem and transformers calls patched."""
    mock_tokenizer = MagicMock()
    mock_model = MagicMock()

    # tokenizer.apply_chat_template returns a tensor; model.generate returns output tensor
    mock_input_ids = MagicMock()
    mock_input_ids.shape = [1, 5]  # shape[-1] == 5 prompt tokens
    mock_tokenizer.apply_chat_template.return_value = mock_input_ids

    mock_output_ids = MagicMock()
    # output_ids[0][5:] simulated via __getitem__
    mock_output_ids.__getitem__ = MagicMock(return_value=MagicMock())
    mock_model.generate.return_value = mock_output_ids

    mock_tokenizer.decode.return_value = reply

    mock_transformers.AutoTokenizer.from_pretrained.return_value = mock_tokenizer
    mock_transformers.AutoModelForCausalLM.from_pretrained.return_value = mock_model

    with (
        patch.object(abstract_pipe_channel, "ensure_pipe"),
        patch.object(abstract_pipe_channel.os, "open", return_value=3),
        patch.object(abstract_pipe_channel.os, "fdopen", return_value=MagicMock()),
    ):
        ch = TransformersPipeChannel("mock-model", "/tmp/test-transformers-pipe")
    ch._tokenizer = mock_tokenizer
    ch._model = mock_model
    return ch


# ---------------------------------------------------------------------------
# TestTransformersPipeChannel
# ---------------------------------------------------------------------------


class TestTransformersPipeChannel:
    def test_chat_handler_registered(self):
        ch = make_channel()
        assert "CHAT" in ch._handlers

    def test_chat_sends_response(self):
        ch = make_channel(reply="Hi there!")
        ch.send_message = MagicMock()

        conversation = [{"role": "user", "content": "Hey"}]
        ch.dispatch({"cmd": "CHAT", "data": json.dumps(conversation)})

        ch.send_message.assert_called_once_with("CHAT_RESPONSE", "Hi there!")

    def test_chat_invalid_json_sends_error(self):
        ch = make_channel()
        ch.send_message = MagicMock()

        ch.dispatch({"cmd": "CHAT", "data": "not valid json {"})

        ch.send_message.assert_called_once_with("ERROR", "invalid JSON")

    def test_generation_kwargs_forwarded_to_generate(self):
        mock_transformers.reset_mock()
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_input_ids = MagicMock()
        mock_input_ids.shape = [1, 3]
        mock_tokenizer.apply_chat_template.return_value = mock_input_ids
        mock_model.generate.return_value = MagicMock()
        mock_tokenizer.decode.return_value = "ok"
        mock_transformers.AutoTokenizer.from_pretrained.return_value = mock_tokenizer
        mock_transformers.AutoModelForCausalLM.from_pretrained.return_value = mock_model

        with (
            patch.object(abstract_pipe_channel, "ensure_pipe"),
            patch.object(abstract_pipe_channel.os, "open", return_value=3),
            patch.object(abstract_pipe_channel.os, "fdopen", return_value=MagicMock()),
        ):
            ch = TransformersPipeChannel(
                "mock-model",
                "/tmp/test-transformers-pipe",
                max_new_tokens=128,
                temperature=0.5,
                do_sample=True,
            )
        ch._tokenizer = mock_tokenizer
        ch._model = mock_model
        ch.send_message = MagicMock()

        conversation = [{"role": "user", "content": "Hi"}]
        ch.dispatch({"cmd": "CHAT", "data": json.dumps(conversation)})

        _, kwargs = mock_model.generate.call_args
        assert kwargs.get("max_new_tokens") == 128
        assert kwargs.get("temperature") == 0.5
        assert kwargs.get("do_sample") is True

    def test_uses_cpu_when_no_accelerator(self):
        mock_torch.backends.mps.is_available.return_value = False
        mock_torch.cuda.is_available.return_value = False

        with (
            patch.object(abstract_pipe_channel, "ensure_pipe"),
            patch.object(abstract_pipe_channel.os, "open", return_value=3),
            patch.object(abstract_pipe_channel.os, "fdopen", return_value=MagicMock()),
        ):
            ch = TransformersPipeChannel("mock-model", "/tmp/test-transformers-pipe")

        assert ch._device == "cpu"
