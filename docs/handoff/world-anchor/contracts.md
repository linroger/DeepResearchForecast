# World Anchor v1: owner interface and closed contracts

**Date:** 2026-10-29. **Status:** Pure/offline slice complete and independently closed: 114 non-private checks and two same-source private stdin checks pass. Parent whole-feature integration and operational acceptance remain separate. The interface now has fifteen public functions, including explicit receipt attachment. Integration and installed-consumer checks remain coordinator/consumer ownership. Active checkout is `/Users/rogerlin/.codex/worktrees/world-anchor/DeepResearchForecast`, branch `codex/world-anchor`, based on delivered spending commits `c2736d36` and `9916b3be`. The approved [plan](PLANS.md) and producer/consumer maps remain authoritative. Ownership remains only `deerflow_bridge/world_anchor.py`, `backend/tests/test_world_anchor.py` and this file.

**Ownership:** The contract owner owns the implemented stdlib-only `deerflow_bridge/world_anchor.py` and dedicated tests. No application imports, provider transport, runtime/compiler implementation, quota store, or import-time I/O belongs in that module. Binder owns prompts, transport and pre-seal integration; consumers own runtime semantics. This document is this owner's working record; coordinator-owned handoffs and other owners' files are unchanged.

MUST, SHOULD and MAY have their RFC 2119 meanings. All shapes below are closed: every listed field is required, `?T` means an explicitly nullable field, lists may be empty unless stated otherwise, and undeclared keys are errors. Unannotated identifiers/text fields are strings; `ID` is an identifier and `JSONPointer` is RFC 6901 text. Counts are nonnegative strict integers. Tagged unions permit exactly the fields of their selected alternative. Python functions use snake_case; this new wire format also uses snake_case. Existing case and world-spec fields retain their native casing at adapters.

## 1. Public Python interface

The capitalized types below denote validated ordinary JSON dictionaries, except `EvidenceIndex` and `ProducerReceipts`, opaque read-only handles issued by `index_snapshot` and `producer_receipts`. The handles retain verified artifact bytes privately; `EvidenceIndex.snapshot()` returns a fresh normalized inventory, and both handles provide `artifact_bytes(artifact_id)` for bounded producer access; its JSON shape in section 4 describes its inventory view, not a deserialization constructor. A caller cannot supply a JSON dictionary and have it treated as an authenticated index. Functions return fresh values and do not modify inputs. `index_snapshot`, `producer_receipts`, `read_pack`, and `emit_pack` are the only filesystem operations; all others are pure. A downstream caller must retain the externally pinned manifest/contract/policy hashes: a hash supplied by the same untrusted artifact does not authenticate it. A replay creates a fresh authenticated index from the pinned snapshot; one producer invocation may reuse its immutable handle.

```python
class AnchorError(ValueError):
    code: str            # one of the E_* codes in section 10
    path: str            # JSON Pointer or artifact ID; no absolute private path
    requirement_id: str | None

def requirements_from_contract(
    contract: Contract | None, *, scope: Scope,
) -> Requirements: ...

def index_snapshot(
    root: Path, manifest: InputManifest, *,
    expected_manifest_hash: str, expected_scope: Scope,
    requirements: Requirements, policy: Policy,
) -> EvidenceIndex: ...

def admit_reviewed_evidence(
    index: EvidenceIndex, proposal: EvidenceProposal,
    review: SemanticReviewReceipt, *, requirements: Requirements, policy: Policy,
    receipts: ProducerReceipts,
) -> EvidenceIndex: ...

def producer_receipts(
    root: Path, manifest: ProducerManifest, *,
    expected_manifest_hash: str, expected_scope: Scope,
) -> ProducerReceipts: ...

def attach_producer_receipts(
    index: EvidenceIndex, *, receipts: list[ProducerReceipts] | tuple[ProducerReceipts, ...],
) -> EvidenceIndex: ...

def availability_from_receipts(
    source: Source, *, index: EvidenceIndex, cutoff: str,
) -> Availability: ...

def candidates_for_requirements(
    requirements: Requirements, index: EvidenceIndex,
) -> CandidateSet: ...

def admit_bindings(
    requirements: Requirements, index: EvidenceIndex,
    candidates: CandidateSet, proposal: BindingProposal, *,
    policy: Policy, attempts: list[ResolutionAttempt], metering: Metering,
) -> AnchorPack: ...

def validate_pack(
    pack: AnchorPack, *, requirements: Requirements,
    index: EvidenceIndex, policy: Policy,
) -> AnchorPack: ...

def anchor_hash(value: JSONValue) -> str: ...

def emit_pack(
    directory: Path, pack: AnchorPack, *, requirements: Requirements,
    index: EvidenceIndex, policy: Policy,
) -> EmissionReceipt: ...

def read_pack(
    directory: Path, receipt: EmissionReceipt, *, expected_receipt_hash: str,
    expected_pack_hash: str, requirements: Requirements,
    index: EvidenceIndex, policy: Policy,
) -> AnchorPack: ...

def engine_projection(
    pack: AnchorPack, *, requirements: Requirements,
    index: EvidenceIndex, policy: Policy, engine: Engine,
) -> EngineProjection: ...

def actor_projection(
    pack: AnchorPack, *, requirements: Requirements,
    index: EvidenceIndex, policy: Policy, actor_ref: str, at: str,
) -> ActorProjection: ...

def prepare_world_parameters(
    pack: AnchorPack, requests: list[ParameterRequest], *,
    expected_pack_hash: str, requirements: Requirements,
    index: EvidenceIndex, policy: Policy,
) -> PreparedParameters: ...
```

There is no generic `load_any`, arbitrary expression evaluator, arbitrary target-field writer, or implicit environment read. Each admission/projection validates its scope/hash links. `validate_pack` reconstructs candidates, admission decisions, section projections and readiness from the retained proposal and authenticated inputs; it rejects a pack with caller-edited decisions or values. Transport/metering receipts are hash-bound producer evidence, not something the pure module can independently prove was incurred.

`requirements_from_contract(None, ...)` returns an empty requirement registry with a blocking `missing_contract` gap. It does not search numeric rows for a target. Invalid supplied contracts raise; absent contracts produce evidence of absence. `engine_projection` and `prepare_world_parameters` raise `E_NOT_READY` for blocking requirements of that engine. Research emission still succeeds for a structurally valid gap pack.

## 2. Primitive, identity and resource rules

`Engine = oasis-legacy | world-v1 | target-first-v1`. `Hash` is 64 lowercase SHA256 hex characters. An upstream ID is a nonempty string of at most 128 characters; generated IDs are `<prefix>_<64 hex>`. IDs never derive from display labels alone. An absolute source URL is metadata, never an instruction to fetch.

`JSONValue` admits only dictionaries with string keys, lists, strings, true/false, null, integers and finite floats. Reject duplicate JSON keys, NaN/infinities, boolean-as-number, invalid UTF-8, lone surrogates, cycles, unbounded integer/exponent tokens and unknown keys. All quantities use `DecimalText`, a canonical finite decimal string: plain base-10, no exponent, no leading plus/zeros, no trailing fractional zeros, negative zero normalized to `"0"`, at most 38 significant digits and 18 fractional digits. `Value = {kind: number, value: DecimalText} | {kind: range, low: DecimalText, high: DecimalText} | {kind: boolean, value: bool} | {kind: text, value: str}`. Range low MUST be <= high. Unknown is null, never zero or an empty range.

`Period = {start: YYYY-MM-DD, end: YYYY-MM-DD, granularity: day|month|quarter|year|interval}`; dates are inclusive and valid, start <= end. Calendar year 2026 is `2026-01-01` through `2026-12-31`. Periods are not vintages. `Instant` is a canonical UTC timestamp `YYYY-MM-DDTHH:MM:SSZ`. `Time = {value: ?Instant, precision: second|day|unknown, basis_ref_ids: [ID]}`. Day precision is conservatively the end of that UTC day for cutoff admission; it does not imply knowledge earlier that day. Unknown has null value and no positive availability inference. No wall-clock defaults.

Canonical bytes are UTF-8 `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)` without a newline, after domain validation and quantity normalization. Do not normalize retained source strings or quotes. Lists with set semantics sort by ID; ordered mechanism inputs, source rows, span sequences and time-series points retain defined order. Hashes cover these exact bytes; file hashes cover raw file bytes. No self-hash field appears in its own digest.

Stable IDs use `prefix + "_" + sha256(canonical_bytes([domain_version, identity_parts]))`. Identity parts are: source = scope + track + ledger artifact ID + JSON pointer; evidence = source ID + content hash + locator; claim = scope + artifact ID + raw artifact hash + row pointer; requirement = pre-binding contract hash + origin pointer + kind + scoped identity + consumer; observation = claim ID + typed tuple + support references; binding = requirement ID + selected observation IDs + assumption ID; gap = requirement ID/null + code + sorted related IDs. Identical S107 labels in different tracks therefore cannot collide. A new generation changes scope-sensitive IDs; reordering a proposed candidate list does not change an admitted binding.

Initial fixed limits (`world-anchor-limits/v1`, not environment configurable): 8 MiB per structured artifact/proposal/pack, 16 MiB per retained page, 512 MiB aggregate bytes read, depth 32, 256 KiB per ordinary string, 8 KiB per quote, 4,096 artifacts, 4,096 sources, 20,000 inventory rows, 1,024 requirements, 512 mechanisms, 512 actors, 64 references per row, six selected candidates per requirement and twelve requirements per binder request. Aggregate budget is checked before and during reading. An over-limit artifact fails with `E_LIMIT`; no silent inventory truncation. A bounded candidate list is explicit selection, not truncation of the inventory. The provider ceilings remain 20 physical model attempts, 150,000 retained input/output token envelopes and eight physical catalog attempts across the stage; filesystem limits do not authorize calls.

