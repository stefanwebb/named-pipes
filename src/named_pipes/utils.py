"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import os

import psutil


def ensure_pipe(path):
    if not os.path.exists(path):
        os.mkfifo(path)


def remove_pipe(path):
    if os.path.exists(path):
        os.remove(path)


def get_pids_for_pipe(pipe_path):
    pids = []
    for proc in psutil.process_iter():
        try:
            for f in proc.open_files():
                if f.path == pipe_path:
                    pids.append(proc.pid)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return pids
