r"""Collection of demand-matching algorithms.

At it's simplest, the demand matching algorithm solves the following problem,

- given a demand for a commodity :math:`D_d`, with :math:`d\in\mathcal{D}`
- given processes to supply these commodities, with an associated cost per process,
  :math:`C_{d, i}`, with :math:`i\in\mathcal{I}`

Match demand and supply while minimizing the associated cost.

.. math::

   \min_{X} \sum_{d, i} C_{d,i} X_{d, i}

   X_{d, i} \geq 0

   \sum_o X_o \geq D_d

The basic algorithm proceeds as follows:

#. sort all costs :math:`C_{d, i}` accross both :math:`d` and :math:`i`

#. for each cost :math:`c_0` in order:

    #. find the set of indices :math:`\mathcal{C}\subseteq\mathcal{D}\cup\mathcal{I}`
       for which

        .. math::

            \forall (d, i) \in \mathcal{C}\quad C_{d, i} == c_0

    #. determine the partial result for the current cost

        .. math::

            \forall (d, i) \in \mathcal{C}\quad X_{d, i} = \frac{D_d}{|i\in\mathcal{C}|}

        Where :math:`|i\in\mathcal{C}|` indicates the number of indices :math:`i` in
        :math:`\mathcal{C}`.

However, in practice, the problem to solve often contains constraints, e.g. a constraint
on production :math:`\sum_d X_{d, i} \leq M_i`. The algorithms in this module try and
solve these constrained problems one way or another.
"""
__all__ = ["demand_matching"]


from typing import Optional, Set

from xarray import DataArray


