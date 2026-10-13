# Discovery Question Catalog

**Company:** `<COMPANY_NAME>`  
**Use:** Workshops before integrating semantic planning, local frontend, or changing the existing NL-to-SQL package.  
**Rule:** Do not fill gaps by inventing KPI formulas, system names, or security exceptions.

Each question includes **why it matters**, **expected respondent**, **decision affected**, **risk if unanswered**, **current status**, and **design phase where it must be resolved**.

Status values: `Open` · `Assumed` · `Confirmed` · `Not applicable`

---

## How to use

1. Close Business, Security/Auth, KPI, and NL-to-SQL interface questions before frontend implementation.
2. Record answers in the workshop template (§19).
3. Deferred items keep `definition_status: unresolved` in YAML; the graph clarifies or refuses.

---

## 1. Business

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| B-01 | What business outcomes must AI-for-BI improve in 12 months? | Scopes MVP | `<BUSINESS_SPONSOR_ROLE>` | MVP classes, success metrics | Novelty without decisions | Open | Before frontend MVP |
| B-02 | Which personas are in v1? | UX, latency, narrative | `<BUSINESS_SPONSOR_ROLE>` | Dashboard vs chatbot emphasis | Wrong UX | Open | Before FE build |
| B-03 | Which decisions must never be answered by NLQ? | Policy denylist | `<GENERAL_COUNSEL_ROLE>` | Unsupported taxonomy | Risky answers | Open | Before prod pilot |
| B-04 | Self-serve analyst vs executive briefing? | Answer length, SQL visibility | `<BUSINESS_SPONSOR_ROLE>` | Response contract | Distrust | Open | Before FE build |
| B-05 | What does a good answer contain? | Eval rubric | `<ENTERPRISE_ANALYTICS_LEAD>` | Answer contract | Missing caveats | Open | Before answer prompts freeze |
| B-06 | Fiscal vs calendar grains required? | Time intelligence | `<FPNA_LEAD>` | Default calendar | Wrong YTD | Open | Before time metrics compile |
| B-07 | Are forecasts in v1, with which method? | Forecast route | `<FPNA_LEAD>`, `<DATA_SCIENCE_LEAD>` | Unsupported vs compile | Invented forecasts | Open | Before forecast questions enabled |
| B-08 | Must answers show SQL, product, semantic version? | Trust vs load | `<AUDIT_LEAD>` | UI contract | Unauditable or abandoned UI | Open | Before FE build |
| B-09 | Which ambiguities are unacceptable? | Clarification policy | `<ENTERPRISE_ANALYTICS_LEAD>` | Ambiguity node | Silent KPI substitution | Open | Before planner freeze |
| B-10 | Languages/locales required? | Synonyms/prompts | `<BUSINESS_SPONSOR_ROLE>` | Locale packs | Wrong retrieval | Open | Before synonym certification |
| B-11 | Enterprise-wide vs local color? | Core vs BU split | `<ENTERPRISE_KPI_COUNCIL>` | What belongs in `ent.core` | Competing numbers | Open | Before BU onboarding wave |
| B-12 | Who owns NLQ vs board-pack disagreements? | Escalation | `<ENTERPRISE_KPI_COUNCIL>` | Incident path | Unowned conflicts | Open | Before pilot |

---

