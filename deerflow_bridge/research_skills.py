"""Research method skills: registry, SKILL.md section parser, router and prompt blocks.

The method skills live as ordinary skill folders under ``skills/<name>/`` (deployed by
runtime_skill_sync to ``deer-flow/skills/public/<name>/``).  Each SKILL.md carries fixed
``##`` sections (Activation, Plan, Investigate, Synthesize, Gaps, References; contract in
docs/handoff/research-skills/design.md).  Both research engines inject those sections
into their own prompts:

- the v3 engine (linear_research.py): the Plan sections into the planning task, the
  Investigate sections into KIQ tasks, the Gaps lines into the gap review and the
  Synthesize sections into the writers;
- the legacy engine (deerflow_research.py): read_file pointers in its planning passes,
  Investigate cards for its workers and Synthesize cards for its final synthesis.

Everything here is deterministic for a given question, skills directory and reference
year (the router reads "2030" as future only after that year; callers pass the run's
as-of year, the default is the current UTC year), never raises into a research run (a
missing or malformed skill yields no text), and is a no-op with ``RESEARCH_SKILLS=off``.
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import os
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

# Registry order is the tie-break order of the router (domain skills first).
SKILL_NAMES: tuple[str, ...] = (
    "industry-research",
    "industry-forecasting",
    "competitive-landscape-forecasting",
    "macro-research",
    "policy-and-trade-forecasting",
    "geopolitical-forecasting",
    "election-forecasting",
    "financial-markets-forecasting",
    "reference-class-forecasting",
)
CROSS_CUTTING = "reference-class-forecasting"
INDUSTRY_SKILLS = frozenset({"industry-research", "industry-forecasting"})
SECTIONS: tuple[str, ...] = ("Activation", "Plan", "Investigate", "Synthesize", "Gaps", "References")
# Engine-injected section caps (characters); a longer section is cut by _cap (never mid-word).
SECTION_CAPS: Mapping[str, int] = {"Activation": 900, "Plan": 1800, "Investigate": 2400,
                                   "Synthesize": 1500, "Gaps": 700}
SECTOR_CAP = 1200
SECTOR_FILES: tuple[str, ...] = ("sectors-technology.md", "sectors-economy.md")
MAX_PLAN_SKILLS = 3            # skills on a plan (cross-cutting skill included)
MAX_DOMAIN_SKILLS = 2          # domain skills routed for a question
MAX_KIQ_SKILLS = 2             # Investigate sections in one KIQ task
MAX_WRITER_SKILLS = 2          # Synthesize sections in one writer task
MAX_KIQ_SECTORS = 2            # sector adapters in one KIQ task
MODES = ("auto", "off")

_HEADING_RE = re.compile(r"(?m)^## (.+?)\s*$")
_SECTOR_RE = re.compile(r"(?m)^### (\S+)\s*$")
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)


def skills_mode(env: Mapping[str, str] | None = None) -> str:
    """``auto`` (default) or ``off`` from ``RESEARCH_SKILLS``; an unknown value is ``auto``."""
    raw = str((os.environ if env is None else env).get("RESEARCH_SKILLS") or "").strip().lower()
    if raw in ("", "auto", "on", "true", "1"):
        return "auto"
    if raw in ("off", "false", "0", "none", "disabled"):
        return "off"
    logger.warning("RESEARCH_SKILLS=%r is not auto/off; using auto", raw)
    return "auto"


def skills_dir(env: Mapping[str, str] | None = None) -> Path | None:
    """The directory holding ``<name>/SKILL.md``: ``RESEARCH_SKILLS_DIR``, else the deployed
    runtime copy next to this module (``skills/public``), else the bridge source (``skills``)."""
    source = os.environ if env is None else env
    here = Path(__file__).resolve().parent
    candidates = [Path(os.path.expanduser(str(source["RESEARCH_SKILLS_DIR"])))] \
        if str(source.get("RESEARCH_SKILLS_DIR") or "").strip() else []
    candidates += [here / "skills" / "public", here / "skills"]
    for candidate in candidates:
        if any((candidate / name / "SKILL.md").is_file() for name in SKILL_NAMES):
            return candidate
    return None


# Where an over-long section may be cut, best first: (separator, characters of it kept).
_CUT_POINTS: tuple[tuple[str, int], ...] = (("\n", 0), ("。", 1), (". ", 1), ("; ", 0), ("；", 0),
                                             (", ", 0), ("，", 0), (" ", 0))


def _cap(text: str, limit: int) -> str:
    """``text`` within ``limit`` characters: cut at its last complete line, else at the
    last sentence, clause or word end in the second half of the limit (never mid-word)."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    for separator, kept in _CUT_POINTS:
        index = head.rfind(separator)
        if index >= limit // 2:
            return head[:index + kept].rstrip()
    return head.rstrip()


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    mandate: str
    sections: Mapping[str, str]
    sha256: str

    def section(self, heading: str) -> str:
        return _cap(self.sections.get(heading, ""), SECTION_CAPS.get(heading, 20000))


def parse_skill(name: str, text: str) -> Skill | None:
    """A Skill from SKILL.md text, or None when it lacks the frontmatter, the matching
    name or any engine-injected section."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    front = match.group(1)
    declared = re.search(r"(?m)^name:\s*(\S+)\s*$", front)
    if not declared or declared.group(1) != name:
        return None
    description = re.search(r"(?ms)^description:\s*(.+?)(?=^[A-Za-z][\w-]*:|\Z)", front)
    body = text[match.end():]
    title = re.search(r"(?m)^# .+\n+(.+)", body)
    parts = _HEADING_RE.split(body)
    sections = {heading.strip(): content.strip("\n") for heading, content in zip(parts[1::2], parts[2::2])}
    if any(not sections.get(heading, "").strip() for heading in SECTION_CAPS):
        return None
    return Skill(name=name,
                 description=re.sub(r"\s+", " ", description.group(1)).strip().lstrip(">-|").strip()
                 if description else "",
                 mandate=re.sub(r"\s+", " ", title.group(1)).strip() if title else "",
                 sections=sections, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


def parse_sectors(text: str) -> dict[str, str]:
    """``### <key>`` blocks of a sector-adapter file."""
    parts = _SECTOR_RE.split(text)
    return {key: _cap(block, SECTOR_CAP) for key, block in zip(parts[1::2], parts[2::2])}


