# Skill: access-control
Covers: AC-01 to AC-06, DB-01 to DB-03

## When to use
An app has users, roles or data that belongs to a user (notes, orders, profiles).

## What to check
1. Protected routes reject anonymous requests.
2. User B cannot read, change or delete User A's objects.
3. A normal user cannot call admin functions.
4. Users cannot set protected fields (`role`, `is_admin`, `owner_id`).
5. The same rules hold for list, search, export and direct database access, not only "get one item".

## How to detect
- **Static:** routes with no auth middleware; queries by ID with no owner filter; Supabase tables with no RLS or with `using (true)`; admin checks done only in the UI.
- **Live:** as User A create an object; as User B request it, update it and delete it; as User B call each admin route; as Anonymous call each protected route; as User B try to set `role` on your own profile; repeat through the REST/database layer.

## How to prove
Save both requests and both responses. Expected for the safe case: 401, 403, 404 or an empty list. A `200` with User A's data is proof of failure.

## How to fix (React + Supabase)
- Turn RLS on and add an owner policy:
  `create policy "owner only" on notes for all using (auth.uid() = user_id) with check (auth.uid() = user_id);`
- On the server, read the user from the verified token, never from the request body.
- Check roles on the server, and keep the UI check only as a convenience.
- Whitelist updatable fields.

## Common mistakes and false positives
- Testing with the service key (it bypasses RLS). Always use the user's own token.
- Testing only GET. Test update, delete, list and search too.
- Policies written for `select` only.
- Resources that are public on purpose. Check the protection list and the PRD before reporting.
