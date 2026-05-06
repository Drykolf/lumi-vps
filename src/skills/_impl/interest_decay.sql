
-- run at session close
UPDATE persons
   SET interest_score = MAX(interest_score - 0.02 * weeks_since_last, -1.0),
       status = CASE
                  WHEN interest_score < 0.10 AND
                       julianday('now') - julianday(last_mentioned) >= 56
                       AND interest_score >= 0
                  THEN 'forgotten'
                  WHEN interest_score < 0.30
                  THEN 'decaying'
                  ELSE status
                END
 WHERE is_jose = 0
   AND interest_score >= 0
   AND julianday('now') - julianday(last_mentioned) >= 28;
