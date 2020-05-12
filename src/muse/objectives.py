"""Valuation functions for replacement technologies.

.. currentmodule:: muse.objectives

Objectives are used to compare replacement technologies. They should correspond to
a single well defined economic concept. Multiple objectives can later be combined
via decision functions.

Objectives should be registered via the
:py:func:`@register_objective<register_objective>` decorator. This makes it possible to
refer to them by name in agent input files, and nominally to set extra input parameters.

The :py:func:`factory` function creates a function that calls all objectives defined in
its input argument and returns a dataset with each objective as a separate data array.

Objectives are not expected to modify their arguments. Furthermore they should
conform the following signatures:

.. code-block:: Python

    @register_objective
    def comfort(
        agent: Agent,
        demand: DataArray,
        search_space: DataArray,
        technologies: Dataset,
        market: Dataset,
        **kwargs
    ) -> DataArray:
        pass

Arguments:
    agent: the agent relevant to the search space. The filters may need to query
        the agent for parameters, e.g. the current year, the interpolation
        method, the tolerance, etc.
    demand: Demand to fulfill.
    search_space: A boolean matrix represented as a ``DataArray``, listing replacement
        technologies for each asset.
    technologies: A data set characterising the technologies from which the
        agent can draw assets.
    market: Market variables, such as prices or current capacity and retirement
        profile.
    kwargs: Extra input parameters. These parameters are expected to be set from the
        input file.

        .. warning::

            The standard :ref:`agent csv file<inputs-agents>` does not allow to set
            these parameters.

Returns:
    A dataArray with at least one dimension corresponding to ``replacement``.  Only the
    technologies in ``search_space.replacement`` should be present.  Furthermore, if an
    ``asset`` dimension is present, then it should correspond to ``search_space.asset``.
    Other dimensions can be present, as long as the subsequent decision function nows
    how to reduce them.
"""
__all__ = [
    "register_objective",
    "comfort",
    "efficiency",
    "fixed_costs",
    "capital_costs",
    "emission_cost",
    "fuel_consumption_cost",
    "lifetime_levelized_cost_of_energy",
    "net_present_value",
    "equivalent_annual_cost",
    "capacity_to_service_demand",
    "factory",
]

from typing import Callable, Mapping, Sequence, Text, Union

from xarray import DataArray, Dataset

from muse.agent import Agent
from muse.registration import registrator

OBJECTIVE_SIGNATURE = Callable[
    [Agent, DataArray, DataArray, Dataset, Dataset], DataArray
]
"""Objectives signature."""

OBJECTIVES: Mapping[Text, OBJECTIVE_SIGNATURE] = {}
"""Dictionary of objectives when selecting replacement technology."""


def factory(
    settings: Union[Text, Mapping, Sequence[Union[Text, Mapping]]] = "fixed_costs"
) -> Callable:
    """Creates a function computing multiple objectives.

    The input can be a single objective defined by its name alone. Or it can be a single
    objective defined by a dictionary which must include at least a "name" item, as well
    as any extra parameters to pass to the objective. Or it can be a sequence of
    objectives defined by name or by dictionary.
    """
    from typing import List, Dict
    from functools import partial
    from logging import getLogger

    if isinstance(settings, Text):
        params: List[Dict] = [{"name": settings}]
    elif isinstance(settings, Mapping):
        params = [dict(**settings)]
    else:
        params = [
            {"name": param} if isinstance(param, Text) else dict(**param)
            for param in settings
        ]

    if len(set(param["name"] for param in params)) != len(params):
        msg = (
            "The same objective is named twice."
            " The result may be undefined if parameters differ."
        )
        getLogger(__name__).critical(msg)

    functions = [
        (
            param["name"],
            partial(
                OBJECTIVES[param["name"]],
                **{k: v for k, v in param.items() if k != "name"},
            ),
        )
        for param in params
    ]

    def objectives(
        agent: Agent, demand: DataArray, search_space: DataArray, *args, **kwargs
    ) -> Dataset:
        result = Dataset(coords=search_space.coords)
        for name, objective in functions:
            result[name] = objective(agent, demand, search_space, *args, **kwargs)
        return result

    return objectives


