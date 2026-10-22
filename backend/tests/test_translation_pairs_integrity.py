"""Native raw-model pair protocol plus retained historical validator controls."""
import json
import re

import pytest

from app.services.model_translation import ENGINE, valid_receipt
from app.services.translation_tools import translate_pairs, valid_pair_translation


class Translator:
    """Controlled translator/reviewer; responses are not live semantic evidence."""
    model = 'controlled-translation-reviewer'
    provider = 'fake'

    def __init__(self, mutator=None, translations=None):
        self.calls = []
        self.mutator = mutator
        self.translations = dict(translations or {})
        self.generation_calls = 0

    def render(self, source):
        if source in self.translations:
            return self.translations[source]
        # A symbolic transport fixture for non-semantic tests. Typed-unit/name
        # fixtures retain their spelling; actual equivalence examples use an
        # explicit complete source/target pair below.
        pieces = re.split(r'(```[\s\S]*?```|`[^`\n]+`|https?://[^\s<>()]+|\[S\d+\]|<!--[\s\S]*?-->)', source)
        units = {'W', 'kW', 'MW', 'GW', 'TW', 'mW', 'Wh', 'kWh', 'MWh', 'GWh', 'TWh', 'mWh'}
        def word(match):
            value = match.group(0)
            return value if value in units or value.isupper() or '_' in value or any(ch.isdigit() for ch in value) else '译'
        return ''.join(piece if piece.startswith(('`', 'http', '[S', '<!--')) else
                       re.sub(r'[A-Za-z][A-Za-z0-9_]*', word, piece) for piece in pieces)

    def chat(self, messages, **kwargs):
        assert kwargs.get('response_format') == {'type': 'json_object'}
        payload = json.loads(messages[-1]['content'])
        self.calls.append(payload)
        if 'entries' in payload:
            self.generation_calls += 1
            translated = {key: self.render(value) for key, value in payload['entries'].items()}
            raw = self.mutator(translated, self.generation_calls) if self.mutator else json.dumps(translated, ensure_ascii=False)
            return '{"translations":' + raw + '}'
        assert 'pairs' in payload, payload
        reviews = {}
        for key, pair in payload['pairs'].items():
            accepted = pair['translation'] == self.render(pair['source'])
            reviews[key] = {'faithful': accepted, 'complete': accepted, 'target_language': accepted,
                            'issues': [] if accepted else ['controlled semantic mismatch']}
        return json.dumps({'reviews': reviews}, ensure_ascii=False)


def test_raw_source_and_equivalent_localized_numbers_reach_the_shared_core():
    source = ('Committee plans 25 MW capacity in November 9–10, 2026, with $3.7 billion funding '
              'and 40% probability [S12]. Source https://example.test/2026/report, GDP_USD FY2030.')
    target = ('委员会计划于2026年11月9–10日增加25 MW产能，融资为37亿美元，概率为40% [S12]。'
              '来源 https://example.test/2026/report, GDP_USD FY2030。')
    llm = Translator(translations={source: target})
    mapping, level = translate_pairs(llm, [('a', source)], '简体中文', context='research fields')
    assert mapping == {'a': target} and level == 0
    assert llm.calls[0]['entries'] == {'a': source}
    assert '⟦KEEP:' not in json.dumps(llm.calls, ensure_ascii=False)
    assert '$3.7 billion' in llm.calls[0]['entries']['a']
    assert llm.calls[1]['pairs']['a'] == {'source': source, 'translation': target}
    assert mapping.calls_used == 2
    assert mapping.receipts['a']['engine'] == ENGINE
    assert valid_receipt(source, target, 'zh', mapping.receipts['a'], context='research fields')
    # The old numeric/date token spelling would reject this valid localization;
    # it must not be the active producer or cache admission rule anymore.
    assert not valid_pair_translation(source, target, '简体中文')


