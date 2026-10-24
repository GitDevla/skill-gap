import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import {
  type AnalysisResponse,
  type EssentialSkillState,
  type HasSkill,
  type Occupation,
  type Verdict,
  fetchAnalysis,
  fetchOccupation,
  saveSkillStatement,
} from "../api";
import SkillStatementToggle from "../components/SkillStatementToggle";
import { formatTitleCase } from "../titleCase";
import { VERDICT_TEXT_CLASSES } from "../verdicts";

const VERDICT_STYLES: Record<Verdict, { title: string; className: string }> = {
  READY: { title: "Ready for this occupation", className: "border-green-300 bg-green-50 text-green-900" },
  GAP: { title: "Skill gap", className: "border-red-300 bg-red-50 text-red-900" },
  UNKNOWN: { title: "Not enough information", className: "border-amber-300 bg-amber-50 text-amber-900" },
};
const STATE_LABELS: Record<EssentialSkillState, { label: string; className: string }> = {
  lacking: { label: "Missing", className: "bg-red-100 text-red-800" },
  not_stated: { label: "Not stated", className: "bg-amber-100 text-amber-800" },
  covered: { label: "Covered", className: "bg-green-100 text-green-800" },
  held: { label: "Held", className: "bg-green-100 text-green-800" },
};
const STATE_ORDER: EssentialSkillState[] = ["lacking", "not_stated", "covered", "held"];
const CACHE_LABELS = { hit: "Read from the Redis cache", miss: "Recomputed (cache miss)" };

function toHasSkill(state: EssentialSkillState): HasSkill {
  if (state === "held") return true;
  if (state === "lacking") return false;
  return null;
}

export default function AnalysisPage({ personId }: { personId: number }) {
  const { occupationId = "" } = useParams();
  const [occupation, setOccupation] = useState<Occupation | null>(null);
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setError(null);
    fetchOccupation(occupationId).then(setOccupation, (loadError: Error) => setError(loadError.message));
    fetchAnalysis(personId, occupationId).then(setResult, (loadError: Error) => setError(loadError.message));
  }, [personId, occupationId]);

  async function changeStatement(skillId: string, hasSkill: HasSkill) {
    setSaving(true);
    setError(null);
    try {
      await saveSkillStatement(personId, skillId, hasSkill);
      setResult(await fetchAnalysis(personId, occupationId));
    } catch (saveError) {
      setError((saveError as Error).message);
    }
    setSaving(false);
  }

  if (error) return <p className="rounded border border-red-300 bg-red-50 px-3 py-2 text-red-800">{error}</p>;
  if (occupation === null || result === null) return <p className="text-stone-500">Loading…</p>;

  const { analysis } = result;
  const verdictStyle = VERDICT_STYLES[analysis.verdict];
  const essentialSkills = [...analysis.evidence.essential_skills].sort(
    (first, second) => STATE_ORDER.indexOf(first.state) - STATE_ORDER.indexOf(second.state),
  );

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="text-2xl font-semibold">{formatTitleCase(occupation.preferred_label.en)}</h1>
          <span className="text-sm text-stone-500">
            {CACHE_LABELS[result.cache]} · analysis {analysis.analysis_id} · rule {analysis.rule_version}
          </span>
        </div>
        <p className="text-sm text-stone-700">{occupation.description.en}</p>
        {occupation.alternative_labels?.en && (
          <p className="text-xs text-stone-500">Also called: {occupation.alternative_labels.en.map(formatTitleCase).join(", ")}</p>
        )}
      </div>

      <section className={`rounded-lg border-2 p-5 ${verdictStyle.className}`}>
        <h2 className="text-xl font-semibold">{verdictStyle.title}</h2>
        <p className="mt-1">{analysis.verdict_reason}</p>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Essential skills ({essentialSkills.length})</h2>
        <ul className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white">
          {essentialSkills.map((skill) => {
            const stateLabel = STATE_LABELS[skill.state];
            return (
              <li key={skill.skill_id} className="flex items-center justify-between gap-3 px-4 py-2">
                <div className="min-w-0">
                  <span className={`mr-2 rounded px-2 py-0.5 text-xs font-medium ${stateLabel.className}`}>
                    {stateLabel.label}
                  </span>
                  <span className="text-sm">{formatTitleCase(skill.label)}</span>
                  {skill.covered_by.length > 0 && (
                    <span className="ml-2 text-xs text-stone-500">
                      via {skill.covered_by.map((narrower) => formatTitleCase(narrower.label)).join(", ")}
                    </span>
                  )}
                </div>
                <SkillStatementToggle
                  value={toHasSkill(skill.state)}
                  disabled={saving}
                  onChange={(hasSkill) => changeStatement(skill.skill_id, hasSkill)}
                />
              </li>
            );
          })}
        </ul>
        <p className="text-xs text-stone-500">
          A held narrower skill covers a broader one (ESCO skill hierarchy). Optional skills held:{" "}
          {analysis.evidence.optional_skills_held.length} of {analysis.evidence.optional_skill_count}
          {analysis.evidence.optional_skills_held.length > 0 &&
            ` (${analysis.evidence.optional_skills_held.map((skill) => formatTitleCase(skill.label)).join(", ")})`}
          .
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Similar occupations</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {analysis.evidence.alternatives.map((alternative) => (
            <Link
              key={alternative.occupation_id}
              to={`/occupations/${alternative.occupation_id}`}
              className="rounded-lg border border-stone-200 bg-white p-4 hover:border-stone-400"
            >
              <h3 className="font-semibold">{formatTitleCase(alternative.label)}</h3>
              <p className={`text-sm font-medium ${VERDICT_TEXT_CLASSES[alternative.verdict]}`}>{alternative.verdict}</p>
              <p className="text-sm text-stone-600">
                {alternative.essential_met} of {alternative.essential_total} essential skills met
                {alternative.essential_lacking > 0 && `, ${alternative.essential_lacking} missing`}
              </p>
              <p className="text-xs text-stone-500">
                similarity {alternative.similarity.toFixed(3)} ({analysis.vector_store})
              </p>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
