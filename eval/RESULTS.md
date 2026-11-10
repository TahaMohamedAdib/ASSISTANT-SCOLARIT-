# Résultats d'évaluation — Assistant Scolarité EIH

## Jeu de test

`eval/testset.jsonl` contient **81 questions** générées et vérifiées par `eval/build_testset.py` :

| Catégorie | Nombre | Ce qu'elle teste |
| --- | --- | --- |
| factual | 18 | une information précise |
| numeric_table | 11 | chiffres, délais, tableaux |
| multi_doc | 11 | réponse répartie sur plusieurs documents |
| out_of_corpus | 10 | l'assistant doit répondre « introuvable » |
| yes_no | 8 | question fermée |
| multi_part | 7 | plusieurs sous-questions |
| version | 6 | une note de service modifie une règle antérieure |
| summary | 5 | synthèse |
| vague | 5 | formulation imprécise |

Chaque question dispose d'une réponse de référence et de **preuves** recopiées mot pour mot des PDF ; le script vérifie que chaque preuve existe dans le document attendu. Les métriques de recherche sont calculées **au niveau du passage** : une preuve compte comme retrouvée si son texte figure dans l'un des k fragments transmis au LLM.

- **Recall@k** : part des preuves retrouvées.
- **FullRecall@k** : part des questions dont *toutes* les preuves sont retrouvées. C'est la métrique décisive : sans toutes les preuves, le LLM ne peut pas répondre complètement.
- **MRR** : rang du premier fragment utile.

Ces métriques portent sur les 71 questions qui ont une réponse dans le corpus.

## 1. Recherche (terminée)

Commande : `python eval/experiments.py retrieval --grid <baseline|chunking|mode|embedding|topk|rerank>`. Les résultats bruts sont dans `eval/results/retrieval_experiments.csv` ; ce tableau est produit par `python eval/make_tables.py`.

