import tempfile
from typing import Union, Any, Type

from reCBZ2 import CACHE_PREFIX
from pathlib import Path
from reCBZ2.formats import Image, Png, Jpeg, WebpLossless, WebpLossy


class Page:
    """
    Page object to store and manipulate image data
    """

    def __init__(self, file_name):
        self.fp = Path(file_name)
        # i tried for hours but windows can't correctly pickle the
        # GLOBAL_CACHEDIR, it's not thread safe for whatever reason. some
        # instances will init with a new UUID which can't be compared.
        # this is the least hacky way I could come up with to keep Unix parity
        uuid_part = [part for part in self.fp.parts if CACHE_PREFIX in part]
        global_cache = Path(tempfile.gettempdir()) / uuid_part[0]
        local_cache = global_cache / self.fp.relative_to(global_cache).parts[0]
        self.rel_path = self.fp.relative_to(local_cache)
        self.name = str(self.fp.name)
        self.stem = str(self.fp.stem)
        self._img: Image.Image
        self._fmt = None
        self._closed = True

    @property
    def fmt(self) -> Type[Png | Jpeg | WebpLossless | WebpLossy] | Any:
        """
        Returns the format of the image

        :return: Image format
        :rtype: Format
        """
        if self._fmt is not None:
            return self._fmt
        else:
            pillow_format = self.img.format
            if pillow_format is None:
                raise KeyError(f"Image.format returned None")
            elif pillow_format == "PNG":
                return Png
            elif pillow_format == "JPEG":
                return Jpeg
            elif pillow_format == "WEBP":
                # https://github.com/python-pillow/Pillow/discussions/6716
                with open(self.fp, "rb") as file:
                    if file.read(16)[-1:] == b"L":
                        return WebpLossless
                    else:
                        return WebpLossy
            else:
                raise KeyError(f"'{pillow_format}': invalid format")

    @fmt.setter
    def fmt(self, new: Any):
        """
        Set the format of the image

        :param Any new: New format
        """
        self._fmt = new

    @property
    def img(self) -> Image.Image:
        """
        Returns the image object

        :return: Image object
        :rtype: Image.Image
        """
        if self._closed:
            self._img = Image.open(self.fp)
            self._closed = False
            return self._img
        else:
            return self._img

    @img.setter
    def img(self, new: Image.Image):
        """
        Set the image object

        :param Image.Image new: New image object
        """
        self._img = new
        self._closed = False

    @property
    def size(self) -> tuple[int, int]:
        """
        Returns the size of the image

        :return: Image size
        :rtype: tuple[int, int]
        """
        return self.img.size

    @property
    def landscape(self):
        """
        Returns True if the image is landscape

        :return: Landscape status
        :rtype: bool
        """
        if self.size[0] > self.size[1]:
            return True
        else:
            return False

    def save(self, dest: Any):
        """
        Save the image to a new location

        :param Any dest: Destination path
        """
        self.fmt.save(self.img, dest)
        self.fp = Path(dest)
        self.name = str(self.fp.name)
        self.stem = str(self.fp.stem)
        self._img.close()
        self._closed = True

    def __reduce__(self) -> tuple[Type["Page"], tuple[Union[str, Path]]]:
        """
        Required for pickling

        :return: Class and arguments
        :rtype: tuple[Type["Page"], tuple[Union[str, Path]]]
        """
        # pickle pee. pum pa rum
        # https://stackoverflow.com/q/19855156/
        return (self.__class__, (self.fp,))  # noqa