@registrator(registry=OBJECTIVES, loglevel="info")
def register_objective(function: OBJECTIVE_SIGNATURE):
    """Decorator to register a function as a objective.

    Registers a function as a objective so that it can be applied easily
    when sorting technologies one against the other.

    The input name is expected to be in lower_snake_case, since it ought to be a
    python function. CamelCase, lowerCamelCase, and kebab-case names are also
    registered.
    """
    from functools import wraps

    @wraps(function)
    def decorated(
        agent: Agent, demand: DataArray, search_space: DataArray, *args, **kwargs
    ) -> DataArray:
        from numpy import issubdtype, number, bool_
        from logging import getLogger

        reduced_demand = demand.sel(asset=search_space.asset)
        result = function(  # type:ignore
            agent, reduced_demand, search_space, *args, **kwargs
        )

        dtype = result.values.dtype
        if not (issubdtype(dtype, number) or issubdtype(dtype, bool_)):
            msg = "dtype of objective %s is not a number (%s)" % (
                function.__name__,
                dtype,
            )
            getLogger(function.__module__).warning(msg)

        if not {"replacement", "asset"}.issuperset(result.dims):
            raise RuntimeError(
                "Objective {func} returned an array with dimensions {dims}; "
                "it is not a subset of {{'replacemment', 'asset'}}.".format(
                    dims=result.dims, func=function.__name__
                )
            )
        if "technology" in result.dims:
            raise RuntimeError("Objective should not return a dimension 'technology'")
        if "technology" in result.coords:
            raise RuntimeError("Objective should not return a coordinate 'technology'")
        result.name = function.__name__
        return result

    return decorated


@register_objective
def comfort(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    *args,
    **kwargs,
) -> DataArray:
    """Comfort value provided by technologies."""
    return technologies.comfort.sel(technology=search_space.replacement).drop_vars(
        "technology"
    )


@register_objective
def efficiency(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    *args,
    **kwargs,
) -> DataArray:
    """Efficiency of the technologies."""
    result = agent.filter_input(
        technologies.efficiency, year=agent.year, technology=search_space.replacement
    ).drop_vars("technology")
    assert isinstance(result, DataArray)
    return result


@register_objective(name="capacity")
def capacity_to_service_demand(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    *args,
    **kwargs,
) -> DataArray:
    """Minimum capacity required to fulfill the demand."""
    from muse.timeslices import represent_hours

    params = agent.filter_input(
        technologies[["utilization_factor", "fixed_outputs"]],
        year=agent.year,
        region=agent.region,
        technology=search_space.replacement,
    ).drop_vars("technology")
    if "represent_hours" in market:
        hours = market.represent_hours
    elif "represent_hours" in search_space.coords:
        hours = search_space.represent_hours
    else:
        hours = represent_hours(market.timeslice)

    max_hours = hours.max() / hours.sum()

    commodity_output = params.fixed_outputs.sel(commodity=demand.commodity)

    max_demand = (
        demand.where(commodity_output > 0, 0)
        / commodity_output.where(commodity_output > 0, 1)
    ).max(("commodity", "timeslice"))

    return max_demand / params.utilization_factor / max_hours


@register_objective
def fixed_costs(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    *args,
    **kwargs,
) -> DataArray:
    r"""Fixed costs associated with a technology.

    Given a factor :math:`\alpha` and an  exponent :math:`\beta`, the fixed costs
    :math:`F` are computed from the :py:func:`capacity fulfilling the current demand
    <capacity_to_service_demand>` :math:`C` as:

    .. math::

        F = \alpha * C^\beta

    :math:`\alpha` and :math:`\beta` are "fix_par" and "fix_exp" in
    :ref:`inputs-technodata`, respectively.
    """
    cfd = capacity_to_service_demand(
        agent, demand, search_space, technologies, market, *args, **kwargs
    )
    data = agent.filter_input(
        technologies[["fix_par", "fix_exp"]],
        technology=search_space.replacement,
        year=agent.year,
    ).drop_vars("technology")
    return data.fix_par * (cfd ** data.fix_exp)


