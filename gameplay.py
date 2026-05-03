import pygame
import sys
import os
import glob
import json
import subprocess
import sonic_python
import global_state as g
from skin_importer import _load_image_safe
from replay import ReplayData, ReplayJudgment, save_replay


# --- 皮肤渲染辅助函数 ---

def _scale_to_width(img, target_w):
    """将图片等比缩放到目标宽度。"""
    if img is None:
        return None
    iw, ih = img.get_size()
    if iw <= 0:
        return None
    target_h = int(ih * target_w / iw)
    if target_h <= 0:
        target_h = 1
    return pygame.transform.smoothscale(img, (int(target_w), target_h))


def _draw_tap_note_with_skin(lane, y, note_missed, lane_x):
    """使用皮肤绘制 tap note；如果皮肤不可用则回退到默认矩形。"""
    sa = g.skin_assets
    lane_key = f"note_{lane}"
    if sa and sa["images"].get(lane_key):
        img = _scale_to_width(sa["images"][lane_key], 80)
        if img:
            iw, ih = img.get_size()
            if note_missed:
                img = img.copy()
                img.set_alpha(80)
            g.screen.blit(img, (lane_x - iw // 2, int(y) - ih // 2))
            return True
    return False


def _draw_hold_note_with_skin(lane, head_y, tail_y, note, lane_x):
    """使用皮肤绘制 hold note（长条）。"""
    sa = g.skin_assets
    if not sa:
        return False

    head_key = f"hold_head_{lane}"
    body_key = f"hold_body_{lane}"
    tail_key = f"hold_tail_{lane}"

    head_img = sa["images"].get(head_key)
    body_img = sa["images"].get(body_key)
    tail_img = sa["images"].get(tail_key)

    if head_img is None:
        return False

    note_w = 80
    head_scaled = _scale_to_width(head_img, note_w)
    if head_scaled is None:
        return False

    int_head_y = int(head_y)
    int_tail_y = int(tail_y)

    holding = note.get("holding", False)
    missed = note.get("missed", False)

    # 透明度
    if missed:
        alpha = 80
    elif holding:
        alpha = 255
    else:
        alpha = 200

    # 绘制 body（平铺）
    if body_img and int_head_y - int_tail_y > 0:
        body_scaled = _scale_to_width(body_img, note_w)
        if body_scaled:
            bw, bh = body_scaled.get_size()
            if bh < 1:
                bh = 1

            # body 从头底部平铺到尾顶部，无缝连接
            head_h = head_scaled.get_height()
            tail_h = 0
            tail_scaled = None
            if tail_img:
                tail_scaled = _scale_to_width(tail_img, note_w)
                if tail_scaled:
                    tail_h = tail_scaled.get_height()

            body_top = int_head_y - head_h // 2   # 头图片中心
            body_bottom = int_tail_y - tail_h      # 尾图片顶部（尾底部对齐 int_tail_y）
            body_height = body_top - body_bottom

            if body_height > 0:
                # 裁剪绘制区域
                old_clip = g.screen.get_clip()
                clip_rect = pygame.Rect(lane_x - bw // 2, body_bottom, bw, body_height)
                if old_clip:
                    clip_rect = clip_rect.clip(old_clip)
                g.screen.set_clip(clip_rect)

                # 从下往上平铺
                tile_y = body_top
                while tile_y > body_bottom:
                    g.screen.blit(body_scaled, (lane_x - bw // 2, tile_y - bh))
                    tile_y -= bh

                g.screen.set_clip(old_clip)

    # 绘制头部
    head_h = head_scaled.get_height()
    if missed:
        head_scaled = head_scaled.copy()
        head_scaled.set_alpha(alpha)
    elif holding:
        pass  # 保持原样
    else:
        head_scaled = head_scaled.copy()
        head_scaled.set_alpha(alpha)

    g.screen.blit(head_scaled, (lane_x - head_scaled.get_width() // 2, int_head_y - head_h))

    # 绘制尾部
    if tail_img:
        tail_scaled = _scale_to_width(tail_img, note_w)
        if tail_scaled:
            if missed:
                tail_scaled = tail_scaled.copy()
                tail_scaled.set_alpha(alpha)
            tail_flipped = pygame.transform.rotate(tail_scaled, 180)
            g.screen.blit(tail_flipped, (lane_x - tail_flipped.get_width() // 2, int_tail_y - tail_flipped.get_height()))

    return True


def _draw_key_pads(lane_pressed_states):
    """在屏幕底部绘制按键底板。"""
    sa = g.skin_assets
    if not sa:
        return False

    LANES = [50, 150, 250, 350]
    # 按键底板始终固定在屏幕底部，不随判定线移动
    key_area_y = g.SCREEN_HEIGHT - 105

    has_keys = False
    for lane in range(4):
        # 优先用 D（亮色）变体，因为部分皮肤默认变体是黑色不可见
        key_img = sa["images"].get(f"key_{lane}D") or sa["images"].get(f"key_{lane}")
        if key_img is None:
            continue

        has_keys = True
        scaled = _scale_to_width(key_img, 75)
        if not scaled:
            continue

        iw, ih = scaled.get_size()
        if ih > 100:
            crop_h = min(100, ih)
            sub = scaled.subsurface((0, ih - crop_h, iw, crop_h))
        else:
            sub = scaled
            crop_h = ih

        # 按下时全亮，释放时半透明
        if not lane_pressed_states[lane]:
            sub = sub.copy()
            sub.set_alpha(120)

        g.screen.blit(sub, (LANES[lane] - iw // 2, key_area_y))

    return has_keys


def _draw_stage_background():
    """绘制舞台背景。"""
    sa = g.skin_assets
    if not sa:
        return False

    stage_img = sa["images"].get("stage_bottom")
    # 回退：如果配置引用的图片太小，尝试加载标准 mania-stage-bottom.png
    if stage_img is not None:
        iw, ih = stage_img.get_size()
        if iw < 10 or ih < 2:
            stage_img = None

    if stage_img is None:
        skin_dir = os.path.join("skins", g.active_skin_name or "")
        fallback_path = os.path.join(skin_dir, "mania-stage-bottom.png")
        if os.path.exists(fallback_path):
            stage_img = _load_image_safe(fallback_path)

    if stage_img is None:
        return False

    iw, ih = stage_img.get_size()
    scaled = pygame.transform.smoothscale(stage_img, (g.SCREEN_WIDTH, ih))
    # 舞台背景固定在默认位置，不随判定线移动
    y_pos = 500 - ih
    g.screen.blit(scaled, (0, y_pos))
    return True


def _draw_hit_burst(judgement_type, frame_counter):
    """绘制判定爆发特效图片。返回 True 表示已渲染。"""
    sa = g.skin_assets
    if not sa:
        return False

    # osu! 同款映射: 判定结果 → 皮肤图片
    hit_map = {
        "PERFECT": "hit_300g",   # 300g (炫彩)
        "GREAT":   "hit_300",    # 300
        "GOOD":    "hit_200",    # 200
        "OK":      "hit_100",    # 100
        "MEH":     "hit_50",     # 50
        "MISS":    "hit_0",      # 0
    }
    img_key = hit_map.get(judgement_type)
    if img_key is None:
        return False

    img = sa["images"].get(img_key)
    # 逐级回退：找不到图片时找低一级的
    if img is None:
        fallbacks = {
            "hit_300g": ["hit_300"],
            "hit_300":  ["hit_200"],
            "hit_200":  ["hit_100"],
            "hit_100":  ["hit_50", "hit_0"],
            "hit_0":    [],
        }
        for fb in fallbacks.get(img_key, []):
            img = sa["images"].get(fb)
            if img is not None:
                break

    if img is None:
        return False

    scaled = _scale_to_width(img, 180)
    if scaled:
        iw, ih = scaled.get_size()
        x = g.SCREEN_WIDTH // 2 - iw // 2
        y = 250 - ih // 2
        # 渐隐动画：随时间逐渐透明
        alpha = max(0, 255 - int(frame_counter * 6))
        if alpha <= 0:
            return True  # 完全透明，跳过绘制
        burst = scaled.copy()
        burst.set_alpha(alpha)
        g.screen.blit(burst, (x, y))
        return True
    return False


# --- 标准化分数 & Rank ---

RANK_COLORS = {
    "SS": (0xde, 0x31, 0xae), "S": (0x02, 0xb5, 0xc3),
    "A": (0x88, 0xda, 0x20), "B": (0xe3, 0xb1, 0x30),
    "C": (0xff, 0x8e, 0x5d), "D": (0xff, 0x5a, 0x5a),
}


def calc_standardized_score(accuracy, combo_progress, accuracy_progress, bonus=0):
    """osu! mania 标准化分数 (0~1,000,000)"""
    acc_pow = accuracy ** (2 + 2 * accuracy) if accuracy > 0 else 0
    return int(150000 * combo_progress + 850000 * acc_pow * accuracy_progress + bonus)


def get_rank(accuracy, counts):
    """根据精度和判定统计计算 Rank。"""
    if accuracy >= 1.0 and counts.get("good", 0) == 0 and \
       counts.get("ok", 0) == 0 and counts.get("meh", 0) == 0 and counts.get("miss", 0) == 0:
        return "SS"
    if accuracy >= 0.95: return "S"
    if accuracy >= 0.9: return "A"
    if accuracy >= 0.8: return "B"
    if accuracy >= 0.7: return "C"
    return "D"


def _draw_accuracy_circle(screen, cx, cy, radius, accuracy, rank, rank_color):
    """绘制精度圆环和 Rank 字母。"""
    import math
    # 灰色底环
    pygame.draw.circle(screen, (60, 60, 60), (cx, cy), radius, 6)
    # 渐变色填充环: 用多段短弧模拟渐变
    segs = 60
    fill_angle = accuracy * 360
    for i in range(int(segs * accuracy)):
        a1 = math.radians(-90 + i * 360 / segs)
        a2 = math.radians(-90 + (i + 1) * 360 / segs)
        t = i / segs
        r = int(0x7C + (0xBA - 0x7C) * t)
        g_c = int(0xF6 + (0xFF - 0xF6) * t)
        b = int(0xFF + (0xA9 - 0xFF) * t)
        color = (r, g_c, b)
        # 画弧线段
        pts = [(cx, cy)]
        for a in [a1 + (a2 - a1) * j / 4 for j in range(5)]:
            pts.append((cx + (radius - 1) * math.cos(a), cy + (radius - 1) * math.sin(a)))
        if len(pts) >= 3:
            pygame.draw.polygon(screen, color, pts)
    # 内圈：Rank 字母
    inner_r = radius - 8
    pygame.draw.circle(screen, (30, 30, 40), (cx, cy), inner_r)
    rank_font_size = 52 if rank != "SS" else 44
    rank_surf = g.font.render(rank, True, rank_color)
    rs = pygame.transform.scale(rank_surf,
        (rank_surf.get_width() * rank_font_size // 36, rank_font_size))
    screen.blit(rs, (cx - rs.get_width() // 2, cy - rs.get_height() // 2))


def _draw_judgment_bars(screen, y_start, counts, total):
    """绘制彩色判定统计条。"""
    items = [
        ("PERFECT", counts.get("perfect", 0), (0xde, 0x31, 0xae)),
        ("GREAT",   counts.get("great", 0),   (0x02, 0xb5, 0xc3)),
        ("GOOD",    counts.get("good", 0),    (0x88, 0xda, 0x20)),
        ("OK",      counts.get("ok", 0),      (0xe3, 0xb1, 0x30)),
        ("MEH",     counts.get("meh", 0),     (0xff, 0x8e, 0x5d)),
        ("MISS",    counts.get("miss", 0),    (0xff, 0x5a, 0x5a)),
    ]
    bar_max_w = 150
    y = y_start
    for label, cnt, color in items:
        pct = cnt / total * 100 if total > 0 else 0
        bar_w = int(bar_max_w * cnt / total) if total > 0 else 0
        lbl = g.tiny_font.render(f"{label}", True, color)
        g.screen.blit(lbl, (50, y))
        pygame.draw.rect(g.screen, (40, 40, 40), (140, y + 2, bar_max_w, 12))
        if bar_w > 0:
            pygame.draw.rect(g.screen, color, (140, y + 2, bar_w, 12))
        cnt_text = g.tiny_font.render(f"{cnt} ({pct:.1f}%)", True, (200, 200, 200))
        g.screen.blit(cnt_text, (140 + bar_max_w + 10, y))
        y += 22


# --- 统计图表 ---

def _draw_histogram(screen, offsets, x, y, w, h):
    """绘制命中偏移直方图。"""
    if not offsets: return
    import math
    bin_w = 5  # ms per bin
    bins = {}
    for o in offsets:
        b = int((o + 150) // bin_w) * bin_w - 150
        bins[b] = bins.get(b, 0) + 1

    max_cnt = max(bins.values()) if bins else 1
    bar_w = max(2, w // 60)
    for b_val in range(-150, 151, bin_w):
        cnt = bins.get(b_val, 0)
        bar_h = int(cnt / max_cnt * h)
        bx = x + int((b_val + 150) / 300 * w)
        color = (100, 255, 100) if abs(b_val) <= 20 else (255, 200, 50)
        pygame.draw.rect(screen, color, (bx, y + h - bar_h, bar_w, bar_h))

    pygame.draw.line(screen, (255, 255, 255), (x, y + h // 2), (x + w, y + h // 2), 1)
    pygame.draw.line(screen, (255, 0, 0), (x + w // 2, y), (x + w // 2, y + h), 2)

    mean = sum(offsets) / len(offsets) if offsets else 0
    variance = sum((o - mean) ** 2 for o in offsets) / len(offsets) if offsets else 0
    sigma = math.sqrt(variance)
    ur = 10.0 * sigma  # unstable rate

    info = g.tiny_font.render(
        f"μ={mean:.1f}ms  σ={sigma:.1f}ms  UR={ur:.1f}  n={len(offsets)}", True, (200, 200, 200))
    screen.blit(info, (x, y + h + 5))


def _draw_time_acc_curve(screen, judgments, total_notes, x, y, w, h, view_start, view_end):
    """绘制时间-ACC 曲线。"""
    if not judgments: return
    # 累计 ACC
    cum_score = 0; cum_total = 0
    pts = []
    duration = judgments[-1].time_ms - judgments[0].time_ms if judgments else 1
    for j in judgments:
        weights = {"PERFECT": 305, "GREAT": 300, "GOOD": 200, "OK": 100, "MEH": 50, "MISS": 0}
        cum_score += weights.get(j.type, 0)
        cum_total += 305
        t_rel = (j.time_ms - judgments[0].time_ms) / max(duration, 1)
        acc = cum_score / cum_total * 100 if cum_total > 0 else 100
        pts.append((t_rel, acc))

    # 绘制
    pygame.draw.rect(screen, (30, 30, 40), (x, y, w, h))
    pygame.draw.line(screen, (100, 100, 100), (x, y), (x, y + h))
    pygame.draw.line(screen, (100, 100, 100), (x, y + h), (x + w, y + h))
    pygame.draw.line(screen, (60, 60, 80), (x, y + h // 2), (x + w, y + h // 2))

    if view_end <= view_start: view_end = view_start + 1
    for i in range(1, len(pts)):
        t0, a0 = pts[i - 1]; t1, a1 = pts[i]
        sx = (t0 - view_start) / (view_end - view_start)
        ex = (t1 - view_start) / (view_end - view_start)
        if sx > 1 or ex < 0: continue
        sx_c = max(0, min(1, sx)); ex_c = max(0, min(1, ex))
        px0 = x + int(sx_c * w); py0 = y + h - int(a0 / 100 * h)
        px1 = x + int(ex_c * w); py1 = y + h - int(a1 / 100 * h)
        if abs(px1 - px0) < 10:
            pygame.draw.line(screen, (0, 255, 200), (px0, py0), (px1, py1), 2)

    # 标签
    lab = g.tiny_font.render(f"Time-ACC  [{view_start:.0%}~{view_end:.0%}]", True, (200, 200, 200))
    screen.blit(lab, (x, y + h + 5))


def _draw_nsec_acc(screen, judgments, total_duration, x, y, w, h, n_sec, view_start, view_end):
    """绘制每 N 秒 ACC 柱状图。"""
    if not judgments or total_duration <= 0: return
    sec_buckets = {}
    for j in judgments:
        bucket = int(j.time_ms / 1000 / n_sec)
        if bucket not in sec_buckets:
            sec_buckets[bucket] = {"score": 0, "total": 0}
        weights = {"PERFECT": 305, "GREAT": 300, "GOOD": 200, "OK": 100, "MEH": 50, "MISS": 0}
        sec_buckets[bucket]["score"] += weights.get(j.type, 0)
        sec_buckets[bucket]["total"] += 305

    max_bucket = max(sec_buckets.keys()) if sec_buckets else 0
    view_buckets = int((view_end - view_start) * max_bucket) + 1

    pygame.draw.rect(screen, (30, 30, 40), (x, y, w, h))
    bar_w = max(2, w // max(view_buckets, 1))
    for bk in sorted(sec_buckets.keys()):
        b_rel = bk / max(max_bucket, 1)
        if b_rel < view_start or b_rel > view_end: continue
        bx = x + int((b_rel - view_start) / (view_end - view_start) * w)
        d = sec_buckets[bk]
        acc_v = d["score"] / d["total"] * 100 if d["total"] > 0 else 0
        bar_h = int(acc_v / 100 * h)
        c = (0, 200, 100) if acc_v > 95 else (200, 200, 50) if acc_v > 80 else (200, 100, 50)
        pygame.draw.rect(screen, c, (bx, y + h - bar_h, bar_w, bar_h))

    lab = g.tiny_font.render(f"{n_sec}s-ACC  [{view_start:.0%}~{view_end:.0%}]  [X] n={n_sec:.1f}", True, (200, 200, 200))
    screen.blit(lab, (x, y + h + 5))


def play_game(map_path):
    
    LANES = [50, 150, 250, 350]
    HIT_Y = g.config.get("hit_position", 500)

    song_rate = g.config.get("song_rate", 1.0)
    
    od = g.config.get("od", 5.0)

    def _dr(d0, d5, d10):
        """osu! DifficultyRange: OD 0/5/10 锚点间线性插值"""
        if od > 5:
            return d5 + (d10 - d5) * (od - 5) / 5
        elif od < 5:
            return d5 - (d5 - d0) * (5 - od) / 5
        return d5

    PERFECT_WINDOW = _dr(22.4, 19.4, 13.9) * song_rate
    GREAT_WINDOW   = _dr(64, 49, 34) * song_rate
    GOOD_WINDOW    = _dr(97, 82, 67) * song_rate
    OK_WINDOW      = _dr(127, 112, 97) * song_rate
    MEH_WINDOW     = _dr(151, 136, 121) * song_rate
    MISS_WINDOW    = _dr(188, 173, 158) * song_rate
    
    raw_speed = g.config.get("scroll_speed", 24)
    # 兼容旧格式 (旧值 < 5 表示 0.1~2.0 的老倍率，自动 *30 迁移到 osu! 风格)
    if raw_speed < 5:
        raw_speed = raw_speed * 30
        g.config["scroll_speed"] = raw_speed
        g.save_config()
    eff_speed = raw_speed / 24.0 / song_rate
    global_offset = g.config["global_offset"]
    
    with open(map_path, "r", encoding="utf-8") as f:
        map_data = json.load(f)

    notes_data = map_data["notes"]
    # 确保音符严格按照时间先后排序，这对于后续每一帧的性能剔除算法至关重要
    notes_data.sort(key=lambda x: x["time"])
    
    for note in notes_data:
        note["hit"] = False
        note["missed"] = False
        if note.get("type") == "hold":
            note["holding"] = False

    try:
        # 将谱面中的相对音频路径转换为与 json 所在真实文件夹的绝对/相对拼接路径
        audio_file = os.path.abspath(os.path.join(os.path.dirname(map_path), map_data["meta"]["song"]))
        
        audio_to_load = audio_file
        if song_rate != 1.0:
            temp_base_name = f".temp_{song_rate}x_{os.path.basename(audio_file)}"
            temp_audio_file = os.path.abspath(os.path.join(os.path.dirname(map_path), os.path.splitext(temp_base_name)[0] + ".wav"))

            if not os.path.exists(temp_audio_file):
                g.screen.fill((30, 30, 30))
                gen_text = g.small_font.render(f"Applying {song_rate}x Rate...", True, (200, 200, 200))
                g.screen.blit(gen_text, (g.SCREEN_WIDTH // 2 - gen_text.get_width() // 2, g.SCREEN_HEIGHT // 2))
                g.update_display()

                ok = sonic_python.generate_stretched_audio(audio_file, temp_audio_file, song_rate)
                if not ok:
                    print(f"[Audio] 变速生成失败，使用原始速度音频")
                else:
                    audio_to_load = temp_audio_file
            else:
                audio_to_load = temp_audio_file
        
        if g.mixer_available:
            g.audio_load(audio_to_load)
            music_started = False
        else:
            music_started = True
    except Exception as e:
        print(f"Warning: {e}")
        music_started = True

    start_time = pygame.time.get_ticks() 
    map_offset = map_data["meta"].get("offset", 0)
    LEAD_IN_TIME = 3000

    score = 0
    combo = 0
    max_combo = 0
    perfect_count = 0   # 305
    great_count = 0     # 300
    good_count = 0      # 200
    ok_count = 0        # 100
    meh_count = 0       # 50
    miss_count = 0

    # 回放录制
    replay_data = ReplayData(
        map_path=map_path, song_rate=song_rate, od=od,
        scroll_speed=raw_speed if 'raw_speed' in dir() else g.config.get("scroll_speed", 24),
        hit_position=HIT_Y)
    replay_data.modified = (song_rate != 1.0 or od != 5.0 or raw_speed != 24)
    replay_data.player_name = g.config.get("player_name", "Player")
    _last_replay_frame_time = -100

    # 皮肤相关状态
    g.key_pressed_state = [False, False, False, False]
    judgement_frame_counter = 0
    current_judgement_type = None
    last_hit_offset = 0       # 最近一次打击的偏移 (ms)
    hit_timestamps = []        # 最近 3 秒内的打击时间戳 (ms)
    total_offset = 0.0         # 累计偏移 (ms)
    total_hits = 0             # 总打击次数 (用于计算平均)
    
    total_judgments = sum(2 if n.get("type", "tap") == "hold" else 1 for n in notes_data)
    
    # 计算谱面的总时长，以便实现游玩进度条
    total_duration = 1.0 # 提供一个默认避免除零
    if len(notes_data) > 0:
        total_duration = max([n.get("end_time", n.get("time")) for n in notes_data])

    active_idx = 0
    
    # 从原始封面直接 cover 填充至 real_screen 作为背景（显示在两侧黑边）
    g.set_real_background_from_original(map_path, map_data)

    while True:
        g.screen.fill((30, 30, 30)) # 背景深灰色
        
        # 加入图谱特定的偏移与玩家自身的全局偏移，另外通过LEAD_IN_TIME预留出3秒游戏内部时间，从而让原本挤在这个时候的音符被推迟，先慢慢往下落
        real_elapsed_time = pygame.time.get_ticks() - start_time
        current_time = real_elapsed_time * song_rate - map_offset - global_offset - LEAD_IN_TIME
        
        # 音频随缘触发
        if current_time >= 0 and not music_started and g.mixer_available:
            g.audio_play()
            music_started = True
        
        # --- 事件处理 ---
        judgement_text = None  # 每帧重置
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
                
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    g.show_fps = not g.show_fps
                    
                elif event.key == pygame.K_ESCAPE:
                    if music_started and g.mixer_available:
                        g.audio_pause()
                    pause_start_time = pygame.time.get_ticks()
                    
                    options = ["继续 (Continue)", "重来 (Restart)", "退出 (Exit)"]
                    selected_opt = 0
                    action = None
                    
                    while True:
                        g.screen.fill((40, 40, 60))
                        title = g.font.render("=== PAUSED ===", True, (255, 255, 255))
                        g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 100))
                        
                        y_off = 200
                        for i, opt in enumerate(options):
                            color = (0, 255, 100) if i == selected_opt else (150, 150, 150)
                            prefix = ">> " if i == selected_opt else "   "
                            opt_surf = g.font.render(prefix + opt, True, color)
                            g.screen.blit(opt_surf, (g.SCREEN_WIDTH // 2 - opt_surf.get_width() // 2, y_off))
                            y_off += 50
                            
                        if g.show_fps:
                            fps_text = g.small_font.render(f"FPS: {int(g.clock.get_fps())}", True, (255, 100, 100))
                            g.screen.blit(fps_text, (10, g.SCREEN_HEIGHT - 30))
                        
                        g.update_display()
                        
                        for p_event in pygame.event.get():
                            if p_event.type == pygame.QUIT:
                                pygame.quit()
                                sys.exit()
                            elif p_event.type == pygame.KEYDOWN:
                                if p_event.key == pygame.K_UP:
                                    selected_opt = (selected_opt - 1) % len(options)
                                elif p_event.key == pygame.K_DOWN:
                                    selected_opt = (selected_opt + 1) % len(options)
                                elif p_event.key == pygame.K_RETURN:
                                    action = options[selected_opt]
                                    break
                                elif p_event.key == pygame.K_ESCAPE:
                                    action = options[0] # 按ESC默认继续
                                    break
                                elif p_event.key == pygame.K_f and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                                    g.show_fps = not g.show_fps
                        
                        if action:
                            break
                        g.clock.tick(60)
                        
                    if "Exit" in action:
                        if g.mixer_available:
                            g.audio_stop()
                        return "exit"
                    elif "Restart" in action:
                        if g.mixer_available:
                            g.audio_stop()
                        return "restart"
                    else: # Continue
                        # 继续有三秒倒计时
                        # 冻结统计快照
                        frozen_kps = len([t for t in hit_timestamps if current_time - t <= 3000]) / 3.0
                        frozen_combo = combo
                        frozen_acc = (score / ((perfect_count + great_count + good_count + ok_count + meh_count + miss_count) * 305) * 100) if (perfect_count + great_count + good_count + ok_count + meh_count + miss_count) > 0 else 100.0
                        frozen_offset = last_hit_offset
                        frozen_avg = total_offset / total_hits if total_hits > 0 else 0

                        count_start = pygame.time.get_ticks()
                        while True:
                            now = pygame.time.get_ticks()
                            elp = now - count_start
                            if elp >= 3000:
                                break

                            g.screen.fill((30, 30, 30))
                            _draw_stage_background()

                            # 皮肤按键
                            if g.skin_assets:
                                _draw_key_pads(g.key_pressed_state)

                            pygame.draw.line(g.screen, (255, 0, 0), (0, HIT_Y), (g.SCREEN_WIDTH, HIT_Y), 5)

                            # 渲染暂停时刻的音符（使用皮肤）
                            for i in range(active_idx, len(notes_data)):
                                note = notes_data[i]
                                if (note["time"] - current_time) * eff_speed > g.SCREEN_HEIGHT + 100:
                                    break
                                if note["hit"]:
                                    continue

                                x = LANES[note["lane"]]
                                note_type = note.get("type", "tap")
                                if note_type == "tap":
                                    y = HIT_Y - (note["time"] - current_time) * eff_speed
                                    if -50 < y < g.SCREEN_HEIGHT:
                                        if not _draw_tap_note_with_skin(note["lane"], y, note["missed"], x):
                                            color = (100, 100, 100) if note["missed"] else (0, 200, 255)
                                            pygame.draw.rect(g.screen, color, (x - 40, int(y) - 10, 80, 20))
                                elif note_type == "hold":
                                    if "stuck_y" in note:
                                        if note.get("holding"): head_y = note["stuck_y"]
                                        elif "release_time" in note: head_y = note["stuck_y"] + (current_time - note["release_time"]) * eff_speed
                                        else: head_y = HIT_Y - (note["time"] - current_time) * eff_speed
                                    else:
                                        head_y = HIT_Y - (note["time"] - current_time) * eff_speed
                                    tail_y = HIT_Y - (note["end_time"] - current_time) * eff_speed
                                    if int(head_y) - int(tail_y) > 0 and int(tail_y) < g.SCREEN_HEIGHT and int(head_y) > -50:
                                        if not _draw_hold_note_with_skin(note["lane"], head_y, tail_y, note, x):
                                            color = (150, 255, 150) if note.get("holding") else (80, 100, 80) if note["missed"] else (0, 255, 100)
                                            pygame.draw.rect(g.screen, color, (x - 40, int(tail_y), 80, int(head_y) - int(tail_y)))

                            # 顶部 UI + 冻结统计
                            pygame.draw.rect(g.screen, (0, 0, 0), (0, 0, g.SCREEN_WIDTH, 40))
                            pygame.draw.line(g.screen, (200, 200, 200), (0, 40), (g.SCREEN_WIDTH, 40), 2)

                            cb = g.small_font.render(f"Combo: {frozen_combo}", True, (255, 255, 0))
                            g.screen.blit(cb, (10, 10))
                            sign = "+" if frozen_offset > 0 else ""
                            avg_sign = "+" if frozen_avg > 0 else ""
                            od = g.tiny_font.render(f"Offset: {sign}{frozen_offset:.0f}ms (avg {avg_sign}{frozen_avg:.0f}ms)", True, (150, 255, 150))
                            g.screen.blit(od, (10, 34))

                            ac = g.small_font.render(f"ACC: {frozen_acc:.2f}%", True, (0, 255, 255))
                            g.screen.blit(ac, (g.SCREEN_WIDTH - ac.get_width() - 10, 10))
                            kps = g.tiny_font.render(f"KPS: {frozen_kps:.1f}", True, (150, 200, 255))
                            g.screen.blit(kps, (g.SCREEN_WIDTH - kps.get_width() - 10, 34))

                            pygame.draw.rect(g.screen, (50, 50, 50), (0, 0, g.SCREEN_WIDTH, 4))
                            progress_percentage = min(1.0, max(0.0, current_time / total_duration))
                            pygame.draw.rect(g.screen, (100, 200, 255), (0, 0, int(g.SCREEN_WIDTH * progress_percentage), 4))

                            cnum = 3 - (elp // 1000)
                            if cnum > 0:
                                text = g.font.render(str(cnum), True, (255, 255, 255))
                                g.screen.blit(text, (g.SCREEN_WIDTH // 2 - text.get_width() // 2, g.SCREEN_HEIGHT // 2 - text.get_height() // 2))

                            if g.show_fps:
                                fps_text = g.small_font.render(f"FPS: {int(g.clock.get_fps())}", True, (255, 100, 100))
                                g.screen.blit(fps_text, (10, g.SCREEN_HEIGHT - 30))

                            g.update_display()
                            for ev in pygame.event.get():
                                if ev.type == pygame.QUIT:
                                    pygame.quit(); sys.exit()
                            g.clock.tick(60)
                        
                        # 修正在暂停和倒计时期间流逝的时间
                        pause_end_time = pygame.time.get_ticks()
                        start_time += (pause_end_time - pause_start_time)
                        
                        # 同步current_time否则刚刚过去一帧可能会突变
                        real_elapsed_time = pygame.time.get_ticks() - start_time
                        current_time = real_elapsed_time * song_rate - map_offset - global_offset - LEAD_IN_TIME
                        
                        if current_time >= 0 and music_started and g.mixer_available:
                            g.audio_unpause()
                        # 需要跳过这个事件循环中由于暂停产生的堆积事件，可以直接continue跳过剩下的KEYDOWN处理
                        continue

                # 判断按键是否是有效键
                elif event.key in g.KEY_MAP:
                    lane_pressed = g.KEY_MAP[event.key]
                    g.key_pressed_state[lane_pressed] = True
                    
                    # 过滤出该轨道的可用音符, 且不要把正在按住(holding)的长条再次判定
                    valid_notes = []
                    for i in range(active_idx, len(notes_data)):
                        n = notes_data[i]
                        if n["lane"] == lane_pressed and not n["hit"] and not n["missed"] and not n.get("holding", False):
                            valid_notes.append(n)
                            # 考虑到音符已经整体排序，我们只需要看距离当前最近的少数几个就行了，不必完全遍历
                            if len(valid_notes) > 3:
                                break
                    valid_notes.sort(key=lambda x: x["time"])
                    
                    if valid_notes:
                        # 找 time_diff 最小的音符（最接近当前时间），而非只检查第一个
                        best_note = None
                        best_diff = float("inf")
                        for n in valid_notes:
                            d = abs(n["time"] - current_time)
                            if d < best_diff:
                                best_diff = d
                                best_note = n

                        target_note = best_note
                        time_diff = best_diff
                        last_hit_offset = target_note["time"] - current_time
                        total_offset += last_hit_offset; total_hits += 1
                        hit_timestamps.append(current_time)

                        if time_diff <= MISS_WINDOW:
                            if time_diff <= PERFECT_WINDOW:
                                judgement_text = "PERFECT"
                                score += 305; perfect_count += 1
                            elif time_diff <= GREAT_WINDOW:
                                judgement_text = "GREAT"
                                score += 300; great_count += 1
                            elif time_diff <= GOOD_WINDOW:
                                judgement_text = "GOOD"
                                score += 200; good_count += 1
                            elif time_diff <= OK_WINDOW:
                                judgement_text = "OK"
                                score += 100; ok_count += 1
                            elif time_diff <= MEH_WINDOW:
                                judgement_text = "MEH"
                                score += 50; meh_count += 1
                            elif time_diff <= MISS_WINDOW:
                                judgement_text = "MISS"
                                combo = 0; miss_count += 1
                                target_note["missed"] = True

                            if not target_note["missed"]:
                                combo += 1
                                if target_note.get("type", "tap") == "tap":
                                    target_note["hit"] = True
                                elif target_note.get("type") == "hold":
                                    target_note["holding"] = True
                                    target_note["stuck_y"] = HIT_Y - (target_note["time"] - current_time) * eff_speed

                            replay_data.add_judgment(current_time, target_note["lane"],
                                                     judgement_text, last_hit_offset)

            elif event.type == pygame.KEYUP:
                if event.key in g.KEY_MAP:
                    lane_released = g.KEY_MAP[event.key]
                    g.key_pressed_state[lane_released] = False
                    
                    # 寻找该轨道正在被按住（holding）的长条音符
                    holding_notes = [notes_data[i] for i in range(active_idx, len(notes_data)) if notes_data[i].get("holding") and notes_data[i]["lane"] == lane_released and not notes_data[i]["hit"] and not notes_data[i]["missed"]]
                    if holding_notes:
                        target_note = holding_notes[0]
                        target_note["holding"] = False # 解除按住状态
                        
                        # 检查松手的时机是否接近长条结尾
                        time_diff = abs(target_note["end_time"] - current_time)
                        last_hit_offset = target_note["end_time"] - current_time
                        total_offset += last_hit_offset; total_hits += 1
                        hit_timestamps.append(current_time)  # 正=late, 负=early

                        if time_diff <= PERFECT_WINDOW:
                            judgement_text = "PERFECT"
                            score += 305; perfect_count += 1; combo += 1
                            target_note["hit"] = True
                        elif time_diff <= GREAT_WINDOW:
                            judgement_text = "GREAT"
                            score += 300; great_count += 1; combo += 1
                            target_note["hit"] = True
                        elif time_diff <= GOOD_WINDOW:
                            judgement_text = "GOOD"
                            score += 200; good_count += 1; combo += 1
                            target_note["hit"] = True
                        elif time_diff <= OK_WINDOW:
                            judgement_text = "OK"
                            score += 100; ok_count += 1; combo += 1
                            target_note["hit"] = True
                        elif time_diff <= MEH_WINDOW:
                            judgement_text = "MEH"
                            score += 50; meh_count += 1; combo += 1
                            target_note["hit"] = True
                        else:
                            judgement_text = "MISS"
                            combo = 0; miss_count += 1
                            target_note["missed"] = True
                            target_note["release_time"] = current_time

                        replay_data.add_judgment(current_time, target_note["lane"],
                                                 judgement_text, last_hit_offset)

        max_combo = max(max_combo, combo)

        # --- 皮肤：舞台背景 ---
        _draw_stage_background()

        # 轨道线已注释
        # for x in LANES:
        #     pygame.draw.line(g.screen, (80, 80, 100), (x, 0), (x, g.SCREEN_HEIGHT), 1)

        # 画判定线（皮肤可配置隐藏）
        skin_show_line = True
        if g.skin_assets and g.skin_assets.get("config"):
            skin_show_line = g.skin_assets["config"].get("JudgementLine", "1") != "0"
        if skin_show_line:
            pygame.draw.line(g.screen, (255, 0, 0), (0, HIT_Y), (g.SCREEN_WIDTH, HIT_Y), 5)

        # --- 核心：处理底漏与渲染音符 ---
        # 性能优化1：剔除那些已经玩过（被接住或者漏掉）且已经完全掉出屏幕外的陈年老音符
        while active_idx < len(notes_data):
            old_note = notes_data[active_idx]
            nt = old_note.get("end_time", old_note["time"])
            # 如果它已经被判定过，并且以当前速度下落已经远远超过并离开屏幕视口（屏幕高600，落到800外即为不可见）
            if (old_note["hit"] or old_note["missed"]) and (current_time - nt) * eff_speed > 300:
                active_idx += 1
            else:
                break
                
        for i in range(active_idx, len(notes_data)):
            note = notes_data[i]
            
            # 性能优化2：对于几秒之后远在天边的未来音符，不进行任何坐标和遮挡计算，直接打断当帧计算循环
            # 这项优化保证了一帧 300Hz 的循环从计算 3000 次骤降到只算屏幕里的几十次
            if (note["time"] - current_time) * eff_speed > g.SCREEN_HEIGHT + 100:
                break

            note_type = note.get("type", "tap")
            
            # 底部漏判检测
            if note_type == "tap":
                if not note["hit"] and not note["missed"] and current_time - note["time"] > MISS_WINDOW:
                    note["missed"] = True
                    judgement_text = "MISS"
                    combo = 0
                    miss_count += 1
                    
            elif note_type == "hold":
                if not note["hit"]:
                    # 如果没接住长条头
                    if not note["missed"] and not note.get("holding") and current_time - note["time"] > MISS_WINDOW:
                        note["missed"] = True
                        judgement_text = "MISS"
                        combo = 0
                        miss_count += 1

                    # 如果长条按穿（按超时）还没有松手，视为通过或是完美判定
                    elif note.get("holding") and current_time >= note["end_time"]:
                        note["hit"] = True
                        note["holding"] = False
                        judgement_text = "PERFECT"
                        score += 305; perfect_count += 1; combo += 1
                
            # 渲染 (即便是 miss 的音符，只要没流出屏幕也继续渲染)
            if not note["hit"]:
                x = LANES[note["lane"]]

                if note_type == "tap":
                    y = HIT_Y - (note["time"] - current_time) * eff_speed
                    if -50 < y < g.SCREEN_HEIGHT:
                        # 尝试皮肤渲染，失败则回退到默认矩形
                        if not _draw_tap_note_with_skin(note["lane"], y, note["missed"], x):
                            color = (100, 100, 100) if note["missed"] else (0, 200, 255)
                            pygame.draw.rect(g.screen, color, (x - 40, int(y) - 10, 80, 20))

                elif note_type == "hold":
                    # 如果长条按下了，用按下瞬间锁死的 Y 坐标；如果中途松手 miss 了，让剩下来的一小截从松手位置以正常速度掉出屏幕外
                    if "stuck_y" in note:
                        if note.get("holding"):
                            head_y = note["stuck_y"]
                        elif "release_time" in note:
                            head_y = note["stuck_y"] + (current_time - note["release_time"]) * eff_speed
                        else:
                            head_y = HIT_Y - (note["time"] - current_time) * eff_speed
                    else:
                        head_y = HIT_Y - (note["time"] - current_time) * eff_speed

                    # 计算长条尾部的位置，由于松手与否不影响长条本身的物理时常，它照常流逝即可
                    tail_y = HIT_Y - (note["end_time"] - current_time) * eff_speed

                    # 强转为整型以避免浮点数在 pygame 矩形渲染时引发的边框 1 像素上下抖动
                    int_head_y = int(head_y)
                    int_tail_y = int(tail_y)

                    rect_h = int_head_y - int_tail_y

                    # 防越界绘制反向矩形 (只要还没有吃到头就画)
                    if rect_h > 0 and int_tail_y < g.SCREEN_HEIGHT and int_head_y > -50:
                        # 尝试皮肤渲染，失败则回退到默认矩形
                        if not _draw_hold_note_with_skin(note["lane"], head_y, tail_y, note, x):
                            if note.get("holding"):
                                color = (150, 255, 150)
                            elif note["missed"]:
                                color = (80, 100, 80)
                            else:
                                color = (0, 255, 100)
                            pygame.draw.rect(g.screen, color, (x - 40, int_tail_y, 80, rect_h))

        # --- 皮肤按键底板（在音符之上，确保四个圈始终可见） ---
        if g.skin_assets:
            _draw_key_pads(g.key_pressed_state)

        # --- 顶部横幅UI显示 (黑条防遮挡) ---
        pygame.draw.rect(g.screen, (0, 0, 0), (0, 0, g.SCREEN_WIDTH, 40)) # 顶部黑色背景条
        pygame.draw.line(g.screen, (200, 200, 200), (0, 40), (g.SCREEN_WIDTH, 40), 2) # 分界线
        
        combo_display = g.small_font.render(f"Combo: {combo}", True, (255, 255, 0))
        g.screen.blit(combo_display, (10, 10))

        # 偏移显示 + 平均偏移
        sign = "+" if last_hit_offset > 0 else ""
        offset_color = (255, 150, 150) if abs(last_hit_offset) > 30 else (150, 255, 150)
        avg = total_offset / total_hits if total_hits > 0 else 0
        avg_sign = "+" if avg > 0 else ""
        offset_display = g.tiny_font.render(
            f"Offset: {sign}{last_hit_offset:.0f}ms (avg {avg_sign}{avg:.0f}ms)", True, offset_color)
        g.screen.blit(offset_display, (10, 34))

        # KPS 显示 (右上角, 3 秒窗口)
        hit_timestamps = [t for t in hit_timestamps if current_time - t <= 3000]
        kps = len(hit_timestamps) / 3.0
        kps_color = (150, 200, 255) if kps < 10 else (255, 200, 100) if kps < 20 else (255, 100, 100)
        kps_display = g.tiny_font.render(f"KPS: {kps:.1f}", True, kps_color)
        g.screen.blit(kps_display, (g.SCREEN_WIDTH - kps_display.get_width() - 10, 34))
        
        processed_notes = perfect_count + great_count + good_count + ok_count + meh_count + miss_count
        acc = (score / (processed_notes * 305) * 100) if processed_notes > 0 else 100.0
        acc_display = g.small_font.render(f"ACC: {acc:.2f}%", True, (0, 255, 255))
        g.screen.blit(acc_display, (g.SCREEN_WIDTH - acc_display.get_width() - 10, 10))

        # 进度条
        progress_percentage = min(1.0, max(0.0, current_time / total_duration))
        progress_width = int(g.SCREEN_WIDTH * progress_percentage)
        # 底色
        pygame.draw.rect(g.screen, (50, 50, 50), (0, 0, g.SCREEN_WIDTH, 4))
        # 实际进度
        pygame.draw.rect(g.screen, (100, 200, 255), (0, 0, progress_width, 4))
        
        # --- 游玩前倒计时的核心屏幕文字渲染 ---
        if current_time < 0:
            import math
            countdown_num = math.ceil(abs(current_time) / 1000)
            if countdown_num > 0:
                text = g.font.render(str(countdown_num), True, (255, 255, 255))
                g.screen.blit(text, (g.SCREEN_WIDTH // 2 - text.get_width() // 2, g.SCREEN_HEIGHT // 2 - text.get_height() // 2))

        # --- 判定特效追踪 ---
        if "judgement_text" in locals() and judgement_text:
            current_judgement_type = judgement_text
            judgement_frame_counter = 0
            judgement_text = None  # 消费掉，避免重复触发

        # 渲染判定文字/特效
        if current_judgement_type:
            if g.skin_assets:
                _draw_hit_burst(current_judgement_type, judgement_frame_counter)
            else:
                judge_display = g.font.render(current_judgement_type, True, (0, 255, 100))
                g.screen.blit(judge_display, (g.SCREEN_WIDTH // 2 - judge_display.get_width() // 2, 200))

            judgement_frame_counter += 1
            if judgement_frame_counter > 60:
                current_judgement_type = None

        if g.show_fps:
            fps_text = g.small_font.render(f"FPS: {int(g.clock.get_fps())}", True, (255, 100, 100))
            g.screen.blit(fps_text, (10, g.SCREEN_HEIGHT - 30))

        # 回放帧录制 (~60fps 或按键变化时)
        keys_mask = (1 if g.key_pressed_state[0] else 0) | \
                    (2 if g.key_pressed_state[1] else 0) | \
                    (4 if g.key_pressed_state[2] else 0) | \
                    (8 if g.key_pressed_state[3] else 0)
        if current_time - _last_replay_frame_time >= 16 or \
           (replay_data.frames and replay_data.frames[-1].pressed_keys != keys_mask):
            replay_data.add_frame(current_time, keys_mask)
            _last_replay_frame_time = current_time

        g.update_display() # 刷新屏幕
        g.clock.tick(0) # 彻底解除帧率限制，让游戏火力全开飙到多高是多高 (0表示不限速)

        # 检查游戏是否结束 (只需要判定剔除指针是不是推到了最后即可，这可以彻底省去每秒90万次的 all() 迭代)
        if active_idx == len(notes_data) and len(notes_data) > 0:
            if current_time > total_duration + 1500:
                break

    # 填充回放总结
    replay_data.set_result(
        total_notes=total_judgments,
        max_combo=max_combo,
        counts={"perfect": perfect_count, "great": great_count, "good": good_count,
                "ok": ok_count, "meh": meh_count, "miss": miss_count},
        score=score,
        acc=(score / (total_judgments * 305) * 100) if total_judgments > 0 else 100.0)

    # 退出游戏时清除 real_screen 背景（结算界面无背景）
    g.clear_real_background()
    
    import datetime
    
    # === 结算界面 ===
    show_results_screen(map_path, map_data, score, perfect_count, great_count, good_count,
                        ok_count, meh_count, miss_count, max_combo, total_judgments,
                        song_rate, replay_data, total_duration, is_replay=False)
    return


def show_results_screen(map_path, map_data, score, perfect_count, great_count, good_count,
                        ok_count, meh_count, miss_count, combo, total_judgments,
                        song_rate, replay_data, total_duration=1.0, is_replay=False):
    """统一的结算界面（正常游玩和回放共用）。"""
    import datetime
    base_song_name = os.path.splitext(os.path.basename(map_path))[0]
    acc = (score / (total_judgments * 305) * 100.0) if total_judgments > 0 else 100.0
    rel_path = os.path.relpath(map_path, start=os.getcwd()).replace("\\", "/")

    # 标准化分数 & Rank
    _counts = {"perfect": perfect_count, "great": great_count, "good": good_count,
               "ok": ok_count, "meh": meh_count, "miss": miss_count}
    _total_hits = perfect_count + great_count + good_count + ok_count + meh_count + miss_count
    std_score = calc_standardized_score(acc / 100.0,
        combo / max(total_judgments, 1),
        _total_hits / max(total_judgments, 1)) if _total_hits > 0 else 0
    rank = get_rank(acc / 100.0, _counts)
    rank_color = RANK_COLORS.get(rank, (200, 200, 200))

    # 保存历史
    if rel_path not in g.history_data:
        g.history_data[rel_path] = []
    record = {"score": std_score, "acc": acc, "rank": rank,
              "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "rate": song_rate}
    g.history_data[rel_path].append(record)
    g.history_data[rel_path].sort(key=lambda x: x["score"], reverse=True)
    if len(g.history_data[rel_path]) > 10:
        g.history_data[rel_path] = g.history_data[rel_path][:10]
    g.save_history()

    # 统计页面状态
    page = 0
    stat_view_start = 0.0; stat_view_end = 1.0
    stat_n_sec = 5.0
    stat_adjust_n = False
    hit_offsets = [j.offset_ms for j in replay_data.judgments if j.type != "MISS"]

    while True:
        g.screen.fill((20, 20, 35))

        if page == 0:
            _draw_results_page1(base_song_name, acc, combo, song_rate, _counts, _total_hits, std_score, rank, rank_color, is_replay)
        elif page == 1:
            _draw_results_stats_page1(hit_offsets)
        elif page == 2:
            _draw_results_stats_page2(replay_data.judgments, total_judgments, stat_view_start, stat_view_end)
        elif page == 3:
            _draw_results_stats_page3(replay_data.judgments, total_duration, stat_n_sec, stat_view_start, stat_view_end, stat_adjust_n)

        # 底部提示
        hint = g.tiny_font.render("[ENTER] 返回  [S] 保存回放  [←→] 翻页", True, (150, 150, 150))
        g.screen.blit(hint, (g.SCREEN_WIDTH // 2 - hint.get_width() // 2, g.SCREEN_HEIGHT - 25))

        if g.show_fps:
            fps_t = g.small_font.render(f"FPS: {int(g.clock.get_fps())}", True, (255, 100, 100))
            g.screen.blit(fps_t, (10, g.SCREEN_HEIGHT - 30))

        g.update_display()

        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    g.show_fps = not g.show_fps
                if event.key == pygame.K_s:
                    map_dir = os.path.dirname(map_path)
                    safe_name = base_song_name.replace("/", "_").replace("\\", "_")
                    replay_path = os.path.join(map_dir,
                        f"{replay_data.player_name}_{replay_data.date.replace(':', '-')}_{safe_name}.osr")
                    save_replay(replay_data, replay_path)
                    sv = g.small_font.render("Saved!", True, (0, 255, 0))
                    g.screen.blit(sv, (g.SCREEN_WIDTH // 2 - sv.get_width() // 2, g.SCREEN_HEIGHT - 50))
                    g.update_display()
                    pygame.time.wait(800)
                elif event.key in (pygame.K_LEFT, pygame.K_UP):
                    page = (page - 1) % 4
                elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                    page = (page + 1) % 4
                elif event.key == pygame.K_RETURN:
                    if page == 0: return
                # 统计页操作
                elif page == 2:
                    shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
                    s = 0.05 if shift else 0.2
                    if event.key == pygame.K_a: stat_view_end = max(0.05, stat_view_end - s)
                    elif event.key == pygame.K_d: stat_view_end = min(1.0, stat_view_end + s)
                    elif event.key == pygame.K_z: dv = stat_view_end - stat_view_start; stat_view_start = max(0, stat_view_start - s); stat_view_end = stat_view_start + dv
                    elif event.key == pygame.K_c: dv = stat_view_end - stat_view_start; stat_view_start = min(1.0 - dv, stat_view_start + s); stat_view_end = stat_view_start + dv
                elif page == 3:
                    shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
                    s = 0.05 if shift else 0.2
                    if stat_adjust_n:
                        ns = 0.5 if shift else 0.1
                        if event.key == pygame.K_a: stat_n_sec = max(0.5, stat_n_sec - ns)
                        elif event.key == pygame.K_d: stat_n_sec = min(30, stat_n_sec + ns)
                        elif event.key == pygame.K_x: stat_adjust_n = False
                    else:
                        if event.key == pygame.K_a: stat_view_end = max(0.05, stat_view_end - s)
                        elif event.key == pygame.K_d: stat_view_end = min(1.0, stat_view_end + s)
                        elif event.key == pygame.K_z: dv = stat_view_end - stat_view_start; stat_view_start = max(0, stat_view_start - s); stat_view_end = stat_view_start + dv
                        elif event.key == pygame.K_c: dv = stat_view_end - stat_view_start; stat_view_start = min(1.0 - dv, stat_view_start + s); stat_view_end = stat_view_start + dv
                        elif event.key == pygame.K_x: stat_adjust_n = True
        g.clock.tick(60)


def _draw_results_page1(base_song_name, acc, combo, song_rate, counts, total, std_score, rank, rank_color, is_replay=False):
    """结算第1页：精度圆环 + Rank + 判定条"""
    tag = "[REPLAY] " if is_replay else ""
    title = g.font.render(f"=== {tag}结算 ===", True, (255, 100, 100) if is_replay else (255, 255, 255))
    g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 8))
    _draw_accuracy_circle(g.screen, g.SCREEN_WIDTH // 2, 130, 60, acc / 100.0, rank, rank_color)
    score_text = g.font.render(f"{std_score:,}", True, (255, 255, 255))
    g.screen.blit(score_text, (g.SCREEN_WIDTH // 2 - score_text.get_width() // 2, 195))
    g.draw_marquee_text(g.screen, base_song_name, g.tiny_font,
        (150, 200, 255), g.SCREEN_WIDTH // 2, 230, g.SCREEN_WIDTH - 40)
    info_y = 255
    ac_t = g.small_font.render(f"ACC: {acc:.2f}%  |  Max Combo: {combo}x  |  {song_rate:.1f}x", True, (200, 200, 200))
    g.screen.blit(ac_t, (g.SCREEN_WIDTH // 2 - ac_t.get_width() // 2, info_y))
    _draw_judgment_bars(g.screen, info_y + 30, counts, total if total > 0 else 1)


def _draw_results_stats_page1(offsets):
    """统计第1页：命中偏移直方图"""
    title = g.font.render("=== 命中偏移 ===", True, (255, 255, 255))
    g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 8))
    _draw_histogram(g.screen, offsets, 20, 50, 360, 400)


def _draw_results_stats_page2(judgments, total_notes, view_start, view_end):
    """统计第2页：时间-ACC 曲线"""
    title = g.font.render("=== ACC 曲线 ===", True, (255, 255, 255))
    g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 8))
    hint = g.tiny_font.render("A/D:缩放  Z/C:平移", True, (150, 150, 150))
    g.screen.blit(hint, (g.SCREEN_WIDTH // 2 - hint.get_width() // 2, 30))
    _draw_time_acc_curve(g.screen, judgments, total_notes, 20, 55, 360, 500, view_start, view_end)


def _draw_results_stats_page3(judgments, total_duration, n_sec, view_start, view_end, adjust_n):
    """统计第3页：每 N 秒 ACC"""
    title = g.font.render("=== 分段 ACC ===", True, (255, 255, 255))
    g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 8))
    mode_hint = "(调节N)" if adjust_n else "(缩放)"
    hint = g.tiny_font.render(f"A/D:缩放  Z/C:平移  X:{mode_hint}", True, (150, 150, 150))
    g.screen.blit(hint, (g.SCREEN_WIDTH // 2 - hint.get_width() // 2, 30))
    _draw_nsec_acc(g.screen, judgments, total_duration, 20, 55, 360, 500, n_sec, view_start, view_end)
