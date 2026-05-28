-- Manus Meta AI multi-tenant storage
-- Safe to run more than once from the Supabase SQL Editor.

create table if not exists public.tenant_accounts (
  tenant_id text primary key,
  email text unique not null,
  display_name text,
  password_hash text not null,
  status text default 'active',
  added_at timestamptz default now(),
  disabled_at timestamptz,
  deleted_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.tenant_accounts add column if not exists status text default 'active';
alter table public.tenant_accounts add column if not exists added_at timestamptz default now();
alter table public.tenant_accounts add column if not exists disabled_at timestamptz;
alter table public.tenant_accounts add column if not exists deleted_at timestamptz;
alter table public.tenant_accounts add column if not exists subscription_started_at timestamptz;
alter table public.tenant_accounts add column if not exists access_expires_at timestamptz;

create table if not exists public.tenant_meta_apps (
  tenant_id text primary key references public.tenant_accounts(tenant_id) on delete cascade,
  meta_app_id text not null,
  meta_app_secret text not null,
  meta_oauth_scopes text,
  webhook_verify_token text,
  webhook_callback_url text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists public.meta_connections (
  tenant_id text not null references public.tenant_accounts(tenant_id) on delete cascade,
  meta_user_id text not null,
  meta_user_name text,
  meta_access_token text not null,
  granted_scopes text,
  selected_page_id text,
  selected_page_name text,
  selected_page_access_token text,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  primary key (tenant_id, meta_user_id)
);

alter table public.meta_connections add column if not exists selected_page_id text;
alter table public.meta_connections add column if not exists selected_page_name text;
alter table public.meta_connections add column if not exists selected_page_access_token text;

create table if not exists public.google_connections (
  tenant_id text primary key references public.tenant_accounts(tenant_id) on delete cascade,
  google_user_email text,
  access_token text not null,
  refresh_token text,
  expires_at timestamptz,
  scopes text,
  selected_ga4_property_id text,
  selected_ga4_property_name text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.google_connections add column if not exists google_user_email text;
alter table public.google_connections add column if not exists access_token text;
alter table public.google_connections add column if not exists refresh_token text;
alter table public.google_connections add column if not exists expires_at timestamptz;
alter table public.google_connections add column if not exists scopes text;
alter table public.google_connections add column if not exists selected_ga4_property_id text;
alter table public.google_connections add column if not exists selected_ga4_property_name text;

create table if not exists public.clarity_connections (
  tenant_id text primary key references public.tenant_accounts(tenant_id) on delete cascade,
  project_name text,
  api_token text not null,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.clarity_connections add column if not exists project_name text;
alter table public.clarity_connections add column if not exists api_token text;

create table if not exists public.oauth_codes (
  code text primary key,
  tenant_id text not null references public.tenant_accounts(tenant_id) on delete cascade,
  meta_user_id text not null,
  expires_at timestamptz not null,
  used boolean default false
);

create table if not exists public.app_tokens (
  app_token text primary key,
  tenant_id text not null references public.tenant_accounts(tenant_id) on delete cascade,
  meta_user_id text not null,
  expires_at timestamptz not null
);

create index if not exists idx_meta_connections_tenant_updated_at
  on public.meta_connections (tenant_id, updated_at desc);

create index if not exists idx_meta_connections_meta_user
  on public.meta_connections (meta_user_id);

create index if not exists idx_google_connections_tenant_updated_at
  on public.google_connections (tenant_id, updated_at desc);

create index if not exists idx_google_connections_selected_property
  on public.google_connections (selected_ga4_property_id);

create index if not exists idx_clarity_connections_tenant_updated_at
  on public.clarity_connections (tenant_id, updated_at desc);

create index if not exists idx_app_tokens_tenant_meta_user
  on public.app_tokens (tenant_id, meta_user_id);

create index if not exists idx_oauth_codes_tenant_used_expires
  on public.oauth_codes (tenant_id, used, expires_at);

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'tenant_accounts_status_check'
  ) then
    alter table public.tenant_accounts
      add constraint tenant_accounts_status_check
      check (status in ('active', 'disabled', 'deleted'));
  end if;
end $$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_tenant_accounts_updated_at on public.tenant_accounts;
create trigger trg_tenant_accounts_updated_at
before update on public.tenant_accounts
for each row execute function public.set_updated_at();

drop trigger if exists trg_tenant_meta_apps_updated_at on public.tenant_meta_apps;
create trigger trg_tenant_meta_apps_updated_at
before update on public.tenant_meta_apps
for each row execute function public.set_updated_at();

drop trigger if exists trg_meta_connections_updated_at on public.meta_connections;
create trigger trg_meta_connections_updated_at
before update on public.meta_connections
for each row execute function public.set_updated_at();

drop trigger if exists trg_google_connections_updated_at on public.google_connections;
create trigger trg_google_connections_updated_at
before update on public.google_connections
for each row execute function public.set_updated_at();

drop trigger if exists trg_clarity_connections_updated_at on public.clarity_connections;
create trigger trg_clarity_connections_updated_at
before update on public.clarity_connections
for each row execute function public.set_updated_at();

alter table public.tenant_accounts enable row level security;
alter table public.tenant_meta_apps enable row level security;
alter table public.meta_connections enable row level security;
alter table public.google_connections enable row level security;
alter table public.clarity_connections enable row level security;
alter table public.oauth_codes enable row level security;
alter table public.app_tokens enable row level security;

-- The FastAPI server uses SUPABASE_SERVICE_ROLE_KEY, which bypasses RLS.
-- No anon/authenticated policies are created here, so browser clients cannot
-- read tokens or tenant records directly from Supabase.