@register_objective
def capital_costs(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    *args,
    **kwargs,
) -> DataArray:
    r"""Capital costs for input technologies.

    The capital costs are computed as :math:`a * b^\alpha`, where :math:`a` is
    "cap_par" from the :ref:`inputs-technodata`, :math:`b` is the "scaling_size", and
    :math:`\alpha` is "cap_exp". In other words, capital costs are constant across the
    simulation for each technology.
    """
    data = agent.filter_input(
        technologies[["cap_par", "scaling_size", "cap_exp"]],
        technology=search_space.replacement,
        year=agent.year,
    ).drop_vars("technology")
    return data.cap_par * (data.scaling_size ** data.cap_exp)


@register_objective(name="emissions")
def emission_cost(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    *args,
    **kwargs,
) -> DataArray:
    r"""Emission cost for each technology when fultfilling whole demand.

    Given the demand share :math:`D`, the emissions per amount produced :math:`E`, and
    the prices per emittant :math:`P`, then emissions costs :math:`C` are computed
    as:

    .. math::

        C = \sum_s \left(\sum_cD\right)\left(\sum_cEP\right),

    with :math:`s` the timeslices and :math:`c` the commodity.
    """
    from muse.commodities import is_enduse, is_pollutant

    enduses = is_enduse(technologies.comm_usage.sel(commodity=demand.commodity))
    total = demand.sel(commodity=enduses).sum("commodity")
    allemissions = agent.filter_input(
        technologies.fixed_outputs,
        commodity=is_pollutant(technologies.comm_usage),
        technology=search_space.replacement,
        year=agent.year,
    ).drop_vars("technology")
    envs = is_pollutant(technologies.comm_usage)
    prices = agent.filter_input(market.prices, year=agent.forecast_year, commodity=envs)
    return (total * (allemissions * prices).sum("commodity")).sum("timeslice")


@register_objective
def capacity_in_use(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    *args,
    **kwargs,
):
    from muse.commodities import is_enduse
    from muse.timeslices import represent_hours

    if "represent_hours" in market:
        hours = market.represent_hours
    elif "represent_hours" in search_space.coords:
        hours = search_space.represent_hours
    elif hours is None:
        hours = represent_hours(market.timeslice)

    ufac = agent.filter_input(
        technologies.utilization_factor,
        technology=search_space.replacement,
        year=agent.year,
    ).drop_vars("technology")
    enduses = is_enduse(technologies.comm_usage.sel(commodity=demand.commodity))
    return (
        (demand.sel(commodity=enduses).sum("commodity") / hours).sum("timeslice")
        * hours.sum()
        / ufac
    )


@register_objective
def consumption(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    *args,
    **kwargs,
) -> DataArray:
    """Commodity consumption when fulfilling the whole demand.

    Currently, the consumption is implemented for commodity_max == +infinity.
    """
    from muse.quantities import consumption

    params = agent.filter_input(
        technologies[["fixed_inputs", "flexible_inputs"]],
        year=agent.year,
        technology=search_space.replacement.values,
    )
    prices = agent.filter_input(market.prices, year=agent.forecast_year)
    demand = demand.where(search_space, 0).rename(replacement="technology")
    result = consumption(technologies=params, prices=prices, production=demand)
    return result.sum(("commodity", "timeslice")).rename(technology="replacement")


@register_objective
def fuel_consumption_cost(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    *args,
    **kwargs,
):
    """Cost of fuels when fulfilling whole demand."""
    from muse.quantities import consumption
    from muse.commodities import is_fuel

    commodity = is_fuel(technologies.comm_usage.sel(commodity=market.commodity))
    params = agent.filter_input(
        technologies[["fixed_inputs", "flexible_inputs"]],
        year=agent.year,
        technology=search_space.replacement.values,
    )
    prices = agent.filter_input(market.prices, year=agent.forecast_year)
    demand = demand.where(search_space, 0).rename(replacement="technology")
    fcons = consumption(technologies=params, prices=prices, production=demand)
    return (
        (fcons * prices)
        .sel(commodity=commodity)
        .sum(("commodity", "timeslice"))
        .rename(technology="replacement")
    )


