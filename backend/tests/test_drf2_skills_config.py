"""DRF-2 scaffold offline tests: skills / config / extensions / market tool.

验证 drf2/（REDESIGN.md 的新系统脚手架）中「技能 + 配置」子树的正确性：

1. drf2/skills/**/SKILL.md 用 **真实的** deer-flow 2.0 解析器/校验器
   （sys.modules 手术式注入，绕过 deerflow.skills.__init__ 对 langchain 的重依赖；
   deer-flow-2.0.0 源码树缺失或依赖不可用时干净地 skip）。
2. drf2/config/config.yaml：YAML 合法、必备块齐全、$ENV 占位符、子代理与技能/
   工具白名单互相一致（漂移守卫）。
3. drf2/config/extensions_config.json：两台引擎的 stdio 注册 + 7 技能启用。
4. drf2/config/market_tools.py：Polymarket 快照纯逻辑（过滤/去重/排序/每事件封顶/降级），
   全程 mock fetch，离线可跑。
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
import subprocess
import sys
import types as pytypes
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DRF2 = REPO_ROOT / "drf2"
SKILLS_ROOT = DRF2 / "skills"
CONFIG_YAML = DRF2 / "config" / "config.yaml"
EXTENSIONS_JSON = DRF2 / "config" / "extensions_config.json"
HARNESS_ROOT = REPO_ROOT / "deer-flow-2.0.0" / "backend" / "packages" / "harness" / "deerflow"

EXPECTED_SKILLS = {
    "deep-research",
    "actor-ontology-research",
    "ontology-generation",
    "kg-construction",
    "simulation-design",
    "forecast-report",
    "prediction-markets",
}

def _resolve_skills_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()

# 引擎 MCP 工具名（与 drf2/engines/*/server.py 实际注册的名字一致；技能 allowed-tools /
# 子代理 tools 白名单都据此校验。TestEngineToolNameDrift 再把这两个集合与引擎源码
# 提取出的真名对表 —— 引擎改名会先让测试红，再同步技能与配置）。
KG_MCP_TOOLS = {
    "kg_add_episode", "kg_search", "kg_get_entities", "kg_get_edges",
    "kg_causal_paths", "kg_n_hop_subgraph", "kg_trace_cascade", "kg_centrality_priors",
}
SIM_MCP_TOOLS = {"sim_start", "sim_status", "sim_results", "sim_stop", "sim_interview_agents"}
HARNESS_BUILTIN_TOOLS = {"tool_search"}  # tool_search.enabled=true 时由 harness 注入

# ---------------------------------------------------------------------------
# INT-3 跨树技能漂移守卫。同一份 SKILL.md 方法论有**三处副本**，各自的角色不同：
#   deerflow_bridge/skills/<name>/          —— 源（Wave-1-3 的方法论升级都落在这里）
#   deer-flow/skills/public/<name>/         —— authoritative atomic mirror 的运行副本
#   drf2/skills/custom/<name>/              —— DRF-2 新脚手架里的副本
# 两个不变式需要长期守卫：
#   (1) bridge↔drf2 共享方法论不能悄悄结构性分叉；
#   (2) bridge→deer-flow 部署必须逐字节一致（manifest mirror + gate 的直接结果）。
# ---------------------------------------------------------------------------
BRIDGE_SKILLS_ROOT = REPO_ROOT / "deerflow_bridge" / "skills"
DEERFLOW_PUBLIC_ROOT = REPO_ROOT / "deer-flow" / "skills" / "public"
RUNTIME_SKILL_SYNC_HELPER = REPO_ROOT / "deerflow_bridge" / "runtime_skill_sync.py"

# bridge 已吸收 Wave-1-3 升级（深度档位、市场自取、prediction-markets 口径重构），所以
# bridge 与 drf2 的正文已**合法分叉** —— 逐行 body-diff 会长期误报。改为守一个更弱但仍
# 有用的**结构不变式**：drf2 副本里出现的每个小节标题（归一化后）都必须在 bridge 副本里
# 存在，从而在任一方未来**新增/删除/改名共享方法论小节**时先变红提示复核。
# 已知的合法「drf2 独有」小节在下方 warn-list 放行：
#   - actor-ontology：bridge 把「硬性演员上限」并进了 §2.3 正文，而 drf2 把它拆成了独立的
#     §2.4 子节 —— 这是有意的结构差异，不是漂移。
#   - deep-research：bridge 副本已重构为「精简核心 + references/ 懒加载」形态（/deep-research
#     每个独立 pass 都会激活，压缩常驻正文省 token），详细 tradecraft 移入
#     references/source-tradecraft.md 与 references/final-dossier-contract.md，并已逐字节部署到
#     deer-flow/skills/public/。drf2 副本保留完整长文结构（脚手架单次加载，无重复激活成本），
#     故其 §1-§13 编号小节在 bridge 侧不再以标题形式存在 —— 有意分叉，非漂移。
# 除此之外任何**新**的 drf2 独有标题都不在白名单里，会让守卫变红。
KNOWN_DRF2_ONLY_HEADINGS = {
    "actor-ontology-research": {"2.4 the hard cast cap"},
    "deep-research": {
        "deep research skill",
        "1. mission & operating principles",
        "2. phase 0",
        "3. search craft",
        "3.1 operator toolkit",
        "3.2 document-type targeting",
        "3.3 pivots when results are thin",
        "4. source quality framework",
        "4.1 tiers",
        "4.2 domain map",
        "4.3 eight signal checks",
        '4.4 evaluating an "expert"',
        "5. the evidence ledger",
        "6. verification tradecraft",
        "7. adversarial analysis",
        "8. forecast-oriented research",
        "9. temporal awareness",
        "10. budget & efficiency discipline",
        "10.5 obstacle playbook",
        "11. synthesis gate",
        "12. output contract",
        "13. failure modes",
    },
}

_HEADING_RE = re.compile(r"^#{1,6}\s")


def _normalize_heading(line: str) -> str:
    """把一行 Markdown 标题归一化到「稳定核」：去掉 #、截断括注/破折号之后的描述性尾巴、
    小写、压缩空白。小节编号（`1.` / `2.3` / …）本身承担同一性，因此截掉描述尾巴既能吸收
    「§2 Query craft (full-text search likes short phrases)」↔「§2 Query craft (match how
    markets are titled)」这类合法措辞分叉，又不会把不同编号的小节误合并成一个。"""
    text = re.sub(r"^#+\s*", "", line.strip())
    text = re.split(r"\(|—|--", text, maxsplit=1)[0]
    text = text.strip().lower().rstrip(".:—- ")
    return re.sub(r"\s+", " ", text)


def _skill_headings(skill_md: Path) -> list[str]:
    return [_normalize_heading(ln)
            for ln in skill_md.read_text(encoding="utf-8").splitlines()
            if _HEADING_RE.match(ln)]


def _bridge_skill_names() -> set[str]:
    if not BRIDGE_SKILLS_ROOT.is_dir():
        return set()
    return {p.parent.name for p in BRIDGE_SKILLS_ROOT.glob("*/SKILL.md")}


def _drf2_custom_skill_names() -> set[str]:
    custom = SKILLS_ROOT / "custom"
    if not custom.is_dir():
        return set()
    return {p.parent.name for p in custom.glob("*/SKILL.md")}


def _git_tracked_bridge_skill_files() -> list[Path] | None:
    """Return every tracked file in a bridge skill bundle.

    并发工作树里，兄弟 subagent 常有尚未提交的在途新技能（git `??` 状态），此时 orchestrator
    的 glob 同步 / gate 还没把它部署到 deer-flow/。对这类在途技能做「必须已部署」的硬断言会
    误报。因此「存在性 + 逐字节」强不变式只锚定**已提交基线**（gate 真正负责同步的集合），
    在途技能改由更宽的漂移网（部署副本≠源即红）覆盖 —— 既不误报，又不漏掉真实内容漂移。"""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", "deerflow_bridge/skills"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    files = [
        rel for rel in out.stdout.split("\0")
        if rel.strip()
        and "/__pycache__/" not in rel
        and not rel.endswith((".pyc", ".pyo", "/.DS_Store"))
    ]
    return sorted(REPO_ROOT / rel for rel in files)


def _dirty_bridge_skill_files() -> set[Path]:
    """工作树里有未提交改动（modified/untracked/renamed）的 bridge 技能文件。

    并发会话会在 orchestrator 下一次 pre-launch 同步之前编辑源技能：这个瞬时窗口内
    deployed 副本**合法地**滞后于源，对 dirty 文件做逐字节断言必然误报（与在途新增
    技能「尚未部署」同属瞬时状态）。clean（已提交且未改动）文件不受影响 —— CI 的
    干净 checkout 里该集合为空，两层守卫保持全强度。"""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "-z", "--", "deerflow_bridge/skills"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode != 0:
        return set()
    dirty: set[Path] = set()
    tokens = out.stdout.split("\0")
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        dirty.add(REPO_ROOT / path)
        # rename/copy 记录额外携带一个 NUL 分隔的旧路径字段，一并视为 dirty
        if status[0] in ("R", "C") and index < len(tokens) and tokens[index]:
            dirty.add(REPO_ROOT / tokens[index])
            index += 1
    return dirty


def _skill_dirs() -> list[Path]:
    if not SKILLS_ROOT.is_dir():
        return []
    return sorted(p.parent for p in SKILLS_ROOT.glob("**/SKILL.md"))


# ---------------------------------------------------------------------------
# 真实 deer-flow 2.0 模块的手术式导入。
# deerflow.skills.__init__ / deerflow.models 会连锁 import langchain（backend venv
# 没有），因此预注册带 __path__ 的空壳包对象、只加载需要的叶子模块，模块级测试
# 结束后清掉全部 deerflow* 注入，绝不污染其余 584 项测试。
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def deerflow_shell():
    if not (HARNESS_ROOT / "skills" / "parser.py").is_file():
        pytest.skip("deer-flow-2.0.0 vendored source not present — cannot import the real modules")
    if "deerflow" in sys.modules:  # 环境里已有真 deerflow（不太可能）→ 直接用
        yield
        return
    for name, path in (("deerflow", HARNESS_ROOT),
                       ("deerflow.skills", HARNESS_ROOT / "skills"),
                       ("deerflow.config", HARNESS_ROOT / "config")):
        shell = pytypes.ModuleType(name)
        shell.__path__ = [str(path)]
        sys.modules[name] = shell
    try:
        yield
    finally:
        for name in [n for n in sys.modules if n == "deerflow" or n.startswith("deerflow.")]:
            sys.modules.pop(name, None)


@pytest.fixture(scope="module")
def deerflow_skill_modules(deerflow_shell):
    try:
        parser = importlib.import_module("deerflow.skills.parser")
        validation = importlib.import_module("deerflow.skills.validation")
        skill_types = importlib.import_module("deerflow.skills.types")
    except ImportError as exc:  # 依赖缺失 → skip 而非 fail
        pytest.skip(f"real deer-flow parser unimportable in this venv: {exc}")
    return parser, validation, skill_types


@pytest.fixture(scope="module")
def deerflow_config_modules(deerflow_shell):
    try:
        app_config = importlib.import_module("deerflow.config.app_config")
        extensions_config = importlib.import_module("deerflow.config.extensions_config")
    except ImportError as exc:  # pydantic/dotenv 等缺失 → skip 而非 fail
        pytest.skip(f"real deer-flow config schema unimportable in this venv: {exc}")
    return app_config, extensions_config


class TestSkillsParseWithRealParser:
    def test_seven_skills_present(self):
        names = {d.name for d in _skill_dirs()}
        assert names == EXPECTED_SKILLS, f"skill dirs mismatch: {names ^ EXPECTED_SKILLS}"

    def test_every_skill_passes_real_validator(self, deerflow_skill_modules):
        _, validation, _ = deerflow_skill_modules
        for skill_dir in _skill_dirs():
            ok, message, name = validation._validate_skill_frontmatter(skill_dir)
            assert ok, f"{skill_dir.name}: {message}"
            assert name == skill_dir.name, (
                f"frontmatter name {name!r} must equal directory name {skill_dir.name!r}")

    def test_every_skill_parses_with_real_parser(self, deerflow_skill_modules):
        parser, _, skill_types = deerflow_skill_modules
        for skill_dir in _skill_dirs():
            skill = parser.parse_skill_file(
                skill_dir / "SKILL.md", skill_types.SkillCategory.CUSTOM)
            assert skill is not None, f"{skill_dir.name}: parse_skill_file returned None"
            assert skill.name == skill_dir.name
            assert skill.description.strip()
            # allowed-tools 是本管线的强制约束：每个技能都要显式声明工具面
            assert skill.allowed_tools, f"{skill_dir.name}: allowed-tools missing/empty"

    def test_skills_live_under_custom_category(self):
        # harness loader 只扫 <skills.path>/{public,custom}/ —— 布局守卫
        for skill_dir in _skill_dirs():
            rel = skill_dir.relative_to(SKILLS_ROOT)
            assert rel.parts[0] == "custom", (
                f"{skill_dir.name} must live under drf2/skills/custom/ (got {rel})")

    def test_allowed_tools_reference_known_tools(self, deerflow_skill_modules):
        parser, _, skill_types = deerflow_skill_modules
        cfg = yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8"))
        config_tools = {t["name"] for t in cfg.get("tools", [])}
        known = config_tools | KG_MCP_TOOLS | SIM_MCP_TOOLS | HARNESS_BUILTIN_TOOLS
        for skill_dir in _skill_dirs():
            skill = parser.parse_skill_file(
                skill_dir / "SKILL.md", skill_types.SkillCategory.CUSTOM)
            unknown = set(skill.allowed_tools or []) - known
            assert not unknown, f"{skill_dir.name}: unknown allowed-tools {sorted(unknown)}"


class TestConfigYaml:
    @pytest.fixture(scope="class")
    def cfg(self):
        assert CONFIG_YAML.is_file(), "drf2/config/config.yaml missing"
        return yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8"))

    def test_required_blocks(self, cfg):
        for key in ("config_version", "models", "tools", "tool_groups",
                    "tool_search", "sandbox", "subagents", "skills", "database"):
            assert key in cfg, f"config.yaml missing required block {key!r}"
        assert isinstance(cfg["config_version"], int) and cfg["config_version"] >= 14

    def test_models_claude_and_minimax(self, cfg):
        by_name = {m["name"]: m for m in cfg["models"]}
        assert "claude-sonnet" in by_name and "minimax-m3" in by_name
        claude = by_name["claude-sonnet"]
        assert claude["use"] == "deerflow.models.claude_provider:ClaudeChatModel"
        mm = by_name["minimax-m3"]
        assert mm["use"] == "deerflow.models.patched_minimax:PatchedChatMiniMax"
        assert mm["model"] == "MiniMax-M3"
        # $ENV 占位符（绝不硬编码 key）
        assert mm["api_key"] == "$MINIMAX_API_KEY"
        assert "api_key" not in claude or str(claude.get("api_key", "")).startswith("$")
        # MiniMax 契约：temperature ∈ (0.0, 1.0]
        assert 0.0 < float(mm["temperature"]) <= 1.0
        # thinking 预算须小于 max_tokens（Anthropic API 硬约束）
        budget = claude["when_thinking_enabled"]["thinking"]["budget_tokens"]
        assert 1024 <= int(budget) < int(claude["max_tokens"])

    def test_no_hardcoded_secrets(self):
        text = CONFIG_YAML.read_text(encoding="utf-8")
        for marker in ("sk-", "xoxb-", "tp-", "AKIA"):
            for line in text.splitlines():
                if "api_key" in line.lower() and marker in line:
                    pytest.fail(f"possible hardcoded secret in config.yaml: {line.strip()}")

    def test_custom_agents_wiring(self, cfg):
        agents = cfg["subagents"]["custom_agents"]
        assert set(agents) == {"researcher", "ontology-builder", "sim-configurer", "forecaster"}
        # 每阶段模型路由 + 提升的超时（REDESIGN：research/forecast 2700，sim-config 900）
        assert agents["researcher"]["model"] == "claude-sonnet"
        assert agents["forecaster"]["model"] == "claude-sonnet"
        assert agents["ontology-builder"]["model"] == "minimax-m3"
        assert agents["sim-configurer"]["model"] == "minimax-m3"
        assert agents["researcher"]["timeout_seconds"] == 2700
        assert agents["forecaster"]["timeout_seconds"] == 2700
        assert agents["sim-configurer"]["timeout_seconds"] == 900
        model_names = {m["name"] for m in cfg["models"]}
        for name, agent in agents.items():
            assert agent["description"].strip() and agent["system_prompt"].strip()
            assert agent["model"] in model_names, f"{name}: unknown model {agent['model']}"

    def test_agent_skill_whitelists_reference_real_skills(self, cfg):
        skill_names = {d.name for d in _skill_dirs()}
        for name, agent in cfg["subagents"]["custom_agents"].items():
            skills = agent.get("skills")
            assert skills, f"{name}: skills whitelist must be non-empty"
            missing = set(skills) - skill_names
            assert not missing, f"{name}: whitelisted skills not on disk: {sorted(missing)}"

    def test_agent_tool_whitelists_reference_known_tools(self, cfg):
        config_tools = {t["name"] for t in cfg["tools"]}
        known = config_tools | KG_MCP_TOOLS | SIM_MCP_TOOLS | HARNESS_BUILTIN_TOOLS
        for name, agent in cfg["subagents"]["custom_agents"].items():
            unknown = set(agent.get("tools") or []) - known
            assert not unknown, f"{name}: unknown tools {sorted(unknown)}"

    def test_prediction_market_tool_registered(self, cfg):
        tools = {t["name"]: t for t in cfg["tools"]}
        assert "prediction_market_search" in tools
        assert tools["prediction_market_search"]["use"] == (
            "drf2.config.market_tools:prediction_market_search_tool")

    def test_skills_path_points_at_drf2_skills(self, cfg):
        path = _resolve_skills_path(cfg["skills"]["path"])
        assert path == SKILLS_ROOT.resolve(), f"skills.path {path} != {SKILLS_ROOT.resolve()}"
        # loader 扫 {public,custom} —— custom 必须存在且非空
        assert (path / "custom").is_dir() and any((path / "custom").iterdir())

    def test_tool_search_enabled_for_deferred_mcp(self, cfg):
        assert cfg["tool_search"]["enabled"] is True


class TestRealSchemaValidation:
    """用 harness 自己的 pydantic 模型整体校验两份配置（最强的 schema 契约测试）。"""

    def test_config_yaml_loads_via_real_appconfig(self, deerflow_config_modules):
        app_config, _ = deerflow_config_modules
        cfg = app_config.AppConfig.from_file(str(CONFIG_YAML))
        assert [m.name for m in cfg.models] == ["claude-sonnet", "minimax-m3"]
        assert set(cfg.subagents.custom_agents) == {
            "researcher", "ontology-builder", "sim-configurer", "forecaster"}
        assert cfg.subagents.custom_agents["researcher"].timeout_seconds == 2700
        assert cfg.subagents.custom_agents["sim-configurer"].timeout_seconds == 900
        assert cfg.tool_search.enabled is True
        assert _resolve_skills_path(cfg.skills.path) == SKILLS_ROOT.resolve()

    def test_extensions_json_loads_via_real_schema(self, deerflow_config_modules):
        _, extensions_config = deerflow_config_modules
        ext = extensions_config.ExtensionsConfig.from_file(str(EXTENSIONS_JSON))
        enabled = ext.get_enabled_mcp_servers()
        assert set(enabled) == {"drf2-kg", "drf2-simulation"}
        for server in enabled.values():
            assert server.type == "stdio"
        for name in EXPECTED_SKILLS:
            assert ext.is_skill_enabled(name, "custom"), f"skill {name} not enabled"


class TestExtensionsConfig:
    @pytest.fixture(scope="class")
    def ext(self):
        assert EXTENSIONS_JSON.is_file(), "drf2/config/extensions_config.json missing"
        return json.loads(EXTENSIONS_JSON.read_text(encoding="utf-8"))

    def test_two_engine_servers_registered(self, ext):
        servers = ext["mcpServers"]
        assert set(servers) == {"drf2-kg", "drf2-simulation"}
        for name, server in servers.items():
            assert server["enabled"] is True
            assert server["type"] == "stdio"
            assert server["command"], f"{name}: empty command"
            assert server["args"][0] == "-m", f"{name}: expected python -m entrypoint"
            # $ENV 占位符注入（不落明文 key）
            for key, value in server.get("env", {}).items():
                if key.endswith("_KEY"):
                    assert str(value).startswith("$"), f"{name}: {key} must be $ENV placeholder"
        assert servers["drf2-kg"]["args"][1] == "drf2.engines.kg.server"
        assert servers["drf2-simulation"]["args"][1] == "drf2.engines.simulation.server"

    def test_engine_entry_modules_exist(self, ext):
        # extensions_config 引用的 python -m 入口必须真实存在于 drf2/engines/
        for server in ext["mcpServers"].values():
            module = server["args"][1]
            path = REPO_ROOT / (module.replace(".", "/") + ".py")
            assert path.is_file(), f"entry module {module} not found at {path}"

    def test_all_seven_skills_enabled(self, ext):
        skills = ext["skills"]
        assert set(skills) == EXPECTED_SKILLS
        assert all(entry.get("enabled") is True for entry in skills.values())


class TestEngineToolNameDrift:
    """把测试内的工具名集合与引擎源码里实际注册的名字对表（漂移守卫）。"""

    def test_kg_tool_names_match_engine_source(self):
        src = REPO_ROOT / "drf2" / "engines" / "kg" / "server.py"
        if not src.is_file():
            pytest.skip("KG engine source not present yet")
        # server.py 的工具注册表以裸字符串常量声明工具名（整串恰为 kg_xxx）
        extracted = set(re.findall(r'"(kg_[a-z_]+)"', src.read_text(encoding="utf-8")))
        assert extracted == KG_MCP_TOOLS, (
            f"KG engine tool names drifted: engine={sorted(extracted)} "
            f"tests/config/skills expect={sorted(KG_MCP_TOOLS)}")

    def test_sim_tool_names_match_engine_source(self):
        src = REPO_ROOT / "drf2" / "engines" / "simulation" / "server.py"
        if not src.is_file():
            pytest.skip("simulation engine source not present yet")
        extracted = set(re.findall(r"async def (sim_[a-z_]+)\(",
                                   src.read_text(encoding="utf-8")))
        assert extracted == SIM_MCP_TOOLS, (
            f"simulation engine tool names drifted: engine={sorted(extracted)} "
            f"tests/config/skills expect={sorted(SIM_MCP_TOOLS)}")


# ---------------------------------------------------------------------------
# market_tools 纯逻辑（无网络、无 langchain 依赖）
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def market_tools():
    spec = importlib.util.spec_from_file_location(
        "drf2_market_tools_under_test", DRF2 / "config" / "market_tools.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _raw_market(**over):
    """一条 Polymarket /public-search 里嵌套的 market 行（字符串价，镜像真实 API）。"""
    base = {
        "id": "m1", "question": "Will X happen by 2027?",
        "closed": False, "outcomes": '["Yes","No"]', "outcomePrices": '["0.2100","0.7900"]',
        "volume": "1000", "liquidity": "50", "groupItemTitle": "",
    }
    base.update(over)
    return base


def _event(markets, title="X"):
    return {"title": title, "slug": "s", "markets": markets}


class TestMarketToolsLogic:
    def test_normalize_good_market(self, market_tools):
        norm = market_tools.normalize_market(_raw_market(), matched_query="x", event_title="X")
        assert norm == {
            "market_id": "m1", "exchange": "polymarket",
            "question": "Will X happen by 2027?", "implied_yes_prob": 0.21,
            "volume": 1000.0, "liquidity": 50.0, "event_title": "X",
            "matched_query": "x",
        }

    @pytest.mark.parametrize("over", [
        {"closed": True},                           # 已关闭
        {"outcomePrices": None},                    # 无价
        {"outcomePrices": '["1","0"]'},             # 价=1 定盘
        {"outcomePrices": '["0","1"]'},             # 价=0 定盘
        {"volume": "10"},                           # 低量（< 200）
        {"id": ""},                                 # 无 id
    ])
    def test_normalize_rejects_bad_markets(self, market_tools, over):
        assert market_tools.normalize_market(_raw_market(**over), matched_query="x") is None

    def test_snapshot_dedupes_sorts_and_limits(self, market_tools):
        def fetch(q, limit):
            if q == "tariff":
                return [_event([_raw_market(id="a", volume="500"),
                                _raw_market(id="b", volume="9000")])]
            return [_event([_raw_market(id="a", volume="500"),   # 跨 query 重复 → 去重
                            _raw_market(id="c", volume="3000")])]
        out = market_tools.snapshot_for_queries(["tariff", "chips"], fetch=fetch)
        assert [m["market_id"] for m in out] == ["b", "c", "a"]  # volume 降序
        assert out[2]["matched_query"] == "tariff"               # 首个命中的 query 保留
        capped = market_tools.snapshot_for_queries(["tariff", "chips"], fetch=fetch, max_total=2)
        assert [m["market_id"] for m in capped] == ["b", "c"]

    def test_snapshot_caps_per_event(self, market_tools):
        # 一个事件的 5 个高量子市场不得霸占全部名额；默认每事件≤3。
        def fetch(q, limit):
            ladder = [_raw_market(id=f"c{i}", volume=str(9000 - i)) for i in range(5)]
            return [_event(ladder, title="Ladder"),
                    _event([_raw_market(id="other", volume="100")], title="Other")]
        out = market_tools.snapshot_for_queries(["x"], fetch=fetch, min_volume=50)
        assert len([m for m in out if m["event_title"] == "Ladder"]) == 3
        assert any(m["event_title"] == "Other" for m in out)
        unlimited = market_tools.snapshot_for_queries(["x"], fetch=fetch, min_volume=50,
                                                      max_per_event=0)
        assert len([m for m in unlimited if m["event_title"] == "Ladder"]) == 5

    def test_snapshot_survives_query_failure(self, market_tools):
        def fetch(q, limit):
            if q == "boom":
                raise RuntimeError("network down")
            return [_event([_raw_market(id="ok")])]
        out = market_tools.snapshot_for_queries(["boom", "fine"], fetch=fetch)
        assert [m["market_id"] for m in out] == ["ok"]  # 单 query 失败不阻断整体

    def test_impl_uses_snapshot_keyless(self, market_tools, monkeypatch):
        # keyless：无需任何环境变量，直接走 snapshot。
        monkeypatch.setattr(
            market_tools, "snapshot_for_queries",
            lambda qlist, **kw: [{"market_id": "m9", "implied_yes_prob": 0.4}])
        payload = json.loads(market_tools.prediction_market_search_impl("tariff\nchips"))
        assert payload["queries"] == ["tariff", "chips"]
        assert payload["markets"][0]["market_id"] == "m9"
        assert "calibration anchors" in payload["note"]

    def test_impl_empty_markets_note(self, market_tools, monkeypatch):
        monkeypatch.setattr(market_tools, "snapshot_for_queries", lambda qlist, **kw: [])
        payload = json.loads(market_tools.prediction_market_search_impl("tariff, chips"))
        assert payload["markets"] == []
        assert "No active" in payload["note"]

    def test_impl_empty_queries(self, market_tools):
        payload = json.loads(market_tools.prediction_market_search_impl("  \n , "))
        assert payload["markets"] == [] and "no queries" in payload["note"]

    def test_module_importable_without_langchain(self, market_tools):
        # backend venv 无 langchain：模块必须仍可导入，tool 变量为 None（harness 环境才非 None）
        assert hasattr(market_tools, "prediction_market_search_tool")


# ---------------------------------------------------------------------------
# INT-3：三副本技能漂移守卫
# ---------------------------------------------------------------------------
class TestCrossTreeSkillStructureDrift:
    """bridge↔drf2 共享方法论的结构不变式（正文已合法分叉 → 守小节结构而非逐行 body）。"""

    def test_expected_shared_skills_present(self):
        # bridge 与 drf2/custom 都是入库源码：三个方法论技能必须三树同源，缺一即真实回归。
        common = _bridge_skill_names() & _drf2_custom_skill_names()
        if not common:
            pytest.skip("neither deerflow_bridge/skills nor drf2/skills/custom present")
        expected = {"deep-research", "actor-ontology-research", "prediction-markets"}
        missing = expected - common
        assert not missing, (
            f"shared methodology skills missing from a tree (bridge={sorted(_bridge_skill_names())}, "
            f"drf2={sorted(_drf2_custom_skill_names())}): {sorted(missing)}")

    def test_drf2_section_headings_subset_of_bridge(self):
        # 对 bridge∩drf2 的每个技能：drf2 副本的小节标题（归一化）须是 bridge 副本标题的子集，
        # KNOWN_DRF2_ONLY_HEADINGS 里已登记的合法分叉除外。任一方未来动了共享小节结构 → 变红。
        common = sorted(_bridge_skill_names() & _drf2_custom_skill_names())
        if not common:
            pytest.skip("no skill present in both deerflow_bridge/skills and drf2/skills/custom")
        for name in common:
            drf2_headings = _skill_headings(SKILLS_ROOT / "custom" / name / "SKILL.md")
            bridge_headings = set(_skill_headings(BRIDGE_SKILLS_ROOT / name / "SKILL.md"))
            allowed = bridge_headings | KNOWN_DRF2_ONLY_HEADINGS.get(name, set())
            missing = [h for h in drf2_headings if h and h not in allowed]
            assert not missing, (
                f"{name}: drf2/custom section heading(s) absent from the deerflow_bridge copy — "
                f"shared methodology drift: {missing}. If this divergence is intentional, register "
                f"it in KNOWN_DRF2_ONLY_HEADINGS with a rationale comment.")

    def test_known_drf2_only_headings_stay_relevant(self):
        # warn-list 卫生：登记项必须仍是「drf2 有、bridge 无」的真实分叉。若某项已被 bridge
        # 追平（两边都出现或 drf2 已删除），它就成了僵尸豁免，应从白名单移除 —— 此处强制变红。
        for name, headings in KNOWN_DRF2_ONLY_HEADINGS.items():
            drf2_md = SKILLS_ROOT / "custom" / name / "SKILL.md"
            bridge_md = BRIDGE_SKILLS_ROOT / name / "SKILL.md"
            if not (drf2_md.is_file() and bridge_md.is_file()):
                pytest.skip(f"{name}: one of the two skill copies is absent")
            drf2_set = set(_skill_headings(drf2_md))
            bridge_set = set(_skill_headings(bridge_md))
            for h in headings:
                assert h in drf2_set, (
                    f"{name}: warn-listed heading {h!r} no longer in drf2 copy — drop it from "
                    f"KNOWN_DRF2_ONLY_HEADINGS")
                assert h not in bridge_set, (
                    f"{name}: warn-listed heading {h!r} now ALSO in bridge copy — the divergence "
                    f"is resolved; drop it from KNOWN_DRF2_ONLY_HEADINGS")


class TestBridgeSkillsDeployedByteIdentical:
    """Every tracked skill body/resource must deploy byte-identically.

    This includes lazy references, renderer scripts, and future nested assets;
    checking only SKILL.md can leave an apparently healthy but unusable bundle.

    两层守卫：committed 基线走「存在性 + 逐字节」强断言（gate 负责同步的集合），全部已部署
    副本再走一层「内容不得与源分叉」的宽漂移网 —— 后者连并发在途、尚未纳入基线的技能也一并
    监控内容一致性，同时对「新增但尚未同步」这种瞬时状态不误报。"""

    def test_setup_uses_the_same_authoritative_sync_helper(self):
        setup = (REPO_ROOT / "setup.sh").read_text(encoding="utf-8")
        assert 'SKILL_SYNC_HELPER="$BRIDGE_DIR/runtime_skill_sync.py"' in setup
        assert '--source-root "$BRIDGE_DIR/skills"' in setup
        assert '--deployed-public-root "$DEERFLOW_DIR/skills/public"' in setup
        assert 'cp -R "$_skill_src/." "$_skill_dst/"' not in setup
        assert RUNTIME_SKILL_SYNC_HELPER.is_file()

    def test_committed_bridge_skills_deployed_byte_identical(self):
        # 已提交的 bridge 技能是 gate 负责的部署基线：必须存在于 deer-flow/public 且逐字节一致。
        if not DEERFLOW_PUBLIC_ROOT.is_dir():
            pytest.skip("deer-flow/skills/public absent (fresh checkout without the deployed tree)")
        tracked = _git_tracked_bridge_skill_files()
        if tracked is None:
            pytest.skip("git unavailable — cannot determine the committed bridge-skill baseline")
        if not tracked:
            pytest.skip("no git-tracked deerflow_bridge skill resources in this checkout")
        dirty = _dirty_bridge_skill_files()
        for src in tracked:
            if src in dirty:
                continue  # 在途未提交改动：deployed 合法滞后，待 orchestrator pre-launch 同步
            rel = src.relative_to(BRIDGE_SKILLS_ROOT)
            deployed = DEERFLOW_PUBLIC_ROOT / rel
            assert deployed.is_file(), (
                f"{rel}: committed bridge skill resource not deployed at "
                f"{deployed.relative_to(REPO_ROOT)} — orchestrator glob sync / gate did not run")
            src_bytes = src.read_bytes()
            deployed_bytes = deployed.read_bytes()
            assert src_bytes == deployed_bytes, (
                f"{rel}: deployed skill resource drifted from the deerflow_bridge source "
                f"(bridge={len(src_bytes)}B, deployed={len(deployed_bytes)}B) — "
                f"re-run the orchestrator skill sync to redeploy byte-identical")

    def test_deployed_copies_never_diverge_from_bridge_source(self):
        # 宽漂移网：任何**已部署**的技能（含尚未提交的在途新技能）其部署副本都不得与 bridge 源
        # 分叉。未部署的在途技能（同步尚未追平）跳过，不误报；已部署却内容漂移则立刻变红。
        if not DEERFLOW_PUBLIC_ROOT.is_dir():
            pytest.skip("deer-flow/skills/public absent (fresh checkout without the deployed tree)")
        bridge_skill_files = [
            path for path in sorted(BRIDGE_SKILLS_ROOT.rglob("*"))
            if path.is_file()
            and not any(part.startswith(".") or part == "__pycache__"
                        for part in path.relative_to(BRIDGE_SKILLS_ROOT).parts)
            and path.suffix not in {".pyc", ".pyo"}
            and (BRIDGE_SKILLS_ROOT / path.relative_to(BRIDGE_SKILLS_ROOT).parts[0]
                 / "SKILL.md").is_file()
        ]
        if not bridge_skill_files:
            pytest.skip("deerflow_bridge/skills has no SKILL.md")
        dirty = _dirty_bridge_skill_files()
        checked = 0
        for src in bridge_skill_files:
            if src in dirty:
                continue  # 在途未提交改动：deployed 合法滞后，待 orchestrator pre-launch 同步
            rel = src.relative_to(BRIDGE_SKILLS_ROOT)
            deployed = DEERFLOW_PUBLIC_ROOT / rel
            if not deployed.is_file():
                continue  # 在途新增、glob 同步尚未部署 —— 属瞬时状态，非内容漂移
            checked += 1
            src_bytes = src.read_bytes()
            deployed_bytes = deployed.read_bytes()
            assert src_bytes == deployed_bytes, (
                f"{rel}: deployed skill resource diverged from the deerflow_bridge source "
                f"(bridge={len(src_bytes)}B, deployed={len(deployed_bytes)}B) — "
                f"re-run the orchestrator skill sync to redeploy byte-identical")
        if checked == 0:
            pytest.skip("no bridge skill is currently deployed under deer-flow/skills/public")
