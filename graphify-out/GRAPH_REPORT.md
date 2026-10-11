# Graph Report - .  (2026-10-11)

## Corpus Check
- 106 files · ~142,141 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1684 nodes · 2865 edges · 66 communities detected
- Extraction: 66% EXTRACTED · 34% INFERRED · 0% AMBIGUOUS · INFERRED: 968 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `Settings` - 234 edges
2. `PgStore` - 201 edges
3. `Push` - 152 edges
4. `OllamaEmbedder` - 147 edges
5. `HybridSearch` - 98 edges
6. `SearchCache` - 72 edges
7. `WebSearchConnector` - 55 edges
8. `SocialSearchConnector` - 52 edges
9. `OpenRouterClient` - 48 edges
10. `TaskScheduler` - 33 edges

## Surprising Connections (you probably didn't know these)
- `Tests for init scan — helpers + integration (updated detection, supersede flow).` --uses--> `Settings`  [INFERRED]
  tests/test_init_scan.py → src/config.py
- `Integration tests for init_scan() — updated file detection, supersede, skip unch` --uses--> `Settings`  [INFERRED]
  tests/test_init_scan.py → src/config.py
- `Scan a directory with markdown files, verify they get indexed.` --uses--> `Settings`  [INFERRED]
  tests/test_init_scan.py → src/config.py
- `Second scan of unchanged files should skip them with skipped_unchanged.` --uses--> `Settings`  [INFERRED]
  tests/test_init_scan.py → src/config.py
- `Modified file should trigger supersede + re-index (not new index).` --uses--> `Settings`  [INFERRED]
  tests/test_init_scan.py → src/config.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (208): Search cache — LRU + TTL cache for search results., Thread-safe LRU + TTL search result cache., SearchCache, Claude Code hook — auto-ingest κ/ψ files into synapse via PostToolUse hook.  Rep, Check if path is inside a κ/ or ψ/ vault directory., Derive project name from path containing ψ/ or κ/., CLI entry point: python3 -m src.ingest.claude_hook <file-path>, Ingest a single file into synapse if it's a κ/ψ vault file.      Returns the pus (+200 more)