## 2. Business Unit scope

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| BUS-01 | Which BUs are in the v1 cohort and order? | Rollout capacity | `<BUSINESS_SPONSOR_ROLE>` | YAML inventory | Unusable generic agent | Open | Before onboarding |
| BUS-02 | Canonical BU code list and hierarchy? | RLS keys | `<ORGANIZATION_STEWARD_ROLE>` | Org product, filters | Wrong BU rows | Open | Before RLS |
| BUS-03 | Can a user belong to multiple BUs? | AuthZ model | `<SECURITY_ARCHITECT_ROLE>` | `authorized_bu_codes` | Over/under sharing | Open | Before auth |
| BUS-04 | For `<BU_NAME>`, enterprise KPI vs `<BU_OPERATIONAL_KPI>`? | Metric routing | `<BU_KPI_OWNER_ROLE>` | Resolution policy | Wrong metric family | Open | Before BU YAML cert |
| BUS-05 | BUs that must never see customer-level grain? | Extra RLS | `<SECURITY_ARCHITECT_ROLE>` | Policies | Privacy incident | Open | Before customer dims |
| BUS-06 | Shared-service BUs with cross-BU mandate? | Privilege exceptions | `<BUSINESS_SPONSOR_ROLE>` | Cross-BU roles | Blocked or over-open | Open | Before cross-BU |
| BUS-07 | Display name vs code, including renames? | Synonyms/history | `<ORGANIZATION_STEWARD_ROLE>` | Synonym set | Broken trends | Open | Before synonym freeze |
| BUS-08 | Which BU products are certified vs raw? | Allowlist | `<BU_DATA_PRODUCT_OWNER_ROLE>` | Curated inventory | Staging queried | Assumed: only curated allowed | Before NLQ enablement |
| BUS-09 | Named `<BU_SEMANTIC_OWNER_ROLE>`? | Governance | `<BU_SPONSOR_ROLE>` | Onboarding | Orphan YAML | Open | Before onboarding |
| BUS-10 | One DSS project vs per-BU projects? | Topology | `<PLATFORM_OWNER_ROLE>` | Flow design | Rework | Open | Before DSS promotion |

---

## 3. Data

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| D-01 | Which curated products may be queried? | Allowlist | `<DATA_GOVERNANCE_ROLE>` | `data_products` | LLM table leakage | Open | Before SQL enablement |
| D-02 | Grain of `<ENTERPRISE_DATA_PRODUCT>` / primary fact? | Additivity | Steward | Metric grain | Fan-out | Open | Before metric cert |
| D-03 | Conformed keys across BU facts and enterprise dims? | Joins | `<ENTERPRISE_MASTER_DATA_TEAM>` | Relationship conditions | Bad cardinalities | Open | Before join approval |
| D-04 | Are customer/product/geo/org masters certified? | Shared dims | MDM team | Core dimensions | Local copies | Open | Before core freeze |
| D-05 | Source systems per curated product? | Lineage | `<DATA_PLATFORM_LEAD>` | Flow mapping | Unexplainable numbers | Open | Before lineage panel |
| D-06 | SCD types? | History | Governance | Join predicates | Wrong attribution | Open | Before historical trends |
| D-07 | Degenerate BU codes on facts? | RLS injection | Fact steward | `bu_filters.column` | Non-filtering RLS | Open | Before RLS |
| D-08 | Physical platform for curated products? | Dialect/executor | `<DATA_PLATFORM_LEAD>` | DEP-03 | Invalid SQL | Open | Before execution pin |
| D-09 | Competing marts for same grain? | Single product id | Governance | Inventory | Political metrics | Open | Before cert |
| D-10 | Views over raw mistaken as curated? | Zone audit | Platform | Queryable flags | Silent raw access | Open | Before allowlist |
| D-11 | Sample-value strategy without PII in prompts? | Retrieval | Privacy + governance | Slice policy | PII in logs | Open | Before retrieval |
| D-12 | Deleted/voided row representation? | Filters | Fact steward | `filter_sql` | Inflated counts | Open | Before count KPIs |
| D-13 | How does local KPI parquet `<LOCAL_KPI_PARQUET_PATH>` map to a certified curated product? | Fixture vs product | Steward + platform | D-01 instantiation | Treating download extract as certified | Assumed: development fixture only | Before domain cert |
| D-14 | Observed wide KPI extract columns (dimensions vs measures) — which are certified metrics vs deferred? | Prevent formula invention | `<ENTERPRISE_KPI_COUNCIL>` | Domain YAML scope | Premature certification | Open | Before domain expansion |

---

