-- One row per run. ``requests`` is part of the usage returned by the API.
create table runs (
    id              text primary key,
    parent_id       text references runs(id) on delete set null,
    agent           text not null,
    manifest_digest text not null,
    input           text not null,
    output          text,
    status          text not null check (status in ('running', 'ok', 'failed')),
    error           text,
    input_tokens    integer,
    output_tokens   integer,
    requests        integer,
    cost            numeric,
    latency_ms      integer,
    created_at      timestamptz not null default now()
);

create index runs_created_at_idx on runs (created_at desc);
create index runs_parent_id_idx on runs (parent_id);
create index runs_agent_idx on runs (agent);
