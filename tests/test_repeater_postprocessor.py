"""Count optimality, real decay boundaries, and restoration safety regressions."""
import contextlib
import io
import itertools
import unittest

from redstone_geometry import FACING,signal_neighbors,signal_powers
from repeater_postprocessor import (build_graph,build_graph_baseline,is_eligible,
                                    _repeater_feedback)
from tests.repeater_stress import fixture,stress_fixtures


def electrical(f,added):
    inverse = {name:direction for direction,name in FACING.items()}
    signals = {p:(inverse[s.split('facing=')[1].split(',')[0].split(']')[0]]
                  if 'repeater' in s else None)
               for p,s in f.blocks.items() if 'redstone_wire' in s or 'minecraft:repeater' in s}
    signals.update({p:inverse[d] for p,d in added.items()})
    solids = {p for p,s in f.blocks.items() if p not in signals and
              not any(name in s for name in ('air','torch','lever','sign'))}
    return signals,solids


def quiet(algorithm,f):
    with contextlib.redirect_stdout(io.StringIO()):
        return algorithm(f.blocks,f.sources)


class RepeaterPostprocessorTests(unittest.TestCase):
    def test_stress_sources_individually_reach_every_original_node(self):
        for f in stress_fixtures():
            with self.subTest(name=f.name):
                if f.expected_error:
                    with self.assertRaises(ValueError):
                        quiet(build_graph,f)
                    continue
                original,solids = electrical(f,{})
                graph,added = quiet(build_graph,f)
                signals,_ = electrical(f,added)
                self.assertFalse(_repeater_feedback(signals,solids,added))
                for source,power,_ in f.sources:
                    reached,order = {source},[source]
                    for p in order:
                        for q in signal_neighbors(p,original,solids):
                            if q not in reached:
                                reached.add(q)
                                order.append(q)
                    powers = signal_powers(signals,solids,source,power)
                    self.assertTrue(all(powers.get(p,0) > 0 for p in reached))
                for p in added:
                    self.assertTrue(is_eligible(p,f.blocks))
                    self.assertNotIn(p,{root for root,_,_ in f.sources})
                    self.assertNotIn('repeater',f.blocks[p])
                self.assertTrue(all(graph[p]['power'] > 0 for net in f.nets for p in net))

    def test_straight_line_lower_bound_for_every_length_and_source_power(self):
        for power in range(1,16):
            for length in range(2,100):
                f = fixture('line',[[[(x,1,0) for x in range(length+1)]]],[(0,1,0)])
                f.sources[0] = ((0,1,0),power,'south')
                _,added = quiet(build_graph,f)
                # Initial dust covers power-1 edges. Each legal repeater adds
                # 16 edges: its own position plus 15 following dust positions.
                minimum = max(0,(length-(power-1)+15)//16)
                self.assertEqual(len(added),minimum,(power,length))

    def test_small_networks_match_exhaustive_placement_oracle(self):
        selected = {'line_30','fork_10_14','fork_14_16','sparse_corner_landings'}
        for f in stress_fixtures():
            if f.name not in selected:
                continue
            _,added = quiet(build_graph,f)
            signals,solids = electrical(f,{})
            root,power,_ = f.sources[0]
            # Enumerate every legal straight site and both directions. Prove
            # no assignment using fewer repeaters than the DP can work.
            candidates = []
            for p in signals:
                if p == root or not is_eligible(p,f.blocks):
                    continue
                adjacent = list(signal_neighbors(p,signals,solids))
                axis = (adjacent[0][0]-p[0],adjacent[0][2]-p[2])
                candidates.append((p,(axis,(-axis[0],-axis[1]))))
            for count in range(len(added)):
                for sites in itertools.combinations(candidates,count):
                    for directions in itertools.product(*(options for _,options in sites)):
                        trial = signals.copy()
                        trial.update((site[0],direction) for site,direction in zip(sites,directions))
                        powers = signal_powers(trial,solids,root,power)
                        self.assertFalse(all(powers.get(p,0) > 0 for p in signals),f.name)

    def test_shared_fork_and_comb_counts(self):
        expected = {'fork_10_14':1,'fork_12_13':1,'fork_13_14':1,'comb_shared_trunk':4}
        for f in stress_fixtures():
            if f.name in expected:
                self.assertEqual(len(quiet(build_graph,f)[1]),expected[f.name])

    def test_zero_dust_landing_is_a_valid_repeater_input(self):
        f = next(f for f in stress_fixtures() if f.name == 'only_landing_at_zero')
        with self.assertRaises(ValueError):
            quiet(build_graph_baseline,f)
        self.assertEqual(quiet(build_graph,f)[1],{(15,15,0):'west'})

    def test_old_loop_feedback_is_removed_without_extra_repeaters(self):
        for name in ('loop_9_3','loop_12_3','loop_27_3'):
            f = next(f for f in stress_fixtures() if f.name == name)
            old = quiet(build_graph_baseline,f)[1]
            new = quiet(build_graph,f)[1]
            signals,solids = electrical(f,old)
            self.assertIsNotNone(_repeater_feedback(signals,solids,old),name)
            signals,solids = electrical(f,new)
            self.assertIsNone(_repeater_feedback(signals,solids,new),name)
            self.assertLessEqual(len(new),len(old))

    def test_source_order_and_input_map_are_preserved(self):
        f = next(f for f in stress_fixtures() if f.name == 'stacked_crossing')
        original = f.blocks.copy()
        first = quiet(build_graph,f)[1]
        f.sources.reverse()
        self.assertEqual(first,quiet(build_graph,f)[1])
        self.assertEqual(original,f.blocks)

    def test_long_loop_is_safe_when_return_signal_decays(self):
        f = next(f for f in stress_fixtures() if f.name == 'loop_1_7')
        _,added = quiet(build_graph,f)
        self.assertEqual(len(added),1)
        signals,solids = electrical(f,added)
        self.assertIsNone(_repeater_feedback(signals,solids,added))

    def test_cyclic_heuristic_keeps_the_better_safe_solution(self):
        f = next(f for f in stress_fixtures() if f.name == 'loop_0_17')
        # A single spanning-tree DP needs four here; alternative paths allow
        # the baseline's three. Do not regress a safe baseline on a cycle.
        self.assertEqual(len(quiet(build_graph,f)[1]),3)


if __name__ == '__main__':
    unittest.main()
