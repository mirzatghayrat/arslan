-- The expert-era tables as a v0.1.64 install had them before C7c-5b, CREATE text copied from
-- sqlite_master after a fresh boot at d33e75f66 (C7c-4). C7c-5b removed their models, so tests that need an
-- upgraded install's shape load this file with foreign keys off (tests/server/pre_0103.py).
-- Statements end with a line holding only ';'. Sections start with '-- section: <name>'.

-- section: tables
CREATE TABLE spawns (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	domain_category VARCHAR(50) NOT NULL, 
	domain_subcategory VARCHAR(50), 
	capabilities JSON, 
	persona_role VARCHAR(200), 
	persona_tone VARCHAR(50), 
	system_prompt TEXT NOT NULL, 
	template_used VARCHAR(100), 
	generation_level INTEGER, 
	config JSON, 
	is_default BOOLEAN DEFAULT '0' NOT NULL, 
	level INTEGER, 
	memory_facts JSON, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (name)
)
;
CREATE TABLE chat_messages (
	id INTEGER NOT NULL, 
	spawn_id INTEGER NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	timestamp DATETIME, 
	archived BOOLEAN DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id)
)
;
CREATE TABLE feedback (
	id INTEGER NOT NULL, 
	spawn_id INTEGER NOT NULL, 
	session_id VARCHAR(50) NOT NULL, 
	message_id INTEGER, 
	user_action VARCHAR(20) NOT NULL, 
	edits JSON, 
	quality_signal INTEGER, 
	timestamp DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id)
)
;
CREATE TABLE spawn_capabilities (
	id INTEGER NOT NULL, 
	spawn_id INTEGER NOT NULL, 
	kind VARCHAR(10) NOT NULL, 
	ref_key VARCHAR(60) NOT NULL, 
	grant VARCHAR(10) NOT NULL, 
	granted_by VARCHAR(20) NOT NULL, 
	expires_turn INTEGER, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (spawn_id, kind, ref_key), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id) ON DELETE CASCADE
)
;
CREATE INDEX ix_spawn_capabilities_spawn_id ON spawn_capabilities (spawn_id)
;
CREATE TABLE spawn_phases (
	id INTEGER NOT NULL, 
	conversation_id VARCHAR(50) NOT NULL, 
	spawn_id INTEGER NOT NULL, 
	phase VARCHAR(20) NOT NULL, 
	direction TEXT NOT NULL, 
	updated_at VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id)
)
;
CREATE INDEX ix_spawn_phases_conversation_id ON spawn_phases (conversation_id)
;
CREATE TABLE conversation_spawns (
	id INTEGER NOT NULL, 
	conversation_id VARCHAR(50) NOT NULL, 
	spawn_id INTEGER NOT NULL, 
	joined_via VARCHAR(16) NOT NULL, 
	joined_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_conversation_spawn UNIQUE (conversation_id, spawn_id), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id)
)
;
CREATE INDEX ix_conversation_spawns_conversation_id ON conversation_spawns (conversation_id)
;
CREATE TABLE spawn_collections (
	id INTEGER NOT NULL, 
	spawn_id INTEGER NOT NULL, 
	collection_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (spawn_id, collection_id), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id) ON DELETE CASCADE, 
	FOREIGN KEY(collection_id) REFERENCES collections (id) ON DELETE CASCADE
)
;
CREATE INDEX ix_spawn_collections_collection_id ON spawn_collections (collection_id)
;
CREATE INDEX ix_spawn_collections_spawn_id ON spawn_collections (spawn_id)
;
CREATE TABLE evolution_proposals (
	id INTEGER NOT NULL, 
	spawn_id INTEGER NOT NULL, 
	candidate_prompt TEXT NOT NULL, 
	gate_passed BOOLEAN NOT NULL, 
	evidence JSON, 
	status VARCHAR(20) NOT NULL, 
	base_prompt_sha VARCHAR(64), 
	created_at DATETIME, 
	promoted_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id) ON DELETE CASCADE
)
;
CREATE INDEX ix_evolution_proposals_spawn_id ON evolution_proposals (spawn_id)
;
CREATE TABLE synthetic_tasks (
	id INTEGER NOT NULL, 
	spawn_id INTEGER NOT NULL, 
	version INTEGER NOT NULL, 
	task TEXT NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	source_run_id INTEGER, 
	split_side VARCHAR(10) NOT NULL, 
	status VARCHAR(10) DEFAULT 'active' NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id) ON DELETE CASCADE
)
;
CREATE INDEX ix_synthetic_tasks_spawn_id ON synthetic_tasks (spawn_id)
;
CREATE TABLE evolution_attempts (
	id INTEGER NOT NULL, 
	spawn_id INTEGER NOT NULL, 
	started_at DATETIME, 
	finished_at DATETIME, 
	outcome VARCHAR(20), 
	source VARCHAR(10), 
	estimate JSON, 
	actual JSON, 
	proposal_id INTEGER, 
	reason TEXT DEFAULT '' NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id) ON DELETE CASCADE
)
;
CREATE INDEX ix_evolution_attempts_spawn_id ON evolution_attempts (spawn_id)
;
CREATE TABLE persona_seeds (
	id INTEGER NOT NULL, 
	slug VARCHAR(120) NOT NULL, 
	division VARCHAR(80), 
	name VARCHAR(160), 
	identity TEXT, 
	mission TEXT, 
	rules TEXT, 
	deliverables TEXT, 
	workflow TEXT, 
	success_metrics TEXT, 
	raw TEXT NOT NULL, 
	source VARCHAR(200), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (slug)
)
;

