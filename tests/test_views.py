from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
import public_ui.package as package_io
from public_ui.schema import PublicDataError

APP=Path(__file__).resolve().parents[1]/'app.py'


@pytest.mark.parametrize('case,view',[
    ('Case A 独立储能','资产与口径'),('Case A 独立储能','日前计划'),
    ('Case A 独立储能','滚动更新'),('Case A 独立储能','账本与复盘'),
    ('Case B 新能源发电企业','场景与口径'),('Case B 新能源发电企业','头寸与申报'),
    ('Case B 新能源发电企业','账本与风险'),('Case B 新能源发电企业','交易复盘'),
])
def test_all_eight_views(case,view):
    app=AppTest.from_file(str(APP),default_timeout=30).run()
    assert not app.exception and not app.error
    app.radio(key='case_nav').set_value(case).run()
    key='a_view' if case.startswith('Case A') else 'b_view'
    app.radio(key=key).set_value(view).run()
    assert not app.exception and not app.error


def test_case_reset_and_two_sessions():
    a=AppTest.from_file(str(APP),default_timeout=30).run()
    b=AppTest.from_file(str(APP),default_timeout=30).run()
    a.radio(key='case_nav').set_value('Case A 独立储能').run()
    a.selectbox(key='a_strategy').set_value('E_oracle_reference').run()
    assert a.warning and b.radio(key='case_nav').value=='项目总览'
    a.radio(key='case_nav').set_value('Case B 新能源发电企业').run()
    assert a.selectbox(key='b_strategy').value=='risk_averse'
    a.selectbox(key='b_group').set_value('private_2026-09').run()
    a.radio(key='b_view').set_value('交易复盘').run()
    assert not a.exception and not a.error
    a.radio(key='case_nav').set_value('Case A 独立储能').run()
    assert a.selectbox(key='a_strategy').value=='D_rolling_rt'


def test_private_and_unknown_labels():
    app=AppTest.from_file(str(APP),default_timeout=30).run()
    app.radio(key='case_nav').set_value('Case B 新能源发电企业').run()
    for group in ['private_2026-09','private_2026-10']:
        app.selectbox(key='b_group').set_value(group).run()
        app.radio(key='b_view').set_value('账本与风险').run()
        assert any('非同期' in v.value for v in app.warning)
        assert any('完整利润' in v.value for v in app.warning)
        assert not app.exception and not app.error


def test_error_view_does_not_echo_payload(monkeypatch):
    def reject():
        raise PublicDataError('/Users/'+'probe'+'/secret must not be rendered')
    monkeypatch.setattr(package_io,'get_package',reject)
    app=AppTest.from_file(str(APP),default_timeout=30).run()
    assert not app.exception
    assert len(app.error)==1
    assert '校验未通过' in app.error[0].value
    assert 'probe' not in app.error[0].value
