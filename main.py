import pygame
import sys
import global_state as g

# Initialize engine and shared resources
g.init_globals()

# Import game modules
import menus
import preview
import gameplay

if __name__ == "__main__":
    while True:
        menus.welcome_screen()
        while True:
            song_dict = menus.main_menu()
            if song_dict is None:
                break  # ESC → 返回欢迎界面
            final_map = preview.preview_map(song_dict)
            if final_map:
                while True:
                    res = gameplay.play_game(final_map)
                    if res != "restart":
                        break
