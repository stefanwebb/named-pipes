# Example: `BasicPipeChannel`

A minimal end-to-end example using `BasicPipeChannel` to communicate between a server and client over named pipes.

## What it does

1. **Server** creates a `BasicPipeChannel` and registers handlers for `SUBSCRIBE`, `PING`, `GREET`, `TIME`, `ECHO`, `SEND_BYTES`, and `QUIT`.
2. **Client** connects, subscribes, sends a `PING`, waits for the `PONG` response, then sends `QUIT` to shut the server down.

## Usage

Start the server first (it creates the named pipe), then run the client in a separate terminal:

```bash
# Terminal 1
conda activate named-pipes
python src/test_basic_pipe/server.py

# Terminal 2
conda activate named-pipes
python src/test_basic_pipe/client.py
```

Expected output:

```
# Server
Listening to open pipe...
Client <pid> subscribed to server <pid>
Event: on_ping
Event: on_quit

# Client
Subscribing to server...
Subscribed to server. Sending PING...
Received PONG!
Ping test passed.
```

## Pipe layout

| Path | Direction |
|------|-----------|
| `/tmp/basic_pipe` | client → server (upstream) |
| `/tmp/basic_pipe-<pid>` | server → client (downstream, one per subscriber) |
