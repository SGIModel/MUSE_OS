from pytest import mark


@mark.usefixtures("save_timeslice_globals")
@mark.regression
def test_fullsim_regression(fullsim_dir, tmpdir, compare_dirs):
    from warnings import simplefilter
    from pathlib import Path
    from pandas.errors import DtypeWarning
    from muse.mca import MCA
    from muse.examples import copy_model

    # fail the test if this warning crops up
    simplefilter("error", DtypeWarning)

    # Copy the data to tmpdir
    copy_model(path=tmpdir)

    # main() will output to cwd
    with tmpdir.as_cwd():
        MCA.factory(Path(tmpdir) / "model" / "settings.toml").run()

    compare_dirs(tmpdir / "Results", fullsim_dir / "output")