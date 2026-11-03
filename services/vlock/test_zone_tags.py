"""Fixed per-zone SCADA tags: stable names, honest Unknown values and leftover cleanup."""
import tempfile
import time
import unittest
from pathlib import Path

from services.vlock import zone_tags
from services.vlock.store import Store

ZONE = dict(id='zone-1', tagKey='A-101', name='A-101', output='person_and_laptop', outputType='condition',
            target='person', firstRelation='overlaps area', ruleJoin='ALL (AND)', persistence=1,
            extraConditions=[dict(object='laptop', relation='entirely inside area')])


def observation(status='active', **changes):
    return dict(dict(asset_id='zone-1', source_id='vision', signal_id='person_and_laptop', status=status,
                     reason='Zone condition is active.', ttl_seconds=15,
                     details=dict(counts={'person': 1, 'laptop': 2}, scores={'person': .87, 'laptop': .6},
                                  check_seconds=5.9)), **changes)


class ZoneTagTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.now = [time.time()]
        self.store = Store(Path(self.directory.name) / 'bridge.sqlite3', clock=lambda: self.now[0])

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def zone(self):
        return self.store.zones()['zones'][0]

    def test_keys_are_readable_unique_and_valid(self):
        self.assertEqual(zone_tags.tag_key('A-101', []), 'A-101')
        self.assertEqual(zone_tags.tag_key('Glass cutter #2', []), 'Glass-cutter-2')
        self.assertEqual(zone_tags.tag_key('A-101', ['a-101']), 'A-101-2')
        self.assertEqual(zone_tags.tag_key('***', []), 'zone')
        for name in ['_x', 'Ünïcode zone', 'x' * 80]:
            self.assertTrue(zone_tags.KEY.fullmatch(zone_tags.tag_key(name, [])), name)

    def test_manifest_describes_the_rule(self):
        entry = zone_tags.manifest(ZONE)
        self.assertEqual(entry['Rule'], 'person overlaps the area AND laptop is entirely inside the area for 1 s')
        self.assertEqual((entry['Object1'], entry['Object2']), ('person', 'laptop'))

    def test_values_follow_the_observation_and_never_show_a_stale_clear(self):
        self.store.set_zones([zone_tags.manifest(ZONE)])
        self.assertEqual(self.zone()['State'], 'Unknown')
        self.assertIsNone(self.zone()['Active'])
        self.store.submit(observation())
        zone = self.zone()
        self.assertEqual((zone['State'], zone['Active'], zone['Quality']), ('Active', True, 'Good'))
        self.assertEqual((zone['Count1'], zone['Count2'], zone['Score1']), (1, 2, .87))
        self.assertEqual(zone['CheckSeconds'], 5.9)
        self.now[0] += 1
        self.store.submit(observation('clear'))
        self.assertEqual((self.zone()['State'], self.zone()['Active']), ('Clear', False))
        self.now[0] += 16
        zone = self.zone()
        self.assertEqual((zone['State'], zone['Quality']), ('Unknown', 'Stale'))
        self.assertIsNone(zone['Active'])
        self.assertIsNone(zone['Count1'])
        self.assertIn('No fresh result', zone['Reason'])

    def test_count_and_event_outputs(self):
        count = dict(ZONE, outputType='count')
        self.store.set_zones([zone_tags.manifest(count)])
        self.store.submit(observation('valid', kind='measurement', value={'person': 1, 'laptop': 2}))
        zone = self.zone()
        self.assertEqual(zone['State'], 'Valid')
        self.assertIsNone(zone['Active'])
        self.assertEqual(zone['Count2'], 2)
        self.store.retain({'zone-1': ('person_and_laptop', 'measurement')})
        event = dict(ZONE, outputType='event')
        self.store.set_zones([zone_tags.manifest(event)])
        self.now[0] += 1
        self.store.submit(observation('valid', kind='measurement', value={'state': 'Warning'}))
        self.assertEqual((self.zone()['State'], self.zone()['Active']), ('Active', True))

    def test_retain_removes_renamed_and_removed_outputs(self):
        self.store.submit(observation('clear', signal_id='zone_condition'))
        self.store.submit(observation('clear'))
        self.store.submit(observation('clear', asset_id='zone-gone'))
        removed = self.store.retain({'zone-1': ('person_and_laptop', 'condition')})
        self.assertEqual(sorted(removed), [('zone-1', 'zone_condition'), ('zone-gone', 'person_and_laptop')])
        asset = self.store.snapshot()['assets'][0]
        self.assertEqual(asset['observation_status'], 'clear', 'A renamed output no longer holds the zone at Unknown')
        self.assertEqual(len(self.store.snapshot()['assets']), 1)
        removed = self.store.retain({'zone-1': ('person_and_laptop', 'measurement')})
        self.assertEqual(removed, [('zone-1', 'person_and_laptop')], 'A kind change starts a fresh signal')
        self.assertEqual([e['event_type'] for e in self.store.events(limit=3)][-1], 'removed')

    def test_removed_zone_document_is_unknown(self):
        doc = zone_tags.removed('A-101')
        self.assertEqual((doc['TagKey'], doc['State'], doc['Active']), ('A-101', 'Unknown', None))
        self.assertIn('removed', doc['Reason'])

    def test_ignition_export_has_one_udt_and_an_instance_per_zone(self):
        export = zone_tags.ignition_export([zone_tags.manifest(ZONE)])
        types, folder = export['tags']
        udt = types['tags'][0]
        self.assertEqual((types['name'], udt['name'], udt['tagType']), ('_types_', 'vLockZone', 'UdtType'))
        self.assertEqual([tag['name'] for tag in udt['tags']], [tag for tag, *_ in zone_tags.TAGS])
        active = udt['tags'][0]
        self.assertEqual(active['opcItemPath']['binding'], 'nsu=urn:vlock:bridge:v1;s=Bridge/Zones/{ZoneKey}/Active')
        self.assertEqual(active['opcServer']['binding'], '{OpcServer}')
        instance = folder['tags'][1]
        self.assertEqual((instance['name'], instance['typeId'], instance['parameters']['ZoneKey']['value']),
                         ('A-101', 'vLockZone', 'A-101'))
        self.assertEqual(folder['tags'][0]['tags'][0]['opcItemPath'], 'nsu=urn:vlock:bridge:v1;s=Bridge/Online')


if __name__ == '__main__':
    unittest.main()
