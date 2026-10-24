import type { HasSkill } from "../api";

type Props = {
  value: HasSkill;
  onChange: (value: HasSkill) => void;
  disabled?: boolean;
};

const OPTIONS: { label: string; value: HasSkill; selectedClass: string }[] = [
  { label: "Have", value: true, selectedClass: "bg-green-700 text-white" },
  { label: "Don't have", value: false, selectedClass: "bg-red-700 text-white" },
  { label: "Not stated", value: null, selectedClass: "bg-stone-600 text-white" },
];

export default function SkillStatementToggle({ value, onChange, disabled = false }: Props) {
  return (
    <div className="flex shrink-0 overflow-hidden rounded border border-stone-300 text-xs">
      {OPTIONS.map((option) => {
        const selected = value === option.value;
        return (
          <button
            key={option.label}
            type="button"
            disabled={disabled}
            aria-pressed={selected}
            className={`px-2 py-1 disabled:opacity-50 ${selected ? option.selectedClass : "bg-white text-stone-700 hover:bg-stone-100"}`}
            onClick={() => {
              const nextValue = selected ? null : option.value;
              if (nextValue !== value) onChange(nextValue);
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
