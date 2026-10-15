"""Research method skills: format contract, router, prompt blocks and engine wiring.

Contract: docs/handoff/research-skills/design.md.  The skills are the real folders under
deerflow_bridge/skills/; no provider or model call is made.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "deerflow_bridge"
sys.path.insert(0, str(BRIDGE))
import data_catalog  # noqa: E402
import research_skills as rs  # noqa: E402

SKILLS = BRIDGE / "skills"
CAPS = {"Activation": 900, "Plan": 1800, "Investigate": 2400, "Synthesize": 1500, "Gaps": 700}
SECTOR_KEYS = {
    "sectors-technology.md": ["semiconductors", "ai-compute-datacenters", "cloud-software", "telecom-networks",
                              "internet-platforms-media", "autos-ev", "energy-storage-batteries", "frontier-tech",
                              "aerospace-defense"],
    "sectors-economy.md": ["power-utilities", "renewables", "oil-gas", "mining-metals", "agriculture-food",
                           "biopharma", "healthcare-services-medtech", "banking-insurance",
                           "real-estate-construction", "consumer-retail", "industrials-machinery",
                           "transport-logistics"],
}
SECTOR_LABELS = ("Unit and segments", "Decisive metrics", "Supply and capacity", "Cycle and price signals",
                 "Forecast drivers", "Sources", "Traps")
ID_RE = re.compile(r"(?<![A-Za-z0-9_])((?:fred|bls|bis|imf|wb|usgov):[A-Za-z0-9_./#%-]+[A-Za-z0-9_])")


def _body_sections(text: str) -> tuple[list[str], dict[str, str]]:
    body = re.match(r"^---\n.*?\n---\n", text, re.S)
    rest = text[body.end():] if body else text
    order = re.findall(r"(?m)^## (.+?)\s*$", rest)
    parts = re.split(r"(?m)^## .+?\s*$", rest)
    return order, {heading: part.strip("\n") for heading, part in zip(order, parts[1:], strict=True)}


# ----------------------------------------------------------------------------- format contract

@pytest.mark.parametrize("name", rs.SKILL_NAMES)
def test_every_method_skill_follows_the_engine_contract(name):
    folder = SKILLS / name
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    assert len(text) <= 11000, len(text)
    front = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert front, "frontmatter"
    keys = re.findall(r"(?m)^([A-Za-z_-]+):", front.group(1))
    assert sorted(keys) == ["description", "name"]    # no allowed-tools: it would shrink subagent tools
    assert re.search(rf"(?m)^name:\s*{re.escape(name)}\s*$", front.group(1))
    skill = rs.parse_skill(name, text)
    assert skill is not None
    assert 40 <= len(skill.description) <= 1000 and "<" not in skill.description and ">" not in skill.description
    order, sections = _body_sections(text)
    assert order == list(rs.SECTIONS)
    for heading, cap in CAPS.items():
        assert 0 < len(sections[heading]) <= cap, (heading, len(sections[heading]))
    for heading in ("Plan", "Investigate", "Synthesize", "Gaps"):
        assert "$" not in sections[heading], heading                  # write USD, never a dollar sign
        assert not re.search(r"\[S\d+\]", sections[heading]), heading  # no fake citation markers
    assert not re.search(r"deep-research\s*§", text)
    for link in re.findall(r"\]\((references/[^)#]+)\)", text):
        assert (folder / link).is_file(), link


@pytest.mark.parametrize("name", rs.SKILL_NAMES)
def test_every_official_series_a_skill_names_is_in_the_catalog(name):
    folder = SKILLS / name
    files = [folder / "SKILL.md", *sorted((folder / "references").glob("*.md"))]
    missing = []
    for path in files:
        for identity in ID_RE.findall(path.read_text(encoding="utf-8")):
            if data_catalog.lookup(identity.split("#", 1)[0]) is None:
                missing.append(f"{path.name}: {identity}")
    assert missing == []


@pytest.mark.parametrize("name", rs.SKILL_NAMES)
def test_references_are_linked_and_small_enough_for_the_legacy_summarizer(name):
    folder = SKILLS / name
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    refs = sorted((folder / "references").glob("*.md"))
    assert refs, "at least one reference"
    for ref in refs:
        assert len(ref.read_text(encoding="utf-8")) <= 14000, ref.name
        if ref.name not in SECTOR_KEYS:
            assert f"references/{ref.name}" in text, ref.name


@pytest.mark.parametrize("filename", sorted(SECTOR_KEYS))
def test_sector_adapters_cover_every_sector_with_the_seven_labels(filename):
    text = (SKILLS / "industry-research" / "references" / filename).read_text(encoding="utf-8")
    blocks = rs.parse_sectors(text)
    assert list(blocks) == SECTOR_KEYS[filename]
    for key, block in blocks.items():
        assert len(block) <= rs.SECTOR_CAP, key
        assert all(f"**{label}**" in block for label in SECTOR_LABELS), key
        assert "$" not in block, key
    assert f"references/{filename}" in (SKILLS / "industry-research" / "SKILL.md").read_text(encoding="utf-8")


def test_router_sector_keys_match_the_adapter_files():
    assert set(rs._SECTOR_TERMS) == {key for keys in SECTOR_KEYS.values() for key in keys}


def test_the_library_loads_all_nine_skills_and_every_sector():
    library = rs.load_library({"RESEARCH_SKILLS_DIR": str(SKILLS)})
    assert library is not None and library.names == list(rs.SKILL_NAMES)
    assert set(library.sectors) == set(rs._SECTOR_TERMS)
    for name in rs.SKILL_NAMES:
        assert library.skills[name].mandate, name


# ----------------------------------------------------------------------------- router

ROUTES = [
    # Real prompts of earlier runs (abridged) and the live-eval questions.
    ("Forecast the development of quantum computing in the United States, China, and the European Union from "
     "2026 through 2040, and its impact on the economy.", "industry-forecasting", {"industry-research"}),
    ("Forecast the federal funds rate (upper bound of the target range) at year-end 2026. Include recent FOMC "
     "decisions and forward guidance.", "macro-research", set()),
    ("Forecast the future state of the US trading system by 2028: tariff policy trajectory, the effective US "
     "tariff rate and the fate of the IEEPA-based reciprocal tariffs.", "policy-and-trade-forecasting", set()),
    ("Forecast the outcome of the 2026 US midterm election: which party controls the House and Senate.",
     "election-forecasting", set()),
    ("How and when will the Russia–Ukraine war end? Research the front lines and territorial control.",
     "geopolitical-forecasting", set()),
    ("你作为全球云计算产业资深分析师，预判2028年全球云计算市场格局与头部厂商排名。", "industry-forecasting",
     {"competitive-landscape-forecasting"}),
    ("预测到2030年，哪家美国人工智能实验室或企业将成为美国AI领域竞争的主导者。", "competitive-landscape-forecasting",
     {"industry-forecasting"}),
    ("你担任资深投行 A 股权益分析师，预判 2026 年底前登陆 A 股、上市后总市值体量最高的 IPO 企业。",
     "financial-markets-forecasting", {"competitive-landscape-forecasting"}),
    ("分析 2030 年前全球半导体行业的发展走向，围绕设计、制造、封装测试等全产业链环节展开研究。",
     "industry-forecasting", {"industry-research"}),
    ("请对2035 年中国储能与电池市场做出深度、结构化预测与竞争格局研判。", "industry-forecasting",
     {"industry-research"}),
    ("请基于美伊双方核心战略诉求、军事实力对比，研判2026年美伊冲突走向。", "geopolitical-forecasting", set()),
    ("Will US CPI inflation fall below 2.5% year over year by December 2027, and how will the Federal Reserve "
     "policy rate evolve through 2027?", "macro-research", set()),
    ("How much will US data-center electricity consumption grow by 2030, and will grid and power-price "
     "constraints slow the AI data-center buildout?", "industry-forecasting", {"industry-research"}),
    ("2027年中国实际GDP增速会低于4%吗？请结合官方统计数据、IMF与世界银行预测进行研判。", "macro-research", set()),
    ("Will Brent crude average above 90 USD per barrel in 2027?", "financial-markets-forecasting", set()),
    # Who-leads questions lead with the landscape skill even when a sector noun and a year also route the
    # industry outlook ("lab", "cloud" and "quantum" are sector nouns, not industry questions).
    ("Which US AI lab will lead the frontier by 2030?", "competitive-landscape-forecasting",
     {"industry-forecasting"}),
    ("Which cloud provider will lead the cloud computing market by 2030?", "competitive-landscape-forecasting",
     {"industry-forecasting"}),
    ("2030年云计算市场的领导者是谁？", "competitive-landscape-forecasting", {"industry-forecasting"}),
    ("US China EU quantum computing race 2026-2040: who leads?", "competitive-landscape-forecasting",
     {"industry-forecasting"}),
    ("Forecast the HBM and memory market by 2028: market size, pricing, and which suppliers will lead HBM share.",
     "industry-forecasting", {"competitive-landscape-forecasting"}),
    # "Who will win" is an election (or war) question, not a ranking one.
    ("Who will win the 2028 US presidential election?", "election-forecasting", set()),
    ("Which party will win the Senate in 2026?", "election-forecasting", set()),
    ("2026年11月美国中期选举，共和党能否保住众议院多数？", "election-forecasting", set()),
    ("Will the Federal Reserve cut rates in December 2026?", "macro-research", set()),
    ("美联储2026年12月会降息吗？", "macro-research", set()),
    ("2027年居民消费价格指数同比涨幅会超过2%吗？", "macro-research", set()),
    ("Which countries will impose tariffs on Chinese EVs by 2027?", "policy-and-trade-forecasting",
     {"industry-forecasting"}),
    ("到2028年，美国IEEPA关税是否会被最高法院推翻？", "policy-and-trade-forecasting", set()),
    ("Will Russia have the military capacity for a new offensive in 2027?", "geopolitical-forecasting", set()),
    ("Will the yuan weaken past 7.5 per dollar by end-2027?", "financial-markets-forecasting", set()),
    ("Will the price war among Chinese EV makers end by 2027?", "industry-forecasting", {"industry-research"}),
    # Superlatives over contenders are ranking questions too.
    ("Will Nvidia remain the world's largest company by market cap through 2027?",
     "competitive-landscape-forecasting", {"financial-markets-forecasting"}),
    ("Will TSMC remain the #1 foundry by 2030?", "competitive-landscape-forecasting", {"industry-forecasting"}),
    # Commodity price thresholds are market questions in both languages; the industry outlook stays second.
    ("2027年布伦特原油均价会高于90美元/桶吗？", "financial-markets-forecasting", {"industry-forecasting"}),
    ("2027年铜价会超过每吨1万美元吗？", "financial-markets-forecasting", set()),
    ("Will copper exceed 10,000 USD per tonne in 2027?", "financial-markets-forecasting", set()),
]


@pytest.mark.parametrize("question, primary, also", ROUTES)
def test_real_questions_route_to_their_method_skills(question, primary, also):
    names = [r.name for r in rs.route(question, year=2026)]
    assert names[0] == primary, names
    assert also <= set(names), names
    assert names[-1] == rs.CROSS_CUTTING and len(names) <= rs.MAX_PLAN_SKILLS


@pytest.mark.parametrize("question, absent", [
    ("Will the price war among Chinese EV makers end by 2027?", "geopolitical-forecasting"),
    ("Will the US-China trade war end by 2027?", "geopolitical-forecasting"),
    ("Will Congress pass a crypto market structure bill by 2026?", "industry-forecasting"),
    ("Will private sector payrolls fall below 100k by 2027?", "industry-forecasting"),
    ("How will monetary policy transmission affect US inflation by 2027?", "industry-forecasting"),
    ("Which IPO candidates will list on the STAR Market in 2026?", "election-forecasting"),
    ("Who will win the 2028 US presidential election?", "competitive-landscape-forecasting"),
    ("Which countries will impose tariffs on Chinese EVs by 2027?", "competitive-landscape-forecasting"),
    ("中国2026年毛利率最高的上市公司有哪些？", "macro-research"),                    # 毛利率 is no interest rate
    ("2027年居民消费价格指数同比涨幅会超过2%吗？", "financial-markets-forecasting"),  # a price index, not a stock index
    ("中国储能市场规模到2030年将达到多少亿元人民币？", "financial-markets-forecasting"),  # an amount, not FX
    ("预计2027年新车上市数量会超过100款吗？", "financial-markets-forecasting"),      # a launch, not a listing
    ("Will online shopping sales in the Philippines grow by 2027?", "macro-research"),  # no "ppi" inside words
    ("Will a bipolar disorder drug win approval by 2027?", "financial-markets-forecasting"),  # no "ipo" inside words
    ("How much grain will be fed into ethanol plants by 2027?", "macro-research"),
    # A sizing perimeter or a historical superlative is not a ranking question.
    ("How much will the largest companies spend on AI capex by 2030?", "competitive-landscape-forecasting"),
    ("Will the 2026 budget deficit be the largest since WWII?", "competitive-landscape-forecasting"),
    ("Will inflation remain the top concern of voters in 2026?", "competitive-landscape-forecasting"),
    # A commodity noun without a price, or a cost curve, is no market question.
    ("Will China's copper demand grow by 2030?", "financial-markets-forecasting"),
    ("储能系统价格到2030年会降至每瓦时0.5元吗？", "financial-markets-forecasting"),
])
def test_router_false_positives_stay_out(question, absent):
    assert absent not in [r.name for r in rs.route(question, year=2026)]


@pytest.mark.parametrize("text, key", [
    ("2026年HBM市场规模与HBM4量产", "semiconductors"),           # ASCII terms inside Chinese text
    ("美国AI领域的竞争格局", "cloud-software"),
    ("Which chipmaker will lead HBM4 supply in 2027?", "semiconductors"),
    ("ＴＳＭＣ的ＨＢＭ４封装产能", "semiconductors"),                # full-width letters and digits
])
def test_sector_terms_match_inside_chinese_and_full_width_text(text, key):
    assert key in rs.detect_sectors(text, limit=3)


@pytest.mark.parametrize("text, absent", [
    ("US exports and imports, per the annual report, support growth", "transport-logistics"),
    ("lithium-ion battery cell prices", "mining-metals"),
    ("中国锂电池出货量", "mining-metals"),
    ("data-center capacity under construction", "real-estate-construction"),
    ("refinancing needs of hyperscalers", "oil-gas"),
    ("lithium deposits in Chile", "banking-insurance"),
    ("wind farm and solar farm capacity", "agriculture-food"),
    ("a K-drama streaming hit", "semiconductors"),
    ("Archduke Ferdinand's legacy", "semiconductors"),
    ("云厂商的存储能力与带宽", "energy-storage-batteries"),
    ("消费市场结构变化", "consumer-retail"),
    ("居民消费价格指数", "consumer-retail"),
    ("retail investors in A shares", "consumer-retail"),
    ("monetary policy transmission", "power-utilities"),
    ("insurgents in the Sahel", "banking-insurance"),
    ("container orchestration software", "transport-logistics"),
    ("开源节流的财政政策", "cloud-software"),
])
def test_sector_terms_do_not_fire_on_lookalike_words(text, absent):
    assert absent not in rs.detect_sectors(text, limit=len(rs._SECTOR_TERMS))


def test_the_future_test_uses_the_reference_year():
    past = "What was the global semiconductor market size by 2024?"
    assert "industry-forecasting" not in [r.name for r in rs.route(past, year=2026)]
    assert "industry-forecasting" in [r.name for r in rs.route(past, year=2023)]
    # A deadline in the reference year is still ahead; a bare year counts only after it.
    assert "industry-forecasting" in [r.name for r in rs.route("全球半导体市场规模到2026年底", year=2026)]
    assert "industry-forecasting" not in [r.name for r in rs.route("2026年半导体行业现状", year=2026)]
    assert "industry-forecasting" in [r.name for r in rs.route("2027年半导体行业现状", year=2026)]
    assert rs.route(past, year=2026) == rs.route(past, year=2026)


@pytest.mark.parametrize("question", ["Summarize the plot of Hamlet.", "What is the history of the Roman Empire?",
                                      "Translate this paragraph into French."])
def test_unrelated_questions_route_to_nothing(question):
    assert rs.route(question) == []


def test_world_bank_and_central_banks_are_not_the_banking_sector():
    assert "banking-insurance" not in rs.detect_sectors("IMF与世界银行预测；中国人民银行降准；the World Bank and the "
                                                        "central bank outlook")
    assert rs.detect_sectors("US regional banks' deposit outflows") == ["banking-insurance"]


def test_routing_is_deterministic_and_bilingual():
    question = "预判2035年前全球电动汽车产业的发展趋势：技术路线演进、产业链竞争格局"
    assert rs.route(question) == rs.route(question)
    assert rs.detect_sectors(question)[0] == "autos-ev"


def test_planner_choice_wins_and_keeps_the_cross_cutting_skill():
    names = list(rs.SKILL_NAMES)
    chosen, source = rs.choose_plan_skills(["macro-research", "bogus", "macro-research"],
                                           ["financial-markets-forecasting", rs.CROSS_CUTTING], names)
    assert (chosen, source) == (["macro-research", rs.CROSS_CUTTING], "planner")
    assert rs.choose_plan_skills(None, ["macro-research", rs.CROSS_CUTTING], names) == (
        ["macro-research", rs.CROSS_CUTTING], "router")
    too_many = ["industry-research", "industry-forecasting", "macro-research", "election-forecasting"]
    chosen, _ = rs.choose_plan_skills(too_many, [rs.CROSS_CUTTING], names)
    assert len(chosen) == rs.MAX_PLAN_SKILLS and chosen[-1] == rs.CROSS_CUTTING


def test_kiq_skill_choice():
    plan = ["industry-forecasting", "industry-research", rs.CROSS_CUTTING]
    # A baseline KIQ (a past year, no forecast words) gets the baseline skill, a target-year one the outlook
    # skill, and never both: the pair shares one evidence path and the sector adapters.
    assert rs.kiq_skills(plan, "2025年全球半导体销售额是多少？", kind="data", base_rate=False,
                         year=2026) == ["industry-research"]
    assert rs.kiq_skills(plan, "全球晶圆厂2026-2030年新增产能多少？", kind="data", base_rate=False,
                         year=2026) == ["industry-forecasting"]
    # Every kind gets a method: each domain skill's Investigate section carries its actor-record rules.
    assert rs.kiq_skills(plan, "Who are the main regulators?", kind="actor", base_rate=False) == [
        "industry-forecasting"]
    # A base-rate KIQ is led by the reference-class skill.
    assert rs.kiq_skills(plan, "How often have similar adoption curves stalled?", kind="general",
                         base_rate=True)[0] == rs.CROSS_CUTTING
    # The domain skill the KIQ's own words name wins over the plan's primary one.
    landscape = ["industry-forecasting", "competitive-landscape-forecasting", rs.CROSS_CUTTING]
    assert rs.kiq_skills(landscape, "Historically, how often has the DRAM market leader lost the top share "
                                    "position within five years?", kind="general", base_rate=True) == [
        rs.CROSS_CUTTING, "competitive-landscape-forecasting"]
    assert rs.kiq_skills(["macro-research"], "What is the latest CPI print?", kind="data", base_rate=True) == [
        "macro-research"]                            # no reference-class skill on the plan: nothing added


# ----------------------------------------------------------------------------- library and blocks

@pytest.fixture
def library():
    lib = rs.load_library({"RESEARCH_SKILLS_DIR": str(SKILLS)})
    assert lib is not None
    return lib


def test_mode_parsing():
    assert rs.skills_mode({}) == "auto" and rs.skills_mode({"RESEARCH_SKILLS": "OFF"}) == "off"
    assert rs.skills_mode({"RESEARCH_SKILLS": "maybe"}) == "auto"


def test_missing_or_malformed_skills_degrade_to_nothing(tmp_path):
    assert rs.load_library({"RESEARCH_SKILLS_DIR": str(tmp_path / "none")}) is not None   # falls back to bridge
    (tmp_path / "macro-research").mkdir()
    (tmp_path / "macro-research" / "SKILL.md").write_text("---\nname: macro-research\ndescription: x\n---\n# T\n")
    assert rs.parse_skill("macro-research", "no frontmatter") is None
    assert rs.parse_skill("macro-research", (tmp_path / "macro-research" / "SKILL.md").read_text()) is None
    lonely = rs.load_library({"RESEARCH_SKILLS_DIR": str(tmp_path)})
    assert lonely is None or "macro-research" not in lonely.names


def test_blocks_carry_the_right_sections(library):
    plan = rs.planning_block(library, ["industry-forecasting", rs.CROSS_CUTTING])
    assert plan.startswith("\n" + rs.PLAN_HEADER)
    assert library.skills["industry-forecasting"].section("Plan") in plan and '"skills": [...]' in plan
    assert all(f"- {name}:" in plan for name in rs.SKILL_NAMES)
    kiq = rs.kiq_block(library, ["industry-research"], ["semiconductors"], data_enabled=False)
    assert rs.KIQ_HEADER in kiq and rs.NO_DATA_NOTE in kiq and "[sector: semiconductors]" in kiq
    assert library.sectors["semiconductors"] in kiq
    assert rs.kiq_block(library, ["macro-research"], ["semiconductors"], data_enabled=True).count("[sector:") == 0
    assert rs.GAP_HEADER in rs.gaps_block(library, ["macro-research"])
    writer = rs.writer_block(library, rs.writer_skills(["macro-research", rs.CROSS_CUTTING], scenario=True))
    assert library.skills[rs.CROSS_CUTTING].section("Synthesize") in writer
    pointers = rs.read_file_pointers(library, ["macro-research"])
    assert "read_file /mnt/skills/public/macro-research/SKILL.md" in pointers
    assert rs.planning_block(library, []) == rs.kiq_block(library, [], [], data_enabled=True) == ""


def test_an_industry_skill_beside_another_method_brings_its_sector_adapters_only(library):
    """Base-rate KIQs (reference-class first) and KIQs that also name a landscape, policy or market
    skill get that method's Investigate text plus the sector adapters, never two quick paths."""
    investigate = library.skills["industry-forecasting"].section("Investigate")
    for pair in ([rs.CROSS_CUTTING, "industry-forecasting"], ["industry-forecasting",
                                                              "competitive-landscape-forecasting"]):
        block = rs.kiq_block(library, pair, ["semiconductors", "ai-compute-datacenters"], data_enabled=True)
        other = next(name for name in pair if name not in rs.INDUSTRY_SKILLS)
        assert investigate not in block and library.skills[other].section("Investigate") in block
        assert block.count("[sector:") == 2
    alone = rs.kiq_block(library, ["industry-forecasting"], ["semiconductors"], data_enabled=True)
    assert investigate in alone and alone.count("[sector:") == 1


