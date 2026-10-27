"""One-dispatch model transport for PDF review; no retries or CLI fallback.

The generic client remains the application's general transport. This narrow adapter
uses the same configured OpenAI-compatible credentials and accounting, but owns the
single-request boundary needed by the durable export ledger. Image comprehension is
established by the agent's persisted pixel probe, never by a provider-name guess.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
import math
import queue
import re
import threading
import time
from urllib.parse import urlsplit

from .contracts import PdfExportError


COMPATIBLE = frozenset({'openai', 'kimi', 'minimax', 'deepseek', 'qwen', 'glm', 'antigravity'})
CLI = frozenset({'claude-cli', 'codex-cli'})
APIS = frozenset({'chat_completions', 'responses'})
_DISPATCH_LOCK = threading.Lock()
_DISPATCHES = {}  # Strong ownership until SDK teardown, even after a caller times out.


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest_json(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def strict_json(text, *, max_chars=262144):
    """Reject repaired/truncated JSON, duplicate keys, nonfinite numbers and fences."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError('nonfinite JSON')

    try:
        if not isinstance(text, str) or len(text) > max_chars:
            raise ValueError('response size')
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
        if not isinstance(result, dict):
            raise ValueError('object required')
        return result
    except (ValueError, TypeError, RecursionError):
        raise PdfExportError('model_response_invalid', 'The export model returned invalid structured output.') from None


def _config(config=None):
    if config is None:
        from ...config import Config
        return Config
    return config


@dataclass(frozen=True)
class Limits:
    max_calls: int = 96
    timeout_seconds: float = 900
    call_timeout_seconds: float = 90
    max_output_tokens: int = 8192
    max_source_chars: int = 500000
    batch_chars: int = 12000
    max_pages: int = 80
    max_image_bytes: int = 8388608

    @classmethod
    def configured(cls, config=None):
        config = _config(config)
        values = {}
        for name, attr in (
            ('max_calls', 'RESEARCH_PDF_MAX_CALLS'),
            ('timeout_seconds', 'RESEARCH_PDF_TIMEOUT_SECONDS'),
            ('call_timeout_seconds', 'RESEARCH_PDF_CALL_TIMEOUT_SECONDS'),
            ('max_output_tokens', 'RESEARCH_PDF_MAX_OUTPUT_TOKENS'),
            ('max_source_chars', 'RESEARCH_PDF_MAX_SOURCE_CHARS'),
            ('batch_chars', 'RESEARCH_PDF_BATCH_CHARS'),
            ('max_pages', 'RESEARCH_PDF_MAX_PAGES'),
            ('max_image_bytes', 'RESEARCH_PDF_MAX_IMAGE_BYTES'),
        ):
            default = getattr(cls(), name)
            raw = getattr(config, attr, default)
            try:
                value = float(raw) if isinstance(default, float) or 'seconds' in name else int(raw)
                if isinstance(raw, bool) or not math.isfinite(value) or value <= 0:
                    raise ValueError('positive finite limit required')
            except (ValueError, TypeError, OverflowError):
                raise PdfExportError('export_configuration', 'PDF export limits must be positive finite values.') from None
            values[name] = value
        if values['batch_chars'] > values['max_source_chars']:
            raise PdfExportError('export_configuration', 'The PDF source batch limit exceeds the total source limit.')
        return cls(**values)


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    api: str = 'chat_completions'
    reasoning_json: str = 'null'
    user_agent: str = field(default='', repr=False)

    def identity(self):
        # Never serialize endpoint strings (which may contain private paths) or keys.
        return {'provider': self.provider, 'model': self.model, 'api': self.api,
                'endpoint_sha256': hashlib.sha256(self.base_url.encode()).hexdigest(),
                'inference_sha256': digest_json({'reasoning': self.reasoning_json, 'user_agent': self.user_agent}),
                'automatic_retries': 0, 'fallback': False}


