/* Tiny i18n for the DeepAgentForecast demo site.
 * Usage: elements carry data-i18n="key" (textContent) or data-i18n-html="key"
 * (innerHTML, for strings with markup). drfT(key) for JS strings.
 * Language persists in localStorage('drf_lang'); default follows the browser. */
(function () {
  var STRINGS = {
    /* ——— shared nav / footer ——— */
    'nav.demos':        { en: 'Live demos', zh: '在线演示' },
    'nav.video':        { en: 'Video', zh: '演示视频' },
    'nav.how':          { en: 'How it works', zh: '工作原理' },
    'nav.alldemos':     { en: 'All demos', zh: '全部演示' },
    'footer.line':      { en: 'Unedited output of real end-to-end runs', zh: '真实端到端运行的未编辑产出' },

    /* ——— index hero ——— */
    'hero.tag':         { en: 'one prompt · research to forecast', zh: '一句话 · 从调研到预测' },
    'hero.h1a':         { en: 'Ask one question.', zh: '输入一个问题。' },
    'hero.h1b':         { en: 'Auto-research, build a world, simulate the future.', zh: '自动调研、构建世界、推演未来。' },
    'hero.lead':        { en: 'A deep-research agent (DeerFlow) searches the web and builds an evidence-grounded dossier; the system constructs a local temporal knowledge graph (Graphiti), generates digital personas for the real-world actors it found, runs a multi-agent population simulation (OASIS, dual-platform), and a report agent synthesizes the forecast. The pages below show every stage of real runs, unedited.',
                          zh: '深度研究 Agent（DeerFlow）联网搜集证据并写出研究档案；系统据此构建本地时序知识图谱（Graphiti）、为调研发现的真实行动者生成数字人格、运行多智能体群体模拟（OASIS 双平台），最终由报告 Agent 综合产出预测。下面的页面展示了真实运行的每一个阶段，未经编辑。' },
    'hero.cta':         { en: 'View the demo forecasts ↓', zh: '查看演示预测 ↓' },
    'hero.run':         { en: 'Run it yourself', zh: '自己跑一个' },

    /* ——— index demos section ——— */
    'demos.h2':         { en: 'Live demos — real end-to-end runs', zh: '在线演示 —— 真实端到端运行' },
    'demos.sub':        { en: 'Each card is one full pipeline run. Click through to walk the whole workflow: deep-research log → research dossier → ontology → knowledge graph → simulated forum → final forecast.',
                          zh: '每张卡片都是一次完整的管线运行。点进去可以走完整个工作流：深度研究日志 → 研究档案 → 本体 → 知识图谱 → 模拟论坛 → 最终预测报告。' },
    'demos.completed':  { en: '● completed · full pipeline', zh: '● 已完成 · 完整管线' },
    'demos.cta':        { en: 'Walk through the run →', zh: '查看完整运行 →' },

    'card.ai.title':    { en: 'Who dominates US AI by 2030?', zh: '2030 年谁主导美国 AI？' },
    'card.ai.meta':     { en: '40-round dual-platform simulation · 42 personas · 6-section forecast', zh: '40 轮双平台模拟 · 42 个人格 · 6 章预测报告' },
    'card.ev.title':    { en: 'Global EV industry through 2035', zh: '2035 年前全球电动汽车产业' },
    'card.ev.meta':     { en: '19-round dual-platform simulation · 12 personas · 119-node knowledge graph · 12 binary forecasts & 5 mutually exclusive scenarios · 98.9% audited quantitative-citation coverage', zh: '19 轮双平台模拟 · 12 个人格 · 119 节点知识图谱 · 12 项二元预测与 5 个互斥情景 · 定量声明引用覆盖率经审计达 98.9%' },
    'card.ru.title':    { en: 'How and when does the Russia–Ukraine war end?', zh: '俄乌战争如何终结、何时终结？' },
    'card.ru.meta':     { en: '36 personas · multi-scenario endgame analysis grounded in a 40K-char research dossier', zh: '36 个人格 · 基于 4 万字研究档案的多情景终局推演' },
    'card.semi.title':  { en: 'Global semiconductors through 2030', zh: '2030 年前全球半导体产业' },
    'card.semi.meta':   { en: '40-round dual-platform simulation · 115 personas · full value chain: memory / HBM / logic / foundry across 17 named companies', zh: '40 轮双平台模拟 · 115 个人格 · 覆盖存储 / HBM / 逻辑 / 代工全产业链与 17 家企业' },
    'card.mem.title':   { en: 'Global memory-chip market through 2030', zh: '2030 年前全球存储半导体市场' },
    'card.mem.meta':    { en: '4-round dual-platform simulation · 80 personas · DRAM / NAND / HBM competitive landscape — Samsung, SK Hynix, Micron & YMTC, AI-driven HBM demand and export controls', zh: '4 轮双平台模拟 · 80 个人格 · DRAM / NAND / HBM 竞争格局——三星、SK 海力士、美光、长江存储、AI 驱动的 HBM 需求与出口管制' },
    'card.ess.title':   { en: "China's energy storage & battery market in 2035", zh: '2035 年中国储能与电池市场' },
    'card.ess.meta':    { en: '40-round dual-platform simulation · 94 personas · grid / C&I / home storage segments, full supply chain & winners-vs-losers analysis', zh: '40 轮双平台模拟 · 94 个人格 · 大储 / 工商业 / 户储细分赛道、全产业链与赢家输家研判' },
    'card.iran.title':  { en: 'How does the 2026 US–Iran war end?', zh: '2026 年美伊战争如何收场？' },
    'card.iran.meta':   { en: '40-round dual-platform simulation · 135 personas · endgame scenarios, peace-deal terms & post-war Middle East order', zh: '40 轮双平台模拟 · 135 个人格 · 终局情景、终战协议条款与战后中东秩序重构' },
    'card.collision.title': { en: 'The Collision Decade — Modern Mercantilism × AI, 2026–2031', zh: '碰撞的十年 —— 现代重商主义 × AI（2026–2031）' },
    'card.collision.meta':  { en: '24-round dual-platform simulation · 80 personas · 13 binary forecasts & 4 scenarios · Bridgewater-style 3-part brief — tariffs, chip export controls & the AI-capex supercycle to 2031', zh: '24 轮双平台模拟 · 80 个人格 · 13 条二元预测与 4 个情景 · 桥水式三部分简报——关税、芯片出口管制与 AI 资本开支超级周期推演至 2031' },
    'card.midterms.title': { en: 'The 2026 US midterms — House & Senate control scenarios', zh: '2026 年美国中期选举 —— 参众两院控制权情景' },
    'card.midterms.meta':  { en: "36-round dual-platform simulation · 14 personas · 194-node knowledge graph · 13 binary forecasts & 4 scenarios · prediction-market-benchmarked, targeting the real next midterm, Nov 3 2026", zh: '36 轮双平台模拟 · 14 个人格 · 194 节点知识图谱 · 13 条二元预测与 4 个情景 · 对标预测市场，聚焦真实的下一次中期选举（2026 年 11 月 3 日）' },
    'card.trade.title': { en: "America's trading system in 2028 — tariffs, reshoring & the AI-productivity race", zh: '2028 年美国贸易体系 —— 关税、供应链回流与 AI 生产力竞赛' },
    'card.trade.meta':  { en: '36-round dual-platform simulation · 20 personas · 263-node knowledge graph · 11 binary forecasts & 3 scenarios — high tariffs, fragmented alliances & AI-enabled resilience through 2028', zh: '36 轮双平台模拟 · 20 个人格 · 263 节点知识图谱 · 11 条二元预测与 3 个情景——高关税、联盟分化与 AI 驱动韧性推演至 2028 年' },
    'card.storage.title': { en: 'Storage semiconductors — the 2027–2028 outlook', zh: '2027—2028 年存储半导体前景预判' },
    'card.storage.meta':  { en: '40-round dual-platform simulation · 80 personas · 213-node knowledge graph · competitive landscape, next-gen tech (HBM4E / DDR6 / CXL 4.0), supply-demand & pricing, 40-year cycle history', zh: '40 轮双平台模拟 · 80 个人格 · 213 节点知识图谱 · 厂商格局、新一代技术（HBM4E / DDR6 / CXL 4.0）、供需与价格、四十年周期史' },
    'card.cloud.title':   { en: 'Global cloud computing — the 2030 endgame', zh: '2030 年全球云计算竞争格局推演' },
    'card.cloud.meta':    { en: 'Dual-platform population simulation · 80 personas · 130-node knowledge graph · the Big Three vs. Oracle OCI, sovereign cloud & AI-capex dynamics — winners & losers to 2030', zh: '双平台群体模拟 · 80 个人格 · 130 节点知识图谱 · 三巨头与 Oracle OCI、主权云与 AI 资本开支博弈——2030 年赢家与输家' },

    /* ——— index video / screenshots / how ——— */
    'video.h2':         { en: '47-second demo', zh: '47 秒演示' },
    'video.sub':        { en: 'One prompt → research console → knowledge graph → live simulation feed → forecast.', zh: '一句提示词 → 研究控制台 → 知识图谱 → 实时模拟信息流 → 预测报告。' },
    'shots.h2':         { en: 'Screenshots', zh: '截图' },
    'how.h2':           { en: 'How it works', zh: '工作原理' },
    'how.s1':           { en: 'research — DeerFlow deep-research agent searches the web, extracts key actors (role / stance / influence) and writes a cited dossier', zh: 'research（深度研究）—— DeerFlow 联网搜索，提取关键行动者（角色/立场/影响力），写出带引用的研究档案' },
    'how.s2':           { en: 'ontology — an LLM derives entity & relation types from the dossier and your question', zh: 'ontology（本体生成）—— LLM 依据研究档案与你的问题推导实体与关系类型' },
    'how.s3':           { en: 'graph — the dossier is ingested into a local temporal knowledge graph (Graphiti, GraphRAG)', zh: 'graph（图谱构建）—— 研究档案灌入本地时序知识图谱（Graphiti，GraphRAG）' },
    'how.s4':           { en: 'prepare — researched actors become digital personas with evidence-based stances', zh: 'prepare（环境搭建）—— 调研得到的行动者成为带实证立场的数字人格' },
    'how.s5':           { en: 'run — hundreds of LLM personas interact on a simulated Twitter + Reddit (OASIS)', zh: 'run（群体模拟）—— 大量 LLM 人格在模拟的 Twitter + Reddit 上互动（OASIS）' },
    'how.s6':           { en: 'report — a tool-augmented ReAct agent queries graph + simulation and writes the forecast', zh: 'report（预测报告）—— 工具增强的 ReAct Agent 检索图谱与模拟结果并写出预测' },

    /* ——— demo viewer ——— */
    'viewer.back':      { en: '← back to demos', zh: '← 返回演示列表' },
    'viewer.prompt':    { en: 'Prompt', zh: '提示词' },
    'tab.log':          { en: '① Deep research', zh: '① 深度研究' },
    'tab.dossier':      { en: '② Research dossier', zh: '② 研究档案' },
    'tab.ontology':     { en: '③ Ontology', zh: '③ 本体生成' },
    'tab.graph':        { en: '④ Knowledge graph', zh: '④ 知识图谱' },
    'tab.forum':        { en: '⑤ Simulated forum', zh: '⑤ 模拟论坛' },
    'tab.report':       { en: '⑥ Forecast report', zh: '⑥ 预测报告' },
    'viewer.loading':   { en: 'Loading…', zh: '加载中…' },
    'viewer.loadfail':  { en: 'Failed to load:', zh: '加载失败：' },
    'viewer.unknown':   { en: 'Unknown demo run.', zh: '未知的演示运行。' },
    'viewer.backlist':  { en: 'Back to the demo list →', zh: '返回演示列表 →' },

    'log.intro':        { en: 'Live console of the DeerFlow deep-research subprocess — every search, fetch and synthesis step of stage 1.', zh: 'DeerFlow 深度研究子进程的实时控制台 —— 阶段 1 的每一次搜索、抓取与综合。' },
    'log.prompt':       { en: 'Initial research / forecast prompt', zh: '初始研究 / 预测提示词' },
    'log.history':      { en: 'Complete recorded research-event history', zh: '完整的已记录研究事件历史' },
    'log.historyPartial': { en: 'Recorded history · completeness not re-verified', zh: '已记录历史 · 完整性未经重新验证' },
    'log.lines':        { en: 'lines', zh: '行' },
    'log.sources':      { en: 'log sources', zh: '个日志源' },
    'log.complete':     { en: 'all recorded events', zh: '全部已记录事件' },

    'dossier.actors':   { en: 'Researched actors', zh: '调研得到的行动者' },
    'dossier.actorsub': { en: 'Extracted by the research agent; these seed the ontology, the personas and the simulation’s initial posts.', zh: '由研究 Agent 提取；它们为本体、人格与模拟初始帖子提供种子。' },
    'dossier.brief':    { en: 'Research brief', zh: '研究简报' },
    'dossier.sources':  { en: 'Cited sources', zh: '引用来源' },
    'actor.role':       { en: 'Role', zh: '角色' },
    'actor.stance':     { en: 'Stance', zh: '立场' },
    'actor.influence':  { en: 'influence', zh: '影响力' },
    'dossier.noactors': { en: 'This run predates structured actor extraction — the dossier below was the seeding input.', zh: '这次运行早于结构化行动者提取功能 —— 下方研究档案即为种子输入。' },

    'onto.intro':       { en: 'Stage 2: an LLM reads the dossier and your question, then derives the entity and relation types the knowledge graph will use.', zh: '阶段 2：LLM 阅读研究档案与你的问题，推导出知识图谱将使用的实体与关系类型。' },
    'onto.summary':     { en: 'Analysis summary', zh: '分析摘要' },
    'onto.entities':    { en: 'Entity types', zh: '实体类型' },
    'onto.edges':       { en: 'Relation types', zh: '关系类型' },
    'onto.attrs':       { en: 'attributes', zh: '属性' },
    'onto.examples':    { en: 'e.g.', zh: '例如' },

    'graph.intro':      { en: 'Stage 3: the dossier is chunked into a local temporal knowledge graph (Graphiti). Drag to pan, scroll to zoom, hover a node or edge for its extracted summary/fact.', zh: '阶段 3：研究档案分块灌入本地时序知识图谱（Graphiti）。拖拽平移、滚轮缩放，悬停节点或边可查看抽取出的摘要/事实。' },
    'graph.nodes':      { en: 'entities', zh: '个实体' },
    'graph.edges':      { en: 'relations', zh: '条关系' },
    'graph.rebuilt':    { en: 'Rebuilt from the run’s saved dossier + ontology.', zh: '由该次运行保存的研究档案 + 本体重建。' },
    'graph.unavailable': { en: 'The knowledge graph for this run is unavailable.', zh: '该次运行的知识图谱暂不可用。' },

    'forum.intro':      { en: 'Stage 5: digital personas post, reply and vote on a simulated Twitter + Reddit. This is the raw action feed of the run.', zh: '阶段 5：数字人格在模拟的 Twitter + Reddit 上发帖、回复、点赞。下面是这次运行的原始动作流。' },
    'forum.posts':      { en: 'posts', zh: '帖子' },
    'forum.comments':   { en: 'comments', zh: '评论' },
    'forum.likes':      { en: 'likes', zh: '点赞' },
    'forum.round':      { en: 'round', zh: '轮次' },
    'forum.comment':    { en: 'replied', zh: '回复' },
    'forum.empty':      { en: 'No feed recorded for this platform.', zh: '该平台没有记录到动作流。' },

    'report.intro':     { en: 'Stage 6: the final forecast, written by a tool-augmented ReAct agent that queried both the knowledge graph and the simulation.', zh: '阶段 6：最终预测报告，由同时检索知识图谱与模拟结果的工具增强 ReAct Agent 撰写。' },
    'doclang.report':   { en: 'Report language', zh: '报告语言' },
    'doclang.dossier':  { en: 'Dossier language', zh: '档案语言' },
    'doclang.original': { en: 'Original', zh: '原文' },
    'doclang.translated.en': { en: 'Translated from the English original · every number, date and citation checked against it', zh: '译自英文原文 · 所有数字、日期与引用均已与原文逐一核对' },
    'doclang.translated.zh': { en: 'Translated from the Chinese original · every number, date and citation checked against it', zh: '译自中文原文 · 所有数字、日期与引用均已与原文逐一核对' },

    'run.ai.title':     { en: 'Who dominates US AI by 2030?', zh: '2030 年谁主导美国 AI？' },
    'run.ev.title':     { en: 'Global EV industry through 2035', zh: '2035 年前全球电动汽车产业' },
    'run.ru.title':     { en: 'How and when does the Russia–Ukraine war end?', zh: '俄乌战争如何终结、何时终结？' },
    'run.semi.title':   { en: 'Global semiconductors through 2030', zh: '2030 年前全球半导体产业' },
    'run.mem.title':    { en: 'Global memory-chip market through 2030', zh: '2030 年前全球存储半导体市场' },
    'run.ess.title':    { en: "China's energy storage & battery market in 2035", zh: '2035 年中国储能与电池市场' },
    'run.iran.title':   { en: 'How does the 2026 US–Iran war end?', zh: '2026 年美伊战争如何收场？' },
    'run.storage.title': { en: 'Storage semiconductors — the 2027–2028 outlook', zh: '2027—2028 年存储半导体前景预判' },
    'run.cloud.title':   { en: 'Global cloud computing — the 2030 endgame', zh: '2030 年全球云计算竞争格局推演' },
    'run.collision.title': { en: 'The Collision Decade — Modern Mercantilism × AI, 2026–2031', zh: '碰撞的十年 —— 现代重商主义 × AI（2026–2031）' },
    'run.midterms.title': { en: 'The 2026 US midterms — House & Senate control scenarios', zh: '2026 年美国中期选举 —— 参众两院控制权情景' },
    'run.trade.title': { en: "America's trading system in 2028 — tariffs, reshoring & the AI-productivity race", zh: '2028 年美国贸易体系 —— 关税、供应链回流与 AI 生产力竞赛' },
    'run.grid.title': { en: 'Global grid-scale energy storage through 2040', zh: '2040 年前全球电网级储能产业' },
    'run.dc.title': { en: 'Global data centers to 2030 — the US–China compute race', zh: '2030 年前全球数据中心市场 —— 中美算力竞赛' },
    'run.quantum.title': { en: 'Quantum computing to 2040 — the US, China & EU race', zh: '2040 年前的量子计算 —— 美中欧竞速' },
    'card.quantum.title': { en: 'Quantum computing to 2040 — the US, China & EU race', zh: '2040 年前的量子计算 —— 美中欧竞速' },
    'card.quantum.meta': { en: '29-round calendar simulation · 18 personas · 137-node knowledge graph · 10 binary forecasts & 5 scenarios — superconducting vs. trapped-ion, neutral-atom, photonic, spin & topological qubits; US / China / EU strategy, funding & export controls; fault-tolerance timelines and the post-quantum-cryptography window, run end-to-end on GLM-5.3 · report and dossier in English & Chinese', zh: '29 轮日历模拟 · 18 位人格 · 137 节点知识图谱 · 10 条二元预测与 5 个情景 —— 超导、离子阱、中性原子、光量子、硅自旋与拓扑量子比特路线对比；美中欧战略、资金与出口管制；容错时间表与后量子密码迁移窗口，全程由 GLM-5.3 完成 · 报告与研究档案均提供中英双语' },
    'card.grid.title': { en: 'Global grid-scale energy storage through 2040', zh: '2040 年前全球电网级储能产业' },
    'card.dc.title': { en: 'Global data centers to 2030 — the US–China compute race', zh: '2030 年前全球数据中心市场 —— 中美算力竞赛' },
    'card.grid.meta': { en: '29-round calendar simulation · 19 personas · 183-node knowledge graph · 11 binary forecasts & 5 scenarios — LFP vs. sodium-ion, flow, thermal, CAES & long-duration routes across 8 regions, with an additive decision-channel simulation that moved the base case to LDES-Diversified', zh: '29 轮日历模拟 · 19 位人格 · 183 节点知识图谱 · 11 条二元预测与 5 个情景 —— 磷酸铁锂对钠离子、液流、热储、压缩空气与长时储能路线，覆盖 8 大区域；决策通道模拟真实改变了预测，将基准情景移至「长时储能多元化」' },
    'card.dc.meta': { en: '17-round calendar simulation · 18 personas · 107-node knowledge graph · 14 binary forecasts & 5 scenarios — revenue/CAGR & IT-capacity outlook, colocation/hyperscale/enterprise/edge split, power & cooling constraints, and the US–China compute race, run end-to-end on GLM-5.3', zh: '17 轮日历模拟 · 18 人格 · 107 节点知识图谱 · 14 条二元预测与 5 情景 —— 营收/CAGR 与 IT 装机容量展望、托管/超大规模/企业级/边缘细分、电力与散热约束、中美算力竞赛，全程由 GLM-5.3 线性研究引擎完成' },
  };

  var lang = null;
  try { lang = localStorage.getItem('drf_lang'); } catch (e) { /* noop */ }
  if (lang !== 'en' && lang !== 'zh') {
    lang = (navigator.language || '').toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en';
  }

  function t(key) {
    var s = STRINGS[key];
    if (!s) return key;
    return s[lang] || s.en;
  }

  function apply() {
    document.documentElement.lang = (lang === 'zh') ? 'zh-CN' : 'en';
    var els = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < els.length; i++) els[i].textContent = t(els[i].getAttribute('data-i18n'));
    var toggles = document.querySelectorAll('.lang-toggle');
    for (var j = 0; j < toggles.length; j++) toggles[j].textContent = (lang === 'zh') ? 'EN' : '中文';
  }

  function setLang(next) {
    lang = next;
    try { localStorage.setItem('drf_lang', lang); } catch (e) { /* noop */ }
    apply();
    document.dispatchEvent(new CustomEvent('drf:lang', { detail: lang }));
  }

  window.drfT = t;
  window.drfLang = function () { return lang; };
  window.drfApplyI18n = apply;

  document.addEventListener('DOMContentLoaded', function () {
    apply();
    var toggles = document.querySelectorAll('.lang-toggle');
    for (var i = 0; i < toggles.length; i++) {
      toggles[i].addEventListener('click', function () { setLang(lang === 'zh' ? 'en' : 'zh'); });
    }
  });
})();