def test_prompt_suffixes_stay_within_their_size_budgets(library):
    """Planner suffix about 7,000 characters at most, a KIQ suffix about 6,000 (header included)."""
    for question, _, _ in ROUTES:
        candidates = [r.name for r in rs.route(question, year=2026)]
        assert len(rs.planning_block(library, candidates)) <= 7000, question
    longest = sorted(library.sectors, key=lambda key: -len(library.sectors[key]))[:rs.MAX_KIQ_SECTORS]
    for first in rs.SKILL_NAMES:
        for second in (None, *rs.SKILL_NAMES):
            if second == first:
                continue
            block = rs.kiq_block(library, [first] + ([second] if second else []), longest, data_enabled=False)
            assert len(block) <= 6000, (first, second, len(block))


def test_the_menu_names_every_skill_without_cutting_words(library):
    lines = rs.menu_lines(library, shown=["macro-research"])
    assert len(lines) == len(rs.SKILL_NAMES)
    assert "- macro-research: (planning notes above)" in lines
    for line in lines:
        scope = line.split(": ", 1)[1]
        assert 10 <= len(scope) <= rs.MENU_SCOPE_CHARS and (scope[-1].isalnum() or scope.endswith(")")), line


def test_the_cap_never_cuts_inside_a_word():
    text = "alpha beta, gamma delta epsilon zeta eta theta iota kappa lambda mu"
    for limit in range(20, len(text)):
        cut = rs._cap(text, limit)
        assert len(cut) <= limit and text.startswith(cut)
        assert text[len(cut):][:1] in ("", " ", ","), (limit, cut)
    assert rs._cap("第一句。第二句很长很长很长很长。第三句", 16) == "第一句。第二句很长很长很长很长。"
    lines = "line one\nline two is here\nline three"
    assert rs._cap(lines, 26) == "line one\nline two is here"


