# 4K Rhythm Game — 项目概要

基于 Python + Pygame 的 4K 下落式音游，支持皮肤、回放、osu! 同款判定、统计图表。

## 环境
- Python 3.14 + pygame 2.6.1
- 激活虚拟环境: `source ~/myenv/bin/activate`
- pygame 的 mixer 和 font 模块在 Python 3.14 上有 bug，已用 PIL 和 BASS 回退替代

## 项目结构

| 文件 | 作用 |
|------|------|
| `main.py` | 入口，循环: `welcome_screen → main_menu → preview → play_game` |
| `gameplay.py` | 核心游玩逻辑，皮肤渲染、判定、回放录制、结算界面 |
| `menus.py` | 欢迎界面、主菜单、设置（翻页）、流速/OD/判定线调节器、退出确认 |
| `preview.py` | 谱面预览、游玩历史、回放浏览入口 |
| `global_state.py` | 全局状态（config/screen/font/skin/key_map/audio/delay_history） |
| `skin_importer.py` | osu! 皮肤 .osk 导入、skin.ini 解析、图片加载(PIL回退) |
| `bass_audio.py` | BASS 音频引擎 ctypes 封装（替代 pygame.mixer） |
| `sonic_python.py` | C 语言 sonic 变调算法绑定（用于倍速不变调） |
| `replay.py` | 回放数据结构、保存/加载 .osr (gzip JSON) |
| `replay_viewer.py` | 回放播放器，调用 gameplay 渲染 + 结算 |
| `mania_difficulty.py` | osu! 同款难度星数计算（支持速度因子） |
| `osu_converter.py` | osu! .osz/.osu → 游戏 JSON 转换 |
| `editor.py` | 可视化制谱器 |
| `config.json` | 用户配置（键位/流速/OD/皮肤/判定线位置） |
| `history.json` | 每谱面最近 10 次游玩记录 |
| `delay_history.json` | 全局最近 200 次游玩平均偏移记录 |

## 导航层级

```
欢迎界面 ──ENTER──▶ 选歌界面 ──ENTER──▶ 预览 ──ENTER──▶ 游玩
   ▲                  │                                   │
   └──── ESC ─────────┘                                   │
   │                                                      │
  ESC                                                   结束
   ▼
退出确认
```

- `main_menu` 返回 `None` 时回到欢迎界面
- `play_game` 返回 `"restart"` 时重玩同谱面

## 核心架构

### 屏幕系统
- `g.screen`: 400×600 逻辑 Surface，所有渲染基于此（宽度可随舞台缩放动态变化）
- `g.real_screen`: 物理窗口（支持全屏 GPU 缩放）
- `g.update_display()`: 将 screen 缩放居中到 real_screen 并 flip
- GPU 全屏模式：`logical_w` 根据屏幕宽高比计算，`pygame.SCALED` 自动缩放无黑边

### 音频 (跨平台 BASS)
- 优先 BASS，回退 pygame.mixer
- macOS: `libbass.dylib` | Windows: `bass.dll` | Linux: `libbass.so`
- `bass_audio._find_bass_lib()` 自动按平台查找
- 统一接口: `g.audio_load/play/pause/unpause/stop/seek`
- 倍速时 sonic 生成变速 WAV，失败则用原音频

### 音频偏移 (osu! 同款)
- 实现公式: `game_clock = audio_position + global_offset`
- `current_time = real_elapsed * song_rate - map_offset - global_offset - LEAD_IN_TIME`
- 音频在 `current_time >= global_offset` 时播放（而非 `>= 0`）
- 正 offset → 游戏时钟领先音频 → 音符更早出现（补偿音频延迟）
- 负 offset → 游戏时钟落后音频 → 音符更晚出现（补偿输入延迟）
- seek 时: `audio_seek(target_ct - global_offset)`

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
- 判定窗口受倍速影响: 窗口值 × song_rate

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
- 回放数据包含: song_rate, od, scroll_speed, mirror_mode, hit_position

### 镜像模式
- 谱面加载时互换 lane: `{0:3, 1:2, 2:1, 3:0}`
- 配置项 `mirror_mode`，选歌界面 M 键切换
- 回放自动记录并还原

### 暂停恢复（回退机制）
- 选择「继续」后立即回退 3 秒，无倒计时
- 已判定音符 (hit/missed) 标记 `ghost = True`：不渲染，不参与判定
- `holding=True` 的长条不标 ghost：尾判正常，头部由 `not n.get("holding")` 保护
- keydown/keyup/底漏均检查 `not n.get("ghost", False)`

### 空格快进
- 仅 lead-in 阶段可用，只能使用一次
- 目标: `first_note_time - 3000`，仅当 `target_ct > 0` 时生效
- 调整 start_time 实现时间跳跃，同步 seek 音频

### 结算界面
- 第1页: 精度圆环 + Rank字母(SS/S/A/B/C/D) + 判定统计条 + mods 信息
- 第2页: 命中偏移直方图 (UR/σ/μ)
- 第3页: 时间-ACC 曲线 (A/D缩放 Z/C平移)
- 第4页: 每N秒ACC (X 切换N调节模式)
- ← → 翻页，回放时标题有 [REPLAY] 标记

### 延迟历史记录
- `delay_history.json`: 最近 200 局平均偏移
- 每局结算时从 `replay_data.judgments` 计算并 `add_delay_record()`
- 选歌界面 offset 行显示 `(avg: ±Xms)`

## 配置项 (config.json)
```
scroll_speed: 24        # osu! 风格流速
od: 5.0                 # 判定精度 0-11
hit_position: 500       # 判定线 Y 坐标
active_skin: "..."      # 当前皮肤名
key_bindings: [...]     # 整数键码或字符串键名
global_offset: 0        # 全局延迟偏移 ms (osu! 同款)
song_rate: 1.0          # 播放倍速 0.5-2.0
stage_spacing: 100      # 轨道间距
stage_scale: 1.0        # 舞台缩放
show_fps: True          # 游玩时显示 FPS
mirror_mode: False      # 镜像模式
player_name: "Player"   # 回放中的玩家名
```

## 注意事项
- 不要引入 numpy/scipy，保持轻量
- 皮肤 key 图片优先用 `D` 变体（亮色），`set_alpha` 不宜太低
- BASS 只在 init 时加载一次，全局单例
- `_PILFont.render` 接口兼容 `pygame.font.Font.render`
- 新功能需在 `load_config` 默认配置和 `init_globals` 中处理
- ReplayData 新增字段需同步更新 `to_dict` / `from_dict`