@dataclass
class SkillLibrary:
    """The method skills of one skills directory (parsed once; immutable afterwards)."""
    root: Path
    skills: dict[str, Skill] = field(default_factory=dict)
    sectors: dict[str, str] = field(default_factory=dict)
    sector_hash: str = ""

    @property
    def names(self) -> list[str]:
        return [name for name in SKILL_NAMES if name in self.skills]

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def fingerprint(self, names: Iterable[str]) -> dict[str, str]:
        return {name: self.skills[name].sha256[:16] for name in names if name in self.skills}


_LIBRARY_CACHE: dict[tuple, SkillLibrary] = {}
_LIBRARY_LOCK = threading.Lock()


def load_library(env: Mapping[str, str] | None = None) -> SkillLibrary | None:
    """The parsed library, or None when no method skill can be read.  Cached by the
    directory and every file's (mtime, size); never raises."""
    try:
        root = skills_dir(env)
        if root is None:
            return None
        files = [root / name / "SKILL.md" for name in SKILL_NAMES]
        files += [root / "industry-research" / "references" / sector for sector in SECTOR_FILES]
        stamp = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) if path.is_file() else (str(path),)
                      for path in files)
        key = (str(root), stamp)
        with _LIBRARY_LOCK:
            cached = _LIBRARY_CACHE.get(key)
        if cached is not None:
            return cached
        library = SkillLibrary(root=root)
        for name in SKILL_NAMES:
            path = root / name / "SKILL.md"
            if not path.is_file():
                continue
            skill = parse_skill(name, path.read_text(encoding="utf-8"))
            if skill is None:
                logger.warning("research skill %s is malformed (frontmatter or sections); skipped", name)
                continue
            library.skills[name] = skill
        digest = hashlib.sha256()
        for sector_file in SECTOR_FILES:
            path = root / "industry-research" / "references" / sector_file
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                library.sectors.update(parse_sectors(text))
                digest.update(text.encode("utf-8"))
        library.sector_hash = digest.hexdigest()[:16] if library.sectors else ""
        if not library.skills:
            return None
        with _LIBRARY_LOCK:
            _LIBRARY_CACHE.clear()
            _LIBRARY_CACHE[key] = library
        return library
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.warning("research skills unavailable (%s: %s)", type(exc).__name__, exc)
        return None


# ============================================================================ router
# Bilingual trigger patterns per skill: (pattern, weight).  A skill is routed when its
# score reaches ROUTE_MIN_SCORE; weights below 2 are supporting words that only count
# together with others.  Patterns are matched case-insensitively against the question
# (plus restated question / key entities when the caller passes them) after
# _match_text: NFKC-normalised, with a space at every CJK/ASCII boundary, so a
# \b-bounded ASCII term ("\bai\b", "\bhbm\b", "\bcpi\b") also matches inside Chinese
# text ("美国AI领域" reads "美国 AI 领域") and a Chinese pattern never needs one.

_ROUTE_MIN_SCORE = 2.0

_CJK = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"   # CJK ideographs (ext. A, unified, compatibility)
_CJK_ASCII_RE = re.compile(rf"(?<=[{_CJK}])(?=[A-Za-z0-9])|(?<=[A-Za-z0-9])(?=[{_CJK}])")


def _match_text(text: Any) -> str:
    """The text the router reads (idempotent): NFKC (full-width letters, digits and
    punctuation become ASCII) and a space between CJK and ASCII letters or digits."""
    return _CJK_ASCII_RE.sub(" ", unicodedata.normalize("NFKC", str(text or "")))


