export type Scenario = 'greeting' | 'recommendation' | 'post_purchase' | 'reactivation' | 'invitation' | 'price_objection'
export type LifecycleStage = 'unknown' | 'new' | 'developing' | 'established'
export type ClientBackground = {
  gender: 'unknown' | 'female' | 'male' | 'other' | 'undisclosed'
  age: number | null; occupation: string; source: string; observed_on: string | null
}
export type DraftInput = {
  client_id?: string | null
  client_revision?: number | null
  scenario: Scenario
  client: { preferred_name: string; relationship: string; preferences: string[]; notes: string[]; lifecycle_stage?: LifecycleStage; background?: ClientBackground }
  conversation_history: { speaker: 'client' | 'advisor'; text: string }[]
  product_ids: string[]
  scenario_details: Record<string, string>
}
export type DevCase = { case_id: string; purpose: string; input: DraftInput }
export type Candidate = { strategy: string; message: string }
export type ReplyBrief = { goal: string; approaches: { title: string; intent: string }[]; focus_evidence: { ref: string; topic: string; value: string }[] }
export type QualityReview = {
  version: string; status: 'needs_review' | 'no_rule_flags'; copy_blocked: boolean
  findings: { candidate_index: number; code: string; message: string; excerpt: string; severity: 'revise' | 'block' | 'review' }[]
  automatic_rewrite_count: number; rewrite_outcome?: string; not_checked: string[]; human_review: 'not_reviewed'; semantic_score: null
}
export type Product = { id: string; name: string; price_cny: number; material: string; colors: string[]; features: string[] }
export type Brand = { name: string; version: string; category: string; voice: string[]; writing_guidelines: string[]; business_rules: string[]; care_information: string[] }
export type Bootstrap = { version: string; model: string; api_configured: boolean; brand: Brand; products: Product[]; cases: DevCase[]; capabilities?: { client_memory?: boolean; client_background?: boolean; reply_quality?: boolean; review_samples?: boolean } }
export type Run = {
  run_id: string; created_at: string; case_id: string | null; tool_version: string
  prompt_version: string; brand_version: string; status: string; elapsed_ms: number
  scenario: Scenario; client_name: string; candidate_count: number; attempt_count: number
  model: string | null; semantic_evaluation: string
  candidates?: Candidate[]; input?: DraftInput
  usage?: { input_tokens: number; output_tokens: number }
  client_id?: string | null; client_revision?: number | null; client_memory?: ClientMemory | null
  profile_check?: 'current_at_completion' | 'changed_during_generation' | null
  comparison_mode?: string | null; comparison_baseline_run_id?: string | null
  quality_status?: QualityReview['status'] | null; quality_review?: QualityReview | null; reply_brief?: ReplyBrief | null
}

export type FactKind = 'preference' | 'style' | 'constraint' | 'experience' | 'intent'
export type FactScope = Scenario | 'all'
export type ClientFact = {
  id: string; client_id: string; kind: FactKind; topic: string; value: string; scope: FactScope
  source: string; status: 'confirmed' | 'pending' | 'superseded' | 'retired'
  observed_at: string; valid_until: string | null; replaces_fact_id: string | null; created_at: string
}
export type ClientInteraction = {
  id: string; client_id: string; speaker: 'client' | 'advisor'; text: string; source: string
  scenario: Scenario | null; occurred_at: string; created_at: string; status: 'active' | 'retired'
}
export type ClientSummary = {
  id: string; preferred_name: string; relationship: string; contact_status: 'allowed' | 'paused'
  revision: number; created_at: string; updated_at: string; fact_count?: number; interaction_count?: number
  lifecycle_stage?: LifecycleStage; background?: ClientBackground
}
export type ClientProfile = ClientSummary & {
  fictional: true; facts: ClientFact[]; interactions: ClientInteraction[]
  events: { id: string; revision: number; action: string; created_at: string; payload: Record<string, unknown> }[]
}
export type ClientMemory = {
  client_id: string; revision: number; preferred_name: string; relationship: string; retrieved_at: string
  scenario: Scenario; facts: ClientFact[]; interactions: ClientInteraction[]; available_fact_count: number; selection_policy: string
  lifecycle_stage?: LifecycleStage; background?: ClientBackground
}