## 4. KPI definitions

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| KPI-01 | Certified formula/grain/filters for `<ENTERPRISE_PRIMARY_KPI>`? | Primary compile | KPI council | `metric.ent.primary_kpi` | Guessing | Open | Before compile |
| KPI-02 | Volume/value/count/ratio enterprise KPIs? | Metric family | KPI council | Enterprise metrics | Inconsistent compares | Open | Before compile |
| KPI-03 | Certified `<BU_OPERATIONAL_KPI>` vs enterprise primary? | BU extension | BU KPI owner | BU metric | Local/dashboard disagreement | Open | Before BU enable |
| KPI-04 | Additive / semi / non-additive classification? | Planner rules | KPI council | `additive_type` | Summed ratios | Open | Before planner |
| KPI-05 | `<ENTERPRISE_TARGET_KPI>` grain vs actuals? | Variance | FP&A | Target metric/joins | Wrong variance | Open | Before variance views |
| KPI-06 | FX method and rate type for value KPIs? | Comparability | Finance | Currency rules | Incomparable value | Open | Before value KPIs |
| KPI-07 | Canonical unit for `<BU_OPERATIONAL_KPI>`? | Unit conversion | BU KPI owner | Unit rules | Mixed units | Open | Before BU charts |
| KPI-08 | Mandatory filters per KPI? | Eligibility | KPI owner | `filter_sql` | Ineligible rows | Open | Before cert |
| KPI-09 | Restatement / as-of policy? | Reproducibility | Council + audit | As-of | Irreproducible answers | Open | Before pilot |
| KPI-10 | Official vs forbidden synonyms? | Ambiguity | Analytics lead | Synonym file | Glossary guessing | Open | Before synonym freeze |
| KPI-11 | Who certifies KPI changes and SLA to update NLQ? | Versioning | Council | Change process | Stale formulas | Open | Before change mgmt |
| KPI-12 | Explicit out-of-scope KPIs for v1? | Unsupported catalog | Sponsor | Refuse list | Pressure to invent | Open | Before pilot |

---

## 5. Semantic modelling

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| SM-01 | Conformed enterprise bus agreed? | Core dims | Governance | Dimension inventory | Local customers | Open | Before core freeze |
| SM-02 | Certified cardinalities? | Relationships | Fact steward | Cardinality fields | Duplicated metrics | Open | Before joins |
| SM-03 | Inner vs left on missing keys? | Join type | Governance | `join.type` | Dropped facts | Assumed LEFT pending SM-03 | Before join cert |
| SM-04 | Fiscal year start and week start? | Time intel | FP&A | `cal.ent.fiscal` | Wrong QTD | Open | Before time compile |
| SM-05 | Local BU fiscal calendars allowed? | Inheritance | Council | Calendar merge | Incomparable periods | Open | Before BU calendar overrides |
| SM-06 | Grain/SCD of `<BU_SPECIALTY_DIMENSION>`? | Drill-downs | BU data owner | Specialty entity | Unstable ranks | Open | Before BU drill |
| SM-07 | Unmatched FK labeling in answers? | Warnings | Analytics lead | Result validation | Silent Other | Open | Before result validation |
| SM-08 | BU override of enterprise KPI allowed? | Merge policy | Council + legal | `allow_metric_override` | Fractured numbers | Assumed false in v0.2.0 | Before override support |
| SM-09 | Multiple synonym matches ⇒ mandatory clarify? | Ambiguity | Analytics lead | Ambiguity rules | Hidden choice | Assumed yes | Before planner |
| SM-10 | Max subgraph size retrieved? | Tokens/leakage | Platform + architect | Slice rules | Full-model prompts | Open | Before retrieval tune |
| SM-11 | Deprecated metric UX? | Lifecycle | Semantic owner | Planner filters | Zombie metrics | Open | Before deprecation |
| SM-12 | Many-to-many bridges in v1? | Join complexity | Governance | Join patterns | Unconstrained graphs | Open | Before M2M |

---