_SECTOR_TERMS: Mapping[str, str] = {
    "semiconductors": r"semiconductor|\bchips?\b|chipmak|foundr(?:y|ies)|\bwafers?\b|\bfabs?\b|\bdram\b|\bnand\b|"
                      r"\bhbm(?:\d[a-z]?)?\b|memory (?:chips?|markets?|semiconductors?)|lithograph|\beuv\b|\btsmc\b|"
                      r"samsung|\bsk ?hynix\b|\bmicron\b|\bsmic\b|半导体|芯片|晶圆|存储芯片|存储器|内存|闪存|光刻|"
                      r"晶圆代工|芯片代工|封装|封测|台积电|中芯国际|海力士|美光|先进制程",
    "ai-compute-datacenters": r"data[ -]?cent(?:er|re)s?|hyperscal|\bgpus?\b|\btpus?\b|"
                              r"\bai (?:compute|chips?|servers?|infrastructure|accelerators?|clusters?)\b|"
                              r"(?:gpu|ai|hardware) accelerators?|compute capacity|数据中心|算力|智算|服务器|"
                              r"\bai\s*芯片",
    "cloud-software": r"\bcloud\b|\bsaas\b|\bsoftware\b|\biaas\b|\bpaas\b|enterprise ai|open[- ]source ai|"
                      r"open[- ]weights?|\bllms?\b|large language models?|foundation models?|frontier (?:ai|models?)|"
                      r"\bai labs?\b|artificial intelligence|generative ai|\bai\b|云计算|云服务|软件|大模型|"
                      r"开源(?!节流)|\bai\s*实验室|人工智能|生成式",
    "telecom-networks": r"telecom|\b[56]g\b|wireless|(?:radio )?spectrum (?:auctions?|allocation|licen[cs]es?)|"
                        r"broadband|fib(?:er|re)[- ](?:optic|network|broadband)|\bftth\b|satellite internet|"
                        r"电信|通信|运营商",
    "internet-platforms-media": r"(?:online|digital|internet|social|e-?commerce|gig|tech) platforms?|"
                                r"platform (?:economy|companies|firms|regulation)|social media|advertis|e-?commerce|"
                                r"streaming|search engines?|互联网|平台经济|互联网平台|电商平台|平台企业|电商|广告|"
                                r"短视频|社交媒体",
    "autos-ev": r"electric vehicles?|\bevs?\b|\bnevs?\b|\bbevs?\b|\bphevs?\b|automo(?:tive|biles?|kers?)|"
                r"car (?:market|sales)|vehicle sales|\bplug-in|autonomous driving|robotaxis?|电动汽车|新能源汽车|"
                r"新能源车|电动车|汽车|乘用车|智能驾驶|自动驾驶",
    "energy-storage-batteries": r"batter(?:y|ies)|energy storage|\bbess\b|lithium[- ]ion|lithium iron phosphate|"
                                r"\blfp\b|sodium[- ]ion|(?<!存)储能|电池|锂电|动力电池|钠离子|固态电池",
    "frontier-tech": r"quantum|\bfusion\b|\brobot|humanoid|space (?:launch|industry|economy)|\bsatellites?\b|"
                     r"brain[- ]computer|量子|聚变|机器人|人形机器人|商业航天|卫星|脑机",
    "aerospace-defense": r"aerospace|defen[cs]e (?:industry|industrial|spending|budgets?|contractors?|procurement)|"
                         r"\baircraft\b|\baviation\b|munitions?|drone (?:industry|makers?|production)|航空|航天|"
                         r"国防(?!部)|军工|飞机|无人机",
    "power-utilities": r"electricity|power (?:demand|grids?|prices?|sector|markets?|generation|consumption|plants?)|"
                       r"\bgrid\b|\butilit(?:y|ies)\b|(?:power|electricity) transmission|"
                       r"transmission (?:lines?|grids?|capacity|networks?|system)|interconnection|nuclear power|"
                       r"电力|电网|用电|发电|电价|核电",
    "renewables": r"\bsolar\b|photovoltaic|\bpv\b|wind (?:power|energy|turbines?|farms?)|offshore wind|renewable|"
                  r"hydrogen|electroly[sz]ers?|光伏|风电|可再生|新能源发电|氢能|绿氢",
    "oil-gas": r"(?<!palm )(?<!olive )(?<!cooking )\boil\b|\bcrude\b|natural gas|\blng\b|\bopec|refiner(?:y|ies|s)?|"
               r"\brefining\b|petroleum|\bshale\b|石油|原油|天然气|炼油|成品油|欧佩克",
    "mining-metals": r"(?<!data )(?<!crypto )(?<!bitcoin )\bmining\b|\blithium\b(?![- ](?:ion|iron|batter))|"
                     r"\bcopper\b|\bnickel\b|\bcobalt\b|rare earths?|critical minerals?|iron ore|\bsteel\b|"
                     r"alumini?um|矿业|矿产|矿山|矿石|采矿|铁矿|锂矿|铜矿|碳酸锂|锂(?![电离])|铜|镍|钴|稀土|关键矿产|"
                     r"钢铁|铝",
    "agriculture-food": r"agricultur|(?<!wind )(?<!solar )(?<!server )\bfarm(?:s|ing|land|ers?)?\b|\bcrops?\b|"
                        r"\bgrains?\b|soybeans?|\bwheat\b|\bcorn\b|\bmaize\b|fertili[sz]ers?|livestock|"
                        r"food (?:prices|industry|security)|农业|粮食|大豆|小麦|玉米|化肥|食品|农产品|生猪",
    "biopharma": r"pharma|biotech|\bdrugs?\b|vaccines?|glp-1|clinical trials?|biologics?|biosimilars?|医药|生物医药|"
                 r"药品|疫苗|创新药|临床|制药",
    "healthcare-services-medtech": r"healthcare|health care|hospitals?|medical devices?|medtech|health insurance|"
                                   r"医疗|医院|医疗器械|医保",
    # "World Bank", central banks and 世界银行/人民银行/中央银行 are not the banking sector.
    "banking-insurance": r"(?<!world )(?<!central )(?<!development )\bbanks?\b|\bbanking\b|"
                         r"\binsur(?:ance|ers?|ed|tech)\b|reinsur|\blenders?\b|credit (?:cards?|losses)|"
                         r"\bbank deposits?\b|deposit (?:outflows?|flight|rates?|base|insurance)|net interest margin|"
                         r"(?<!世界)(?<!人民)(?<!中央)(?<!开发)(?<!投资)银行|保险|信贷|存款",
    "real-estate-construction": r"real estate|property (?:market|sector|developers?|prices?)|\bhousing\b|"
                                r"home (?:sales|prices|builders?)|homebuild|construction (?:spending|activity|sector|"
                                r"industry|output|starts?|firms?|companies)|building permits|"
                                r"房地产|地产|楼市|住房|房价|建筑业|建筑施工|基建",
    "consumer-retail": r"consumer (?:spending|goods|staples|discretionary|brands?)|\bretail(?:ers?|ing)?\b"
                       r"(?! investors?| traders?| trading| brokerage)|luxury|beverages?|restaurants?|apparel|"
                       r"消费品|消费(?:支出|升级|降级|零售|行业)|社零|零售|奢侈品|餐饮|服装|白酒",
    "industrials-machinery": r"industrial (?:machinery|automation|equipment|robots?)|\bindustrials\b|machinery|"
                             r"machine tools?|capital goods|manufacturing (?:pmi|output|sector|industry)|"
                             r"工业(?:机器人|母机|自动化)|机械|装备制造|高端装备|制造业",
    "transport-logistics": r"shipping (?:industry|rates?|lines?|companies|costs?)|container (?:ships?|shipping|"
                           r"rates?|freight|ports?|throughput)|dry bulk|tanker rates|logistics|freight|"
                           r"\bairlines?\b|railways?|rail freight|trucking|\bports?\b|航运|物流|货运|集装箱|港口|"
                           r"铁路|快递",
}

# Industry wording.  Strong terms make a question an industry question on their own;
# weak ones ("sector", "capacity", "supply chain") also open macro, policy and war
# questions ("private sector", "military capacity"), so they count only with a sector.
_INDUSTRY_STRONG = (r"\bindustr(?:y|ies)\b|market size|market sizing|\btam\b|value chain|"
                    r"market (?:outlook|landscape)|industry structure|行业|产业|产业链|市场规模|市场空间|赛道")