def test_the_planner_choice_accepts_strings_and_never_drops_the_domain():
    names = list(rs.SKILL_NAMES)
    routed = ["macro-research", rs.CROSS_CUTTING]
    assert rs.choose_plan_skills("election-forecasting, reference-class-forecasting", routed, names) == (
        ["election-forecasting", rs.CROSS_CUTTING], "planner")
    assert rs.choose_plan_skills(["Election_Forecasting"], routed, names) == (
        ["election-forecasting", rs.CROSS_CUTTING], "planner")
    assert rs.choose_plan_skills([{"name": "macro-research"}], [], names) == (["macro-research"], "planner")
    # Only the cross-cutting skill is no domain opinion: the router's domain skills stay.
    assert rs.choose_plan_skills([rs.CROSS_CUTTING], routed, names) == (routed, "router")
    assert rs.choose_plan_skills([rs.CROSS_CUTTING], [], names) == ([rs.CROSS_CUTTING], "planner")
    assert rs.choose_plan_skills(42, routed, names) == (routed, "router")


def test_headers_carry_the_engine_rules(library):
    # A VERIFIED finding whose own threshold or ratio is not on its page would be downgraded to UNVERIFIED.
    assert "VERIFIED finding carries only numbers its fetched page prints" in rs.KIQ_HEADER
    assert "[S<n>]" in rs.KIQ_HEADER and "(VERIFIED|REPORTED)" in rs.KIQ_HEADER
    assert "KIQ limit" in rs.PLAN_HEADER and "executive summary" in rs.PLAN_HEADER
    assert "belong to the sections you are writing" in rs.WRITER_HEADER
    summary = rs.writer_block(library, ["macro-research"], summary=True)
    assert summary.startswith("\n" + rs.SUMMARY_HEADER) and rs.WRITER_HEADER not in summary
    assert library.skills["macro-research"].section("Synthesize") in summary


