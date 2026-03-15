# `named-pipes`: a simple client/server example of interprocess communication with named pipes
This simple project is my first foray into Claude Code.

The challenge: I need a low-latency method for interprocess communication between a client process (the "agent"), and multiple server processes (for SST, LLM inference, TTS, vector DBs, etc.)

I've done this via local HTTP, but want to build a system based on named pipes for the lowest **local** latency (short of shared-memory).