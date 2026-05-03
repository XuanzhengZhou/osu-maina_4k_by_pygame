"""BASS 音频库 Python 封装 —— 替代 pygame.mixer。

通过 ctypes 调用 libbass.dylib，提供基本的音频播放控制。
"""

import ctypes
import os
import sys

# --- 常量 ---
BASS_ACTIVE_STOPPED = 0
BASS_ACTIVE_PLAYING = 1
BASS_ACTIVE_STALLED = 2
BASS_ACTIVE_PAUSED = 3

BASS_POS_BYTE = 0

BASS_STREAM_AUTOFREE = 0x40000
BASS_UNICODE = 0x80000000

BASS_ERROR_INIT = 8
BASS_ERROR_FILEOPEN = 2
BASS_ERROR_HANDLE = 5

# --- 加载 BASS 库 ---

_bass = None
_initialized = False


def _find_bass_lib():
    """根据平台查找 BASS 动态库。"""
    base = os.path.dirname(os.path.abspath(__file__))

    if sys.platform == "darwin":
        lib_name = "libbass.dylib"
    elif sys.platform == "win32":
        lib_name = "bass.dll"
    else:
        lib_name = "libbass.so"

    candidates = [
        os.path.join(base, "libs", lib_name),
        os.path.join(base, lib_name),  # 兼容旧布局
    ]

    # 打包后
    if getattr(sys, 'frozen', False):
        candidates.insert(0, os.path.join(os.path.dirname(sys.executable), lib_name))
        candidates.insert(1, os.path.join(sys._MEIPASS, lib_name))

    # Linux: 尝试 libs/linux/ 下的架构子文件
    if sys.platform not in ("darwin", "win32"):
        import platform
        arch_map = {"x86_64": "libbass.so", "AMD64": "libbass.so", "aarch64": "libbass_aarch64.so",
                    "armv7l": "libbass_armhf.so", "i686": "libbass_x86.so"}
        arch_lib = arch_map.get(platform.machine(), "libbass.so")
        candidates.append(os.path.join(base, "libs", "linux", arch_lib))

    for p in candidates:
        if os.path.exists(p):
            return p
    print(f"[BASS] 未找到 {lib_name}，搜索路径: {candidates}")
    return None


def init():
    """初始化 BASS 音频系统。返回 True 成功，False 失败。"""
    global _bass, _initialized

    if _initialized:
        return True

    lib_path = _find_bass_lib()
    if not lib_path:
        print("[BASS] 未找到 libbass.dylib，将在静音模式下运行")
        return False

    try:
        _bass = ctypes.CDLL(lib_path)
    except Exception as e:
        print(f"[BASS] 加载失败: {e}")
        return False

    # 设置函数签名
    _bass.BASS_Init.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    _bass.BASS_Init.restype = ctypes.c_int

    _bass.BASS_Free.restype = ctypes.c_int

    _bass.BASS_StreamCreateFile.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint]
    _bass.BASS_StreamCreateFile.restype = ctypes.c_uint

    _bass.BASS_StreamFree.argtypes = [ctypes.c_uint]
    _bass.BASS_StreamFree.restype = ctypes.c_int

    _bass.BASS_ChannelPlay.argtypes = [ctypes.c_uint, ctypes.c_int]
    _bass.BASS_ChannelPlay.restype = ctypes.c_int

    _bass.BASS_ChannelStop.argtypes = [ctypes.c_uint]
    _bass.BASS_ChannelStop.restype = ctypes.c_int

    _bass.BASS_ChannelPause.argtypes = [ctypes.c_uint]
    _bass.BASS_ChannelPause.restype = ctypes.c_int

    _bass.BASS_ChannelIsActive.argtypes = [ctypes.c_uint]
    _bass.BASS_ChannelIsActive.restype = ctypes.c_uint

    _bass.BASS_ChannelSetPosition.argtypes = [ctypes.c_uint, ctypes.c_uint64, ctypes.c_uint]
    _bass.BASS_ChannelSetPosition.restype = ctypes.c_int

    _bass.BASS_ErrorGetCode.restype = ctypes.c_int

    _bass.BASS_SetConfig.argtypes = [ctypes.c_uint, ctypes.c_uint]
    _bass.BASS_SetConfig.restype = ctypes.c_int

    # 初始化 BASS（默认设备，44.1kHz，无特殊标志）
    try:
        result = _bass.BASS_Init(-1, 44100, 0, 0, None)
        if not result:
            err = _bass.BASS_ErrorGetCode()
            print(f"[BASS] 初始化失败，错误码: {err}")
            return False
    except Exception as e:
        print(f"[BASS] 初始化异常: {e}")
        return False

    _initialized = True
    print("[BASS] 音频系统初始化成功")
    return True


