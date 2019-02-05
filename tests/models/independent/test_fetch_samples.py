""" Tests for fetching Samples of certain attributes values from a Project """

from collections import defaultdict
import itertools
import os

import mock
import pytest
import yaml

from peppy import Project, Sample
from peppy.utils import fetch_samples


__author__ = "Vince Reuter"
__email__ = "vreuter@virginia.edu"



PROTOCOL_BY_SAMPLE = {
    sample_name: protocol for sample_name, protocol in [
        ("atac_A", "ATAC-Seq"), ("atac_B", "ATAC-Seq"),
        ("chip1", "ChIP-Seq"), ("WGBS-1", "WGBS"), ("RRBS-1", "RRBS"),
        ("rna_SE", "RNA-seq"), ("rna_PE", "RNA-seq")]
}
BASIC_PROTOCOL_NAMES = set(PROTOCOL_BY_SAMPLE.values())


def _group_samples_by_protocol():
    """ Invert mapping from protocol name to sample name.

    :return Mapping[str, list[str]]: sample names by protocol name
    """
    name_by_protocol = defaultdict(list)
    for sn, p in PROTOCOL_BY_SAMPLE.items():
        name_by_protocol[p].append(sn)
    return name_by_protocol


@pytest.fixture
def expected_sample_names(request):
    """
    Generate expected sample names for a test case's fetch_samples() call.

    Use the test case's fixture regarding protocol names to determine which
    protocols for which to grab sample names.

    :param pytest.fixtures.FixtureRequest request: test case requesting fixture
    :return set[str]: collection of sample names associated with either the
        test cases's protocol names (inclusion) or not associated with them
        (exclusion)
    """
    names_by_protocol = _group_samples_by_protocol()
    if "inclusion" in request.fixturenames:
        prot_spec = request.getfixturevalue("inclusion")
    elif "exclusion" in request.fixturenames:
        prot_spec = request.getfixturevalue("exclusion")
    else:
        raise ValueError(
            "Test case lacks either 'inclusion' and 'exclusion' fixtures, "
            "so no sample names can be generated; "
            "it should have one or the other.")
    if isinstance(prot_spec, str):
        prot_spec = [prot_spec]
    prot_spec = set(prot_spec)
    protocols = prot_spec if "inclusion" in request.fixturenames \
            else BASIC_PROTOCOL_NAMES - prot_spec
    print("Protocols generating expectations: {}".format(protocols))
    return itertools.chain.from_iterable(
            names_by_protocol[p] for p in protocols)


@pytest.fixture
def samples():
    """
    Create collection of Samples, useful for mocking a Project.

    :return Iterable[Sample]: collection of bare bones Sample objects, with
        only name and protocol defined
    """
    return [Sample({"sample_name": sn, "protocol": p})
            for sn, p in PROTOCOL_BY_SAMPLE.items()]


def _write_project_files(tmpdir, all_samples, sp_samples, sp_name):
    """
    Write key project files.

    :param py._path.local.LocalPath tmpdir: tmpdir fixture from test case
    :param Iterable[Sample] all_samples: collection of samples for the
        main Project sample annotations
    :param Iterable[Sample] sp_samples: collection of samples for the
        subproject
    :return str: Project config file
    """

    # Parse name and protocol from actual Sample objects.
    def sample_data(samples):
        return [(s.sample_name, getattr(s, "protocol", "")) for s in samples]

    def write_anns(fh, samples):
        fh.write("\n".join(map(
            lambda name_proto_pair: "{},{}".format(*name_proto_pair),
            [("sample_name", "protocol")] + sample_data(samples))))

    # Create paths.
    metadir = tmpdir.mkdir("metadata")

    # Write annotations
    full_anns = metadir.join("anns.csv")
    write_anns(full_anns, all_samples)
    sp_anns = metadir.join("sp-anns.csv")
    write_anns(sp_anns, sp_samples)

    # So that parsing pipeline interfaces is skipped, don't create pipedir.
    pipe_path = os.path.join(tmpdir.strpath, "pipelines")
    outdir = tmpdir.mkdir("output")

    conf_data = {
        "metadata": {
            "sample_annotation": full_anns.strpath, "output_dir": outdir.strpath,
            "pipeline_interfaces": pipe_path},
        "subprojects": {sp_name: {
            "metadata": {"sample_annotation": sp_anns.strpath}}}
    }

    conf = metadir.join("conf.yaml")
    with open(conf.strpath, 'w') as f:
        yaml.dump(conf_data, f)

    return conf.strpath


@pytest.mark.parametrize(
    argnames=["attribute", "exclusion"],
    argvalues=[("faulty_attr", "RNA-Seq"), ("faulty_attr", "RRBS")])
def test_has_attribute(attribute, exclusion, samples):
    """ At least one of the samples has to have the specified attribute. """
    prj = mock.MagicMock(samples=samples)
    with pytest.raises(AttributeError):
        fetch_samples(prj, attribute=attribute, exclusion=exclusion)


