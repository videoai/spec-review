using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace SpecReview;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--open-url")
        {
            if (Uri.TryCreate(args[1], UriKind.Absolute, out var uri) && uri.Scheme == "https" && uri.Host == "github.com")
                Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
            return;
        }
        ApplicationConfiguration.Initialize();
        Application.Run(new ReviewWindow(args.Contains("--smoke-test")));
    }
}

internal sealed class ReviewWindow : Form
{
    private readonly WebView2 web = new() { Dock = DockStyle.Fill };
    private readonly string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ONVIF Spec Review");
    private readonly bool smoke;
    private Process? backend;
    private ProcessJob? job;
    private Uri? origin;
    private bool stopping;
    private bool switching;
    private bool allowClose;
    private bool checkingClose;
    private string RepositoryFile => Path.Combine(root, "repository.json");
    private static readonly HashSet<string> Repositories = ["onvif/specs", "videoai/test-specs"];

    public ReviewWindow(bool smoke)
    {
        this.smoke = smoke;
        Text = "ONVIF Spec Review";
        Width = 1280; Height = 900; MinimumSize = new Size(820, 600);
        StartPosition = FormStartPosition.CenterScreen;
        Controls.Add(web);
        Shown += async (_, _) => await Initialize();
        FormClosing += OnClosing;
    }

    private async Task Initialize()
    {
        try
        {
            Directory.CreateDirectory(root);
            var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(root, "WebView2"));
            await web.EnsureCoreWebView2Async(environment);
            web.CoreWebView2.Settings.AreDevToolsEnabled = false;
            web.CoreWebView2.Settings.AreHostObjectsAllowed = false;
            web.CoreWebView2.NavigationStarting += NavigationStarting;
            web.CoreWebView2.NewWindowRequested += (_, e) =>
            {
                e.Handled = true;
                if (Uri.TryCreate(e.Uri, UriKind.Absolute, out var url))
                {
                    if (Local(url)) web.CoreWebView2.Navigate(url.AbsoluteUri);
                    else OpenExternal(url);
                }
            };
            web.CoreWebView2.PermissionRequested += (_, e) => e.State = CoreWebView2PermissionState.Deny;
            web.CoreWebView2.WebMessageReceived += MessageReceived;
            await web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync("if(window===window.top){window.print=()=>window.chrome.webview.postMessage({action:'print'});}");
            if (smoke)
            {
                // CI checks the actual WebView2 host/bridge with no GitHub login or data.
                web.CoreWebView2.NavigateToString("<html><body><h1>Windows host smoke test</h1><script>window.chrome.webview.postMessage({action:'smoke-ready'});</script></body></html>");
                var timer = new System.Windows.Forms.Timer { Interval = 30000 };
                timer.Tick += (_, _) => { timer.Stop(); Environment.ExitCode = 1; allowClose = true; Close(); };
                timer.Start();
                return;
            }
            await StartBackend();
        }
        catch (WebView2RuntimeNotFoundException)
        {
            MessageBox.Show(this, "Install Microsoft Edge WebView2 Runtime, then reopen the app.\n\nThe download link is included in READ ME.txt.", Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
            Environment.ExitCode = 1; allowClose = true; Close();
        }
        catch (Exception error) { Fail(error); }
    }

