# eggdesktop 🥚

**桌面与桌面之间，有个桌面。**

在 macOS 终端里完整复现《三角符文》(DELTARUNE) 的「蛋房」彩蛋：那棵树、树后的男人，和那颗「不是很重要，也不是不重要」的蛋。

**A full recreation of DELTARUNE's "Egg Room" easter egg inside a macOS terminal — the tree, the man behind it, and the egg that is *not too important, not too unimportant*.**

📺 演示视频 Demo：[Bilibili](https://www.bilibili.com/video/BV1iUYF6LEmf)

---

## 特性 | Features

- 全屏伪终端：窗口是真的，shell 是假的——`cat tree` 试试
- 树会动：ASCII 逐行打印成型，然后突变为高分辨率半块字符动画
- `cd .behind`：假死、斑块腐化 glitch、清屏重演——进入蛋房
- 与男人的对话（Y/N 交互），蛋会真正进入你的**菜单栏**
- 点击菜单栏的蛋，只有一句话
- `whoami`：蛋房深处的你，HP 90，LV 1，没有称号

- A fullscreen pseudo-terminal: the window is real, the shell is not — try `cat tree`
- The tree lives: printed line-by-line in ASCII, then mutates into a hi-res half-block animation
- `cd .behind`: freeze, patchy corruption glitch, redraw — welcome to the egg room
- Talk to the man (Y/N), and the egg literally enters your **menu bar**
- Click it. It says one thing only
- `whoami`: in the egg room you have 90 HP, LV 1, and no title

## 运行 | Run

要求 Requirements：**macOS** + Python 3（系统自带 / built-in）

```bash
# 方式一：双击 run.command
# 方式二：终端执行
python3 eggdesktop.py
```

> macOS 可能拦截菜单栏蛋组件（eggbar，未签名）。如遇拦截：
> If macOS blocks the menu-bar egg (unsigned binary), run:
>
> ```bash
> xattr -d com.apple.quarantine eggbar
> ```
>
> 仅移除「下载自网络」标记，不改动程序本身。
> This only removes the "downloaded from the internet" flag.

## 校验完整性 | Verify

网盘与 Release 中的 `eggdesktop.zip` 是同一份文件：

```bash
shasum -a 256 eggdesktop.zip
# 1011b0a7323950b737cce597af5c676cee1f15876466b590ffd794e49e6f1080
```

## 玩法 | Walkthrough（剧透 Spoilers）

<details>
<summary>点击展开 | Click to reveal</summary>

```
% cat tree        # 看看那棵树 / look at the tree
% ls -a           # 现在多了什么 / what's new
% cd .behind      # 到树后面去 / go behind it
% man tree        # 男人与树 / the man and the tree
% egg             # 之后 / afterwards
% whoami          # 在蛋房里, 你是谁 / who are you, in here
% quit            # 回到光世界 / return to the light world
```

然后，看看你的菜单栏。
Then, take a look at your menu bar.

</details>

## 致谢 | Credits

- 原作 [DELTARUNE](https://deltarune.com) by **Toby Fox**——树、男人与蛋均出自游戏彩蛋，相关设定与素材版权归 Toby Fox 所有
- Original game [DELTARUNE](https://deltarune.com) by **Toby Fox** — the tree, the man and the egg are from the game's easter egg; all related rights belong to him
- 与 [Kimi](https://www.kimi.com)（Moonshot AI）结对编程完成 / Built via pair-programming with [Kimi](https://www.kimi.com)

## License

代码以 [MIT](LICENSE) 发布。游戏相关内容权利归原作者。
Code released under [MIT](LICENSE). All game-related rights belong to the original author.