### Community 1 - "Community 1"
Cohesion: 0.03
Nodes (12): Tests for LINE webhook handler — auto-ingest pipeline v2., LINE doesn't render markdown — _strip_markdown removes all formatting., Simulate a typical LLM response with markdown that LINE can't render., TestBuildKnowledgeDoc, TestChatIdFromEvent, TestEventToScope, TestIsCommand, TestIsGroupChat (+4 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (21): Tests for PgStore — CRUD, FTS search, supersession, concepts, trace., After supersede, find_by_source_file returns the NEW doc (not the old one)., Callers without include_hash should still work., Integration tests for pgvector — embedding storage, similarity search, tag enric, Store an embedding and retrieve via cosine similarity., Vector search results include tags from junction table., Vector search filters by tags via junction table., Clearing embedding removes doc from vector search results. (+13 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (19): check_due_tasks(), _format_alert_message(), _is_obsidian_vault(), Format an alert message for LINE notification., Send a push message via LINE Messaging API. Errors are logged, never raised., Check for due scheduled_tasks and create alert_log entries.      If access_token, _send_push(), TaskScheduler (+11 more)

### Community 4 - "Community 4"
Cohesion: 0.04
Nodes (2): parseArgs(), runCommand()

### Community 5 - "Community 5"
Cohesion: 0.04
Nodes (13): Tests for init scan — helpers + integration (updated detection, supersede flow)., Integration tests for init_scan() — updated file detection, supersede, skip unch, Scan a directory with markdown files, verify they get indexed., Second scan of unchanged files should skip them with skipped_unchanged., Modified file should trigger supersede + re-index (not new index)., Dry run should not write to database., Empty files should be skipped, not errored., Files under oracle project structure get oracle metadata extracted. (+5 more)

### Community 6 - "Community 6"
Cohesion: 0.04
Nodes (18): Retrieve package — hybrid search with RRF fusion., Run full reconcile: defrag + detox.      When cross_scope=True, both defrag and, reconcile(), Social search connector — search social platforms for topics.  Supports: twitter, Search Hacker News via Algolia API (no auth needed)., Single social search result., Search a social platform for a query., Search Twitter/X via Nitter (no API key needed) or fallback to scraping. (+10 more)

### Community 7 - "Community 7"
Cohesion: 0.04
Nodes (10): Tests for daemon — PID file management, Docker detection, signal handling., TestGetDockerContainerStatus, TestGetStatus, TestIsRunning, TestIsRunningInDocker, TestReadPid, TestRemovePid, TestSetupSignals (+2 more)

### Community 8 - "Community 8"
Cohesion: 0.04
Nodes (15): Tests for HTTP API routes — FastAPI TestClient tests., TestAPIConcepts, TestAPIGetDocument, TestAPIHealth, TestAPILineWebhook, TestAPIList, TestAPIPush, TestAPIReconcileLog (+7 more)

### Community 9 - "Community 9"
Cohesion: 0.05
Nodes (6): Tests for LINE webhook handler v2 — full chatbot features., TestAnswerQuestion, TestHandleCommand, TestIsCommand, TestIsQuestion, TestProcessLineEventsFullFlow

### Community 10 - "Community 10"
Cohesion: 0.07
Nodes (18): Exception, _merge_dense_results(), Hybrid search — pgvector dense + PostgreSQL tsvector → Reciprocal Rank Fusion., Doc-level ANN + chunk-level ANN, merged by best score.          Long docs (>MAX_, Search across multiple scopes, merging results via RRF for fairness., Merge doc-level and chunk-level dense hits into one ranked list.      - Best sco, reciprocal_rank_fusion(), SearchError (+10 more)

### Community 11 - "Community 11"
Cohesion: 0.05
Nodes (9): Tests for registry — project registration, scope detection, backup/restore., TestDetectScope, TestGetAllScopes, TestListProjects, TestRegisterProject, TestRestoreRegistryBackup, TestSaveRegistryBackup, TestUnregisterProject (+1 more)

### Community 12 - "Community 12"
Cohesion: 0.06
Nodes (20): api_add_search_topic(), api_chat(), api_fix_doctype(), api_ingest_file(), api_ingest_website(), api_ingest_youtube(), api_models(), api_push() (+12 more)

### Community 13 - "Community 13"
Cohesion: 0.06
Nodes (15): _ensure_list(), _init_codecs(), _parse_interval(), PostgreSQL store — CRUD, FTS search, vector search, supersession, concepts, trac, Insert tags into junction tables (tags + document_tags)., Insert concepts into junction tables (concepts + document_concepts)., Get pending tasks where due_date - alert_before <= now and not yet alerted in th, Batch update doc_type for documents matching criteria.          Used to fix inco (+7 more)

### Community 14 - "Community 14"
Cohesion: 0.07
Nodes (11): build_parser(), cli_main(), _cmd_init(), _cmd_list(), _cmd_push(), _cmd_search(), _cmd_search_cross(), _do_shutdown() (+3 more)

### Community 15 - "Community 15"
Cohesion: 0.06
Nodes (8): Tests for Obsidian Writer — sanitize, frontmatter, wikilinks, write to vault., If a file with the same name already exists, append a counter., Doc with no trace links should show fallback message., TestBuildFrontmatter, TestBuildWikilinks, TestSanitizeFilename, TestWriteDocumentToObsidian, TestWriteSearchResultsToObsidian

### Community 16 - "Community 16"
Cohesion: 0.06
Nodes (9): Tests for SearchCache — LRU + TTL thread-safe cache., TestCacheClear, TestCacheGetPut, TestCacheInvalidate, TestCacheKeyConstruction, TestCacheLRU, TestCacheStats, TestCacheThreadSafety (+1 more)

### Community 17 - "Community 17"
Cohesion: 0.08
Nodes (15): _guess_image_ext(), _ollama_ocr(), _ollama_summarize(), OpenRouterError, OpenRouter client — cheap, reliable LLM with Ollama fallback., OCR an image using vision model. Returns text or None if no text found., Fallback summarization via Ollama., Base error for OpenRouter client. (+7 more)

### Community 18 - "Community 18"
Cohesion: 0.09
Nodes (5): MockSettings, Tests for local-only URL validation., TestCheckAndWarn, TestValidateAllSettings, TestValidateLocalUrl

### Community 19 - "Community 19"
Cohesion: 0.15
Nodes (28): _answer_question(), _build_knowledge_doc(), _chat_id_from_event(), _chat_with_user(), _download_line_media(), event_to_scope(), event_to_tags(), _extract_task_info() (+20 more)

### Community 20 - "Community 20"
Cohesion: 0.16
Nodes (21): MockAsyncClient, MockResponse, MockSettings, _patch_httpx(), Tests for reconcile.llm — analyze_conflict and summarize_content., test_analyze_conflict_all_models_fail_returns_none(), test_analyze_conflict_exception(), test_analyze_conflict_falls_back_when_primary_missing() (+13 more)

### Community 21 - "Community 21"
Cohesion: 0.21
Nodes (22): _make_analysis(), MockEmbedder, MockPgStore, MockSettings, Tests for reconcile.detox — conflict detection and resolution., Return other docs from list_docs as mock ANN candidates., test_detox_analyze_conflict_no_conflict(), test_detox_analyze_conflict_returns_none() (+14 more)

### Community 22 - "Community 22"
Cohesion: 0.07
Nodes (5): Integration tests — Push pipeline with dual-store write and oracle path detectio, Same content with different tags still deduplicates by content_hash., TestPushOraclePathDetection, TestPushPipeline, TestSemanticDedup

### Community 23 - "Community 23"
Cohesion: 0.08
Nodes (4): Tests for CLI commands — parser structure and command dispatch., TestCLIParser, TestCommandDispatch, TestParseHelpers

### Community 24 - "Community 24"
Cohesion: 0.09
Nodes (6): Tests for guided question flow — pending_review confirmation logic., TestFormatGuidedQuestion, TestIsGuidedAnswer, TestParseEditInstructions, TestPendingReviewFlow, TestShouldAskGuidedQuestions

### Community 25 - "Community 25"
Cohesion: 0.09
Nodes (5): Tests for hook installer and context injection script., TestBuildContextInjectHookEntry, TestFindHookEntry, TestInstallHooks, TestLoadSaveSettings

### Community 26 - "Community 26"
Cohesion: 0.1
Nodes (4): Tests for Claude ingest pipeline — claude_hook.py., TestExtractTaskInfo, TestIsVaultFile, TestResolveSourceProject

### Community 27 - "Community 27"
Cohesion: 0.1
Nodes (2): Tests for concept extraction — hashtags and PascalCase identifiers., TestExtractConcepts

### Community 28 - "Community 28"
Cohesion: 0.1
Nodes (4): Tests for config — Settings dataclass with YAML loading and reload., TestSettingsDefaults, TestSettingsFromYaml, TestSettingsReload

### Community 29 - "Community 29"
Cohesion: 0.13
Nodes (12): _async_body(), _make_request(), Tests for webhook HMAC signature verification., test_invalid_signature_raises_401(), test_missing_signature_raises_401(), test_no_secret_skips_verification(), test_plain_hex_signature(), test_valid_signature() (+4 more)

### Community 30 - "Community 30"
Cohesion: 0.11
Nodes (5): Tests for MCP server tool handlers., TestMCPPush, TestMCPScopeStats, TestMCPSearch, TestMCPTrace

### Community 31 - "Community 31"
Cohesion: 0.11
Nodes (3): Tests for vault_migrator — scan_memory_files and migrate., TestMigrate, TestScanMemoryFiles

### Community 32 - "Community 32"
Cohesion: 0.11
Nodes (5): Tests for oracle path mapping., TestExtractMetadata, TestExtractOracleName, TestValidateDocType, TestValidateTraceRelation

### Community 33 - "Community 33"
Cohesion: 0.16
Nodes (18): get_docker_container_status(), get_status(), is_running(), is_running_in_docker(), Daemon lifecycle — PID file management, signal handling, status., Stop a running daemon by sending SIGTERM, or stop Docker container. Returns stat, Detect if current process is inside a Docker container., Get daemon status. Checks PID file first, then Docker fallback. (+10 more)

### Community 34 - "Community 34"
Cohesion: 0.16
Nodes (17): detect_project_name(), get_all_project_names(), list_projects(), Project registry — PostgreSQL-backed project registration for cross-project sear, Restore registered projects from JSON backup if DB is empty.      Returns {resto, Auto-detect project name from path. Returns last directory component, sanitized., Validate project name: lowercase, alphanumeric, dashes only, 1-64 chars., Register a project with the vault. Auto-detect project name if not provided. (+9 more)

### Community 35 - "Community 35"
Cohesion: 0.12
Nodes (4): Tests for tag_rules engine — CRUD, seeding, rule application., TestApplyTagRules, TestSeedDefaultRules, TestTagRulesCRUD

### Community 36 - "Community 36"
Cohesion: 0.13
Nodes (3): Tests for assistant scheduler — scheduled_tasks + alert_log CRUD., TestAlertLogCRUD, TestScheduledTasksCRUD

### Community 37 - "Community 37"
Cohesion: 0.24
Nodes (11): MockPgStore, Tests for reconcile.defrag — duplicate compaction., test_defrag_dry_run(), test_defrag_empty_docs(), test_defrag_finds_duplicates_and_supersedes(), test_defrag_missing_full_doc(), test_defrag_multiple_groups(), test_defrag_no_duplicates() (+3 more)

### Community 38 - "Community 38"
Cohesion: 0.2
Nodes (13): _build_frontmatter(), _build_wikilinks(), Obsidian Writer — write Synapse documents to Obsidian vault as .md files.  Produ, Write search result documents to Obsidian vault.      Args:         pg: PgStore, Convert a title to a safe filename. Uses doc_id[:8] suffix to avoid collisions., Serialize a value for YAML frontmatter., Build YAML frontmatter block from document fields., Build [[wikilinks]] from related document titles, deduplicated. (+5 more)

### Community 39 - "Community 39"
Cohesion: 0.18
Nodes (10): extract_metadata(), extract_oracle_name(), is_content_type(), is_event_type(), Oracle path mapping — kappa/psi brain structure to synapse metadata.  Document t, Validate and normalize doc_type. Resolves legacy aliases., Check if doc_type is content-based (knowledge, note, idea, etc.)., Check if doc_type is event-based (todo, reminder, payment, etc.). (+2 more)

### Community 40 - "Community 40"
Cohesion: 0.23
Nodes (11): build_context_inject_hook_entry(), find_hook_entry(), install_hooks(), load_settings(), Hook installer — register synapse hooks in ~/.claude/settings.json., Load settings.json, return empty dict if not found., Save settings.json with pretty formatting., Find a hook entry containing the marker string in any command. (+3 more)

### Community 41 - "Community 41"
Cohesion: 0.18
Nodes (7): issue009_store(), ISSUE-009 causal tests — unqualified created_at breaks tags-filtered queries.  R, Create a throwaway DB with the real schema; drop it afterwards., list_docs must resolve created_at against knowledge_documents only., search_fts (FTS + ILIKE paths) must survive the tags join., The ILIKE phase has its own ORDER BY created_at — cover it too., TestTagsFilteredQueries

### Community 42 - "Community 42"
Cohesion: 0.27
Nodes (9): _analyze_and_resolve(), _count_action(), detox(), _find_candidates(), Detox — detect and resolve conflicts using pgvector ANN pre-filter + LLM., Tally reportable actions from conflict resolutions., Analyze conflict between two docs and optionally resolve.      Returns:, Detect conflicts between documents using ANN pre-filter + LLM analysis.      Ste (+1 more)

### Community 43 - "Community 43"
Cohesion: 0.24
Nodes (9): create_traces_from_links(), extract_links(), Obsidian-style link parsing — [[Link Title]] and [[Link Title|Display]]., Extract all Obsidian-style links from content.      Returns list of dicts: {targ, Parse Obsidian links in content and create trace links to referenced docs., Replace Obsidian links with markdown links using resolved IDs.      resolver: di, Resolve link targets to document IDs.      Searches across all documents first,, replace_links() (+1 more)

### Community 44 - "Community 44"
Cohesion: 0.27
Nodes (9): _compare_signatures(), _generate_signature(), Webhook signature verification — HMAC-SHA256., Generate HMAC-SHA256 hex digest for payload bytes., Constant-time comparison to prevent timing attacks., Verify webhook HMAC signature. Returns raw body bytes if valid.      Raises HTTP, Sign payload with secret for testing / client use., sign_payload() (+1 more)

### Community 45 - "Community 45"
Cohesion: 0.39
Nodes (8): init_scan(), read_docx_file(), read_file_content(), read_pdf_file(), read_text_file(), scan_files(), should_skip(), summarize_with_llm()

### Community 46 - "Community 46"
Cohesion: 0.25
Nodes (0): 

### Community 47 - "Community 47"
Cohesion: 0.25
Nodes (1): Tests for Obsidian-style link parsing.

### Community 48 - "Community 48"
Cohesion: 0.32
Nodes (7): check_and_warn(), Local-only enforcement — validate all service URLs are localhost., Validate that a URL points to localhost only. Returns list of violations., Validate all service URLs in settings are localhost. Returns list of violations., Validate settings and log warnings for violations. Returns list of violations., validate_all_settings(), validate_local_url()

### Community 49 - "Community 49"
Cohesion: 0.29
Nodes (7): apply_tag_rules(), _extract_task_info_from_content(), Tag Rules Engine — applies tag_rules when documents are stored.  When a document, Ensure default tag rules exist. Always upserts — restores defaults on restart., Apply matching tag rules after a document is stored.      Returns list of action, Extract task metadata from content text.      Reuses the same detection logic as, seed_default_rules()

### Community 50 - "Community 50"
Cohesion: 0.29
Nodes (2): Tests for FastAPI app lifecycle — startup, shutdown, graceful degradation., TestAppLifecycle

### Community 51 - "Community 51"
Cohesion: 0.33
Nodes (3): from_yaml(), Configuration — settings from environment variables + optional YAML config., Re-read settings from env vars + config file (for SIGHUP).

### Community 52 - "Community 52"
Cohesion: 0.33
Nodes (5): analyze_conflict(), LLM client for reconcile — conflict analysis and content synthesis via Ollama., Use LLM to summarize content. Returns summary or None., Use a local Ollama LLM to analyze whether two documents conflict.      Tries eac, summarize_content()

### Community 53 - "Community 53"
Cohesion: 0.7
Nodes (4): ingest_file(), _is_vault_file(), main(), _resolve_source_project()

### Community 54 - "Community 54"
Cohesion: 0.5
Nodes (4): create_app(), _format_tool_error(), run_server(), _validate_tool_input()

### Community 55 - "Community 55"
Cohesion: 0.83
Nodes (3): measure(), run(), seed()

### Community 56 - "Community 56"
Cohesion: 0.5
Nodes (3): Benchmark — measure synapse retrieval quality  Metrics: 1. Token savings: contex, Run benchmark and return metrics., run_benchmark()

### Community 57 - "Community 57"
Cohesion: 0.5
Nodes (3): extract_concepts(), Concept extraction from content — hashtags and key terms., Extract concepts from content.      Returns deduplicated list of:     - Hashtags

### Community 58 - "Community 58"
Cohesion: 0.83
Nodes (3): main(), migrate(), scan_memory_files()

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (0): 

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (0): 

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): Primary judge model missing (404) -> fallback model answers.

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): Every judge model 404s -> must return None (caller reports llm_errors).

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Accept signatures without 'sha256=' prefix.

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Load settings from YAML file, falling back to env vars for missing keys.

## Knowledge Gaps
- **106 isolated node(s):** `Tests for assistant scheduler — scheduled_tasks + alert_log CRUD.`, `Tests for tag_rules engine — CRUD, seeding, rule application.`, `TestRegisterProject`, `TestUnregisterProject`, `TestListProjects` (+101 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 59`** (2 nodes): `fix_line_tasks.py`, `main()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (2 nodes): `check_line_docs.py`, `main()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `vite.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `Primary judge model missing (404) -> fallback model answers.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `Every judge model 404s -> must return None (caller reports llm_errors).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `Accept signatures without 'sha256=' prefix.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `Load settings from YAML file, falling back to env vars for missing keys.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Settings` connect `Community 0` to `Community 1`, `Community 3`, `Community 5`, `Community 6`, `Community 8`, `Community 41`, `Community 9`, `Community 10`, `Community 13`, `Community 17`, `Community 51`, `Community 28`?**
  _High betweenness centrality (0.240) - this node is a cross-community bridge._
- **Why does `PgStore` connect `Community 0` to `Community 2`, `Community 3`, `Community 34`, `Community 38`, `Community 41`, `Community 42`, `Community 10`, `Community 13`?**
  _High betweenness centrality (0.136) - this node is a cross-community bridge._
- **Why does `synapse — FastAPI app + CLI entry point.` connect `Community 0` to `Community 3`, `Community 14`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Are the 232 inferred relationships involving `Settings` (e.g. with `TestShouldSkip` and `TestScanFiles`) actually correct?**
  _`Settings` has 232 INFERRED edges - model-reasoned connections that need verification._
- **Are the 141 inferred relationships involving `PgStore` (e.g. with `Test configuration — shared V2 fixtures for PostgreSQL-based tests.` and `TestTagsFilteredQueries`) actually correct?**
  _`PgStore` has 141 INFERRED edges - model-reasoned connections that need verification._
- **Are the 142 inferred relationships involving `Push` (e.g. with `Test configuration — shared V2 fixtures for PostgreSQL-based tests.` and `FakeEmbedder`) actually correct?**
  _`Push` has 142 INFERRED edges - model-reasoned connections that need verification._
- **Are the 139 inferred relationships involving `OllamaEmbedder` (e.g. with `Test configuration — shared V2 fixtures for PostgreSQL-based tests.` and `TestOllamaEmbedder`) actually correct?**
  _`OllamaEmbedder` has 139 INFERRED edges - model-reasoned connections that need verification._