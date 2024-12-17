import platform
import signal
import textwrap
from functools import wraps
from multiprocessing import Pool
from multiprocessing.pool import ThreadPool
from pathlib import Path
from re import split

import reCBZ2.config as config


class MPrunnerInterrupt(KeyboardInterrupt):
    """KeyboardInterrupt gracefully caught in MP_runner, please catch me"""


def shorten(*args, width=config.term_width()) -> str:
    text = " ".join(args)
    return textwrap.shorten(text, width=width, placeholder="...")


def mylog(msg: str, progress=False) -> None:
    if config.loglevel == -1:
        return
    elif config.loglevel > 2:
        print(msg, flush=True)
    elif config.loglevel == 2 and not progress:
        print(msg, flush=True)
    elif config.loglevel == 1 and progress:
        msg = "[*] " + msg
        msg = shorten(msg)
        print(msg, end="\n", flush=True)
    elif config.loglevel == 0 and progress:
        # no newline (i.e. overwrite line)
        # flush last first
        print("[*]".ljust(config.term_width()), end="\r")
        msg = "[*] " + msg
        msg = shorten(msg)
        print(msg, end="\r", flush=True)


def human_sort(lst) -> list:
    """Sort the given iterable in the way that humans expect."""
    # https://stackoverflow.com/a/2669120/
    if not type(lst[0]) is str:
        lst = [str(i) for i in lst]
    convert = lambda text: int(text) if text.isdigit() else text
    alphanum_key = lambda key: [convert(c) for c in split("([0-9]+)", key)]
    return sorted(lst, key=alphanum_key)


def human_bytes(b: float) -> str:
    # derived from https://github.com/x4nth055 (MIT)
    suffix = "B"
    FACTOR = 1024
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if b < FACTOR:
            return f"{b:.2f}{unit}{suffix}"
        b /= FACTOR
    return f"{b:.2f}Y{suffix}"


def pct_change(base: float, new: float) -> str:
    diff = new - base
    pct_change = diff / base * 100
    if pct_change >= 0:
        return f"+{pct_change:.2f}%"
    else:
        return f"{pct_change:.2f}%"


def pool_CTRL_C_handler(*args, **kwargs):
    global ctrl_c_entered
    ctrl_c_entered = True


def init_pool():
    # set global variable for each process in the pool:
    global ctrl_c_entered
    global default_sigint_handler
    ctrl_c_entered = False
    default_sigint_handler = signal.signal(signal.SIGINT, pool_CTRL_C_handler)


def worker_sigint_CTRL_C(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not "ctrl_c_entered" in globals():
            # init_pool hasn't been called because we're not from mp_pool_manager
            # (i.e. single threaded)
            return func(*args, **kwargs)
        global ctrl_c_entered
        if not ctrl_c_entered:  # the default
            signal.signal(signal.SIGINT, default_sigint_handler)
            try:
                return func(*args, **kwargs)
            except KeyboardInterrupt:
                ctrl_c_entered = True
                return KeyboardInterrupt()
            finally:
                signal.signal(signal.SIGINT, pool_CTRL_C_handler)
        else:
            return KeyboardInterrupt()

    return wrapper


def map_workers(func, tasks, multithread=False):
    pcount = min(len(tasks), config.pcount())
    if pcount == 1:
        return map(func, tasks)
    elif multithread:
        # mourn the day they inevitably condense the parallel modules in
        # python and I have to recall how any of this works
        with ThreadPool(processes=pcount) as Tpool:
            return Tpool.map(func, tasks)
    else:
        if platform.system == "windows":
            # this hangs on Unix, but prevents hanging on Windows (insanity)
            # god bless https://stackoverflow.com/a/68695455/
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        with Pool(processes=pcount, initializer=init_pool) as MPpool:
            try:
                return MPpool.map(func, tasks)
            except KeyboardInterrupt:
                mylog("MAY YOUR WOES BE MANY")
                MPpool.terminate()
                mylog("AND YOUR DAYS FEW")
                raise MPrunnerInterrupt()


def write_zip(save_path: str, chapters: list, chapter_prefix: str) -> str:
    """
    Write a .zip file from a list of chapters

    :param str save_path: Path to the .zip file
    :param list chapters: List of chapters, each containing a list of pages
    :param str chapter_prefix: Prefix for the chapter folders
    :return: Path to the .zip file
    :rtype: str
    """
    from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

    new_zip = ZipFile(save_path, "w")
    lead_zeroes = len(str(len(chapters)))
    for i, chapter in enumerate(chapters):
        for page in chapter:

            if len(chapters) > 1:  # no parent if there's only one chapter
                dest = Path(f"{chapter_prefix}{i+1:0{lead_zeroes}d}") / page.rel_path
            else:
                dest = Path(page.rel_path)
            mylog(f"ZIP: write '{page.name}' to {dest}")
            if config.compress_zip:
                new_zip.write(page.fp, dest, ZIP_DEFLATED, 9)
            else:
                new_zip.write(page.fp, dest, ZIP_STORED)
    new_zip.comment = str.encode(config.ZIPCOMMENT)
    new_zip.close()
    return save_path


def write_epub(save_path: str, chapters: list) -> str:
    """
    Write an .epub file from a list of chapters

    :param str save_path: Path to the .epub file
    :param list chapters: List of chapters, each containing a list of pages
    :return: Path to the .epub file
    :rtype: str
    """
    from itertools import chain
    from reCBZ2 import epub

    pages = list(chain(*chapters))
    title = Path(save_path).stem
    mylog(f"Write .epub: {title}.epub", progress=True)
    if len(chapters) > 1:
        save_path = epub.multi_chapter_epub(title, chapters)
    else:
        save_path = epub.single_chapter_epub(title, pages)
    # TODO: compress the .epub file if enabled in config
    # if Config.compress_zip:
    #     ZipFile(savepath, mode='w', compression=ZIP_DEFLATED, compresslevel=9).write(savepath)
    return save_path


# TODO: not used right now, implement or delete?
def write_mobi(savepath, chapters):
    import subprocess

    try:
        subprocess.run(["kindlegen", "", "/dev/null"], capture_output=True)
    except FileNotFoundError:
        raise OSError("'kindlegen' can't be found. is it installed and in PATH?")
    pass
