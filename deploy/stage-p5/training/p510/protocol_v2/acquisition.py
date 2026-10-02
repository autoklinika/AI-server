"""Offline quarantine checks and review queue; never a certification/assignment API.

Only supplied metadata is inspected. URLs and payload paths are never dereferenced.
Canonical document identity and semantic equivalence still require human review.
"""
import re
from collections import Counter
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

LINEAGES = {'v3', 'v4_r3', 'p57_step008', 'p58_step008', 'p59_step008'}
PUBLISHERS = {
    'Texas Instruments': {'www.ti.com', 'e2e.ti.com'},
    'NXP': {'www.nxp.com'}, 'Microchip': {'ww1.microchip.com', 'www.microchip.com'},
    'Infineon': {'www.infineon.com'}, 'onsemi': {'www.onsemi.com'},
    'Renesas': {'www.renesas.com'}, 'STMicroelectronics': {'www.st.com'},
    'Analog Devices': {'www.analog.com'}, 'Analog Devices/Maxim': {'www.analog.com'},
    'Murata': {'www.murata.com', 'article.murata.com'},
    'Vishay': {'www.vishay.com'}, 'Bourns': {'www.bourns.com'},
    'Littelfuse': {'www.littelfuse.com'},
}
SOURCE_BINDING_FIELDS = ('source_id', 'source_family_id', 'vendor', 'title', 'url',
                         'locator', 'accessed_date', 'license', 'retrieval_status',
                         'retrieved_sha256', 'record_sha256')


def require_text(record, fields):
    for field in fields:
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise ValueError('missing acquisition text: ' + field)


def unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError('duplicate acquisition ' + label)


def canonical_url(url):
    """Remove only tracking, not document-selecting queries (e.g. Vishay doc IDs)."""
    u = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in {'ts', 'tracking'}]
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.lower(),
                       urlencode(sorted(query)), ''))


def review_groups(rows):
    """Conservative transitive holds, NOT counts of independent observations."""
    by_id = {r['family_id']: r for r in rows}
    parent = {key: key for key in by_id}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def join(a, b):
        parent[root(a)] = root(b)

    owners = {}
    for r in rows:
        fid = r['family_id']
        keys = [('source', s) for s in r.get('source_family_ids', [r['source_family_id']])]
        keys.append(('causal', r['causal_cluster_id']))
        for key in keys:
            if key in owners:
                join(fid, owners[key])
            owners[key] = fid
        for other in r.get('possible_overlap_family_ids', []):
            if other not in by_id or other == fid:
                raise ValueError('invalid overlap family reference')
            join(fid, other)
    groups = {}
    for fid in sorted(by_id):
        groups.setdefault(root(fid), []).append(fid)
    for group in groups.values():
        if len({by_id[fid]['role'] for fid in group}) != 1:
            raise ValueError('cross-role source/causal/possible-overlap review hold')
    return sorted(groups.values())


