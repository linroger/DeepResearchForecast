#!/usr/bin/env python3
"""Private, headless target-run bootstrap. Requires Python -I -S -B.

Preparation is provider-free and creates no spending authority. A later run
requires a separately reviewed manifest, existing qualified credentials and an
outside-runtime consumption registry. This trusted-process boundary follows the
pre-import checks in main_offline_pytest and world_dossier_replay; it is not an
OS sandbox, a deployment tool, or an assertion about provider invoices.

Prompts must be exact normalized UTF-8 with LF line endings. CR characters
(including CRLF) are unsupported and refused before authorization; input is
never silently normalized or replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import stat
import sys
import tempfile
import time
import types

SCHEMA = "target-acceptance-runtime/v1"
SCHEMA_V2 = "target-acceptance-runtime/v2"
LAUNCHER = "app/backend/scripts/target_acceptance_run.py"
CORE = "app/deerflow_bridge/run_spending.py"
CHILD = "deer-flow/deerflow_research.py"
HARNESS = "deer-flow/backend/packages/harness"
SKILL_LOCK = "deer-flow/skills/.drf-runtime-skill-sync.lock"
IDENTITY = ("HOME", "home", "CODEX_HOME", "USERPROFILE")
CARRIERS = ("DRF_RUN_SPENDING_REQUIRED", "DRF_RUN_SPENDING_BINDING",
            "DRF_RUN_SPENDING_MODULE_SHA256", "DRF_RUN_SPENDING_OPERATION")
REQUEST_KEYS = {"prompt", "mode", "depth", "language", "model", "forecast_authority", "target_simulation"}
ANCHOR_LIMITS = {"model_attempt_limit": 20, "token_envelope_limit": 150000,
                 "catalog_attempt_limit": 8, "followup_attempt_limit": 12}
ANCHOR_FIELDS = {"mode", "anchor_budget_scope_id", "policy_version", "source_policy_sha256",
                 *ANCHOR_LIMITS, "catalog_lookups_per_gap", "followup_round_limit"}
MUTABLE = ("spend", "app/backend/uploads", "app/backend/logs", "deer-flow-home", "tmp", "cache")
FORBIDDEN_PARTS = {"uploads", "logs", ".git", ".venv", "venv", "node_modules", "__pycache__",
                   "secrets", "credentials", ".ssh", ".aws", ".codex", ".claude"}
HEX = re.compile(r"[0-9a-f]{64}\Z")
# Existing Config.PROVIDER_META / research _PROVIDER_KEY_ENVS mappings. These
# aliases select an already-supported OpenAI-compatible research profile; they
# do not qualify its tariff/account or assert that a coding subscription is API.
PROFILES = {"glm": ("glm", "ZHIPUAI_API_KEY"), "deepseek": ("deepseek", "DEEPSEEK_API_KEY"),
            "qwen": ("qwen", "DASHSCOPE_API_KEY"), "minimax": ("minimax", "MINIMAX_API_KEY"),
            "kimi": ("kimi", "KIMI_API_KEY")}
SAFE_CODES = {"invalid_path", "invalid_spec", "source_drift", "invalid_request", "invalid_binding",
              "unsafe_environment", "unsafe_import", "billing_class_unverified", "missing_ledger",
              "runtime_exists", "isolated_python_required", "pipeline_failed", "launcher_failed", "resume_denied",
              "stage_profile_oversize", "unsupported_route"}


class LauncherStop(RuntimeError):
    """Never include paths, argv, prompts, bindings or exception text in errors."""
    def __init__(self, code):
        self.code = code if code in SAFE_CODES else "launcher_failed"
        super().__init__(self.code)


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        raise LauncherStop("invalid_request")


def require(condition, code="invalid_spec"):
    if not condition:
        raise LauncherStop(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def path_checked(value, *, directory=False, new=False, private=False):
    require(isinstance(value, (str, Path)), "invalid_path")
    p = Path(value)
    require(p.is_absolute() and str(p) == os.path.abspath(p), "invalid_path")
    for part in (p, *p.parents):
        require(not part.is_symlink(), "invalid_path")
    require(p.resolve() == p, "invalid_path")
    if new:
        require(not p.exists(), "runtime_exists")
        path_checked(p.parent, directory=True)
        return p
    s = p.stat()
    require(stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode), "invalid_path")
    if not directory:
        require(s.st_nlink == 1, "invalid_path")
    if private:
        require(s.st_uid == os.getuid() and not s.st_mode & 0o077, "invalid_path")
    else:
        require(not s.st_mode & 0o022, "invalid_path")
    return p


def read_bytes(path):
    p = path_checked(path)
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read()
        after = os.fstat(stream.fileno())
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "source_drift")
    return data


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    raw = read_bytes(path)
    require(len(raw) <= 32_000_000)
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: require(False))


def write_new(path, data):
    path_checked(path, new=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def relative(value, *, source=False):
    require(isinstance(value, str) and value and "\\" not in value)
    p = Path(value)
    require(not p.is_absolute() and str(p) == value and ".." not in p.parts)
    if source:
        require(not any(x.lower() in FORBIDDEN_PARTS or x.lower().startswith(".env") for x in p.parts))
        require(p.suffix.lower() not in {".pth", ".pyc", ".pyo", ".pem", ".key", ".p8", ".sqlite", ".sqlite3", ".db"})
        require(p.name.lower() not in {"credentials.json", "auth.json", ".netrc", ".git-credentials"})
    return p


def hash_map(value, *, source=False):
    require(type(value) is dict and bool(value))
    for name, sha in value.items():
        relative(name, source=source)
        require(isinstance(sha, str) and HEX.fullmatch(sha))
    return value


def check_request(request):
    require(type(request) is dict and set(request) in (REQUEST_KEYS, REQUEST_KEYS | {"world_anchor"}), "invalid_request")
    require(request["mode"] == "full" and request["forecast_authority"] == "target-first-v1", "invalid_request")
    require(request["depth"] in {"quick", "standard", "deep"}
            and request["language"] in {"English", "Chinese", ""}, "invalid_request")
    for key in ("prompt", "model"):
        require(isinstance(request[key], str) and bool(request[key]) and request[key] == request[key].strip(), "invalid_request")
    # The existing research CLI uses universal-newline text reads. Qualify
    # only LF input before approval so an authorized CR/CRLF prompt cannot
    # silently become a different string at the later in-memory scope check.
    require("\r" not in request["prompt"], "invalid_request")
    require(request["model"] == request["model"].lower(), "invalid_request")
    sim = request["target_simulation"]
    require(type(sim) is dict and set(sim) == {"paths", "periods", "seed"}, "invalid_request")
    for key, low, high in (("paths", 1, 256), ("periods", 1, 120), ("seed", 0, 2**31 - 1)):
        require(type(sim[key]) is int and low <= sim[key] <= high, "invalid_request")
    if "world_anchor" in request:
        anchor = request["world_anchor"]
        require(type(anchor) is dict and set(anchor) == ANCHOR_FIELDS, "invalid_request")
        require(anchor["mode"] == "v1" and anchor["policy_version"] == "world-anchor-budget/v1", "invalid_request")
        require(isinstance(anchor["anchor_budget_scope_id"], str)
                and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", anchor["anchor_budget_scope_id"]), "invalid_request")
        require(isinstance(anchor["source_policy_sha256"], str) and HEX.fullmatch(anchor["source_policy_sha256"]), "invalid_request")
        for key, maximum in ANCHOR_LIMITS.items():
            minimum = 1 if key in {"model_attempt_limit", "token_envelope_limit"} else 0
            require(type(anchor[key]) is int and minimum <= anchor[key] <= maximum, "invalid_request")
        for key in ("catalog_lookups_per_gap", "followup_round_limit"):
            require(type(anchor[key]) is int and anchor[key] == 1, "invalid_request")
    return request


def check_anchor_budget(budget, request, model):
    """Validate the private prepared policy without loading application code."""
    check_request(request)
    require("world_anchor" in request, "invalid_request")
    fields = {"schema", "scope_id", "policy_version", "source_policy_sha256", *ANCHOR_LIMITS,
              "catalog_lookups_per_gap", "followup_round_limit", "model_profile",
              "catalog_route_ids", "followup_route_ids", "usage_policy"}
    require(type(budget) is dict and set(budget) == fields, "invalid_request")
    require(budget["schema"] == "anchor-budget/v1" and budget["usage_policy"] == "provider_reported_required", "invalid_request")
    expected = {"mode": "v1", "anchor_budget_scope_id": budget["scope_id"],
                **{key: budget[key] for key in ANCHOR_FIELDS - {"mode", "anchor_budget_scope_id"}}}
    # Validate separately: Python equality alone would admit bool as integer.
    check_request({**request, "world_anchor": expected})
    require(canonical(expected) == canonical(request["world_anchor"]), "invalid_request")
    profile = budget["model_profile"]
    require(type(profile) is dict and set(profile) == {"route_id", "max_output_tokens"}, "invalid_request")
    require(isinstance(profile["route_id"], str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", profile["route_id"]), "invalid_request")
    require(type(profile["max_output_tokens"]) is int and 1 <= profile["max_output_tokens"] <= 2000
            and profile["max_output_tokens"] <= model["max_output_tokens"], "invalid_request")
    for key in ("catalog_route_ids", "followup_route_ids"):
        values = budget[key]
        require(type(values) is list and len(values) <= 16
                and all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value) for value in values), "invalid_request")
        require(len(set(values)) == len(values), "invalid_request")
    envelope = model["input_ceiling"] + profile["max_output_tokens"]
    require(envelope <= budget["token_envelope_limit"], "stage_profile_oversize")
    return {"scope_id": budget["scope_id"], "input_upper_bound": model["input_ceiling"],
            "max_output_tokens": profile["max_output_tokens"], "token_envelope_units": envelope}


def tree_files(root):
    """Exact inventory, with no symlink traversal, executable .pth or bytecode."""
    result = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            path_checked(Path(folder) / name, directory=True)
        dirs[:] = [name for name in dirs if name != "__pycache__"]
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                continue
            p = path_checked(Path(folder) / name)
            require(not name.endswith((".pth", ".egg-link")) and not name.startswith(".env"), "unsafe_import")
            result[str(p.relative_to(root))] = digest(read_bytes(p))
    return result


def check_dependencies(dependencies, root):
    require(type(dependencies) is list and bool(dependencies))
    seen = set()
    for item in dependencies:
        require(type(item) is dict and set(item) == {"path", "files"})
        p = path_checked(item["path"], directory=True)
        require(not p.is_relative_to(root) and str(p) not in seen, "unsafe_import")
        seen.add(str(p))
        hash_map(item["files"])
        require(tree_files(p) == item["files"], "source_drift")
        require(not any((p / name).exists() for name in ("app", "deerflow", "deerflow_bridge", "run_spending.py")), "unsafe_import")


def model_config(model):
    require(type(model) is dict and set(model) == {"provider", "alias", "name", "endpoint", "input_ceiling", "max_output_tokens"})
    require(model["provider"] in PROFILES and model["alias"] == PROFILES[model["provider"]][0], "billing_class_unverified")
    require(isinstance(model["name"], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}", model["name"]))
    from urllib.parse import urlsplit
    url = urlsplit(model["endpoint"])
    require(url.scheme == "https" and url.hostname and not url.username and not url.password
            and not url.query and not url.fragment, "billing_class_unverified")
    for key in ("input_ceiling", "max_output_tokens"):
        require(type(model[key]) is int and 0 < model[key] <= 2**31 - 1)
    return {"config_version": 11, "log_level": "warning", "token_usage": {"enabled": True},
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider", "allow_host_bash": False},
            "models": [{"name": model["alias"], "use": "langchain_openai:ChatOpenAI",
                        "model": model["name"], "base_url": model["endpoint"], "api_key": "$LLM_API_KEY",
                        "max_tokens": model["max_output_tokens"], "max_retries": 0,
                        "context_window_tokens": model["input_ceiling"], "supports_thinking": False}],
            "tools": [], "tool_groups": []}


def import_roots(root):
    return [str(root / p) for p in ("app/backend", "app", "deer-flow", HARNESS)]


def prepare(source, deerflow_source, root, spec_path):
    """All reads/validation precede creating R; source is copied by explicit map."""
    source = path_checked(source, directory=True)
    deerflow_source = path_checked(deerflow_source, directory=True)
    root = path_checked(root, new=True)
    no_dotenv(root)
    require(not any(root.is_relative_to(p) or p.is_relative_to(root) for p in (source, deerflow_source)), "invalid_path")
    spec = read_json(spec_path)
    require(type(spec) is dict)
    is_v2 = spec.get("schema") == "target-acceptance-prepare/v2"
    fields = {"schema", "python", "python_sha256", "app_files", "deerflow_files", "dependencies", "request", "model"}
    require(set(spec) == fields | ({"anchor_budget"} if is_v2 else set()))
    require(spec["schema"] in {"target-acceptance-prepare/v1", "target-acceptance-prepare/v2"})
    python = path_checked(spec["python"])
    require(os.access(python, os.X_OK) and digest(read_bytes(python)) == spec["python_sha256"], "source_drift")
    check_dependencies(spec["dependencies"], root)
    request = check_request(spec["request"])
    config = model_config(spec["model"])
    require(request["model"] == spec["model"]["alias"], "invalid_request")
    require(("world_anchor" in request) == is_v2, "invalid_request")
    if is_v2:
        check_anchor_budget(spec["anchor_budget"], request, spec["model"])
    staged = {}
    for prefix, origin, entries in (("app", source, spec["app_files"]), ("deer-flow", deerflow_source, spec["deerflow_files"])):
        for name, sha in hash_map(entries, source=True).items():
            require(Path(name).name != "config.yaml", "invalid_spec")
            raw = read_bytes(origin / name)
            require(digest(raw) == sha, "source_drift")
            staged[f"{prefix}/{name}"] = raw
    for required in (LAUNCHER, CORE, "app/backend/app/config.py", "app/backend/app/services/run_spending.py",
                     "app/backend/app/services/pipeline_orchestrator.py"):
        require(required in staged, "invalid_spec")
    require(staged[LAUNCHER] == read_bytes(Path(__file__).resolve()), "source_drift")
    # Deploy bridge bytes only into the new private tree, from the same reviewed
    # source map as the parent. Never run setup.sh or copy an installed bridge.
    for name, raw in list(staged.items()):
        p = Path(name)
        if p.parent == Path("app/deerflow_bridge") and p.suffix == ".py":
            dest = "deer-flow/" + p.name
            require(dest not in staged or staged[dest] == raw, "source_drift")
            staged[dest] = raw
    require(CHILD in staged and "deer-flow/run_spending.py" in staged)
    require(HARNESS + "/deerflow/__init__.py" in staged and HARNESS + "/deerflow/config/__init__.py" in staged)
    require(SKILL_LOCK not in staged, "invalid_spec")
    staged["control/request.json"] = canonical(request)
    staged["control/config.json"] = canonical(spec["model"])
    if is_v2:
        staged["control/anchor_budget.json"] = canonical(spec["anchor_budget"])
    staged["deer-flow/config.yaml"] = canonical(config)  # JSON is a YAML subset.
    runtime = {"schema": SCHEMA_V2 if is_v2 else SCHEMA, "root": str(root), "python": str(python), "python_sha256": spec["python_sha256"],
               "files": {name: digest(raw) for name, raw in staged.items()}, "dependencies": spec["dependencies"],
               "import_roots": import_roots(root), "mutable_roots": [str(root / p) for p in MUTABLE]}
    root.mkdir(mode=0o700)
    for name in (*MUTABLE, HARNESS):
        (root / name).mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, raw in staged.items():
        p = root / name
        p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_new(p, raw)
    write_new(root / "control/runtime.json", canonical(runtime))
    write_new(root / "spend/runtime.json", canonical(runtime))
    return verify(root)


def no_dotenv(root):
    # Ancestor .env must be detected without reading its (possibly secret) bytes.
    for directory in (root, *root.parents, Path.cwd(), *Path.cwd().parents):
        require(not (directory / ".env").exists() and not (directory / ".env").is_symlink(), "unsafe_environment")


def verify(root):
    root = path_checked(root, directory=True, private=True)
    no_dotenv(root)
    runtime = read_json(root / "spend/runtime.json")
    require(read_bytes(root / "spend/runtime.json") == read_bytes(root / "control/runtime.json"), "source_drift")
    require(type(runtime) is dict and set(runtime) == {"schema", "root", "python", "python_sha256", "files", "dependencies", "import_roots", "mutable_roots"})
    require(runtime["schema"] in {SCHEMA, SCHEMA_V2} and runtime["root"] == str(root), "invalid_binding")
    is_v2 = runtime["schema"] == SCHEMA_V2
    require(runtime["import_roots"] == import_roots(root)
            and runtime["mutable_roots"] == [str(root / p) for p in MUTABLE], "invalid_binding")
    for name in (*runtime["mutable_roots"], *runtime["import_roots"]):
        path_checked(name, directory=True)
    python = path_checked(runtime["python"])
    require(os.access(python, os.X_OK) and digest(read_bytes(python)) == runtime["python_sha256"], "source_drift")
    files = hash_map(runtime["files"])
    for name in files:
        require(name != SKILL_LOCK, "invalid_spec")
        controls = {"control/request.json", "control/config.json"} | ({"control/anchor_budget.json"} if is_v2 else set())
        require(name.startswith(("app/", "deer-flow/")) or name in controls)
        relative(name, source=True)
        require(digest(read_bytes(root / name)) == files[name], "source_drift")
    for name in (LAUNCHER, CORE, CHILD, "deer-flow/run_spending.py", "control/request.json", "control/config.json", "deer-flow/config.yaml"):
        require(name in files, "source_drift")
    require(files[CORE] == files["deer-flow/run_spending.py"], "source_drift")
    # Runtime artifacts may be added only under the declared mutable roots.
    observed = {}
    for prefix in ("app", "deer-flow"):
        for folder, dirs, names in os.walk(root / prefix, followlinks=False):
            for name in dirs:
                path_checked(Path(folder) / name, directory=True)
            dirs[:] = [name for name in dirs if str((Path(folder) / name).relative_to(root)) not in MUTABLE]
            for name in names:
                p = Path(folder) / name
                if str(p.relative_to(root)) == SKILL_LOCK:
                    path_checked(p)  # one empty regular flock artifact only
                    require(p.stat().st_size == 0, "source_drift")
                    continue
                require(str(p.relative_to(root)) in files, "source_drift")
                observed[str(p.relative_to(root))] = digest(read_bytes(p))
    require(observed == {k: v for k, v in files.items() if k.startswith(("app/", "deer-flow/"))}, "source_drift")
    check_dependencies(runtime["dependencies"], root)
    request = check_request(read_json(root / "control/request.json"))
    model = read_json(root / "control/config.json")
    require(request["model"] == model["alias"] and read_json(root / "deer-flow/config.yaml") == model_config(model), "source_drift")
    require(("world_anchor" in request) == is_v2, "invalid_request")
    budget = None
    if is_v2:
        require("control/anchor_budget.json" in files, "source_drift")
        budget = read_json(root / "control/anchor_budget.json")
        check_anchor_budget(budget, request, model)
    # Core source_files deliberately excludes spend/. Pin an immutable mirror
    # and require byte-for-byte equality with the coordinator-facing descriptor.
    source_files = {**files, "control/runtime.json": digest(read_bytes(root / "control/runtime.json"))}
    checked = {"runtime": runtime, "request": request, "model": model, "source_files": source_files}
    if is_v2:
        checked["anchor_budget"] = budget
    return checked


def load_core(root, *, child=False):
    path = root / ("deer-flow/run_spending.py" if child else CORE)
    existing = sys.modules.get("run_spending") or sys.modules.get("deerflow_bridge.run_spending")
    if existing is not None:
        require(Path(existing.__file__) == path, "unsafe_import")
        return existing
    spec = importlib.util.spec_from_file_location("run_spending", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_spending"] = module
    spec.loader.exec_module(module)
    return module


def qualify_manifest(core, checked, manifest):
    manifest = core.validate_manifest(manifest)
    is_v2 = checked["runtime"]["schema"] == SCHEMA_V2
    require(manifest["schema"] == ("target-run-spending/v2" if is_v2 else "target-run-spending/v1"), "invalid_binding")
    require(manifest["root"] == checked["runtime"]["root"]
            and manifest["source_files"] == checked["source_files"]
            and manifest["request_sha256"] == core.hash_payload(checked["request"]), "source_drift")
    if is_v2:
        require(canonical(manifest["anchor_budget"]) == canonical(checked["anchor_budget"]), "source_drift")
        check_anchor_budget(manifest["anchor_budget"], checked["request"], checked["model"])
        # No catalog credential/transport mapping is qualified in this initial
        # launcher profile. Core/binder synthetic catalog tests are separate.
        require(not manifest["anchor_budget"]["catalog_route_ids"]
                and not any(r["kind"] == "catalog_lookup" for r in manifest["routes"].values()), "unsupported_route")
    routes = {r["kind"]: r for r in manifest["routes"].values()}
    require(set(routes) == {"openai_chat", "firecrawl_search", "firecrawl_scrape"}, "billing_class_unverified")
    route, model = routes["openai_chat"], checked["model"]
    require(route["model"] == model["name"] and route["endpoint"] == model["endpoint"]
            and route["input_ceiling"] == model["input_ceiling"]
            and route["max_output_tokens"] == model["max_output_tokens"], "billing_class_unverified")
    require(routes["firecrawl_search"]["endpoint"] == "https://api.firecrawl.dev/v2/search"
            and routes["firecrawl_scrape"]["endpoint"] == "https://api.firecrawl.dev/v2/scrape", "billing_class_unverified")
    return manifest


def preflight_bound_runtime(core, binding, checked):
    """Bound v2 consumer guard, called before importing application/providers."""
    require(binding["schema"] == "target-run-spending-binding/v2", "invalid_binding")
    core.validate_bound_request(binding, checked["request"])
    profile = core.preflight_anchor_profile(binding)
    expected = check_anchor_budget(checked["anchor_budget"], checked["request"], checked["model"])
    require(all(profile[key] == value for key, value in expected.items())
            and profile["policy_sha256"] == core.hash_payload(checked["anchor_budget"])
            and profile["route_id"] == checked["anchor_budget"]["model_profile"]["route_id"], "invalid_binding")
    return profile


def check_credentials(credentials, manifest):
    require(type(credentials) is dict and set(credentials) == {"LLM_API_KEY", "FIRECRAWL_API_KEY"}, "unsafe_environment")
    for route in manifest["routes"].values():
        key = "LLM_API_KEY" if route["kind"] == "openai_chat" else "FIRECRAWL_API_KEY"
        value = credentials[key]
        require(isinstance(value, str) and value.strip() == value and bool(value)
                and digest(value.encode()) == route["account_sha256"], "billing_class_unverified")


def controlled_environment(root, checked):
    model = checked["model"]
    env = {"PATH": os.defpath, "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "LLM_PROVIDER": model["provider"], "LLM_BASE_URL": model["endpoint"], "LLM_MODEL_NAME": model["name"],
           "LLM_FAST_MODEL": model["name"], "LLM_STRONG_MODEL": model["name"],
           "DEERFLOW_MODEL": model["alias"], "DEERFLOW_RESEARCH_MODEL": model["alias"],
           "DEERFLOW_DIR": str(root / "deer-flow"), "DEERFLOW_PYTHON": checked["runtime"]["python"],
           "DEER_FLOW_PROJECT_ROOT": str(root / "deer-flow"), "DEER_FLOW_HOME": str(root / "deer-flow-home"),
           "DEER_FLOW_CONFIG_PATH": str(root / "deer-flow/config.yaml"),
           "RESEARCH_MODEL_LEASE_DB": str(root / "spend/research-model-leases.sqlite3"),
           "RESEARCH_ENGINE": "v3", "RESEARCH_MODEL_TIERING": "false", "DEERFLOW_SUBAGENTS": "false",
           "RESOLUTION_MONITOR_AUTORUN_HOURS": "0", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    for name in ("LLM_TIERED_ROUTING", "DATA_SOURCES_ENABLED", "NEWS_CONTEXT_ENABLED", "MARKET_INTELLIGENCE_ENABLED",
                 "PREDICTION_MARKETS_ENABLED", "REDDIT_SIGNALS_ENABLED", "RESEARCH_MCP_KG", "RESEARCH_FALLBACK_ON_EXHAUST",
                 "RESEARCH_TIMEOUT_EXTRACT_SALVAGE", "RESEARCH_DUAL_TRACK", "DEERFLOW_DUAL_TRACK", "RESEARCH_DIRECT_FETCH"):
        env[name] = "false"
    for name in ("LLM_FALLBACK_PROVIDER", "LLM_FALLBACK_MODEL_NAME", "DEERFLOW_FALLBACK_MODEL"):
        env[name] = ""
    for name, relative_path in {"TMPDIR": "tmp", "TMP": "tmp", "TEMP": "tmp", "XDG_CACHE_HOME": "cache",
                                "XDG_CONFIG_HOME": "cache/config", "MPLCONFIGDIR": "cache/matplotlib",
                                "HF_HOME": "cache/huggingface", "TIKTOKEN_CACHE_DIR": "cache/tiktoken",
                                "DATA_SOURCES_CACHE_DIR": "cache/data", "PLOTLY_DIR": "cache/plotly",
                                "RESEARCH_SOURCE_CACHE_DIR": "cache/sources", "RESEARCH_SEARCH_CACHE_DIR": "cache/search",
                                "PREDICTION_MARKETS_CACHE_DIR": "cache/markets"}.items():
        env[name] = str(root / relative_path)
    return env


def child_controls(env, root, checked, binding, argv):
    """Carry only bounded coordinator-authored execution/receipt fields forward."""
    expected = controlled_environment(root, checked)
    for key in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL_NAME", "LLM_FAST_MODEL", "LLM_STRONG_MODEL",
                "DEERFLOW_MODEL", "DEERFLOW_RESEARCH_MODEL", "DEERFLOW_DIR", "DEER_FLOW_CONFIG_PATH",
                "RESEARCH_ENGINE", "DEERFLOW_DUAL_TRACK", "PYTHON_DOTENV_DISABLED"):
        if key in env:
            require(env[key] == expected[key], "unsafe_environment")
    values, switches = parse_child_arguments(argv[1:])
    handoff = Path(values["--out-dir"])
    expected_handoff = root / "app/backend/uploads/pipelines" / binding["pipeline_id"] / "handoff"
    require(handoff == expected_handoff, "invalid_binding")
    require(Path(values["--prompt-file"]).parent == handoff, "invalid_binding")
    result = {"RESEARCH_BUDGET_RUN_ID": binding["pipeline_id"], "DEERFLOW_RUN_ARTIFACT_DIR": str(handoff),
              "RESEARCH_BUDGET_DB": str(handoff / "research_budget.sqlite3"),
              "RESEARCH_BUDGET_TELEMETRY_PATH": str(handoff / "research_budget.json"),
              "RESEARCH_BUDGET_LANE_ID": "outer-track-1",
              "RESEARCH_BUDGET_EPOCH": "spending-generation-" + str(binding["generation"]),
              "DEERFLOW_SUBAGENTS": "true" if "--subagents" in switches else "false"}
    for key in ("RESEARCH_BUDGET_DB", "RESEARCH_BUDGET_TELEMETRY_PATH", "DEERFLOW_RUN_ARTIFACT_DIR"):
        if env.get(key):
            p = Path(env[key])
            require(p.is_absolute() and p.is_relative_to(handoff)
                    and p.resolve() == p and not any(x.is_symlink() for x in (p, *p.parents)), "invalid_path")
            if key == "DEERFLOW_RUN_ARTIFACT_DIR":
                require(p == handoff, "invalid_binding")
            result[key] = str(p)
    for key in ("RESEARCH_BUDGET_RUN_ID", "RESEARCH_BUDGET_EPOCH", "RESEARCH_BUDGET_LANE_ID", "RESEARCH_CHECKPOINT_ID",
                "NEWS_CONTEXT_QUESTION_SHA256"):
        if env.get(key):
            require(re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", env[key]), "invalid_binding")
            result[key] = env[key]
    if "RESEARCH_BUDGET_RUN_ID" in result:
        require(result["RESEARCH_BUDGET_RUN_ID"] == binding["pipeline_id"], "invalid_binding")
    require(result["RESEARCH_BUDGET_LANE_ID"] == "outer-track-1", "invalid_binding")
    if "--resume" in switches:
        # Only a generation advanced by the core's explicit clean-resume proof
        # can carry a resume checkpoint. The child cannot create that approval.
        require(type(binding.get("generation")) is int and binding["generation"] > 1
                and env.get("RESEARCH_CHECKPOINT_ID") and env.get("RESEARCH_BUDGET_EPOCH"), "invalid_binding")
    else:
        require(not env.get("RESEARCH_CHECKPOINT_ID"), "invalid_binding")
    for key in ("DEERFLOW_RESEARCH_TIMEOUT", "DEERFLOW_DEEP_OPENING_RECURSION_LIMIT", "RESEARCH_FANOUT_WIDTH",
                "RESEARCH_MODEL_CONCURRENCY_GLOBAL", "RESEARCH_GLOBAL_SUBAGENT_CAP", "ACTOR_CAST_MAX",
                "RESEARCH_BUDGET_ATTEMPTS_GLOBAL", "RESEARCH_BUDGET_SEARCH_GLOBAL", "RESEARCH_BUDGET_SEARCH_LANE",
                "RESEARCH_BUDGET_FETCH_GLOBAL", "RESEARCH_BUDGET_FETCH_LANE", "RESEARCH_NEGATIVE_CACHE_TTL_SECONDS",
                "RESEARCH_NEGATIVE_CACHE_RETRIES", "DEER_FLOW_MAX_CONCURRENT_SUBAGENTS"):
        if key in env:
            require(re.fullmatch(r"[0-9]{1,9}", env[key]), "invalid_binding")
            result[key] = env[key]
    for key in ("RESEARCH_DEEP_FANOUT", "ACTOR_EXCLUDE_MEDIA", "RESEARCH_SHARED_ACTOR_TRACK"):
        if key in env:
            require(env[key] in {"true", "false"}, "invalid_binding")
            result[key] = env[key]
    if "DRF_RUNTIME_SKILL_SYNC_REQUIRED" in env or "DRF_RUNTIME_SKILL_SYNC" in env:
        require(env.get("DRF_RUNTIME_SKILL_SYNC_REQUIRED") == "1", "invalid_binding")
        payload = json.loads(env.get("DRF_RUNTIME_SKILL_SYNC", "null"))
        require(type(payload) is dict and payload.get("deployed_path") == str(root / "deer-flow/skills/public"), "invalid_binding")
        require(payload.get("source_manifest_hash") == payload.get("deployed_manifest_hash")
                and isinstance(payload.get("source_manifest_hash"), str)
                and HEX.fullmatch(payload["source_manifest_hash"]), "source_drift")
        result.update(DRF_RUNTIME_SKILL_SYNC_REQUIRED="1", DRF_RUNTIME_SKILL_SYNC=canonical(payload).decode())
    return result


def reject_ambient(env, *, child=False, model=None):
    credential_alias = PROFILES[model["provider"]][1] if model else None
    for key, value in env.items():
        sensitive = key != "TIKTOKEN_CACHE_DIR" and any(part in key.upper() for part in ("API_KEY", "TOKEN", "CREDENTIAL", "PASSWORD", "SECRET"))
        if sensitive and value:
            require(child and key in {"LLM_API_KEY", "FIRECRAWL_API_KEY", credential_alias}, "unsafe_environment")
            if key == credential_alias:
                require(value == env.get("LLM_API_KEY"), "billing_class_unverified")
        require(not (value and (key in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES"}
                               or ("FALLBACK" in key and value.lower() not in {"false", "0"}))), "unsafe_environment")


class ImportBoundary:
    """Validate origins before the ordinary PathFinder executes a module."""
    def __init__(self, checked):
        root = Path(checked["runtime"]["root"])
        self.files = {str(root / name): sha for name, sha in checked["source_files"].items()}
        for dep in checked["runtime"]["dependencies"]:
            self.files.update({str(Path(dep["path"]) / name): sha for name, sha in dep["files"].items()})
        self.stdlib = Path(os.__file__).resolve().parent

    def origin(self, origin):
        if origin in (None, "built-in", "frozen"):
            return
        p = path_checked(origin)
        if str(p) in self.files:
            require(digest(read_bytes(p)) == self.files[str(p)], "source_drift")
        else:
            require(p.is_relative_to(self.stdlib) and not any(x in p.parts for x in ("site-packages", "dist-packages")), "unsafe_import")

    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is not None:
            self.origin(spec.origin)
            if isinstance(spec.loader, importlib.machinery.SourceFileLoader):
                boundary = self
                class VerifiedSourceLoader(importlib.machinery.SourceFileLoader):
                    def get_code(self, module_name):
                        # -B does not disable reading .pyc. Compile the hashed
                        # source explicitly, including when a forged cache is
                        # present with matching metadata or an unchecked hash.
                        filename = self.get_filename(module_name)
                        raw = read_bytes(filename)
                        expected = boundary.files.get(filename)
                        if expected is not None:
                            require(digest(raw) == expected, "source_drift")
                        return compile(raw, filename, "exec", dont_inherit=True)
                spec.loader = VerifiedSourceLoader(fullname, spec.origin)
            elif isinstance(spec.loader, importlib.machinery.SourcelessFileLoader):
                raise LauncherStop("unsafe_import")
            if spec.submodule_search_locations:
                for folder in spec.submodule_search_locations:
                    p = path_checked(folder, directory=True)
                    require(p.is_relative_to(self.stdlib) or any(Path(name).is_relative_to(p) for name in self.files), "unsafe_import")
        return spec


def install_imports(checked):
    boundary = ImportBoundary(checked)
    for name, module in tuple(sys.modules.items()):
        if name not in {__name__, "__main__"}:
            boundary.origin(getattr(module, "__file__", None))
    stdlib_paths = [p for p in sys.path if p and Path(p).is_relative_to(boundary.stdlib)
                    and "site-packages" not in Path(p).parts and "dist-packages" not in Path(p).parts]
    sys.path[:] = [*stdlib_paths, *checked["runtime"]["import_roots"],
                   *(dep["path"] for dep in checked["runtime"]["dependencies"])]
    sys.meta_path.insert(0, boundary)
    # Prevent application factory/__init__ side effects in this headless process.
    app = types.ModuleType("app")
    app.__path__ = [str(Path(checked["runtime"]["root"]) / "app/backend/app")]
    sys.modules["app"] = app
    # Mirrors the offline guard: never invoke dotenv discovery, including APIs
    # used by dependencies that predate PYTHON_DOTENV_DISABLED support.
    dotenv = types.ModuleType("dotenv")
    dotenv.__path__ = []
    dotenv.load_dotenv = lambda *a, **kw: False
    dotenv.find_dotenv = lambda *a, **kw: ""
    dotenv.dotenv_values = lambda *a, **kw: {}
    main = types.ModuleType("dotenv.main")
    for name in ("load_dotenv", "find_dotenv", "dotenv_values"):
        setattr(main, name, getattr(dotenv, name))
    dotenv.main = main
    sys.modules.update({"dotenv": dotenv, "dotenv.main": main})


class RuntimeGuard:
    """No listening, arbitrary subprocess, credential discovery or external writes."""
    def __init__(self, checked, registry, authorization_id=None):
        self.root = Path(checked["runtime"]["root"])
        self.python = checked["runtime"]["python"]
        self.python_sha256 = checked["runtime"]["python_sha256"]
        self.registry = Path(registry)
        self.pinned = {self.root / name for name in checked["source_files"]}
        self.pinned.add(self.root / "spend/runtime.json")
        self.pipeline_receipt = (self.registry / (digest(canonical(authorization_id)) + ".pipeline.json")
                                 if authorization_id is not None else None)

    def write_path(self, value):
        require(not isinstance(value, int), "invalid_path")
        p = Path(os.fsdecode(value)).absolute()
        require(p.is_relative_to(self.root) and p not in self.pinned and p.resolve() == p, "invalid_path")
        for part in (p, *p.parents):
            require(not part.is_symlink(), "invalid_path")

    def __call__(self, event, args):
        if event in {"socket.bind", "os.system", "os.exec", "os.posix_spawn", "os.fork"}:
            raise LauncherStop("unsafe_environment")
        if event == "subprocess.Popen":
            argv = args[1]
            prefix = [self.python, "-I", "-S", "-B", str(self.root / LAUNCHER), "_child", "--", str(self.root / CHILD)]
            require(isinstance(argv, (list, tuple)) and list(argv[:len(prefix)]) == prefix, "unsafe_environment")
            require(digest(read_bytes(self.python)) == self.python_sha256, "source_drift")
        if event == "open" and not isinstance(args[0], int):
            p = Path(os.fsdecode(args[0])).absolute()
            require(not p.name.startswith(".env") and p.suffix != ".pth"
                    and not any(x in p.parts for x in (".ssh", ".aws", ".claude")), "unsafe_environment")
            flags = args[2] if len(args) > 2 else 0
            if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if p == self.pipeline_receipt:
                    # The core publishes this one immutable outside-R binding
                    # during common start. No update/delete/overwrite is legal.
                    require(flags & os.O_EXCL and flags & os.O_NOFOLLOW and flags & os.O_CREAT, "invalid_path")
                    path_checked(p, new=True)
                else:
                    self.write_path(p)
        if event == "sqlite3.connect":
            value = str(args[0])
            if value.startswith("file:"):
                from urllib.parse import unquote, urlsplit
                value = unquote(urlsplit(value).path)
            self.write_path(value)
        if event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.truncate", "os.utime"}:
            self.write_path(args[0])
        if event in {"os.rename", "os.link", "os.symlink"}:
            self.write_path(args[0])
            self.write_path(args[1])


def setup_execution(root, checked, credentials, carriers, registry, *, controls=None):
    preserved = {k: os.environ[k] for k in ("LANG", "LC_ALL", "LC_CTYPE") if k in os.environ}
    # Identity must stay untouched even transiently; clear/update would unset
    # HOME before restoring it and violate the inherited process boundary.
    for key in tuple(os.environ):
        if key not in IDENTITY:
            del os.environ[key]
    os.environ.update({**preserved, **controlled_environment(root, checked), **(controls or {}), **credentials, **carriers})
    os.environ[PROFILES[checked["model"]["provider"]][1]] = credentials["LLM_API_KEY"]
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(root / "tmp")
    os.chdir(root / "deer-flow")
    install_imports(checked)
    binding = json.loads(carriers["DRF_RUN_SPENDING_BINDING"])
    sys.addaudithook(RuntimeGuard(checked, registry,
                                binding["authorization_id"] if binding["participant_id"] == "parent" else None))
    if binding["participant_id"] == "parent":
        from app.config import Config
        model = checked["model"]
        require(Config.LLM_PROVIDER == model["provider"] and Config.LLM_BASE_URL == model["endpoint"]
                and Config.LLM_MODEL_NAME == model["name"] and Config.LLM_FAST_MODEL == model["name"]
                and Config.LLM_STRONG_MODEL == model["name"] and Config.DEERFLOW_MODEL == model["alias"]
                and Config.LLM_TIERED_ROUTING is False, "unsafe_environment")
        for name in ("UPLOAD_FOLDER", "PIPELINE_DATA_DIR", "OASIS_SIMULATION_DATA_DIR", "DEERFLOW_DIR"):
            original = Path(getattr(Config, name))
            require(original.is_absolute() and original.resolve().is_relative_to(root)
                    and not any(p.is_symlink() for p in (original, *original.parents)), "invalid_path")
            # Config uses app/../uploads defaults. Canonicalize the trusted
            # producer before managers cache paths; emitted argv stays intact.
            setattr(Config, name, str(original.resolve()))


def wait_pipeline(core, binding, request):
    """Common start binds; retain exclusive ownership until its thread is gone."""
    from app.services.pipeline_orchestrator import PipelineOrchestrator, PipelineManager
    state = PipelineOrchestrator.start(**request)
    current = core.current_binding()
    require(current and current["pipeline_id"] == state.pipeline_id, "invalid_binding")
    worker = PipelineOrchestrator._threads.get(state.pipeline_id)
    try:
        if worker is not None:
            worker.join()  # terminal state can precede finally/participant cleanup
        while state.pipeline_id in PipelineOrchestrator._threads:
            time.sleep(0.05)
    except BaseException as interrupted:
        # A user interrupt must never drop ownership while a daemon worker or
        # owned research child is still running. Typed lifecycle cancellation
        # latches first; finally/participant exit remains under this lock.
        try:
            core.halt(current, "halted_cancelled")
        except BaseException:
            # A missing/corrupt ledger already forbids further admission. It
            # must not prevent stopping the processes this parent owns.
            interrupted.add_note("durable_halt_failed")
        try:
            PipelineOrchestrator.cancel(state.pipeline_id)
        except BaseException:
            interrupted.add_note("owned_cancellation_failed")
        finally:
            if worker is not None:
                worker.join()
            while state.pipeline_id in PipelineOrchestrator._threads:
                time.sleep(0.05)
        raise
    saved = PipelineManager.load(state.pipeline_id)
    require(saved and saved["status"] in {"completed", "failed", "cancelled"}, "pipeline_failed")
    result = core.summary(current)
    require(saved["status"] != "completed" or result["state"] == "closed", "invalid_binding")
    return result


def run(root, authorization, registry, credentials_path):
    reject_ambient(os.environ)
    checked = verify(root)
    root = Path(checked["runtime"]["root"])
    require(Path(__file__).resolve() == root / LAUNCHER
            and digest(read_bytes(root / LAUNCHER)) == checked["source_files"][LAUNCHER], "source_drift")
    require(Path(sys.executable).resolve() == Path(checked["runtime"]["python"]), "source_drift")
    registry = path_checked(registry, directory=True, private=True)
    require(not registry.is_relative_to(root) and not root.is_relative_to(registry), "invalid_path")
    require(not (root / "spend/authorization.json").exists() and not (root / "spend/binding.json").exists()
            and not (root / "spend/run.sqlite3").exists(), "missing_ledger")
    core = load_core(root)
    manifest = qualify_manifest(core, checked, read_json(path_checked(authorization, private=True)))
    credentials = read_json(path_checked(credentials_path, private=True))
    check_credentials(credentials, manifest)
    write_new(root / "spend/authorization.json", canonical(manifest))
    binding = core.create_authorization(root / "spend/authorization.json", registry_dir=registry)
    write_new(root / "spend/binding.json", canonical(binding))
    with core.run_lock(binding):
        carriers = core.export_environment(binding)
        setup_execution(root, checked, credentials, carriers, registry)
        core.activate_binding(binding)
        result = wait_pipeline(core, binding, checked["request"])
        write_new(root / "spend/result.json", canonical(result))
        return result


def parse_child_arguments(args):
    allowed = {"--prompt-file", "--out-dir", "--model", "--depth", "--forecast-authority", "--target-language", "--thread-id"}
    switches, values = set(), {}
    index = 0
    while index < len(args):
        key = args[index]
        require(key not in values and key not in switches, "invalid_request")
        if key in {"--subagents", "--resume"}:
            switches.add(key)
            index += 1
            continue
        require(key in allowed and index + 1 < len(args), "invalid_request")
        value = args[index + 1]
        require(isinstance(value, str) and value and not value.startswith("--"), "invalid_request")
        values[key] = value
        index += 2
    return values, switches


def child_argv(root, checked, args):
    require(args and args[0] == "--", "invalid_request")
    args = args[1:]
    require(args and args[0] == str(root / CHILD), "invalid_request")
    values, _ = parse_child_arguments(args[1:])
    require({"--prompt-file", "--out-dir", "--model", "--depth", "--forecast-authority"} <= values.keys(), "invalid_request")
    for key in ("--prompt-file", "--out-dir"):
        p = path_checked(values[key], directory=key == "--out-dir")
        require(p.is_relative_to(root / "app/backend/uploads"), "invalid_path")
    require(values["--model"] == checked["request"]["model"] and values["--depth"] == checked["request"]["depth"]
            and values["--forecast-authority"] == "target-first-v1", "invalid_request")
    require(values.get("--target-language", "") == checked["request"]["language"], "invalid_request")
    # A valid location does not authorize a different question. Do not strip,
    # replace invalid UTF-8, normalize Unicode, or rewrite a rejected file.
    approved = checked["request"]["prompt"]
    prompt_path = Path(values["--prompt-file"])
    require(prompt_path.stat().st_size == len(approved.encode("utf-8")), "invalid_request")
    try:
        prompt = read_bytes(prompt_path).decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise LauncherStop("invalid_request") from None
    require(prompt == approved, "invalid_request")
    return args


def require_fresh_child(argv):
    values, switches = parse_child_arguments(argv[1:])
    work = Path(values["--out-dir"]) / "v3"
    # Target-v3 reuses this state even without --resume. The current producer
    # supplies no reviewed v3 checkpoint carrier; legacy checkpoint IDs are
    # not substitute authority. No child may silently resume it in this slice.
    require("--resume" not in switches and not work.exists() and not work.is_symlink(), "resume_denied")


def child(args):
    require(os.environ.get(CARRIERS[0]) == "1" and all(os.environ.get(k) for k in CARRIERS), "invalid_binding")
    binding = json.loads(os.environ[CARRIERS[1]])
    require(type(binding) is dict and binding.get("participant_id") != "parent", "invalid_binding")
    root = path_checked(binding.get("root"), directory=True, private=True)
    checked = verify(root)
    require(Path(__file__).resolve() == root / LAUNCHER
            and Path(sys.executable).resolve() == Path(checked["runtime"]["python"]), "source_drift")
    require(os.environ[CARRIERS[2]] == checked["source_files"][CORE], "source_drift")
    argv = child_argv(root, checked, args)
    require_fresh_child(argv)
    reject_ambient(os.environ, child=True, model=checked["model"])
    core = load_core(root, child=True)
    manifest = qualify_manifest(core, checked, read_json(root / "spend/authorization.json"))
    credentials = {k: os.environ.get(k) for k in ("LLM_API_KEY", "FIRECRAWL_API_KEY")}
    check_credentials(credentials, manifest)
    bound = core.binding_from_environment()  # existing ledger + spawn-bound operation
    require(bound == binding, "invalid_binding")
    is_v2 = checked["runtime"]["schema"] == SCHEMA_V2
    if is_v2:
        core.activate_binding(bound)
        core.check_context()
        preflight_bound_runtime(core, bound, checked)
    carriers = {k: os.environ[k] for k in CARRIERS}
    controls = child_controls(os.environ, root, checked, bound, argv)
    setup_execution(root, checked, credentials, carriers, binding["registry_dir"], controls=controls)
    if not is_v2:
        core.activate_binding(bound)  # claims registered participant before model factory
    core.check_context()
    sys.argv = argv
    runpy.run_path(argv[0], run_name="__main__")


def main(argv=None):
    require(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode, "isolated_python_required")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "_child":
        child(argv[1:])
        return 0
    parser = PrivateParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    for name in ("source", "deerflow-source", "root", "spec"):
        prep.add_argument("--" + name, required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--root", required=True)
    run_parser = commands.add_parser("run")
    for name in ("root", "authorization", "registry", "credentials"):
        run_parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        checked = prepare(args.source, args.deerflow_source, args.root, args.spec)
        print(json.dumps({"status": "prepared_without_authorization", "source_files": checked["source_files"]}, sort_keys=True))
    elif args.command == "verify":
        checked = verify(args.root)
        root = Path(args.root)
        if (root / "spend/authorization.json").exists() or (root / "spend/binding.json").exists():
            require((root / "spend/run.sqlite3").is_file(), "missing_ledger")
            core = load_core(root)
            qualify_manifest(core, checked, read_json(root / "spend/authorization.json"))
            core.open_existing(read_json(root / "spend/binding.json"))
        print(json.dumps({"status": "verified", "source_files": checked["source_files"]}, sort_keys=True))
    else:
        result = run(args.root, args.authorization, args.registry, args.credentials)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["state"] == "closed" else 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Neither third-party errors nor raw exception arguments are printable.
        print(json.dumps({"status": "refused", "code": error.code if isinstance(error, LauncherStop) else "launcher_failed"}), file=sys.stderr)
        raise SystemExit(2) from None
