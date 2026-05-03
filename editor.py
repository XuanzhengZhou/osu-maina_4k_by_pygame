import pygame
import sys
import json
import os
import shutil
import subprocess

pygame.init()
pygame.mixer.init()

SCREEN_WIDTH = 600
SCREEN_HEIGHT = 800
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Json 制谱器")
pygame.key.stop_text_input()  # 禁用输入法，防止在 Windows 下按字母键被输入法拦截
clock = pygame.time.Clock()

LANES = [100, 200, 300, 400]
timeline_y = 700

map_data = {
    "meta": {
        "song": "song0.ogg",
        "bg": "",
        "offset": 0,
        "bpm": 218.0
    },
    "notes": []
}

# 当前工作区中的实际文件路径（便于后续复制和加载）
current_song_path = "song0.ogg"
current_bg_path = ""

playback_speed = 1.0

import sonic_python

def load_audio(speed=1.0):
    global current_song_path
    if not os.path.exists(current_song_path):
        print(f"音频文件不存在: {current_song_path}")
        return
    
    if speed == 1.0:
        try:
            pygame.mixer.music.load(current_song_path)
        except Exception as e:
            print(f"无法加载音频 {current_song_path}: {e}")
    else:
        temp_song = "temp_" + os.path.basename(current_song_path)
        temp_song_path = os.path.splitext(temp_song)[0] + ".wav"
        try:
            # 使用原生的 sonic-python CTypes 绑定
            sonic_python.generate_stretched_audio(current_song_path, temp_song_path, speed)
            pygame.mixer.music.load(temp_song_path)
            print(f"正在以 {speed}x 速度加载音频")
        except Exception as e:
            print(f"变调加载失败: {e}")

load_audio(playback_speed)

bpm = map_data["meta"]["bpm"]
snap_divisor = 4 
use_snap = True

def get_snap_step():
    return 60000.0 / bpm / snap_divisor

def snap_time(t):
    if not use_snap:
        return t
    step = get_snap_step()
    offset = map_data["meta"]["offset"]
    return round((t - offset) / step) * step + offset

current_time = 0
is_playing = False
zoom = 0.5

holding_lane = -1
hold_start_time = 0
show_help = False

# 使用支持中文的字体列表防止因为含有中文字符导致的豆腐块（白框）
chinese_fonts = ["notosanscjkscregular", "notosanscjksc", "wqyzenhei", "wqymicrohei", "microsoftyahei", "simhei", "arial"]
font = pygame.font.SysFont(chinese_fonts, 22)
help_font = pygame.font.SysFont(chinese_fonts, 20)

def time_to_y(t):
    return timeline_y - (t - current_time) * zoom

def y_to_time(y):
    return current_time + (timeline_y - y) / zoom