@pytest.mark.parametrize('damage', ['extra', 'missing', 'duplicate', 'nonstring', 'number', 'english'])
def test_invalid_outputs_receive_one_bounded_native_repair_without_extra_key_poison(damage):
    def corrupt(result, generation):
        if generation > 1:
            return json.dumps(result, ensure_ascii=False)
        if damage == 'extra':
            result['UNREQUESTED'] = '恶意新增'
        elif damage == 'missing':
            result.pop('b')
        elif damage == 'duplicate':
            return '{"a":"甲","a":"乙","b":"丙"}'
        elif damage == 'nonstring':
            result['a'] = {'nested': 'poison'}
        elif damage == 'number':
            result['a'] = result['a'].replace('25 MW', '99 MW')
        else:
            result['a'] = 'The committee will keep this whole policy statement in English without translating anything.'
        return json.dumps(result, ensure_ascii=False)
    llm = Translator(corrupt)
    pairs = [('a', 'The policy raises capacity to 25 MW.'), ('b', 'A different policy statement.')]
    mapping, _ = translate_pairs(llm, pairs, '简体中文')
    assert set(mapping) == {'a', 'b'}
    assert llm.generation_calls == 2 and mapping.calls_used <= 4
    assert '25 MW' in mapping['a'] and 'UNREQUESTED' not in mapping
    for key, source in pairs:
        assert valid_receipt(source, mapping[key], 'zh', mapping.receipts[key])
    if damage in {'number', 'english'}:
        assert set(llm.calls[2]['entries']) == {'a'}, 'a successful entry must never be repaired again'


def test_coherent_whole_entry_is_not_clipped_or_token_rewritten_and_calls_are_bounded():
    source = ('A long policy description with 25 MW capacity. ' * 180) + 'Final statement 99%.'
    llm = Translator()
    mapping, _ = translate_pairs(llm, [('long', source)], '简体中文')
    assert mapping['long'].endswith('99%.') and mapping['long'].count('25 MW') == 180
    assert llm.calls[0]['entries']['long'] == source
    assert valid_receipt(source, mapping['long'], 'zh', mapping.receipts['long'])
    bad = Translator(lambda result, count: 'not JSON')
    mapping, _ = translate_pairs(bad, [(str(i), 'Some full sentence.') for i in range(40)], '简体中文', max_calls=3)
    assert mapping == {} and mapping.calls_used <= 3 and len(bad.calls) <= 3


def test_semantic_review_rejects_echo_but_permits_explicit_names():
    source = 'The committee delayed its planned decision.'
    llm = Translator(translations={source: '委员会推迟了原定决策。', 'NVIDIA': 'NVIDIA', 'Federal Reserve': 'Federal Reserve'})
    good, _ = translate_pairs(llm, [('statement', source), ('name', 'NVIDIA'), ('bank', 'Federal Reserve')], 'zh')
    assert set(good) == {'statement', 'name', 'bank'}
    bad = Translator(lambda result, count: json.dumps({key: '译文：' + source for key in result}), translations=llm.translations)
    rejected, _ = translate_pairs(bad, [('statement', source)], 'zh')
    assert rejected == {} and rejected.calls_used == 4
    assert any('semantic review' in issue for issue in rejected.issues['statement'])


def test_provider_failure_callback_counts_one_call_without_content_ladder_or_fanout():
    class Down:
        model = 'fake-down'
        def chat(self, **kwargs):
            raise RuntimeError('controlled provider unavailable')
    failed = []
    mapping, _ = translate_pairs(Down(), [('a', 'The policy might change.')], 'zh', on_failure=lambda: failed.append(True))
    assert mapping == {} and mapping.calls_used == 1 and failed == [True]


def test_legacy_validator_helpers_remain_available_for_explicit_historical_controls():
    assert valid_pair_translation('NVIDIA', 'NVIDIA', '简体中文')
    assert valid_pair_translation('Federal Reserve', 'Federal Reserve', '简体中文')
    assert not valid_pair_translation('Capacity reaches 25 MW.', '产能达到25 GW。', '简体中文')
    assert not valid_pair_translation('The last price is .41 with −2% change and 1e-3 uncertainty.',
                                      '价格为41、变化2%、误差1e3。', '简体中文')