-- section: triggers
-- What memory activation put on spawns (memory_activation._guard_spawn_preferences).
CREATE TRIGGER guard_legacy_spawn_preferences BEFORE UPDATE OF memory_facts ON spawns
        WHEN COALESCE(NEW.memory_facts,'[]') != COALESCE(OLD.memory_facts,'[]')
          AND (SELECT phase FROM memory_store_state WHERE id=1) != 'maintenance'
        BEGIN SELECT RAISE(ABORT, 'legacy_memory_is_read_only'); END
;
CREATE TRIGGER guard_new_spawn_preferences BEFORE INSERT ON spawns
        WHEN COALESCE(NEW.memory_facts,'[]') != '[]'
          AND (SELECT phase FROM memory_store_state WHERE id=1) != 'maintenance'
        BEGIN SELECT RAISE(ABORT, 'legacy_memory_is_read_only'); END
;

-- section: child_tables
-- The four tables that kept a spawn_id column, as their CREATE text read with the foreign key to spawns.
-- Only the foreign-key clause differs from what create_all makes since C7c-5b.
CREATE TABLE arslan_messages (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	conversation_id VARCHAR(50) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	display_content TEXT, 
	spawn_id INTEGER, 
	run_id INTEGER, 
	timestamp DATETIME, 
	job_outcome VARCHAR(20), 
	source VARCHAR(20), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id), 
	FOREIGN KEY(run_id) REFERENCES runs (id) ON DELETE SET NULL
)
;
CREATE TABLE knowledge_chunks (
	id INTEGER NOT NULL, 
	spawn_id INTEGER, 
	collection_id INTEGER, 
	source VARCHAR(200) NOT NULL, 
	chunk_index INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	embedding BLOB, 
	embedding_model VARCHAR(80), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_chunk_exactly_one_scope CHECK ((spawn_id IS NULL) != (collection_id IS NULL)), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id) ON DELETE CASCADE, 
	FOREIGN KEY(collection_id) REFERENCES collections (id) ON DELETE CASCADE
)
;
CREATE TABLE runs (
	id INTEGER NOT NULL, 
	conversation_id VARCHAR(50) NOT NULL, 
	spawn_id INTEGER, 
	spawn_name VARCHAR(100), 
	user_message TEXT NOT NULL, 
	started_at DATETIME NOT NULL, 
	ended_at DATETIME, 
	total_ms INTEGER, 
	task_tokens INTEGER NOT NULL, 
	execution_budget JSON, 
	no_learning BOOLEAN DEFAULT '0' NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	overall_score FLOAT, 
	overall_badge VARCHAR(10), 
	created_at DATETIME, 
	model VARCHAR(80), 
	provider VARCHAR(40), 
	tokens_in INTEGER, 
	tokens_out INTEGER, 
	tokens_estimated BOOLEAN NOT NULL, 
	has_images BOOLEAN, 
	read_outside BOOLEAN, 
	error_kind VARCHAR(60), 
	error_text TEXT, 
	system_prompt TEXT, 
	injected_kb TEXT, 
	injected_kb_sources JSON, 
	kind VARCHAR(10) DEFAULT 'live' NOT NULL, 
	epoch INTEGER DEFAULT '0' NOT NULL, 
	continuation BOOLEAN DEFAULT '0' NOT NULL, 
	final_output TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id) ON DELETE SET NULL
)
;
CREATE TABLE scheduled_tasks (
	id INTEGER NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	prompt TEXT NOT NULL, 
	spawn_id INTEGER, 
	conversation_id VARCHAR(50), 
	target VARCHAR(10) DEFAULT 'spawn' NOT NULL, 
	schedule_kind VARCHAR(10) NOT NULL, 
	interval_s INTEGER, 
	cron VARCHAR(40), 
	enabled BOOLEAN NOT NULL, 
	last_fired_at DATETIME, 
	next_due_at DATETIME, 
	consecutive_failures INTEGER NOT NULL, 
	paused_reason TEXT, 
	created_at DATETIME, 
	seen_at DATETIME, 
	outside_seen BOOLEAN DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(spawn_id) REFERENCES spawns (id) ON DELETE SET NULL
)
;