Safe paths are relative POSIX paths, <=512 characters, with no absolute/drive form, backslash, NUL, empty/`.`/`..` component. Every component below an explicitly trusted root must be non-symlink; files must be regular files, with no FIFO/device/socket reads. Use descriptor-relative/no-follow reads and validate the same opened bytes for size/hash and parsing; a resolve-then-open containment check alone is insufficient. No caller chooses an output filename other than the four fixed names in section 9.

## 3. Frozen scope, contract and requirements

```text
Scope = {run_id, research_generation_id, snapshot_id, authority,
         cutoff: Instant, horizon: Period}
authority = legacy-kiq-v1 | target-first-v1

Identity = {entity_id, metric_id, denominator_id: ?ID, geography_id: ?ID,
            unit: Unit, reference_period: Period}
Unit = {id, dimension, scale: DecimalText, currency: ?str,
        price_basis: nominal|real|not_applicable|unknown,
        base_period: ?Period}

Contract = {schema_version: world-anchor-contract/v1, scope: Scope,
            authority_artifact_id, authority_artifact_hash,
            authority_pointer, authority_kind: admitted_contract|reviewed_fixture|research_inventory,
            settlement: ?{target_node_id, identity: Identity,
                         authority_artifact_id, pointer},
            aliases: [Alias], terms: [RequirementSpec], mechanisms: [MechanismSpec],
            identities: [IdentitySpec], actors: [ActorSpec],
            calendar: [CalendarSpec], hazards: [HazardSpec],
            indicators: [IndicatorSpec], reference_classes: [ReferenceClassSpec]}

RequirementSpec = {origin_pointer, kind, identity: ?Identity,
                   actor_ref: ?ID, value_type: number|range|boolean|text,
                   accepted_value_kinds: [ValueKind],
                   accepted_evidence: [page|official_row|typed_claim|contract],
                   priority: 0|1|2, required: bool, consumers: [Consumer],
                   dependency_origins: [JSONPointer],
                   assumption_policy_id: ?ID, cardinality?: one|many}
Requirement = RequirementSpec + {requirement_id, dependency_ids: [ID]}
kind = baseline|target_definition|mechanism_parameter|identity|actor_statement|
       actor_authority|actor_plan|red_line|event|hazard|indicator|reference_class
Consumer = {engine: Engine, role: initial_state|mechanism|observation|calendar|
            actor_brief|diagnostic|compiler_parameter|research_note, object_id, field}
Alias = {field: entity|metric|denominator|geography|unit,
         canonical_id, literal, artifact_id, artifact_hash: Hash, pointer}
ValueKind = observed|reported|third_party_forecast|analyst_inferred|assumed|simulated

Requirements = {schema_version: world-anchor-requirements/v1, scope: Scope,
                contract_hash: ?Hash, contract: ?Contract,
                requirements: [Requirement], gaps: [Gap]}
```

The binder/producer constructs `Contract` by copying explicit admitted contract/case identities and selected templates, with pointers to the frozen authority artifact. For target-first, freeze the pre-binding planning contract projection, excluding assessments, binary probabilities and scenario weights; do not hash the future final case into this contract. A later outer seal pairs the final case hash with the anchor hash. For legacy input lacking identity/settlement, provide a reviewed fixture contract with its actual review receipt or pass null. Neither a KIQ question nor a metric slug is a settlement contract. The authority artifact/pointer resolves to the producer-normalized authority object `{settlement: Identity, terms: [RequirementSpec]}` plus any declared section lists/aliases. Its terms, settlement and section lists must exactly match the Contract projection. The producer owns normalization from the admitted native contract/case and retains its upstream seal; numeric rows cannot create this authority. The private fixture uses the same explicit shape.

`requirements_from_contract` copies terms, assigns deterministic IDs, resolves dependency origins and checks duplicate origins, cycles, target identity and the declared consumers. A non-null contract has exactly one `target_definition` term for its settlement target and at least one consumer on every term. It does not add default numeric values, assumed parameters, event dates, targets, or probability requirements. A target definition may be bound by its admitted contract reference; it does not require observing a future target value. Each executable primitive/parameter must have an explicit requirement. Named consumers are claims of intended wiring, not proof of runtime execution.

Policy is separately frozen, never granted by a binder reply:

```text
Policy = {schema_version: world-anchor-policy/v1,
          admission_version: explicit-support/v1,
          limits_version: world-anchor-limits/v1,
          selection_version: exact-identity-lexical/v1,
          prior_rules: [PriorRule], conversions: [Conversion],
          review_profile: ReviewProfile, consumer_rules: [ConsumerRule]}
ConsumerRule = {engine: Engine, adapter_version, role, object_id, field,
                template_versions: [str]}
PriorRule = {policy_id, artifact_id, artifact_hash, pointer,
             requirement_origins: [JSONPointer], value: Value,
             identity: Identity, rationale, library_version}
Conversion = {conversion_id, from_unit: Unit, to_unit: Unit,
              factor: DecimalText, offset: DecimalText,
              artifact_id, artifact_hash, pointer}
ReviewProfile = {profile_id, extraction_prompt_version, review_prompt_version,
                 qualification_artifact_id, qualification_artifact_hash: Hash}
```

The producer owns a bounded extraction call and a distinct qualified review call; the model emits neither transport receipts nor its own approval envelope. The frozen review profile identifies qualified prompts and source-review behavior. No manual per-run review is required. V1 conversions remain exact affine unit/scale conversions with matching dimension, currency, price basis and period; no implicit FX, deflation, annualization or forecast-to-actual conversion. Prior rules cannot supply missing target identity, settlement, actor authority or source provenance. An explicitly allowed proxy baseline stays an assumption with its source estimate preserved.

## 4. Input manifest and authenticated index

```text
InputManifest = {schema_version: world-anchor-input/v1, scope: Scope,
                 parent_manifest_hash: ?Hash, artifacts: [Artifact],
                 tracks: [Track], crosswalk: [Crosswalk],
                 omissions: [InputOmission]}
Artifact = {artifact_id, track_id: ?ID, path, sha256: Hash, bytes: int,
            encoding: utf8_json|utf8_text|binary, role}
role = contract|policy|review|legacy_kiq|legacy_quantitative|legacy_timeline|
       legacy_sources|source_ledger|page|actor_bundle|official_manifest|
       official_series|official_csv|capture_metadata|target_plan|target_case|target_checkpoint|target_findings|
       target_bindings|target_state|target_evidence|metering_receipt|retained_input
Track = {track_id, adapter: legacy-kiq/v1|target-case/v1,
         ledger_artifact_id, kiq_artifact_ids: [ID],
         quantitative_artifact_id: ?ID, timeline_artifact_id: ?ID,
         actor_artifact_id: ?ID, case_artifact_id: ?ID,
         supporting_artifact_ids: [ID]}
Crosswalk = {crosswalk_id, source_key, namespace: ledger_sid|report_position|
             url_source_id|target_source_id|official_dataset,
             external_id, track_id, artifact_id, pointer, proof_ref_ids: [ID]}
InputOmission = {artifact_id: ?ID, track_id: ?ID, pointer: ?JSONPointer,
                reason: not_retained|unsupported_shape|producer_truncated,
                declared_count: ?int}

EvidenceIndex = {schema_version: world-anchor-index/v1, scope: Scope,
                 input_hash: Hash, requirements_hash: Hash, policy_hash: Hash,
                 evidence_hash: Hash, evidence_proposals: [EvidenceProposal],
                 review_receipts: [SemanticReviewReceipt], producer_manifest_hashes: [Hash],
                 manifest: InputManifest,
                 sources: [Source], references: [EvidenceRef],
                 inventory: [InventoryRow], observations: [Observation],
                 gaps: [Gap]}
Source = {source_key, track_id, ledger_artifact_id, ledger_pointer,
          local_source_id, url: ?str, title: ?str,
          content_artifact_id: ?ID, content_hash: ?Hash,
          retention: fetched_page|snippet_only|official_row|missing,
          tier: primary|secondary|social|unknown,
          published_at: Time, available_at: Time, retrieved_at: Time,
          retained_at: Time, capture: Capture, audience: Audience}
Capture = {kind: content|error_page|unknown, retained_bytes_complete: bool,
           remote_document_complete: ?bool, ends_mid_table: bool}
InventoryRow = {claim_id, artifact_id, pointer, raw_hash: Hash,
                origin: kiq_fact|legacy_quant|legacy_timeline|actor_item|
                        case_node|case_claim|case_parameter|official_observation,
                kiq_id: ?ID, fact_index: ?int, upstream_claim_id: ?ID,
                source_keys: [ID], ref_ids: [ID], observation_ids: [ID],
                disposition: indexed|unsupported|missing_provenance,
                reason_code: ?GapCode}
```

Every retained row has exactly one inventory entry, including unsupported rows and extraction rows that lost `source_ref`. Legacy KIQ facts are located by artifact hash plus `/facts/<index>` and retain `kiq`, `sids`, `tag`, `verified_numbers`; none of those flags authenticates a fact. The adapter inventories legacy `quantitative.json` as extracted rows and target-first `quantitative.json` as case nodes only when its admitted track adapter says so; filename/shape guessing is forbidden. Target case claims require checkpoint/findings/state authentication and retained page evidence, not just the supplemental `target_evidence.json`. The legacy actor wrapper is unwrapped only through its documented producer shape; an unknown wrapper is inventoried as unsupported, not treated as an empty dossier.

Ledger SIDs are scoped to their track. Crosswalk links must resolve both endpoints and explicit producer associations; matching URLs or display citations may nominate a link but cannot prove it. Ambiguous report positions/URL IDs produce `ambiguous_source`. A fetched page named in a ledger must match the manifest file hash and ledger content hash. A source whose page was never retained yields `missing_page`; a manifest-required file that is now absent raises `E_FILE_MISSING`. A copied page's new copy time is not `retrieved_at`.

Official series admission uses the full JSON metadata/observation flags and complete official-generation manifest, not CSV/latest-row projections or the loader that silently omits invalid rows. Required manifest members reconcile exactly. No official datasets is an honest empty inventory. Neither search snippets nor synthesized reports admit quantitative state in v1; they can identify a candidate or gap.