@register_objective(name="LCOE")
def lifetime_levelized_cost_of_energy(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    *args,
    **kwargs,
):
    """Levelized cost of energy (LCOE) of technologies over their lifetime.

    It follows the `simpified LCOE` given by NREL.

    Arguments:
        agent: The agent of interest
        search_space: The search space space for replacement technologies
        technologies: All the technologies
        market: The market parameters

    Return:
        DataArray with the LCOE calculated for the relevant technologies
    """
    from muse.quantities import lifetime_levelized_cost_of_energy as lifetimeLCOE

    techs = agent.filter_input(technologies, technology=search_space.replacement.values)
    assert isinstance(techs, Dataset)
    prices = agent.filter_input(market.prices)
    assert isinstance(techs, DataArray)
    return lifetimeLCOE(prices, techs, agent.year, **kwargs).rename(
        replacement="technology"
    )


def capital_recovery_factor(
    agent: Agent, search_space: DataArray, technologies: Dataset
) -> DataArray:
    """Capital recovery factor using interest rate and expected lifetime.

    The `capital recovery factor`_ is computed using the expression given by HOMER
    Energy.

    .. _capital recovery factor:
        https://www.homerenergy.com/products/pro/docs/3.11/capital_recovery_factor.html

    Arguments:
        agent: The agent of interest
        search_space: The search space space for replacement technologies
        technologies: All the technologies

    Return:
        DataArray with the CRF calculated for the relevant technologies
    """

    tech = agent.filter_input(
        technologies[["technical_life", "interest_rate"]],
        technology=search_space.replacement,
        year=agent.year,
    ).drop_vars("technology")
    nyears = tech.technical_life.astype(int)

    return tech.interest_rate / (1 - (1 / (1 + tech.interest_rate) ** nyears))


