import os
import subprocess
import ctypes
import wave
import pygame
import atexit

# 动态获取当前目录并定义库名和源文件
DIR_PATH = os.path.dirname(os.path.abspath(__file__))
LIB_PATH = os.path.join(DIR_PATH, "libsonic.so" if os.name != 'nt' else "sonic.dll")
C_PATH_C = os.path.join(DIR_PATH, "sonic.c")

# 垃圾文件自动清理机制
def cleanup_temp_wavs():
    """ 自动遍历并删除运行中产生的庞大 .wav 变速缓存 """
    # 退出前必须强制卸载 pygame 的混音器，否则 Windows 下文件会被占用导致删不掉
    try:
        pygame.mixer.music.unload()
    except Exception:
        pass
    try:
        pygame.mixer.quit()
    except Exception:
        pass
        
    # PyInstaller打包后，DIR_PATH 是临时解压目录，而临时歌曲通常在当前工作目录(执行EXE的目录)
    # 所以要扫描 os.getcwd() 
    search_dir = os.getcwd()
    for root, _, files in os.walk(search_dir):
        for f in files:
            # 匹配 editor.py 和 gameplay.py 生成的临时变速大文件
            if (f.startswith(".temp_") or f.startswith("temp_")) and f.endswith(".wav"):
                try:
                    os.remove(os.path.join(root, f))
                    print(f"Cleared cache: {f}")
                except Exception as e:
                    print(f"Failed to clear {f}: {e}")

atexit.register(cleanup_temp_wavs)

# 如果缺少原生库，尝试静默编译它 (Windows下假设自带或可调用gcc)
if not os.path.exists(LIB_PATH) and os.path.exists(C_PATH_C):
    print("Compiling sonic C extension for sonic-python...")
    try:
        if os.name == 'nt':
            subprocess.run(["gcc", "-shared", "-fPIC", "-O3", "-o", LIB_PATH, C_PATH_C])
        else:
            subprocess.run(["gcc", "-shared", "-fPIC", "-O3", "-o", LIB_PATH, C_PATH_C])
    except Exception as e:
        print("Failed to compile sonic:", e)

