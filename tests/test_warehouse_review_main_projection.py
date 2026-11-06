# 验证建议卡片满级主属性沿用公共投影，保留真实等级和副属性，缺曲线不宣称满级。
from copy import deepcopy
from types import SimpleNamespace

from src.services.equipment.equipment_level_projection_service import project_equipment_items_to_max_level
from src.features.inventory.warehouse.recommendation_cards import recommendation_item_view


def test_max_main_projection_preserves_source_and_display_percent():
    raw = dict(kind='core',item_id='core',quality='orange',grid_count=15,level=0,max_level=20,
               main_stats=[dict(property_id='CritBase',value=.06,percent=True)],
               sub_stats=[dict(property_id='CritDamageBase',value=.2,percent=True)])
    frozen = deepcopy(raw)
    calls = []
    def curve(identity, level):
        calls.append((identity,level))
        return .30
    dao = SimpleNamespace(list_equipment_items=lambda:[{'item_id':'core','max_level':20}],
                          evaluate_equipment_base_attribute_curve=curve)
    projected = project_equipment_items_to_max_level([raw], dao, include_projection_evidence=True)[0]
    assert calls == [('CritBase_Core_ITEM_QUALITY_ORANGE',20)]
    assert raw == frozen and projected['sub_stats'] == raw['sub_stats']
    assert projected['main_stats_at_max_level']
    display = {**raw, 'main_stats':projected['main_stats'], 'main_stats_at_max_level':True}
    view = recommendation_item_view(dict(kind='tape', set_name='套装', display_item=display, current_scores={}))
    assert view['level'] == 0 and view['main_stats'][0]['value'] == '+30%'
    assert view['main_stats_at_max_level']


def test_missing_curve_or_max_level_cannot_be_labeled_full_level():
    raw = dict(kind='module',item_id='drive',quality='purple',grid_count=3,level=1,max_level=16,
               main_stats=[dict(property_id='AtkAdd',value=12)])
    dao = SimpleNamespace(list_equipment_items=lambda:[],evaluate_equipment_base_attribute_curve=lambda *_:None)
    result = project_equipment_items_to_max_level([raw],dao,include_projection_evidence=True)[0]
    assert not result['main_stats_at_max_level'] and result['main_stats']==raw['main_stats']
    dao.evaluate_equipment_base_attribute_curve = lambda *_: 80
    result = project_equipment_items_to_max_level([{**raw,'max_level':0}],dao,include_projection_evidence=True)[0]
    assert not result['main_stats_at_max_level']
