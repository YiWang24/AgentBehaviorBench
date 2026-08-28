"""Deterministic stubs copied verbatim from upstream `api/routers.py`.

`routers.py` imports FastAPI at module scope, so it cannot be imported here.
The three pieces the draft-graph factory needs are copied byte-for-byte:
they are upstream's own fallback for running the graph without a model, used
here only when the interceptor supplies no key.
"""

from __future__ import annotations

from typing import Any, cast


def _make_stub_llm_callable(payload: Any):
    """MVP stub callable to keep workflow executable before real model integration."""

    def _call(_: str, __: dict[str, Any]) -> Any:
        return payload

    return _call
_DRAFT_STUBS = {'extract_tech': {'source_quotes': ['占位说明文本用于测试流程稳定运行并满足字段最小长度要求。', '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。', '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'],
                  'background_and_core_problems': ['占位说明文本用于测试流程稳定运行并满足字段最小长度要求。', '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。', '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'],
                  'core_solution_overview': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                  'detailed_features': [{'feature_name': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                         'detailed_structure_or_step': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                         'solved_sub_problem': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                         'specific_effect': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'},
                                        {'feature_name': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                         'detailed_structure_or_step': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                         'solved_sub_problem': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                         'specific_effect': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'},
                                        {'feature_name': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                         'detailed_structure_or_step': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                         'solved_sub_problem': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                         'specific_effect': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'}],
                  'overall_advantages': ['占位说明文本用于测试流程稳定运行并满足字段最小长度要求。', '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。', '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。']},
 'draft_claims': {'claims': [{'claim_number': 1,
                              'claim_type': 'independent',
                              'depends_on': [],
                              'preamble': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                              'transition': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                              'elements': ['占位说明文本用于测试流程稳定运行并满足字段最小长度要求。', '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。', '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'],
                              'full_text': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'},
                             {'claim_number': 2,
                              'claim_type': 'dependent',
                              'depends_on': [1],
                              'preamble': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                              'transition': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                              'elements': ['占位说明文本用于测试流程稳定运行并满足字段最小长度要求。', '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'],
                              'full_text': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'}]},
 'revise_claims': {'claims': [{'claim_number': 1,
                               'claim_type': 'independent',
                               'depends_on': [],
                               'preamble': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                               'transition': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                               'elements': ['占位说明文本用于测试流程稳定运行并满足字段最小长度要求。', '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'],
                               'full_text': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'}]},
 'write_spec': {'title': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                'technical_field': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                'background_art': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                'invention_content': {'technical_problem': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                      'technical_solution': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                      'beneficial_effects': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'},
                'drawings_description': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                'detailed_implementation': {'introductory_boilerplate': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                            'overall_architecture': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                            'component_details': [{'feature_name': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                                   'structure_and_connection': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                                   'working_principle': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'},
                                                                  {'feature_name': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                                   'structure_and_connection': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                                   'working_principle': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'},
                                                                  {'feature_name': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                                   'structure_and_connection': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                                   'working_principle': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'}],
                                            'workflow_description': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                            'alternative_embodiments': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'}},
 'traceability': {'reports': [{'claim_number': 1,
                               'elements_evidence': [{'feature_text': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                      'verbatim_quote': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                      'support_level': 'Explicit',
                                                      'reasoning': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'},
                                                     {'feature_text': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                      'verbatim_quote': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                      'support_level': 'Explicit',
                                                      'reasoning': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'},
                                                     {'feature_text': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                      'verbatim_quote': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。',
                                                      'support_level': 'Explicit',
                                                      'reasoning': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'}],
                               'is_fully_supported': True}],
                  'overall_risk_assessment': '占位说明文本用于测试流程稳定运行并满足字段最小长度要求。'},
 'logic_review': {'issues': []},
 'drawing_map': {'figures': [],
                 'overall_notes': 'No drawing analysis available in stub mode.',
                 'warnings': ['stub_mode_no_vision']}}
def _minimal_specification_stub() -> dict[str, Any]:
    write_spec = _DRAFT_STUBS.get("write_spec")
    if isinstance(write_spec, dict):
        return cast(dict[str, Any], write_spec)
    return {
        "title": "占位说明文本用于测试流程稳定运行并满足字段最小长度要求。",
        "technical_field": "占位说明文本用于测试流程稳定运行并满足字段最小长度要求。",
        "background_art": "占位说明文本用于测试流程稳定运行并满足字段最小长度要求。",
        "invention_content": {
            "technical_problem": "占位说明文本用于测试流程稳定运行并满足字段最小长度要求。",
            "technical_solution": "占位说明文本用于测试流程稳定运行并满足字段最小长度要求。",
            "beneficial_effects": "占位说明文本用于测试流程稳定运行并满足字段最小长度要求。",
        },
        "drawings_description": "占位说明文本用于测试流程稳定运行并满足字段最小长度要求。",
        "detailed_implementation": {
            "introductory_boilerplate": "占位说明文本用于测试流程稳定运行并满足字段最小长度要求。",
            "overall_architecture": "占位说明文本用于测试流程稳定运行并满足字段最小长度要求。",
            "component_details": [],
            "workflow_description": "占位说明文本用于测试流程稳定运行并满足字段最小长度要求。",
            "alternative_embodiments": "占位说明文本用于测试流程稳定运行并满足字段最小长度要求。",
        },
    }
