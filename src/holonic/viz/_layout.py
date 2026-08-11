"""yFiles layout dispatch, tolerant of the 1.x/2.x API split.

``yfiles-jupyter-graphs`` 2.0 moved layout selection onto a ``graph_layout``
property and renamed one convenience method: ``hierarchic_layout`` became
``hierarchical_layout`` (``Layout.HIERARCHICAL``). ``organic_layout``,
``circular_layout``, and ``tree_layout`` survive under their 1.x names, so
the hierarchic case is the only one that breaks outright -- as an
``AttributeError`` at render time, not at import.

holonic keeps ``"hierarchic"`` as its own public layout token (it appears in
example notebooks and in the ``options=[...]`` dropdowns of every viz
widget); this module is the single place that maps holonic's tokens onto
whichever method names the installed yFiles actually provides.
"""

from __future__ import annotations

from typing import Any

# holonic layout token -> candidate yFiles method names, most-current first.
# Both spellings of the hierarchic layout are listed so a single install of
# either major version resolves without a version check.
LAYOUT_METHODS: dict[str, tuple[str, ...]] = {
    "hierarchic": ("hierarchical_layout", "hierarchic_layout"),
    "hierarchical": ("hierarchical_layout", "hierarchic_layout"),
    "organic": ("organic_layout",),
    "circular": ("circular_layout",),
    "tree": ("tree_layout",),
    "orthogonal": ("orthogonal_layout",),
    "radial": ("radial_layout",),
}


def apply_layout(widget: Any, layout: str) -> None:
    """Apply a named layout algorithm to a yFiles ``GraphWidget``.

    Parameters
    ----------
    widget :
        A ``yfiles_jupyter_graphs.GraphWidget``.
    layout :
        A holonic layout token -- one of the keys of :data:`LAYOUT_METHODS`.

    Raises:
    ------
    ValueError
        If ``layout`` is not a known token, or if none of the candidate
        methods exist on the widget. The previous ``if/elif`` chain fell
        through in silence on an unknown token, rendering the default
        layout and leaving the caller to wonder why their choice was
        ignored.

    .. versionadded:: 0.8.0
    """
    try:
        candidates = LAYOUT_METHODS[layout]
    except KeyError:
        raise ValueError(
            f"unknown layout {layout!r}; expected one of {', '.join(sorted(LAYOUT_METHODS))}"
        ) from None

    for name in candidates:
        method = getattr(widget, name, None)
        if method is not None:
            method()
            return

    raise ValueError(
        f"layout {layout!r} is not supported by the installed "
        f"yfiles-jupyter-graphs (tried: {', '.join(candidates)})"
    )


__all__ = ["LAYOUT_METHODS", "apply_layout"]
