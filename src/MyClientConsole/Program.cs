using var channel = new PipeChannel("/tmp/agent");

var done = new ManualResetEventSlim();

byte[] payload = [1, 2, 3, 4, 5, 255, 128, 0];

// Remaining commands to send; each is dispatched from the listener thread
// after the previous response arrives.
Queue<Action> steps = new([
    () => channel.SendMessage("GREET", "World"),
    () => channel.SendMessage("TIME"),
    () => channel.SendMessage("ECHO", "hello there"),
    () =>
    {
        // SEND_BYTES: send command + data; the data listener thread will fire
        // DataReceived when Python echoes the bytes back, and the message
        // listener will then pick up the "OK" status message independently.
        Console.WriteLine($"  Sending data: [{string.Join(", ", payload)}]");
        channel.SendMessage("SEND_BYTES");
        channel.SendData(payload);
    },
    () => channel.SendMessage("QUIT"),
]);

channel.MessageReceived += (_, e) =>
{
    Console.WriteLine($"Response: cmd={e.Cmd} data={e.Data}");

    if (e.Cmd == "BYE")
    {
        done.Set();
        return;
    }

    if (steps.TryDequeue(out var next))
        next();
};

channel.DataReceived += (_, e) =>
    Console.WriteLine($"Data:     [{string.Join(", ", e.Data)}]");

channel.StartListening();

// Kick off the chain from the main thread
Console.WriteLine("Sending:  PING");
channel.SendMessage("PING");

done.Wait();
