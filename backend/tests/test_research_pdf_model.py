"""Controlled SDK transport tests; no provider calls or unguarded app imports."""
import base64
import hashlib
import io
import threading
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from app.services.research_pdf.contracts import PdfExportError
from app.services.research_pdf.model import ExportModel, Limits, policy_identity, resolve_route, strict_json

pytestmark = pytest.mark.guarded_runner


def config(**overrides):
    values = {'LLM_PROVIDER':'openai', 'LLM_MODEL_NAME':'existing-model',
              'LLM_BASE_URL':'https://configured.test/v1', 'LLM_API_KEY':'private-test-credential'}
    return NS(**(values | overrides))


def png():
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), 'blue').save(buffer, format='PNG')
    data = buffer.getvalue()
    return {'bytes': data, 'sha256': hashlib.sha256(data).hexdigest()}


class SDK:
    def __init__(self, *, answer='{"verdict":"pass"}', error=None, api='chat_completions', finish='stop'):
        self.answer, self.error, self.api, self.finish = answer, error, api, finish
        self.requests, self.options, self.closed = [], [], 0

    def factory(self, **kwargs):
        self.options.append(kwargs)
        return NS(chat=NS(completions=NS(create=self.create)), responses=NS(create=self.create), close=self.close)

    def close(self):
        self.closed += 1

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        if self.api == 'responses':
            return NS(output_text=self.answer, status='completed' if self.finish == 'stop' else 'incomplete',
                      usage=NS(input_tokens=17, output_tokens=9))
        return NS(choices=[NS(message=NS(content=self.answer), finish_reason=self.finish)],
                  usage=NS(prompt_tokens=17, completion_tokens=9))


def complete(adapter, **kwargs):
    return adapter.complete(system='Return JSON only.', payload={'source': 'accepted text'}, images=[png()],
                            timeout=kwargs.get('timeout', 2), max_tokens=321)


@pytest.mark.parametrize('api', ['chat_completions', 'responses'])
def test_real_image_parts_and_explicit_caps_reach_sdk_without_fallback(api):
    sdk = SDK(api=api)
    adapter = ExportModel('reviewer', config=config(RESEARCH_PDF_MODEL_API=api), client_factory=sdk.factory)
    result = complete(adapter)
    request = sdk.requests[0]
    if api == 'responses':
        parts = request['input'][0]['content']
        assert parts[1]['type'] == 'input_image'
        image_url = parts[1]['image_url']
        assert request['max_output_tokens'] == 321
        assert request['store'] is False
    else:
        parts = request['messages'][1]['content']
        assert parts[1]['type'] == 'image_url'
        image_url = parts[1]['image_url']['url']
        assert request['max_tokens'] == 321
    assert base64.b64decode(image_url.split(',', 1)[1]) == png()['bytes']
    assert len(sdk.requests) == sdk.closed == 1
    assert sdk.options[0]['max_retries'] == 0
    assert sdk.options[0]['timeout'] == request['timeout'] == 2
    assert result['usage'] == {'input_tokens': 17, 'output_tokens': 9, 'precision': 'reported'}
    assert result['identity']['fallback'] is False
    assert 'private-test-credential' not in repr(result)
    assert 'configured.test' not in repr(result)


def test_explicit_reviewer_override_never_borrows_other_provider_credentials():
    settings = config(RESEARCH_PDF_REVIEW_PROVIDER='glm', RESEARCH_PDF_REVIEW_MODEL='glm-review',
                      RESEARCH_PDF_REVIEW_BASE_URL='https://review.test/v1')
    with pytest.raises(PdfExportError, match='credentials'):
        resolve_route('reviewer', settings)
    settings.RESEARCH_PDF_REVIEW_API_KEY = 'review-private'
    reviewer = resolve_route('reviewer', settings)
    assert reviewer.api_key == 'review-private'
    assert reviewer.model == 'glm-review'
    assert 'review-private' not in repr(reviewer)
    assert resolve_route('planner', settings).model == 'existing-model'


