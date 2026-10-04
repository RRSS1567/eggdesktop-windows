# -*- coding: utf-8 -*-
"""eggdesktop Windows 系统托盘蛋。仅使用标准库和 Win32 ctypes。"""
import ctypes, os, sys
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32
shell32 = ctypes.windll.shell32

WM_USER = 0x0400
WM_TRAY = WM_USER + 1
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_DESTROY = 0x0002
NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 1
NIF_ICON = 2
NIF_TIP = 4
IDI_APPLICATION = 32512
ERROR_ALREADY_EXISTS = 183
MB_OK = 0x00000000
MB_ICONINFORMATION = 0x00000040

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON)
    ]

class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", wintypes.WINFUNCTYPE(wintypes.LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HCURSOR), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)
    ]

# Keep callback alive.
WNDPROC = wintypes.WINFUNCTYPE(wintypes.LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

def make_egg_icon():
    # 32-bit ARGB DIB: a simple white egg with a subtle gray outline.
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]
    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = 32
    bi.bmiHeader.biHeight = -32
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    bits = ctypes.c_void_p()
    hdc = user32.GetDC(0)
    hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bi), 0, ctypes.byref(bits), None, 0)
    user32.ReleaseDC(0, hdc)
    if not hbmp:
        return user32.LoadIconW(None, IDI_APPLICATION)
    arr = (ctypes.c_uint32 * (32*32)).from_address(bits.value)
    for y in range(32):
        for x in range(32):
            dx = (x - 15.5) / 10.0
            dy = (y - 16.0) / 13.0
            d = dx*dx + dy*dy
            # slight egg tilt/shape
            alpha = 255 if d <= 1.0 else 0
            if alpha:
                edge = d > 0.86
                v = 0xD8D8D8 if edge else 0xFFFFFF
                arr[y*32+x] = (alpha << 24) | (v << 16) | (v << 8) | v
            else:
                arr[y*32+x] = 0
    # 1-bpp mask bitmap, all zero (alpha controls transparency on modern Windows).
    mask = gdi32.CreateBitmap(32, 32, 1, 1, None)
    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                    ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                    ("hbmColor", wintypes.HBITMAP)]
    ii = ICONINFO(True, 0, 0, mask, hbmp)
    icon = user32.CreateIconIndirect(ctypes.byref(ii))
    gdi32.DeleteObject(mask)
    gdi32.DeleteObject(hbmp)
    return icon or user32.LoadIconW(None, IDI_APPLICATION)

MUTEX_NAME = "Global\\EggDesktop_Windows_Egg_Tray_Mutex"
mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
    sys.exit(0)

icon = None
nid = None
hwnd = None

@WNDPROC
def wndproc(hWnd, msg, wParam, lParam):
    global nid
    if msg == WM_TRAY:
        if lParam == WM_LBUTTONUP:
            user32.MessageBoxW(hWnd, "没那么重要，也没那么不重要。",
                               "蛋", MB_OK | MB_ICONINFORMATION)
        elif lParam == WM_RBUTTONUP:
            # Right click intentionally does nothing: the egg cannot be discarded.
            pass
        return 0
    if msg == WM_DESTROY:
        if nid:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        return 0
    return user32.DefWindowProcW(hWnd, msg, wParam, lParam)

def main():
    global icon, nid, hwnd
    hinst = kernel32.GetModuleHandleW(None)
    clsname = "EggDesktopEggTrayWindow"
    wc = WNDCLASSW()
    wc.lpfnWndProc = wndproc
    wc.hInstance = hinst
    wc.lpszClassName = clsname
    if not user32.RegisterClassW(ctypes.byref(wc)):
        if ctypes.get_last_error():
            pass
    hwnd = user32.CreateWindowExW(0, clsname, clsname, 0, 0, 0, 0, 0,
                                  0, 0, hinst, None)
    if not hwnd:
        return
    icon = make_egg_icon()
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(nid)
    nid.hWnd = hwnd
    nid.uID = 1
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = WM_TRAY
    nid.hIcon = icon
    nid.szTip = "蛋"
    shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

if __name__ == "__main__":
    try:
        main()
    finally:
        if icon:
            user32.DestroyIcon(icon)
        if mutex:
            kernel32.CloseHandle(mutex)
