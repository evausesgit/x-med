// Étape numérotée de la page « Comment ça marche », partagée par les deux
// versions linguistiques du contenu (content.fr.tsx / content.en.tsx).
export default function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="arch-step">
      <div className="step-head">
        <span className="step-num">{n}</span>
        <h2>{title}</h2>
      </div>
      <div className="step-body">{children}</div>
    </section>
  );
}
