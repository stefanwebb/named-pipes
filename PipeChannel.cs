using System.Buffers.Binary;
using System.Text.Json;

class MessageReceivedEventArgs(string cmd, string data) : EventArgs
{
    public string Cmd  { get; } = cmd;
    public string Data { get; } = data;
}

class DataReceivedEventArgs(byte[] data) : EventArgs
{
    public byte[] Data { get; } = data;
}

class PipeChannel : IDisposable
{
    private readonly StreamWriter _msgWriter;
    private readonly StreamReader _msgReader;
    private readonly Stream       _dataWriter;
    private readonly Stream       _dataReader;

    private readonly Lock _msgWriteLock  = new();
    private readonly Lock _dataWriteLock = new();

    private Thread? _msgListenerThread;
    private Thread? _dataListenerThread;

    public event EventHandler<MessageReceivedEventArgs>? MessageReceived;
    public event EventHandler<DataReceivedEventArgs>?    DataReceived;

    public PipeChannel(string pipeName = "/tmp/agent")
    {
        var msgSend  = new FileStream($"{pipeName}-cmd-upstream",   FileMode.Open, FileAccess.Write, FileShare.ReadWrite);
        var msgRecv  = new FileStream($"{pipeName}-cmd-downstream", FileMode.Open, FileAccess.Read,  FileShare.ReadWrite);
        var dataSend = new FileStream($"{pipeName}-data-upstream",  FileMode.Open, FileAccess.Write, FileShare.ReadWrite);
        var dataRecv = new FileStream($"{pipeName}-data-downstream",FileMode.Open, FileAccess.Read,  FileShare.ReadWrite);

        _msgWriter  = new StreamWriter(msgSend)  { AutoFlush = true };
        _msgReader  = new StreamReader(msgRecv);
        _dataWriter = dataSend;
        _dataReader = dataRecv;
    }

    // --- send (thread-safe) ---

    public void SendMessage(string cmd, string data = "")
    {
        var json = JsonSerializer.Serialize(new { cmd, data });
        lock (_msgWriteLock)
            _msgWriter.WriteLine(json);
    }

    public void SendData(byte[] data)
    {
        Span<byte> lengthBuf = stackalloc byte[4];
        BinaryPrimitives.WriteInt32BigEndian(lengthBuf, data.Length);
        lock (_dataWriteLock)
        {
            _dataWriter.Write(lengthBuf);
            _dataWriter.Write(data);
            _dataWriter.Flush();
        }
    }

    // --- listener threads ---

    public void StartListening()
    {
        _msgListenerThread = new Thread(MsgListenerLoop)
        {
            IsBackground = true,
            Name         = "MsgListener",
        };
        _dataListenerThread = new Thread(DataListenerLoop)
        {
            IsBackground = true,
            Name         = "DataListener",
        };
        _msgListenerThread.Start();
        _dataListenerThread.Start();
    }

    public void StopListening()
    {
        _msgReader.Close();    // unblocks ReadLine()
        _dataReader.Close();   // unblocks ReadExactly()
        _msgListenerThread?.Join();
        _dataListenerThread?.Join();
    }

    private void MsgListenerLoop()
    {
        try
        {
            while (true)
            {
                var line = _msgReader.ReadLine();
                if (line is null) break;

                using var doc = JsonDocument.Parse(line);
                var cmd  = doc.RootElement.GetProperty("cmd").GetString()  ?? "";
                var data = doc.RootElement.GetProperty("data").GetString() ?? "";
                MessageReceived?.Invoke(this, new MessageReceivedEventArgs(cmd, data));
            }
        }
        catch (ObjectDisposedException) { }
        catch (IOException)             { }
    }

    private void DataListenerLoop()
    {
        try
        {
            Span<byte> lengthBuf = stackalloc byte[4];
            while (true)
            {
                _dataReader.ReadExactly(lengthBuf);
                int    length = BinaryPrimitives.ReadInt32BigEndian(lengthBuf);
                byte[] data   = new byte[length];
                _dataReader.ReadExactly(data);
                DataReceived?.Invoke(this, new DataReceivedEventArgs(data));
            }
        }
        catch (ObjectDisposedException) { }
        catch (IOException)             { }
    }

    public void Dispose()
    {
        StopListening();
        _msgWriter.Dispose();
        _msgReader.Dispose();
        _dataWriter.Dispose();
        _dataReader.Dispose();
    }
}