```text
EvidenceRef = {ref_id, source_key, run_id, research_generation_id, snapshot_id,
               track_id, claim_id: ?ID, kiq_id: ?ID, fact_index: ?int,
               artifact_id, content_hash: Hash, locator: Locator}
Locator = {kind: text_span, start_byte: int, end_byte: int, quote: str}
        | {kind: json_value, pointer: JSONPointer, value_hash: Hash}
Support = {field: entity|metric|denominator|geography|unit|reference_period|
                   value|value_kind|published_at|available_at|effective_at|visible_at|
                   vintage|cadence|producer_class|audience|actor_basis|authority,
           ref_id, selector: Locator, expected: str}

Audience = {kind: public|actors|analyst, actor_refs: [ID]}
Observation = {observation_id, claim_id, identity: ?Identity, value: Value,
               value_kind: ValueKind,
               producer_class: ProducerClass,
               subject_actor_ref: ?ID, owner_actor_ref: ?ID,
               audience: Audience, actor_basis: none|self_statement|
                 mandate|public_record,
               ref_ids: [ID], support: [Support],
               support_rule: typed_source/v1|reviewed/v1,
               review_id: ?ID, conversion_id: ?ID, source_value: Value,
               published_at: Time, available_at: Time, known_by: Time,
               retrieved_at: Time,
               effective_at: Time, visible_at: Time, vintage: Time,
               cadence: Cadence, supersedes_observation_id: ?ID}
Cadence = {kind: catalogued|source_stated|inferred|unknown,
           interval_days: ?DecimalText, release_lag_days: ?DecimalText,
           uncertainty_days: ?DecimalText, ref_ids: [ID]}
ProducerClass = official_observation|primary_statement|secondary_report|
                external_forecast|research_analyst|model_prior|simulation
```

`text_span` offsets are zero-based UTF-8 byte offsets, end-exclusive, in the exact artifact bytes. Both endpoints must be code-point boundaries and `quote == bytes[start_byte:end_byte].decode("utf-8")`; no newline/Unicode/whitespace normalization is allowed. A support selector must lie within its reference span or its explicitly referenced JSON subtree. JSON selectors use RFC 6901 and exact raw decoded values; hashes use canonical bytes. Tables need an authenticated row plus explicit header references from the same artifact; ambiguous merged cells remain a gap. No concatenating words/numbers across sources to manufacture one claim. Per-reference hashes and membership are checked individually; one valid citation cannot bless another invalid citation in the same row.

`Audience.actors` requires nonempty sorted actor refs, while public/analyst require an empty list. Producer class, epistemic/value kind, subject, owner and audience are independent. A public research-analyst claim about an actor is still analyst inference and is not actor-known. A third-party forecast may be public knowledge as a forecast, never as observed state. `actor_basis` itself requires supporting references; the binder cannot grant it. Numeric observations require non-null identity. Qualitative actor/authority/event statements may have null identity when their requirement does too; they must still identify the subject, exact statement and supported temporal/authority classification. This exception does not admit a numeric field without identity.

## 5. Two minimal API refinements for freeze

### A. Producer extraction plus independent semantic review

`admit_reviewed_evidence` returns a new immutable index; it does not call a model or mutate its input. `index_snapshot` authenticates and inventories retained rows; the current slice routes numeric admissions through a qualified receipt, including typed rows. It does not claim an additional automatic official-series semantic adapter. The binder's extraction call can propose typed tuples and exact source references from that prose. A separate qualified review invocation checks the explicit association against retained source bytes and the requirement. It may use the same qualified model in a separate request; it cannot reuse the extractor's completion or approve itself. The reviewer receives the source context, tuple and requirements, not the extractor's persuasive rationale. Both physical calls, repairs and their token envelopes consume the same retained 20-attempt/150,000-token stage allowance. Existing transport/budget ownership is unchanged.

```text
EvidenceProposal = {schema_version: world-anchor-evidence-proposal/v1,
                    input_hash: Hash, requirements_hash: Hash,
                    extraction_attempt_id, references: [EvidenceRef],
                    rows: [EvidenceExtraction]}
EvidenceExtraction = Observation minus {observation_id, support_rule, review_id, known_by}
                     plus {proposal_id, requirement_ids: [ID]}
SemanticReviewReceipt = {schema_version: world-anchor-semantic-review/v1,
                        review_id, input_hash: Hash, requirements_hash: Hash,
                        proposal_hash: Hash, policy_hash: Hash,
                        profile_id, review_prompt_version,
                        extraction_attempt_id, review_attempt_id,
                        transport_receipt_artifact_id, transport_receipt_hash: Hash,
                        raw_response_artifact_id, raw_response_hash: Hash,
                        decisions: [ReviewDecision]}
ReviewDecision = {proposal_id, verdict: explicit_support|ambiguous|unsupported,
                  checks: [{field: Support.field,
                            verdict: explicit_support|ambiguous|unsupported,
                            ref_ids: [ID]}]}
```

The `minus/plus` definition is exact closed field inheritance, not an open object. Proposed temporal/audience fields remain assertions to check. The producer constructs and pins the receipt envelope from the actual registered transport invocation; only `decisions` come from the reviewer. Invocation identities must differ, match the approved profile and raw request/response receipts, and join the same durable budget scope. The receipt is not authenticated merely by containing its own hash. In offline replay the caller supplies the externally pinned producer receipts; a scripted fixture is labeled offline and establishes no live model qualification.

Deterministic admission checks scope, proposal/response hashes, per-reference source membership/content hash/byte span, declared conversions, exact tuple matching, distinct qualified invocations and complete per-field review results. Each numeric proposal needs explicit-support results for entity, metric, denominator, geography, unit, period, value and value kind; null denominator/geography mean explicitly inapplicable, not unknown. Subject/audience/actor basis and temporal classifications need their applicable checks too. Duplicate, foreign or omitted review results cannot pass. Numeric tokens/conversions must independently match retained values. Conflicting/ambiguous associations stay gaps; no average, fabricated correction or silent confidence threshold. A positive review establishes a bounded judgment of explicit textual support, not general truth or guaranteed natural-language entailment.

Typed source selectors remain exact evidence inputs to the same admission boundary. Free prose no longer needs a fabricated `entity=...` grammar or a manually prepared review. The later binding proposal may be assembled deterministically from admitted extraction rows; a third model call merely to select IDs is not required. `semantic_review.json` in the private specimen supplies quoted spans and interpretation candidates only: it is **not** a qualified independent review receipt and cannot automatically approve evidence.

The returned index retains proposals/receipts and computes `evidence_hash = anchor_hash({input_hash, requirements_hash, policy_hash, proposal_hashes, review_receipt_hashes})`, with sorted proposal/review hashes. The legacy `producer_manifest_hashes` slot inside that semantic digest is fixed to an empty list; the actual producer inventory is independently sealed in the index/pack and completion manifest. Attaching accounting proof or replaying identical semantic files from an equivalent authenticated bundle cannot change evidence/candidate identity. Candidate sets and the final pack pin this digest; replay reconstructs it from pinned source and producer artifacts. Reviews are producer outputs sealed with the pack, not inserted into the pre-extraction source manifest or its hash. `validate_pack` must re-admit retained proposals/receipts using the pinned producer receipts before comparing decisions.

### Authenticated producer receipts (frozen correction)

```text
ProducerManifest = {schema_version: world-anchor-producer-receipts/v1,
                    scope: Scope, policy_hash: Hash, files: [ProducerArtifact],
                    transport_artifact_ids: [ID]}
ProducerArtifact = {artifact_id, path, sha256: Hash, bytes: int,
                    role: raw_response|transport_receipt|metering_receipt}
TransportReceipt = {schema_version: world-anchor-transport/v1, attempt_id,
                    role: extraction|semantic_review, mode: offline_scripted|metered,
                    anchor_budget_scope_id: ?ID, profile_id, prompt_version,
                    input_hash: Hash, requirements_hash: Hash, proposal_hash: ?Hash,
                    request_hash: Hash, response_artifact_id, response_hash: Hash,
                    physical_attempts: 0|1, reserved_tokens: int, outcome: completed}
MeteringReceipt = {schema_version: world-anchor-metering/v1, anchor_budget_scope_id,
                   physical_model_attempts: int, reserved_tokens: int,
                   physical_catalog_attempts: int, physical_followup_attempts?: int}
```

The producer manifest contains raw response and transport files, **not** the review envelope. Optional metering receipts live here too, avoiding a source-input hash cycle. `producer_receipts` verifies safe files against an externally pinned manifest hash. Raw extraction response parses to exactly `{references, rows}`; raw review response parses to exactly `{decisions}`. Their hashes cover actual file bytes, including whitespace. Review envelope fields must match these authenticated files and transport identities; envelope-supplied hashes alone confer no authority. Both invocations must use the pinned profile/prompts, input/requirement hashes and the same budget scope. Scripted receipts have zero attempts/tokens and explicitly establish no live model qualification. Metered receipts retain one attempt and the admitted token envelope. Every envelope is counted once by attempt ID across retained producer handles, and collisions fail.

`admit_reviewed_evidence(..., receipts=handle)` stores this authentication in the immutable returned index. `validate_pack` and `read_pack` retain their `index=` signatures: replay first reconstructs that index from source pins and the retained producer manifests, then re-admits the saved extraction/review envelopes through the authenticated handles. Never bootstrap the handle from hashes read only from the untrusted pack. Completion seals pin source-input manifest hash, all producer manifest hashes, policy, final pack and final case independently. No receipt contains its own digest.

### B. Availability as a supported known-by upper bound

```text
Availability = {published_at: Time, available_at: Time, known_by: Time,
                cutoff_status: known_by_cutoff|after_cutoff|unknown|conflict,
                basis: published|available|retrieved|retained|unknown,
                ref_ids: [ID]}
```

