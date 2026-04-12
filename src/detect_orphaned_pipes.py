"""
Detect orphaned named pipes under /tmp.

A pipe is considered orphaned when no running process currently has it open —
typically left behind by a process that crashed or exited without cleanup.

Usage:
    python src/detect_orphaned_pipes.py            # scan /tmp
    python src/detect_orphaned_pipes.py /var/tmp   # scan a different directory
"""

import os
import stat
import sys


def find_fifos(root: str) -> list[str]:
    """Return all FIFO (named pipe) paths found under *root*."""
    fifos = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                if stat.S_ISFIFO(os.stat(path).st_mode):
                    fifos.append(path)
            except OSError:
                # File disappeared or permission denied — skip it.
                pass
    return fifos


def open_file_paths() -> set[str]:
    """Return the set of all file paths currently open by any process.

    Reads /proc/<pid>/fd symlinks directly rather than using psutil.open_files(),
    because psutil silently omits FIFOs on some kernel versions.
    """
    paths: set[str] = set()
    try:
        pids = [e for e in os.listdir("/proc") if e.isdigit()]
    except OSError:
        return paths
    for pid in pids:
        fd_dir = f"/proc/{pid}/fd"
        try:
            for fd in os.listdir(fd_dir):
                try:
                    target = os.readlink(f"{fd_dir}/{fd}")
                    paths.add(target)
                except OSError:
                    pass
        except OSError:
            pass
    return paths


def detect_orphaned_pipes(root: str = "/tmp") -> dict[str, list[str]]:
    """
    Scan *root* for named pipes and classify each as connected or orphaned.

    Returns a dict with two keys:
        "connected"  – pipes open by at least one process
        "orphaned"   – pipes with no process holding them open
    """
    fifos = find_fifos(root)
    if not fifos:
        return {"connected": [], "orphaned": []}

    open_paths = open_file_paths()

    connected = []
    orphaned = []
    for path in sorted(fifos):
        if path in open_paths:
            connected.append(path)
        else:
            orphaned.append(path)

    return {"connected": connected, "orphaned": orphaned}


def main() -> None:
    root = sys.argv[1] if len(sys.argv) > 1 else "/tmp"

    if not os.path.isdir(root):
        print(f"error: {root!r} is not a directory", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {root!r} for named pipes ...\n")
    result = detect_orphaned_pipes(root)

    connected = result["connected"]
    orphaned = result["orphaned"]
    total = len(connected) + len(orphaned)

    if total == 0:
        print("No named pipes found.")
        return

    print(f"Found {total} named pipe(s): {len(connected)} connected, {len(orphaned)} orphaned.\n")

    if connected:
        print("Connected (open by a process):")
        for path in connected:
            print(f"  {path}")
        print()

    if orphaned:
        print("Orphaned (no process has these open):")
        for path in orphaned:
            print(f"  {path}")
    else:
        print("No orphaned pipes found.")


if __name__ == "__main__":
    main()
