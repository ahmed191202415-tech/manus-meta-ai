-- Meta Ads Intelligence persistent storage for Supabase/Postgres.
-- Safe to run multiple times.

create extension if not exists pgcrypto;

create table if not exists public.raw_insights_daily (
  id bigserial primary key,
  tenant_id text,
  account_id text not null,
  campaign_id text,
  adset_id text,
  ad_id text,
  date date not null,
  level text not null,
  objective text,
  optimization_goal text,
  billing_event text,
  breakdown_signature text default '',
  spend numeric,
  impressions numeric,
  reach numeric,
  frequency numeric,
  clicks numeric,
  inline_link_clicks numeric,
  outbound_clicks numeric,
  actions jsonb,
  action_values jsonb,
  cost_per_action_type jsonb,
  raw_json jsonb,
  created_at timestamptz default now(),
  unique(date, account_id, campaign_id, adset_id, ad_id, level, breakdown_signature)
);

create table if not exists public.derived_metrics_daily (
  id bigserial primary key,
  tenant_id text,
  account_id text not null,
  campaign_id text,
  adset_id text,
  ad_id text,
  date date not null,
  level text not null,
  breakdown_signature text default '',
  spend numeric,
  impressions numeric,
  reach numeric,
  frequency numeric,
  link_clicks numeric,
  outbound_clicks numeric,
  landing_page_views numeric,
  add_to_cart numeric,
  initiate_checkout numeric,
  purchases numeric,
  leads numeric,
  messaging_conversations numeric,
  purchase_value numeric,
  ctr_link numeric,
  outbound_ctr numeric,
  lpv_rate numeric,
  atc_rate numeric,
  checkout_rate numeric,
  purchase_rate numeric,
  cpa numeric,
  cost_per_purchase numeric,
  roas numeric,
  signal_quality numeric,
  created_at timestamptz default now(),
  unique(date, account_id, campaign_id, adset_id, ad_id, level, breakdown_signature)
);

create table if not exists public.baselines (
  id bigserial primary key,
  tenant_id text,
  account_id text,
  metric text not null,
  entity_level text not null,
  entity_id text not null,
  baseline_7d numeric,
  baseline_14d numeric,
  baseline_30d numeric,
  mean numeric,
  median numeric,
  std numeric,
  p10 numeric,
  p90 numeric,
  samples integer,
  updated_at timestamptz default now(),
  unique(account_id, metric, entity_level, entity_id)
);

create table if not exists public.analysis_runs (
  run_id uuid primary key default gen_random_uuid(),
  tenant_id text,
  account_id text,
  campaign_id text,
  level text,
  period text,
  phase text,
  question text,
  campaign_type text,
  completed_modules jsonb,
  skipped_modules jsonb,
  errors jsonb,
  result_json jsonb,
  report_markdown text,
  created_at timestamptz default now()
);

create table if not exists public.diagnostics_daily (
  id bigserial primary key,
  run_id uuid references public.analysis_runs(run_id) on delete cascade,
  tenant_id text,
  account_id text,
  campaign_id text,
  date date,
  entity_level text,
  entity_id text,
  scenario text,
  severity text,
  confidence text,
  evidence_json jsonb,
  diagnosis_ar text,
  recommended_action text,
  next_metric text,
  created_at timestamptz default now()
);

create table if not exists public.relationship_edges (
  id bigserial primary key,
  run_id uuid references public.analysis_runs(run_id) on delete cascade,
  tenant_id text,
  account_id text,
  campaign_id text,
  source_metric text,
  target_metric text,
  relation_type text,
  weight numeric,
  confidence text,
  explanation_ar text,
  evidence_json jsonb,
  created_at timestamptz default now()
);

create table if not exists public.knowledge_rules (
  id bigserial primary key,
  rule_key text unique,
  layer text,
  campaign_type text,
  required_metrics text[],
  condition_logic text,
  meaning_ar text,
  recommended_action_ar text,
  next_metric text,
  enabled boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_raw_insights_account_campaign_date
  on public.raw_insights_daily(account_id, campaign_id, date desc);
create index if not exists idx_derived_account_campaign_date
  on public.derived_metrics_daily(account_id, campaign_id, date desc);
create index if not exists idx_analysis_runs_account_campaign_created
  on public.analysis_runs(account_id, campaign_id, created_at desc);
create index if not exists idx_diagnostics_run
  on public.diagnostics_daily(run_id);
create index if not exists idx_relationship_edges_run
  on public.relationship_edges(run_id);
create index if not exists idx_knowledge_rules_layer_enabled
  on public.knowledge_rules(layer, enabled);

alter table public.raw_insights_daily enable row level security;
alter table public.derived_metrics_daily enable row level security;
alter table public.baselines enable row level security;
alter table public.analysis_runs enable row level security;
alter table public.diagnostics_daily enable row level security;
alter table public.relationship_edges enable row level security;
alter table public.knowledge_rules enable row level security;

-- Service role bypasses RLS. These permissive policies help future authenticated clients if needed.
do $$ begin
  create policy "service_role_all_raw_insights" on public.raw_insights_daily for all using (true) with check (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "service_role_all_derived_metrics" on public.derived_metrics_daily for all using (true) with check (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "service_role_all_baselines" on public.baselines for all using (true) with check (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "service_role_all_analysis_runs" on public.analysis_runs for all using (true) with check (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "service_role_all_diagnostics" on public.diagnostics_daily for all using (true) with check (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "service_role_all_relationship_edges" on public.relationship_edges for all using (true) with check (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "service_role_all_knowledge_rules" on public.knowledge_rules for all using (true) with check (true);
exception when duplicate_object then null; end $$;
