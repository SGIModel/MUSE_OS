from typing import cast

import numpy as np
import xarray as xr
from pytest import approx, fixture


@fixture
def demand(
    technologies: xr.Dataset, capacity: xr.DataArray, market: xr.DataArray
) -> xr.DataArray:
    from typing import Any, Hashable, Mapping

    region = xr.DataArray(list(set(capacity.region.values)), dims="region")
    coords: Mapping[Hashable, Any] = {
        "commodity": technologies.commodity,
        "year": capacity.year,
        "region": region,
        "timeslice": market.timeslice,
    }
    data = np.random.randint(0, 5, tuple(len(u) for u in coords.values()))
    return xr.DataArray(data, coords=coords, dims=tuple(coords.keys()))


@fixture
def production(technologies: xr.Dataset, capacity: xr.DataArray) -> xr.DataArray:
    from numpy.random import random

    comms = xr.DataArray(
        random(len(technologies.commodity)),
        coords={"commodity": technologies.commodity},
        dims="commodity",
    )
    return capacity * comms


def make_array(array):

    data = np.random.randint(1, 5, len(array))
    return xr.DataArray(data, dims=array.dims, coords=array.coords)


def test_supply_enduse(technologies, capacity, timeslice):
    """End-use part of supply."""
    from numpy.random import random

    from muse.commodities import is_enduse
    from muse.quantities import maximum_production, supply

    production = maximum_production(technologies, capacity)
    share = xr.DataArray(
        random(timeslice.timeslice.shape),
        coords={"timeslice": timeslice.timeslice},
        dims="timeslice",
    )
    demand = (production.sum("asset") + 1) * share / share.sum()
    spl = supply(capacity, demand, technologies).where(
        is_enduse(technologies.comm_usage), 0
    )
    assert (abs(spl.sum("timeslice") - production) < 1e-12).all()
    assert (spl.sum("asset") < demand).all()

    demand = production.sum("asset") * 0.7 * share / share.sum()
    spl = supply(capacity, demand, technologies).where(
        is_enduse(technologies.comm_usage), 0
    )
    assert (spl.sum("timeslice") <= production + 1e-12).all()
    assert (
        abs(spl.sum("asset") - demand.where(production.sum("asset") > 0, 0)) < 1e-12
    ).all()


def test_supply_emissions(technologies, capacity):
    """Emission part of supply."""
    from muse.commodities import is_enduse, is_pollutant
    from muse.quantities import emission, maximum_production, supply

    production = maximum_production(technologies, capacity)
    spl = supply(capacity, production.sum("asset") + 1, technologies)
    msn = emission(spl.where(is_enduse(spl.comm_usage), 0), technologies.fixed_outputs)
    actual, expected = xr.broadcast(
        spl.sel(commodity=is_pollutant(spl.comm_usage)), msn
    )
    assert actual.values == approx(expected.values)


def test_gross_margin(technologies, capacity, market):
    from muse.commodities import is_enduse, is_fuel, is_pollutant
    from muse.quantities import gross_margin

    # we modify the variables to have just the values we want for the testing
    technologies = technologies.sel(technology=technologies.technology == "soda_shaker")
    capacity = capacity.sel(asset=capacity.technology == "soda_shaker")
    capacity[:] = capa = 9

    # This will leave 2 environmental outputs and 4 fuel inputs.
    usage = technologies.comm_usage

    technologies.var_par[:] = vp = 2
    technologies.var_exp[:] = ve = 0.5
    technologies.fixed_inputs[{"commodity": is_fuel(usage)}] = fuels = 2
    technologies.fixed_outputs[{"commodity": is_pollutant(usage)}] = envs = 10
    technologies.fixed_outputs[{"commodity": is_enduse(usage)}] = prod = 5

    market.prices[:] = prices = 3
    market.prices[{"commodity": is_pollutant(usage)}] = env_prices = 6
    # We expect a xr.DataArray with 1 replacement technology
    actual = gross_margin(technologies, capacity, market.prices)

    revenues = prices * prod * sum(is_enduse(usage))
    env_costs = env_prices * envs * sum(is_pollutant(usage))
    cons_costs = prices * fuels * sum(is_fuel(usage))
    var_costs = vp * (capa**ve) * market.represent_hours / sum(market.represent_hours)
    expected = revenues - env_costs - cons_costs - var_costs

    expected, actual = xr.broadcast(expected, actual)
    assert actual.values == approx(expected.values)


