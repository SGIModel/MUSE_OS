"""Various search-space filters.

Search-space filters return a modified matrix of booleans, with dimension
`(asset, replacement)`, where `asset` refer to technologies currently managed by
the agent, and `replacement` to all technologies the agent could consider, prior
to filtering.

Filters should be registered using the decorator :py:func:`register_filter`. The
registration makes it possible to call then from the agent by specifying the
`search_rule` attribute. The `search_rule` attribute is string or list of
strings specifying the filters to apply one after the other when considering the
search space.

Filters are not expected to modify any of their arguments. They should all
follow the same signature:

.. code-block:: Python

    @register_filter
    def search_space_filter(agent: Agent, search_space: DataArray,
                            technologies: Dataset, market: Dataset) -> DataArray:
        pass

Arguments:
    agent: the agent relevant to the search space. The filters may need to query
        the agent for parameters, e.g. the current year, the interpolation
        method, the tolerance, etc.
    search_space: the current search space.
    technologies: A data set characterising the technologies from which the
        agent can draw assets.
    market: Market variables, such as prices or current capacity and retirement
        profile.

Returns:
    A new search space with the same data-type as the input search-space, but
    with potentially different values.


In practice, an initial search space is created by calling a function with the signature
given below, and registered with :py:func:`register_initializer`. The initializer
function returns a search space which is passed on to a chain of filters, as done in the
:py:func:`factory` function.

Functions creating initial search spaces should have the following signature:

.. code-block:: Python

    @register_initializer
    def search_space_initializer(
        agent: Agent,
        demand: DataArray,
        technologies: Dataset,
        market: Dataset
    ) -> DataArray:
        pass

Arguments:
    agent: the agent relevant to the search space. The filters may need to query
        the agent for parameters, e.g. the current year, the interpolation
        method, the tolerance, etc.
    demand: share of the demand per existing reference technology (e.g.
        assets).
    technologies: A data set characterising the technologies from which the
        agent can draw assets.
    market: Market variables, such as prices or current capacity and retirement
        profile.

Returns:
    An initial search space
"""
__all__ = [
    "factory",
    "register_filter",
    "register_initializer",
    "identity",
    "similar_technology",
    "same_enduse",
    "same_fuels",
    "currently_existing_tech",
    "currently_referenced_tech",
    "maturity",
    "compress",
    "with_asset_technology",
    "initialize_from_technologies",
]

from typing import Callable, Mapping, MutableMapping, Optional, Sequence, Text, Union

from xarray import DataArray, Dataset

from muse.agent import Agent
from muse.registration import registrator

SSF_SIGNATURE = Callable[[Agent, DataArray, Dataset, Dataset], DataArray]
""" Search space filter signature """

SEARCH_SPACE_FILTERS: MutableMapping[Text, SSF_SIGNATURE] = {}
"""Filters for selecting technology search spaces."""


SSI_SIGNATURE = Callable[[Agent, DataArray, Dataset, Dataset], DataArray]
""" Search space initializer signature """

SEARCH_SPACE_INITIALIZERS: MutableMapping[Text, SSI_SIGNATURE] = {}
"""Functions to create an initial search-space."""


@registrator(registry=SEARCH_SPACE_FILTERS, loglevel="info")
def register_filter(function: SSF_SIGNATURE) -> Callable:
    """Decorator to register a function as a filter.

    Registers a function as a filter so that it can be applied easily
    when constraining the technology search-space.

    The name that the function is registered with defaults to the function name.
    However, it can also be specified explicitly as a *keyword* argument. In any
    case, it must be unique amongst all search-space filters.
    """
    from functools import wraps

    @wraps(function)
    def decorated(agent: Agent, search_space: DataArray, *args, **kwargs) -> DataArray:
        result = function(agent, search_space, *args, **kwargs)  # type: ignore
        if isinstance(result, DataArray):
            result.name = search_space.name
        return result

    return decorated


