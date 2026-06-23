// © 2025–2026, Stefan Webb. Some Rights Reserved.
// Licensed under CC BY-SA 4.0
//
// C# client for the named-pipes STT server (any backend implementing the
// `stt` interface). Mirrors src/examples/stt_client.py.
//
// Lists available input devices, prompts you to choose one, then starts
// streaming transcription and overwrites the current line in place as the
// transcript updates.
//
// Requires the STT server to already be running:
//   cpipe --serve stt
//
// Then:
//   cd src/MyClientConsole && dotnet run

using System.Text.Json.Nodes;

const string ToolName = "stt";
var pipePath = $"/tmp/tool-{ToolName}";

if (!File.Exists(pipePath))
{
    Console.Error.WriteLine(
        $"STT server not running (no pipe at {pipePath}). Start it first with:\n  cpipe --serve stt");
    return 1;
}

var printer = new LinePrinter();
var devices = new List<(int Index, string Name, int Channels)>();
var devicesReceived = new ManualResetEventSlim(false);
var started = new ManualResetEventSlim(false);
var speechEnded = new ManualResetEventSlim(true);
var stateReceived = new ManualResetEventSlim(false);
var currentState = "";

// States in which the mic is already open — list_devices/set_device/start
// are skipped so a second client can attach to a session another process
// started.
var activeStates = new HashSet<string> { "listening", "transcribing" };

using var client = new ToolClient(ToolName);

client.On("devices", msg =>
{
    if (msg["devices"] is JsonArray arr)
    {
        foreach (var node in arr)
        {
            if (node is not JsonObject d) continue;
            devices.Add((
                d["index"]?.GetValue<int>() ?? -1,
                d["name"]?.GetValue<string>() ?? "",
                d["channels"]?.GetValue<int>() ?? 0));
        }
    }
    devicesReceived.Set();
});

client.On("device", msg =>
    Console.WriteLine($"[device] using index {msg["device"]?.ToJsonString() ?? "null"}"));

client.On("state", msg =>
{
    currentState = msg["state"]?.GetValue<string>() ?? "";
    stateReceived.Set();
});

client.On("speech_start", _ =>
{
    speechEnded.Reset();
    printer.Newline();
    Console.WriteLine("[speech_start]");
});

client.On("speech", msg =>
{
    // The forced aligner runs out-of-process and reports back after the
    // fact, so a "speech" event with words can arrive well after this
    // utterance's speech_end. Only print the timestamps then, instead of
    // re-printing the live partial text again.
    if (msg["words"] is JsonArray words && words.Count > 0)
    {
        if (speechEnded.IsSet)
        {
            var parts = words
                .OfType<JsonObject>()
                .Select(w =>
                {
                    var start = w["start"]?.GetValue<double>() ?? 0;
                    var end = w["end"]?.GetValue<double>() ?? 0;
                    var word = w["word"]?.GetValue<string>() ?? "";
                    return $"[{start:F3}–{end:F3}] {word}";
                });
            Console.WriteLine(string.Join(" ", parts));
        }
        return;
    }
    printer.Overwrite(msg["text"]?.GetValue<string>() ?? "");
});

client.On("speech_end", _ =>
{
    printer.Newline();
    Console.WriteLine("[speech_end]");
    speechEnded.Set();
});

client.On("state_changed", msg =>
{
    var state = msg["state"]?.GetValue<string>() ?? "";
    Console.WriteLine($"[state_changed] {state}");
    if (state == "listening")
        started.Set();
});

client.On("error", msg =>
    Console.Error.WriteLine($"[error] {msg["message"]?.GetValue<string>() ?? ""}"));

client.StartListening();
client.Subscribe();

client.SendCommand("get_state");
if (!stateReceived.Wait(TimeSpan.FromSeconds(5)))
{
    Console.Error.WriteLine("Timed out waiting for server state.");
    return 1;
}

var attached = activeStates.Contains(currentState);
if (attached)
{
    Console.WriteLine(
        $"STT server already running (state: {currentState}); attaching to the existing session.\n");
    started.Set();
}
else
{
    // Ask the server for the available input devices.
    client.SendCommand("list_devices");
    if (!devicesReceived.Wait(TimeSpan.FromSeconds(5)))
    {
        Console.Error.WriteLine("Timed out waiting for device list.");
        return 1;
    }

    Console.WriteLine("Available input devices:");
    foreach (var d in devices)
        Console.WriteLine($"  [{d.Index}] {d.Name} ({d.Channels} ch)");

    Console.Write("\nSelect a device index (blank = server default): ");
    var choice = Console.ReadLine()?.Trim();
    int? device = string.IsNullOrEmpty(choice) ? null : int.Parse(choice);
    client.SendCommand("set_device",
        new JsonObject { ["device"] = device.HasValue ? JsonValue.Create(device.Value) : null });

    Console.WriteLine("\nStarting transcription. Speak into the mic; Ctrl+C to stop.\n");
    client.SendCommand("start");
}

// Block until Ctrl+C, then pause the server cleanly (unless we only attached
// to a session another process started).
var stop = new ManualResetEventSlim(false);
Console.CancelKeyPress += (_, e) =>
{
    e.Cancel = true;   // don't let the runtime kill us before we pause
    stop.Set();
};

started.Wait(TimeSpan.FromSeconds(10));
stop.Wait();

if (attached)
{
    Console.WriteLine("\nDetaching (leaving the existing session running)...");
}
else
{
    Console.WriteLine("\nPausing...");
    client.SendCommand("pause");
}
return 0;

/// <summary>Overwrites an in-place block of one or more terminal lines.</summary>
class LinePrinter
{
    private int _height;

    public void Overwrite(params string[] lines)
    {
        var rows = Math.Max(lines.Length, _height);
        if (_height > 0)
        {
            if (_height > 1)
                Console.Write($"\x1b[{_height - 1}A");
            Console.Write("\r");
        }
        for (var i = 0; i < rows; i++)
        {
            var line = i < lines.Length ? lines[i] : "";
            Console.Write($"\x1b[2K{line}");
            if (i < rows - 1)
                Console.Write("\n");
        }
        Console.Out.Flush();
        _height = rows;
    }

    public void Newline()
    {
        if (_height > 0)
            Console.WriteLine();
        _height = 0;
    }
}
