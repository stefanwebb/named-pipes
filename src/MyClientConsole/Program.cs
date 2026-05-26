// C# ToolClient demo — connects to a chat ToolServer and sends a message.
//
// Start the chat server first:
//   python src/examples/chat_server.py
//
// Then:
//   cd src/MyClientConsole && dotnet run

using System.Text.Json.Nodes;

const string ToolName = "chat";
var pipePath = $"/tmp/tool-{ToolName}";

if (!File.Exists(pipePath))
{
    Console.Error.WriteLine($"Server pipe not found at {pipePath}. Is the chat server running?");
    return 1;
}

using var client = new ToolClient(ToolName);
var responseSeen = new ManualResetEventSlim(false);

client.EventReceived += (_, e) =>
{
    Console.WriteLine($"< {e.Event}: {e.Data.ToJsonString()}");
    responseSeen.Set();
};

client.StartListening();
client.Subscribe();

Console.WriteLine("> message: Hello, world!");
client.SendCommand("message", new JsonObject { ["content"] = "Hello, world!" });

responseSeen.Wait(TimeSpan.FromSeconds(5));

Console.WriteLine("Done.");
return 0;