| Expérience | Découpage | Embedding | Mode (poids dense) | Reranker | k | Recall@k | FullRecall@k | MRR | s/question |
|---|---|---|---|---|---|---|---|---|---|
| baseline_dense_fixed | fixed 500/100 | MiniLM-L12-v2 | dense | — | 5 | 0.711 | 0.634 | 0.611 | 0.11 |
| baseline_dense_structural | structural 500/100 | MiniLM-L12-v2 | dense | — | 5 | 0.817 | 0.775 | 0.679 | 0.11 |
| chunk_fixed_300_50 | fixed 300/50 | MiniLM-L12-v2 | hybrid (0.5) | — | 5 | 0.796 | 0.718 | 0.667 | 0.12 |
| chunk_fixed_500_100 | fixed 500/100 | MiniLM-L12-v2 | hybrid (0.5) | — | 5 | 0.838 | 0.775 | 0.705 | 0.12 |
| chunk_fixed_800_150 | fixed 800/150 | MiniLM-L12-v2 | hybrid (0.5) | — | 5 | 0.859 | 0.831 | 0.695 | 0.11 |
| chunk_fixed_1200_200 | fixed 1200/200 | MiniLM-L12-v2 | hybrid (0.5) | — | 5 | 0.845 | 0.817 | 0.649 | 0.11 |
| chunk_structural_300_50 | structural 300/50 | MiniLM-L12-v2 | hybrid (0.5) | — | 5 | 0.866 | 0.817 | 0.759 | 0.11 |
| chunk_structural_500_100 | structural 500/100 | MiniLM-L12-v2 | hybrid (0.5) | — | 5 | 0.908 | 0.859 | 0.803 | 0.11 |
| chunk_structural_800_150 | structural 800/150 | MiniLM-L12-v2 | hybrid (0.5) | — | 5 | 0.923 | 0.873 | 0.808 | 0.10 |
| chunk_structural_1200_200 | structural 1200/200 | MiniLM-L12-v2 | hybrid (0.5) | — | 5 | 0.951 | 0.930 | 0.833 | 0.11 |
| mode_dense | structural 500/100 | MiniLM-L12-v2 | dense | — | 5 | 0.817 | 0.775 | 0.679 | 0.11 |
| mode_bm25 | structural 500/100 | MiniLM-L12-v2 | bm25 | — | 5 | 0.944 | 0.901 | 0.870 | 0.05 |
| mode_hybrid | structural 500/100 | MiniLM-L12-v2 | hybrid (0.5) | — | 5 | 0.908 | 0.859 | 0.803 | 0.11 |
| weight_0.3 | structural 500/100 | MiniLM-L12-v2 | hybrid (0.3) | — | 5 | 0.930 | 0.887 | 0.829 | 0.11 |
| weight_0.7 | structural 500/100 | MiniLM-L12-v2 | hybrid (0.7) | — | 5 | 0.908 | 0.859 | 0.780 | 0.10 |
| topk_3 | structural 500/100 | MiniLM-L12-v2 | hybrid (0.5) | — | 3 | 0.866 | 0.817 | 0.793 | 0.10 |
| topk_5 | structural 500/100 | MiniLM-L12-v2 | hybrid (0.5) | — | 5 | 0.908 | 0.859 | 0.803 | 0.11 |
| topk_8 | structural 500/100 | MiniLM-L12-v2 | hybrid (0.5) | — | 8 | 0.951 | 0.915 | 0.808 | 0.10 |
| topk_10 | structural 500/100 | MiniLM-L12-v2 | hybrid (0.5) | — | 10 | 0.951 | 0.915 | 0.808 | 0.11 |
| e5_dense_500 | structural 500/100 | e5-base | dense | — | 5 | 0.958 | 0.915 | 0.883 | 0.30 |
| e5_hybrid_500 | structural 500/100 | e5-base | hybrid (0.5) | — | 5 | 0.951 | 0.915 | 0.911 | 0.28 |
| e5_dense_800 | structural 800/150 | e5-base | dense | — | 5 | 0.972 | 0.944 | 0.876 | 0.27 |
| e5_hybrid_800 | structural 800/150 | e5-base | hybrid (0.5) | — | 5 | 0.958 | 0.930 | 0.912 | 0.27 |
| e5_dense_1200 | structural 1200/200 | e5-base | dense | — | 5 | 0.972 | 0.944 | 0.891 | 0.25 |
| e5_hybrid_1200 | structural 1200/200 | e5-base | hybrid (0.5) | — | 5 | 0.965 | 0.944 | 0.908 | 0.25 |
| e5_hybrid_1200_w0.3 | structural 1200/200 | e5-base | hybrid (0.3) | — | 5 | 0.965 | 0.944 | 0.906 | 0.26 |
| e5_hybrid_1200_w0.7 | structural 1200/200 | e5-base | hybrid (0.7) | — | 5 | 0.972 | 0.944 | 0.911 | 0.27 |
| minilm_hybrid_1200_w0.3 | structural 1200/200 | MiniLM-L12-v2 | hybrid (0.3) | — | 5 | 0.965 | 0.944 | 0.900 | 0.10 |
| bm25_1200 | structural 1200/200 | MiniLM-L12-v2 | bm25 | — | 5 | 0.965 | 0.944 | 0.874 | 0.04 |
| bgem3_dense_800 | structural 800/150 | bge-m3 | dense | — | 5 | 0.965 | 0.930 | 0.913 | 0.79 |
| bgem3_hybrid_800 | structural 800/150 | bge-m3 | hybrid (0.7) | — | 5 | 0.972 | 0.958 | 0.915 | 0.80 |
| bgem3_dense_1200 | structural 1200/200 | bge-m3 | dense | — | 5 | 0.979 | 0.958 | 0.903 | 0.76 |
| bgem3_hybrid_1200 | structural 1200/200 | bge-m3 | hybrid (0.7) | — | 5 | 0.979 | 0.972 | 0.896 | 0.51 |
| e5_hybrid_800_rr_mmarco | structural 800/150 | e5-base | hybrid (0.7) | mmarco-mMiniLMv2-L12-H384-v1 | 5 | 0.951 | 0.915 | 0.908 | 3.63 |
| e5_1200_qexp | structural 1200/200 | e5-base | hybrid (0.7) + expansion | — | 5 | 0.965 | 0.930 | 0.913 | 2.52 |
| **e5_1200_w0.7_k6** (retenue) | structural 1200/200 | e5-base | hybrid (0.7) | — | 6 | 0.979 | **0.958** | 0.911 | 0.31 |
| e5_1200_w0.7_k8 | structural 1200/200 | e5-base | hybrid (0.7) | — | 8 | 0.979 | 0.958 | 0.911 | 0.29 |
| e5_hybrid_800_rr_bge | structural 800/150 | e5-base | hybrid (0.7) | bge-reranker-v2-m3 | 5 | 0.979 | 0.958 | 0.897 | 32.17 |
| e5_hybrid_1200_rr_mmarco | structural 1200/200 | e5-base | hybrid (0.7) | mmarco-mMiniLMv2-L12-H384-v1 | 5 | 0.965 | 0.944 | 0.911 | 3.69 |

