.. _simulation-settings:

===================
Simulation settings
===================

.. currentmodule:: muse

This section details the TOML input for MUSE. The format for TOML files is
described in this :ref:`previous section <toml-primer>`. Here, however, we focus on sections and
attributes that are specific to MUSE.

The TOML file can be read using :py:func:`~readers.toml.read_settings`. The resulting
data is used to construt the market clearing algorithm directly in the :py:meth:`MCA's
factory function <mca.MCA.factory>`.

------------
Main section
------------

This is the topmost section. It contains settings relevant to the simulation as
a whole.

.. code-block:: TOML

   time_framework = [2020, 2025, 2030, 2035, 2040, 2045, 2050]
   regions = ["USA"]
   interpolation_mode = 'Active'
   log_level = 'info'

   equilibrium_variable = 'demand'
   maximum_iterations = 100
   tolerance = 0.1
   tolerance_unmet_demand = -0.1

time_framework
   Required. List of years for which the simulation will run.

region
   Subset of regions to consider. If not given, defaults to all regions found in the
   simulation data.

interpolation_mode
   interpolation when reading the initial market. One of
   `linear`, `nearest`, `zero`, `slinear`, `quadratic`, `cubic`. Defaults to `linear`.

   * `linear` interpolates using a `linear function <https://en.wikipedia.org/wiki/Linear_interpolation>`_.

   * `nearest` uses `nearest-neighbour interpolation <https://en.wikipedia.org/wiki/Nearest-neighbor_interpolation>`_. That is, the closest known data point is used as the prediction for the data point to interpolate.

   * `zero` assumes that the data point to interpolate is zero.

   * `slinear` uses a spline of order 1. This is a similar method to `linear` interpolation.

   * `quadratic` uses a quadratic equation for interpolation. This should be used if you expect your data to take a quadratic form.

   * `cubic` interpolation is similar to `quadratic` interpolation, but uses a cubic function for interpolation.



log_level:
   verbosity of the output.

equilibirum_variable
   whether equilibrium of `demand` or `prices` should be sought. Defaults to `demand`.

maximum_iterations
   Maximum number of iterations when searching for equilibrium. Defaults to 3.

tolerance
   Tolerance criteria when checking for equilibrium. Defaults to 0.1. 0.1 signifies that 10% of a deviation is allowed among the iterative value of either demand or price over a year per region.

tolerance_unmet_demand
   Criteria checking whether the demand has been met.  Defaults to -0.1.

excluded_commodities
   List of commodities excluded from the equilibrium considerations. Defaults to the
   list `["CO2f", "CO2r", "CO2c", "CO2s", "CH4", "N2O", "f-gases"]`.

plugins
    Path or list of paths to extra python plugins, i.e. files with registered functions
    such as :py:meth:`~muse.outputs.register_output_quantity`.


outputs_cache
   This option behaves exactly like `outputs` below for sectors and accepts the same options but
   controls the output of cached quantities instead. This option is NOT available for
   sectors themselves (i.e using `[[sector.comercial.outputs_cache]]` will have no effect). See
   :py:mod:`muse.outputs.cache` for more details.

   A single row looks like this:

   .. code-block:: TOML

      [[outputs_cache]]
      quantity = "production"
      sink = "aggregate"
      filename = "{cwd}/{default_output_dir}/Cache{Quantity}.csv"
      index = false

-------------
Carbon market
-------------

This section containts the settings related to the modelling of the carbon market. If omitted, it defaults to not
including the carbon market in the simulation.

Example

.. code-block:: TOML

   [carbon_budget_control]
   budget = []

budget
   Yearly budget. There should be one item for each year the simulation will run. In
   other words, if given and not empty, this is a list with the same length as
   `time_framework` from the main section. If not given or an empty list, then the
   carbon market feature is disabled. Defaults to an empty list.

method
   Method used to equilibrate the carbon market. The only preset option is `fitting`, however this can be expanded with the `@register_carbon_budget_fitter` hook in `muse.carbon_budget`.

   The market-clearing algortihm iterates over the sectors until the market reaches an equilibrium in the foresight period (the period next to the one analysed). This is represented by a stable variation of a commodity demand (or price) between iterations below a defined tolerance. The market-clearing algorithm samples a user-defined set of carbon prices and estimates a regression model of the global emissions as a function of the carbon price. The regression model is set by the user. The new carbon price is estimated as a root of the regression model estimated at the value of the emission equal to the user-defined emission cap in the foresight period.

commodities
   Commodities that make up the carbon market. Defaults to an empty list.