_INDUSTRY_WEAK = (r"\bsectors?\b|market shares?|supply chains?|\bcapacity\b|shipments|penetration|"
                  r"adoption rates?|供应链|产能|出货|渗透率|装机")
# Forecast wording without a year; a year counts through _DEADLINE_YEAR_RE / _YEAR_RE.
_FUTURE_TERMS = (r"\boutlook|forecast|predict|projection|trajector|\bfuture\b|"
                 r"预测|预判|展望|前景|趋势|走向|未来")
# "by 2030", "through 2030", "到2030", "2030年前": future while the year has not ended.
_DEADLINE_YEAR_RE = re.compile(
    r"(?:\bby (?:the )?(?:end of |end-|year-end )?|\b(?:through|thru|until|till|before|to) |到\s*|至\s*|截至\s*)"
    r"(20\d\d)(?!\d)|(?<!\d)(20\d\d)\s*年\s*(?:前|底|末|之前)|\b(?:year-end|end-of-|end-) ?(20\d\d)(?!\d)", re.I)
# A bare year after the reference year is future-looking too ("2030 年全球…", "in 2035");
# the reference year and earlier ("2025年的出货量") are not.
_YEAR_RE = re.compile(r"(?<!\d)(20\d\d)(?!\d)")
_ROUTES: Mapping[str, tuple[tuple[str, float], ...]] = {
    "competitive-landscape-forecasting": (
        # Ranking intent about firms, labs, platforms or a technology race.
        (r"\bwhich (?:[\w.&'-]+ ){0,3}?(?:company|companies|lab|labs|firm|firms|player|players|vendor|vendors|"
         r"provider|providers|supplier|suppliers|manufacturer|manufacturers|maker|makers|chipmaker|chipmakers|"
         r"automaker|automakers|model|models|platform|platforms|brand|brands|startup|startups|hyperscaler|"
         r"hyperscalers)\b|\b(?:dominate|dominates|dominant|dominance|leadership|market leaders?|front ?runners?|"
         r"rank|ranks|ranking|rankings|ranked|league table)\b|"
         r"哪家|哪些企业|哪些公司|哪些厂商|排名|排行|第一梯队|头部厂商|头部企业|主导者|主导地位|领导者|领导地位|"
         r"领先地位|领跑|领军|龙头地位|前沿的(?:实验室|企业|公司)", 2.0),
        # Superlatives over contenders ("the most valuable IPO", "remain the largest", "市值最高的企业").
        # "the largest companies" alone is a sizing perimeter, so largest/biggest need "be/remain the".
        (r"\b(?:most valuable|highest[- ]valued|top-ranked)\b (?:[\w.&'-]+ ){0,3}?(?:company|companies|firm|"
         r"firms|lab|labs|ipos?|listings?|maker|makers|producer|producers|supplier|suppliers|player|players|"
         r"brand|brands|issuer|issuers)\b|\b(?:be|become|becomes|is|are|remain|remains|stay|stays|still be) "
         r"(?:the )?(?:world'?s )?(?:largest|biggest|most valuable|leader|number one|no\. ?1|#1)"
         r"(?!\w| since| ever| on record| in (?:history|decades|years))|"
         r"(?:最高|最大|最多|最强|第一)的?[^，。？！、,.?!]{0,10}?(?:企业|公司|厂商|实验室|品牌|发行人)|"
         r"(?:保持|仍是|仍为|继续保持)(?:全球|世界|行业)?(?:第一|最大|领先|龙头)", 2.0),
        # "Who will win", "which country": they also open election and war questions, so
        # they count only with other ranking evidence.
        (r"\bwho (?:will|would|leads|wins|dominates|ranks|is (?:ahead|leading|winning))\b|"
         r"\bwhich (?:[\w.-]+ ){0,2}?(?:country|countries|nation|nations)\b|谁将|谁会|谁能|哪个国家|哪些国家", 1.0),
        # Supporting words: they also appear in plain industry questions.
        (r"\b(?:lead|leads|leader|leaders|winner|winners|top \d+|largest|biggest|race)\b|"
         r"\bleading\b(?! indicators?)|competitive landscape|competitive dynamics|market share|格局|竞争格局|领先|"
         r"主导|龙头|头部|市占率|份额|胜出|站稳|赢家|竞赛|最高的|最大的", 1.0),
    ),
    "macro-research": (
        (r"\binflation\b|\bcpi\b|\bpce\b|\bppi\b|\bgdp\b|recessions?|unemployment|jobless|payrolls|federal funds|"
         r"federal reserve|\bfed\b(?!\s+(?:into|up|with|back)\b)|\bfomc\b|central banks?|\becb\b|\bboj\b|"
         r"\bboe\b|\bpboc\b|monetary policy|rate (?:cut|hike)s?|(?:cut|cuts|raise|raises|hike|hikes|lower|lowers) "
         r"(?:interest )?rates|interest rates?|policy rate|soft landing|stagflation|fiscal deficit|budget deficit|"
         r"debt-to-gdp|economic growth|yield curve", 2.0),
        (r"通胀|通货膨胀|居民消费价格|消费者物价|物价|经济增长|经济增速|衰退|失业率|降息|加息|降准|(?<![毛净])利率|央行|"
         r"美联储|欧洲央行|货币政策|财政赤字|宏观经济|宏观|社融|社会融资", 2.0),
        # Supporting words only: "its impact on the economy" does not make an industry question macro.
        (r"\beconom(?:y|ic|ies)\b|增速|就业|财政|经济", 1.0),
    ),
    "policy-and-trade-forecasting": (
        (r"tariff|trade (?:war|deal|policy|agreement|system|talks|regime)|\bieepa\b|section (?:232|301|201|122)|"
         r"export controls?|sanction|entity list|anti-dumping|\bwto\b|trade deficit|mercantilis|protectionis|"
         r"decoupling|de-?risking|reshoring|industrial policy|countervailing|safeguard dut|"
         r"(?:import|customs) duties", 2.0),
        (r"\bcongress(?:ional)? (?:pass|vote|approv)|\bpass(?:es|ed)? (?:the |a |an )?(?:[\w-]+ ){0,4}?bill\b|"
         r"signed into law|\bveto(?:es|ed)?\b|\bfinal rule\b|\bproposed rule\b|supreme court (?:rule|decide)|"
         r"\bstrike down\b|struck down", 2.0),
        (r"legislat|\bbill\b|congress|senate vote|supreme court|court (?:ruling|case)|lawsuit|litigation|"
         r"executive order|regulat|rulemaking|antitrust|\bban\b|subsid(?:y|ies)|\bact\b|policy", 1.0),
        (r"关税|贸易战|贸易协定|贸易体系|贸易政策|出口管制|制裁|实体清单|反倾销|反补贴|世贸|重商主义|保护主义|脱钩|产业政策|"
         r"通过法案|立法通过|最高法院", 2.0),
        (r"法案|立法|监管|法院|裁决|诉讼|行政令|反垄断|补贴政策|禁令|政策", 1.0),
    ),
    "geopolitical-forecasting": (
        # "trade war" (policy), "price war" (industry) and the like are not armed conflict.
        (r"(?<!trade )(?<!tariff )(?<!price )(?<!currency )(?<!chip )(?<!tech )(?<!talent )(?<!bidding )"
         r"(?<!culture )(?<!format )(?<!console )(?<!streaming )\bwars?\b|ceasefire|cease-fire|truce|armistice|"
         r"peace (?:deal|talks|agreement|process|plan)|invasion|"
         r"military (?:operation|strike|conflict|escalation|action|confrontation|clash)|"
         r"(?<!cost )(?<!price )(?<!tariff )(?<!trade )escalat|airstrikes?|"
         r"nuclear (?:deal|program|programme|weapons?|talks)|regime (?:change|collapse)|\bcoup\b|blockade|"
         r"taiwan strait|geopolitic|global order|world order|great[- ]power (?:competition|rivalry)|"
         r"leadership (?:transition|succession)|succession crisis", 2.0),
        (r"\brussia|\bukrain|\biran|\bisrael|\bgaza|\bhamas|\bhezbollah|\bnato\b|north korea|\bconflict\b", 1.0),
        # Military wording: with a party above ("Russia", "Iran") it makes a conflict question.
        (r"\bmilitary\b|\btroops?\b|\boffensives?\b|front ?lines?|territorial control|\bmissiles?\b|\bnuclear\b",
         1.0),
        (r"战争|停火|休战|和谈|和平协议|入侵|军事|冲突升级|核协议|核武|地缘政治|政权|政变|封锁|台海|全球秩序|"
         r"国际秩序|大国博弈|换届|党代会|接班", 2.0),
        (r"俄乌|俄罗斯|乌克兰|美伊|伊朗|以色列|加沙|北约|朝鲜|冲突", 1.0),
    ),
    "election-forecasting": (
        (r"\b(?:re-?)?elections?\b|electoral|\bmidterms?\b|referend(?:um|a)|\bballots?\b|\bpolls?\b|polling|vote share|"
         r"primar(?:y|ies) (?:race|election|contest)s?|presidential (?:race|election|primary|nominee|candidate)|"
         r"(?:house|senate|chamber|congressional|parliamentary) (?:control|majority|seats?|races?)|"
         r"control (?:of )?(?:the )?(?:house|senate|congress|parliament|chamber)|"
         r"\bwin (?:the )?(?:house|senate|presidency|white house|governorship|majority|election|seat)|"
         r"\b(?:which|what) party\b|party control|(?:presidential|senate|house|gubernatorial|party|democratic|"
         r"republican|opposition) candidates?|incumbent party|approval rating|net approval|governor'?s? races?", 2.0),
        (r"选举|中期选举|大选|公投|民调|参议院|众议院|议会选举|候选人|选票|连任|支持率|执政党|在野党|议席|席位", 2.0),
    ),
    "financial-markets-forecasting": (
        (r"stock price|share price|market cap|market capitali[sz]ation|valuations?|s&p ?500|nasdaq|dow jones|"
         r"\bindex (?:level|close)|treasury yields?|10-year yield|bond yields?|credit spreads?|exchange rates?|"
         r"\busd/|\beur/|(?:yuan|renminbi|\brmb\b|\bcny\b|\bcnh\b)\W{0,3}(?:[\w.]+ ){0,3}?(?:exchange|appreciat|"
         r"depreciat|weaken|strengthen|against|versus|vs\b|per (?:us )?dollar|to the dollar|fixing)|bitcoin|"
         r"gold price|oil price|\bbrent\b|\bwti\b|commodity prices?|\bipos?\b|(?:stock|share|exchange) listings?|"
         r"\blisting (?:date|day|process)|"
         r"\blist(?:s|ed|ing)? (?:on|in) (?:the )?(?:nasdaq|nyse|star market|hong kong|shanghai|shenzhen|"
         r"stock exchange)|default rates?|equity markets?|stock markets?|"
         r"\b(?:copper|alumini?um|aluminum|nickel|zinc|silver|platinum|palladium|iron ore|lithium(?: carbonate)?|"
         r"crude|wheat|corn|soybeans?|cocoa|coffee|sugar) (?:prices?|futures)\b", 2.0),
        # A price threshold or average makes a commodity question a market question.
        (r"\bprices?\b[^.?!]{0,40}\b(?:above|below|exceed|reach|hit|average)\b|per barrel|per ounce|per tonne|"
         r"\bclose (?:above|below)|"
         r"(?:价格?|均价)[^。？！，,；;]{0,12}?(?:高于|低于|超过|突破|跌破|站上|跌至|升至|降至|回落至)|"
         r"(?:美元|元)\s*/\s*(?:桶|盎司|吨)|每(?:桶|盎司|吨)", 1.5),
        # Commodity nouns: with a price threshold ("copper above 10,000 USD per tonne") a market question.
        (r"\b(?:copper|alumini?um|aluminum|nickel|zinc|silver|gold|platinum|palladium|iron ore|lithium carbonate|"
         r"crude|wheat|corn|soybeans?)\b", 1.0),
        (r"股价|市值|估值|股指|(?:上证|深证|沪深\s*300|中证|恒生|标普|纳斯达克|道琼斯|日经)(?:\s*\d+)?\s*指数|"
         r"收益率|国债收益率|汇率|人民币(?:汇率|兑|对美元|升值|贬值)|离岸人民币|比特币|金价|油价|大宗商品价格|首发上市|"
         r"布伦特|(?:铜|铝|镍|锌|锂|银|铁矿石?|煤|大豆|小麦|玉米|原油|黄金|白银|碳酸锂)(?:价|价格|均价|期货)|"
         r"上市(?:首日|发行|审核|申请|辅导|募资)|(?:登陆|登录)\s*(?:a\s*股|港股|美股|科创板|创业板|北交所|主板)|"
         r"\bipo\b|\ba\s*股|港股|美股|违约|股市|债市", 2.0),
    ),
}
_FORECAST_RE = re.compile(
    r"\bwill\b|\bby (?:the end of )?20\d\d|\bprobabilit|\bchance|\blikel(?:y|ihood)|forecast|predict|odds|"
    r"\boutlook|会不会|是否|能否|概率|可能性|预测|预判|研判|到\s*20\d\d|20\d\d\s*年(?:前|底|末)|会.*吗", re.I)