def inspect(sdoc, cdoc, legacy_sources, legacy_rows, domains, record_hash, split_guard, normalized):
    if sdoc.get('schema_version') != 1 or sdoc.get('status') != 'QUARANTINE':
        raise ValueError('invalid acquisition source envelope')
    fixed = dict(schema_version=1, status='QUARANTINE', certification='NOT_CERTIFIED',
                 acceptance_authorized=False, training_authorized=False, parent=None,
                 sealed_final='UNOPENED', independent_review=None, custodian_attestation=None,
                 assigned_roles=[])
    if any(k not in cdoc or cdoc[k] != v or type(cdoc[k]) is not type(v) for k, v in fixed.items()):
        raise ValueError('acquisition quarantine promotion')
    sources, candidates = sdoc.get('sources'), cdoc.get('candidates')
    if not isinstance(sources, list) or not sources or not isinstance(candidates, list) or not candidates:
        raise ValueError('empty/malformed acquisition corpus')
    for s in sources:
        require_text(s, ('source_id', 'source_family_id', 'vendor', 'title', 'url', 'locator',
                         'accessed_date', 'license', 'claim', 'inspection_scope', 'review'))
        if s.get('record_sha256') != record_hash(s):
            raise ValueError('acquisition source hash mismatch')
        if (s.get('status') != 'QUARANTINE' or s.get('certification') != 'NOT_CERTIFIED'
                or s.get('kind') != 'primary_vendor_documentation'
                or s.get('review') != 'AUTOMATED_SOURCE_INSPECTION_NOT_INDEPENDENT'
                or s.get('snapshot_retained_in_repository') is not False
                or s.get('archive_status') != 'NOT_ARCHIVED_FOR_INDEPENDENT_REVIEW'):
            raise ValueError('unsupported acquisition provenance/review claim')
        u = urlsplit(s['url'])
        if u.scheme != 'https' or u.hostname not in PUBLISHERS.get(s['vendor'], set()) or u.username:
            raise ValueError('source must bind an allowed primary publisher')
        accessed = date.fromisoformat(s['accessed_date'])
        attempted = datetime.fromisoformat(s['retrieval_attempted_at_utc'])
        if attempted.tzinfo is None or attempted.date() != accessed:
            raise ValueError('source retrieval date mismatch')
        if s.get('retrieval_status') == 'FETCHED_RESPONSE_HASHED':
            if (not isinstance(s.get('retrieved_sha256'), str)
                    or not re.fullmatch('[0-9a-f]{64}', s['retrieved_sha256'])
                    or type(s.get('retrieved_bytes')) is not int or s['retrieved_bytes'] <= 0
                    or type(s.get('http_status')) is not int or not 200 <= s['http_status'] < 300
                    or s.get('response_format') not in {'PDF_TEXT_EXTRACTED', 'HTML_OR_OTHER_REQUIRES_CONTENT_CHECK'}
                    or 'error' in s):
                raise ValueError('invalid fetched source hash/status')
            require_text(s, ('retrieved_url', 'content_type'))
            fetched = urlsplit(s['retrieved_url'])
            if fetched.scheme != 'https' or fetched.hostname not in PUBLISHERS[s['vendor']]:
                raise ValueError('retrieved source publisher mismatch')
        elif s.get('retrieval_status') == 'WEB_EXCERPT_RAW_FETCH_FAILED':
            if s.get('retrieved_sha256', 'missing') is not None or 'retrieved_bytes' in s:
                raise ValueError('failed source fetch cannot have a payload hash/size')
            require_text(s, ('error',))
        else:
            raise ValueError('unsupported source retrieval status')
    all_sources = legacy_sources + sources
    for field in ('source_id', 'source_family_id'):
        unique([s[field] for s in all_sources], field)
    unique([canonical_url(s['url']) for s in all_sources], 'canonical URL')
    unique([normalized(s['title']) for s in all_sources], 'document title')
    source_map = {s['source_id']: s for s in sources}
    unique([r['causal_cluster_id'] for r in candidates], 'causal cluster')
    unique([normalized(r['topology'] + ' ' + r['mechanism']) for r in legacy_rows + candidates],
           'numeric-normalized causal fingerprint')
    used_sources = set()
    for r in candidates:
        require_text(r, ('family_id', 'source_family_id', 'causal_cluster_id', 'automotive_context',
                         'topology', 'mechanism', 'competing_mechanism', 'intervention', 'prediction',
                         'source_support_scope', 'review_notes'))
        if r.get('record_sha256') != record_hash(r):
            raise ValueError('acquisition candidate hash mismatch')
        if (r.get('domain') not in domains or r.get('role') != 'quarantine'
                or r.get('status') != 'QUARANTINE' or r.get('certification') != 'NOT_CERTIFIED'
                or r.get('authorship') != 'CODEX_AUTHORED_NOT_INDEPENDENT_REVIEW'
                or r.get('semantic_independence') != 'UNKNOWN_REQUIRES_REVIEW'
                or r.get('eligible_roles') != []):
            raise ValueError('candidate quarantine promotion')
        for key in ('correctness_review', 'independence_review', 'custodian_attestation'):
            if key not in r or r[key] is not None:
                raise ValueError('automatic review cannot promote acquisition candidate')
        if (not isinstance(r.get('source_ids'), list) or not r['source_ids']
                or any(s not in source_map for s in r['source_ids'])):
            raise ValueError('missing acquisition source binding')
        unique(r['source_ids'], 'candidate source binding')
        used_sources.update(r['source_ids'])
        bound = [{k: source_map[s][k] for k in SOURCE_BINDING_FIELDS} for s in r['source_ids']]
        if r.get('primary_sources') != bound or r['source_family_id'] != bound[0]['source_family_id']:
            raise ValueError('candidate source provenance binding mismatch')
        if (r.get('discriminating_measurement_or_intervention') != r['intervention']
                or r.get('conditional_prediction') != r['prediction']):
            raise ValueError('candidate causal field disagreement')
        potential = r.get('sufficiency_potential', {})
        require_text(potential, ('sufficient_if', 'insufficient_if'))
        if (potential.get('classification') != 'BOTH_POTENTIAL_NOT_LABELLED'
                or 'observed_data' not in potential or potential['observed_data'] is not None):
            raise ValueError('unsupported sufficiency/observation claim')
        safety = r.get('safety_constraints')
        if not isinstance(safety, list) or not safety or any(not isinstance(s, str) or not s.strip() for s in safety):
            raise ValueError('missing safety constraints')
        exposure = r.get('exposure', {})
        if set(exposure) != LINEAGES or any(v != dict(status='UNKNOWN', certification='NOT_CERTIFIED',
                                                      attestation=None) for v in exposure.values()):
            raise ValueError('unsupported lineage exposure claim')
        overlaps = r.get('possible_overlap_family_ids')
        if not isinstance(overlaps, list) or any(not isinstance(x, str) for x in overlaps):
            raise ValueError('missing overlap review disposition')
        unique(overlaps, 'overlap reference')
    if used_sources != set(source_map):
        raise ValueError('unbound acquisition source; distinguish leads from candidate evidence')
    # Expand every source binding, including secondary sources, before collision checking.
    enriched = []
    registry = {s['source_id']: s['source_family_id'] for s in all_sources}
    for r in legacy_rows + candidates:
        enriched.append(dict(r, source_family_ids=[registry[s] for s in r['source_ids']]))
    split_guard(enriched)
    groups = review_groups(enriched)
    return dict(status='QUARANTINE', certification='NOT_CERTIFIED', certified_scenarios=0,
                candidate_count=len(candidates), provisional_causal_cluster_count=len(candidates),
                new_primary_source_families=len(sources),
                domains=dict(sorted(Counter(r['domain'] for r in candidates).items())),
                vendors=dict(sorted(Counter(s['vendor'] for s in sources).items())),
                retrieval=dict(sorted(Counter(s['retrieval_status'] for s in sources).items())),
                candidates_with_possible_overlap=sum(bool(r['possible_overlap_family_ids']) for r in candidates),
                review_queue=dict(status='REQUIRES_INDEPENDENT_REVIEW_AND_CUSTODIAN_ATTESTATION',
                                  assigned_roles=[], eligible_candidates=0,
                                  conservative_groups_including_legacy=groups,
                                  group_count_is_not_independence_count=True,
                                  required_pools=dict(parent_selection=240, selection_dev=240, prefinal=400)))