control_undershoot
   Whether to control carbon budget undershoots. This parameter allows for carbon tax credit from one year to be passed to the next in the case of less carbon being emitted than the budget. Defaults to True.

control_overshoot
   Whether to control carbon budget overshoots. If the amount of carbon emitted is above the carbon budget, this parameter specifies whether this deficit is carried over to the next year. Defaults to True.

method_options:
   Additional options for the specific carbon method.

   `fitter` specifies the regression model fit. Predefined options are `linear` and `exponential`. Further options can be defined using the `@register_carbon_budget_fitter` hook in `muse.carbon_budget`.


------------------
Global input files
------------------

Defines the paths specific simulation data files. The paths can be formatted as
explained in the :ref:`toml-primer`.

.. code-block:: TOML

   [global_input_files]
   projections = '{path}/inputs/Projections.csv'
   regions = '{path}/inputs/Regions.csv'
   global_commodities = '{path}/inputs/MUSEGlobalCommodities.csv'

projections:
   Path to a csv file giving initial market projection. See :ref:`inputs-projection`.

global_commodities:
   Path to a csv file describing the comodities in the simulation. See
   :ref:`inputs-commodities`.

.. _timeslices_toml:

----------
Timeslices
----------

Time-slices represent a sub-year disaggregation of commodity demand. Generally,
timeslices are expected to introduce several levels, e.g. season, day, or hour. The
simplest is to show the TOML for the default timeslice:

.. code-block:: TOML

    [timeslices]
    winter.weekday.night = 396
    winter.weekday.morning = 396
    winter.weekday.afternoon = 264
    winter.weekday.early-peak = 66
    winter.weekday.late-peak = 66
    winter.weekday.evening = 396
    winter.weekend.night = 156
    winter.weekend.morning = 156
    winter.weekend.afternoon = 156
    winter.weekend.evening = 156
    spring-autumn.weekday.night = 792
    spring-autumn.weekday.morning = 792
    spring-autumn.weekday.afternoon = 528
    spring-autumn.weekday.early-peak = 132
    spring-autumn.weekday.late-peak = 132
    spring-autumn.weekday.evening = 792
    spring-autumn.weekend.night = 300
    spring-autumn.weekend.morning = 300
    spring-autumn.weekend.afternoon = 300
    spring-autumn.weekend.evening = 300
    summer.weekday.night = 396
    summer.weekday.morning  = 396
    summer.weekday.afternoon = 264
    summer.weekday.early-peak = 66
    summer.weekday.late-peak = 66
    summer.weekday.evening = 396
    summer.weekend.night = 150
    summer.weekend.morning = 150
    summer.weekend.afternoon = 150
    summer.weekend.evening = 150
    level_names = ["month", "day", "hour"]

This input introduces three levels, via ``level_names``: ``month``, ``day``, ``hours``.
Other simulations may want fewer or more levels.  The ``month`` level is split into
three points of data, ``winter``, ``spring-autumn``, ``summer``. Then ``day`` splits out
weekdays from weekends, and so on. Each line indicates the number of hours for the
relevant slice. It should be noted that the slices are not a cartesian products of each
levels. For instance, there no ``peak`` periods during weekends. All that matters is
that the relative weights (i.e. the number of hours) are consistent and sum up to a
year.

The input above defines the finest times slice in the code. In order to define rougher
timeslices we can introduce items in each levels that represent aggregates at that
level. By default, we have the following:

.. code-block:: TOML

    [timeslices.aggregates]
    all-day = ["night", "morning", "afternoon", "early-peak", "late-peak", "evening"]
    all-week = ["weekday", "weekend"]
    all-year = ["winter", "summer", "spring-autumn"]

Here, ``all-day`` aggregates the full day. However, one could potentially create
aggregates such as:

.. code-block:: TOML

    [timeslices.aggregates]
    daylight = ["morning", "afternoon", "early-peak", "late-peak"]
    nightlife = ["evening", "night"]

Once the finest timeslice and its aggregates are given, it is  possible for each sector
to define the timeslice simply by refering to the slices it will use at each level.

.. code-block:: TOML

    [sectors.some_sector.timeslice_levels]
    day = ["daylight", "nightlife"]
    month = ["all-year"]

Above, ``sectors.some_sector.timeslice_levels.week`` defaults its value in the finest
timeslice. Indeed, if the subsection ``sectors.some_sector.timeslice_levels`` is not
given, then the sector will default to using the finest timeslices.