def test_decommissioning_demand(technologies, capacity):
    from muse.commodities import is_enduse
    from muse.quantities import decommissioning_demand

    years = [2010, 2015]
    capacity = capacity.interp(year=years)
    capacity.loc[{"year": 2010}] = current = 1.3
    capacity.loc[{"year": 2015}] = forecast = 1.0
    technologies.fixed_outputs[:] = fouts = 0.5
    technologies.utilization_factor[:] = ufac = 0.4
    decom = decommissioning_demand(technologies, capacity, years)
    assert set(decom.dims) == {"asset", "commodity", "year"}
    assert decom.sel(commodity=is_enduse(technologies.comm_usage)).values == approx(
        ufac * fouts * (current - forecast)
    )


def test_consumption_no_flex(technologies, production, market):
    from muse.commodities import is_enduse, is_fuel
    from muse.quantities import consumption

    fins = (
        technologies.fixed_inputs.where(is_fuel(technologies.comm_usage), 0)
        .interp(year=sorted(set(production.installed.values)), method="slinear")
        .sel(
            technology=production.technology,
            region=production.region,
            year=production.installed,
        )
    )
    services = technologies.commodity.sel(commodity=is_enduse(technologies.comm_usage))
    expected = (
        (production.rename(commodity="comm_in") * fins)
        .sel(comm_in=production.commodity.isin(services).rename(commodity="comm_in"))
        .sum("comm_in")
    )

    actual = consumption(technologies, production)
    assert set(actual.dims) == set(expected.dims)
    assert "timeslice" not in actual.dims
    actual, expected = xr.broadcast(actual, expected)
    assert actual.values == approx(expected.values)

    technologies.flexible_inputs[:] = 0
    actual = consumption(technologies, production, market.prices)
    expected = expected * market.represent_hours / market.represent_hours.sum()
    actual, expected = xr.broadcast(actual, expected)
    assert actual.values == approx(expected.values)


def test_consumption_with_flex(technologies, production, market):
    from itertools import product

    from muse.commodities import is_enduse, is_fuel
    from muse.quantities import consumption

    techs = technologies.copy()
    techs.fixed_inputs[:] = 0
    techs.flexible_inputs[:] = 0
    consumables = is_fuel(techs.comm_usage)
    while (techs.flexible_inputs.sel(commodity=consumables) == 0).all():
        techs.flexible_inputs[:] = (
            np.random.randint(0, 2, techs.flexible_inputs.shape) != 0
        )
        techs.flexible_inputs[{"commodity": ~consumables}] = 0

    def one_dim(dimension):
        from numpy import arange
        from numpy.random import shuffle

        data = arange(len(dimension), dtype="int")
        shuffle(data)
        return xr.DataArray(data, coords=dimension.coords, dims=dimension.dims)

    year = one_dim(production.year)
    asset = one_dim(production.asset)
    region = one_dim(market.region)
    timeslice = one_dim(market.timeslice)
    commodity = one_dim(market.commodity)
    hours = market.represent_hours / market.represent_hours.sum()

    prices = timeslice + commodity + year * region
    assert set(prices.dims) == set(market.prices.dims)
    assert set((asset + year + commodity).dims) == set(production.dims)
    noenduse = ~is_enduse(techs.comm_usage)
    production = asset * year + commodity
    production.loc[{"commodity": noenduse}] = 0

    actual = consumption(technologies, production, prices)
    assert set(actual.dims) == {"year", "timeslice", "asset", "commodity"}
    assert (year.year == actual.year).all()
    assert (timeslice.timeslice == actual.timeslice).all()
    assert (asset.asset == actual.asset).all()
    assert (commodity.commodity == actual.commodity).all()

    fuels = techs.commodity.loc[{"commodity": consumables}].values
    dims = ("timeslice", "asset", "year")
    allprods = list(product(*(actual[u] for u in dims)))
    allprods = [
        allprods[i] for i in np.random.choice(range(len(allprods)), 50, replace=False)
    ]
    for (ts, asset, year) in allprods:
        flexs = techs.flexible_inputs.sel(
            region=asset.region, technology=asset.technology
        ).interp(year=asset.installed, method="slinear")
        comm_prices = prices.sel(region=asset.region, year=year, timeslice=ts)
        comm_prices = [int(p) for p, f in zip(comm_prices, flexs) if f > 0]
        min_price = min(comm_prices) if comm_prices else None
        ncomms = max(len([u for u in comm_prices if u == min_price]), 1)
        for comm in fuels:
            current_price = prices.sel(
                region=asset.region, year=year, timeslice=ts, commodity=comm
            )
            coords = dict(timeslice=ts, year=year, asset=asset, commodity=comm)
            if current_price != min_price:
                assert actual.sel(coords).values == approx(0)
                continue
            prod = production.sel(asset=asset, year=year).sum("commodity")
            expected = (
                prod * hours.sel(timeslice=ts) / ncomms * flexs.sel(commodity=comm)
            )
            assert expected.values == approx(actual.sel(coords).values)


