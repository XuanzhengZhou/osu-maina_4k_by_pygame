import pygame
import sys
import os
import json
import ctypes


# --- 安全图片加载 (pygame 无 SDL_image 时的 PIL 回退) ---

def _load_image_pygame(path, use_alpha=True):
    """安全加载图片，pygame 失败时回退 PIL。"""
    if not path or not os.path.exists(path):
        return None
    try:
        img = pygame.image.load(path)
        return img.convert_alpha() if use_alpha else img.convert()
    except Exception:
        pass
    try:
        from PIL import Image
        pil_img = Image.open(path)
        if pil_img.mode != "RGBA":
            pil_img = pil_img.convert("RGBA")
        raw = pil_img.tobytes()
        surf = pygame.image.fromstring(raw, pil_img.size, "RGBA")
        return surf.convert_alpha() if use_alpha else surf
    except Exception:
        return None


# --- PIL 字体回退 (pygame 2.6.1 在 Python 3.14 上 font 模块不可用) ---

class _PILFont:
    """用 PIL 渲染字体的 pygame.font.Font 兼容替代品。"""

    def __init__(self, font_path, size):
        from PIL import ImageFont
        if font_path is None:
            font_path = _get_default_font_path()
        try:
            self._pil_font = ImageFont.truetype(font_path, size)
        except Exception:
            self._pil_font = ImageFont.load_default()
        self._font_size = size

    def render(self, text, antialias, color, bg=None):
        """兼容 pygame.font.Font.render 的接口。返回 pygame Surface。"""
        from PIL import Image, ImageDraw

        if len(color) >= 4:
            fg = tuple(color[:4])
        else:
            fg = tuple(color[:3])

        if bg and len(bg) >= 4:
            bg_c = tuple(bg[:4])
        elif bg:
            bg_c = tuple(bg[:3])
        else:
            bg_c = None

        bbox = self._pil_font.getbbox(text or " ")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if tw <= 0 or th <= 0:
            tw, th = 1, self._font_size

        pad = 2
        img_w, img_h = tw + pad * 2, th + pad * 2

        if bg_c:
            img = Image.new("RGBA", (img_w, img_h), bg_c)
        else:
            img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))

        draw = ImageDraw.Draw(img)
        draw.text((pad - bbox[0], pad - bbox[1]), text, font=self._pil_font, fill=fg)

        raw = img.tobytes()
        return pygame.image.fromstring(raw, (img_w, img_h), "RGBA")

    def size(self, text):
        """兼容 pygame.font.Font.size 的接口。"""
        bbox = self._pil_font.getbbox(text or " ")
        return (bbox[2] - bbox[0] + 4, bbox[3] - bbox[1] + 4)


class _PILSysFont(_PILFont):
    """系统字体的 PIL 替代品（使用默认字体路径）。"""
    def __init__(self, name, size):
        # 忽略 name，使用项目自带的字体
        super().__init__(_get_default_font_path(), size)