# ----------------------------------------------------------------------------- v3 engine

CPI_FED = ("Will US CPI inflation fall below 2.5% year over year by December 2027, and how will the Federal "
           "Reserve policy rate evolve through 2027?")


@pytest.fixture
def v3(tmp_path, monkeypatch):
    import data_sources
    import test_v3_official_data as v3o

    def make(question=CPI_FED, *, skills="auto", data="true", sub="run"):
        env = {"DATA_SOURCES_ENABLED": data, "RESEARCH_SKILLS": skills, "RESEARCH_SKILLS_DIR": str(SKILLS)}
        return v3o.real_engine(tmp_path / sub, monkeypatch, data_sources, v3o.RealSources(data_sources),
                               question=question, env=env)
    return make


def _planner_task(engine, raw_plan=None):
    seen = []

    def plan_json(shared, task, **kwargs):
        seen.append(task)
        if raw_plan is None:
            import research_gateway as rg
            raise rg.GatewayError("fixture")
        return raw_plan
    engine._plan_json = plan_json
    engine._scout = lambda queries: "(no scout results)"
    import research_gateway as rg
    scope, raw, _ = engine._plan_calls("brief", rg.Deadline(100), scope={"scout_queries": ["q"]})
    return seen[-1], scope, raw


def test_v3_off_keeps_every_prompt_and_artifact_byte_identical(v3):
    import linear_research as lr
    off, base = v3(skills="off", sub="off"), v3(skills="off", sub="base")
    assert off.skill_library is None and "research_skills" not in off.meta
    task, _, _ = _planner_task(off)
    assert rs.PLAN_HEADER not in task and '"skills"' not in task
    off.plan.skills = []
    kiq = lr.Kiq("K1", "What is the latest US CPI inflation rate?", [], kind="data")
    assert rs.KIQ_HEADER not in off._kiq_task(kiq, [])
    assert off._kiq_task(kiq, []) == base._kiq_task(kiq, [])
    assert rs.WRITER_HEADER not in off.section_task(off.plan.sections[:1])
    assert "skills" not in off.plan.to_dict()


