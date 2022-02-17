"""Output cached quantities

Functions that output the state of diverse quantities at intermediate steps of the
calculation.

The core of the method is the OutputCache class that initiated by the MCA with input
parameters defined in the TOML file, much like the existing 'output' options but in a
'output_cache' list, enables a channel to "listen" for data to be cached and, after each
period, saved into disk via the 'consolidate_cache' method.

Anywhere in the code, you can write:

.. code-block:: python

    pub.sendMessage("cache_quantity", quantity=quantity_name, data=some_data)

If the quantity has been set as something to cache, the data will be stored and,
eventually, save to disk after - possibly - agregating the data and remove those entries
corresponding to non-convergent investment attempts. This process of cleaning and
aggregation is quantity specific.
"""
from __future__ import annotations

from typing import (
    List,
    Mapping,
    Text,
    Union,
    Callable,
    Optional,
    MutableMapping,
    Sequence,
)

from pubsub import pub
import xarray as xr
import pandas as pd

from muse.registration import registrator


OUTPUT_QUANTITY_SIGNATURE = Callable[
    [List[xr.DataArray]], Union[xr.DataArray, pd.DataFrame]
]
"""Signature of functions computing quantities for later analysis."""

OUTPUT_QUANTITIES: MutableMapping[Text, OUTPUT_QUANTITY_SIGNATURE] = {}
"""Quantity for post-simulation analysis."""

CACHE_TOPIC_CHANNEL = "cache_quantity"
"""Topic channel to use with the pubsub messaging system."""


@registrator(registry=OUTPUT_QUANTITIES)
def register_output_quantity(function: OUTPUT_QUANTITY_SIGNATURE) -> Callable:
    """Registers a function to compute an output quantity."""
    from functools import wraps

    @wraps(function)
    def decorated(*args, **kwargs):
        result = function(*args, **kwargs)
        if isinstance(result, (pd.DataFrame, xr.DataArray)):
            result.name = function.__name__
        return result

    return decorated


def cache_quantity(
    function: Optional[Callable] = None,
    quantity: Union[str, Sequence[str], None] = None,
    **kwargs: xr.DataArray,
) -> Callable:
    """Cache one or more quantities to be post-processed later on.

    This function can be used as a decorator, in which case the quantity input argument
    must be set, or directly called with any number of keyword arguments. In the former
    case, the matching between quantities and values to cached is done by the function
    'match_quantities'. When used in combination with other decorators, care must be
    taken to decide the order in which they are applied to make sure the approrpriate
    output is cached.

    Note that if the quantity has NOT been selected to be cached when configuring the
    MUSE simulation, it will be silently ignored if present as an input to this
    function.

    Example:
        As a decorator, the quantity argument must be set:

        >>> @cache_quantity(quantity="capacity")
        >>> def some_calculation():
        ...     return xr.DataArray()

        If returning a sequence of DataArrays, the number of quantities to record must
        be the same as the number of arrays. They are paired in the same order they are
        given and the 'name' attribute of the arrays, if present, is ignored.

        >>> @cache_quantity(quantity=["capacity", "production"])
        >>> def other_calculation():
        ...     return xr.DataArray(), xr.DataArray()

        For a finer control of what is cached when there is a complex output, combine
        the DataArrays in a Dataset. In this case, the 'quantity' input argument can be
        either a string or a sequence of strings to record multiple variables in the
        Dataset.

        >>> @cache_quantity(quantity=["capacity", "production"])
        >>> def and_another_one():
        ...     return xr.Dataset(
        ...         {
        ...             "not cached": xr.DataArray(),
        ...             "capacity": xr.DataArray(),
        ...             "production": xr.DataArray(),
        ...         }
        ...     )

        When this function is called directly and not used as a decorator, simply
        provide the name of the quantities and the DataArray to record as keyword
        arguments:

        >>> cache_quantity(capacity=xr.DataArray(), production=xr.DataArray())

    Args:
        function (Optional[Callable]): The decorated function, if any. Its output must
            be a DataArray, a sequence of DataArray or a Dataset. See 'match_quantities'
        quantity (Union[str, List[str], None]): The name of the quantities to record.
        **kwargs (xr.DataArray): Keyword arguments of the form
            'quantity_name=quantity_value'.

    Raises:
        ValueError: If a function input argument is provided at the same time than
        keyword arguments.

    Return:
        (Callable) The decorated function (or a dummy function if called directly).
    """
    from functools import wraps

    # When not used as a decorator
    if len(kwargs) > 0:
        if function is not None:
            raise ValueError(
                "If keyword arguments are provided, then 'function' must be None"
            )
        pub.sendMessage(CACHE_TOPIC_CHANNEL, data=kwargs)
        return lambda: None

    # When used as a decorator
    if function is None:
        return lambda x: cache_quantity(x, quantity=quantity)

    if quantity is None:
        raise ValueError(
            "When 'cache_quantity' is used as a decorator the 'quantity' input argument"
            " must be a string or sequence of strings. None found."
        )

    @wraps(function)
    def decorated(*args, **kwargs):
        result = function(*args, **kwargs)
        cache_quantity(**match_quantities(quantity, result))
        return result

    return decorated


