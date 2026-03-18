#!/usr/bin/env python3
"""Subprocess server for C# LLMPipeChannel integration tests.

Stubs out vllm with a MagicMock before importing LLMPipeChannel so the
server can run without a real GPU or vllm installation.

Usage: python3 tests/server_llm.py [pipe_name]
  pipe_name defaults to /tmp/agent
"""
import sys
import os
from unittest.mock import MagicMock

# Stub vllm before any import of llm_pipe_channel
mock_vllm = MagicMock()
sys.modules["vllm"] = mock_vllm

# Configure LLM().chat() to return a recognisable mock reply.
# chat() returns a list; code accesses outputs[0].outputs[0].text.
mock_output = MagicMock()
mock_output.outputs[0].text = "Mock LLM reply."
mock_vllm.LLM.return_value.chat.return_value = [mock_output]

# Ensure repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from llm_pipe_channel import LLMPipeChannel  # noqa: E402 (import after stub)


def main():
    pipe_name = sys.argv[1] if len(sys.argv) > 1 else "/tmp/agent"

    with LLMPipeChannel("mock-model", pipe_name) as ch:
        print("Pipes open. Listening...", flush=True)

        try:
            while True:
                msg = ch.recv_message()
                if not msg:
                    continue
                if msg["cmd"].upper() == "QUIT":
                    ch.send_message("BYE")
                    break
                ch.dispatch(msg)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