def test_v3_planner_gets_the_routed_plan_sections_and_may_choose(v3):
    engine = v3()
    assert engine.skill_library is not None
    task, scope, _ = _planner_task(engine)
    assert task.startswith("PLANNING TASK") and rs.PLAN_HEADER in task
    assert engine.skill_library.skills["macro-research"].section("Plan") in task
    assert '"skills": [...]' in task
    import linear_research as lr
    plan = lr.build_plan(engine.question, engine.language, "2026-10-12", engine.preset, 4, scope, None)
    engine.plan = plan
    engine._assign_skills(plan, {"skills": ["financial-markets-forecasting"]}, scope)
    assert plan.skills == ["financial-markets-forecasting", rs.CROSS_CUTTING]
    assert engine.meta["research_skills"]["source"] == "planner"
    engine._assign_skills(plan, {}, scope)
    assert plan.skills[0] == "macro-research" and engine.meta["research_skills"]["source"] == "router"
    # Round trip: the chosen skills survive plan.json, and a plan without skills writes no key.
    again = lr.Plan.from_dict(plan.to_dict())
    assert again.skills == plan.skills
    plan.skills = []
    assert "skills" not in plan.to_dict()


def test_v3_kiq_gap_and_writer_tasks_carry_the_method_text_last(v3):
    import linear_research as lr
    engine = v3()
    engine.plan.skills = ["macro-research", rs.CROSS_CUTTING]
    library = engine.skill_library
    data_kiq = lr.Kiq("K1", "What are the latest US CPI and core inflation readings?", [], kind="data")
    task = engine._kiq_task(data_kiq, [])
    assert task.startswith("KIQ INVESTIGATION TASK") and rs.KIQ_HEADER in task
    assert task.index(rs.KIQ_HEADER) > task.index("Official tools:")            # after the data text
    assert library.skills["macro-research"].section("Investigate") in task
    base_rate = lr.Kiq("K4", "How often historically has CPI fallen below 2.5% within 15 months of a peak?", [],
                       kind="general")
    assert library.skills[rs.CROSS_CUTTING].section("Investigate") in engine._kiq_task(base_rate, [])
    # An actor KIQ gets the plan's domain method too (its actor-record rules), even without domain words.
    actor = lr.Kiq("K3", "Which advocacy groups lobby on this issue and what do they want?", [], kind="actor")
    assert library.skills["macro-research"].section("Investigate") in engine._kiq_task(actor, [])
    fomc = lr.Kiq("K5", "How will FOMC voters weigh inflation against unemployment?", [], kind="actor")
    assert library.skills["macro-research"].section("Investigate") in engine._kiq_task(fomc, [])
    scenario = [s for s in engine.plan.sections if s.is_scenario]
    writer = engine.section_task(scenario)
    assert rs.WRITER_HEADER in writer and library.skills[rs.CROSS_CUTTING].section("Synthesize") in writer
    plain = [s for s in engine.plan.sections if not s.is_scenario][:1]
    assert library.skills[rs.CROSS_CUTTING].section("Synthesize") not in engine.section_task(plain)
    assert library.skills["macro-research"].section("Synthesize") in engine.section_task(plain)


