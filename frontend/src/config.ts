/**
 * Configuration modifiable de l'interface.
 * - Les suggestions de l'écran d'accueil se modifient ici (texte affiché → question envoyée).
 * - Le contact de la scolarité vient de l'API (/api/config, variables RAG_CONTACT_* du .env) ;
 *   les valeurs ci-dessous ne servent que si l'API ne répond pas.
 */
export const appConfig = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, ''),
  suggestions: {
    fr: [
      { label: 'Attestation de scolarité', question: 'Comment obtenir une attestation de scolarité et sous quel délai ?' },
      { label: 'Durée minimale du PFE', question: "Quelle est la durée minimale d'un PFE qui commence en février 2027 ?" },
      { label: 'Contester une note', question: 'Comment contester une note et dans quel délai ?' },
      { label: 'Partir en mobilité', question: "Quelles conditions faut-il remplir pour partir en semestre d'études à l'étranger ?" },
    ],
    en: [
      { label: 'Enrolment certificate', question: 'Comment obtenir une attestation de scolarité et sous quel délai ?' },
      { label: 'Minimum PFE length', question: "Quelle est la durée minimale d'un PFE qui commence en février 2027 ?" },
      { label: 'Contest a grade', question: 'Comment contester une note et dans quel délai ?' },
      { label: 'Study abroad', question: "Quelles conditions faut-il remplir pour partir en semestre d'études à l'étranger ?" },
    ],
  },
  fallbackContact: { email: 'scolarite@eih.ma', phone: '+212 5 22 00 00 00' },
  topK: { min: 1, max: 15 },
  requestTimeoutMs: 30_000,
  healthPollMs: 20_000,
}
