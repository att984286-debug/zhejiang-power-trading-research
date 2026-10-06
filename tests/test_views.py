from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
import public_ui.package as package_io
from public_ui.schema import PublicDataError

APP=Path(__file__).resolve().parents[1]/'app.py'


@pytest.mark.parametrize('case,view',[
    ('案例 A · 独立储能','电池有什么限制'),('案例 A · 独立储能','原来怎么安排'),
    ('案例 A · 独立储能','后来怎么调整'),('案例 A · 独立储能','钱和风险在哪'),
    ('案例 B · 新能源发电企业','有哪些条件'),('案例 B · 新能源发电企业','签多少报多少'),
    ('案例 B · 新能源发电企业','钱怎么算'),('案例 B · 新能源发电企业','结果为什么变了'),
])
def test_all_eight_views(case,view):
    app=AppTest.from_file(str(APP),default_timeout=30).run()
    assert not app.exception and not app.error
    app.radio(key='sandbox_nav').set_value(case).run()
    key='a_view_s4' if case.startswith('案例 A') else 'b_view_s4'
    app.radio(key=key).set_value(view).run()
    assert not app.exception and not app.error


def test_case_reset_and_two_sessions():
    a=AppTest.from_file(str(APP),default_timeout=30).run()
    b=AppTest.from_file(str(APP),default_timeout=30).run()
    a.radio(key='sandbox_nav').set_value('案例 A · 独立储能').run()
    a.selectbox(key='a_strategy').set_value('E_oracle_reference').run()
    assert a.warning and b.radio(key='sandbox_nav').value=='项目总览'
    a.radio(key='sandbox_nav').set_value('案例 B · 新能源发电企业').run()
    assert a.selectbox(key='b_strategy').value=='risk_averse'
    a.selectbox(key='b_group').set_value('private_2026-09').run()
    a.radio(key='b_view_s4').set_value('结果为什么变了').run()
    assert not a.exception and not a.error
    a.radio(key='sandbox_nav').set_value('案例 A · 独立储能').run()
    assert a.selectbox(key='a_strategy').value=='D_rolling_rt'


def test_private_and_unknown_labels():
    app=AppTest.from_file(str(APP),default_timeout=30).run()
    app.radio(key='sandbox_nav').set_value('案例 B · 新能源发电企业').run()
    for group in ['private_2026-09','private_2026-10']:
        app.selectbox(key='b_group').set_value(group).run()
        app.radio(key='b_view_s4').set_value('钱怎么算').run()
        assert any('非同期' in v.value for v in app.warning)
        assert any('完整利润' in v.value for v in app.warning)
        assert not app.exception and not app.error


def test_error_view_does_not_echo_payload(monkeypatch):
    def reject():
        raise PublicDataError('/Users/'+'probe'+'/secret must not be rendered')
    monkeypatch.setattr(package_io,'get_package',reject)
    from sandbox_ui import replay
    monkeypatch.setattr(replay,'get_package',reject)
    app=AppTest.from_file(str(APP),default_timeout=30).run()
    app.radio(key='sandbox_nav').set_value('案例 A · 独立储能').run()
    assert not app.exception
    assert len(app.error)==1
    assert '校验未通过' in app.error[0].value
    assert 'probe' not in app.error[0].value
