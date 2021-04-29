from pytest import mark


def modify_minimum_service_factors(
    model_path, sector, process_name, minimum_service_factor
):
    import pandas as pd

    technodata_timeslices = pd.read_csv(
        model_path / "technodata" / sector / "TechnodataTimeslices.csv"
    )

    technodata_timeslices.loc[
        technodata_timeslices["ProcessName"] == process_name[0], "MinimumServiceFactor"
    ] = minimum_service_factor[0]

    technodata_timeslices.loc[
        technodata_timeslices["ProcessName"] == process_name[1], "MinimumServiceFactor"
    ] = minimum_service_factor[1]

    return technodata_timeslices


@mark.parametrize("process_name", [("gasCCGT", "windturbine")])
@mark.parametrize(
    "minimum_service_factor", [([1, 2, 3, 4, 5, 6], [0] * 6), ([0], [1, 2, 3, 4, 5, 6])]
)
def test_minimum_service_factor(tmpdir, minimum_service_factor, process_name):
    from muse import examples
    from muse.mca import MCA
    import pandas as pd
    import glob

    sector = "power"

    # Copy the model inputs to tmpdir
    model_path = examples.copy_model(
        name="default_timeslice", path=tmpdir, overwrite=True
    )

    technodata_timeslices = modify_minimum_service_factors(
        model_path=model_path,
        sector=sector,
        process_name=process_name,
        minimum_service_factor=minimum_service_factor,
    )

    technodata_timeslices.to_csv(
        model_path / "technodata" / sector / "TechnodataTimeslices.csv"
    )

    with tmpdir.as_cwd():
        MCA.factory(model_path / "settings.toml").run()

    path = str(tmpdir / "Results" / "Power" / "Supply_Timeslice")
    all_files = glob.glob(path + "/*.csv")

    results = []
    for filename in all_files:
        result = pd.read_csv(filename, index_col=None, header=0)
        results.append(result)

    supply_timeslice = pd.concat(results)
    supply_timeslice

    for process, service_factor in zip(process_name, minimum_service_factor):
        for i, factor in enumerate(service_factor):
            assert (
                supply_timeslice[
                    (supply_timeslice.technology == process)
                    & (supply_timeslice.commodity == "electricity")
                    & (supply_timeslice.timeslice == i)
                ].supply
                >= factor
            ).all()
