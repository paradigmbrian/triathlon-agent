-- 008_guardrails.sql
-- Guardrails, 2026-09-24 spec: a week whose design still fails validation after its retry is
-- not proposed. It is stored with designed = null and the validator's violations here; a clean
-- design writes null back.

alter table plan_weeks add column if not exists violations jsonb;