## 6. Existing NL-to-SQL implementation

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| NLSQL-01 | Is canonical package path `python/nl_to_sql` or observed `src/nlq`? | Integration docs | NLQ tech lead | Layout assumption | Broken onboarding | Confirmed observed `src/nlq`; target `python/` Assumed | Before packaging |
| NLSQL-02 | What are the public entrypoints (functions/CLI/notebooks)? | Adapter targets | NLQ tech lead | Interface list | Wrong wrappers | Assumed: `NLQRunner.run`, `ask_nlq` | Before adapter |
| NLSQL-03 | Exact input/output JSON (or Python) contracts today? | Plan adapter | NLQ tech lead | Plan mapping | Silent field drops | Open | Before adapter |
| NLSQL-04 | Does current code already use SQLGlot validation? | Safety baseline | NLQ tech lead | Safety gap list | Duplicate or missing controls | Assumed yes in `src/nlq` | Before safety gap closure |
| NLSQL-05 | Current error-handling and repair limits? | Workflow alignment | NLQ tech lead | Repair policy | Infinite loops / opaque failures | Open | Before orchestration wiring |
| NLSQL-06 | Current DB connectivity (local SQL, parquet, DSS)? | Execution design | NLQ tech lead | Executor pin | Wrong backend | Open | Before FE integration |
| NLSQL-07 | Supported SQL dialect? | SQLGlot `read` | NLQ tech lead | Dialect pin | Invalid SQL | Open | Before validation pin |
| NLSQL-08 | Current semantic metadata usage (catalog/glossary/YAML)? | Avoid parallel truths | NLQ tech lead | Retrieval unification | Conflicting definitions | Open | Before semantic cutover |
| NLSQL-09 | What must **not** change in the existing package this phase? | Preserve investment | Sponsor + tech lead | Non-goals | Accidental rewrite | Confirmed: no rewrite this phase | Design freeze |
| NLSQL-10 | How should unsupported/unauthorized map to existing statuses? | UX consistency | Product + tech lead | Status enum | Confusing refusals | Open | Before FE |

---

## 7. Local Jupyter notebook structure

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| NB-01 | Which notebooks are canonical demos vs experiments? | Support surface | NLQ tech lead | Doc links | Users run stale notebooks | Open | Before enablement |
| NB-02 | Notebook entry: `ask_nlq` vs future `ask` alias? | DX | Tech lead | Exports | Fragmented APIs | Open | Before DX freeze |
| NB-03 | Do notebooks load local parquet, DSS, or both? | Data path | Tech lead | Fixture strategy | Irreproducible demos | Assumed local possible | Before demo pack |
| NB-04 | Should notebooks call the semantic planner before NL-to-SQL? | Design alignment | Architect | Notebook pattern | Bypassing plan | Assumed yes eventually | Before notebook refresh |
| NB-05 | Are Dataiku project notebooks in scope for local UX? | Scope | Platform | Doc boundaries | Split-brain guidance | Open | Before DSS phase |

---

## 8. Frontend and dashboard

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| FE-01 | Local FE framework (Streamlit vs other)? | Implementation | Sponsor + FE lead | FE stack | Rework | Open | Before FE code |
| FE-02 | Single-page dashboard + side chatbot vs separate routes? | IA | Product | Navigation | Poor discoverability | Open | Before FE code |
| FE-03 | Default enterprise KPI cards for v1? | Dashboard config | Analytics lead | Card config | Empty home | Open | Before dashboard MVP |
| FE-04 | BU default cards vs chatbot-only metrics? | Config vs allowlist | BU analytics | Card config | Users think missing card = unavailable | Open | Before FE MVP |
| FE-05 | May UI context restrict chatbot metrics? | Security/UX | Security + product | Contract: hints only | Accidental deny | Assumed: UI never security boundary | Design freeze |
| FE-06 | Chart library (Plotly vs other)? | Viz | FE lead | Chart specs | Rework | Assumed Plotly candidate | Before chart impl |
| FE-07 | Export formats and role gates? | CLS/row limits | Security | Export controls | Data scrape | Open | Before export |
| FE-08 | Where do metric tooltips/lineage render? | Trust UX | Product | Panels | Opaque numbers | Open | Before FE MVP |
| FE-09 | Local static mock vs live semantic bootstrap first? | Delivery plan | FE + architect | Sprint plan | Blocked FE | Open | Before FE sprint |
| FE-10 | Accessibility / locale requirements? | Compliance | Product | i18n | Exclusion | Open | Before FE pilot |

---

