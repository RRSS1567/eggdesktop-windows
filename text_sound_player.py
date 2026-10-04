# -*- coding: utf-8 -*-
"""EggDesktop Windows text-sound worker.
Receives one command per line on stdin and plays the supplied WAV synchronously.
The parent PID is monitored so closing the main CMD also ends this worker.
"""
import ctypes
import os
import sys
import time
import winsound

if len(sys.argv) < 3:
    raise SystemExit(1)

sound_path = sys.argv[1]
parent_pid = int(sys.argv[2])


def parent_alive(pid):
    PROCESS_SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not h:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
    finally:
        ctypes.windll.kernel32.CloseHandle(h)

try:
    while parent_alive(parent_pid):
        line = sys.stdin.buffer.readline()
        if not line:
            break
        try:
            # The main process sends only a single byte as a trigger.
            # Use the complete WAV path from argv rather than trusting stdin.
            winsound.PlaySound(sound_path, winsound.SND_FILENAME)
        except Exception:
            pass
except Exception:
    pass
finally:
    try:
        winsound.PlaySound(None, 0)
    except Exception:
        pass
