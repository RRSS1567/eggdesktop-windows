// eggbar —— 菜单栏里的那颗蛋。
// 从暗世界(终端)被带回光世界(桌面)的唯一物品。
// 点击 = "使用"蛋, 弹窗只有一句话。没有退出选项: 蛋不能被丢弃。
// 实在要移除: killall eggbar
import Cocoa

let EGG_LINE = "Not too important, not too unimportant."

// 高倍位图渲染: 18pt 的菜单栏蛋按 scale 倍出图(Retina/高分屏不虚),
// 弹窗图标用 64pt 版本, 轮廓依旧锐利
func makeEggImage(points: CGFloat, scale: CGFloat) -> NSImage {
    let px = Int(points * scale)
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil,
                                     pixelsWide: px, pixelsHigh: px,
                                     bitsPerSample: 8, samplesPerPixel: 4,
                                     hasAlpha: true, isPlanar: false,
                                     colorSpaceName: .calibratedRGB,
                                     bytesPerRow: 0, bitsPerPixel: 0) else {
        return NSImage()
    }
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    // 蛋形路径设计于 18×18 坐标系: k 把它统一到任意目标位图尺寸,
    // 菜单栏 18pt 与弹窗 96pt 共用同一条贝塞尔曲线, 都不变形
    let k = points * scale / 18.0
    func P(_ x: CGFloat, _ y: CGFloat) -> NSPoint { NSPoint(x: x * k, y: y * k) }
    // 纯色蛋形: 顶点窄、腹部饱满的贝塞尔蛋, 不是椭圆(18pt 设计坐标 × s)
    let p = NSBezierPath()
    p.move(to: P(9.0, 15.3))
    p.curve(to: P(4.1, 8.0),
            controlPoint1: P(6.7, 15.3),
            controlPoint2: P(4.1, 12.2))
    p.curve(to: P(9.0, 2.7),
            controlPoint1: P(4.1, 4.2),
            controlPoint2: P(6.0, 2.7))
    p.curve(to: P(13.9, 8.0),
            controlPoint1: P(12.0, 2.7),
            controlPoint2: P(13.9, 4.2))
    p.curve(to: P(9.0, 15.3),
            controlPoint1: P(13.9, 12.2),
            controlPoint2: P(11.3, 15.3))
    p.close()
    NSColor.white.setFill()
    p.fill()
    // 描边: 浅色模式下白蛋与白底不可区分, 深色模式里这道暗边几乎隐形
    NSColor.black.withAlphaComponent(0.55).setStroke()
    p.lineWidth = 1.0 * k
    p.stroke()
    NSGraphicsContext.restoreGraphicsState()
    let img = NSImage(size: NSSize(width: points, height: points))
    img.addRepresentation(rep)
    img.isTemplate = false  // 保持纯白, 不随深浅色模式反色
    return img
}

// NSApplication.stopModal 有重载, 直接当 action 会歧义——包一层专用 target
class ModalStopper: NSObject {
    @objc func stop() { NSApp.stopModal() }
}
let modalStopper = ModalStopper()

func showEggAlert() {
    let app = NSApplication.shared
    app.activate(ignoringOtherApps: true)
    // 新版 macOS 的 NSAlert: icon 被限死在固定小格, accessoryView 又被
    // Auto Layout 压塌——弹窗干脆自绘成毛玻璃面板, 尺寸全由自己说了算
    let W: CGFloat = 300, H: CGFloat = 256
    let panel = NSPanel(
        contentRect: NSRect(x: 0, y: 0, width: W, height: H),
        styleMask: [.titled, .fullSizeContentView],
        backing: .buffered, defer: false)
    panel.titlebarAppearsTransparent = true
    panel.titleVisibility = .hidden
    panel.isOpaque = false
    panel.backgroundColor = .clear
    panel.isMovableByWindowBackground = true
    panel.level = .floating
    panel.standardWindowButton(.closeButton)?.isHidden = true
    panel.standardWindowButton(.miniaturizeButton)?.isHidden = true
    panel.standardWindowButton(.zoomButton)?.isHidden = true

    let bg = NSVisualEffectView(frame: NSRect(x: 0, y: 0, width: W, height: H))
    bg.material = .popover
    bg.state = .active
    bg.blendingMode = .behindWindow

    let side: CGFloat = 96
    let egg = NSImageView(frame: NSRect(x: (W - side) / 2,
                                        y: H - side - 26,
                                        width: side, height: side))
    egg.image = makeEggImage(points: side, scale: 3)
    egg.imageScaling = .scaleProportionallyUpOrDown

    let label = NSTextField(wrappingLabelWithString: EGG_LINE)
    label.font = NSFont.boldSystemFont(ofSize: 13)
    label.alignment = .center
    label.frame = NSRect(x: 20, y: 78, width: W - 40, height: 40)

    let button = NSButton(frame: NSRect(x: (W - 180) / 2, y: 22,
                                        width: 180, height: 32))
    button.title = "OK"
    button.bezelStyle = .rounded
    button.bezelColor = .controlAccentColor
    button.keyEquivalent = "\r"
    button.target = modalStopper
    button.action = #selector(ModalStopper.stop)

    bg.addSubview(egg)
    bg.addSubview(label)
    bg.addSubview(button)
    panel.contentView = bg
    panel.center()
    app.runModal(for: panel)
    panel.orderOut(nil)
}

class EggDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem!

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = makeEggImage(points: 18, scale: 3)
            button.imagePosition = .imageOnly
            button.target = self
            button.action = #selector(useEgg)
        }
    }

    @objc func useEgg() {
        showEggAlert()
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)  // 无 Dock 图标, 只住菜单栏

// 验收模式: ./eggbar --show-alert —— 不驻留菜单栏, 直接弹窗看效果, 点完即退
if CommandLine.arguments.contains("--show-alert") {
    showEggAlert()
    exit(0)
}

let delegate = EggDelegate()
app.delegate = delegate
app.run()
