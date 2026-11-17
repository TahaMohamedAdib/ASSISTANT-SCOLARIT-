# Assistant Scolarité EIH

Application RAG (Retrieval-Augmented Generation) qui répond aux questions des étudiants à partir des PDF indexés. Le corpus initial de l'École d'Ingénieurs Hélianthe contient sept documents officiels : règlement des études, guide des stages et du PFE, charte de mobilité, calendrier académique, guide de la vie étudiante, FAQ scolarité et note de service 2026-14.

- Backend : API FastAPI et interface en ligne de commande, index vectoriel persistant Chroma.
- Frontend : application React TypeScript.
- Les PDF officiels de `corpus/` sont en lecture seule pour l'API. Les PDF téléversés sont conservés dans `data/uploads/`.

Les résultats d'évaluation et le choix de la configuration sont détaillés dans [eval/RESULTS.md](eval/RESULTS.md).

## Architecture

```
PDF ──► extraction (pdfplumber)          tableaux rendus ligne à ligne avec leurs en-têtes,
        │                                marges répétées et puces "(cid:127)" nettoyées
        ▼
   découpage structurel                  titres > articles > sous-sections > Q/R de FAQ,
        │                                hiérarchie conservée d'une page à l'autre,
        │                                1200 caractères, chevauchement 200
        ▼
   index Chroma (multilingual-e5-base)   texte indexé = titre du document > chemin des titres + contenu
        │
question ──► recherche hybride           dense (Chroma) + BM25 (rank-bm25), fusion RRF (poids dense 0,7)
        │    [option] reranker           cross-encoder multilingue (désactivé : voir RESULTS.md)
        │    [option] expansion          sous-requêtes générées par le LLM (désactivée : voir RESULTS.md)
        ▼
   top-6 fragments ──► LLM (Groq, openai/gpt-oss-120b)
                       prompt contraint : réponse fondée sur les extraits uniquement, citations [n],
                       règle des versions (une note de service prévaut), refus exact hors corpus
```

| Module | Rôle |
| --- | --- |
| `src/eih_rag/extraction.py` | Extraction par page, métadonnées (référence, type, date, version), tableaux contextualisés |
| `src/eih_rag/chunking.py` | Découpages `structural` (par défaut) et `fixed` |
| `src/eih_rag/rag/store.py` | Adaptateur Chroma (reconstruction idempotente, lecture du corpus pour BM25) |
| `src/eih_rag/rag/retrieval.py` | Recherche hybride, fusion RRF, reranker, expansion de requête |
| `src/eih_rag/rag/prompting.py` | Prompts `v1` (initial) et `v2` (retenu), contrôle des citations |
| `src/eih_rag/rag/llm.py` | Clients Ollama et OpenAI-compatible (Groq), avec gestion des quotas (429) |
| `src/eih_rag/cli.py` | Interface en ligne de commande |
| `eval/` | Jeux de test, banc d'expériences et résultats |

## Installation

Python **3.12** est recommandé. Avec Python 3.14, torch n'est pas disponible et chromadb peut être bloqué par la stratégie de contrôle des applications de Windows. Node.js 20+ est requis pour le frontend.

```powershell
uv venv .venv --python 3.12              # ou : py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
Copy-Item .env.example .env              # puis renseigner la clé Groq
```

### Clé LLM (Groq, gratuite)

Créez une clé sur <https://console.groq.com/keys>, puis renseignez-la dans `.env`, qui n'est jamais versionné :

```ini
RAG_LLM_PROVIDER=openai_compatible
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_MODEL=openai/gpt-oss-120b
OPENAI_API_KEY=gsk_...
```

Pour une alternative locale sans clé : `RAG_LLM_PROVIDER=ollama`, `OLLAMA_MODEL=qwen2.5:3b`, puis `ollama pull qwen2.5:3b`. Elle est plus lente et moins précise sur les questions multi-documents.

Au premier lancement, le modèle d'embeddings `intfloat/multilingual-e5-base` (environ 1 Go) est téléchargé depuis Hugging Face. Les documents ne sont jamais envoyés à un fournisseur d'embeddings ; seuls les extraits retrouvés sont transmis au LLM.

## Utilisation

### Ligne de commande

```powershell
$env:PYTHONPATH = "src"
python -m eih_rag.cli ingest                         # indexe les PDF officiels et téléversés (structural 1200/200)
python -m eih_rag.cli ask "Combien de jours avant la soutenance faut-il déposer le rapport de PFE ?"
python -m eih_rag.cli chat                           # session interactive
python -m eih_rag.cli search "convention de stage" -k 8   # recherche seule, sans LLM
```

Chaque réponse est suivie de ses sources numérotées (fichier, page, section, score de pertinence).

### API et interface web

```powershell
python -m uvicorn eih_rag.main:app --app-dir src --host 127.0.0.1 --port 8000
# dans un second terminal
Set-Location frontend; npm install; npm run dev     # http://localhost:5173
```

| Route | Rôle |
| --- | --- |
| `GET /api/health` | État du service et nombre de fragments ; `503` si Chroma est indisponible |
| `POST /api/ingest` | Reconstruit l'index à partir des deux dossiers (par défaut `structural`, 1200, 200) |
| `GET /api/documents` | Tableau des documents indexés avec les champs existants et `origin` (`official` ou `upload`) |
| `POST /api/documents/upload` | Reçoit le champ multipart `file`, reconstruit l'index et renvoie le document indexé (`201`) |
| `DELETE /api/documents/{filename}` | Supprime un PDF téléversé et reconstruit l'index (`204`, corps vide) |
| `POST /api/search` | Recherche seule avec scores et filtre `filters.type` |
| `POST /api/ask` | Recherche, génération citée et contrôle des citations ; `502` si le LLM est indisponible |