## 9. Chatbot experience

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| CHAT-01 | Persistent panel, standalone page, or both? | Placement | Product | IA | Low adoption | Open | Before FE |
| CHAT-02 | Suggested questions source? | Discovery | Analytics | Suggestions | Irrelevant prompts | Assumed semantic samples | Before FE |
| CHAT-03 | Clarification UX (chips vs free text)? | Ambiguity | Product | Clarification node UI | Abandonment | Open | Before FE |
| CHAT-04 | Always show supporting table? | Transparency | Product | Response layout | Overload | Open | Before FE |
| CHAT-05 | When to auto-chart vs ask? | Viz policy | Analytics | Chart node | Misleading charts | Open | Before chart rules |
| CHAT-06 | Must chatbot answer metrics not on dashboard? | Core requirement | Sponsor | Acceptance tests | Broken product promise | Confirmed required by design | Design freeze |
| CHAT-07 | Streaming vs synchronous answers? | UX/tech | FE + platform | API shape | Complexity | Open | Before API |
| CHAT-08 | Conversation memory scope? | Multi-turn | Architect | State | Cross-question leakage | Open | Before multi-turn |
| CHAT-09 | Developer trace mode in FE? | Support | Tech lead | FE modes | Unsupportable prod | Open | Before FE pilot |

---

## 10. Authentication

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| AUTH-01 | Local auth approach (dev user file, SSO stub, OS user)? | Local FE security | Security + platform | AuthN node | Open dashboard | Open | Before FE auth |
| AUTH-02 | How are roles assigned locally vs future IdP? | Mapping | IAM | Role bridge | Dual models | Open | Before auth |
| AUTH-03 | Service identity for batch/notebooks? | Least privilege | Platform | Batch auth | Overnight all-BU scans | Open | Before batch |
| AUTH-04 | Session timeout and logout UX? | Risk | Security | FE session | Stale entitlements | Open | Before FE pilot |

---

## 11. Security

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| SEC-01 | IdP and group→role mapping for future DSS? | AuthZ | Security | `maps_to_idp_group` | Locked or open agent | Open | Before DSS auth |
| SEC-02 | Break-glass steward process? | PII access | Security | Sensitive allow roles | Always deny/always allow | Open | Before PII dims |
| SEC-03 | Sensitive columns inventory? | CLS | Privacy | `sensitive_columns` | Leakage | Open | Before CLS |
| SEC-04 | Mask vs deny-only? | Actions | Privacy | CLS actions | Weak masking | Open | Before CLS |
| SEC-05 | RLS injection even if DB views exist? | Defense in depth | Security | `enforced_in_sql` | Single-layer failure | Assumed yes | Design freeze |
| SEC-06 | Audit field redaction policy? | Privacy vs debug | Audit + privacy | Audit schema | PII in logs | Open | Before audit sink |
| SEC-07 | LLM residency / Mesh region? | Compliance | Security | LLM pin | Regulatory breach | Open | Before Mesh |
| SEC-08 | Who may see SQL in UI? | Least privilege | Security | Response per role | Schema inference | Open | Before FE |
| SEC-09 | Row-limit / export “all rows” policy? | Scrape risk | Security | `max_rows` | Warehouse scrape | Assumed limited | Before export |
| SEC-10 | People/HR question denylist? | Policy | HR + legal | Unsupported class | Inference harm | Open | Before pilot |

---

## 12. Cross-Business-Unit comparison

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| XBU-01 | Who may compare BUs, which metrics/grains? | Privileged path | Sponsor + security | `can_query_cross_bu` | Secret access or none | Open | Before cross-BU UI |
| XBU-02 | Must compared BUs share formula/currency? | Comparability | Council | Planner guards | Fake rankings | Open | Before cross-BU |
| XBU-03 | Are BU-local metrics cross-comparable? | Q class | Council | Allowlist | Fake league tables | Assumed no | Design freeze |
| XBU-04 | Org restructures in history? | Restatement | Org steward | SCD | Misleading trends | Open | Before historical XBU |
| XBU-05 | Allocation methods certified or unsupported? | Allocation Qs | FP&A | Unsupported vs metric | Invented allocations | Open | Before allocation Qs |
| XBU-06 | Aggregate peer compare without peer row detail? | Privilege split | Security | Aggregate role | Row leakage | Open | Before peer compare |
| XBU-07 | Legally firewalled BUs? | Deny rules | Legal | Denylist | Regulatory breach | Open | Before XBU |
| XBU-08 | Official peer sets? | Clarification | Analytics | Peer dimension | Ad hoc compares | Open | Before peer UX |

