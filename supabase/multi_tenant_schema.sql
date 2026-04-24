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

create index if not exists idx_app_tokens_tenant_meta_user
  on public.app_tokens (tenant_id, meta_user_id);

alter table public.tenant_accounts add column if not exists status text default 'active';
alter table public.tenant_accounts add column if not exists added_at timestamptz default now();
alter table public.tenant_accounts add column if not exists disabled_at timestamptz;
alter table public.tenant_accounts add column if not exists deleted_at timestamptz;
alter table public.tenant_accounts add column if not exists subscription_started_at timestamptz;
alter table public.tenant_accounts add column if not exists access_expires_at timestamptz;
