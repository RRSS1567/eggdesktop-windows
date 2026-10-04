#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eggdesktop —— "桌面与桌面之间,有个桌面"
全屏伪终端:在 macOS / Linux 的终端里复现 Deltarune 蛋房彩蛋。
纯标准库,无需安装任何依赖。全屏终端中运行: python3 eggdesktop.py
树以背景色块像素渲染(无双宽字符依赖), 21 帧摇曳动画常驻屏幕上方
(数据逐像素取自官方 tree.gif), 下方终端区域照常输入。
"""
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata

IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    def _enable_windows_ansi():
        try:
            kernel32 = ctypes.windll.kernel32
            h = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
                kernel32.SetConsoleMode(h, mode.value | 0x0004 | 0x0008)
        except Exception:
            pass

    _enable_windows_ansi()
    import winsound

# ===================== 音乐 =====================
MUSIC_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music", "egg_room.wav")
TEXT_SOUND_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music", "text_tick.wav")
MUSIC_PLAYER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_player.py")
TEXT_SOUND_PLAYER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "text_sound_player.py")
_MUSIC_STARTED = False
_MUSIC_PROC = None
_TEXT_SOUND_PROCS = []
_TEXT_SOUND_INDEX = 0
_TEXT_SOUND_LOCK = threading.Lock()
_TEXT_SOUND_WORKERS = 8

def start_behind_music():
    """循环播放场景音乐；单独进程播放，避免文字音效打断背景音乐。"""
    global _MUSIC_STARTED, _MUSIC_PROC
    if not IS_WINDOWS or _MUSIC_STARTED:
        return
    try:
        if os.path.isfile(MUSIC_FILE) and os.path.isfile(MUSIC_PLAYER):
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.isfile(pyw):
                pyw = sys.executable
            _MUSIC_PROC = subprocess.Popen(
                [pyw, MUSIC_PLAYER, MUSIC_FILE, str(os.getpid())],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            _MUSIC_STARTED = True
    except Exception:
        _MUSIC_PROC = None
        _MUSIC_STARTED = False

def stop_behind_music():
    """停止场景音乐。"""
    global _MUSIC_STARTED, _MUSIC_PROC
    if not IS_WINDOWS:
        return
    try:
        if _MUSIC_PROC and _MUSIC_PROC.poll() is None:
            _MUSIC_PROC.terminate()
            try:
                _MUSIC_PROC.wait(timeout=0.5)
            except Exception:
                _MUSIC_PROC.kill()
        else:
            winsound.PlaySound(None, 0)
    except Exception:
        pass
    _MUSIC_PROC = None
    _MUSIC_STARTED = False

# 无论是正常退出、Ctrl+C，还是窗口/CMD 被关闭，都尽量立即停止音乐。
import atexit
atexit.register(stop_behind_music)

def _ensure_text_sound_workers():
    """启动一小组独立声音进程，让多个字符音效可以重叠播放。"""
    global _TEXT_SOUND_PROCS
    if not IS_WINDOWS or not os.path.isfile(TEXT_SOUND_FILE) or not os.path.isfile(TEXT_SOUND_PLAYER):
        return
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pyw):
        pyw = sys.executable
    alive = [p for p in _TEXT_SOUND_PROCS if p.poll() is None and p.stdin is not None]
    _TEXT_SOUND_PROCS = alive
    while len(_TEXT_SOUND_PROCS) < _TEXT_SOUND_WORKERS:
        try:
            proc = subprocess.Popen(
                [pyw, TEXT_SOUND_PLAYER, TEXT_SOUND_FILE, str(os.getpid())],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            _TEXT_SOUND_PROCS.append(proc)
        except Exception:
            break

def stop_text_sound_workers():
    """结束所有文字音效工作进程。"""
    global _TEXT_SOUND_PROCS
    with _TEXT_SOUND_LOCK:
        for proc in _TEXT_SOUND_PROCS:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        for proc in _TEXT_SOUND_PROCS:
            try:
                proc.wait(timeout=0.3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        _TEXT_SOUND_PROCS = []


def play_text_sound():
    """每输出一个可见字符触发一次音效；8 个独立 worker 允许音效重叠。"""
    global _TEXT_SOUND_INDEX
    if not IS_WINDOWS:
        return
    with _TEXT_SOUND_LOCK:
        try:
            _ensure_text_sound_workers()
            if not _TEXT_SOUND_PROCS:
                return
            # 轮询分配。主程序每生成一个字符就写入一次触发信号。
            n = len(_TEXT_SOUND_PROCS)
            for _ in range(n):
                proc = _TEXT_SOUND_PROCS[_TEXT_SOUND_INDEX % n]
                _TEXT_SOUND_INDEX = (_TEXT_SOUND_INDEX + 1) % max(1, n)
                if proc.poll() is not None or proc.stdin is None:
                    continue
                try:
                    proc.stdin.write(b"1\n")
                    proc.stdin.flush()
                    return
                except Exception:
                    continue
        except Exception:
            pass

atexit.register(stop_text_sound_workers)

# ===================== 配置区(拍视频要改的都集中在这里) =====================
SHOW_DATE = None                    # 登录横幅日期: None = 跟随真实系统时间;
                                    # 拍视频时改成字符串, 如 "Thu Dec 25 09:41:03"
USER = "kris"                       # 提示符用户名
HOST = "eggdesktop"                 # 提示符主机名
TREE_COLS = None                    # 树的像素列数: None = 自动吃满终端(最高 100, 即官方贴图原生宽度);
                                    # 也可填固定数值。录制时把终端字号调小(Cmd+-)可获得更细的色块
USE_HALFBLOCK = False               # True = 用 ▀▄ 半块字符渲染, 同屏面积分辨率翻倍;
                                    # 仅在你的终端把 ▀ 显示为单宽时打开(出现折行/错位就关掉)
DELAY_LINE = 0.055                  # ASCII 树逐行打印间隔(秒)
DELAY_CHAR = 0.035                  # 对话打字机每字符间隔(秒)
PAUSE_BEFORE_MORPH = 1.4            # ASCII 成型后、突变为动画树前的停顿
PAUSE_BLACK = 1.6                   # cd .behind 后画面定格假死的时长(期间输入被吞掉)
PAUSE_WRONG = 2.0                   # 树后输错指令后, 报错原地停留几秒再刷新指令区
GLITCH_RATIO = 0.33                 # 假死时腐化为 ASCII 的色块比例(斑块状分布)
FRAME_DELAY = 0.30                  # 树动画每帧间隔(秒)
SPAWN_ON = "acquire"                # "exit": 退出终端后蛋出现在菜单栏
                                    # "acquire": 拿到蛋的瞬间就出现(选 Yes 的刹那)
# ===========================================================================

EGG_LINE = "没那么重要，也没那么不重要。"
EGGBAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eggbar")

PX = {"R": (0xE0, 0x20, 0x40),   # 树冠正红
      "P": (0xC0, 0x00, 0x80),   # 品红
      "M": (0xA0, 0x00, 0x80),   # 暗品红
      "N": (0x20, 0x20, 0x40)}   # 树干暗蓝紫
ASCII_CHAR = {"R": "#", "P": "*", "M": "%", "N": ":"}

# 由 build_art.py 从官方 tree.gif 生成, 勿手改
MASTER_COLS = 100
FRAMES = [['                                                              RRRRRRRRRRRRRRRR                      ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                 RRRRRRRRRRRRRRRRRRRRRRRRRRRRR                      ', '                                                RRRRRRRRRRRRRRRRRRRR                                ', '                          RRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRRR                                ', '                         RRRRRRRRRRRRRRRRRRP   PPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRPPP             ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMMPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRPPPPPPPPMMMMMMMMMMMMMMMMMMMPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPPPPPPPPMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRRPPPPPPPPMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRPPPPPPPPPPMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMMPPPPPPPPPPPPPMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRRR', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRRR', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPRR ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRPRRRRRRRRRRRRRRRRRRRRRRRRRPPPMMMMMMMMMMMMMPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                          RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMM                       ', '                                     MMMMMRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMM                        ', '                                          RRRRRRRRRRRRRRRNNP      NNNNNNNNNNNNNNN                   ', '                                          RRRRRRRRRRRRRRRNNP      NNNNNNNNNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRNNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRNNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRNNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRMNNPPPPPPMNNNNM                             ', '                                           RRRMNNNNNNNNNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                  RRRRRRRRRRRRRRRRRRRRRRRRRRRRR                     ', '                                                 RRRRRRRRRRRRRRRRRRR                                ', '                          RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                ', '                         RRRRRRRRRRRRRRRRRRRP   PPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRPP             ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMMPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRRRRPPPPPPPPMMMMMMMMMMMMMMMMMMMPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPPPMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRRRRRRRRRRRRPPPPPPPPPPMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMMPPPPPPPPPPPPPMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPRR ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPRRRRRRRRRRRRRRRRRRRRRRRRRPPMMMMMMMMMMMMMPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                          RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMM                       ', '                                     MMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMM                        ', '                                          RRRRRRRRRRRRRRRMNP      NNNNNNNNNNNNNNN                   ', '                                          RRRRRRRRRRRRRRRMNP      NNNNNNNNNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRMNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRMNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRMNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRRNNPPPPPPMNNNNM                             ', '                                           RRRMNNNNNNNNNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                  RRRRRRRRRRRRRRRRRRRRRRRRRRRRR                     ', '                                                 RRRRRRRRRRRRRRRRRRR                                ', '                          RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                ', '                         RRRRRRRRRRRRRRRRRRRP   PPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         PRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         PRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRPP             ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMMPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRRRPPPPPPPPPMMMMMMMMMMMMMMMMMMMPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPPPMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRRRRRRRRRRRRPPPPPPPPPMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPRR ', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPRRRRRRRRRRRRRRRRRRRRRRRRRPPMMMMMMMMMMMMPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                          RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMM                        ', '                                   MMMMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMM                        ', '                                    MMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMM                         ', '                                          RRRRRRRRRRRRRRRMNP      NNNNNNNNNNNNNNN                   ', '                                          RRRRRRRRRRRRRRRMNP      NNNNNNNNNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRMNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRMNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRMNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRRNNPPPPPPMNNNNM                             ', '                                           RRRMNNNNNNNNNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                  RRRRRRRRRRRRRRRRRRRRRRRRRRRRR                     ', '                                                 RRRRRRRRRRRRRRRRRRR                                ', '                          RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                ', '                         RRRRRRRRRRRRRRRRRRRP   PPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRPP             ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMMPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRRRRRRRRPPPPMMMMMMMMMMMMMMMMMMMPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRRRRRRRRRRRRPPPPPPPPPMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPPMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMMPPPPPPPPPPPPPMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR', '       MMMMMMPPPPPPPPPPPPMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPRR ', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPRRRRRRRRRRRRRRRRRRRRRRRRRPPMMMMMMMMMMMMPPPPPPPPP    ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM              ', '                          RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMM                        ', '                                   MMMMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMM                        ', '                                   MMMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMM                        ', '                                    MMMMMMRRRRRRRRRRRRRRRMMPMMMMMMMMMMMMMMNNNNNNN                   ', '                                          RRRRRRRRRRRRRRRMNP      NNNNNNNNNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRMNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRMNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRMNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRRNNPPPPPPMNNNNM                             ', '                                           RRRMNNNNNNNNNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                  RRRRRRRRRRRRRRRRRRRRRRRRRRRRR                     ', '                                                 RRRRRRRRRRRRRRRRRRR                                ', '                          RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                ', '                         RRRRRRRRRRRRRRRRRRRP   PPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRPP             ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMMPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRRRRRRRRPPPPMMMMMMMMMMMMMMMMMMMPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRRRRRRRRRRRRPPPPPPPPPMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPPMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMMPPPPPPPPPPPPPMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR', '       MMMMMMPPPPPPPPPPPPMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPRR ', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPRRRRRRRRRRRRRRRRRRRRRRRRRPPMMMMMMMMMMMMPPPPPPPPP    ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM              ', '                          RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMM                        ', '                                   MMMMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMM                        ', '                                   MMMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMM                        ', '                                    MMMMMMRRRRRRRRRRRRRRRMMPMMMMMMMMMMMMMMNNNNNNN                   ', '                                          RRRRRRRRRRRRRRRMNP      NNNNNNNNNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRMNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRMNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRMNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRRNNPPPPPPMNNNNM                             ', '                                           RRRMNNNNNNNNNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                  RRRRRRRRRRRRRRRRRRRRRRRRRRRRR                     ', '                                                 RRRRRRRRRRRRRRRRRRR                                ', '                          RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                ', '                         RRRRRRRRRRRRRRRRRRRP   PPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         PRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRPP             ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMMPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRRRRRRRRPPPPMMMMMMMMMMMMMMMMMMMPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRRRRRRRRRRRRPPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR', '       MMMMMMPPPPPPPPPPPPMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPRR ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPRRRRRRRRRRRRRRRRRRRRRRRRRPPMMMMMMMMMMMMPPPPPPPPP    ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM              ', '                          RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMM                         ', '                                  MMMMMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMM                         ', '                                  MMMMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMM                         ', '                                   MMMMMMMRRRRRRRRRRRRRRRMMPMMMMMMMMMMMMMMNNNNNNN                   ', '                                          RRRRRRRRRRRRRRRMNP      NNNNNNNNNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRMNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRMNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRMNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRRNNPPPPPPMNNNNM                             ', '                                           RRRMNNNNNNNNNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             PRRRRRRRRRRRRRRRRR                     ', '                                                  RRRRRRRRRRRRRRRRRR                                ', '                                                 RRRRRRRRRRRRRRRRRR                                 ', '                          RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRRP   PPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMMPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRP              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRPPPPP             ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRPPPPPRRRRRRPPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR', '       MMMMMMPPPPPPPPPPPPMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRR ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMPPPPPPPPPPPPPPP    ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMM              ', '                                  MMMMMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMM                         ', '                                  MMMMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMM                         ', '                                   MMMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMNNNNNNN                   ', '                                          RRRRRRRRRRRRRRRMNP      NNNNNNNNNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRMNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRMNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRMNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRRMNPPPPPPMNNNNM                             ', '                                           RRRRRRRRRRRRRNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             PRRRRRRRRRRRRRRRRR                     ', '                                                  RRRRRRRRRRRRRRRRRR                                ', '                                                 RRRRRRRRRRRRRRRRRR                                 ', '                          RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRRP   PPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMMPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRP              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRPPPPP             ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRPPPPPRRRRRRPPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR', '       MMMMMMPPPPPPPPPPPPMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRR ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMPPPPPPPPPPPPPPP    ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMM              ', '                                  MMMMMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMM                         ', '                                  MMMMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMM                         ', '                                   MMMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMNNNNNNN                   ', '                                          RRRRRRRRRRRRRRRMNP      NNNNNNNNNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRMNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRMNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRMNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRRMNPPPPPPMNNNNM                             ', '                                           RRRRRRRRRRRRRNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             RRRRRRRRRRRRRRRRRRR                    ', '                                                             PRRRRRRRRRRRRRRRRR                     ', '                                                  RRRRRRRRRRRRRRRRRR                                ', '                                                 RRRRRRRRRRRRRRRRRR                                 ', '                          RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRRP   PPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMMPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRP              ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRPPPPP             ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRRPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '  RRRRRPPPPPRRRRRRPPPPPPPPMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR', '       MMMMMMPPPPPPPPPPPPMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRR ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMPPPPPPPPPPPPPPP    ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMM              ', '                                  MMMMMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMM                         ', '                                  MMMMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMM                         ', '                                   MMMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMNNNNNNN                   ', '                                          RRRRRRRRRRRRRRRMNP      NNNNNNNNNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRMNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRMNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRMNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRRMNPPPPPPMNNNNM                             ', '                                           RRRRRRRRRRRRRNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRR                      ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             PRRRRRRRRRRRRRRRR                      ', '                                                 RRRRRRRRRRRRRRRRRRR                                ', '                                                RRRRRRRRRRRRRRRRRRR                                 ', '                          RRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRP   PPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                       RPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '             MMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRP              ', '             MMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRPPPPP             ', '             MMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '             MMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '             MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPPPPPPPMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRPPPPPRRRRRPPPPPPPPPMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR', '       MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRRR', '       MMMMMMPPPPPPPPPPPPMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRR ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMPPPPPPPPPPPPPPP    ', '       MMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM              ', '                                  MMMMMMMRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMM                         ', '                                  MMMMMMMMRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMM                         ', '                                  MMMMMMMMRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMNNNNNN                   ', '                                   MMMMMMMRRRRRRRRRRRRRRRMMPMMMMMMMMMMMMMMNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRNNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRNNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRNNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRRNNPPPPPPMNNNNM                             ', '                                           RRRRRRRRRRRRRNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRR                      ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             PRRRRRRRRRRRRRRRR                      ', '                                                 RRRRRRRRRRRRRRRRRRR                                ', '                                                RRRRRRRRRRRRRRRRRRR                                 ', '                          RRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRP   PPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                        MRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                       RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRP              ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRPPPPP             ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPPPPPPPPMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRPPPPPRRRRPPPPPPPPPPMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPPMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '       MMMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR', '       MMMMMMPPPPPPPPPPPPPMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRRR', '       MMMMMMPPPPPPPPPPPPMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRR ', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '       MMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMPPPPPPPPPPPPPPP    ', '       MMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '       MMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM              ', '                                   MMMMMMRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMM                        ', '                                   MMMMMMMRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMM                        ', '                                   MMMMMMMRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMNNNNNN                   ', '                                    MMMMMMRRRRRRRRRRRRRRRMMPMMMMMMMMMMMMMMNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRNNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRNNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRNNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRRNNPPPPPPMNNNNM                             ', '                                           RRRRRRRRRRRRRNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRR                      ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             PRRRRRRRRRRRRRRRR                      ', '                                                 RRRRRRRRRRRRRRRRRRR                                ', '                                                RRRRRRRRRRRRRRRRRRR                                 ', '                          RRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRRP   PPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                       RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRP              ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRPPPPP             ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '              MMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPPPPPPPPMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRPPPPPRRRRPPPPPPPPPPMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR', '        MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRRR', '        MMMMMMPPPPPPPPPPPPMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRR ', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                                   MMMMMMRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMM                        ', '                                   MMMMMMMRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMM                        ', '                                   MMMMMMMRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMNNNNN                   ', '                                    MMMMMMRRRRRRRRRRRRRRRMMPMMMMMMMMMMMMMMMNNNMMM                   ', '                                          RRRRRRRRRRRRRRRNNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRNNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRNNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRRNNPPPPPPMNNNNM                             ', '                                           RRRRRRRRRRRRRNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                             RRRRRRRRRRRRRRRRR                      ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            PRRRRRRRRRRRRRRRRR                      ', '                                                 RRRRRRRRRRRRRRRRRR                                 ', '                                                RRRRRRRRRRRRRRRRRR                                  ', '                         RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRRP   PPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR                ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                      RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR               ', '              MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '              MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '              MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRP               ', '              MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRPPPPP              ', '              MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR  ', '              MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '              MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '              MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '              MMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '              MMMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRPPPPPPPPMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', ' RRRRRRRPPPPPRRRRPPPPPPPPPPMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR ', '        MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR ', '        MMMMMMPPPPPPPPPPPPMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRR  ', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                                   MMMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMM                        ', '                                   MMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMM                        ', '                                   MMMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMNNNNN                   ', '                                    MMMMMRRRRRRRRRRRRRRRMMMPMMMMMMMMMMMMMMMNNNMMM                   ', '                                         RRRRRRRRRRRRRRRMNNP     MNNNNNNNNMMMMMPP                   ', '                                         RRRRRRRRRRRRRRRMNNP     MMNNNMMMMPPPP                      ', '                                         RRRRRRRRRRRRRRRMNNP     PMNNNMPPP                          ', '                                         RRRRRRRRRRRRRRRMNNPPPPPPMNNNNM                             ', '                                          RRRRRRRRRRRRRNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                             RRRRRRRRRRRRRRRRR                      ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            PRRRRRRRRRRRRRRRRR                      ', '                                                 RRRRRRRRRRRRRRRRRR                                 ', '                                                RRRRRRRRRRRRRRRRRR                                  ', '                         RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRRP   PPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR                ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                      RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                MMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRP               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRPPPPP              ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR  ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRPPPPPPPPPMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', ' RRRRRRRRPPPPRRRRPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR ', '        MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR ', '        MMMMMMPPPPPPPPPPPPMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRR  ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                                    MMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMNNNNN                   ', '                                     MMMMRRRRRRRRRRRRRRRMMMPMMMMMMMMMMMMMMMNNNMMM                   ', '                                         RRRRRRRRRRRRRRRMNNP     MNNNNNNNNMMMMMPP                   ', '                                         RRRRRRRRRRRRRRRMNNP     MMNNNMMMMPPPP                      ', '                                         RRRRRRRRRRRRRRRMNNP     PMNNNMPPP                          ', '                                         RRRRRRRRRRRRRRRMNNPPPPPPMNNNNM                             ', '                                          RRRRRRRRRRRRRNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                             RRRRRRRRRRRRRRRRR                      ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            PRRRRRRRRRRRRRRRRR                      ', '                                                 RRRRRRRRRRRRRRRRRR                                 ', '                                                RRRRRRRRRRRRRRRRRR                                  ', '                         RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRRP   PPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR                ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                      RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                MMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRP               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRPPPPP              ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR  ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRPPPPPPPPPMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', ' RRRRRRRRPPPPRRRRPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR ', '        MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR ', '        MMMMMMPPPPPPPPPPPPMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRR  ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                                    MMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMNNNNN                   ', '                                     MMMMRRRRRRRRRRRRRRRMMMPMMMMMMMMMMMMMMMNNNMMM                   ', '                                         RRRRRRRRRRRRRRRMNNP     MNNNNNNNNMMMMMPP                   ', '                                         RRRRRRRRRRRRRRRMNNP     MMNNNMMMMPPPP                      ', '                                         RRRRRRRRRRRRRRRMNNP     PMNNNMPPP                          ', '                                         RRRRRRRRRRRRRRRMNNPPPPPPMNNNNM                             ', '                                          RRRRRRRRRRRRRNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                             RRRRRRRRRRRRRRRRR                      ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            PRRRRRRRRRRRRRRRRR                      ', '                                                 RRRRRRRRRRRRRRRRRR                                 ', '                                                RRRRRRRRRRRRRRRRRR                                  ', '                         RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRRP   PPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR                ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                      RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                MMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRP               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRPPPPP              ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR  ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRPPPPPPPPPMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', ' RRRRRRRRPPPPPRRRPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR ', '         MMMMMPPPPPPPPPPPPPPMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR ', '         MMMMMMPPPPPPPPPPPPMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRR  ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '          MMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                                    MMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMNNNN                   ', '                                     MMMMRRRRRRRRRRRRRRRMMMPMMMMMMMMMMMMMMMMNNMMM                   ', '                                         RRRRRRRRRRRRRRRMNNP     MNNNNNNNNMMMMMPP                   ', '                                         RRRRRRRRRRRRRRRMNNP     MMNNNMMMMPPPP                      ', '                                         RRRRRRRRRRRRRRRMNNP     PMNNNMPPP                          ', '                                         RRRRRRRRRRRRRRRMNNPPPPPPMNNNNM                             ', '                                          RRRRRRRRRRRRRNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                             RRRRRRRRRRRRRRRRR                      ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            PRRRRRRRRRRRRRRRRR                      ', '                                                 RRRRRRRRRRRRRRRRRR                                 ', '                                                RRRRRRRRRRRRRRRRRR                                  ', '                         RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRRP   PPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR                ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRP               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRPPPPP              ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR  ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRPPPPPPPPPMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', ' RRRRRRRRPPPPPRRRPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR ', '         MMMMMPPPPPPPPPPPPPMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRR  ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '          MMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                                    MMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                     MMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMNNNNN                   ', '                                         RRRRRRRRRRRRRRRMNNP      NNNNNNNNNNNNMMM                   ', '                                         RRRRRRRRRRRRRRRMNNP     MNNNNNNNNMMMMMPP                   ', '                                         RRRRRRRRRRRRRRRMNNP     MMNNNMMMMPPPP                      ', '                                         RRRRRRRRRRRRRRRMNNP     PMNNNMPPP                          ', '                                         RRRRRRRRRRRRRRRMNNPPPPPPMNNNNM                             ', '                                          RRRRRRRRRRRRRNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                             RRRRRRRRRRRRRRRRR                      ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            PRRRRRRRRRRRRRRRRR                      ', '                                                 RRRRRRRRRRRRRRRRRR                                 ', '                                                RRRRRRRRRRRRRRRRRR                                  ', '                         RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRRP   PPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR                ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRP               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRPPPPP              ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR  ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRPPPPPPPPPMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', ' RRRRRRRRPPPPPRRRPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPRRRR ', '         MMMMMPPPPPPPPPPPPPMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRR  ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPPPPPPPPMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '          MMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                                    MMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                     MMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMNNNNN                   ', '                                         RRRRRRRRRRRRRRRMNNP      NNNNNNNNNNNNMMM                   ', '                                         RRRRRRRRRRRRRRRMNNP     MNNNNNNNNMMMMMPP                   ', '                                         RRRRRRRRRRRRRRRMNNP     MMNNNMMMMPPPP                      ', '                                         RRRRRRRRRRRRRRRMNNP     PMNNNMPPP                          ', '                                         RRRRRRRRRRRRRRRMNNPPPPPPMNNNNM                             ', '                                          RRRRRRRRRRRRRNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                             RRRRRRRRRRRRRRRRR                      ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                 RRRRRRRRRRRRRRRRRRRRRRRRRRRRR                      ', '                                                RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                 ', '                        RRRRRRRRRRRRRRRRRRRP   PPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR                ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        PRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                MMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRPP              ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR  ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', ' RRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRPPPPPPPPPMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', ' RRRRRRRRRRRRRRRRPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '         MMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRR ', '         MMMMMPPPPPPPPPPPPPMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPRR  ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMPPPPPPPPPPPPPPPP    ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRPRRRRRRRRRRRRRRRRRRRRRRRRRPPMMMMMMMMMMMMMMMMPPPPP     ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '          MMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                                    MMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                     MMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMNNNNN                   ', '                                         RRRRRRRRRRRRRRRMNNP      NNNNNNNNNNNNMMM                   ', '                                         RRRRRRRRRRRRRRRMNNP     MNNNNNNNNMMMMMPP                   ', '                                         RRRRRRRRRRRRRRRMNNP     MMNNNMMMMPPPP                      ', '                                         RRRRRRRRRRRRRRRMNNP     PMNNNMPPP                          ', '                                         RRRRRRRRRRRRRRRNNNPPPPPPMNNNNM                             ', '                                          RRRRMNNNNNNNNNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                             RRRRRRRRRRRRRRRRR                      ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                            RRRRRRRRRRRRRRRRRRR                     ', '                                                 RRRRRRRRRRRRRRRRRRRRRRRRRRRRR                      ', '                                                RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRR                                  ', '                        RRRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                 ', '                        RRRRRRRRRRRRRRRRRRRP   PPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR                ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                        PRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRR               ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRPP              ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR  ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', ' RRRRRRRRRRRRRRPPMMMMMMMMMMMMMMMMMMMPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', 'RRRRRRRRRRRRRRRRRRPPPPPPPPPMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', ' RRRRRRRRRRRRRRRRPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPPMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '        MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRR ', '        MMMMMMPPPPPPPPPPPPMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPRRR ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPRR  ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMPPPPPPPPPPPPPPPP    ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRPRRRRRRRRRRRRRRRRRRRRRRRRRPPMMMMMMMMMMMMMMPPPPPPP     ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                        RRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMPRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                     MMMMRRRRRRRRRRRRRRRMMMPMMMMMMMMMMMMMMMNNNNNN                   ', '                                         RRRRRRRRRRRRRRRMNNP      NNNNNNNNNNNNMMM                   ', '                                         RRRRRRRRRRRRRRRMNNP     MNNNNNNNNMMMMMPP                   ', '                                         RRRRRRRRRRRRRRRMNNP     MMNNNMMMMPPPP                      ', '                                         RRRRRRRRRRRRRRRMNNP     PMNNNMPPP                          ', '                                         RRRRRRRRRRRRRRRNNNPPPPPPMNNNNM                             ', '                                          RRRRMNNNNNNNNNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            '], ['                                                              RRRRRRRRRRRRRRRR                      ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                             RRRRRRRRRRRRRRRRRR                     ', '                                                 RRRRRRRRRRRRRRRRRRRRRRRRRRRRR                      ', '                                                RRRRRRRRRRRRRRRRRRRR                                ', '                          RRRRRRRRRRRRRRRR      RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRR                                 ', '                         RRRRRRRRRRRRRRRRRR     RRRRRRRRRRRRRRRRRRRR                                ', '                         RRRRRRRRRRRRRRRRRRP   PPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR               ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                         PRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR              ', '                MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRR              ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRPPP             ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '               MMMMMMMMPPPPPPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRPPPMMMMMMMMMMMMMMMMMMMPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', 'RRRRRRRRRRRRRRRRRRRPPPPPPPPMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', ' RRRRRRRRRRRRRRRRRPPPPPPPPPPMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPPMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPPMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPPMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR', '        MMMMMPPPPPPPPPPPPPPMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRRR', '        MMMMMMPPPPPPPPPPPPMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPRRRR', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPPPPPPPPPPPPPPPPPPPPPRR ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMMMMMMMPPPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMMPPPPPPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMPRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRMMMMMPPPPPPPPPPPPPPPPP   ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRPRRRRRRRRRRRRRRRRRRRRRRRRRPPPMMMMMMMMMMMMMPPPPPPPP    ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '        MMMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '         MMMMMMMMMMMMMMMMRRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM            ', '                         RRRRRRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM             ', '                          RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRPMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMPRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMM                       ', '                                    MMMMMMRRRRRRRRRRRRRRRMMMMMMMMMMMMMMMMMMMM                       ', '                                     MMMMMRRRRRRRRRRRRRRRMMPMMMMMMMMMMMMMMMNNNNNN                   ', '                                          RRRRRRRRRRRRRRRNNP      NNNNNNNNNNNNMMM                   ', '                                          RRRRRRRRRRRRRRRNNP     MNNNNNNNNMMMMMPP                   ', '                                          RRRRRRRRRRRRRRRNNP     MMNNNMMMMPPPP                      ', '                                          RRRRRRRRRRRRRRRNNP     PMNNNMPPP                          ', '                                          RRRRRRRRRRRRRRMNNPPPPPPMNNNNM                             ', '                                           RRRMNNNNNNNNNNNNNNNNNNNNNNNM                             ', '                                             PMNNNNNNNNNNNNNNNNNNNNNNMP                             ', '                                             PMNNNNNNNNNNNNNNNNNNNMPPP                              ', '                                             PMNNNNNNNNNNPPPPPPPPPP                                 ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                             PMNNNNNNNNNNP                                          ', '                                     PPPPPPPPNNNNNNNNNNNNP                                          ', '                                   PPNNNNNNNNNNNNNNNNNNNNP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNNNMP                                          ', '                                  PMNNNNNNNNNNNNNNNNNNMMP                                           ', '                                  PMNNNNNNNNNNNNNMMMMMPPP                                           ', '                                  PMNNNNNNNNNNNNMPPPPPP                                             ', '                                  PMNNNNNNNNNNNMPP                                                  ', '                                  PMNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNNNNNNMP                                                   ', '                                 PMNNNMNNNMNNMNMP                                                   ', '                              PPPMNNNNMNNNPNNMNNMPP                                                 ', '                           PPPMNNMMMNNPNNNPNNNPMNNMPPP                                              ', '                           PNNNMMMNNNMPNNNNPNNNMPPMNNMPP                                            ', '                          PNNPPPMNMPPPNNNNMMPNNNNNMMNNNNMMMMM                                       ', '                          PNPNNNNMMNNNNNPPPPPNNNMMMMMMNN                                            ']]

CSI = "\x1b["
RESET = CSI + "0m"
# Match ANSI/VT escape sequences so the typewriter can print them atomically.
# Windows Terminal and modern CMD both understand these sequences when ANSI is enabled.
ESC_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[@-_])")


def fg(rgb):
    return f"{CSI}38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def bg(rgb):
    return f"{CSI}48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


class Tree:
    """常驻屏幕顶部的动画树 + 下方终端滚动区域的管理。"""

    def __init__(self):
        self.active = False
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = None
        self.cols = self.pxrows = self.lines = self.pad = 0
        self.th = 24
        self.esc_frames = []
        self.grids = []
        self.frame_idx = 0

    # ---- 布局与缩放 ----

    def measure(self):
        # 安全模式(默认): 每像素=两个同色背景空格, 包围盒 (2*cols)列 x pxrows行
        # 半块模式: 每像素=1 个 ▀/▄ 格, 纵向一格装 2 像素, 同屏面积分辨率翻倍
        tw, self.th = shutil.get_terminal_size((80, 24))
        self.hpix = 1 if USE_HALFBLOCK else 2   # 每像素列占的终端格数
        max_cw = (tw - 2) // self.hpix
        cw = min(TREE_COLS or MASTER_COLS, max_cw)
        while True:
            self.pxrows = max(2, round(len(FRAMES[0]) * cw / MASTER_COLS))
            self.lines = (self.pxrows + 1) // 2 if USE_HALFBLOCK else self.pxrows
            if self.lines + 7 <= self.th or cw <= 12:
                break
            cw -= 4
        self.cols = cw
        self.pad = max(0, (tw - self.hpix * cw) // 2)

    def scale(self, frame):
        """最近邻降采样主分辨率帧到当前终端适配尺寸。"""
        src_rows = len(frame)
        out = []
        for y in range(self.pxrows):
            row = frame[min(src_rows - 1, y * src_rows // self.pxrows)]
            out.append("".join(row[min(MASTER_COLS - 1, x * MASTER_COLS // self.cols)]
                               for x in range(self.cols)))
        if USE_HALFBLOCK and len(out) % 2:
            out.append(" " * self.cols)
        return out

    # ---- 渲染 ----

    def esc_pixels(self, grid):
        """安全模式的一帧: 每个像素=两个同色背景空格, 逐行绝对定位到顶部区域。
        只用空格+背景色, 不依赖任何特殊字形, 所有终端宽度行为一致。"""
        parts = []
        for i, row in enumerate(grid):
            line = [f"{CSI}{i + 1};{self.pad + 1}H"]
            x = 0
            while x < len(row):
                c = row[x]
                j = x
                while j < len(row) and row[j] == c:
                    j += 1
                n = j - x
                if c != " ":
                    line.append(bg(PX[c]) + "  " * n + RESET)
                else:
                    line.append("  " * n)
                x = j
            parts.append("".join(line))
        return "".join(parts)

    def esc_halfblock(self, grid):
        """半块模式的一帧: 上行像素当前景色、下行当背景色, 一格装 2 像素。
        要求终端把 ▀▄ 渲染为单宽, 否则会折行(USE_HALFBLOCK 开关)。"""
        parts = []
        for i in range(self.lines):
            up, lo = grid[2 * i], grid[2 * i + 1]
            line = [f"{CSI}{i + 1};{self.pad + 1}H"]
            for x in range(self.cols):
                a, b = up[x], lo[x]
                if a == " " and b == " ":
                    line.append(" ")
                elif a != " " and b != " ":
                    line.append(fg(PX[a]) + bg(PX[b]) + "▀")
                elif a != " ":
                    line.append(fg(PX[a]) + "▀")
                else:
                    line.append(fg(PX[b]) + "▄")
            line.append(RESET)
            parts.append("".join(line))
        return "".join(parts)

    def esc_frame(self, grid):
        return self.esc_halfblock(grid) if USE_HALFBLOCK else self.esc_pixels(grid)

    def ascii_rows(self, grid):
        """同一包围盒的 ASCII 阶段: 半块模式每 2 像素行取主导色, 安全模式 1:1。"""
        def char_row(pixels):
            return [ASCII_CHAR[c] if c in ASCII_CHAR else " " for c in pixels]
        if not USE_HALFBLOCK:
            return [char_row(row) for row in grid]
        rows = []
        for i in range(self.lines):
            up, lo = grid[2 * i], grid[2 * i + 1]
            rows.append(char_row([a if a != " " else b for a, b in zip(up, lo)]))
        return rows

    def write_ascii_row(self, i, row, mutate=False):
        out = [f"{CSI}{i + 1};{self.pad + 1}H"]
        for ch in row:
            if mutate and ch != " " and random.random() < 0.35:
                ch = random.choice("#*%:")
            code = {"#": "R", "*": "P", "%": "M", ":": "N"}.get(ch)
            out.append(fg(PX[code]) + ch * self.hpix if code else " " * self.hpix)
        out.append(RESET + CSI + "K")
        sys.stdout.write("".join(out))

    # ---- 呈现流程 ----

    def present(self):
        # 先停掉可能存在的旧动画线程, 否则多次 cat 会多线程抢画同一区域
        if self.thread:
            self.stop.set()
            self.thread.join(timeout=1)
            self.thread = None
        self.active = False
        self.stop.clear()
        self.measure()
        grids = [self.scale(f) for f in FRAMES]
        self.grids = grids            # 假死 glitch 需要按像素寻址
        self.frame_idx = 0
        self.esc_frames = [self.esc_frame(g) for g in grids]
        rows = self.ascii_rows(grids[0])
        with self.lock:
            sys.stdout.write(CSI + "r" + CSI + "2J" + CSI + "H")
            sys.stdout.flush()
        for i, row in enumerate(rows):
            with self.lock:
                self.write_ascii_row(i, row)
                sys.stdout.flush()
            time.sleep(DELAY_LINE)
        time.sleep(PAUSE_BEFORE_MORPH)
        for _ in range(2):                      # 原位闪烁, 预示突变
            with self.lock:
                for i, row in enumerate(rows):
                    self.write_ascii_row(i, row, mutate=True)
                sys.stdout.flush()
            time.sleep(0.07)
        with self.lock:
            sys.stdout.write(self.esc_frames[0])
            # 划定滚动区域: 树占据 1..lines, 终端文本在 lines+2 起滚动
            sys.stdout.write(f"{CSI}{self.lines + 2};{self.th}r"
                             f"{CSI}{self.lines + 2};1H")
            sys.stdout.flush()
        self.active = True
        self.stop.clear()
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()

    def _animate(self):
        i = 0
        n = len(self.esc_frames)
        while not self.stop.wait(FRAME_DELAY):
            i = (i + 1) % n
            self.frame_idx = i
            with self.lock:
                sys.stdout.write("\x1b7" + self.esc_frames[i] + "\x1b8")
                sys.stdout.flush()

    def write_cell_ascii(self, y, x, code):
        """把单个像素格改写成 ASCII 字符样式(假死 glitch 用)。"""
        ch = ASCII_CHAR[code]
        col = self.pad + x * self.hpix + 1
        if USE_HALFBLOCK:
            # 同格的另一半像素保留: 用背景色承载
            grid = self.grids[self.frame_idx]
            other = grid[y + 1][x] if y % 2 == 0 and y + 1 < len(grid) else \
                    grid[y - 1][x] if y > 0 else " "
            seq = fg(PX[code]) + (bg(PX[other]) if other != " " else "") \
                + ch + RESET
            sys.stdout.write(f"{CSI}{y // 2 + 1};{col}H" + seq)
        else:
            sys.stdout.write(f"{CSI}{y + 1};{col}H" + fg(PX[code]) + ch * 2 + RESET)

    def clear_text_area(self):
        """清空树下方的终端文本区域, 树不动。"""
        if self.active:
            sys.stdout.write(f"{CSI}{self.lines + 2};1H{CSI}0J")
        else:
            sys.stdout.write(CSI + "2J" + CSI + "H")

    def shutdown(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
        with self.lock:
            # 解除滚动区域、清屏、还光标: 把干净的终端还给真正的 shell
            sys.stdout.write(CSI + "r" + CSI + "2J" + CSI + "H"
                             + CSI + "?25h" + RESET)
            sys.stdout.flush()


# Windows unified story renderer: one thread owns terminal writes while man tree
# is running. This keeps the animated tree and Chinese typewriter text in one frame.
STORY_MODE = [False]
STORY_STOP = threading.Event()
STORY_THREAD = [None]
STORY_LOCK = threading.RLock()
STORY_LINES = []
STORY_CURRENT = [""]
STORY_INPUT = [""]
STORY_PROMPT = [""]

def _cell_width(ch):
    import unicodedata
    if ch == "\t":
        return 4
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1

def _wrap_story(text, width):
    out, line, used = [], "", 0
    for ch in text:
        if ch == "\n":
            out.append(line); line = ""; used = 0
            continue
        w = _cell_width(ch)
        if used + w > width and line:
            out.append(line); line = ch; used = w
        else:
            line += ch; used += w
    out.append(line)
    return out

def _story_build_lines(width):
    lines = []
    for x in STORY_LINES:
        lines.extend(_wrap_story(x, width))
    if STORY_CURRENT[0]:
        lines.extend(_wrap_story(STORY_CURRENT[0], width))
    return lines


def _story_render_once(frame_idx=None):
    """同步绘制当前剧情状态，并把光标放到下一行，供主循环继续打印提示符。"""
    if not TREE.esc_frames:
        return
    try:
        tw, _ = shutil.get_terminal_size((80, 24))
    except Exception:
        tw = 80
    width = max(10, tw - 2)
    with STORY_LOCK:
        lines = _story_build_lines(width)
        if frame_idx is None:
            frame_idx = TREE.frame_idx % len(TREE.esc_frames)
        max_rows = max(1, TREE.th - TREE.lines - 2)
        visible = lines[-max_rows:]
        base = TREE.lines + 2
        with TREE.lock:
            sys.stdout.write(TREE.esc_frames[frame_idx])
            sys.stdout.write(f"{CSI}{base};1H{CSI}0J")
            row = base
            for line in visible:
                sys.stdout.write(f"{CSI}{row};1H{CSI}2K{line}")
                row += 1
            # 关键修复：上一版渲染完最后一行后，光标仍停在该行末尾，
            # 所以主循环紧接着打印 man tree 提示符时会和剧情粘在同一行。
            # 现在显式把光标放到剧情区下一行。
            sys.stdout.write(f"{CSI}{base + len(visible)};1H")
            sys.stdout.flush()


def _story_render():
    """Windows 统一渲染器：文字高频刷新，树按独立节奏换帧。

    STORY_MODE 开启期间，剧情区完全由此线程绝对定位重绘；外部不得
    用裸 emit() 写入换行，否则会把终端光标移走并与重绘造成文字重叠。
    """
    frame_idx = 0
    next_frame = time.monotonic()
    render_delay = 0.025  # 约 40 FPS，保证打字机不会卡顿

    while not STORY_STOP.wait(render_delay):
        now = time.monotonic()

        with STORY_LOCK:
            if not STORY_MODE[0] or not TREE.esc_frames:
                continue

            # 树只按自己的速度换帧；渲染循环本身保持高频运行。
            if now >= next_frame:
                frame_idx = (frame_idx + 1) % len(TREE.esc_frames)
                TREE.frame_idx = frame_idx
                next_frame = now + FRAME_DELAY

            try:
                tw, _ = shutil.get_terminal_size((80, 24))
            except Exception:
                tw = 80

            width = max(10, tw - 2)
            lines = _story_build_lines(width)

            # 每 25ms 刷新一次文字，因此中文打字机不会被 0.30 秒的树动画间隔拖慢。
            with TREE.lock:
                sys.stdout.write(TREE.esc_frames[frame_idx])
                base = TREE.lines + 2
                sys.stdout.write(f"{CSI}{base};1H{CSI}0J")
                row = base
                max_rows = max(1, TREE.th - TREE.lines - 2)
                visible = lines[-max_rows:]
                for line in visible:
                    sys.stdout.write(f"{CSI}{row};1H{CSI}2K{line}")
                    row += 1
                # 保持光标在剧情区最后一行的下一行，避免后续 man tree 提示符粘行。
                sys.stdout.write(f"{CSI}{base + len(visible)};1H")
                sys.stdout.flush()

def _story_start():
    if not IS_WINDOWS:
        return
    # Stop the old tree-only renderer; the new renderer animates the tree itself.
    if TREE.thread:
        TREE.stop.set()
        TREE.thread.join(timeout=1)
        TREE.thread = None
    STORY_LINES.clear()
    STORY_CURRENT[0] = ""
    STORY_INPUT[0] = ""
    STORY_PROMPT[0] = ""
    STORY_STOP.clear()
    STORY_MODE[0] = True
    t = threading.Thread(target=_story_render, daemon=True)
    STORY_THREAD[0] = t
    t.start()

def _story_stop():
    if not IS_WINDOWS:
        return
    # 在线程停下前先把最后一帧剧情同步落盘，防止最后一个字还没来得及
    # 被 25 FPS 渲染线程画出来就被立即切回普通终端。
    with STORY_LOCK:
        if STORY_MODE[0] and TREE.esc_frames:
            _story_render_once(TREE.frame_idx)
    STORY_MODE[0] = False
    STORY_STOP.set()
    t = STORY_THREAD[0]
    if t:
        t.join(timeout=1)
    STORY_THREAD[0] = None

def _story_add_char(ch):
    with STORY_LOCK:
        STORY_CURRENT[0] += ch

def _story_newline():
    with STORY_LOCK:
        if STORY_CURRENT[0]:
            STORY_LINES.append(STORY_CURRENT[0])
        STORY_CURRENT[0] = ""

def _story_wait_key():
    wait_key()

def _story_typewriter(text, newline=True, ff=True):
    # Keep the original timing and skip-to-end behavior, but update only state.
    if not sys.stdin.isatty():
        _story_add_char(text)
        if newline: _story_newline()
        return
    for ch in text:
        _story_add_char(ch)
        if not ch.isspace():
            play_text_sound()
        deadline = time.time() + DELAY_CHAR
        while time.time() < deadline:
            if msvcrt.kbhit():
                c = _win_key()
                if c is None:
                    continue
                if ord(c) == 0x03:
                    raise KeyboardInterrupt
                if c in ("\r", "\n") and ff:
                    # Finish the remainder immediately.
                    for rest in text[text.index(ch) + 1:]:
                        _story_add_char(rest)
                    if newline: _story_newline()
                    return
            time.sleep(0.005)
    if newline:
        _story_newline()

TREE = Tree()
OLD_TERM = [None]                 # 启动前的终端属性, 退出时恢复(程序全程关回显)
DIRTY = [False]                   # 本轮指令是否产生过可见输出(输错刷新指令区用)


def _windows_text_safe(text):
    """Windows Terminal 对部分中文字体的东亚宽字符处理不一致。
    仅对普通可见中文文本做逐行宽度保护；ANSI/换行/控制序列保持原样。
    不插入额外空格，避免改变剧情排版；原位重写另行使用 _cell_width。
    """
    return text


def emit(text):
    """所有终端输出统一走这里，与动画线程互斥。"""
    if IS_WINDOWS:
        text = _windows_text_safe(text)
    with TREE.lock:
        sys.stdout.write(text)
        sys.stdout.flush()
    if text.strip():
        DIRTY[0] = True


def _win_key():
    """Read one Windows console key without echo."""
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        # Extended key: consume its scan-code byte.
        try:
            msvcrt.getwch()
        except Exception:
            pass
        return None
    return ch


def _win_flush():
    while msvcrt.kbhit():
        try:
            msvcrt.getwch()
        except Exception:
            break


def _win_cursor(show):
    # Windows Terminal/CMD both understand VT cursor control when enabled.
    # Keep this isolated so transition code never depends on POSIX termios.
    emit(CSI + ("?25h" if show else "?25l"))


def read_command():
    """Cross-platform raw-ish command line reader with explicit echo."""
    if IS_WINDOWS:
        if STORY_MODE[0] and sys.stdin.isatty():
            buf = []
            _win_cursor(False)
            while True:
                ch = _win_key()
                if ch is None:
                    continue
                o = ord(ch)
                if o in (0x7F, 0x08, 0x02):
                    if buf:
                        buf.pop()
                        with STORY_LOCK:
                            STORY_CURRENT[0] = STORY_PROMPT[0] + "".join(buf)
                elif o in (0x0D, 0x0A):
                    line = "".join(buf)
                    with STORY_LOCK:
                        STORY_CURRENT[0] = STORY_PROMPT[0] + line
                    _story_newline()
                    return line
                elif o == 0x03:
                    raise KeyboardInterrupt
                elif ch.isprintable():
                    buf.append(ch)
                    with STORY_LOCK:
                        STORY_CURRENT[0] = STORY_PROMPT[0] + "".join(buf)
        if not sys.stdin.isatty():
            line = sys.stdin.readline()
            return None if line == "" else line.rstrip("\r\n")
        buf = []
        _win_cursor(True)
        try:
            while True:
                ch = _win_key()
                if ch is None:
                    continue
                o = ord(ch)
                if o in (0x7F, 0x08, 0x02):
                    if buf:
                        buf.pop()
                        emit("\b \b")
                elif o in (0x0D, 0x0A):
                    emit("\r\n")
                    return "".join(buf)
                elif o == 0x04 and not buf:
                    emit("\r\n")
                    return None
                elif o == 0x03:
                    raise KeyboardInterrupt
                elif ch.isprintable():
                    # 空格也是有效的命令行字符；不能用 isspace() 把它过滤掉。
                    buf.append(ch)
                    emit(ch)
        finally:
            _win_cursor(False)
    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        return None if line == "" else line.rstrip("\n")
    fd = sys.stdin.fileno()
    import termios, tty
    old = termios.tcgetattr(fd)
    buf = []
    emit(CSI + "?25h")
    try:
        tty.setraw(fd, termios.TCSADRAIN)
        while True:
            ch = sys.stdin.read(1)
            if ch == "":
                return None
            o = ord(ch)
            if o in (0x7F, 0x08, 0x02):
                if buf:
                    buf.pop()
                    emit("\b \b")
            elif o in (0x0D, 0x0A):
                emit("\r\n")
                return "".join(buf)
            elif o == 0x04 and not buf:
                emit("\r\n")
                return None
            elif o == 0x03:
                raise KeyboardInterrupt
            elif o == 0x1B:
                nxt = sys.stdin.read(1)
                if nxt == "[":
                    while True:
                        c = sys.stdin.read(1)
                        if c == "" or 0x40 <= ord(c) <= 0x7E:
                            break
            elif 0x20 <= o < 0x7F:
                buf.append(ch)
                emit(ch)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        emit(CSI + "?25l")


def wait_key():
    if not sys.stdin.isatty():
        return
    if IS_WINDOWS:
        _win_flush()
        while True:
            ch = _win_key()
            if ch is None:
                continue
            o = ord(ch)
            if o == 0x03:
                raise KeyboardInterrupt
            if o in (0x0D, 0x0A):
                return
    fd = sys.stdin.fileno()
    import termios, tty
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd, termios.TCSADRAIN)
        termios.tcflush(fd, termios.TCIFLUSH)
        while True:
            ch = sys.stdin.read(1)
            if ch == "":
                return
            o = ord(ch)
            if o == 0x03:
                raise KeyboardInterrupt
            if o in (0x0D, 0x0A):
                return
            if o == 0x1B:
                nxt = sys.stdin.read(1)
                if nxt == "[":
                    while True:
                        c = sys.stdin.read(1)
                        if c == "" or 0x40 <= ord(c) <= 0x7E:
                            break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def typewriter(text, newline=True, ff=True):
    if IS_WINDOWS and STORY_MODE[0]:
        _story_typewriter(text, newline=newline, ff=ff)
        return
    if not sys.stdin.isatty():
        emit(text + ("\n" if newline else ""))
        return
    parts = []
    pos = 0
    for m in ESC_RE.finditer(text):
        for j in range(pos, m.start()):
            parts.append((False, text[j], j + 1))
        parts.append((True, m.group(0), m.end()))
        pos = m.end()
    for j in range(pos, len(text)):
        parts.append((False, text[j], j + 1))

    if IS_WINDOWS:
        _win_flush()
        i = 0
        while i < len(parts):
            is_esc, chunk, raw_end = parts[i]
            emit(chunk)
            i += 1
            if is_esc:
                continue
            # Windows 普通剧情（非统一故事渲染器）也保持逐字打字机，并且
            # 每个非空白可见字符触发一次文字音效。
            if chunk and not chunk.isspace():
                play_text_sound()
            deadline = time.time() + DELAY_CHAR
            while time.time() < deadline:
                if not msvcrt.kbhit():
                    time.sleep(0.01)
                    continue
                c = _win_key()
                if c is None:
                    continue
                if ord(c) == 0x03:
                    raise KeyboardInterrupt
                if c in ("\r", "\n") and ff:
                    remainder = text[raw_end:]
                    emit(remainder + ("\r\n" if newline else ""))
                    return
        if newline:
            emit("\r\n")
        return

    fd = sys.stdin.fileno()
    import termios, tty, select
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd, termios.TCSADRAIN)
        termios.tcflush(fd, termios.TCIFLUSH)
        i = 0
        while i < len(parts):
            is_esc, chunk, raw_end = parts[i]
            emit(chunk)
            i += 1
            if is_esc:
                continue
            deadline = time.time() + DELAY_CHAR
            while time.time() < deadline:
                if not select.select([fd], [], [], 0.01)[0]:
                    continue
                c = os.read(fd, 1)
                if c == b"\x03":
                    raise KeyboardInterrupt
                if c in (b"\r", b"\n") and ff:
                    emit(text[raw_end:] + ("\r\n" if newline else ""))
                    return
        if newline:
            emit("\r\n")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def say(text):
    """显示剧情：Windows 全程使用打字机；story 模式由统一渲染器绘制。"""
    if IS_WINDOWS and STORY_MODE[0]:
        _story_typewriter(text, newline=False)
        _story_wait_key()
        _story_newline()
        return
    if IS_WINDOWS and sys.stdin.isatty():
        # 不再瞬间打印：cd .behind 后的开场文字、以及最后几句结尾文字，
        # 都走和前面一致的逐字打字机 + 字符音效。此时树仍在动画线程中，
        # 因此调用方会在这些剧情段开始前切到 STORY_MODE。
        typewriter(text, newline=False, ff=True)
        wait_key()
        emit("\r\n")
        return
    typewriter(text, newline=False)
    wait_key()
    emit("\r\n")



def _resume_tree_animation():
    """剧情结束后恢复普通树动画；光标位置由剧情渲染器预先放到下一行。"""
    if not IS_WINDOWS:
        return
    if TREE.active and TREE.esc_frames and TREE.thread is None:
        TREE.stop.clear()
        TREE.thread = threading.Thread(target=TREE._animate, daemon=True)
        TREE.thread.start()


def spawn_eggbar():
    if IS_WINDOWS:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eggbar_win.py")
        if not os.path.exists(script):
            return
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pyw):
            pyw = sys.executable
        try:
            subprocess.Popen([pyw, script],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
        return
    if not (os.path.exists(EGGBAR) and os.access(EGGBAR, os.X_OK)):
        return
    if subprocess.run(["pgrep", "-x", "eggbar"],
                      stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        return
    subprocess.Popen([EGGBAR], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def glitch_mask(grid, ratio):
    """生成斑块状腐化掩码: 从随机种子点出发做随机游走生长,
    腐化区域呈有机团块而非均匀噪点。返回 {(x, y), ...}。"""
    cells = [(x, y) for y, row in enumerate(grid)
             for x, c in enumerate(row) if c != " "]
    if not cells:
        return set()
    cellset = set(cells)
    target = max(1, int(len(cells) * ratio))
    n_seeds = max(2, target // 45)                # 斑块数量随总面积伸缩
    mask = set()
    for sx, sy in random.sample(cells, min(n_seeds, len(cells))):
        budget = max(10, target // n_seeds + random.randint(-8, 18))
        x, y = sx, sy
        gained = steps = 0
        # 随机游走生长, 直到斑块的"有效腐化面积"达到预算(设有步数上限)
        while gained < budget and steps < budget * 12:
            steps += 1
            if (x, y) in cellset and (x, y) not in mask:
                mask.add((x, y))
                gained += 1
            dx, dy = random.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
            x, y = x + dx, y + dy
    return mask


def freeze_glitch(seconds, do_glitch=True):
    """Freeze the current tree while swallowing Windows console input.

    On Windows msvcrt is already in console mode; unlike POSIX we must not
    try to emulate termios/ICANON.  In particular, changing console/input
    state during the .behind transition can make the launcher appear to
    crash or leave the console in a broken state.
    """
    if IS_WINDOWS:
        try:
            _win_flush()
            grid = TREE.grids[TREE.frame_idx] if TREE.grids else None
            if do_glitch and grid:
                with TREE.lock:
                    for x, y in glitch_mask(grid, GLITCH_RATIO):
                        TREE.write_cell_ascii(y, x, grid[y][x])
                    sys.stdout.flush()
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                # Consume keys without ever echoing them or changing console mode.
                _win_flush()
                time.sleep(0.02)
            _win_flush()
        except (OSError, ValueError):
            # A closed/replaced console should not take down the whole program.
            time.sleep(seconds)
        return

    noecho = sys.stdin.isatty()
    fd = sys.stdin.fileno() if noecho else None
    import termios
    old = termios.tcgetattr(fd) if noecho else None
    try:
        if noecho:
            new = termios.tcgetattr(fd)
            new[3] &= ~(termios.ECHO | termios.ICANON)
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
        grid = TREE.grids[TREE.frame_idx] if TREE.grids else None
        if do_glitch and grid:
            with TREE.lock:
                for x, y in glitch_mask(grid, GLITCH_RATIO):
                    TREE.write_cell_ascii(y, x, grid[y][x])
                sys.stdout.flush()
        time.sleep(seconds)
        if noecho:
            termios.tcflush(fd, termios.TCIFLUSH)
    finally:
        if noecho:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def teardown_tree():
    """离开 .behind 时清理掉显示的树: 停动画、解除滚动区域、清屏。"""
    if not TREE.active:
        return
    TREE.stop.set()
    if TREE.thread:
        TREE.thread.join(timeout=1)
        TREE.thread = None
    TREE.active = False
    with TREE.lock:
        sys.stdout.write(CSI + "r" + CSI + "2J" + CSI + "H")
        sys.stdout.flush()


class State:
    cwd = "~"
    egg = False
    man_gone = False                  # 拒绝或收蛋后, 男人永久离开
    tree_seen = False                 # cat tree 至少一次后, ls -a 才揭示 .behind
    fresh_cat = False                 # 上次离开 .behind 后有新的 cat, 才允许假死腐化

# 蛋房开场两行: 进场时命令用词被抹去(留空), 两个空合起来就是 man tree;
# 输入 man tree 的刹那显形为完整的句子(留空与词一一对应)
OPEN_BLANK = ("*（这么多平行世界，这么多____，"
              "这么多蛋。而你还是再次来到了这里。）",
              "*（嗯，这里也有一个___。）")
OPEN_FULL = ("*（这么多平行世界，这么多树，"
             "这么多蛋。而你还是再次来到了这里。）",
             "*（嗯，这里也有一个男人。）")

def _cell_width(text):
    """计算终端显示宽度：中文/全角字符占 2 格，ASCII 占 1 格。"""
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width

def _preserve_line_width(text, target_width):
    """原位重写剧情文本时严格保持终端列宽。

    Windows Terminal 按东亚宽字符占 2 列处理中文。原版的
    ASCII 下划线占 1 列，直接替换会造成后续字符错列，因此这里
    按显示列宽计算，并在不足时补空格；超出时按显示列截断。
    """
    out = []
    width = 0
    for ch in text:
        w = 0 if unicodedata.combining(ch) else (2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1)
        if width + w > target_width:
            break
        out.append(ch)
        width += w
    return "".join(out) + " " * max(0, target_width - width)


def enter_behind(st):
    # 动画骤停、画面定格假死数秒(输入被吞掉; 若此前有新的 cat tree,
    # 树会被斑块状腐化为 ASCII 并保持定格) → 清屏完整重演树的呈现
    # → 打印开场两行后回到提示符等待指令
    if TREE.active:
        TREE.stop.set()
        if TREE.thread:
            TREE.thread.join(timeout=1)
            TREE.thread = None
        TREE.active = False
    freeze_glitch(PAUSE_BLACK, do_glitch=st.fresh_cat)
    st.fresh_cat = False
    TREE.present()
    # 树已经完整显现后，立刻切换到统一渲染器；随后才启动背景音乐。
    # 这样 cd .behind 后的两行开场文字也走同一套打字机 + 音效，
    # 同时不会和树动画线程抢终端输出。
    _story_start()
    start_behind_music()
    # STORY_MODE 开启后由统一渲染器管理剧情区光标，不能再注入裸换行。
    st.cwd = "~/.behind"
    if st.egg or st.man_gone:
        say("*（这里已经没有那个男人了。）")
    else:
        say(OPEN_BLANK[0])
        say(OPEN_BLANK[1])

    # 开场两行显示完后，必须退出剧情渲染模式，才能把控制权还给
    # 主循环显示普通命令提示符并继续输入 man tree 等命令。
    # 同时恢复普通树动画；否则统一剧情渲染器停止后树会冻结在最后一帧。
    _story_stop()
    # 剧情渲染器已经把光标放在剧情区的下一行；这里不要再输出换行，
    # 否则会多出一个空白行，导致后面的命令提示符隔一行出现。
    _resume_tree_animation()


def reveal_opening():
    """man tree 成功后，原位的待填空旁白一次性替换成完整中文。

    Windows 上不要逐字改写中文行；直接清行并一次性输出，避免双宽字符
    在终端重绘期间出现重叠。"""
    with TREE.lock:
        # 与剧情渲染器保持同一基准：剧情区第一行是 TREE.lines + 2，
        # 第二行是 TREE.lines + 3。上一版偏移了一行，导致第一行的
        # ____ 没有被正确替换。
        sys.stdout.write("\x1b7"
                         + f"{CSI}{TREE.lines + 2};1H{CSI}2K" + OPEN_FULL[0]
                         + f"{CSI}{TREE.lines + 3};1H{CSI}2K" + OPEN_FULL[1]
                         + "\x1b8")
        sys.stdout.flush()


def refresh_opening():
    """树后输错指令(或空按 Enter 顶行)后刷新指令区: 清掉文本区,
    两行待填空旁白瞬时直印回固定行位(早就读过, 不再走打字机)——
    man tree 显形按绝对行寻址, 旁白被顶走后必须立刻复位。"""
    with TREE.lock:
        TREE.clear_text_area()
        sys.stdout.flush()
    emit("\n" + OPEN_BLANK[0] + "\n" + OPEN_BLANK[1] + "\n")



def offer(st):
    """在 .behind 输入 man tree 触发: 男人的馈赠(破墙版)。

    咏唱成功的刹那, 开场两行里被抹去的词立刻显形, 再打印后续对话。
    第一问 Take the Egg?: No = 不带走这个时空的蛋(假死腐化→只剩树);
    Yes = 蛋立刻到手并进菜单栏, 男人再问要不要更多——
    第二问要: 镜厅无尽树海; 不要: 直接跳到挥手告别。两条路汇合, 男人永久离开。
    所有叙事行都按任意键才进下一行(原作的对话节奏)。
    """
    reveal_opening()            # 下划线立刻被正确字符替换
    time.sleep(1.0)             # 显形留一拍
    TREE.clear_text_area()      # 超行重置对话区, 后续对话从干净区域开始
    _story_start()
    say("*（经历了无数次重逢之后，他见到你依然很高兴。）")
    say("*（他相信你不会再忘记他了。"
        "你们谁都不会忘记。）")
    say("拿着这个，像往常一样，记住我。")
    say("你不会拒绝，对吧？")
    STORY_PROMPT[0] = "要拿走蛋吗？[是/否] " if STORY_MODE[0] else ""
    if STORY_MODE[0]:
        with STORY_LOCK:
            STORY_CURRENT[0] += STORY_PROMPT[0]
    else:
        typewriter(STORY_PROMPT[0], newline=False, ff=False)
    try:
        ans = (read_command() or "n").strip().lower()
    except KeyboardInterrupt:
        emit("\n")
        ans = "n"
    if not (ans.startswith("y") or ans.startswith("是")):
        # 不带走这个时空的蛋: 假死+斑块腐化 → 清屏重演, 只剩只有树的文本
        st.man_gone = True
        if TREE.active:
            TREE.stop.set()
            if TREE.thread:
                TREE.thread.join(timeout=1)
                TREE.thread = None
            TREE.active = False
        _story_stop()
        freeze_glitch(PAUSE_BLACK, do_glitch=True)
        TREE.present()          # 清屏重演: 只剩树
        _story_start()          # 结尾文字继续使用统一渲染器 + 打字机音效
        say("*（这里已经没有那个男人了。）")
        _story_stop()
        # 不再额外换行：否则结尾剧情后的命令提示符会多出一个空白行。
        _resume_tree_animation()
        return
    st.egg = True               # 选 Yes 的刹那: 蛋到手, 立刻进菜单栏
    if SPAWN_ON == "acquire":
        spawn_eggbar()
    say("*（你得到了一个蛋。）")
    STORY_PROMPT[0] = "还要再要一个蛋吗？[是/否] " if STORY_MODE[0] else ""
    if STORY_MODE[0]:
        with STORY_LOCK:
            STORY_CURRENT[0] += STORY_PROMPT[0]
    else:
        typewriter(STORY_PROMPT[0], newline=False, ff=False)
    try:
        more = (read_command() or "n").strip().lower()
    except KeyboardInterrupt:
        emit("\n")
        more = "n"
    if more.startswith("y") or more.startswith("是"):
        say("*（男人指向了你来时的方向。）")
        say("*（一排排树木延伸到你眼前，宛如一座镜厅——）")
        say("*（不，是无数排树。而且没有两棵完全相同。）")
    say("*（还没等你回过神来，他已经笑着向你挥手告别了。）")
    st.man_gone = True
    time.sleep(2.5)             # 告别与收蛋都落定, 再清屏
    _story_stop()
    TREE.present()              # 清屏重演: 只剩树
    _story_start()              # 最后的三句也保持打字机 + 音效
    say("*（这里已经没有那个男人了。）")
    say("*（你不由得感到一阵释然。）")
    say("*（他没有让你感到忧郁。）")
    _story_stop()
    # 剧情渲染器已经把光标放在剧情区的下一行；这里不要再输出换行，
    # 否则会多出一个空白行，导致后面的命令提示符隔一行出现。
    _resume_tree_animation()


def prompt_str(st):
    return f"{USER}@{HOST} {st.cwd} % "


def run():
    st = State()
    if SHOW_DATE:
        banner_date = SHOW_DATE
    else:
        now = time.localtime()
        weekdays = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
        banner_date = f"{weekdays[now.tm_wday]} {now.tm_mon}月{now.tm_mday}日 {now.tm_hour:02d}:{now.tm_min:02d}:{now.tm_sec:02d}"
    if sys.stdin.isatty():
        emit(CSI + "?25l")
    tty_name = "控制台" if IS_WINDOWS else "终端"
    emit(f"最后登录：{banner_date}，终端：{tty_name}\n")
    # 程序全程接管回显: 演出/打字机期间提前敲的字符不回显、不错位,
    # 静默排队, 由 read_command 在提示符后统一回显; 退出时恢复
    if sys.stdin.isatty() and not IS_WINDOWS:
        import termios
        fd0 = sys.stdin.fileno()
        OLD_TERM[0] = termios.tcgetattr(fd0)
        noecho = termios.tcgetattr(fd0)
        noecho[3] &= ~termios.ECHO
        termios.tcsetattr(fd0, termios.TCSADRAIN, noecho)
    while True:
        emit(prompt_str(st))
        try:
            line = read_command()
        except KeyboardInterrupt:
            emit("\n")
            continue
        if line is None:
            break
        parts = line.strip().split()
        if not parts:
            # 空 Enter 也会把待填空旁白一行行顶出交互区: 男人还在等时立即复位
            if st.cwd != "~" and not st.egg and not st.man_gone:
                refresh_opening()
            continue
        cmd, args = parts[0], parts[1:]

        # was_pending = 男人还在树后等那句 man tree(输错后要刷新指令区)
        was_pending = (st.cwd != "~" and not st.egg and not st.man_gone)
        DIRTY[0] = False

        # 树后不是文件系统: 除 man/cd/exit/whoami 与蛋相关命令外, 一律 not found
        if st.cwd != "~" and cmd not in ("man", "cd", "exit", "quit", "logout",
                                         "egg", "help", "whoami"):
            emit(f"找不到命令：{cmd}\n")
        elif cmd == "ls":
            all_flag = any(a.startswith("-") and "a" in a for a in args)
            operands = [a for a in args if not a.startswith("-")]
            if not operands or all(op in (".", "..") for op in operands):
                # 无操作数: 列当前目录
                if st.cwd == "~":
                    # 只有 cat tree 至少一次后, .behind 才会被 ls -a 揭示
                    if all_flag:
                        emit(".  ..  .behind  tree\n" if st.tree_seen
                             else ".  ..  tree\n")
                    else:
                        emit("tree\n")
                else:
                    emit(".  ..\n" if all_flag else "")
            else:
                for op in operands:
                    if op in (".", ".."):
                        continue
                    if st.cwd == "~" and op == "tree":
                        emit("tree\n")          # tree 是看得见的真实文件
                    elif st.cwd == "~" and op == ".behind" and st.tree_seen:
                        # 揭示后列得动, 但对 ls 来说里面"空无一物"
                        emit(".  ..\n" if all_flag else "")
                    else:
                        # 未揭示的 .behind 与其他名字: 查无此物
                        emit(f"ls：{op}：没有那个文件或目录\n")
        elif cmd == "cat":
            if args and args[0] == "tree" and st.cwd == "~":
                TREE.present()
                # 树完整出现后再开始背景音乐。
                start_behind_music()
                st.tree_seen = True       # 揭示 .behind
                st.fresh_cat = True       # 允许下次进 .behind 时腐化
            elif args:
                emit(f"cat：{args[0]}：没有那个文件或目录\n")
        elif cmd == "whoami":
            emit(USER + "\n")
            if st.cwd != "~":
                # "之间"的区域: HP 变回 90, 等级 LV1, 称号被移除
                # title 字段存在而值为空 = 移除
                emit("用户ID=1(kris) 生命值=90 等级=1 称号=\n")
        elif cmd == "man":
            # 在树后 man tree = 召唤那个男人; 其余一律按正常 man 处理
            if (args and args[0] == "tree" and st.cwd != "~"
                    and not st.egg and not st.man_gone):
                offer(st)
            elif not args:
                emit("你想查看哪个命令的手册？\n")
            elif args[0] == "egg" and st.egg:
                typewriter(EGG_LINE, newline=True, ff=False)
            else:
                emit(f"没有找到 {args[0]} 的手册条目\n")
        elif cmd == "cd":
            tgt = args[0] if args else "~"
            if tgt in ("~", "/", "..", "."):
                if st.cwd != "~":
                    teardown_tree()      # 离开树后, 清理掉显示的树
                stop_behind_music()
                st.cwd = "~"
            elif tgt == "tree":
                emit("cd：tree 不是一个目录\n")
            elif tgt == ".behind" and st.cwd == "~":
                enter_behind(st)
            elif tgt == ".behind":
                pass
            else:
                emit(f"cd：没有那个文件或目录：{tgt}\n")
        elif cmd == "pwd":
            emit((os.path.expanduser("~") if IS_WINDOWS else "/Users/" + USER) + ("/.behind" if st.cwd != "~" else "") + "\n")
        elif cmd == "clear":
            with TREE.lock:
                TREE.clear_text_area()
                sys.stdout.flush()
        elif cmd in ("egg", "help") and (cmd == "egg" or args[:1] == ["egg"]):
            if cmd == "egg" and not st.egg:
                emit("找不到命令：egg\n")
            elif cmd == "egg" or st.egg:
                typewriter(EGG_LINE, newline=True, ff=False)
            else:
                emit("找不到命令：help\n")
        elif cmd in ("exit", "quit", "logout"):
            break
        else:
            emit(f"找不到命令：{cmd}\n")

        # 男人还在等那句 man tree: 任何产生输出的输错都会把待填空旁白顶走,
        # 报错原地留几秒, 再把指令区刷回固定行位(显形按绝对行寻址, 不能漂移)
        if (was_pending and st.cwd != "~" and not st.egg and not st.man_gone
                and DIRTY[0]):
            time.sleep(PAUSE_WRONG)
            refresh_opening()

    if st.egg and SPAWN_ON == "exit":
        spawn_eggbar()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass                    # ^C 静默退出, 不喷 traceback
    finally:
        if OLD_TERM[0] is not None and sys.stdin.isatty() and not IS_WINDOWS:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN,
                              OLD_TERM[0])
        TREE.shutdown()
        sys.stdout.write("\n")