---

## 13. Performance

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| P-01 | Interactive p95 latency budget? | Timeouts | Platform | Timeouts | Abandonment | Open | Before FE SLA |
| P-02 | Peak concurrency? | Sizing | Platform | Capacity | Incidents | Open | Before pilot |
| P-03 | Partitioning aligned to filters? | Physical design | Data platform | DDL | Timeouts | Open | Before scale |
| P-04 | Certified summary products allowed? | Grain ladder | Semantic owner | Extra products | Inconsistent grains | Open | Before aggregates |
| P-05 | Max rows to LLM vs chart? | Tokens | Architect | Truncation | Overflow | Open | Before answer node tune |
| P-06 | SQL-only compute; pandas presentation only? | Auditability | Architect | Analytics scope | Hidden compute | Assumed yes | Design freeze |

---

## 14. Data freshness

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| FR-01 | SLA hours per product? | Freshness rules | Data product owners | `sla_hours` | Stale as live | Open | Before freshness UI |
| FR-02 | Trusted freshness column? | Runtime check | Owners | `freshness_column` | False stale/fresh | Open | Before freshness |
| FR-03 | Warn vs block when stale? | Result validation | Sponsor + council | `stale_behavior` | Bricked or silent stale | Open | Before result validation |
| FR-04 | Partial BU freshness in cross-BU views? | Comparability | Governance | Warnings | Mixed as-of leagues | Open | Before XBU |
| FR-05 | Expose “data as of” always? | Trust | Analytics | Answer template | Ambiguity | Assumed yes | Design freeze |
| FR-06 | Who is paged on SLA miss? | Ops | Platform | Monitoring | Unowned outages | Open | Before monitoring |

---

## 15. Evaluation

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| EV-01 | Promotion score gates? | Release | Eval owner + platform | CI/eval | Regressions | Open | Before release |
| EV-02 | Golden-set owners per BU/enterprise? | Maintenance | Eval owner | Stewardship | Rotting fixtures | Open | Before golden sets |
| EV-03 | Expected answers before KPI cert? | Honest eval | Eval owner | Routing-only vs numeric | Fake accuracy | Assumed routing/safety first | Design freeze |
| EV-04 | Fraction unauthorized/unsupported/`not_on_dashboard`? | Safety + chatbot independence | Security + product | Bank mix | Easy-only accuracy | Open | Before bank v1 |
| EV-05 | Hallucination definition? | Scoring | Eval owner | Metrics | Fluent wrong | Open | Before harness |
| EV-06 | Gold SQL vs result equivalence? | Brittle tests | Architect | Scorer | False negatives | Open | Before SQL eval |
| EV-07 | Eval cadence? | Cost | Platform | Workflows | No signal / Mesh cost | Open | Before CI |
| EV-08 | Feedback without poisoning labels? | Human loop | Eval owner | Feedback workflow | Popular wrong labels | Open | Before feedback |

---

## 16. Governance

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| GOV-01 | RACI for metric/join/security/prompt? | Operating model | Governance | RACI | Unreviewed changes | Open | Before onboarding |
| GOV-02 | Approval board for `ent.core` versions? | Promotion | Semantic owner | Version policy | Hotfixes | Open | Before release |
| GOV-03 | Major vs minor metric changes? | SemVer | Semantic owner | Compatibility | Silent breaks | Open | Before change mgmt |
| GOV-04 | Prompt files change-controlled like metrics? | Version everything | Architect | Prompt bundles | Untracked drift | Assumed yes | Design freeze |
| GOV-05 | Deprecation window? | Merge safety | Council | Deprecation | Broken BU YAML | Open | Before deprecate |
| GOV-06 | Human review for high-risk classes? | Hold-out node | Audit + sponsor | Graph branch | Latency or risk | Open | Before pilot |
| GOV-07 | NLQ must not replace statutory reports? | Scope | Legal | Unsupported | Screenshot compliance | Open | Before pilot |
| GOV-08 | Kill switch owner? | Incidents | Platform | Feature flag | Lingering incidents | Open | Before pilot |
| GOV-09 | Vendor/contractor access? | Identity lifecycle | IAM | Auth exceptions | Standing privilege | Open | Before external users |
| GOV-10 | Audit documentation per semantic version? | Auditability | Audit | Release checklist | Unexplainable history | Open | Before release |
| GOV-11 | External GitHub semantic_layer repository availability and authority? | Import policy | Semantic owner | External assets | 404 / unverified source | Confirmed 404 at design time; remains Open for authority | Before external import |

