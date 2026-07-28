"use client";

// Champ multi-valeurs (étiquettes). Le profil accepte depuis toujours PLUSIEURS
// sous-spécialités (colonne TEXT[]), mais le champ texte « séparés par des
// virgules » ne le montrait pas : on saisit ici une valeur à la fois, chacune
// devient une étiquette qu'on peut retirer.
import { useRef, useState } from "react";

const split = (s: string) =>
  s.split(",").map((x) => x.trim()).filter(Boolean);

export default function TagsField({
  label,
  hint,
  placeholder,
  values,
  onChange,
}: {
  label: string;
  hint?: string;
  placeholder?: string;
  values: string[];
  onChange: (v: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Ajoute une ou plusieurs valeurs (le collage d'une liste « a, b, c » crée
  // toutes les étiquettes d'un coup). Doublons ignorés, casse comprise.
  const add = (raw: string) => {
    const kept = [...values];
    for (const v of split(raw)) {
      if (!kept.some((x) => x.toLowerCase() === v.toLowerCase())) kept.push(v);
    }
    if (kept.length !== values.length) onChange(kept);
  };

  const commitDraft = () => {
    if (draft.trim()) add(draft);
    setDraft("");
  };

  return (
    <div className="field" style={{ flex: "1 1 100%" }}>
      <label>{label}</label>
      <div
        className="tagfield"
        // Cliquer n'importe où dans le cadre revient à cliquer dans le champ.
        onClick={() => inputRef.current?.focus()}
      >
        {values.map((v) => (
          <span className="chip" key={v}>
            {v}
            <button
              type="button"
              aria-label={`Retirer ${v}`}
              onClick={(e) => {
                e.stopPropagation();
                onChange(values.filter((x) => x !== v));
              }}
            >
              ×
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          type="text"
          className="tagfield-input"
          value={draft}
          placeholder={values.length === 0 ? placeholder : "Ajouter…"}
          onChange={(e) => {
            // Une virgule (frappée ou collée) valide ce qui précède.
            if (e.target.value.includes(",")) {
              const parts = e.target.value.split(",");
              add(parts.slice(0, -1).join(","));
              setDraft(parts[parts.length - 1].trimStart());
            } else {
              setDraft(e.target.value);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              // Sans ça, Entrée soumettrait le formulaire au lieu de valider
              // l'étiquette en cours de saisie.
              e.preventDefault();
              commitDraft();
            } else if (e.key === "Backspace" && !draft && values.length) {
              onChange(values.slice(0, -1));
            }
          }}
          // Filet de sécurité : une saisie non validée n'est pas perdue quand on
          // clique directement sur « Enregistrer ».
          onBlur={commitDraft}
        />
      </div>
      {hint && <span className="tagfield-hint">{hint}</span>}
    </div>
  );
}
