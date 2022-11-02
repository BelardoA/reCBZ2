#!/usr/bin/python3
# -*- coding: utf-8 -*-
from sys import argv, exit
import time
import os
from zipfile import ZipFile, ZIP_DEFLATED
from multiprocessing import Pool
from tempfile import TemporaryDirectory
from functools import partial
from shutil import get_terminal_size
try:
    from PIL import Image
except ModuleNotFoundError:
    print("Please install Pillow!\nrun 'pip3 install pillow'")
    exit(1)

# TODO:
# may prove useful for determing format of the images in the archive, although
# its too new (python 3.11) at the moment:
# https://docs.python.org/3/library/zipfile.html#zipfile.Path.suffixes
# consider replacing os.path with pathlib, as it might be simpler:
# https://docs.python.org/3/library/pathlib.html#correspondence-to-tools-in-the-os-module

# limit output message width. ignored if verbose
T_COLUMNS, T_LINES = get_terminal_size()
if T_COLUMNS > 120: max_column = 120
elif T_COLUMNS < 30: max_column= 30
else: max_column = T_COLUMNS


def print_title() -> None:
    align = int(T_COLUMNS / 2) - 11
    if align > 21: align = 21
    if align + 22 > T_COLUMNS or align < 0:
        align = 0
    align = align * ' '
    title_multiline = (f"{align}┬─┐┌─┐┌─┐┌┐ ┌─┐ ┌─┐┬ ┬\n"
                       f"{align}├┬┘├┤ │  ├┴┐┌─┘ ├─┘└┬┘\n"
                       f"{align}┴└─└─┘└─┘└─┘└─┘o┴   ┴")
    print(title_multiline)


class Config():
    def __init__(self):
        # General options:
        # ---------------------------------------------------------------------
        # whether to enable multiprocessing. fast, uses lots of memory
        self.parallel:bool = True
        # number of processes to spawn
        self.pcount:int = 16
        # this only affects the extension name. will always be a zip archive
        self.zipext:str = '.cbz'
        # number of images to test in analyze
        self.autocount:int = 10
        # debugging messages
        self.verbose:bool = False
        # suppress progress messages
        self.quiet:bool = False

        # Options which affect image quality and/or file size:
        # ---------------------------------------------------------------------
        # new image width / height. set to 0 to preserve original dimensions
        # self.newsize:tuple = (1440,1920)
        self.newsize = (0,0)
        # set to True to not upscale images smaller than newsize
        self.noupscale:bool = False
        # compression quality for lossy images (not the archive). greatly
        # affects file size. values higher than 95% might increase file size
        self.quality:int = 80
        # force lossy compression when converting from png to webp. significant
        # effect on file size, often but not always smaller.
        self.forcelossy:bool = False
        # compresslevel for the archive. barely affects file size (images are
        # already compressed) but has a significant impact on performance,
        # which persists when reading the archive, so 0 is recommended
        self.compresslevel:int = 0
        # LANCZOS sacrifices performance for optimal upscale quality. doesn't
        # affect file size. less critical for downscaling, BOX or BILINEAR can
        # be used if performance is important
        self.resamplemethod = Image.Resampling.LANCZOS
        # whether to convert images to grayscale. moderate effect on file size
        # on full-color comics. useless on BW manga
        self.grayscale:bool = False
        # least to most space, generally: WEBP, JPEG, or PNG. WEBP uses less
        # space but is not universally supported and may cause errors on older
        # devices, so JPEG is recommended. leave empty to preserve original
        self.imgtype:str = 'jpeg'

        self.rescale:bool = False
        if all(self.newsize):
            self.rescale = True


# TODO define class with name, description, and extension attributes for each
# format. perhaps also define Image.save() arguments as __init__ attributes
# so there's a universal "save" method after instantiating
class ImageFormat():
    pass


