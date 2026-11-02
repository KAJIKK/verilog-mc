"""Routing-cache isolation and generated test-runtime boundary regressions."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import route_cache
from tests.live_test_runtime import install_chunk_lease,install_case_dispatch


class RuntimePerformanceTests(unittest.TestCase):
    def test_cache_hit_is_exact_and_does_not_share_mutable_state(self):
        nets = [[(0,0,True),(0,0,False)]]
        with tempfile.TemporaryDirectory() as directory:
            a = route_cache.cached_route(nets,1,directory=directory)
            with patch.object(route_cache,'route',side_effect=AssertionError('Unexpected search')):
                b = route_cache.cached_route(nets,1,directory=directory)
                self.assertEqual(a.blocks,b.blocks)
                self.assertEqual(list(a.blocks),list(b.blocks))
                self.assertEqual(a.net_wires,b.net_wires)
                self.assertEqual([list(net) for net in a.net_wires],[list(net) for net in b.net_wires])
                self.assertEqual(a.net_pins,b.net_pins)
                self.assertEqual(a.required_air,b.required_air)
                b.blocks.clear()
                c = route_cache.cached_route(nets,1,directory=directory)
                self.assertEqual(c.blocks,a.blocks)
            self.assertTrue(c.route_stats['cached'])

    def test_changed_geometry_or_headroom_misses_cache(self):
        nets = [[(0,0,True),(0,0,False)]]
        with tempfile.TemporaryDirectory() as directory:
            route_cache.cached_route(nets,1,directory=directory)
            changed = route_cache.cached_route(nets,3,directory=directory)
            self.assertFalse(changed.route_stats['cached'])
            changed = route_cache.cached_route(nets,1,[(0,0,True)],directory)
            self.assertFalse(changed.route_stats['cached'])
            self.assertIn((0,1,0),changed.required_air)

    def test_corrupt_cache_recomputes_instead_of_using_wrong_blocks(self):
        nets = [[(0,0,True),(0,0,False)]]
        with tempfile.TemporaryDirectory() as directory:
            a = route_cache.cached_route(nets,1,directory=directory)
            path = next(Path(directory).glob('*.json.gz'))
            with gzip.open(path,'rt') as handle:
                body = json.load(handle)
            body['body']['blocks'] = []
            with gzip.open(path,'wt') as handle:
                json.dump(body,handle)
            b = route_cache.cached_route(nets,1,directory=directory)
            self.assertFalse(b.route_stats['cached'])
            self.assertEqual(a.blocks,b.blocks)

    def test_chunk_leases_cover_negative_boundaries_and_preserve_preexisting(self):
        functions = {}
        count = install_chunk_lease(lambda name,commands:functions.update({name:commands}),
                                    'example',(-17,-1,-1),(0,8,16))
        self.assertEqual(count,9)
        self.assertTrue(all('unless data storage example:leases owned.' in line for line in functions['load']))
        lease = functions['lease_0']
        self.assertIn('forceload query -32 -16',lease[1])
        self.assertTrue(all('{probe:0b}' in line for line in lease[2:]))
        self.assertTrue(all('if data storage example:leases owned.' in line for line in functions['unload'][:-1]))
        self.assertEqual(functions['unload'][-1],'data remove storage example:leases owned')

    def test_dispatch_is_constant_size_and_handles_last_case(self):
        functions = {}
        write = lambda name,commands:functions.update({name:commands})
        commands = install_case_dispatch(write,'example',1328)
        self.assertEqual(len(commands),3)
        self.assertIn('matches 1..1327',commands[1])
        self.assertIn('matches 1328',commands[2])
        self.assertEqual(functions['dispatch'],['$function example:apply_$(case)'])
        commands = install_case_dispatch(write,'example',1)
        self.assertEqual(len(commands),2)
        self.assertFalse(any('1..0' in line for line in commands))


if __name__ == '__main__':
    unittest.main()
