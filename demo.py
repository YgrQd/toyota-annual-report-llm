"""Toyota annual report -> selected sections -> grounded LLM analysis."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
import tiktoken
from src.datasinking import DataSinkingClient, DataSinkingError
from src.retrieval import items, section_titles, select, extract_content, validate_analysis, local_subsections

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retrieve-only', action='store_true', help='Retrieve sections without calling OpenAI')
    parser.add_argument('--max-sections', type=int, default=8)
    parser.add_argument('--max-input-tokens', type=int, default=24000, help='Hard cap on complete prompt and evidence')
    parser.add_argument('--allow-broad-section', action='store_true', help='Explicitly allow downloading the broad enterprise chapter when the server catalog lacks topical sections; split locally')
    parser.add_argument('--self-check', action='store_true', help='Offline checks; no report or LLM results fabricated')
    args = parser.parse_args()
    if args.self_check:
        import unittest
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if args.max_sections < 1 or args.max_input_tokens < 1000:
        parser.error('Use positive section count and at least 1000 input tokens.')
    load_dotenv(ROOT / '.env')
    needed = ['DATASINK_API_KEY'] + ([] if args.retrieve_only else ['OPENAI_API_KEY'])
    missing = [key for key in needed if not os.getenv(key)]
    if missing:
        print('Missing ' + ', '.join(missing) + '. Copy .env.example to .env and fill these values.', file=sys.stderr)
        return 2
    client = DataSinkingClient(os.environ['DATASINK_API_KEY'])
    stocks = items(client.stocks())
    matches = [s for s in stocks if isinstance(s, dict) and (s.get('symbol') == '7203.T' or str(s.get('stock_code')) == '7203')]
    if not matches:
        raise ValueError('Toyota 7203.T was not found in JPX stock metadata.')
    reports = items(client.reports())
    if not reports:
        raise ValueError('No annual reports returned for Toyota.')
    report = reports[0]
    if report.get('symbol') != '7203.T' or report.get('doc_type') != 'annual' or not report.get('report_period'):
        raise ValueError('Report identity/type/period did not pass validation.')
    titles = section_titles(client.sections(report['id']))
    chosen = select(titles, args.max_sections)
    local_content = {}
    broad_title = None
    if not chosen and args.allow_broad_section:
        broad_title = next((t for t in titles if '企業情報' in t), None)
        if broad_title:
            local_content = local_subsections(extract_content(client.section(report['id'], broad_title)))
            chosen = select(list(local_content), args.max_sections)
    if not chosen:
        raise ValueError('No matching sections. Review the catalog and extend TOPICS; no full-report fallback.')
    prompt = (ROOT / 'prompts/financial_analysis.md').read_text(encoding='utf-8')
    model = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        raise ValueError('Unknown model tokenizer; choose a model supported by tiktoken.') from None
    identity = {k: report.get(k) for k in ('id', 'symbol', 'title', 'report_period', 'doc_type', 'announcement_time')}
    base = 'REPORT METADATA: ' + json.dumps(identity, ensure_ascii=False) + '\n'
    evidence, manifest, skipped = [], [], []
    # Conservative allowance for message framing; never cut a table/unit label.
    used = len(enc.encode(prompt + base)) + 256
    for title, topics in chosen:
        content = local_content[title] if local_content else extract_content(client.section(report['id'], title))
        if not content.strip():
            skipped.append({'title': title, 'reason': 'empty content'})
            continue
        sid = f'S{len(evidence)+1}'
        block = f'\n<report-section id="{sid}">\nTitle: {title}\n{content}\n</report-section>\n'
        tokens = len(enc.encode(block))
        if used + tokens > args.max_input_tokens:
            skipped.append({'title': title, 'reason': 'whole section exceeds remaining token budget', 'tokens': tokens})
            continue
        used += tokens
        evidence.append(block)
        manifest.append({'id': sid, 'title': title, 'topics': topics, 'tokens': tokens,
            'sha256': hashlib.sha256(content.encode()).hexdigest(),
            'source': f'https://api.datasink.ing/documents/{report["id"]}',
            'section_query': title})
    if not evidence:
        raise ValueError('No complete sections fit. Raise the token budget or select narrower sections; no full-report fallback.')
    out = ROOT / 'output'
    out.mkdir(exist_ok=True)
    record = {'report': identity, 'section_catalog': titles, 'selected_sections': manifest,
        'skipped_sections': skipped, 'estimated_input_tokens_with_margin': used,
        'model': model, 'full_report_fetched': False, 'retrieval_mode': 'broad_server_section_then_local_subsections' if local_content else 'server_sections', 'broad_server_section': broad_title, 'status': 'retrieved_only'}
    (out / 'retrieval_manifest.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'selected_sections.md').write_text(base + ''.join(evidence), encoding='utf-8')
    print(f'Retrieved {len(evidence)} complete sections for {report["report_period"]}; input estimate {used} tokens.')
    if args.retrieve_only:
        return 0
    try:
        response = OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=120, max_retries=2).chat.completions.create(
            model=model, temperature=0, max_completion_tokens=5000,
            messages=[{'role': 'system', 'content': prompt}, {'role': 'user', 'content': base + ''.join(evidence)}])
    except OpenAIError:
        raise RuntimeError('OpenAI request failed; credentials and server details suppressed. Retrieved evidence is saved.') from None
    analysis = response.choices[0].message.content
    if not analysis or response.choices[0].finish_reason != 'stop':
        raise ValueError('LLM returned empty or incomplete output; analysis was not published.')
    validate_analysis(analysis, [s['id'] for s in manifest])
    for heading in [line for line in prompt.splitlines() if line.startswith('## ')]:
        if heading not in analysis:
            raise ValueError('LLM omitted a required analysis heading.')
    sources = '\n'.join(f'- [{s["id"]}] {s["title"]} (document {report["id"]}, period {report["report_period"]})' for s in manifest)
    (out / 'analysis.md').write_text(f'# Toyota selected-section analysis\n\nReport period: {report["report_period"]}\n\n' + analysis + '\n\n## Source sections\n' + sources + '\n\nAI-generated; verify figures against original disclosures. Not investment advice.\n', encoding='utf-8')
    record['status'] = 'analysis_completed'
    record['usage'] = response.usage.model_dump() if response.usage else None
    (out / 'retrieval_manifest.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Saved output/analysis.md, selected_sections.md and retrieval_manifest.json.')
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (DataSinkingError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
