"""Construit eval/testset.jsonl (jeu de test etendu) et verifie chaque preuve.

Chaque question porte :
- ``category`` : type de question (voir CATEGORIES) ;
- ``expected_answer`` / ``answer_keywords`` : reponse de reference ;
- ``expected_references`` : documents sources attendus ;
- ``evidence`` : extraits courts, recopies mot pour mot du corpus, qui doivent
  figurer dans les fragments recuperes (rappel au niveau du passage). Un element
  peut etre une liste de formulations equivalentes lorsque le meme fait figure
  dans deux documents (ex. une date dans la FAQ et dans le calendrier).

Le script echoue si une preuve n'existe pas dans le texte extrait du corpus,
ce qui garantit que le jeu de test reste coherent avec les PDF.

    python eval/build_testset.py
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

NO_ANSWER = "Je ne trouve pas cette information dans les documents de l'École."

REG, GUIDE, CHARTE, CAL, BVE, FAQ, NS = (
    "EIH-DE-REG-2026",
    "EIH-SRE-GUIDE-2026",
    "EIH-BRI-CHARTE-2026",
    "EIH-DE-CAL-2026",
    "EIH-BVE-GUIDE-2026",
    "EIH-SCOL-FAQ-2026",
    "EIH-DE-NS-2026-14",
)

CATEGORIES = ("factual", "numeric_table", "yes_no", "multi_part", "multi_doc", "version", "summary", "vague", "out_of_corpus")


def q(id, category, question, answer, keywords, refs, evidence):
    return {
        "id": id,
        "category": category,
        "question": question,
        "expected_found": category != "out_of_corpus",
        "expected_answer": answer,
        "answer_keywords": keywords,
        "expected_references": refs,
        "evidence": evidence,
    }


def ooc(id, question):
    return q(id, "out_of_corpus", question, NO_ANSWER, [], [], [])


QUESTIONS = [
    # ---------------- factual ----------------
    q("fact_01", "factual", "Combien de places de semestre d'études à l'étranger sont ouvertes au total ?",
      "16 places de semestre d'études sont ouvertes, dont 5 en double diplôme.", ["16 places", "5"], [CHARTE],
      ["16 places de semestre d'études sont ouvertes"]),
    q("fact_02", "factual", "Combien de jours avant le début d'un stage la convention doit-elle être déposée ?",
      "La convention signée doit être déposée sur le Portail Stages au moins 15 jours calendaires avant le début du stage.",
      ["15 jours", "calendaires"], [GUIDE], ["15 jours calendaires avant le début du stage"]),
    q("fact_03", "factual", "Quelle est la durée minimale du stage technique de fin de 2A ?",
      "Le stage technique dure au minimum 8 semaines.", ["8 semaines"], [GUIDE], ["Durée minimale : 8 semaines"]),
    q("fact_04", "factual", "Comment obtenir une attestation de scolarité et sous quel délai ?",
      "La demande se fait sur le Portail Scolarité, rubrique « Mes documents » ; l'attestation signée électroniquement est disponible sous 3 jours ouvrables.",
      ["Mes documents", "3 jours ouvrables"], [FAQ], ["disponible en version signée électroniquement sous 3 jours ouvrables"]),
    q("fact_05", "factual", "Combien d'ouvrages peut-on emprunter à la bibliothèque et pendant combien de temps ?",
      "4 ouvrages au maximum pour 3 semaines, renouvelable une fois.", ["4 ouvrages", "3 semaines", "renouvelable"], [BVE],
      ["4 ouvrages au maximum pour 3 semaines"]),
    q("fact_06", "factual", "Dans quel délai une absence doit-elle être justifiée ?",
      "Toute absence doit être justifiée dans un délai de 48 heures suivant la fin de l'absence.", ["48 heures"], [REG],
      ["justifiée dans un délai de 48 heures suivant la fin de l'absence"]),
    q("fact_07", "factual", "Quelle est la pondération du contrôle continu et de l'examen final dans la note d'un module ?",
      "Sauf disposition contraire de la fiche module : contrôle continu 40 %, examen final 60 %.", ["40 %", "60 %"], [REG],
      ["contrôle continu (CC) : 40 %"]),
    q("fact_08", "factual", "Quel est le délai pour formuler une réclamation sur une note ?",
      "La réclamation doit être formulée par écrit dans un délai de 5 jours ouvrables après la publication des résultats.",
      ["5 jours ouvrables"], [REG, FAQ], ["dans un délai de 5 jours ouvrables après la publication"]),
    q("fact_09", "factual", "Combien de redoublements sont autorisés sur l'ensemble du cycle ingénieur ?",
      "Un seul redoublement est autorisé ; un second échec entraîne l'exclusion définitive du cycle.", ["seul redoublement"], [REG],
      ["Un seul redoublement est autorisé sur l'ensemble du cycle"]),
    q("fact_10", "factual", "Quels sont les horaires d'ouverture du Bureau de la Vie Étudiante ?",
      "Le BVE est ouvert du lundi au vendredi, de 9h00 à 17h00.", ["9h00", "17h00"], [BVE],
      ["ouvert du lundi au vendredi, de 9h00 à 17h00"]),
    q("fact_11", "factual", "Combien de clubs actifs compte l'École ?",
      "L'École compte 18 clubs actifs, coordonnés par le BDE.", ["18 clubs"], [BVE], ["L'École compte 18 clubs actifs"]),
    q("fact_12", "factual", "Quel est le montant maximal de la subvention annuelle d'un club ?",
      "Le montant accordé est plafonné à 15 000 MAD par club et par an.", ["15 000 MAD"], [BVE],
      ["plafonné à 15 000 MAD par club et par an"]),
    q("fact_13", "factual", "Combien de temps à l'avance faut-il déclarer un événement organisé dans les locaux de l'École ?",
      "Il doit être déclaré au BVE au moins 3 semaines à l'avance.", ["3 semaines"], [BVE], ["au moins 3 semaines à l'avance"]),
    q("fact_14", "factual", "Quel est le délai pour obtenir un duplicata de carte d'étudiant ?",
      "Le Service de la Scolarité établit un duplicata dans un délai de 7 jours.", ["7 jours"], [FAQ],
      ["établit un duplicata dans un délai de 7 jours"]),
    q("fact_15", "factual", "Quand a lieu la rentrée universitaire 2026-2027 ?",
      "Le lundi 14 septembre 2026.", ["14 septembre 2026"], [CAL], ["Lundi 14 septembre 2026 ; Événement : Rentrée universitaire"]),
    q("fact_16", "factual", "Quelle doit être la longueur du rapport de PFE ?",
      "Le rapport de PFE fait 40 à 70 pages hors annexes.", ["40 à 70 pages"], [GUIDE], ["40 à 70 pages hors annexes"]),
    q("fact_17", "factual", "Quel taux de similarité déclenche l'examen d'un rapport de PFE par une commission ?",
      "Un taux de similarité supérieur à 25 %.", ["25 %"], [GUIDE], ["Un taux de similarité supérieur à 25 %"]),
    q("fact_18", "factual", "Quelle est la date de la cérémonie de remise des diplômes de la promotion 2027 ?",
      "Le samedi 23 octobre 2027.", ["23 octobre 2027"], [CAL], ["Samedi 23 octobre 2027"]),
    # ---------------- numbers & tables ----------------
    q("tab_01", "numeric_table", "Quelle mention obtient un étudiant avec une moyenne générale du cycle de 15/20 ?",
      "La mention Bien (moyenne de 14/20 à moins de 16/20).", ["Bien"], [REG], ["de 14/20 à moins de 16/20 ; Mention : Bien"]),
    q("tab_02", "numeric_table", "Comment est pondérée l'évaluation du PFE ?",
      "Travail en entreprise 30 % (encadrant en entreprise), rapport écrit 30 % (jury), soutenance orale 40 % (jury).",
      ["30 %", "40 %", "soutenance"], [GUIDE], ["Travail en entreprise ; Pondération : 30 %", "Soutenance orale ; Pondération : 40 %"]),
    q("tab_03", "numeric_table", "Combien de places propose l'Université Polytechnique de Valmorel et dans quelle langue sont les cours ?",
      "4 places, enseignement en anglais, sans double diplôme.", ["4", "anglais"], [CHARTE],
      ["Université Polytechnique de Valmorel ; Langue d'enseignement : Anglais ; Places : 4"]),
    q("tab_04", "numeric_table", "Quels établissements partenaires proposent un double diplôme ?",
      "L'Institut Nordique des Sciences Numériques (3 places) et la Hochschule Lindenfeld (2 places).",
      ["Institut Nordique", "Lindenfeld"], [CHARTE],
      ["Institut Nordique des Sciences Numériques ; Langue d'enseignement : Anglais ; Places : 3 ; Double diplôme : Oui",
       "Hochschule Lindenfeld ; Langue d'enseignement : Anglais ou allemand ; Places : 2 ; Double diplôme : Oui"]),
    q("tab_05", "numeric_table", "Quel est le montant de la Bourse Hélianthe Mobilité ?",
      "5 000 MAD par mois, pendant 5 mois au maximum, pour 10 étudiants au plus par an.", ["5 000 MAD", "5 mois"], [CHARTE],
      ["5 000 MAD par mois, pendant 5 mois au maximum"]),
    q("tab_06", "numeric_table", "Combien de crédits ECTS rapporte le stage d'initiation et sur quel semestre sont-ils validés ?",
      "2 crédits ECTS, validés en S3.", ["2", "S3"], [GUIDE], ["2 ECTS, validés en S3"]),
    q("tab_07", "numeric_table", "Combien de crédits ECTS compte le cycle ingénieur au total ?",
      "180 crédits : 30 par semestre, 60 par année, sur six semestres.", ["180 crédits"], [REG], ["180 crédits pour l'ensemble du cycle"]),
    q("tab_08", "numeric_table", "Quand se déroule la session de rattrapage en 2027 ?",
      "Du lundi 5 au vendredi 16 juillet 2027.", ["5", "16 juillet 2027"], [CAL], ["Du lundi 5 au vendredi 16 juillet 2027"]),
    q("tab_09", "numeric_table", "Comment est pondérée l'évaluation du stage technique ?",
      "Appréciation de l'entreprise 40 %, rapport 30 %, soutenance 30 %.", ["40 %", "30 %"], [GUIDE],
      ["appréciation de l'entreprise (40 %), rapport (30 %), soutenance (30 %)"]),
    q("tab_10", "numeric_table", "Quels sont les critères de sélection pour une mobilité et leur poids ?",
      "Moyenne de S3 (60 %), qualité du projet de mobilité (25 %), niveau de langue (15 %).", ["60 %", "25 %", "15 %"], [CHARTE],
      ["la moyenne de S3 (60 %), la qualité du projet de mobilité (25 %)"]),
    q("tab_11", "numeric_table", "Quand se déroulent les examens finaux des semestres S2 et S4 ?",
      "Du lundi 7 au vendredi 18 juin 2027.", ["7", "18 juin 2027"], [CAL], ["Du lundi 7 au vendredi 18 juin 2027"]),
    # ---------------- yes / no ----------------
    q("yn_01", "yes_no", "Un stage effectué sans convention peut-il être validé ?",
      "Non. Un stage effectué sans convention n'est pas reconnu et ne peut pas être validé.", ["Non"], [GUIDE],
      ["Un stage effectué sans convention n'est pas reconnu"]),
    q("yn_02", "yes_no", "La mobilité internationale est-elle obligatoire pour obtenir le diplôme ?",
      "Non, elle reste facultative et ne constitue pas une condition d'obtention du diplôme.", ["Non", "facultative"], [CHARTE],
      ["Elle reste facultative"]),
    q("yn_03", "yes_no", "Le PFE peut-il être validé par compensation ?",
      "Non, le PFE ne peut pas être compensé ; il est validé si la note est supérieure ou égale à 10/20.", ["Non"], [GUIDE, REG],
      ["Il ne peut pas être compensé"]),
    q("yn_04", "yes_no", "L'inscription au rattrapage est-elle automatique ?",
      "Non. Elle est obligatoire et se fait sur le Portail Scolarité dans les 5 jours ouvrables suivant la publication des résultats ; sans inscription, la note initiale est conservée.",
      ["Non", "obligatoire", "5 jours ouvrables"], [FAQ, REG], ["Elle est obligatoire et se fait sur le Portail Scolarité"]),
    q("yn_05", "yes_no", "Peut-on changer de filière après le début de la 2A ?",
      "Non, aucun changement n'est possible après le début de la 2A.", ["Non"], [FAQ],
      ["Aucun changement n'est possible après le début de la 2A"]),
    q("yn_06", "yes_no", "L'engagement dans le bureau d'un club donne-t-il des crédits ECTS ?",
      "Non. Il est mentionné dans le supplément au diplôme (après au moins une année complète) mais ne donne pas de crédits ECTS.",
      ["Non", "supplément au diplôme"], [BVE], ["ne donne pas lieu à l'attribution de crédits ECTS"]),
    q("yn_07", "yes_no", "Un étudiant en PFE peut-il passer le rattrapage d'un module de S5 ?",
      "Oui, il est convoqué à la session de rattrapage de juillet et l'entreprise est informée pour le libérer.", ["Oui", "juillet"], [FAQ],
      ["Les étudiants en PFE sont convoqués à la session de rattrapage de juillet"]),
    q("yn_08", "yes_no", "Les consultations de la cellule d'écoute sont-elles payantes ?",
      "Non, elles sont gratuites et confidentielles, sur rendez-vous pris auprès du BVE.", ["Non", "gratuite"], [BVE],
      ["de façon confidentielle et gratuite"]),
    # ---------------- multi-part ----------------
    q("mp_01", "multi_part", "Quelles sont la durée minimale, la période de réalisation et la longueur du rapport du stage d'initiation ?",
      "4 semaines minimum, entre le 1er juillet et le 31 août ; rapport de 10 à 15 pages.", ["4 semaines", "31 août", "10 à 15 pages"], [GUIDE],
      ["Durée minimale : 4 semaines, entre le 1er juillet et le 31 août", "un rapport de 10 à 15 pages"]),
    q("mp_02", "multi_part", "Combien de temps dure la soutenance du PFE et comment le jury est-il composé ?",
      "30 minutes de présentation et 20 minutes d'échanges, devant un jury de trois membres : un président (enseignant), l'encadrant académique et l'encadrant en entreprise ou son représentant.",
      ["30 minutes", "20 minutes", "président", "encadrant académique"], [GUIDE], ["30 minutes de présentation suivies de 20 minutes d'échanges"]),
    q("mp_03", "multi_part", "À quelles conditions un module peut-il être validé par compensation ?",
      "Si la moyenne pondérée du semestre est d'au moins 10/20 et qu'aucune note de module du semestre n'est inférieure à 7/20 ; uniquement au sein d'un même semestre, ni pour le PFE ni pour les stages.",
      ["10/20", "7/20", "même semestre"], [REG],
      ["la moyenne pondérée du semestre est supérieure ou égale à 10/20", "aucune note de module du semestre n'est inférieure à 7/20"]),
    q("mp_04", "multi_part", "Quelles sont les conditions de délivrance du diplôme d'ingénieur ?",
      "Avoir acquis les 180 crédits dont les 30 du PFE, avoir validé le stage d'initiation et le stage technique, et justifier d'un niveau d'anglais B2 au plus tard à la soutenance du PFE.",
      ["180 crédits", "stage d'initiation", "stage technique", "B2"], [REG],
      ["avoir acquis les 180 crédits du cycle, dont les 30 crédits du PFE", "justifier d'un niveau d'anglais B2"]),
    q("mp_05", "multi_part", "Comment demander un aménagement d'épreuves et en combien de temps la décision est-elle rendue ?",
      "Prendre rendez-vous avec le référent accessibilité du BVE, déposer la demande avec un certificat médical récent avant le 30 octobre (ou dans les 15 jours suivant le diagnostic) ; la commission notifie sa décision sous 3 semaines.",
      ["référent accessibilité", "certificat médical", "30 octobre", "3 semaines"], [BVE],
      ["Prendre rendez-vous avec le référent accessibilité du BVE", "notifie sa décision dans un délai de 3 semaines"]),
    q("mp_06", "multi_part", "Quelles sanctions sont possibles en cas de fraude ou de plagiat ?",
      "Après saisine du Conseil de discipline : avertissement, blâme, 0/20 au module sans accès au rattrapage, exclusion temporaire d'un an au maximum, exclusion définitive.",
      ["avertissement", "blâme", "0/20", "exclusion"], [REG],
      ["la note de 0/20 au module concerné, sans accès au rattrapage", "l'exclusion temporaire de l'École pour une durée maximale d'un an"]),
    q("mp_07", "multi_part", "Que doit contenir l'annexe de déclaration d'utilisation de l'IA générative du rapport de PFE ?",
      "Les outils utilisés, les parties du travail concernées et la manière dont l'étudiant a vérifié les contenus produits ; si aucun outil n'a été utilisé, l'annexe le précise.",
      ["outils utilisés", "parties du travail", "vérifiés"], [NS],
      ["Déclaration d'utilisation des outils d'IA générative", "la manière dont les contenus produits ont été vérifiés par l'étudiant"]),
    # ---------------- multi-document ----------------
    q("md_01", "multi_doc", "Que doit faire un groupe d'étudiants pour créer un club et obtenir une subvention ?",
      "Déposer au BVE un dossier avec au moins 10 membres fondateurs, un enseignant référent, des statuts et une présentation des objectifs ; la subvention se demande au BVE avant le 30 octobre avec un budget prévisionnel.",
      ["10", "enseignant référent", "statuts", "30 octobre", "budget prévisionnel"], [BVE, CAL],
      ["une liste d'au moins 10 étudiants membres fondateurs", "avant le 30 octobre avec un budget prévisionnel"]),
    q("md_02", "multi_doc", "Quand déposer un dossier de mobilité 2027-2028 et quelle condition confirme la sélection après la 2A ?",
      "Le dossier est déposé au plus tard le 15 mars ; la sélection est confirmée si l'étudiant valide sa 2A sans dette avec une moyenne annuelle d'au moins 12/20.",
      ["15 mars", "sans dette", "12/20"], [CHARTE, CAL], ["15 mars de l'année précédant le départ", "valider sa 2A sans dette"]),
    q("md_03", "multi_doc", "Pour un PFE débutant en février 2027, indiquez la fenêtre de début, la durée minimale et le délai de dépôt du rapport.",
      "Début entre le 1er février et le 1er mars, durée minimale de 18 semaines (note de service 2026-14), rapport déposé au plus tard 14 jours calendaires avant la soutenance.",
      ["1er février", "1er mars", "18 semaines", "14 jours"], [GUIDE, CAL, NS],
      ["portée de 16 semaines à 18 semaines", "14 jours calendaires avant la date de soutenance"]),
    q("md_04", "multi_doc", "Un étudiant malade le jour d'un examen doit-il s'inscrire au rattrapage et dans quel délai doit-il fournir son certificat ?",
      "Il dépose le certificat dans les 48 heures suivant la fin de son absence et doit s'inscrire au rattrapage dans les délais ; si le justificatif est accepté, sa note n'est pas plafonnée.",
      ["48 heures", "inscrire", "pas plafonnée"], [FAQ, REG], ["48 heures suivant la fin", "Vous devez aussi vous inscrire au rattrapage dans les délais"]),
    q("md_05", "multi_doc", "Quelles autorisations faut-il pour réaliser un PFE à l'étranger et la soutenance peut-elle se faire à distance ?",
      "L'accord du responsable de filière et du BRI ; les règles restent identiques et la soutenance peut avoir lieu par visioconférence.",
      ["responsable de filière", "BRI", "visioconférence"], [GUIDE, CHARTE],
      ["responsable de filière et du Bureau des Relations Internationales", "La soutenance peut avoir lieu par visioconférence"]),
    q("md_06", "multi_doc", "Un étudiant à qui il manque 6 crédits en fin de 2A peut-il passer en 3A et partir en semestre d'études à l'étranger ?",
      "Le jury peut l'autoriser à passer en 3A sous condition (dette d'au plus 6 crédits), mais sa mobilité serait annulée : la sélection exige de valider la 2A sans dette.",
      ["passage conditionnel", "sans dette", "annulée"], [REG, CHARTE], ["n'a pas acquis au plus 6 crédits", "valider sa 2A sans dette"]),
    q("md_07", "multi_doc", "Un étudiant en mobilité au S5 doit soutenir son stage technique : quand et comment ?",
      "En octobre de la 3A (du 4 au 15 octobre 2026), à distance par visioconférence.", ["octobre", "visioconférence"], [CHARTE, GUIDE, CAL],
      ["se déroule par visioconférence pour les étudiants en mobilité", "Du lundi 4 au vendredi 15 octobre 2026"]),
    q("md_08", "multi_doc", "J'ai manqué un examen de S3 sans justificatif. Quelle note aurai-je au mieux après rattrapage et jusqu'à quand dois-je m'y inscrire ?",
      "0/20 à l'épreuve ; au rattrapage la note est plafonnée à 12/20 ; inscription au plus tard le vendredi 12 février 2027.",
      ["0/20", "12/20", "12 février 2027"], [REG, FAQ, CAL], ["plafonnée à 12/20", "12 février 2027"]),
    q("md_09", "multi_doc", "Quand doit être déposée la fiche sujet de PFE et qui valide le sujet ?",
      "Au plus tard le mardi 15 décembre 2026 ; le sujet est validé par le responsable de filière.", ["15 décembre 2026", "responsable de filière"], [CAL, GUIDE],
      ["Date limite de dépôt de la fiche sujet de PFE", "Le responsable de filière valide le sujet"]),
    q("md_10", "multi_doc", "Quand ont lieu les soutenances de PFE de la session 2 et pour quels PFE sont-elles prévues ?",
      "Du lundi 20 septembre au vendredi 1er octobre 2027 ; notamment pour les PFE terminant après la mi-juillet et les PFE réalisés à l'étranger.",
      ["20 septembre", "1er octobre 2027", "mi-juillet", "étranger"], [CAL, GUIDE],
      ["Du lundi 20 septembre au vendredi 1er octobre 2027", "aux PFE terminant après la mi-juillet"]),
    q("md_11", "multi_doc", "Jusqu'à quand peut-on demander une année de césure en 2027 et à quel moment du cursus se fait-elle ?",
      "Avant le vendredi 30 avril 2027 ; une seule année de césure est possible, entre la 2A et la 3A, avec l'accord de la Direction des Études.",
      ["30 avril", "entre la 2A et la 3A"], [CAL, FAQ], ["Date limite des demandes d'année de césure", "une seule année de césure est possible, entre la 2A et la 3A"]),
    # ---------------- version / amendments ----------------
    q("ver_01", "version", "Quelle est la durée minimale d'un PFE qui commence en février 2027 ?",
      "18 semaines : la note de service 2026-14 a remplacé les 16 semaines du guide des stages.", ["18 semaines"], [NS, GUIDE],
      ["portée de 16 semaines à 18 semaines"]),
    q("ver_02", "version", "Combien de jours avant la soutenance faut-il déposer le rapport de PFE à partir de février 2027 ?",
      "14 jours calendaires avant la soutenance, au lieu de 10 jours dans le guide (note de service 2026-14).", ["14 jours"], [NS, GUIDE],
      ["14 jours calendaires avant la date de soutenance"]),
    q("ver_03", "version", "La note de service 2026-14 modifie-t-elle les règles du stage technique ?",
      "Non, elle ne modifie pas les règles du stage d'initiation ni du stage technique ; elle ne concerne que le PFE.", ["Non"], [NS],
      ["ne modifie pas les règles applicables au stage d'initiation"]),
    q("ver_04", "version", "Quelle est la durée maximale d'un PFE en 2027 ?",
      "24 semaines, inchangée par la note de service 2026-14.", ["24 semaines"], [NS, GUIDE], ["La durée maximale reste fixée à 24 semaines"]),
    q("ver_05", "version", "Un PFE réalisé à l'étranger et débutant en février 2027 doit-il durer au moins 18 semaines ?",
      "Oui : la note de service s'applique à tous les PFE débutant à partir du 1er février 2027, y compris à l'étranger.", ["Oui", "18 semaines"], [NS],
      ["y compris les PFE réalisés à l'étranger"]),
    q("ver_06", "version", "Que se passe-t-il si le rapport de PFE ne contient pas l'annexe de déclaration d'IA générative ?",
      "Le rapport est irrecevable jusqu'à sa régularisation ; une utilisation substantielle non déclarée constitue une fraude.", ["irrecevable"], [NS],
      ["rend le rapport irrecevable jusqu'à sa régularisation"]),
    # ---------------- summaries ----------------
    q("sum_01", "summary", "Résume les règles de la session de rattrapage.",
      "Session unique en fin d'année pour les modules non validés et non compensés de tous les semestres ; inscription obligatoire dans les 5 jours ouvrables ; note plafonnée à 12/20 sauf absence justifiée ; le contrôle continu n'est pas repris ; la meilleure des deux notes est retenue.",
      ["unique", "inscription", "12/20", "meilleure"], [REG],
      ["Une session de rattrapage unique est organisée en fin d'année", "la meilleure des deux est retenue"]),
    q("sum_02", "summary", "Quels services propose le Bureau de la Vie Étudiante ?",
      "Il accompagne les étudiants pour le logement, la santé (cellule d'écoute), l'accessibilité et les aménagements, les clubs et les événements ; ouvert du lundi au vendredi de 9h à 17h.",
      ["logement", "santé", "accessibilité", "clubs"], [BVE], ["logement, santé, accessibilité, clubs et événements"]),
    q("sum_03", "summary", "Quelles sont les étapes de la candidature à une mobilité internationale ?",
      "Dépôt du dossier avant le 15 mars, commission de sélection fin mars, résultats au plus tard le 15 avril, contrat d'études signé avant le 30 juin, confirmation après les délibérations de juillet.",
      ["15 mars", "15 avril", "30 juin", "juillet"], [CHARTE],
      ["Réunion de la commission de sélection", "Signature du contrat d'études (learning agreement)"]),
    q("sum_04", "summary", "Quels sont les changements introduits par la note de service 2026-14 ?",
      "Durée minimale du PFE portée de 16 à 18 semaines, rapport à déposer 14 jours (au lieu de 10) avant la soutenance, annexe obligatoire de déclaration d'IA générative ; applicable aux PFE débutant à partir du 1er février 2027.",
      ["18 semaines", "14 jours", "IA"], [NS], [["portée de 16 semaines à 18 semaines", "À partir de la présente note : 18 semaines"], "Annexe obligatoire dans le rapport"]),
    q("sum_05", "summary", "Quelles sont les périodes en milieu professionnel du cycle ingénieur ?",
      "Stage d'initiation en fin de 1A (4 semaines min.), stage technique en fin de 2A (8 semaines min.), PFE en 3A au semestre S6 (18 à 24 semaines depuis la note de service 2026-14).",
      ["stage d'initiation", "stage technique", "PFE"], [GUIDE],
      ["Stage d'initiation ; Année : Fin de 1A", "Projet de Fin d'Études ; Année : 3A (S6)"]),
    # ---------------- vague / colloquial ----------------
    q("vague_01", "vague", "je suis malade je fais quoi ?",
      "Justifier l'absence dans les 48 heures suivant sa fin (certificat médical au Service de la Scolarité ou sur le Portail Scolarité) ; si un examen est manqué, l'épreuve est repassée au rattrapage sans plafonnement.",
      ["48 heures", "certificat"], [REG, FAQ], ["48 heures suivant la fin"]),
    q("vague_02", "vague", "c'est quoi les règles pour l'IA ?",
      "L'IA générative n'est autorisée dans un travail évalué que si la fiche module ou l'enseignant l'autorise explicitement, avec déclaration des outils ; sinon c'est une fraude. Pour le PFE, une annexe de déclaration est obligatoire.",
      ["autorise", "déclar", "fraude"], [REG, FAQ, NS], ["n'est autorisée que si la fiche module"]),
    q("vague_03", "vague", "logement ?",
      "La résidence étudiante compte 320 lits en chambres individuelles ; demande sur le Portail Scolarité avant le 15 juillet ; priorité aux entrants en 1A et aux boursiers.",
      ["320 lits", "15 juillet"], [BVE], ["La résidence étudiante de l'École compte 320 lits"]),
    q("vague_04", "vague", "j'ai eu 8 dans un module mais 11 de moyenne au semestre, je dois repasser ?",
      "Non, si aucune autre note du semestre n'est inférieure à 7/20, le module est validé par compensation (moyenne du semestre ≥ 10/20).",
      ["compensation", "7/20"], [REG], ["aucune note de module du semestre n'est inférieure à 7/20"]),
    q("vague_05", "vague", "mon stage commence lundi et j'ai pas encore déposé ma convention, c'est grave ?",
      "Oui : la convention signée doit être déposée au moins 15 jours calendaires avant le début, et un stage sans convention n'est pas reconnu ni validé.",
      ["15 jours", "pas reconnu"], [GUIDE], ["15 jours calendaires avant le début du stage"]),
    # ---------------- out of corpus ----------------
    ooc("ooc_01", "Quel est le montant des frais de scolarité annuels de l'EIH ?"),
    ooc("ooc_02", "Quel est le mot de passe du Wi-Fi étudiant ?"),
    ooc("ooc_03", "Quels sont les horaires de la navette entre l'École et le centre-ville ?"),
    ooc("ooc_04", "Quel est le prix mensuel d'une chambre à la résidence étudiante ?"),
    ooc("ooc_05", "Quelle est la date des prochains concours d'admission à l'EIH ?"),
    ooc("ooc_06", "Combien coûte un repas au restaurant de l'École ?"),
    ooc("ooc_07", "Quel est le nom du directeur de l'EIH ?"),
    ooc("ooc_08", "Quel est le numéro de téléphone du Service de la Scolarité ?"),
    ooc("ooc_09", "Quel était le taux de réussite au diplôme de la promotion 2026 ?"),
    ooc("ooc_10", "L'École met-elle un parking à disposition des étudiants ?"),
]


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.replace("’", "'")
    return re.sub(r"\s+", " ", value.lower()).strip()


def corpus_texts() -> dict[str, str]:
    from eih_rag.extraction import extract_pdf

    texts = {}
    for pdf in sorted((ROOT / "corpus").glob("*.pdf")):
        metadata, pages = extract_pdf(pdf)
        texts[metadata.reference] = normalize("\n".join(page.text for page in pages))
    return texts


def main() -> int:
    ids = [item["id"] for item in QUESTIONS]
    assert len(ids) == len(set(ids)), "identifiants dupliques"
    texts = corpus_texts()
    errors = []
    for item in QUESTIONS:
        assert item["category"] in CATEGORIES, item["id"]
        for evidence in item["evidence"]:
            # Une preuve peut etre une liste de formulations equivalentes (meme fait dans deux documents).
            alternatives = evidence if isinstance(evidence, list) else [evidence]
            owners = [ref for ref, text in texts.items() if any(normalize(alt) in text for alt in alternatives)]
            if not owners:
                errors.append(f"{item['id']}: preuve introuvable -> {evidence!r}")
            elif not set(owners) & set(item["expected_references"]):
                errors.append(f"{item['id']}: preuve trouvee dans {owners}, hors references attendues")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    output = ROOT / "eval" / "testset.jsonl"
    output.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in QUESTIONS), encoding="utf-8")
    from collections import Counter

    print(f"{len(QUESTIONS)} questions -> {output}")
    print(dict(Counter(item["category"] for item in QUESTIONS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
