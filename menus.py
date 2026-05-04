import pygame
import sys
import os
import glob
import json
import subprocess
import global_state as g
from skin_importer import get_installed_skins, import_osz, delete_skin


# --- 星数颜色光谱 (osu! 同款) ---

def _star_color(stars):
    """根据星数返回 RGB 颜色。"""
    spectrum = [
        (0.0, (170, 170, 170)), (1.0, (66, 144, 251)), (1.5, (79, 255, 213)),
        (2.5, (124, 255, 79)), (3.5, (246, 240, 92)), (4.5, (255, 128, 104)),
        (5.5, (255, 78, 111)), (6.5, (198, 69, 184)), (8.0, (101, 99, 222)),
    ]
    if stars <= spectrum[0][0]: return spectrum[0][1]
    if stars >= spectrum[-1][0]: return spectrum[-1][1]
    for i in range(len(spectrum) - 1):
        s0, c0 = spectrum[i]; s1, c1 = spectrum[i + 1]
        if s0 <= stars <= s1:
            t = (stars - s0) / (s1 - s0)
            return tuple(int(c0[j] + (c1[j] - c0[j]) * t) for j in range(3))
    return (200, 200, 200)

def load_songs():
    songs_dir = "songs"
    if not os.path.exists(songs_dir):
        try:
            os.makedirs(songs_dir)
        except:
            pass
        
    songs = []
    if os.path.exists(songs_dir):
        for folder_name in os.listdir(songs_dir):
            folder_path = os.path.join(songs_dir, folder_name)
            if os.path.isdir(folder_path):
                jsons = glob.glob(os.path.join(folder_path, "*.json"))
                if jsons:
                    songs.append({
                        "dir_name": folder_name,
                        "path": folder_path,
                        "jsons": sorted(jsons),
                        "selected_diff": 0
                    })
                    
    # 如果没在歌曲目录找到，尝试返回根目录谱面作为兜底
    if not songs:
        all_jsons = glob.glob("*.json")
        map_files = [f for f in all_jsons if f not in ["config.json", "map_export.json"]]
        if not map_files:
            map_files = ["map.json"]
        songs.append({
            "dir_name": "默认根目录谱面",
            "path": ".",
            "jsons": sorted(map_files),
            "selected_diff": 0
        })
        
    return sorted(songs, key=lambda x: x["dir_name"])

def get_first_map_data(song):
    """从歌曲中获取第一个谱面的 JSON 数据和路径"""
    if not song["jsons"]:
        return None, None
    first_json = song["jsons"][0]
    try:
        with open(first_json, "r", encoding="utf-8") as f:
            map_data = json.load(f)
        return first_json, map_data
    except:
        return None, None

