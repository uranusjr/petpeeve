import posixpath
import warnings

from pip._vendor import requests, six
from pip._vendor.packaging import specifiers as packaging_specifiers

from petpeeve._compat.functools import lru_cache
from petpeeve.dependencies import DependencySet

from ..exceptions import APIError, PackageNotFound
from .links import select_link_constructor, UnwantedLink


class SimplePageParser(six.moves.html_parser.HTMLParser):
    """Parser to scrap links from a simple API page.
    """
    def __init__(self, base_url):
        # Can't use super() because HTMLParser was an old-style class.
        six.moves.html_parser.HTMLParser.__init__(self)
        self.base_url_parts = six.moves.urllib_parse.urlsplit(base_url)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return
        url_parts = None
        python_specifier = packaging_specifiers.SpecifierSet('')
        for attr, value in attrs:
            if attr == 'href':
                url_parts = six.moves.urllib_parse.urlsplit(value)
                checksum = url_parts.fragment
                url_parts = url_parts._replace(fragment='')
            elif attr == 'data-requires-python':
                python_specifier = packaging_specifiers.SpecifierSet(value)
        if not url_parts:
            return
        try:
            replacements = {
                fn: part
                for fn, part in zip(url_parts._fields, url_parts)
                if part or fn == 'fragment'
            }
            url = six.moves.urllib_parse.urlunsplit(
                self.base_url_parts._replace(**replacements),
            )
            link_ctor = select_link_constructor(url.rsplit('/', 1)[-1])
        except UnwantedLink:
            return
        self.links.append(link_ctor(
            url=url, checksum=checksum,
            python_specifier=python_specifier,
        ))


PYPI_PAGE_CACHE_SIZE = 64   # Should be reasonable?


def _link_sort_key(link):
    try:
        is_binary_compatible = link.is_binary_compatible
    except AttributeError:
        return 0
    return 1 if is_binary_compatible() else -1


class IndexServer(object):

    def __init__(self, base_url):
        self.base_url = base_url

    @lru_cache(maxsize=PYPI_PAGE_CACHE_SIZE)
    def _get_package_links(self, package):
        """Get links on a simple API page.
        """
        url = posixpath.join(self.base_url, package)
        response = requests.get(url)
        if response.status_code == 404:
            raise PackageNotFound(package)
        elif not response.ok:
            raise APIError(response.reason)
        parser = SimplePageParser(base_url=self.base_url)
        parser.feed(response.text)
        return parser.links

    def get_links(self, candidate):
        return sorted((
            link for link in self._get_package_links(candidate.name)
            if link.info.version == candidate.version
        ), key=_link_sort_key)

    def get_dependencies(self, candidate, offline=False):
        """Discover dependencies for this candidate.

        Returns a collection of :class:`packaging.requirements.Requirement`
        instances, specifying dependencies of this candidate.
        """
        for link in self.get_links(candidate):
            wheel = link.as_wheel(offline=offline)
            if not wheel:
                continue
            return DependencySet.from_wheel(wheel)
        warnings.warn('failed to find dependencies with the Simple API')
        return []