def resolve_route(role='planner', config=None, *, require_key=True):
    """Resolve roles before dispatch, including the documented official GLM default.

    A primary glm/glm-5.3 on open.bigmodel.cn uses glm-5.3-flash for review
    when REVIEW_MODEL is empty and the endpoint is inherited. Planner, endpoint
    and credentials stay unchanged. Explicit models/custom routes win. This is
    deterministic role configuration, never a failure fallback; the agent still
    requires its actual pixel-comprehension probe.
    """
    config = _config(config)
    if role not in {'planner', 'reviewer'}:
        raise PdfExportError('export_configuration', 'Unknown PDF model role.')
    primary = str(getattr(config, 'LLM_PROVIDER', 'claude-cli') or 'claude-cli').strip().lower()
    review_provider = str(getattr(config, 'RESEARCH_PDF_REVIEW_PROVIDER', '') or '').strip().lower()
    # An explicitly configured HTTP reviewer may also plan when the primary is CLI.
    # This choice is exposed in both role fingerprints, never a runtime fallback.
    use_review = role == 'reviewer' or (primary in CLI and bool(review_provider))
    provider = (review_provider or primary) if use_review else primary
    same_provider = provider == primary
    primary_model = str(getattr(config, 'LLM_MODEL_NAME', '') or '').strip()
    review_model = str(getattr(config, 'RESEARCH_PDF_REVIEW_MODEL', '') or '').strip() if use_review else ''
    model = review_model or (getattr(config, 'RESEARCH_PDF_MODEL', None) if same_provider else None)
    model = str(model or (primary_model if same_provider else '')).strip()
    base = (getattr(config, 'RESEARCH_PDF_REVIEW_BASE_URL', None) if use_review else None)
    base = str(base or (getattr(config, 'LLM_BASE_URL', '') if same_provider else '') or '').strip()
    key = ''
    if require_key:
        key = (getattr(config, 'RESEARCH_PDF_REVIEW_API_KEY', None) if use_review else None)
        key = str(key or (getattr(config, 'LLM_API_KEY', '') if same_provider else '') or '')
    api = (getattr(config, 'RESEARCH_PDF_REVIEW_API', None) if use_review else None)
    api = str(api or getattr(config, 'RESEARCH_PDF_MODEL_API', 'chat_completions') or 'chat_completions')
    if provider not in COMPATIBLE:
        raise PdfExportError('image_review_configuration',
                             'Configure an OpenAI-compatible PDF reviewer; CLI routes cannot deliver page images.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}', model) or api not in APIS:
        raise PdfExportError('export_configuration', 'Configure a valid PDF model and API mode.')
    try:
        url = urlsplit(base)
        valid = (url.scheme in {'http', 'https'} and bool(url.hostname) and not url.username
                 and not url.password and not url.query and not url.fragment)
    except ValueError:
        valid = False
    if not valid or (require_key and not key):
        raise PdfExportError('export_configuration', 'Configure the PDF model endpoint and its existing credentials.')
    if (role == 'reviewer' and primary == provider == 'glm' and primary_model.lower() == 'glm-5.3'
            and not review_model and url.hostname == 'open.bigmodel.cn'
            and base == str(getattr(config, 'LLM_BASE_URL', '') or '').strip()):
        model = 'glm-5.3-flash'
    reasoning = getattr(config, 'reasoning_extra_body', lambda *_: None)(provider, model) if api == 'chat_completions' else None
    user_agent = str(getattr(config, 'LLM_USER_AGENT', 'claude-cli/1.0.0')) if provider == 'kimi' else ''
    return Route(provider, model, base, key, api, canonical(reasoning), user_agent)


def policy_identity(config=None):
    config = _config(config)
    return {role: resolve_route(role, config, require_key=False).identity() for role in ('planner', 'reviewer')}


def _usage(raw, api):
    input_name, output_name = ('input_tokens', 'output_tokens') if api == 'responses' else ('prompt_tokens', 'completion_tokens')
    inputs, outputs = getattr(raw, input_name, None), getattr(raw, output_name, None)
    if type(inputs) is int and inputs >= 0 and type(outputs) is int and outputs >= 0:
        return {'input_tokens': inputs, 'output_tokens': outputs, 'precision': 'reported'}
    return {'input_tokens': None, 'output_tokens': None, 'precision': 'unknown'}


