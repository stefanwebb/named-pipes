"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import errno
import importlib.metadata
import json
import os
import stat
import subprocess


def get_version() -> str:
    """Return the installed package version.

    For editable installs, appends git commit info when not on a tagged commit:
    e.g. "0.3.0" at the tag, or "0.3.0-3-gabcdef" three commits ahead.
    Falls back to importlib.metadata for non-editable installs or when git is unavailable.
    """
    try:
        dist = importlib.metadata.Distribution.from_name("named-pipes")
        direct_url_text = dist.read_text("direct_url.json")
        if direct_url_text:
            direct_url = json.loads(direct_url_text)
            if direct_url.get("dir_info", {}).get("editable", False):
                src_dir = direct_url.get("url", "").removeprefix("file://")
                result = subprocess.run(
                    ["git", "describe", "--tags", "--long"],
                    cwd=src_dir,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    # Format from git: v0.3.0-3-gabcdef
                    parts = result.stdout.strip().rsplit("-", 2)
                    tag = parts[0].lstrip("v")
                    n_commits = int(parts[1])
                    commit_hash = parts[2]
                    if n_commits == 0:
                        return tag
                    return f"{tag}-{n_commits}-{commit_hash}"
    except Exception:
        pass
    return importlib.metadata.version("named-pipes")


def ensure_pipe(path):
    if not os.path.exists(path):
        os.mkfifo(path)


def remove_pipe(path):
    if os.path.exists(path):
        os.remove(path)


def _is_fifo_connected(path: str) -> bool:
    """Return True if at least one process has the read end of *path* open.

    Uses a non-blocking O_WRONLY open: this succeeds instantly when a reader
    exists and fails with ENXIO when none does.  Works on Linux and macOS
    without spawning any subprocess or enumerating processes.

    Processes that open the FIFO O_RDWR (as our servers do) count as readers,
    so the test correctly identifies live server pipes.  The temporary write-end
    fd is closed immediately; because the server already holds O_RDWR the
    reference count never drops to zero and no POLLHUP is delivered to readers.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno == errno.ENXIO:
            return False
        raise
    try:
        os.close(fd)
    except OSError:
        pass
    return True


def get_pids_for_pipe(pipe_path: str) -> list[int]:
    """Return the PIDs of all processes that currently have *pipe_path* open.

    Uses /proc on Linux (psutil omits FIFOs on some kernels) and lsof on macOS
    and other platforms.
    """
    # Linux: /proc/<pid>/fd symlinks
    try:
        pid_strs = [e for e in os.listdir("/proc") if e.isdigit()]
        pids = []
        for pid_str in pid_strs:
            fd_dir = f"/proc/{pid_str}/fd"
            try:
                for fd in os.listdir(fd_dir):
                    try:
                        if os.readlink(f"{fd_dir}/{fd}") == pipe_path:
                            pids.append(int(pid_str))
                            break
                    except OSError:
                        pass
            except OSError:
                pass
        return pids
    except OSError:
        pass

    # macOS / other: lsof cannot look up FIFOs by path argument.
    # Reuse scan_pipes on the parent directory (single lsof call).
    folder = os.path.dirname(os.path.abspath(pipe_path))
    result = scan_pipes(folder, with_pids=True)
    for entry in result["connected"]:
        if entry["path"] == pipe_path:
            return entry["pids"]
    return []


def list_fifos(folder: str = "/tmp") -> list[str]:
    """Return all FIFO paths found under *folder*, sorted."""
    fifos: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(folder):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                if stat.S_ISFIFO(os.stat(path).st_mode):
                    fifos.append(path)
            except OSError:
                pass
    return sorted(fifos)


def scan_pipes(folder: str = "/tmp", *, with_pids: bool = False) -> dict:
    """Scan *folder* for named pipes and classify as connected or orphaned.

    Returns::

        {
            "connected": [{"path": str, "pids": [int, ...]}, ...],
            "orphaned":  [str, ...],
        }

    When *with_pids* is False (the default), connected/orphaned status is
    determined by attempting a non-blocking O_WRONLY open on each FIFO —
    O(1) per pipe, no subprocess, works on Linux and macOS.

    When *with_pids* is True, a full process scan is performed (/proc on
    Linux, lsof on macOS) to populate the ``pids`` lists.  This is slower
    but returns the PID(s) of every process that has each pipe open.
    """
    fifos = list_fifos(folder)
    if not fifos:
        return {"connected": [], "orphaned": []}

    if not with_pids:
        connected: list[dict] = []
        orphaned: list[str] = []
        for path in fifos:
            if _is_fifo_connected(path):
                connected.append({"path": path, "pids": []})
            else:
                orphaned.append(path)
        return {"connected": connected, "orphaned": orphaned}

    # --- with_pids=True: full process scan ---
    # Resolve symlinks: lsof reports real paths (e.g. /private/tmp on macOS).
    fifo_pairs: list[tuple[str, str]] = [(p, os.path.realpath(p)) for p in fifos]
    real_set = {real for _, real in fifo_pairs}
    path_pids: dict[str, list[int]] = {}  # keyed by real path

    # Linux: read /proc/<pid>/fd symlinks directly.
    proc_used = False
    try:
        pid_strs = [e for e in os.listdir("/proc") if e.isdigit()]
        for pid_str in pid_strs:
            fd_dir = f"/proc/{pid_str}/fd"
            try:
                for fd in os.listdir(fd_dir):
                    try:
                        target = os.readlink(f"{fd_dir}/{fd}")
                        if target in real_set:
                            path_pids.setdefault(target, []).append(int(pid_str))
                    except OSError:
                        pass
            except OSError:
                pass
        proc_used = True
    except OSError:
        pass

    # macOS / other: lsof cannot look up FIFOs by path — full scan required.
    # Output format: "p<pid>\nf<fd>\nn<path>\nf<fd>\nn<path>..." per process.
    if not proc_used:
        try:
            result = subprocess.run(
                ["lsof", "-F", "pn"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            current_pid: int | None = None
            for line in result.stdout.splitlines():
                if line.startswith("p"):
                    try:
                        current_pid = int(line[1:])
                    except ValueError:
                        current_pid = None
                elif line.startswith("n") and current_pid is not None:
                    real_path = line[1:]
                    if real_path in real_set:
                        path_pids.setdefault(real_path, []).append(current_pid)
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass

    connected_pids: list[dict] = []
    orphaned_list: list[str] = []
    for orig, real in fifo_pairs:
        pids = path_pids.get(real, [])
        if pids:
            connected_pids.append({"path": orig, "pids": sorted(set(pids))})
        else:
            orphaned_list.append(orig)

    return {"connected": connected_pids, "orphaned": orphaned_list}