def test_v3_without_data_tools_says_so_in_the_method_text(v3):
    import linear_research as lr
    engine = v3(data="false")
    engine.plan.skills = ["macro-research", rs.CROSS_CUTTING]
    task = engine._kiq_task(lr.Kiq("K1", "What is the latest US CPI inflation rate?", [], kind="data"), [])
    assert rs.NO_DATA_NOTE in task and "Official tools:" not in task


def test_v3_a_resumed_plan_reuses_its_saved_skills(v3, tmp_path):
    import json
    import linear_research as lr
    engine = v3()
    engine.plan.skills = ["election-forecasting", rs.CROSS_CUTTING]
    saved = lr.Plan.from_dict(json.loads(json.dumps(engine.plan.to_dict())))
    assert saved.skills == ["election-forecasting", rs.CROSS_CUTTING]
    engine.plan = saved
    engine._record_skills(saved, "plan.json")
    assert engine.meta["research_skills"]["skills"] == saved.skills
    assert engine.meta["research_skills"]["source"] == "plan.json"


# ----------------------------------------------------------------------------- legacy engine

@pytest.fixture
def legacy(monkeypatch):
    import importlib
    monkeypatch.setenv("RESEARCH_SKILLS_DIR", str(SKILLS))
    module = importlib.import_module("deerflow_research")
    return module


