"""Sign convention and label parsing for Terna's inter-zonal flows (no network)."""
import pandas as pd

from etl import internal_flows as ifl


def _terna_frame():
    """Mimics the API shape: long format, one row per (timestamp, link)."""
    idx = pd.date_range("2026-07-13", periods=2, freq="h", tz="Europe/Rome")
    rows = []
    for t in idx:
        rows += [
            # label direction Sicily->Calabria, value negative => power moved Calabria->Sicily
            {"flow": "Sicily -> Calabria", "physical_internal_flow_MW": -313.1},
            # label direction matches our canonical (CSUD, SUD)? no: ours is CSUD->SUD
            {"flow": "Centre-South -> Centre-North", "physical_internal_flow_MW": -328.9},
            {"flow": "North -> Centre-North", "physical_internal_flow_MW": 1200.0},
        ]
    return pd.DataFrame(rows, index=idx.repeat(3))


def test_label_parsing_maps_terna_names():
    assert ifl._parse_link("Centre-South -> Centre-North") == ("CSUD", "CNOR")
    assert ifl._parse_link("Sicily -> Calabria") == ("SICI", "CALA")
    assert ifl._parse_link("Atlantis -> Sicily") is None      # unknown label is skipped


def test_sign_is_flipped_to_the_canonical_direction(monkeypatch):
    """Terna labels a link in its own order; we normalise so + always means from -> to."""
    monkeypatch.setattr(ifl, "_client", lambda: type("C", (), {
        "get_physical_internal_flow": staticmethod(lambda start, end: _terna_frame())})())
    df = ifl.fetch_internal_flows(pd.Timestamp("2026-07-13", tz="Europe/Rome"),
                                  pd.Timestamp("2026-07-14", tz="Europe/Rome"))
    # canonical link is CALA-SICI; Terna said "Sicily -> Calabria = -313" i.e. 313 MW CALA->SICI
    assert "CALA-SICI" in df.columns
    assert abs(df["CALA-SICI"].iloc[0] - 313.1) < 1e-6      # sign flipped, now positive CALA->SICI
    # canonical CNOR-CSUD; Terna said "Centre-South -> Centre-North = -328.9" i.e. 328.9 CNOR->CSUD
    assert abs(df["CNOR-CSUD"].iloc[0] - 328.9) < 1e-6
    # a link already in canonical order keeps its sign
    assert abs(df["NORD-CNOR"].iloc[0] - 1200.0) < 1e-6


def test_hourly_profile_has_24_slots(monkeypatch):
    idx = pd.date_range("2026-07-13", periods=48, freq="30min", tz="Europe/Rome")
    flows = pd.DataFrame({"CALA-SICI": 300.0}, index=idx)
    prof = ifl.hourly_profiles(flows, pd.Timestamp("2026-07-13").date())
    assert len(prof["CALA-SICI"]) == 24
    assert prof["CALA-SICI"][0] == 300.0


def test_links_cover_the_italian_topology():
    zones = {z for link in ifl.LINKS for z in link}
    assert zones == {"NORD", "CNOR", "CSUD", "SUD", "CALA", "SICI", "SARD"}
    assert len(ifl.LINKS) == 7          # 7 flows is exactly what the API returns
