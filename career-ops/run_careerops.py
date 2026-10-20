#!/usr/bin/env python3
"""CLI Entrypoint for Career-Ops (JD Scraping, Scoring, and Application Generation)."""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.career_ops.pipeline_manager import PipelineManager


def main():
    parser = argparse.ArgumentParser(
        description="Career-Ops: AI-Assisted Job Scraping, Match Scoring & Tailored Application Generator"
    )
    parser.add_argument(
        "action",
        choices=["status", "evaluate", "generate", "all"],
        default="status",
        nargs="?",
        help="Action to execute: status | evaluate | generate | all",
    )
    parser.add_argument(
        "--pipeline",
        type=str,
        default="career-ops/data/pipeline.md",
        help="Path to pipeline.md file",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default="career-ops/config/profile.yaml",
        help="Path to candidate profile.yaml",
    )

    args = parser.parse_args()
    manager = PipelineManager(pipeline_path=args.pipeline, profile_path=args.profile)

    if args.action == "status":
        entries = manager.load_entries()
        print("\n" + "=" * 80)
        print("📊 Career-Ops Pipeline Status")
        print("=" * 80)
        if not entries:
            print("No jobs currently in pipeline. Tap [📥 Queue Career-Ops] in Telegram to add jobs!")
        else:
            for idx, e in enumerate(entries, start=1):
                print(f"[{idx}] {e.company} - {e.role}")
                print(f"    Location: {e.location} | Source: {e.source}")
                print(f"    Status:   {e.status} | Score: {e.match_score}")
                if e.notes:
                    print(f"    Notes:    {e.notes}")
                print("-" * 80)

    elif args.action == "evaluate":
        print("\n🔍 Evaluating queued positions against profile...")
        results = manager.evaluate_all()
        if not results:
            print("No queued positions pending evaluation.")
        else:
            for entry, eval_res in results:
                print(f"✅ {entry.company} - {entry.role}: {eval_res.overall_score}% ({eval_res.classification})")
                print(f"   Matches: {', '.join(eval_res.matched_skills) if eval_res.matched_skills else 'None'}")
                print(f"   Missing: {', '.join(eval_res.missing_skills) if eval_res.missing_skills else 'None'}")

    elif args.action == "generate":
        print("\n✍️ Generating tailored German applications (Anschreiben & Lebenslauf)...")
        paths = manager.generate_all_applications()
        if not paths:
            print("No positions ready for application generation. Run 'evaluate' first or check pipeline.")
        else:
            for p in paths:
                print(f"🎉 Generated application in: {p}")
                print(f"   📄 Cover Letter (HTML): {p / 'anschreiben.html'}")
                print(f"   📄 Resume (HTML):       {p / 'lebenslauf.html'}")

    elif args.action == "all":
        print("\n🚀 Running End-to-End Pipeline: Evaluate -> Generate...")
        manager.evaluate_all()
        paths = manager.generate_all_applications()
        print(f"\n✨ Finished! Generated {len(paths)} tailored application package(s).")


if __name__ == "__main__":
    main()
