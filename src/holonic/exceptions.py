"""Exception hierarchy for the holonic library.

Every exception the library raises deliberately derives from
:class:`HolonicError`, so downstream code can catch the whole family with a
single ``except HolonicError`` while still catching individual errors by their
long-standing builtin bases (``ValueError``, ``RuntimeError``, ``KeyError``).

The concrete exceptions live next to the code that raises them
(:mod:`holonic.model`, :mod:`holonic.plugins`,
:mod:`holonic.backends._fuseki_client`); each mixes in :class:`HolonicError`
alongside the builtin it already subclassed, so existing ``except ValueError``
/ ``except KeyError`` / ``except RuntimeError`` handlers keep working.

.. versionadded:: 0.8.0
   Introduced the common :class:`HolonicError` base. This is additive --
   pre-0.8.0 handlers that caught the builtin bases are unaffected.
"""

from __future__ import annotations


class HolonicError(Exception):
    """Base class for every exception raised by the holonic library.

    Catch this to handle any library-specific failure uniformly::

        try:
            ds.traverse(source, target, fail_on_breach=True)
        except HolonicError:
            ...  # membrane breach, sealed portal, backend error, etc.
    """