def test_production_aggregate_asset_view(
    capacity: xr.DataArray, technologies: xr.Dataset
):
    """Production when capacity has format of agent.sector.

    E.g. capacity aggregated across agents.
    """
    from muse.commodities import is_enduse
    from muse.quantities import maximum_production

    technologies: xr.Dataset = technologies[  # type:ignore
        ["fixed_outputs", "utilization_factor"]
    ]

    enduses = is_enduse(technologies.comm_usage)
    assert enduses.any()

    technologies.fixed_outputs[:] = 1
    technologies.utilization_factor[:] = 1
    prod = maximum_production(technologies, capacity)
    assert set(prod.dims) == set(capacity.dims).union({"commodity"})
    assert prod.sel(commodity=~enduses).values == approx(0)
    prod, expected = xr.broadcast(prod.sel(commodity=enduses), capacity)
    assert prod.values == approx(expected.values)

    technologies.fixed_outputs[:] = fouts = 2
    technologies.utilization_factor[:] = ufact = 0.5
    prod = maximum_production(technologies, capacity)
    assert prod.sel(commodity=~enduses).values == approx(0)
    assert set(prod.dims) == set(capacity.dims).union({"commodity"})
    prod, expected = xr.broadcast(prod.sel(commodity=enduses), capacity)
    assert prod.values == approx(fouts * ufact * expected.values)

    technologies.fixed_outputs[:] = fouts = 3
    technologies.utilization_factor[:] = ufact = 0.5
    prod = maximum_production(technologies, capacity)
    assert prod.sel(commodity=~enduses).values == approx(0)
    assert set(prod.dims) == set(capacity.dims).union({"commodity"})
    prod, expected = xr.broadcast(prod.sel(commodity=enduses), capacity)
    assert prod.values == approx(fouts * ufact * expected.values)


def test_production_agent_asset_view(capacity: xr.DataArray, technologies: xr.Dataset):
    """Production when capacity has format of agent.assets.capacity."""
    from muse.utilities import coords_to_multiindex, reduce_assets

    capacity = coords_to_multiindex(reduce_assets(capacity)).unstack("asset").fillna(0)
    test_production_aggregate_asset_view(capacity, technologies)


