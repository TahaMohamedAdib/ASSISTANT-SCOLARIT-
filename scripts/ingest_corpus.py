"""Genere le JSON de fragments de la seance 1.

Exemple:
    python scripts/ingest_corpus.py --strategy structural --output data/chunks.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from eih_rag.chunking import create_chunks, validate_chunk_parameters
from eih_rag.extraction import extract_pdf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extrait et decoupe le corpus PDF EIH.")
    parser.add_argument("--corpus", type=Path, default=PROJECT_ROOT / "corpus", help="Dossier contenant les 7 PDF.")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "chunks.json", help="Fichier JSON produit.")
    parser.add_argument("--strategy", choices=("fixed", "structural"), default="structural")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--overlap", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_chunk_parameters(args.chunk_size, args.overlap)
    except ValueError as error:
        print(f"Erreur de parametres : {error}", file=sys.stderr)
        return 2

    corpus = args.corpus.resolve()
    pdf_files = sorted(corpus.glob("*.pdf"))
    if len(pdf_files) != 7:
        print(f"Erreur : 7 PDF attendus dans {corpus}, {len(pdf_files)} trouves.", file=sys.stderr)
        return 2

    documents = []
    serialized_chunks = []
    for pdf_path in pdf_files:
        metadata, pages = extract_pdf(pdf_path)
        chunks = create_chunks(pages, metadata, args.strategy, args.chunk_size, args.overlap)
        document = metadata.to_dict()
        document["chunk_count"] = len(chunks)
        documents.append(document)
        serialized_chunks.extend(chunk.to_dict() for chunk in chunks)
        print(f"{pdf_path.name}: {len(pages)} pages, {len(chunks)} fragments")

    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": {"name": args.strategy, "chunk_size": args.chunk_size, "overlap": args.overlap},
        "documents": documents,
        "chunks": serialized_chunks,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON cree : {output} ({len(serialized_chunks)} fragments)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
