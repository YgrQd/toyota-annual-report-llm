import re

TOPICS = {
    'financial': ['financial', 'revenue', 'profit', 'results', '財務', '経理', '業績', '経営成績', '経営指標'],
    'strategy': ['strategy', 'strategic', 'outlook', 'management', '経営方針', '戦略', '対処すべき', '経営者'],
    'business': ['business', 'operations', 'growth', '事業の内容', '事業等', '事業概況'],
    'risk': ['risk', 'リスク'],
    'technology': ['research', 'development', 'technology', 'hybrid', 'electric', '研究開発', '技術', 'ハイブリッド', '電動'],
}

def items(payload, keys=('items', 'sections', 'stocks', 'data')):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError('Unsupported list response shape; inspect API schema without exposing credentials.')

def section_titles(payload):
    result = []
    for item in items(payload):
        title = item if isinstance(item, str) else next((item[k] for k in ('title', 'heading', 'name') if isinstance(item.get(k), str)), None)
        if not title:
            raise ValueError('Section metadata lacks a recognized title field.')
        if title not in result:
            result.append(title)
    return result

def select(titles, limit=8):
    scored = []
    for index, title in enumerate(titles):
        groups = [k for k, words in TOPICS.items() if any(w in title.lower() for w in words)]
        if groups:
            scored.append((title, groups, index))
    chosen, covered = [], set()
    # Greedy topic coverage, followed by original section order.
    while scored and len(chosen) < limit:
        best = max(scored, key=lambda x: (len(set(x[1]) - covered), len(x[1]), -x[2]))
        scored.remove(best)
        chosen.append(best)
        covered.update(best[1])
    return [(title, groups) for title, groups, _ in sorted(chosen, key=lambda x: x[2])]

def extract_content(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('content'), str):
        raise ValueError('Section response must contain a content string.')
    return payload['content']

def validate_analysis(text, ids):
    cited = set(re.findall(r'\[(S\d+)\]', text))
    unknown = cited - set(ids)
    if unknown:
        raise ValueError('LLM produced unknown section citations.')
    if not cited:
        raise ValueError('LLM response has no section citations.')

def local_subsections(content):
    """Split broad server chapter at Markdown headings without cutting tables."""
    parts = re.split(r'(?m)(?=^### )', content)
    result = {}
    for part in parts:
        heading = re.match(r'### (.+)', part)
        if heading:
            result[heading.group(1).strip()] = part
    return result
