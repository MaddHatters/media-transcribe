export interface StepStatusResponse {
  status: string
  started_at: string | null
  completed_at: string | null
  error: string | null
  output_path: string | null
  duration_seconds: number | null
  attempt: number
}

export interface PostSummary {
  post_id: string
  source_id: string
  url: string
  title: string
  published_at: string | null
  post_type: string
  has_video: boolean
  has_audio: boolean
  duration_seconds: number | null
  thumbnail_url: string | null
  tags: string[]
  overall_status: string
  steps: Record<string, StepStatusResponse>
}

export interface PostDetail extends PostSummary {
  created_at: string | null
  edited_at: string | null
  embed_url: string | null
  embed_provider: string | null
  like_count: number | null
  comment_count: number | null
  is_paid: boolean | null
  min_cents_pledged_to_view: number | null
  discovered_at: string | null
  recording_mb: number | null
  transcript_words: number | null
  output_path: string | null
}

export interface QueueEntry {
  post_id: string
  title: string
  priority: number
  added_at: string
  status: string
}

export interface WatcherStatus {
  running: boolean
  pid: number | null
  cycle: number
  interval_hours: number
  last_run: string | null
  next_run: string | null
  last_result: Record<string, unknown>
  total_recorded: number
}

export interface AgentHealth {
  healthy: boolean
  obs_connected: boolean
  chrome_available: boolean
  disk_ok: boolean
  obs_version: string | null
  error: string | null
}

export interface CatalogStats {
  total_posts: number
  video_posts: number
  audio_posts: number
  by_status: Record<string, number>
  by_type: Record<string, number>
  by_step: Record<string, Record<string, number>>
}

export interface WebSocketEvent {
  type: string
  data: Record<string, unknown>
  timestamp: string
}

export interface PaginatedPosts {
  posts: PostSummary[]
  total: number
  page: number
  per_page: number
}

export interface DiscoveryRunResponse {
  id: number | null
  started_at: string
  completed_at: string | null
  posts_found: number
  new_posts: number
  source: string
  status: string
}

export const PIPELINE_STEPS = [
  'record', 'analyze', 'transcribe', 'correct',
  'find_gaps', 'extract_frames', 'ocr',
] as const

export type PipelineStep = typeof PIPELINE_STEPS[number]