La documentation interactive est disponible sur <http://localhost:8000/docs>.

### Gestion des PDF

Dans l'onglet **Documents**, sélectionnez un PDF, puis cliquez sur **Téléverser le PDF**. La bibliothèque affiche l'origine et les métadonnées de chaque document. Le bouton de suppression apparaît sur les PDF téléversés et demande une confirmation.

Le nom de l'application et les couleurs des champs, boutons et alertes se règlent dans `frontend/vite.config.ts`.

Envoyez le fichier avec `curl -F "file=@guide.pdf" http://localhost:8000/api/documents/upload`.
Pour la suppression, encodez le nom du fichier comme un segment d'URL, par exemple
`curl -X DELETE http://localhost:8000/api/documents/guide.pdf`.

L'API accepte les PDF contenant du texte extractible et impose une limite de 20 Mio par fichier.
Un nom invalide renvoie `400`, un PDF officiel à supprimer `403`, un fichier introuvable `404`,
un nom déjà utilisé `409` (casse ignorée), un fichier trop volumineux `413` et un fichier non pris
en charge, illisible ou sans texte indexable `415`. Les PDF scannés sans couche texte
nécessitent une OCR préalable. Les erreurs contiennent le champ FastAPI `detail`.

Les modifications réutilisent le dernier découpage enregistré, ou les valeurs par défaut à la
première indexation. Le manifeste et la collection Chroma active basculent ensemble après
construction de la nouvelle collection. En cas d'échec d'indexation, l'opération renvoie `503`
et l'index actif reste disponible. Les documents téléversés complètent les sources officielles
dans les réponses de l'assistant.

Lancez l'API avec un seul processus Uvicorn pour la base Chroma locale. Les routes de gestion
agissent sur un corpus partagé et sont accessibles aux clients de cette API locale.

### Configuration (`.env`, préfixe `RAG_`)

| Variable | Défaut | Effet |
| --- | --- | --- |
| `RAG_UPLOADS_DIR` | `data/uploads/` | Dossier des PDF téléversés, distinct de `corpus/` |
| `RAG_MAX_UPLOAD_BYTES` | `20971520` | Taille maximale d'un PDF téléversé, en octets |
| `RAG_EMBEDDING_MODEL` | `intfloat/multilingual-e5-base` | Modèle d'embeddings |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | `1200` / `200` | Découpage utilisé par la CLI |
| `RAG_RETRIEVAL_MODE` | `hybrid` | `dense`, `bm25` ou `hybrid` |
| `RAG_HYBRID_DENSE_WEIGHT` | `0.7` | Poids du dense dans la fusion RRF (BM25 = 1 − poids) |
| `RAG_DEFAULT_TOP_K` | `6` | Nombre de fragments transmis au LLM |
| `RAG_RERANKER_ENABLED` | `false` | Active le cross-encoder (`RAG_RERANKER_MODEL`) |
| `RAG_QUERY_EXPANSION` | `false` | Active la reformulation de la question par le LLM |
| `RAG_SCORE_THRESHOLD` | `0.28` | Seuil de pertinence en dessous duquel le LLM n'est pas appelé |

## Évaluation

Il y a deux jeux de questions :

- `eval/questions.jsonl` : les 20 questions de la consigne (8 simples, 5 synthèses, 2 versions, 5 hors corpus), utilisées par `eval/run_eval.py` via l'API.
- `eval/testset.jsonl` : le jeu étendu de **81 questions** en 9 catégories (factuelles, chiffres et tableaux, oui/non, multi-parties, multi-documents, versions, synthèses, questions vagues, hors corpus). Il est généré par `eval/build_testset.py`. Chaque question contient la réponse attendue, les documents sources et des **preuves** recopiées mot pour mot du corpus. Le script vérifie automatiquement que chaque preuve existe dans le PDF attendu.

```powershell
python eval/build_testset.py                         # (re)génère et vérifie le jeu de test
python eval/experiments.py retrieval --grid chunking # grilles : baseline, chunking, mode, embedding, topk, rerank
python eval/experiments.py retrieval --name essai --set chunk_size=800 overlap=150 mode=bm25
python eval/experiments.py generate --name final --set embedding=intfloat/multilingual-e5-base chunk_size=1200 overlap=200 dense_weight=0.7 top_k=6
```

Les métriques calculées sont les suivantes :

- **Recherche** : Recall@k et FullRecall@k (toutes les preuves présentes dans le top-k) au niveau du passage, et MRR.
- **Génération** : exactitude notée de 0 à 2 par un LLM juge distinct (`qwen/qwen3.8-27b`) par rapport à la réponse de référence, fidélité au contexte, refus corrects, refus à tort et citations invalides.

Les résultats sont ajoutés à `eval/results/*.csv` ; le détail par question est enregistré dans `eval/results/generation_<nom>.json`. Les appels LLM sont mis en cache (`eval/results/llm_cache.json`), ce qui permet de relancer une évaluation sans consommer de quota.

## Tests

```powershell
python -m pytest -q                  # 30 tests : extraction, découpage, recherche hybride, API, évaluation
npm --prefix frontend run build
```