def test_capacity_in_use(production: xr.DataArray, technologies: xr.Dataset):
    from muse.commodities import is_enduse
    from muse.quantities import capacity_in_use

    technologies: xr.Dataset = technologies[  # type: ignore
        ["fixed_outputs", "utilization_factor"]
    ]
    production[:] = prod = 10
    technologies.fixed_outputs[:] = fout = 5
    technologies.utilization_factor[:] = ufac = 2

    enduses = is_enduse(technologies.comm_usage)
    capa = capacity_in_use(production, technologies, max_dim=None)
    assert "commodity" in capa.dims
    capa, expected = xr.broadcast(capa, enduses * prod / fout / ufac)
    assert capa.values == approx(expected.values)

    capa = capacity_in_use(production, technologies)
    assert "commodity" not in capa.dims
    assert capa.values == approx(prod / fout / ufac)

    maxcomm = np.random.choice(production.commodity.sel(commodity=enduses).values)
    production.loc[{"commodity": maxcomm}] = prod = 11
    capa = capacity_in_use(production, technologies)
    assert "commodity" not in capa.dims
    assert capa.values == approx(prod / fout / ufac)


def test_supply_cost(production: xr.DataArray, timeslice: xr.Dataset):
    from numpy import average
    from numpy.random import random

    from muse.quantities import supply_cost

    timeslice = timeslice.timeslice
    production = production.sel(year=production.year.min(), drop=True)
    # no zero production, because it does not sit well with np.average
    production[:] = random(production.shape)
    lcoe = xr.DataArray(
        random((len(production.asset), len(timeslice))),
        coords={"timeslice": timeslice, "asset": production.asset},
        dims=("asset", "timeslice"),
    )

    production, lcoe = xr.broadcast(production, lcoe)
    actual = supply_cost(production, lcoe, asset_dim="asset")
    for region in set(production.region.values):
        expected = average(
            lcoe.sel(asset=production.region == region),
            weights=production.sel(asset=production.region == region)
            / production.sel(asset=production.region == region).sum("asset"),
            axis=production.get_axis_num("asset"),
        )

    for region in set(production.region.values):

        weight = production / production.sel(asset=production.region == region).sum(
            "asset"
        ).sum("timeslice")

        expected = lcoe * weight

        assert actual.sel(region=region).values == approx(
            expected.sel(asset=production.region == region).sum(
                axis=production.get_axis_num("asset")
            )
        )


def test_supply_cost_zero_prod(production: xr.DataArray, timeslice: xr.Dataset):
    from numpy.random import randn

    from muse.quantities import supply_cost

    timeslice = timeslice.timeslice
    production = production.sel(year=production.year.min(), drop=True)
    production[:] = 0
    lcoe = xr.DataArray(
        randn(len(production.asset), len(timeslice)),
        coords={"timeslice": timeslice, "asset": production.asset},
        dims=("asset", "timeslice"),
    )
    production, lcoe = xr.broadcast(production, lcoe)
    actual = supply_cost(production, lcoe, asset_dim="asset")
    assert actual.values == approx(0e0)


def test_emission(production: xr.DataArray, technologies: xr.Dataset):
    from muse.commodities import is_enduse, is_pollutant
    from muse.quantities import emission

    envs = is_pollutant(technologies.comm_usage)
    technologies = cast(xr.Dataset, technologies[["fixed_outputs"]])
    technologies.fixed_outputs[{"commodity": envs}] = fout = 1.5
    technologies.fixed_outputs[{"commodity": ~envs}] = 2

    enduses = is_enduse(technologies.comm_usage.sel(commodity=production.commodity))
    production[{"commodity": enduses}] = prod = 0.5
    production[{"commodity": ~enduses}] = 5

    em = emission(production, technologies)
    assert em.commodity.isin(envs.commodity).all()
    assert em.values == approx(fout * enduses.sum().values * prod)