Similarly, it is possible to specify a timeslice for the mca by adding an
`mca.timeslice_levels` section. However, be aware that if the MCA uses a rougher
timeslice framework, the market will be expressed within it. Hence information from
sectors with a finer timeslice framework will be lost.

----------------
Standard sectors
----------------

Sectors are declared in the TOML file by adding a subsection to the `sectors` section:

.. code-block:: TOML

   [sectors.residential]
   type = 'default'
   [sectors.power]
   type = 'default'

Above, we've added two sectors, residential and power. The name of the subsection is
only used for identification. In other words, it should be chosen to be meaningful to
the user, since it will not affect the model itself.

Sectors are defined in :py:class:`~muse.sectors.Sector`.

A sector accepts a number of attributes and subsections.

.. _sector-type:

type
   Defines the kind of sector this is. *Standard* sectors are those with type
   "default". This value corresponds to the name with which a sector class is registerd
   with MUSE, via :py:meth:`~muse.sectors.register_sector`. [INSERT OTHER OPTIONS HERE]

.. _sector-priority:

priority
   An integer denoting which sectors runs when. Lower values imply the sector will run
   earlier. If two sectors share the same priority. Later sectors can depend on earlier
   sectors for the their input. If two sectors share the same priority, then their
   order is not defined. Indeed, it should indicate that they can run in parallel.
   For simplicity, the keyword also accepts standard values:

   - "preset": 0
   - "demand": 10
   - "conversion": 20
   - "supply": 30
   - "last": 100
   
   Defaults to "last".

interpolation
   Interpolation method user when filling in missing values. Available interpolation
   methods depend on the underlying `scipy method's kind attribute`_.
   
   .. _scipy method's kind attribute: https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.interp1d.html

investment_production
   In its simplest form, this is the name of a method to compute the production from a
   sector, as used when splitting the demand across agents. In other words, this is the
   computation of the production which affects future investments. In it's more general
   form, *production* can be a subsection of its own, with a "name" attribute. For
   instance:

   .. code-block:: TOML

      [sectors.residential.production]
      name = "match"
      costing = "prices"

   MUSE provides two methods in :py:mod:`muse.production`:
   
   - share: the production is the maximum production for the existing capacity and
      the technology's utilization factor.
      See :py:func:`muse.production.maximum_production`.
   - match: production and demand are matched according to a given cost metric. The
      cost metric defaults to "prices". It can be modified by using the general form
      given above, with a "costing" attribute. The latter can be "prices",
      "gross_margin", or "lcoe".
      See :py:func:`muse.production.demand_matched_production`.

   *production* can also refer to any custom production method registered with MUSE via
   :py:func:`muse.production.register_production`.

   Defaults to "share".

dispatch_production
   The name of the production method used to compute the sector's output, as returned
   to the muse market clearing algorithm. In other words, this is computation of the
   production method which will affect other sectors.

   It has the same format and options as the *production* attribute above.

demand_share
   A method used to split the MCA demand into seperate parts to be serviced by specific
   agents. There is currently two options:
   
   - "standard_demand", where all the demand is split among the "new" agents, raising
     and error if retro agents are found for the sector.
   - "new_and_retro", corresponding to splitting the demand among *new* and *retro* 
      agents, in adition to splitting it between agents of the same type.


interactions
   Defines interactions between agents. These interactions take place right before new
   investments are computed. The interactions can be anything. They are expected to
   modify the agents and their assets. MUSE provides a default set of interactions that
   have *new* agents pass on their assets to the corresponding *retro* agent, and the
   *retro* agents pass on the make-up of their assets to the corresponding *new*
   agents.

   *interactions* are specified as a :ref:`TOML array<toml-array>`, e.g. with double
   brackets. Each sector can specify an arbitrary number of interactaction, simply by
   adding an extra interaction row.    

   There are two orthogonal concepts to interactions:

   - a *net* defines the set of agents that interact. A set can contain any
     number of agents, whether zero, two, or all agents in a sector. See
     :py:func:`muse.interactions.register_interaction_net`.
   - an *interaction* defines how the net actually interacts.  See
     :py:func:`muse.interactions.register_agent_interaction`.

   In practice, we always consider sequences of nets (i.e. more than one net) that
   interact using the same interaction function.

   Hence, the input looks something like the following:

   .. code-block:: TOML

      [[sectors.commercial.interactions]]
      net = 'new_to_retro'
      interaction = 'transfer'

   "new_to_retro" is a function that figures out all "new/retro" pairs of agents.
   Whereas "transfer" is a function that performs the transfer of assets and
   information between each pair.

   Furthermore, it is possible to pass parameters to either the net of the interaction
   as follows:

   .. code-block:: TOML

      [[sectors.commercial.interactions]]
      net = {"name": "some_net", "param": "some value"}
      interaction = {"name": "some_interaction", "param": "some other value"}

   The parameters will depend on the net and interaction functions. Neither
   "new_to_retro" nor "transfer" take any arguments at this point. MUSE interaction
   facilities are defined in :py:mod:`muse.interactions`.

   An error is raised if and empty network is found. This is the case, for example, if a
   "new_to_retro" type of network has been defined but no retro agents are included in
   the sector.


