-- 003_rename_skeleton_to_targets.sql  (apply to tri_analyze and tri_analyze_test)
-- training_plans.skeleton held the list of WeekTarget rows; the code calls that list "targets".

alter table training_plans rename column skeleton to targets;
