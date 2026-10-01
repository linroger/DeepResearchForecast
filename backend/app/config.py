"""
配置管理
统一从项目根目录的 .env 文件加载配置
"""

import os
import threading
from dotenv import load_dotenv

try:
    from .config_audit import ERROR, WARNING, Issue, audit_env, extract_knobs, sanitize_numeric_env
except ImportError:
    # Loaded by path outside the app package (tests exec a private copy of this file
    # with spec_from_file_location): load the stdlib-only audit module beside it.
    import importlib.util as _importlib_util
    _audit_spec = _importlib_util.spec_from_file_location(
        '_drf_config_audit', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_audit.py'))
    _config_audit = _importlib_util.module_from_spec(_audit_spec)
    _audit_spec.loader.exec_module(_config_audit)
    ERROR, WARNING, Issue = _config_audit.ERROR, _config_audit.WARNING, _config_audit.Issue
    audit_env, extract_knobs = _config_audit.audit_env, _config_audit.extract_knobs
    sanitize_numeric_env = _config_audit.sanitize_numeric_env

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

# 测试隔离：backend/tests/conftest.py 在导入 app 之前设置 DRF_TEST_PROCESS=1。开发者本机的
# 根 .env 以 override=True 加载，会把生产旋钮（如 RESEARCH_ENGINE、REPORT_PUBLISH_GATE_*、
# SIM_RESUME）泄漏进 pytest 进程，使测试结果随本机配置漂移。测试进程一律不加载 .env，
# 各旋钮取代码默认值，需要特定值的测试显式 monkeypatch。
if os.environ.get('DRF_TEST_PROCESS') == '1':
    pass
elif os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)

# INFRA-14 config audit (app/config_audit.py).  The knob table is parsed once from this
# file's source.  Before class Config reads anything, a blank, unparseable or non-finite
# int/float value is popped from os.environ, so its code default applies and the import
# never crashes; each one stays an error in CONFIG_IMPORT_ISSUES (see Config.config_issues).
# An unreadable source (a bytecode-only deployment) only disables the audit.
try:
    CONFIG_KNOBS = extract_knobs(__file__)
except (OSError, SyntaxError, ValueError) as _audit_exc:
    CONFIG_KNOBS = {}
    CONFIG_IMPORT_ISSUES = [Issue(WARNING, 'CONFIG_STRICT_VALIDATION',
                                  f'config audit unavailable: cannot parse config.py ({_audit_exc})')]
else:
    CONFIG_IMPORT_ISSUES = sanitize_numeric_env(os.environ, CONFIG_KNOBS)


