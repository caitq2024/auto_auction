export interface TickSeries {
  tick: number[]
  alpha: (number | null)[]
  cost: number[]
  cum_cost: number[]
  conversions: number[]
  cum_conversions: number[]
  win_pv: number[]
  remaining_budget: number[]
}

export interface EpisodeData {
  episode: number
  score: number
  conversions: number
  cost: number
  actual_cpa: number
  budget_utilization: number
  ticks: TickSeries
}

export interface Candidate {
  id: string
  name: string
  score_mean: number
  conversions_mean: number
  actual_cpa_mean: number
  budget_utilization_mean: number
  episodes: EpisodeData[]
}

export interface Comparison {
  key: string
  label: string
  pv_num: number
  budget: number
  target_cpa: number
  seed: number
  candidates: Candidate[]
}

export interface LLMCall {
  tick: number
  observation: Record<string, Record<string, unknown>> | null
  raw_output: string
  parsed_alpha: number | null
  applied_alpha: number
  fallback: string | null
  latency_sec: number
  error: string | null
}

export interface LLMEpisode {
  episode: number
  calls: LLMCall[]
  fallback_rate: number
  mean_latency_sec: number
}

export interface LLMRun {
  key: string
  label: string
  model: string
  pv_num: number
  total_input_tokens: number | null
  total_output_tokens: number | null
  episodes: LLMEpisode[]
}

export interface SampleRow {
  label: string
  note: string
  row: {
    timeStepIndex: number
    pValue: number
    bid: number
    leastWinningCost: number
    adSlot: number
    isExposed: number
    cost: number
    conversionAction: number
  }
}

export interface DemoData {
  generated_from: string
  sample_rows: SampleRow[]
  comparisons: Comparison[]
  llm_runs: LLMRun[]
}
