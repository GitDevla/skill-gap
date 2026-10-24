export type Person = {
  id: number;
  name: string;
  city: string;
  current_occupation_id: string;
  current_occupation_label: string;
  target_occupation_id: string;
  target_occupation_label: string;
};

export type OccupationSummary = { id: string; label: string; isco_group: string };

export type LanguageText = { en: string; hu?: string };

export type Occupation = {
  _id: string;
  esco_uri: string;
  isco_group: string;
  preferred_label: LanguageText;
  alternative_labels?: { en?: string[]; hu?: string[] };
  description: LanguageText;
  essential_skill_ids: string[];
  optional_skill_ids: string[];
  updated_at?: string;
};

export type SimilarOccupation = { concept_id: string; label: string; isco_minor_group: string; score: number };

export type Verdict = "READY" | "GAP" | "UNKNOWN";

export type EssentialSkillState = "held" | "covered" | "lacking" | "not_stated";

export type SkillRef = { skill_id: string; label: string };

export type Alternative = {
  occupation_id: string;
  label: string;
  similarity: number;
  verdict: Verdict;
  essential_total: number;
  essential_met: number;
  essential_lacking: number;
};

export type Analysis = {
  analysis_id: number;
  person_id: number;
  occupation_id: string;
  occupation_label: string;
  occupation_label_hu: string | null;
  verdict: Verdict;
  verdict_reason: string;
  rule_version: string;
  vector_store: string;
  evidence: {
    essential_skills: (SkillRef & { state: EssentialSkillState; covered_by: SkillRef[] })[];
    optional_skills_held: SkillRef[];
    optional_skill_count: number;
    alternatives: Alternative[];
    statement_count: number;
  };
};

export type AnalysisResponse = { analysis: Analysis; cache: "hit" | "miss" };

export type HasSkill = boolean | null;

export type SkillStatement = { skill_id: string; label: string; skill_type: string; has_skill: boolean; stated_at: string };

export type SkillSearchResult = { skill_id: string; label: string; skill_type: string; score: number; has_skill: HasSkill };

export type HistoryRow = {
  id: number;
  occupation_id: string;
  occupation_label: string;
  verdict: Verdict;
  verdict_reason: string;
  decided_at: string;
};

export type StoreOverview = Record<string, string[]> & { graph_counts: Record<string, number> };

export type StorePage = { records: Record<string, unknown>[]; total: number; page: number; page_size: number };

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail ?? response.statusText);
    throw new Error(`${response.status}: ${message}`);
  }
  return response.json() as Promise<T>;
}

export const fetchPeople = () => requestJson<Person[]>("/api/people");
export const fetchOccupations = () => requestJson<OccupationSummary[]>("/api/occupations");
export const searchOccupations = (text: string) =>
  requestJson<SimilarOccupation[]>(`/api/occupations/search?q=${encodeURIComponent(text)}`);
export const fetchOccupation = (occupationId: string) => requestJson<Occupation>(`/api/occupations/${occupationId}`);
export const fetchAnalysis = (personId: number, occupationId: string) =>
  requestJson<AnalysisResponse>(`/api/people/${personId}/analyses/${occupationId}`);
export const fetchHistory = (personId: number) => requestJson<HistoryRow[]>(`/api/people/${personId}/analyses`);
export const fetchSkillStatements = (personId: number) =>
  requestJson<SkillStatement[]>(`/api/people/${personId}/skills`);
export const searchSkills = (personId: number, text: string) =>
  requestJson<SkillSearchResult[]>(`/api/people/${personId}/skills/search?q=${encodeURIComponent(text)}`);
export const saveSkillStatement = (personId: number, skillId: string, hasSkill: HasSkill) =>
  requestJson<{ invalidated_cached_analyses: number }>(`/api/people/${personId}/skills/${skillId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ has_skill: hasSkill }),
  });
export const fetchStoreOverview = () => requestJson<StoreOverview>("/api/db");
export const fetchStorePage = (store: string, collection: string, page: number) =>
  requestJson<StorePage>(`/api/db/${store}/${encodeURIComponent(collection)}?page=${page}`);
