"""`apps.opps.tenancy.TenancyAccess` — will a released reviewer open this link?

`admin only` on the run summary means "a reviewer of this run never gets
access" (Jonathan, 2026-10-03). These pin the per-link rule against the
real Spark tenancy and the shared tenants `dimagi-team`'s opps live in.
"""
from apps.opps.tenancy import TenancyAccess

SPARK = {
    "hq_domain": "connect-ace-spark",
    "connect_pm_org": "spark-pm-org-test",
    "connect_holding_org": "spark-nm-org-test",
}
SHARED = {
    "hq_domain": "connect-ace-prod",
    "connect_holding_org": "ace-nm-org",
    "ocs_team": "connect-ace",
}
HQ = "https://www.commcarehq.org/a/{}/apps/view/8c073531bbb94350a7f0e8b894709ec0/"
CONNECT = "https://connect.dimagi.com/a/{}/opportunity/ad6c2d40/"


def test_spark_links_inside_its_own_tenancy_are_reviewer_openable():
    t = TenancyAccess(SPARK)
    assert t.has_own_tenancy
    assert t.hq_app(HQ.format("connect-ace-spark"))
    assert t.connect(CONNECT.format("spark-nm-org-test"))
    assert t.connect(CONNECT.format("spark-pm-org-test"))
    assert t.workbench()


def test_a_link_outside_the_opps_tenancy_stays_internal():
    t = TenancyAccess(SPARK)
    assert not t.hq_app(HQ.format("connect-ace-prod"))
    assert not t.connect(CONNECT.format("ace-nm-org"))


def test_the_ocs_console_is_always_internal():
    assert not TenancyAccess(SPARK).ocs_console()
    assert not TenancyAccess({**SPARK, "ocs_team": "spark-ocs"}).ocs_console()


def test_shared_tenancy_keeps_everything_internal():
    t = TenancyAccess(SHARED)
    assert not t.has_own_tenancy
    assert not t.hq_app(HQ.format("connect-ace-prod"))
    assert not t.connect(CONNECT.format("ace-nm-org"))
    assert not t.workbench()


def test_unknown_tenancy_is_internal_not_guessed():
    for t in (TenancyAccess(None), TenancyAccess({})):
        assert not t.has_own_tenancy
        assert not t.hq_app(HQ.format("anything"))
        assert not t.connect(CONNECT.format("anything"))
        assert not t.workbench()