`availability_from_receipts` computes the earliest supported upper bound for this exact content version from admitted publication/availability evidence or a trusted original fetch/retention receipt bound to its source URL/content hash. A trusted receipt at or before cutoff establishes `known_by <= cutoff`; it does **not** manufacture `published_at` or assert that first availability equaled retrieval time. A later retrieval/copy cannot establish historical availability; independent earlier version-bound evidence is still usable. A bare model date, filesystem mtime or the new specimen-copy timestamp is not a trusted original receipt. Contradictory version/timestamp evidence returns `conflict`, not the most convenient date. Day precision uses the conservative end of that day. Unknown publication remains unknown. All evidence admission uses this result instead of requiring a known publication date.

Known-by admission is about researcher evidence availability; actor audience/visibility still passes its separate gate. An error-page capture authenticates those error bytes, not substantive evidence. A partial retained page may support a complete local passage, but cannot establish remote completeness or missing table rows. Future announcements can be known before their effective date; future observation values cannot become known facts from a scheduled release. Missing cadence remains unknown. Same-period forecast revisions remain revisions, never cross-period growth history.

## 6. Candidates, binder reply and admission result

```text
CandidateSet = {schema_version: world-anchor-candidates/v1,
                requirements_hash: Hash, input_hash: Hash,
                evidence_hash: Hash, selection_version: exact-identity-lexical/v1,
                rows: [CandidateRow]}
CandidateRow = {requirement_id, ranked: [Candidate],
                excluded_counts: [ExclusionCount]}
Candidate = {candidate_id, claim_id, observation_id: ?ID,
             ref_ids: [ID], rank: int,
             match: exact|alias|lexical, gap_codes: [GapCode]}
ExclusionCount = {reason: incompatible_identity|incompatible_unit|
                  incompatible_period|unavailable|unproven|candidate_limit|unrelated,
                  count: int}

BindingProposal = {schema_version: world-anchor-proposal/v1,
                   requirements_hash: Hash, input_hash: Hash,
                   candidate_hash: Hash, rows: [ProposalRow]}
ProposalRow = {requirement_id, decision: bind|conflict|gap|assume,
               candidate_ids: [ID], prior_policy_id: ?ID,
               note: str}

Binding = {binding_id, requirement_id, status: bound|conflict|gap|contested,
           observation_ids: [ID], assumption: ?Assumption,
           contract_ref: ?ContractRef,
           rejected: [{candidate_id, code: GapCode}], gap_ids: [ID]}
ContractRef = {artifact_id, artifact_hash: Hash, pointer,
               contract_hash: Hash}
Assumption = {policy_id, value: Value, identity: Identity,
              value_kind: assumed, basis_artifact_id, basis_hash: Hash,
              rationale, replaces_observation_ids: [ID]}
Gap = {gap_id, requirement_id: ?ID, code: GapCode,
       related_ids: [ID], blocking_engines: [Engine], detail: str}
ResolutionAttempt = {attempt_id, requirement_ids: [ID],
                     kind: captured_official|catalog|followup|prior,
                     outcome: matched|no_match|denied|failed|unknown|not_attempted,
                     receipt_artifact_id: ?ID, receipt_hash: ?Hash,
                     code: ?GapCode}
```

Ranking is deterministic: exact typed identity before admitted alias before lexical nomination, then supported before unproven, then observation ID/claim ID ascending. It is not a truth/confidence score. Each requirement has <=6 ranked entries; excluded counts are computed over the full inventory with one reason per excluded row in the listed reason order. The deterministic selection rule and complete inventory reproduce the exact excluded IDs without an inventory-times-requirements duplication in the pack. No embeddings/provider calls. `observation_id=null` candidates are useful discovery gaps, never admissible facts. Binder rows may choose only IDs from this exact candidate set. The binder supplies no new values, refs, aliases, timestamps, producer classes, audience permissions, authority or assumptions. Admission checks the full matching observation inventory for conflicts even when some rows were outside the six-candidate shortlist.

One row per proposed requirement; duplicates/foreign IDs/schema/hash mismatch reject the whole reply (`E_PROPOSAL`). Omitted requirements become explicit `unproposed` gaps, except `target_definition`, which admission binds directly to the authenticated settlement contract using `contract_ref` and no observation/assumption. Binder rows for `target_definition` are rejected: target identity is not model-selectable. A bound requirement has exactly one basis category: observation IDs, assumption, or contract_ref. For `bind`, admission independently checks all matching supported observations for unresolved conflicts, not only the chosen row; a model cannot hide a disagreement by selecting one source. A wrong support/period/unit candidate becomes a typed rejection and gap; it never receives a repaired invented citation. `assume` needs a matching pre-authorized prior rule; its binding remains explicitly assumed through `assumption`, never observed. `conflict` retains all valid alternatives. Missing required dependencies propagate blocking gaps transitively. A model's note is private diagnostic text only and is never projected to actors/reports.

## 7. Closed pack and section descriptors

```text
AnchorPack = {schema_version: world-anchor/v1, scope: Scope,
              contract_hash: ?Hash, input_hash: Hash,
              requirements_hash: Hash, policy_hash: Hash, evidence_hash: Hash,
              evidence_proposals: [EvidenceProposal], review_receipts: [SemanticReviewReceipt],
              producer_manifest_hashes: [Hash],
              requirements: [Requirement], candidates: CandidateSet,
              proposal: BindingProposal, inventory: [InventoryRow],
              sources: [Source], references: [EvidenceRef],
              observations: [Observation], bindings: [Binding],
              variables: [Variable], mechanisms: [MechanismSpec],
              identities: [IdentitySpec], actor_dossiers: [ActorSpec],
              calendar: [CalendarSpec], hazards: [HazardSpec],
              indicators: [IndicatorSpec], reference_classes: [ReferenceClassSpec],
              gaps: [Gap], resolution_attempts: [ResolutionAttempt],
              coverage: Coverage, readiness: [Readiness], metering: Metering}
Variable = {node_id, identity: Identity, binding_id: ?ID,
            history_observation_ids: [ID], revision_observation_ids: [ID],
            writable: bool, producer_mechanism_id: ?ID}
MechanismSpec = {mechanism_id, template: Template, template_version,
                 input_node_ids: [ID], output_node_id,
                 parameters: [ParameterSlot], lag_requirement_origin: ?JSONPointer,
                 applicability_requirement_origins: [JSONPointer],
                 consumers: [Consumer]}
Template = growth|sum|product|linear|supply_demand|adoption|regulatory_milestone
ParameterSlot = {name, requirement_origin: JSONPointer, unit: Unit}
IdentitySpec = {identity_id, lhs_node_id, rhs_mechanism_id,
                absolute_tolerance: DecimalText, relative_tolerance: DecimalText,
                scale_unit: Unit, basis_requirement_origin: JSONPointer}
ActorSpec = {actor_ref, registry_artifact_id, registry_pointer,
             statements: [JSONPointer], authority: [AuthoritySpec],
             plans: [JSONPointer], red_lines: [RedLineSpec]}
AuthoritySpec = {lever_id, requirement_origin: JSONPointer, node_id,
                 mode: sole|shared|consent|vote, coholder_actor_refs: [ID],
                 bound_requirement_origins: [JSONPointer]}
RedLineSpec = {requirement_origin: JSONPointer, predicate: ?Predicate}
Predicate = {node_id, operator: lt|lte|gt|gte, value: DecimalText}
          | {node_id, operator: between, low: DecimalText, high: DecimalText}
CalendarSpec = {event_id, requirement_origin: JSONPointer,
                classification: scheduled|intention|historical,
                time_requirement_origin: JSONPointer,
                effect_requirement_origins: [JSONPointer]}
HazardSpec = {hazard_id, trigger: ?Predicate,
              likelihood_requirement_origin: ?JSONPointer,
              effect_requirement_origins: [JSONPointer],
              recurrence_requirement_origin: ?JSONPointer, consumers: [Consumer]}
IndicatorSpec = {indicator_id, node_id, requirement_origin: JSONPointer,
                 consumer: Consumer, trigger: ?Predicate}
ReferenceClassSpec = {reference_class_id, membership_requirement_origins: [JSONPointer],
                      observation_ids: [ID], purpose: diagnostic|parameter_prior}
Readiness = {engine: Engine, status: ready|blocked,
             blocking_gap_ids: [ID], unmet_requirement_ids: [ID]}
Coverage = {inventory_total: int, indexed: int, unsupported: int,
            missing_provenance: int, admitted_observations: int,
            bound_requirements: int, conflicted_requirements: int,
            contested_requirements: int, gap_requirements: int,
            omissions: [InputOmission]}
Metering = {anchor_budget_scope_id: ?ID, receipt_artifact_id: ?ID,
            receipt_hash: ?Hash, mode: offline_deterministic|metered,
            physical_model_attempts: int, reserved_tokens: int,
            physical_catalog_attempts: int, physical_followup_attempts?: int}
```

The `*Spec` objects are copied from the contract and refer to exact requirement origins; they are not model-authored executable blobs. Requirement origins resolve through the registry, and numeric values resolve through admitted bindings/observations. To avoid circular IDs, pre-binding reference-class membership uses requirement origins and an empty `observation_ids` list; consumers and the human sheet resolve members through admitted bindings without rewriting the frozen descriptor. Other section specs remain exact copies. Variables derive from explicit baseline/target node consumers and mechanism outputs; no additional variable may be synthesized from a number or label.

Mechanism parameter names/arity retain the existing grammar: growth and supply_demand have two inputs and no parameters; sum/product have >=1 input and no parameters; linear has >=1 input, one `coefficient:<node_id>` slot for each ordered input plus `intercept`; adoption has two inputs and `rate`; regulatory_milestone has zero inputs and `milestonePeriod`, `before`, `after`. Case projection maps coefficient slots back to native `coefficients` order. Ranges retain bases, source references and declared units. The existing runtime compiler owns dimension checks, propagation, lag execution, random draws and supported template versions; an unknown template/version/consumer mapping produces `modeling_gap`, never arbitrary evaluation. No second numerical runtime is created here.

