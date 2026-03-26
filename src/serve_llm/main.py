#!/usr/bin/env python3

from named_pipes.transformers_pipe_channel import TransformersPipeChannel


def main():
    with TransformersPipeChannel(
        "HuggingFaceTB/SmolLM2-135M-Instruct",
        max_new_tokens=256,
        temperature=0.7,
        do_sample=True,
    ) as ch:
        done = ch.listen()
        print("Listening on pipe...")
        done.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
