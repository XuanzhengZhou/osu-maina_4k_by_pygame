# 4K Rhythm Game

基于 Python + Pygame 的 4K 下落式音游，支持 osu! 皮肤、回放、osu! 同款 OD 判定、统计图表。

---

## 附带的默认内容

项目预装了开箱即用的皮肤和曲包：

- **默认皮肤** `skins/R Skin v2.2 (New style_Diamond) (Retsukiya)` — 作者日常使用的皮肤，钻石风格按键、清晰的判定特效，手感舒适
- **附赠曲包** `songs/1360153 Various Artists - Malody Essential Pack` — 来自 Malody 社区的 27 首入门级 4K 谱面，难度适中，适合新手练习和测试

> 启动游戏后按 `S` → 第2页可切换皮肤，主菜单选歌即可游玩附赠曲包。

---

## 各平台运行

### 依赖
```bash
pip install pygame Pillow
```

### 配置 BASS 音频库
将 `libs/` 下对应平台的库文件复制到**项目根目录**（与 `main.py` 同级）：

| 平台 | 源文件 | 目标文件名 |
|------|--------|-----------|
| macOS | `libs/libbass.dylib` | `libbass.dylib` (无需改名) |
| Windows 64位 | `libs/bass_x64.dll` | `bass.dll` |
| Windows 32位 | `libs/bass.dll` | `bass.dll` |
| Linux x86_64 | `libs/linux/libbass.so` | `libbass.so` |
| Linux ARM | `libs/linux/libbass_aarch64.so` | `libbass.so` |
| Linux 32位 | `libs/linux/libbass_x86.so` | `libbass.so` |

> 如果 pygame.mixer 不可用（如 Python 3.14），游戏自动使用 BASS；字体也自动回退到 PIL。

### 运行
```bash
python main.py
```

---

## 导入歌曲

### 方式一：命令行（推荐）
```bash
# 将 .osz 文件放入 songs/ 目录，然后：
python -c "from osu_converter import handle_osz_file; handle_osz_file('songs/你的谱面.osz')"
```

### 方式二：GUI
```bash
python osu_converter.py
# 弹出文件选择窗口 → 选择 .osz 或 .osu → 自动转换
```
> GUI 模式需要 tkinter（macOS/Windows 自带，Linux 需 `apt install python3-tk`）

转换后的曲包位于 `songs/<曲包名>/`，每个难度一个 `.json` 文件。启动游戏即可在选歌菜单看到。

### 谱面结构
```
songs/
  └── 曲包名/
       ├── audio.mp3        # 歌曲文件
       ├── bg.jpg           # 背景封面
       ├── 难度1.osu        # 原始谱面
       └── 难度1.json       # 转换后谱面（游戏读取此文件）
```

---

## 导入皮肤

1. 将 osu! 皮肤 `.osk` 文件放入 `skins/` 目录
2. 启动游戏 → 按 `S` 进入设置 → 按 `→` 翻到第2页
3. 按 `I` 导入 → 选择皮肤文件 → `ENTER` 确认
4. 按 `M` 循环切换已安装的皮肤，按 `0` 恢复默认

> 已有一个测试皮肤 `skins/R Skin v2.2 ... .osz` 可直接导入试用。

皮肤支持元素：
- 音符贴图（每轨独立）
- 长条（头部 / 平铺身体 / 尾部）
- 按键底板（按下/释放双状态）
- 舞台背景
- 判定特效（300g/300/200/100/50/0 六种）

---

## 主界面

| 按键 | 功能 |
| :--- | :--- |
| `↑/↓` | 切换曲目 |
| `ENTER` | 进入谱面预览 |
| `A/D` | 全局偏移 ±5ms (Shift ±1ms) |
| `W/E` | 倍速 ±0.1x (Shift ±0.01x) |
| `S` | 进入设置 (←→翻3页) |
| `F` | 全屏切换 |
| `R` | 分辨率切换 |

## 设置界面 (←→ 翻 3 页)

| 页 | 功能 | 操作 |
|:---|:---|:---|
| 1 | 键位绑定 | [1-4] 改键，支持小键盘 |
| 1 | 流速 | [L] A/D 加减，S 保存 |
| 2 | 全屏/分辨率 | [F/R] |
| 2 | 皮肤管理 | [I]导入 [M]切换 [DEL]删除 [0]默认 |
| 3 | OD 判定精度 | [O] 0~11，步长 0.1 |
| 3 | 判定线位置 | [J] A/D 调节 |

## 游玩界面

```
Combo: 42               ACC: 98.5%
Offset: -12ms (avg -8)  KPS: 8.3
```

### 判定 (osu! 同款 OD 系统)
| 判定 | 分数 | OD=5 窗口 |
|------|------|-----------|
| PERFECT | 305 | ±19ms |
| GREAT | 300 | ±49ms |
| GOOD | 200 | ±82ms |
| OK | 100 | ±112ms |
| MEH | 50 | ±136ms |
| MISS | 0 | ±173ms |

- OD 范围 0-11，默认 5
- 流速 5-60，默认 24

---

## 结算界面 (←→ 翻 4 页)

### 第1页 — 成绩
- 精度圆环（渐变色填充）+ 中心 Rank 字母 (SS~D)
- 标准化分数 (0~1,000,000)
- 6 种判定的彩色统计条 + 数量 + 百分比
- 按 `S` 保存回放

### 第2页 — 命中偏移直方图
- 横轴: 偏移时间 (-150~+150ms)，纵轴: 次数
- 底部显示 μ(均值)、σ(标准差)、UR=10σ

### 第3页 — 时间-ACC 曲线
- 累计 ACC 随谱面时间变化
- **A/D** 缩放 **Z/C** 平移

### 第4页 — 每N秒分段ACC
- 每 N 秒独立计算 ACC，柱状图
- **A/D** 缩放 **Z/C** 平移 **X** 切换 N 调节模式

---

## 回放

- 游玩自动录制，结算按 `S` 保存 `.osr`
- 预览界面按 `R` 浏览/播放回放
- 回放自动切换记录的倍速/OD/流速
- 回放结算与正常游玩完全一致（含4页统计）

---

## 项目结构

| 文件 | 作用 |
|------|------|
| `main.py` | 入口 |
| `gameplay.py` | 游玩、判定、回放录制、结算 |
| `menus.py` | 菜单、设置、调节器 |
| `preview.py` | 预览、历史、回放入口 |
| `global_state.py` | 全局状态 |
| `skin_importer.py` | osu! 皮肤导入 |
| `bass_audio.py` | BASS 跨平台音频 |
| `replay.py` / `replay_viewer.py` | 回放系统 |
| `mania_difficulty.py` | 星数计算 |
| `osu_converter.py` | osu! 谱面转换 |
| `editor.py` | 制谱器 |
| `sonic_python.py` | 变速算法 |
| `libs/` | 全平台 BASS 音频库 |
