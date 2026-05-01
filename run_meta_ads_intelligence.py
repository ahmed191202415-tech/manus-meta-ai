from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.analytics.analysis_pipeline import analyze_file


def main() -> None:
    parser = argparse.ArgumentParser(description='Run Meta Ads Intelligence on a local CSV/XLSX/JSON export.')
    parser.add_argument('--input', required=True, help='Path to Meta Ads export file')
    parser.add_argument('--compare', default=None, help='Optional previous-period export')
    parser.add_argument('--campaign-type', default='unknown', help='sales/messages/leads/awareness/video/traffic/app')
    parser.add_argument('--question', default='', help='User question')
    parser.add_argument('--level', default='campaign', help='account/campaign/adset/ad')
    parser.add_argument('--db', default='exports/meta_ads_intelligence.sqlite', help='SQLite output path')
    parser.add_argument('--report-out', default='', help='Optional markdown report output path')
    args = parser.parse_args()

    result = analyze_file(
        args.input,
        compare_path=args.compare,
        campaign_type=args.campaign_type,
        question=args.question,
        level=args.level,
        db_path=args.db,
    )
    if args.report_out:
        out = Path(args.report_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result['report_markdown'], encoding='utf-8')
    print(json.dumps({
        'run_id': result['run_id'],
        'rows': result['rows'],
        'phase': result['phase'],
        'diagnostics_count': len(result.get('diagnostics', [])),
        'relationships_count': len(result.get('relationships', [])),
        'skipped_sections_count': len(result.get('skipped_sections', [])),
        'db_path': args.db,
        'report_out': args.report_out,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
