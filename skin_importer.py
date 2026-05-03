import os
import json
import zipfile
import shutil
import configparser
from typing import Optional


def _pil_to_pygame(pil_image):
    """将 PIL Image 转换为 pygame Surface (RGBA)。"""
    import pygame

    if pil_image.mode != "RGBA":
        pil_image = pil_image.convert("RGBA")
    raw_data = pil_image.tobytes()
    return pygame.image.fromstring(raw_data, pil_image.size, "RGBA")


def _load_image_safe(path: str):
    """安全加载图片为 pygame Surface，兼容无 SDL_image 环境。"""
    import pygame

    if not path or not os.path.exists(path):
        return None

    try:
        return pygame.image.load(path).convert_alpha()
    except Exception:
        pass

    try:
        from PIL import Image
        return _pil_to_pygame(Image.open(path))
    except Exception:
        return None

# --- 路径工具 ---

SKINS_DIR = "skins"


def _ensure_skins_dir():
    if not os.path.exists(SKINS_DIR):
        os.makedirs(SKINS_DIR)


# --- skin.ini 解析 (手动，因为 skin.ini 不是标准 INI —— 有多个同名 [Mania] section) ---


def _parse_skin_ini(ini_path: str) -> dict:
    """解析 osu! 皮肤 skin.ini，提取所有 [Mania] 段落的配置。

    返回格式:
    {
        "general": {...},
        "mania_configs": {
            4: {  # Keys 数量
                "HitPosition": 467,
                "ColumnWidth": [65, 65, 65, 65],
                "NoteImage0": "Arrownote\\diamond",
                "NoteImage0H": "Arrownote\\diamond",
                ...
            },
            ...
        }
    }
    """
    with open(ini_path, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()

    result = {"general": {}, "mania_configs": {}}
    current_section = None
    current_mania_config = None
    current_keys = None

    for raw_line in lines:
        line = raw_line.strip()

        # 跳过空行和注释
        if not line or line.startswith("//") or line.startswith("#"):
            continue

        # 去掉行内 // 注释
        if "//" in line:
            line = line.split("//")[0].strip()
        if not line:
            continue

        # section header
        if line.startswith("[") and line.endswith("]"):
            section_name = line[1:-1].strip()
            current_section = section_name
            if section_name == "Mania":
                current_mania_config = {}
                current_keys = None
            continue

        # skin.ini 使用 : 作为键值分隔符
        sep = ":"
        if sep not in line:
            # 也兼容 = 分隔符
            if "=" not in line:
                continue
            sep = "="

        key, value = line.split(sep, 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if current_section == "General":
            result["general"][key] = value
        elif current_section == "Colours":
            pass  # 我们暂时不需要颜色信息
        elif current_section == "Fonts":
            pass
        elif current_section == "Mania" and current_mania_config is not None:
            if key == "Keys":
                current_keys = int(value)
                if current_keys not in result["mania_configs"]:
                    result["mania_configs"][current_keys] = current_mania_config
                    current_mania_config["Keys"] = current_keys
                else:
                    # 重复的 Keys 段落，创建新的配置
                    current_mania_config = {}
                    current_mania_config["Keys"] = current_keys
                    result["mania_configs"][current_keys] = current_mania_config
            else:
                current_mania_config[key] = value

    return result


def _resolve_image_path(skin_root: str, image_ref: str) -> Optional[str]:
    """在皮肤目录中解析图片引用路径。

    处理:
    - "Arrownote\\diamond" → Arrownote/diamond.png
    - "mania-note1" → mania-note1.png
    - 如果找不到 .png，尝试 .jpg
    - 如果找不到，尝试在当前皮肤根目录以及子目录中模糊搜索
    """
    if not image_ref:
        return None

    # 将反斜杠转为正斜杠
    image_ref = image_ref.replace("\\", "/").replace("\\\\", "/")

    # 去除已有的扩展名
    base_ref = image_ref
    if image_ref.lower().endswith((".png", ".jpg", ".jpeg")):
        base_ref = os.path.splitext(image_ref)[0]

    # 尝试不同的路径组合
    candidates = [
        os.path.join(skin_root, base_ref + ".png"),
        os.path.join(skin_root, base_ref + ".jpg"),
        os.path.join(skin_root, base_ref + ".jpeg"),
        # 也尝试从子目录中找
        os.path.join(skin_root, os.path.basename(base_ref) + ".png"),
        os.path.join(skin_root, os.path.basename(base_ref) + ".jpg"),
    ]

    # 如果路径包含目录，也尝试从根目录的子目录找
    if "/" in base_ref:
        dir_name = os.path.dirname(base_ref)
        file_name = os.path.basename(base_ref)
        candidates.append(os.path.join(skin_root, dir_name, file_name + ".png"))
        candidates.append(os.path.join(skin_root, dir_name, file_name + ".jpg"))

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    return None


# --- 导入 .osk/.osz 文件 ---


def import_osz(osz_path: str, progress_callback=None) -> Optional[str]:
    """导入一个 osu! 皮肤压缩包 (.osk / .osz)。

    步骤:
    1. 解压到 skins/<skin_name>/
    2. 解析 skin.ini
    3. 保存解析后的配置为 skin_config.json
    4. 返回皮肤名称，失败则返回 None
    """
    _ensure_skins_dir()

    if not os.path.exists(osz_path):
        print(f"[Skin Importer] 文件不存在: {osz_path}")
        return None

    try:
        with zipfile.ZipFile(osz_path, "r") as zf:
            # 找到皮肤根目录名称 (zip 内的顶级文件夹)
            # 忽略 __MACOSX
            top_dirs = set()
            for name in zf.namelist():
                if name.startswith("__MACOSX") or name.startswith("."):
                    continue
                parts = name.split("/")
                if parts[0]:
                    top_dirs.add(parts[0])

            if not top_dirs:
                print("[Skin Importer] 压缩包中没有找到有效内容")
                return None

            # 取第一个非系统文件夹作为皮肤名称
            skin_inner_name = sorted(top_dirs)[0]

            # 目标路径
            skin_target_dir = os.path.join(SKINS_DIR, skin_inner_name)

            # 如果已存在，先删除
            if os.path.exists(skin_target_dir):
                shutil.rmtree(skin_target_dir)

            os.makedirs(skin_target_dir, exist_ok=True)

            # 解压（只解压皮肤内容，跳过 MACOSX）
            total = len([n for n in zf.namelist()
                        if not n.startswith("__MACOSX") and not n.startswith(".")])
            extracted = 0
            for name in zf.namelist():
                if name.startswith("__MACOSX") or name.startswith("."):
                    continue
                # 剥离顶级目录前缀
                parts = name.split("/")
                if parts[0] == skin_inner_name:
                    inner_path = "/".join(parts[1:])
                    if not inner_path:
                        continue  # 跳过顶级目录本身
                    target_path = os.path.join(skin_target_dir, inner_path)
                else:
                    target_path = os.path.join(skin_target_dir, name)

                if name.endswith("/"):
                    os.makedirs(target_path, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with zf.open(name) as src, open(target_path, "wb") as dst:
                        dst.write(src.read())
                    extracted += 1
                    if progress_callback:
                        progress_callback(extracted, total)

            # 解析 skin.ini
            ini_path = os.path.join(skin_target_dir, "skin.ini")
            if os.path.exists(ini_path):
                parsed = _parse_skin_ini(ini_path)

                # 保存配置
                config_out = os.path.join(skin_target_dir, "skin_config.json")
                with open(config_out, "w", encoding="utf-8") as f:
                    json.dump(parsed, f, indent=2, ensure_ascii=False)

            print(f"[Skin Importer] 成功导入皮肤: {skin_inner_name}")
            return skin_inner_name

    except zipfile.BadZipFile:
        print(f"[Skin Importer] 无效的压缩包: {osz_path}")
        return None
    except Exception as e:
        print(f"[Skin Importer] 导入失败: {e}")
        import traceback
        traceback.print_exc()
        return None


# --- 获取已安装皮肤列表 ---


def get_installed_skins() -> list:
    """返回已安装皮肤的名称列表。"""
    _ensure_skins_dir()
    skins = []
    if not os.path.exists(SKINS_DIR):
        return skins
    for name in os.listdir(SKINS_DIR):
        skin_path = os.path.join(SKINS_DIR, name)
        if os.path.isdir(skin_path) and not name.startswith("."):
            # 确认有 skin_config.json 或 skin.ini
            if os.path.exists(os.path.join(skin_path, "skin_config.json")) or \
               os.path.exists(os.path.join(skin_path, "skin.ini")):
                skins.append(name)
    return sorted(skins)


# --- 加载皮肤资源 ---


def load_skin_assets(skin_name: str) -> Optional[dict]:
    """加载指定皮肤的 4K 游玩界面资源。

    返回格式:
    {
        "name": "...",
        "config": {...},  # 4K mania 配置
        "images": {
            "note_0": Surface, "note_1": Surface, ...
            "hold_head_0": Surface, ...
            "hold_body_0": Surface, ...
            "hold_tail_0": Surface, ...
            "key_0": Surface, "key_0D": Surface, ...  # D=按下状态
            "stage_bottom": Surface,
            "stage_hint": Surface,
            "hit_300": Surface, "hit_200": Surface, "hit_100": Surface,
            "hit_50": Surface, "hit_0": Surface,
            "hit_300g": Surface,
        }
    }
    如果皮肤不存在或加载失败返回 None。
    """
    import pygame

    skin_path = os.path.join(SKINS_DIR, skin_name)
    if not os.path.isdir(skin_path):
        return None

    # 尝试加载 skin_config.json，如果没有则解析 skin.ini
    config_path = os.path.join(skin_path, "skin_config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            parsed = json.load(f)
    else:
        ini_path = os.path.join(skin_path, "skin.ini")
        if os.path.exists(ini_path):
            parsed = _parse_skin_ini(ini_path)
        else:
            return None

    mania_configs = parsed.get("mania_configs", {})
    # 获取 4K 配置
    keys_4 = mania_configs.get("4") or mania_configs.get(4)

    result = {
        "name": parsed.get("general", {}).get("Name", skin_name),
        "config": keys_4 or {},
        "images": {}
    }

    images = result["images"]
    cfg = keys_4 or {}

    # 辅助函数：加载并安全返回 Surface
    def _load_img(image_ref, default=None):
        path = _resolve_image_path(skin_path, image_ref)
        if path:
            return _load_image_safe(path) or default
        return default

    # 辅助函数：获取配置值
    def _cfg(key, default_val=None):
        return cfg.get(key, default_val)

    # --- 4 个轨道的音符图片 ---
    for lane in range(4):
        # Tap note
        note_img = _load_img(_cfg(f"NoteImage{lane}", f"mania-note{lane+1}"))
        # 如果指定路径不存在，回退到 mania-note1.png
        if note_img is None and lane > 0:
            note_img = _load_img(_cfg("NoteImage0", "mania-note1"))
        images[f"note_{lane}"] = note_img

        # Hold head
        head_img = _load_img(_cfg(f"NoteImage{lane}H", f"mania-note{lane+1}H"))
        if head_img is None:
            head_img = note_img  # 如果不存在，回退到普通note
        images[f"hold_head_{lane}"] = head_img

        # Hold body (tiled)
        body_img = _load_img(_cfg(f"NoteImage{lane}L", f"mania-note{lane+1}L"))
        if body_img is None:
            body_img = _load_img("mania-note1L")
        images[f"hold_body_{lane}"] = body_img

        # Hold tail
        tail_img = _load_img(_cfg(f"NoteImage{lane}T", f"mania-note{lane+1}T"))
        if tail_img is None:
            tail_img = head_img  # 回退到head
        images[f"hold_tail_{lane}"] = tail_img

        # Key (pressed)
        key_img = _load_img(_cfg(f"KeyImage{lane}", f"mania-key{lane+1}"))
        images[f"key_{lane}"] = key_img

        # Key (released)
        key_d_img = _load_img(_cfg(f"KeyImage{lane}D", f"mania-key{lane+1}D"))
        if key_d_img is None:
            key_d_img = key_img  # 回退
        images[f"key_{lane}D"] = key_d_img

    # --- 舞台/背景 ---
    images["stage_bottom"] = _load_img(_cfg("StageBottom", "mania-stage-bottom"))
    images["stage_hint"] = _load_img(_cfg("StageHint", "mania-stage-hint"))
    images["stage_light"] = _load_img(_cfg("StageLight", "mania-stage-light"))
    images["stage_left"] = _load_img(_cfg("StageLeft", "mania-stage-left"))
    images["stage_right"] = _load_img(_cfg("StageRight", "mania-stage-right"))

    # --- 判定特效 ---
    images["hit_300"] = _load_img(_cfg("Hit300Image", "mania-hit300"))
    images["hit_300g"] = _load_img(_cfg("Hit300gImage", "mania-hit300g"))
    images["hit_200"] = _load_img(_cfg("Hit200Image", "mania-hit200"))
    images["hit_100"] = _load_img(_cfg("Hit100Image", "mania-hit100"))
    images["hit_50"] = _load_img(_cfg("Hit50Image", "mania-hit50"))
    images["hit_0"] = _load_img(_cfg("Hit0Image", "mania-hit0"))

    # 如果 hit_200 不存在，尝试回退
    if images["hit_200"] is None:
        images["hit_200"] = _load_img("mania-hit200")
    if images["hit_100"] is None:
        images["hit_100"] = _load_img("mania-hit100")
    if images["hit_50"] is None:
        images["hit_50"] = _load_img("mania-hit50")
    if images["hit_0"] is None:
        images["hit_0"] = _load_img("mania-hit0")

    return result


def delete_skin(skin_name: str) -> bool:
    """删除指定皮肤。"""
    skin_path = os.path.join(SKINS_DIR, skin_name)
    if os.path.isdir(skin_path):
        shutil.rmtree(skin_path)
        return True
    return False