class Archive():
    valid_imgtypes = ['webp','png','jpeg'] #,'webpll']


    def __init__(self, filename:str, config:Config):
        self.filename = filename # TODO: test if exists, raise otherwise
        self.config = config

    def analyze(self) -> tuple:
        self._log(f'Extracting: {self.filename}', progress=True)
        source_zip = ZipFile(self.filename)
        compressed_files = source_zip.namelist()

        # select 5 images from the middle of the archive, in increments of two
        delta = int(len(compressed_files) / 2) # TODO raise if archive is too small
        sample_size = 5
        sample_imgs = compressed_files[delta-sample_size:delta+sample_size:1]

        # extract them and compute their size
        size_totals = []
        with TemporaryDirectory() as tempdir:
            for name in sample_imgs:
                source_zip.extract(name, tempdir)
            source_zip.close()
            # https://stackoverflow.com/a/3207973/8225672 absolutely nightmarish
            # but this is the only way to avoid problems with subfolders
            sample_imgs = [os.path.join(dpath,f) for (dpath, dnames, fnames)
                            in os.walk(tempdir) for f in fnames]
            nbytes = sum(os.path.getsize(f) for f in sample_imgs)
            sample_fmt = os.path.splitext(sample_imgs[0])[1][1:].lower()
            if sample_fmt == 'jpg': sample_fmt = 'jpeg'
            size_totals.append((nbytes, f'{sample_fmt} (original)'))

            # also compute the size of each valid format after converting
            for fmt in Archive.valid_imgtypes:
                fmtdir = os.path.join(tempdir, fmt)
                os.mkdir(fmtdir)
                func = partial(self._transform_img, dest=fmtdir, newformat=fmt)
                if self.config.parallel:
                    with Pool(processes=self.config.pcount) as pool:
                        results = pool.map(func, sample_imgs)
                else:
                    results = map(func, sample_imgs)
                converted_imgs = [path for path in results if path]
                nbytes = sum(os.path.getsize(f) for f in converted_imgs)
                size_totals.append((nbytes,fmt))

        # finally, compare
        # in multidepth lists, sorted compares the first element by default :)
        size_totals = tuple(sorted(size_totals))
        suggested_fmt = size_totals[0][1]
        summary = Archive._diff_summary_analyze(size_totals, sample_size)
        self._log(str(size_totals))
        self._log('', progress=True)
        return suggested_fmt, summary


    def repack(self) -> tuple:
        start_t = time.perf_counter()
        self._log(f'Extracting: {self.filename}', progress=True)
        source_zip = ZipFile(self.filename)
        source_zip_size = os.path.getsize(self.filename)
        source_zip_name = os.path.splitext(str(source_zip.filename))[0]
        # extract all
        with TemporaryDirectory() as tempdir:
            source_zip.extractall(tempdir)
            source_zip.close()
            source_imgs = [os.path.join(dpath,f) for (dpath, dnames, fnames)
                            in os.walk(tempdir) for f in fnames]

            # process images in place
            if self.config.parallel:
                with Pool(processes=self.config.pcount) as pool:
                    results = pool.map(self._transform_img, source_imgs)
            else:
                results = map(self._transform_img, source_imgs)
            converted_imgs = [path for path in results if path]
            names = [os.path.basename(f) for f in converted_imgs] # TODO: unecessary?

            # write to new local archive
            zip_name = f'{source_zip_name} [reCBZ]{self.config.zipext}'
            if os.path.exists(zip_name):
                self._log(f'{zip_name} exists, removing...')
                os.remove(zip_name)
            new_zip = ZipFile(zip_name,'w')
            self._log(f'Write {self.config.zipext}: {zip_name}', progress=True)
            for source, dest in zip(converted_imgs, names):
                new_zip.write(source, dest, ZIP_DEFLATED, self.config.compresslevel)
            new_zip.close()
            zip_size = os.path.getsize(zip_name)

        end_t = time.perf_counter()
        elapsed = f'{end_t - start_t:.2f}s'
        diff = Archive._diff_summary_repack(source_zip_size, zip_size)
        self._log('', progress=True)
        return zip_name, elapsed, diff


    def _transform_img(self, source:str, dest=None, newformat=None):
        start_t = time.perf_counter()
        source_stem, source_ext = os.path.splitext(source)
        try:
            self._log(f'Read image: {os.path.basename(source)}', progress=True)
            log_buff = f'	/open: {source}\n'
            img = Image.open(source)
        except IOError:
            self._log(f"{source}: can't open as image, ignoring...'")
            return None

        if newformat:
            ext = '.' + newformat
        elif self.config.imgtype in ('jpeg', 'png', 'webp'):
            ext = '.' + self.config.imgtype
        else:
            ext = source_ext

        # set IO format specific actions
        if ext == '.webp':
            # webp_lossy appears to result in bigger files than webp_lossless
            # when the source is a png
            if source_ext == '.png' and not self.config.forcelossy:
                save_func = self._save_webp_lossless
            else:
                save_func = self._save_webp_lossy
        elif ext in ('.jpeg', '.jpg'):
            save_func = self._save_jpeg
            # remove alpha layer
            if not img.mode == 'RGB':
                log_buff += '	|convert: mode RGB\n'
                img = img.convert('RGB')
        elif ext == '.png':
            save_func = self._save_png
        else:
            self._log(f"{source}: invalid format, ignoring...'")
            return None

        # transform
        if self.config.grayscale:
            log_buff += '	|convert: mode L\n'
            img = img.convert('L')
        if self.config.rescale:
            log_buff += f'	|convert: resize to {self.config.newsize}\n'
            img = self._resize_img(img)

        # save
        if dest:
            path = os.path.join(dest, f'{os.path.basename(source_stem)}{ext}')
        else:
            path = f'{source_stem}{ext}'
        log_buff += f'	|convert: {source_ext} -> {ext}\n'
        save_func(img, path)
        end_t = time.perf_counter()
        elapsed = f'{end_t-start_t:.2f}s'
        self._log(f'{log_buff}	\\write: {path}: took {elapsed}')
        return path


    def _resize_img(self, img:Image.Image) -> Image.Image:
        width, height = img.size
        newsize = self.config.newsize
        # preserve aspect ratio for landscape images
        if width > height:
            newsize = newsize[::-1]
        n_width, n_height = newsize
        # downscaling
        if (width > n_width) and (height > n_height):
            img = img.resize((newsize), self.config.resamplemethod)
        # upscaling
        elif not self.config.noupscale:
            img = img.resize((newsize), self.config.resamplemethod)
        return img


    def _save_webp_lossy(self, img:Image.Image, path) -> str:
        img.save(path, lossless=False, quality=self.config.quality)
        return path


    def _save_webp_lossless(self, img:Image.Image, path) -> str:
        # for some reason 'quality' refers to compress_level when lossless
        img.save(path, lossless=True, quality=100)
        return path


    def _save_jpeg(self, img:Image.Image, path) -> str:
        img.save(path, optimize=True, quality=self.config.quality)
        return path


    def _save_png(self, img:Image.Image, path) -> str:
        # img.save(path, optimize=True, quality=self.config.quality)
        img.save(path, optimize=True, compress_level=9)
        return path


    def _log(self, msg:str, progress=False) -> None:
        if self.config.quiet:
            pass
        elif self.config.verbose:
            print(msg)
        elif progress:
            # wrap to terminal width characters, no newline
            msglen = max_column - 1
            msg = msg[:msglen]
            fill = ' '
            align = '<'
            width = msglen
            print(f'*{msg:{fill}{align}{width}}', end='\r')
        else:
            pass


    @classmethod
    def _get_size_format(cls, b:float) -> str:
        # derived from https://github.com/x4nth055 (MIT)
        suffix = "B"
        FACTOR = 1024
        for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
            if b < FACTOR:
                return f"{b:.2f}{unit}{suffix}"
            b /= FACTOR
        return f"{b:.2f}Y{suffix}"


    @classmethod
    def _get_pct_change(cls, base:float, new:float) -> str:
        diff = new - base
        pct_change = diff / base * 100
        if pct_change >= 0:
            return f"+{pct_change:.2f}%"
        else:
            return f"{pct_change:.2f}%"


    @classmethod
    def _diff_summary_repack(cls, base:int, new:int) -> str:
        verb = 'decrease'
        if new > base:
            verb = 'INCREASE!'
        change = Archive._get_pct_change(base, new)
        basepretty = cls._get_size_format(base)
        newpretty = cls._get_size_format(new)
        return f"Original: {basepretty} ■ New: {newpretty} ■ {change} {verb}"


    @classmethod
    def _diff_summary_analyze(cls, totals:tuple, sample_size:int) -> str:
        base = [total[0] for total in totals if 'original' in total[1]][0]
        summary = f'┌── Disk size ({sample_size} pages) with present settings\n'
        for i, total in enumerate(totals):
            if i == len(totals)-1:
                prefix = '└─'
            # elif i == 0:
            #     prefix = '┌───'
            else:
                prefix = '├─'
            change = cls._get_pct_change(base, total[0])
            fmt = total[1]
            human_size = Archive._get_size_format(total[0])
            # justify to the left and right respectively. effectively the same
            # as using f'{part1: <20} | {part2: >8}\n'
            part1 = f'{prefix}■{i+1} {fmt}'.ljust(25)
            part2 = f'{human_size}'.rjust(8)
            summary += f'{part1} {part2} | {change}\n'
        return summary[0:-1] # strip last newline


# class ArchiveList():
#     def __init__(self, )

if __name__ == '__main__':
    config = Config()
    if len(argv) > 1 and os.path.isfile(argv[1]):
        soloarchive = Archive(argv[1], config)
    else:
        print('BAD!!! >:(')
        exit(1)
    print_title()
    if len(argv) > 2 and argv[2] == '-a':
        results = soloarchive.analyze()
        print(results[1])
        print(f'Suggested format: {results[0]}')
    else:
        results = soloarchive.repack()
        print(f"┌─ '{results[0]}' completed in {results[1]}")
        print(f"└───■■ {results[2]} ■■")