@pytest.mark.parametrize('provider', ['claude-cli', 'codex-cli'])
def test_cli_never_qualifies_as_image_route(provider):
    with pytest.raises(PdfExportError) as caught:
        ExportModel('reviewer', config=config(LLM_PROVIDER=provider))
    assert caught.value.code == 'image_review_configuration'


def test_explicit_api_reviewer_can_also_plan_for_cli_primary():
    settings = config(LLM_PROVIDER='claude-cli', RESEARCH_PDF_REVIEW_PROVIDER='openai',
                      RESEARCH_PDF_REVIEW_MODEL='review-model', RESEARCH_PDF_REVIEW_BASE_URL='http://localhost:9999/v1',
                      RESEARCH_PDF_REVIEW_API_KEY='review-private')
    assert resolve_route('planner', settings) == resolve_route('reviewer', settings)


def test_fingerprint_never_reads_credential_fields():
    class NoCredentials:
        LLM_PROVIDER = 'openai'
        LLM_MODEL_NAME = 'existing-model'
        LLM_BASE_URL = 'https://configured.test/v1'

        def __getattr__(self, name):
            if name.endswith('API_KEY'):
                raise AssertionError('policy must not read keys')
            raise AttributeError(name)

    assert policy_identity(NoCredentials())['reviewer']['model'] == 'existing-model'


@pytest.mark.parametrize('url', ['https://user:secret@host/v1', 'https://host/v1?key=secret', 'file:///tmp/key'])
def test_credentials_cannot_enter_endpoint_identity(url):
    with pytest.raises(PdfExportError) as caught:
        resolve_route(config=config(LLM_BASE_URL=url))
    assert 'secret' not in str(caught.value)


@pytest.mark.parametrize('text', ['{"a":1,"a":2}', '{"a":NaN}', '```json\n{}\n```', '{"a":', '[]'])
def test_json_is_strict_no_local_repair_or_retry(text):
    sdk = SDK(answer=text)
    with pytest.raises(PdfExportError) as caught:
        complete(ExportModel(config=config(), client_factory=sdk.factory))
    assert caught.value.code == 'model_response_invalid'
    assert len(sdk.requests) == 1


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_truncated_model_output_never_qualifies(api):
    sdk = SDK(api=api, finish='length')
    with pytest.raises(PdfExportError) as caught:
        complete(ExportModel(config=config(RESEARCH_PDF_MODEL_API=api), client_factory=sdk.factory))
    assert caught.value.code == 'model_response_invalid'
    assert len(sdk.requests) == 1


@pytest.mark.parametrize('status,code', [(401, 'model_request_rejected'), (429, 'model_request_rejected'),
                                      (500, 'model_dispatch_unknown'), (408, 'model_dispatch_unknown')])
def test_provider_errors_are_safe_and_never_retried(status, code):
    failure = RuntimeError('sk-private-source-body-credential')
    failure.status_code = status
    sdk = SDK(error=failure)
    with pytest.raises(PdfExportError) as caught:
        complete(ExportModel(config=config(), client_factory=sdk.factory))
    assert caught.value.code == code
    assert 'sk-private' not in str(caught.value.public())
    assert len(sdk.requests) == 1


def test_local_timeout_returns_unknown_without_replaying_request():
    release = threading.Event()
    sdk = SDK()
    original = sdk.create

    def blocked(**kwargs):
        release.wait(2)
        return original(**kwargs)

    sdk.create = blocked
    try:
        with pytest.raises(PdfExportError) as caught:
            complete(ExportModel(config=config(), client_factory=sdk.factory), timeout=.02)
        assert caught.value.code == 'model_dispatch_unknown'
        assert len(sdk.options) == 1
    finally:
        release.set()


def test_image_integrity_failure_never_dispatches():
    sdk = SDK()
    image = png() | {'sha256': 'incorrect'}
    with pytest.raises(PdfExportError) as caught:
        ExportModel(config=config(), client_factory=sdk.factory).complete(
            system='JSON', payload={}, images=[image], timeout=2, max_tokens=100)
    assert caught.value.code == 'artifact_changed'
    assert not sdk.options


