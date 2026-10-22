"""Controlled transports for the model-led translation/review protocol.

These are fixture oracles, not a semantic model. Pass a deterministic *faithful*
renderer as expected_fn when testing a corrupt/partial generation. Reviews compare
against that independently specified result; they never approve every candidate.
The raw strings retain Markdown/code/link/citation carriers before rendering prose.
"""
from __future__ import annotations

import json
import re

_CARRIERS = re.compile(
    r"(```[^\n]*\n[\s\S]*?```|~~~[^\n]*\n[\s\S]*?~~~|`[^`\n]+`|"
    r"<!--[\s\S]*?-->|<[^>\n]+>|https?://[^\s<>\)]+|\[S\d+(?:-[A-Za-z])?\]|(?<![A-Za-z])(?:MW|GW|kW|mW|W|µW|μW|kWh|MWh|GHz|USD)(?![A-Za-z])|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|\b(?:fred|bls|bis|imf|eia|fiscaldata):[A-Za-z0-9_.-]+|\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s<>]*)?)"
)


def preserve_carriers(source, translate_fn):
    return ''.join(part if index % 2 else translate_fn(part)
                   for index, part in enumerate(_CARRIERS.split(source)))


def model_protocol(messages, translate_fn, *, expected_fn=None):
    """Return JSON text for the new protocol, or None for an explicit legacy call.

    ``translate_fn`` receives each whole readable source entry. ``expected_fn``
    must describe the known faithful fixture translation, not the broken output.
    It defaults to translate_fn for faithful positive fixture renderers only.
    """
    try:
        payload = json.loads((messages or [{}])[-1].get('content', ''))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get('entries'), dict):
        entries = payload['entries']
        assert all(isinstance(key, str) and isinstance(text, str) for key, text in entries.items())
        return json.dumps({'translations': {key: translate_fn(text) for key, text in entries.items()}}, ensure_ascii=False)
    if isinstance(payload.get('pairs'), dict):
        expected = expected_fn or translate_fn
        reviews = {}
        for key, pair in payload['pairs'].items():
            source, candidate = pair['source'], pair['translation']
            faithful = expected(source)
            same = candidate == faithful
            # A faithful fixture renderer must actually translate ordinary prose;
            # identity is permitted only for code/IDs/names/already-target strings.
            visible = _CARRIERS.sub('', candidate)
            foreign_echo = (candidate == source and payload.get('target_language') == 'zh'
                            and not re.search(r'[\u3400-\u9fff]', visible)
                            and len(re.findall(r'\b[a-zA-Z]{4,}\b', visible)) >= 4)
            ok = same and not foreign_echo
            reviews[key] = {'faithful': ok, 'complete': ok, 'target_language': ok,
                            'issues': [] if ok else ['candidate differs from fixture-known faithful translation' if not same else 'source prose was echoed']}
        return json.dumps({'reviews': reviews}, ensure_ascii=False)
    return None


def raw_fixture_zh(value):
    """A deterministic fixture renderer for readable dates/amounts, without app masking.

    Ordinary vocabulary is a stable CJK stand-in, not a live translation-quality
    claim. Explicit dates and magnitudes have independently asserted target forms.
    """
    from decimal import Decimal
    months = {'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
              'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12}
    names = '|'.join(months)
    def decimal(number):
        return format(number, 'f').rstrip('0').rstrip('.') if '.' in format(number, 'f') else format(number, 'f')
    def render(text):
        text = text.replace('## References', '## 参考来源')
        text = re.sub(r'\b(' + names + r')\s+(\d{1,2})[–-](\d{1,2})(?:,\s*(\d{4}))?',
                      lambda m: (m[4] + '年' if m[4] else '') + f'{months[m[1]]}月{m[2]}日–{m[3]}日', text)
        text = re.sub(r'\b(' + names + r')\s+(\d{1,2}),?\s+(\d{4})',
                      lambda m: f'{m[3]}年{months[m[1]]}月{m[2]}日', text)
        text = re.sub(r'\b(' + names + r')\s+(\d{4})', lambda m: f'{m[2]}年{months[m[1]]}月', text)
        def amount(match):
            prefix, first, second, scale_word = match.group(1, 2, 3, 4)
            sign = -1 if '-' in prefix or '−' in prefix else 1
            factor = Decimal(1000000 if scale_word.lower() == 'million' else 1000000000)
            values = [Decimal(first) * sign * factor]
            if second is not None:
                values.append(Decimal(second.replace('−', '-')) * factor)
            magnitude = max(abs(number) for number in values)
            divisor, scale = (Decimal(100000000), '亿') if magnitude >= 100000000 else ((Decimal(10000), '万') if magnitude >= 10000 else (Decimal(1), ''))
            currency = '美元' if '$' in prefix else ('欧元' if '€' in prefix else ('英镑' if '£' in prefix else ''))
            return '–'.join(decimal(number / divisor) for number in values) + scale + currency
        text = re.sub(r'([+\-−]?[$€£]?|[$€£][+\-−]?)(\d+(?:\.\d+)?)(?:[–-]([+\-−]?\d+(?:\.\d+)?))?\s+(million|billion)\b', amount, text)
        text = re.sub(r'(\d+(?:\.\d+)?)\s+Millions of Dollars', lambda m: decimal(Decimal(m[1]) / 100) + '亿美元', text)
        return re.sub(r'(?<![A-Za-z0-9])[A-Za-z][A-Za-z\u2019\u2013\u2014\x27-]*',
                      lambda m: ''.join(chr(0x4E00 + (ord(ch.lower()) - 97) % 40) for ch in re.sub('[^A-Za-z]', '', m[0])[:3]) or '词', text)
    return preserve_carriers(value, render)
