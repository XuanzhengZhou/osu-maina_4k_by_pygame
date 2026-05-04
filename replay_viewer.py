"""回放播放器：加载 .osr 文件并重放"""

import pygame
import sys
import os
import json
import global_state as g
from replay import load_replay


def play_replay(replay_path):
    """播放回放文件。"""
    rd = load_replay(replay_path)
    print(f"[Replay Viewer] 加载回放: {os.path.basename(replay_path)}")
    print(f"  Rate={rd.song_rate}x  OD={rd.od}  Speed={rd.scroll_speed}")

    map_path = rd.map_path
    if not os.path.exists(map_path):
        # 尝试在当前目录下查找
        alt = os.path.join(os.getcwd(), os.path.basename(map_path))
        if os.path.exists(alt):
            map_path = alt
        else:
            print(f"[Replay Viewer] 谱面不存在: {map_path}")
            return

    with open(map_path, "r", encoding="utf-8") as f:
        map_data = json.load(f)

    notes_data = map_data["notes"]
    notes_data.sort(key=lambda x: x["time"])
    for note in notes_data:
        note["hit"] = False
        note["missed"] = False
        if note.get("type") == "hold":
            note["holding"] = False

    # 回放记录的镜像模式
    if rd.mirror_mode:
        mirror_map = {0: 3, 1: 2, 2: 1, 3: 0}
        for note in notes_data:
            note["lane"] = mirror_map[note["lane"]]

    # 使用回放记录的设置
    song_rate = rd.song_rate
    od = rd.od
    scroll_speed = rd.scroll_speed
    HIT_Y = rd.hit_position

    # 应用轨道间距和缩放（同 gameplay）
    sp = g.config.get("stage_spacing", 100)
    sc = g.config.get("stage_scale", 1.0)
    gap = sp * sc
    needed_w = int(gap * 3 + 80 * sc + 30)
    if needed_w != g.SCREEN_WIDTH:
        g.SCREEN_WIDTH = max(400, needed_w)
        g.screen = pygame.Surface((g.SCREEN_WIDTH, g.SCREEN_HEIGHT))
        g.set_display_mode()
        g.set_real_background_from_original(map_path, map_data)
    cx = g.SCREEN_WIDTH // 2
    LANES = [int(cx - gap * 1.5), int(cx - gap * 0.5), int(cx + gap * 0.5), int(cx + gap * 1.5)]
    g.stage_lanes = LANES
    g.note_width = int(80 * sc)
    note_w = g.note_width

    def _dr(d0, d5, d10):
        if od > 5: return d5 + (d10 - d5) * (od - 5) / 5
        elif od < 5: return d5 - (d5 - d0) * (5 - od) / 5
        return d5

    PERFECT_WINDOW = _dr(22.4, 19.4, 13.9) * song_rate
    GREAT_WINDOW   = _dr(64, 49, 34) * song_rate
    GOOD_WINDOW    = _dr(97, 82, 67) * song_rate
    OK_WINDOW      = _dr(127, 112, 97) * song_rate
    MEH_WINDOW     = _dr(151, 136, 121) * song_rate
    MISS_WINDOW    = _dr(188, 173, 158) * song_rate

    eff_speed = scroll_speed / 24.0 / song_rate
    global_offset = g.config.get("global_offset", 0)

    # 音频
    try:
        audio_file = os.path.abspath(os.path.join(os.path.dirname(map_path), map_data["meta"]["song"]))
        if g.mixer_available:
            g.audio_load(audio_file)
            music_started = False
        else:
            music_started = True
    except Exception:
        music_started = True

    map_offset = map_data["meta"].get("offset", 0)
    LEAD_IN_TIME = 3000

    score = 0; combo = 0; max_combo = 0
    perfect_count = 0; great_count = 0; good_count = 0
    ok_count = 0; meh_count = 0; miss_count = 0
    total_judgments = sum(2 if n.get("type", "tap") == "hold" else 1 for n in notes_data)

    total_duration = max([n.get("end_time", n.get("time")) for n in notes_data]) if notes_data else 1.0

    g.key_pressed_state = [False, False, False, False]
    active_idx = 0
    judgement_text = None
    current_judgement_type = None
    judgement_frame_counter = 0
    last_hit_offset = 0
    hit_timestamps = []
    total_offset = 0.0
    total_hits = 0

    g.set_real_background_from_original(map_path, map_data)
    start_time = pygame.time.get_ticks()

    # 回放帧索引 + 预计算判定数据
    frame_idx = 0
    replay_frames = rd.frames
    replay_judgments = rd.judgments
    _judge_idx = 0

    _dbg = False  # 调试开关

    def _reset_all_notes():
        """完全重置所有音符为未判定状态。"""
        nonlocal active_idx
        if _dbg: print(f"[DBG] _reset_all_notes: {len(notes_data)} notes, active_idx={active_idx}")
        for n in notes_data:
            n["hit"] = False; n["missed"] = False
            if n.get("type") == "hold": n["holding"] = False
            if "stuck_y" in n: del n["stuck_y"]
            if "release_time" in n: del n["release_time"]
        active_idx = 0

    def _seek_to(target_ct):
        """跳转: 用预记录判定精确标记 target_ct 时刻之前的所有音符状态。"""
        nonlocal frame_idx, active_idx
        frame_idx = 0
        for i, f in enumerate(replay_frames):
            if f.time_ms <= target_ct: frame_idx = i
            else: break
        # 以「音符时间」为准：音符在 target_ct 之前就应该有判定结果
        hit_c = 0; miss_c = 0; hold_c = 0
        for n in notes_data:
            n_time = n["time"]
            if n_time >= target_ct: continue
            if n["hit"] or n["missed"]: continue
            best_j = None
            for j in replay_judgments:
                if j.lane != n["lane"]: continue
                if n.get("type", "tap") == "tap":
                    if abs(j.time_ms - n_time) < 200: best_j = j; break
                elif n.get("type") == "hold":
                    if abs(j.time_ms - n_time) < 200: best_j = j; break
            if best_j and best_j.type != "MISS":
                if n.get("type", "tap") == "tap": n["hit"] = True; hit_c += 1
                elif n.get("type") == "hold": n["holding"] = True; hold_c += 1
            else:
                n["missed"] = True; miss_c += 1
        rel_c = 0
        for n in notes_data:
            if n.get("type") != "hold": continue
            if n["time"] >= target_ct: continue
            if not n.get("holding") and not n["hit"]: continue
            if n.get("holding"):
                for j in replay_judgments:
                    if j.lane == n["lane"] and abs(j.time_ms - n.get("end_time", 0)) < 200:
                        n["holding"] = False; rel_c += 1
                        if j.type == "MISS": n["missed"] = True
                        else: n["hit"] = True
                        break
        if _dbg: print(f"[DBG] _seek_to(target={target_ct}): frame_idx={frame_idx} active_idx={active_idx} hit={hit_c} miss={miss_c} hold={hold_c} released={rel_c}")
        while active_idx < len(notes_data):
            n = notes_data[active_idx]
            nt = n.get("end_time", n["time"])
            if (n["hit"] or n["missed"]) and (target_ct - nt) * eff_speed > 300:
                active_idx += 1
            else: break

    def _get_replay_state_at(t):
        """根据预记录的判定数据，计算截至时间 t 的游戏状态。"""
        nonlocal _judge_idx
        s = 0; p = 0; g = 0; d = 0; o = 0; m = 0; miss_c = 0
        cb = 0; max_cb = 0
        total_off = 0.0; total_n = 0
        last_off = 0
        hit_ts = []
        for j in replay_judgments:
            if j.time_ms > t: break
            w = {"PERFECT": 305, "GREAT": 300, "GOOD": 200, "OK": 100, "MEH": 50, "MISS": 0}
            pts = w.get(j.type, 0)
            s += pts
            if j.type == "PERFECT": p += 1
            elif j.type == "GREAT": g += 1
            elif j.type == "GOOD": d += 1
            elif j.type == "OK": o += 1
            elif j.type == "MEH": m += 1
            elif j.type == "MISS": miss_c += 1
            if j.type == "MISS": cb = 0
            else: cb += 1
            max_cb = max(max_cb, cb)
            total_off += j.offset_ms; total_n += 1
            last_off = j.offset_ms
            hit_ts.append(j.time_ms)
        total_j = p + g + d + o + m + miss_c
        acc_v = (s / (total_j * 305) * 100) if total_j > 0 else 100.0
        _ks = len([h for h in hit_ts if t - h <= 3000]) / 3.0
        avg_o = total_off / total_n if total_n > 0 else 0
        return s, p, g, d, o, m, miss_c, cb, max_cb, acc_v, _ks, last_off, avg_o

    # 延迟加载 gameplay 渲染函数（避免循环导入）
    from gameplay import (_draw_stage_background, _draw_key_pads,
                          _draw_tap_note_with_skin, _draw_hold_note_with_skin,
                          _draw_hit_burst, _scale_to_width)

    while True:
        g.screen.fill((30, 30, 30))
        real_elapsed_time = pygame.time.get_ticks() - start_time
        current_time = real_elapsed_time * song_rate - map_offset - global_offset - LEAD_IN_TIME

        if current_time >= global_offset and not music_started and g.mixer_available:
            g.audio_play()
            music_started = True

        # 处理事件
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    g.show_fps = not g.show_fps
                elif event.key == pygame.K_ESCAPE:
                    if g.mixer_available: g.audio_stop()
                    g.clear_real_background()
                    return
                elif event.key == pygame.K_SPACE:
                    if g.mixer_available: g.audio_pause()
                    import bass_audio
                    if bass_audio.is_available():
                        ms_pos = int(current_time) if current_time > 0 else 0
                    pause_start = pygame.time.get_ticks()
                    while True:
                        g.screen.fill((30, 30, 40))
                        t = g.font.render("PAUSED", True, (255, 255, 255))
                        g.screen.blit(t, (g.SCREEN_WIDTH // 2 - t.get_width() // 2, g.SCREEN_HEIGHT // 2 - 50))
                        h = g.small_font.render("[SPACE] 继续  [ESC] 退出", True, (200, 200, 200))
                        g.screen.blit(h, (g.SCREEN_WIDTH // 2 - h.get_width() // 2, g.SCREEN_HEIGHT // 2))
                        g.update_display()
                        for pev in pygame.event.get():
                            if pev.type == pygame.QUIT: pygame.quit(); sys.exit()
                            if pev.type == pygame.KEYDOWN:
                                if pev.key == pygame.K_SPACE: break
                                if pev.key == pygame.K_ESCAPE:
                                    g.clear_real_background(); return
                        else: continue
                        break
                    start_time += pygame.time.get_ticks() - pause_start
                    if g.mixer_available: g.audio_play()
                elif event.key == pygame.K_LEFT:
                    real_elapsed = pygame.time.get_ticks() - start_time
                    cur_ct = real_elapsed * song_rate - map_offset - global_offset - LEAD_IN_TIME
                    target_ct = max(0, cur_ct - 5000)
                    # LEFT seek
                    _reset_all_notes()
                    _seek_to(target_ct)
                    start_time = pygame.time.get_ticks() - int((target_ct + map_offset + global_offset + LEAD_IN_TIME) / song_rate)
                    real_elapsed_time = pygame.time.get_ticks() - start_time
                    current_time = real_elapsed_time * song_rate - map_offset - global_offset - LEAD_IN_TIME
                    # 音频位置 = game_time - global_offset
                    if g.mixer_available: g.audio_seek(max(0, target_ct - global_offset))
                elif event.key == pygame.K_RIGHT:
                    real_elapsed = pygame.time.get_ticks() - start_time
                    cur_ct = real_elapsed * song_rate - map_offset - global_offset - LEAD_IN_TIME
                    target_ct = cur_ct + 5000
                    if target_ct >= total_duration:
                        if g.mixer_available: g.audio_stop()
                        g.clear_real_background()
                        if g.SCREEN_WIDTH != 400:
                            g.SCREEN_WIDTH = 400; g.screen = pygame.Surface((400, g.SCREEN_HEIGHT)); g.set_display_mode()
                        break
                    _reset_all_notes()
                    _seek_to(target_ct)
                    start_time = pygame.time.get_ticks() - int((target_ct + map_offset + global_offset + LEAD_IN_TIME) / song_rate)
                    real_elapsed_time = pygame.time.get_ticks() - start_time
                    current_time = real_elapsed_time * song_rate - map_offset - global_offset - LEAD_IN_TIME
                    if g.mixer_available: g.audio_seek(max(0, target_ct - global_offset))

        # --- 模拟按键：从回放帧读取 ---
        frame_proc = 0
        while frame_idx < len(replay_frames) and replay_frames[frame_idx].time_ms <= current_time:
            frame = replay_frames[frame_idx]
            new_keys = frame.pressed_keys
            # 检测按键变化并生成判定
            old_keys = 0
            if frame_idx > 0:
                old_keys = replay_frames[frame_idx - 1].pressed_keys

            for lane in range(4):
                old_pressed = (old_keys >> lane) & 1
                new_pressed = (new_keys >> lane) & 1
                g.key_pressed_state[lane] = bool(new_pressed)

                if new_pressed and not old_pressed:
                    # KEYDOWN 模拟
                    valid = []
                    for i in range(active_idx, len(notes_data)):
                        n = notes_data[i]
                        if n["lane"] == lane and not n["hit"] and not n["missed"] and not n.get("holding"):
                            valid.append(n)
                            if len(valid) > 3: break
                    valid.sort(key=lambda x: x["time"])
                    if valid:
                        best = min(valid, key=lambda n: abs(n["time"] - current_time))
                        td = abs(best["time"] - current_time)
                        if td <= MISS_WINDOW:
                            if td <= PERFECT_WINDOW:
                                judgement_text = "PERFECT"; score += 305; perfect_count += 1
                            elif td <= GREAT_WINDOW:
                                judgement_text = "GREAT"; score += 300; great_count += 1
                            elif td <= GOOD_WINDOW:
                                judgement_text = "GOOD"; score += 200; good_count += 1
                            elif td <= OK_WINDOW:
                                judgement_text = "OK"; score += 100; ok_count += 1
                            elif td <= MEH_WINDOW:
                                judgement_text = "MEH"; score += 50; meh_count += 1
                            elif td <= MISS_WINDOW:
                                judgement_text = "MISS"; combo = 0; miss_count += 1
                                best["missed"] = True
                            if not best["missed"]:
                                combo += 1; max_combo = max(max_combo, combo)
                                if best.get("type", "tap") == "tap":
                                    best["hit"] = True
                                    if _dbg: print(f"[DBG] sim HIT tap lane={lane} t={best['time']} at frame_t={frame.time_ms}")
                                elif best.get("type") == "hold":
                                    best["holding"] = True
                                    if _dbg: print(f"[DBG] sim HOLD H lane={lane} t={best['time']} at frame_t={frame.time_ms}")
                                    best["stuck_y"] = HIT_Y - (best["time"] - current_time) * eff_speed
                            last_hit_offset = best["time"] - current_time
                            total_offset += last_hit_offset; total_hits += 1
                            hit_timestamps.append(current_time)
                            judgement_text = judgement_text

                elif not new_pressed and old_pressed:
                    # KEYUP 模拟
                    holding_notes = [notes_data[i] for i in range(active_idx, len(notes_data))
                                     if notes_data[i].get("holding") and notes_data[i]["lane"] == lane
                                     and not notes_data[i]["hit"] and not notes_data[i]["missed"]]
                    if holding_notes:
                        tn = holding_notes[0]
                        tn["holding"] = False
                        td = abs(tn["end_time"] - current_time)
                        if td <= PERFECT_WINDOW:
                            judgement_text = "PERFECT"; score += 305; perfect_count += 1; combo += 1
                            tn["hit"] = True
                        elif td <= GREAT_WINDOW:
                            judgement_text = "GREAT"; score += 300; great_count += 1; combo += 1
                            tn["hit"] = True
                        elif td <= GOOD_WINDOW:
                            judgement_text = "GOOD"; score += 200; good_count += 1; combo += 1
                            tn["hit"] = True
                        elif td <= OK_WINDOW:
                            judgement_text = "OK"; score += 100; ok_count += 1; combo += 1
                            tn["hit"] = True
                        elif td <= MEH_WINDOW:
                            judgement_text = "MEH"; score += 50; meh_count += 1; combo += 1
                            tn["hit"] = True
                        else:
                            judgement_text = "MISS"; combo = 0; miss_count += 1
                            tn["missed"] = True
                            tn["release_time"] = current_time
                        max_combo = max(max_combo, combo)
                        last_hit_offset = tn["end_time"] - current_time
                        total_offset += last_hit_offset; total_hits += 1
                        hit_timestamps.append(current_time)

            frame_idx += 1; frame_proc += 1

        if _dbg and frame_proc > 0:
            print(f"[DBG] frame_sim: processed {frame_proc} frames, now frame_idx={frame_idx}, current_time={current_time:.0f}")
        # 底部漏判（帧模拟之后运行，确保按键先处理）
        bot_miss = 0
        while active_idx < len(notes_data):
            old_note = notes_data[active_idx]
            nt = old_note.get("end_time", old_note["time"])
            if (old_note["hit"] or old_note["missed"]) and (current_time - nt) * eff_speed > 300:
                active_idx += 1
            else: break
        for i in range(active_idx, len(notes_data)):
            note = notes_data[i]
            if (note["time"] - current_time) * eff_speed > g.SCREEN_HEIGHT + 100: break
            if note.get("type", "tap") == "tap":
                if not note["hit"] and not note["missed"] and current_time - note["time"] > MISS_WINDOW:
                    note["missed"] = True; bot_miss += 1
            elif note.get("type") == "hold":
                if not note["hit"] and not note.get("holding"):
                    if not note["missed"] and current_time - note["time"] > MISS_WINDOW:
                        note["missed"] = True; bot_miss += 1
                elif note.get("holding") and current_time >= note["end_time"]:
                    note["hit"] = True; note["holding"] = False
        if _dbg and bot_miss > 0:
            print(f"[DBG] bottom-miss: {bot_miss} notes marked as miss at current_time={current_time:.0f} active_idx={active_idx} MISS_WINDOW={MISS_WINDOW:.0f}")

        # --- 判定文字处理（同 gameplay） ---
        if judgement_text:
            current_judgement_type = judgement_text
            judgement_frame_counter = 0
            judgement_text = None

        if current_judgement_type:
            if g.skin_assets:
                _draw_hit_burst(current_judgement_type, judgement_frame_counter)
            else:
                jd = g.font.render(current_judgement_type, True, (0, 255, 100))
                g.screen.blit(jd, (g.SCREEN_WIDTH // 2 - jd.get_width() // 2, 200))
            judgement_frame_counter += 1
            if judgement_frame_counter > 60:
                current_judgement_type = None

        # --- 渲染 ---
        stage_left = max(0, int(LANES[0] - note_w // 2 - 10))
        stage_right = min(g.SCREEN_WIDTH, int(LANES[3] + note_w // 2 + 10))
        if stage_left > 0:
            pygame.draw.rect(g.screen, (10, 10, 15), (0, 0, stage_left, g.SCREEN_HEIGHT))
        if stage_right < g.SCREEN_WIDTH:
            pygame.draw.rect(g.screen, (10, 10, 15), (stage_right, 0, g.SCREEN_WIDTH - stage_right, g.SCREEN_HEIGHT))
        _draw_stage_background()

        # 判定线（按皮肤配置控制显隐）
        skin_show = True
        if g.skin_assets and g.skin_assets.get("config"):
            skin_show = g.skin_assets["config"].get("JudgementLine", "1") != "0"
        if skin_show:
            pygame.draw.line(g.screen, (255, 0, 0), (0, HIT_Y), (g.SCREEN_WIDTH, HIT_Y), 5)

        for i in range(active_idx, len(notes_data)):
            note = notes_data[i]
            if (note["time"] - current_time) * eff_speed > g.SCREEN_HEIGHT + 100:
                break
            if note["hit"]: continue
            x = LANES[note["lane"]]
            nt = note.get("type", "tap")
            if nt == "tap":
                y = HIT_Y - (note["time"] - current_time) * eff_speed
                if -50 < y < g.SCREEN_HEIGHT:
                    if not _draw_tap_note_with_skin(note["lane"], y, note["missed"], x):
                        c = (100, 100, 100) if note["missed"] else (0, 200, 255)
                        pygame.draw.rect(g.screen, c, (x - 40, int(y) - 10, 80, 20))
            elif nt == "hold":
                if "stuck_y" in note:
                    if note.get("holding"): hy = note["stuck_y"]
                    elif "release_time" in note: hy = note["stuck_y"] + (current_time - note["release_time"]) * eff_speed
                    else: hy = HIT_Y - (note["time"] - current_time) * eff_speed
                else: hy = HIT_Y - (note["time"] - current_time) * eff_speed
                ty = HIT_Y - (note["end_time"] - current_time) * eff_speed
                if int(hy) - int(ty) > 0 and int(ty) < g.SCREEN_HEIGHT and int(hy) > -50:
                    if not _draw_hold_note_with_skin(note["lane"], hy, ty, note, x):
                        c = (150,255,150) if note.get("holding") else (80,100,80) if note["missed"] else (0,255,100)
                        pygame.draw.rect(g.screen, c, (x-40, int(ty), 80, int(hy)-int(ty)))

        # 顶部UI（使用预记录判定数据，不受跳转影响）
        rs, rp, rg, rd2, ro, rm, rmiss, rcb, rmax_cb, racc, rkps, rlast_off, ravg_off = \
            _get_replay_state_at(current_time)

        pygame.draw.rect(g.screen, (0, 0, 0), (0, 0, g.SCREEN_WIDTH, 40))
        pygame.draw.line(g.screen, (200, 200, 200), (0, 40), (g.SCREEN_WIDTH, 40), 2)

        cb = g.small_font.render(f"Combo: {rcb}", True, (255, 255, 0))
        g.screen.blit(cb, (10, 10))
        sign = "+" if rlast_off > 0 else ""
        avg_sign = "+" if ravg_off > 0 else ""
        od_text = g.tiny_font.render(f"Offset: {sign}{rlast_off:.0f}ms (avg {avg_sign}{ravg_off:.0f}ms)", True, (150,255,150))
        g.screen.blit(od_text, (10, 34))
        ac = g.small_font.render(f"ACC: {racc:.2f}%", True, (0, 255, 255))
        g.screen.blit(ac, (g.SCREEN_WIDTH - ac.get_width() - 10, 10))
        kps = g.tiny_font.render(f"KPS: {rkps:.1f}", True, (150, 200, 255))
        g.screen.blit(kps, (g.SCREEN_WIDTH - kps.get_width() - 10, 34))

        # REPLAY 标记 + mods
        mods_parts = [f"OD:{od:.1f}"]
        if song_rate != 1.0: mods_parts.append(f"{song_rate:.1f}x")
        if rd.mirror_mode: mods_parts.append("Mirror")
        mods_str = " | ".join(mods_parts)
        replay_tag = g.small_font.render("[REPLAY]", True, (255, 100, 100))
        g.screen.blit(replay_tag, (g.SCREEN_WIDTH // 2 - replay_tag.get_width() // 2, 8))
        mods_text = g.tiny_font.render(mods_str, True, (200, 255, 200))
        g.screen.blit(mods_text, (g.SCREEN_WIDTH // 2 - mods_text.get_width() // 2, 30))

        # 进度条
        pp = min(1.0, max(0.0, current_time / total_duration))
        pygame.draw.rect(g.screen, (50, 50, 50), (0, 0, g.SCREEN_WIDTH, 4))
        pygame.draw.rect(g.screen, (255, 100, 100), (0, 0, int(g.SCREEN_WIDTH * pp), 4))

        if current_time < 0:
            import math
            cn = math.ceil(abs(current_time) / 1000)
            if cn > 0:
                t = g.font.render(str(cn), True, (255, 255, 255))
                g.screen.blit(t, (g.SCREEN_WIDTH//2 - t.get_width()//2, g.SCREEN_HEIGHT//2 - t.get_height()//2))

        if g.show_fps:
            fps_t = g.small_font.render(f"FPS: {int(g.clock.get_fps())}", True, (255, 100, 100))
            g.screen.blit(fps_t, (10, g.SCREEN_HEIGHT - 30))

        if g.skin_assets:
            _draw_key_pads(g.key_pressed_state)

        g.update_display()
        g.clock.tick(0)

        # 回放结束
        if active_idx == len(notes_data) and len(notes_data) > 0:
            if current_time > total_duration + 1500:
                break

    # 清理
    if g.mixer_available:
        g.audio_stop()
    g.clear_real_background()
    if g.SCREEN_WIDTH != 400:
        g.SCREEN_WIDTH = 400
        g.screen = pygame.Surface((g.SCREEN_WIDTH, g.SCREEN_HEIGHT))
        g.set_display_mode()

    # 使用回放预记录的判定数据作为结算
    final_score = rd.score if rd.score > 0 else score
    c = rd.counts
    final_perfect = c.get("perfect", perfect_count)
    final_great = c.get("great", great_count)
    final_good = c.get("good", good_count)
    final_ok = c.get("ok", ok_count)
    final_meh = c.get("meh", meh_count)
    final_miss = c.get("miss", miss_count)
    final_combo = rd.max_combo if rd.max_combo > 0 else max_combo

    from gameplay import show_results_screen
    show_results_screen(map_path, map_data, final_score, final_perfect, final_great, final_good,
                        final_ok, final_meh, final_miss, final_combo, total_judgments,
                        song_rate, rd, total_duration, is_replay=True)