output
   Outputs are made up of several components. MUSE is designed to allow users to
   mix-and-match both how and what to save.

   *output* is specified as a TOML array, e.g. with double brackets. Each sector can
   specify an arbitrary number of outputs, simply by adding an extra output row.

   A single row looks like this:

   .. code-block:: TOML

      [[sectors.commercial.outputs]]
      filename = '{cwd}/Results/{Sector}/{Quantity}/{year}{suffix}'
      quantity = "capacity"
      sink = 'csv'
      overwrite = true

   The following attributes are available:

   - quantity: Name of the quantity to save. Currently, only `capacity` exists,
      refering to :py:func:`muse.outputs.capacity`. However, users can
      customize and create further output quantities by registering with MUSE via
      :py:func:`muse.outputs.register_output_quantity`. See
      :py:mod:`muse.outputs` for more details.

   - sink: the sink is the place (disk, cloud, database, etc...) and format with which
      the computed quantity is saved. Currently only sinks that save to files are
      implemented. The filename can specified via `filename`, as given below. The
      following sinks are available: "csv", "netcfd", "excel". However, more sinks can
      be added by interested users, and registered with MUSE via
      :py:func:`muse.outputs.register_output_sink`. See
      :py:mod:`muse.outputs` for more details.
   
   - filename: defines the format of the file where to save the data. There are several
      standard values that are automatically substituted:

      - cwd: current working directory, where MUSE was started
      - path: directory where the TOML file resides
      - sector: name of the current sector (.e.g. "commercial" above)
      - Sector: capitalized name of the current sector
      - quantity: name of the quantity to save (as given by the quantity attribute)
      - Quantity: capitablized name of the quantity to save
      - year: current year
      - suffix: standard suffix/file extension of the sink

      Defaults to `{cwd}/{default_output_dir}/{Sector}/{Quantity}/{year}{suffix}`.

   - overwrite: If `False` MUSE will issue an error and abort, instead of
      overwriting an existing file. Defaults to `False`. This prevents important output files from being overwritten.

technodata
   Path to a csv file containing the characterization of the technologies involved in
   the sector, e.g. lifetime, capital costs, etc... See :ref:`inputs-technodata`.

timeslice_levels
   Slices to consider in a level. If absent, defaults to the finest timeslices.  See
   `Timeslices`_

commodities_in
   Path to a csv file describing the inputs of each technology involved in the sector.
   See :ref:`inputs-iocomms`.

commodities_out
   Path to a csv file describing the outputs of each technology involved in the sector.
   See :ref:`inputs-iocomms`.

existing_capacity
   Path to a csv file describing the initial capacity of the sector.
   See :ref:`inputs-existing-capacity`.

agents
    Path to a csv file describing the agents in the sector.
    See :ref:`inputs-agents`.

lpsolver
   This is the optimisation solver used to make investment decisions. The two options
   available for this are "adhoc" (which sums costs on the timeslices, whilst its variant "adhoc_timeslices" chooses the asset at the minimum timeslice cost and iterates) or "scipy" solvers. The "scipy" solver should be used
   when introducing minimum constraints and using the trade functionality.


--------------
Preset sectors
--------------

The commodity production, commodity consumption and product prices of preset sectors are determined
exogeneously. They are know from the start of the simulation and are not affected by the
simulation. 

Preset sectors are defined in :py:class:`~muse.sectors.PresetSector`.

The three components, production, consumption, and prices, can be set independantly and
not all three need to be set. Production and consumption default to zero, and prices
default to leaving things unchanged.

The following defines a standard preset sector where consumption is defined as a
function of macro-economic data, i.e. population and gdp.


.. code-block:: TOML

    [sectors.commercial_presets]
    type = 'presets'
    priority = 'presets'
    timeslice_shares_path = '{path}/technodata/TimesliceShareCommercial.csv'
    macrodrivers_path = '{path}/technodata/Macrodrivers.csv'
    regression_path = '{path}/technodata/regressionparameters.csv'
    timeslices_levels = {'day': ['all-day']}
    forecast = [0, 5]