_COMPILED_ROUTES = {name: tuple((re.compile(pattern, re.I), weight) for pattern, weight in rules)
                    for name, rules in _ROUTES.items()}
_COMPILED_SECTORS = {key: re.compile(pattern, re.I) for key, pattern in _SECTOR_TERMS.items()}
_INDUSTRY_STRONG_RE = re.compile(_INDUSTRY_STRONG, re.I)
_INDUSTRY_WEAK_RE = re.compile(_INDUSTRY_WEAK, re.I)
_FUTURE_RE = re.compile(_FUTURE_TERMS, re.I)


@dataclass(frozen=True)
class Route:
    name: str
    score: float
    reasons: tuple[str, ...]


def _hits(pattern: re.Pattern, text: str) -> list[str]:
    return sorted({match.group(0).strip().lower() for match in pattern.finditer(text) if match.group(0).strip()})


def _reference_year(year: int | None) -> int:
    """The year "future" is measured from: the caller's (the run's as-of year), else today's (UTC)."""
    return int(year) if year else datetime.datetime.now(datetime.timezone.utc).year


def _future_hits(text: str, year: int | None) -> list[str]:
    """Forecast wording, deadlines that have not passed ("by 2026" in 2026) and bare
    years after the reference year.  ``text`` is already _match_text."""
    now = _reference_year(year)
    hits = set(_hits(_FUTURE_RE, text))
    for match in _DEADLINE_YEAR_RE.finditer(text):
        if int(next(group for group in match.groups() if group)) >= now:
            hits.add(" ".join(match.group(0).lower().split()))
    hits.update(found for found in _YEAR_RE.findall(text) if int(found) > now)
    return sorted(hits)


