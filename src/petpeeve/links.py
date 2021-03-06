import collections
import functools
import hashlib
import sys
import warnings

from pip._vendor import six
from pip._vendor.distlib.wheel import Wheel
from pip._vendor.packaging import version as packaging_version
from wheel import pep425tags

from .wheels import get_built_wheel_path, get_wheel_path


class WheelNotFoundError(OSError):
    pass


class Link(object):
    """Represents a link to a package.

    Links are usually found in a Simple API page, but can also be specified
    directly in a Requirement with PEP 508's URL-based lookup.
    """
    def __init__(
            self, url, checksum,
            file_stem, file_extension,
            python_specifier):
        self.url = url
        self.checksum = checksum
        self.file_stem = file_stem
        self.extension = file_extension
        self.python_specifier = python_specifier
        self.info = self.parse_for_info()

    def __repr__(self):
        return '<{type} {filename}>'.format(
            type=type(self).__name__,
            filename=self.filename,
        )

    @property
    def filename(self):
        return self.file_stem + self.extension

    def parse_for_info(self):
        raise NotImplementedError

    def check_download(self, data):
        """Check if the downloaded data is good.
        """
        if not self.checksum:
            return
        htype, hvalue = self.checksum.split('=')
        h = hashlib.new(htype)
        h.update(data)
        value = h.hexdigest()
        if hvalue != value:
            raise ValueError('expected {}, but got {}'.format(hvalue, value))

    def as_wheel(self, offline=False):
        """Build a representation of a local wheel artifact with the link.

        The return value is a distlib.wheel.Wheel. If `offline` if `True`,
        `WheelNotFoundError` is raised if the wheel is not found in the
        local cache. Otherwise the wheel is downloaded.
        """
        raise NotImplementedError


SourceInformation = collections.namedtuple('SourceInformation', [
    'distribution_name',
    'version',
])


class SourceDistributionLink(Link):
    """Link to an sdist.
    """
    def parse_for_info(self):
        name, ver = self.file_stem.rsplit('-', 1)
        return SourceInformation(name, packaging_version.parse(ver))

    def as_wheel(self, offline=False):
        if offline:     # TODO: Can we peek into the wheel cache here?
            raise WheelNotFoundError(self.filename)
        path = get_built_wheel_path(self)
        if not path:
            raise WheelNotFoundError(self.filename)
        return Wheel(path)


WheelInformation = collections.namedtuple('WheelInformation', [
    'distribution_name',
    'version',
    'build_tag',
    'language_implementation_tag',
    'abi_tag',
    'platform_tag',
])


class WheelDistributionLink(Link):
    """Link to a wheel.
    """
    def parse_for_info(self):
        """Parse the wheel's file name according to PEP427.

        https://www.python.org/dev/peps/pep-0427/#file-name-convention
        """
        parts = self.file_stem.split('-')
        if len(parts) == 6:
            name, ver, build, impl, abi, plat = parts
            build = int(build)
        elif len(parts) == 5:
            name, ver, impl, abi, plat = parts
            build = None
        version = packaging_version.parse(ver)
        return WheelInformation(name, version, build, impl, abi, plat)

    def is_binary_compatible(self):
        with warnings.catch_warnings():
            # Ignore "Python ABI tag may be incorrect" warnings on Windows.
            # Windows wheels don't specify those anyway.
            if sys.platform.startswith('win'):
                warnings.simplefilter('ignore')
            supported_tags = pep425tags.get_supported()
        wheel_tag = (
            self.info.language_implementation_tag,
            self.info.abi_tag,
            self.info.platform_tag,
        )
        if wheel_tag not in supported_tags:
            return False
        return True

    def as_wheel(self, offline=False):
        path = get_wheel_path(self, offline)
        if not path:
            raise WheelNotFoundError(self.filename)
        return Wheel(path)


class UnwantedLink(ValueError):
    pass


# TODO: Maintain this list to support more formats.
WANTED_EXTENSIONS = [
    ('.whl', WheelDistributionLink),
    ('.tar.gz', SourceDistributionLink),
    ('.tar.bz2', SourceDistributionLink),
    ('.zip', SourceDistributionLink),
]


def _select_link_klass(filename):
    """Parse the file name to recognize an artifact type.

    This is important because we need to somehow handle the sdist .tar.gz
    extension. We also exclude packages we don't want here.
    """
    for ext, klass in WANTED_EXTENSIONS:
        if filename.endswith(ext):
            return functools.partial(
                klass,
                file_stem=filename[:-len(ext)],
                file_extension=ext,
            )
    raise UnwantedLink(filename)


def parse_link(url, python_specifier):
    if isinstance(url, six.string_types):
        parts = six.moves.urllib_parse.urlsplit(url)
    else:
        parts = url
    checksum = parts.fragment
    parts = parts._replace(fragment='')

    klass = _select_link_klass(parts.path.rsplit('/', 1)[-1])
    return klass(
        url=six.moves.urllib_parse.urlunsplit(parts),
        checksum=checksum, python_specifier=python_specifier,
    )
