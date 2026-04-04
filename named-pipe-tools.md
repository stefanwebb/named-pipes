# Conventions for Named Pipe Tools
The following conventions define a simple system for interprocess communication between a locally running “tool”, and one or more “users” of that tool via named pipes.

In this system, because a tool runs on a separate process independently of the tool user, it can have statefulness via system memory, in contrast to a CLI, which has to use the file system or an external API to affect state. This is useful in scenarios like local model servers, where it is impractical to load the model every time the tool is called. Another useful scenario is for in-memory databases.

Moreover, because the communication transport is implemented by named pipes, the fastest form of interprocess communication outside of shared memory, very low latency can be achieved. This is important for applications like voice agents.

Examples of useful named pipe tools:

* An LLM inference server implementing the OpenAI Completions API
* A STT server transcribing streaming audio packets
* A TTS server generating audio packets from streaming text
* An in-memory key-value store, vector database, or graph database
* A web browser automation server

## Named Pipes

A named pipe is a special file on the filesystem that allows two processes to communicate by reading and writing to it, just like a regular pipe (|), but it persists as a named entry in the filesystem rather than being anonymous and tied to a single command line.

One process opens it for writing, another opens it for reading, and data flows between them in a first-in, first-out manner.

### Upstream Pipes

There is a single upstream named pipe for each running tool located at `/tmp/tool-[tool name]`, for example, `/tmp/tool-llm-server`.

Multiple processes can open and write to the same upstream pipe.

A single process - the tool - creates, opens, and reads from this pipe.

The tool is responsible for deleting the pipe once it finishes.

### Downstream Pipes

A downstream pipe is a named pipe located at `/tmp/tool-[tool name]-[pid]`, for example, `/tmp/tool-llm-server-519`.

Due to this convention, a tool’s human readable name cannot end with `-[integer]`

A single process, the tool user with process id `[pid]`, creates the corresponding downstream pipe, opens it, and reads from it

After creating the downstream pipe, the tool user registers its process id with the tool by sending it a subscribe message.

The tool writes to all subscribed downstream pipes each time a message is sent.

## Clients and Servers

The tool is a “server” that listens to and reads from upstream pipe and writes to downstream pipe(s).

A user of the tool is a “client” that listens to and reads its downstream pipe and writes to the upstream pipe of the server.

The tool is responsible for creating and deleting the upstream pipe and each client is responsible for creating and deleting its downstream pipe.

## Message Protocol

The requirements on the message protocol between the tool and its user(s) are minimal:

Messages sent and received between the tool and its user(s) must be in JSON format.

For every message received by the tool except for the unsubscribe command, it must send a message to all subscribed pipes, even if it is just a single EOF.

### Required Messages
The tool must respond to the following messages:

{ pid: <pid of caller>, cmd: “subscribe” } ⇒ Opens the downstream pipe and responds with { result: “subscribed” }

{ pid: <pid of caller>, cmd: “unsubscribe” } ⇒ Closes the downstream pipe if it is open. No response as the communication channel is closed.

{ pid: <pid of caller>, cmd: “description” } ⇒ Returns a natural language description of when it should be used

{ pid: <pid of caller>, cmd: “help” } ⇒ Returns an agent SKILL.md as { result: “[content of SKILL.md]”}

{ pid: <pid of caller>, cmd: “exit” } ⇒ Requests that the tool process terminate. If it decides to honor the request, it responds with { result: “exiting” }, and if not it responds with { result: “rejected” }. Before exiting, the tool will broadcast the message { result: “exiting” } to all clients that are subscribed to it.

There are no other restrictions on the protocol of messages sent to the tool aside from that they must be valid JSON.

## Future Work

* Extend this system so that tools and users can send and receive *binary data*, which is useful, for example, for sending images and audio.
* Determine whether and how a browser could interact with a named pipe tool.