@pytest.mark.parametrize(
    argnames=["inclusion", "exclusion"], argvalues=itertools.product(
        ["ATAC-Seq", "ChIPmentation", {"RNA-Seq", "ChIP"}],
            ["WGBS", {"WGBS", "RRBS"}]))
def test_only_inclusion_or_exclusion(inclusion, exclusion, samples):
    """ Only an inclusion or exclusion set is permitted. """
    prj = mock.MagicMock(samples=samples)
    with pytest.raises(TypeError):
        fetch_samples(prj, inclusion=inclusion, exclusion=exclusion)


@pytest.mark.parametrize(
    argnames=["inclusion", "exclusion"], argvalues=[
            ("ATAC-Seq", None), ({"ChIPmentation", "RNA-Seq"}, None),
            (None, "ChIP-Seq"), (None, {"ATAC-Seq", "ChIPmentation"})])
def test_no_samples(inclusion, exclusion):
    """ Regardless of filtration, lack of samples means empty collection. """
    prj = mock.MagicMock(samples=[])
    observed = fetch_samples(prj, inclusion=inclusion, exclusion=exclusion)
    assert [] == observed


@pytest.mark.parametrize(
    argnames=["inclusion", "exclusion"],
    argvalues=[(None, None), (None, {}), ([], None), ([], [])])
def test_no_filter(inclusion, exclusion, samples):
    """ Without a filtration mechanism, all Samples are retained. """
    prj = mock.MagicMock(samples=samples)
    assert samples == fetch_samples(prj, inclusion=inclusion, exclusion=exclusion)


class ProtocolInclusionTests:
    """ Samples can be selected for by protocol. """

    # Note that even if the vary_protocol_name "parameter" to a test case
    # function appears to go unnoticed, it's likely present so that the
    # samples fixture can use its value to accordingly adjust the protocol
    # name for each Sample.

    @pytest.mark.parametrize(
        argnames="inclusion",
        argvalues=["totally-radical-protocol",
                   ["WackyNewProtocol", "arbitrary_protocol"]])
    def test_empty_intersection_with_inclusion(
            self, samples, inclusion):
        """ Sensitivity and specificity for positive protocol selection. """
        prj = mock.MagicMock(samples=samples)
        observed = fetch_samples(prj, inclusion=inclusion)
        assert set() == set(observed)

    @pytest.mark.parametrize(
        argnames="inclusion",
        argvalues=["ATAC-Seq", "ChIP-Seq"])
    def test_partial_intersection_with_inclusion(self,
            samples, inclusion, expected_sample_names):
        """ Empty intersection with the inclusion means no Samples. """

        # Mock the Project instance.
        prj = mock.MagicMock(samples=samples)

        # Debug aid (only visible if failed)
        print("Grouped sample names (by protocol): {}".
              format(_group_samples_by_protocol()))
        print("Inclusion specification: {}".format(inclusion))

        # Perform the call under test and make the associated assertions.
        observed = fetch_samples(prj, inclusion=inclusion)
        _assert_samples(expected_sample_names, observed)

    def test_complete_intersection_with_inclusion(
            self, samples):
        """ Project with Sample set a subset of inclusion has all fetched. """
        prj = mock.MagicMock(samples=samples)
        expected = {s.name for s in samples}
        inclusion_protocols = list(BASIC_PROTOCOL_NAMES)
        print("Inclusion protocols: {}".format(inclusion_protocols))
        observed = fetch_samples(prj, inclusion=inclusion_protocols)
        _assert_samples(expected, observed)

    @pytest.mark.parametrize(
        argnames=["inclusion", "expected_names"],
        argvalues=[("ATAC-Seq", {}),
                   (("ChIP-Seq", "ATAC-Seq", "RNA-seq"),
                    {"chip1", "rna_SE", "rna_PE"})])
    def test_samples_without_protocol_are_not_included(
            self, samples, inclusion, expected_names):
        """ Inclusion does not grab Sample lacking protocol. """

        # Note that the expectations fixture isn't used here since this does
        # not fit the generic framework in which that one applies.

        prj = mock.MagicMock(samples=samples)

        # Remove protocol for ATAC-Seq samples.
        for s in samples:
            if s.protocol == "ATAC-Seq":
                delattr(s, "protocol")

        observed = fetch_samples(prj, inclusion=inclusion)
        _assert_samples(expected_names, observed)
        
    @pytest.mark.parametrize(
        argnames="inclusion", argvalues=["ATAC-Seq", {"WGBS", "RRBS"}],
        ids=lambda protos: str(protos))
    def test_equivalence_with_subproject(self, tmpdir, samples, inclusion):
        """ Selection for protocol(s) is like specific subproject. """
        sp_name = "atac"
        confpath = _write_project_files(
            tmpdir, all_samples=samples, sp_name=sp_name,
            sp_samples=list(filter(lambda s: s.protocol in inclusion, samples)))
        try:
            full_project = Project(confpath)
        except Exception:
            anns_file = os.path.join(tmpdir.strpath, "metadata", "anns.csv")
            print("Annotations file lines:")
            with open(anns_file, 'r') as f:
                print(f.readlines())
            raise
        subproject = Project(confpath, subproject=sp_name)
        expected = {s.name for s in subproject.samples}
        observed = fetch_samples(full_project, inclusion=inclusion)
        _assert_samples(expected, observed_samples=observed)