---

## 17. Deployment

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| DEP-01 | DSS project topology? | Flow/IAM | Platform | Flow design | Rework | Open | Before DSS phase |
| DEP-02 | Promote local FE, native webapp, API, or all? | Consumption | Sponsor + platform | Prod surface | Split-brain | Open | Before DSS phase |
| DEP-03 | SQL engine + DSS connection? | Dialect/timeout | Data platform | Executor | Wrong cluster | Open | Before DSS SQL |
| DEP-04 | LLM Mesh connection / model pin? | Quality/residency | Platform + security | `llm_model_pin` | Drift | Open | Before Mesh |
| DEP-05 | GitHub → DSS promotion path? | No hot-edit | Platform | CI/CD | Config drift | Open | Before promotion |
| DEP-06 | Runtime location of YAML? | Load path | Architect | Loader | Stale YAML | Open | Before DSS sync |
| DEP-07 | Read-only warehouse role? | Defense | Data platform | Connection IAM | DML risk | Assumed required | Before DSS SQL |
| DEP-08 | Secrets injection? | Security | Security | DSS connections | Secrets in git | Open | Before DSS |
| DEP-09 | Rollback of semantic_version? | Incidents | Platform | Pin previous | Prolonged wrong KPIs | Open | Before release |
| DEP-10 | Is current phase production deployment? | Scope | Sponsor | Non-goal | Premature prod | Confirmed: not production | Design freeze |

---

## 18. Support

| ID | Question | Why it matters | Expected respondent | Decision affected | Risk if unanswered | Status | Resolve by |
|---|---|---|---|---|---|---|---|
| SUP-01 | Support channel/SLA for wrong numbers? | Trust recovery | Support + BU analytics | Runbook | Silent abandonment | Open | Before pilot |
| SUP-02 | Alert routing for eval/freshness/auth spikes? | Ops | Platform | Monitoring | Silent failure | Open | Before monitoring |
| SUP-03 | Contest metric vs report bug? | Ticket taxonomy | Council + support | Routing | Misrouted work | Open | Before support |
| SUP-04 | What support may see (SQL, question, identity)? | Privacy | Privacy | Support console | PII in tickets | Open | Before support tooling |
| SUP-05 | In-product known limitations copy? | Deflection | Analytics | Refuse copy | Repeat unsupported Qs | Open | Before FE |
| SUP-06 | Local audit/feedback storage location? | Dev ops | Platform | Local sinks | Lost traces | Open | Before local FE |
| SUP-07 | Retention for audit/feedback? | Legal | Audit | Lifecycle | Over/under retention | Open | Before pilot |

---

## 19. Coverage of critical unresolved decisions

| Topic | Primary IDs |
|---|---|
| Existing NL-to-SQL layout/IO/safety | NLSQL-01…NLSQL-10 |
| Notebooks | NB-01…NB-05 |
| Local FE + chatbot | FE-01…FE-10, CHAT-01…CHAT-09 |
| Local auth | AUTH-01…AUTH-04 |
| KPI / fiscal / FX | KPI-01, KPI-06, SM-04 |
| Cross-BU / override / stale | XBU-01, SM-08, FR-03 |
| Future DSS | DEP-01…DEP-10 |
| External semantic GitHub | GOV-11 |
| Local KPI parquet mapping | D-13, D-14 |

---

## 20. Workshop output template

```text
id: NLSQL-03
status: Open | Assumed | Confirmed | Not applicable
answer: <free text; no silent invention>
owner: <role>
date: <ISO date>
effect_on_yaml: <objects>
effect_on_plan_contract: <fields>
effect_on_frontend: <screens>
design_phase_resolved: <phase name>
```
