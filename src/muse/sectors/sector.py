from __future__ import annotations

from typing import Any, Callable, List, Mapping, Optional, Sequence, Text, Tuple, Union

from pandas import MultiIndex
from xarray import DataArray, Dataset

from muse.agent import AgentBase
from muse.demand_share import DEMAND_SHARE_SIGNATURE
from muse.production import PRODUCTION_SIGNATURE
from muse.sectors.abstract import AbstractSector
from muse.sectors.register import register_sector


@register_sector(name="default")
class Sector(AbstractSector):  # type: ignore
    """Base class for all sectors."""

    @classmethod
    def factory(cls, name: Text, settings: Any) -> Sector:
        from muse.readers import read_timeslices, read_technologies
        from muse.utilities import nametuple_to_dict
        from muse.outputs import factory as ofactory
        from muse.production import factory as pfactory
        from muse.interactions import factory as interaction_factory
        from muse.demand_share import factory as share_factory
        from muse.agent import agents_factory
        from logging import getLogger

        sector_settings = getattr(settings.sectors, name)._asdict()
        for attribute in ("name", "type", "priority", "path"):
            sector_settings.pop(attribute, None)

        timeslices = read_timeslices(
            sector_settings.pop("timeslice_levels", None)
        ).get_index("timeslice")

        # We get and filter the technologies
        technologies = read_technologies(
            sector_settings.pop("technodata"),
            sector_settings.pop("commodities_out"),
            sector_settings.pop("commodities_in"),
            commodities=settings.global_input_files.global_commodities,
        )
        ins = (technologies.fixed_inputs > 0).any(("year", "region", "technology"))
        outs = (technologies.fixed_outputs > 0).any(("year", "region", "technology"))
        techcomms = technologies.commodity[ins | outs]
        technologies = technologies.sel(commodity=techcomms, region=settings.regions)

        # Finally, we create the agents
        agents = agents_factory(
            sector_settings.pop("agents"),
            sector_settings.pop("existing_capacity"),
            technologies=technologies,
            regions=settings.regions,
            year=min(settings.time_framework),
        )

        # make sure technologies includes the requisite years
        maxyear = max(a.forecast for a in agents) + max(settings.time_framework)
        if technologies.year.max() < maxyear:
            msg = "Forward-filling technodata to fit simulation timeframe"
            getLogger(__name__).info(msg)
            years = technologies.year.data.tolist() + [maxyear]
            technologies = technologies.sel(year=years, method="ffill")
            technologies["year"] = "year", years
        minyear = min(settings.time_framework)
        if technologies.year.min() > minyear:
            msg = "Back-filling technodata to fit simulation timeframe"
            getLogger(__name__).info(msg)
            years = [minyear] + technologies.year.data.tolist()
            technologies = technologies.sel(year=years, method="bfill")
            technologies["year"] = "year", years

        outputs = ofactory(*sector_settings.pop("outputs", []))

        production_args = sector_settings.pop(
            "production", sector_settings.pop("investment_production", {})
        )
        if isinstance(production_args, Text):
            production_args = {"name": production_args}
        else:
            production_args = nametuple_to_dict(production_args)
        production = pfactory(**production_args)

        supply_args = sector_settings.pop(
            "supply", sector_settings.pop("dispatch_production", {})
        )
        if isinstance(supply_args, Text):
            supply_args = {"name": supply_args}
        else:
            supply_args = nametuple_to_dict(supply_args)
        supply = pfactory(**supply_args)

        interactions = interaction_factory(sector_settings.pop("interactions", None))

        demand_share = share_factory(sector_settings.pop("demand_share", None))

        return cls(
            name,
            technologies,
            agents,
            timeslices=timeslices,
            production=production,
            supply_prod=supply,
            outputs=outputs,
            interactions=interactions,
            demand_share=demand_share,
            **sector_settings,
        )

    def __init__(
        self,
        name: Text,
        technologies: Dataset,
        agents: Sequence[AgentBase] = [],
        timeslices: Optional[MultiIndex] = None,
        interactions: Optional[Callable[[Sequence[AgentBase]], None]] = None,
        interpolation: Text = "linear",
        outputs: Optional[Callable] = None,
        production: Optional[PRODUCTION_SIGNATURE] = None,
        supply_prod: Optional[PRODUCTION_SIGNATURE] = None,
        demand_share: Optional[DEMAND_SHARE_SIGNATURE] = None,
    ):
        from muse.production import maximum_production
        from muse.outputs import factory as ofactory
        from muse.interactions import factory as interaction_factory
        from muse.demand_share import factory as share_factory

        self.name: Text = name
        """Name of the sector."""
        self.agents: List[AgentBase] = list(agents)
        """Agents controlled by this object."""
        self.technologies: Dataset = technologies
        """Parameters describing the sector's technologies."""
        self.timeslices: Optional[MultiIndex] = timeslices
        """Timeslice at which this sector operates.

        If None, it will operate using the timeslice of the input market.
        """
        self.interpolation: Mapping[Text, Any] = {
            "method": interpolation,
            "kwargs": {"fill_value": "extrapolate"},
        }
        """Interpolation method and arguments when computing years."""
        if interactions is None:
            interactions = interaction_factory()
        self.interactions = interactions
        """Interactions between agents.

        Called right before computing new investments, this function should manage any
        interactions between agents, e.g. passing assets from *new* agents  to *retro*
        agents, and maket make-up from *retro* to *new*.

        Defaults to doing nothing.

        The function takes the sequence of agents as input, and returns nothing. It is
        expected to modify the agents in-place.

        See Also
        --------

        :py:mod:`muse.interactions` contains MUSE's base interactions
        """
        self.outputs: Callable = (  # type: ignore
            ofactory() if outputs is None else outputs
        )
        """A function for outputing data for post-mortem analysis."""
        self.production = production if production is not None else maximum_production
        """ Computes production as used for investment demands.

        It can be anything registered with
        :py:func:`@register_production<muse.production.register_production>`.
        """
        self.supply_prod = (
            supply_prod if supply_prod is not None else maximum_production
        )
        """ Computes production as used to return the supply to the MCA.

        It can be anything registered with
        :py:func:`@register_production<muse.production.register_production>`.
        """
        if demand_share is None:
            demand_share = share_factory()
        self.demand_share = demand_share
        """Method defining how to split the input demand amongst agents.

        This is a function registered by :py:func:`@register_demand_share
        <muse.demand_share.register_demand_share>`.
        """

    @property
    def forecast(self):
        """Maximum forecast horizon across agents.

        If no agents with a "forecast" attribute are found, defaults to 5. It cannot be
        lower than 1 year.
        """
        forecasts = [
            getattr(agent, "forecast")
            for agent in self.agents
            if hasattr(agent, "forecast")
        ]
        if len(forecasts) == 0:
            return 5
        return max(1, max(forecasts))

    def next(self, mca_market: Dataset, time_period: Optional[int] = None) -> Dataset:
        """Advance sector by one time period.

        Args:
            mca_market:
                Market with ``demand``, ``supply``, and ``prices``.
            time_period:
                Length of the time period in the framework. Defaults to the range of
                ``mca_market.year``.

        Returns:
            A market containing the ``supply`` offered by the sector, it's attendant
            ``consumption`` of fuels and materials and the associated ``costs``.
        """
        from logging import getLogger

        if time_period is None:
            time_period = int(mca_market.year.max() - mca_market.year.min())
        getLogger(__name__).info(f"Running {self.name} for year {time_period}")

        # > to sector timeslice
        market = self.convert_market_timeslice(
            mca_market.sel(
                commodity=self.technologies.commodity, region=self.technologies.region
            ).interp(
                year=sorted(
                    {
                        int(mca_market.year.min()),
                        int(mca_market.year.min()) + time_period,
                        int(mca_market.year.min()) + self.forecast,
                    }
                ),
                **self.interpolation,
            ),
            self.timeslices,
        )
        # > agent interactions
        self.interactions(self.agents)
        # > investment
        years = sorted(
            set(
                market.year.data.tolist()
                + self.capacity.installed.data.tolist()
                + self.technologies.year.data.tolist()
            )
        )
        technologies = self.technologies.interp(year=years, **self.interpolation)
        self.investment(market, technologies, time_period=time_period)
        # > output to mca
        result = self.market_variables(market, technologies)
        # < output to mca
        self.outputs(self.capacity, result, technologies, sector=self.name)
        # > to mca timeslices
        result = self.convert_market_timeslice(
            result.groupby("region").sum("asset"), mca_market.timeslice
        )
        result["comm_usage"] = technologies.comm_usage.sel(commodity=result.commodity)
        result.set_coords("comm_usage")
        # < to mca timeslices
        return result

    def market_variables(self, market: Dataset, technologies: Dataset) -> Dataset:
        """Computes resulting market: production, consumption, and costs."""
        from muse.quantities import (
            consumption,
            supply_cost,
            annual_levelized_cost_of_energy,
        )
        from muse.commodities import is_pollutant

        years = market.year.values
        capacity = self.capacity.interp(year=years, **self.interpolation)

        result = Dataset()
        result["supply"] = self.supply_prod(
            market=market, capacity=capacity, technologies=technologies
        )
        result["consumption"] = consumption(technologies, result.supply, market.prices)
        result["costs"] = supply_cost(
            result.supply.where(~is_pollutant(result.comm_usage), 0),
            annual_levelized_cost_of_energy(market.prices, technologies),
        ).sum("technology")
        return result

    def investment(
        self, market: Dataset, technologies: Dataset, time_period: Optional[int] = None
    ) -> None:
        """Computes demand share for each agent and run investment."""
        from logging import getLogger

        if time_period is None:
            time_period = int(market.year.max() - market.year.min())

        shares = self.demand_share(  # type: ignore
            self.agents,
            market,
            technologies,
            current_year=market.year.min(),
            forecast=self.forecast,
        )
        capacity = self.capacity.interp(
            year=market.year,
            method=self.interpolation["method"],
            kwargs={"fill_value": 0.0},
        )
        agent_market = market.copy()
        agent_market["capacity"] = self.asset_capacity(capacity)

        for agent in self.agents:
            assert market.year.min() == getattr(agent, "year", market.year.min())
            if shares[agent.uuid].size == 0:
                getLogger(__name__).critical(
                    "Demand share is empty, no investment needed "
                    f"for {agent.category} agent {agent.name} "
                    f"of {self.name} sector in year {int(agent_market.year.min())}."
                )
            elif shares[agent.uuid].sum() < 1e-12:
                getLogger(__name__).critical(
                    "No demand, no investment needed for "
                    f"for {agent.category} agent {agent.name} "
                    f"of {self.name} sector in year {int(agent_market.year.min())}."
                )

            agent.next(
                technologies, agent_market, shares[agent.uuid], time_period=time_period
            )

    @property
    def capacity(self) -> DataArray:
        """Aggregates capacity across agents.

        The capacities are aggregated leaving only two
        dimensions: asset (technology, installation date,
        region), year.
        """
        from muse.utilities import reduce_assets

        return reduce_assets([u.assets.capacity for u in self.agents])

    def _trajectory(self, market: Dataset, capacity: DataArray, technologies: Dataset):
        from muse.quantities import supply

        production = self.production(
            market=market, capacity=capacity, technologies=technologies
        )
        supp = supply(production, market.consumption, technologies).sum("asset")
        return (market.consumption - supp).clip(min=0)

    def decommissioning_demand(
        self, capacity: DataArray, technologies: Dataset, year: int
    ) -> DataArray:
        from muse.quantities import decommissioning_demand

        return decommissioning_demand(
            technologies, capacity, [int(year), int(year) + self.forecast]
        )

    def asset_capacity(self, capacity: DataArray) -> DataArray:
        from muse.utilities import reduce_assets, coords_to_multiindex

        capa = reduce_assets(capacity, ("region", "technology"))
        return coords_to_multiindex(capa, "asset").unstack("asset").fillna(0)

    def demands(
        self, year: int, capacity: DataArray, market: Dataset, technologies: Dataset
    ) -> Dataset:
        r"""Asset-based demands.

        Computes the demands for all agents and regions in one go.
        The demands are:

        - new_demand: considering the supply in current year, extra demand needed
          (compared to current year) to fulfill the additional demand from forecast
          year.
        - retrofit_demand: the lesser of the unmet demand in current and forecast year.

        Args:
            capacity: generally, the aggregate assets across the sector,
                :math:`A^{r}_a(y) = \sum_iA^{i, r}_a(y)`.
            market: the input MCA market transformed to sector timeslices
            technologies: quantities describing the technologies.

        Pseudo-code:

        #. the capacity is expanded over timeslices (extensive quantity) and aggregated
           over agents. Generally:

           .. math::

               A_{a, s}^r = w_s\sum_i A_a^{r, i}

           with :math:`w_s` a weight associated with each timeslice and determined via
           :py:func:`muse.timeslices.convert_timeslice`.

        #. An intermediate quantity, the *unmet* demand :math:`U` is defined from
           :math:`P[\mathcal{M}, \mathcal{A}]`, a function giving the production for a
           given market :math:`\mathcal{M}`, the associated consumption
           :math:`\mathcal{C}`, and aggregate assets :math:`\mathcal{A}`:

           .. math::
               U[\mathcal{M}, \mathcal{A}] =
                 \max(\mathcal{C} - P[\mathcal{M}, \mathcal{A}], 0)

           where :math:`\max` operates element-wise, and indices have been dropped for
           simplicity. The resulting expression has the same indices as the consumption
           :math:`\mathcal{C}_{c, s}^r`.

           :math:`P` is any function registered with
           :py:func:`@register_production<muse.production.register_production>`.
           It is the the attribute :py:attr:`production`.


        #. the *retrofit* demand :math:`M` is the lesser of the current and future
           *unmet* demand defined previously:

           .. math::

               M = \min\left(
                   U[\mathcal{M}^r(y), \mathcal{A}_{a, s}^r(y)],
                   U[\mathcal{M}^r(y+1), \mathcal{A}_{a, s}^r(y + 1)]
               \right)

        #. the *new* demand :math:`N` is defined as the lesser between the
            year-on-year (or period to period) increase in consumption and the *unmet*
            demand for the future period from the current capacity.

            .. math::

                N = \min\left(
                    \mathcal{C}_{c, s}^r(y + 1) - \mathcal{C}_{c, s}^r(y),
                    U[\mathcal{M}^r(y+1), \mathcal{A}_{a, s}^r(y)]
                \right)

        .. SeeAlso::

            :ref:`indices`, :ref:`quantities`,
            :ref:`Agent investments<model, agent investment>`,
            :py:func:`muse.quantities.maximum_production`
        """
        from muse.timeslices import convert_timeslice, QuantityType

        data = market.copy(deep=False)
        data["ts_capa"] = convert_timeslice(
            capacity, market.timeslice, QuantityType.EXTENSIVE
        )
        current = data.sel(year=year, drop=True)
        forecast = data.sel(year=year + self.forecast, drop=True)

        market_vars = list(market.data_vars.keys())
        delta = (forecast.consumption - current.consumption).clip(min=0)
        missing = self._trajectory(forecast[market_vars], current.ts_capa, technologies)
        now = self._trajectory(current[market_vars], forecast.ts_capa, technologies)
        future = self._trajectory(forecast[market_vars], forecast.ts_capa, technologies)

        result = Dataset(
            {
                "new_demand": delta.where(delta < missing, missing),
                "retrofit_demand": now.where(now < future, future),
            }
        )

        if getattr(getattr(result, "region", None), "size", 0) > 1:
            result = result.groupby("region")

        return result

    @staticmethod
    def convert_market_timeslice(
        market: Dataset,
        timeslice: MultiIndex,
        intensive: Union[Text, Tuple[Text]] = "prices",
    ) -> Dataset:
        """Converts market from one to another timeslice."""
        from xarray import merge
        from muse.timeslices import convert_timeslice, QuantityType

        if isinstance(intensive, Text):
            intensive = (intensive,)

        timesliced = {d for d in market.data_vars if "timeslice" in market[d].dims}
        intensives = convert_timeslice(
            market[list(timesliced.intersection(intensive))],
            timeslice,
            QuantityType.INTENSIVE,
        )
        extensives = convert_timeslice(
            market[list(timesliced.difference(intensives.data_vars))],
            timeslice,
            QuantityType.EXTENSIVE,
        )
        others = market[list(set(market.data_vars).difference(timesliced))]
        return merge([intensives, extensives, others])