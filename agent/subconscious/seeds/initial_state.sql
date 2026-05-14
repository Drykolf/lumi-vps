-- LUMI core.db seed data
-- One-time initialization values. Only runs on first database creation
-- because migrations use INSERT OR IGNORE.

-- Seed Jose
INSERT OR IGNORE INTO person_interest (person_id, is_jose, interest_score, status)
VALUES ('jose', 1, 0.70, 'active');

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

-- Seed heartbeat tasks (mandatory rows, status defaults to 'never')
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('rhythm_tick');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('hourly_mood_check');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('daily_morning');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('daily_maintenance');
INSERT OR IGNORE INTO heartbeat_state (task_name) VALUES ('weekly_decay');
