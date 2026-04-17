# Examples

Runnable examples showing how to use the named-pipe servers.

For most purposes the servers are started with `cpipe --serve <type>`. The `minimal_server.py` script is included for cases where you need a standalone Python process (e.g. no `cpipe` on PATH, or debugging).

## Files

| File | Servers required | What it does |
|---|---|---|
| `chat_client.py` | `cpipe --serve chat` | Sends one streaming and one blocking inference request to the LLM server and prints the replies |
| `tts_client.py` | `cpipe --serve chat` + `cpipe --serve tts` | Streams a chat query to the LLM server and forwards each token to the TTS server for real-time speech synthesis |
| `stt_client.py` | `cpipe --serve stt` | Subscribes to the STT server and prints transcribed tokens and VAD events until Ctrl+C |
| `minimal_server.py` | *(none)* | Minimal standalone STT server — equivalent to `cpipe --serve stt` |

## Running

Start servers first (each in its own terminal), then run the client.

### LLM chat

```bash
cpipe --serve chat          # Terminal 1
python src/examples/chat_client.py  # Terminal 2
```

### LLM → TTS pipeline (spoken output)

```bash
cpipe --serve chat          # Terminal 1
cpipe --serve tts           # Terminal 2
python src/examples/tts_client.py   # Terminal 3
```

### Speech-to-text

```bash
cpipe --serve stt           # Terminal 1
python src/examples/stt_client.py   # Terminal 2
```
