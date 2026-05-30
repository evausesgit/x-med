// Page statique « Comment ça marche » : explique le pipeline de bout en bout
// (récupérer → analyser → trouver/scorer → digest). Server Component par défaut
// (aucun état, aucune interactivité) → rendu une fois, pas de JS côté client.
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "X-Med — Comment ça marche",
  description:
    "Le pipeline X-Med expliqué : récupération des articles PubMed, analyse, recherche et scoring.",
};

function Step({
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

export default function ArchitecturePage() {
  return (
    <main className="container">
      <h1>Comment ça marche</h1>
      <p className="subtitle">
        De l&apos;article brut publié sur PubMed jusqu&apos;au résultat classé
        que vous voyez dans la recherche — les quatre étapes du pipeline X-Med.
      </p>

      <p className="meta">
        Vous cherchez plutôt à tester ?{" "}
        <Link href="/">← Retour à la recherche</Link>
      </p>

      <Step n={1} title="Récupérer les articles">
        <p>
          La source principale est le <strong>FTP de la NLM</strong> (la
          bibliothèque de médecine américaine), qui publie l&apos;intégralité de
          PubMed sous forme de fichiers compressés <code>.xml.gz</code> :
        </p>
        <ul>
          <li>
            un <strong>socle annuel</strong> (« baseline ») de ~1 455 fichiers,
            chargé une fois ;
          </li>
          <li>
            des <strong>mises à jour quotidiennes</strong> (1 à 3 fichiers/jour)
            avec les nouveaux articles et les corrections.
          </li>
        </ul>
        <p>
          On garde la trace des fichiers déjà traités dans une table{" "}
          <code>ftp_state</code> pour ne <strong>jamais retraiter</strong> deux
          fois le même, et on vérifie l&apos;intégrité de chaque fichier par sa
          somme <code>MD5</code> avant de l&apos;ouvrir.
        </p>
        <p className="note">
          Une seconde source, l&apos;<strong>API E-utilities</strong> de PubMed,
          sert aux recherches ponctuelles « à la demande » — à ne pas confondre
          avec le flux bulk quotidien ci-dessus.
        </p>
      </Step>

      <Step n={2} title="Analyser (parser) chaque article">
        <p>
          Un fichier <code>.xml.gz</code> peut contenir des dizaines de milliers
          d&apos;articles. On le lit <strong>en streaming</strong> (lecture au
          fil de l&apos;eau, article par article, sans tout charger en mémoire) :
          pour chaque <code>&lt;PubmedArticle&gt;</code> on extrait le titre,
          le résumé (abstract), les auteurs, la revue, l&apos;année, les
          identifiants (PMID, DOI) et les <strong>tags MeSH</strong> (le
          vocabulaire médical normalisé de PubMed).
        </p>
        <p>
          On en <strong>déduit automatiquement un niveau de preuve</strong> (de
          1 = le plus solide à 4) à partir du type d&apos;étude annoncé :
        </p>
        <ul>
          <li>
            <span className="badge ev1">Niv. 1</span> méta-analyse, revue
            systématique, essai randomisé contrôlé ;
          </li>
          <li>
            <span className="badge ev2">Niv. 2</span> essai clinique, étude de
            cohorte, comparative ;
          </li>
          <li>
            <span className="badge ev3">Niv. 3</span> séries / rapports de cas ;
          </li>
          <li>
            <span className="badge ev4">Niv. 4</span> le reste (éditorial,
            lettre, opinion…).
          </li>
        </ul>
        <p>
          Tout est rangé dans la table <code>articles</code>. C&apos;est aussi à
          ce moment qu&apos;on calcule l&apos;<strong>embedding</strong> de
          l&apos;article (voir étape&nbsp;3).
        </p>
      </Step>

      <Step n={3} title="Trouver les bons articles & les scorer">
        <p>
          Impossible (et hors de prix) de demander à une IA d&apos;analyser les
          ~4 000 articles publiés chaque jour. On procède donc{" "}
          <strong>en deux temps</strong> : un tri rapide et grossier, puis un
          tri fin et coûteux uniquement sur les survivants.
        </p>

        <h3>a. Le pré-filtre rapide (gratuit, en base)</h3>
        <p>Deux manières complémentaires de mesurer si un article « colle » :</p>
        <ul>
          <li>
            <strong>Par mots / tags MeSH</strong> : recherche plein-texte
            classique. Le moteur classe les articles par un score{" "}
            <code>ts_rank</code> (à quel point les mots de la requête sont
            présents et rares dans le texte).
          </li>
          <li>
            <strong>Par le sens (embeddings)</strong> : chaque article et chaque
            requête sont transformés en un <em>vecteur</em> — une liste de
            nombres qui résume le sens. Deux textes proches par le sens ont des
            vecteurs proches. On mesure cette proximité par la{" "}
            <strong>similarité cosinus</strong> (entre 0 et 1). C&apos;est ce qui
            permet de retrouver un article anglais à partir d&apos;une phrase en
            français, ou de rattraper les synonymes cliniques.
          </li>
        </ul>
        <p className="note">
          Modèles d&apos;embedding utilisés : <strong>bge-m3</strong> (1024
          dimensions, multilingue FR/EN) et <strong>MedCPT</strong> (768
          dimensions, spécialisé biomédical). La recherche du site combine les
          deux approches (texte + sens) par une fusion appelée{" "}
          <strong>RRF</strong>, qui mélange les <em>classements</em> plutôt que
          les scores bruts.
        </p>

        <h3>b. Rang vs « match » : comment lire les résultats</h3>
        <p>
          Dans la page de recherche, le chiffre qui compte est le{" "}
          <strong>rang</strong> (#1, #2, #3…) : c&apos;est l&apos;ordre de
          pertinence, fiable dans tous les cas. La <strong>barre de match</strong>{" "}
          du mode « Par sens » indique la pertinence{" "}
          <em>relative au meilleur résultat</em> de la page — ce n&apos;est{" "}
          <strong>pas</strong> un pourcentage de certitude. (Le score de fusion
          brut, lui, est un petit nombre technique sans signification directe
          pour un lecteur.)
        </p>

        <h3>c. Le scoring fin par IA (Claude)</h3>
        <p>
          Seuls les quelques dizaines de candidats retenus par le pré-filtre
          sont envoyés à <strong>Claude</strong>, qui, pour le profil précis
          d&apos;un médecin, attribue un <strong>score de pertinence de 0 à 1</strong>,
          rédige un <strong>résumé traduit en français</strong> et signale les
          articles <strong>prioritaires</strong>. Pour maîtriser le coût, la
          partie « profil médecin » du prompt est mise en cache (elle ne change
          pas d&apos;un article à l&apos;autre).
        </p>
      </Step>

      <Step n={4} title="Envoyer le digest">
        <p>
          Les articles les mieux scorés deviennent un <strong>email
          personnalisé</strong> (résumé + lien PubMed), envoyé via le service{" "}
          <strong>Resend</strong>. Chaque envoi est journalisé pour ne pas
          renvoyer deux fois le même article à un médecin.
        </p>
      </Step>

      <p className="meta" style={{ marginTop: 24 }}>
        <Link href="/">← Retour à la recherche</Link>
      </p>
    </main>
  );
}
