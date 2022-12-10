import os
from importlib import resources

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from PIL import Image

import reCBZ
from reCBZ.profiles import profiles_list

# LANCZOS sacrifices performance for optimal upscale quality
RESAMPLE_TYPE = Image.Resampling.LANCZOS
ZIPCOMMENT:str = 'repacked with reCBZ'
_cfg = tomllib.loads(resources.read_text("reCBZ", "defaults.toml"))

overwrite:bool = _cfg["general"]["overwrite"]
ignore_err:bool = _cfg["general"]["ignore"]
force_write:bool = _cfg["general"]["force"]
no_write:bool = _cfg["general"]["nowrite"]
loglevel:int = _cfg["general"]["loglevel"]
processes:int = _cfg["general"]["processes"]
samples_count:int = _cfg["general"]["samplecount"]
archive_format:str = _cfg["archive"]["archiveformat"]
compress_zip:int = _cfg["archive"]["compresszip"]
right_to_left:bool = _cfg["archive"]["righttoleft"]
img_format:str = _cfg["image"]["imageformat"]
img_quality:int = _cfg["image"]["quality"]
img_size:tuple = _cfg["image"]["size"]
no_upscale:bool = _cfg["image"]["noupscale"]
no_downscale:bool = _cfg["image"]["nodownscale"]
grayscale:bool = _cfg["image"]["grayscale"]
blacklisted_fmts:str = _cfg["image"]["blacklistedfmts"]
ebook_profile = None


def pcount() -> int:
    default_value = 4
    if processes > 0:
        return processes
    else:
        logical_cores = os.cpu_count()
        try:
            assert logical_cores is not None
            if logical_cores not in range(1,3):
                logical_cores -= 1 # be kind
            return logical_cores
        except AssertionError:
            return default_value


def term_width() -> int:
    # limit output message width. ignored if verbose
    try:
        TERM_COLUMNS, TERM_LINES = os.get_terminal_size()
        assert TERM_COLUMNS > 0 and TERM_LINES > 0
        if TERM_COLUMNS > 120: max_width = 120
        elif TERM_COLUMNS < 30: max_width = 30
        else: max_width = TERM_COLUMNS - 2
    except (AssertionError, OSError):
        print("[!] Can't determine terminal size, defaulting to 78 cols")
        max_width = 78
    return max_width


def set_profile(name) -> None:
    global blacklisted_fmts, ebook_profile, archive_format, img_size, grayscale
    dic = {prof.nickname:prof for prof in profiles_list}
    try:
        profile = dic[name]
    except KeyError:
        raise ValueError(f"Invalid profile '{name}'")
    grayscale = profile.gray
    img_size = profile.size
    # if profile.prefer_epub:
    archive_format = 'epub'
    ebook_profile = profile
    blacklisted_fmts += profile.blacklisted_fmts


preload_profile = _cfg["archive"]["ebookprofile"]
if preload_profile != '':
    set_profile(preload_profile.upper())
