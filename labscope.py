#!/usr/bin/env python3
"""LabScope CLI.

  python labscope.py init-db                      create tables
  python labscope.py seed                         load data/seed_models.json into DB
  python labscope.py literature [--models a,b] [--limit N] [--no-llm]
  python labscope.py datasheets [--models a,b]
  python labscope.py market [--models a,b]
  python labscope.py market-import file.csv
  python labscope.py tool <name> '<json-args>'    run one agent tool directly
  python labscope.py chat                         SDK chat agent (needs API creds)
  python labscope.py stats                        DB summary
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db as dbm  # noqa: E402


def _models_arg(s: str | None) -> list[str] | None:
    return [m.strip() for m in s.split(",")] if s else None


def cmd_stats(_args) -> None:
    conn = dbm.connect()
    for label, q in [
        ("instruments", "SELECT COUNT(*) c FROM instruments"),
        ("papers", "SELECT COUNT(*) c FROM papers"),
        ("links (all)", "SELECT COUNT(*) c FROM instrument_paper"),
        ("links (conf>=0.7)", "SELECT COUNT(*) c FROM instrument_paper WHERE confidence >= 0.7"),
        ("links with evidence", "SELECT COUNT(*) c FROM instrument_paper WHERE evidence_snippet IS NOT NULL"),
        ("listings", "SELECT COUNT(*) c FROM listings"),
    ]:
        print(f"{label:22s} {conn.execute(q).fetchone()['c']}")
    print("\ntop models by confirmed links:")
    for r in conn.execute(
        """SELECT i.manufacturer, i.model, COUNT(*) n
           FROM instrument_paper ip JOIN instruments i ON i.id = ip.instrument_id
           WHERE ip.confidence >= 0.7 GROUP BY ip.instrument_id ORDER BY n DESC LIMIT 12"""
    ):
        print(f"  {r['n']:4d}  {r['manufacturer']} {r['model']}")
    conn.close()


def main() -> None:
    p = argparse.ArgumentParser(prog="labscope")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db")
    sub.add_parser("seed")
    sp = sub.add_parser("literature")
    sp.add_argument("--models")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--no-llm", action="store_true", help="skip LLM disambiguation (marks links 0.55)")
    sp = sub.add_parser("datasheets")
    sp.add_argument("--models")
    sp = sub.add_parser("market")
    sp.add_argument("--models")
    sp = sub.add_parser("market-import")
    sp.add_argument("csv_path")
    sp = sub.add_parser("tool")
    sp.add_argument("name")
    sp.add_argument("json_args", nargs="?", default="{}")
    sub.add_parser("chat")
    sub.add_parser("stats")

    args = p.parse_args()

    if args.cmd == "init-db":
        dbm.init_db()
        print("db initialised")
    elif args.cmd == "seed":
        from pipelines import seed
        seed.run()
    elif args.cmd == "literature":
        from pipelines import literature
        stats = literature.run(_models_arg(args.models), args.limit, skip_llm=args.no_llm)
        print("\nsummary:", json.dumps(stats, ensure_ascii=False))
    elif args.cmd == "datasheets":
        from pipelines import datasheets
        print(json.dumps(datasheets.run(_models_arg(args.models)), ensure_ascii=False))
    elif args.cmd == "market":
        from pipelines import marketplace
        print(json.dumps(marketplace.run(_models_arg(args.models)), ensure_ascii=False))
    elif args.cmd == "market-import":
        from pipelines import marketplace
        marketplace.import_csv(args.csv_path)
    elif args.cmd == "tool":
        from agent.tools import TOOL_FUNCS
        fn = TOOL_FUNCS.get(args.name)
        if not fn:
            sys.exit(f"unknown tool {args.name}; available: {', '.join(TOOL_FUNCS)}")
        print(json.dumps(fn(**json.loads(args.json_args)), indent=2, ensure_ascii=False, default=str))
    elif args.cmd == "chat":
        from agent.chat import main as chat_main
        chat_main()
    elif args.cmd == "stats":
        cmd_stats(args)


if __name__ == "__main__":
    main()
