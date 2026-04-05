"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

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