class ExportModel:
    """Public protocol: identity() and complete(system=, payload=, images=, timeout=, max_tokens=).

    images contains private PNG bytes plus hashes supplied by the host. No path or
    remote URL is passed to a provider. The returned result contains parsed data,
    usage precision and route identity; exceptions never expose provider payloads.
    """
    def __init__(self, role='planner', *, config=None, client_factory=None):
        self.config = _config(config)
        self.route = resolve_route(role, self.config)
        self.client_factory = client_factory

    def identity(self):
        return self.route.identity()

    def complete(self, *, system, payload, images=(), timeout, max_tokens):
        if not math.isfinite(timeout) or timeout <= 0 or type(max_tokens) is not int or max_tokens <= 0:
            raise PdfExportError('export_budget', 'The PDF model request has no remaining allowance.')
        text = canonical(payload)
        parts = [{'type': 'text', 'text': text}]
        for image in images:
            raw = image['bytes']
            if (not isinstance(raw, bytes) or not raw.startswith(b'\x89PNG\r\n\x1a\n')
                    or hashlib.sha256(raw).hexdigest() != image['sha256']):
                raise PdfExportError('artifact_changed', 'A PDF review image failed its integrity check.')
            parts.append({'type': 'image_url', 'image_url': {
                'url': 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii'), 'detail': 'high'}})
        results = queue.Queue(maxsize=1)
        dispatch_id = object()
        limit = max(1, int(getattr(self.config, 'RESEARCH_PDF_MAX_CONCURRENT', 2)))
        with _DISPATCH_LOCK:
            if len(_DISPATCHES) >= limit:
                raise PdfExportError('model_dispatch_busy',
                                     'A prior PDF model request is still closing; retry after it finishes.', retryable=True)
            _DISPATCHES[dispatch_id] = {'worker': None, 'started': time.monotonic()}

        def dispatch():
            try:
                results.put((True, self._request(system, parts, timeout, max_tokens)))
            except Exception as exc:
                # Keep the raw exception only in this private transient queue; never log it.
                results.put((False, exc))
            finally:
                with _DISPATCH_LOCK:
                    _DISPATCHES.pop(dispatch_id, None)

        started = time.monotonic()
        worker = threading.Thread(target=dispatch, name='pdf-model-request', daemon=True)
        with _DISPATCH_LOCK:
            _DISPATCHES[dispatch_id]['worker'] = worker
        try:
            worker.start()
        except Exception:
            with _DISPATCH_LOCK:
                _DISPATCHES.pop(dispatch_id, None)
            raise PdfExportError('model_not_dispatched', 'The PDF model worker could not start.', retryable=True) from None
        try:
            ok, result = results.get(timeout=timeout)
        except queue.Empty:
            raise PdfExportError('model_dispatch_unknown',
                                 'The PDF model request timed out; its dispatch outcome is unknown.') from None
        if not ok:
            if isinstance(result, PdfExportError) and result.code == 'model_response_invalid':
                raise result from None
            status = getattr(result, 'status_code', None)
            if type(status) is int and 400 <= status < 500 and status not in {408}:
                raise PdfExportError('model_request_rejected',
                                     'The configured model rejected the PDF request. Check its model and image support.',
                                     retryable=status == 429) from None
            raise PdfExportError('model_dispatch_unknown',
                                 'The PDF model request did not return a confirmed response; automatic replay is disabled.') from None
        content, usage = result
        if usage['precision'] == 'reported':
            # Record in the caller's context, not the dispatch thread's empty contextvars.
            from ...utils.telemetry import LLMMeter, get_run_context
            run_id, stage = get_run_context()
            LLMMeter.record(self.route.provider, self.route.model, usage['input_tokens'], usage['output_tokens'],
                            (time.monotonic() - started) * 1000, cached=False, stage=stage, run_id=run_id)
        return {'data': strict_json(content), 'usage': usage, 'identity': self.identity()}

    def _request(self, system, parts, timeout, max_tokens):
        factory = self.client_factory
        if factory is None:
            from openai import OpenAI
            factory = OpenAI
        headers = {'User-Agent': self.route.user_agent} if self.route.user_agent else None
        kwargs = {'api_key': self.route.api_key, 'base_url': self.route.base_url,
                  'timeout': timeout, 'max_retries': 0}
        if headers:
            kwargs['default_headers'] = headers
        client = factory(**kwargs)
        try:
            if self.route.api == 'responses':
                content = [{'type': 'input_text', 'text': part['text']} if part['type'] == 'text'
                           else {'type': 'input_image', 'image_url': part['image_url']['url'], 'detail': 'high'}
                           for part in parts]
                response = client.responses.create(model=self.route.model, instructions=system,
                    input=[{'role': 'user', 'content': content}], max_output_tokens=max_tokens,
                    text={'format': {'type': 'json_object'}}, store=False, timeout=timeout)
                if getattr(response, 'status', None) != 'completed':
                    raise PdfExportError('model_response_invalid', 'The PDF model response is incomplete.')
                return response.output_text, _usage(getattr(response, 'usage', None), 'responses')
            request = {'model': self.route.model, 'messages': [
                {'role': 'system', 'content': system}, {'role': 'user', 'content': parts}],
                'max_tokens': max_tokens, 'response_format': {'type': 'json_object'}, 'timeout': timeout}
            reasoning = json.loads(self.route.reasoning_json)
            if reasoning:
                request['extra_body'] = reasoning
            if self.route.provider == 'kimi':
                request['temperature'] = 0.6 if (reasoning or {}).get('thinking', {}).get('type') == 'disabled' else 1.0
            response = client.chat.completions.create(**request)
            choice = response.choices[0]
            if getattr(choice, 'finish_reason', None) != 'stop':
                raise PdfExportError('model_response_invalid', 'The PDF model response is incomplete.')
            return choice.message.content, _usage(getattr(response, 'usage', None), 'chat_completions')
        finally:
            client.close()