`writable=false` for derived nodes, including a derived target. Missing/contested input stops dependent propagation. An identity passes when `abs(lhs-rhs) <= absolute_tolerance + relative_tolerance * max(abs(lhs),abs(rhs))` after declared scale conversion; an unevaluable identity stays unknown, not passed. Nonnegative tolerances require a pinned basis. Runtime acceptance must prove the existing compiler executes the advertised templates; this document is not that evidence.

Calendar/intention/history classes remain distinct. A calendar date alone does not authenticate its effect magnitude. Hazard probability, size and recurrence each need separate support/allowed parameter priors; missing probability never becomes 0 or 1. Actor plans do not imply accomplished actions. Sole authority requires evidence; shared/consent/vote modes require identified co-holders and their authority requirements. Unsupported red-line predicates remain narrative gaps. Canonical agency classification remains the existing C5 map, outside this pack.

Coverage sums `indexed + unsupported + missing_provenance == inventory_total`; requirement statuses partition the registry. Every row remains visible in inventory even if unused. Readiness is admission readiness, computed per engine from required consumers, transitive dependencies and exact `Policy.consumer_rules` pins. It additionally requires at least one bound policy-mapped executable consumer; diagnostic/actor-brief-only and unmapped engines receive `modeling_gap`. Unused mechanisms belonging only to another engine neither block nor enter the selected engine projection; it is necessary but not sufficient for the downstream compiler/runtime's own validation. These reviewed consumer rules declare authorized mappings and versions; a valid policy hash does not attest installed adapter support. Every real consumer MUST independently enforce the adapter/version and semantics implemented by its own code before preparing or executing a model. For the reflexive path, Newton owns the installed `world-anchor-reflexive/v1` and template `v1` checks, exact native parameter-slot coverage/units, and rejection of unsupported lag/applicability. A policy declaration cannot extend those capabilities. No diagnostic-only runtime profile is implicitly authorized. An unmapped consumer is `modeling_gap`. Absence of requirements/contract blocks all engines. Optional unmet requirements remain gaps and are excluded from executable projections. Required identity/authority cannot be waived by library priors. Metered counts must match the pinned durable receipt and ceilings; deterministic offline mode has null receipt/scope and all counts zero. A replay preserves the original receipt and performs zero new calls; it does not relabel a metered pack as offline.

## 8. Engine, actor and prepared world-v1 projections

```text
EngineProjection = {schema_version: world-anchor-engine/v1,
                     engine: Engine, scope: Scope, pack_hash: Hash,
                     contract_hash: Hash, input_hash: Hash,
                     variables: [Variable], observations: [Observation],
                     bindings: [Binding], references: [EvidenceRef],
                     mechanisms: [MechanismSpec], identities: [IdentitySpec],
                     calendar: [CalendarSpec], hazards: [HazardSpec],
                     indicators: [IndicatorSpec], gap_ids: [ID]}
ActorProjection = {schema_version: world-anchor-actor/v1,
                    actor_ref, at: Instant, items: [ActorItem]}
ActorItem = {item_id, text: str, value: ?Value, value_kind: ValueKind,
             identity: ?Identity, public_source_url: ?str,
             known_by: Instant, effective_at: ?Instant}
```

EngineProjection is privileged runtime input, never an actor prompt. It includes only admitted bindings needed by that engine and their provenance closure, with private notes/unselected inventory/proposal text excluded. Target-first applies this projection inside the producer to the admitted case before assessment/seal; runtime continues to consume that final case. OASIS must explicitly persist/load fields and connect due events, mechanisms and indicators. A raw pack key ignored by a runtime is not supported. Engine projections do not include assessments, scenario weights, binary probabilities, estimator values or new target definitions.

ActorProjection is an allowlist: exact supported statements/authorized observations with supported `known_by <= min(cutoff, at)` and `visible_at <= at`, public audience or that actor's authorized audience, and an admitted actor basis. Exclude research_analyst/model_prior/simulation producer classes and analyst_inferred/assumed/simulated initial dossiers, all first-party estimator/scenario content and rival-private material. Later simulated observations use the engine's separate observation channel and remain simulated. A visibility grant may delay release but cannot establish knowledge before its independently supported known-by bound. Unknown knowledge times and unsupported visibility grants remain excluded. Public speech can be quoted as speech, not an assertion of sincere private belief. Actor text is an exact authorized quote or deterministic rendering of its admitted typed fields, never proposal/model notes.

Actor payloads MUST NOT contain global pack/input hashes, hidden gap/count metadata, private filesystem paths or raw reference registries: those can change under private-only perturbations. Actor item IDs derive only from the visible item's canonical content, with provenance IDs retained in a privileged sidecar. The application caches by actor/cast scope + authorized payload digest + observation time; it must not reuse another actor's summary. Global artifact pins may govern privileged cache invalidation, never enter actor messages. The consumer owner must filter existing role dossiers/config behavior/shared/private briefs/summaries in the entire system/user request. Filtering only this projection does not meet I-30.

Actor UUID joining occurs after ontology through a separate receipt, never by editing the pack:

```text
ActorJoin = {schema_version: world-anchor-actor-join/v1,
             pack_hash: Hash, research_manifest_hash: Hash, cast_hash: Hash,
             rows: [{actor_ref, entity_uuid, registry_artifact_id,
                     registry_pointer, alias_ref_ids: [ID]}]}
```

Consumer owner validates one-to-one membership and evidence-supported aliases against the sealed cast; ambiguous aliases, one dossier mapped to multiple UUIDs or many dossiers sharing a UUID fail. Do not generate actor UUIDs in this module. Existing C5 declarations/bases are validated separately against this join.

The exact parameter-admission interchange for the compiled world is:

```text
ParameterRequest = {request_id, requirement_id, binding_id,
                    observation_id: ?ID,
                    field: value|range.low|range.high,
                    target: JSONPointer, target_object_id, identity: Identity,
                    expected_value: Value}
PreparedParameters = {schema_version: prepared-typed-world/v1,
                       engine: world-v1, scope: Scope,
                       pack_hash: Hash, contract_hash: Hash, input_hash: Hash,
                       parameters: [PreparedParameter]}
PreparedParameter = {request_id, requirement_id, binding_id,
                      observation_id: ?ID, field, target: JSONPointer,
                      target_object_id, identity: Identity, value: Value,
                      value_kind: ValueKind, producer_class,
                      audience: Audience, available_at: Time, known_by: Time,
                      effective_at: Time, visible_at: Time,
                      ref_ids: [ID], source_bindings: [EvidenceRef],
                      assumption: ?Assumption}
AnchorBasis = {kind: anchor_evidence,
               refs: [{pack_hash: Hash, requirement_id, binding_id,
                       observation_id: ?ID, field, target: JSONPointer,
                       target_object_id}]}
```

`prepare_world_parameters` recomputes each selected value; `expected_value` is an equality assertion, not an override. It requires a ready world-v1 pack and exactly one admitted binding per requested target leaf. Observation references resolve the selected observation, identity/unit/period and declared conversion; assumed bindings have null observation ID and explicit prior evidence, producer_class=model_prior, analyst audience and unknown evidence times unless the prior receipt explicitly supplies them. Such parameters are not initial actor knowledge. Range endpoints may only support matching declared input bounds; selecting an endpoint as a point estimate requires a separate admitted modeling policy. No boolean/decimal coercion. Parameters use DecimalText to preserve the existing compiler's decimal-string quantities. Prepared receipts are privileged; model proposals cannot author them.

Targets are RFC 6901 paths into the exact precompile world-spec: `/initialState/accounts/<id>/balance`, `/initialState/metrics/<id>/value`, `/initialState/rules/<id>/value`, `/initialState/relations/<id>/value`, `/actionCatalog/<index>/parameters/<field>`, `/actionCatalog/<index>/inputs/<name>/min|.../max`, `/scheduledEvents/<index>/parameters/<field>`, or `/flows/<index>/ratePerDay`. The compiler validates indices/record identities and the existing closed action/event schema; paths are selectors, never arbitrary mutation instructions. Nested agreement transfers/vote weights require an explicitly supported compiler selector and otherwise yield `unsupported_mapping`. A request must match the requirement's exact world-v1 consumer object and field, not just its numeric value. `field` refers to the observation/assumption value; `target` refers to the spec leaf. Non-numeric rule/relationship values retain their exact type and semantic identity.

The compiler authenticates AnchorBasis against this prepared receipt and the pinned pack before accepting any value. It validates target entity/metric/unit/period, field semantics, audience, current record IDs, target contract and generation. It computes the native per-record basis plus `sourceBindings.worldAnchor = {schemaVersion: world-anchor-binding/v1, packHash, inputHash, contractHash, researchGenerationId, preparedParametersHash, references: [AnchorBasis refs]}` itself. Caller-supplied sourceBindings are discarded. The existing world_input_manifest additionally pins these hashes plus the final case hash when present. A source claim attributed to an actor, a report excerpt, or a model-generated qualifier is not an alias for anchor_evidence.

Descriptions, profiles, structural IDs, event timing and authority still need their own admitted existing provenance or explicit anchor binding; a parameter receipt does not bless an entire action. Unsupported mechanisms remain `modeling_gap` and stop enabled preparation. Service/manager/orchestrator owners thread the optional pack/receipt through the existing prepare/compiler chain; no engine switch or kernel rewrite is implied. Report/after-action owners render admitted diagnostic provenance and initial/final comparisons through their explicit artifact fields; they preserve simulationWeight=0 and RW-11.

## 9. Deterministic emission, read and optional-mode lifecycle

