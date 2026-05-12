-- Run at session close: decay interest for inactive non-Jose persons
UPDATE person_interest
   SET interest_score = MAX(
           interest_score - 0.02 * CAST((julianday('now') - julianday(last_mentioned)) / 7 AS INTEGER),
           -1.0
       ),
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