# 加载 C 动态链接库并通过 ctypes 绑定接口
try:
    libsonic = ctypes.cdll.LoadLibrary(LIB_PATH)
    
    # 按照 sonic.h 绑定接口参数类型
    libsonic.sonicCreateStream.restype = ctypes.c_void_p
    libsonic.sonicCreateStream.argtypes = [ctypes.c_int, ctypes.c_int]
    
    libsonic.sonicSetSpeed.restype = None
    libsonic.sonicSetSpeed.argtypes = [ctypes.c_void_p, ctypes.c_float]
    
    libsonic.sonicWriteShortToStream.restype = ctypes.c_int
    libsonic.sonicWriteShortToStream.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_short), ctypes.c_int]
    
    libsonic.sonicReadShortFromStream.restype = ctypes.c_int
    libsonic.sonicReadShortFromStream.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_short), ctypes.c_int]
    
    libsonic.sonicFlushStream.restype = ctypes.c_int
    libsonic.sonicFlushStream.argtypes = [ctypes.c_void_p]
    
    libsonic.sonicDestroyStream.restype = None
    libsonic.sonicDestroyStream.argtypes = [ctypes.c_void_p]

    def process_audio(raw_bytes, speed, samplerate, channels):
        if speed == 1.0:
            return raw_bytes
            
        stream = libsonic.sonicCreateStream(samplerate, channels)
        libsonic.sonicSetSpeed(stream, speed)
        
        # 认为按标准 Pygame 设置，取得 16-bit PCM 数据
        num_frames = len(raw_bytes) // (2 * channels)
        arr_type = ctypes.c_short * (len(raw_bytes) // 2)
        in_buffer = arr_type.from_buffer_copy(raw_bytes)
        
        libsonic.sonicWriteShortToStream(stream, in_buffer, num_frames)
        libsonic.sonicFlushStream(stream)
        
        # 提供足够的缓存空间接收结果
        out_frames = int(num_frames / speed * 1.5) + 4096 
        out_buffer = (ctypes.c_short * (out_frames * channels))()
        
        read_frames = libsonic.sonicReadShortFromStream(stream, out_buffer, out_frames)
        libsonic.sonicDestroyStream(stream)
        
        return bytearray(out_buffer)[:read_frames * channels * 2]

except Exception as e:
    print(f"Failed to load libsonic via ctypes: {e}")
    def process_audio(raw_bytes, speed, samplerate, channels):
        print("Fallback directly bypassing sonic")
        return raw_bytes

def write_wav(path, raw_bytes, samplerate, channels):
    with wave.open(path, 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2) # 16 bit
        wav.setframerate(samplerate)
        wav.writeframes(raw_bytes)

def generate_stretched_audio(in_file, out_wav_file, speed):
    """生成变速音频。成功返回 True，失败返回 False。"""
    if speed == 1.0:
        return False

    # 尝试 pygame.mixer 方式
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        freq, fmt, channels = pygame.mixer.get_init()
        snd = pygame.mixer.Sound(in_file)
        raw_data = snd.get_raw()
        stretched_bytes = process_audio(raw_data, speed, freq, channels)
        write_wav(out_wav_file, stretched_bytes, freq, channels)
        return True
    except Exception:
        pass

    # 回退：尝试用 wave 直接读 WAV 文件
    try:
        import wave as wav_mod
        with wav_mod.open(in_file, 'rb') as wf:
            freq = wf.getframerate()
            channels = wf.getnchannels()
            raw_data = wf.readframes(wf.getnframes())
        stretched_bytes = process_audio(raw_data, speed, freq, channels)
        write_wav(out_wav_file, stretched_bytes, freq, channels)
        return True
    except Exception:
        pass

    # 回退：尝试 BASS 解码
    try:
        import bass_audio
        if bass_audio.is_available():
            raw_data, freq, channels = _read_audio_bass(in_file)
            if raw_data:
                stretched_bytes = process_audio(raw_data, speed, freq, channels)
                write_wav(out_wav_file, stretched_bytes, freq, channels)
                return True
    except Exception:
        pass

    print(f"[sonic] 无法处理变速音频: {in_file}，将使用原始速度")
    return False


def _read_audio_bass(file_path):
    """使用 BASS 解码音频文件，返回 (pcm_bytes, sample_rate, channels)。"""
    import ctypes
    import bass_audio
    bass = bass_audio._bass
    if not bass or not bass_audio._initialized:
        return None, 0, 0

    BASS_STREAM_DECODE = 0x200000
    BASS_POS_BYTE = 0

    path_bytes = file_path.encode("utf-8")
    handle = bass.BASS_StreamCreateFile(0, path_bytes, 0, 0, BASS_STREAM_DECODE)
    if handle == 0:
        return None, 0, 0

    # 获取流信息
    class BASS_CHANNELINFO(ctypes.Structure):
        _fields_ = [("freq", ctypes.c_uint), ("chans", ctypes.c_uint),
                    ("flags", ctypes.c_uint), ("ctype", ctypes.c_uint),
                    ("origres", ctypes.c_uint), ("plugin", ctypes.c_uint),
                    ("sample", ctypes.c_uint), ("filename", ctypes.c_char_p)]

    info = BASS_CHANNELINFO()
    bass.BASS_ChannelGetInfo.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    bass.BASS_ChannelGetInfo.restype = ctypes.c_int
    bass.BASS_ChannelGetInfo(handle, ctypes.byref(info))

    bass.BASS_ChannelGetLength.argtypes = [ctypes.c_uint, ctypes.c_uint]
    bass.BASS_ChannelGetLength.restype = ctypes.c_uint64
    length = bass.BASS_ChannelGetLength(handle, BASS_POS_BYTE)

    out_buf = (ctypes.c_char * length)()
    bass.BASS_ChannelGetData.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    bass.BASS_ChannelGetData.restype = ctypes.c_uint
    read = bass.BASS_ChannelGetData(handle, out_buf, length)

    bass.BASS_StreamFree(handle)

    if read > 0:
        return bytes(out_buf[:read]), info.freq, info.chans
    return None, 0, 0
