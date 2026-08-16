/* Passerelle entre le menu du header et le panneau d'historique.

   La barre de navigation est globale, le panneau des recherches récentes vit
   dans la page d'accueil : on ne peut pas partager d'état React entre les deux.
   Depuis l'accueil on passe donc par un évènement ; depuis une autre page on
   pose un drapeau de session que l'accueil consomme à l'arrivée. */

export const HISTORY_EVENT = "xm-open-history";
const HISTORY_FLAG = "xm-open-history";

// Appelé par le header. `onHome` : la page d'accueil est déjà à l'écran.
export function requestHistoryPanel(onHome: boolean) {
  if (onHome) window.dispatchEvent(new Event(HISTORY_EVENT));
  else window.sessionStorage.setItem(HISTORY_FLAG, "1");
}

// Appelé par l'accueil au montage : vrai une seule fois par demande.
export function consumeHistoryRequest(): boolean {
  if (window.sessionStorage.getItem(HISTORY_FLAG) !== "1") return false;
  window.sessionStorage.removeItem(HISTORY_FLAG);
  return true;
}