`emit_pack` validates the pack and renders exactly `world_anchor.json` (canonical authoritative bytes), `world_anchor.md` (deterministic private human view), `world_anchor_gaps.json` and `world_anchor_coverage.json`. The two JSON companions are `{schema_version: world-anchor-gaps/v1, pack_hash, gaps}` and `{schema_version: world-anchor-coverage/v1, pack_hash, coverage, readiness}`. Markdown has fixed section/order formatting, escaped source text and no ambient timestamps. These are private research outputs, not public or actor views.

```text
EmissionReceipt = {schema_version: world-anchor-emission/v1,
                   scope: Scope, pack_hash: Hash,
                   contract_hash: ?Hash, input_hash: Hash, policy_hash: Hash,
                   files: [{path, sha256: Hash, bytes: int}]}
EnabledPin = {mode: v1, policy_hash: Hash, research_generation_id,
              pack_hash: Hash, emission_receipt_hash: Hash}
```

`files` has exactly those four fixed paths sorted lexically. No receipt self-hash. Write with exclusive staging files, fsync, no-overwrite publication and directory fsync; an existing identical generation is idempotent, a differing file is `E_IMMUTABLE`. Return the receipt only after all outputs are durable. Coordinator publishes the parent manifest last with receipt bytes/hash, final case hash if any, and the final research-generation inventory. A crash before that manifest leaves an unpublished generation; readers cannot treat loose files as a completed pack.

The coordinator first authenticates the existing parent completion manifest and passes its exact `receipt` and expected hashes explicitly to `read_pack`; this module does not guess a parent-manifest pathname or trust a loose sidecar. `read_pack` checks the receipt hash, all four file hashes, scope/contract/input/policy, then calls `validate_pack` with an authenticated index. It renders companions again and checks exact equality. The coordinator cross-binds the anchor input generation to its final research-generation digest without forcing unrelated ID schemes equal. A missing parent completion manifest is a coordinator publication error; a missing/mismatched supplied receipt/hash, altered source input, mixed-generation artifact or changed pack fails closed here. No reader consults network, environment, new current time, binder, or source discovery. No reader reopens a sealed research generation.

EnabledPin is written by coordinator only for enabled runs. Absence means off forever on retry/reuse/fork, even if `SIM_WORLD_ANCHOR` later changes. Off mode MUST bypass these APIs completely: zero new keys/calls/RNG draws/order changes/receipt identities. An enabled pin with absent/invalid artifacts cannot fall back to legacy. A producer's intent to enable precedes completion pins; it is not a ready pack. Fork ownership changes are handled by a new child manifest referencing immutable parent identities; child IDs must never be substituted inside an inherited pack.

## 10. Errors, gaps and validation commitments

`AnchorError.code` is closed: `E_SCHEMA`, `E_VERSION`, `E_LIMIT`, `E_NONFINITE`, `E_DUPLICATE_KEY`, `E_PATH`, `E_FILE_MISSING`, `E_HASH`, `E_SCOPE`, `E_REFERENCE`, `E_CONTRACT`, `E_PROPOSAL`, `E_IMMUTABLE`, `E_PUBLICATION`, `E_NOT_READY`, `E_PRIVACY`, `E_BUDGET_RECEIPT`. Hard integrity/scope/schema failures raise; valid missing or ambiguous evidence produces a Gap. Error text identifies safe artifact/requirement IDs, never embeds source pages, private quotes, credentials or provider payloads.

`GapCode` is closed: `retrieval_error_page`, `partial_capture`, `unknown_remote_completeness`, `evidence_class_not_allowed`, `missing_contract`, `missing_identity`, `missing_settlement`, `missing_page`, `missing_provenance`, `unsupported_shape`, `inventory_omission`, `ambiguous_source`, `ambiguous_support`, `unsupported_semantics`, `wrong_entity`, `wrong_metric`, `wrong_unit`, `wrong_denominator`, `wrong_geography`, `wrong_period`, `wrong_value_kind`, `unsupported_conversion`, `unknown_availability`, `after_cutoff`, `future_observation`, `conflicting_values`, `identity_residual`, `dependency_unready`, `unproposed`, `no_candidate`, `forbidden_actor_evidence`, `missing_authority`, `ambiguous_actor`, `unsupported_predicate`, `unknown_cadence`, `missing_effect`, `missing_likelihood`, `missing_recurrence`, `modeling_gap`, `unsupported_mapping`, `prior_not_allowed`, `budget_exhausted`, `profile_unqualified`, `access_denied`, `cancelled`, `outcome_unknown`, `sealed_generation`. Any newly needed code/schema change is coordinated before producer and consumer diverge.

Future dedicated offline tests must establish WA01–05 plus malformed/foreign refs, byte/span/hash changes, path/symlink/race/finite-JSON limits, deterministic read/emission and readiness. Consumer owners additionally prove WA06–09/11/12/14/16 at actual runtime/message/compiler boundaries. The contract owner does not run application imports/tests before worktree release.

The private package is `/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-specimen-20261029-055917Z-v3`. Its raw `manifest.json` SHA256 is `9dfa2f0861a6133d174d06fd76d850e3ef4404c0775572721db04f81569c3f27`. The provided `2ce833dadd4edbbaaad6692bfe2258aa2954383ff03193e6d71a47891b35ef39` is `seal.json.package_sha256`, not the SHA256 of `seal.json` itself (`21fb718730e8664cb750f211f775d5971e2f1bd2f60240dcef55f7b5a303cdea`). The specimen manifest explicitly declares it is not a World Anchor contract. Adapt its pinned file map to InputManifest; do not treat raw metadata as admitted typed evidence.

The owner reports ten KIQs/116 facts, 201 sources (34 hash-verified pages, 167 snippets), 95 raw files, no official series and no typed forecast contract. The current contract review verified the manifest hash and both S107 quote byte spans without copying private quotes to Git; it did not perform a full package replay. S107's 239.8→244.2→246.2→248.2→247.5 figures are 2026 forecast revisions through a secondary chain. S141 retains an error page; S107 ends mid-table; remote completeness is unknown. Keep these capture limitations distinct from content-hash integrity. A separately trusted pre-cutoff fetch receipt may establish known_by, but the private quote review alone supplies no availability or independent semantic admission. Missing target contract still blocks preparation.

## 11. Owner progress and next handoff

- 2026-10-29: Read the root/topic handoffs, approved plan, producer/consumer maps and bounded existing case/compiler interfaces without app imports or tests. Preserved the dirty spending work and concurrent owners' files.
- 2026-10-29: Drafted the public API, closed input/index/proposal/pack/projection contracts and conservative evidence rules here. This is a design deliverable, not implementation evidence. The separate metering transaction/request version remains spending/coordinator ownership.
- 2026-10-29: Static self-review clarified explicit read receipts, authenticated index handles, qualitative versus numeric identity, contract-only target definitions, bounded literal support and compact exclusion accounting. The documentation whitespace check passed; no application imports, test runs or runtime acceptance occurred.
- 2026-10-29: Continued only in the new world-anchor worktree after spending delivery. Proposed two coordinator-requested refinements: producer extraction plus distinct qualified review, and trusted-receipt known_by admission. Corrected text spans to UTF-8 bytes and separated capture completeness from hash integrity. The old worktree remains untouched.
- Next: coordinator freezes these two corrections, then explicitly releases pure-module/consumer implementation. No application source, tests, providers, commits or delegation were used for this revision.

## Frozen consumer alignment (2026-10-29)

- Reflexive engine is `oasis-legacy`, adapter `world-anchor-reflexive/v1`. Initial state uses `object_id=node_id, field=value`. Calendar uses ISO text/supported effective time and effect requirements with role `calendar`, node object ID and `field=set|add|mul`.
- Hazards use native `1/day` with `field=hazard_per_day` and boolean recurrence. A cumulative probability/window needs an explicit process assumption/version; it is not a unit conversion. Indicators require a node and supported Predicate that reaches a runtime signpost. Unsupported mappings remain `modeling_gap`.
- Coordinator owns `AnchorContext` with `.pack/.requirements/.index/.policy/.pack_hash/.join`. No app wrapper is introduced in the pure module. Anchor input-generation IDs and compiler `researchGenerationId` digests are different identity schemes: the outer completion manifest cross-binds them rather than asserting equality.
- Whole private specimen seal was checked: 108 manifest members match sizes/hashes; the 109-file package map matches its supplied package digest. No private bytes were changed.

## Core delivery receipt — 2026-10-29

The owned module and test file are frozen for coordinator integration. Only these two source files and this contract were edited by this owner in the new worktree. No application/runtime/integration/budget files, old-worktree files, providers, commits or delegation were used. Existing shared application changes belong to their respective owners.

The final guarded receipt is [completed.json](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-core-final-private-06/completed.json), with [JUnit results](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-core-final-private-06/junit.xml): **53 passed, zero failed, zero skipped, 3.30 seconds**. The guard reports only the existing app-config and logger redirects, no network/subprocess/credential attempts, no source drift, and completed shutdown. Ruff formatting and the selected correctness/unused-symbol checks pass. The module source hash is recorded separately below; the runner's automatic source map includes the selected tests and its existing guarded imports.

The private acceptance inventories 201 scoped sources, 34 hash-verified pages, 167 snippet-only entries, 116 KIQ facts, 52 legacy quantitative rows and 24 timeline rows, plus actor records. With no typed contract, it emits and reloads a blocked evidence pack with no invented variables/observations/requirements. A separate explicit fixture contract exercises the actual S107 retained byte span and independently captured **scripted offline** extraction/review artifacts: 247.5 remains a 2026 third-party forecast, publication stays unknown, original capture supplies known_by, and forecast revisions never become growth history. Scripted receipt acceptance is not live model qualification or proof of general semantic entailment.