def main_menu():
    songs = load_songs()
    selected_index = 0

    camera_y = 0
    
    # 背景缓存
    prev_selected_index = -1
    
    while True:
        # 如果选中歌曲变更 或 显示模式切换后需要重新加载背景
        if selected_index != prev_selected_index or g.bg_dirty:
            g.bg_dirty = False
            prev_selected_index = selected_index
            song = songs[selected_index]
            first_json, map_data = get_first_map_data(song)
            if first_json and map_data:
                g.set_real_background_from_original(first_json, map_data)
            else:
                g.clear_real_background()
        
        g.screen.fill((40, 40, 60))
        
        # 渲染标题和设置提示 (Fixed Header)
        title = g.font.render("=== 选歌菜单 ===", True, (255, 255, 255))
        g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 40))
        
        hist_avg = g.get_average_delay()
        hist_str = f"(avg: {hist_avg:+.0f}ms)" if g.delay_records else "(no data)"
        offset_text = g.small_font.render(f"Offset: {g.config.get('global_offset', 0)}ms {hist_str}  (A / D)", True, (200, 200, 200))
        rate_val = g.config.get("song_rate", 1.0)
        rate_text = g.small_font.render(f"Rate: {rate_val:.2f}x (W/E)", True, (255, 200, 200))
        mirror_on = g.config.get("mirror_mode", False)
        mirror_color = (100, 255, 150) if mirror_on else (150, 150, 150)
        mirror_text = g.small_font.render(f"Mirror: {'ON' if mirror_on else 'OFF'} (M)", True, mirror_color)

        g.screen.blit(offset_text, (20, 80))
        g.screen.blit(rate_text, (20, 110))
        g.screen.blit(mirror_text, (20, 140))
        
        # 预先计算所有曲目的高度和 Y 轴坐标，以便计算滚动视口
        sim_y = 0
        item_bounds = []
        for i, song in enumerate(songs):
            display_name = (">> " if i == selected_index else "   ") + song["dir_name"]
            
            # 使用逐字防爆宽容换行计算高度
            lines_curr = []
            cur_line = ""
            for char in display_name:
                test_line = cur_line + char
                if g.small_font.size(test_line)[0] < g.SCREEN_WIDTH - 40:
                    cur_line = test_line
                else:
                    if cur_line: lines_curr.append(cur_line)
                    cur_line = "      " + char
            if cur_line: lines_curr.append(cur_line)
            
            item_h = len(lines_curr) * 25 + 5
            item_bounds.append({"y": sim_y, "h": item_h, "lines": lines_curr})
            sim_y += item_h
            
        # 设定摄像机滚动目标：让选中的曲目尽量居中
        target_item = item_bounds[selected_index]
        target_camera_y = target_item["y"] + target_item["h"] / 2 - (g.SCREEN_HEIGHT - 190 - 80) / 2
        # 约束滚动边界
        max_scroll = max(0, sim_y - (g.SCREEN_HEIGHT - 190 - 80))
        target_camera_y = max(0, min(target_camera_y, max_scroll))
        
        # 平滑滚动
        camera_y += (target_camera_y - camera_y) * 0.15
        if abs(camera_y - target_camera_y) < 1.0:
            camera_y = target_camera_y

        # 因为 Rate 选项占用了 Y=140，且字体加上行距大概二十多，为防止重叠，把列表绘制的顶线往下推到 Y=175
        clip_rect = pygame.Rect(0, 195, g.SCREEN_WIDTH, g.SCREEN_HEIGHT - 195 - 70)
        g.screen.set_clip(clip_rect)

        # 渲染计算好的曲目列表
        draw_y = 205 - camera_y
        for i, bound in enumerate(item_bounds):
            if draw_y + bound["h"] > 175 and draw_y < g.SCREEN_HEIGHT - 70:
                color = (0, 255, 100) if i == selected_index else (150, 150, 150)
                item_y = draw_y
                for count, line in enumerate(bound["lines"]):
                    item_text = g.small_font.render(line, True, color)
                    x_pos = 20 if count == 0 else 40
                    g.screen.blit(item_text, (x_pos, item_y))
                    item_y += 25
            draw_y += bound["h"]

        # 解除剪裁保护，准备渲染底部菜单
        g.screen.set_clip(None)
        
        # 底部透明渐边/横线遮挡效果（可选）
        pygame.draw.line(g.screen, (100, 100, 150), (0, 195), (g.SCREEN_WIDTH, 195), 2)
        pygame.draw.line(g.screen, (100, 100, 150), (0, g.SCREEN_HEIGHT - 70), (g.SCREEN_WIDTH, g.SCREEN_HEIGHT - 70), 2)

        settings_tip = g.small_font.render("Press S for Settings", True, (200, 255, 200))

        # Blit the text on screen (Centered)
        g.screen.blit(settings_tip, (g.SCREEN_WIDTH // 2 - settings_tip.get_width() // 2, g.SCREEN_HEIGHT - 45))

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    g.show_fps = not g.show_fps
                    
                if event.key == pygame.K_s:
                    settings_menu()
                    
                if event.key == pygame.K_UP:
                    selected_index = (selected_index - 1) % len(songs)
                elif event.key == pygame.K_DOWN:
                    selected_index = (selected_index + 1) % len(songs)
                

                    
                # A/D 键调节全局延迟
                elif event.key == pygame.K_a:
                    step = 1 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 5
                    g.config["global_offset"] -= step
                elif event.key == pygame.K_d:
                    step = 1 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 5
                    g.config["global_offset"] += step
                    
                # W/E 键调节播放倍速
                elif event.key == pygame.K_w:
                    step = 0.01 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 0.1
                    current_rate = g.config.get("song_rate", 1.0)
                    g.config["song_rate"] = max(0.5, round(current_rate - step, 2))
                elif event.key == pygame.K_e:
                    step = 0.01 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 0.1
                    current_rate = g.config.get("song_rate", 1.0)
                    g.config["song_rate"] = min(2.0, round(current_rate + step, 2))

                # M 键切换镜像模式
                elif event.key == pygame.K_m:
                    g.config["mirror_mode"] = not g.config.get("mirror_mode", False)

                # F 键全屏，R 键分辨率
                elif event.key == pygame.K_f and not (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    g.config["fullscreen"] = not g.config.get("fullscreen", False)
                    g.set_display_mode()
                    # 切换模式后 real_bg_surf 被重置，强制下一帧重新加载背景
                    prev_selected_index = -1
                elif event.key == pygame.K_r and not (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    g.config["fullscreen"] = False
                    current_res = (g.config.get("window_width", 400), g.config.get("window_height", 600))
                    available_res = [(1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440)]
                    try:
                        idx = available_res.index(current_res)
                        next_res = available_res[(idx + 1) % len(available_res)]
                    except ValueError:
                        next_res = available_res[0]
                    g.config["window_width"] = next_res[0]
                    g.config["window_height"] = next_res[1]
                    g.set_display_mode()
                    # 分辨率变更后强制重新加载背景
                    prev_selected_index = -1
                    
                elif event.key == pygame.K_RETURN:
                    g.save_config()
                    # 返回整个曲包信息给详细界面
                    song = songs[selected_index]
                    return song
                
                elif event.key == pygame.K_ESCAPE:
                    return None  # 返回欢迎界面

        if g.show_fps:
            fps_text = g.small_font.render(f"FPS: {int(g.clock.get_fps())}", True, (255, 100, 100))
            g.screen.blit(fps_text, (10, g.SCREEN_HEIGHT - 30))

        g.update_display()
        g.clock.tick(60)

# --- 皮肤管理辅助 ---

def _find_osz_files():
    """在 skins/ 目录查找 .osk / .osz 皮肤压缩包。"""
    candidates = []
    search_dir = "skins"
    if os.path.isdir(search_dir):
        for f in os.listdir(search_dir):
            if f.lower().endswith((".osk", ".osz")) and not f.startswith("._"):
                candidates.append(os.path.join(search_dir, f))
    return candidates


def _import_skin_interactive():
    """交互式皮肤导入：列出可导入的 .osk/.osz 文件供用户选择。"""
    candidates = _find_osz_files()
    installed = set(get_installed_skins())

    # 过滤已安装的
    new_skins = []
    for path in candidates:
        name = os.path.splitext(os.path.basename(path))[0]
        if name not in installed:
            new_skins.append(path)

    if not new_skins:
        # 没有新皮肤可导入，显示提示
        g.screen.fill((50, 40, 60))
        title = g.font.render("=== 导入皮肤 ===", True, (255, 255, 255))
        g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 30))
        msg1 = g.small_font.render("没有找到可导入的皮肤文件。", True, (255, 200, 200))
        msg2 = g.small_font.render("请将 .osk/.osz 文件放入 skins/ 目录。", True, (200, 200, 200))
        g.screen.blit(msg1, (g.SCREEN_WIDTH // 2 - msg1.get_width() // 2, 180))
        g.screen.blit(msg2, (g.SCREEN_WIDTH // 2 - msg2.get_width() // 2, 220))
        g.update_display()
        pygame.time.wait(1500)
        return None

    selected = 0
    while True:
        g.screen.fill((50, 40, 60))
        title = g.font.render("=== 导入皮肤 ===", True, (255, 255, 255))
        g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 30))

        hint = g.small_font.render("将 .osk 放入 skins/ 目录后选择导入  [ENTER]确认  [ESC]返回", True, (200, 200, 200))
        g.screen.blit(hint, (g.SCREEN_WIDTH // 2 - hint.get_width() // 2, 80))

        y_off = 140
        for i, path in enumerate(new_skins):
            name = os.path.basename(path)
            color = (0, 255, 100) if i == selected else (150, 150, 150)
            prefix = ">> " if i == selected else "   "
            text = g.small_font.render(prefix + name, True, color)
            g.screen.blit(text, (40, y_off))
            y_off += 35

        g.update_display()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return None
                elif event.key == pygame.K_UP:
                    selected = (selected - 1) % len(new_skins)
                elif event.key == pygame.K_DOWN:
                    selected = (selected + 1) % len(new_skins)
                elif event.key == pygame.K_RETURN:
                    # 导入选中皮肤
                    g.screen.fill((30, 30, 30))
                    msg = g.font.render("Importing...", True, (255, 255, 255))
                    g.screen.blit(msg, (g.SCREEN_WIDTH // 2 - msg.get_width() // 2, g.SCREEN_HEIGHT // 2))
                    g.update_display()

                    skin_name = import_osz(new_skins[selected])
                    if skin_name:
                        g.active_skin_name = skin_name
                        g.config["active_skin"] = skin_name
                        g.save_config()
                        g.load_active_skin()
                        return skin_name
                    else:
                        # 显示错误
                        err_msg = g.small_font.render("Import failed! Press any key.", True, (255, 100, 100))
                        g.screen.blit(err_msg, (g.SCREEN_WIDTH // 2 - err_msg.get_width() // 2, g.SCREEN_HEIGHT // 2 + 40))
                        g.update_display()
                        pygame.time.wait(1500)
                        return None

        g.clock.tick(60)


# --- 流速调节 ---

def _speed_adjuster():
    spd = g.config.get("scroll_speed", 24)
    while True:
        g.screen.fill((40, 30, 50))
        title = g.font.render("=== 调节流速 ===", True, (255, 255, 255))
        g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 40))

        hint = g.small_font.render(f"A/D: 加减  |  Shift+A/D: 快调  |  [S/Enter] 保存  |  [Q/Esc] 取消", True, (200, 200, 200))
        g.screen.blit(hint, (g.SCREEN_WIDTH // 2 - hint.get_width() // 2, 100))

        val = g.font.render(f"流速: {spd:.0f}", True, (0, 255, 150))
        g.screen.blit(val, (g.SCREEN_WIDTH // 2 - val.get_width() // 2, 200))

        bar_w = 300; bar_h = 6; bar_x = 50; bar_y = 280
        pygame.draw.rect(g.screen, (60, 60, 80), (bar_x, bar_y, bar_w, bar_h))
        fill = int((spd - 5) / 55 * bar_w)
        fps_color = (0, 255, 100) if spd < 35 else (255, 200, 50) if spd < 45 else (255, 100, 100)
        pygame.draw.rect(g.screen, fps_color, (bar_x, bar_y, min(fill, bar_w), bar_h))

        g.update_display()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT: return
            if ev.type == pygame.KEYDOWN:
                shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
                step = 10 if shift else 1
                if ev.key == pygame.K_a:
                    spd = max(5, spd - step)
                elif ev.key == pygame.K_d:
                    spd = min(60, spd + step)
                elif ev.key in (pygame.K_s, pygame.K_RETURN):
                    g.config["scroll_speed"] = spd
                    g.save_config()
                    return
                elif ev.key in (pygame.K_q, pygame.K_ESCAPE):
                    return
        g.clock.tick(60)


# --- OD 调节 ---

def _od_adjuster():
    od = g.config.get("od", 5.0)
    while True:
        g.screen.fill((40, 30, 50))
        t = g.font.render("=== OD 判定精度 ===", True, (255, 255, 255))
        g.screen.blit(t, (g.SCREEN_WIDTH // 2 - t.get_width() // 2, 40))

        hint = g.small_font.render("A/D: ±0.1  |  Shift+A/D: ±1.0  |  [S/Enter] 保存  |  [Q/Esc] 取消", True, (200, 200, 200))
        g.screen.blit(hint, (g.SCREEN_WIDTH // 2 - hint.get_width() // 2, 100))

        val = g.font.render(f"OD: {od:.1f}", True, (0, 255, 150))
        g.screen.blit(val, (g.SCREEN_WIDTH // 2 - val.get_width() // 2, 180))

        # 显示各判定窗口
        def _dr(d0, d5, d10):
            o = od
            if o > 5: return d5 + (d10 - d5) * (o - 5) / 5
            elif o < 5: return d5 - (d5 - d0) * (5 - o) / 5
            return d5

        windows = [
            ("PERFECT (305)", _dr(22.4, 19.4, 13.9)),
            ("GREAT (300)", _dr(64, 49, 34)),
            ("GOOD (200)", _dr(97, 82, 67)),
            ("OK (100)", _dr(127, 112, 97)),
            ("MEH (50)", _dr(151, 136, 121)),
            ("MISS", _dr(188, 173, 158)),
        ]
        wy = 230
        for label, w in windows:
            c = (150, 255, 150) if "PERFECT" in label else (255, 255, 150) if "GREAT" in label else \
                (200, 200, 200) if "GOOD" in label else (150, 200, 200) if "OK" in label else \
                (200, 150, 150) if "MEH" in label else (255, 100, 100)
            g.screen.blit(g.tiny_font.render(f"{label}: ±{w:.1f}ms", True, c), (80, wy))
            wy += 22

        # 进度条
        bar_w, bar_h, bar_x, bar_y = 300, 6, 50, wy + 10
        pygame.draw.rect(g.screen, (60, 60, 80), (bar_x, bar_y, bar_w, bar_h))
        fill = int(od / 11 * bar_w)
        od_col = (0, 255, 100) if od < 4 else (255, 200, 50) if od < 8 else (255, 100, 100)
        pygame.draw.rect(g.screen, od_col, (bar_x, bar_y, min(fill, bar_w), bar_h))

        g.update_display()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT: return
            if ev.type == pygame.KEYDOWN:
                shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
                step = 1.0 if shift else 0.1
                if ev.key == pygame.K_a: od = max(0, round(od - step, 1))
                elif ev.key == pygame.K_d: od = min(11, round(od + step, 1))
                elif ev.key in (pygame.K_s, pygame.K_RETURN):
                    g.config["od"] = od; g.save_config(); return
                elif ev.key in (pygame.K_q, pygame.K_ESCAPE): return
        g.clock.tick(60)


# --- 轨道间距 + 舞台缩放 ---

def _stage_adjuster():
    sp = g.config.get("stage_spacing", 100)
    sc = g.config.get("stage_scale", 1.0)

    # 皮肤默认间距（从 skin.ini ColumnWidth 换算）
    skin_default_sp = 100
    if g.skin_assets and g.skin_assets.get("config"):
        cw = g.skin_assets["config"].get("ColumnWidth", "")
        if cw:
            try:
                vals = [float(x.strip()) for x in cw.split(",") if x.strip()]
                if vals:
                    avg_cw = sum(vals) / len(vals)
                    skin_default_sp = int(avg_cw * (600 / 480) * 1.5)
            except: pass

    while True:
        g.screen.fill((40, 30, 50))
        t = g.font.render("=== 轨道布局 ===", True, (255, 255, 255))
        g.screen.blit(t, (g.SCREEN_WIDTH // 2 - t.get_width() // 2, 30))

        hint = g.small_font.render("A/D:间距  Z/C:缩放  Shift:快调  [J]皮肤默认  [S]保存  [Q]取消", True, (200, 200, 200))
        g.screen.blit(hint, (g.SCREEN_WIDTH // 2 - hint.get_width() // 2, 80))

        # 显示值
        g.screen.blit(g.small_font.render(f"间距: {sp:.0f}px    缩放: {sc:.2f}x", True, (0, 255, 150)),
                      (g.SCREEN_WIDTH // 2 - 120, 120))

        # 预览轨道
        gap = sp * sc
        cx = g.SCREEN_WIDTH // 2
        lanes = [cx - gap*1.5, cx - gap*0.5, cx + gap*0.5, cx + gap*1.5]
        nw = int(80 * sc)

        for lx in lanes:
            if 0 <= lx <= g.SCREEN_WIDTH:
                pygame.draw.line(g.screen, (100, 100, 140), (int(lx), 180), (int(lx), 500), 1)

        # 示例音符
        import random
        for i, lx in enumerate(lanes):
            if 0 <= lx <= g.SCREEN_WIDTH:
                pygame.draw.rect(g.screen, (0, 180, 255),
                    (int(lx) - nw//2, 250 + i*40, nw, 18))

        # 判定线
        hy = g.config.get("hit_position", 500)
        pygame.draw.line(g.screen, (255, 60, 60), (0, hy), (g.SCREEN_WIDTH, hy), 3)

        pygame.draw.line(g.screen, (60, 60, 80), (0, 510), (g.SCREEN_WIDTH, 510), 1)

        # 底部 bar
        bar = int(sp / 150 * 200)
        pygame.draw.rect(g.screen, (50, 50, 60), (100, 540, 200, 8))
        pygame.draw.rect(g.screen, (0, 200, 150), (100, 540, min(bar, 200), 8))
        g.screen.blit(g.tiny_font.render(f"间距 {sp}px", True, (200, 200, 200)), (100, 550))

        bar2 = int(sc / 2.5 * 200)
        pygame.draw.rect(g.screen, (50, 50, 60), (100, 570, 200, 8))
        pygame.draw.rect(g.screen, (200, 150, 50), (100, 570, min(bar2, 200), 8))
        g.screen.blit(g.tiny_font.render(f"缩放 {sc:.2f}x", True, (200, 200, 200)), (100, 580))

        g.update_display()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT: return
            if ev.type == pygame.KEYDOWN:
                shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
                s_sp = 10 if shift else 2
                s_sc = 0.1 if shift else 0.02

                if ev.key == pygame.K_a: sp = max(30, sp - s_sp)
                elif ev.key == pygame.K_d: sp = min(200, sp + s_sp)
                elif ev.key == pygame.K_z: sc = max(0.3, round(sc - s_sc, 2))
                elif ev.key == pygame.K_c: sc = min(2.5, round(sc + s_sc, 2))
                elif ev.key == pygame.K_j: sp = skin_default_sp; sc = 1.0
                elif ev.key in (pygame.K_s, pygame.K_RETURN):
                    g.config["stage_spacing"] = sp; g.config["stage_scale"] = sc
                    g.save_config(); return
                elif ev.key in (pygame.K_q, pygame.K_ESCAPE): return
        g.clock.tick(60)


# --- 判定线调节 ---

def judgement_line_adjuster():
    """显示游戏画面预览，调节判定线位置。
    A/D 微调 ±1px  |  Shift+A/D 快调 ±10px  |  S 保存  |  Q 退出不保存
    """
    import pygame
    hit_y = g.config.get("hit_position", 500)
    LANES = [50, 150, 250, 350]

    # 获取皮肤默认判定线位置
    skin_default_y = 500
    if g.skin_assets and g.skin_assets.get("config"):
        skin_hit = g.skin_assets["config"].get("HitPosition")
        if skin_hit:
            try:
                # osu! 坐标转换: 皮肤 HitPosition (480基准) → 游戏 600px 坐标
                osu_hit = float(skin_hit)
                skin_default_y = int(600 - (480 - osu_hit) * (600 / 480))
            except (ValueError, TypeError):
                pass

    while True:
        g.screen.fill((20, 20, 30))

        # 画轨道线
        for x in LANES:
            pygame.draw.line(g.screen, (100, 100, 100), (x, 0), (x, g.SCREEN_HEIGHT), 2)

        # 画皮肤默认判定线（虚线效果）
        for sx in range(0, g.SCREEN_WIDTH, 16):
            pygame.draw.line(g.screen, (80, 80, 120),
                             (sx, skin_default_y), (sx + 8, skin_default_y), 2)

        # 画当前判定线
        pygame.draw.line(g.screen, (255, 50, 50), (0, hit_y), (g.SCREEN_WIDTH, hit_y), 5)

        # 画一些示例音符预览
        demo_notes = [
            (LANES[0], hit_y - 80, (0, 200, 255)),
            (LANES[1], hit_y - 200, (0, 200, 255)),
            (LANES[2], hit_y - 50, (0, 255, 100)),
            (LANES[3], hit_y - 350, (0, 200, 255)),
            (LANES[1], hit_y - 120, (0, 200, 255)),
        ]
        for lx, ly, color in demo_notes:
            if -50 < ly < g.SCREEN_HEIGHT + 50:
                pygame.draw.rect(g.screen, color, (lx - 35, ly - 10, 70, 20))

        # 顶部提示
        title = g.font.render("=== 调节判定线 ===", True, (255, 255, 255))
        g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 8))

        inst = g.small_font.render(
            f"A/D: 上下调节  |  Shift+A/D: 快速  |  [J] 皮肤默认  |  [S] 保存  |  [Q] 取消",
            True, (200, 200, 200))
        g.screen.blit(inst, (g.SCREEN_WIDTH // 2 - inst.get_width() // 2, 40))

        pos_text = g.small_font.render(
            f"当前: Y={hit_y}  |  皮肤默认: Y={skin_default_y}  |  偏移: {hit_y - skin_default_y:+d}px",
            True, (255, 255, 180))
        g.screen.blit(pos_text, (g.SCREEN_WIDTH // 2 - pos_text.get_width() // 2, 65))

        g.update_display()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            elif event.type == pygame.KEYDOWN:
                shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
                step = 10 if shift else 1

                if event.key == pygame.K_a:
                    hit_y = max(100, hit_y - step)
                elif event.key == pygame.K_d:
                    hit_y = min(580, hit_y + step)
                elif event.key == pygame.K_s:
                    # 保存并退出
                    g.config["hit_position"] = hit_y
                    g.save_config()
                    return
                elif event.key == pygame.K_j:
                    hit_y = skin_default_y
                elif event.key == pygame.K_q:
                    return

        g.clock.tick(60)


# --- 2.2 设置界面 (分页) ---

def settings_menu():
    binding_index = -1
    page = 0
    total_pages = 2

    while True:
        g.screen.fill((50, 40, 60))

        # 标题 + 页码
        title = g.font.render(f"=== 游戏设置 ({page+1}/{total_pages+1}) ===", True, (255, 255, 255))
        g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 30))

        nav_hint = g.tiny_font.render("[LEFT]/[RIGHT] 翻页  [ESC] 保存返回", True, (150, 150, 150))
        g.screen.blit(nav_hint, (g.SCREEN_WIDTH // 2 - nav_hint.get_width() // 2, 65))

        if page == 0:
            _draw_settings_page1(binding_index)
        elif page == 1:
            _draw_settings_page2()
        else:
            _draw_settings_page3()

        g.update_display()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    g.show_fps = not g.show_fps
                    continue

                if binding_index != -1:
                    g.config["key_bindings"][binding_index] = str(event.key)
                    binding_index = -1
                    continue

                # 翻页
                if event.key in (pygame.K_LEFT, pygame.K_UP):
                    page = (page - 1) % (total_pages + 1)
                elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                    page = (page + 1) % (total_pages + 1)

                # Page 0 handlers
                elif page == 0:
                    if event.key == pygame.K_ESCAPE:
                        g.save_config(); g.update_key_map(); return
                    elif event.key == pygame.K_1: binding_index = 0
                    elif event.key == pygame.K_2: binding_index = 1
                    elif event.key == pygame.K_3: binding_index = 2
                    elif event.key == pygame.K_4: binding_index = 3
                    elif event.key == pygame.K_COMMA:
                        step = 1 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 5
                        g.config["scroll_speed"] = max(5, g.config.get("scroll_speed", 24) - step)
                    elif event.key == pygame.K_PERIOD:
                        step = 1 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 5
                        g.config["scroll_speed"] = g.config.get("scroll_speed", 24) + step
                    elif event.key == pygame.K_l:
                        _speed_adjuster()

                # Page 1 handlers
                elif page == 1:
                    if event.key == pygame.K_ESCAPE:
                        g.save_config(); g.update_key_map(); return
                    elif event.key == pygame.K_f:
                        g.config["fullscreen"] = not g.config.get("fullscreen", False)
                        g.set_display_mode(); g.bg_dirty = True
                    elif event.key == pygame.K_r:
                        g.config["fullscreen"] = False
                        current_res = (g.config.get("window_width", 400), g.config.get("window_height", 600))
                        available_res = [(1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440)]
                        try:
                            idx = available_res.index(current_res)
                            next_res = available_res[(idx + 1) % len(available_res)]
                        except ValueError: next_res = available_res[0]
                        g.config["window_width"] = next_res[0]; g.config["window_height"] = next_res[1]
                        g.set_display_mode(); g.bg_dirty = True
                    elif event.key == pygame.K_i: _import_skin_interactive()
                    elif event.key == pygame.K_m:
                        skins = get_installed_skins()
                        if skins:
                            if g.active_skin_name and g.active_skin_name in skins:
                                idx = skins.index(g.active_skin_name)
                                g.active_skin_name = skins[(idx + 1) % len(skins)]
                            else: g.active_skin_name = skins[0]
                            g.config["active_skin"] = g.active_skin_name
                            g.save_config(); g.load_active_skin()
                    elif event.key == pygame.K_0:
                        g.active_skin_name = None; g.config["active_skin"] = ""
                        g.save_config(); g.unload_skin()
                    elif event.key == pygame.K_DELETE:
                        if g.active_skin_name:
                            if delete_skin(g.active_skin_name):
                                g.active_skin_name = None; g.config["active_skin"] = ""
                                g.save_config(); g.unload_skin()

                # Page 2 handlers
                elif page == 2:
                    if event.key == pygame.K_ESCAPE:
                        g.save_config(); g.update_key_map(); return
                    elif event.key == pygame.K_j: judgement_line_adjuster()
                    elif event.key == pygame.K_o: _od_adjuster()
                    elif event.key == pygame.K_p: _stage_adjuster()

        g.clock.tick(60)


def _draw_settings_page1(binding_index):
    """第1页: 键位 + 流速"""
    hint = g.small_font.render("按 [1][2][3][4] 改键" if binding_index == -1 else f"按下第 {binding_index+1} 键的新键位...", True, (255, 200, 200))
    g.screen.blit(hint, (g.SCREEN_WIDTH // 2 - hint.get_width() // 2, 90))

    y = 140
    for i in range(4):
        key_raw = g.config["key_bindings"][i]
        try:
            kn = pygame.key.name(int(key_raw)).upper()
        except (ValueError, TypeError):
            kn = key_raw.upper()
        color = (0, 255, 255) if i == binding_index else (200, 200, 200)
        t = g.small_font.render(f"[{i+1}] 轨道 {i+1}: {kn}", True, color)
        g.screen.blit(t, (50, y)); y += 40

    y += 10
    spd = g.config.get("scroll_speed", 24)
    st = g.small_font.render(f"[L] 流速: {spd:.0f}  (按L进入调节)", True, (200, 255, 200))
    g.screen.blit(st, (50, y))


def _draw_settings_page2():
    """第2页: 显示 + 皮肤"""
    y = 140
    fs_status = "开" if g.config.get("fullscreen", False) else "关"
    g.screen.blit(g.small_font.render(f"[F] 全屏: {fs_status}", True, (200, 255, 200)), (50, y)); y += 35
    g.screen.blit(g.small_font.render(f"[R] 分辨率: {g.config.get('window_width', 400)}x{g.config.get('window_height', 600)}", True, (200, 255, 200)), (50, y)); y += 50

    pygame.draw.line(g.screen, (100, 100, 140), (50, y), (g.SCREEN_WIDTH - 50, y)); y += 10
    cn = g.active_skin_name or "默认 (Default)"
    g.screen.blit(g.small_font.render(f"皮肤: {cn}", True, (255, 200, 100)), (50, y)); y += 30
    g.screen.blit(g.tiny_font.render("[I]导入 [M]切换 [DEL]删除 [0]默认", True, (200, 200, 200)), (50, y))


def _draw_settings_page3():
    """第3页: 判定 + 其他"""
    y = 140
    hit_y = g.config.get("hit_position", 500)
    g.screen.blit(g.small_font.render(f"[J] 判定线位置: Y={hit_y}", True, (200, 255, 200)), (50, y)); y += 35
    od = g.config.get("od", 5.0)
    g.screen.blit(g.small_font.render(f"[O] OD 判定精度: {od:.1f}  (按O调节)", True, (200, 255, 200)), (50, y)); y += 35
    sp = g.config.get("stage_spacing", 100)
    sc = g.config.get("stage_scale", 1.0)
    g.screen.blit(g.small_font.render(f"[P] 轨道间距: {sp:.0f}  缩放: {sc:.2f}  (按P调节)", True, (200, 255, 200)), (50, y))

# --- 2.5 谱面信息预览 ---
def exit_confirm():
    import pygame
    import sys
    import global_state as g

    while True:
        overlay = pygame.Surface((g.SCREEN_WIDTH, g.SCREEN_HEIGHT))
        overlay.set_alpha(200)
        overlay.fill((0, 0, 0))
        g.screen.blit(overlay, (0, 0))

        box = pygame.Rect(g.SCREEN_WIDTH // 2 - 150, g.SCREEN_HEIGHT // 2 - 80, 300, 160)
        pygame.draw.rect(g.screen, (50, 50, 70), box)
        pygame.draw.rect(g.screen, (255, 255, 255), box, 2)

        msg = g.font.render("Quit Game?", True, (255, 255, 255))
        msg2 = g.small_font.render("[ENTER] 确认  [ESC] 取消", True, (200, 200, 200))

        g.screen.blit(msg, (g.SCREEN_WIDTH // 2 - msg.get_width() // 2, g.SCREEN_HEIGHT // 2 - 40))
        g.screen.blit(msg2, (g.SCREEN_WIDTH // 2 - msg2.get_width() // 2, g.SCREEN_HEIGHT // 2 + 20))

        g.update_display()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    pygame.quit()
                    sys.exit()
                elif event.key == pygame.K_ESCAPE:
                    return


def welcome_screen():
    """osu! 风格欢迎界面：粉色圆圈 + Py Mania!"""
    import math
    g.clear_real_background()

    import time
    start_ticks = pygame.time.get_ticks()
    revealed = False  # 是否已显示单人模式选项

    cx = g.SCREEN_WIDTH // 2
    cy = g.SCREEN_HEIGHT // 2 - 30
    radius = 90

    while True:
        elapsed = pygame.time.get_ticks() - start_ticks
        # 圆圈呼吸动画
        pulse = 1.0 + math.sin(elapsed * 0.003) * 0.04

        g.screen.fill((20, 20, 35))

        # 粉色外圈光晕
        glow_r = int((radius + 12) * pulse)
        glow = pygame.Surface((glow_r * 2, glow_r * 2), pygame.SRCALPHA)
        for i in range(5, 0, -1):
            alpha = 25 // i
            pygame.draw.circle(glow, (0xff, 0x66, 0x99, alpha), (glow_r, glow_r), glow_r - i * 6)
        g.screen.blit(glow, (cx - glow_r, cy - glow_r))

        # 粉色主圆
        pygame.draw.circle(g.screen, (0xff, 0x66, 0x99), (cx, cy), int(radius * pulse))
        # 内圈高光
        highlight_r = int(radius * 0.7 * pulse)
        pygame.draw.circle(g.screen, (0xff, 0x99, 0xbb), (cx - 8, cy - 8), highlight_r)

        # Py Mania! 文字
        title_text = g.font.render("Py Mania!", True, (255, 255, 255))
        g.screen.blit(title_text, (cx - title_text.get_width() // 2, cy - title_text.get_height() // 2))

        # 单人模式入口（触发后显示）
        if revealed:
            # 左侧竖线（装饰）
            line_x = cx - 60
            pygame.draw.line(g.screen, (255, 255, 255), (line_x, cy + radius + 25), (line_x, cy + radius + 55), 2)
            # 文字
            solo_text = g.font.render("单人模式", True, (255, 255, 255))
            g.screen.blit(solo_text, (cx - solo_text.get_width() // 2, cy + radius + 35))
            dot_text = g.small_font.render("(Press ENTER)", True, (180, 180, 180))
            g.screen.blit(dot_text, (cx - dot_text.get_width() // 2, cy + radius + 65))

        # 底部版本信息
        ver = g.tiny_font.render("v1.0  |  osu!-style 4K Rhythm Game", True, (120, 120, 140))
        g.screen.blit(ver, (g.SCREEN_WIDTH // 2 - ver.get_width() // 2, g.SCREEN_HEIGHT - 30))

        g.update_display()
        g.clock.tick(60)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    exit_confirm()
                    # 返回后重置状态
                    revealed = False
                    start_ticks = pygame.time.get_ticks()
                elif event.key == pygame.K_RETURN:
                    if revealed:
                        return
                    else:
                        revealed = True
                elif event.key == pygame.K_f and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    g.show_fps = not g.show_fps
                else:
                    # 任意其他键显示单人模式
                    if not revealed:
                        revealed = True
            elif event.type == pygame.MOUSEBUTTONDOWN:
                # 点击圆圈或任意位置显示单人模式
                if not revealed:
                    revealed = True