class Config:
    """Flask配置类"""
    
    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    # 默认关闭 debug：开发期显式设 FLASK_DEBUG=true。debug 模式有两个生产隐患——
    # (1) Werkzeug 调试器暴露在 0.0.0.0（局域网可触发任意代码执行）；
    # (2) 自动 reloader 会在代码变动时重启进程，杀死在飞的研究/模拟管线。
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False

    # —— API 暴露面收敛（EXECPLAN2 F-13-0 / F-13-2）——
    # 默认仅环回可达：未配置令牌时，非环回来源一律拒绝（fail-closed）。
    # 配置 APP_API_TOKEN 后，所有 /api/* 变更请求需带 X-API-Token 头（常量时间比较）。
    APP_API_TOKEN = os.environ.get('APP_API_TOKEN', '').strip()
    # 允许的 CORS 来源（逗号分隔）。默认仅本机前端开发端口；设为 '*' 可恢复旧的全开行为。
    APP_CORS_ORIGINS = os.environ.get(
        'APP_CORS_ORIGINS',
        'http://localhost:3000,http://127.0.0.1:3000,http://localhost:5001,http://127.0.0.1:5001',
    ).strip()
    # 连通性/研究子进程发起的出站请求是否禁止私网/环回地址（暴露到环回之外时建议开启）。
    APP_BLOCK_PRIVATE_URLS = os.environ.get('APP_BLOCK_PRIVATE_URLS', 'False').strip().lower() == 'true'
    # DNS-rebinding guard (INFRA-10): a request is trusted without a token because it
    # arrives over loopback only when its Host header also names this machine
    # (localhost / 127.0.0.1 / ::1, port ignored). A web page whose own domain resolves
    # to 127.0.0.1 sends that domain as Host and gets 403. Default on is safe: the local
    # frontend (Vite proxy with changeOrigin -> Host localhost:5001) and direct
    # localhost / 127.0.0.1 access keep working; token-authenticated requests are
    # unaffected. Set false to restore the legacy Host-agnostic loopback trust.
    # Parsed fail-closed, unlike the usual `== 'true'` knobs: only an explicit
    # false/0/no/off disables this guard, so 1/yes/on or a typo keeps it on.
    APP_HOST_CHECK = os.environ.get('APP_HOST_CHECK', 'true').strip().lower() not in ('false', '0', 'no', 'off')
    # Extra Host names (comma-separated, port ignored) accepted on loopback requests,
    # e.g. a custom /etc/hosts alias for this machine. Empty = only the built-in names.
    APP_ALLOWED_HOSTS = os.environ.get('APP_ALLOWED_HOSTS', '').strip()

    # 串行化 apply_provider 对共享 Config 类属性 + os.environ + .env 的读改写（EXECPLAN2 F-8-4），
    # 避免并发切换提供方时与正在读取配置的管线发生竞态/撕裂。
    _provider_lock = threading.Lock()

    # —— LLM 可观测性 / 缓存 / 预算（EXECPLAN2 I-5-0/I-5-2/I-6-0/I-5-3）——
    # 计量默认开（开销极小，仅累加计数）；缓存与预算默认关，保持现有行为。
    LLM_TELEMETRY_ENABLED = os.environ.get('LLM_TELEMETRY_ENABLED', 'True').strip().lower() == 'true'
    # 内容寻址缓存：对完全相同的 chat()/chat_json() 调用复用结果（同一管线内的抽取/分解去重）。
    # SIM-9 / CACHE-1：默认开——进程内、精确键、有界 LRU；仅确定性 attempt-0 调用命中，
    # 故多样性不受影响。跨 seed/resume/fork 的 prepare/persona/config-gen 复用收益最大。
    LLM_CACHE_ENABLED = os.environ.get('LLM_CACHE_ENABLED', 'True').strip().lower() == 'true'
    # INFRA-1：LLM 传输层严格归一化（默认开）。开启时 LLMClient 用 llm_text.strip_think 剥离
    # 推理残留（闭合 <think> 块 + 孤立 </think> 前缀 + 被 max_tokens 截断的悬空 <think>；JSON 模式下
    # 以 { / [ 开头的回复内的标签属正文、保留），并且
    # finish_reason 为 length/content_filter/error 或带悬空 <think> 的回复不写入 LLMCache
    # （否则截断回复会被永久重放）。默认开是安全的：正常回复（stop、无 think 标签）输出逐字节不变，
    # 只影响残缺回复。false 恢复旧的正则剥离 + 无条件缓存。类型化异常与 usage 竞态修复不受此开关控制。
    LLM_TRANSPORT_STRICT = os.environ.get('LLM_TRANSPORT_STRICT', 'true').strip().lower() == 'true'
    # INFRA-2：chat_json 结构化输出修复轮（默认开）。首轮回复不是单个合法 JSON 对象（解析失败，或
    # 解析出 list/标量/null）时：从 LLMCache 删掉这份坏回复，再以同温度发一次修复轮——原消息 + 坏回复
    # （assistant）+ 点名失败原因的纠正提示，两轮皆失败仍抛 ValueError；每次结局计入
    # LLMMeter 的 structured_outputs。旧行为是盲目降温 0.2 重发同一提示：LLMCache 按温度作键，
    # temperature=0 的调用方（graphiti 图谱抽取）会原样重放缓存里的坏回复，失败不可恢复。默认开
    # 是安全的：首轮即合法的 JSON 对象回复逐字节不变，只改变原本就会失败或返回非对象值的调用。
    # false 恢复旧的降温重发（且照旧可能返回非 dict）。
    LLM_JSON_REPAIR_TURN = os.environ.get('LLM_JSON_REPAIR_TURN', 'true').strip().lower() == 'true'
    # INFRA-3：推理模型把 max_tokens 全耗在推理上、回复为空且 finish_reason=length 时，chat() 立即
    # （不退避）以更大的 max_tokens 重发：max(当前×2, 1024)，封顶 PROVIDER_META 的 max_output_tokens
    # （未配置时 LLM_MAX_TOKENS_CEILING）与「上下文窗口 − prompt − 1024」，至多 LLM_MAX_ESCALATIONS 次。
    # 被拒的空回复照样计量（token 已花掉）并做预算检查（BudgetExceeded 中止，回退提供方里的超预算
    # 同样中止、不再被吞掉换成主提供方的错误）；升档耗尽（或升档后的 max_tokens 被提供方以 400 拒绝，
    # 此时按空回复处理，不让回退提供方进入确定性失败冷却）则直接转回退提供方，不再做同一请求的主
    # 提供方退避重试。默认开是安全的：只作用于原本必然失败的空截断回复，正常回复逐字节不变，花费
    # 受次数与上限约束。报告前置探测（max_tokens=64）收到这种空截断回复时视为提供方可达、放行。
    # false 恢复旧行为（同一 max_tokens 退避重试 3 次；前置探测照旧判失败）。
    LLM_LENGTH_ESCALATION = os.environ.get('LLM_LENGTH_ESCALATION', 'true').strip().lower() == 'true'
    try:
        LLM_MAX_ESCALATIONS = max(0, int(os.environ.get('LLM_MAX_ESCALATIONS', '2') or '2'))
    except ValueError:
        LLM_MAX_ESCALATIONS = 2
    try:
        LLM_MAX_TOKENS_CEILING = int(os.environ.get('LLM_MAX_TOKENS_CEILING', '32768') or '32768')
    except ValueError:
        LLM_MAX_TOKENS_CEILING = 32768
    if LLM_MAX_TOKENS_CEILING <= 0:
        LLM_MAX_TOKENS_CEILING = 32768
    # INFRA-3：预测抽取对截断的 JSON 回复失败即关闭（默认开）。回复 finish_reason=length 或 chat_json
    # 靠补括号才解析成功（json_truncation_repaired）时：骨架 draw 整个丢弃（全部丢弃 = 骨架失败，照旧
    # 回退成稿后抽取），二元抽取与市场匹配/分歧重述丢掉被截在半途的列表项（本地补括号时只在补全
    # 合上了被截断的列表项时丢，无从判断时丢最后一项），红队评审/事前验尸原样返回输入；兜底的成稿后
    # 抽取保留结果但记 quality.llm_truncation。被判截断的回复同时移出 LLMCache，重试与 resume 不会
    # 重放它。默认开是安全的：只影响被截断的回复，完整回复逐字节不变。false 恢复旧行为（截断内容
    # 照常采纳、不标注）。
    LLM_JSON_TRUNCATION_FAIL_CLOSED = os.environ.get('LLM_JSON_TRUNCATION_FAIL_CLOSED', 'true').strip().lower() == 'true'
    # INFRA-4：LLM JSON 严格数值（默认开）。_parse_json_response_ex 把 NaN / Infinity / -Infinity 与
    # 溢出的浮点字面量（1e999）当作非法 JSON（它们不是 RFC 8259 JSON，Python json 却默认接受），
    # chat_json 于是走修复轮重问一次（原因点名 NaN/Infinity），而不是把 NaN 概率带进骨架与产物。
    # 默认开是安全的：只含有限数的回复解析结果逐字节不变。false 恢复旧的宽松解析。
    LLM_JSON_STRICT_NUMBERS = os.environ.get('LLM_JSON_STRICT_NUMBERS', 'true').strip().lower() == 'true'
    # INFRA-4：LLM 错误分类先看状态（默认开）。_classify_llm_error 先按异常类型 / HTTP 状态判定
    # （RateLimitError/429 → 配额，AuthenticationError/401/403 → 认证，422 → 内容审查，400 → 非法请求；
    # Claude CLI 信封的 api_error_status 亦算状态），其次按文本「配额先于认证」（_is_quota 的措辞 +
    # insufficient balance；429 / 2056 / 1113 只按整数匹配，不再误中 duration_ms:1429 之类），最后才是
    # 确定性非法请求。chat() 重试环、chat()/chat_with_tools 的 429 熔断计数、_is_deterministic_auth_error
    # 与编排器 _classify_provider_outage 都读它：带认证样措辞的 MiniMax 2056 用量上限消息不再被判成
    # 确定性认证失败（跳过重试、回退进 900s 冷却）。开启时 2056 / 1113 也和状态码一样不进失败消息
    # （max_tokens / 模型名）。默认开是安全的：只改变同时命中配额与认证文本、或带状态码的异常的归类。
    # false 恢复旧顺序（认证文本 → 配额文本）。
    LLM_ERROR_CLASSIFY_STATUS_FIRST = os.environ.get(
        'LLM_ERROR_CLASSIFY_STATUS_FIRST', 'true').strip().lower() == 'true'
    # 每个 run 的 token / 成本上限（0=不限）。超限后下一次 LLM 调用抛 BudgetExceeded，止血式中止。
    LLM_RUN_BUDGET_TOKENS = int(os.environ.get('LLM_RUN_BUDGET_TOKENS', '0') or '0')
    LLM_RUN_BUDGET_USD = float(os.environ.get('LLM_RUN_BUDGET_USD', '0') or '0')
    # DEFECT-1（run 级中断熔断）：编排器进程内连续 N 次提供方级 LLM 失败（配额/连接/认证，
    # 零成功间隔）→ 管线止损为可恢复的 failed 检查点态（POST /api/research/<id>/resume 续跑），
    # 而非对已死提供方持续空转（2026-07-08 曾以 231 错误/分钟磨了 ~26 小时）。≤0 关闭。
    LLM_OUTAGE_HALT_CONSECUTIVE = int(os.environ.get('LLM_OUTAGE_HALT_CONSECUTIVE', '10') or '10')
    # ITEM-18：每个 provider 的 $/Mtok 成本覆盖表（JSON），形如 {"openai":[5.0,15.0],"myprov":[0.5,1.5]}
    # （每百万 token 的 [输入, 输出] 美元价）。叠加在 telemetry._COST_PER_1K 的保守内建默认之上（同名覆盖、
    # 新名新增）。留空=纯用内建默认；解析失败=退回无覆盖（degrade-safe，见 telemetry._cost_overrides）。
    LLM_COST_PER_MTOK = os.environ.get('LLM_COST_PER_MTOK', '').strip()
    # EVAL-17: comma-separated providers billed as a flat-rate plan (e.g. a coding-plan or
    # token-plan endpoint), matched case-insensitively against the provider part of the meter's
    # "provider:model" keys. Their volume is labelled cost_basis='subscription' in
    # run_telemetry.json, like claude-cli/codex-cli, while cost_usd keeps the API-rate
    # equivalent. Safe default: empty = only the built-in CLI providers count as subscription,
    # so the classification is unchanged.
    LLM_SUBSCRIPTION_PROVIDERS = os.environ.get('LLM_SUBSCRIPTION_PROVIDERS', '').strip()

    # —— 调优后的 LLM HTTP 客户端（R2-EXEC-6）——
    # 默认 httpx 把 keepalive 连接上限压在 20 且无多路复用，并发抬高后每次调用都要重做 TLS 握手，
    # 把 R2-EXEC-1 的并发旋钮卡在「连不上代理」。LLM_HTTP2=true 启用 HTTP/2 多路复用 + 更大 keepalive；
    # 协议协商失败时回退 http1（degrade-safe）。LLM_HTTP_KEEPALIVE 抬高最大 keepalive 连接数（原 20）。
    LLM_HTTP2 = os.environ.get('LLM_HTTP2', 'True').strip().lower() == 'true'
    LLM_HTTP_KEEPALIVE = int(os.environ.get('LLM_HTTP_KEEPALIVE', '128') or '128')
    # INFRA-14: hard per-call HTTP timeout (seconds) of the OpenAI-compatible client
    # (llm_client._build_openai_client), so a stream that dies mid-read cannot wedge a
    # pipeline thread.  Declared here so .env reaches it; 600 is the value the client
    # already used (0 also means 600 there), so the default is unchanged.
    LLM_HTTP_TIMEOUT_S = float(os.environ.get('LLM_HTTP_TIMEOUT_S', '600') or '600')

    # —— 双层模型路由（EXECPLAN2 I-6-2）——
    # 把机械型结构化调用（子查询分解 / 受访者选择 / 访谈问题生成 / JSON 修复重试 /
    # 图谱实体边抽取）路由到更便宜更快的 "fast" 模型，把质量敏感的合成型调用
    # （人设生成 / 报告规划 / 章节合成）留在旗舰 "strong" 模型。默认关：未开启时
    #  tier 参数为 no-op，所有调用一律走当前 LLM_MODEL_NAME（行为与现状逐字节一致）。
    # 配置错误（未设 fast/strong 模型）一律回退到 strong/当前模型，绝不报错。
    # GAP-1：默认开——把机械抽取/分解路由到 fast 模型是单调最大的 per-call 延迟杠杆。
    # 但「未设 LLM_FAST_MODEL → fast_model() 回退到 LLM_MODEL_NAME」，且 CLI 订阅提供方只有单一
    # 模型 → tier 自动降级为 no-op；因此本旗标在没有真正 fast 模型前是 inert 的（degrade-safe），
    # 真正提速需在 .env 设 LLM_FAST_MODEL=<proxy 上的非推理快模型>。
    LLM_TIERED_ROUTING = os.environ.get('LLM_TIERED_ROUTING', 'True').strip().lower() == 'true'
    # fast / strong 模型别名（留空 → 回退到当前 LLM_MODEL_NAME，见 fast_model()/strong_model()）。
    # 仅在 LLM_TIERED_ROUTING=true 且为 OpenAI 兼容提供方时生效；CLI 订阅提供方（claude-cli/
    # codex-cli）只有单一订阅模型，tier 自动降级为 no-op（graceful degradation）。
    LLM_FAST_MODEL = (os.environ.get('LLM_FAST_MODEL') or '').strip() or None
    LLM_STRONG_MODEL = (os.environ.get('LLM_STRONG_MODEL') or '').strip() or None
    # 可选：让 fast tier 走一个完全不同的 OpenAI 兼容提供方（如本地廉价抽取 + 远端旗舰合成）。
    # 留空 → fast tier 复用当前提供方/连接参数，仅切换模型名。设置后需配合 LLM_FAST_BASE_URL /
    # LLM_FAST_API_KEY（缺任一则忽略此项、回退为「同提供方切模型」）。
    LLM_FAST_PROVIDER = (os.environ.get('LLM_FAST_PROVIDER') or '').strip().lower() or None
    LLM_FAST_BASE_URL = (os.environ.get('LLM_FAST_BASE_URL') or '').strip() or None
    LLM_FAST_API_KEY = (os.environ.get('LLM_FAST_API_KEY') or '').strip() or None

    # —— 自适应上下文预算（EXECPLAN2 I-6-4；RQ-7 已接线）——
    # RQ-7 状态：**已接线**——token_budget.py（estimate_tokens/truncate_to_tokens/context_budget/
    # slice_budget_chars/clamp_chars/fit_to_budget）现由三处生产调用点消费：
    #  (1) report_agent._prior_section_char_budget —— 前序章节 [:8000] 切片按提供方窗口预算化；
    #  (2) oasis_profile_generator —— 人设上下文 [:3000] 切片按窗口放宽（floor=PERSONA_CONTEXT_FLOOR_CHARS）；
    #  (3) simulation_config_generator —— 世界简报上限 1400→SIM_WORLD_BRIEF_MAX_CHARS（大窗口）。
    # 设计：把散落各处的硬编码字符切片换成「按提供方上下文窗口动态计算」的预算化截断——
    #  大窗口模型（MiniMax 512K / DeepSeek 1M）塞入更多事实与更长前文以提升 grounding，
    #  小窗口模型守住今天的固定切片作为 floor（绝不收紧）。估算器为近似值（≈4 字符/token），
    #  故保留充裕的 RESERVED_COMPLETION_TOKENS 安全余量。
    # 默认开（true）：接线后打开即让长研究报告真正抵达下游提示词（大窗口提供方）；
    #  任何 token_budget 异常/小窗口/未知提供方一律退回固定切片（degrade-safe），故默认开是安全的。
    #  设 false 可逐字节复现接线前的固定切片行为。
    ADAPTIVE_CONTEXT = os.environ.get('ADAPTIVE_CONTEXT', 'True').strip().lower() == 'true'
    # 预留给「补全输出」的 token 余量（从可用窗口中扣除，避免 prompt 顶满窗口后无处生成）。
    RESERVED_COMPLETION_TOKENS = int(os.environ.get('RESERVED_COMPLETION_TOKENS', '8192') or '8192')
    # 单条上下文条目（单个事实/单段前文）允许占用的硬上限 token 数，防止某一超长条目吃光整个预算。
    CONTEXT_ITEM_MAX_TOKENS = int(os.environ.get('CONTEXT_ITEM_MAX_TOKENS', '4096') or '4096')
    # RQ-7：人设上下文切片的 floor（字符）。ADAPTIVE_CONTEXT=false 或小窗口时即用此值（=接线前的
    # context[:3000]，行为不变）；ADAPTIVE_CONTEXT=true 且大窗口时以此为下限向上放宽。
    PERSONA_CONTEXT_FLOOR_CHARS = int(os.environ.get('PERSONA_CONTEXT_FLOOR_CHARS', '3000') or '3000')
    # RQ-7：模拟世界简报的字符上限（ceiling）。ADAPTIVE_CONTEXT=true 且大窗口时把 ≤1400（floor）
    # 抬到此值以承载更完整的世界背景；ADAPTIVE_CONTEXT=false 或小窗口 → 守住 1400 floor（行为不变）。
    SIM_WORLD_BRIEF_MAX_CHARS = int(os.environ.get('SIM_WORLD_BRIEF_MAX_CHARS', '3000') or '3000')
    # 各提供方上下文窗口（token）。未列出的提供方回退到保守默认 32K（见 context_window_for）。
    # 注意：这里按提供方粒度而非具体模型；fast/strong 同提供方时共用此窗口。
    PROVIDER_CONTEXT_WINDOWS = {
        'openai': 128000,
        'kimi': 256000,
        'minimax': 512000,
        'deepseek': 1000000,
        'qwen': 131072,
        'glm': 200000,
        # CLI 订阅提供方：claude/codex 当前主力模型均为 200K 窗口量级，给保守值。
        'claude-cli': 200000,
        'codex-cli': 200000,
    }
    DEFAULT_CONTEXT_WINDOW = int(os.environ.get('DEFAULT_CONTEXT_WINDOW', '32000') or '32000')

    @classmethod
    def fast_model(cls):  # EXECPLAN2 I-6-2
        """fast tier 模型名：LLM_FAST_MODEL 优先，未设则回退到当前 LLM_MODEL_NAME（不报错）。"""
        return cls.LLM_FAST_MODEL or cls.LLM_MODEL_NAME

    @classmethod
    def strong_model(cls):  # EXECPLAN2 I-6-2
        """strong tier 模型名：LLM_STRONG_MODEL 优先，未设则回退到当前 LLM_MODEL_NAME（不报错）。"""
        return cls.LLM_STRONG_MODEL or cls.LLM_MODEL_NAME

    @classmethod
    def context_window_for(cls, provider):  # EXECPLAN2 I-6-4
        """返回某提供方的上下文窗口（token）；未知提供方回退到 DEFAULT_CONTEXT_WINDOW。"""
        return int(cls.PROVIDER_CONTEXT_WINDOWS.get((provider or '').lower(), cls.DEFAULT_CONTEXT_WINDOW))

    # 结构化预测（机器可读的情景+概率+判定标准+引用审计，EXECPLAN2 I-3-0/I-9-1/I-3-1；
    # NEXTSTEPS P0-1）。默认开：预测是本产品的交付物，结构化骨架应是一等公民而非旁支。
    # 关闭则回到旧的纯文本报告行为（degrade-safe）。落 forecast.json。
    REPORT_STRUCTURED_FORECAST = os.environ.get('REPORT_STRUCTURED_FORECAST', 'True').strip().lower() == 'true'
    # QUALITY-OPT S1: before declaring a run completed, validate the real deliverable —
    # HARD-FAIL (status=failed) on an all-placeholder report or missing/empty forecast.json,
    # and record a degraded health block (consumed by status API + sim-caveat) for hollow/
    # truncated sims. Stops the "fake completed" runs (8/13 of the audited corpus).
    PIPELINE_HEALTH_GATE = os.environ.get('PIPELINE_HEALTH_GATE', 'True').strip().lower() == 'true'
    # RESEARCH-2: add pipeline_health.stages.research = {health: degraded, issues, score}
    # when research_quality is degraded, so the status API and the executive brief's
    # honesty note name the research degradation.  Degrade-only: it never fails the
    # pipeline, but the run's status is degraded, so a force resume (ORCH-3, which only
    # regenerates the report) is accepted and cannot repair the research.
    # Default false: off = pipeline_health without a research stage, as before.
    PIPELINE_HEALTH_RESEARCH_STAGE = os.environ.get(
        'PIPELINE_HEALTH_RESEARCH_STAGE', 'false').strip().lower() == 'true'
    # NEXTSTEPS P0-1：在撰写任何章节叙事**之前**先从信号包+forecast_inputs 推导「预测骨架」
    # （情景+概率+判定标准），强制 MECE 纪律并把骨架注入每章提示词，让叙事对齐可证伪目标。
    # 默认开；关闭则回退为旧的「报告写完后再从成稿抽取」行为（degrade-safe）。
    REPORT_FORECAST_SPINE_FIRST = os.environ.get('REPORT_FORECAST_SPINE_FIRST', 'True').strip().lower() == 'true'
    # 结构化预测后追加红队自校准（纠正过度自信/基率忽视，EXECPLAN2 I-3-5；NEXTSTEPS P2-1）。
    # 默认开：与基率锚定+inter-seed 一致度配合做 anchor-and-adjust，纠正内视过度自信（多一次 LLM 调用）。
    REPORT_FORECAST_SELF_CRITIQUE = os.environ.get('REPORT_FORECAST_SELF_CRITIQUE', 'True').strip().lower() == 'true'
    # NEXTSTEPS P2-3 / LOOP-010：发布门。严格解析后的定量引用覆盖不足等认识论缺口
    # 至多降一级 confidence；概率不闭合、缺兜底情景和最终工件完整性缺陷写入 hard_issues，
    # 由最终只读审计阻止 completed 发布。默认开；关闭仅跳过结构化预测门。
    REPORT_PUBLISH_GATE = os.environ.get('REPORT_PUBLISH_GATE', 'True').strip().lower() == 'true'
    REPORT_PUBLISH_GATE_MIN_COVERAGE = float(os.environ.get('REPORT_PUBLISH_GATE_MIN_COVERAGE', '0.75') or '0.75')
    # A single generic source repeated throughout a long report is usually a
    # provenance-collapse signal, not stronger evidence.  The final audit blocks
    # publication above this count so synthesis must either cite the actual
    # evidence span or leave a visible coverage gap.
    REPORT_MAX_CITATIONS_PER_SOURCE = int(
        os.environ.get('REPORT_MAX_CITATIONS_PER_SOURCE', '20') or '20'
    )
    # LOOP-010：所有正文改写与引用最终化之后，对将发布的精确 Markdown 做一次只读审计。
    # 记录 SHA-256、磁盘一致性、严格引用解析、语言/流程泄漏与 lint would-change，并把结果
    # 合并进 forecast.json.quality；绝不在审计阶段再次改写报告。默认开。
    REPORT_FINAL_READ_ONLY_AUDIT = os.environ.get(
        'REPORT_FINAL_READ_ONLY_AUDIT', 'True'
    ).strip().lower() == 'true'
    # Increment whenever a hard publication rule changes. Byte-matched audits
    # from an older policy are drafts until replayed under the current rules.
    REPORT_FINAL_AUDIT_POLICY_VERSION = 3
    # RESEARCH-9: persist what the publish stabilizer did to citations before the
    # read-only audit (markers before, dangling / semantic / overuse strips, the
    # quantitative repair's added citations and removed sentences) as
    # final_audit.json pre_audit_repairs and forecast.json quality.citation_finalization.
    # Telemetry only, so default on: the Markdown, full_report.md and every gate
    # are unchanged; off = neither key is written.
    REPORT_FINALIZATION_TELEMETRY = os.environ.get(
        'REPORT_FINALIZATION_TELEMETRY', 'true'
    ).strip().lower() == 'true'
    # NEXTSTEPS P2-2：在报告末尾追加一个**确定性**的「如何验证本预测」章节——逐情景列可证伪判定
    # 标准 + 来自 forecast_inputs 的带日期/触发观察指标，并把指标-情景映射写进 forecast.json 供
    # 解析调度器使用。默认开；无结构化预测/无情景时自动跳过（degrade-safe）。
    REPORT_RESOLUTION_SECTION = os.environ.get('REPORT_RESOLUTION_SECTION', 'True').strip().lower() == 'true'
    # VIZ-1：确定性报告可视化器（无 LLM）。把已落盘的结构化工件（forecast/timeline/actors/
    # world_state_trajectory/comparison/校准账本）渲染成 Mermaid 代码块 + matplotlib PNG，落盘
    # reports/{id}/charts/ 与 viz_manifest.json。主开关默认开；关闭=完全不生成图（degrade-safe）。
    REPORT_VISUALIZER = os.environ.get('REPORT_VISUALIZER', 'True').strip().lower() == 'true'
    # VIZ-1：Mermaid 族（零依赖）开关——时间线/因果路径/派系/角色关系网络。默认开。
    REPORT_VIZ_MERMAID = os.environ.get('REPORT_VIZ_MERMAID', 'True').strip().lower() == 'true'
    # VIZ-1：matplotlib PNG 族开关——情景误差棒/模型 vs 市场哑铃/世界态堆叠面积/对比分组柱/校准
    # 曲线。默认开；matplotlib 未安装时该族自动无效（仅 Mermaid），无需改此旋钮。
    REPORT_VIZ_CHARTS = os.environ.get('REPORT_VIZ_CHARTS', 'True').strip().lower() == 'true'
    # VIZ-1：PNG 渲染 dpi（PDF 宽度下可读性；下限 72）。
    REPORT_VIZ_DPI = int(os.environ.get('REPORT_VIZ_DPI', '160') or '160')
    # VIZ-1：网络图/因果图/派系图的节点上限（防止巨图不可读；超出即截断，确定性保留首现节点）。
    REPORT_VIZ_MAX_NODES = int(os.environ.get('REPORT_VIZ_MAX_NODES', '40') or '40')
    # VIZ-1（ITEM-16）：交互式 HTML 图表族开关——用 plotly 生成 matplotlib PNG 的可交互等价物
    # （情景误差棒/模型vs市场哑铃/市场价格历史折线/世界态堆叠面积），落 reports/{id}/charts/*.html
    # （plotly.js 内联，完全离线自包含），manifest type='html'。默认开；plotly 未安装时该族自动
    # 无效（与 PNG 族并存，互不影响）。关闭=不生成 HTML 图（degrade-safe）。
    REPORT_VIZ_INTERACTIVE = os.environ.get('REPORT_VIZ_INTERACTIVE', 'True').strip().lower() == 'true'
    # WAVE9-VIZ：plotly 静态 PNG 导出开关——每张 plotly HTML 图经 kaleido 同步导出 PNG 对
    # （scale=2、宽 1200px，供 PDF/exec-brief 内嵌，manifest 项挂 png_path）。默认开；kaleido
    # 未安装或运行时渲染失败自动回退 matplotlib（有等价图时）或仅保留 HTML（degrade-safe）。
    REPORT_VIZ_PNG_EXPORT = os.environ.get('REPORT_VIZ_PNG_EXPORT', 'True').strip().lower() == 'true'
    # WAVE9-VIZ：plotly 时间线泳道图的事件上限（同日高重合去重后按显著度截断，再按时间升序）。
    REPORT_VIZ_TIMELINE_MAX_EVENTS = int(os.environ.get('REPORT_VIZ_TIMELINE_MAX_EVENTS', '40') or '40')
    # WAVE9-VIZ：plotly 角色关系网络图的节点上限（按 graph_priors 权重+度数排序保留；边随节点裁剪）。
    REPORT_VIZ_NETWORK_MAX_NODES = int(os.environ.get('REPORT_VIZ_NETWORK_MAX_NODES', '60') or '60')
    # VIZ-1 钩子：把 ReportVisualizer 产出的图表/图注注入成稿 full_report.md——Mermaid 块按章节
    # 标题关键词模糊匹配就地插入，未匹配的图与全部 PNG 归入文末「Visual Annex / 可视化附录」（双语
    # 随报告语言）。与 REPORT_VISUALIZER 正交：后者管「是否生成图 + 落 charts/」，此旋钮管「是否
    # 注入正文」。默认开；关闭或注入失败=成稿不含图区（图仍落盘，degrade-safe）。
    REPORT_VISUALIZATIONS = os.environ.get('REPORT_VISUALIZATIONS', 'True').strip().lower() == 'true'
    # W9-8（报告链融合）：交互式 HTML 图注入正文——manifest 里 type=html 且带 png_path 的项内嵌
    # 静态 PNG 并附「[交互版 Interactive](charts/x.html)」链接行；纯 html 项只留链接行；html/png
    # 项按 placement_hint 就地插入命中章节（此前仅 mermaid 参与就地放置，html 项一直被静默丢弃）。
    # 关闭=html 项不注入、png 全部归附录（与历史行为一致，degrade-safe）。
    REPORT_VIZ_INTERACTIVE_EMBED = os.environ.get('REPORT_VIZ_INTERACTIVE_EMBED', 'True').strip().lower() == 'true'
    # W9-8：Mermaid 退役——正文不再注入裸 ```mermaid 围栏（前端无 mermaid 渲染器，围栏只会显示为
    # 源码；PDF 侧 mmdc 亦未安装）。可视化器若仍产出 mermaid 项，改以 <details> 折叠代码块的形式
    # 仅归入文末 Visual Annex。关闭=回退旧行为（按关键词就地插入裸围栏）。
    REPORT_VIZ_MERMAID_ANNEX_ONLY = os.environ.get('REPORT_VIZ_MERMAID_ANNEX_ONLY', 'True').strip().lower() == 'true'
    # PDF-1：GET /api/report/{id}/pdf 惰性把 full_report.md 导出为 full_report.pdf——相对图表路径
    # 绝对化 +（PATH 有 mmdc 时）预渲染 Mermaid 为 PNG，pandoc+xelatex（CJKmainfont=PingFang SC、
    # geometry margin 2.5cm、--toc），失败回退 markdown→HTML→PyMuPDF Story。按成稿 mtime 缓存。
    # 默认开；关闭=端点 404（degrade-safe）。
    REPORT_PDF_EXPORT = os.environ.get('REPORT_PDF_EXPORT', 'True').strip().lower() == 'true'
    # PDF-1：单次 pandoc 构建超时秒数（防挂死；超时即回退 PyMuPDF）。
    REPORT_PDF_TIMEOUT = int(os.environ.get('REPORT_PDF_TIMEOUT', '180') or '180')
    # —— WAVE10：无缝引用（[S12] 记号 → 参考来源附录 / 悬空修复 / 译文对账 / PDF 脚注）——
    # 单一引用语法：来源索引用 actors.sources_index_unified 渲染——正文记号只有裸 [S<n>]
    # 一种形状（n=来源原始位置），层级 [S1-a] 降级为标题后的展示注记；条目按「研究报告中被
    # 引用优先 → 层级 → 原始顺序」相关性排序截取。关闭=回退旧分层/位置索引（degrade-safe）。
    REPORT_CITATION_SINGLE_GRAMMAR = os.environ.get('REPORT_CITATION_SINGLE_GRAMMAR', 'true').strip().lower() == 'true'
    # 注入索引的来源条数上限（替代旧的盲切 [:40]；688 条全量注入会撑爆章节提示词）。
    REPORT_SOURCES_INDEX_MAX = int(os.environ.get('REPORT_SOURCES_INDEX_MAX', '60') or '60')
    # 引用最终化：语言纯度/lint 之后、双语翻译之前，把正文 [S12] 解析为文末「References/
    # 参考来源」附录（只列被引用来源，URL 有效性守卫拦截截断域名）+ citations.json 工件。
    # 关闭=不追加附录、不落工件（记号保持字面，行为与历史一致）。
    REPORT_CITATION_FINALIZER = os.environ.get('REPORT_CITATION_FINALIZER', 'true').strip().lower() == 'true'
    # 悬空引用修复（注册进 REPORT_REPAIR_PASSES 修复链）：索引解析不到的 [S246] 型记号 →
    # 全量来源列表内数字锚定验证保留 / 重映射到命中来源 / 删除（三步确定性处置）。
    REPORT_CITATION_REPAIR = os.environ.get('REPORT_CITATION_REPAIR', 'true').strip().lower() == 'true'
    # 双语译文引用对账：逐 H2 块记号多重集比较，漂移块用精确记号清单重译一次；仍漂移 →
    # 保留译文并把 citation_drift 记进 translations 条目（quality=warning）。
    REPORT_TRANSLATION_CITATION_PARITY = os.environ.get('REPORT_TRANSLATION_CITATION_PARITY', 'true').strip().lower() == 'true'
    # PDF 引用脚注：pandoc 路径把可解析 [S12] 首次出现改写为真脚注（citations.json 驱动，
    # 脚注链接文本用短域名防边距溢出，colorlinks 高亮）；PyMuPDF 回退跳过变换。
    REPORT_PDF_CITATION_FOOTNOTES = os.environ.get('REPORT_PDF_CITATION_FOOTNOTES', 'true').strip().lower() == 'true'
    # DELIV-1：从每份完成报告惰性派生「一页高管简报 + 可分享速览」——GET /api/report/{id}/
    # exec-brief（md）、/exec-brief.pdf、/digest 按源 mtime 缓存构建（与 PDF 端点同思路）。纯确定性
    # （NO LLM，只从成稿/forecast.json 抽取）：预测问题 + 3 句论点 + TOP 二元预测表（≤8 行，概率±集成
    # 离散/市场锚 Δ/判定日期）+ 关键情景概率 + scenario-bars 图 + 3 个带日期观察指标 + 一行诚实声明；
    # 双语（随成稿语言，另按 meta.translations[] 生成 exec_brief.<lang>.md）。PDF 复用 pandoc 引擎选择/
    # PyMuPDF 回退但去 --toc 收紧边距做单页。默认开；关闭=三端点 404（degrade-safe）。
    REPORT_EXEC_BRIEF = os.environ.get('REPORT_EXEC_BRIEF', 'True').strip().lower() == 'true'
    # INFRA-4：预测工件严格 JSON（默认开）。forecast.json（骨架早落版 / 成稿版 / lint 回写 /
    # scripts/backfill_report_visuals.py 回填）与 market_comparison.json 按 allow_nan=False 序列化：
    # 含 NaN/±Infinity 的骨架不钉、不早落（回退成稿后抽取）；成稿工件里的非有限叶子记 error 后置 null，
    # 路径记入 forecast.quality.nonfinite_nulled。浏览器 JSON.parse 拒绝 NaN，默认开是安全的：
    # 有限数内容逐字节不变。false 恢复旧的照写 NaN。
    ARTIFACT_STRICT_JSON = os.environ.get('ARTIFACT_STRICT_JSON', 'true').strip().lower() == 'true'
    # NEXTSTEPS P2-4：把每份 forecast.json 追加进校准账本（horizon/resolution date 为键），已解析
    # 预测的历史 Brier/ECE surfacing 进新预测 confidence_rationale——让信心由 track record 赚得而非
    # 自评。默认开（仅 jsonl 追加/读取，无 LLM）；初期无已解析样本时对信心无影响（degrade-safe）。
    REPORT_FORECAST_LEDGER = os.environ.get('REPORT_FORECAST_LEDGER', 'True').strip().lower() == 'true'
    FORECAST_LEDGER_DIR = os.environ.get('FORECAST_LEDGER_DIR', '').strip()  # 空=PIPELINE_DATA_DIR/_forecast_ledger
    # EVAL-1: when a report enters the calibration ledger. 'published' (default) commits the
    # audit-sealed forecast.json bytes only after the final publish audit passed and meta.json
    # says completed (schema_version 2 rows: idempotent, pre-registration keyed, self-contained);
    # 'legacy' restores the pre-audit schema_version 1 append inside _finalize_structured_forecast
    # byte-for-byte; 'off' writes nothing. Unknown values act as 'published'. The default is an
    # intended behaviour change: reports that later fail publication no longer poison calibration.
    # REPORT_FORECAST_LEDGER=false still disables every ledger write and the calibration read.
    FORECAST_LEDGER_COMMIT_MODE = os.environ.get('FORECAST_LEDGER_COMMIT_MODE', 'published').strip().lower()
    # EVAL-1: in 'published' mode, a terminal report that is not publishable (failed, or failed
    # the final audit) leaves one row_type='unpublished_terminal' row in the same ledger with its
    # reasons, so the calibration denominator stays auditable (ADR 0002 I-20). Such rows carry no
    # scenarios and are never scored, so the default cannot change any calibration number.
    FORECAST_LEDGER_RECORD_UNPUBLISHED = os.environ.get('FORECAST_LEDGER_RECORD_UNPUBLISHED', 'true').strip().lower() == 'true'
    # EVAL-1: cap on the question text stored in a commit row (question_sha256 always covers the
    # full normalized text, so the cap only bounds row size, never identity).
    FORECAST_LEDGER_QUESTION_MAX_CHARS = int(os.environ.get('FORECAST_LEDGER_QUESTION_MAX_CHARS', '4000') or '4000')
    # EVAL-3: true = the report's historical calibration folds the settlement events of
    # resolutions.jsonl into the production primary commit rows, admits only items whose outcome
    # was known before 00:00Z of the report's as-of date (forecast_resolution.admissible) and adds
    # that as_of plus a binary-scale block to forecast['historical_calibration']. Default off
    # (ADR 0002 decision 6, shadow first): the report path stays byte-identical, while the
    # resolution monitor always shows the folded numbers as shadow observability.
    FORECAST_LEDGER_SETTLEMENT_FOLD = os.environ.get('FORECAST_LEDGER_SETTLEMENT_FOLD', 'false').strip().lower() == 'true'
    # R2-CAL-5 / EVAL-3: shadow-only. forecast_ledger.recalibration_param reports this as
    # `enabled` beside the fitted slope, but nothing applies a slope until a WP14
    # PromotionDecision, so neither value changes any forecast; default off.
    REPORT_RECALIBRATE_FROM_LEDGER = os.environ.get('REPORT_RECALIBRATE_FROM_LEDGER', 'false').strip().lower() == 'true'
    # MON-1 持续预测/判定监测（scripts/resolution_monitor.py，cron 驱动）：对已发布报告的锚定
    # 市场周期性重报价 + 查询判定终态，落 price_track.jsonl / resolutions.jsonl / monitor_report.md。
    # 纯脚本旁路，不改任何在线管线语义；下列旋钮仅被该脚本读取（degrade-safe，默认保守）。
    RESOLUTION_MONITOR_RECENT_N = int(os.environ.get('RESOLUTION_MONITOR_RECENT_N', '10') or '10')  # --all-recent 缺省处理的最近报告条数
    RESOLUTION_MONITOR_LOOKBACK_DAYS = int(os.environ.get('RESOLUTION_MONITOR_LOOKBACK_DAYS', '0') or '0')  # 0=不限；>0 仅监测 created_at 在近 N 天内的报告
    RESOLUTION_MONITOR_DRIFT_THRESHOLD = float(os.environ.get('RESOLUTION_MONITOR_DRIFT_THRESHOLD', '0.05') or '0.05')  # 研究期价→现价 |Δ|≥此值才计入「biggest movers」
    # i8（LOOP-017 尾巴「resolution monitor never ran」）：脚本此前没有任何调度方——判定
    # 账本/价格轨迹永远是空的。>0 时后端进程内以该小时数为周期在后台跑一次
    # `scripts/resolution_monitor.py run --all-recent`（子进程隔离，失败只记日志）。
    # 默认 0=关：行为与今日逐字节一致；开启是 owner 的一行 env 决定（keyless 公共
    # Gamma 重报价，无 LLM/付费调用）。仅 run.py 生产入口启动，测试进程绝不自启。
    RESOLUTION_MONITOR_AUTORUN_HOURS = float(os.environ.get('RESOLUTION_MONITOR_AUTORUN_HOURS', '0') or '0')
    # EVAL-2 settlement events v2 (read only by scripts/resolution_monitor.py; inert unless the
    # monitor runs, and autorun above stays off by default). RESOLUTION_SETTLE_LEDGER: `run
    # --all-recent` also sweeps the production primary commit rows of ledger.jsonl (`settle`
    # does it on demand); the sweep only appends idempotent, fail-closed settlement events.
    RESOLUTION_SETTLE_LEDGER = os.environ.get('RESOLUTION_SETTLE_LEDGER', 'true').strip().lower() == 'true'
    # Weakest market-anchor resolution_equivalence a settlement event may be scoring-eligible at
    # (exact|near|loose; unknown values act as exact). loose behaves exactly like near: an anchor
    # with a loose or missing equivalence always fails the completeness check (anchor_incomplete).
    # Default exact: a near market resolves a different proposition, so its outcome must never
    # label ours.
    RESOLUTION_MARKET_MIN_EQUIVALENCE = os.environ.get('RESOLUTION_MARKET_MIN_EQUIVALENCE', 'exact').strip().lower()
    # Days after a binary's resolution date before an item still lacking a settlement gets one
    # never-scored terminal event ('unresolvable_after_grace'), so nothing stays pending forever.
    RESOLUTION_PENDING_GRACE_DAYS = int(os.environ.get('RESOLUTION_PENDING_GRACE_DAYS', '180') or '180')
    # Cap on the newest production primary commit rows one settle sweep fetches market
    # resolutions for (rows with an unrecorded market-anchored binary). Unanchored binaries
    # past their grace period need no network and are always settled; rows with nothing
    # actionable (every binary recorded, or unanchored and still inside grace) never count.
    RESOLUTION_SETTLE_MAX_TARGETS = int(os.environ.get('RESOLUTION_SETTLE_MAX_TARGETS', '200') or '200')
    # NEXTSTEPS P3-8：把已实现关系按价投影一个「到预测时点的轨迹」（allied→likely_persists /
    # adversarial→persists_or_escalates / transactional→contingent），喂进报告信号包帮助情景分叉
    # 分析（contingent 纽带=支点）。**模型先验非证据**，块内显式标注。默认关（保守，避免被当成证据）。
    REPORT_PROJECTED_EDGES = os.environ.get('REPORT_PROJECTED_EDGES', 'False').strip().lower() == 'true'
    # OASIS 抽样/人设生成确定性种子（EXECPLAN2 I-7-2；0/空=随机，复现/集成跑设同一正整数）。
    SIM_SEED = int(os.environ.get('SIM_SEED', '0') or '0')
    # NEXTSTEPS P0-3：同问多种子集成。LLM 驱动的模拟是随机生成器，单次=单抽样；对同一图谱用
    # 不同 SIM_SEED 跑 N 次 sim+report，聚合各自 forecast.json→ensemble_forecast.json。
    # Foglamp WP1 (1D, I-12)：默认回到【1】。当前额外种子共享同一 graph_id 且图谱反馈曾默认
    # 开启——后种子可读到先种子写入的合成痕迹，并发种子还会产生顺序依赖状态；这样的
    # spread/agreement 不是干净的不确定性度量（伪集成）。在 WP10/WP12 交付「快照一次 + 每种子
    # 隔离 overlay + 独立 RNG」之前不得回调 >1。
    N_FORECAST_SEEDS = max(1, int(os.environ.get('N_FORECAST_SEEDS', '1') or '1'))
    # PAR-3：多种子集成的并行度。此前额外种子严格串行（wall-clock ≈ ×N_FORECAST_SEEDS 的
    # sim+report 段）；每个种子跑在独立 simulation_id → 独立目录/DB/文件式 IPC/仅注入子进程的
    # env（见 _run_one_seed 的线程安全论证），故可安全并行。默认 2、上限 3（并行度越高对
    # LLM provider 的瞬时压力越大——每个种子子进程内部还各自受 OASIS 信号量约束）。设 1 =
    # 复现旧的严格串行行为（degrade-safe）。注意：共享的 graph_id 会被并发种子的图谱反馈同时
    # 写入——串行版本本就共享同一张图，Zep 服务端处理并发写；每种子的 updater 按 sim_id 独立键。
    ENSEMBLE_SEED_CONCURRENCY = max(1, min(3, int(os.environ.get('ENSEMBLE_SEED_CONCURRENCY', '2') or '2')))

    # —— 二元预测契约（QUALITY-OPT A1/A4：briefs 常要求「>=N 个二元 yes/no 预测，各含客观判定」）——
    # 研究阶段往往已产出合规的二元预测（如 research_report 的 F1-Fn），但下游 finalizer 之前只输出
    # 情景而丢弃它们。开启后：从研究报告抽取/补足 >=BINARY_FORECASTS_MIN_COUNT 条独立二元预测，
    # 各带 statement(一句)/probability(独立, 不归一)/客观 resolution_criteria(指标+阈值+日期+来源)，
    # 写入 forecast['binary_forecasts']，与 scenarios 并存。degrade-safe：抽取失败则维持旧行为。
    FORECAST_EMIT_BINARY = os.environ.get('FORECAST_EMIT_BINARY', 'True').strip().lower() == 'true'
    BINARY_FORECASTS_MIN_COUNT = max(1, int(os.environ.get('BINARY_FORECASTS_MIN_COUNT', '10') or '10'))
    # 对二元预测强制「锐利客观判定」（指标 AND 数字 AND 日期）；不达标的逐条重生成一次。
    FORECAST_BINARY_REQUIRE_SHARP = os.environ.get('FORECAST_BINARY_REQUIRE_SHARP', 'True').strip().lower() == 'true'

    # —— 校准基石（R2-CAL）——
    # R2-CAL-4：发布前给每个保留情景一个概率下限再做最终重归一，绝不发布 0%。消除「已实现但未预测」
    # 结果坐在 ~0 处的灾难性 log-loss/Brier 失败。trivial 且 tail-dominant。
    FORECAST_PROB_FLOOR = float(os.environ.get('FORECAST_PROB_FLOOR', '0.03') or '0.03')
    # REPORT-1：概率字段的类型化解析（utils/probability_parse.py）。开启后 '30%' 读作 0.30，
    # 缺失/区间/上下限/混合量纲等不可读概率一律置 null 并标 probability_status=needs_review
    # （情景合同审计随之失败），绝不再被补成 0.0、均匀分布或 0.98/0.02 钳制。默认开是安全的：
    # 格式良好的数值输入与旧路径逐字节一致，只有畸形输入会改为显式待复核；设 false 复现旧行为。
    FORECAST_PROB_STRICT_PARSE = os.environ.get('FORECAST_PROB_STRICT_PARSE', 'true').strip().lower() == 'true'
    # R2-CAL-1 / R2-CAL-17：把预测脊柱推导 K 次（共享情景名、变 temp），汇成均值概率 + spread→confidence。
    # Foglamp WP1 (1D)：默认回到【1】。同模型重抽样的 spread 不是校准过的不确定性——把它
    # 当区间发布会高估独立性；重抽样只有在测得的不稳定性证明其成本合理时才加（WP15）。
    REPORT_SPINE_SELFCONSISTENCY_K = max(1, int(os.environ.get('REPORT_SPINE_SELFCONSISTENCY_K', '1') or '1'))
    # R2-CAL-2：集成聚合用 log-odds（几何）pooling 的 extremizing 因子；算术均值作为诊断保留。
    # Foglamp WP1 (1D)：默认回到恒等【1.0】——extremize>1 是一个预测政策，必须先过 WP14 的
    # outcome-blind 前瞻晋升门（promoted policy ID）才可覆盖，不得作为环境默认锐化概率。
    ENSEMBLE_EXTREMIZE_A = float(os.environ.get('ENSEMBLE_EXTREMIZE_A', '1.0') or '1.0')
    # W9-5：多种子集成的语义情景对齐。种子间对同一情景常起不同的自由名（中英混排、
    # 'S1 — …' 前缀等），仅按精确规范名分桶会把它们打散成 support=1 的孤桶、一致度误报 0.0
    # （实测 3 种子 11 桶全 support=1、信心被误降为 low）。开启后名字不中时按
    # resolution_criteria 的 token Jaccard（阈值 ENSEMBLE_ALIGN_MIN_OVERLAP）把跨 run 同义
    # 情景并进同一桶；同 run 情景绝不互并；有效共识桶（support≥2）不足 2 个时一致度置 None
    # （无法判定，而非误报）。设 false 复现旧的「仅精确名匹配」行为（degrade-safe）。
    ENSEMBLE_SEMANTIC_ALIGN = os.environ.get('ENSEMBLE_SEMANTIC_ALIGN', 'true').strip().lower() == 'true'
    ENSEMBLE_ALIGN_MIN_OVERLAP = float(os.environ.get('ENSEMBLE_ALIGN_MIN_OVERLAP', '0.34') or '0.34')
    # R2-CAL-3：把 WorldState.shares 作为结构化 base_distribution 传入脊柱推导，约束情景集 + 把概率
    # 限制在建模份额的一个 band 内（除非有依据）。仅当 SIM_DECISION_CHANNEL 开启时生效。
    REPORT_SPINE_ANCHOR_WORLDSTATE = os.environ.get('REPORT_SPINE_ANCHOR_WORLDSTATE', 'true').strip().lower() == 'true'

    # —— EXECPLAN2 第二波改进旋钮（单一真源；各消费方此前经 getattr 读取，这里收口 + 文档化）——
    GRAPH_SEARCH_RECIPE = os.environ.get('GRAPH_SEARCH_RECIPE', 'rrf').strip().lower()          # I-1-0/I-1-6 检索 recipe
    RESEARCH_QUALITY_GATE = os.environ.get('RESEARCH_QUALITY_GATE', 'False').strip().lower() == 'true'  # I-0-3 研究后质量门
    # R2-RES-1：research_quality 分数的软下限——低于此值 run 告警/降信心。修复此前 getattr 孤儿 floor=0
    # 让门双重失效的问题；硬门 RESEARCH_QUALITY_GATE 仍保持 opt-in（默认关），以免稀疏单 actor 问题 wedge。
    RESEARCH_QUALITY_FLOOR = float(os.environ.get('RESEARCH_QUALITY_FLOOR', '0.45') or '0.45')
    PIPELINE_STRICT_SCHEMA = os.environ.get('PIPELINE_STRICT_SCHEMA', 'True').strip().lower() == 'true'  # I-4-4 状态模式版本校验
    # 编排器 RUN 阶段「停滞看门狗」：模拟长时间无轮次推进（区别于慢但在推进）视为卡死，
    # 停模拟并失败，避免管线线程永久空转。秒；<=0 关闭。默认 1800（30 分钟无进展）。
    PIPELINE_RUN_STALL_S = float(os.environ.get('PIPELINE_RUN_STALL_S', '1800') or '1800')
    SIM_EMERGENT_METRICS = os.environ.get('SIM_EMERGENT_METRICS', 'False').strip().lower() == 'true'     # I-2-0 涌现结构指标
    # SIM-12 / OBS-1：默认开——访谈往返 + 人设回退计量开销极小，却让「单薄报告」在多小时跑里可诊断。
    IPC_TELEMETRY_ENABLED = os.environ.get('IPC_TELEMETRY_ENABLED', 'True').strip().lower() == 'true'   # I-5-5 IPC 延迟计量

    ONTOLOGY_TEMPLATE = os.environ.get('ONTOLOGY_TEMPLATE', 'social_opinion').strip().lower()  # I-1-3 领域自适应本体模板
    # 开启后本体层按 prompt 自动在 general_forecast / social_opinion 之间择一（I-1-3）；
    # ONTO-4：默认开——避免把市场/地缘类预测硬塞进社媒 schema；空结果时回退默认模板，
    # 最坏情况等同于今天（degrade-safe）。设 false 可固定用上面的 ONTOLOGY_TEMPLATE。
    ONTOLOGY_AUTO_SELECT = os.environ.get('ONTOLOGY_AUTO_SELECT', 'true').strip().lower() == 'true'
    # 更丰富的本体抽取 prompt（实体分类 archetype/simulation_tier、actor 行为 DNA、valenced 关系）+
    # 保留完整 ontology 对象（CLAUDE/CODEX/GEMINI 三方收敛本体契约）。默认开：新字段缺失时为 no-op，
    # 抽取结果与现状逐字节一致（旧数据/旧测试夹具不受影响）。
    ONTOLOGY_RICH_SCHEMA = os.environ.get('ONTOLOGY_RICH_SCHEMA', 'True').strip().lower() == 'true'
    # NEXTSTEPS P3-2：抽取后对 actors[] 跨轨去重（normalize_name + 双向包含/别名聚类，合并重复
    # 行为规范行并改写关系端点）。默认开：只会收紧 cast（防中心度分裂/重复 persona/salience 污染）；
    # 无重复时为 no-op（与现状一致）。
    CAST_RECONCILE = os.environ.get('CAST_RECONCILE', 'True').strip().lower() == 'true'
    # NEXTSTEPS P3-3：把已实现的 actor 阵容（archetype/relationships[].type）投影成本体种子约束
    # 喂给本体生成（单一真源，避免从散文重新派生导致 schema/instance 漂移）。默认开：把研究确认的
    # 实体类型 + 关系类型作为「保留这些类型、至多再加 2 个领域专属类型、不要重命名」的种子模板注入
    # 本体生成提示词，使本体真正以 actor 阵容 + 关系为底座（与 ONTOLOGY_RICH_SCHEMA 的 archetype/
    # 边族分类元数据互补）。degrade-safe：actor 阵容为空/无类型时 ontology_seed_block 返回 ""，
    # 行为与关闭逐字节一致。如需回到「纯从散文派生本体」可设为 false。
    ONTOLOGY_FROM_DOSSIER = os.environ.get('ONTOLOGY_FROM_DOSSIER', 'True').strip().lower() == 'true'
    PERSONA_EGO_RETRIEVAL = os.environ.get('PERSONA_EGO_RETRIEVAL', 'False').strip().lower() == 'true'   # I-1-5 自我中心人设上下文
    # 人设提示注入 actor 行为 DNA（价值观/信念/激励/资源/风险偏好）+ 关系名册（盟友/对手/竞争者…）。
    # 默认开；仅当 actor 携带 worldview/incentives/resources 等新字段时生效，缺失时为 no-op（与现状一致）。
    PERSONA_BEHAVIORAL_DNA = os.environ.get('PERSONA_BEHAVIORAL_DNA', 'True').strip().lower() == 'true'
    # SIM-7：携带非空 bundled edges/nodes 的人设跳过冗余的 Zep 二次检索（冷实体仍检索）。
    # 此前是 getattr 幽灵旋钮（默认 False）；提升为一等属性并默认开，省去 ~80 个 agent 多数的 1-2 次
    # Zep 搜索。oasis_profile_generator 经 getattr(Config, 'PROFILE_ZEP_SKIP_WHEN_CONTEXT', False) 读取。
    PROFILE_ZEP_SKIP_WHEN_CONTEXT = os.environ.get('PROFILE_ZEP_SKIP_WHEN_CONTEXT', 'True').strip().lower() == 'true'
    API_V1_ENABLED = os.environ.get('API_V1_ENABLED', 'False').strip().lower() == 'true'       # I-9-5 稳定版程序化 API /api/v1
    MODEL_COMPARISON_ENABLED = os.environ.get('MODEL_COMPARISON_ENABLED', 'False').strip().lower() == 'true'  # I-9-4 模型对比
    REPORT_TELEMETRY = os.environ.get('REPORT_TELEMETRY', 'True').strip().lower() == 'true'     # I-5-4 报告级 LLM 计量汇总
    # ITEM-18 / W9-6：完成时把确定性的「Run Telemetry」附录表（stage × 调用/tokens/成本/墙钟）
    # 写到报告目录的独立 telemetry.md（无 LLM、幂等）。W9-6 默认改 False——此前默认 True 把
    # $26.28 的内部成本表追加进了 full_report.md（客户交付物）；置 true 恢复旧的「附录进
    # full_report.md」行为（telemetry.md 两种取值下都会写；run 遥测仍落 telemetry.json / state.options）。
    REPORT_TELEMETRY_APPENDIX = os.environ.get('REPORT_TELEMETRY_APPENDIX', 'False').strip().lower() == 'true'
    # REPORT-3：默认开——把确定性 sim 聚合（top actors/volumes/coalition sizes/P(outcome)/scenario diff）
    # 钉进每章作可引用的数字底座，提升引用覆盖、减少探索式工具调用。
    REPORT_SIGNAL_PACK = os.environ.get('REPORT_SIGNAL_PACK', 'True').strip().lower() == 'true'  # I-3-2 每章注入定量信号包
    # REPORT-5：信号包按 run_summary.json 的 simulation_health 门控（诚实检查，fail-closed，默认开）。
    # hollow（零有机动作）时去掉动作量/关注聚类派生块（议程设置力分层、派系图、情景差异——它们只是
    # 种子动作的回声）；errored 再去掉世界态块；图谱派生块（投影纽带、因果骨架）保留；二者都在包头后
    # 注明「模拟未产出可用行为数据」，无块可留时整包为空。truncated / llm_degraded 保留全部块并附审慎
    # 提示；未识别的非 ok 值同样附提示并告警（偏向关闭）。结果记入 forecast.json
    # quality.signal_pack_health（summary 存在却不可读时另记 summary_unreadable 并告警）。
    # ok / 无 summary / 读取失败 → 信号包逐字节不变；false → 旧行为（不读 summary、不记 quality）。
    REPORT_SIGNAL_PACK_HEALTH_GATE = os.environ.get(
        'REPORT_SIGNAL_PACK_HEALTH_GATE', 'true').strip().lower() == 'true'
    # RQ-4：默认 False→True。基线-情景对比表是 what-if 报告的核心可引用工件；仅在有 base
    # 模拟 + 命中「对比/反事实」章节时注入，缺基线时自动 no-op（degrade-safe）。
    REPORT_COMPARISON_TABLE = os.environ.get('REPORT_COMPARISON_TABLE', 'True').strip().lower() == 'true'  # I-3-4 基线-情景对比表
    # R2-KG-7 / RQ-4：确定性「因果骨架」块——以图谱显著度最高的若干 chokepoint 为中心渲染多跳
    # 因果邻域 + 最强 source→outcome 路径，钉进信号包。此前是 getattr 幽灵旋钮（config 从未定义，
    # 在 .env 里设了也无效）；RQ-4 收编为一等属性并默认 True——因果骨架显著抬升报告的机制密度与
    # 引用覆盖。图层多跳遍历有界、任意失败降级为空串，无 actors/无能动角色时为 no-op（degrade-safe）。
    REPORT_CAUSAL_SPINE = os.environ.get('REPORT_CAUSAL_SPINE', 'True').strip().lower() == 'true'
    # 报告背景注入 actor 关系名册 + 激励结构（盟友/对手/竞争者/客户/供应商/出资方…），让叙事更贴角色。
    # 默认开；仅当 actor 携带 relational_roster/incentives 时生效，缺失时为 no-op（与现状一致）。
    REPORT_RELATIONAL_ROSTER = os.environ.get('REPORT_RELATIONAL_ROSTER', 'True').strip().lower() == 'true'
    # —— W9-8：研究昂贵产物直通报告正文（quantitative/contested/timeline 此前落盘后零下游读者）——
    # 证据块总开关：完整 quantitative.json 渲染「关键指标」表（tier+时效排序过滤，替代 actors 内嵌
    # 20 行副本）；完整 contested.json 渲染「承重争议声明」表注入风险/不确定性章节；timeline.json
    # 渲染紧凑时间线注入背景/时间线章节。关闭=回退 actors 内嵌副本（行为与历史一致，degrade-safe）。
    REPORT_EVIDENCE_BLOCKS = os.environ.get('REPORT_EVIDENCE_BLOCKS', 'True').strip().lower() == 'true'
    REPORT_KEY_METRICS_MAX = int(os.environ.get('REPORT_KEY_METRICS_MAX', '40') or '40')          # 关键指标表行数上限
    REPORT_CONTESTED_TABLE_MAX = int(os.environ.get('REPORT_CONTESTED_TABLE_MAX', '15') or '15')  # 争议声明表行数上限
    REPORT_CHRONOLOGY_MAX_EVENTS = int(os.environ.get('REPORT_CHRONOLOGY_MAX_EVENTS', '25') or '25')  # 紧凑时间线事件上限
    # REPORT-8：已核验指标块。研究 quantitative 行带页面核验标签（verification，RESEARCH-4/REPORT-7）时，
    # 背景块改钉「已核验指标」表替代无核验状态的「关键量化指标」表：只收在所引页面核验到数字的已报告值，
    # 预期/目标值单列并标注「不是已发生的结果」，[S#] 只取报告引用索引内的记号（绝不自造），其余行只计数；
    # Part 2 综合注入同一块并附「来源冲突并列呈现、不调和」规则。默认开且安全：无任何行带标签（旧引擎 /
    # 复用研究）或关闭 → 关键指标表与各提示词逐字节不变；构建失败回退关键指标表（degrade-safe）。
    REPORT_VERIFIED_FACTS_BLOCK = os.environ.get('REPORT_VERIFIED_FACTS_BLOCK', 'true').strip().lower() == 'true'
    REPORT_VERIFIED_FACTS_MAX_ROWS = int(os.environ.get('REPORT_VERIFIED_FACTS_MAX_ROWS', '40') or '40')  # 已核验指标块行数上限（超限先丢预期、再丢陈旧、再丢最旧）
    REPORT_VERIFIED_FACTS_MAX_CHARS = int(os.environ.get('REPORT_VERIFIED_FACTS_MAX_CHARS', '6000') or '6000')  # 已核验指标块字符上限（表头与规则段不截断）；Part 2 注入同一块，故也是 Part 2 注入的上限
    # REPORT-9（C11 第 2 阶段，只检测）：报告正文的数字与 REPORT-8「已核验指标」块逐一比对
    # （verified_facts.check_verified_figures：matched / conflict / ambiguous / states_unverified /
    # market_conflict / unmatched），计数记入 forecast.quality.verified_figures 与 final_audit.json 的
    # verified_figures，终审之后写 reports/<id>/figure_provenance.json（每条已核验数字的来源与引用行）。
    # 默认开且安全：从不改成稿字节、从不加硬性或认识论问题、不提升 REPORT_FINAL_AUDIT_POLICY_VERSION；
    # 已核验指标块为空（旧引擎 / 复用研究 / 未核验）时不写任何字段或文件。REL_TOL 为判为冲突所需的
    # 最小相对差（低于它视为同一数字）。
    REPORT_VERIFIED_FIGURES_CHECK = os.environ.get('REPORT_VERIFIED_FIGURES_CHECK', 'true').strip().lower() == 'true'
    REPORT_VERIFIED_FIGURE_REL_TOL = float(os.environ.get('REPORT_VERIFIED_FIGURE_REL_TOL', '0.02') or '0.02')
    # W9-8：KG 结构先验进报告——因果骨架的 chokepoint 支点优先取 graph_priors_structural.json 的
    # 结构咽喉/介数中心度（研究显著度回退）；关系名册每个 actor 附「结构影响力（KG 中心度）」行
    # （按 actors 别名组折叠去重）。关闭=纯显著度选点、不加中心度行（行为与历史一致）。
    REPORT_KG_STRUCTURAL_SPINE = os.environ.get('REPORT_KG_STRUCTURAL_SPINE', 'True').strip().lower() == 'true'
    # W9-5：集成种子报告按主跑情景脊柱打分——scenario_spine 传入时把命名情景钉进骨架推导提示词，
    # 推导后把返回情景名确定性对齐回钉定名（概率自由、新情景可追加），集成聚合才有稳定的按名对齐
    # 坐标。关闭 / scenario_spine 缺省 = 自由起名（行为与历史一致）。
    REPORT_SCENARIO_SPINE_PIN = os.environ.get('REPORT_SCENARIO_SPINE_PIN', 'True').strip().lower() == 'true'
    RECORD_RUN_MANIFEST = os.environ.get('RECORD_RUN_MANIFEST', 'True').strip().lower() == 'true'  # I-8-1 复现清单 run.json
    # EVAL-15：管线终态（completed/failed/cancelled）时在 _run 的 finally 里写确定性分阶段记分卡
    # <pipeline_dir>/stage_scorecard.json（stage-scorecard/v1：已有工件的纯投影 + 契约检查），并把
    # {stage: passed} 摘要折入 state.options.stage_scorecard_summary。默认开（同 RECORD_RUN_MANIFEST
    # 的观测侧车先例）：只读投影、独立 try/except，绝不改 status/pipeline_health、绝不写报告目录。
    # 关闭 = 不写文件、不加 options 键。孤儿/旧跑用 scripts/stage_scorecard.py score 回填。
    STAGE_SCORECARD_ENABLED = os.environ.get('STAGE_SCORECARD_ENABLED', 'true').strip().lower() == 'true'
    # EVAL-19（P07 第 1 部分）：可发布报告在账本提交之后冻结评估包 reports/<id>/eval_bundle/
    # （brief / forecast_inputs / dossier / quant / graph / sim / market 七个输入块的逐字节副本 +
    # manifest：逐块 sha256、研究目标、上游模型与发布指纹），供 EVAL-20 的块移动研究复用同一输入。
    # 纯旁路：不改报告字节、发布状态与账本；默认关（不写任何文件）。EVAL_DOSSIER_CHARS 为 dossier
    # 块的头尾切片字符预算（forecast_extractor.slice_head_tail；≤0 视为默认 16000，回填同规则）。
    EVAL_BUNDLE_CAPTURE = os.environ.get('EVAL_BUNDLE_CAPTURE', 'false').strip().lower() == 'true'
    EVAL_DOSSIER_CHARS = int(os.environ.get('EVAL_DOSSIER_CHARS', '16000') or '16000')
    # EVAL-18: slim per-pipeline cost card. On: the _run finally block writes
    # <pipeline_dir>/cost_card.json (drf-cost-card/v1: per-stage calls/tokens/wall first, USD
    # secondary, completeness reasons), and the report stage pins the run's config fingerprint
    # in options.config_hash_v1 and stamps that config_hash on its ledger commit rows, so cost
    # and forecast quality can later be joined per configuration. Each attempt start removes
    # the previous attempt's card and pins its unattributed-spend baseline in
    # options.cost_card_attempt_v1 (so an orphan rebuild never borrows another attempt's
    # baseline), and each stage wall window's opening is pinned in
    # options.cost_card_windows_v1 (its start and the calls earlier attempts had made in the
    # stage, so the card can name the walls that do not time all of a row's calls).
    # Default on, like the other observation sidecars (RECORD_RUN_MANIFEST,
    # STAGE_SCORECARD_ENABLED): it only projects durable artifacts in its own try/except,
    # never writes the report folder and never changes status or health. Off = no file, no
    # options keys, no ledger stamp (byte-identical).
    # Backfill: scripts/cost_card.py build <pipeline_id>.
    COST_CARD_ENABLED = os.environ.get('COST_CARD_ENABLED', 'true').strip().lower() == 'true'
    # INFRA-7：run-shape 准入钉（与 safety_policy_v1 并列的第二份准入快照）。开启时 start/fork/批次分叉
    # 把影响结果的旋钮（ACTOR_CAST_MAX、GRAPH_MAX_ENTITIES、SIM_TEMPORAL_MODE…）与 provider/model
    # 出处钉进 options.run_shape_v1，每个 attempt 起点对比当前环境并记录漂移；run.json 保留历次
    # attempt 与复用阶段的原 provider 戳（不再在阶段进入时按当前 provider 重戳），遥测标注每阶段是否复用。
    # 默认开：只增加记录、不改变任何阶段的执行语义（漂移默认只记录）。关闭 = 与引入前逐字节一致。
    RUN_SHAPE_PIN = os.environ.get('RUN_SHAPE_PIN', 'true').strip().lower() == 'true'
    # INFRA-7：resume 时 identity 旋钮漂移的处置。record（默认）= 告警 + 记录后继续；refuse = 以点名
    # 漂移旋钮的错误使本次 attempt 失败。provider/model 仅漂移永不拒绝。未知值按 record 处理并告警。
    RUN_SHAPE_DRIFT_POLICY = os.environ.get('RUN_SHAPE_DRIFT_POLICY', 'record').strip().lower()
    # INFRA-7：resume 血统守卫。上游阶段被重算后，拒绝复用由其旧产物派生的下游产物
    # （研究重算→本体/图谱重建；图谱重算或模拟绑定的 graph_id 不符→重建 PREPARE；RUN 重算或报告绑定的
    # simulation_id 不符→重生成报告），在 options.stage_notes 留 'reuse_refused: <原因>' 面包屑。失效记录
    # 持久化在 options.lineage_invalidated，直到该阶段从当前上游重建才清除——下游重建失败后的下一次 resume
    # 仍拒绝复用陈旧产物；重建已保存的新本体（落盘即结清）与已完成（COMPLETED）的铸出报告（id 记在
    # options.lineage_rebuilt）在打断后的下次 resume 被复用而非再生成。默认开：以重算成本换取不复用陈旧产物
    # （fail closed）；关闭 = 旧的逐阶段存在性复用。
    RESUME_LINEAGE_GUARDS = os.environ.get('RESUME_LINEAGE_GUARDS', 'true').strip().lower() == 'true'
    # INFRA-8: model provenance. On, LLMMeter records per stage which model each call requested
    # (the effective label: a claude-cli call without --model is 'cli-default') and which model
    # the provider reported serving it (snapshot 'model_resolution'; the simulation child writes
    # its own into sim_llm_telemetry.json); research v3 ledger rows and usage summaries carry
    # model/served_model and the v3 work-dir identity gains the resolved model id (a side
    # without one stays compatible, so existing work dirs still resume); run.json resolved
    # blocks gain requested_model/requested_source/requested_models/served_models/
    # model_resolution; forecast.json gains a 'model_provenance' block. The per-call labels and
    # served ids of LLMClient calls come from LLMMeter, so they need LLM_TELEMETRY_ENABLED=true;
    # a stage with no recorded call names the configured provider/model pair instead, marked
    # requested_source='configured' (tier routing or failover may have sent another model).
    # Both children get this value from Config (research-child registry, simulation env).
    # Default on: it only adds recorded keys and changes no call, routing or gate; the one
    # behavioural effect is that a research resume no longer reuses a v3 work dir produced by
    # a different resolved model id. Off = byte-identical to before.
    RECORD_MODEL_PROVENANCE = os.environ.get('RECORD_MODEL_PROVENANCE', 'true').strip().lower() == 'true'
    # INFRA-9：分叉继承安全政策钉。开启时情景分叉（PipelineOrchestrator.fork）与批次问题分叉
    # （scripts/batch_runs.fork_question）深拷贝 base 的 options.safety_policy_v1（origin=fork_inherited）；
    # base 无钉（Foglamp WP1 之前准入）时在分叉准入时捕获当前环境政策（默认 Config 下即安全政策，
    # origin=fork_admission）。默认开：分叉沿用 base 的研究/图谱继续预测，其图谱反馈/种子/extremize/
    # 模拟影响语义不得随服务重载后的环境默认值漂移；只影响分叉。注意：分叉与 base 共用 graph_id——
    # base 以 SIM_GRAPH_FEEDBACK=true 准入时分叉继承 sim_graph_feedback=true，其模拟（含情景注入的
    # 反事实事件）会写入 base 与兄弟分叉共享的观察图；分叉准入时对此记 warning（点名共享图谱）。
    # 关闭 = 旧行为（分叉不带钉，每个读点回退当前环境值）。
    FORK_INHERIT_SAFETY_POLICY = os.environ.get('FORK_INHERIT_SAFETY_POLICY', 'true').strip().lower() == 'true'
    # INFRA-11：严格的 actor 名匹配（名字身份查找歧义即失败，不再猜）。开启时报告工具 opinion_shift 先按
    # 研究名册解析目标（标准化精确名/别名，规范名优先于他人别名 → 名册与动作日志两边合并的 ≥4 字符包含），
    # 多个候选时返回点名全部候选的说明而不是把各自轨迹混在一起（旧的无界子串匹配让 'US' 同时命中
    # Russia/Australia），经别名/包含解析时在输出标题里点名解析结果；trace_cascade 的节点名解析先查名册
    # 别名（不用被两个 actor 争用的别名），包含匹配下限从 2 字符提到 4 字符并要求唯一命中；实体消解的
    # actor_alias_map 排除被两个不同 actor 同时认领的别名（记日志），不再后写者胜。默认开：主要把原先的
    # 错配变成「未解析/歧义」；注意它也不再解析短于 4 字符的唯一包含（如 'Fed' → 'Federal Reserve'），
    # 除非该短名正是名册里的精确名或别名。关闭 = 旧匹配。
    # （actor id 的非拉丁名修复不受此旋钮控制：拉丁名 id 本就不变。）
    ACTOR_NAME_MATCH_STRICT = os.environ.get('ACTOR_NAME_MATCH_STRICT', 'true').strip().lower() == 'true'

    # —— EXECPLAN2 第三波改进旋钮（剩余 L-effort 新能力；全部默认关，留空即保持当前行为）——
    # 预测质量回归评测开关（EXECPLAN2 I-7-7）：opt-in，绝不进默认 CI。开启后 eval_forecast_quality.py
    # 用 LLM-judge 按 rubric 给固定情景集打分并与 baseline 对比。默认关。
    EVAL_ENABLED = os.environ.get('EVAL_ENABLED', 'False').strip().lower() == 'true'  # I-7-7 预测质量评测
    # EVAL-1 黄金题评测账本写入开关：opt-in。golden_eval.py 默认只读打分（写 eval_report.json/markdown）；
    # 仅当本旋钮开启（或 CLI 显式 --to-ledger）时才把已解析黄金题作为二元(YES/NO)预测追加进校准账本，
    # 让 report_visualizer 校准曲线累积黄金题结局。默认关=不污染生产账本（degrade-safe）。
    GOLDEN_EVAL_LEDGER = os.environ.get('GOLDEN_EVAL_LEDGER', 'False').strip().lower() == 'true'  # EVAL-1
    # EVAL-8: golden_eval headline tiering. On, score-forecast-file classifies every matched row from
    # the run's provenance (--pipeline-dir / --run-created-at): only a prospective row (the run, from
    # creation through its last recorded activity, came before the question resolved and within
    # GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS of its as_of_date, and was no pinned hindcast) counts
    # toward the headline; every other row is characterization only, a headline without such rows is
    # withheld, and score-ledger splits golden rows by golden_tier the same way. Default on is safe: the
    # scorer is offline and characterization-only, the legacy 'metrics' block is unchanged, and a
    # headline that cannot be backed is withheld, never invented.
    # false = the pre-EVAL-8 reports (no headline / characterization keys, no golden_tier on rows).
    GOLDEN_HEADLINE_GATE = os.environ.get('GOLDEN_HEADLINE_GATE', 'true').strip().lower() == 'true'
    # EVAL-8: how many days after a golden question's as_of_date a run may still be active and count as
    # prospective (keeps information sets comparable across code versions); must be 0-3650. golden_eval
    # refuses a value it cannot read (the import audit's default 7) instead of scoring with it.
    GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS = int(
        os.environ.get('GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS', '7') or '7')
    # EVAL-13: under an evaluation run whose pin carries a target proposition, a target the binary
    # extraction did not produce verbatim gets exactly one bounded repair draw that asks only for
    # that statement; the row is kept only on a normalized match, never fabricated. Default on is
    # safe: it is inert unless PipelineOrchestrator.start(evaluation=...) pinned a target, so
    # production runs never see the addendum or the extra draw. false = no repair draw (the target
    # is reported under forecast.evaluation.target_binding.missing).
    EVAL_TARGET_REPAIR_DRAW = os.environ.get('EVAL_TARGET_REPAIR_DRAW', 'true').strip().lower() == 'true'

    # —— 运维脚本旋钮（此前各脚本用 getattr(Config, ...) 读但 config.py 从未定义 → "幽灵旋钮"：
    #    在 .env 里设了也无效。这里收口为真实可读项 + .env.example 文档化，消除该反模式）——
    # 定时重跑（scripts/scheduled_rerun.py，NEXTSTEPS P2-4 / I-9-6）。默认关：daemon/tick 才生效。
    SCHEDULER_ENABLED = os.environ.get('SCHEDULER_ENABLED', 'False').strip().lower() == 'true'
    SCHEDULER_TICK_SECONDS = int(os.environ.get('SCHEDULER_TICK_SECONDS', '300') or '300')
    SCHEDULER_MAX_CONCURRENT = int(os.environ.get('SCHEDULER_MAX_CONCURRENT', '1') or '1')
    # 漂移检测阈值（情景概率 |Δ| ≥ 此值即判材料性漂移）+ 漂移 webhook（SSRF 校验后回调）。
    DRIFT_PROB_THRESHOLD = float(os.environ.get('DRIFT_PROB_THRESHOLD', '0.15') or '0.15')
    DRIFT_WEBHOOK_URL = os.environ.get('DRIFT_WEBHOOK_URL', '').strip()
    # 多问题批跑（scripts/batch_runs.py，I-9-3）：单锚点图谱上的最大分叉问题数（成本护栏）。
    BATCH_MAX_FANOUT = int(os.environ.get('BATCH_MAX_FANOUT', '8') or '8')
    BATCH_SHARED_SIMULATION = os.environ.get('BATCH_SHARED_SIMULATION', 'False').strip().lower() == 'true'

    # ============================================================
    # R2 审计修复旋钮汇口（CFG-1 幽灵旋钮收编 + 各组新旗标集中定义）。
    # 全部有安全默认：env 未设时行为与修复前逐字节一致（或按各 finding 的既定默认）。
    # 消费方多为 getattr(Config, NAME, default) 或 env-first 读取，两者与此处定义兼容。
    # ============================================================
    # —— CFG-1：管线编排幽灵旋钮（此前仅 getattr 读、config 从未定义 → .env 设了也无效）——
    # I-4-1 心跳看护：owner 指纹 + 壁钟心跳，让 reconcile 区分「死管线」与「慢但活」。
    PIPELINE_HEARTBEAT_ENABLED = os.environ.get('PIPELINE_HEARTBEAT_ENABLED', 'true').strip().lower() == 'true'
    PIPELINE_HEARTBEAT_INTERVAL_S = float(os.environ.get('PIPELINE_HEARTBEAT_INTERVAL_S', '30') or '30')
    PIPELINE_HEARTBEAT_STALE_S = float(os.environ.get('PIPELINE_HEARTBEAT_STALE_S', '120') or '120')
    # I-5-6 状态 API 的 staleness 判定与 ETA 外推上限。
    PIPELINE_STALE_S = float(os.environ.get('PIPELINE_STALE_S', '300') or '300')
    PIPELINE_ETA_CAP_S = float(os.environ.get('PIPELINE_ETA_CAP_S', '7200') or '7200')
    # I-4-6 运行中临时产物深链 + 扫描节流；I-4-3 复用前产物完整性校验。
    PIPELINE_LIVE_ARTIFACTS = os.environ.get('PIPELINE_LIVE_ARTIFACTS', 'true').strip().lower() == 'true'
    PIPELINE_PARTIAL_SCAN_EVERY_S = float(os.environ.get('PIPELINE_PARTIAL_SCAN_EVERY_S', '10') or '10')
    PIPELINE_VALIDATE_ARTIFACTS = os.environ.get('PIPELINE_VALIDATE_ARTIFACTS', 'true').strip().lower() == 'true'
    # VIZ-2 可视化产物通道：把 handoff/charts/*.png|svg(+charts.json 清单) 与 handoff/data/*.csv
    # 纳入产物 specs（→ manifest 完整性登记 + 运行中 *_partial 深链）。老跑不产出这些文件时，
    # 各机制按「文件缺失即跳过」自然降级，从不误伤健康/完整性校验。默认 true（缺文件即 no-op）。
    PIPELINE_VIZ_ARTIFACTS = os.environ.get('PIPELINE_VIZ_ARTIFACTS', 'true').strip().lower() == 'true'
    # I-8-1 run.json 是否附带关键包版本（pip 枚举有开销，默认关）。
    MANIFEST_CAPTURE_VERSIONS = os.environ.get('MANIFEST_CAPTURE_VERSIONS', 'false').strip().lower() == 'true'
    # SIM-11 persona 并行扇出（HTTP 提供方；CLI 固定 3）。
    PARALLEL_PROFILE_COUNT = int(os.environ.get('PARALLEL_PROFILE_COUNT', '16') or '16')
    # R2-EXEC-7 研究阶段后台预热嵌入器；R2-RES-7 as_of 双时态锚校验；建图输入源。
    EMBED_WARM_AT_RESEARCH = os.environ.get('EMBED_WARM_AT_RESEARCH', 'false').strip().lower() == 'true'
    VALIDATE_AS_OF_DATE = os.environ.get('VALIDATE_AS_OF_DATE', 'true').strip().lower() == 'true'
    # TIME-1: v3 actor extraction may not override the research as-of.  On, actors.json
    # as_of_date is always the plan's as-of (the UTC date fixed when the research plan was
    # made); a different model value is only recorded in meta.json
    # (as_of_model_disagreement).  That date becomes the graph valid_at/reference_time and
    # the simulation calendar anchor, and a model once reported its training cutoff as the
    # as-of.  Honesty fix, so default on and parsed fail-closed like the bridge's _env_flag:
    # only 0/false/no/off turn it off.  false = the model-supplied YYYY-MM-DD value is
    # adopted again (previous bytes).  The parent forwards it to the v3 child.
    RESEARCH_AS_OF_PIN = os.environ.get(
        'RESEARCH_AS_OF_PIN', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
    # TIME-7 hindcast admission: accept as_of (a canonical past-or-today YYYY-MM-DD) on run
    # requests (/api/research/run, /api/v1/run, PipelineOrchestrator.start).  An admitted
    # as_of pins hindcast_policy_v1 plus an evaluation-run pin, runs v3 research with
    # RESEARCH_AS_OF and prediction markets withheld, and anchors the graph at the pin.
    # Default false, which is safe: a request carrying as_of is then rejected (400 /
    # ValueError) instead of silently running live; requests without as_of are unchanged.
    HINDCAST_ENABLED = os.environ.get('HINDCAST_ENABLED', 'false').strip().lower() == 'true'
    # TIME-8 point-in-time evidence gates of a hindcast's v3 research.  Read only at
    # admission (hindcast_policy.capture_hindcast_policy_v1 pins them as the pin's 'pit'
    # block; a resume or a later config change never alters an admitted run) and
    # effective only inside a pinned hindcast, which itself needs HINDCAST_ENABLED, so
    # live runs are unaffected whatever these say.  On, a source whose latest known
    # publication/update date is after the as-of never gets an [S<n>] id or a stored
    # page: late search rows are dropped before registration, URL-dated-late fetches
    # are refused without budget and late pages are withheld before storage.  TIME-9:
    # the report then cites only sources admissible as of the as-of, and the research
    # audit (point_in_time.json) sets forecast.json hindcast.integrity and run.json
    # as_of_enforcement.  An honesty check, so default on and parsed fail-closed: only
    # 0/false/no/off disable it.
    PIT_GATES = os.environ.get('PIT_GATES', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
    # TIME-8: whether a source available on the as-of day itself is admitted.  exclude
    # (default, strict: evidence must predate the as-of) | include.  Anything else is exclude.
    PIT_SAME_DAY_POLICY = ('include' if os.environ.get('PIT_SAME_DAY_POLICY', 'exclude').strip().lower()
                           == 'include' else 'exclude')
    # TIME-8: a fetched page with no readable date.  drop (default, fail closed: withheld
    # like a late page) | flag (stored, pit_status 'unverifiable', labelled undated).
    # drop can starve undated data pages; flag trades that for unverified evidence.
    # Anything else is drop.
    PIT_UNDATED_POLICY = ('flag' if os.environ.get('PIT_UNDATED_POLICY', 'drop').strip().lower()
                          == 'flag' else 'drop')
    # TIME-8: ask the search provider for a date bound (Firecrawl tbs cd_max at the
    # as-of; other providers cannot and are counted unbounded; a bounded request the
    # provider rejects is retried once unbounded).  The primary control; the row gate
    # still runs on every result, and gated search cache entries are keyed apart from
    # live ones either way.  Default on; only 0/false/no/off disable it.
    PIT_PROVIDER_DATE_BOUNDS = os.environ.get(
        'PIT_PROVIDER_DATE_BOUNDS', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
    # TIME-8: rows requested per gated search = 5 x this, so dropped late rows do not
    # starve the render slots; clamped to 1..4 where it is pinned at admission
    # (hindcast_policy.PIT_OVERFETCH_MAX).  Default 1 (no over-fetch: the provider bound
    # is the primary control and each extra row can be billed).
    PIT_SEARCH_OVERFETCH = int(os.environ.get('PIT_SEARCH_OVERFETCH', '1') or '1')
    # W9-10：建图输入源默认 both→dossier_only——用户明确要求 KG 收敛到关键 actor：actor 中心的
    # 卷宗切块入图，广覆盖研究报告只喂本体/报告上下文（graph 阶段 8h38m/60% 跳块的主要输入面）。
    # dossier 缺失/为空时代码自动回退 both 语义（全量报告切块），设 'both' 可显式恢复旧行为。
    GRAPH_CHUNK_SOURCE = os.environ.get('GRAPH_CHUNK_SOURCE', 'dossier_only').strip().lower()  # both|dossier_only|report_only
    # W9-1/W9-3：孤儿回收打捞 + run 遥测增量落盘。
    # 打捞：reconcile_orphans 遇到「report 阶段已完成且 full_report.md+forecast.json 在盘」的
    # running 孤儿时，落成 completed(pipeline_health=degraded, 集成跳过) 而非 failed——两条 $10+
    # 的跑曾带着完整报告被整线判死。设 false 回退「一律判 failed」。
    PIPELINE_SALVAGE_COMPLETED_ORPHANS = os.environ.get('PIPELINE_SALVAGE_COMPLETED_ORPHANS', 'true').strip().lower() == 'true'
    # 遥测增量 flush 的调用步长：每新增 N 次 LLM 调用（在心跳/进度回调上检查）+ 每次阶段转换，
    # 把 LLMMeter 快照落盘 run_telemetry.json——重启不再清零整跑的 token/成本账。<=0 关增量
    # flush（仅保留终态一次性落盘 = 旧行为）。
    PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS = int(os.environ.get('PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS', '20') or '20')

    # —— ORCH-2/ORCH-8/XRUN-3：编排器/CLI 鲁棒性 ——
    # 启动回收前先探测本机端口是否已有后端在服务：占用则整体跳过孤儿回收（注定 Address-in-use
    # 而死的重复进程不得破坏活进程拥有的管线状态）。
    PIPELINE_RECLAIM_PORT_PROBE = os.environ.get('PIPELINE_RECLAIM_PORT_PROBE', 'true').strip().lower() == 'true'
    # 与管线回收同构：第二个后端（或任何误启动的 app factory）若发现目标端口已有
    # 健康 owner，不得在自身绑定端口失败之前先终止那个 owner 的活模拟。
    SIMULATION_RECLAIM_PORT_PROBE = os.environ.get(
        'SIMULATION_RECLAIM_PORT_PROBE', 'true'
    ).strip().lower() == 'true'
    # 报告阶段起飞前 ~10 token 探测主/回退提供方可用性；双双不可用时 <60s 内以可恢复的
    # REPORT 阶段失败收场，而不是烧完全部章节成本后才被健康门拦下。
    REPORT_LLM_PREFLIGHT = os.environ.get('REPORT_LLM_PREFLIGHT', 'true').strip().lower() == 'true'
    # claude CLI 子进程隔离操作员的全局 ~/.claude hooks（--settings 内联 disableAllHooks，
    # 保留 OAuth；--bare 会丢登录态故不用）。SessionEnd 钩子曾让 2769+ 次管线调用空错误失败。
    LLM_CLI_ISOLATE_HOOKS = os.environ.get('LLM_CLI_ISOLATE_HOOKS', 'true').strip().lower() == 'true'

    # —— 研究组（RES-*；deerflow bridge 在自己的 venv 里直读 os.environ，此处定义仅为
    #    配置面单一真源 + 编排器侧镜像守卫消费；bridge 不 import Config）——
    ACTOR_SYNTH_MIN_CONTEXT_CHARS = int(os.environ.get('ACTOR_SYNTH_MIN_CONTEXT_CHARS', '3000') or '3000')
    RESEARCH_MIN_REPORT_CHARS = int(os.environ.get('RESEARCH_MIN_REPORT_CHARS', '400') or '400')
    RESEARCH_FETCH_ACCOUNTING_V2 = os.environ.get('RESEARCH_FETCH_ACCOUNTING_V2', 'true').strip().lower() == 'true'
    RESEARCH_ASOF_MAX_LAG_DAYS = int(os.environ.get('RESEARCH_ASOF_MAX_LAG_DAYS', '45') or '45')
    RESEARCH_QUALITY_GROUNDING = os.environ.get('RESEARCH_QUALITY_GROUNDING', 'true').strip().lower() == 'true'
    ACTOR_DOSSIER_JUDGE_STRICT = os.environ.get('ACTOR_DOSSIER_JUDGE_STRICT', 'false').strip().lower() == 'true'
    RESEARCH_COVERAGE_GATE_STANDARD = os.environ.get('RESEARCH_COVERAGE_GATE_STANDARD', 'false').strip().lower() == 'true'
    # W9-9：研究子进程接入后端 KG MCP server（deerflow_bridge/extensions_config.json 部署副本）。
    # 仅在图谱已存在的路径（fork/continue/resume-with-graph，即 state.graph_id 非空）下发
    # DEER_FLOW_EXTENSIONS_CONFIG_PATH + DRF_MCP_KG_GRAPH_ID——what-if/续跑研究可直接查基线 KG
    # （kg_search/kg_trace_cascade）而非重搜网页。首跑无图谱时不下发，行为与今日逐字节一致。
    RESEARCH_MCP_KG = os.environ.get('RESEARCH_MCP_KG', 'true').strip().lower() == 'true'
    # W9-7：多轨研究卷宗合并后的一次有界 LLM 整理——合并 K 份执行摘要为单一开篇、'# Track N' H1
    # 降级为 '## Part N — <english title>' H2、输出「跨轨分歧」小节点名冲突的头条数字。仅喂各轨
    # 执行摘要（cap ~30K 字符）；任何失败降级为纯拼接（与今日逐字节一致）。
    RESEARCH_TRACK_RECONCILE = os.environ.get('RESEARCH_TRACK_RECONCILE', 'true').strip().lower() == 'true'
    # LOOP-007: one cross-process budget ledger bounds multiplicative outer tracks,
    # dual workflows, phases, and subagents at the actual search/fetch boundary.
    RESEARCH_BUDGET_ENABLED = os.environ.get(
        'RESEARCH_BUDGET_ENABLED', 'true').strip().lower() == 'true'
    RESEARCH_BUDGET_ATTEMPTS_GLOBAL = int(os.environ.get(
        'RESEARCH_BUDGET_ATTEMPTS_GLOBAL', '1800') or '1800')
    RESEARCH_BUDGET_SEARCH_GLOBAL = int(os.environ.get(
        'RESEARCH_BUDGET_SEARCH_GLOBAL', '900') or '900')
    RESEARCH_BUDGET_SEARCH_LANE = int(os.environ.get(
        'RESEARCH_BUDGET_SEARCH_LANE', '360') or '360')
    RESEARCH_BUDGET_FETCH_GLOBAL = int(os.environ.get(
        'RESEARCH_BUDGET_FETCH_GLOBAL', '450') or '450')
    RESEARCH_BUDGET_FETCH_LANE = int(os.environ.get(
        'RESEARCH_BUDGET_FETCH_LANE', '180') or '180')
    # One explicit pipeline task/resume owns one independently bounded ledger.
    # Keep a small hard ceiling so repeated resumes cannot create unbounded paid
    # search/fetch epochs while still allowing a timed-out deep run to recover.
    RESEARCH_BUDGET_MAX_EPOCHS = int(os.environ.get(
        'RESEARCH_BUDGET_MAX_EPOCHS', '3') or '3')
    RESEARCH_NEGATIVE_CACHE_TTL_SECONDS = int(os.environ.get(
        'RESEARCH_NEGATIVE_CACHE_TTL_SECONDS', '600') or '600')
    RESEARCH_NEGATIVE_CACHE_RETRIES = int(os.environ.get(
        'RESEARCH_NEGATIVE_CACHE_RETRIES', '1') or '1')
    # LOOP-007B: raw per-track actor prose remains auditable under track_N/;
    # graph extraction consumes one bounded canonical cast + one-hop dossier.
    RESEARCH_COMPACT_MERGED_DOSSIER = os.environ.get(
        'RESEARCH_COMPACT_MERGED_DOSSIER', 'true').strip().lower() == 'true'
    ACTOR_DOSSIER_MAX_CHARS = int(os.environ.get(
        'ACTOR_DOSSIER_MAX_CHARS', '80000') or '80000')
    # W9-11：研究卷宗定稿后跑确定性编辑 lint（report_lint.lint_report(md, lang, mode='research')，
    # 清理 [citation:...] 残渣、pass/working-notes 叙述泄漏等机器语法）。模块未部署（ImportError）
    # 或本旋钮为 false 时静默跳过（degrade-safe）。
    REPORT_LINT = os.environ.get('REPORT_LINT', 'true').strip().lower() == 'true'

    # —— 本体/准备组（ONT-1/PREP-*/XRUN-10；utils/actors.py 与 config 生成器经 getattr 读取）——
    ONTOLOGY_SEED_ADAPTIVE_BUDGET = os.environ.get('ONTOLOGY_SEED_ADAPTIVE_BUDGET', 'true').strip().lower() == 'true'
    SIM_EVENT_REACT_BUFFER = os.environ.get('SIM_EVENT_REACT_BUFFER', 'true').strip().lower() == 'true'
    SIM_SCHEDULE_CLAMP_ROUNDS = os.environ.get('SIM_SCHEDULE_CLAMP_ROUNDS', 'true').strip().lower() == 'true'
    SIM_RULE_FALLBACK_STANCE = os.environ.get('SIM_RULE_FALLBACK_STANCE', 'true').strip().lower() == 'true'
    SIM_SEED_POST_VARIANTS = os.environ.get('SIM_SEED_POST_VARIANTS', 'true').strip().lower() == 'true'
    PERSONA_FIELD_EXTRACTION = os.environ.get('PERSONA_FIELD_EXTRACTION', 'true').strip().lower() == 'true'

    # —— 图谱组（KG-*/ONT-7；graph_builder / zep_entity_reader / report 检索经 getattr 读取）——
    GRAPH_CHOKEPOINT_PRIORS = os.environ.get('GRAPH_CHOKEPOINT_PRIORS', 'false').strip().lower() == 'true'
    try:
        GRAPH_CHOKEPOINT_MAX_NODES = int(os.environ.get('GRAPH_CHOKEPOINT_MAX_NODES', '1500') or '1500')
    except ValueError:
        GRAPH_CHOKEPOINT_MAX_NODES = 1500
    if GRAPH_CHOKEPOINT_MAX_NODES <= 0:
        GRAPH_CHOKEPOINT_MAX_NODES = 1500
    GRAPH_PRIORS_ALIAS_FOLD = os.environ.get('GRAPH_PRIORS_ALIAS_FOLD', 'true').strip().lower() == 'true'
    GRAPH_MAX_SKIPPED_RATIO = float(os.environ.get('GRAPH_MAX_SKIPPED_RATIO', '0.3') or '0.3')
    SIM_TIER_FROM_ONTOLOGY = os.environ.get('SIM_TIER_FROM_ONTOLOGY', 'false').strip().lower() == 'true'
    # KG-2: 图谱检索查询长度上限。0=自动（GRAPHITI_REMOTE=true 时 380，本地后端 1200）。
    GRAPH_QUERY_MAX_CHARS = int(os.environ.get('GRAPH_QUERY_MAX_CHARS', '0') or '0')
    GRAPH_QUERY_CLAMP_SEMANTIC = os.environ.get('GRAPH_QUERY_CLAMP_SEMANTIC', 'true').strip().lower() == 'true'

    # —— 运行环组（RUN-*/XRUN-*；run_parallel_simulation.py 以 env-first 再 getattr 读取）——
    SIM_START_HOUR = int(os.environ.get('SIM_START_HOUR', '0') or '0')          # 0-23；time_config.start_hour 优先
    SIM_RECENCY_CARRY = os.environ.get('SIM_RECENCY_CARRY', 'false').strip().lower() == 'true'
    SIM_TWITTER_MODEL_FREE_FEED = os.environ.get('SIM_TWITTER_MODEL_FREE_FEED', 'true').strip().lower() == 'true'
    SIM_TOOL_ARG_NORMALIZE = os.environ.get('SIM_TOOL_ARG_NORMALIZE', 'true').strip().lower() == 'true'
    SIM_IDLE_CLOSE_MIN = float(os.environ.get('SIM_IDLE_CLOSE_MIN', '60') or '60')  # <=0 = 无限等待
    SIM_LLM_ERROR_RATE_THRESHOLD = float(os.environ.get('SIM_LLM_ERROR_RATE_THRESHOLD', '0.5') or '0.5')
    SIM_RESUME = os.environ.get('SIM_RESUME', 'false').strip().lower() == 'true'
    # DEFECT-1 (resume 复用已完成模拟)：RUN 阶段启动时，若 sim 目录已存在「绑定同一份密封
    # simulation_config 的已完成模拟」（每个启用平台的 simulation_end 完成标记 + 有效
    # run_summary + simulation_config seal 身份校验通过），直接复用产物、不再重启模拟子进程
    # （2026-07-15 取证：resume 对着耗尽的配额把同一场 18 轮模拟重跑 4 次，损失 3h34m）。
    # 置 false 恢复旧行为（stage 位丢失即无条件重跑）。不完整/无效/身份不匹配的模拟仍照旧重跑。
    SIM_RESUME_REUSE_COMPLETED = os.environ.get('SIM_RESUME_REUSE_COMPLETED', 'true').strip().lower() == 'true'
    # ITEM 3: 轮级检查点写入开关（默认开）。开启时每轮原子落盘 <platform>/checkpoint.json
    # （含 config_hash + python-random RNG 状态），使任意崩溃/被杀/后端重启后的运行可被续跑；
    # 续跑本身仍由 SIM_RESUME/--resume 触发。置 false → 不产出 checkpoint.json（RUN-7 早期 degrade-safe 行为）。
    SIM_CHECKPOINT = os.environ.get('SIM_CHECKPOINT', 'true').strip().lower() == 'true'
    INTERVIEW_TIMEOUT_PER_AGENT = float(os.environ.get('INTERVIEW_TIMEOUT_PER_AGENT', '30') or '30')
    SIM_CLI_TOOL_EMULATION = os.environ.get('SIM_CLI_TOOL_EMULATION', 'true').strip().lower() == 'true'
    SIM_LLM_FALLBACK = os.environ.get('SIM_LLM_FALLBACK', 'true').strip().lower() == 'true'
    SIM_MIN_FREE_DISK_GB = float(os.environ.get('SIM_MIN_FREE_DISK_GB', '2') or '2')  # <=0 关闭
    SIM_STEP_FAILURE_LIMIT = int(os.environ.get('SIM_STEP_FAILURE_LIMIT', '3') or '3')  # 0 = 旧的无限跳轮
    # ITEM 20 模拟真实感四件套（均 env 门控、默认安全、可降级）：
    # (1) 参与度采样：每轮有机动作后从活跃 agent 确定性采样 LIKE_POST 落到本轮新帖上（权重∝该帖
    #     本轮已获互动），补足 OASIS 默认 feed「满屏帖 0 赞」的纯广播失真。采样赞标记 is_engagement_sample，
    #     供有机比例侦测器排除（诚实：采样赞不掩盖 agent 自身零点赞）。rate=每个活跃者本轮产生一次赞的概率。
    #     auto（默认）= 仅在回应阶段关闭时开启：采样赞是随机「背书」，会产生与角色矛盾的互动
    #     （如出口管制机构给被管制方点赞）；回应阶段里点赞由 agent 按身份自己决定。true/false 强制。
    SIM_ENGAGEMENT_SAMPLER = os.environ.get('SIM_ENGAGEMENT_SAMPLER', 'auto').strip().lower()
    SIM_ENGAGEMENT_RATE = float(os.environ.get('SIM_ENGAGEMENT_RATE', '0.3') or '0.3')  # [0,1] clamp
    # SIM-REACT 回应阶段：每轮发帖 step 之后，活跃 agent 各做一次只含回复与背书工具（评论/点赞）的
    # 调用，回应按角色相关性挑出的他人帖子（本轮+上轮，含别人对自己帖子的回复）。OASIS 每个 agent
    # 每轮只有一次模型调用，此前几乎全部用来发帖（200 帖 : 9 评论）。false 关闭（旧行为）。
    SIM_REACTION_PHASE = os.environ.get('SIM_REACTION_PHASE', 'true').strip().lower() == 'true'
    SIM_REACTION_SHARE = float(os.environ.get('SIM_REACTION_SHARE', '1.0') or '1.0')  # [0,1]：参与回应的活跃 agent 比例
    # 模拟发帖/回应语言覆盖（English/Chinese）；空 = 用配置的 output_language，缺省按预测问题的语言判定。
    SIM_OUTPUT_LANGUAGE = os.environ.get('SIM_OUTPUT_LANGUAGE', '').strip()
    # (3) 种子 FOLLOW 风暴节流：每个 follower 的种子 FOLLOW 动作上限（add_edge 建图不受影响，仅截断
    #     写 trace/follow 表的 FOLLOW 动作），避免 630 条种子关注淹没早期动作日志。<=0 = 不限（旧行为）。
    SIM_MAX_FOLLOWS_PER_AGENT_ROUND = int(os.environ.get('SIM_MAX_FOLLOWS_PER_AGENT_ROUND', '3') or '3')
    # (2) 有机比例塌缩侦测：逐平台逐轮跟踪 post:comment:like，连续 ≥K 轮 posts>0 而 comments+likes==0
    #     时把结构化告警写入 run_summary（检测+诚实优先，绝不伪造互动）。
    SIM_ORGANIC_RATIO_DETECTOR = os.environ.get('SIM_ORGANIC_RATIO_DETECTOR', 'true').strip().lower() == 'true'
    SIM_ORGANIC_RATIO_MIN_CONSECUTIVE = int(os.environ.get('SIM_ORGANIC_RATIO_MIN_CONSECUTIVE', '3') or '3')
    # SIM-3 (C26): 采样赞（action_args.is_engagement_sample，引擎随机代点）不是 agent 的决策，
    #     不计入 run_summary 的 organic_action_count / rounds_with_organic_actions——否则只有采样赞
    #     与定时事件帖的零自主运行逃过 'hollow'（summary 与管线健康门两处）。排除数写
    #     engagement_sample_count（>0 才写）。默认开是诚实修正：只会把此类运行如实标为 hollow；
    #     false 恢复旧计数（采样赞算有机）。
    SIM_ORGANIC_EXCLUDES_ENGAGEMENT_SAMPLES = os.environ.get(
        'SIM_ORGANIC_EXCLUDES_ENGAGEMENT_SAMPLES', 'true').strip().lower() == 'true'
    # SIM-3 (C16): 定时事件可达性审计——round 非法/≥ total_rounds、缺发帖者或内容的
    #     scheduled_events 永远不会触发（fire_scheduled_events 静默跳过），模拟角色从未看到它们。
    #     仅当存在不可达事件时 run_summary 写 schedule_audit，管线运行健康记 'degraded' issue
    #     （绝不判失败）；全部可达 → summary 键逐字节不变，故默认开安全。false 关闭审计。
    SIM_SCHEDULE_AUDIT = os.environ.get('SIM_SCHEDULE_AUDIT', 'true').strip().lower() == 'true'

    # —— 报告组（RPT-*/XRUN-1/XRUN-5/RPT-6/RPT-8；report_agent / forecast_extractor 经 getattr 读取）——
    REPORT_ABORT_ON_LLM_OUTAGE = os.environ.get('REPORT_ABORT_ON_LLM_OUTAGE', 'true').strip().lower() == 'true'
    REPORT_SECTION_RETRY_MAX = int(os.environ.get('REPORT_SECTION_RETRY_MAX', '2') or '2')  # RQ-1 1→2；0=旧的无重试
    REPORT_SECTION_RETRY_BACKOFF_S = float(os.environ.get('REPORT_SECTION_RETRY_BACKOFF_S', '8.0') or '8.0')
    REPORT_CRITIQUE_BEFORE_PROSE = os.environ.get('REPORT_CRITIQUE_BEFORE_PROSE', 'true').strip().lower() == 'true'
    # INFRA-2：红队自校准每份报告至多执行一次（默认开）。self_critique_forecast 调用评审 LLM 后
    # 给预测打 critique_attempted 标记；叙事前评审失败/被回退（未 critiqued）时，成稿后的第二次评审
    # 不再发 LLM 调用，只记 quality.critique_pre_prose='reverted_or_failed'——此前第二次评审会在
    # 正文写完后再挪概率（正文捍卫的数字与 forecast.json 矛盾），并白付一次评审成本。默认开是安全
    # 的：评审成功的路径不变（本就跳过二次评审），标记在 LLM 调用之后才写、且不进评审/验尸提示词。
    # false 恢复旧的「失败后成稿再评一次」且不写标记。
    REPORT_CRITIQUE_SINGLE_PASS = os.environ.get('REPORT_CRITIQUE_SINGLE_PASS', 'true').strip().lower() == 'true'
    FORECAST_BINARY_CONTRARIAN = os.environ.get('FORECAST_BINARY_CONTRARIAN', 'true').strip().lower() == 'true'
    # REPORT-11 二元预测对称护栏（默认关）：逆向框架 / 低概率重述规则与基础 RULES 只把模型推离 0.5，
    # 没有一句约束反方向的失败。开启后每条二元抽取提示词都追加 SYMMETRY GUARD（紧跟当轮逆向 / 低概率
    # 规则；FORECAST_BINARY_CONTRARIAN 关时紧跟基础 RULES）：证据不支持所给概率就丢掉候选，绝不为凑
    # 目标区间挪数字，不为显得果断制造极端。这是会移动概率的提示词政策，须经 WP14 前瞻、结果盲的
    # 晋升门才可默认开启（ADR-0002 I-21：不得凭 golden / 形状指标晋升）。开启时记入
    # forecast.quality.forecast_policy（与形状遥测旗标无关）与准入钉 safety_policy_v1。默认关是安全的：
    # 二元抽取提示词逐字节不变。
    FORECAST_BINARY_SYMMETRIC_GUARD = os.environ.get('FORECAST_BINARY_SYMMETRIC_GUARD', 'false').strip().lower() == 'true'
    # EVAL-14（P14）：数值阈值型二元的结构化 target——二元抽取提示词追加 STRUCTURED TARGET 规则，
    # 模型给出的 target 经 binary_targets.validate_binary_target 校验后存 row['target']（不合格存
    # target_rejected 及原因），报告在定稿概率上做同目标阈值阶梯单调性审计
    # （binary_quality.threshold_ladder，只告警，不影响发布门与终审政策版本），并记入
    # quality.forecast_policy.binary_structured_target。默认关：二元抽取提示词、max_tokens 与二元行
    # 逐字节不变，forecast.json 不多任何键（开启会改变提示词，从而可能改变起草）。不随此旗标的改动
    # 只有判定标准解析器 _extract_comparable_numeric_range 的两处修复：(1) RESEARCH-15(c) 要求的
    # 否定修复（否定比较词如 "does not exceed"/"no more than"/不超过 按正确方向读；指标吞入否定词
    # 或反向判词——"Fails if"、"Resolves negatively/false if"、"Falsified if"——的子句不解析）；
    # (2) 解析前把水平空白串（制表符、全角空格 U+3000 等）折叠为一个空格以保持线性时间，原先被
    # 制表符或全角空格截断的子句现在可读。情景分区审计据此读到真实指标，可能新报或不再报
    # overlapping_numeric_ranges——这是正确行为，不是旗标泄漏。
    FORECAST_BINARY_STRUCTURED_TARGET = os.environ.get('FORECAST_BINARY_STRUCTURED_TARGET', 'false').strip().lower() == 'true'
    # REPORT-11 概率形状遥测（默认开）：确定性计算情景形状（峰值 max_probability、归一化熵、距均匀分布的
    # TV 距离，叙事前 / 成稿后批判成功时另算批判前后差值）与二元预测形状（0.40-0.60 中间带 / 0.45-0.55
    # 近半 / ≤0.05 或 ≥0.95 极端占比、十分位直方图、市场重述与分区对账向 / 远离 0.5 的移动计数），记入
    # forecast.quality.probability_shape（批判成功时另记 quality.pre_critique_scenarios），发布提交时
    # 作为账本行 objective_signals。纯观测：任何门都不读它，零 LLM 调用，不改概率与提示词，故默认开是
    # 安全的。false 时 forecast.json 与账本提交行逐字节回到旧形态。
    FORECAST_PROBABILITY_SHAPE = os.environ.get('FORECAST_PROBABILITY_SHAPE', 'true').strip().lower() == 'true'
    FORECAST_SIM_SENSITIVITY = os.environ.get('FORECAST_SIM_SENSITIVITY', 'true').strip().lower() == 'true'
    FORECAST_BINARY_THEMES = os.environ.get('FORECAST_BINARY_THEMES', '').strip()  # 空=由 brief/主题自适应
    FORECAST_HORIZON_CHECK = os.environ.get('FORECAST_HORIZON_CHECK', 'true').strip().lower() == 'true'  # RQ-6 需求↔二元预测结算年份一致性标记
    # ITEM 12：多模型二元预测集成。逗号分隔的（副）提供方名清单（如 'openai,deepseek,glm'）；
    # 空=关闭（默认，逐字节复现旧单模型行为）。开启时对每个所列提供方各跑一次同提示词二元抽取，
    # 按 id/陈述匹配同一条预测，用与种子集成同一套 extremizing log-odds（ENSEMBLE_EXTREMIZE_A）
    # 把各模型概率池化为发布概率，记 binary['ensemble']={models,probs,pooled,spread}。任一副提供方
    # 构造/抽取失败仅跳过并记 flag，绝不阻断主抽取。
    FORECAST_ENSEMBLE_MODELS = os.environ.get('FORECAST_ENSEMBLE_MODELS', '').strip()
    # 跨模型概率样本 stdev 超此阈值 → 该预测记入 low-agreement（binary_quality.ensemble），
    # 二元预测表渲染以 ±spread 显示分歧。默认 0.15。
    FORECAST_ENSEMBLE_SPREAD_THRESHOLD = float(os.environ.get('FORECAST_ENSEMBLE_SPREAD_THRESHOLD', '0.15') or '0.15')
    # EVAL-11（P15）骨架跨底座敏感性影子检查：主报告骨架定稿后，以骨架原提示词 + 已定情景名的 follow
    # 提示各抽一次——同底座对照（复制主客户端，钉住骨架所用模型、绕过缓存）与副底座（下列清单中第一个
    # 可构造且 (provider, model) 不同于主底座者）——比较跨底座（对照 vs 副）与同底座（批判前骨架 vs 对照）
    # 的情景分布差异，记入 forecast.quality.backbone_sensitivity。纯影子诊断：不改概率、区间、渲染与
    # 发布门。准入时钉进 safety_policy_v1.backbone_check（resume 不重新捕获；缺失即关闭）；种子报告 /
    # model_comparison / API 重生成从不运行。默认关是安全的：不发任何额外 LLM 调用，forecast.json 与
    # 全部提示词逐字节不变；开启时每次运行多 2 次骨架调用。对照与副底座调用与主报告共用该提供方的
    # 进程级 422/429 熔断状态（失败计入连败、成功清零、熔断改变后续调用的服务方），故主提供方熔断
    # 已有连败或处于冷却时不发调用（记 unchecked:primary_throttled），同样状态的副候选被跳过。
    BACKBONE_CHECK_ENABLED = os.environ.get('BACKBONE_CHECK_ENABLED', 'false').strip().lower() == 'true'
    # 副底座候选：逗号分隔的提供方名（构造方式同 FORECAST_ENSEMBLE_MODELS）。空 = 无副底座
    # （开启时记 unchecked:no_distinct_secondary，不发调用）。
    BACKBONE_CHECK_PROVIDERS = os.environ.get('BACKBONE_CHECK_PROVIDERS', '').strip()
    # 越界阈值：任一情景 |Δp| ≥ 此值或领先情景不一致即算越界（取值须在 (0, 1]，否则记 unchecked）。
    BACKBONE_CHECK_MAX_ABS_DELTA = float(os.environ.get('BACKBONE_CHECK_MAX_ABS_DELTA', '0.15') or '0.15')
    # TIME-5（P13）已发布二元阈值的数值一致性影子检查：off | shadow（默认 shadow）。shadow 时二元抽取提示词
    # 多索取一个可选 latest_actual 字段（同指标在 dossier 里的最新实际值；每条约 50 个输出 token，不加
    # LLM 调用，二元抽取的 max_tokens 按条数相应放宽），utils.numeric_guards 做确定性检查（scale_mismatch /
    # status_quo_contradiction / inverted_interval），只盖 binary['numeric_guard'] 章并汇总进
    # forecast.quality.numeric_guards。检查本身不改概率、正文、发布门、终审与
    # REPORT_FINAL_AUDIT_POLICY_VERSION；但追加的提示词规则会改变模型起草，二元与概率可能与 off 不同——
    # 需要与改动前完全一致的生成时设 off。准入时钉进 safety_policy_v1.numeric_guard_mode（服务重载不改变
    # 已准入运行，并进入 EVAL-18 配置指纹）；API 重生成读当前值。非法值按 shadow 运行并告警。enforce 刻意
    # 不实现（须前瞻证据，ADR 0002 I-21）。off → 提示词、forecast.json 与正文逐字节回到旧行为。
    NUMERIC_GUARD_MODE = os.environ.get('NUMERIC_GUARD_MODE', 'shadow').strip().lower()
    # 阈值与最新实际值中点之比 ≥ 此值（或 ≤ 其倒数）且单位类 / 币种相同 → scale_mismatch（误解析级）。
    # 取值须 > 1，否则回落 300。
    NUMERIC_GUARD_SCALE_RATIO = float(os.environ.get('NUMERIC_GUARD_SCALE_RATIO', '300') or '300')
    # 现状判定边际 m：最新实际值越过阈值 K 至少 m·|K| 才算「已满足 / 已违背」（概率落在 0.5 另一侧即
    # status_quo_contradiction）。取值须在 [0, 1)，否则回落 0.25。
    NUMERIC_GUARD_STATUS_QUO_MARGIN = float(os.environ.get('NUMERIC_GUARD_STATUS_QUO_MARGIN', '0.25') or '0.25')
    REPORT_QUOTE_AUDIT_V2 = os.environ.get('REPORT_QUOTE_AUDIT_V2', 'true').strip().lower() == 'true'
    REPORT_COMPACT_RETRIEVAL_QUERY = os.environ.get('REPORT_COMPACT_RETRIEVAL_QUERY', 'true').strip().lower() == 'true'
    # RQ-2 报告修复门：质量门失败时按维度单次定向修复（引用回填 / 引文接地 / 占位符解析），
    # 然后重跑审计一次并把 before/after 记进 forecast['quality']['repair']（合并，不覆盖）。默认开；
    # 任一步失败仅告警（degrade-safe），绝不影响主报告。
    REPORT_REPAIR_PASSES = os.environ.get('REPORT_REPAIR_PASSES', 'true').strip().lower() == 'true'
    # RQ-2 成稿语言纯度扫描：检测非 CJK 目标报告中的 CJK 片段（反之亦然），一次批量 LLM 调用内联翻译，
    # 引用型原文以括注/脚注保留。默认开；任何错误 degrade-safe 跳过（保留原文）。
    REPORT_LANGUAGE_PURITY = os.environ.get('REPORT_LANGUAGE_PURITY', 'true').strip().lower() == 'true'
    # RQ-5 每章反思：草稿通过基本有效性后做一次廉价批判（骨架概率一致性 / 硬数字接地 / 篇幅下限 /
    # 不复述前序章节），返回 PASS 或单条修订指令；至多一次修订抽取。轮数由 MAX_REFLECTION_ROUNDS 上限。
    REPORT_SECTION_REFLECTION = os.environ.get('REPORT_SECTION_REFLECTION', 'true').strip().lower() == 'true'
    # REPORT-2（P08 stage 1a）确定性叙事同步：红队批判（含谦逊钳制/兜底情景/舍入闭合）、事前验尸
    # 转移与 K>1 自洽池化都会移动情景概率，但 headline / confidence_rationale / 情景 summary 仍写着
    # 移动前的数字（已发布的 report_ffe1ea6bf50d 标题「基准情景（40%）」对应 A=0.35），而该标题被钉进
    # 每章提示词、大纲摘要、摘要标题与看板。开启后每个移动概率的步骤按「移动前→移动后」唯一值映射
    # 逐数字改写（歧义值/无法按名配对的值/区间/数量/合计语境一律跳过并计数；无法归属的值记入
    # quality.narrative_sync_blocked，后续步骤在同一字段不再映射），原文存 *_detail，逐处编辑记入
    # forecast.quality.narrative_sync。默认开是安全的：零 token、纯确定性、只改叙事文本，从不改概率；
    # 设 false 逐字节复现旧 forecast.json。
    REPORT_NARRATIVE_SYNC = os.environ.get('REPORT_NARRATIVE_SYNC', 'true').strip().lower() == 'true'
    # REPORT-3（P08 stage 1b）别名感知概率槽审计（services/logic_number.py，零 token）：S11 只锚定完整
    # 情景名的首次出现，report_ffe1ea6bf50d 摘要 blockquote 的「基准情景（40%）」（A=0.35）因此过了终审。
    # 严格槽位（别名（N%）/ 别名：N% 概率 / N% 的概率 别名 …）+ REPORT-2 的区间/数量/合计守卫找出与骨架
    # 不符的数字。off = 不审计；observe（默认）= 只记 forecast.quality.logic_number 与 final_audit.json 的
    # logic_number，不进 hard_issues / 发布门；numeric = 把别名槽不符（可修复与未解决的全部——守卫只决定
    # 能否改写；检测异常记为不符，失败即关闭）并入 S11（_audit_numeric_consistency 与
    # report_lint.check_scenario_probabilities），经既有硬路径阻止发布。numeric 改变一条硬发布规则，
    # 因此必须同时提升 REPORT_FINAL_AUDIT_POLICY_VERSION 并提供重放工具——属 owner 决策，本 WP 不提升。
    # 未知值按 observe 处理并告警。确定性修复（大纲摘要同步 + 稳定器之前的正文槽位替换）另由
    # REPORT_LOGIC_NUMBER_REPAIR 控制。默认 observe 是安全的：只读观测，任何硬规则与发布结果不变。
    REPORT_LOGIC_NUMBER_GATE = os.environ.get('REPORT_LOGIC_NUMBER_GATE', 'observe').strip().lower()
    # REPORT-3 零 token 槽位修复（大纲摘要同步 + 稳定器之前的正文别名概率槽改成骨架值），还需
    # REPORT_NARRATIVE_SYNC 开。默认关（编排决策，评审第 4 轮后）：每轮评审都找到新的语境——修复把
    # 并非该情景概率的百分数（增长率、份额、另一事件的概率，如「有55%的概率实现基准扩张路径下的…」）
    # 改成情景值，确定性的正文改写绝不能默认编造数字。只读审计（REPORT_LOGIC_NUMBER_GATE=observe）
    # 照常记录 fixable / unresolved，作为开启前的证据；关 = 成稿、大纲与 forecast.json 不被改写。
    REPORT_LOGIC_NUMBER_REPAIR = os.environ.get('REPORT_LOGIC_NUMBER_REPAIR', 'false').strip().lower() == 'true'
    # REPORT-4 报告阶段提示词的类型化缺失标记（utils/absence.py）：章节质检无骨架时去掉概率一致性
    # 规则、缺失的信号包/市场表写成「本次未启用 / 检索为空 / 不可用」标记而非「（无）」、并行撰写的
    # 大纲意图不再冒充前序章节摘要；骨架提示词首句只列实际注入的输入并要求无研究基率时写明基率出处；
    # 二元预测 source 行在模拟信号未注入时不再邀请具名模拟信号；章节前缀追加一行市场缺失说明；
    # forecast.quality.prompt_slot_states 记录市场槽状态。默认开是安全的：只改提示词措辞（诚实性修复，
    # 概率锚点仍是数值），标记文本由 report_lint 的泄漏哨兵兜底删除；设 false 逐字节复现旧提示词。
    REPORT_ABSENCE_MARKERS = os.environ.get('REPORT_ABSENCE_MARKERS', 'true').strip().lower() == 'true'

    # —— WAVE9-FOCUS：报告焦点与编辑纪律（模拟=内部方法，报告主语=现实世界）——
    # 确定性编辑 lint（report_lint.lint_report）：修复 passes 之后、双语翻译之前清理引用残留 /
    # 边转储 / 旧模拟标签 / 孤悬归因行 / 引用记号变体 / 重复整句；lint 报告记入 forecast.json
    # quality['lint']。默认开；失败仅告警（degrade-safe）。
    REPORT_EDITORIAL_LINT = os.environ.get('REPORT_EDITORIAL_LINT', 'true').strip().lower() == 'true'
    # RESEARCH-5：已报告 vs 预期的归因观测（report_lint.check_projection_attribution，纯确定性、只记数/
    # 采样、绝不改写成稿）。研究 quantitative 行按 quant_typing.quant_class 分型（未分型行忽略），正文
    # 句子同时含该行的关键数字、单位与指标锚词时，按「实现」/「预期」措辞记 projection_as_fact 等计数。
    # 终审副本（final_audit.json 与 forecast.quality.final_audit 的 projection_attribution）总是写入；
    # forecast.quality.projection_attribution 由编辑 lint 通道写入，故另需 REPORT_EDITORIAL_LINT 开启。
    # 默认开是安全的：只读观测，不进 hard_issues、不改发布状态；设 false 各处字段都不写（逐字节复现旧产物）。
    REPORT_PROJECTION_LINT = os.environ.get('REPORT_PROJECTION_LINT', 'true').strip().lower() == 'true'
    # 模拟机制泄漏修复（_repair_simulation_leakage，注册进 REPORT_REPAIR_PASSES 修复链）：
    # Tier-1 确定性改写（标签/边/工具记号/平台行为引文/泄漏标题）→ Tier-2 每个泄漏段落一次
    # 有界 LLM 重写（数字 token 逐字节校验，失败弃用）→ 重扫后删除仍泄漏句子。默认开。
    REPORT_SIMLEAK_REPAIR = os.environ.get('REPORT_SIMLEAK_REPAIR', 'true').strip().lower() == 'true'
    # Tier-2 泄漏段落 LLM 重写的段数上限（超出预算的段落直接句子级删除）。默认 12。
    REPORT_SIMLEAK_MAX_LLM_PARAGRAPHS = int(os.environ.get('REPORT_SIMLEAK_MAX_LLM_PARAGRAPHS', '12') or '12')
    # 大纲标题 lint：含方法学词汇（模拟/智能体/Agent/Simulation/Behavior/行为轨迹）的章节标题
    # 确定性改名（改名而非删除，保住 6-14 节章节数契约）。默认开。
    REPORT_OUTLINE_TITLE_LINT = os.environ.get('REPORT_OUTLINE_TITLE_LINT', 'true').strip().lower() == 'true'
    # 信号包量化结果的定性转写：simulation_outcomes 的动作计数转写为「议程设置力分层」再注入
    # 章节提示词（防 'TSMC 以 48 次动作居首' 型机制泄漏）；关闭则注入原始文本（旧行为）。默认开。
    REPORT_SIGNAL_PACK_QUALITATIVE = os.environ.get('REPORT_SIGNAL_PACK_QUALITATIVE', 'true').strip().lower() == 'true'
    # 章节语言验收：成稿章节的外语字符占比超阈值时做一次整章重写重申输出语言（S3/S9 整章
    # 中文进英文报告的故障）。默认开；阈值对 CJK 目标自动放宽到 >=0.6（合法拉丁 token 多）。
    REPORT_SECTION_LANG_ENFORCE = os.environ.get('REPORT_SECTION_LANG_ENFORCE', 'true').strip().lower() == 'true'
    REPORT_SECTION_LANG_MAX_FOREIGN_RATIO = float(os.environ.get('REPORT_SECTION_LANG_MAX_FOREIGN_RATIO', '0.25') or '0.25')
    # 语言纯度：单个 H2 块污染片段数超此阈值 → 整章重译（子串内联补丁在重污染章节产出
    # 'SK SK Hynix' 型混合垃圾）；<=0 关闭整章重译（恒走内联路径）。默认 8。
    REPORT_PURITY_RETRANSLATE_SEGMENTS = int(os.environ.get('REPORT_PURITY_RETRANSLATE_SEGMENTS', '8') or '8')
    # COST-1(b)：语言纯度逐段升级上限。批量 chat_json 未解决/被拒的片段才逐段走 strong-tier
    # chat 升级，每段一次调用且各自携带完整重试梯；无上限时提供方故障会把至多
    # REPORT_PURITY_MAX_SEGMENTS(180) 个片段全部串行升级。每份报告至多升级此数量，
    # 其余片段保留原文（末端只读纯度审计仍兜底）；<=0 关闭逐段升级。默认 12。
    REPORT_PURITY_ESCALATION_MAX = int(os.environ.get('REPORT_PURITY_ESCALATION_MAX', '12') or '12')
    # 反思修订反收缩护栏：修订稿长度下限 = max(原稿 × 此比例, 章节字符下限)；短于下限且确实
    # 缩水的修订一律拒绝（14824→1518 的「章节销毁」故障）。默认 0.6。
    REPORT_REVISION_MIN_RATIO = float(os.environ.get('REPORT_REVISION_MIN_RATIO', '0.6') or '0.6')
    # 反思护栏的章节有效下限比例：章节字符下限 = max(MIN_VALID_SECTION_CHARS(800),
    # 章节目标下限 × 此比例)。默认 0.4（3000 目标 → 1200）。
    REPORT_SECTION_MIN_VALID_RATIO = float(os.environ.get('REPORT_SECTION_MIN_VALID_RATIO', '0.4') or '0.4')
    # 截断续写：章节以句中截断收尾（'(依据' / 裸字母数字 / 冒号）时做一次续写调用补全。默认开。
    REPORT_SECTION_TRUNCATION_CONTINUE = os.environ.get('REPORT_SECTION_TRUNCATION_CONTINUE', 'true').strip().lower() == 'true'

    # —— BILINGUAL：双语报告（自动生成另一语种版本）——
    # 报告生成末尾（finalize/可视化/纯度之后）自动生成成稿的「另一语种」版本：英文报告 → 简体中文
    # 版，中文报告 → analyst-grade 英文版。按 H2（'## '）章节边界切块、并发逐章翻译（严格保留
    # markdown 结构 / 表格列数 / 代码 & mermaid 围栏原样 / 图片 URL / 引用标记 / 数字概率逐字节），
    # 落 reports/{id}/full_report.{en|zh}.md 并把 translations 条目写入 meta。完全 degrade-safe：
    # 任何失败/非中英文脚本 → 跳过，主交付物（full_report.md）绝不受影响。默认开；设 false 关闭。
    REPORT_BILINGUAL = os.environ.get('REPORT_BILINGUAL', 'true').strip().lower() == 'true'
    # 逐章节翻译的并发度（ThreadPoolExecutor 线程数）；下限 1（串行）。默认 4。
    REPORT_TRANSLATION_CONCURRENCY = max(1, int(os.environ.get('REPORT_TRANSLATION_CONCURRENCY', '4') or '4'))
    # Rounds of report_agent._repair_variant_contamination (re-translate the source-language
    # lines a translated variant kept; clamped to 1-5 there).  INFRA-14 declared it: the
    # report agent read it with a getattr default of 3, so an .env value never reached it.
    # The default 3 is that getattr default, so an unset knob changes nothing.
    REPORT_TRANSLATION_CONTAMINATION_RETRIES = int(
        os.environ.get('REPORT_TRANSLATION_CONTAMINATION_RETRIES', '3') or '3')
    # Lines a published translation may keep in the source language after the full
    # repair ladder (min(this, one per 200 body lines, at least 1)); they publish with a
    # recorded warning instead of withholding the whole translation.  0 = strict.
    REPORT_TRANSLATION_RESIDUAL_LINES = max(0, int(os.environ.get('REPORT_TRANSLATION_RESIDUAL_LINES', '3') or '3'))
    # Per-request timeout for translation model calls (the client default is 600 s, which
    # lets one dead HTTP/2 stream stall a translation for 10 minutes before the retry).
    REPORT_TRANSLATION_CALL_TIMEOUT_S = max(0.0, float(os.environ.get('REPORT_TRANSLATION_CALL_TIMEOUT_S', '240') or '240'))
    # Still-contaminated lines that get one last whole-line retranslation (2 prompts each).
    REPORT_TRANSLATION_RESIDUAL_LINE_RETRIES = max(0, int(os.environ.get('REPORT_TRANSLATION_RESIDUAL_LINE_RETRIES', '12') or '12'))

    # —— PM-2：确定性逐预测市场锚定（forecast_extractor 经 getattr 读取）——
    # 抽取二元预测后跑一次批处理 LLM 匹配（陈述表 × 相关性门控市场表），确定性回填
    # rich market_anchor（隐含概率取我们的快照、divergence 本地计算）。默认开；关闭则回到
    # 「仅模型自愿转录 market_anchor」的 opt-in 行为（取证 0/13 命中，degrade-safe）。
    FORECAST_MARKET_ANCHORING = os.environ.get('FORECAST_MARKET_ANCHORING', 'true').strip().lower() == 'true'
    # 锚定采纳的最小 resolution_equivalence 严格度：exact|near|loose（默认 near，即采纳
    # exact/near、丢弃 loose 的宽泛主题匹配，避免把不同结算口径的市场硬贴成锚点）。
    FORECAST_MARKET_ANCHOR_MIN_EQUIVALENCE = os.environ.get('FORECAST_MARKET_ANCHOR_MIN_EQUIVALENCE', 'near').strip().lower()
    # EVAL-6（市场价时溯源）：重报价拿到现价的市场行记 quoted_at（取价时刻，UTC ISO；之后
    # 再次重报价失败时保留，因为留下的价仍是那次报价），研究 handoff 快照行 / 报告期现抓行记
    # snapshot_as_of（快照 as_of / 现抓时刻，只是取价时刻的上界：研究快照 as_of 在落盘时才取，
    # 其中智能体工具检索到的行可能更早就已报价）；_build_market_anchor 据此给锚点写 price_time +
    # price_time_basis（requote|snapshot，时刻未知则两键都不写）。basis=requote 时锚点的
    # price_at_research 实为报告期重报价（历史字段名）。纯溯源字段，不动任何概率、锚定决策或
    # 发布闸门，因此默认开；false → 市场行与 forecast.json 锚点逐字节复现旧形状。
    MARKET_ANCHOR_PRICE_TIME = os.environ.get('MARKET_ANCHOR_PRICE_TIME', 'true').strip().lower() == 'true'
    # 10pp 规则：锚定后 |model_p − market_p|>0.10 且理由未提及市场的预测，做一次有界重述，
    # 须在理由中引用市场或有依据地保留分歧（绝不静默移动概率）。默认开；关闭=不重述。
    FORECAST_MARKET_DIVERGENCE_REVISION = os.environ.get('FORECAST_MARKET_DIVERGENCE_REVISION', 'true').strip().lower() == 'true'
    # LOOP-017 P0（影响边界）：分歧重述的**资格**门槛——只有 match_confidence >= 此值的锚点
    # 才被允许把概率移向市场（缺失/None 一律不合格）。低置信匹配仍可作为校准展示锚点，
    # 但绝不获得移动发布概率的资格（取证事故：0.4x 置信的错配把概率拉向无关市场，随后
    # 对账弹出锚点、修订概率却永久保留）。默认 0.6——高于锚点完整性下限
    # （_market_anchor_complete 的 0.5）：影响概率的门槛必须严于仅作展示的门槛。
    FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE = float(os.environ.get('FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE', '0.6') or '0.6')
    # REPORT-12 (deterministic market blend): the 10pp divergence restatement asks the model
    # only for a bounded market_weight w (plus a market-citing rationale, all or none) and code
    # computes the revised probability (1-w)*p + w*m from DRF's own snapshot price m, stamps the
    # formula in market_influence.blend and shows it in the Market Cross-Check.  Default off: it
    # changes how published probabilities move, so it is promoted only through an outcome-blind
    # (WP14) decision; off -> the legacy free-probability restatement, byte-identical.
    FORECAST_MARKET_BLEND_ARITHMETIC = os.environ.get('FORECAST_MARKET_BLEND_ARITHMETIC', 'false').strip().lower() == 'true'
    # REPORT-12: the largest market_weight accepted (a larger one rejects the whole revision).
    # Default 0.8: markets are calibration anchors, not truth, so a blend never fully adopts the
    # market price.  Read only while FORECAST_MARKET_BLEND_ARITHMETIC is on; clamped to [0, 1]
    # so a blend always stays on the segment between the forecast and the market price, then
    # floored to two decimals (the 0.01 grid the model's weight is rounded to), so the cap the
    # prompt states is exactly the cap that is enforced.
    FORECAST_MARKET_BLEND_WEIGHT_MAX = float(os.environ.get('FORECAST_MARKET_BLEND_WEIGHT_MAX', '0.8') or '0.8')
    # REPORT-10（信息墙）：注入实时市场包时，二元抽取的 dossier 视图删掉研究桥追加的机器市场表
    # （"## Prediction Market Signals" H2 节，研究期价格、可能过时），市场价只经实时市场包一个
    # 入口进入 _draw，且不再占用 head+tail 的尾部预算。默认关：删除会改变二元提示词进而可能
    # 改变概率，先对比再晋升；关 → 提示词逐字节不变。
    FORECAST_DRAW_DOSSIER_STRIP_MARKET_TABLE = os.environ.get('FORECAST_DRAW_DOSSIER_STRIP_MARKET_TABLE', 'false').strip().lower() == 'true'
    # REPORT-10（诚实标注）：Market Cross-Check 说明句追加披露——预测起草时已参考市场价格，Δ 是
    # 锚定之后的差值，而非独立于市场的估计。默认开（纯披露文字、不动任何数字）；false → 说明句
    # 逐字节恢复旧文案。
    REPORT_MARKET_XCHECK_DISCLOSURE = os.environ.get('REPORT_MARKET_XCHECK_DISCLOSURE', 'true').strip().lower() == 'true'

    # —— RQ-2：成稿后抽取切片（head+tail，结论在文末）+ 抽取 max_tokens（forecast_extractor 经 getattr 读取）——
    # 情景/二元抽取此前只取正文开头 [:budget]，把文末的收敛判断切掉；改为「前 head_ratio +
    # 后 (1-head_ratio)」两段拼接。默认值即新行为；调小 head_ratio 偏向结论、调大偏向导言。
    FORECAST_EXTRACT_BUDGET = int(os.environ.get('FORECAST_EXTRACT_BUDGET', '40000') or '40000')
    FORECAST_BINARY_EXTRACT_BUDGET = int(os.environ.get('FORECAST_BINARY_EXTRACT_BUDGET', '48000') or '48000')
    FORECAST_EXTRACT_HEAD_RATIO = float(os.environ.get('FORECAST_EXTRACT_HEAD_RATIO', '0.6') or '0.6')
    # 情景抽取 max_tokens 2048→4096（5 情景 × anchor/rationale/criteria 常被 2048 截断成断裂 JSON）。
    FORECAST_EXTRACT_MAX_TOKENS = int(os.environ.get('FORECAST_EXTRACT_MAX_TOKENS', '4096') or '4096')

    # —— RESEARCH-13（P09）：概率提示词的确定性证据包（forecast_context_packer，零 LLM 调用）——
    # 二元抽取：以按 H2 节分类的 dossier 摘录（可判定/二元预测节 > 执行摘要 > 情景 > 正文，
    # References / Visual Annex / How to Read 永不入包，Sources/方法论只吃剩余预算）加一条按 as_of
    # 过滤、由新到旧的「近期进展」时间线通道，取代 48k head+tail 切片 + situation_brief[:2000]；
    # 包文与摘要落 reports/<id>/context_pack_binary.json，摘要（无正文）记 forecast.context_pack。
    # 默认关：改变概率权威看到的证据可能移动概率，按回放指标 + 人工抽查晋升；关 → 提示词逐字节不变。
    FORECAST_CONTEXT_PACK_BINARY = os.environ.get('FORECAST_CONTEXT_PACK_BINARY', 'false').strip().lower() == 'true'
    # 骨架：以「研究证据包（按时点标注）」（执行摘要/情景节、局势简报、as_of 切分的时间线、关键指标，
    # 按份额填充）取代 [态势简报] 的 2000 字切片；EVAL-11 影子检查重建的提示词同样带包。默认关，理由同上。
    FORECAST_CONTEXT_PACK_SPINE = os.environ.get('FORECAST_CONTEXT_PACK_SPINE', 'false').strip().lower() == 'true'
    # 二元包 dossier 摘录的字符预算（与旧切片同为 48000）。时间线通道不计入：封顶约 7.6k 字（12 条近期进展
    # + 5 条已排期 + 两行标题）；包同时去掉 2k 的 [Situation brief]，净增约 5.6k（运行无简报时即 7.6k）。
    FORECAST_CONTEXT_PACK_BINARY_BUDGET = int(os.environ.get('FORECAST_CONTEXT_PACK_BINARY_BUDGET', '48000') or '48000')
    # 骨架证据包的总字符预算。
    FORECAST_CONTEXT_PACK_SPINE_BUDGET = int(os.environ.get('FORECAST_CONTEXT_PACK_SPINE_BUDGET', '14000') or '14000')
    # 「已排期」（日期晚于 as_of 的时间线条目）只在 as_of 距今不超过此天数的实时运行中展示；回溯运行
    # 的此类条目可能是事后写成的，一律扣下并计数（post_as_of_rows_withheld）；回测运行（TIME-6 回测钉）不论
    # 截止日多近一律扣下。只影响上面两个包与下面的章节时间线切分，三者默认都关。
    FORECAST_SCHEDULED_LIVE_WINDOW_DAYS = int(os.environ.get('FORECAST_SCHEDULED_LIVE_WINDOW_DAYS', '30') or '30')
    # 章节提示词的「关键事件时间线」块按 as_of 切分：已发生（日期在 as_of 当日或之前，最近 15 条）与
    # 单列的「已排期」子列表（同一实时运行门）；无日期/跨越 as_of 的条目只计数。默认关：关 → 块逐字节不变。
    REPORT_CHRONOLOGY_ASOF_SPLIT = os.environ.get('REPORT_CHRONOLOGY_ASOF_SPLIT', 'false').strip().lower() == 'true'
    # RESEARCH-6: cross-source forecast-dispersion diagnostics (off | shadow).  shadow: the
    # research quantitative rows typed projected are grouped by metric family (else the
    # forecaster-free metric), region, target year and unit; a group with >= 2 forecasters
    # records min/max/median, the max/min spread ratio, vintages, staleness and
    # same-forecaster revisions, and rows dated after the research as-of (actors.as_of_date,
    # else the hindcast pin's) are excluded (leakage guard; leakage_guard=false in the
    # digest when neither is a full day).  The payload goes to
    # reports/<id>/consensus_evidence.json and its digest to forecast.quality.consensus.
    # Deterministic, zero model calls, and no prompt, probability or publish-gate input
    # changes.  Default off (no key, no file: forecast.json byte-identical); blank or any
    # other value is off.
    REPORT_CONSENSUS_DIAGNOSTICS = os.environ.get('REPORT_CONSENSUS_DIAGNOSTICS', 'off').strip().lower()

    # LLM提供方（默认使用 Claude Code CLI 订阅）
    # claude-cli: 通过本机 `claude` CLI 调用（使用 Claude Code 订阅，无需 API Key）
    # codex-cli:  通过本机 `codex` CLI 调用（使用 Codex 订阅，无需 API Key）
    # openai:     回退到 OpenAI 兼容 API（需要 LLM_API_KEY）
    # kimi:       Kimi-for-coding（api.kimi.com/coding，OpenAI 兼容 + coding-agent UA 网关）
    # minimax:    MiniMax 代码计划（api.minimaxi.com 国内版，OpenAI 兼容，MiniMax-M3 推理模型）
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'claude-cli').strip().lower()

    # Kimi-for-coding 默认连接参数（provider=kimi 且未显式覆盖时启用）
    _KIMI_DEFAULT_BASE_URL = 'https://api.kimi.com/coding/v1'
    # K2.7 Code：网关同时接受 'kimi-k2.7' 与历史别名 'kimi-for-coding'（/models 仅列后者，
    # 但补全请求 echo 回 'kimi-k2.7'）。注意该模型对 temperature 有硬约束（开推理=1/关=0.6），
    # 由 LLMClient._coerce_temperature 统一兜底。
    _KIMI_DEFAULT_MODEL = 'kimi-k2.7'
    _is_kimi = LLM_PROVIDER == 'kimi'

    # MiniMax 代码计划默认连接参数（provider=minimax 且未显式覆盖时启用）
    # 国内版 OpenAI 兼容端点；模型名严格区分大小写 'MiniMax-M3'（512K 上下文）。
    _MINIMAX_DEFAULT_BASE_URL = 'https://api.minimaxi.com/v1'
    _MINIMAX_DEFAULT_MODEL = 'MiniMax-M3'
    _is_minimax = LLM_PROVIDER == 'minimax'

    # —— 新增 OpenAI 兼容提供方默认连接参数 ——
    # DeepSeek V4（api.deepseek.com，1M 上下文）。报告/模拟为高频调用，默认用更经济稳定的
    # deepseek-chat；深度研究阶段在 deer-flow/config.yaml 用旗舰 deepseek-v4-pro。
    _DEEPSEEK_DEFAULT_BASE_URL = 'https://api.deepseek.com/v1'
    _DEEPSEEK_DEFAULT_MODEL = 'deepseek-chat'
    _is_deepseek = LLM_PROVIDER == 'deepseek'
    # 通义千问 Qwen（DashScope OpenAI 兼容；国际站端点，CN 用户改 dashscope.aliyuncs.com）。
    _QWEN_DEFAULT_BASE_URL = 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'
    _QWEN_DEFAULT_MODEL = 'qwen-plus'
    _is_qwen = LLM_PROVIDER == 'qwen'
    # 智谱 GLM（Z.ai/BigModel OpenAI 兼容；国际站端点，CN 用户改 open.bigmodel.cn）。
    _GLM_DEFAULT_BASE_URL = 'https://api.z.ai/api/paas/v4'
    _GLM_DEFAULT_MODEL = 'glm-4.6'
    _is_glm = LLM_PROVIDER == 'glm'

    # LLM配置（provider=openai/kimi/minimax/deepseek/qwen/glm 时统一使用 OpenAI 格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL') or (
        _KIMI_DEFAULT_BASE_URL if _is_kimi
        else _MINIMAX_DEFAULT_BASE_URL if _is_minimax
        else _DEEPSEEK_DEFAULT_BASE_URL if _is_deepseek
        else _QWEN_DEFAULT_BASE_URL if _is_qwen
        else _GLM_DEFAULT_BASE_URL if _is_glm
        else 'https://api.openai.com/v1'
    )
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME') or (
        _KIMI_DEFAULT_MODEL if _is_kimi
        else _MINIMAX_DEFAULT_MODEL if _is_minimax
        else _DEEPSEEK_DEFAULT_MODEL if _is_deepseek
        else _QWEN_DEFAULT_MODEL if _is_qwen
        else _GLM_DEFAULT_MODEL if _is_glm
        else 'gpt-4o-mini'
    )

    # coding-agent 身份头：Kimi-for-coding 网关按 User-Agent 校验调用方，
    # 必须发送被识别的 coding-agent UA（如 claude-cli/...）否则返回 access_terminated_error。
    # 注意：MiniMax 不做 UA 校验，仅 kimi 需要注入此头。
    LLM_USER_AGENT = os.environ.get('LLM_USER_AGENT', 'claude-cli/1.0.0')

    # kimi-for-coding / MiniMax-M3 都是“推理模型”：默认会把大量 token 花在隐藏推理上，
    # 当 max_tokens 被推理耗尽时返回的 content 为空（finish_reason=length），导致 JSON 解析失败；
    # MiniMax 还会把思维链以 <think>…</think> 内联进 content。对模拟/报告这类多调用、要求稳定
    # 可解析输出的工作负载，默认关闭推理（thinking:disabled）——content 直出、更快更省。
    # 可设对应 *_DISABLE_THINKING=false 重新开启推理。
    LLM_KIMI_DISABLE_THINKING = os.environ.get('LLM_KIMI_DISABLE_THINKING', 'true').strip().lower() == 'true'
    LLM_MINIMAX_DISABLE_THINKING = os.environ.get('LLM_MINIMAX_DISABLE_THINKING', 'true').strip().lower() == 'true'
    # 新增推理提供方(deepseek/qwen/glm)的统一关闭推理开关（默认关闭推理，保证报告/模拟输出稳定可解析）
    LLM_DISABLE_THINKING = os.environ.get('LLM_DISABLE_THINKING', 'true').strip().lower() == 'true'

    # 各推理提供方"关闭推理"对应的 extra_body。GLM/DeepSeek/Kimi/MiniMax 用 thinking.type；
    # 通义千问 DashScope 用非标准的 enable_thinking 布尔。
    _DISABLE_THINKING_EXTRA_BODY = {
        'kimi': {"thinking": {"type": "disabled"}},
        'minimax': {"thinking": {"type": "disabled"}},
        'deepseek': {"thinking": {"type": "disabled"}},
        'glm': {"thinking": {"type": "disabled"}},
        'qwen': {"enable_thinking": False},
    }

    @classmethod
    def reasoning_extra_body(cls, provider=None):
        """OpenAI 兼容推理提供方关闭推理用的 extra_body；非推理提供方或开关关闭时返回 None。

        kimi/minimax 沿用各自历史开关；deepseek/qwen/glm 统一受 LLM_DISABLE_THINKING 控制。
        关闭推理可避免 reasoning 吃光 max_tokens 导致 content 为空、JSON 解析失败。
        """
        # An explicit provider matters for failover clients.  Reading only the global primary
        # provider made an ``openai`` fallback inherit MiniMax's non-standard
        # ``thinking.type=disabled`` payload, which can make an otherwise healthy proxy reject
        # the request.  Existing callers may omit the argument and retain the old behavior.
        p = (provider or cls.LLM_PROVIDER or '').strip().lower()
        if p == 'kimi' and not cls.LLM_KIMI_DISABLE_THINKING:
            return None
        if p == 'minimax' and not cls.LLM_MINIMAX_DISABLE_THINKING:
            return None
        if p in ('deepseek', 'qwen', 'glm') and not cls.LLM_DISABLE_THINKING:
            return None
        return cls._DISABLE_THINKING_EXTRA_BODY.get(p)

    # 向后兼容别名（旧调用点）：等价于 reasoning_extra_body。
    @classmethod
    def kimi_extra_body(cls):
        return cls.reasoning_extra_body()

    # —— 运行时模型提供方切换（供 /api/settings 使用）——
    # 每个提供方的展示与路由元数据：
    #   label          前端显示名
    #   needs_key      是否需要用户填写 API Key（CLI/订阅类为 False）
    #   deerflow_model 深度研究阶段在 deer-flow/config.yaml 选用的模型 stanza 名
    #   openai_compat  报告/模拟阶段是否走 OpenAI 兼容 HTTP 客户端（否则走本机 CLI）
    #   default_base / default_model  OpenAI 兼容提供方的默认连接参数
    #   key_env        把用户填的 Key 镜像到的提供方专属环境变量（供 deer-flow $VAR 解析）
    PROVIDER_META = {
        'claude-cli': {'label': 'Claude Code（CLI 订阅）', 'needs_key': False, 'deerflow_model': 'claude', 'openai_compat': False},
        'codex-cli':  {'label': 'Codex（ChatGPT 订阅）',   'needs_key': False, 'deerflow_model': 'codex',  'openai_compat': False},
        'openai':     {'label': 'OpenAI 兼容 API',          'needs_key': True,  'deerflow_model': 'claude', 'openai_compat': True,
                       'default_base': 'https://api.openai.com/v1', 'default_model': 'gpt-4o-mini'},
        'kimi':       {'label': 'Kimi-for-coding',          'needs_key': True,  'deerflow_model': 'kimi', 'openai_compat': True,
                       'default_base': _KIMI_DEFAULT_BASE_URL, 'default_model': _KIMI_DEFAULT_MODEL, 'key_env': 'KIMI_API_KEY'},
        # LLM-6: native_tools=False——MiniMax-M3 的 agentic 工具调用不可靠（0-tool-call 推理
        # 残段烧掉工具预算后才被 ReAct 兜底救回）；缺省键=True，其余 openai-compat 提供方不受影响。
        # 验证可靠后删除此键即可恢复；LLM_NATIVE_TOOLS_PROVIDERS 环境变量可整体覆盖。
        'minimax':    {'label': 'MiniMax 代码计划（国内版）', 'needs_key': True,  'deerflow_model': 'minimax', 'openai_compat': True,
                       'default_base': _MINIMAX_DEFAULT_BASE_URL, 'default_model': _MINIMAX_DEFAULT_MODEL, 'key_env': 'MINIMAX_API_KEY',
                       'native_tools': False},
        'deepseek':   {'label': 'DeepSeek V4',              'needs_key': True,  'deerflow_model': 'deepseek', 'openai_compat': True,
                       'default_base': _DEEPSEEK_DEFAULT_BASE_URL, 'default_model': _DEEPSEEK_DEFAULT_MODEL, 'key_env': 'DEEPSEEK_API_KEY'},
        'qwen':       {'label': '通义千问 Qwen3.7 Max',      'needs_key': True,  'deerflow_model': 'qwen', 'openai_compat': True,
                       'default_base': _QWEN_DEFAULT_BASE_URL, 'default_model': _QWEN_DEFAULT_MODEL, 'key_env': 'DASHSCOPE_API_KEY'},
        'glm':        {'label': '智谱 GLM-4.6',             'needs_key': True,  'deerflow_model': 'glm', 'openai_compat': True,
                       'default_base': _GLM_DEFAULT_BASE_URL, 'default_model': _GLM_DEFAULT_MODEL, 'key_env': 'ZHIPUAI_API_KEY'},
    }

    @classmethod
    def provider_info(cls):
        """当前提供方 + 受支持提供方清单（含展示元数据），供前端设置菜单渲染。"""
        return {
            'current': cls.LLM_PROVIDER,
            'deerflow_model': cls.DEERFLOW_MODEL,
            'has_api_key': bool(cls.LLM_API_KEY),
            'base_url': cls.LLM_BASE_URL,
            'model_name': cls.LLM_MODEL_NAME,
            'providers': [
                {'id': pid, 'label': meta['label'], 'needs_key': meta['needs_key'],
                 'deerflow_model': meta.get('deerflow_model', 'claude')}
                for pid, meta in cls.PROVIDER_META.items()
            ],
        }

    @classmethod
    def resolve_endpoint(cls, provider, base_url=None, model=None):
        """解析 OpenAI 兼容提供方的 (base_url, model)：显式值 > 当前已配置值 > 提供方默认值。

        「当前已配置值」只在 provider 就是当前提供方时沿用（与 API Key 的留空沿用语义一致）：
        否则设置页对已配置提供方点「测试/保存」且字段留空时，会改用 PROVIDER_META 的默认
        端点/模型——例如 GLM Coding Plan（open.bigmodel.cn/api/coding/paas/v4 + glm-5.3）
        被测成 api.z.ai + glm-4.6，得到 1113「余额不足」的假 429，保存则把默认值写回 .env。
        """
        meta = cls.PROVIDER_META.get(provider, {})
        same = provider == cls.LLM_PROVIDER
        url = ((base_url or '').strip() or (same and (cls.LLM_BASE_URL or '').strip())
               or meta.get('default_base') or 'https://api.openai.com/v1')
        name = ((model or '').strip() or (same and (cls.LLM_MODEL_NAME or '').strip())
                or meta.get('default_model') or 'gpt-4o-mini')
        return url, name

    @classmethod
    def apply_provider(cls, provider, api_key=None, base_url=None, model=None):
        """在运行时切换 LLM 提供方（对**新发起**的管线生效，无需重启）。

        更新 Config 类属性 + os.environ（DeerFlow 子进程继承环境变量），并持久化到 .env。
        OpenAI 兼容提供方未显式传 base_url/model 时：重新保存当前提供方沿用已配置的值，
        切换到其他提供方才回退到该提供方默认值（见 resolve_endpoint）。
        """
        provider = (provider or '').strip().lower()
        if provider not in cls.SUPPORTED_LLM_PROVIDERS:
            raise ValueError(f"不支持的提供方: {provider}（需为 {', '.join(cls.SUPPORTED_LLM_PROVIDERS)} 之一）")
        meta = cls.PROVIDER_META.get(provider, {})
        is_openai_compat = bool(meta.get('openai_compat'))

        keeps_existing_key = (provider == cls.LLM_PROVIDER and bool(cls.LLM_API_KEY))
        if meta.get('needs_key') and not ((api_key or '').strip() or keeps_existing_key):
            raise ValueError(f"提供方 {provider} 需要 API Key")

        # 校验/清洗用户输入，避免 .env 注入与 SSRF（EXECPLAN2 F-8-1 / F-13-2）。
        from .utils.security import sanitize_env_value, validate_safe_url
        try:
            api_key = sanitize_env_value(api_key) if api_key else api_key
            model = sanitize_env_value(model) if model else model
            base_url = sanitize_env_value(base_url) if base_url else base_url
        except ValueError as e:
            raise ValueError(f"非法字段（含换行/控制字符）：{e}") from e
        if is_openai_compat and base_url:
            try:
                validate_safe_url(base_url, block_private=cls.APP_BLOCK_PRIVATE_URLS)
            except ValueError as e:
                raise ValueError(f"非法的 base_url：{e}") from e

        # 在锁内完成「改类属性 + 改 os.environ + 写 .env」整段读改写（F-8-4）。
        with cls._provider_lock:
            # 必须在改写 LLM_PROVIDER 之前解析：「沿用已配置值」只对重新保存当前提供方成立。
            endpoint = cls.resolve_endpoint(provider, base_url, model)
            cls.LLM_PROVIDER = provider
            cls._is_kimi = provider == 'kimi'
            cls._is_minimax = provider == 'minimax'
            cls._is_deepseek = provider == 'deepseek'
            cls._is_qwen = provider == 'qwen'
            cls._is_glm = provider == 'glm'
            cls.DEERFLOW_MODEL = meta.get('deerflow_model', 'claude')

            env_updates = {'LLM_PROVIDER': provider, 'DEERFLOW_MODEL': cls.DEERFLOW_MODEL}
            if is_openai_compat:
                cls.LLM_BASE_URL, cls.LLM_MODEL_NAME = endpoint
                _key = (api_key or '').strip()
                if _key:
                    cls.LLM_API_KEY = _key
                env_updates['LLM_BASE_URL'] = cls.LLM_BASE_URL
                env_updates['LLM_MODEL_NAME'] = cls.LLM_MODEL_NAME
                if cls.LLM_API_KEY:
                    env_updates['LLM_API_KEY'] = cls.LLM_API_KEY
                    # 把 Key 镜像到提供方专属环境变量，供 deer-flow/config.yaml 的 $VAR 解析
                    # （deepseek→$DEEPSEEK_API_KEY、qwen→$DASHSCOPE_API_KEY、glm→$ZHIPUAI_API_KEY、
                    #  minimax→$MINIMAX_API_KEY），这样深度研究子进程也能拿到正确的 Key。
                    key_env = meta.get('key_env')
                    if key_env:
                        env_updates[key_env] = cls.LLM_API_KEY

            for k, v in env_updates.items():
                os.environ[k] = v
            # The runtime switch above already took effect; persistence is reported, not
            # raised. A stub that predates the (ok, error) contract (returns None) reads
            # as persisted, matching the old fire-and-forget semantics.
            persisted = cls._persist_env(env_updates)
            env_ok, env_error = (
                persisted if isinstance(persisted, tuple) and len(persisted) == 2 else (True, None)
            )
            info = cls.provider_info()
            info['env_persisted'] = bool(env_ok)
            info['env_persist_error'] = env_error
            return info

    @classmethod
    def _persist_env(cls, updates, *, env_path=None):
        """把 key=value 安全 upsert 进 .env，返回 ``(ok, error_class)``。

        每个值都经 sanitize（拒绝换行/控制字符，防止注入额外 KEY=VALUE 行）+ dotenv
        安全引号，再以 0600 原子落盘（EXECPLAN2 F-8-1；INFRA-10）。失败不再静默吞掉：
        返回 ``(False, 异常类名)``，由 apply_provider / 设置 API 如实上报，已有 .env 不被破坏。
        ``env_path`` 缺省为项目根 .env（测试传临时路径，绝不触碰真实 .env）。
        """
        try:
            from .utils.security import sanitize_env_value, quote_env_value
            from .utils.atomic import write_secret_text_atomic
            if env_path is None:
                env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../.env'))
            lines = []
            if os.path.exists(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    lines = f.read().splitlines()
            # 预先清洗所有值；任一非法直接放弃整次写入（不破坏现有 .env）。
            safe = {k: quote_env_value(sanitize_env_value(v)) for k, v in updates.items()}
            remaining = dict(safe)
            out = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith('#') and '=' in stripped:
                    key = stripped.split('=', 1)[0].strip()
                    if key in remaining:
                        out.append(f"{key}={remaining.pop(key)}")
                        continue
                out.append(line)
            for key, val in remaining.items():
                out.append(f"{key}={val}")
            write_secret_text_atomic(env_path, '\n'.join(out) + '\n')
        except Exception as exc:  # noqa: BLE001 — 上报失败类别，由调用方决定如何呈现
            return False, type(exc).__name__
        return True, None

    # ============================================================
    # 知识图谱后端：本地 Graphiti（替代 Zep Cloud）
    # 不再需要 ZEP_API_KEY / 任何外部 SaaS。图谱在本机运行：
    #   - 默认嵌入式 FalkorDB（falkordblite，Python>=3.12，无需 Docker）
    #   - 实体/关系抽取复用 Config.LLM_PROVIDER（含 claude-cli 等免 Key 提供方）
    #   - 向量嵌入用本地 sentence-transformers 多语言模型（无需 Key）
    # ============================================================
    # 图数据库后端：auto | falkordblite | falkordb | kuzu
    GRAPH_BACKEND = os.environ.get('GRAPH_BACKEND', 'auto').strip().lower()
    # 图数据持久化目录（嵌入式 FalkorDB / Kuzu 文件落盘位置）
    GRAPHITI_DATA_DIR = os.environ.get(
        'GRAPHITI_DATA_DIR',
        os.path.join(os.path.dirname(__file__), '../uploads/graphiti_db')
    )
    # 本地嵌入模型（多语言，覆盖中英文舆情内容）及其维度
    GRAPHITI_EMBED_MODEL = os.environ.get('GRAPHITI_EMBED_MODEL', 'paraphrase-multilingual-MiniLM-L12-v2')
    GRAPHITI_EMBED_DIM = int(os.environ.get('GRAPHITI_EMBED_DIM', '384'))
    # 重排序：rrf（默认，纯本地、零下载）| bge（本地 sentence-transformers 交叉编码器，更准但需下载模型）
    GRAPHITI_RERANKER = os.environ.get('GRAPHITI_RERANKER', 'rrf').strip().lower()
    # 可选：连接外部 FalkorDB 服务（设置后 auto 优先使用）
    FALKORDB_HOST = os.environ.get('FALKORDB_HOST') or None
    FALKORDB_PORT = int(os.environ.get('FALKORDB_PORT', '6379'))

    # 兼容保留：旧版 Zep 配置（已不再必需）。本地 Graphiti 不需要任何 Key，但代码中仍有若干
    # `if not Config.ZEP_API_KEY` / `if not self.api_key` 真值守卫与服务构造检查。给一个非空哨兵值
    # 让这些守卫一律通过（shim 会忽略该值），从而无需改动 5 个服务构造器与 API 守卫。
    # 四个重试/退避旋钮仍被分页工具复用于本地图谱的瞬态错误重试。
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY') or 'local-graphiti'
    # GRAPH-9 / GRAPH-11：4→2。瞬态错误重试预算降到 2，避免一个慢/卡死的 op 在失败前耗掉
    # 4×op_timeout；与受限的 op 超时配合把失败延迟收紧。
    ZEP_MAX_RETRIES = int(os.environ.get('ZEP_MAX_RETRIES', '2'))
    ZEP_RETRY_DELAY_SECONDS = float(os.environ.get('ZEP_RETRY_DELAY_SECONDS', '2.0'))
    ZEP_RATE_LIMIT_BUFFER_SECONDS = float(os.environ.get('ZEP_RATE_LIMIT_BUFFER_SECONDS', '1.0'))
    ZEP_RATE_LIMIT_MAX_SLEEP_SECONDS = float(os.environ.get('ZEP_RATE_LIMIT_MAX_SLEEP_SECONDS', '90.0'))
    
    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 文本处理配置
    # CHUNK-1 / GRAPH-2 / ONTO-1 / ONTO-2 / RESEARCH-1：500→2500 chars/episode。
    # ~400 个微 episode 是 5 小时建图的根因；2.5K chars 把相关三元组留在同一窗口，即便
    # concurrency=1 也把 episode 数砍 ~5x，且提升关系召回。orchestrator/本体分块共用此默认。
    DEFAULT_CHUNK_SIZE = int(os.environ.get('DEFAULT_CHUNK_SIZE', '2500') or '2500')  # 默认切块大小（chars/graph episode）
    # CHUNK-1 / GAP-3：50→250（~10% chunk_size，按更大块等比放大），保证实体不在边界被切断又不大量重抽。
    DEFAULT_CHUNK_OVERLAP = int(os.environ.get('DEFAULT_CHUNK_OVERLAP', '250') or '250')  # 默认重叠大小
    
    # OASIS模拟配置
    # T3.7: 0 = 不截断（跑满按 total_hours/minutes_per_round 算出的完整轮数，如 72h/60min=72 轮）。
    # 设为正整数则作为全局轮数上限（每次运行可被 options.max_rounds 覆盖；冒烟测试用小值）。
    # SIM-2：0→36。封顶一个 config-gen 产出的病态 336 轮（~9x）；options.max_rounds 仍可为长时域覆盖。
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '36'))
    # —— 日历时间轴模式（TEMPORAL-*；仅影响 config 生成，运行侧按 temporal_config 是否存在分派）——
    # calendar（默认）= 生成 temporal_config：每轮对应一个自然日历时段（日/周/半月/月/季/半年），
    # 事件按真实日期落轮、预测期限完整覆盖。hours = 不生成 temporal_config，走旧的小时制路径（字节不变）。
    SIM_TEMPORAL_MODE = os.environ.get('SIM_TEMPORAL_MODE', 'calendar').strip().lower()
    # 日历单位选择的软轮数预算（时间粒度在此预算内取最接近理想轮数的单位；不截断预测期）。
    SIM_CALENDAR_TARGET_MAX_ROUNDS = int(os.environ.get('SIM_CALENDAR_TARGET_MAX_ROUNDS', '36') or '36')
    # 绝对轮数上界（短时域反锯齿细化的天花板，防止 unit 细化后轮数失控）。
    SIM_CALENDAR_HARD_MAX_ROUNDS = int(os.environ.get('SIM_CALENDAR_HARD_MAX_ROUNDS', '48') or '48')
    # 问题中解析不出预测期限（确定性各档 + LLM 兜底均失败）时的降级默认时域（月）。
    SIM_HORIZON_DEFAULT_MONTHS = int(os.environ.get('SIM_HORIZON_DEFAULT_MONTHS', '12') or '12')
    # 世界时钟头部附带上一时段变化摘要（world_delta 纯确定性拼装，仅日历模式生效）。
    SIM_WORLD_DELTA = os.environ.get('SIM_WORLD_DELTA', 'true').strip().lower() == 'true'
    # REPORT-6：世界时钟头部区分「首轮 / 平静期 / 摘要不可用 / 本次运行不产出摘要」与
    # 「本时段无日程事件」，取代一律回落的 "(first period)" / "(none)"（演化失败或 in-band
    # 关闭时每轮都自称首轮，与 "round N/M" 矛盾；"(none)" 被读成"世界无事发生"）。
    # 默认开是安全的：只改 agent 可见的占位措辞（不含数字/百分号，herding guard 不变）+
    # 轨迹附加键 delta_state_counts；关闭 → 头部与轨迹逐字节回到旧行为。
    SIM_ABSENCE_MARKERS = os.environ.get('SIM_ABSENCE_MARKERS', 'true').strip().lower() == 'true'
    # SIM-6：逐时段上下文如实送达。世界时钟事件段改标「研究时间线上的预期事件，结果事先未知」
    # （不再称 CONFIRMED）、情景注入标 SCENARIO ASSUMPTION；摘要落后于时钟时注明其覆盖时段；
    # sampled agent 缺席事件轮后首次激活时补报漏掉的日程事件；全平台死轮的到期事件并入下一次
    # 摘要；摘要事件/帖文分段整行封顶带省略标记（不再静默截断 900 字符）；无状态的回应阶段
    # 辅助 agent 也拿到本期事件与变化。默认开是安全的：只改 agent 可见措辞（诊断性质的模拟），
    # 不新增 LLM 调用，占位措辞仍由 SIM_ABSENCE_MARKERS 决定；关闭 → agent 可见文本逐字节回到旧行为。
    SIM_PERIOD_CONTEXT_V2 = os.environ.get('SIM_PERIOD_CONTEXT_V2', 'true').strip().lower() == 'true'
    # SIM-6：漏报事件补报块的字符上限（整行保留、最新优先，超出部分以 "(+N earlier scheduled
    # events omitted)" 标注）；只影响缺席过事件轮的 agent，控制记忆增长与 token 成本。
    SIM_EVENT_CATCHUP_MAX_CHARS = int(os.environ.get('SIM_EVENT_CATCHUP_MAX_CHARS', '1200') or '1200')
    # 决策通道改为逐轮在环内引出承诺并推进 WorldState（仅日历模式；关闭则回退事后一次性通道）。
    SIM_DECISION_CHANNEL_INBAND = os.environ.get('SIM_DECISION_CHANNEL_INBAND', 'true').strip().lower() == 'true'
    # WorldState.step 熵地板：按时段天数向种子基率先验混合，防止长时域份额锁死（仅日历模式生效）。
    WORLDSTATE_ENTROPY_MIX = os.environ.get('WORLDSTATE_ENTROPY_MIX', 'true').strip().lower() == 'true'
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    # —— OASIS 并发上限（每轮在飞 LLM 请求数）单一真源（EXECPLAN2 I-8-4）——
    # 此前这两个旋钮只在 utils/oasis_llm.py::get_oasis_semaphore 里经 os.environ 直读，
    # 绕过了集中式 Config 配置面——对 doctor/validate/run 清单不可见、无法记录复现。
    # 提升为一等 Config 属性，默认值与 oasis_llm.py 的 DEFAULT_*_SEMAPHORE 逐字节一致
    # （CLI 提供方 8、OpenAI 兼容提供方 30），故 env 未设时行为字节稳定不变。
    # CLI 提供方(claude-cli/codex-cli)：每个调用 spawn 子进程，8 是吞吐与负载的稳妥平衡。
    OASIS_CLI_SEMAPHORE = int(os.environ.get('OASIS_CLI_SEMAPHORE', '8') or '8')
    # OpenAI 兼容提供方：纯 HTTP 并发。SIM-3：默认 24（在飞 agent LLM 调用数，//platforms 分摊）；
    # 从保守值 16→24→32 逐档 ramp 盯 p95，而非一步到 64。
    OASIS_SEMAPHORE = int(os.environ.get('OASIS_SEMAPHORE', '24') or '24')
    
    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent配置
    # T4.4/RQ-1: 每章最多工具调用。默认 8→12——展开后的长章节（目标 3000-6000 字 + 2-4 个
    # ### 子小节）需要更多实证检索轮次才能填满机制密度；小 page_budget 的报告经 derive_report_shape
    # 收敛回 8（见 report_agent._report_shape）。运维可下调以省成本。
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '12'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    # 章节正文生成的输出 token 上限（OpenAI 兼容提供方生效；CLI 提供方由 prompt 篇幅下限驱动）。
    # 此前硬编码 8192，会截断长章节正文。默认提升到 32768——gemini-3.5-flash 等大输出模型
    # （65536 输出上限）可写出更完整的分析章节；需要更省/更短可调低。强制收尾兜底仍受此约束。
    REPORT_AGENT_SECTION_MAX_TOKENS = int(os.environ.get('REPORT_AGENT_SECTION_MAX_TOKENS', '32768') or '32768')
    # REPORT-9：中间「工具选择」回合的较小补全预算。32768 用在决定工具的回合上会诱发冗长推理；
    # 仅压中间回合，最终答案回合仍用 REPORT_AGENT_SECTION_MAX_TOKENS（32768），不缩短成稿章节长度。
    REPORT_AGENT_TOOL_TURN_MAX_TOKENS = int(os.environ.get('REPORT_AGENT_TOOL_TURN_MAX_TOKENS', '8192') or '8192')
    # RQ-1：章节篇幅契约（展开默认）。REPORT_SECTION_TARGET_CHARS 为 'lo-hi' 目标区间（字符数，
    # 模板进 SECTION_SYSTEM/USER_PROMPT），REPORT_SECTION_FLOOR_CHARS 为硬下限。默认 3000-6000 /
    # 下限 2000，取代旧的 1800-2800 / 1500。小 page_budget 报告经 derive_report_shape 收敛回旧的
    # 紧凑值（1800-2800 / 1500），故此处仅设「无/大 page_budget」时采用的展开上限。解析失败回退默认。
    REPORT_SECTION_TARGET_CHARS = os.environ.get('REPORT_SECTION_TARGET_CHARS', '3000-6000').strip()
    REPORT_SECTION_FLOOR_CHARS = int(os.environ.get('REPORT_SECTION_FLOOR_CHARS', '2000') or '2000')

    @classmethod
    def report_section_target_chars(cls):
        """把 REPORT_SECTION_TARGET_CHARS('lo-hi') 解析成 (lo, hi) 两个正整数；
        任何解析失败（缺分隔符/非数字/lo>=hi）回退到展开默认 (3000, 6000)（degrade-safe）。"""
        raw = (cls.REPORT_SECTION_TARGET_CHARS or '').strip()
        try:
            lo_s, hi_s = raw.split('-', 1)
            lo, hi = int(lo_s.strip()), int(hi_s.strip())
            if lo > 0 and hi > lo:
                return lo, hi
        except (ValueError, AttributeError):
            pass
        return 3000, 6000

    # 支持的 LLM 提供方（直接从 PROVIDER_META 派生，新增提供方只需改一处）
    SUPPORTED_LLM_PROVIDERS = tuple(PROVIDER_META.keys())

    # ============================================================
    # DeerFlow 深度研究集成（前置 Step 0：用一个 prompt 自动调研生成种子材料）
    # DeerFlow runs in its OWN venv (separate dependency tree). MiroFish launches
    # the in-repo deer-flow checkout's deerflow_research.py via subprocess and
    # consumes the file-based handoff contract.
    # ============================================================
    # 默认指向仓库内的 deer-flow 目录（由 ./setup.sh 自动下载）：<repo>/deer-flow
    DEERFLOW_DIR = os.environ.get(
        'DEERFLOW_DIR',
        os.path.abspath(os.path.join(os.path.dirname(__file__), '../..', 'deer-flow'))
    )
    # DeerFlow venv 的 python（留空则自动探测 .venv，再退回到 `uv run`）
    DEERFLOW_PYTHON = os.environ.get('DEERFLOW_PYTHON', '').strip() or None
    # DeerFlow config.yaml 中的模型名（默认 claude → Claude Code 订阅 OAuth；
    # 可选 claude | minimax | deepseek | qwen | glm | codex | kimi）
    DEERFLOW_MODEL = os.environ.get('DEERFLOW_MODEL', 'claude').strip()
    # 研究深度：quick / standard / deep。CONF-1：默认 standard→deep——deep 的多轮调研协议
    # （source map → primary evidence → contradictions → synthesis）是报告证据密度的最大杠杆。
    DEERFLOW_RESEARCH_DEPTH = os.environ.get('DEERFLOW_RESEARCH_DEPTH', 'deep').strip().lower()
    # 研究报告/结构化输出语言。CONF-1：默认 Chinese→空 = 不传 --target-language，由模型按
    # brief 自动检测语言（英文 brief → 英文报告）。所有消费方均 None-safe：编排器空值不加
    # CLI 参数；report_agent 先走 detect_output_language(brief) 再回退。显式设值仍强制该语言。
    DEERFLOW_RESEARCH_LANGUAGE = os.environ.get('DEERFLOW_RESEARCH_LANGUAGE', '').strip() or None
    # 研究阶段最长等待秒数（仅作为兜底/显式覆盖；正常由研究深度自适应）
    DEERFLOW_RESEARCH_TIMEOUT = int(os.environ.get('DEERFLOW_RESEARCH_TIMEOUT', '10800'))
    # 是否启用 DeerFlow 子代理（并行 scoped workers，更深但更慢）。CONF-1：默认 false→true——
    # 并行 scoped workers 的覆盖增益远超时延成本（时延由 deerflow_depth_budget 的 ×1.5 兜住）。
    DEERFLOW_SUBAGENTS = os.environ.get('DEERFLOW_SUBAGENTS', 'true').strip().lower() == 'true'
    # 深度研究 per-KIQ / per-actor 子代理扇出（EXECPLAN2 I-0-4）：开场 scope pass 产出种子清单后，
    # 并行派发若干 scoped 子调查，合并工作笔记再做矛盾核验+综合。CONF-1：默认 false→true——
    # per-KIQ 扇出显著抬高证据覆盖；关闭则回到线性协议。经 env 下发给 deerflow 子进程（独立 venv）读取。
    RESEARCH_DEEP_FANOUT = os.environ.get('RESEARCH_DEEP_FANOUT', 'true').strip().lower() == 'true'
    # 扇出宽度上限（并行子调查数）；防止子代理把工具/LLM 预算放大失控。CONF-1：4→8 与扇出默认开配套。
    RESEARCH_FANOUT_WIDTH = int(os.environ.get('RESEARCH_FANOUT_WIDTH', '8') or '8')
    # 研究引擎选择（deep-research engine v3）。编排器把规范化后的值经 env RESEARCH_ENGINE
    # 显式下发给研究子进程（不再依赖子进程继承的环境），取值：
    #   v3     —— 默认。线性有界引擎（deerflow_bridge/linear_research.py + research_gateway.py）：
    #             plan → 按 KIQ 有界并行采集 → gap → 分节综合 → 确定性 QA → 定稿/结构化抽取；
    #             引擎内部自带有界并行扇出，故编排器对 v3 强制单条外层研究轨（忽略
    #             RESEARCH_PARALLEL_TRACKS>1，避免重复的证据开销与 --evidence-only 契约不兼容）。
    #             v3 不产出 Track B 卷宗/封印的 actor-intelligence 平面：准入时 actor 策略对 v3
    #             钉为非必需并披露原因（DEERFLOW_DUAL_TRACK 仅对 legacy 生效）。
    #   linear —— v3 的别名（兼容历史 .env 里的 RESEARCH_ENGINE=linear）。
    #   legacy —— 旧 LangGraph 多 pass 引擎（外层多轨/全局综合/--evidence-only 等行为与今日逐字节一致）；
    #             deerflow / agentic 为其别名（与 bridge 侧解析器的别名集合一致）。
    # 未知值按 v3 处理并告警一次；空值 = 默认 v3。引擎自身旋钮见 .env.example 的 RESEARCH_LINEAR_*。
    RESEARCH_ENGINE = os.environ.get('RESEARCH_ENGINE', 'v3').strip().lower()
    # v3 quantitative-row page verification (RESEARCH-4): each quantitative.json row is
    # checked against the fetched page of the source it cites and labelled verification =
    # verified | unverified | snippet_only | none (absent = unchecked: no checkable number on
    # a fetched page), plus a `verified` bool; values are never changed.  snippet_only means
    # the source was never fetched or its stored page is unavailable; its search snippet is
    # not checked, so the label says nothing about whether the number appears anywhere.
    # The same knob gates the evidence windows (REPORT-7): the page sentence that states a
    # verified figure next to >= 2 of its metric words becomes a sources.json `supports`
    # span (<= 360 chars, cleaned like web text; <= 2 per figure, <= 8 per source, every
    # figure's best window first; windows over the cap are counted, never silent), so the
    # report's number-aware citation check sees figures deeper than the 1,200-char page
    # excerpt; quant rows keep source_ref and get evidence_window / future_dated, and the
    # findings and figures are projected to handoff verified_facts.json (SHA-manifested).
    # Default true: deterministic, zero model calls, labels and spans are additive keys;
    # false leaves every research artifact byte-identical.  The parent forwards it to the
    # v3 child.
    RESEARCH_VERIFIED_FACTS = os.environ.get('RESEARCH_VERIFIED_FACTS', 'true').strip().lower() == 'true'
    # v3 reported/projected typing of quantitative rows (RESEARCH-4): epistemic_class,
    # date_precision, target-date repair (a forecast's target date put in as_of_date),
    # future-dated rows bucketed apart from fresh ones in meta.quant_freshness, and a
    # date-semantics rule in the facts extraction prompt.  Default false: the facts prompt
    # changes extraction behaviour and needs a live A/B first; off = byte-identical rows,
    # prompt and meta.  The parent forwards it to the v3 child.
    RESEARCH_QUANT_TYPING = os.environ.get('RESEARCH_QUANT_TYPING', 'false').strip().lower() == 'true'
    # RESEARCH-5: report-side rendering of that typing.  On, a persona's quantitative fact the
    # research stamped projected/unknown carries "(expectation by {source}, target {period})",
    # or ", as of {date}" when the row states only the source's date
    # (actor_role_prompt._pack_report_rows), and the chart labels read epistemic_class before
    # value_kind/value_type (report_visualizer: projected -> forecast marker, reported -> actual).
    # Default false: it changes role-prompt bytes (PREPARE recomputes their SHAs) and chart
    # markers, and only acts on rows RESEARCH_QUANT_TYPING stamped; off = byte-identical.
    QUANT_TYPED_RENDERING = os.environ.get('QUANT_TYPED_RENDERING', 'false').strip().lower() == 'true'
    # RESEARCH-6: forecaster attribution in v3 fact extraction.  On, the facts task asks each
    # estimate/forecast/target row for its forecaster (also written to `analyst`, so charts
    # split by forecaster rather than by publisher) with a forecaster-free metric, plus the
    # range (low/high) and forecaster count (n_forecasters) the report states.  Every kept
    # bound must be made of the report's own numbers and a count must stand next to a count
    # noun ("40 economists"); a value written as a range becomes low/high (range_kind
    # stated_range); meta.forecaster_attribution counts kept and dropped fields.  Default
    # false: the fields add ~5-10% extraction output and the forecaster names change which
    # quant rows match an actor in PREPARE context packs (a row that matched still matches
    # and, at the 32-row pack cap, keeps its place: forecaster-only matches fill spare
    # slots only, FU-10); off =
    # byte-identical facts prompt, quantitative.json and meta.  The parent forwards it to
    # the v3 child.
    RESEARCH_FORECASTER_ATTRIBUTION = os.environ.get(
        'RESEARCH_FORECASTER_ATTRIBUTION', 'false').strip().lower() == 'true'
    # RESEARCH-10 v3 evidence headers: each KIQ block of the writers' evidence digest opens
    # with the engine's count of its evidence (sourced findings by tag, cited sources
    # fetched vs snippet-only, distinct domains; counted before lines are dropped for
    # length) and a sufficiency label (insufficient: deterministic fallback notes, < 3
    # sourced findings or no fetched source; thin: < 2 VERIFIED, < 2 fetched or < 2
    # domains; else adequate); a legend opens the digest, the gap review's coverage matrix
    # gains fetched/domains/sufficiency, the section rules gain one thin-evidence line,
    # meta.kiqs gains evidence/sufficiency and a degradation event fires when at least
    # half of the researched KIQs are insufficient.  Zero model calls.  Default false: it
    # changes the writers' cached prefix and section task, and the DRF-original thresholds
    # must first be validated on stored kiq/*.json; off = digest, coverage matrix, section
    # task and meta byte-identical.  Forwarded to the v3 child.
    RESEARCH_EVIDENCE_HEADERS = os.environ.get('RESEARCH_EVIDENCE_HEADERS', 'false').strip().lower() == 'true'
    # RESEARCH-10 fair deterministic truncation (v3): the plan's scout digest shares its
    # 6,000 chars max-min fairly between the scout queries (each keeps at least an equal
    # share), cut only between search results and noting "(k results omitted for
    # length)", where the head-cut of the joined digest silently lost the last queries;
    # an over-cap digest block drops, among lines of equal priority, the one sharing the
    # fewest terms with the KIQ question first (not simply the last).  Zero model calls.
    # Default false: it changes the plan prompt and the writers' digest; off =
    # byte-identical.  Forwarded to the v3 child.
    RESEARCH_TRUNCATION_FAIRNESS = os.environ.get(
        'RESEARCH_TRUNCATION_FAIRNESS', 'false').strip().lower() == 'true'
    # RESEARCH-1：抓取层抽取空壳检测（诚实性检查，故默认开 = fail closed）。开启时 reader 空壳
    # （"Markdown Content: undefined"）、"page unavailable" 页、bot wall 与短付费墙预告不再算成功
    # 读取：不进 72h 源缓存、触发 provider 回退、v3 工具层返回 FETCH_FAILED(<reason>) 且绝不标记
    # fetched；续跑的工作目录里检查之前存下的空壳页取消 fetched 标记，定稿时以 cited 发布
    # （fetch_status=shell:<reason>）。false = 空壳处理与之前逐字节一致（直连回退的 PDF 解析
    # 修复无条件生效）。fail closed：只有显式假值 0/false/no/off 关闭，空值、1/yes/on 与拼写
    # 错误都保持开启（与 bridge 侧解析一致）。编排器经 env 显式下发给研究子进程
    # （cached_fetch / linear_research 读取）。
    RESEARCH_FETCH_SHELL_DETECTION = os.environ.get(
        'RESEARCH_FETCH_SHELL_DETECTION', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
    # RESEARCH-1：v3 单次 web_fetch 的硬墙钟上限（秒）。旧路径 asyncio.run 在收尾时等待事件循环
    # 默认线程池，挂住的 to_thread 解析/SDK/DNS 可让一次抓取远超各 provider 超时；有界运行器
    # 到时即返回 FETCH_FAILED(fetch_call_deadline_exceeded)（非瞬态，不重试）且不等残留线程。
    # 默认 150：最坏 provider 链约 90s 加余量，仍低于工具层 singleflight 等待（180s）。成功的
    # 抓取结果不变；0 = 旧的 asyncio.run 路径（逐字节一致）。
    RESEARCH_FETCH_CALL_TIMEOUT_S = max(
        0, int(os.environ.get('RESEARCH_FETCH_CALL_TIMEOUT_S', '150') or '150'))
    # RESEARCH-2: typed source outcomes for the research tools.  On: search budget
    # denials stop counting as fetch failures; a Firecrawl 401/402 on search latches
    # the v3 run (SEARCH_NOT_CONFIGURED, no further backend calls) and on fetch
    # disables Firecrawl for the process and opens the shared provider circuit;
    # outages never enter the gateway run cache or the fetch negative cache; a DDG
    # "No results found" is SEARCH_EMPTY_UNCONFIRMED; fetch failures say whether the
    # service (FETCH_UNAVAILABLE) or the page (FETCH_FAILED) failed; meta.source_health
    # and source-health degradation events are written.  Default false: the new
    # sentinels may end some KIQs earlier during outages and need a live comparison
    # run first; off = byte-identical tool text, caches and meta.  The parent forwards
    # it to every research child (search_tools / cached_fetch / linear_research).
    RESEARCH_SOURCE_TAXONOMY = os.environ.get('RESEARCH_SOURCE_TAXONOMY', 'false').strip().lower() == 'true'
    # RESEARCH-3 absence discipline (v3): web search is relevance-ranked and undated, so
    # an empty search is not evidence that something did not happen.  On: an empty
    # search answers NO_RESULTS plus that sentence, the KIQ task and the section rules
    # each gain one line (state an absence only when a cited source says so), and
    # findings that state an absence are counted per KIQ (record absence_cues) and per
    # run (meta.absence_findings) without changing any tag.  Default false: it changes
    # agent and writer prompts, which needs a live comparison run first; off = tool
    # text, prompts, KIQ records and meta byte-identical.  Forwarded to the v3 child.
    RESEARCH_ABSENCE_DISCIPLINE = os.environ.get(
        'RESEARCH_ABSENCE_DISCIPLINE', 'false').strip().lower() == 'true'
    # RESEARCH-11 v3 question spec: one post-scout JSON call (reusing the plan call's
    # cached prefix) pins the operational question, outcome definition, resolution
    # source, horizon and reference class, and discloses at most 3 defaults it chose
    # instead of asking.  Written to handoff question_spec.json (drf.question_spec/v1,
    # SHA-manifested), appended to the run brief, fed to the plan call and mirrored
    # into actors.json (question_spec, horizon_date, forecast_inputs.base_rates).  A
    # failed call never fails the run (status unavailable + a degradation event).
    # Default false: it adds a model call and changes the plan prompt; off = brief,
    # plan, actors.json and every prompt byte-identical.  Forwarded to the v3 child.
    RESEARCH_QUESTION_SPEC = os.environ.get('RESEARCH_QUESTION_SPEC', 'false').strip().lower() == 'true'
    # RESEARCH-12 question spec consumers (backend only): a valid actors.json
    # question_spec (schema, status ok/partial, spec_sha256 recomputed; anything else is
    # ignored) supplies the simulation calendar's horizon below every deterministic
    # prompt date (skipping the LLM fallback; horizon_source 'question_spec') and
    # _infer_horizon_date's fallback, is prepended to the spine prompt's research
    # inputs (only when its deadline is the run's horizon), is disclosed in the
    # report's resolution section and is summarized in forecast.json question_spec
    # (horizon_applied records that check).  Default true is safe: without a spec (needs
    # RESEARCH_QUESTION_SPEC) every consumer is byte-identical.  False = shadow mode
    # (the spec stays persisted but unused).
    QUESTION_SPEC_DOWNSTREAM = os.environ.get('QUESTION_SPEC_DOWNSTREAM', 'true').strip().lower() == 'true'
    # Forecast-input extraction master switch (EXECPLAN2 I-0-5), read by the legacy
    # bridge's extraction prompt and the report agent's forecast-inputs block (both
    # already read this name); parsed exactly like the bridge (unset or empty = true,
    # else 1/true/yes/on), so the default keeps today's behaviour.  Forwarded to every
    # research child.
    RESEARCH_FORECAST_INPUTS = (os.environ.get('RESEARCH_FORECAST_INPUTS', '').strip().lower() or 'true') in (
        '1', 'true', 'yes', 'on')
    # Evidence-grading switch (EXECPLAN2 I-0-0/I-0-1): source tiers, dates and Admiralty
    # grades plus contested claims in the legacy bridge's extraction, and the report
    # agent's contested-claims block and tiered source index.  INFRA-14 declared it
    # (the report agent read it with a getattr default, so .env never reached the
    # backend) and forwards it to every research child.  Parsed like its sibling above
    # and the bridge (blank = true, else 1/true/yes/on), so the default and every
    # child's reading stay as they were.
    RESEARCH_EVIDENCE_GRADING = (os.environ.get('RESEARCH_EVIDENCE_GRADING', 'true').strip().lower()
                                 or 'true') in ('1', 'true', 'yes', 'on')
    # Quantitative sanity checks of the research child (TIME-4): quantitative rows on the
    # same metric and unit (v3: also the same period end and length, geography and
    # reported/projected class, but not the series name, so two entities' readings of one
    # generic metric can still reconcile) that disagree by > 10% become contested.json
    # claims (origin quant_reconcile; v3 adds at most 10, probable unit-scale errors first),
    # a ~1000x gap is also a probable unit-scale error in meta.quant_unit_warnings, and
    # claimed actuals dated after the research as-of (v3: also those whose as_of_date the
    # bridge cannot read, or for a period ending after it) or with > 150% growth are listed
    # in meta.quant_implausible.  Read-only:
    # quantitative.json never changes.  The legacy engine has always run them under this
    # bridge-read name (its full run lists quant_implausible regardless of the knob);
    # TIME-4 restores them in v3 and the extract-only salvage.  Parsed like the bridge
    # (blank = true, else 1/true/yes/on), so the default keeps the legacy engine as it
    # was; false = v3 and extract-only artifacts and meta byte-identical to before.
    # Forwarded to every research child.  The report agent reads it too (FU-9): when its
    # contested-claims block (at most 15 claims) would cut quant_reconcile rows, up to 3
    # slots (more when the plain cut already shows more) go to them, probable unit-scale
    # errors first, and a note counts those still cut; nothing changes when nothing is
    # cut, and false = the plain first-15 cut.
    RESEARCH_QUANT_RECONCILE = (os.environ.get('RESEARCH_QUANT_RECONCILE', 'true').strip().lower()
                                or 'true') in ('1', 'true', 'yes', 'on')
    # RESEARCH-11 v3 forecast inputs: the facts extraction also asks for the drivers
    # and dated leading indicators (precision-preserving dates, never padded) that
    # fill actors.json forecast_inputs.drivers / .indicators, which v3 wrote empty.
    # Needs RESEARCH_FORECAST_INPUTS too.  Default false until one live A/B: it
    # extends the facts prompt; off = prompt and actors.json byte-identical.
    # Forwarded to the v3 child.
    RESEARCH_V3_FORECAST_INPUTS = os.environ.get(
        'RESEARCH_V3_FORECAST_INPUTS', 'false').strip().lower() == 'true'
    # RESEARCH-9 v3 citation stats: the QA phase records qa.json citation_stats
    # (markers before QA and published, orphan markers renumbering dropped, stale
    # groups, cited fetched vs snippet sources and their marker share, unused fetched
    # pages, writer bibliographies, scaffold echo lines, prose numbers no evidence
    # traces), mirrored into meta.research_qa and meta.research_quality.  Detection
    # only, so default on: research_report.md and sources.json are byte-identical
    # either way; off = no key.  Forwarded to the v3 child.
    RESEARCH_V3_CITATION_STATS = os.environ.get(
        'RESEARCH_V3_CITATION_STATS', 'true').strip().lower() == 'true'
    # INFRA-4: v3 research-gateway JSON parsing (parse_json_object) rejects NaN, Infinity,
    # -Infinity and overflowing float literals (1e999): a model reply carrying one is unparseable
    # (a dict nested inside it is not taken for the reply either), so the gateway's JSON retry
    # asks again (naming the non-finite number) instead of handing a NaN to the plan, facts and
    # handoff artifacts.  Control characters stay tolerated.  Default true is safe: replies with
    # finite numbers parse byte-identically; false = the previous permissive decoder.  The bridge
    # reads it from its env; the parent forwards it to the v3 child.
    RESEARCH_JSON_STRICT_NUMBERS = os.environ.get(
        'RESEARCH_JSON_STRICT_NUMBERS', 'true').strip().lower() == 'true'
    # RESEARCH-7: verbatim evidence-span contract for v3 findings (off | audit | enforce).
    # Not off: the KIQ task asks each finding for an EVIDENCE: "<verbatim passage>" clause,
    # the source ledger keeps every distinct search snippet of a row, and each quote is
    # located deterministically (zero model calls) in the stored page / search text of the
    # cited sources; KIQ facts get evidence, evidence_status, evidence_near_miss,
    # claimed_tag and a REPORTED-number audit, and meta.evidence is written.  audit changes
    # no tag; enforce demotes a fact whose quotes are not on what the agent was shown
    # (UNVERIFIED) or a VERIFIED fact whose numbers lie outside its quoted passages
    # (REPORTED).  Default off (byte-identical prompts, facts, ledger and sources.json):
    # longer notes cost ~2-3% more units and GLM may paraphrase; enforce needs an
    # owner-approved audit run (located share >= 0.8, QA passing) first.  Blank or an
    # unknown value is off.  The parent forwards it to the v3 child.
    RESEARCH_EVIDENCE_QUOTES = os.environ.get('RESEARCH_EVIDENCE_QUOTES', 'off').strip().lower()
    # RESEARCH-7: with RESEARCH_EVIDENCE_QUOTES not off, up to 3 located verbatim quotes of
    # a source (<= 280 chars, page quotes first) become its sources.json `supports`, ahead
    # of the REPORT-7 evidence windows.  Default false: supports feed the report's
    # semantic-citation and quote-grounding checks (publish-gate inputs), so the gate delta
    # is measured in an audit run first; off = supports exactly as before.  Forwarded to
    # the v3 child.
    RESEARCH_EVIDENCE_SUPPORTS = os.environ.get('RESEARCH_EVIDENCE_SUPPORTS', 'false').strip().lower() == 'true'
    # RESEARCH-8: declarative derived findings in v3.  On, the KIQ task asks a finding
    # that states a figure the agent calculated (growth rate, ratio, share) to end with
    # "(DERIVED: <formula>; a=<value> [S<n>], ...)", and the notes postprocessor
    # recomputes it with zero model calls (hardened Decimal evaluator, operands checked
    # at their full value on the one fetched page they cite, stated result within
    # display precision, every other figure of the finding on that page too): a
    # passing finding is tagged DERIVED (never VERIFIED), a failing one UNVERIFIED with
    # a derivation_error.  The digest shows the calculation, the section rules say how
    # to state it, sources.json gains a separate derived_supports field (the report's
    # citation evidence spans read it), unverified quant rows matching a DERIVED result
    # gain derived_from, and meta gains kiqs.derived and derived.  Default false: model
    # compliance with the clause format is unmeasured; off = KIQ task, section rules,
    # facts, digest, sources.json and meta byte-identical.  Forwarded to the v3 child.
    RESEARCH_DERIVED_FINDINGS = os.environ.get('RESEARCH_DERIVED_FINDINGS', 'false').strip().lower() == 'true'
    # TIME-2 source publication dates (v3): each searched/fetched source is dated from
    # its provider metadata (Firecrawl scrape metadata and search row dates, Exa
    # published_date, the opt-in direct fetch's JSON-LD/<meta>/<time>), converted to the
    # UTC calendar (offsets applied, offset-less values and epochs read as UTC) with its
    # precision and provenance; a date after the run's UTC date or before 1900 is
    # rejected, never clamped.  Shown in tool row headers (outside the untrusted
    # block), the SOURCE INDEX and References; written to sources.json (date,
    # date_precision, date_source, modified_at, modified_source, date_rejected),
    # quantitative rows (source_date, as_of_after_source: an actual value dated after
    # its source, where only a metadata modified date widens the source's window and a
    # page-head "Updated:" line never does; never dropped) and meta.source_dates (dated /
    # undated / rejected counts by source and precision).  Zero model calls.  Default
    # false: the extractors are unproven on real pages and need a precision check
    # first; off = tool text, source ledger, sources.json and report byte-identical.
    # The fetch layer records date metadata whatever this flag says (source-cache
    # entries gain a "meta" key when a provider reported dates; the opt-in direct
    # fetch scans the page head for them), so a later flag-on run dates cache hits
    # too; nothing reads that metadata while the flag is off.  Forwarded to the v3
    # child.
    RESEARCH_SOURCE_DATES = os.environ.get('RESEARCH_SOURCE_DATES', 'false').strip().lower() == 'true'
    # TIME-2: with RESEARCH_SOURCE_DATES on, sources are also dated from two heuristics
    # ranked below metadata: a fetched page's head datelines (Published/Updated/发布时间
    # lines) and the URL path (/YYYY/MM/DD/) of a fetched page or a search row.  Off,
    # only provider/HTML metadata and search-provider row dates date a source.  Only
    # read when RESEARCH_SOURCE_DATES is on, so the default true changes nothing by
    # itself; only 0/false/no/off disable it (the child reads unknown values as on).
    # Forwarded to the v3 child.
    RESEARCH_SOURCE_DATE_TEXT_FALLBACK = os.environ.get(
        'RESEARCH_SOURCE_DATE_TEXT_FALLBACK', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
    # PAR-2：编排器级「多角度并行研究轨」。>1 时研究阶段并行跑 K 个 DeerFlowResearchRunner
    # 子进程，每个带角度特化前缀（轨1=基线证据扫描，即原始 brief 逐字；轨2=基率/参照类/历史
    # 类比；轨3=行为者激励+反面证伪+市场定价），各写入 handoff/track_<k>/，随后确定性合并回
    # handoff/（报告按 '# Track N' H1 拼接、来源按 URL 去重保最高层级、actors 走 reconcile_cast、
    # quantitative/contested/timeline 拼接去重、research_quality 取各轨最小值、预测市场取最新）。
    # 各轨看门狗用既有 per-run 预算故 wall-clock ≈ 1 轨。默认 3；某轨失败 → 用存活轨（≥1）继续
    # 并打降级标；全失败 → 阶段失败（与今日一致）。设 1 = 今日单轨路径逐字节一致（degrade-safe）。
    # 上限受已定义角度数约束（当前 3）；>3 的值被夹到 3。
    RESEARCH_PARALLEL_TRACKS = max(1, int(os.environ.get('RESEARCH_PARALLEL_TRACKS', '3') or '3'))
    # LOOP-010: parallel tracks own evidence discovery, not three independent
    # publishable dossiers.  With >1 track, export lossless evidence packs and
    # run one global routed synthesis/judge/extraction namespace afterward.
    RESEARCH_GLOBAL_SYNTHESIS = os.environ.get(
        'RESEARCH_GLOBAL_SYNTHESIS', 'true').strip().lower() == 'true'
    # LOOP-009：外层轨与 harness 子代理共享一个并行度信封。旧行为是 3 外轨 × 每轨 5
    # 子代理 = 最多 15 条并发模型流；最近实跑显示这会重复上下文与检索、而非线性增质。
    # 默认全局信封 9、每轨最多 5：3 轨时自动分成 3/轨，单轨仍可用满 5。
    RESEARCH_GLOBAL_SUBAGENT_CAP = max(
        1, int(os.environ.get('RESEARCH_GLOBAL_SUBAGENT_CAP', '9') or '9'))
    RESEARCH_SUBAGENTS_PER_TRACK_MAX = max(
        1, min(8, int(os.environ.get('RESEARCH_SUBAGENTS_PER_TRACK_MAX', '5') or '5')))
    # Total provider-facing model streams, including outer lead calls and nested
    # harness workers. ``0`` derives the safe envelope as global subagents plus
    # concurrently active outer tracks; a positive value is an explicit override.
    RESEARCH_GLOBAL_MODEL_CONCURRENCY = max(
        0, int(os.environ.get('RESEARCH_GLOBAL_MODEL_CONCURRENCY', '0') or '0'))
    # Stable application-level lease DB shared by every concurrently running
    # pipeline. Tool budgets remain per-run; provider admission must not.
    RESEARCH_MODEL_LEASE_DB = (
        os.environ.get('RESEARCH_MODEL_LEASE_DB', '').strip()
        or os.path.join(UPLOAD_FOLDER, 'research_model_leases.sqlite3')
    )
    # 双轨研究：在研究阶段「同时」跑两套调研工作流——Track A = 既有 deep-research 工作流
    # （deep-research skill）产出 research_report.md（广覆盖证据报告，角色不变）；Track B =
    # 新增 actor-ontology 研究工作流（actor-ontology-research skill）产出 actor_dossier.md
    # （以 actor 为中心、面向本体的卷宗：archetype/simulation_tier/role/价值观/信念/激励/资源、
    #  有向且带 valence 的关系、历史演变、情势简报）。随后 Track B 卷宗作为「主」actor 来源喂给
    # 本体生成 + actor 抽取；Track A 报告作为「附加上下文」增强知识图谱/本体/人设上下文/情势上下文。
    # 默认开；关闭（或 Track B 失败/空）时行为与现状逐字节一致（单跑 Track A，不落 actor_dossier.md）。
    # 注意：开启后研究阶段 LLM 成本约翻倍（两套工作流并行），如需省额度可设为 false 关闭。
    DEERFLOW_DUAL_TRACK = os.environ.get('DEERFLOW_DUAL_TRACK', 'True').strip().lower() == 'true'

    # ============================================================
    # EXECPLAN —— 打通「研究 → 图谱 → 模拟 → 报告」结构化契约的旋钮
    # 默认值保持「当前行为」；所有新字段可选降级（缺失即回退旧路径）。
    # ============================================================
    # --- 图谱（Phase 2）---
    # 文本抽取前，把研究确认的 actors + relationships 作为 typed 边种入图谱（T2.2）
    GRAPH_SEED_FROM_ACTORS = os.environ.get('GRAPH_SEED_FROM_ACTORS', 'true').strip().lower() == 'true'
    # episode 并发抽取数（>1 提速，但有轻微 dedup 排序风险；1 = 与旧行为逐字节一致）(T2.5)
    # GRAPH-1：1→4。串行 concurrency=1 是 ~5h 的主瓶颈；5h 内零 429 说明代理容得下并行负载。
    # 必须与 GRAPH_RESOLVE_ENTITIES=true 配对，用 post-build 合并兜住并行建图的 dedup race。
    GRAPH_BUILD_CONCURRENCY = int(os.environ.get('GRAPH_BUILD_CONCURRENCY', '4'))
    # GRAPH-3：graphiti 单 episode 内 per-node/edge 的 LLM 扇出（graphiti 默认 20；此前 effective 8
    # 把 intra-episode 并行压到 ~3-4 波）。16 拓宽扇出，与 concurrency 联合 sizing。runtime.py 经 env 读取，
    # 故模块底部用 os.environ.setdefault 把该默认下发给只读 env 的 runtime（见文件末尾）。
    GRAPHITI_MAX_COROUTINES = int(os.environ.get('GRAPHITI_MAX_COROUTINES', '16') or '16')
    # R2-EXEC-1：graphiti 阻塞式 LLM HTTP I/O 专用线程池大小。没有专用 I/O executor 时，round-1 的
    # 并发旋钮会被共享 cpu+4 默认池（~20）硬封顶；64 ≈ concurrency × coroutines + headroom。
    GRAPH_LLM_EXECUTOR_WORKERS = int(os.environ.get('GRAPH_LLM_EXECUTOR_WORKERS', '64') or '64')
    # R2-EXEC-2：SentenceTransformer encode 的独立小算力池，避免 CPU-bound 编码抢占 LLM I/O 线程
    # 并在 GIL 上串行化。保持小（4），仅隔离编码工作负载。
    EMBED_EXECUTOR_WORKERS = int(os.environ.get('EMBED_EXECUTOR_WORKERS', '4') or '4')
    # R2-EXEC-5 / GAP-2：持久化写穿嵌入缓存（键=(model, normalized_text)），跨 resume/seed 复用。
    # 留空=落在 GRAPHITI_DATA_DIR/embed_cache.sqlite（即文档里的 uploads/graphiti_db/embed_cache.sqlite）。
    EMBED_DISK_CACHE_PATH = (
        os.environ.get('EMBED_DISK_CACHE_PATH', '').strip()
        or os.path.join(GRAPHITI_DATA_DIR, 'embed_cache.sqlite')
    )
    # GRAPH-6：zep_paging 节点读取上限（此前硬编码 2000）。~400-episode 语料的节点数会超过 2000 而被
    # 静默截断，连带影响中心度/分量/dedup/agent 选池。8000 防止该静默截断。
    GRAPH_MAX_NODES = int(os.environ.get('GRAPH_MAX_NODES', '8000') or '8000')
    # 建图末尾跑 Leiden 社区发现（派系/联盟，best-effort）(T2.4 / NEXTSTEPS P3-9)。
    # ⚠️ 默认关：graphiti_core 的 label_propagation（community_operations.py:102 `while True`）在
    # 某些图拓扑上不收敛 → 100% CPU 死循环，且因运行在 graphiti 单一后台事件循环上、是纯同步 CPU 段，
    # 无法被 op-timeout 取消，会拖垮 build 之后的所有读/操作（实测全部 900s 超时、管线在 prepare 失败）。
    # 历次运行社区数恒为 0（本工作负载无价值）。待 graphiti_core 修复 label_propagation 收敛性后再开。
    # 关闭后 GRAPH_COMMUNITY_RETRIEVAL 自动跟随关闭，faction_brief 退回行为日志启发式（既有降级路径）。
    GRAPH_BUILD_COMMUNITIES = os.environ.get('GRAPH_BUILD_COMMUNITIES', 'false').strip().lower() == 'true'
    # NEXTSTEPS P3-7：把建图时算出的度数中心度（此前丢弃）作为影响力先验融入 agent-cap 的
    # salience 排序——高中心度=更枢纽，比原始提及数更接地。默认开；无 graph_priors 时 +0.0（no-op）。
    GRAPH_CENTRALITY_PRIORS = os.environ.get('GRAPH_CENTRALITY_PRIORS', 'true').strip().lower() == 'true'
    # 把已发现的社区(派系)做成一等可检索结构：报告侧 faction_brief 工具 + 人设侧群体身份
    # （EXECPLAN2 I-1-2）。默认跟随 GRAPH_BUILD_COMMUNITIES（无社区节点时 faction_brief 自动
    # 降级到 coalition_map 的行为日志聚类）。显式设 true/false 可覆盖。
    GRAPH_COMMUNITY_RETRIEVAL = (
        os.environ.get('GRAPH_COMMUNITY_RETRIEVAL', '').strip().lower() == 'true'
        if os.environ.get('GRAPH_COMMUNITY_RETRIEVAL', '').strip() != ''
        else GRAPH_BUILD_COMMUNITIES
    )
    # 建图末尾跑一遍实体消解 / 规范别名合并（EXECPLAN2 I-1-4）：把 'OpenAI'/'OpenAI 公司'/
    # '@OpenAI' 等同实体的分裂节点合并到 actors.json 的规范名上。
    # GRAPH-4 / GRAPH-1：默认开——廉价的 embedding+规范名匹配合并（无 LLM），由 0.88 余弦 + 规范名
    # 双重门把关；既是 GRAPH_BUILD_CONCURRENCY 并行建图的 dedup 安全网，又修复碎片化中心度。
    GRAPH_RESOLVE_ENTITIES = os.environ.get('GRAPH_RESOLVE_ENTITIES', 'true').strip().lower() == 'true'
    # 合并所需的最小 embedding 余弦相似度（规范名匹配 + 此阈值 双重门，降低误合并）。
    GRAPH_RESOLVE_SIM_THRESHOLD = float(os.environ.get('GRAPH_RESOLVE_SIM_THRESHOLD', '0.88') or '0.88')
    # 实体消解的 O(N²) 全配对扫描（plan_merges）在节点数很大时会成为纯 Python CPU 墙（实测
    # 大图谱在此步 100% CPU 卡死）。超过此阈值时改走 O(N) 的「精确规范名/别名」快路（plan_merges_fast，
    # 只合并完全同名/同别名的重复节点，跳过昂贵的包含+余弦细化）——仍捕获最高价值的精确重复，绝不卡死。
    # 小图谱（≤ 阈值）仍走完整 plan_merges，与现状逐字节一致。
    GRAPH_RESOLVE_MAX_NODES = int(os.environ.get('GRAPH_RESOLVE_MAX_NODES', '1200') or '1200')
    # 弱连通分量数超过 ratio×节点数时告警（图谱多为孤立单点 = 实体欠合并的特征，KG cookbook 第4步）。
    # KG-8：默认 0.5→0.2。graph_builder 现已按浮点比较（>1 下限保留），0.2 让审计里
    # 132 节点/30 分量的建图真正触发欠合并告警（0.5 时静默放行）。
    GRAPH_COMPONENT_WARN_RATIO = float(os.environ.get('GRAPH_COMPONENT_WARN_RATIO', '0.2') or '0.2')
    # ---（Wave9-KG）图谱收敛：核心 actor 约束 + 建后剪枝 + UI 子图 + 陈旧图谱 GC ---
    # 建后剪枝总开关（graph_pruner.prune_graph）。关闭时 prune_graph 直接返回空审计，
    # 图谱与现状逐字节一致（degrade-safe）。
    GRAPH_PRUNE_ENABLED = os.environ.get('GRAPH_PRUNE_ENABLED', 'true').strip().lower() == 'true'
    # 剪枝后图谱的硬实体上限：核心 actor 恒保留，因此有效上限为
    # max(GRAPH_MAX_ENTITIES, 已匹配核心节点数)。其余只从 N-hop 内按重要度补位。
    GRAPH_MAX_ENTITIES = int(os.environ.get('GRAPH_MAX_ENTITIES', '400'))
    # 以核心 actor（actors.json names+aliases）为起点保留 N 跳邻域；0 = 仅核心。
    GRAPH_CORE_ACTOR_HOPS = int(os.environ.get('GRAPH_CORE_ACTOR_HOPS', '2'))
    # destructive prune 的 actor 行命中率下限；低于阈值整体跳过并标 degraded，防止围绕
    # 少数误命中核心删除其它真正关键 actor。范围由 graph_pruner clamp 到 [0,1]。
    GRAPH_PRUNE_MIN_CORE_COVERAGE = float(
        os.environ.get('GRAPH_PRUNE_MIN_CORE_COVERAGE', '0.8')
    )
    # 已弃用兼容项：硬剪枝不再以度数或任意长连通路径豁免 keep-set 外节点。
    GRAPH_PRUNE_MIN_DEGREE = int(os.environ.get('GRAPH_PRUNE_MIN_DEGREE', '2'))
    # keep-set 内单一实体类型（主标签）的数量上限，防止某一类型（如 Organization）挤占全部席位。
    GRAPH_MAX_ENTITIES_PER_TYPE = int(os.environ.get('GRAPH_MAX_ENTITIES_PER_TYPE', '150'))
    # UI 子图默认节点上限：前端传 top_k<=0 时按此值取度数 top-K（不传 top_k = 全量，行为不变）。
    GRAPH_UI_MAX_NODES = int(os.environ.get('GRAPH_UI_MAX_NODES', '400') or '400')
    # /graph/data 响应的 TTL 缓存秒数（前端 10s 轮询不再每次重分页读库）。0 = 关闭缓存。
    GRAPH_UI_CACHE_TTL_S = float(os.environ.get('GRAPH_UI_CACHE_TTL_S', '60') or '60')
    # 陈旧图谱 GC：除被 uploads/pipelines/*/pipeline_state.json（及项目档案）引用的图谱外，
    # 额外按新旧保留最近 N 个未引用图谱，其余 delete_graph 回收（falkor.db 40 图中 39 个已死）。
    GRAPH_RETAIN_COUNT = int(os.environ.get('GRAPH_RETAIN_COUNT', '5') or '5')
    # 建图完成后服务端预计算弹簧布局（networkx spring_layout，缺 networkx 时退化为
    # 确定性的按度数径向布局），持久化 positions.json 供前端免仿真直出。
    GRAPH_LAYOUT_PRECOMPUTE = os.environ.get('GRAPH_LAYOUT_PRECOMPUTE', 'true').strip().lower() == 'true'
    # episode 抽取失败（模型回显 JSON schema 而非实例）时，episode 级重试次数——
    # 每次重试都会重滚 llm_adapter 的升温阶梯（0.4 档非确定性，重滚真正有效）。
    GRAPH_EPISODE_SCHEMA_RETRIES = int(os.environ.get('GRAPH_EPISODE_SCHEMA_RETRIES', '1') or '1')
    # schema-echo 重试耗尽后，是否用 LLM_FALLBACK_PROVIDER（若已配置）再兜底重抽一次该 episode。
    GRAPH_INGEST_FALLBACK = os.environ.get('GRAPH_INGEST_FALLBACK', 'true').strip().lower() == 'true'
    # W10-COST（cast 相关性 chunk 预过滤）：提交 LLM 抽取前，先按「已种入图谱的 cast
    # （actors.json names+aliases+关系端点，归一化子串匹配）」过滤 chunk——零命中的 chunk
    # 直接跳过、不发任何 LLM 调用，计入 skipped_cast_filter（与 LLM 失败的 skip 原因分开，
    # GRAPH_MAX_SKIPPED_RATIO 告警分母只算实际提交 LLM 的 chunk）。
    # 实测依据（2026-07 forensic audit）：graph 阶段 8h37m 占一次 13h58m run 的 62%；
    # dossier_only 466 chunk 中 278（60%）在烧完整套重试阶梯后才被跳过，抽取膨胀到 823
    # 节点又被实体消解+剪枝砍回 GRAPH_MAX_ENTITIES=400——大部分抽取产出是设计上注定丢弃的。
    # false = 关闭预过滤（旧行为：所有 chunk 全量送抽取）。
    GRAPH_CAST_CHUNK_FILTER = os.environ.get('GRAPH_CAST_CHUNK_FILTER', 'true').strip().lower() == 'true'
    # W10-COST（重试阶梯封顶）：单 chunk 的「完整抽取尝试」总数上限，作用在最外层图侧
    # 阶梯（episode 级 schema 重滚 + 兜底提供方换入 + 并发批的 429 重放合并计数）。
    # 此前最坏叠加：episode 重滚 2 × 兜底 +1 × 批重放 +1，每次完整尝试内部又叠 graphiti
    # tenacity 4 × llm_adapter 升温 2 × llm_client 3——一天 23,496 条 rate-limit/连接错误
    # 日志即由此放大。默认 2：注定失败的 chunk 最多两次完整尝试后立即跳过（schema 类失败
    # 的最后一个名额优先给兜底提供方）。<=0 = 不封顶（旧拓扑）。
    GRAPH_CHUNK_MAX_ATTEMPTS = int(os.environ.get('GRAPH_CHUNK_MAX_ATTEMPTS', '2') or '2')

    # 远程 Graphiti/Zep 才需要分批限流停顿；本地 FalkorDB 关闭死延迟（T2.6）
    GRAPHITI_REMOTE = os.environ.get('GRAPHITI_REMOTE', 'false').strip().lower() == 'true'
    # 每个 Graphiti 操作（add_episode/search/list…）的挂钟上限（秒）。sync→async 桥兜底，
    # 避免某次 LLM/DB 调用卡死时永久阻塞调用它的 Flask 线程。0=不设上限（旧行为）。
    # GRAPH-9：1800→900。fast-tier 路由 + ~5x 更少 episode 让单批远低于 15 分钟；降到 900 让卡死的
    # 读取快速失败而不是干等 30 分钟。
    GRAPHITI_OP_TIMEOUT_S = float(os.environ.get('GRAPHITI_OP_TIMEOUT_S', '900') or '900')

    # --- 模拟（Phase 3）---
    # 智能体数量上限；超过则按 (是否匹配 actor, 影响力, 邻边数) 排序保留，始终保留研究 actor（T3.13）
    OASIS_MAX_AGENTS = int(os.environ.get('OASIS_MAX_AGENTS', '80'))
    # 主角色阵容硬上限（actor-cast discipline）：任何真实预测模拟都应蒸馏到 ≤20 个主角色——
    # 只保留其决策/行动会因果性影响预测结果的 main actors。该上限贯穿全管线：研究抽取
    # （deerflow bridge 按影响力/tier 排序截断 actors.json）、本体生成提示词、以及模拟
    # agent 池（entity 池按主阵容派生，不再向 OASIS_MAX_AGENTS 填充图谱通用节点）。
    # 同时是最大成本杠杆：80→20 个 persona 把画像 LLM 调用与每轮模拟调用都砍 4 倍。
    # 设为 ≥ OASIS_MAX_AGENTS（unset-high）可恢复旧的「填充到 80」行为（degrade-safe）。
    # Hard cap on MAIN actors kept through the pipeline; media/observers are context, not cast.
    ACTOR_CAST_MAX = int(os.environ.get('ACTOR_CAST_MAX', '20') or '20')
    # 媒体/观察者降级：媒体机构、记者、评论员、分析师、智库等「报道/评论方」不是能动 actor
    # ——它们是 context（信息源，tier 3），不应占据主阵容席位或被实例化为模拟 agent。
    # true（默认）时：type=Media / 媒体类 role 的 actor 推断为 simulation_tier=3（显式
    # simulation_tier/archetype 标注仍优先），从而被 agent 准入门（tier 1/2）挡在池外。
    # false 恢复旧行为（media 默认 tier 1 全放行）。Media orgs are demoted to context, never agents.
    ACTOR_EXCLUDE_MEDIA = os.environ.get('ACTOR_EXCLUDE_MEDIA', 'true').strip().lower() == 'true'
    # 主阵容之外的「填充/受众」persona 数（程序化生成的沉默大多数，无逐个 LLM 调研成本）。
    # 默认 0 = agent 池只含主阵容（此前池子会被图谱通用节点填充到 ~80）。兼容旧名
    # SIM_AUDIENCE_SIZE（I-2-2）。Number of filler/audience personas beyond the main cast.
    SIM_AUDIENCE_AGENTS = int(
        os.environ.get('SIM_AUDIENCE_AGENTS', os.environ.get('SIM_AUDIENCE_SIZE', '0') or '0') or '0'
    )
    # 人设活动节律/时区预设：选择 simulation_config_generator 用哪套作息-时区模板。
    # 默认 'china_social' 完整保留当前的北京作息行为（与现状逐字节一致）；
    # 'us_business' / 'global_market' 是另两套预设，由 simulation_config_generator 消费。
    SIM_ACTIVITY_PROFILE = os.environ.get('SIM_ACTIVITY_PROFILE', 'china_social').strip().lower()
    # Foglamp WP1 (1A, I-11/I-12)：模拟 → 观察图谱反馈回路默认【关】。
    # 此前默认开：模拟活动被刻意去掉「模拟」前缀写成普通事实散文（zep_graph_memory_updater
    # .to_episode_text），typed 边与终局采访也写进同一张观察图——下游阶段可把合成叙事当作
    # 观察到的事实检索回来（观察/推断/假设/模拟四类永不静默合流是 I-11 的硬边界）。
    # 在 WP10 的隔离 overlay（run/seed/scenario 作用域）就绪之前，任何生成活动都不得进入
    # 观察图。显式设 true 仅用于特征化 fixture / 一次性隔离图，绝非生产回退。(T3.10→WP1)
    SIM_GRAPH_FEEDBACK = os.environ.get('SIM_GRAPH_FEEDBACK', 'false').strip().lower() == 'true'
    # 反馈除自由文本 episode 外，再写带名实体的 typed 边（A LIKED/REPLIED_TO/FOLLOWED B）
    # (T3.10)。Foglamp WP1 (1A)：同上默认【关】。
    SIM_TYPED_FEEDBACK_EDGES = os.environ.get('SIM_TYPED_FEEDBACK_EDGES', 'false').strip().lower() == 'true'
    # Foglamp WP1 (1A)：终局采访（write_interview_fact，T3.14）单独设门并默认【关】——
    # 采访是模拟产物，写入观察图等同把合成反思当事实。采访仍保留在 run 产物 JSON 里。
    SIM_INTERVIEW_GRAPH_FEEDBACK = os.environ.get(
        'SIM_INTERVIEW_GRAPH_FEEDBACK', 'false').strip().lower() == 'true'
    # 把 *_config 的 recsys 旋钮（recsys_type/refresh_rec_post_count/max_rec_post_len + echo→
    # following_post_count）映射到 oasis Platform；默认关 = 用 DefaultPlatformType（与旧行为一致）(T3.12)
    SIM_WIRE_RECSYS = os.environ.get('SIM_WIRE_RECSYS', 'false').strip().lower() == 'true'
    # 逐智能体动态情感状态（情绪/精力/立场强度/疲劳）按轮更新并注入该轮提示（EXECPLAN2 I-2-1）。
    # NEXTSTEPS P0-4：默认开——无 intra-agent 状态时多轮模拟只是"N 次独立单轮投票重复 T 次"，
    # 缺少升级/从众/疲劳这些让 discourse 真正移动结果的级联动态。关闭则回到每轮静态人设。
    SIM_AGENT_DYNAMICS = os.environ.get('SIM_AGENT_DYNAMICS', 'true').strip().lower() == 'true'
    # 种子内容兜底：事件配置 LLM 有时返回 0 条 initial_posts。此时智能体开局面对空 feed，
    # 只能 FOLLOW（无内容可评论/转发）→ 整场模拟 0 条有机帖/评论（"空转/hollow"，历史上几乎
    # 每次运行的根因）。开启后，当且仅当 LLM 未产出初始帖时，从研究档案合成种子帖（按影响力/
    # tier 取头部角色，各自就一个热点议题陈述其实证立场），让开局 feed 承载真实、对立的观点。
    # 窄触发（只补空缺失的失败态，不改 LLM 已产出帖的正常路径）+ degrade-safe（异常→空，与现状一致）。
    SIM_SYNTH_SEED_POSTS = os.environ.get('SIM_SYNTH_SEED_POSTS', 'true').strip().lower() == 'true'
    SIM_SYNTH_SEED_POSTS_MAX = int(os.environ.get('SIM_SYNTH_SEED_POSTS_MAX', '10') or '10')
    # 世界简报注入：把「预测问题 + 局势简报 + 热点话题」拼成 ≤1400 字的共同世界背景，写入模拟配置
    # world_brief 字段，运行时追加到每个 agent 的 system prompt——agent 知道这个世界在争论什么。
    SIM_WORLD_BRIEF = os.environ.get('SIM_WORLD_BRIEF', 'true').strip().lower() == 'true'
    # SIM-5 世界简报诚实标题：v3 situation_brief 是未逐条标注来源（无 [S#]）的研究综述，旧标题
    # 却称其为「深度研究实证/权威背景」。开启 → 标题改为「研究综述，未逐条标注来源；背景参考，
    # 并非已核实事实」（仅 SimulationConfigGenerator._build_world_brief 这一处 agent 可见的
    # 调用点）。默认开是诚实修正；关闭 → 旧标题逐字节恢复。
    SIM_WORLD_BRIEF_HONEST_LABEL = os.environ.get(
        'SIM_WORLD_BRIEF_HONEST_LABEL', 'true').strip().lower() == 'true'
    # SIM-5 定时事件来源标注（ADR-0002 I-11）：研究时间线事件/情景注入由名字匹配或最高影响力
    # 回退选中的真实行为者发帖，此前被当作该行为者的自发行为（动作统计、议程分层、派系图、立场
    # 轨迹、决策名册、回应阶段的「X wrote:」与 ResponseLog）。开启 → feed 帖带
    # [WORLD EVENT …]/[SCENARIO ASSUMPTION …] 前缀、日志行带 event_provenance，上述消费端全部
    # 剔除或改标注入内容。默认开是诚实修正（注入内容从不冒充行为者）；关闭 → 旧行为逐字节恢复
    # （同帖者同轮事件合并、缺发帖者静默丢弃这两处 bug 修复不受开关影响）。
    SIM_EVENT_PROVENANCE = os.environ.get('SIM_EVENT_PROVENANCE', 'true').strip().lower() == 'true'
    # 人格设计（实证语境工程）：对有档案的真实主体（政府/企业/机构），在画像 LLM 调用中要求产出
    # 结构化 persona_design（identity/views_beliefs/incentives/objectives/relations/red_lines/
    # decision_style/rhetoric），严格接地于研究档案、禁止发明立场；多样性来自真实主体的真实差异。
    SIM_PERSONA_DESIGN = os.environ.get('SIM_PERSONA_DESIGN', 'true').strip().lower() == 'true'
    # ITEM 11 市场先验注入（SIM_MARKET_PRIORS）：把本次运行 handoff/prediction_markets.json 里
    # relevance-gated 的市场隐含概率（Yes 价）灌进模拟侧——(1) 世界底稿 world_brief 追加一段
    # 「市场定价」块（top 5 相关市场：question + 隐含 P），让全体 Agent 知道priced beliefs 并据此
    # 争论；(2) 对「分析师/媒体」类人设追加一行市场感知提示（其关注话题与市场问题词重叠时）。
    # 文件缺失/解析失败 / 无对应 handoff → 与今日行为逐字节一致（degrade-safe）。默认开。
    SIM_MARKET_PRIORS = os.environ.get('SIM_MARKET_PRIORS', 'true').strip().lower() == 'true'
    # Polymarket 预测市场（官方公开 Gamma API，keyless）：研究阶段拉取与题目相关的活跃市场，
    # 把市场隐含概率（Yes 价）作为校准锚注入研究报告 + 报告章节 + 二元预测抽取（预测 vs 市场
    # 分歧 >10pt 须解释）。无需 API key；网络失败 → 静默跳过（degrade-safe），不影响主流程。
    PREDICTION_MARKETS_ENABLED = os.environ.get('PREDICTION_MARKETS_ENABLED', 'true').strip().lower() == 'true'
    # 市场快照上限（按成交量降序取头部）。新名 PREDICTION_MARKETS_MAX；旧名 ODDPOOL_MAX_MARKETS 仍读作兜底以平滑迁移。
    PREDICTION_MARKETS_MAX = int(os.environ.get('PREDICTION_MARKETS_MAX',
                                                os.environ.get('ODDPOOL_MAX_MARKETS', '20')) or '20')
    # 成交量噪声下限（USDC）：低于此量的市场价格是噪声，不配当锚点。
    PREDICTION_MARKETS_MIN_VOLUME = float(os.environ.get('PREDICTION_MARKETS_MIN_VOLUME', '200') or '200')
    # 每个事件最多取几条市场：防止一个多结局事件的子市场阶梯（如「N 次降息」0~12）霸占全部名额，
    # 保证快照的事件多样性。<=0 视为不限制。
    PREDICTION_MARKETS_MAX_PER_EVENT = int(os.environ.get('PREDICTION_MARKETS_MAX_PER_EVENT', '3') or '3')
    # 每个检索词最多取几个匹配事件（Gamma public-search 的 limit_per_type，8→15）：检索词已被
    # LLM/启发式收敛到题目相关，放宽召回不放噪声——快照仍受 MAX/MIN_VOLUME/MAX_PER_EVENT 收口。
    PREDICTION_MARKETS_PER_QUERY = int(os.environ.get('PREDICTION_MARKETS_PER_QUERY', '15') or '15')
    # 相关性门槛（0~10）：调用方提供 llm_call 时对快照批量打相关性分，低于此分的市场剔除、
    # 其余按 (relevance_score, volume) 重排——错误锚点比没有锚点更糟。未打分/打分失败 →
    # 保持 volume 排序（与今天一致，degrade-safe）。
    PREDICTION_MARKETS_MIN_RELEVANCE = float(os.environ.get('PREDICTION_MARKETS_MIN_RELEVANCE', '5') or '5')
    # PM-3：报告阶段对研究期落盘的市场快照做实时重报价（handoff-PLUS-refresh）——保留研究期价
    # price_at_research 与当下价，算 Δ 呈现「研究→现在」的价格移动，并在二元预测抽取前再重报价一次
    # 使 market_anchor 用现价。关闭 → 只用研究期快照（在包头标注时效性）。重报价失败一律 degrade-safe：
    # 保留研究期价 + 时效性说明，绝不阻断报告（PolymarketClient.requote_markets 每行自带失败标记）。
    PREDICTION_MARKETS_REQUOTE = os.environ.get('PREDICTION_MARKETS_REQUOTE', 'true').strip().lower() == 'true'
    # TIME-3 endDate hygiene: a market past its endDate can stay open at a near-settled price
    # while it awaits UMA resolution. With the gate on, such a market never anchors a binary
    # forecast and never seeds SIM priors (world brief / persona hints); it still appears in
    # the market pack and research section, labelled "window ended ... awaiting settlement",
    # because its price remains evidence. Default on (honesty fix); false restores the exact
    # pre-gate prompts, anchors, snapshot and market-pack bytes. The research child receives
    # both knobs from Config.
    PREDICTION_MARKETS_END_DATE_GATE = os.environ.get('PREDICTION_MARKETS_END_DATE_GATE', 'true').strip().lower() == 'true'
    # Hours after endDate before a market counts as ended (absorbs Gamma endDate quirks on
    # extended events); clamped to [0, 168] where it is used. 0 = strictly after endDate.
    PREDICTION_MARKETS_END_DATE_GRACE_HOURS = float(os.environ.get('PREDICTION_MARKETS_END_DATE_GRACE_HOURS', '0') or '0')
    # PM-HZ（WAVE9）：预测市场远期降级阶梯——主检索词零命中/全被相关性门挡时，按「剥 4 位年份 →
    # 事件级宽词（前 3 词）」两级放宽重试。降级候选必须过 LLM 相关性门（fail-closed：打分不可用
    # 即整阶段丢弃），命中行打 horizon_degraded 标签留痕。同时研究阶段**始终**落盘
    # prediction_markets.json（空结果带显式 no_relevant_markets 标记），让下游能陈述「无市场锚点」。
    # bridge 侧经环境变量读取（编排器 env=dict(os.environ) 原样透传）。
    PREDICTION_MARKETS_HORIZON_RETRY = os.environ.get('PREDICTION_MARKETS_HORIZON_RETRY', 'true').strip().lower() == 'true'
    # WAVE9-RQ（研究卷宗质量；bridge 经环境变量读取，同上透传）：
    # RQ1 禁流程叙事——所有合成/分节提示词注入硬风格规则（禁 passes/working notes/tracks/
    # coverage gates/字数目标/[citation:...] 语法/自指编辑注记出现在卷宗散文里）。
    RESEARCH_BAN_PROCESS_NARRATION = os.environ.get('RESEARCH_BAN_PROCESS_NARRATION', 'true').strip().lower() == 'true'
    # RQ2 内联引注——研究阶段定义 [S<n>] 记号 + 机器可解析 '## References' 节；合成路径钉一个
    # 与 sources.json fetched 主干同序的 SOURCE INDEX，落盘前确定性校验（悬空记号剔除并计数）。
    RESEARCH_INLINE_CITATIONS = os.environ.get('RESEARCH_INLINE_CITATIONS', 'true').strip().lower() == 'true'
    # 钉进合成提示词的引注索引条数上限（防提示词膨胀）。
    RESEARCH_CITATION_INDEX_MAX = int(os.environ.get('RESEARCH_CITATION_INDEX_MAX', '100') or '100')
    # RQ3 跨节去重——多段合成缝合步跑归一化 12-gram shingle 检测，剔除跨节逐字重复段（保首现）。
    RESEARCH_DEDUP_SHINGLES = os.environ.get('RESEARCH_DEDUP_SHINGLES', 'true').strip().lower() == 'true'
    # RQ4 强制研究图表——卷宗最少图表数（actor 网络/时间线/定量 Top 指标；0=关闭强制图表与
    # 确定性渲染步，write-step 提示词回退旧 OPTIONAL 措辞）。渲染经 forecast-visuals 技能捆绑的
    # scripts/render.py（plotly 本地、degrade-safe），PNG 内嵌进 research_report.md 的 Visual Annex。
    RESEARCH_CHARTS_MIN = int(os.environ.get('RESEARCH_CHARTS_MIN', '3') or '3')
    # 图表渲染子进程超时（秒）与解释器显式覆盖（缺省自动探测 backend/.venv → sys.executable）。
    RESEARCH_CHARTS_TIMEOUT = int(os.environ.get('RESEARCH_CHARTS_TIMEOUT', '180') or '180')
    RESEARCH_CHARTS_PYTHON = os.environ.get('RESEARCH_CHARTS_PYTHON', '').strip()
    # B2 三部结构：按 Bridgewater 简报把成稿组织为 Part 1（二元预测表）/ Part 2（框架综合，
    # 单次 LLM 调用、字数按 requirement_spec 的 page_budget 收敛）/ Part 3（附录 = 原详细章节）。
    # 无 Part 1 或综合产出过短 → 跳过不改文档（degrade-safe，幂等）。
    REPORT_THREE_PART_SKELETON = os.environ.get('REPORT_THREE_PART_SKELETON', 'true').strip().lower() == 'true'
    # 情感状态更新的学习率/速率常数（有界 clamp，保守取值；仅 SIM_AGENT_DYNAMICS=true 时生效）。
    SIM_DYNAMICS_MOOD_LR = float(os.environ.get('SIM_DYNAMICS_MOOD_LR', '0.25') or '0.25')
    SIM_DYNAMICS_OPINION_LR = float(os.environ.get('SIM_DYNAMICS_OPINION_LR', '0.15') or '0.15')
    SIM_DYNAMICS_FATIGUE_RATE = float(os.environ.get('SIM_DYNAMICS_FATIGUE_RATE', '0.20') or '0.20')
    SIM_DYNAMICS_FATIGUE_DECAY = float(os.environ.get('SIM_DYNAMICS_FATIGUE_DECAY', '0.10') or '0.10')
    # NEXTSTEPS P1-1（决策/承诺通道 + 演化 WorldState）：让 agent 不只发帖，而是每轮就 forecast
    # 情景做一次结构化"承诺"，按资源/影响力加权演化一个由 base_rates 初始化的**结果世界态**，把
    # 模拟从"度量声量"变为"度量结果"。默认关（每个活跃 agent 每轮多一次结构化 LLM 调用，成本可观；
    # 关闭则与现状逐字节一致：只有声量份额 final_stance_share）。落 decisions.jsonl + world_state_trajectory.json。
    # R2-SIM-1 / R2-CAL-3：默认开——硬前提：没有它脊柱只看到活动量、零建模结果。成本由
    # OASIS_DEFAULT_MAX_ROUNDS 封顶 + SIM_CONVERGENCE_STOP 早停 + 并行 elicitation 约束。
    SIM_DECISION_CHANNEL = os.environ.get('SIM_DECISION_CHANNEL', 'true').strip().lower() == 'true'
    # SIM-8 (P23 follow-on): the decision-channel elicitor, the call that steps WorldState,
    # sees the period's scheduled research-timeline events (with SIM_PERIOD_CONTEXT_V2 also
    # events carried out of rounds no elicitation saw: SIM-6 dead rounds, in-band rounds
    # with an empty roster, post-hoc rounds without actions, labelled as earlier periods)
    # as a labelled exogenous block before the roster, capped at 800 characters on whole
    # lines: in-band every calendar round with events, and in the post-hoc calendar
    # fallback. Default on: zero extra LLM calls, the block carries no WorldState number
    # and asks for no direction, and the channel stays diagnostic_only; the post-hoc cache
    # key gains an events digest only for rounds that have events. false = prompts and
    # cache keys byte-identical to before.
    SIM_DECISION_EVENTS = os.environ.get('SIM_DECISION_EVENTS', 'true').strip().lower() == 'true'
    # SIM-2 (C26): bind every decision-channel reply to the round roster before it can move
    # WorldState — canonical roster ids, unknown ids and duplicate rows dropped, magnitude and
    # confidence finite and clamped to [0,1], a missing magnitude rejected instead of becoming
    # 1.0 — and record reason-coded counts per round plus a run-level fallback_share. Default
    # on: an honesty check that fails closed with zero extra LLM calls and unchanged prompt
    # text (only rosters above 17 rows get a larger max_tokens). false restores the legacy
    # parse loop and trajectories byte for byte.
    DECISION_CHANNEL_VALIDATION = os.environ.get(
        'DECISION_CHANNEL_VALIDATION', 'true').strip().lower() == 'true'
    # SIM-2: a run whose share of roster slots without an accepted or abstained answer exceeds
    # this is at best 'inconclusive' (fallback_share_exceeded, forecast_effect=no_update).
    # Uncalibrated: 0.5 is a conservative majority-of-slots floor; log live rates before tightening.
    # Must be a share in [0,1]: the verdict replaces NaN/out-of-range values (e.g. 50 meant as a
    # percent) with 0.5 and logs a warning, so a typo cannot silently disable the gate.
    DECISION_CHANNEL_FALLBACK_MAX_SHARE = float(
        os.environ.get('DECISION_CHANNEL_FALLBACK_MAX_SHARE', '0.5') or '0.5')
    # SIM-2 (defines the SIM-5 cap knob): per-round individual-actor cap before the tail
    # collapses into one public block. Previously a ghost knob read via getattr by both
    # decision-channel producers; 60 is the default they already used, so defining it here
    # changes nothing. An explicit run_decision_channel(max_active_per_round=...) still wins.
    DECISION_CHANNEL_MAX_ACTIVE = int(os.environ.get('DECISION_CHANNEL_MAX_ACTIVE', '60') or '60')
    # Foglamp WP1 (1D, I-16/I-18)：模拟对已发布概率的影响政策（run-pinned）。
    #   diagnostic_only —— 默认。模拟/WorldState 产出只进「显式标注模拟来源」的分析散文，
    #                      不进 derive_forecast_spine() 的概率生成输入，不调整任何概率。
    #   no_update       —— 连诊断散文也不注入（最保守）。
    #   validated_update —— 仅当 WP6/12/14 交付 outcome-blind 前瞻晋升（immutable
    #                      PromotionDecision）后才可用；当前一律回落 diagnostic_only。
    #   legacy_prompt   —— 仅供特征化 fixture 复现旧行为（模拟数字直接喂概率生成），
    #                      绝非生产回退；运行期使用会被显式告警。
    SIMULATION_FORECAST_EFFECT = (
        os.environ.get('SIMULATION_FORECAST_EFFECT', 'diagnostic_only').strip().lower()
        if os.environ.get('SIMULATION_FORECAST_EFFECT', 'diagnostic_only').strip().lower()
        in ('diagnostic_only', 'no_update', 'validated_update', 'legacy_prompt')
        else 'diagnostic_only'
    )
    # SIM-4（C30）：零 LLM 的决策通道先验回声诊断（services/sim_prior_echo.py，策略
    # drf-sim-control/v1）：终局份额与种子先验几乎一致（prior_echo）或承诺扎堆先验领先情景
    # （prior_leader_herd）时，编排器在 decision_channel_summary.prior_echo 记录并告警，报告
    # 世界态块追加一行不含数字的定性提示。纯诊断：不动任何概率、不影响运行健康门，其余裁定
    # 下报告逐字节不变，故默认开；false = 不计算、不记录、不加提示。
    SIM_PRIOR_ECHO_DIAGNOSTIC = os.environ.get('SIM_PRIOR_ECHO_DIAGNOSTIC', 'true').strip().lower() == 'true'
    # SIM-1：报告世界态块/世界态图表/fork 情景对比表遵从决策通道的显式非 valid 裁定
    # （world_state_trajectory.json 顶层 validity 存在且 != valid）——隐藏结果份额与演化
    # 航点、跳过图表（trajectory_not_valid）、对比表返回 None。默认开：诚实检查 fail-closed，
    # 非 valid 分布本就 forecast_effect=no_update；valid 轨迹与无 validity 的旧轨迹逐字节不变。
    # false → 回到旧行为（仍渲染份额，仅附 ⚠️ 警示行）。
    REPORT_WORLDSTATE_HIDE_INVALID = os.environ.get(
        'REPORT_WORLDSTATE_HIDE_INVALID', 'true').strip().lower() == 'true'
    SIM_DECISION_INERTIA = float(os.environ.get('SIM_DECISION_INERTIA', '0.7') or '0.7')  # 先验每轮持久度
    # NEXTSTEPS P1-4：收敛/均衡检测——按 WorldState 的逐轮变化 EWMA 早停（区别于按声量），
    # 把"收敛于 R 轮（稳定）" vs "未收敛（低信心）"本身作为校准信号。需 P1-1 的世界态（现已默认开）。
    # SIM-1：默认开——观点动力学通常 10-25 轮settle，72→~20 是 ~3-4x 更少 sim 调用；收敛-at-R 成为校准信号。
    SIM_CONVERGENCE_STOP = os.environ.get('SIM_CONVERGENCE_STOP', 'true').strip().lower() == 'true'
    SIM_CONVERGENCE_EPS = float(os.environ.get('SIM_CONVERGENCE_EPS', '0.02') or '0.02')
    SIM_CONVERGENCE_WINDOW = int(os.environ.get('SIM_CONVERGENCE_WINDOW', '3') or '3')
    # 模拟中断后从上次完成的轮次继续（而非从第 0 轮重启），依赖 OASIS DB 持久性（EXECPLAN2 I-4-2）。
    # 默认关 = 全量重启（与现状一致）。
    SIM_RESUME_FROM_ROUND = os.environ.get('SIM_RESUME_FROM_ROUND', 'false').strip().lower() == 'true'

    # —— 本体契约：实体分类 / 显著度排序 / valenced 关系（CLAUDE/CODEX/GEMINI 三方收敛）——
    # 智能体池按 is_agent_eligible() 收敛：仅 archetype actor/collective（simulation_tier 1/2）入池，
    # 记者/媒体/抽象概念（tier 3/4）不再被当作仿真智能体。默认开；当没有实体携带 archetype/
    # simulation_tier 时自动 no-op（保留全部，与现状一致）。
    SIM_TIER_ELIGIBILITY = os.environ.get('SIM_TIER_ELIGIBILITY', 'True').strip().lower() == 'true'
    # 智能体上限裁剪改按 salience_score() 排序（而非纯邻边度数）。默认开；salience 缺失时回退到
    # 现状的 (是否匹配 actor, 影响力, 邻边数) 排序元组（与现状一致）。
    SIM_SALIENCE_RANKING = os.environ.get('SIM_SALIENCE_RANKING', 'True').strip().lower() == 'true'
    # 关注图 + 情感用关系 valence/polarity（盟友≠对手≠交易方）。默认开；仅对新增关系类型生效，
    # 既有 8 类 legacy 关系行为与现状逐字节一致。
    SIM_VALENCED_RELATIONS = os.environ.get('SIM_VALENCED_RELATIONS', 'True').strip().lower() == 'true'

    # --- 报告（Phase 4）---
    # 每节最少/对话模式最多工具调用（与 REPORT_AGENT_MAX_TOOL_CALLS 配套；T4.4 接入硬编码值）
    REPORT_AGENT_MIN_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MIN_TOOL_CALLS', '4'))
    REPORT_AGENT_MAX_TOOL_CALLS_CHAT = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS_CHAT', '2'))
    # 用原生 tool calling 取代脆弱的 regex ReAct（T4.5）。
    # REPORT-4：默认开——消除 conflict/contamination 的纠正往返与 contamination-adoption 失败模式；
    # 每章遇异常自动 per-section 回退到 ReAct（degrade-safe）。
    REPORT_NATIVE_TOOLS = os.environ.get('REPORT_NATIVE_TOOLS', 'true').strip().lower() == 'true'
    # INFRA-5：报告工具调用边界（默认开）。ReAct / chat 的 <tool_call> 改为宽容解析：块内多个对象取首个、
    # 缺右括号补齐、tool/params/arguments/args/input 键名归一、与 name 并列的扁平参数上提进 parameters、
    # 字符串化的 parameters 解码；仍无法解析的块不再静默丢弃，而是回给模型一条纠正性 Observation。
    # 派发前校验必填参数 / as_of / limit，被拒调用不计入工具预算（超出 REPORT_TOOL_MAX_REJECTED_PER_SECTION
    # 后才计）。原生路径 arguments 解析失败或参数无效时以 role=tool 'ERROR: …' 回包、不执行不计费，并按模型
    # 原文回填 assistant.tool_calls。默认开是安全的：格式良好、参数齐全的调用解析与派发不变，只影响此前被丢弃
    # 或以空参数白跑的调用；false 恢复旧的严格正则解析与不校验直接派发（原生路径对未知工具名的 fail-closed
    # 拒绝与 agent_log 的 tool_unknown 行不受此开关控制）。
    REPORT_TOOL_ARG_REPAIR = os.environ.get('REPORT_TOOL_ARG_REPAIR', 'true').strip().lower() == 'true'
    # INFRA-5：每章可免费（不计工具预算）被拒的工具调用次数；超出后被拒调用照常计入预算，防止模型在无效
    # 调用上无限空转。仅在 REPORT_TOOL_ARG_REPAIR 开启时生效（关闭时没有参数类拒绝）；未知工具名的拒绝
    # （ReAct 与原生路径）从不计费，也不占此额度。计费的被拒调用只占上限预算，不算入每章工具调用下限。
    REPORT_TOOL_MAX_REJECTED_PER_SECTION = int(os.environ.get('REPORT_TOOL_MAX_REJECTED_PER_SECTION', '6') or '6')
    # INFRA-5：原生工具循环迭代用尽、被迫无工具收尾时，把已检索到的工具结果（首尾截取到
    # REPORT_NATIVE_FINAL_EVIDENCE_CHARS 字符）附进收尾提示，而非丢弃全部证据凭空成文。默认开是安全的：
    # 只改变迭代用尽后的兜底回合；false 恢复旧的「仅原始提示」收尾。
    REPORT_NATIVE_FINAL_WITH_EVIDENCE = os.environ.get('REPORT_NATIVE_FINAL_WITH_EVIDENCE', 'true').strip().lower() == 'true'
    REPORT_NATIVE_FINAL_EVIDENCE_CHARS = int(os.environ.get('REPORT_NATIVE_FINAL_EVIDENCE_CHARS', '12000') or '12000')
    # 并发生成报告章节（EXECPLAN2 I-6-3）：>1 时正文章节走线程池并行，摘要/结论章节最后串行
    # （依赖正文全文）。章节级 LLM 并发受 OASIS 信号量同源约束。
    # REPORT-1：1→3。正文章节相互独立，并行 ~2.5-3.5x 加速；正文段自动走 brief 上下文避免 O(N²) token。
    # PAR-3：3→6——正文章节彼此独立、并发受 OASIS 信号量同源约束封顶，进一步抬高并发上限压缩
    # 报告阶段 wall-clock；实际并发始终 min(此值, 正文章节数)，故对短报告无副作用。
    # 串行成本实测（COST-2 审计）：12 章节串行 ≈ 24.6 分钟 / 216 次 LLM 调用——默认必须 >1。
    REPORT_SECTION_CONCURRENCY = int(os.environ.get('REPORT_SECTION_CONCURRENCY', '6') or '6')
    # 章节上下文模式（I-6-3）：full = 每章注入此前所有章节全文；brief = 注入大纲+各章 1-2 句摘要
    # （去除 O(N²) 上下文膨胀）。并发模式下正文章节强制用 brief（并行时拿不到彼此全文）。
    # REPORT-2：默认 brief——大致砍半报告输入 token；尾/摘要章节仍拿全文，执行摘要不受影响。
    REPORT_SECTION_CONTEXT_MODE = os.environ.get('REPORT_SECTION_CONTEXT_MODE', 'brief').strip().lower()

    # --- DeerFlow 模型 / Key / 预算 单一真源（T6.4 / T6.6）---
    # antigravity = vibeproxy 本地 OpenAI 兼容代理（config.yaml 的 antigravity stanza，
    # 用占位 key sk-dummy，无需环境变量 Key，故不入 DEERFLOW_KEY_ENV）。
    SUPPORTED_DEERFLOW_MODELS = ('claude', 'codex', 'minimax', 'deepseek', 'qwen', 'glm', 'kimi', 'antigravity')
    # 模型 → 所需 Key 环境变量（claude/codex 用本机订阅，无需 Key；antigravity 用本地代理占位 key）
    DEERFLOW_KEY_ENV = {
        'minimax': 'MINIMAX_API_KEY', 'deepseek': 'DEEPSEEK_API_KEY',
        'qwen': 'DASHSCOPE_API_KEY', 'glm': 'ZHIPUAI_API_KEY', 'kimi': 'KIMI_API_KEY',
    }
    # 研究深度 → 超时预算（秒）；DEERFLOW_RESEARCH_TIMEOUT 为显式覆盖（优先级最高）(T6.6)
    # CONF-1：standard 2400→7200、deep 10800→21600——旧预算下 deep 的多轮协议经常被看门狗
    # 无差别 SIGKILL 在综合阶段之前。原始 dict 保留为兼容契约；内部读者应走 deerflow_depth_budget()。
    DEERFLOW_DEPTH_BUDGETS = {'quick': 900, 'standard': 7200, 'deep': 21600}
    # deep 开场 pass 的递归上限（旧版在 bridge 内直接读 os.environ；提升为 Config 属性）(T6.6)
    # CONF-1：220→400——扇出/双轨默认开后开场 pass 的工具调用数近乎翻倍，220 会提前截断 scope。
    DEERFLOW_DEEP_OPENING_RECURSION_LIMIT = int(os.environ.get('DEERFLOW_DEEP_OPENING_RECURSION_LIMIT', '400'))

    @classmethod
    def deerflow_depth_budget(cls, depth) -> int:
        """研究深度 → 生效超时预算（秒），带并行模式自动放大（CONF-1）。

        DEERFLOW_DUAL_TRACK / DEERFLOW_SUBAGENTS / RESEARCH_DEEP_FANOUT 任一开启时，
        研究阶段的工作量近乎翻倍（双轨两套工作流 / 子代理扇出），固定档位预算会把
        更深的跑法无差别 SIGKILL——故生效预算 ×1.5。原始 DEERFLOW_DEPTH_BUDGETS dict
        保持不变（兼容契约）；显式 timeout 参数 / 用户 .env 里的 DEERFLOW_RESEARCH_TIMEOUT
        仍由调用方优先（本方法只负责档位默认值）。degrade-safe：任何异常回退到未放大的
        原始档位值。
        """
        raw = cls.DEERFLOW_DEPTH_BUDGETS.get(
            str(depth or '').strip().lower(), cls.DEERFLOW_RESEARCH_TIMEOUT)
        try:
            if (getattr(cls, 'DEERFLOW_DUAL_TRACK', False)
                    or getattr(cls, 'DEERFLOW_SUBAGENTS', False)
                    or getattr(cls, 'RESEARCH_DEEP_FANOUT', False)):
                return int(raw * 1.5)
            return int(raw)
        except (TypeError, ValueError):  # noqa: BLE001 — 预算计算绝不阻塞研究启动
            return raw

    # 统一管线产物目录
    PIPELINE_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/pipelines')

    # .env.example 里的占位符：保留占位符等同于未配置（否则首跑要等研究阶段
    # 烧完几十分钟额度后才在建图阶段发现 Zep 401）。
    _PLACEHOLDER_VALUES = {
        'your_zep_api_key_here', 'your_zep_api_key', 'your_api_key',
        'your_api_key_here', 'changeme', 'xxx', '...',
    }

    @classmethod
    def _is_placeholder(cls, value) -> bool:
        return bool(value) and str(value).strip().lower() in cls._PLACEHOLDER_VALUES

    # INFRA-14: strict config validation.  On (default), the errors of config_issues()
    # (a non-canonical boolean such as X=1, a blank or malformed number, an enum / range /
    # coupled-pair violation, a malformed LLM_COST_PER_MTOK) refuse pipeline admission:
    # preflight_pipeline lists them and PipelineOrchestrator.start raises
    # ConfigurationError.  The server still starts (run.py prints every issue as a WARN
    # line).  false downgrades them to warnings.  A clean environment has no issue, so
    # the default changes nothing.  Parsed fail-closed like APP_HOST_CHECK: only an
    # explicit false/0/no/off turns it off, so an ambiguous value cannot disable the audit.
    CONFIG_STRICT_VALIDATION = os.environ.get('CONFIG_STRICT_VALIDATION', 'true').strip().lower() not in (
        'false', '0', 'no', 'off')

    @classmethod
    def config_issues(cls) -> list:
        """INFRA-14: the config audit's issues (config_audit.Issue: level, knob, message).

        The import-time numeric sanitisation issues plus audit_env over the current
        os.environ (apply_provider writes land there too).  With
        CONFIG_STRICT_VALIDATION off every error is returned as a warning.
        """
        issues = list(CONFIG_IMPORT_ISSUES) + audit_env(os.environ, CONFIG_KNOBS)
        if not cls.CONFIG_STRICT_VALIDATION:
            issues = [issue._replace(level=WARNING) for issue in issues]
        return issues

    @classmethod
    def config_errors(cls) -> list:
        """INFRA-14: the messages of the config_issues() that refuse a run (none when not strict)."""
        return [issue.message for issue in cls.config_issues() if issue.level == ERROR]

    @classmethod
    def validate(cls, *, include_audit: bool = True):
        """验证必要配置

        INFRA-14: include_audit (default) appends config_errors(); run.py passes False,
        so its startup exit gate is unchanged and the audit only refuses pipeline runs.
        """
        errors = []

        if cls.LLM_PROVIDER not in cls.SUPPORTED_LLM_PROVIDERS:
            errors.append(
                f"LLM_PROVIDER 必须是 {', '.join(cls.SUPPORTED_LLM_PROVIDERS)} 之一，"
                f"当前为 '{cls.LLM_PROVIDER}'"
            )

        # 需要 Key 的提供方（needs_key=True）必须配置 LLM_API_KEY；CLI/订阅提供方使用本机订阅
        if cls.PROVIDER_META.get(cls.LLM_PROVIDER, {}).get('needs_key') and not cls.LLM_API_KEY:
            errors.append(f"LLM_PROVIDER={cls.LLM_PROVIDER} 时必须配置 LLM_API_KEY")

        # INFRA-6: 非法的 LLM_FALLBACK_REASONING_EFFORT 以前只在每次回退调用时抛 ValueError
        # （每次都记错误日志，且不进确定性冷却），回退形同虚设。改为启动期报错（run.py 退出 1）：
        # 即便当前未配置 LLM_FALLBACK_PROVIDER，拼错的值也会阻止启动——这是有意的。
        from .utils.provider_overrides import FALLBACK_REASONING_EFFORTS
        _fb_effort = (os.environ.get('LLM_FALLBACK_REASONING_EFFORT', '') or '').strip()
        if _fb_effort and _fb_effort.lower() not in FALLBACK_REASONING_EFFORTS:
            errors.append(
                f"LLM_FALLBACK_REASONING_EFFORT 必须是 {'/'.join(FALLBACK_REASONING_EFFORTS)} 之一"
                f"（或留空），当前为 '{_fb_effort}'"
            )

        # 知识图谱已迁移到本地 Graphiti——不再需要 ZEP_API_KEY。
        # 仅校验 GRAPH_BACKEND 取值合法；嵌入式后端无需任何外部服务或 Key。
        _valid_backends = ('auto', 'falkordblite', 'falkordb', 'kuzu')
        if cls.GRAPH_BACKEND not in _valid_backends:
            errors.append(
                f"GRAPH_BACKEND 必须是 {', '.join(_valid_backends)} 之一，当前为 '{cls.GRAPH_BACKEND}'"
            )

        # T6.4: 校验 DEERFLOW_MODEL —— 未知模型直接报错（启动期暴露拼写错误，而非 40 分钟后）；
        # 缺失对应 Key 仅告警（claude/codex 用本机订阅无需 Key；缺 Key 会在 POST /run 的 preflight 拦截）。
        _df_model = (cls.DEERFLOW_MODEL or 'claude').strip().lower()
        if _df_model not in cls.SUPPORTED_DEERFLOW_MODELS:
            errors.append(
                f"DEERFLOW_MODEL 必须是 {', '.join(cls.SUPPORTED_DEERFLOW_MODELS)} 之一，当前为 '{cls.DEERFLOW_MODEL}'"
            )
        else:
            _key_env = cls.DEERFLOW_KEY_ENV.get(_df_model)
            if _key_env and not os.environ.get(_key_env, '').strip():
                import logging
                logging.getLogger('mirofish.config').warning(
                    "DEERFLOW_MODEL=%s 需要环境变量 %s，当前未设置（研究阶段将失败）。", _df_model, _key_env
                )

        # EXECPLAN2 I-8-4: OASIS 并发上限纳入集中式校验。<1 会让 get_oasis_semaphore
        # 返回 0/负值（信号量直接死锁），故启动期硬性拦截，而非运行时悬挂。
        for _sem_name in ('OASIS_CLI_SEMAPHORE', 'OASIS_SEMAPHORE'):
            _sem_val = getattr(cls, _sem_name, None)
            if not isinstance(_sem_val, int) or _sem_val < 1:
                errors.append(f"{_sem_name} 必须是 >=1 的整数，当前为 '{_sem_val}'")
        if include_audit:
            errors.extend(cls.config_errors())
        return errors

    @classmethod
    def validation_warnings(cls) -> list:
        """INFRA-8: model settings that silently do nothing (warnings only, never refuse a run).

        - LLM_FALLBACK_MODEL set while LLM_FALLBACK_PROVIDER is empty: failover is off, so the
          fallback model is never used.
        - LLM_FAST_MODEL / LLM_STRONG_MODEL set for a CLI primary (claude-cli / codex-cli) to a
          model other than LLM_MODEL_NAME: the CLI transport never receives a tier model
          (claude-cli is given --model from LLM_MODEL_NAME, and only for a claude id/alias;
          codex-cli never), so every call runs LLM_MODEL_NAME's effective model or the CLI
          account's default ('cli-default'), whatever the tier model names.

        run.py prints them at startup; scripts/preflight.py lists them as WARN rows.
        """
        from .utils.model_provenance import CLI_DEFAULT_LABEL, effective_model_label
        warnings = []
        fb_model = (os.environ.get('LLM_FALLBACK_MODEL', '') or '').strip()
        fb_provider = (os.environ.get('LLM_FALLBACK_PROVIDER', '') or '').strip()
        if fb_model and not fb_provider:
            warnings.append(
                f"LLM_FALLBACK_MODEL={fb_model} is set but LLM_FALLBACK_PROVIDER is empty: "
                "failover is off and the fallback model is never used"
            )
        provider = (cls.LLM_PROVIDER or '').strip().lower()
        if provider in ('claude-cli', 'codex-cli'):
            runs = effective_model_label(provider, cls.LLM_MODEL_NAME)
            runs_text = ("the CLI account's default model" if runs == CLI_DEFAULT_LABEL
                         else f"{runs} (from LLM_MODEL_NAME)")
            for name in ('LLM_FAST_MODEL', 'LLM_STRONG_MODEL'):
                value = getattr(cls, name, None)
                if value and value.strip() != (cls.LLM_MODEL_NAME or '').strip():
                    warnings.append(
                        f"{name}={value} is set for LLM_PROVIDER={provider} but is ignored: the "
                        f"CLI is never given a tier model, so every call runs {runs_text}"
                    )
        return warnings


# ------------------------------------------------------------------
# DeerFlow 子进程兼容：deer-flow/config.yaml 在加载时会“贪婪地”解析所有模型 stanza 里的
# $VAR（api_key），任意一个未设置的环境变量都会让整份 config 解析直接抛错——从而连带
# 拖垮当前实际选用的研究模型（如 claude）。因此为所有提供方专属 Key 环境变量预置空默认值
# （仅在未设置时），保证未配置的提供方 stanza 也能被安全解析；真正选用某提供方时，
# apply_provider 会把真实 Key 写入对应变量。子进程通过 env=dict(os.environ) 继承这些值。
for _meta in Config.PROVIDER_META.values():
    _ke = _meta.get('key_env')
    if _ke:
        os.environ.setdefault(_ke, '')

# GRAPH-3：runtime.py 在 services/graphiti_client/runtime.py 里直接 os.environ.get(
# "GRAPHITI_MAX_COROUTINES", "8") 读取该旋钮（绕过 Config 类属性）。把上面 Config 解析出的默认值
# 下发到进程环境（仅在 .env / 环境未显式设置时填充），让 16 的文档化默认真正在 runtime 生效，
# 同时尊重用户显式覆盖（setdefault 不会覆盖既有值）。
os.environ.setdefault('GRAPHITI_MAX_COROUTINES', str(Config.GRAPHITI_MAX_COROUTINES))