| Reproduced defect | Red evidence | Green evidence |
|---|---|---|
| Authenticated noncanonical raw JSON incorrectly compared to canonical re-encoding | `world-anchor-core-red-rawbytes`: 1 failed | `world-anchor-core-02`: 33 passed |
| Sentence-final `10.`/`10.5.` rejected; exponent tail `3` in `1e-3` admitted | `world-anchor-core-red-punctuation`: 3 failed, 11 passed | `world-anchor-core-green-punctuation`: 14 passed |
| Target-first-only mechanism leaked into world-v1 projection | `world-anchor-core-red-engine-scope`: 1 failed | `world-anchor-core-green-engine`: 2 passed |
| Diagnostic-only/unmapped engines vacuously ready | `world-anchor-core-red-empty-engine`: 1 failed | `world-anchor-core-green-engine`: 2 passed |

All evidence directories are under `/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/`; the final 53-case gate includes every correction. The private fixture is supplied via bounded stdin because the existing guard removes custom environment variables. The guard was not weakened. Raw private quotes/pages remain outside Git.

The API hash is SHA256 of compact JSON containing the public function signatures in module declaration order (`name + '(' + ast.unparse(args) + ')'`). API SHA256: `02985fc00cea976a4d381098f1b10a45c1b05587a172b58af9681101879e0e39`.

- `deerflow_bridge/world_anchor.py`: `028d26ff1958a51b3537baed1996d81823777c613f8ac11dae2e532af20dfbb1`.
- `backend/tests/test_world_anchor.py`: `7835da1369e26b751f2c261f069690b2c9bb602d0f2c4f0bb97dc561f6e82c89`.

Next-owner prompt: retain the frozen fourteen-function interface, authenticated producer handles and per-engine readiness. Run the consumer/publication/lifecycle scenarios against these bytes; preserve independent source-input and producer-receipt manifests and cross-bind the compiler generation separately. The existing C5 authority, whole actor payload I-30 gate, actual mechanism/event/signpost execution, stage reservation transaction and protected forecast/report authority remain their assigned owners' gates. Do not treat this core gate as full-feature or live-provider acceptance.

## Actor-time and installed-consumer review — 2026-10-29

The coordinator identified an actor-time boundary requiring `known_by <= min(cutoff, requested_actor_time)`, independent of a `visible_at` grant. This owner will capture a focused red/green receipt, retain equality/late/unknown controls, and refresh the core source freeze. Ownership remains the same three files. Newton owns the reflexive installed-adapter/slot/version/lag/applicability fixes; this owner does not edit those files. A policy hash authenticates declared rules and never attests that an adapter is installed or implements the declared semantics.

- Focused red receipt: `world-anchor-core-red-actor-time-07` reproduced three early-knowledge leaks; seven equality/later-visibility/unknown/cutoff/unsupported-review controls already passed. The fix compares known_by to the earlier of the research cutoff and requested actor time. The pure public API and schema are unchanged.

### Refreshed source freeze

The focused actor-time gate passed all ten cases after reproducing three early-knowledge leaks. Equality with the known-by bound remains allowed; later visibility, missing capture time, capture after cutoff and omitted visibility review remain denied. `actor_projection` now requires `known_by <= min(cutoff, at)` as well as `visible_at <= at`. A visibility grant cannot backdate independently authenticated knowledge.

- Red: [actor-time JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-core-red-actor-time-07/junit.xml), 3 failed / 7 passed.
- Focused green: [actor-time JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-core-green-actor-time-08/junit.xml), 10 passed.
- Composed green: [completion receipt](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-core-freeze-actor-time-09/completed.json) and [JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-core-freeze-actor-time-09/junit.xml), **63 passed, zero failures/errors/skips, 3.82 seconds**, including both private-specimen controls. Guard events are only the existing app-config/logger redirects; shutdown completed and recorded source drift is empty. Selected Ruff checks pass.

Current module SHA256: `09be39b27a5cceb7cbda3ef2b10efe264fc139826daee5aba4fe0b905ddf41df`. Current tests SHA256: `108784ef6e8ef6b9e5b077187f1bee599c8047df59eb4de9b38acc0eb9a73496`. Unchanged API SHA256: `02985fc00cea976a4d381098f1b10a45c1b05587a172b58af9681101879e0e39`. These source hashes supersede the prior core freeze; earlier receipts remain historical evidence.

`admit_bindings` and `engine_projection` explicitly establish admission prerequisites only. Their policy checks have been named/documented as policy admission, not installed capability. This owner makes no new consumer-runtime acceptance claim: Newton and the other actual consumers must independently reject unsupported adapter/template versions, parameter-slot/unit mappings, lag and applicability even when the policy and pack hashes are valid. No consumer, integration, budget or old-worktree files were edited for this correction.

## Human anchor sheet completion — 2026-10-29

The private analyst renderer is being expanded from the incomplete binding/status summary into variables, mechanisms and parameter bases, actor items/classes, calendar, hazards, indicators, reference classes, identities, source provenance, gaps, coverage and typed omissions. Labels must resolve through authenticated source/registry/alias bytes; no fresh narrative inference or ambient source reads are allowed. Rendering must preserve explicit unknowns and assumptions, escape source text, and reproduce identical bytes through a fresh authenticated replay. Admission/projection behavior and public signatures are not part of this change. The shared pure module is held during the compiled-owner's short final gate; isolated tests and this documentation proceed first.

## Final interface additions and review repairs — 2026-10-30

### Non-executable research inventory

`authority_kind=research_inventory` explicitly admits a legacy/incomplete research inventory with `settlement=null`. Every term has `identity=null`, `value_type=text`, no prior fallback, and consumers exclusively using `research_note`. Mechanisms and identities are empty. Actor descriptors may retain registry references and statement origins, with authority/plans/red_lines empty. Calendar/hazard/indicator/reference-class descriptors may reference note requirements but cannot carry executable predicates/effects or parameter priors. All engines always receive blocking `missing_contract`; a non-null inventory hash is not settlement authority. Normal `requirements_from_contract(None)` remains an empty blocked registry.

The closed research kind set is `actor_objective`, `actor_incentive`, `actor_constraint`, `actor_capability`, `actor_information`, `actor_decision_process`, `actor_authority`, `actor_belief`, `red_line`, `actor_plan`, `actor_relationship`, `actor_track_record`, `actor_statement`, `calendar_event`, `event`, `hazard`, `indicator`, `reference_class`, and `research_note`. Actor plans remain stated intentions and never become scheduled effects. Temporal fields remain explicitly sourced or unknown. No extra ad-hoc term keys are accepted.

`cardinality` is the sole optional requirement field: omission means `one`; `many` permits a selected collection of text observations. Numeric/range/boolean collections and scalar state/parameter consumers are refused. Qualitative matching uses the requirement IDs retained in authenticated extraction proposals and actor association, so unrelated quotes do not conflict. Different text in an explicit collection may coexist; scalar text/boolean and admissible numeric identity conflicts remain strict. Explicit conflict proposals still remain conflicts. Missing evidence remains a typed gap.

When note requirements are present, the pack additionally contains `research_items`, derived only from bound observations:

```text
ResearchItem = {research_item_id, requirement_id, observation_id, kind, actor_ref: ?ID,
                quote, value_kind: ValueKind, producer_class: ProducerClass,
                audience: Audience, known_by: Time, effective_at: Time, visible_at: Time,
                ref_ids: [ID], executable: false}
```

The quote resolves from the authenticated value-support text span or JSON string selector. It is not a model note or a fabricated summary. Research-only requirements grant no actor visibility. Engine preparation is blocked for research_inventory; actor/public consumers retain their independent permission and time checks.

### Receipt attachment and retained accounting

`attach_producer_receipts(index, *, receipts)` accepts only externally authenticated opaque handles, checks scope/policy and manifest/file collisions, deduplicates by manifest hash, and preserves observations, reviews and semantic evidence/candidate identity. Publication must attach all bundles before review replay and pack validation, including budget-only bundles with no model transports. No dummy review or private-index mutation is permitted.

Metered `pack.metering` has exactly `mode`, `anchor_budget_scope_id`, `receipt_artifact_id`, `receipt_hash`, `physical_model_attempts`, `reserved_tokens`, `physical_catalog_attempts`, and `physical_followup_attempts`. The authenticated raw summary additionally names `budget_receipt_artifact_id` and `budget_receipt_hash`; those two links do not belong at top level. Offline metering retains the previous zero/null shape and may include followup=0. Bound zero-call stages remain metered.

The linked core budget receipt uses the exact `anchor-budget-receipt/v1` fields: `schema`, `authorization_sha256`, `pipeline_id`, `scope_id`, `session_id`, `generation`, `policy_sha256`, `source_sha256`, `routes_sha256`, `retained`, `limits`, and `barrier_sha256`. Retained usage must not exceed declared immutable limits, which must not exceed hard ceilings 20/150000/8/12. Lower immutable caps are valid. Scope, authorization, policy/source/routes and limits agree across retained seals; counter vectors are monotone. The selected summary and its linked budget must cover the retained maxima, including `reserved_max_microusd`. Parent adoption separately joins the selected budget's canonical hash to the trusted ledger exit receipt; the pure maximum check does not replace that lifecycle proof.

### Source classes, priors and raw identifiers

Accepted evidence names remain `page`, `official_row`, `typed_claim`, and `contract`. Authenticated fetched-page sources qualify as page evidence; native official rows qualify as official_row. Authenticated native case claim/node/parameter provenance may additionally qualify as typed_claim. A newly typed model extraction does not acquire that class merely by having a tuple shape. Every referenced source must satisfy the allowed closure; disallowed matches yield `evidence_class_not_allowed`.

An assumed parameter requires a retained artifact matching the prior's raw hash and pointer. The selected object must reproduce the declared value and library version, and any supplied identity must agree. The prior's value kind must equal the requirement's value_type and `assumed` must be allowed. Missing/tampered basis, wrong pointer/projection/library, wrong value type and forbidden assumed class fail closed. This closes an API defect; it does not assert that the producer had invoked that invalid path.