def demand_matching(
    demand: DataArray,
    cost: DataArray,
    *constraints: DataArray,
    protected_dims: Optional[Set] = None,
) -> DataArray:
    r"""Demand matching over heterogenous dimensions.

    This algorithm enables demand matching while enforcing constraints on how much an
    asset can produce. Any set of dimensions can be matched. The algorithm is general
    with respect to the dimensions in demand and cost. It also enforces constraints over
    sets of indices.


    .. math::

        \min_{X} \sum_{d, i} C_{d, i} X_{d, i}

        X_{d, i} \geq 0

        \sum_i X_{d, i} \geq D_d

        M_{(d, i) \in \mathcal{R}^{(\alpha)}}^{(\alpha)}
            \geq \sum_{(d, i)\notin\mathcal{R}^{(\alpha)}} X_{d, i}

    Where :math:`\alpha` is an index running over constraints,
    :math:`\mathcal{R}^{(\alpha)}\subseteq\mathcal{D}\cup\mathcal{I}` is a subset of
    indices.

    The algorithm proceeds as described in :py:mod:`muse.demand_matching`.
    However, an extra step is added to ensure that the solutions falls within the
    convex-hull formed by the constraints. This projects the current solution onto the
    constraint. Hence, the solution will depend on the order in which the constraints
    are given.

    #. sort all costs :math:`C_{d, m}` accross both :math:`d` and :math:`m`

    #. for each cost :math:`c_0` in order:

        #. find the set of indices :math:`\mathcal{C}`

            .. math::

                \mathcal{C}\subseteq\mathcal{D}\cup\mathcal{I}

                \forall (d, i) \in \mathcal{C}\quad C_{d, i} == c_0

        #. determine an interim partial result for the current cost

            .. math::

                \forall (d, i) \in \mathcal{C}\quad
                \delta X_{d, i} = \frac{1}{|i\in\mathcal{C}|}\left(
                    D_d - \sum_{j \in \mathcal{I}} X_{d, j}\right)

            Where :math:`|i\in\mathcal{C}|` indicates the number of :math:`i` indices in
            :math:`\mathcal{C}`. The expression in the parenthesis is the currently
            unserviced demand.

        #. Loop over each constraint :math:`\alpha`. Below we drop the index
           :math:`\alpha` over constraints for simplicity.

            #. Determine the excess over the constraint:

                .. math::

                    E_{(d, i) \in \mathcal{R}} = \max\left\{
                        0,
                        \sum_{(d, i)\notin\mathcal{R}}\left(
                            X_{d, i} + \delta X_{d, i}
                        \right) - M_{(d, i) \in \mathcal{R}}
                    \right\}

            #. Correct :math:`\delta X` as follows:

                .. math::

                    \forall (d, i) \in \mathcal{C}\cap\mathcal{R}\quad
                    \delta X\prime_{d, i} =
                        E_{(d, i)}
                        \frac{\delta X_{(d, i)}}{
                            \sum_{(e, j)\in \mathcal{C}\cap\mathcal{R}} \delta X_{(e,j)}
                        }


                    \forall (d, i) \notin \mathcal{R}, (d, i)\in\mathcal{C} \quad
                    \delta X\prime_{d, i} = 0

            #. Set :math:`\delta X = \max(0, \delta X - \delta X\prime)`


    A more complex problem would see independant dimensions for each quantity. In that,
    case we can reduce to the original problem as shown here

    .. math::

        C_{d, i, c} = \min_cC\prime_{d, i, c}

        D_d = \sum_{d\prime} D\prime_{d, d\prime}

        M_r = \sum_m M\prime_{r, m}

        X_{d, d\prime, i, m, c} =
            \left(C\prime_{d, i, c} == C_{d, i}\right)
            \frac{M\prime_{r, m}}{M_r} \frac{D\prime_{d, d\prime}}{D_d} X_{d, i}

    A dimension could be shared by all quantities, in which case each point along that
    dimension is treated as independant.

    Similarly, if a dimension is shared only by the demand and a constraint but not by
    the cost, then the problem can be reduced a set of problems independant along that
    direction.

    Arguments:
        demand: Demand to match with production. It should have the same physical units
            as `max_production`.
        cost: Cost to minimize while fulfiling the demand.
        *constraints: each item is a seperate constraint :math:`M_r`.

    Returns:
        An array with the joint dimensionality of `max_production`, `cost`, and
        `demand`, containing the supply that fulfills the demand. The units of this
        supply are the same as `demand` and `max_production`.
    """
    from pandas import MultiIndex
    from xarray import Dataset

    if protected_dims is None:
        protected_dims = set()

    # demand has extra dimensions unique to it
    extra_dims = set(demand.dims).difference(
        cost.dims, *(cons.dims for cons in constraints)
    )

    if extra_dims:
        summed_demand = demand.sum(extra_dims)
        demand_share = (demand / summed_demand).where(demand > 0, 0)
        result = demand_matching(summed_demand, cost, *constraints)
        return demand_share * result

    # a constraint has dimensions unique to it
    for i, constraint in enumerate(constraints):
        others = [cons for j, cons in enumerate(constraints) if j != i]
        extra_dims = set(constraint.dims).difference(
            demand.dims, cost.dims, *(cons.dims for cons in others), protected_dims
        )
        if extra_dims:
            summed_constraint = constraint.sum(extra_dims)
            share = (constraint / summed_constraint).where(constraint > 0, 0)
            others.insert(i, summed_constraint)
            result = demand_matching(demand, cost, *others)
            return share * result

    # cost has extra dimensions unique to it
    extra_dims = set(cost.dims).difference(
        demand.dims, *(cons.dims for cons in constraints), protected_dims
    )
    if extra_dims:
        mincost = cost.min(extra_dims)
        result = demand_matching(demand, mincost, *constraints)
        structure = cost == mincost
        cost_share = (1 / structure.sum(extra_dims)).where(structure, 0)
        return result * cost_share

    # missing coordinates in max_production
    # add a fake coordinate so that the individual items in coordinate-less dimension
    # can be addressed at the end of the main loop.
    ds = Dataset(
        {
            **{f"constraint{i}": cons for i, cons in enumerate(constraints)},
            "cost": cost,
            "demand": demand,
        }
    )

    nocoords = set(ds.dims).difference(ds.coords.keys())

    if nocoords:
        for coord in nocoords:
            ds.coords[coord] = coord, ds.coords[coord].values
        result = demand_matching(  # type: ignore
            ds.demand, ds.cost, *(ds[f"constraint{i}"] for i in range(len(constraints)))
        )
        return result.drop_vars(nocoords)

    # multi-index dimensions seem to make life complicated for groupby
    # so drop them for the duration of the call.
    # see https://github.com/pydata/xarray/issues/1603
    multics = {
        k: ds.coords[k] for k in ds.dims if isinstance(ds.get_index(k), MultiIndex)
    }

    if len(multics) > 0:
        for k in multics:
            ds.coords[k] = list(range(len(ds[k])))
        result = demand_matching(  # type: ignore
            ds.demand, ds.cost, *(ds[f"constraint{i}"] for i in range(len(constraints)))
        )
        for k, v in multics.items():
            result.coords[k] = v
        return result
    return _demand_matching_impl(demand, cost, *constraints)