def _industry_hits(text: str, sectors: Sequence[str]) -> tuple[list[str], list[str]]:
    """``(strong, all)`` industry terms of ``text``; weak terms count only beside a sector."""
    strong = _hits(_INDUSTRY_STRONG_RE, text)
    return strong, strong + (_hits(_INDUSTRY_WEAK_RE, text) if sectors else [])


def detect_sectors(text: str, limit: int = MAX_KIQ_SECTORS) -> list[str]:
    """Sector-adapter keys whose terms the text names, most hits first (ties: table order)."""
    text = _match_text(text)
    scored = []
    for order, (key, pattern) in enumerate(_COMPILED_SECTORS.items()):
        hits = _hits(pattern, text)
        if hits:
            scored.append((-len(hits), order, key))
    return [key for _, _, key in sorted(scored)[:limit]]


def score_skills(text: str, *, year: int | None = None) -> list[Route]:
    """Every domain skill whose triggers the text names, with its score (unordered,
    unfiltered).  ``year`` is the reference year of the future test (default: today's)."""
    text = _match_text(text)
    routes: list[Route] = []
    sectors = detect_sectors(text, limit=len(_COMPILED_SECTORS))
    _, industry = _industry_hits(text, sectors)
    future = _future_hits(text, year)
    sector_score = 1.5 + 0.25 * (len(sectors) - 1) if sectors else 0.0
    for name in SKILL_NAMES:
        if name == CROSS_CUTTING:
            continue
        score, reasons = 0.0, []
        for pattern, weight in _COMPILED_ROUTES.get(name, ()):
            hits = _hits(pattern, text)
            if hits:
                score += weight + 0.25 * (len(hits) - 1)
                reasons += hits[:3]
        if name in INDUSTRY_SKILLS:
            score += sector_score
            reasons += [f"sector:{key}" for key in sectors[:2]]
        if name == "industry-research" and industry:
            score += 1.5 + 0.25 * (len(industry) - 1) + (0.5 if sectors else 0.0)
            reasons = industry[:3] + reasons
        if name == "industry-forecasting":
            if (industry or sectors) and future:
                score += 1.5 + (1.5 if industry else 0.0)
                reasons += future[:2]
            else:
                score = 0.0
        if score > 0:
            routes.append(Route(name, round(score, 2), tuple(dict.fromkeys(reasons))))
    return routes