@registrator(
    registry=SEARCH_SPACE_INITIALIZERS, logname="initial search-space", loglevel="info"
)
def register_initializer(function: SSI_SIGNATURE) -> Callable:
    """Decorator to register a function as a search-space initializer."""
    from functools import wraps

    @wraps(function)
    def decorated(agent: Agent, *args, **kwargs) -> DataArray:
        result = function(agent, *args, **kwargs)  # type: ignore
        if isinstance(result, DataArray):
            result.name = "search_space"
        return result

    return decorated


def factory(
    settings: Optional[Union[Text, Mapping, Sequence[Union[Text, Mapping]]]] = None
):
    """Creates filters from input TOML data.

    The input data is standardized to a list of dictionaries where each dictionary
    contains at least one member, "name".

    The first dictionary specifies the initial function which creates the search space
    from the demand share, the market, and the dataset describing technologies in the
    sectors.

    The next entries are applied in turn and transform the search space in some way.
    In other words the process is more or less:

    .. code-block:: Python

        search_space = initial_filter(
            agent, demand, technologies=technologies, market=market
        )
        for afilter in filters:
            search_space = afilter(
                agent, search_space, technologies=technologies, market=market
            )
        return search_space

    ``initial_filter`` is simply first filter given on input, if that filter is
    registered with :py:func:`register_initializer`. Otherwise,
    :py:func:`initialize_from_technologies` is automatically inserted.
    """
    from typing import List, Dict
    from functools import partial

    if settings is None:
        settings = []
    elif isinstance(settings, (Text, Mapping)):
        settings = [settings]
    if len(settings) == 0:
        settings = [{"name": "initialize_from_technologies"}]

    parameters: List[Dict] = [
        {"name": item} if isinstance(item, Text) else dict(**item) for item in settings
    ]
    if parameters[0]["name"] not in SEARCH_SPACE_INITIALIZERS:
        parameters = [{"name": "initialize_from_technologies"}] + parameters

    initial_settings, parameters = parameters[0], parameters[1:]

    functions = [
        partial(
            SEARCH_SPACE_INITIALIZERS[initial_settings["name"]],
            **{k: v for k, v in initial_settings.items() if k != "name"}
        ),
        *(
            partial(
                SEARCH_SPACE_FILTERS[setting["name"]],
                **{k: v for k, v in setting.items() if k != "name"}
            )
            for setting in parameters
        ),
    ]

    def filters(agent: Agent, demand: DataArray, *args, **kwargs) -> DataArray:
        """Applies a series of filter to determine the search space."""
        result = demand
        for function in functions:
            result = function(agent, result, *args, **kwargs)
        return result

    return filters


@register_filter
def same_enduse(
    agent: Agent,
    search_space: DataArray,
    technologies: Dataset,
    *args,
    enduse_label: Text = "service",
    **kwargs
) -> DataArray:
    """Only allow for technologies with at least the same end-use."""
    from muse.commodities import is_enduse

    tech_enduses = agent.filter_input(
        technologies.fixed_outputs,
        year=agent.year,
        commodity=is_enduse(technologies.comm_usage),
    )
    tech_enduses = (tech_enduses > 0).astype(int).rename(technology="replacement")
    asset_enduses = tech_enduses.sel(replacement=search_space.asset)
    return search_space & ((tech_enduses - asset_enduses) >= 0).all("commodity")


@register_filter(name="all")
def identity(agent: Agent, search_space: DataArray, *args, **kwargs) -> DataArray:
    """Returns search space as given."""
    return search_space


@register_filter(name="similar")
def similar_technology(
    agent: Agent, search_space: DataArray, technologies: Dataset, *args, **kwargs
):
    """Filters technologies with the same type."""
    tech_type = agent.filter_input(technologies.tech_type)
    asset_types = tech_type.sel(technology=search_space.asset)
    tech_types = tech_type.sel(technology=search_space.replacement)
    return search_space & (asset_types == tech_types)


