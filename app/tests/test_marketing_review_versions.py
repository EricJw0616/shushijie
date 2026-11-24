"""Historical unversioned adoption must not approve regenerated marketing material."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store
import marketing_state

class MarketingReviewVersionTests(unittest.TestCase):
    def test_legacy_adoption_cannot_approve_changed_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'B01'))
            path = os.path.join(tmp, 'B01', 'marketing.json')
            data = {'items': {'summary': {'value': {'text': '相同文案'}, 'evidence': [{'seg': 'B01-1', 'quote': '原证据'}]}}}
            def save():
                with open(path, 'w') as f: json.dump(data, f)
            save()
            with patch.object(store.E, 'OUT', tmp), patch.object(store, 'marketing_flags', return_value={}) as flags:
                before = marketing_state.raw_rows('B01')[0]
                flags.return_value = {before['id']: 'adopt'}
                data['items']['summary']['evidence'] = [{'seg': 'B01-2', 'quote': '新的证据'}]
                save()
                after = marketing_state.raw_rows('B01')[0]
                self.assertEqual(before['id'], after['id'])
                self.assertNotEqual(before['revision'], after['revision'])
                self.assertEqual(after['status'], 'review')
                self.assertEqual(marketing_state.raw_rows('B01', approved_only=True), [])