def _get_default_font_path():
    """获取默认字体路径。"""
    candidates = [
        os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.abspath("."), "SourceHanSansCN-Bold.otf"),
        os.path.join(getattr(sys, '_MEIPASS', os.path.abspath(".")), "SourceHanSansCN-Bold.otf"),
        os.path.join(os.path.abspath("."), "SourceHanSansCN-Bold.otf"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return "SourceHanSansCN-Bold.otf"


# 暴露给外部使用的 Font 类——优先 pygame.font.Font，不可用时回退 PIL
Font = None
SysFont = None

try:
    if os.name == 'nt':
        ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

config = {}
history_data = {}
show_fps = False
KEY_MAP = {}
clock = None

# 皮肤系统
active_skin_name = None       # 当前选中的皮肤名称 (None = 默认皮肤)
skin_assets = None            # 加载后的皮肤资源 dict
key_pressed_state = [False, False, False, False]  # 四轨按键按下状态

# 音频系统可用性标志
mixer_available = False

SCREEN_WIDTH = 400
SCREEN_HEIGHT = 600
screen = None
real_screen = None
current_w = 400
current_h = 600

# 逻辑显示尺寸（GPU 全屏模式下使用）
# 在 GPU 全屏模式下，real_screen 的尺寸为 (logical_w, SCREEN_HEIGHT)，
# 其中 logical_w 根据屏幕宽高比计算，使得 SCALED 缩放后无 letterbox 黑边
logical_w = 400
logical_h = 600

_cached_scaled_surf = None
_cached_scaled_size = (0, 0)
use_gpu_scale = False

# 真实屏幕背景封面（显示在两侧"黑边"区域）
real_bg_surf = None

# 背景脏标记：显示模式切换后设为 True，主菜单检测到后重新加载封面
bg_dirty = False

# 最后一次成功加载的封面信息（用于显示模式切换后自动恢复背景）
_last_bg_map_path = None
_last_bg_map_data = None

font = None
small_font = None


def load_history():
    global history_data
    history_path = "history.json"
    if not os.path.exists(history_path):
        history_data = {}
        save_history()
    else:
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history_data = json.load(f)
        except:
            history_data = {}

def save_history():
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump(history_data, f, indent=4)

def load_config():
    load_history()
    global config, active_skin_name
    config_path = "config.json"
    if not os.path.exists(config_path):
        default_config = {
            "scroll_speed": 24,
            "global_offset": 0,
            "key_bindings": ["d", "f", "j", "k"],
            "window_width": 1920,
            "window_height": 1080,
            "fullscreen": False,
            "active_skin": "",
            "hit_position": 500,
            "od": 5.0
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4)
        config = default_config
    else:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    # 加载皮肤
    skin_name = config.get("active_skin", "")
    if skin_name:
        active_skin_name = skin_name
        load_active_skin()

def save_config():
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

def update_key_map():
    global KEY_MAP
    KEY_MAP.clear()
    bindings = config.get("key_bindings", ["d", "f", "j", "k"])
    for i, key_str in enumerate(bindings):
        key_code = None
        # 尝试作为整数键码
        try:
            key_code = int(key_str)
        except (ValueError, TypeError):
            pass
        # 尝试作为 pygame.K_xxx 常量名
        if key_code is None and hasattr(pygame, f"K_{key_str}"):
            key_code = getattr(pygame, f"K_{key_str}")
        # 也尝试大写
        if key_code is None and hasattr(pygame, f"K_{key_str.upper()}"):
            key_code = getattr(pygame, f"K_{key_str.upper()}")

        if key_code is not None:
            KEY_MAP[key_code] = i

def set_display_mode():
    global real_screen, current_w, current_h, screen, SCREEN_WIDTH, SCREEN_HEIGHT
    global use_gpu_scale, real_bg_surf, logical_w, logical_h

    # 标记背景需要重新加载
    global bg_dirty
    bg_dirty = True

    if real_screen is not None:
        pygame.display.quit()
        pygame.display.init()
        pygame.display.set_caption("4K Rhythm Game")

    # 重置背景
    real_bg_surf = None

    if config.get("fullscreen", False):
        # === GPU 硬件加速全屏模式 ===
        use_gpu_scale = True
        info = pygame.display.Info()
        current_w = info.current_w
        current_h = info.current_h

        # 关键计算：逻辑显示尺寸，高度保持 SCREEN_HEIGHT(600)，
        # 宽度按屏幕比例扩展，使得 SCALED 缩放后无 letterbox 黑边
        # 例如：16:9 屏幕 → logical_w = 600 * 16/9 ≈ 1067
        screen_aspect = current_w / current_h
        logical_w = int(SCREEN_HEIGHT * screen_aspect)
        logical_h = SCREEN_HEIGHT
        # 安全保护：确保逻辑显示区域至少能够容纳 400x600 的游戏画面
        #（竖屏显示器上宽度可能不足，此时改为以宽度为基准计算高度）
        if logical_w < SCREEN_WIDTH:
            logical_w = SCREEN_WIDTH
            logical_h = int(SCREEN_WIDTH / screen_aspect)

        real_screen = pygame.display.set_mode(
            (logical_w, logical_h),
            pygame.FULLSCREEN | pygame.SCALED | pygame.DOUBLEBUF
        )
    else:
        # === CPU 缩放窗口模式 ===
        use_gpu_scale = False
        logical_w = SCREEN_WIDTH
        logical_h = SCREEN_HEIGHT
        current_w = config.get("window_width", 400)
        current_h = config.get("window_height", 600)
        flags = pygame.DOUBLEBUF
        info = pygame.display.Info()
        if current_w == info.current_w and current_h == info.current_h:
            flags |= pygame.NOFRAME
        real_screen = pygame.display.set_mode((current_w, current_h), flags)

    pygame.key.stop_text_input()

    # 如果之前成功加载过封面，在显示模式切换后自动恢复
    if _last_bg_map_path is not None and _last_bg_map_data is not None:
        set_real_background_from_original(_last_bg_map_path, _last_bg_map_data)

def set_real_background_from_original(map_path, map_data):
    """从原始封面图片直接 cover 填充至背景层。

    在 GPU 全屏模式下，填充至 (logical_w, SCREEN_HEIGHT) 逻辑显示区域，
    使得两侧"黑边"也能显示封面。
    在窗口 CPU 模式下，填充至 (current_w, current_h) 物理窗口。
    加载失败或 bg 为空时自动清除背景。
    """
    global real_bg_surf, _last_bg_map_path, _last_bg_map_data
    bg_name = map_data.get("meta", {}).get("bg", "")
    if not bg_name:
        real_bg_surf = None
        return

    bg_path = os.path.abspath(os.path.join(os.path.dirname(map_path), bg_name))
    if not os.path.exists(bg_path):
        real_bg_surf = None
        return

    try:
        img = _load_image_pygame(bg_path, use_alpha=False)
        img_w, img_h = img.get_size()

        if use_gpu_scale:
            # GPU 模式：封面覆盖整个逻辑显示区域（无黑边）
            target_w = logical_w
            target_h = logical_h
        else:
            # CPU 模式（窗口）：封面覆盖整个物理窗口
            target_w = current_w
            target_h = current_h

        # cover 模式：等比缩放至填满目标区域，多余部分居中裁剪
        scale = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        scaled = pygame.transform.smoothscale(img, (new_w, new_h))

        crop_x = (new_w - target_w) // 2
        crop_y = (new_h - target_h) // 2
        if crop_x == 0 and crop_y == 0:
            real_bg_surf = scaled
        else:
            real_bg_surf = scaled.subsurface((crop_x, crop_y, target_w, target_h)).copy()

        # 缓存成功加载的封面信息，用于显示模式切换后自动恢复
        _last_bg_map_path = map_path
        _last_bg_map_data = map_data
    except:
        real_bg_surf = None

def clear_real_background():
    """清除背景封面（同时清除缓存，防止 set_display_mode 自动恢复）"""
    global real_bg_surf, _last_bg_map_path, _last_bg_map_data
    real_bg_surf = None
    _last_bg_map_path = None
    _last_bg_map_data = None

def update_display():
    global real_screen, current_w, current_h, screen, SCREEN_WIDTH, SCREEN_HEIGHT
    global _cached_scaled_surf, _cached_scaled_size, use_gpu_scale, real_bg_surf, logical_w

    if use_gpu_scale:
        # === GPU 硬件加速渲染路径 ===
        # pygame.SCALED 自动将 (logical_w, logical_h) GPU 缩放至全屏
        # 由于 logical_w/logical_h 与屏幕同比例，SDL2 不会添加 letterbox 黑边
        # 1) 封面作为底层背景填入整个逻辑显示区域
        if real_bg_surf is not None:
            real_screen.blit(real_bg_surf, (0, 0))
        else:
            real_screen.fill((0, 0, 0))

        # 2) 将 400x600 的游戏画面居中叠加在逻辑显示区域上
        # 两侧多出的区域（原黑边区）显示封面背景
        x_offset = (logical_w - SCREEN_WIDTH) // 2
        y_offset = (logical_h - SCREEN_HEIGHT) // 2
        real_screen.blit(screen, (x_offset, y_offset))
        pygame.display.flip()
        return

    # === CPU 缩放模式（窗口模式） ===
    if real_bg_surf is not None:
        real_screen.blit(real_bg_surf, (0, 0))
    else:
        real_screen.fill((0, 0, 0))

    # 手动缩放游戏画面到窗口中心
    scale_w = current_w / SCREEN_WIDTH
    scale_h = current_h / SCREEN_HEIGHT
    scale = min(scale_w, scale_h)
    new_w = int(SCREEN_WIDTH * scale)
    new_h = int(SCREEN_HEIGHT * scale)

    if _cached_scaled_size != (new_w, new_h):
        _cached_scaled_size = (new_w, new_h)
        _cached_scaled_surf = pygame.Surface((new_w, new_h))

    pygame.transform.scale(screen, (new_w, new_h), _cached_scaled_surf)

    x_offset = (current_w - new_w) // 2
    y_offset = (current_h - new_h) // 2
    real_screen.blit(_cached_scaled_surf, (x_offset, y_offset))
    pygame.display.flip()

def init_globals():
    global screen, clock, font, small_font, tiny_font, mixer_available
    pygame.init()

    # 音频系统：优先使用 BASS，失败则尝试 pygame.mixer，都不行则静音
    mixer_available = False
    try:
        import bass_audio
        if bass_audio.init():
            mixer_available = True
            print("[Info] 使用 BASS 音频引擎")
    except Exception:
        pass

    if not mixer_available:
        try:
            pygame.mixer.init()
            mixer_available = True
            print("[Info] 使用 pygame.mixer 音频引擎")
        except Exception:
            print("[Warning] 无音频引擎可用，游戏将在静音模式下运行")

    load_config()
    load_history()
    screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    set_display_mode()
    pygame.key.stop_text_input()
    pygame.display.set_caption("4K Rhythm Game")
    clock = pygame.time.Clock()

    # --- 字体加载（pygame.font → PIL 回退） ---
    global Font, SysFont

    # 尝试使用 pygame 原生字体
    try:
        from pygame.font import Font as _NativeFont
        Font = _NativeFont
        from pygame.sysfont import SysFont as _NativeSysFont
        SysFont = _NativeSysFont
        print("[Info] 使用 pygame 原生字体渲染")
    except ImportError:
        Font = _PILFont
        SysFont = _PILSysFont
        print("[Info] pygame.font 不可用，使用 PIL 字体渲染")

    font_path = _get_default_font_path()

    try:
        font = Font(font_path, 36)
        small_font = Font(font_path, 24)
        tiny_font = Font(font_path, 18)
    except Exception as e:
        print(f"字体加载失败: {e}, 尝试使用系统缺省")
        try:
            font = SysFont("simhei", 36)
            small_font = SysFont("simhei", 24)
            tiny_font = SysFont("simhei", 18)
        except Exception:
            font = Font(None, 36) if Font else None
            small_font = Font(None, 24) if Font else None
            tiny_font = Font(None, 18) if Font else None

    update_key_map()

def load_fill_bg(map_path, map_data):
    """加载封面图片并将其缩放填充至整个 400x600 屏幕（cover 模式，居中裁剪）"""
    bg_name = map_data.get("meta", {}).get("bg", "")
    if not bg_name:
        return None

    bg_path = os.path.abspath(os.path.join(os.path.dirname(map_path), bg_name))
    if not os.path.exists(bg_path):
        return None

    try:
        img = _load_image_pygame(bg_path, use_alpha=False)
        img_w, img_h = img.get_size()
        scale = max(SCREEN_WIDTH / img_w, SCREEN_HEIGHT / img_h)
        new_w, new_h = int(img_w * scale), int(img_h * scale)
        scaled = pygame.transform.smoothscale(img, (new_w, new_h))
        crop_x = (new_w - SCREEN_WIDTH) // 2
        crop_y = (new_h - SCREEN_HEIGHT) // 2
        if crop_x == 0 and crop_y == 0:
            return scaled
        cropped = scaled.subsurface((crop_x, crop_y, SCREEN_WIDTH, SCREEN_HEIGHT))
        return cropped.copy()
    except Exception as e:
        print(f"Failed to load background image {bg_path}: {e}")
        return None

def load_bg_image(map_path, map_data):
    """加载封面缩略图（用于结算/预览界面展示）"""
    bg_name = map_data.get("meta", {}).get("bg", "")
    if not bg_name:
        return None

    bg_path = os.path.abspath(os.path.join(os.path.dirname(map_path), bg_name))
    if not os.path.exists(bg_path):
        return None

    try:
        img = _load_image_pygame(bg_path, use_alpha=False)
        img_w, img_h = img.get_size()
        max_w, max_h = 280, 160
        scale = min(max_w / img_w, max_h / img_h)
        new_w, new_h = int(img_w * scale), int(img_h * scale)
        thumb_surf = pygame.transform.smoothscale(img, (new_w, new_h))
        return thumb_surf
    except Exception as e:
        print(f"Failed to load background image {bg_path}: {e}")
        return None

# --- 皮肤管理 ---

def load_active_skin():
    """加载当前选中的皮肤资源。"""
    global skin_assets, active_skin_name
    skin_assets = None

    if not active_skin_name:
        return

    try:
        import skin_importer
        skin_assets = skin_importer.load_skin_assets(active_skin_name)
        if skin_assets is None:
            print(f"[Skin] 加载皮肤失败: {active_skin_name}，回退到默认")
            active_skin_name = None
    except Exception as e:
        print(f"[Skin] 加载皮肤异常: {e}")
        active_skin_name = None
        skin_assets = None


def unload_skin():
    """卸载当前皮肤，回到默认样式。"""
    global skin_assets, active_skin_name
    skin_assets = None
    active_skin_name = None


# --- 统一音频接口 (BASS / pygame.mixer) ---

_bass_module = None


def _bass_available():
    global _bass_module
    if _bass_module is None:
        try:
            import bass_audio
            _bass_module = bass_audio if bass_audio.is_available() else False
        except Exception:
            _bass_module = False
    return _bass_module is not False


def audio_load(path):
    """加载音频文件。"""
    if mixer_available:
        if _bass_available():
            return _bass_module.music_load(path)
        else:
            try:
                pygame.mixer.music.load(path)
                return True
            except Exception:
                return False
    return False


def audio_play():
    """开始/恢复播放。"""
    if mixer_available:
        if _bass_available():
            _bass_module.music_play()
        else:
            try:
                pygame.mixer.music.play()
            except Exception:
                pass


def audio_pause():
    """暂停播放。"""
    if mixer_available:
        if _bass_available():
            _bass_module.music_pause()
        else:
            try:
                pygame.mixer.music.pause()
            except Exception:
                pass


def audio_unpause():
    """恢复播放（BASS 与 play 相同）。"""
    if mixer_available:
        if _bass_available():
            _bass_module.music_play()
        else:
            try:
                pygame.mixer.music.unpause()
            except Exception:
                pass


def audio_stop():
    """停止播放。"""
    if mixer_available:
        if _bass_available():
            _bass_module.music_stop()
        else:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass


def draw_marquee_text(surface, text, font, color, center_x, y, max_width):
    if not text:
        return
    text_surf = font.render(text, True, color)
    text_w = text_surf.get_width()

    if text_w <= max_width:
        x_pos = center_x - text_w // 2
        surface.blit(text_surf, (x_pos, y))
    else:
        speed = 60.0
        gap = 100
        total_w = text_w + gap

        import pygame
        ms = pygame.time.get_ticks()

        cycle_duration = (total_w / speed * 1000) + 1500
        current_time_in_cycle = ms % cycle_duration

        if current_time_in_cycle < 1500:
            offset = 0
        else:
            offset = ((current_time_in_cycle - 1500) / 1000.0) * speed

        x_start = center_x - max_width // 2
        clip_rect = pygame.Rect(x_start, y, max_width, text_surf.get_height())
        old_clip = surface.get_clip()

        if old_clip:
            clip_rect = clip_rect.clip(old_clip)

        surface.set_clip(clip_rect)

        draw_x = x_start - offset
        surface.blit(text_surf, (draw_x, y))
        if draw_x + text_w < x_start + max_width:
            surface.blit(text_surf, (draw_x + total_w, y))

        surface.set_clip(old_clip)