@pytest.mark.parametrize('value', [0, -1, float('inf'), float('nan'), True])
def test_nonpositive_or_nonfinite_limits_fail_closed(value):
    with pytest.raises(PdfExportError):
        Limits.configured(config(RESEARCH_PDF_TIMEOUT_SECONDS=value))


def test_valid_json_object_is_not_changed():
    assert strict_json('{"number":"(1.2%)","text":"准确"}') == {'number': '(1.2%)', 'text': '准确'}


def test_inference_options_are_frozen_and_part_of_route_identity():
    sdk = SDK()
    settings = config(reasoning_extra_body=lambda *_: {'thinking': {'type': 'disabled'}})
    model = ExportModel(config=settings, client_factory=sdk.factory)
    before = model.identity()
    settings.reasoning_extra_body = lambda *_: {'thinking': {'type': 'enabled'}}
    complete(model)
    assert sdk.requests[0]['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert model.identity() == before
    assert ExportModel(config=settings, client_factory=sdk.factory).identity() != before


def test_timed_out_request_retains_capacity_until_transport_teardown():
    from app.services.research_pdf import model as module
    release = threading.Event()
    sdk = SDK()
    original = sdk.create

    def blocked(**kwargs):
        release.wait(2)
        return original(**kwargs)

    sdk.create = blocked
    adapter = ExportModel(config=config(RESEARCH_PDF_MAX_CONCURRENT=1), client_factory=sdk.factory)
    try:
        with pytest.raises(PdfExportError) as caught:
            complete(adapter, timeout=.01)
        assert caught.value.code == 'model_dispatch_unknown'
        with pytest.raises(PdfExportError) as caught:
            complete(adapter)
        assert caught.value.code == 'model_dispatch_busy'
        assert len(sdk.options) == 1
        with module._DISPATCH_LOCK:
            workers = [entry['worker'] for entry in module._DISPATCHES.values()]
    finally:
        release.set()
    for worker in workers:
        worker.join(2)
    assert not module._DISPATCHES


@pytest.mark.parametrize('name', ['glm-5.3', 'glm-5.3-flash', 'glm-5.3-flashx'])
def test_glm53_family_config_never_disables_required_thinking(name, monkeypatch):
    from app.config import Config
    monkeypatch.setattr(Config, 'LLM_DISABLE_THINKING', True)
    monkeypatch.setattr(Config, 'LLM_ALWAYS_THINKING_MODELS', 'glm-5')
    monkeypatch.setattr(Config, 'LLM_THINKING_REQUIRED_EFFORT', 'low')
    assert Config.reasoning_extra_body('glm', name) == {
        'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low'}


def test_flash_reviewer_reuses_existing_glm_credentials_and_sends_enabled_thinking(monkeypatch):
    from app.config import Config
    for name, value in {'LLM_PROVIDER': 'glm', 'LLM_MODEL_NAME': 'glm-5.3',
        'LLM_BASE_URL': 'https://configured.test/api/coding/paas/v4', 'LLM_API_KEY': 'synthetic-existing-key',
        'LLM_DISABLE_THINKING': True, 'LLM_ALWAYS_THINKING_MODELS': 'glm-5',
        'LLM_THINKING_REQUIRED_EFFORT': 'low', 'RESEARCH_PDF_MODEL': '',
        'RESEARCH_PDF_REVIEW_PROVIDER': '', 'RESEARCH_PDF_REVIEW_MODEL': 'glm-5.3-flash',
        'RESEARCH_PDF_REVIEW_BASE_URL': '', 'RESEARCH_PDF_REVIEW_API_KEY': '',
        'RESEARCH_PDF_MODEL_API': 'chat_completions', 'RESEARCH_PDF_REVIEW_API': ''}.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    sdk = SDK()
    adapter = ExportModel('reviewer', config=Config, client_factory=sdk.factory)
    result = complete(adapter)
    assert sdk.requests[0]['model'] == 'glm-5.3-flash'
    assert sdk.requests[0]['extra_body'] == {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low'}
    assert sdk.requests[0]['messages'][1]['content'][1]['type'] == 'image_url'
    assert sdk.options[0]['api_key'] == 'synthetic-existing-key'
    assert sdk.options[0]['base_url'] == Config.LLM_BASE_URL
    assert resolve_route('planner', Config).model == 'glm-5.3'
    assert Config.LLM_MODEL_NAME == 'glm-5.3'
    assert 'synthetic-existing-key' not in repr(result)


@pytest.mark.parametrize('primary_model', ['glm-5.3', 'GLM-5.3'])
def test_official_glm53_reviewer_default_is_role_configuration_only(primary_model):
    settings = config(LLM_PROVIDER='glm', LLM_MODEL_NAME=primary_model,
                      LLM_BASE_URL='https://open.bigmodel.cn/api/coding/paas/v4')
    planner, reviewer = resolve_route('planner', settings), resolve_route('reviewer', settings)
    assert planner.model == primary_model
    assert reviewer.model == 'glm-5.3-flash'
    assert planner.provider == reviewer.provider == 'glm'
    assert planner.base_url == reviewer.base_url == settings.LLM_BASE_URL
    assert planner.api_key == reviewer.api_key == settings.LLM_API_KEY
    identities = policy_identity(settings)
    assert identities['planner']['model'] == primary_model
    assert identities['reviewer']['model'] == 'glm-5.3-flash'
    assert identities['reviewer']['fallback'] is False
    assert identities['reviewer']['automatic_retries'] == 0
    assert identities['reviewer']['endpoint_sha256'] == identities['planner']['endpoint_sha256']
    assert 'private-test-credential' not in repr(identities)
    assert settings.LLM_MODEL_NAME == primary_model


@pytest.mark.parametrize('overrides,expected', [
    ({'RESEARCH_PDF_REVIEW_MODEL': 'glm-5.3'}, 'glm-5.3'),
    ({'RESEARCH_PDF_REVIEW_MODEL': 'explicit-vision-model'}, 'explicit-vision-model'),
    ({'RESEARCH_PDF_REVIEW_MODEL': ' glm-5.3-flashx '}, 'glm-5.3-flashx'),
    ({'LLM_PROVIDER': 'openai'}, 'glm-5.3'),
    ({'LLM_BASE_URL': 'https://api.z.ai/api/paas/v4'}, 'glm-5.3'),
    ({'LLM_BASE_URL': 'https://open.bigmodel.cn.proxy.test/v1'}, 'glm-5.3'),
    ({'RESEARCH_PDF_REVIEW_BASE_URL': 'https://review-proxy.test/v1'}, 'glm-5.3'),
    ({'LLM_BASE_URL': 'https://proxy.test/v1',
      'RESEARCH_PDF_REVIEW_BASE_URL': 'https://open.bigmodel.cn/api/paas/v4'}, 'glm-5.3'),
    ({'LLM_MODEL_NAME': 'glm-5.2'}, 'glm-5.2'),
    ({'LLM_MODEL_NAME': 'glm-5.3-preview'}, 'glm-5.3-preview'),
])
def test_glm_reviewer_default_preserves_explicit_models_and_other_routes(overrides, expected):
    base = {'LLM_PROVIDER': 'glm', 'LLM_MODEL_NAME': 'glm-5.3',
            'LLM_BASE_URL': 'https://open.bigmodel.cn/api/coding/paas/v4'}
    settings = config(**(base | overrides))
    assert resolve_route('reviewer', settings).model == expected


def test_explicit_reviewer_identity_overrides_automatic_default():
    settings = config(LLM_PROVIDER='glm', LLM_MODEL_NAME='glm-5.3',
                      LLM_BASE_URL='https://open.bigmodel.cn/api/coding/paas/v4')
    implicit = policy_identity(settings)
    settings.RESEARCH_PDF_REVIEW_MODEL = 'glm-5.3-flashx'
    explicit = policy_identity(settings)
    assert explicit['reviewer']['model'] == 'glm-5.3-flashx'
    assert implicit['reviewer'] != explicit['reviewer']
    assert implicit['planner'] == explicit['planner']
