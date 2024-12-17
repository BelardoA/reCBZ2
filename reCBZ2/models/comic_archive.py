import shutil
import tempfile
import time
from functools import partial
from pathlib import Path
from typing import Optional, Any
from zipfile import ZipFile, BadZipFile

from PIL import UnidentifiedImageError

from reCBZ2 import GLOBAL_CACHEDIR, config
from reCBZ2.formats import FormatDict
from reCBZ2.formats import Jpeg, LossyFmt
from reCBZ2.util import (
    mylog,
    map_workers,
    human_sort,
    worker_sigint_CTRL_C,
    write_zip,
    write_epub,
)


class ComicArchive:
    SOURCE_NAME: str = "Source"
    VALID_BOOK_FORMATS: tuple = ("cbz", "zip", "epub", "mobi")
    chapter_prefix: str = "v"  # :) :D C:

    def __init__(self, filename: str):
        mylog("Archive: __init__")
        if Path(filename).exists():
            self.fp: Path = Path(filename)
        else:
            raise ValueError(f"{filename}: invalid path")
        self._page_opt = {}
        self._page_opt["format"] = self.get_format_class(config.img_format)
        self._page_opt["quality"] = config.img_quality
        self._page_opt["size"] = config.img_size
        self._page_opt["keep_ratio"] = config.keep_ratio
        self._page_opt["grayscale"] = config.grayscale
        self._page_opt["noup"] = config.no_upscale
        self._page_opt["nodown"] = config.no_downscale
        self._index: list = []
        self._chapter_lengths = []
        self._chapters = []
        self._bad_files = []
        self._cachedir = Path(tempfile.mkdtemp(prefix="book_", dir=GLOBAL_CACHEDIR))

    @worker_sigint_CTRL_C
    def convert_page_worker(self, source, options, savedir=None):
        from reCBZ2.models import Page

        start_t = time.perf_counter()
        # page = copy.deepcopy(source)
        page = Page(source.fp)  # create a copy

        # ensure file can be opened as image, and that it's a valid format
        try:
            mylog(f"Read file: {page.name}", progress=True)
            log_buff = f"/open:  {page.fp}\n"
            source_fmt = page.fmt
            img = page.img
        except (IOError, UnidentifiedImageError) as err:
            if config.ignore_page_err:
                mylog(f"{page.fp}: can't open file as image, ignoring...'")
                return False, page
            else:
                raise err
        except KeyError as err:
            if config.ignore_page_err:
                mylog(f"{page.fp}: invalid image format, ignoring...'")
                return False, page
            else:
                raise err

        # determine target (new) format
        if options["format"]:
            new_fmt = options["format"]
        else:
            new_fmt = source_fmt
        page.fmt = new_fmt

        # apply format specific actions
        if new_fmt is Jpeg:
            if not img.mode == "RGB":
                log_buff += "|trans: mode RGB\n"
                img = img.convert("RGB")

        # transform
        if options["grayscale"]:
            log_buff += "|trans: mode L\n"  # me lol
            img = img.convert("L")

        if all(options["size"]):
            log_buff += f'|trans: resize to {options["size"]}\n'
            width, height = img.size
            new_size = options["size"]
            # preserve aspect ratio for landscape images
            if page.landscape:
                new_size = new_size[::-1]
            n_width, n_height = new_size
            if options["keep_ratio"]:
                resize_size = self.get_size_that_preserves_ratio(
                    img_size=(width, height), size_of_viewport=new_size
                )
                log_buff += f"|trans: keeping ratio: size changed from {(width, height)} to {resize_size}\n"
            else:
                resize_size = new_size
            # downscaling
            if width > n_width and height > n_height and not options["nodown"]:
                img = img.resize((resize_size), config.RESAMPLE_TYPE)
            # upscaling
            elif not options["noup"]:
                img = img.resize((resize_size), config.RESAMPLE_TYPE)

        LossyFmt.quality = options["quality"]

        # save
        page.img = img
        ext = page.fmt.ext[0]
        if savedir:
            new_fp = Path.joinpath(savedir, f"{page.stem}{ext}")
        else:
            new_fp = Path.joinpath(page.fp.parents[0], f"{page.stem}{ext}")
        log_buff += f"|trans: {source_fmt.name} -> {new_fmt.name}\n"
        page.save(new_fp)

        end_t = time.perf_counter()
        elapsed = f"{end_t - start_t:.2f}s"
        mylog(f"{log_buff}\\write: {new_fp}: took {elapsed}")
        mylog(f"Save file: {new_fp.name}", progress=True)
        return True, page

    @staticmethod
    def get_size_that_preserves_ratio(
        *, img_size: tuple[int, int], size_of_viewport: tuple[int, int]
    ) -> tuple[int, int]:
        """
        Calculate the size that preserves the aspect ratio of an image when resized

        :param tuple[int, int] img_size: Tuple containing the width and height of the image
        :param tuple[int, int] size_of_viewport: Tuple containing the width and height of the viewport
        :return: Tuple containing the width and height of the new size
        :rtype: tuple[int, int]
        """
        # derived from https://pillow.readthedocs.io/en/stable/_modules/PIL/Image.html#Image.thumbnail (HPND)
        import math

        def round_aspect(number, key):
            return max(min(math.floor(number), math.ceil(number), key=key), 1)

        x, y = size_of_viewport

        width, height = img_size

        aspect = width / height
        if x / y >= aspect:
            x = round_aspect(y * aspect, key=lambda n: abs(aspect - n / y))
        else:
            y = round_aspect(
                x / aspect, key=lambda n: 0 if n == 0 else abs(aspect - x / n)
            )
        return x, y

    @staticmethod
    def get_format_class(name: Optional[Any] = None) -> Optional[Any]:
        """
        Get the format class from a format name

        :param Optional[Any] name: Name of the format, defaults to None
        :return: Format class if name provided, None otherwise
        :rtype: Optional[Any]
        """
        if not name:
            return None
        try:
            return FormatDict[name]
        except KeyError:
            raise ValueError(f"Invalid format name '{name}'")

    @property
    def bad_files(self):
        return self._bad_files

    def fetch_pages(self):
        if len(self._index) == 0:
            self._index = list(self.extract())
        return self._index

    def fetch_chapters(self):
        # ensure it's a copy, so we can't delete the original objects
        index_copy = [page for page in self.fetch_pages()]
        if len(self._chapter_lengths) == 0:
            self._chapter_lengths = [len(index_copy)]
        chapters = []
        for length in self._chapter_lengths:
            chapters.append(index_copy[:length])
            del index_copy[:length]
        return chapters

    def extract(self, count: int = 0, raw: bool = False) -> tuple:
        try:
            source_zip = ZipFile(self.fp)
        except BadZipFile as err:
            raise ValueError(f"Fatal: '{self.fp}': not a zip file")

        compressed_files = source_zip.namelist()
        assert len(compressed_files) >= 1, "no files in archive"
        if count > 0:
            # select x images from the middle of the archive, in increments of 2
            if count * 2 > len(compressed_files):
                raise ValueError(f"{self.fp} is smaller than samples * 2")
            delta = int(len(compressed_files) / 2)
            compressed_files = compressed_files[delta - count : delta + count : 2]

        mylog(f"Extracting: {self.fp}", progress=True)
        for file in compressed_files:
            source_zip.extract(file, self._cachedir)

        from reCBZ2.models import Page

        # god bless you Georgy https://stackoverflow.com/a/50927977/
        raw_paths = tuple(filter(Path.is_file, Path(self._cachedir).rglob("*")))
        # solves the need to invert files in EPUB, where the destination can't
        # be inferred from the original filepath. critical, because files are
        # randomly ordered on Windows (probably due to the ZLIB implementation)
        sorted_paths = tuple(human_sort(raw_paths))
        sorted_pages = tuple(Page(path) for path in sorted_paths)

        mylog("", progress=True)
        if raw:
            return sorted_paths
        else:
            return sorted_pages

    def add_chapter(self, second_archive, start=None, end=None) -> tuple:
        try:
            assert isinstance(second_archive, ComicArchive)
        except AssertionError:
            raise ValueError("second_archive is not an instance of Archive")

        new_chapter = second_archive.fetch_pages()
        if start:
            try:
                assert type(start) is int
            except AssertionError:
                raise ValueError("start must be an integer")
            # can raise IndexError but we want it to do so
            new_chapter = new_chapter[start:]
        if end:
            try:
                assert type(start) is int
            except AssertionError:
                raise ValueError("end must be an integer")
            new_chapter = new_chapter[:end]

        # ensure chapter1 is populated
        self.fetch_chapters()
        self._chapter_lengths.append(len(new_chapter))
        self._index.extend(new_chapter)
        return tuple(self.fetch_pages())

    def convert_pages(self, fmt=None, quality=None, grayscale=None, size=None) -> tuple:
        # TODO assert values are the right type
        options = dict(self._page_opt)
        if fmt is not None:
            options["format"] = self.get_format_class(fmt)
        if quality is not None:
            options["quality"] = int(quality)
        if grayscale is not None:
            options["grayscale"] = bool(grayscale)
        if size is not None:
            options["size"] = size

        worker = partial(self.convert_page_worker, options=options)
        results = map_workers(worker, self.fetch_pages())

        self._bad_files = [item[1].fp for item in results if item[0] is False]
        self._index = [item[1] for item in results if item[0]]
        mylog("", progress=True)
        return tuple(self._index)

    def compute_fmt_sizes(self) -> tuple:
        def compute_single_fmt(sample_pages, cachedir, fmt) -> tuple:
            fmtdir = Path.joinpath(cachedir, fmt.name)
            Path.mkdir(fmtdir)

            options = dict(self._page_opt)  # ensure it's a copy
            options["format"] = fmt
            worker = partial(self.convert_page_worker, savedir=fmtdir, options=options)
            results = map_workers(worker, sample_pages)

            # pages don't need to be sorted here, as they're discarded
            converted_pages = [item[1] for item in results if item[0]]
            nbytes = sum(page.fp.stat().st_size for page in converted_pages)
            return nbytes, fmt.desc, fmt.name

        # extract images and compute their original size
        # manually call extract so we don't overwrite _pages cache
        source_pages = self.extract(count=config.samples_count)
        nbytes = sum(page.fp.stat().st_size for page in source_pages)
        mylog(f"reference format: {source_pages[0].name}")
        source_fmt = source_pages[0].fmt
        source_fsize = [
            nbytes,
            f"{self.SOURCE_NAME} ({source_fmt.desc})",
            source_fmt.name,
        ]

        # compute the size of each format after converting.
        # one thread per individual format. n processes per thread
        fmt_fsizes = []
        worker = partial(compute_single_fmt, source_pages, self._cachedir)
        results = map_workers(worker, config.allowed_page_formats(), multithread=True)
        fmt_fsizes.extend(results)

        # finally, compare
        # in multidepth lists, sorted compares the first element by default :)
        sorted_fmts = list(sorted(fmt_fsizes))
        sorted_fmts.insert(0, source_fsize)
        mylog(str(sorted_fmts))
        mylog("", progress=True)
        return tuple(sorted_fmts)

    def write_archive(self, book_format="cbz", file_name: str = "") -> str:
        if book_format not in self.VALID_BOOK_FORMATS:
            raise ValueError(f"Invalid format '{book_format}'")

        if file_name != "":
            parent = Path(file_name).parents[0]
            if not (parent.exists() and parent.is_dir()):
                raise ValueError(f"Parent folder '{parent}' does not exist")
            new_path = Path(f"{file_name}.{book_format}")
        else:
            # write to current dir
            new_path = Path(f"{self.fp.stem}.{book_format}")
        if new_path.exists():
            mylog(f"Write .{book_format}: {new_path}", progress=True)
            mylog(f"{new_path} exists, removing...")
            new_path.unlink()

        new_path = str(new_path)
        if book_format == "cbz":
            return write_zip(new_path, self.fetch_chapters(), self.chapter_prefix)
        elif book_format == "zip":
            return write_zip(new_path, self.fetch_chapters(), self.chapter_prefix)
        elif book_format == "epub":
            return write_epub(new_path, self.fetch_chapters())
        elif book_format == "mobi":
            raise NotImplementedError
        else:
            raise ValueError

    def add_page(self, fp, index=-1):
        try:
            assert Path(fp).exists()
            from reCBZ2.models import Page

            Page(fp)
        except AssertionError:
            raise ValueError(f"can't open {fp}")
        # we want the IndexError
        self._index.insert(index, fp)

    def remove_page(self, index):
        return self._index.pop(index)

    def cleanup(self):
        if self._cachedir.exists():
            mylog(f"cleanup(): {self._cachedir}")
            try:
                shutil.rmtree(self._cachedir)
            except PermissionError:
                mylog(f"PermissionError, couldn't clean {self._cachedir}")
