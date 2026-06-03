-- 0003 — fixes found by running the app end-to-end against a real Supabase
-- project (PostgREST + RLS), not just by applying the schema.

-- (1) Owners must be able to read their own workspace.
-- The only SELECT policy on workspaces was "members can read their
-- workspaces", but a freshly-created workspace has no members yet. Onboarding
-- step 1 does `supabase.from("workspaces").insert({...}).select().single()`,
-- and PostgREST's return=representation applies the SELECT policy to the row it
-- echoes back -- so the owner (not yet a member) got an empty body and
-- onboarding failed with PGRST116 before it could insert the bootstrap member
-- row. This policy is non-recursive (owner_id = auth.uid()), so it needs no
-- SECURITY DEFINER helper. Owners and members can now both read; INSERT/UPDATE
-- policies are unchanged.
create policy "owners can read their workspaces"
  on public.workspaces for select
  using (owner_id = auth.uid());

-- (2) Pin handle_new_user's search_path (advisor lint 0011_function_search_path
-- _mutable). It is SECURITY DEFINER, so a mutable search_path is an injection
-- vector -- the same reason user_workspace_ids/role/count already set it. It is
-- a trigger function (fired as table owner on auth.users insert), so it never
-- needs to be callable via /rest/v1/rpc; drop the default PUBLIC execute.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1)));
  return new;
end;
$$;
revoke execute on function public.handle_new_user() from public, anon, authenticated;
