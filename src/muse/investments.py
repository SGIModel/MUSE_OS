"""Investment decision.

An investment determines which technologies to invest given a metric to
determine preferred technologies, a corresponding search space of technologies,
and the demand to fulfill.

Investments should be registered via the decorator `register_investment`. The
registration makes it possible to call investments dynamically through
`compute_investment`, by specifying the name of the investment. It is part of
MUSE's plugin platform.

Investments are not expected to modify any of their arguments. They should all
have the following signature:

.. code-block:: python

    @register_investment
    def investment(
        costs: xr.DataArray,
        search_space: xr.DataArray,
        technologies: xr.Dataset,
        constraints: List[Constraint],
        year: int,
        **kwargs
    ) -> xr.DataArray:
        pass

Arguments:
    costs: specifies for each `asset` which `replacement` technology should be invested
        in preferentially. This should be an integer or floating point array with
        dimensions `asset` and `replacement`.
    search_space: an `asset` by `replacement` matrix defining allowed and disallowed
        replacement technologies for each asset
    technologies: a dataset containing all constant data characterizing the
        technologies.
    constraints: a list of constraints as defined in :py:mod:`~muse.constraints`.
    year: the current year.

Returns:
    A data array with dimensions `asset` and `technology` specifying the amount
    of newly invested capacity.
"""
__all__ = [
    "adhoc_match_demand",
    "cliff_retirement_profile",
    "register_investment",
    "INVESTMENT_SIGNATURE",
]
from typing import (
    Any,
    Callable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Text,
    Union,
    cast,
)

import numpy as np
import xarray as xr
from mypy_extensions import KwArg

from muse.constraints import Constraint
from muse.errors import FailedInterpolation, GrowthOfCapacityTooConstrained
from muse.outputs.cache import cache_quantity
from muse.registration import registrator

INVESTMENT_SIGNATURE = Callable[
    [xr.DataArray, xr.DataArray, xr.Dataset, List[Constraint], KwArg(Any)],
    Union[xr.DataArray, xr.Dataset],
]
"""Investment signature. """

INVESTMENTS: MutableMapping[Text, INVESTMENT_SIGNATURE] = {}
"""Dictionary of investment functions."""


@registrator(registry=INVESTMENTS, loglevel="info")
def register_investment(function: INVESTMENT_SIGNATURE) -> INVESTMENT_SIGNATURE:
    """Decorator to register a function as an investment.

    The output of the function can be a DataArray, with the invested capacity, or a
    Dataset. In this case, it must contain a DataArray named "capacity" and, optionally,
    a DataArray named "production". Only the invested capacity DataArray is returned to
    the calling function.
    """
    from functools import wraps

    @wraps(function)
    def decorated(
        costs: xr.DataArray,
        search_space: xr.DataArray,
        technologies: xr.Dataset,
        constraints: List[Constraint],
        **kwargs,
    ) -> xr.DataArray:
        result = function(costs, search_space, technologies, constraints, **kwargs)

        if isinstance(result, xr.Dataset):
            investment = result["capacity"].rename("investment")
            if "production" in result:
                cache_quantity(production=result["production"])
        else:
            investment = result.rename("investment")

        cache_quantity(capacity=investment)

        return investment

    return decorated


