// © 2025–2026, Stefan Webb. Some Rights Reserved.
// Licensed under CC BY-SA 4.0
//
// C# client for the Named Pipe Tools protocol.
// Mirrors the Python ToolClient in src/named_pipes/tool_client.py.
// See named-pipe-tools.md for the full specification.

using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

class EventReceivedEventArgs(string @event, JsonObject data) : EventArgs
{
    public string Event { get; } = @event;
    public JsonObject Data { get; } = data;
}

/// <summary>
/// C# client for the Named Pipe Tools protocol.
///
/// Connects to a ToolServer at /tmp/tool-{name} and receives events on a
/// per-process downstream pipe at /tmp/tool-{name}-{pid}.
///
/// Typical usage:
///   using var client = new ToolClient("demo");
///   client.On("pong", _ => Console.WriteLine("pong"));
///   client.StartListening();
///   client.Subscribe();
///   client.SendCommand("ping");
///   client.Unsubscribe();
/// </summary>
class ToolClient : IDisposable
{
    [DllImport("libc", SetLastError = true)]
    private static extern int mkfifo(string pathname, uint mode);

    [DllImport("libc", SetLastError = true)]
    private static extern int unlink(string pathname);

    private readonly string _downstreamPath;
    private readonly int _pid;

    private readonly StreamWriter _writer;
    private readonly StreamReader _reader;
    private readonly Lock _writeLock = new();

    private Thread? _listenerThread;
    private readonly ManualResetEventSlim _subscribedEvent = new(false);
    private readonly ManualResetEventSlim _done = new(false);
    private bool _disposed;

    private readonly Dictionary<string, Action<JsonObject>> _handlers = new();

    /// <summary>Fired for every event received from the server (except "subscribed").</summary>
    public event EventHandler<EventReceivedEventArgs>? EventReceived;

    public ToolClient(string name)
    {
        var pipeName = $"/tmp/tool-{name}";
        _pid = Environment.ProcessId;
        _downstreamPath = $"{pipeName}-{_pid}";

        // Create the per-client downstream FIFO for server → client messages.
        unlink(_downstreamPath);  // remove stale pipe if present
        if (mkfifo(_downstreamPath, 0x1B6) != 0)  // 0o666 = rw-rw-rw-
            throw new IOException($"mkfifo failed for {_downstreamPath}");

        // Open downstream FIFO O_RDWR (FileAccess.ReadWrite) so the open does
        // not block waiting for a writer — the server opens its write end later
        // when it processes our subscribe command.
        _reader = new StreamReader(new FileStream(
            _downstreamPath, FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite));

        // Open upstream FIFO O_RDWR — the server already has it open O_RDWR,
        // so this does not block either.
        _writer = new StreamWriter(new FileStream(
            pipeName, FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite))
        { AutoFlush = true };
    }

    // --- event handler registration ---

    /// <summary>Register a handler called whenever the server sends the named event.</summary>
    public void On(string eventName, Action<JsonObject> handler) =>
        _handlers[eventName] = handler;

    // --- sending ---

    /// <summary>Send {"pid": ..., "cmd": cmd, ...extra} to the server.</summary>
    public void SendCommand(string cmd, JsonObject? extra = null)
    {
        var payload = new JsonObject { ["pid"] = _pid, ["cmd"] = cmd };
        if (extra is not null)
            foreach (var prop in extra)
                payload[prop.Key] = prop.Value?.DeepClone();
        lock (_writeLock)
            _writer.WriteLine(payload.ToJsonString());
    }

    /// <summary>Send subscribe and block until the server confirms.</summary>
    public void Subscribe()
    {
        SendCommand("subscribe");
        _subscribedEvent.Wait();
    }

    /// <summary>Send unsubscribe (no response expected).</summary>
    public void Unsubscribe() => SendCommand("unsubscribe");

    // --- background listener ---

    /// <summary>
    /// Start the background listener thread.
    /// Returns a ManualResetEventSlim that is set when the listener exits.
    /// </summary>
    public ManualResetEventSlim StartListening()
    {
        _done.Reset();
        _listenerThread = new Thread(ListenerLoop)
        {
            IsBackground = true,
            Name = "ToolClientListener",
        };
        _listenerThread.Start();
        return _done;
    }

    private void ListenerLoop()
    {
        try
        {
            while (true)
            {
                var line = _reader.ReadLine();
                if (line is null) break;

                var obj = JsonNode.Parse(line)?.AsObject();
                if (obj is null) continue;
                var eventName = obj["event"]?.GetValue<string>() ?? "";

                if (eventName == "subscribed")
                {
                    _subscribedEvent.Set();
                    continue;
                }

                if (_handlers.TryGetValue(eventName, out var handler))
                    handler(obj);

                EventReceived?.Invoke(this, new EventReceivedEventArgs(eventName, obj));
            }
        }
        catch (ObjectDisposedException) { }
        catch (IOException) { }
        finally
        {
            _done.Set();
        }
    }

    // --- cleanup ---

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        try { _reader.Close(); } catch { }     // unblocks ReadLine() in listener thread
        _listenerThread?.Join(TimeSpan.FromSeconds(2));
        try { _writer.Dispose(); } catch { }
        try { _reader.Dispose(); } catch { }
        unlink(_downstreamPath);               // delete the downstream FIFO we created
    }
}