def route(text: str, *, limit: int = MAX_PLAN_SKILLS, year: int | None = None) -> list[Route]:
    """Ranked skills for a research question: at most MAX_DOMAIN_SKILLS domain skills
    scoring at least ROUTE_MIN_SCORE, then the cross-cutting reference-class skill for
    any forecast question (or when a domain skill was routed).

    Ranking: score, then registry order; but when the question names no strong industry
    term, the industry skills (matched by a sector noun alone) rank after any routed
    non-industry skill, so "Which US AI lab will lead", "tariffs on Chinese EVs" or
    "Brent above 90 USD" lead with their own domain and keep the industry method second."""
    text = _match_text(text)
    scored = score_skills(text, year=year)
    order = {name: index for index, name in enumerate(SKILL_NAMES)}
    strong, _ = _industry_hits(text, ())
    eligible = [r for r in scored if r.score >= _ROUTE_MIN_SCORE]
    other_domain = any(r.name not in INDUSTRY_SKILLS for r in eligible)

    def rank(r: Route) -> tuple:
        return (bool(r.name in INDUSTRY_SKILLS and other_domain and not strong), -r.score, order[r.name])

    ranked = sorted(eligible, key=rank)
    domain = ranked[:MAX_DOMAIN_SKILLS]
    # A target-year industry question keeps both industry skills (outlook + baseline)
    # unless a second domain claims the slot.
    names = [r.name for r in domain]
    if "industry-forecasting" in names and "industry-research" not in names and len(domain) < MAX_DOMAIN_SKILLS:
        domain.append(next((r for r in scored if r.name == "industry-research"),
                           Route("industry-research", 0.0, ("baseline of the industry outlook",))))
    # A who-leads question keeps its landscape skill even when both industry skills score higher:
    # it replaces the industry baseline (the outlook skill covers the market).
    landscape = next((r for r in ranked if r.name == "competitive-landscape-forecasting"), None)
    if landscape and landscape not in domain and any(r.name == "industry-research" for r in domain):
        domain = sorted((landscape if r.name == "industry-research" else r for r in domain), key=rank)
    routes = list(domain)
    forecast = _hits(_FORECAST_RE, text)
    if forecast or routes:
        routes.append(Route(CROSS_CUTTING, 1.0, tuple(forecast[:3]) or ("paired with a domain skill",)))
    return routes[:limit]


def _skill_name(item: Any) -> str:
    """A planner-written skill name in registry form ("Macro_Research " → "macro-research")."""
    if isinstance(item, Mapping):
        item = item.get("name")
    return re.sub(r"[\s_]+", "-", str(item or "").strip().lower())


def choose_plan_skills(requested: Any, candidates: Sequence[str], available: Iterable[str]) -> tuple[list[str], str]:
    """``(skills, source)``: the planner's valid choice or, when it named no available
    domain skill, the router candidates.

    The choice keeps request order, drops unknown and repeated names, accepts a list or
    a comma-separated string, and holds at most MAX_PLAN_SKILLS names with the
    cross-cutting skill last (kept when the planner or the router named it).  A choice of
    the cross-cutting skill alone is no domain opinion: the router's domain skills stay."""
    known = set(available)
    if isinstance(requested, str):
        requested = re.split(r"[,;\s]+", requested)
    chosen: list[str] = []
    for item in requested if isinstance(requested, (list, tuple)) else []:
        name = _skill_name(item)
        if name in known and name not in chosen:
            chosen.append(name)
    domain = primary_skills(chosen)
    if not domain:
        routed = [name for name in candidates if name in known][:MAX_PLAN_SKILLS]
        if CROSS_CUTTING in chosen and CROSS_CUTTING not in routed:
            routed = routed[:MAX_PLAN_SKILLS - 1] + [CROSS_CUTTING]
        return routed, ("planner" if chosen and not primary_skills(routed) else "router")
    cross = CROSS_CUTTING in known and (CROSS_CUTTING in chosen or CROSS_CUTTING in candidates)
    return domain[:MAX_PLAN_SKILLS - cross] + ([CROSS_CUTTING] if cross else []), "planner"


def primary_skills(skills: Sequence[str]) -> list[str]:
    """The plan's domain skills in order (the cross-cutting skill excluded)."""
    return [name for name in skills if name != CROSS_CUTTING]


def kiq_skills(plan_skills: Sequence[str], kiq_text: str, *, kind: str, base_rate: bool,
               year: int | None = None) -> list[str]:
    """The (at most MAX_KIQ_SKILLS) plan skills whose Investigate method a KIQ gets.

    The plan's domain skills are ranked by how strongly the KIQ's own words route to
    them (ties: plan order).  The best one always comes first, so a KIQ that matches
    nothing gets the plan's primary skill; a second one only when the KIQ routes to it
    too, and never a second industry skill (the pair shares one evidence path and the
    sector adapters).  Every ``kind`` gets a method: each domain skill's Investigate
    section carries its own actor-record rules.  A base-rate KIQ is led by the
    cross-cutting reference-class skill, with the best domain skill second (see
    :func:`kiq_block` for how an industry skill renders beside another method)."""
    del kind  # part of the engines' call signature; selection no longer depends on it
    domain = primary_skills(plan_skills)
    scores = {r.name: r.score for r in score_skills(kiq_text, year=year)}
    ranked = sorted(domain, key=lambda name: (-scores.get(name, 0.0), domain.index(name)))
    chosen: list[str] = []
    for name in ranked:
        if chosen and scores.get(name, 0.0) < _ROUTE_MIN_SCORE:
            break
        if name in INDUSTRY_SKILLS and any(other in INDUSTRY_SKILLS for other in chosen):
            continue
        chosen.append(name)
        if len(chosen) == MAX_KIQ_SKILLS:
            break
    if base_rate and CROSS_CUTTING in plan_skills:
        chosen = [CROSS_CUTTING] + chosen[:MAX_KIQ_SKILLS - 1]
    return chosen


# ============================================================================ prompt blocks
# Engine text (trusted, never wrapped as untrusted data).  Headers are constant so the
# blocks are recognisable in prompts and tests.

PLAN_HEADER = ("METHOD SKILLS (engine guidance for this question): shape the KIQs, data_needs, sections and "
               "scenario frame with the planning notes below, within the JSON shape and counts above. Merge their "
               "suggested KIQs to fit the KIQ limit, keeping a base-rate KIQ; add no executive summary, "
               "introduction or references section. The weights are fixed for the whole run: set them "
               "base-rate-first.")
KIQ_HEADER = ("METHOD for this KIQ (engine guidance). The budget, tools and notes format above still bind: the "
              "first method leads, a second adds only the checks the budget leaves room for. A method's record "
              "format is the content of a Findings bullet, which still ends with its [S<n>] marker and "
              "(VERIFIED|REPORTED) tag. A VERIFIED finding carries only numbers its fetched page prints: put a "
              "proposed threshold, your own ratio, gap or count in a separate REPORTED finding with the marker of "
              "the data it rests on.")