The following attributes are accepted:

type:
   See the attribute in the standard mode, :ref:`type<sector-type>`. *Preset* sectors
   are those with type "presets".

priority
   See the attribute in the standard mode, :ref:`priority<sector-priority>`.

timeslices_levels:
   See the attribute in the standard mode, `Timeslices`_.

.. _preset-consumption:

consumption_path:
   CSV output files, one per year. This attribute can include wild cards, i.e. '*',
   which can match anything. For instance: `consumption_path = "{cwd}/Consumtion*.csv"` will match any csv file starting with "Consumption" in the
   current working directory. The file names must include the year for which it defines
   the consumption, e.g. `Consumption2015.csv`.

   The CSV format should follow the following format:

   .. csv-table:: Consumption
      :header: " ", "RegionName", "ProcessName", "TimeSlice", "electricity", "diesel", "algae"
      :stub-columns: 4

      0,USA,fluorescent light,1,1.9, 0, 0
      1,USA,fluorescent light,2,1.8, 0, 0


   The index column as well as "RegionName", "ProcessName", and "TimeSlice" must be
   present. Further columns are reserved for commodities. "TimeSlice" refers to the
   index of the timeslice.


supply_path:
   CSV file, one per year, indicating the amount of a commodities produced. It follows
   the same format as :ref:`consumption_path <preset-consumption>`.

supply_path:
   CSV file, one per year, indicating the amount of a commodities produced. It follows
   the same format as :ref:`consumption_path <preset-consumption>`.

prices_path:
   CSV file indicating the amount of a commodities produced. The format of the CSV files
   follows that of :ref:`inputs-projection`.

.. _preset-demand:

demand_path:
   Incompatible with :ref:`consumption_path<preset-consumption>` or
   :ref:`macrodrivers_path<preset-macro>`. A CSV file containing the consumption in the
   same format as :ref:`inputs-projection`.

.. _preset-macro:

macrodrivers_path:
   Incompatible with :ref:`consumption_path<preset-consumption>` or
   :ref:`demand_path<preset-demand>`. Path to a CSV file giving the profile of the
   macrodrivers. Also requires :ref:`regression_path<preset-regression>`.

.. _preset-regression:

regression_path:
   Incompatible with :ref:`consumption_path<preset-consumption>` or
   :ref:`demand_path<preset-demand>`. Path to a CSV file giving the regression
   parameters with respect to the macrodrivers.
   Also requires :ref:`macrodrivers_path<preset-macro>`.

timeslice_shares_path
   Optional csv file giving shares per timeslice. Requires
   :ref:`macrodrivers_path<preset-consumption>`.

filters:
   Optional dictionary of entries by which to filter the consumption.  Requires
   :ref:`macrodrivers_path<preset-consumption>`. For instance,

   .. code-block::

      filters.region = ["USA", "ASEA"]
      filters.commodity = ["algae", "fluorescent light"]


--------------
Legacy Sectors
--------------

Legacy sectors wrap sectors developed for a previous version of MUSE to the open-source
version. 

Preset sectors are defined in :py:class:`~muse.sectors.PresetSector`.

The can be defined in the TOML file as follows:

.. code-block:: TOML

   [global_input_files]
   macrodrivers = '{path}/input/Macrodrivers.csv'
   regions = '{path}/input/Regions.csv'
   global_commodities = '{path}/input/MUSEGlobalCommodities.csv'

   [sectors.Industry]
   type = 'legacy'
   priority = 'demand'
   agregation_level = 'month'
   excess = 0

   userdata_path = '{muse_sectors}/Industry'
   technodata_path = '{muse_sectors}/Industry'
   timeslices_path = '{muse_sectors}/Industry/TimeslicesIndustry.csv'
   output_path = '{path}/output'

For historical reasons, the three `global_input_files` above are required. The sector
itself can use the following attributes.

type:
   See the attribute in the standard mode, :ref:`type<sector-type>`. *Legacy* sectors
   are those with type "legacy".

priority
   See the attribute in the standard mode, :ref:`priority<sector-priority>`.

agregation_level:
   Information relevant to the sector's timeslice.

excess:
   Excess factor used to model early obsolescence.

userdata_path:
   Path to a directory with sector-specific data files.

technodata_path:
   Path to a technodata CSV file. See. :ref:`inputs-technodata`.

output_path:
   Path to a diretory where the sector will write output files.