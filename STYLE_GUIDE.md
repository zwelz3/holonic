# RDF Style Guide

Tbd...

# Python Code Style Guide

## Baseline

- We try to abide by strong recommendations in [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- We use [ruff](https://github.com/astral-sh/ruff) for automated style checks
- We use [mypy](https://github.com/python/mypy) to check typing

## Style

Instead of listing all the possible rules, here are the most important rules for contributing:

### Be Pythonic

1. Prefer testing the emptiness of iterables using truthiness: `if some_list`, not `if len(some_list) > 0`
2. Do not use truthiness for zero value checking, though: `if x%2==0`, e.g.
3. Test explicitly for `is None` when applicable.
4. Use comprehensions.
5. Use `enumerate` for iterations that also need an index. Use `zip` instead if you were going to use that index to match another iterable.
6. Inline `... if ... else ...` are preferred if they fit.
7. Do not use `var=[]` or `var={}` as a default argument (see number 3).

### Function Naming and Inputs

It's preferable to use longer variable and function names that make it clear what is happening.

A function with a name like `get_actors_from_area()` is preferred to `area_actors()`, for example.

Similarly, `get_actors_from_hill_areas()` is preferred to `get_actors_from_areas(area_type="hill")`.

An alternative would be to use `Enum` values as an input, rather than strings or booleans, to express the possible values a function or method could take. `get_actors_from_area(AREAS.HILL)` is expressive and explicit, and autocomplete/mypy will help the user avoid bugs.

### Prefer Dictionaries and Dataclasses

If your proposed feature will hand data to the user, rather than returning a tuple:

```python
def some_function() -> tuple[float,...]:
    return a, b, c
```

If it makes sense, return an object that contains information about what you are returning:

```python
@dataclass
class Measurement:
    time: float
    distance: float
    probability: float

def other_function() -> Measurement:
    return Measurement(a, b, c)
```

While docstrings should have this information regardless, it's often helpful to let tab-completion point the user to what they are looking for.

## Dependencies

Tbd

## Docstrings

Docstrings must follow the ``google`` documentation [style guide](https://google.github.io/styleguide/pyguide.html).

More information can be found [here](https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html).

Docstring code is not tested (see `Testing` below), but please provide enough information to show how to use a feature.

## Linting and Typing

The project uses ``ruff`` to check for style in code and docstrings.  Please review the output of the style report in the pipeline before submitting a pull request.

The ``ruff`` report is not a guarantee that the style of the code and the documentation abides by the rules of this style guide, or consistency with other features, and we may ask for small changes to unify the style.

Typing is checked through `mypy`. In many cases, `Any` is fine, especially when passing through user values from a simulation. If possible, keeping the types simple (dataclasses help!) is preferred.

## Testing

Testing is done using `pytest`. Fixtures and parametrization are preferred, if possible, but not required.

Docstrings are not tested. This is because more than a few lines of code are generally required to set up and run any feature, which would make docstrings unreadably long. Write tests for your feature that match the docstring as close as possible. We find that writing a test, then including the test in the Sphinx documentation is a reasonable balance for demonstrating and verifying features.
