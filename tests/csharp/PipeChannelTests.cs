using System.Diagnostics;
using System.Threading.Channels;
using Xunit;

public class PipeChannelTests : IDisposable
{
    private readonly string _pipeName;
    private readonly Process _server;
    private readonly PipeChannel _channel;
    private readonly Channel<MessageReceivedEventArgs> _messages;
    private readonly Channel<DataReceivedEventArgs> _data;

    public PipeChannelTests()
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
        var script   = Path.Combine(repoRoot, "tests", "server_main.py");

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
    public async Task Ping_ReturnsPong()
    {
        _channel.SendMessage("PING");
        var msg = await NextMessage();
        Assert.Equal("PONG", msg.Cmd);
    }

    [Fact]
    public async Task Greet_ReturnsGreeting()
    {
        _channel.SendMessage("GREET", "World");
        var msg = await NextMessage();
        Assert.Equal("GREET", msg.Cmd);
        Assert.Equal("Hello, World!", msg.Data);
    }

    [Fact]
    public async Task Time_ReturnsTimestamp()
    {
        _channel.SendMessage("TIME");
        var msg = await NextMessage();
        Assert.Equal("TIME", msg.Cmd);
        Assert.False(string.IsNullOrEmpty(msg.Data));
    }

    [Fact]
    public async Task Echo_ReturnsData()
    {
        _channel.SendMessage("ECHO", "hello there");
        var msg = await NextMessage();
        Assert.Equal("ECHO", msg.Cmd);
        Assert.Equal("hello there", msg.Data);
    }

    [Fact]
    public async Task SendBytes_EchoesBytes()
    {
        byte[] payload = [1, 2, 3, 4, 5, 255, 128, 0];
        _channel.SendMessage("SEND_BYTES");
        _channel.SendData(payload);

        var dataEvt = await NextData();
        Assert.Equal(payload, dataEvt.Data);

        var msgEvt = await NextMessage();
        Assert.Equal("OK", msgEvt.Cmd);
    }

    [Fact]
    public async Task Quit_ReceivesBye()
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
