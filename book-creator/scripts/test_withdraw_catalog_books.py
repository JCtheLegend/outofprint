import unittest
from unittest.mock import patch

import withdraw_catalog_books as w


class WithdrawalGuards(unittest.TestCase):
    def test_existing_order_stops_before_any_mutation(self):
        plan = {'book_slugs': ['requested'], 'set_slugs': []}
        book = {'id': 'book-id', 'slug': 'requested'}
        with patch.object(w, 'selected', side_effect=[[book], []]), patch.object(w, 'api', return_value=[{'id': 'order-id'}]) as api:
            with self.assertRaisesRegex(ValueError, 'existing orders'):
                w.snapshot(plan, 'digest')
            self.assertEqual(api.call_count, 1)
            self.assertEqual(api.call_args.args[0], 'orders')
            self.assertEqual(len(api.call_args.args), 2)  # GET only

    def test_changed_catalog_stops_before_delete(self):
        saved = {'manifest_sha256': 'digest', 'books': [{'id': 'id', 'price_cents': 3000}], 'book_sets': []}
        changed = {'books': [{'id': 'id', 'price_cents': 3500}], 'book_sets': []}
        with patch.object(w, 'snapshot', return_value=changed), patch.object(w, 'api') as api:
            with self.assertRaisesRegex(ValueError, 'Catalog changed'):
                w.apply({}, 'digest', saved)
            api.assert_not_called()

    def test_failed_delete_restores_previously_removed_book(self):
        a, b = {'id': 'a', 'slug': 'first'}, {'id': 'b', 'slug': 'second'}
        saved = {'manifest_sha256': 'digest', 'books': [a, b], 'book_sets': []}
        calls = []
        def api(table, query='', method='GET', payload=None):
            calls.append((table, query, method, payload))
            if method == 'DELETE' and 'eq.b' in query:
                raise RuntimeError('simulated concurrent foreign-key protection')
            return []
        with patch.object(w, 'snapshot', return_value=saved), patch.object(w, 'api', side_effect=api), patch.object(w, 'selected', side_effect=[[], [b]]):
            with self.assertRaises(RuntimeError):
                w.apply({}, 'digest', saved)
        self.assertEqual(calls[-1], ('books', 'on_conflict=id', 'POST', [a]))


if __name__ == '__main__':
    unittest.main()
