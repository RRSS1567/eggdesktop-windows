#!/bin/zsh
# 双击启动蛋房。建议在终端全屏状态下运行以获得完整体验。
# 启动时把本窗口切成 Basic 描述文件(不透明黑底, 经典耐看), 退出时还原原配置;
# 不想要这层换装, 删掉下面两个 osascript 段即可。
cd "$(dirname "$0")"

INFO=$(osascript 2>/dev/null <<'OSA'
tell application "Terminal"
    set w to front window
    set wid to id of w
    set orig to name of current settings of w
    set current settings of w to settings set "Basic"
    return (wid as text) & "|" & orig
end tell
OSA
)
WID=""
ORIG=""
case "$INFO" in
    *"|"*) WID=${INFO%%|*}; ORIG=${INFO#*|} ;;
esac

sleep 0.5   # 等窗口应用新描述文件(字体与尺寸可能随之变化)

python3 eggdesktop.py

if [ -n "$WID" ] && [ -n "$ORIG" ]; then
    osascript 2>/dev/null <<OSA
tell application "Terminal"
    try
        set current settings of (first window whose id is $WID) to settings set "$ORIG"
    end try
end tell
OSA
fi
