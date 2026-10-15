# Messaging design (Blend chat and DMs)

Spec only. Nothing here is implemented. It is sized for Supabase's free tier and for the app we already have: FastAPI talks to Postgres as the database owner, iOS gets pushes through the existing APNs path, and blocks and reports already exist.

Free tier numbers used below are from Supabase's pricing and Realtime docs (checked Oct 2026):

| Limit | Free |
| --- | --- |
| Database size | 500 MB per project |
| Egress | 5 GB, plus 5 GB cached |
| Monthly active users | 50,000 |
| API requests | Unlimited |
| Realtime peak connections | 200, no paid overage |
| Realtime messages | 2 million per month, no paid overage |
| Realtime messages per second | 100 |
| Channels per connection | 100 |
| Postgres change payload | 1,024 KB |
| Edge function invocations | 500,000 per month |
| Project pause | A free project pauses after a week with no activity |

Going over the free Realtime quota does not bill. It starts a grace period and then the project is restricted. A free project that is paused does not run scheduled jobs.

## Recommendation

Ship v1 as polling through FastAPI, not Supabase Realtime.

One open chat is one Realtime connection. The 200-connection cap is the whole project, shared with any other Realtime use. A few hundred people in the app at once uses it up. Realtime messages are counted per recipient, so a Blend of 8 that sends 100 messages a day is 700 deliveries a day before DMs. That fits in 2 million a month. The connection cap is what runs out first.

Polling does not use that cap. API requests are unlimited. An open thread asks for new rows every 4 seconds: 15 queries a minute per open chat. At 200 open chats that is 3,000 queries a minute, each an indexed read. That is the load to plan for. Close the poll when the thread is not on screen.

Realtime stays the upgrade once the project is on Pro (500 included connections) or chat is the only subscriber. The tables and RLS below are written so that switch does not need a new schema. Until then, iOS does not open a Realtime channel.

## Tables

Four tables. Blend chat and DMs share them. A Blend has one conversation. A DM is a conversation with two members and no Blend.

```sql
create table conversations (
    id bigint generated always as identity primary key,
    kind text not null check (kind in ('blend', 'dm')),
    group_id bigint unique references groups(id) on delete cascade,
    dm_key text unique,
    created_at timestamptz not null default now(),
    check (
        (kind = 'blend' and group_id is not null and dm_key is null)
        or (kind = 'dm' and group_id is null and dm_key is not null)
    )
);

create table conversation_members (
    conversation_id bigint not null references conversations(id) on delete cascade,
    user_id uuid not null references profiles(id) on delete cascade,
    last_read_message_id bigint,
    joined_at timestamptz not null default now(),
    primary key (conversation_id, user_id)
);

create table messages (
    id bigint generated always as identity primary key,
    conversation_id bigint not null references conversations(id) on delete cascade,
    sender_id uuid not null references profiles(id) on delete cascade,
    body text,
    created_at timestamptz not null default now(),
    deleted_at timestamptz
);

create table message_reports (
    id bigint generated always as identity primary key,
    reporter_id uuid not null references profiles(id) on delete cascade,
    message_id bigint not null references messages(id) on delete cascade,
    reason text not null,
    status text not null default 'open',
    resolution_note text,
    resolved_at timestamptz,
    created_at timestamptz not null default now()
);
```

`dm_key` is the two user ids sorted and joined, so the pair can have only one DM. FastAPI writes it. Clients do not.

`last_read_message_id` has no foreign key on purpose. The retention job deletes old messages. A dangling read marker is fine: "everything up to this id is read" still means the right thing after those rows are gone. Adding the foreign key would force the job to null the column first.

Blend membership is copied from `group_members` by the API when someone joins, leaves, or is kicked. Clients cannot insert themselves into `conversation_members`.

`body` is null after a moderation delete. `deleted_at` is set at the same time. Clients show a tombstone, not the old text.

## Indexes

```sql
create index messages_conversation_id_idx
    on messages (conversation_id, id desc);

create index conversation_members_user_idx
    on conversation_members (user_id);

create index message_reports_status_idx
    on message_reports (status, created_at desc);
```

The message index is the pagination index. The primary key on `conversation_members` already covers lookup by conversation. `dm_key` and `group_id` are unique, so they are indexed.

Do not add a per-message read table. That row count grows with members times messages and is the first thing that would press the 500 MB cap.

## RLS

The API uses the database owner and bypasses row level security, the same way the rest of the backend does. RLS is still required. If iOS later subscribes to Realtime, Postgres changes are filtered by the user JWT. A table with RLS and no policies is invisible to that JWT, which is the safe default. Policies below are the allow list for `authenticated`.

```sql
alter table conversations enable row level security;
alter table conversation_members enable row level security;
alter table messages enable row level security;
alter table message_reports enable row level security;

create policy conversations_select on conversations
    for select to authenticated
    using (
        exists (
            select 1 from conversation_members m
            where m.conversation_id = conversations.id
              and m.user_id = auth.uid()
        )
    );

create policy messages_select on messages
    for select to authenticated
    using (
        exists (
            select 1 from conversation_members m
            where m.conversation_id = messages.conversation_id
              and m.user_id = auth.uid()
        )
    );
```

