import os, sys, winsound, time, ctypes

if len(sys.argv) < 2:
    raise SystemExit(1)
path = sys.argv[1]
parent_pid = int(sys.argv[2]) if len(sys.argv) >= 3 else 0

# 监视主程序：如果用户直接关掉 CMD / 主程序异常退出，
# 播放器也会自动结束，避免背景音乐继续播放。
def parent_alive(pid):
    if not pid:
        return True
    PROCESS_SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    WAIT_FAILED = 0xFFFFFFFF
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not h:
        return False
    try:
        r = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
        return r == WAIT_TIMEOUT
    finally:
        ctypes.windll.kernel32.CloseHandle(h)

try:
    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
    while parent_alive(parent_pid):
        time.sleep(0.5)
except (KeyboardInterrupt, SystemExit):
    pass
except Exception:
    pass
finally:
    try:
        winsound.PlaySound(None, 0)
    except Exception:
        pass