def test_demand_matched_production(
    demand: xr.DataArray, capacity: xr.DataArray, technologies: xr.Dataset
):
    from muse.commodities import CommodityUsage, is_enduse
    from muse.quantities import demand_matched_production, maximum_production
    from muse.timeslices import QuantityType, convert_timeslice

    # try and make sure we have a few more outputs than the default fixture
    technologies = technologies.interp(year=capacity.year)
    technologies = technologies.sel(year=capacity.year.min())
    technologies.comm_usage[:] = np.random.choice(
        [CommodityUsage.PRODUCT] * 3 + list(set(technologies.comm_usage.values)),
        technologies.comm_usage.shape,
    )
    technologies.fixed_outputs[:] = np.random.random(technologies.fixed_outputs.shape)
    technologies.fixed_outputs[:] *= is_enduse(technologies.comm_usage)

    capacity = capacity.sel(year=capacity.year.min(), drop=True)
    max_prod = convert_timeslice(
        maximum_production(technologies, capacity),
        demand.timeslice,
        QuantityType.EXTENSIVE,
    )
    demand = max_prod.sum("asset")
    demand[:] *= np.random.choice([0, 1, 1 / 2, 1 / 3, 1 / 10], demand.shape)
    prices = xr.zeros_like(demand)
    prices[:] = np.random.randint(1, 10, prices.shape)
    production = demand_matched_production(demand, prices, capacity, technologies)
    assert set(production.dims) == set(max_prod.dims).union(prices.dims, capacity.dims)
    assert (production <= max_prod + 1e-8).all()


def test_costed_production_exact_match(market, capacity, technologies):
    from muse.quantities import (
        annual_levelized_cost_of_energy,
        costed_production,
        maximum_production,
    )
    from muse.timeslices import QuantityType, convert_timeslice
    from muse.utilities import broadcast_techs

    if set(capacity.region.values) != set(market.region.values):
        capacity.region.values[: len(set(market.region.values))] = list(
            set(market.region.values)
        )
    technodata = broadcast_techs(technologies, capacity)
    costs = annual_levelized_cost_of_energy(
        market.prices.sel(region=technodata.region), technodata
    )
    maxdemand = convert_timeslice(
        xr.Dataset(dict(mp=maximum_production(technologies, capacity)))
        .groupby("region")
        .sum("asset")
        .mp,
        market,
        QuantityType.EXTENSIVE,
    )
    market["consumption"] = maxdemand
    result = costed_production(market.consumption, costs, capacity, technologies)
    assert isinstance(result, xr.DataArray)
    actual = xr.Dataset(dict(r=result)).groupby("region").sum("asset").r
    assert set(actual.dims) == set(maxdemand.dims)
    for dim in actual.dims:
        assert (actual[dim] == maxdemand[dim]).all()
    assert np.abs(actual - maxdemand).max() < 1e-8


def test_costed_production_single_region(market, capacity, technologies):
    from muse.quantities import (
        annual_levelized_cost_of_energy,
        costed_production,
        maximum_production,
    )
    from muse.timeslices import QuantityType, convert_timeslice
    from muse.utilities import broadcast_techs

    capacity = capacity.drop_vars("region")
    capacity["region"] = "USA"
    market = market.sel(region=[capacity.region.values])
    maxdemand = convert_timeslice(
        maximum_production(technologies, capacity).sum("asset"),
        market,
        QuantityType.EXTENSIVE,
    )
    market["consumption"] = 0.9 * maxdemand
    technodata = broadcast_techs(technologies, capacity)
    costs = annual_levelized_cost_of_energy(
        market.prices.sel(region=technodata.region), technodata
    )
    result = costed_production(market.consumption, costs, capacity, technologies)
    assert isinstance(result, xr.DataArray)
    actual = result.sum("asset")
    assert set(actual.dims) == set(maxdemand.dims)
    for dim in actual.dims:
        assert (actual[dim] == maxdemand[dim]).all()
    assert np.abs(actual - 0.9 * maxdemand).max() < 1e-8