### Ce que montrent les expériences

1. **Le découpage structurel est le gain le plus important.** Avec le même modèle (MiniLM, dense, k=5), FullRecall@5 passe de **0,634** (découpage fixe de 500 caractères) à **0,775** (découpage par titres, articles et Q/R). En recherche hybride à 1200/200, le structurel atteint 0,930 contre 0,817 pour le fixe : les articles du règlement et les tableaux restent entiers, avec leur chemin de titres.
2. **L'hybride compense un embedding faible**, mais n'apporte presque plus rien avec un bon embedding. Avec MiniLM, BM25 seul (0,901) bat le dense seul (0,775). Avec e5-base en 1200/200, dense et hybride sont à égalité en FullRecall (0,944) ; l'hybride avec un poids dense de 0,7 améliore surtout le MRR (0,891 → 0,911), c'est-à-dire que le bon passage est mieux classé.
3. **L'embedding.** e5-base obtient 0,944 en 0,27 s par question. bge-m3 hybride obtient 0,972, mais avec un modèle 2,3 fois plus lourd et une latence environ deux fois plus élevée sur CPU.
4. **Les rerankers n'aident pas sur ce corpus.**
   - mmarco : aucun gain en 1200 (0,944), une baisse en 800 (0,915), pour 3,7 s par question.
   - bge-reranker-v2-m3 : 0,958, mais 32 s par question sur CPU.
   - L'expansion de requête par LLM baisse à 0,930 et coûte 2,5 s plus un appel LLM.

   Les deux options restent dans le code, désactivées par défaut.
5. **k=6** récupère une question de plus qu'à k=5 (0,944 → **0,958**) pour un coût négligeable. À k=8, plus rien ne change.

### Configuration retenue

La configuration retenue est la suivante : découpage structurel 1200/200, `intfloat/multilingual-e5-base`, recherche hybride RRF (dense 0,7 / BM25 0,3), k=6, sans reranker ni expansion. Elle obtient **FullRecall@6 = 0,958, Recall@6 = 0,979 et MRR = 0,911**, en 0,3 s par question sur CPU.

bge-m3 hybride ferait gagner une question (0,972) au prix d'un modèle 2,3 fois plus lourd et d'une latence plus élevée ; pour un service étudiant sur un serveur CPU, e5-base est le meilleur compromis.

Les trois questions encore incomplètes à k=6 sont des questions multi-documents ou de synthèse dont la dernière preuve est classée juste après le 6ᵉ fragment : `md_06` (le passage « valider sa 2A sans dette » de la charte), `md_08` et `sum_04`.

**Vérification sur l'index de l'application.** Le bouton « Évaluer la recherche » de la page Admin interroge l'index réellement servi, construit document par document par `DocumentService`. Le 10/11/2026, il a donné **FullRecall@6 = 0,986** et MRR = 0,911. L'écart de deux questions avec le banc hors ligne (0,958), qui reconstruit son propre index, n'a pas été analysé ; les deux mesures situent la configuration au même niveau.