def _demand_matching_impl(
    demand: DataArray, cost: DataArray, *constraints: DataArray
) -> DataArray:
    """Implementation of demand matching.

    It is expected that demand does not have dimension unique to itself, and that all
    dimensions have coordinates. Input sanitization is performed in `demand_matching`
    proper.
    """
    from numpy import isnan, prod
    from xarray import Dataset, align, full_like

    assert not set(demand.dims).difference(
        cost.dims, *(cons.dims for cons in constraints)
    )

    result = full_like(sum(constraints) + demand + cost, 0)  # type: ignore
    names = [f"constraint{i}" for i in range(len(constraints))]
    data = Dataset(
        {
            "cost": cost,
            "demand": demand.copy(deep=True),
            **dict(zip(names, constraints)),
        }
    )

    def expand_dims(x, like):
        """Add extra dims that are in ``like``."""
        N = max(1, prod([len(like[d]) for d in like.dims if d not in x.dims]))
        b = (x / N).expand_dims(**{d: like[d] for d in like.dims if d not in x.dims})
        return b

    def remove_dims(x, to):
        """Remove extra dims that are not in ``to``."""
        extras = set(x.dims).difference(to.dims)
        a = x.sum(extras) / (~isnan(x)).sum(extras)
        return a

    idims = [dim for dim in result.dims if dim not in demand.dims]
    for _, same_cost in data.groupby("cost") if cost.dims else [(cost, data)]:
        current = same_cost.drop_vars("cost").unstack()
        # do not reindex if current has different dimension than demand
        # this may happen if cost is the same across timeslices for many replacement
        if len(current.dims) < len(demand.dims):
            current = current.reindex_like(demand)
            current["demand"].fillna(demand.values)
            for cname in names:
                if "replacement" in data[cname].dims:
                    current[cname] = data[cname].where(
                        data[cname].replacement == current.replacement
                    )
        assert (~isnan(result)).all()

        # current.dims may differ from demand.dims
        # typically it may contain the replacement dimension
        delta_x = expand_dims((demand - result.sum(idims)).clip(0), current)

        for cname in names:
            constraint = remove_dims(current[cname], data[cname])

            constraint = (constraint - result).clip(0)

            delta_x, constraint = align(delta_x, constraint, join="outer", fill_value=0)

            excess = (
                result.sum(set(data.dims).difference(data[cname].dims))
                + delta_x.sum(set(data.dims).difference(data[cname].dims))
                - constraint
            ).clip(min=0)

            excess_share = (
                excess
                * (
                    delta_x / delta_x.sum(set(delta_x.dims).difference(constraint.dims))
                ).fillna(0)
            ).fillna(0)
            delta_x = (expand_dims(delta_x, excess_share) - excess_share).clip(0)
        result = sum(align(result, delta_x.fillna(0), fill_value=0, join="left"))

    return result
