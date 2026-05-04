"""回放系统：录制、保存、加载 osu! 兼容格式的回放文件 (.osr)"""

import json
import os
import gzip
import time

# --- 数据结构 ---

class ReplayFrame:
    """单帧回放数据。"""
    def __init__(self, time_ms, pressed_keys):
        self.time_ms = int(time_ms)
        self.pressed_keys = pressed_keys  # int, 4轨位掩码: bit0=轨0, bit1=轨1...

    def to_dict(self):
        return {"t": self.time_ms, "k": self.pressed_keys}

    @classmethod
    def from_dict(cls, d):
        return cls(d["t"], d["k"])


class ReplayJudgment:
    """单次判定记录。"""
    def __init__(self, time_ms, lane, judgment_type, offset_ms):
        self.time_ms = int(time_ms)
        self.lane = lane
        self.type = judgment_type  # "PERFECT", "GREAT", etc.
        self.offset_ms = int(offset_ms)

    def to_dict(self):
        return {"t": self.time_ms, "l": self.lane, "j": self.type, "o": self.offset_ms}

    @classmethod
    def from_dict(cls, d):
        return cls(d["t"], d["l"], d["j"], d["o"])


class ReplayData:
    """完整回放数据。"""

    def __init__(self, map_path="", song_rate=1.0, od=5.0, scroll_speed=24, hit_position=500):
        self.map_path = map_path
        self.song_rate = song_rate
        self.od = od
        self.scroll_speed = scroll_speed
        self.hit_position = hit_position
        self.modified = False  # 是否有 mod 修改
        self.mirror_mode = False
        self.frames = []       # list of ReplayFrame
        self.judgments = []    # list of ReplayJudgment
        self.total_notes = 0
        self.max_combo = 0
        self.counts = {  # 判定统计
            "perfect": 0, "great": 0, "good": 0,
            "ok": 0, "meh": 0, "miss": 0,
        }
        self.score = 0
        self.acc = 0.0
        self.date = ""
        self.player_name = "Player"

    def add_frame(self, time_ms, pressed_keys):
        self.frames.append(ReplayFrame(time_ms, pressed_keys))

    def add_judgment(self, time_ms, lane, judgment_type, offset_ms):
        self.judgments.append(ReplayJudgment(time_ms, lane, judgment_type, offset_ms))

    def set_result(self, total_notes, max_combo, counts, score, acc):
        self.total_notes = total_notes
        self.max_combo = max_combo
        self.counts = counts.copy()
        self.score = score
        self.acc = acc
        self.date = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self):
        return {
            "version": 1,
            "map_path": self.map_path,
            "song_rate": self.song_rate,
            "od": self.od,
            "scroll_speed": self.scroll_speed,
            "hit_position": self.hit_position,
            "modified": self.modified,
            "mirror_mode": self.mirror_mode,
            "total_notes": self.total_notes,
            "max_combo": self.max_combo,
            "counts": self.counts,
            "score": self.score,
            "acc": self.acc,
            "date": self.date,
            "player_name": self.player_name,
            "frames": [f.to_dict() for f in self.frames],
            "judgments": [j.to_dict() for j in self.judgments],
        }

    @classmethod
    def from_dict(cls, d):
        r = cls()
        r.map_path = d.get("map_path", "")
        r.song_rate = d.get("song_rate", 1.0)
        r.od = d.get("od", 5.0)
        r.scroll_speed = d.get("scroll_speed", 24)
        r.hit_position = d.get("hit_position", 500)
        r.modified = d.get("modified", False)
        r.mirror_mode = d.get("mirror_mode", False)
        r.total_notes = d.get("total_notes", 0)
        r.max_combo = d.get("max_combo", 0)
        r.counts = d.get("counts", {})
        r.score = d.get("score", 0)
        r.acc = d.get("acc", 0.0)
        r.date = d.get("date", "")
        r.player_name = d.get("player_name", "Player")
        r.frames = [ReplayFrame.from_dict(f) for f in d.get("frames", [])]
        r.judgments = [ReplayJudgment.from_dict(j) for j in d.get("judgments", [])]
        return r


# --- 保存 / 加载 ---

def save_replay(replay_data, output_path):
    """保存回放到 .osr 文件 (gzip 压缩 JSON)。"""
    d = replay_data.to_dict()
    json_str = json.dumps(d, ensure_ascii=False, indent=2)
    compressed = gzip.compress(json_str.encode("utf-8"))
    with open(output_path, "wb") as f:
        f.write(compressed)
    print(f"[Replay] 已保存: {output_path}")


def load_replay(file_path):
    """加载 .osr 文件返回 ReplayData。"""
    with open(file_path, "rb") as f:
        compressed = f.read()
    json_str = gzip.decompress(compressed).decode("utf-8")
    d = json.loads(json_str)
    return ReplayData.from_dict(d)


def get_replay_files(map_dir):
    """获取谱面目录下所有 .osr 回放文件。"""
    replays = []
    if not os.path.isdir(map_dir):
        return replays
    for f in os.listdir(map_dir):
        if f.endswith(".osr"):
            replays.append(os.path.join(map_dir, f))
    return sorted(replays, key=lambda x: os.path.getmtime(x), reverse=True)
