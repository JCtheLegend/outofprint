"""Withdraw explicitly listed catalog entries, retaining files and a restore snapshot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request

BASE = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def api(table, query='', method='GET', payload=None):
    url = os.environ['SUPABASE_URL'].rstrip('/')
    if not url.startswith('https://'):
        raise ValueError('Expected the configured HTTPS Supabase service')
    headers = {'apikey': os.environ['SUPABASE_SERVICE_ROLE_KEY'],
               'Authorization': 'Bearer ' + os.environ['SUPABASE_SERVICE_ROLE_KEY'],
               'Content-Type': 'application/json', 'Prefer': 'return=representation,resolution=merge-duplicates'}
    request = urllib.request.Request(url + '/rest/v1/' + table + ('?' + query if query else ''),
        data=None if payload is None else json.dumps(payload).encode(), headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        return json.loads(raw) if raw else []


def selected(table, field, values):
    if not values:
        return []
    return api(table, urllib.parse.urlencode({'select': '*', field: 'in.(' + ','.join(values) + ')'}))


def ensure_no_orders(books, sets):
    for table_field, rows in [('book_id', books), ('set_id', sets)]:
        for row in rows:
            found = api('orders', urllib.parse.urlencode({'select': 'id', table_field: 'eq.' + row['id'], 'limit': '1'}))
            if found:
                raise ValueError('Withdrawal stopped: existing orders reference ' + row['slug'])


def manifest(path):
    path = Path(path).resolve()
    if not path.is_relative_to(BASE / 'withdrawals'):
        raise ValueError('Use a committed manifest inside book-creator/withdrawals')
    plan = read(path)
    for key in ('book_slugs', 'set_slugs'):
        values = plan[key]
        if len(values) != len(set(values)) or any(not re.fullmatch(r'[a-z0-9_-]+', v) for v in values):
            raise ValueError('Invalid or repeated catalog slug')
    if not 1 <= len(plan['book_slugs']) <= 50:
        raise ValueError('A withdrawal must name 1-50 exact books')
    for slug in plan['book_slugs']:
        metadata = read(BASE / 'books' / slug / 'metadata.json')
        if metadata.get('publication_status') != 'withdrawn':
            raise ValueError('Book is not marked withdrawn: ' + slug)
    return plan, hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(plan, digest):
    books = selected('books', 'slug', plan['book_slugs'])
    sets = selected('book_sets', 'slug', plan['set_slugs'])
    for group in sets:
        members = selected('books', 'set_id', [group['id']])
        if any(row['slug'] not in plan['book_slugs'] for row in members):
            raise ValueError('Set has books outside the requested withdrawal: ' + group['slug'])
    ensure_no_orders(books, sets)
    return {'manifest_sha256': digest, 'commit': os.environ.get('GITHUB_SHA'),
            'book_slugs': plan['book_slugs'], 'set_slugs': plan['set_slugs'],
            'books': books, 'book_sets': sets,
            'restore_instructions': 'Upsert book_sets first, then books, retaining all original IDs. Stored PDFs and cover objects have not been removed.'}


def apply(plan, digest, saved):
    if saved['manifest_sha256'] != digest:
        raise ValueError('Manifest changed since snapshot')
    current = snapshot(plan, digest)
    for key in ('books', 'book_sets'):
        if sorted(current[key], key=lambda r: r['id']) != sorted(saved[key], key=lambda r: r['id']):
            raise ValueError('Catalog changed since snapshot; take a fresh snapshot')
    try:
        for row in saved['books']:
            api('books', urllib.parse.urlencode({'id': 'eq.' + row['id'], 'slug': 'eq.' + row['slug']}), 'DELETE')
        for row in saved['book_sets']:
            if selected('books', 'set_id', [row['id']]):
                raise ValueError('Set gained a volume during withdrawal')
            api('book_sets', urllib.parse.urlencode({'id': 'eq.' + row['id'], 'slug': 'eq.' + row['slug']}), 'DELETE')
        if selected('books', 'slug', plan['book_slugs']) or selected('book_sets', 'slug', plan['set_slugs']):
            raise ValueError('Catalog still contains requested withdrawal entries')
    except Exception:
        # Restore the captured public catalog records if a partial withdrawal fails.
        for table, key in [('book_sets', 'book_sets'), ('books', 'books')]:
            missing = [r for r in saved[key] if not selected(table, 'id', [r['id']])]
            if missing:
                api(table, 'on_conflict=id', 'POST', missing)
        raise
    return {'status': 'withdrawn', 'removed_books': [r['slug'] for r in saved['books']],
            'removed_sets': [r['slug'] for r in saved['book_sets']],
            'remaining_requested_entries': 0, 'storage_files_preserved': True,
            'orders_modified': False, 'commit': os.environ.get('GITHUB_SHA')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['snapshot', 'apply'])
    parser.add_argument('manifest')
    parser.add_argument('--snapshot', default='withdrawal-snapshot.json')
    parser.add_argument('--result', default='withdrawal-result.json')
    args = parser.parse_args()
    plan, digest = manifest(args.manifest)
    if args.action == 'snapshot':
        saved = snapshot(plan, digest)
        write(args.snapshot, saved)
        print(json.dumps({'snapshot_books': len(saved['books']), 'snapshot_sets': len(saved['book_sets']), 'order_check': 'passed'}))
    else:
        result = apply(plan, digest, read(args.snapshot))
        write(args.result, result)
        print(json.dumps(result))


if __name__ == '__main__':
    main()