    private string SelectedRepository()
    {
        try
        {
            var value = JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(RepositoryFile));
            if (value != null && value.TryGetValue("repository", out var repo) && Repositories.Contains(repo)) return repo;
        }
        catch (Exception error) when (error is IOException or JsonException) { }
        return "onvif/specs";
    }

    private async Task StartBackend()
    {
        web.CoreWebView2.NavigateToString("<body style='font:20px system-ui;padding:60px;color:#164536'><h1>ONVIF Spec Review</h1><p>Opening your review workspace…</p></body>");
        var folder = AppContext.BaseDirectory;
        var start = new ProcessStartInfo(Path.Combine(folder, "backend", "spec-review-service.exe"))
        {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            WorkingDirectory = root
        };
        start.Environment["PATH"] = string.Join(Path.PathSeparator, Path.Combine(folder, "tools", "gh", "bin"), Path.Combine(folder, "tools", "git", "cmd"), Environment.GetEnvironmentVariable("PATH") ?? "");
        start.Environment["GIT_EXEC_PATH"] = Path.Combine(folder, "tools", "git", "mingw64", "libexec", "git-core");
        start.Environment["GIT_TEMPLATE_DIR"] = Path.Combine(folder, "tools", "git", "mingw64", "share", "git-core", "templates");
        start.Environment["XML_REVIEW_APP_SUPPORT"] = root;
        start.Environment["XML_REVIEW_GITHUB_REPO"] = SelectedRepository();
        start.Environment["GH_BROWSER"] = "\"" + Environment.ProcessPath + "\" --open-url";
        var process = new Process { StartInfo = start, EnableRaisingEvents = true };
        backend = process;
        var ready = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var log = Path.Combine(root, "backend.log");
        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data?.StartsWith("SPEC_REVIEW_READY ") == true)
            {
                try { ready.TrySetResult(JsonDocument.Parse(e.Data[18..]).RootElement.GetProperty("url").GetString()!); }
                catch (Exception error) { ready.TrySetException(error); }
            }
            // Bootstrap/session URLs deliberately never go to logs.
        };
        process.ErrorDataReceived += (_, e) => { if (e.Data != null) { try { lock (this) File.AppendAllText(log, e.Data + Environment.NewLine); } catch (IOException) { } } };
        process.Exited += (_, _) =>
        {
            ready.TrySetException(new InvalidOperationException("The local service stopped. See " + log));
            if (!stopping && !switching && backend == process && IsHandleCreated)
                BeginInvoke(new Action(() => Fail(new InvalidOperationException("The local service stopped. Reopen the app. Logs: " + log))));
        };
        process.Start();
        job = new ProcessJob(); job.Add(process);
        process.BeginOutputReadLine(); process.BeginErrorReadLine();
        var raw = await ready.Task.WaitAsync(TimeSpan.FromSeconds(120));
        origin = new Uri(raw);
        web.CoreWebView2.Navigate(raw);
    }

    private bool Local(Uri url) => origin != null && url.Scheme == "http" && url.Host == "127.0.0.1" && url.Port == origin.Port;
    private void NavigationStarting(object? sender, CoreWebView2NavigationStartingEventArgs e)
    {
        if (!Uri.TryCreate(e.Uri, UriKind.Absolute, out var url)) { e.Cancel = true; return; }
        if (url.Scheme == "about" || Local(url)) return;
        e.Cancel = true; OpenExternal(url);
    }
    private static void OpenExternal(Uri url)
    {
        if (url.Scheme is "https" or "http") Process.Start(new ProcessStartInfo(url.AbsoluteUri) { UseShellExecute = true });
    }

    private async void MessageReceived(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        try
        {
            using var document = JsonDocument.Parse(e.WebMessageAsJson);
            var data = document.RootElement;
            var action = data.GetProperty("action").GetString();
            if (smoke && action == "smoke-ready") { allowClose = true; Close(); return; }
            if (!Uri.TryCreate(e.Source, UriKind.Absolute, out var source) || !Local(source)) return;
            string TextValue() => data.TryGetProperty("text", out var value) ? value.GetString() ?? "" : "";
            switch (action)
            {
                case "copy": Clipboard.SetText(TextValue()); break;
                case "save":
                    using (var dialog = new SaveFileDialog { FileName = Path.GetFileName(data.GetProperty("name").GetString()), OverwritePrompt = true })
                        if (dialog.ShowDialog(this) == DialogResult.OK) await File.WriteAllTextAsync(dialog.FileName, TextValue());
                    break;
                case "print": web.CoreWebView2.ShowPrintUI(CoreWebView2PrintDialogKind.System); break;
                case "repository":
                    var repository = TextValue();
                    if (!Repositories.Contains(repository) || switching) return;
                    switching = true;
                    try
                    {
                        await File.WriteAllTextAsync(RepositoryFile, JsonSerializer.Serialize(new { repository }));
                        StopBackend(); origin = null; await StartBackend();
                    }
                    finally { switching = false; }
                    break;
            }
        }
        catch (Exception error) { Fail(error); }
    }

    private async void OnClosing(object? sender, FormClosingEventArgs e)
    {
        if (!allowClose && !checkingClose && web.CoreWebView2 != null && !smoke)
        {
            e.Cancel = true; checkingClose = true;
            try
            {
                var dirty = await web.CoreWebView2.ExecuteScriptAsync("typeof dirty==='function'&&(dirty()||saving>0)");
                if (dirty == "true" && MessageBox.Show(this, "Discard the unsaved note and close?", Text, MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
                allowClose = true; Close();
            }
            finally { checkingClose = false; }
            return;
        }
        if (!allowClose && checkingClose) { e.Cancel = true; return; }
        stopping = true; StopBackend();
    }
    private void StopBackend()
    {
        job?.Dispose(); job = null;
        if (backend != null)
        {
            try { if (!backend.HasExited) backend.Kill(entireProcessTree: true); } catch (InvalidOperationException) { }
            backend.Dispose(); backend = null;
        }
    }
    private void Fail(Exception error) => MessageBox.Show(this, error.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
}

// Closing this handle terminates the private service, Git and gh even if the UI crashes.
internal sealed class ProcessJob : IDisposable
{
    private readonly nint handle;
    public ProcessJob()
    {
        handle = CreateJobObject(nint.Zero, null);
        if (handle == nint.Zero) throw new System.ComponentModel.Win32Exception();
        var limits = new ExtendedLimits(); limits.Basic.LimitFlags = 0x2000;
        if (!SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf<ExtendedLimits>())) throw new System.ComponentModel.Win32Exception();
    }
    public void Add(Process process) { if (!AssignProcessToJobObject(handle, process.Handle)) throw new System.ComponentModel.Win32Exception(); }
    public void Dispose() { if (handle != nint.Zero) CloseHandle(handle); }
    [StructLayout(LayoutKind.Sequential)] private struct BasicLimits { public long PerProcessUserTimeLimit, PerJobUserTimeLimit; public uint LimitFlags; public nuint MinimumWorkingSetSize, MaximumWorkingSetSize; public uint ActiveProcessLimit; public nuint Affinity; public uint PriorityClass, SchedulingClass; }
    [StructLayout(LayoutKind.Sequential)] private struct IoCounters { public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount, ReadTransferCount, WriteTransferCount, OtherTransferCount; }
    [StructLayout(LayoutKind.Sequential)] private struct ExtendedLimits { public BasicLimits Basic; public IoCounters Io; public nuint ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern nint CreateJobObject(nint attributes, string? name);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool SetInformationJobObject(nint job, int infoClass, ref ExtendedLimits info, uint length);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool AssignProcessToJobObject(nint job, nint process);
    [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool CloseHandle(nint handle);
}