class ProtocolExclusionTests:
    """ Samples can be selected against by protocol. """

    # Note that even if the vary_protocol_name "parameter" to a test case
    # function appears to go unnoticed, it's likely present so that the
    # samples fixture can use its value to accordingly adjust the protocol
    # name for each Sample.

    @pytest.mark.parametrize(
        argnames="exclusion", 
        argvalues=["mystery_protocol", ["wacky-protocol", "BrandNewProtocol"]])
    def test_empty_intersection_with_exclusion(
            self, samples, exclusion):
        """ Empty intersection with exclusion means all Samples remain. """
        prj = mock.MagicMock(samples=samples)
        expected = {s.name for s in samples}
        observed = fetch_samples(prj, exclusion=exclusion)
        _assert_samples(expected, observed)

    @pytest.mark.parametrize(
        argnames="exclusion", argvalues=["ChIP-Seq", ("RNA-seq", "RRBS")])
    def test_partial_intersection_with_exclusion(
            self, samples, exclusion, expected_sample_names):
        """ Sensitivity and specificity for negative protocol selection. """

        # Mock out the Project instance.
        prj = mock.MagicMock(samples=samples)

        # Make the call and the relevant assertions.
        observed = fetch_samples(prj, exclusion=exclusion)
        print(expected_sample_names)
        print(observed)
        _assert_samples(expected_sample_names, observed)

    def test_complete_intersection_with_exclusion(
            self, samples):
        """ Comprehensive exclusion can leave no Samples. """
        prj = mock.MagicMock(samples=samples)
        observed = fetch_samples(
            prj, exclusion=list(BASIC_PROTOCOL_NAMES))
        _assert_samples([], observed)

    @pytest.mark.parametrize(
        argnames="spare_via_anonymity",
        argvalues=["ChIP-Seq", "ATAC-Seq", ["RNA-seq", "WGBS", "RRBS"]],
        ids=lambda spared: str(spared))
    def test_samples_without_protocol_are_not_excluded(
            self, samples, spare_via_anonymity):
        """ Negative selection on protocol leaves Samples without protocol. """
        # Strategy: specify all of the protocols as exclusions, then allow
        # the parameterization to specify which are to be "spared" exclusion
        # by removing the protocol attribute

        print("Spare input: {}".format(spare_via_anonymity))

        # Account for varied argument types, and contextualize the protocol
        # names with the test case parameterization. That is, vary them as they
        # were in the creation of the value supplied via the samples fixture.
        if isinstance(spare_via_anonymity, str):
            spare_via_anonymity = [spare_via_anonymity]
        spare_via_anonymity = list(spare_via_anonymity)

        print("Modified spare: {}".format(spare_via_anonymity))

        # Remove the protocols designated for sparing (from exclusion).
        for s in samples:
            if s.protocol in spare_via_anonymity:
                delattr(s, "protocol")

        print("Protocols on samples: {}".format(
            {s.protocol for s in samples if hasattr(s, "protocol")}))
        print("Protocols to spare: {}".format(spare_via_anonymity))
        print("Non-protocol Samples: {}".format(
            {s.name for s in samples if not hasattr(s, "protocol")}))

        # Mock out the project with the updated Sample objects.
        prj = mock.MagicMock(samples=samples)

        # Expected names are associated with protocols spared exclusion.
        sample_names_by_protocol = _group_samples_by_protocol()
        expected_names = set(itertools.chain.from_iterable(
            sample_names_by_protocol[p] for p in spare_via_anonymity))

        # Make the call and relevant assertions.
        observed = fetch_samples(
            prj, exclusion=list(BASIC_PROTOCOL_NAMES))
        _assert_samples(expected_names, observed)


def _assert_samples(expected_names, observed_samples):
    """
    Assert that each observation is a sample and that the set of expected
    Sample names agrees with the set of observed names.

    :param Iterable[str] expected_names:
    :param Iterable[Sample] observed_samples: collection of Sample objects,
        e.g. obtained with fetch_samples(), to which assertions apply
    """
    expected_names = set(expected_names)
    assert all([isinstance(s, Sample) for s in observed_samples])
    observed_names = {s.name for s in observed_samples}
    assert expected_names == observed_names
