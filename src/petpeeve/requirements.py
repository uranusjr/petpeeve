import collections
import re
import warnings

from pip._vendor import six
from pip._vendor.packaging.markers import Marker
from pip._vendor.packaging.requirements import Requirement as BaseRequirement


# I heard Warehouse and Wheel always put the extra marker at the end, and the
# operator is always ==, so we cheat a little (a lot?) here.
EXTRA_RE = re.compile(
    r"""^(?P<requirement>.+?)(?:extra\s*==\s*['"](?P<extra>.+?)['"])$""",
)


class Requirement(BaseRequirement):
    """Extended requirement representation.

    This adds helper functions to the basic requirement class, and makes it
    hashable and works in a set.
    """
    @classmethod
    def parse(cls, s):
        """Parse both modern and "legacy" requirement styles.

        Old requirements append the extra key at the end of the environment
        markers, e.g.::

            PySocks (!=1.5.7,>=1.5.6); extra == 'socks'

        This uses a very naive pattern-matching logic to strip that last part
        out of the environment markers.

        This kind of formats are used in old wheels and the PyPI's JSON API.

        Returns a 2-tuple `(requirement, extra)`. The first member is a
        `Requirement` instance, and the second the extra's name. If no extra is
        detected, the second member will be `None`.
        """
        requirement = cls(s)
        if not requirement.marker:  # Short circuit to favour the common case.
            return requirement, None
        match = EXTRA_RE.match(s)
        if not match:   # No final "extra" expression, yay.
            return requirement, None
        extra = match.group('extra')
        if not extra:
            return requirement, None
        s = match.group('requirement').rstrip()
        if s.endswith('and'):
            s = s[:-3].rstrip()
        if s.endswith(';'):
            s = s[:-1].rstrip()
        return cls(s), extra

    def __hash__(self):
        return hash(str(self))

    def __eq__(self, other):
        return str(self) == str(other)


def _add_requires(entry, base, extras):
    """Append all requirements in an entry to the list.

    This combines the `environment` key's content into the requirement's
    existing markers, and add them to the appropriate list(s).
    """
    requires = entry.get('requires')
    if not requires:
        return
    environment = entry.get('environment')
    e_extra = entry.get('extra')
    for s in requires:
        r, r_extra = Requirement.parse(s)
        if environment:
            if r.marker:
                m = Marker('({}) and ({})'.format(environment, r.marker))
            else:
                m = Marker(environment)
            r.marker = m
        if not e_extra and not r_extra:
            base.add(r)
        elif e_extra:
            extras[e_extra].add(r)
        elif r_extra:
            extras[r_extra].add(r)


class RequirementSpecification(object):
    """A representation of dependencies of a distribution.

    This representation is abstract, i.e. completely independent from the
    execution environment. Our resolver needs this to give a machine-agnostic
    dependency tree.
    """
    def __init__(self, base, extras):
        self.base = base
        self.extras = extras
        # TODO: We probably want to include some other metadata as well?

    @classmethod
    def empty(cls):
        return cls([], {})

    @classmethod
    def from_wheel(cls, wheel):
        """Build a dependency set from a wheel.

        `wheel` is a `distlib.wheel.Wheel` instance. The metadata is read to
        build the instance.
        """
        base = set()
        extras = collections.defaultdict(set)
        for entry in wheel.metadata.run_requires:
            if isinstance(entry, six.text_type):
                entry = {'requires': [entry]}
            _add_requires(entry, base, extras)
        return cls(base, extras)

    @classmethod
    def from_data(cls, requires_dist):
        """Build a dependency set with data obtained from an API.

        `requires_dist` is a sequence, e.g. decoded from a JSON API.
        """
        base = set()
        extras = collections.defaultdict(set)
        for s in requires_dist:
            requirement, extra = Requirement.parse(s)
            if not extra:
                base.add(requirement)
            else:
                extra_reqs = extras[extra]
                extra_reqs.add(requirement)
                extras[extra] = extra_reqs
        return cls(base, extras)

    def get_dependencies(self, extras):
        deps = set(self.base)
        if not extras:
            return deps
        for extra in extras:
            try:
                extra_deps = self.extras[extra]
            except KeyError:
                warnings.warn('dropping unknown extra {!r} for {}'.format(
                    extra, self,
                ))
            else:
                deps.update(extra_deps)
        return deps