def test_costed_production_single_year(market, capacity, technologies):
    from muse.quantities import (
        annual_levelized_cost_of_energy,
        costed_production,
        maximum_production,
    )
    from muse.timeslices import QuantityType, convert_timeslice
    from muse.utilities import broadcast_techs

    capacity = capacity.sel(year=2010)
    market = market.sel(year=2010)
    maxdemand = convert_timeslice(
        xr.Dataset(dict(mp=maximum_production(technologies, capacity)))
        .groupby("region")
        .sum("asset")
        .mp,
        market,
        QuantityType.EXTENSIVE,
    )
    market["consumption"] = 0.9 * maxdemand
    technodata = broadcast_techs(technologies, capacity)
    costs = annual_levelized_cost_of_energy(
        market.prices.sel(region=technodata.region), technodata
    )
    result = costed_production(market.consumption, costs, capacity, technologies)
    assert isinstance(result, xr.DataArray)
    actual = xr.Dataset(dict(r=result)).groupby("region").sum("asset").r
    assert set(actual.dims) == set(maxdemand.dims)
    for dim in actual.dims:
        assert (actual[dim] == maxdemand[dim]).all()
    assert np.abs(actual - 0.9 * maxdemand).max() < 1e-8


def test_costed_production_over_capacity(market, capacity, technologies):
    from muse.quantities import (
        annual_levelized_cost_of_energy,
        costed_production,
        maximum_production,
    )
    from muse.timeslices import QuantityType, convert_timeslice
    from muse.utilities import broadcast_techs

    capacity = capacity.isel(asset=[0, 1, 2])
    if set(capacity.region.values) != set(market.region.values):
        capacity.region.values[: len(set(market.region.values))] = list(
            set(market.region.values)
        )
    maxdemand = convert_timeslice(
        xr.Dataset(dict(mp=maximum_production(technologies, capacity)))
        .groupby("region")
        .sum("asset")
        .mp,
        market,
        QuantityType.EXTENSIVE,
    )
    market["consumption"] = maxdemand * 0.9
    technodata = broadcast_techs(technologies, capacity)
    costs = annual_levelized_cost_of_energy(
        market.prices.sel(region=technodata.region), technodata
    )
    result = costed_production(market.consumption, costs, capacity, technologies)
    assert isinstance(result, xr.DataArray)
    actual = xr.Dataset(dict(r=result)).groupby("region").sum("asset").r
    assert set(actual.dims) == set(maxdemand.dims)
    for dim in actual.dims:
        assert (actual[dim] == maxdemand[dim]).all()
    assert np.abs(actual - 0.9 * maxdemand).max() < 1e-8


def test_costed_production_with_minimum_service(market, capacity, technologies, rng):
    from muse.quantities import (
        annual_levelized_cost_of_energy,
        costed_production,
        maximum_production,
    )
    from muse.timeslices import QuantityType, convert_timeslice
    from muse.utilities import broadcast_techs

    if set(capacity.region.values) != set(market.region.values):
        capacity.region.values[: len(set(market.region.values))] = list(
            set(market.region.values)
        )
    technologies["minimum_service_factor"] = (
        technologies.utilization_factor.dims,
        rng.uniform(low=0.5, high=0.9, size=technologies.utilization_factor.shape),
    )
    maxprod = convert_timeslice(
        maximum_production(technologies, capacity), market, QuantityType.EXTENSIVE
    )
    minprod = maxprod * broadcast_techs(technologies.minimum_service_factor, maxprod)
    maxdemand = xr.Dataset(dict(mp=minprod)).groupby("region").sum("asset").mp
    market["consumption"] = maxdemand * 0.9
    technodata = broadcast_techs(technologies, capacity)
    costs = annual_levelized_cost_of_energy(
        market.prices.sel(region=technodata.region), technodata
    )
    result = costed_production(market.consumption, costs, capacity, technologies)
    assert isinstance(result, xr.DataArray)
    actual = xr.Dataset(dict(r=result)).groupby("region").sum("asset").r
    assert set(actual.dims) == set(maxdemand.dims)
    for dim in actual.dims:
        assert (actual[dim] == maxdemand[dim]).all()
    assert (actual >= 0.9 * maxdemand - 1e-8).all()
    assert (result >= minprod - 1e-8).all()
