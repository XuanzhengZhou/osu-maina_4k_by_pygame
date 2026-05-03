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

    # 使用回放记录的设置
    song_rate = rd.song_rate
    od = rd.od
    scroll_speed = rd.scroll_speed
    HIT_Y = rd.hit_position
    LANES = [50, 150, 250, 350]

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

    # 回放帧索引
    frame_idx = 0
    replay_frames = rd.frames

    # 延迟加载 gameplay 渲染函数（避免循环导入）
    from gameplay import (_draw_stage_background, _draw_key_pads,
                          _draw_tap_note_with_skin, _draw_hold_note_with_skin,
                          _draw_hit_burst, _scale_to_width)

    while True:
        g.screen.fill((30, 30, 30))
        real_elapsed_time = pygame.time.get_ticks() - start_time
        current_time = real_elapsed_time * song_rate - map_offset - global_offset - LEAD_IN_TIME

        if current_time >= 0 and not music_started and g.mixer_available:
            g.audio_play()
            music_started = True

        # 处理事件（允许 ESC 退出回放）
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

        # --- 模拟按键：从回放帧读取 ---
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
                                elif best.get("type") == "hold":
                                    best["holding"] = True
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

            frame_idx += 1

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

        # --- 底部漏判 ---
        while active_idx < len(notes_data):
            old_note = notes_data[active_idx]
            nt = old_note.get("end_time", old_note["time"])
            if (old_note["hit"] or old_note["missed"]) and (current_time - nt) * eff_speed > 300:
                active_idx += 1
            else: break

        for i in range(active_idx, len(notes_data)):
            note = notes_data[i]
            if (note["time"] - current_time) * eff_speed > g.SCREEN_HEIGHT + 100:
                break
            note_type = note.get("type", "tap")
            if note_type == "tap":
                if not note["hit"] and not note["missed"] and current_time - note["time"] > MISS_WINDOW:
                    note["missed"] = True; combo = 0; miss_count += 1
            elif note_type == "hold":
                if not note["hit"]:
                    if not note["missed"] and not note.get("holding") and current_time - note["time"] > MISS_WINDOW:
                        note["missed"] = True; combo = 0; miss_count += 1
                    elif note.get("holding") and current_time >= note["end_time"]:
                        note["hit"] = True; note["holding"] = False
                        score += 305; perfect_count += 1; combo += 1
                        max_combo = max(max_combo, combo)

        # --- 渲染 ---
        _draw_stage_background()
        if g.skin_assets:
            _draw_key_pads(g.key_pressed_state)

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

        # 顶部UI
        pygame.draw.rect(g.screen, (0, 0, 0), (0, 0, g.SCREEN_WIDTH, 40))
        pygame.draw.line(g.screen, (200, 200, 200), (0, 40), (g.SCREEN_WIDTH, 40), 2)

        cb = g.small_font.render(f"Combo: {combo}", True, (255, 255, 0))
        g.screen.blit(cb, (10, 10))
        sign = "+" if last_hit_offset > 0 else ""
        avg = total_offset / total_hits if total_hits > 0 else 0
        avg_sign = "+" if avg > 0 else ""
        od_text = g.tiny_font.render(f"Offset: {sign}{last_hit_offset:.0f}ms (avg {avg_sign}{avg:.0f}ms)", True, (150,255,150))
        g.screen.blit(od_text, (10, 34))

        pn = perfect_count + great_count + good_count + ok_count + meh_count + miss_count
        acc_val = (score / (pn * 305) * 100) if pn > 0 else 100.0
        ac = g.small_font.render(f"ACC: {acc_val:.2f}%", True, (0, 255, 255))
        g.screen.blit(ac, (g.SCREEN_WIDTH - ac.get_width() - 10, 10))

        hit_timestamps = [t for t in hit_timestamps if current_time - t <= 3000]
        kps_val = len(hit_timestamps) / 3.0
        kps = g.tiny_font.render(f"KPS: {kps_val:.1f}", True, (150, 200, 255))
        g.screen.blit(kps, (g.SCREEN_WIDTH - kps.get_width() - 10, 34))

        # REPLAY 标记
        replay_tag = g.small_font.render("[REPLAY]", True, (255, 100, 100))
        g.screen.blit(replay_tag, (g.SCREEN_WIDTH // 2 - replay_tag.get_width() // 2, 10))

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

    # 统一结算界面（与正常游玩相同 + [REPLAY] 标记）
    from gameplay import show_results_screen
    show_results_screen(map_path, map_data, score, perfect_count, great_count, good_count,
                        ok_count, meh_count, miss_count, max_combo, total_judgments,
                        song_rate, rd, total_duration, is_replay=True)
