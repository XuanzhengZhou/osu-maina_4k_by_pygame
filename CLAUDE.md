# 4K Rhythm Game — 项目概要

基于 Python + Pygame 的 4K 下落式音游，支持皮肤、回放、osu! 同款判定、统计图表。

## 环境
- Python 3.14 + pygame 2.6.1
- 激活虚拟环境: `source ~/myenv/bin/activate`
- pygame 的 mixer 和 font 模块在 Python 3.14 上有 bug，已用 PIL 和 BASS 回退替代

## 项目结构

| 文件 | 作用 |
|------|------|
| `main.py` | 入口，循环: `main_menu → preview → play_game` |
| `gameplay.py` | 核心游玩逻辑，皮肤渲染、判定、回放录制、结算界面 |
| `menus.py` | 主菜单、设置（翻页）、流速/OD/判定线调节器 |
| `preview.py` | 谱面预览、游玩历史、回放浏览入口 |
| `global_state.py` | 全局状态（config/screen/font/skin/key_map/audio） |
| `skin_importer.py` | osu! 皮肤 .osk 导入、skin.ini 解析、图片加载(PIL回退) |
| `bass_audio.py` | BASS 音频引擎 ctypes 封装（替代 pygame.mixer） |
| `sonic_python.py` | C 语言 sonic 变调算法绑定（用于倍速不变调） |
| `replay.py` | 回放数据结构、保存/加载 .osr (gzip JSON) |
| `replay_viewer.py` | 回放播放器，调用 gameplay 渲染 + 结算 |
| `mania_difficulty.py` | osu! 同款难度星数计算（支持速度因子） |
| `osu_converter.py` | osu! .osz/.osu → 游戏 JSON 转换 |
| `editor.py` | 可视化制谱器 |
| `config.json` | 用户配置（键位/流速/OD/皮肤/判定线位置） |

## 核心架构

### 屏幕系统
- `g.screen`: 400×600 逻辑 Surface，所有渲染基于此
- `g.real_screen`: 物理窗口（支持全屏 GPU 缩放）
- `g.update_display()`: 将 screen 缩放居中到 real_screen 并 flip

### 音频 (跨平台 BASS)
- 优先 BASS，回退 pygame.mixer
- macOS: `libbass.dylib` | Windows: `bass.dll` | Linux: `libbass.so`
- `bass_audio._find_bass_lib()` 自动按平台查找
- 统一接口: `g.audio_load/play/pause/unpause/stop`
- 倍速时 sonic 生成变速 WAV，失败则用原音频

### 字体
- 优先 pygame.font.Font，不可用时回退 `_PILFont` (PIL ImageFont)
- 字体文件: `SourceHanSansCN-Bold.otf`

### 图片
- `_load_image_pygame()`: pygame 失败时回退 PIL
- 用于背景、皮肤素材、封面加载

### 判定系统 (OD)
- osu! DifficultyRange 公式: OD 0/5/10 三锚点线性插值
- 6 级判定: PERFECT(305)/GREAT(300)/GOOD(200)/OK(100)/MEH(50)/MISS
- OD 范围 0-11，默认 5，设置界面 O 键调节

### 流速
- osu! 风格: `eff_speed = scroll_speed / 24.0 / song_rate`
- 默认 24，范围 5-60，设置界面第1页 L 键调节

### 皮肤系统
- `skins/<name>/skin.ini` 解析 4K 配置
- 支持: 音符/长条头体尾/按键底板/舞台背景/判定特效
- 默认使用 `key_{lane}D` (亮色变体)，释放时半透明
- 舞台背景回退到 `mania-stage-bottom.png`

### 回放
- 格式: gzip 压缩 JSON (.osr)
- 录制: 每帧记录 4 轨按键位掩码 + 判定记录
- 结算按 S 保存到谱面目录
- 预览界面按 R 浏览回放

### 结算界面
- 第1页: 精度圆环 + Rank字母(SS/S/A/B/C/D) + 判定统计条
- 第2页: 命中偏移直方图 (UR/σ/μ)
- 第3页: 时间-ACC 曲线 (A/D缩放 Z/C平移)
- 第4页: 每N秒ACC (X 切换N调节模式)
- ← → 翻页，回放时标题有 [REPLAY] 标记

## 配置项 (config.json)
```
scroll_speed: 24        # osu! 风格流速
od: 5.0                 # 判定精度 0-11
hit_position: 500       # 判定线 Y 坐标
active_skin: "..."      # 当前皮肤名
key_bindings: [...]     # 整数键码或字符串键名
global_offset: 0        # 全局延迟偏移 ms
song_rate: 1.0          # 播放倍速
```

## 注意事项
- 不要引入 numpy/scipy，保持轻量
- 皮肤 key 图片优先用 `D` 变体（亮色），`set_alpha` 不宜太低
- BASS 只在 init 时加载一次，全局单例
- `_PILFont.render` 接口兼容 `pygame.font.Font.render`
- 新功能需在 `init_globals` 中处理默认配置
