-- LUMI core.db seed data
-- One-time initialization values. Only runs on first database creation
-- because migrations use INSERT OR IGNORE.

-- Seed Jose
INSERT OR IGNORE INTO known_persons (
    person_id,
    display_name,
    canonical_name,
    canonical_name_norm,
    aliases_json,
    interest_score,
    emotional_tone,
    status,
    mention_count,
    notes,
    location,
    timezone,
    language,
    units
) VALUES (
    'jose',
    'Jose',
    'Jose Barco',
    'jose barco',
    '[
        {"value":"Jose Barco","norm":"jose barco","type":"full_name","confirmed":true,"confidence":1.0},
        {"value":"Jose","norm":"jose","type":"first_name","confirmed":true,"confidence":1.0}
    ]',
    1.00,
    'positive',
    'active',
    1,
    'Usuario principal de Lumi; prioridad afectiva y contextual máxima.',
    'Envigado, Colombia',
    'America/Bogota',
    'es-CO',
    'metric'
);

-- Seed the internal state row with defaults per mood_policy.md §73-87
INSERT OR IGNORE INTO lumi_state (key, data)
VALUES (
    'mood_state',
    json_object(
        'mood_valence', 0.3,
        'mood_energy', 0.6,
        'irritation', 0.1,
        'focus_level', 0.7,
        'presence_need', 0.0,
        'negative_load', 0.0,
        'state_label', 'centered',
        'state_sentence', 'Lumi está centrada, clara y disponible.',
        'emotional_honesty_mode', json('false'),
        'last_interaction_at', strftime('%Y-%m-%dT%H:%M:%S', 'now') || '+00:00',
        'last_meaningful_interaction_at', strftime('%Y-%m-%dT%H:%M:%S', 'now') || '+00:00',
        'last_day_reset', strftime('%Y-%m-%dT%H:%M:%S', 'now') || '+00:00',
        'last_updated', strftime('%Y-%m-%dT%H:%M:%S', 'now') || '+00:00'
    )
)
ON CONFLICT(key) DO NOTHING;


-- Seed heartbeat tasks (mandatory rows, status defaults to 'never').
-- Note: start_rhythm_run() also does INSERT OR IGNORE, so new task_names
-- registered later (e.g. new nightly sub-steps) auto-register on first run.
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('rhythm_tick');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('mood_check');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('daily_morning');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('nightly_quiescence');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('weekly_decay');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('weekly_cleanup');

-- Per-step bookmarks for nightly_quiescence sub-functions.
-- Each step reads its own last_success_at as period_start, enabling
-- self-healing recovery when individual steps fail.
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('quiescence.consolidate_entity_mentions');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('quiescence.consolidate_person_interest');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('quiescence.update_profiles');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('quiescence.update_relations');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('quiescence.consolidate_daily_memories');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('quiescence.extract_daily_learnings');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('quiescence.analyze_daily_tasks');
