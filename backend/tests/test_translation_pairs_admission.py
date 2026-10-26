"""Real threaded translation-client admission using controlled clients only."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from app.services.translation_tools import translation_client, translate_pairs


class Calls:
    def __init__(self):
        self.condition = threading.Condition()
        self.release = threading.Event()
        self.attempts = 0
        self.active = 0
        self.peak = 0
        self.entered = []

    def attempting(self):
        with self.condition:
            self.attempts += 1
            self.condition.notify_all()

    def answer(self, label, value, fail=False):
        with self.condition:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.entered.append(label)
            self.condition.notify_all()
        try:
            assert self.release.wait(5), 'test must release held provider calls'
            if fail:
                raise RuntimeError('controlled translation failure')
            return value
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()


class Client:
    def __init__(self, calls, name, fail=False):
        self.calls = calls
        self.model = name
        self.provider = 'controlled'
        self.fail = fail
        self.history = []

    def chat(self, *args, **kwargs):
        self.history.append(('chat', args, kwargs))
        return self.calls.answer(self.model + ':chat', 'translated', self.fail)

    def chat_json(self, *args, **kwargs):
        self.history.append(('chat_json', args, kwargs))
        return self.calls.answer(self.model + ':chat_json', {'translated': True}, self.fail)

    def metadata(self):
        return {'model': self.model, 'provider': self.provider}


@pytest.mark.parametrize('setting,expected', [(None, 1), ('2', 2), ('99', 4), ('0', 1), ('invalid', 1)])
def test_shared_admission_across_different_clients_and_both_methods(monkeypatch, setting, expected):
    if setting is None:
        monkeypatch.delenv('DRF_TRANSLATION_MAX_CONCURRENCY', raising=False)
    else:
        monkeypatch.setenv('DRF_TRANSLATION_MAX_CONCURRENCY', setting)
    calls = Calls()
    count = 8
    start = threading.Barrier(count + 1)
    clients = [translation_client(Client(calls, f'client-{index}')) for index in range(count)]
    def invoke(index):
        start.wait(timeout=5)
        calls.attempting()
        method = clients[index].chat if index % 2 else clients[index].chat_json
        return method(messages=[{'role': 'user', 'content': 'controlled'}])
    with ThreadPoolExecutor(max_workers=count) as executor:
        futures = [executor.submit(invoke, index) for index in range(count)]
        try:
            start.wait(timeout=5)
            with calls.condition:
                assert calls.condition.wait_for(lambda: calls.attempts == count and calls.active >= expected, timeout=3)
                # Hold admitted calls so an unguarded competing client would
                # observably exceed the configured bound before release.
                assert not calls.condition.wait_for(lambda: calls.peak > expected, timeout=.08)
                assert calls.active == expected
        finally:
            calls.release.set()
        assert len([future.result(timeout=5) for future in futures]) == count
    assert calls.peak == expected
    assert calls.active == 0 and len(calls.entered) == count
    assert any(':chat_json' in label for label in calls.entered)
    assert any(label.endswith(':chat') for label in calls.entered)


def test_proxy_is_idempotent_and_preserves_client_attributes_and_arguments(monkeypatch):
    monkeypatch.delenv('DRF_TRANSLATION_MAX_CONCURRENCY', raising=False)
    calls = Calls()
    calls.release.set()
    client = Client(calls, 'original')
    wrapped = translation_client(client)
    assert translation_client(wrapped) is wrapped
    assert wrapped.model == 'original' and wrapped.provider == 'controlled'
    wrapped.model = 'changed'
    assert client.model == 'changed' and wrapped.metadata()['model'] == 'changed'
    assert wrapped.chat('positional', max_tokens=15) == 'translated'
    assert wrapped.chat_json(messages=[{'content': 'input'}], tier='strong') == {'translated': True}
    assert client.history == [
        ('chat', ('positional',), {'max_tokens': 15}),
        ('chat_json', (), {'messages': [{'content': 'input'}], 'tier': 'strong'}),
    ]


@pytest.mark.parametrize('failing_method', ['chat', 'chat_json'])
def test_failure_releases_shared_slot_for_an_already_waiting_client(monkeypatch, failing_method):
    monkeypatch.setenv('DRF_TRANSLATION_MAX_CONCURRENCY', '1')
    calls = Calls()
    failing = translation_client(Client(calls, 'failing', fail=True))
    waiting = translation_client(Client(calls, 'waiting'))
    def invoke(client, method):
        calls.attempting()
        return getattr(client, method)(messages=[{'content': 'controlled'}])
    with ThreadPoolExecutor(max_workers=2) as executor:
        failed = executor.submit(invoke, failing, failing_method)
        with calls.condition:
            assert calls.condition.wait_for(lambda: calls.active == 1, timeout=3)
        succeeded = executor.submit(invoke, waiting, 'chat_json')
        try:
            with calls.condition:
                assert calls.condition.wait_for(lambda: calls.attempts == 2, timeout=3)
                assert not calls.condition.wait_for(lambda: len(calls.entered) > 1, timeout=.08)
        finally:
            calls.release.set()
        with pytest.raises(RuntimeError, match='controlled translation failure'):
            failed.result(timeout=5)
        assert succeeded.result(timeout=5) == {'translated': True}
    assert calls.peak == 1 and calls.active == 0
    assert calls.entered == ['failing:' + failing_method, 'waiting:chat_json']
    # A subsequent operation still obtains a slot after the exception path.
    assert waiting.chat(messages=[]) == 'translated'


def test_real_pair_translator_and_wrapped_report_client_share_one_admission(monkeypatch):
    monkeypatch.delenv('DRF_TRANSLATION_MAX_CONCURRENCY', raising=False)
    calls = Calls()
    report = translation_client(Client(calls, 'report'))
    class PairClient:
        model = 'pairs'
        provider = 'controlled'
        def chat(self, messages, **kwargs):
            from model_translation_fakes import model_protocol
            response = model_protocol(messages, lambda source: '政策可能调整。')
            return calls.answer('pair:chat', response)
    def invoke_report():
        calls.attempting()
        return report.chat_json(messages=[])
    def invoke_pairs():
        calls.attempting()
        return translate_pairs(PairClient(), [('claim', 'The policy may change.')], '简体中文')
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(invoke_report)
        with calls.condition:
            assert calls.condition.wait_for(lambda: calls.active == 1, timeout=3)
        second = executor.submit(invoke_pairs)
        try:
            with calls.condition:
                assert calls.condition.wait_for(lambda: calls.attempts == 2, timeout=3)
                assert not calls.condition.wait_for(lambda: len(calls.entered) > 1, timeout=.08)
        finally:
            calls.release.set()
        assert first.result(timeout=5) == {'translated': True}
        assert second.result(timeout=5)[0] == {'claim': '政策可能调整。'}
    assert calls.peak == 1 and calls.entered == ['report:chat_json', 'pair:chat', 'pair:chat']


def test_proxy_preserves_missing_method_capabilities_and_real_method_errors(monkeypatch):
    monkeypatch.delenv('DRF_TRANSLATION_MAX_CONCURRENCY', raising=False)
    class ChatOnly:
        model = 'chat-only'
        def chat(self, *args, **kwargs):
            return 'chat-only response'
    class JsonOnly:
        def chat_json(self, *args, **kwargs):
            return {'json': True}
    chat = translation_client(ChatOnly())
    assert hasattr(chat, 'chat') and not hasattr(chat, 'chat_json')
    with pytest.raises(AttributeError):
        chat.chat_json(messages=[])
    assert chat.chat(messages=[]) == 'chat-only response'
    structured = translation_client(JsonOnly())
    assert hasattr(structured, 'chat_json') and not hasattr(structured, 'chat')
    assert structured.chat_json(messages=[]) == {'json': True}
    class ActualMethodRaises:
        def chat_json(self, *args, **kwargs):
            raise AttributeError('underlying real method raised internally')
    actual = translation_client(ActualMethodRaises())
    assert hasattr(actual, 'chat_json')
    with pytest.raises(AttributeError, match='underlying real method raised internally'):
        actual.chat_json(messages=[])
    assert chat.chat(messages=[]) == 'chat-only response'
