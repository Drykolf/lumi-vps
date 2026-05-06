INSERT INTO skill_proposals
  (proposed_name, pattern_count, pattern_window_days, sample_queries,
   rationale, draft_path, parent_skill, status)
VALUES
  ('research_v2', 6, 10, '["...","...","..."]',
   'He notado que cuando me pides investigar...', 'src/skills/_drafts/research_v2.md',
   'research', 'pending');