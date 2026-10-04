-- Supabase's security advisor flags a mutable search_path on these two functions (docs/HANDOFF.md section 3, C).
-- Neither reads a table or calls an unqualified function, so an empty search_path changes nothing they do.
ALTER FUNCTION ops.reject_audit_change() SET search_path = '';
ALTER FUNCTION ops.business_today() SET search_path = '';
