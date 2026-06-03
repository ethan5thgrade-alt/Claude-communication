-- Mesh — token-based invite redemption
--
-- Redemption runs as a user who is NOT yet a member of the target workspace.
-- That user therefore cannot, under the 0001 RLS policies:
--   * read the invite row ("workspace members can read invites")
--   * read the workspace row ("members can read their workspaces")
--   * UPDATE the invite use_count (no member-facing update policy)
--   * INSERT into workspace_members (management policy needs owner/admin;
--     bootstrap policy needs an empty workspace owned by the caller)
--
-- Two SECURITY DEFINER functions close that gap with server-side validation,
-- the same pattern 0001 uses for user_workspace_ids / workspace_member_count.
-- NEVER inline a self-subquery against workspace_members here — these helpers
-- exist precisely so callers stay clear of 42P17 recursion.

------------------------------------------------------------------------------
-- preview_invite(token) -----------------------------------------------------
-- Read-only confirmation data for the redemption screen: workspace identity
-- and current member count, plus whether the token is still redeemable. No
-- side effects. Returns nothing for an unknown token so callers can 404.
------------------------------------------------------------------------------
create or replace function public.preview_invite(invite_token text)
returns table (
  workspace_id   uuid,
  workspace_slug text,
  workspace_name text,
  member_count   int,
  expired        boolean,
  exhausted      boolean
)
language sql
security definer
stable
set search_path = public
as $$
  select
    w.id,
    w.slug,
    w.name,
    public.workspace_member_count(w.id),
    (i.expires_at is not null and i.expires_at < now()),
    (i.use_count >= i.max_uses)
  from public.invites i
  join public.workspaces w on w.id = i.workspace_id
  where i.token = invite_token
$$;

------------------------------------------------------------------------------
-- redeem_invite(token) ------------------------------------------------------
-- Validate the token and add the caller to the workspace as a 'member'.
-- Returns the workspace slug on success. Raises on every failure mode so the
-- caller surfaces a precise message. Idempotent for an already-joined member:
-- returns the slug without double-counting a use.
------------------------------------------------------------------------------
create or replace function public.redeem_invite(invite_token text)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid   uuid := auth.uid();
  v_inv   public.invites%rowtype;
  v_slug  text;
  v_member_exists boolean;
begin
  if v_uid is null then
    raise exception 'not authenticated' using errcode = '28000';
  end if;

  select * into v_inv from public.invites where token = invite_token;
  if not found then
    raise exception 'invite not found' using errcode = 'P0002';
  end if;

  -- Already a member: no-op, just return where to go.
  select exists (
    select 1 from public.workspace_members
    where workspace_id = v_inv.workspace_id and user_id = v_uid
  ) into v_member_exists;

  select slug into v_slug from public.workspaces where id = v_inv.workspace_id;

  if v_member_exists then
    return v_slug;
  end if;

  if v_inv.expires_at is not null and v_inv.expires_at < now() then
    raise exception 'invite expired' using errcode = 'P0001';
  end if;

  if v_inv.use_count >= v_inv.max_uses then
    raise exception 'invite use limit reached' using errcode = 'P0001';
  end if;

  insert into public.workspace_members (workspace_id, user_id, role)
  values (v_inv.workspace_id, v_uid, 'member');

  update public.invites
     set use_count = use_count + 1,
         used_by   = v_uid
   where id = v_inv.id;

  return v_slug;
end;
$$;

-- Anon callers never reach these (the web layer requires a session first), but
-- grant to authenticated so the RPC is callable post-login.
grant execute on function public.preview_invite(text) to authenticated;
grant execute on function public.redeem_invite(text) to authenticated;