@register_filter(name="fueltype")
def same_fuels(
    agent: Agent, search_space: DataArray, technologies: Dataset, *args, **kwargs
):
    """Filters technologies with the same fuel type."""
    fuel = agent.filter_input(technologies.fuel)
    asset_fuel = fuel.sel(technology=search_space.asset)
    tech_fuel = fuel.sel(technology=search_space.replacement)
    return search_space & (asset_fuel == tech_fuel)


@register_filter(name="existing")
def currently_existing_tech(
    agent: Agent, search_space: DataArray, technologies: Dataset, market: Dataset
) -> DataArray:
    """Only consider technologies that currently exist in the market.

    This filter only allows technologies that exists in the market and have non-
    zero capacity in the current year. See `currently_referenced_tech` for a
    similar filter that does not check the capacity.
    """
    capacity = agent.filter_input(market.capacity, year=agent.year).rename(
        technology="replacement"
    )
    result = search_space & search_space.replacement.isin(capacity.replacement)
    both = (capacity.replacement.isin(search_space.replacement)).replacement
    result.loc[{"replacement": both.values}] &= capacity.sel(
        replacement=both
    ) > getattr(agent, "tolerance", 1e-8)
    return result


@register_filter
def currently_referenced_tech(
    agent: Agent, search_space: DataArray, technologies: Dataset, market: Dataset
) -> DataArray:
    """Only consider technologies that are currently referenced in the market.

    This filter will allow any technology that exists in the market, even if it
    currently sits at zero capacity (unlike `currently_existing_tech` which
    requires non-zero capacity in the current year).
    """
    capacity = agent.filter_input(market.capacity, year=agent.year).rename(
        technology="replacement"
    )
    return search_space & search_space.replacement.isin(capacity.replacement)


@register_filter
def maturity(
    agent: Agent,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    enduse_label: Text = "service",
    **kwargs
) -> DataArray:
    """Only allows technologies that have achieve a given market share.

    Specifically, the market share refers to the capacity for each end- use.
    """
    from muse.commodities import is_enduse

    capacity = agent.filter_input(market.capacity, year=agent.year)
    outputs = agent.filter_input(
        technologies.fixed_outputs,
        year=agent.year,
        commodity=is_enduse(technologies.comm_usage),
    )
    enduse_production = (capacity * outputs).sum("technology")
    enduse_market_share = agent.maturity_threshhold * enduse_production

    return search_space & (enduse_market_share <= capacity).all("commodity")


@register_filter
def compress(
    agent: Agent,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    **kwargs
) -> DataArray:
    """Compress search space to include only potential technologies.

    This operation reduces the *size* of the search space along the
    `replacement` dimension, such that are left only technologies that
    will be considered as replacement for at least by one asset. Unlike
    most filters, it does not change the data, but rather changes how
    the data is represented. In other words, this is mostly an
    *optimization* for later steps, to avoid unnecessary computations.
    """
    return search_space.sel(replacement=search_space.any("asset"))


@register_filter
def with_asset_technology(
    agent: Agent,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    **kwargs
) -> DataArray:
    """Search space *also* contains its asset technology for each asset."""
    return search_space | (search_space.asset == search_space.replacement)


@register_initializer
def initialize_from_technologies(
    agent: Agent, demand: DataArray, technologies: Dataset, *args, **kwargs
):
    """Initialize a search space from existing technologies."""
    from numpy import ones

    not_assets = [u for u in demand.dims if u != "asset"]
    condtechs = demand.sum(not_assets) > getattr(agent, "tolerance", 1e-8)
    coords = (
        ("asset", demand.asset[condtechs].values),
        ("replacement", technologies.technology.values),
    )
    return DataArray(
        ones(tuple(len(u[1]) for u in coords), dtype=bool),
        coords=coords,
        dims=[u[0] for u in coords],
        name="search_space",
    )