## 2. Génération (incomplète : quota)

Méthode : `python eval/experiments.py generate --name <nom> --set ...`.

- Le générateur est `openai/gpt-oss-120b` (Groq).
- Un juge distinct, `qwen/qwen3.8-27b`, note l'**exactitude** de 0 à 2 par rapport à la référence, la **fidélité** (chaque affirmation est soutenue par les extraits) et le **refus**.
- Le script calcule ensuite les refus corrects (hors corpus), les refus à tort et les citations invalides.

**Statut.** L'évaluation complète n'a pas pu être terminée. L'offre gratuite de Groq limite chaque modèle à **200 000 jetons par jour**. Une passe des 81 questions consomme environ 4 000 jetons de génération et 5 000 jetons de jugement par question, soit environ 330 000 jetons pour le générateur et 400 000 pour le juge : une passe complète demande donc deux jours de quota par modèle. Trois passes étaient prévues : la configuration finale avec le prompt v3, la même recherche avec le prompt initial v1, et la configuration d'origine. Elles ont été lancées le 10/11/2026, puis arrêtées quand le quota des deux modèles a été épuisé.

**Résultat provisoire.** Une passe interrompue (prompt v2, configuration finale) a couvert 56 questions sur 81 :

- 50 réponses entièrement correctes ;
- 5 partielles, avec un détail omis (`fact_01`, `fact_07`, `tab_05`, `yn_04`, `md_09`) ;
- 1 fausse (`md_06`, dont la preuve manque déjà à la recherche, voir ci-dessus).

Ces chiffres proviennent du journal de cette passe, écrasé lors de la relance. Ils ne sont pas reproductibles à partir des fichiers du dépôt et ne doivent pas être cités comme résultat final.

Comportements vérifiés dans l'application pendant le développement :

- **Hors corpus** (« menu de la cafétéria ») : la réponse est le refus exact, et l'interface affiche le contact de la scolarité.
- **Versions** (« durée minimale d'un PFE qui commence en février 2027 ») : 18 semaines, en citant la note de service 2026-14 et en précisant qu'elle remplace les 16 semaines du guide.
- **Question à deux parties dont une est absente du corpus** : la partie couverte reçoit une réponse et l'autre est signalée ; l'interface affiche « Une partie de la question n'est pas couverte ».
- **Injection** dans un fichier joint : ignorée (voir le README, section Sécurité).

### Pour terminer l'évaluation

Les passes sont reprenables grâce au cache des appels LLM (`eval/results/llm_cache.json`). Un défaut qui faisait s'écraser mutuellement les entrées du générateur et du juge a été corrigé : une passe interrompue repart désormais des réponses déjà obtenues.

```powershell
$E5 = "embedding=intfloat/multilingual-e5-base", "chunk_size=1200", "overlap=200", "dense_weight=0.7", "top_k=6"
python eval/experiments.py generate --name final_v3 --set @E5 prompt=v3                   # configuration retenue
python eval/experiments.py generate --name final_retrieval_prompt_v1 --set @E5 prompt=v1  # effet du prompt
python eval/experiments.py generate --name original_setup_v1 --set strategy=fixed chunk_size=500 overlap=100 mode=dense top_k=5 prompt=v1
python eval/make_tables.py                                                                # tableaux Markdown
```

Pour rester dans le quota, trois options :

- Répartir une passe sur deux jours (`--ids` permet aussi d'évaluer un sous-ensemble).
- Utiliser un juge sur un autre quota (`--judge openai/gpt-oss-20b`).
- Passer à l'offre payante de Groq.

## Limites de l'évaluation

- Le juge est un LLM : ses notes de 0 à 2 sont comparables d'une configuration à l'autre, mais pas infaillibles.
- Le jeu de test a été écrit par la même équipe que le système, d'après les mêmes documents. Les questions vagues et hors corpus limitent ce biais sans le supprimer.
- Le corpus est petit (7 documents, 96 fragments) : un écart d'une ou deux questions entre configurations est à interpréter avec prudence.