@register_objective(name="NPV")
def net_present_value(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    *args,
    **kwargs,
):
    """Net present value (NPV) of the relevant technologies.


    The net present value of a Component is the present value  of all the revenues that
    a Component earns over its lifetime minus all the costs of installing and operating
    it. Follows the definition of the `net present cost`_ given by HOMER Energy.

    .. _net present cost:
        https://www.homerenergy.com/products/pro/docs/3.11/net_present_cost.html

    - energy commodities INPUTS are related to fuel costs
    - environmental commodities OUTPUTS are related to environmental costs
    - material and service commodities INPUTS are related to consumable costs
    - fixed and variable costs are given as technodata inputs and depend on the
      installed capacity and production (non-environmental), respectively
    - capacity costs are given as technodata inputs and depend on the installed capacity

    Note:
        Here, the installation year is always agent.year, since objectives compute the
        NPV for technologies to be installed in the current year. A more general NPV
        computation (which would then live in quantities.py) would have to refer to
        installation year of the technology.

    Arguments:
        agent: The agent of interest
        search_space: The search space space for replacement technologies
        technologies: All the technologies
        market: The market parameters

    Return:
        DataArray with the NPV calculated for the relevant technologies
    """
    from muse.commodities import is_pollutant, is_material, is_enduse

    # Filtering of the inputs
    tech = agent.filter_input(
        technologies[
            [
                "technical_life",
                "interest_rate",
                "cap_par",
                "cap_exp",
                "var_par",
                "var_exp",
                "fix_par",
                "fix_exp",
                "fixed_outputs",
                "utilization_factor",
            ]
        ],
        technology=search_space.replacement,
        year=agent.year,
    ).drop_vars("technology")
    nyears = tech.technical_life.astype(int)
    interest_rate = tech.interest_rate
    cap_par = tech.cap_par
    cap_exp = tech.cap_exp
    var_par = tech.var_par
    var_exp = tech.var_exp
    fix_par = tech.fix_par
    fix_exp = tech.fix_exp
    fixed_outputs = tech.fixed_outputs
    utilization_factor = tech.utilization_factor

    # All years the simulation is running
    # NOTE: see docstring about installation year
    iyears = range(agent.year, agent.year + nyears.values.max())
    years = DataArray(iyears, coords={"year": iyears}, dims="year")

    # Filters
    environmentals = is_pollutant(technologies.comm_usage)
    material = is_material(technologies.comm_usage)
    products = is_enduse(technologies.comm_usage)

    # Capacity
    capacity = capacity_to_service_demand(
        agent, demand, search_space, technologies, market
    )

    # Evolution of rates with time
    rates = discount_factor(
        years - agent.year + 1, interest_rate, years <= agent.year + nyears
    )

    # raw revenues --> Make the NPV more positive
    # This production is the absolute maximum production, given the capacity
    prices_non_env = agent.filter_input(
        market.prices, commodity=products, year=years.values
    ).ffill("year")
    production = capacity * fixed_outputs * utilization_factor
    raw_revenues = (production * prices_non_env * rates).sum(
        ("commodity", "year", "timeslice")
    )

    # raw costs --> make the NPV more negative
    # Cost of installed capacity
    installed_capacity_costs = cap_par * capacity ** cap_exp

    # Cost related to environmental products
    prices_environmental = agent.filter_input(
        market.prices, commodity=environmentals, year=years.values
    ).ffill("year")
    environmental_costs = (production * prices_environmental * rates).sum(
        ("commodity", "year", "timeslice")
    )

    # Fuel/energy costs
    fuel_costs = (
        fuel_consumption_cost(agent, demand, search_space, technologies, market) * rates
    ).sum("year")

    # Cost related to material other than fuel/energy and environmentals
    prices_material = agent.filter_input(
        market.prices, commodity=material, year=years.values
    ).ffill("year")
    material_costs = (production * prices_material * rates).sum(
        ("commodity", "year", "timeslice")
    )

    # Fixed and Variable costs
    fixed_costs = fix_par * capacity ** fix_exp
    variable_costs = (var_par * production.sel(commodity=products) ** var_exp).sum(
        "commodity"
    )
    assert set(fixed_costs.dims) == set(variable_costs.dims)
    fixed_and_variable_costs = ((fixed_costs + variable_costs) * rates).sum("year")

    assert set(raw_revenues.dims) == set(installed_capacity_costs.dims)
    assert set(raw_revenues.dims) == set(environmental_costs.dims)
    assert set(raw_revenues.dims) == set(fuel_costs.dims)
    assert set(raw_revenues.dims) == set(material_costs.dims)
    assert set(raw_revenues.dims) == set(fixed_and_variable_costs.dims)
    results = (
        raw_revenues
        - installed_capacity_costs
        - fuel_costs
        - environmental_costs
        - material_costs
        - fixed_and_variable_costs
    )

    return results


@register_objective(name="NPC")
def net_present_cost(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    *args,
    **kwargs,
):
    """Net present cost (NPC) of the relevant technologies.

    The net present cost of a Component is the present value of all the costs of
    installing and operating the Component over the project lifetime, minus the present
    value of all the revenues that it earns over the project lifetime.

    .. seealso::
        :py:func:`net_present_value`.
    """
    return -net_present_value(
        agent, demand, search_space, technologies, market, *args, **kwargs
    )


def discount_factor(years, interest_rate, mask=1.0):
    """Calculate an array with the rate (aka discount factor) values over the
    years."""
    return mask / (1 + interest_rate) ** years


@register_objective(name="EAC")
def equivalent_annual_cost(
    agent: Agent,
    demand: DataArray,
    search_space: DataArray,
    technologies: Dataset,
    market: Dataset,
    *args,
    **kwargs,
):
    """Equivalent annual costs (or annualized cost) of a technology.

    This is the cost that, if it were to occur equally in every year of the
    project lifetime, would give the same net present cost as the actual cash
    flow sequence associated with that component. The cost is computed using the
    `annualized cost`_ expression given by HOMER Energy.

    .. _annualized cost:
        https://www.homerenergy.com/products/pro/docs/3.11/annualized_cost.html

    Arguments:
        agent: The agent of interest
        search_space: The search space space for replacement technologies
        technologies: All the technologies
        market: The market parameters

    Return:
        DataArray with the EAC calculated for the relevant technologies
    """
    npv = net_present_cost(agent, demand, search_space, technologies, market)
    crf = capital_recovery_factor(agent, search_space, technologies)
    return npv * crf