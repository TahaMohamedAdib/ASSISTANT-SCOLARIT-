"""Interface en ligne de commande de l'Assistant Scolarite EIH.

    python -m eih_rag.cli ingest                 # (re)construit l'index Chroma
    python -m eih_rag.cli ask "Ma question ?"    # une question
    python -m eih_rag.cli chat                   # session interactive
    python -m eih_rag.cli search "requete" -k 8  # recherche seule (debogage)

A lancer depuis la racine du projet avec ``--app-dir`` inutile : utiliser
``set PYTHONPATH=backend/src`` (Windows) ou ``python -m`` depuis ``backend/src``.
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from .config import Settings  # noqa: E402
from .rag.llm import LLMUnavailable  # noqa: E402
from .rag.service import RagService  # noqa: E402
from .schemas import AskRequest, IngestRequest, SearchRequest  # noqa: E402


def _print_sources(sources) -> None:
    for index, source in enumerate(sources, start=1):
        where = source.section or "-"
        print(f"  [{index}] {source.file} p.{source.page} | {where} (score {source.score:.3f})")


def _ask(service: RagService, question: str, top_k: int) -> None:
    try:
        response = service.ask(AskRequest(question=question, top_k=top_k))
    except LLMUnavailable as error:
        print(f"LLM indisponible : {error}", file=sys.stderr)
        return
    print(f"\n{response.answer}\n")
    if response.found and response.sources:
        print("Sources :")
        _print_sources(response.sources)
    if response.invalid_citations:
        print(f"Attention : citations invalides {response.invalid_citations}")
    print(f"({response.latency_ms} ms)\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eih_rag", description="Assistant Scolarite EIH (RAG)")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="indexe les 7 PDF du corpus")
    ingest.add_argument("--strategy", default="structural", choices=("structural", "fixed"))
    ingest.add_argument("--chunk-size", type=int, default=None)
    ingest.add_argument("--overlap", type=int, default=None)
    ask = sub.add_parser("ask", help="pose une question")
    ask.add_argument("question")
    ask.add_argument("-k", "--top-k", type=int, default=None)
    chat = sub.add_parser("chat", help="session interactive")
    chat.add_argument("-k", "--top-k", type=int, default=None)
    search = sub.add_parser("search", help="recherche seule, sans LLM")
    search.add_argument("question")
    search.add_argument("-k", "--top-k", type=int, default=None)
    args = parser.parse_args(argv)

    settings = Settings()
    service = RagService(settings)
    top_k = getattr(args, "top_k", None) or settings.default_top_k

    if args.command == "ingest":
        result = service.ingest(
            IngestRequest(
                strategy=args.strategy,
                chunk_size=args.chunk_size or settings.chunk_size,
                overlap=args.overlap if args.overlap is not None else settings.chunk_overlap,
            )
        )
        print(f"{result.documents_indexed} documents, {result.chunks_indexed} fragments indexes ({result.strategy.strategy}:{result.strategy.chunk_size}:{result.strategy.overlap}).")
    elif args.command == "ask":
        _ask(service, args.question, top_k)
    elif args.command == "search":
        for index, hit in enumerate(service.search(SearchRequest(question=args.question, top_k=top_k)).fragments, start=1):
            print(f"[{index}] {hit.file} p.{hit.page} | {hit.section or '-'} (score {hit.score:.3f})\n    {hit.excerpt[:200]!r}")
    else:
        print("Assistant Scolarite EIH - posez vos questions (ligne vide ou 'q' pour quitter).")
        while True:
            try:
                question = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not question or question.lower() in {"q", "quit", "exit"}:
                break
            _ask(service, question, top_k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