Raw KIQ facts always join positive integer `sids` through their own track ledger, even in a target-case track. Native case rows use the explicit authenticated target sourceId crosswalk. Strings, prefixed IDs, floats, booleans and nonpositive KIQ IDs cannot acquire ledger provenance. Original input bytes remain unchanged. Metadata status conflict/unknown, or overflow, forces tier unknown; an explicit evidence_tier never falls back to a stale legacy tier, and no domain inference is introduced.

### Complete private human sheet

The sheet now renders variables with value/unit/period/vintage/status/source, mechanism and parameter bases, actor items with epistemic/producer and declared registry class, calendar, hazards, indicators, reference classes, identities, evidence inventory, research items, sources, requirements, gaps, coverage, admission prerequisites, input/render omissions, candidate exclusions, resolution attempts and metering. Empty executable descriptors do not hide declared research-note categories or their gaps. Authenticated aliases/registry bytes supply labels; scoped IDs such as `main:S107` identify sources. Untrusted Markdown/HTML/control text is escaped in one pass. Unknown dates, classes, units and missing evidence remain explicit; no value is invented for presentation.

Rendering uses only the already authenticated in-memory snapshot and does not mutate the pack or actor/public projections. Fresh authenticated reload reproduces the Markdown bytes exactly. This changes the private Markdown template and its receipt hash; existing generations are not overwritten. The sheet is not public-report or actor-prompt permission.

## Final pure candidate and durable private evidence — 2026-10-30

**Branch:** `codex/world-anchor`. **Owned files:** `deerflow_bridge/world_anchor.py`, `backend/tests/test_world_anchor.py`, and this contract. Core source and tests are held for final independent closure. The parent owns integration/runtime delivery and the final whole-feature gate.

- Current module SHA256: `1b90d45e42dbc2cf52b9d0b83dbb001f9aff13c5ccb78e0fccab7037f6d87df6`.
- Current dedicated tests SHA256: `51dd3e8c2b4905b367ea8265b45757ca41b74e30d1602ccf4d15ec1cd2486f31`.
- Current fifteen-function API SHA256: `4e745eff1a4949ecac9a49812d8e5ae664c833678e975bf03b928bda9dfe367d`. The sole public function addition since the earlier fourteen-function freeze is `attach_producer_receipts(index, *, receipts)`.

The [non-private gate](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-core-candidate-23/completed.json) passed **114 checks**, with the two private stdin tests deliberately deselected. The [same-source private gate](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-private-freeze-24/completed.json) passed **both private tests with zero skips**. The [durable before/after verification](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-private-freeze-24-envelope/verification.json) records matching module/test/runner pins, the full 95 raw files, all 108 manifest members, the 109-member sealed package, exact invocation, private stdin digest/size, and wall time. Original inputs remained unchanged; the private child gate took 2.61 seconds including runner startup.

The private proof retains the whole raw corpus without manufacturing a typed contract or official series. Its no-contract pack remains blocked with explicit gaps. The S107 fixture uses a declared 2026 evidence window and 2026 quantity requirements, not a fabricated 2027 target. A separate no-contract evidence inventory admits the five retained values 239.8, 244.2, 246.2, 248.2 and 247.5 as third-party forecasts for the same 2026 reference period. It creates no variables/requirements or growth history. Exact retained row spans preserve the source's vintage statements without inventing normalized dates, cadence or term variables. These are independently captured scripted offline review artifacts; they do not qualify a live model or establish general semantic truth.

The exact stdlib-only [private runner](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-private-harness-20261030/run_private_gate.py) is retained with SHA256 `76449b425a5183b9001b5184a472b495a41bf5bb562bf75fca67912cea1621ab`. Invoke it with a new evidence directory:

```sh
python3 /Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-private-harness-20261030/run_private_gate.py \
  --repo /Users/rogerlin/.codex/worktrees/world-anchor/DeepResearchForecast \
  --python /Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python \
  --specimen /Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-specimen-20261029-055917Z-v3 \
  --evidence-dir /Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-private-new-receipt
```

The runner performs only standard-library input verification before launching the existing guarded runner with `-I -S -B`. It passes bounded compressed fixture data through stdin, retains no private data in argv, and never combines the target adapter's separate archived-9916 stdin reader with these two tests. It creates an adjacent `-envelope` directory for before/after evidence. A rerun must choose a fresh directory; old receipts are not overwritten.

Human artifacts are available for inspection:

- [Complete synthetic analyst sheet](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-core-candidate-23/pytest-tmp/test_private_anchor_sheet_fres0/sheet/world_anchor.md).
- [Real whole-inventory blocked sheet](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-private-freeze-24/pytest-tmp/test_private_full_inventory_wi0/out/world_anchor.md).
- [S107 five-vintage evidence sheet](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-private-freeze-24/pytest-tmp/test_private_s107_captured_byt0/vintage-out/world_anchor.md).

Review repair evidence remains durable under the evaluations root: `world-anchor-review-red-17` reproduced PR1–PR3; `world-anchor-review-green-18` passed 14 focused controls. `world-anchor-currency-red-20` reproduced the fifth retained-currency component; `world-anchor-render-review-green-21` passed 15 currency/prior/renderer/tier controls. The final 114+2 gates cover the later exact candidate bytes. Bohr independently reproduced the original findings, inspected the complete renderer, and obtained identical outputs after fresh authenticated reconstruction; his final closure belongs in `pure-review.md`.

Remaining work is outside this owner's production scope: parent acceptance must retain the exact selected-budget canonical-hash join to ledger exit; installed consumers must enforce their own capabilities; public native claims require an exact producer-owned observation/reference permission mapping. No public permission may be inferred from node membership, matching text or equal numeric values. No source, integration, provider or whole-feature success is inferred from this bounded pure gate.

## Independent closure — 2026-10-30

Bohr closed the bounded pure review in [pure-review.md](pure-review.md) against module `1b90d45e42dbc2cf52b9d0b83dbb001f9aff13c5ccb78e0fccab7037f6d87df6` and tests `51dd3e8c2b4905b367ea8265b45757ca41b74e30d1602ccf4d15ec1cd2486f31`. PR1–PR3, the fifth retained-currency component, and the separately inspected parent selected-budget join are closed for their recorded brackets. He inspected the 114-case non-private and two-case private owner gates, independently verified the original 109-member package/95 raw files, rebuilt the 796,348-byte stdin payload with its matching digest, and inspected the S107 five-vintage and blocked-inventory artifacts. His final six-file module/test/publication/host/parent-regression rehash matched.

That closure applies to the recorded source only. A subsequent narrow projection defect is reopened below. No provider qualification, live service behavior, deployment or full-feature acceptance follows from this bounded closure. No commits or edits to other owners' production files were made by this owner.

## Research-note projection follow-up — 2026-10-30

The preserved target publication/runtime tests reproduced two failures on module `1b90d45e42dbc2cf52b9d0b83dbb001f9aff13c5ccb78e0fccab7037f6d87df6`: engine matching selected bound `research_note` requirements into executable bindings. The [behavioral red receipt](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-note-red-25-envelope/verification.json) retains the exact invocation, source copies, unchanged before/after pins, and both failures. Prior core/private gates remain evidence only for their original bytes.

The repair excludes `research_note` consumers from direct engine selection and stops dependency traversal at requirements whose consumers are all research notes. A dependency reached independently through a non-note requirement still projects. Mechanisms require their parameter, lag, and applicability origins to be in the selected closure; calendar entries require their event, time, and effect origins; hazards require likelihood, recurrence, and effect origins; indicators require their origin and a non-note engine consumer. Identities require both their mechanism and any declared basis to remain projected. Optional null descriptor origins stay null. This filtering grants no installed adapter support or semantic execution permission.

Admitted notes remain in the private pack, `research_items`, and analyst sheet. Their private evidence is unchanged by projection. An engine projection does not provide `research_items` as runtime authority. Installed consumers must still reject incomplete or unsupported executable descriptions using their existing checks.

The [pure behavioral red](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-note-pure-red-26-envelope/verification.json) retained nine failures across all three engines, covering direct selection, traversal into and through notes, and descriptors. The [final focused gate](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-note-freeze-28/completed.json) passed **32 checks**, with 189 unrelated cases deselected and zero skips. This includes both unchanged Pauli cases through actual publication, reload, and target runtime, positive executable-dependency and descriptor controls, no-contract inventory blocking, native actor-registry/authority controls, and selected future-observation/milestone controls. The [verification envelope](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-note-freeze-28-envelope/verification.json) records all 128 source pins unchanged before/after, exact command, source copies, and 8.129 seconds of process wall time. The guard recorded only the existing storage/log redirects, no contained probes, and completed shutdown.

The new frozen module SHA256 is `c85ce260bb8309019c86efdcdf5ffdffcd1c7ca580cb0c250a56b7fd4a6ae231`; the dedicated tests SHA256 is `2de1211c263ffb6136354bf19cb04bf2d1f28718b3239a65a559b8d7e5060086`. The [AST scope check](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-note-freeze-28-envelope/scope-check.json) verifies that only `engine_projection` changed and every function signature remains unchanged. Pauli's target tests remain `45ef8aaebeb45db4dcdc6159be807a710ba09400b5a7fca1dc92c8786d6c0c2b`, and his adapter remains `ddaba728b5243a51a3e3a205c319eececa0c0053045282a7e0937903f2a96aac`. No adapter admission or other owner's tests changed. PR1–PR3 functions are untouched; the previous 114+2 gates remain historical evidence for `1b90d45e…`, not a repeated full gate on this candidate. Bohr has these exact receipts and pins for the narrow projection rereview.

Bohr closed the narrow projection follow-up in [pure-review.md](pure-review.md) at these exact module/test hashes. He independently confirmed that every other module AST node and all signatures are unchanged, inspected both red receipts and the 32-case green receipt, verified each envelope's four source copies, and matched all 128 live pins at closure. His twelve in-memory pure controls passed across all three engines, covering direct/dependency/descriptor exclusion and independently required executable dependencies. PR1–PR3 closure is preserved. Core/tests remain held for coordinator integration; this is bounded offline projection acceptance, not a new whole-feature or live-provider gate.
