import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router";

import { type Person, fetchPeople } from "./api";
import AnalysisPage from "./pages/AnalysisPage";
import DatabasePage from "./pages/DatabasePage";
import OccupationsPage from "./pages/OccupationsPage";
import HistoryPage from "./pages/HistoryPage";
import SkillsPage from "./pages/SkillsPage";

const PERSON_KEY = "skill-gap.person-id";

export default function App() {
  const [people, setPeople] = useState<Person[]>([]);
  const [personId, setPersonId] = useState<number>(() => Number(localStorage.getItem(PERSON_KEY) ?? 1));

  useEffect(() => {
    fetchPeople().then(setPeople);
  }, []);

  function selectPerson(id: number) {
    localStorage.setItem(PERSON_KEY, String(id));
    setPersonId(id);
  }

  const person = people.find((candidate) => candidate.id === personId) ?? null;
  const navClass = ({ isActive }: { isActive: boolean }) =>
    `-mb-px border-b-2 px-3 py-3 text-sm font-medium ${isActive ? "border-amber-400 text-white" : "border-transparent text-stone-400 hover:text-stone-100"}`;

  return (
    <div className="min-h-screen">
      <header className="bg-stone-900 text-stone-100">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4">
          <span className="flex items-center gap-2 text-lg font-semibold tracking-tight">
            <span className="h-3 w-3 rounded-sm bg-amber-400" />
            Skill Gap
          </span>
          <nav className="flex gap-1">
            <NavLink to="/" end className={navClass}>
              Occupations
            </NavLink>
            <NavLink to="/skills" className={navClass}>
              My skills
            </NavLink>
            <NavLink to="/history" className={navClass}>
              History
            </NavLink>
            <NavLink to="/database" className={navClass}>
              Database
            </NavLink>
          </nav>
          <label className="ml-auto flex items-center gap-2 text-sm text-stone-400">
            Person
            <select
              className="rounded border border-stone-700 bg-stone-800 px-2 py-1 text-stone-100"
              value={personId}
              onChange={(event) => selectPerson(Number(event.target.value))}
            >
              {people.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.id}. {candidate.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Routes>
          <Route path="/" element={<OccupationsPage person={person} />} />
          <Route path="/occupations/:occupationId" element={<AnalysisPage personId={personId} />} />
          <Route path="/skills" element={<SkillsPage personId={personId} />} />
          <Route path="/history" element={<HistoryPage personId={personId} />} />
          <Route path="/database" element={<DatabasePage />} />
        </Routes>
      </main>
    </div>
  );
}