def factory(settings: Optional[Union[Text, Mapping]] = None) -> Callable:
    from typing import Dict

    if settings is None:
        name = "match_demand"
        params: Dict = {}
    elif isinstance(settings, Text):
        name = settings
        params = {}
    else:
        name = settings["name"]
        params = {k: v for k, v in settings.items() if k != "name"}

    top = params.get("timeslice_op", "max")
    if isinstance(top, Text):
        if top.lower() == "max":

            def timeslice_op(x: xr.DataArray) -> xr.DataArray:
                from muse.timeslices import convert_timeslice

                return (x / convert_timeslice(xr.DataArray(1), x)).max("timeslice")

        elif top.lower() == "sum":

            def timeslice_op(x: xr.DataArray) -> xr.DataArray:
                return x.sum("timeslice")

        else:
            raise ValueError(f"Unknown timeslice transform {top}")

        params["timeslice_op"] = timeslice_op

    investment = INVESTMENTS[name]

    def compute_investment(
        search: xr.Dataset,
        technologies: xr.Dataset,
        constraints: List[Constraint],
        **kwargs,
    ) -> xr.DataArray:
        """Computes investment needed to fulfill demand.

        The return is a data array with two dimensions: (asset, replacement).
        """
        from numpy import zeros

        if any(u == 0 for u in search.decision.shape):
            return xr.DataArray(
                zeros((len(search.asset), len(search.replacement))),
                coords={"asset": search.asset, "replacement": search.replacement},
                dims=("asset", "replacement"),
            )

        return investment(
            search.decision,
            search.search_space,
            technologies,
            constraints,
            **params,
            **kwargs,
        ).rename("investment")

    return compute_investment