def match_quantities(
    quantity: Union[str, Sequence[str]],
    data: Union[xr.DataArray, xr.Dataset, Sequence[xr.DataArray]],
) -> Mapping[str, xr.DataArray]:
    """Matches the quantities with the corresponding data.

    The possible name attribute in the DataArrays is ignored.

    Args:
        quantity (Union[str, Sequence[str]]): The name(s) of the quantity(ies) to cache.
        data (Union[xr.DataArray, xr.Dataset, Sequence[xr.DataArray]]): The structure
            containing the data to cache.

    Raises:
        TypeError: If there is an invalid combination of input argument types.
        ValueError: If the number of quantities does not match the length of the data.
        KeyError: If the required quantities do not exist as variables in the dataset.

    Returns:
        (Mapping[str, xr.DataArray]) A dictionary matching the quantity names with the
        corresponding data.
    """
    if isinstance(quantity, Text) and isinstance(data, xr.DataArray):
        return {quantity: data}

    elif isinstance(quantity, Text) and isinstance(data, xr.Dataset):
        return {quantity: data[quantity]}

    elif isinstance(quantity, Sequence) and isinstance(data, xr.Dataset):
        return {q: data[q] for q in quantity}

    elif isinstance(quantity, Sequence) and isinstance(data, Sequence):
        if len(quantity) != len(data):
            msg = f"{len(quantity)} != {len(data)}"
            raise ValueError(
                f"The number of quantities does not match the length of the data {msg}."
            )
        return {q: v for q, v in zip(quantity, data)}

    else:
        msg = f"{type(quantity)} and {type(data)}"
        raise TypeError(f"Invalid combination of input argument types {msg}")


class OutputCache:
    """Creates outputs functions for post-mortem analysis of cached quantities.

    Each parameter is a dictionary containing the following:

    - quantity (mandatory): name of the quantity to output. Mandatory.
    - sink (optional): name of the storage procedure, e.g. the file format
      or database format. When it cannot be guessed from `filename`, it defaults to
      "csv".
    - filename (optional): path to a directory or a file where to store the quantity. In
      the latter case, if sink is not given, it will be determined from the file
      extension. The filename can incorporate markers. By default, it is
      "{default_output_dir}/{sector}{year}{quantity}{suffix}".
    - any other parameter relevant to the sink, e.g. `pandas.to_csv` keyword
      arguments.

    For simplicity, it is also possible to given lone strings as input.
    They default to `{'quantity': string}` (and the sink will default to
    "csv").

    Raises:
        ValueError: If unknown quantities are requested to be cached.
    """

    def __init__(
        self,
        *parameters: Mapping,
        output_quantities: Optional[
            MutableMapping[Text, OUTPUT_QUANTITY_SIGNATURE]
        ] = None,
        topic: str = CACHE_TOPIC_CHANNEL,
    ):
        from muse.outputs.sector import _factory

        output_quantities = (
            OUTPUT_QUANTITIES if output_quantities is None else output_quantities
        )

        missing = [
            p["quantity"] for p in parameters if p["quantity"] not in output_quantities
        ]

        if len(missing) != 0:
            raise ValueError(
                f"There are unknown quantities to cache: {missing}. "
                f"Valid quantities are: {list(output_quantities.keys())}"
            )

        self.to_save: Mapping[str, List[xr.DataArray]] = {
            p["quantity"]: [] for p in parameters if p["quantity"] in output_quantities
        }

        self.factory: Mapping[str, Callable] = {
            p["quantity"]: _factory(output_quantities, p, sector_name="Cache")
            for p in parameters
            if p["quantity"] in self.to_save
        }

        pub.subscribe(self.cache, topic)

    def cache(self, data: Mapping[str, xr.DataArray]) -> None:
        """Caches the data into memory.

        If the quantity has not been selected to be cached when configuring the
        MUSE simulation, it will be silently ignored if present as an input to this
        function.

        Args:
            data (Mapping[str, xr.DataArray]): Dictionary with the quantities and
            DataArray values to save.
        """
        for quantity, value in data.items():
            if quantity not in self.to_save:
                continue
            self.to_save[quantity].append(value.copy())

    def consolidate_cache(self, year: int) -> None:
        """Save the cached data into disk and flushes cache.

        This method is meant to be called after each time period in the main loop of the
        MCA, just after market quantities are saved.

        Args:
            year (int): Year being simulated.
        """
        for quantity, cache in self.to_save.items():
            if len(cache) == 0:
                continue
            self.factory[quantity](cache, year=year)
        self.to_save = {q: [] for q in self.to_save}


@register_output_quantity
def capacity(cached: List[xr.DataArray]) -> xr.DataArray:
    """Consolidates the cached capacities into a single DataArray to save."""
    pass


@register_output_quantity
def production(cached: List[xr.DataArray]) -> xr.DataArray:
    """Consolidates the cached production into a single DataArray to save."""
    pass


@register_output_quantity
def lcoe(cached: List[xr.DataArray]) -> xr.DataArray:
    """Consolidates the cached LCOE into a single DataArray to save."""
    pass