No insert, update, or delete policies for `authenticated`. Writes go through FastAPI. That keeps block checks, body length, and membership in one place. Realtime, when it is turned on, is read-only for the client: the server inserts the message, and Postgres changes deliver the row to members who pass `messages_select`.

`message_reports` has no select policy for the reporter's peers. The reporter gets a 204 from the API and does not read other people's reports. Moderators use the database owner.

`conversation_members` can have a select policy for the member's own row so a later client can read `last_read_message_id`. No write policy.

## Pagination

Keyset, not offset. Offset gets slower as a thread grows and skips or repeats rows when a message arrives mid-page.

```
GET /conversations/{id}/messages?before={message_id}&limit=50
```

`before` is optional. The query is:

```sql
select id, sender_id, body, created_at, deleted_at
from messages
where conversation_id = $1
  and ($2::bigint is null or id < $2)
order by id desc
limit 50;
```

The response is oldest-first after the API reverses the page, plus `next_before` set to the smallest id in the page when the page is full. The poll for new messages is the same table with `id > since` and a limit of 50, ordered by id ascending. `since` is the newest id the client has.

Limit is 1 to 50. Body max length is 2000 characters. Reject anything longer at the API. A 2000-character text is far under the 1,024 KB Realtime payload cap if Realtime is turned on later.

The caller must be a `conversation_members` row. Otherwise 404. Do not 403, so a stranger cannot learn that the conversation exists.

## Read receipts

One column, `conversation_members.last_read_message_id`.

```
POST /conversations/{id}/read
{ "message_id": 123 }
```

The API sets the column when the new id is greater than the stored one. It does not move backwards. Other members learn who has read by `GET /conversations/{id}`, which returns each member's `last_read_message_id`. There is no per-message receipt and no push for "X read your message".

Unread for the badge is "there exists a message in one of my conversations with id greater than my last_read_message_id and sender_id is not me". Compute it when sending a push, not on every poll.

## Blocking

`user_blocks` already exists. A block is two-way for delivery: if either person has blocked the other, a DM cannot be created or sent. The API returns 403 with the existing `{detail: ...}` style.

In a Blend, the message is still stored. The blocked sender is hidden from the blocker's poll and from the blocker's history: the API drops those rows for that caller only, and keeps reading until the page is full or the thread ends. A block must not shorten the page. Other members still see the rows. Push to the blocker is skipped when the sender is blocked. Leaving the Blend is a separate action and is not done automatically.

## Reporting

`POST /reports` already flags a user and the comment on that route says reports are actioned within 24 hours (App Store Review Guideline 1.2). Message reports use the same clock and the same status values (`open`, then a resolved state), in `message_reports`, so a message report does not overload `user_reports`.

```
POST /messages/{id}/report
{ "reason": "..." }
```

204 on success. One open report per reporter and message (unique on that pair). Reporting does not delete the message and does not block the sender. Those stay separate actions.

## Moderation

A moderator reads `message_reports` where `status = 'open'`, oldest first, through an admin path using the same admin check as the rest of the API (`require_admin`).

Acting on a report sets `messages.deleted_at`, clears `messages.body`, and sets the report to resolved with `resolved_at` and an optional `resolution_note`. The 24-hour clock starts at `message_reports.created_at`. There is no automatic ban. A ban is a block or an account deletion, decided by a person.

Soft-deleted bodies stay null. The row stays until the retention job so the report still points at something.

## APNs push

Reuse `device_tokens`, `notification_preferences`, `badge_count`, and `fire_notification`. Do not add a second push client.

Add a `messages` boolean on `notification_preferences`, default true. Add a thread id constant next to the existing ones, `THREAD_MESSAGES = "messages"`, so iOS groups alerts by conversation. The payload `data` carries `type=message`, `conversation_id`, and `message_id`.

Send a push to each other member when a message is inserted, unless:

- the recipient is the sender
- `messages` is false on their preferences
- either person has blocked the other
- the recipient has no device token (the inbox row can still be written the way other notifications do)

Title is the sender's display name, or username. Body is the message text, truncated. For a Blend, prefix with the blend `display_name` once that field exists; until then use `groups.name`. A moderated tombstone does not push.

`badge_count` increments the same way friend activity does. Opening the conversation and posting `/read` up to the latest message does not by itself clear the app badge; the existing badge-reset path stays the one that zeros it.

## Retention

500 MB is the hard stop. Message text is the table that grows.

- A normal message is kept for 180 days, then the retention job deletes the row.
- A moderated message (body already null) is deleted 30 days after `deleted_at`, so a report can be reviewed inside the 24-hour window with time to spare.
- `message_reports` for a deleted message go with it (`on delete cascade`).
- `last_read_message_id` is left as-is when the message row disappears.

The job is a SQL function, `purge_old_messages()`, called from a scheduled Edge Function the same way the weekly digest is scheduled. It deletes in batches of 1000 so one run cannot hold a long lock. Free projects pause after a week of inactivity, so this job does not run while the project is paused. That is acceptable: a paused project is not taking new messages, and the next unpause can run the purge.

Do not turn on `pg_cron` for this. The digest already has a place to hang a weekly call, and a weekly purge is enough at this size.

At a rough size of 1 KB per message including indexes, 180 days of 10,000 messages a day is about 1.8 GB, which does not fit. The cap is the signal to shorten retention or leave the free tier, not to add another store. If volume approaches a few hundred MB, cut retention to 90 days before the database fills.