def cliff_retirement_profile(
    technical_life: xr.DataArray,
    current_year: int = 0,
    protected: int = 0,
    interpolation: Text = "linear",
    **kwargs,
) -> xr.DataArray:
    """Cliff-like retirement profile from current year.

    Computes the retirement profile of all technologies in ``technical_life``.
    Assets with a technical life smaller than the input time-period should automatically
    be renewed.

    Hence, if ``technical_life <= protected``, then effectively, the technical life is
    rewritten as ``technical_life * n`` with ``n = int(protected // technical_life) +
    1``.

    We could just return an array where each year is repesented. Instead, to save
    memory, we return a compact view of the same where years where no change happens are
    removed.

    Arguments:
        technical_life: lifetimes for each technology
        current_year: current year
        protected: The technologies are assumed to be renewed between years
            `current_year` and `current_year + protected`
        **kwargs: arguments by which to filter technical_life, if any.

    Returns:
        A boolean DataArray where each each element along the year dimension is
        true if the technology is still not retired for the given year.
    """
    from muse.utilities import avoid_repetitions

    if kwargs:
        technical_life = technical_life.sel(**kwargs)
    if "year" in technical_life.dims:
        technical_life = technical_life.interp(year=current_year, method=interpolation)
    technical_life = (1 + protected // technical_life) * technical_life  # type:ignore

    if len(technical_life) > 0:
        max_year = int(current_year + technical_life.max())
    else:
        max_year = int(current_year + protected)
    allyears = xr.DataArray(
        range(current_year, max_year + 1),
        dims="year",
        coords={"year": range(current_year, max_year + 1)},
    )

    profile = allyears < (current_year + technical_life)  # type: ignore

    # now we minimize the number of years needed to represent the profile fully
    # this is done by removing the central year of any three repeating year, ensuring
    # the removed year can be recovered by a linear interpolation.
    goodyears = avoid_repetitions(profile.astype(int))

    return profile.sel(year=goodyears).astype(bool)


class LinearProblemError(RuntimeError):
    """Error returned for infeasible LP problems."""

    def __init__(self, *args):
        super().__init__(*args)


@register_investment(name=["adhoc"])
def adhoc_match_demand(
    costs: xr.DataArray,
    search_space: xr.DataArray,
    technologies: xr.Dataset,
    constraints: List[Constraint],
    year: int,
    timeslice_op: Optional[Callable[[xr.DataArray], xr.DataArray]] = None,
) -> xr.DataArray:
    from numpy import any, round

    from muse.demand_matching import demand_matching
    from muse.quantities import capacity_in_use, maximum_production
    from muse.timeslices import QuantityType, convert_timeslice

    demand = next((c for c in constraints if c.name == "demand")).b

    max_capacity = next(
        (c for c in constraints if c.name == "max capacity expansion")
    ).b
    max_prod = maximum_production(
        technologies,
        max_capacity,
        year=year,
        technology=costs.replacement,
        commodity=demand.commodity,
    ).drop_vars("technology")

    if "timeslice" in demand.dims and "timeslice" not in max_prod.dims:
        max_prod = convert_timeslice(max_prod, demand, QuantityType.EXTENSIVE)

    # Push disabled techs to last rank.
    # Any production assigned to them by the demand-matching algorithm will be removed.
    minobj = costs.min()
    maxobj = costs.where(search_space, minobj).max("replacement") + 1
    # Take average asset cost over the assets
    if "timeslice" in costs.dims:
        costs = costs.mean(dim="asset").sum("timeslice")

    decision = costs.where(search_space, maxobj)

    production = demand_matching(
        demand.sel(asset=demand.asset.isin(search_space.asset)),
        decision,
        max_prod,
    ).where(search_space, 0)

    res = round(
        production.sum("replacement").sum("asset")
        - demand.sel(asset=demand.asset.isin(search_space.asset)).sum("asset"),
        4,
    )

    if any(res) < 0:
        raise ValueError("System could not be solved")

    # capacity can come with timeslices if the utilization factor has timeslices
    capacity = capacity_in_use(
        production, technologies, year=year, technology=production.replacement
    ).drop_vars("technology")
    if "timeslice" in capacity.dims and timeslice_op is not None:
        capacity = timeslice_op(capacity)

    return capacity.rename("investment")


@register_investment(name=["adhoc_timeslice"])
def adhoc_timeslice_demand(
    costs: xr.DataArray,
    search_space: xr.DataArray,
    technologies: xr.Dataset,
    constraints: List[Constraint],
    year: int,
    timeslice_op: Optional[Callable[[xr.DataArray], xr.DataArray]] = None,
) -> xr.DataArray:
    from numpy import any, round

    from muse.demand_matching import demand_matching
    from muse.quantities import capacity_in_use, maximum_production
    from muse.timeslices import QuantityType, convert_timeslice

    demand = next((c for c in constraints if c.name == "demand")).b

    max_capacity = next(
        (c for c in constraints if c.name == "max capacity expansion")
    ).b
    max_prod = maximum_production(
        technologies,
        max_capacity,
        year=year,
        technology=costs.replacement,
        commodity=demand.commodity,
    ).drop_vars("technology")

    if "timeslice" in demand.dims and "timeslice" not in max_prod.dims:
        max_prod = convert_timeslice(max_prod, demand, QuantityType.EXTENSIVE)

    # Push disabled techs to last rank.
    # Any production assigned to them by the demand-matching algorithm will be removed.
    minobj = costs.min()
    maxobj = costs.where(search_space, minobj).max("replacement") + 1
    # Take average asset cost over the assets
    if "timeslice" in costs.dims:
        costs = costs.mean(dim="asset")

    decision = costs.where(search_space, maxobj)

    production = demand_matching(
        demand.sel(asset=demand.asset.isin(search_space.asset)).sum("asset"),
        decision,
        max_prod,
    ).where(search_space, 0)

    res = round(
        production.sum("replacement").sum("asset")
        - demand.sel(asset=demand.asset.isin(search_space.asset)).sum("asset"),
        4,
    )

    if any(res) < 0:
        raise ValueError("System could not be solved")

    # capacity can come with timeslices if the utilization factor has timeslices
    capacity = capacity_in_use(
        production, technologies, year=year, technology=production.replacement
    ).drop_vars("technology")
    if "timeslice" in capacity.dims and timeslice_op is not None:
        capacity = timeslice_op(capacity)

    result = xr.Dataset({"capacity": capacity, "production": production})
    return result


@register_investment(name=["scipy", "match_demand"])
def scipy_match_demand(
    costs: xr.DataArray,
    search_space: xr.DataArray,
    technologies: xr.Dataset,
    constraints: List[Constraint],
    year: Optional[int] = None,
    timeslice_op: Optional[Callable[[xr.DataArray], xr.DataArray]] = None,
    **options,
) -> xr.DataArray:
    from logging import getLogger

    from scipy.optimize import linprog

    from muse.constraints import ScipyAdapter

    if technologies.to_dataframe().isnull().sum().sum() > 0:
        raise FailedInterpolation

    if "timeslice" in costs.dims and timeslice_op is not None:
        costs = timeslice_op(costs)
    if "year" in technologies.dims and year is None:
        raise ValueError("Missing year argument")
    elif "year" in technologies.dims:
        techs = technologies.sel(year=year).drop_vars("year")
    else:
        techs = technologies
    timeslice = next((cs.timeslice for cs in constraints if "timeslice" in cs.dims))
    adapter = ScipyAdapter.factory(
        techs, cast(np.ndarray, costs), timeslice, *constraints
    )
    res = linprog(**adapter.kwargs, method="highs")
    if not res.success:
        getLogger(__name__).critical(res.message)
        raise GrowthOfCapacityTooConstrained

    solution = cast(Callable[[np.ndarray], xr.Dataset], adapter.to_muse)(res.x)
    return solution


@register_investment(name=["cvxopt"])
def cvxopt_match_demand(
    costs: xr.DataArray,
    search_space: xr.DataArray,
    technologies: xr.Dataset,
    constraints: List[Constraint],
    year: Optional[int] = None,
    timeslice_op: Optional[Callable[[xr.DataArray], xr.DataArray]] = None,
    **options,
) -> xr.DataArray:
    from importlib import import_module
    from logging import getLogger

    from muse.constraints import ScipyAdapter

    if "year" in technologies.dims and year is None:
        raise ValueError("Missing year argument")
    elif "year" in technologies.dims:
        techs = technologies.interp(year=year).drop_vars("year")
    else:
        techs = technologies

    def default_to_scipy():
        return scipy_match_demand(
            costs, search_space, techs, constraints, timeslice_op=timeslice_op
        )

    try:
        cvxopt = import_module("cvxopt")
    except ModuleNotFoundError:
        msg = (
            "cvxopt is not installed\n"
            "It can be installed with `pip install cvxopt`\n"
            "Using the scipy linear solver instead."
        )
        getLogger(__name__).critical(msg)
        return default_to_scipy()

    if "timeslice" in costs.dims and timeslice_op is not None:
        costs = timeslice_op(costs)
    timeslice = next((cs.timeslice for cs in constraints if "timeslice" in cs.dims))
    adapter = ScipyAdapter.factory(
        techs, -cast(np.ndarray, costs), timeslice, *constraints
    )
    G = np.zeros((0, adapter.c.size)) if adapter.A_ub is None else adapter.A_ub
    h = np.zeros((0,)) if adapter.b_ub is None else adapter.b_ub
    if adapter.bounds[0] != -np.inf and adapter.bounds[0] is not None:
        G = np.concatenate((G, -np.eye(adapter.c.size)))
        h = np.concatenate((h, np.full(adapter.c.size, adapter.bounds[0])))
    if adapter.bounds[1] != np.inf and adapter.bounds[1] is not None:
        G = np.concatenate((G, np.eye(adapter.c.size)))
        h = np.concatenate((h, np.full(adapter.c.size, adapter.bounds[1])))

    args = [adapter.c, G, h]
    if adapter.A_eq is not None:
        args += [adapter.A_eq, adapter.b_eq]
    res = cvxopt.solvers.lp(*map(cvxopt.matrix, args), **options)  # type: ignore
    if res["status"] != "optimal":
        getLogger(__name__).info(res["status"])
    if res["x"] is None:
        getLogger(__name__).critical("infeasible system")
        raise LinearProblemError("Infeasible system", res)

    solution = cast(Callable[[np.ndarray], xr.Dataset], adapter.to_muse)(list(res["x"]))
    return solution
