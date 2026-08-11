"""Exception hierarchy (0.8.0, audit finding A1).

Every library-specific exception derives from :class:`HolonicError` so
downstream code can catch the whole family uniformly, while still deriving from
the builtin base it historically subclassed so pre-0.8.0 handlers keep working.
"""

from holonic import (
    HolonicError,
    MembraneBreachError,
    MembraneHealth,
    SealedPortalError,
)
from holonic.backends._fuseki_client import FusekiError
from holonic.model import MembraneResult
from holonic.plugins import TransformNotFoundError


def test_holonic_error_is_exception() -> None:
    assert issubclass(HolonicError, Exception)


def test_every_library_exception_is_a_holonic_error() -> None:
    for exc in (
        MembraneBreachError,
        SealedPortalError,
        FusekiError,
        TransformNotFoundError,
    ):
        assert issubclass(exc, HolonicError), exc


def test_builtin_bases_are_preserved_for_backward_compatibility() -> None:
    # Each exception kept the builtin base that existing ``except`` clauses
    # (written before 0.8.0 introduced HolonicError) rely on.
    assert issubclass(SealedPortalError, ValueError)
    assert issubclass(FusekiError, RuntimeError)
    assert issubclass(TransformNotFoundError, KeyError)


def test_sealed_portal_error_still_caught_as_value_error() -> None:
    try:
        raise SealedPortalError("urn:portal:sealed")
    except ValueError as exc:  # legacy handler shape
        assert isinstance(exc, HolonicError)
    else:  # pragma: no cover
        raise AssertionError("SealedPortalError was not caught as ValueError")


def test_transform_not_found_still_caught_as_key_error() -> None:
    try:
        raise TransformNotFoundError("missing")
    except KeyError as exc:  # legacy handler shape
        assert isinstance(exc, HolonicError)
    else:  # pragma: no cover
        raise AssertionError("TransformNotFoundError was not caught as KeyError")


def test_membrane_breach_error_is_holonic_error_at_raise_time() -> None:
    result = MembraneResult(
        holon_iri="urn:holon:x",
        conforms=False,
        health=MembraneHealth.COMPROMISED,
        report_text="",
        violations=["urn:holon:x violates sh:minCount"],
    )
    try:
        raise MembraneBreachError(result)
    except HolonicError as exc:
        assert isinstance(exc, MembraneBreachError)
        assert exc.result is result
    else:  # pragma: no cover
        raise AssertionError("MembraneBreachError was not caught as HolonicError")
