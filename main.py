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
        song_dict = menus.main_menu()
        final_map = preview.preview_map(song_dict)
        if final_map:
            while True:
                res = gameplay.play_game(final_map)
                if res != "restart":
                    break
