"""Tests for yFiles layout dispatch across the 1.x/2.x API split.

``yfiles-jupyter-graphs`` 2.0 renamed ``hierarchic_layout`` to
``hierarchical_layout``. holonic's viz widgets called the 1.x name
unconditionally, so every hierarchic render raised ``AttributeError`` once
the lock moved to 2.0 -- caught only by executing notebook 13, since nothing
in the unit suite touches the layout call.

These tests use stub widgets rather than a real ``GraphWidget``, so they run
without yfiles installed and pin the dispatch behaviour for *both* majors
regardless of which one the environment happens to have.
"""

from __future__ import annotations

import pytest

from holonic.viz._layout import LAYOUT_METHODS, apply_layout


class _Yfiles2Widget:
    """Stub exposing only the yfiles 2.x spelling."""

    def __init__(self) -> None:
        self.called: list[str] = []

    def hierarchical_layout(self) -> None:
        self.called.append("hierarchical_layout")

    def organic_layout(self) -> None:
        self.called.append("organic_layout")

    def circular_layout(self) -> None:
        self.called.append("circular_layout")

    def tree_layout(self) -> None:
        self.called.append("tree_layout")


class _Yfiles1Widget:
    """Stub exposing only the yfiles 1.x spelling."""

    def __init__(self) -> None:
        self.called: list[str] = []

    def hierarchic_layout(self) -> None:
        self.called.append("hierarchic_layout")

    def organic_layout(self) -> None:
        self.called.append("organic_layout")


class TestApplyLayout:
    def test_hierarchic_token_uses_2x_method(self):
        w = _Yfiles2Widget()
        apply_layout(w, "hierarchic")
        assert w.called == ["hierarchical_layout"]

    def test_hierarchic_token_falls_back_to_1x_method(self):
        w = _Yfiles1Widget()
        apply_layout(w, "hierarchic")
        assert w.called == ["hierarchic_layout"], (
            "On yfiles 1.x the legacy `hierarchic_layout` spelling must still "
            "be used; holonic supports both majors."
        )

    def test_hierarchical_alias_accepted(self):
        w = _Yfiles2Widget()
        apply_layout(w, "hierarchical")
        assert w.called == ["hierarchical_layout"]

    @pytest.mark.parametrize("token", ["organic", "circular", "tree"])
    def test_unrenamed_layouts_dispatch_directly(self, token):
        w = _Yfiles2Widget()
        apply_layout(w, token)
        assert w.called == [f"{token}_layout"]

    def test_unknown_token_raises(self):
        # The previous if/elif chain fell through in silence, rendering the
        # default layout and hiding the caller's typo.
        with pytest.raises(ValueError, match="unknown layout"):
            apply_layout(_Yfiles2Widget(), "spiral")

    def test_unsupported_by_installed_version_raises(self):
        w = _Yfiles1Widget()  # has no tree_layout
        with pytest.raises(ValueError, match="not supported by the installed"):
            apply_layout(w, "tree")

    def test_widget_dropdown_options_are_all_dispatchable(self):
        # The viz widgets offer these four in their layout dropdowns; each
        # must be a known token or the dropdown can raise on selection.
        for token in ("hierarchic", "organic", "circular", "tree"):
            assert token in LAYOUT_METHODS
