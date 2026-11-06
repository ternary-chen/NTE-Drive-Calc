# 验证候选按最终采用状态保留且属性支配优先，并冻结公共评分器的实际权重。
from types import SimpleNamespace

from src.domain.equipment.warehouse_review import adopted_candidates
from src.services.inventory.warehouse_recommendation_display import freeze_recommendation_stat_weights
from src.features.inventory.warehouse.recommendation_cards import recommendation_item_view


def row(uid, **extra):
    return dict(uid=uid,kind='drive',shape_id='H_3',quality='Gold',decision='keep',
                stats={'攻击力%':1,'暴击伤害%':20},current_scores={'角色':30},original_discarded=False,
                **extra)


def test_only_candidates_retained_after_adoption_and_no_worse_first():
    original=row('current',replacement_uids=['trade','dominant','restore','unknown'])
    trade={**row('trade'),'stats':{'攻击力%':10},'current_scores':{'角色':100}}
    dominant={**row('dominant'),'stats':{'攻击力%':2,'暴击伤害%':20}}
    restore={**row('restore'),'original_discarded':True,'current_scores':{'角色':50}}
    unknown={**row('unknown'),'state_known':False}
    lookup={r['uid']:r for r in (original,trade,dominant,restore,unknown)}
    assert [r['uid'] for r in adopted_candidates(original,lookup,{})]==['dominant','trade']
    assert [r['uid'] for r in adopted_candidates(original,lookup,{'restore':'normal'})]==['restore','dominant','trade']
    assert [r['uid'] for r in adopted_candidates(original,lookup,{'dominant':'discarded'})]==['trade']


def test_frozen_weights_use_public_resolver_and_formal_property_ids():
    prepared=[]
    scorer=SimpleNamespace(roles_db={'角色':{'weights':{'暴击率%':.9},'main_weights':{'暴击率%':.5}}},
        prepare_weight_queries=lambda weights,names:prepared.append((weights,names)),
        flexible_weight=lambda name,weights:weights.get(name,0))
    result=freeze_recommendation_stat_weights(scorer,[{'main_stats':[{'property_id':'CritBase'}],
                                                     'sub_stats':[{'property_id':'CritBase'}]}])
    assert prepared and result['角色']=={'sub':{'CritBase':.9},'main':{'CritBase':.5}}
    raw={'kind':'core','quality':'orange','level':20,'main_stats':[{'property_id':'CritBase','value':.3,'percent':True}],
         'sub_stats':[{'property_id':'CritBase','value':.1,'percent':True}]}
    value={'kind':'tape','set_name':'套装','display_item':raw,'current_scores':{'角色':30}}
    view=recommendation_item_view(value,result['角色'])
    assert view['main_stats'][0]['weight']==.5 and view['sub_stats'][0]['weight']==.9
    assert 'weight' not in raw['sub_stats'][0]