def open_file_dialog(file_type="audio"):
    try:
        if file_type == "audio":
            filter_str = "Audio files | *.ogg *.mp3 *.wav"
        elif file_type == "image":
            filter_str = "Image files | *.png *.jpg *.jpeg"
        elif file_type == "json":
            filter_str = "JSON files | *.json"
        else:
            filter_str = "* | *"
            
        result = subprocess.run(
            ["zenity", "--file-selection", "--title", f"选择文件 ({file_type})", f"--file-filter={filter_str}"], 
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        if file_type == "audio":
            return filedialog.askopenfilename(filetypes=[("Audio Files", "*.ogg *.mp3 *.wav")])
        elif file_type == "image":
            return filedialog.askopenfilename(filetypes=[("Image Files", "*.png *.jpg *.jpeg")])
        elif file_type == "json":
            return filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
    return ""

def ask_project_name(default_name):
    # 手动输入项目名称并检测重复
    try:
        while True:
            result = subprocess.run(
                ["zenity", "--entry", "--title", "保存项目", "--text", "请输入项目(文件夹)名称:", "--entry-text", default_name],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                print("取消保存")
                return None, None
            
            proj_name = result.stdout.strip()
            if not proj_name:
                continue
                
            export_dir = os.path.join("songs", proj_name)
            map_path = os.path.join(export_dir, "map.json")
            if os.path.exists(export_dir):
                if os.path.exists(map_path):
                    # 如果这刚好是个项目文件夹并且已有 map.json
                    ans = subprocess.run(
                        ["zenity", "--list", "--radiolist", "--title", "文件已存在", "--text", f"文件夹 '{proj_name}' 已存在 map.json，请选择操作:",
                         "--column=选择", "--column=操作", "TRUE", "覆盖原谱面 (map.json)", "FALSE", "另存为新谱面 (map_1.json...)"],
                        capture_output=True, text=True
                    )
                    if ans.returncode == 0:
                        choice = ans.stdout.strip()
                        if "覆盖" in choice:
                            return proj_name, "map.json"
                        else:
                            # 寻找 map_1, map_2...
                            idx = 1
                            while os.path.exists(os.path.join(export_dir, f"map_{idx}.json")):
                                idx += 1
                            return proj_name, f"map_{idx}.json"
                    else:
                        continue
                else:
                    return proj_name, "map.json"
            else:
                return proj_name, "map.json"
    except FileNotFoundError:
        import tkinter as tk
        from tkinter import simpledialog, messagebox
        root = tk.Tk()
        root.withdraw()
        while True:
            proj_name = simpledialog.askstring("保存项目", "请输入项目(文件夹)名称:", initialvalue=default_name)
            if not proj_name:
                print("取消保存")
                return None, None
            export_dir = os.path.join("songs", proj_name)
            map_path = os.path.join(export_dir, "map.json")
            if os.path.exists(export_dir) and os.path.exists(map_path):
                # 简单粗暴提示
                if messagebox.askyesno("文件冲突", f"文件夹 '{proj_name}' 中已存在 map.json。\n\n选 '是' 将覆盖，选 '否' 将自动另存为 map_x.json。"):
                    return proj_name, "map.json"
                else:
                    idx = 1
                    while os.path.exists(os.path.join(export_dir, f"map_{idx}.json")):
                        idx += 1
                    return proj_name, f"map_{idx}.json"
            else:
                return proj_name, "map.json"

running = True
update_delta = clock.tick(60)

while running:
    update_delta = clock.tick(60)
    screen.fill((50, 50, 50))
    
    if is_playing:
        current_time += update_delta * playback_speed

    mouse_x, mouse_y = pygame.mouse.get_pos()
    
    hover_lane = -1
    for i, lx in enumerate(LANES):
        if lx - 40 < mouse_x < lx + 40:
            hover_lane = i
            break

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        
        elif event.type == pygame.KEYDOWN:
            mods = pygame.key.get_mods()
            shift_pressed = mods & pygame.KMOD_SHIFT
            
            if event.key == pygame.K_SPACE:
                is_playing = not is_playing
                if is_playing:
                    try:
                        pygame.mixer.music.play(0, (current_time / 1000.0) / playback_speed)
                    except pygame.error:
                        pass
                else:
                    pygame.mixer.music.stop()

            elif event.key == pygame.K_UP and not is_playing:
                current_time += get_snap_step() * snap_divisor
                current_time = snap_time(current_time)
            elif event.key == pygame.K_DOWN and not is_playing:
                current_time = max(0, current_time - get_snap_step() * snap_divisor) 
                current_time = snap_time(current_time)
            
            elif event.key == pygame.K_LEFT:
                map_data["meta"]["offset"] -= 5
                current_time = snap_time(current_time)
            elif event.key == pygame.K_RIGHT:
                map_data["meta"]["offset"] += 5
                current_time = snap_time(current_time)
            
            elif event.key == pygame.K_q:
                if snap_divisor > 1:
                    snap_divisor //= 2
            elif event.key == pygame.K_e:
                snap_divisor *= 2
            
            elif event.key == pygame.K_g:
                use_snap = not use_snap
                
            elif event.key == pygame.K_w:
                playback_speed = max(0.5, playback_speed - 0.25)
                is_playing = False
                pygame.mixer.music.stop()
                load_audio(playback_speed)
            elif event.key == pygame.K_r:
                playback_speed = min(2.0, playback_speed + 0.25)
                is_playing = False
                pygame.mixer.music.stop()
                load_audio(playback_speed)
            
            elif event.key == pygame.K_EQUALS:
                zoom = min(5.0, zoom + 0.1)
            elif event.key == pygame.K_MINUS:
                zoom = max(0.1, zoom - 0.1)

            # 【修改：微调 BPM (配合 Shift 键) 】
            elif event.key == pygame.K_LEFTBRACKET:
                step_int = 1 if shift_pressed else 10
                bpm_int = int(round(bpm * 10))
                bpm = max(1.0, (bpm_int - step_int) / 10.0)
                map_data["meta"]["bpm"] = bpm
            elif event.key == pygame.K_RIGHTBRACKET:
                step_int = 1 if shift_pressed else 10
                bpm_int = int(round(bpm * 10))
                bpm = (bpm_int + step_int) / 10.0
                map_data["meta"]["bpm"] = bpm
                
            # 导入音频
            elif event.key == pygame.K_i:
                file_path = open_file_dialog("audio")
                if file_path:
                    current_song_path = file_path
                    map_data["meta"]["song"] = os.path.basename(file_path)
                    current_time = 0
                    is_playing = False
                    pygame.mixer.music.stop()
                    load_audio(playback_speed)
                    
            # 【新增：导入封面】
            elif event.key == pygame.K_c:
                file_path = open_file_dialog("image")
                if file_path:
                    current_bg_path = file_path
                    map_data["meta"]["bg"] = os.path.basename(file_path)
                    print(f"已选择封面: {file_path}")

            # 【新增：导入谱面 (Load)】
            elif event.key == pygame.K_l:
                file_path = open_file_dialog("json")
                if file_path:
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            map_data = json.load(f)
                        bpm = map_data["meta"].get("bpm", 218)
                        
                        target_dir = os.path.dirname(os.path.abspath(file_path))
                        # 尝试加载相对路径的音频和封面
                        song_name = map_data["meta"].get("song", "")
                        if song_name:
                            pot_song_path = os.path.join(target_dir, song_name)
                            if os.path.exists(pot_song_path):
                                current_song_path = pot_song_path

                        bg_name = map_data["meta"].get("bg", "")
                        if not bg_name:
                            bg_name = map_data["meta"].get("cover", "")
                            
                        # 如果加载的旧谱面是用 cover，转成 bg
                        if "cover" in map_data["meta"]:
                            map_data["meta"]["bg"] = map_data["meta"]["cover"]
                            del map_data["meta"]["cover"]

                        if bg_name:
                            pot_bg_path = os.path.join(target_dir, bg_name)
                            if os.path.exists(pot_bg_path):
                                current_bg_path = pot_bg_path
                        
                        current_time = 0
                        is_playing = False
                        pygame.mixer.music.stop()
                        load_audio(playback_speed)
                        print(f"成功加载谱面: {file_path}")
                    except Exception as e:
                        print(f"加载谱面失败: {e}")

            elif event.key == pygame.K_o:
                show_help = not show_help
                
            # 【新增：批量删除与一键清空】
            elif event.key == pygame.K_DELETE:
                if mods & pygame.KMOD_CTRL:
                    # 一键清空所有音符
                    map_data["notes"] = []
                    print("已清空所有音符!")
                else:
                    # 批量删除当前屏幕上可视的音符
                    visible_notes = []
                    for note in map_data["notes"]:
                        if note["type"] == "tap":
                            y = time_to_y(note["time"])
                            if -50 < y < SCREEN_HEIGHT + 50:
                                visible_notes.append(note)
                        elif note["type"] == "hold":
                            y1 = time_to_y(note["time"])
                            y2 = time_to_y(note["end_time"])
                            if min(y1, y2) < SCREEN_HEIGHT + 50 and max(y1, y2) > -50:
                                visible_notes.append(note)
                    for n in visible_notes:
                        map_data["notes"].remove(n)
                    print(f"已批量删除当前屏幕内的 {len(visible_notes)} 个音符!")

            # 【修改：保存时自动归档工作流】
            elif event.key == pygame.K_s:
                # 默认名字为歌曲文件名去后缀
                audio_name = map_data["meta"].get("song", "unknown_song")
                default_folder = os.path.splitext(audio_name)[0]
                
                # 开始执行输入检测流程
                final_folder_name, final_json_name = ask_project_name(default_folder)
                if not final_folder_name:
                    continue  # 用户取消了操作

                export_dir = os.path.join("songs", final_folder_name)
                os.makedirs(export_dir, exist_ok=True)
                
                # 复制音频文件及其封面文件
                if current_song_path and os.path.exists(current_song_path):
                    target_song = os.path.join(export_dir, map_data["meta"]["song"])
                    if os.path.abspath(current_song_path) != os.path.abspath(target_song):
                        shutil.copy(current_song_path, target_song)
                        current_song_path = target_song # 更新内部路径防重复拷贝
                        
                if current_bg_path and os.path.exists(current_bg_path):
                    target_bg = os.path.join(export_dir, map_data["meta"]["bg"])
                    if os.path.abspath(current_bg_path) != os.path.abspath(target_bg):
                        shutil.copy(current_bg_path, target_bg)
                        current_bg_path = target_bg
                
                map_data["notes"].sort(key=lambda n: n["time"])
                export_path = os.path.join(export_dir, final_json_name)
                with open(export_path, "w", encoding="utf-8") as f:
                    json.dump(map_data, f, indent=4, ensure_ascii=False)
                
                print(f"成功导出至目录组: {export_dir}")
                print(f"谱面路径: {export_path}")
        
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                if hover_lane != -1:
                    holding_lane = hover_lane
                    raw_time = y_to_time(mouse_y)
                    hold_start_time = snap_time(raw_time)
            elif event.button == 3:
                raw_time = y_to_time(mouse_y)
                if hover_lane != -1:
                    to_remove = None
                    for note in reversed(map_data["notes"]):
                        if note["lane"] == hover_lane:
                            if note["type"] == "tap":
                                if abs(note["time"] - raw_time) < 30 / zoom:
                                    to_remove = note
                                    break
                            elif note["type"] == "hold":
                                st, ed = min(note["time"], note["end_time"]), max(note["time"], note["end_time"])
                                if st - 30/zoom <= raw_time <= ed + 30/zoom:
                                    to_remove = note
                                    break
                    if to_remove:
                        map_data["notes"].remove(to_remove)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if holding_lane != -1 and hover_lane == holding_lane:
                raw_end_time = y_to_time(mouse_y)
                hold_end_time = snap_time(raw_end_time)
                
                if abs(hold_end_time - hold_start_time) < get_snap_step() / 2: 
                    map_data["notes"].append({
                        "type": "tap",
                        "time": int(hold_start_time),
                        "lane": holding_lane
                    })
                else:
                    st = min(hold_start_time, hold_end_time)
                    ed = max(hold_start_time, hold_end_time)
                    map_data["notes"].append({
                        "type": "hold",
                        "time": int(st),
                        "end_time": int(ed),
                        "lane": holding_lane
                    })
            holding_lane = -1
            
        elif event.type == pygame.MOUSEWHEEL and not is_playing:
            # event.y > 0 为向上滚，event.y < 0 为向下滚
            mods = pygame.key.get_mods()
            # 如果按住Shift，滚动速度加快
            multiplier = 4 if (mods & pygame.KMOD_SHIFT) else 1
            
            if event.y > 0:
                current_time += get_snap_step() * snap_divisor * event.y * multiplier
                current_time = snap_time(current_time)
            elif event.y < 0:
                current_time = max(0, current_time + get_snap_step() * snap_divisor * event.y * multiplier)
                current_time = snap_time(current_time)

    for lx in LANES:
        pygame.draw.line(screen, (100, 100, 100), (lx, 0), (lx, SCREEN_HEIGHT), 2)
    pygame.draw.line(screen, (255, 0, 0), (0, timeline_y), (SCREEN_WIDTH, timeline_y), 3)

    step_time = get_snap_step()
    offset = map_data["meta"]["offset"]
    
    first_visible_time = ((current_time - offset) // step_time) * step_time + offset
    visible_height_ms = SCREEN_HEIGHT / zoom 
    
    t = first_visible_time
    while t < current_time + visible_height_ms + step_time:
        y = time_to_y(t)
        if 0 < y < timeline_y:
            current_beat_index = round((t - offset) / step_time)
            is_beat = current_beat_index % snap_divisor == 0
            
            color = (150, 150, 150) if is_beat else (70, 70, 70)
            thickness = 2 if is_beat else 1
            start_x = LANES[0] - 40
            end_x = LANES[-1] + 40
            pygame.draw.line(screen, color, (start_x, y), (end_x, y), thickness)
        
        t += step_time

    for note in map_data["notes"]:
        lx = LANES[note["lane"]]
        if note["type"] == "tap":
            y = time_to_y(note["time"])
            if -50 < y < SCREEN_HEIGHT + 50:
                pygame.draw.rect(screen, (0, 200, 255), (lx - 40, y - 10, 80, 20))
        elif note["type"] == "hold":
            y1 = time_to_y(note["time"])
            y2 = time_to_y(note["end_time"])
            if min(y1,y2) < SCREEN_HEIGHT + 50 and max(y1,y2) > -50:
                pygame.draw.rect(screen, (0, 255, 100), (lx - 40, y2, 80, y1 - y2))

    if holding_lane != -1:
        lx = LANES[holding_lane]
        y1 = time_to_y(hold_start_time)
        y2 = mouse_y
        pygame.draw.rect(screen, (200, 255, 100), (lx - 40, min(y1,y2), 80, abs(y1-y2)), border_radius=5)

    time_str = f"Time: {int(current_time)} ms  |  Zoom: {zoom:.1f}x"
    screen.blit(font.render(time_str, True, (255, 255, 255)), (10, 10))
    status_str = f"[{'PLAYING' if is_playing else 'PAUSED'}] | Div: 1/{snap_divisor} | BPM: {bpm}"
    screen.blit(font.render(status_str, True, (0, 255, 0) if is_playing else (255, 200, 0)), (10, 35))
    
    # 【新增：如果有封面/歌曲信息则展示一下】
    bg_txt = map_data['meta'].get('bg', '')
    song_txt = map_data['meta'].get('song', '')
    info_str = f"Song: {song_txt}  |  Bg: {bg_txt if bg_txt else 'None'}"
    screen.blit(font.render(info_str, True, (150, 200, 150)), (10, 60))
    screen.blit(font.render("Press 'O' for Options / Help", True, (200, 200, 255)), (10, 85))

    if show_help:
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        overlay.set_alpha(200)
        overlay.fill((0, 0, 0))
        screen.blit(overlay, (0, 0))
        
        help_texts = [
            "--- Editor Shortcuts ---",
            "[Space]: Play / Pause",
            "[[ / ]]: +/- 1.0 BPM (Hold Shift for +/- 0.1 BPM)",
            "[Up/Down]: Scroll Time",
            "[- / =]: Zoom Out/In (Adjust Falling Speed)",
            "[Q / E]: Decrease/Increase Beat Snap Divisor",
            "[G]: Toggle Grid Snap",
            "[W / R]: Audio Playback Speed",
            "[Left/Right]: Adjust Global Offset (-5/+5 ms)",
            "[ I ]: Import Audio File",
            "[ C ]: Import Cover Image",
            "[ L ]: Load existing map.json",
            "[ S ]: Save (Auto-creates map folder structure)",
            "[Left Click]: Place note or drag for hold",
            "[Right Click]: Delete note",
            "[Del]: Delete Visible Notes (Ctrl+Del to Clear All)",
            "[ O ]: Toggle this Help Menu"
        ]
        
        y_pos = 100
        for text in help_texts:
            lbl = help_font.render(text, True, (255, 255, 255))
            screen.blit(lbl, (SCREEN_WIDTH//2 - lbl.get_width()//2, y_pos))
            y_pos += 35

    pygame.display.flip()

pygame.quit()