def free():
    """释放 BASS 资源。"""
    global _bass, _initialized
    if _bass and _initialized:
        _bass.BASS_Free()
        _initialized = False
        _bass = None


class BassStream:
    """BASS 音频流封装，兼容 pygame.mixer.music 接口风格。"""

    def __init__(self):
        self._handle = 0  # BASS stream handle

    def load(self, file_path):
        """加载音频文件。返回 True 成功。"""
        self.unload()

        if not _initialized:
            return False

        path_bytes = file_path.encode("utf-8") if isinstance(file_path, str) else file_path
        handle = _bass.BASS_StreamCreateFile(0, path_bytes, 0, 0, BASS_STREAM_AUTOFREE)
        if handle == 0:
            err = _bass.BASS_ErrorGetCode()
            print(f"[BASS] 无法加载 {file_path}: 错误码 {err}")
            return False

        self._handle = handle
        return True

    def play(self):
        """开始/恢复播放。"""
        if self._handle and _initialized:
            _bass.BASS_ChannelPlay(self._handle, 0)

    def pause(self):
        """暂停播放。"""
        if self._handle and _initialized:
            _bass.BASS_ChannelPause(self._handle)

    def stop(self):
        """停止并释放。"""
        if self._handle and _initialized:
            _bass.BASS_ChannelStop(self._handle)
            self._handle = 0

    def unload(self):
        """释放音频流。"""
        self.stop()

    def is_playing(self):
        """检查是否正在播放。"""
        if self._handle and _initialized:
            return _bass.BASS_ChannelIsActive(self._handle) == BASS_ACTIVE_PLAYING
        return False

    def is_paused(self):
        """检查是否已暂停。"""
        if self._handle and _initialized:
            return _bass.BASS_ChannelIsActive(self._handle) == BASS_ACTIVE_PAUSED
        return False

    def set_pos_ms(self, ms):
        """设置播放位置（毫秒）。"""
        if self._handle and _initialized:
            # BASS 使用字节位置，但对于流没有直接的毫秒设置
            pass

    def get_pos_ms(self):
        """获取播放位置（毫秒），用于同步。"""
        if not self._handle or not _initialized:
            return 0
        # 使用 BASS_ChannelGetPosition + BASS_POS_BYTE
        _bass.BASS_ChannelGetPosition.argtypes = [ctypes.c_uint, ctypes.c_uint]
        _bass.BASS_ChannelGetPosition.restype = ctypes.c_uint64
        pos_bytes = _bass.BASS_ChannelGetPosition(self._handle, BASS_POS_BYTE)
        # 近似转换：44100 Hz stereo 16-bit → bytes/ms ≈ 176.4
        return int(pos_bytes / 176.4)


# 全局单例，模拟 pygame.mixer.music 模块
_stream = BassStream()


def music_load(path):
    """加载音乐文件。"""
    return _stream.load(path)


def music_play():
    """播放音乐。"""
    _stream.play()


def music_pause():
    """暂停音乐。"""
    _stream.pause()


def music_stop():
    """停止音乐。"""
    _stream.stop()


def music_unload():
    """卸载音乐。"""
    _stream.unload()


def is_available():
    """检查 BASS 是否可用。"""
    return _initialized