GAP_HEADER = ("METHOD COVERAGE CHECKS (engine guidance). Judge each from the coverage list and the brief above: a "
              "check is open only when no KIQ asks it or its KIQ lists it as an open question. Propose a follow-up "
              "only for an open check whose answer would change the forecast:")
WRITER_HEADER = ("METHOD: report contract for this question type (engine guidance). Build only the exhibits and "
                 "analysis that belong to the sections you are writing, each once (the other sections' writers "
                 "build theirs); fill them only with cited evidence and leave out an exhibit the evidence cannot "
                 "fill:")
SUMMARY_HEADER = ("METHOD conventions for this question type (engine guidance): use only their definitions and "
                  "labels (what \"by YEAR\" means, forecast vs projection vs target); build no table or exhibit "
                  "in the summary:")
NO_DATA_NOTE = "Official-data tools are not available in this run: use the web for the statistics named below."
MENU_SCOPE_CHARS = 140


def _scope(mandate: str, limit: int = MENU_SCOPE_CHARS) -> str:
    """A skill's scope for the menu: its mandate's first sentence up to a colon, within
    ``limit`` characters (cut at a clause or word end, see :func:`_cap`)."""
    first = re.split(r"(?<=[.!?。])\s", mandate.strip(), maxsplit=1)[0] if mandate else ""
    return _cap(first.split(": ", 1)[0], limit).rstrip(" .,;:。")


def menu_lines(library: SkillLibrary, shown: Iterable[str] = ()) -> list[str]:
    """One line per available skill: name and scope (see :func:`_scope`); a skill in
    ``shown`` (its Plan section is already in the prompt) points there instead."""
    shown = set(shown)
    return [f"- {name}: " + ("(planning notes above)" if name in shown else _scope(library.skills[name].mandate))
            for name in library.names]


def planning_block(library: SkillLibrary, candidates: Sequence[str]) -> str:
    """Planner suffix: the candidates' Plan sections, the menu, and the optional
    ``skills`` key.  '' when no candidate is available."""
    names = [name for name in candidates if library.get(name)]
    if not names:
        return ""
    parts = ["", PLAN_HEADER]
    for name in names:
        parts += ["", f"### {name}", library.skills[name].section("Plan")]
    parts += ["", "Method skills menu:", *menu_lines(library, names),
              f"Optional JSON key \"skills\": [...]: 1 to {MAX_PLAN_SKILLS} menu names that fit the question, "
              "domain skills first, keeping reference-class-forecasting for any dated forecast; omit it to keep "
              "the engine's match."]
    return "\n".join(parts)


def kiq_block(library: SkillLibrary, skills: Sequence[str], sectors: Sequence[str], *,
              data_enabled: bool) -> str:
    """KIQ-task suffix: the Investigate sections of ``skills`` and, for an industry skill,
    up to MAX_KIQ_SECTORS matching sector adapters.  An industry skill paired with another
    method (the reference-class skill of a base-rate KIQ, or a landscape, policy or market
    skill the KIQ also names) contributes its sector adapters instead of its Investigate
    text: they carry the sector's series, definitions and traps, and one KIQ task then holds
    at most two method texts (about 5,400 characters with the header).  '' when nothing
    applies."""
    names = [name for name in skills if library.get(name)][:MAX_KIQ_SKILLS]
    if not names:
        return ""
    methods = [name for name in names if name not in INDUSTRY_SKILLS] or names[:1]
    parts = ["", KIQ_HEADER]
    if not data_enabled:
        parts.append(NO_DATA_NOTE)
    for name in methods:
        parts += [f"[{name}]", library.skills[name].section("Investigate")]
    if any(name in INDUSTRY_SKILLS for name in names):
        for key in [key for key in sectors if key in library.sectors][:MAX_KIQ_SECTORS]:
            parts += [f"[sector: {key}]", library.sectors[key]]
    return "\n".join(parts)


def gaps_block(library: SkillLibrary, skills: Sequence[str]) -> str:
    names = [name for name in skills if library.get(name)]
    if not names:
        return ""
    parts = ["", GAP_HEADER]
    for name in names:
        parts += [f"[{name}]", library.skills[name].section("Gaps")]
    return "\n".join(parts)


def writer_block(library: SkillLibrary, skills: Sequence[str], *, summary: bool = False) -> str:
    """Writer suffix: the Synthesize sections of ``skills``; ``summary`` frames them for the
    executive summary (conventions only, no exhibits)."""
    names = [name for name in skills if library.get(name)][:MAX_WRITER_SKILLS + 1]
    if not names:
        return ""
    parts = ["", SUMMARY_HEADER if summary else WRITER_HEADER]
    for name in names:
        parts += [f"[{name}]", library.skills[name].section("Synthesize")]
    return "\n".join(parts)


def writer_skills(plan_skills: Sequence[str], *, scenario: bool) -> list[str]:
    """Synthesize sections for a writer: the primary domain skills (at most
    MAX_WRITER_SKILLS) and, for the scenario section, the reference-class skill."""
    names = primary_skills(plan_skills)[:MAX_WRITER_SKILLS]
    if scenario and CROSS_CUTTING in plan_skills:
        names.append(CROSS_CUTTING)
    return names


def read_file_pointers(library: SkillLibrary, skills: Sequence[str], *, mount: str = "/mnt/skills/public") -> str:
    """Legacy planning-pass block: which method skills to load with read_file."""
    names = [name for name in skills if library.get(name)]
    if not names:
        return ""
    lines = ["METHOD SKILLS for this question (domain methodology; load each with read_file before decomposing "
             "the KIQs, then follow its Plan and Investigate sections in the working passes and its Synthesize "
             "section in the final dossier):"]
    lines += [f"- {name}: read_file {mount}/{name}/SKILL.md" for name in names]
    return "\n".join(lines)


def describe(library: SkillLibrary | None, skills: Sequence[str], source: str,
             sectors: Sequence[str]) -> dict[str, Any]:
    """meta record of a run's method skills."""
    if library is None:
        return {"status": "unavailable"}
    return {"status": "enabled", "skills": list(skills), "source": source, "sectors": list(sectors),
            "hashes": library.fingerprint(skills), **({"sector_hash": library.sector_hash}
                                                      if library.sector_hash and sectors else {})}
