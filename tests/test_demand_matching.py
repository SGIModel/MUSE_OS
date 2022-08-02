from pytest import approx, fixture


@fixture(params=["without c", "with c"])
def demand(request):
    from numpy.random import choice, randint
    from xarray import DataArray

    demand = DataArray(
        randint(0, 10, (5, 3, 4)),
        coords={
            "a": choice(range(15), 5, replace=False),
            "b": choice(list("abcdefghi"), 3, replace=False),
            "c": choice(["🐮", "🐄", "🕙", "📕", "💤", "🐜", "🐘"], 4, replace=False),
        },
        dims=("a", "b", "c"),
    )
    if request.param == "without c":
        demand = demand.sum("c")
    return demand.astype("float64")


@fixture
def cost(demand):
    from numpy.random import randint
    from xarray import DataArray

    return DataArray(
        randint(0, 10, size=demand.shape), coords=demand.coords, dims=demand.dims
    )


@fixture
def dataset(timeslice):
    """cost, demand, max_production, demand matches exactly max production."""
    from numpy.random import choice, randint, random
    from xarray import Dataset

    dataset = Dataset()
    for dim in ("d", "m", "c", "dc", "dm", "cm", "dcm"):
        nitems = randint(1, 10)
        dataset[dim] = dim, choice(list(range(2 * nitems)), nitems, replace=False)

    shape = (len(dataset.c), len(dataset.dc), len(dataset.cm), len(dataset.dcm))
    dataset["cost"] = (("c", "dc", "cm", "dcm"), randint(0, 5, shape).astype("float64"))

    shape = (len(dataset.m), len(dataset.dm), len(dataset.cm), len(dataset.dcm))
    dataset["max_production"] = (
        ("m", "dm", "cm", "dcm"),
        1.0 * randint(0, 10, shape) * (0 == randint(0, 2, shape)),
    )

    summed_production = dataset.max_production.sum(("m", "cm"))
    dc = dataset.dc.copy(data=random(dataset.dc.shape))
    dc_share = dc / dc.sum()
    d = dataset.d.copy(data=random(dataset.d.shape))
    d_share = d / d.sum()
    dataset["demand"] = summed_production * dc_share * d_share
    return dataset


def test_cost_order(dataset):
    from numpy import arange
    from xarray import broadcast

    from muse.demand_matching import demand_matching

    # simplify dataset. bail out if size is too small for test.
    ds = dataset.sum(set(dataset.dims).difference(("dm", "cm")))
    if ds.cm.size < 2:
        return

    # ensure we know which tech is selected and that any one tech can fulfill the whole
    # demand.
    ds.cost[:] = arange(ds.cost.size).reshape(ds.cost.shape)
    ds.max_production[:] = ds.demand.sum()

    # should select first tech
    result = demand_matching(ds.demand, ds.cost)
    actual, dems = broadcast(result.sum(ds.cost.dims), ds.demand)
    assert actual.data == approx(dems.data)
    assert result.sum(ds.demand.dims)[0].data == approx(ds.demand.sum().data)

    # should select first and second tech
    ds.cost[0] = 1
    result = demand_matching(ds.demand, ds.cost)
    actual, dems = broadcast(result.sum(ds.cost.dims), ds.demand)
    assert actual.data == approx(dems.data)
    summed = result.sum(ds.demand.dims).data
    assert summed[0] == approx(summed[1])
    assert 2 * summed[0] == approx(ds.demand.sum().data)

    # should select second tech
    ds.cost[0] = 2
    result = demand_matching(ds.demand, ds.cost)
    actual, dems = broadcast(result.sum(ds.cost.dims), ds.demand)
    assert actual.data == approx(dems.data)
    summed = result.sum(ds.demand.dims).data
    assert summed[1] == approx(ds.demand.sum().data)


def test_no_constraints_no_i_dims(demand, cost):
    from xarray import broadcast

    from muse.demand_matching import demand_matching

    x = demand_matching(demand, cost.sum("b"))
    assert set(x.dims) == set(demand.dims)
    x, expected = broadcast(x, demand)
    assert x.values == approx(expected.values)

    x = demand_matching(demand, cost)
    assert set(x.dims) == set(demand.dims)
    x, expected = broadcast(x, demand)
    assert x.values == approx(expected.values)

    x = demand_matching(demand.sum("a"), cost)
    assert set(x.dims) == set(demand.dims)
    x, expected = broadcast(x.sum("a"), demand.sum("a"))
    assert x.values == approx(expected.values)


def test_no_constraints_i_dims(demand, cost):
    from xarray import broadcast

    from muse.demand_matching import demand_matching

    x = demand_matching(demand.sum("a"), cost)
    assert set(x.dims) == set(demand.dims)
    x, expected = broadcast(x.sum("a"), demand.sum("a"))
    assert x.values == approx(expected.values)

    x = demand_matching(demand.sum("b"), cost)
    assert set(x.dims) == set(demand.dims)
    x, expected = broadcast(x.sum("b"), demand.sum("b"))
    assert x.values == approx(expected.values)


def test_one_non_binding_constraint(demand, cost):
    """Constraint where excess is always 0."""
    from xarray import broadcast

    from muse.demand_matching import demand_matching

    x = demand_matching(demand, cost, 2 * demand)
    assert set(x.dims) == set(demand.dims)
    x, expected = broadcast(x, demand)
    assert x.values == approx(expected.values)

    x = demand_matching(demand, cost, (2 * demand).sum("a"))
    assert set(x.dims) == set(demand.dims)
    x, expected = broadcast(x, demand)
    assert x.values == approx(expected.values)
