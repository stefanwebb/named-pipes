using System.Diagnostics;
using System.Text.Json;
using System.Threading.Channels;
using Xunit;

public class LLMPipeChannelTests : IDisposable
{
    private readonly string _pipeName;
    private readonly Process _server;
    private readonly PipeChannel _channel;
    private readonly Channel<MessageReceivedEventArgs> _messages;
    private readonly Channel<DataReceivedEventArgs> _data;

    public LLMPipeChannelTests()
    {
        _pipeName = $"/tmp/pipe-test-{Guid.NewGuid():N}";
        _server   = StartServer(_pipeName);

        _messages = Channel.CreateUnbounded<MessageReceivedEventArgs>();
        _data     = Channel.CreateUnbounded<DataReceivedEventArgs>();

        _channel = new PipeChannel(_pipeName);
        _channel.MessageReceived += (_, e) => _messages.Writer.TryWrite(e);
        _channel.DataReceived    += (_, e) => _data.Writer.TryWrite(e);
        _channel.StartListening();
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private static Process StartServer(string pipeName)
    {
        // Resolve repo root: output is …/tests/csharp/bin/Debug/net10.0/ — 5 levels up.
        var repoRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../.."));
        var script   = Path.Combine(repoRoot, "tests", "server_llm.py");

        var psi = new ProcessStartInfo
        {
            FileName               = "python3",
            Arguments              = $"{script} {pipeName}",
            WorkingDirectory       = repoRoot,
            RedirectStandardOutput = true,
            UseShellExecute        = false,
        };
        var proc = Process.Start(psi)!;

        // Wait until the server signals it is ready.
        while (true)
        {
            var line = proc.StandardOutput.ReadLine();
            if (line is null) throw new InvalidOperationException("Server exited before becoming ready.");
            if (line.Contains("Pipes open")) break;
        }
        return proc;
    }

    private async Task<MessageReceivedEventArgs> NextMessage(int timeoutMs = 5000)
    {
        using var cts = new CancellationTokenSource(timeoutMs);
        return await _messages.Reader.ReadAsync(cts.Token);
    }

    private async Task<DataReceivedEventArgs> NextData(int timeoutMs = 5000)
    {
        using var cts = new CancellationTokenSource(timeoutMs);
        return await _data.Reader.ReadAsync(cts.Token);
    }

    // -----------------------------------------------------------------------
    // Tests
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Chat_ReturnsChatResponse()
    {
        var conversation = new[]
        {
            new { role = "user", content = "Hello!" },
        };
        var json = JsonSerializer.Serialize(conversation);

        _channel.SendMessage("CHAT", json);
        var msg = await NextMessage();

        Assert.Equal("CHAT_RESPONSE", msg.Cmd);
        Assert.False(string.IsNullOrEmpty(msg.Data));
    }

    [Fact]
    public async Task Chat_Quit_ReceivesBye()
    {
        _channel.SendMessage("QUIT");
        var msg = await NextMessage();
        Assert.Equal("BYE", msg.Cmd);
    }

    // -----------------------------------------------------------------------
    // Cleanup
    // -----------------------------------------------------------------------

    public void Dispose()
    {
        _channel.Dispose();
        try { _server.Kill(); } catch { /* already exited */ }
        _server.Dispose();
    }
}