@pytest.mark.parametrize("mode", ["auto", "off"])
def test_legacy_prompts_route_method_skills_and_off_is_byte_identical(legacy, monkeypatch, mode):
    monkeypatch.setenv("RESEARCH_SKILLS", mode)
    question = CPI_FED
    research = legacy.build_research_prompt(question, "standard", None)
    worker = legacy.build_scoped_worker_prompt(question, "What are the latest US CPI readings?", None)
    synthesis = legacy.build_synthesis_prompt(question, None)
    if mode == "off":
        assert "METHOD" not in research + worker + synthesis
        assert legacy._method_skill_names(question) == [] and legacy._method_skills_meta(question) is None
        return
    assert "read_file /mnt/skills/public/macro-research/SKILL.md" in research
    assert rs.KIQ_HEADER in worker and rs.WRITER_HEADER in synthesis
    assert research.startswith("/deep-research\n") and worker.startswith("/deep-research\n")
    assert legacy._method_skill_names(question)[0] == "macro-research"
    assert legacy._method_skills_meta(question)["status"] == "enabled"


def test_legacy_unrouted_questions_keep_their_prompts(legacy, monkeypatch):
    question = "Summarize the plot of Hamlet."
    monkeypatch.setenv("RESEARCH_SKILLS", "auto")
    auto = legacy.build_research_prompt(question, "standard", None)
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    assert auto == legacy.build_research_prompt(question, "standard", None)
