import pygame
import sys
import os
import glob
import json
import subprocess
import global_state as g
import mania_difficulty
from replay import get_replay_files

def show_history(map_path):
    rel_path = os.path.relpath(map_path, start=os.getcwd()).replace("\\", "/")
    records = g.history_data.get(rel_path, [])
    
    while True:
        g.screen.fill((40, 40, 60))
        
        title = g.font.render("=== 游玩历史 ===", True, (255, 255, 255))
        g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 40))
        
        lines = []
        if not records:
            lines.append("暂无游玩记录")
        else:
            for i, rec in enumerate(records):
                # 记录格式: 
                # (分数) (ACC)
                # (时间) (倍速)
                lines.append(f"#{i+1} 分数: {rec['score']}  ACC: {rec['acc']:.2f}%")
                lines.append(f"    {rec['time']}  (倍速: {rec.get('rate', 1.0)}x)")
                lines.append("") # 留空一行间距
                
        lines.append("按 [ESC] 返回")
        
        y_offset = 100
        for line in lines:
            if not line:
                y_offset += 25
                continue
            color = (255, 255, 0) if "ESC" in line else (200, 255, 255) if "#" in line else (200, 200, 200)
            g.draw_marquee_text(g.screen, line, g.small_font, color, g.SCREEN_WIDTH // 2, y_offset, g.SCREEN_WIDTH - 20)
            y_offset += 25
            
        g.update_display()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                import sys
                pygame.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                if not records:
                    return # Any key quits empty history
                if event.key == pygame.K_ESCAPE:
                    return
        g.clock.tick(60)

def preview_map(song_dict):
    selected_diff = song_dict["selected_diff"]
    jsons = song_dict["jsons"]
    
    map_data = {}
    notes_data = []
    total_notes = 0
    song_name = ""
    bg_surf = None
    duration_sec = 0
    duration_str = "00:00"
    current_json = ""
    star_rating = 0.0
    
    def load_diff(idx):
        nonlocal selected_diff, map_data, notes_data, total_notes, song_name, bg_surf, duration_sec, duration_str, current_json, star_rating
        selected_diff = idx % len(jsons)
        current_json = jsons[selected_diff]
        
        # 计算星数（含速度因子）
        star_rating = mania_difficulty.calculate_stars_for_json(
            current_json, speed=g.config.get("song_rate", 1.0))
        
        with open(current_json, "r", encoding="utf-8") as f:
            map_data = json.load(f)
            
        notes_data = map_data["notes"]
        total_notes = len(notes_data)
        
        audio_file = map_data["meta"]["song"]
        song_name = os.path.splitext(os.path.basename(audio_file))[0]
        
        # 尝试加载可能存在的背景图
        bg_surf = g.load_bg_image(current_json, map_data)
        
        if total_notes > 0:
            last_note_time = max([n.get("end_time", n.get("time")) for n in notes_data])
            duration_sec = int((last_note_time / 1000) / g.config.get("song_rate", 1.0))
        else:
            duration_sec = 0
            
        mins = duration_sec // 60
        secs = duration_sec % 60
        duration_str = f"{mins:02d}:{secs:02d}"

    load_diff(selected_diff)
    
    while True:
        # 重置背景层
        g.screen.fill((40, 40, 60))
        
        title = g.font.render("=== 谱面预览 ===", True, (255, 255, 255))
        g.screen.blit(title, (g.SCREEN_WIDTH // 2 - title.get_width() // 2, 40))
        
        y_offset = 100
        
        if bg_surf:
            bg_x = g.SCREEN_WIDTH // 2 - bg_surf.get_width() // 2
            g.screen.blit(bg_surf, (bg_x, y_offset))
            # 画一个带点颜色的细边框
            pygame.draw.rect(g.screen, (200, 200, 200), (bg_x, y_offset, bg_surf.get_width(), bg_surf.get_height()), 2)
            y_offset += bg_surf.get_height() + 20
        else:
            y_offset += 40
        
        diff_count = len(jsons)
        diff_name = os.path.basename(current_json).replace(".json", "")
        
        lines = [
            f"歌曲名称: {song_name}",
            f"谱面星级: {star_rating:.2f}★",
            f"歌曲难度: < {selected_diff+1}/{diff_count}  {diff_name} >",
            f"歌曲长度: {duration_str}",
            f"游戏倍速: {g.config.get('song_rate', 1.0):.1f}x",
            f"按键总数: {total_notes}",
            "",
            "按 [ENTER] 正式开始",
            "按 [Y] 查看游玩历史",
            "按 [R] 查看回放"
        ]
        
        # 使用跑马灯渲染文本
        y_step = 28
        for line in lines:
            if not line:
                y_offset += y_step
                continue
            
            if "ENTER" in line or "[Y]" in line:
                color = (255, 255, 0)
            elif "星级" in line:
                color = (255, 180, 50)  # 橙亮色突出显示星级
            elif "难度:" in line:
                color = (200, 255, 255)
            else:
                color = (200, 200, 200)
                
            g.draw_marquee_text(g.screen, line, g.small_font, color, g.SCREEN_WIDTH // 2, y_offset, g.SCREEN_WIDTH - 20)
            y_offset += y_step
            
        if g.show_fps:
            fps_text = g.small_font.render(f"FPS: {int(g.clock.get_fps())}", True, (255, 100, 100))
            g.screen.blit(fps_text, (10, g.SCREEN_HEIGHT - 30))
            
        g.update_display()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    g.show_fps = not g.show_fps
                elif event.key == pygame.K_LEFT:
                    load_diff(selected_diff - 1)
                elif event.key == pygame.K_RIGHT:
                    load_diff(selected_diff + 1)
                elif event.key == pygame.K_y:
                    show_history(current_json)
                elif event.key == pygame.K_r:
                    _show_replays_for_map(song_dict["path"])
                elif event.key == pygame.K_RETURN:
                    # Save back the selected diff so if user goes back it stays
                    song_dict["selected_diff"] = selected_diff
                    return current_json # 确认开始
                elif event.key == pygame.K_ESCAPE:
                    song_dict["selected_diff"] = selected_diff
                    return None

        g.clock.tick(60)


def _show_replays_for_map(map_dir):
    """浏览并播放谱面目录下的回放文件。"""
    replays = get_replay_files(map_dir)
    if not replays:
        g.screen.fill((40, 40, 60))
        t = g.font.render("=== 回放 ===", True, (255, 255, 255))
        g.screen.blit(t, (g.SCREEN_WIDTH // 2 - t.get_width() // 2, 40))
        msg = g.small_font.render("没有找到回放文件。", True, (200, 200, 200))
        g.screen.blit(msg, (g.SCREEN_WIDTH // 2 - msg.get_width() // 2, 200))
        g.update_display()
        pygame.time.wait(1500)
        return

    selected = 0
    while True:
        g.screen.fill((40, 40, 60))
        t = g.font.render("=== 选择回放 ===", True, (255, 255, 255))
        g.screen.blit(t, (g.SCREEN_WIDTH // 2 - t.get_width() // 2, 30))
        h = g.small_font.render("[ENTER] 播放  [ESC] 返回", True, (200, 200, 200))
        g.screen.blit(h, (g.SCREEN_WIDTH // 2 - h.get_width() // 2, 70))

        y = 120
        max_show = 10
        start = max(0, min(selected - max_show // 2, len(replays) - max_show))
        for i in range(start, min(start + max_show, len(replays))):
            fname = os.path.basename(replays[i]).replace(".osr", "")
            color = (0, 255, 100) if i == selected else (150, 150, 150)
            prefix = ">> " if i == selected else "   "
            lbl = g.small_font.render(prefix + fname[:50], True, color)
            g.screen.blit(lbl, (20, y))
            y += 28

        g.update_display()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT: pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE: return
                if ev.key == pygame.K_UP: selected = max(0, selected - 1)
                if ev.key == pygame.K_DOWN: selected = min(len(replays) - 1, selected + 1)
                if ev.key == pygame.K_RETURN:
                    from replay_viewer import play_replay
                    play_replay(replays[selected])
        g.clock.tick(60)
