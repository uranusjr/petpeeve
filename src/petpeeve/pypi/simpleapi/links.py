import collections
import functools
import sys
import warnings

from pip._vendor.packaging import version as packaging_version

from wheel import pep425tags


def is_specified(specifier, version):
    for _ in specifier.filter([version]):
        return True
    return False


class Link(object):
    """Represents a link in the simple API page.
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

    def is_version_specified(self, requirement):
        try:
            version = self.info.version
        except AttributeError:
            return True
        if not is_specified(requirement.specifier, version):
            return False
        return True

    def is_python_compatible(self, python_version_info):
        """Check if the requires-python info matches specified environment.

        If `python_version_info` is truthy, should be a 3+-tuple (e.g.
        ``sys.version_info``). If falsy, result is always `True`.
        """
        if python_version_info:
            python_version = packaging_version.parse('.'.join(
                str(i) for i in python_version_info[:3]
            ))
            if not is_specified(self.python_specifier, python_version):
                return False
        return True

    def as_wheel(self):
        """Build a representation of a local wheel artifact with the link.

        The return value should probably be distlib.wheel.Wheel? I don't know.
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

    def as_wheel(self):
        # 1. Download the wheel (use the wheel cache if possible)
        # 2. Build an ephemeral wheel. (How do we clean this up?)
        # 3. Wrap the wheel.
        pass


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

    def as_wheel(self):
        # 1. Download the wheel (use the wheel cache if possible)
        # 2. Wrap it.
        pass


class UnwantedLink(ValueError):
    pass


WANTED_EXTENSIONS = [
    ('.whl', WheelDistributionLink),
    ('.tar.gz', SourceDistributionLink),
    ('.tar.bz2', SourceDistributionLink),
    ('.zip', SourceDistributionLink),
]


def select_link_constructor(filename):
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
