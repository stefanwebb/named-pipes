// C# ToolClient demo — connects to a Python ToolServer and sends commands.
//
// Start the demo Python server first, or let this program launch it:
//   python src/examples/demo_server.py
//
// Then:
//   cd src/MyClientConsole && dotnet run

using System.Diagnostics;
using System.Text.Json.Nodes;

const string ToolName = "demo";
var pipePath = $"/tmp/tool-{ToolName}";

if (!File.Exists(pipePath))
{
    Console.WriteLine("Server pipe not found; launching Python demo server ...");
    var script = Path.Combine(FindProjectRoot(), "src", "examples", "demo_server.py");
    Process.Start(new ProcessStartInfo
    {
        FileName = "python",
        Arguments = $"\"{script}\"",
        UseShellExecute = false,
    });
}

// Wait up to 5 s for the server's upstream FIFO to appear
var deadline = DateTime.UtcNow.AddSeconds(5);
while (!File.Exists(pipePath) && DateTime.UtcNow < deadline)
    Thread.Sleep(100);

if (!File.Exists(pipePath))
{
    Console.Error.WriteLine($"Timed out waiting for {pipePath}. Is the Python server running?");
    return 1;
}

using var client = new ToolClient(ToolName);
var stoppingSeen = new ManualResetEventSlim(false);

client.On("pong",          _ => Console.WriteLine("< pong"));
client.On("state",         msg => Console.WriteLine($"< state: {msg["state"]}"));
client.On("description",   msg => Console.WriteLine($"< description: {msg["description"]}"));
client.On("greeting",      msg => Console.WriteLine($"< greeting: {msg["message"]}"));
client.On("state_changed", msg =>
{
    Console.WriteLine($"< state_changed -> {msg["state"]}");
    if (msg["state"]?.GetValue<string>() == "stopping")
        stoppingSeen.Set();
});

client.StartListening();
client.Subscribe();

Console.WriteLine("> ping");            client.SendCommand("ping");
Console.WriteLine("> get_state");      client.SendCommand("get_state");
Console.WriteLine("> get_description"); client.SendCommand("get_description");
Console.WriteLine("> greet Alice");    client.SendCommand("greet", new JsonObject { ["name"] = "Alice" });

Thread.Sleep(300); // let responses arrive before stopping

Console.WriteLine("> stop");
client.SendCommand("stop");
stoppingSeen.Wait(TimeSpan.FromSeconds(3));

Console.WriteLine("Done.");
return 0;

static string FindProjectRoot()
{
    var dir = new DirectoryInfo(AppContext.BaseDirectory);
    while (dir.Parent is not null && !Directory.Exists(Path.Combine(dir.FullName, "src")))
        dir = dir.Parent;
    return dir.FullName;
}
