"""Geometry, electrical reachability, power, and integration regressions."""
from collections import deque
import contextlib
import io
import unittest

from tests.generate_router_test import CASES, postprocess
from intermediate_circuit import IntermediateCircuit
from logic_gates import Gate
from netlist_parser import Graph, Vertex, VertexType
from router import RoutingError, route, _Layout
from redstone_geometry import signal_powers


def verify_geometry(test, circuit):
    owners = {p: i for i, wires in enumerate(circuit.net_wires) for p in wires}
    for owner, pins in enumerate(circuit.net_pins):
        if not pins:
            continue
        seen, queue = {pins[0]}, deque([pins[0]])
        while queue:
            x,y,z = queue.popleft()
            for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
                for dy in (-1,0,1):
                    other = (x+dx,y+dy,z+dz)
                    if other not in owners:
                        continue
                    lower = (x,y,z) if dy == 1 else other
                    throat = (lower[0],lower[1]+1,lower[2])
                    if dy and throat in circuit.blocks:
                        continue
                    test.assertEqual(owners[other], owner, f'Wire short at {other}')
                    if other not in seen:
                        seen.add(other)
                        queue.append(other)
        test.assertTrue(set(pins).issubset(seen), (pins, seen))
        test.assertEqual(seen, set(circuit.net_wires[owner]), 'Disconnected branch')
    for x,y,z in owners:
        support = circuit.blocks.get((x,y-1,z), '')
        test.assertTrue('wool' in support or support == 'minecraft:stone', ((x,y,z), support))
    for throat in circuit.required_air:
        test.assertNotIn(throat,circuit.blocks,'Blocked climbing/descending throat')


class HeightRouterTests(unittest.TestCase):
    def test_basic_through_complex_electrical_routes(self):
        for name,nets,options in CASES:
            with self.subTest(name=name):
                circuit = route(nets, **options)
                self.assertFalse(circuit.routing_repeaters)
                self.assertFalse(any('repeater' in block for block in circuit.blocks.values()))
                verify_geometry(self, circuit)
                blocks, graph, repeaters = postprocess(circuit)
                for wires in circuit.net_wires:
                    self.assertTrue(all(graph.get(p, {}).get('power', 0) > 0 for p in wires))
                for pos in repeaters:
                    x,y,z = pos
                    facing = blocks[pos].split('facing=')[1].split(']')[0]
                    dx,dz = {'east':(1,0),'west':(-1,0),'north':(0,-1),'south':(0,1)}[facing]
                    self.assertIn((x+dx,y,z+dz), circuit.net_wires[next(i for i,w in enumerate(circuit.net_wires) if pos in w)])
                    self.assertIn((x-dx,y,z-dz), circuit.blocks)
                if name in ('tall_uphill','tall_downhill','long_horizontal'):
                    self.assertTrue(repeaters)
                if name in ('stacked_straight_two_levels','perpendicular_two_levels',
                            'repeater_crossing_two_levels'):
                    self.assertTrue(any((x,y+2,z) in circuit.net_wires[1]
                                        for x,y,z in circuit.net_wires[0]),
                                    'Fixture must exercise an actual two-level crossing')

    def test_compact_aligned_connections(self):
        circuit = route([[(x,0,True),(x,0,False)] for x in range(0,9,2)])
        self.assertEqual((circuit.size_x,circuit.size_y,circuit.size_z), (9,1,3))
        self.assertEqual(circuit.route_stats['wire_blocks'], 15)

    def test_shared_x_different_heights_are_distinct(self):
        circuit = route([[(0,0,True),(0,0,False)], [(0,3,True),(0,3,False)]])
        verify_geometry(self, circuit)
        self.assertEqual(circuit.size_y, 4)

    def test_flat_support_can_cover_wire_but_not_slope_throat(self):
        lower, rising = (2,0,2), (2,1,3)
        upper = (2,2,2)
        layout = _Layout(5,5,7,[],{})
        layout.commit([(lower,None)],0)
        self.assertTrue(layout.valid(upper,1,(0,0)))
        self.assertFalse(layout.valid((2,1,2),1,(0,0)), 'Support would replace lower dust')
        layout.commit([(upper,None)],1)
        self.assertEqual(layout.step_clear(lower,(3,0,2),(0,0)),0)
        self.assertIsNone(layout.step_clear(lower,rising,(0,0)))
        self.assertIsNone(layout.step_clear(rising,lower,(0,0)))
        for path in ([(lower,None),(rising,None)], [(rising,None),(lower,None)]):
            layout = _Layout(5,5,7,[],{})
            layout.commit(path,0)
            self.assertIn((2,1,2),layout.clear)
            self.assertFalse(layout.valid(upper,1,(0,0)), 'Support would cut a routed slope')

    def test_uncommitted_slope_and_diagonal_short_are_protected(self):
        layout = _Layout(5,5,7,[],{})
        lower, rising = (2,0,2), (2,1,3)
        wires = layout.bit(lower) | layout.bit(rising)
        throat = layout.step_clear(lower,rising,(0,0))
        self.assertFalse(layout.valid((2,2,2),1,(wires,throat)))
        layout.commit([(lower,None)],0)
        self.assertFalse(layout.valid((3,1,2),1,(0,0)), 'Diagonal dust would short nets')

    def test_declared_external_pin_climb_cannot_be_covered(self):
        with self.assertRaises(RoutingError):
            route([[(0,0,True),(0,0,False)],[(0,2,True),(0,2,False)]],
                  width=1,height=3,length=11,pin_headroom=[(0,0,True)])
        circuit = route([[(0,0,True),(0,0,False)]],pin_headroom=[(0,0,True)])
        self.assertIn((0,1,0),circuit.required_air)

    def test_gate_external_dust_climb_is_detected(self):
        graph = Graph()
        source = Vertex('input',VertexType.INPUT,bits=[2])
        sink = Vertex('output',VertexType.OUTPUT,bits=[2])
        graph.add_vertex(source)
        graph.add_vertex(sink)
        graph.add_edge(source,sink)
        gate = Gate(1,2,1,1,1)
        gate.set_block(0,0,0,'minecraft:white_wool')
        gate.set_block(0,1,0,'minecraft:redstone_wire')
        sink_gate = Gate(1,1,1,1,1)
        sink_gate.set_block(0,0,0,'minecraft:redstone_lamp')
        ic = IntermediateCircuit()
        ic.load_graph(graph)
        ic.gate_layers = [[gate],[sink_gate]]
        with contextlib.redirect_stdout(io.StringIO()):
            ic.route_channels()
        self.assertIn((0,1,0),ic.channels[0].circuit.required_air)

    def test_assembly_rejects_an_extension_cutting_a_port_climb(self):
        source = Vertex('ports',VertexType.FUNCTION,func_type='PORTS',bits=[2,3])
        dummy = Vertex('dummy',VertexType.FUNCTION,func_type='RELAY')
        ports = Gate(2,3,1,0,2)
        ports.x_offset = 0
        ports.output_offsets = [[0,0],[0,2]]
        ports.set_block(0,0,0,'minecraft:white_wool')
        ports.set_block(0,1,0,'minecraft:redstone_wire')
        ports.set_block(0,2,0,'minecraft:redstone_wall_torch[facing=west]')
        ports.set_block(1,2,0,'minecraft:white_wool')
        padding = Gate(1,1,2,0,0)
        padding.x_offset = 3
        ic = IntermediateCircuit()
        ic.vertex_layers = [[source,dummy]]
        ic.gate_layers = [[ports,padding]]
        with self.assertRaisesRegex(ValueError,'headroom'):
            ic.gen_circuit()

    def test_air_substring_does_not_discard_stair_obstacles(self):
        p = (2,0,2)
        circuit = route([[(0,0,True),(0,0,False)]],width=3,height=1,length=7,
                        obstacles={p:'minecraft:stone_stairs'})
        self.assertEqual(circuit.blocks[p],'minecraft:stone_stairs')

    def test_parallel_channels_match_serial_results(self):
        def build(workers):
            graph = Graph()
            nodes = [Vertex('input',VertexType.INPUT,bits=[2]),
                     Vertex('inv',VertexType.FUNCTION,func_type='INV',bits=[3],input_bits={'A':[2]}),
                     Vertex('output',VertexType.OUTPUT,bits=[3])]
            for node in nodes:
                graph.add_vertex(node)
            graph.add_edge(nodes[0],nodes[1])
            graph.add_edge(nodes[1],nodes[2])
            ic = IntermediateCircuit()
            ic.load_graph(graph)
            ic.build_gates()
            with contextlib.redirect_stdout(io.StringIO()):
                ic.route_channels(workers=workers)
            return [(c.circuit.blocks,c.circuit.net_pins) for c in ic.channels]
        self.assertEqual(build(1),build(2))

    def test_empty_and_duplicate_pins(self):
        self.assertFalse(route([]).blocks)
        circuit = route([[], [(0,0,True),(0,0,True),(0,0,False)]])
        self.assertEqual(len(circuit.net_pins[1]), 2)
        verify_geometry(self, circuit)

    def test_invalid_and_conflicting_pins(self):
        for pin in ((-1,0,True), (0,-1,True), (0,1.5,True), (0,0,1)):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                route([[pin]])
        with self.assertRaisesRegex(ValueError, 'multiple nets'):
            route([[(0,3,True)], [(0,3,True)]])

    def test_impossible_bounds_and_obstructed_exit_fail(self):
        with self.assertRaises(RoutingError):
            route([[(0,0,True),(4,0,False)], [(4,0,True),(0,0,False)]],
                  width=5, height=1, length=5, max_states=1000)
        with self.assertRaises(RoutingError):
            route([[(0,0,True),(0,0,False)]], width=1, length=5, height=1,
                  obstacles={(0,0,1): 'minecraft:stone'})
        with self.assertRaises(RoutingError):
            route([[(0,0,True),(0,6,False)]], height=2)

    def test_deterministic_and_obstacles_preserved(self):
        nets = [[(0,0,True),(4,5,False)], [(4,0,True),(0,0,False)]]
        self.assertEqual(route(nets).blocks, route(nets).blocks)
        name,nets,options = next(case for case in CASES if case[0] == 'obstacle_wall')
        circuit = route(nets, **options)
        for p,block in options['obstacles'].items():
            self.assertEqual(circuit.blocks[p], block)

    def test_named_height_pins_keep_signal_identity(self):
        ic = IntermediateCircuit()
        source = Vertex('source', VertexType.FUNCTION, bits=[4,5], output_bits={'Q':[4],'QN':[5]})
        gate = Gate(3,7,2,2,2)
        gate.x_offset = 10
        gate.input_offsets = {'D':[0,3], 'E':[2,6]}
        gate.output_offsets = {'Q':[0,6], 'QN':[2,3]}
        consumer = Vertex('consumer', VertexType.FUNCTION, input_bits={'D':[4],'E':[5]})
        sources = ic._output_sources(source, gate, True)
        self.assertEqual([p for p,s in sources], [(10,6),(12,3)])
        self.assertEqual(ic._input_pins_for_source(consumer, gate, sources[1][1], {consumer:0}, True), [(12,6)])

    def test_height_pins_survive_full_channel_assembly(self):
        graph = Graph()
        source = Vertex('input', VertexType.INPUT, bits=[2])
        output = Vertex('output', VertexType.OUTPUT, bits=[2])
        graph.add_vertex(source)
        graph.add_vertex(output)
        graph.add_edge(source, output)
        ic = IntermediateCircuit()
        ic.load_graph(graph)
        input_gate = Gate(1,6,1,1,1)
        input_gate.output_offsets = [ [0,5] ]
        input_gate.set_block(0,5,0,'minecraft:white_wool')
        output_gate = Gate(1,9,1,1,1)
        output_gate.input_offsets = [ [0,8] ]
        output_gate.set_block(0,8,0,'minecraft:redstone_lamp')
        ic.gate_layers = [[input_gate],[output_gate]]
        ic.route_channels()
        circuit, sources, _ = ic.gen_circuit()
        channel = ic.channels[0].circuit
        self.assertEqual(channel.net_pins[0], [(0,5,0),(0,8,channel.size_z-1)])
        self.assertIn(((0,5,1),15,'south'), sources)
        self.assertGreaterEqual(circuit.size_y,9)
        self.assertEqual(circuit.blocks[(0,8,circuit.size_z-1)],'minecraft:redstone_lamp')

    def test_no_fixed_height_ceiling(self):
        circuit = route([[(0,128,True),(0,0,False)]], width=1)
        verify_geometry(self,circuit)
        self.assertEqual(circuit.size_y,129)
        _,graph,repeaters = postprocess(circuit)
        self.assertTrue(repeaters)
        self.assertGreater(graph[circuit.net_pins[0][1]]['power'],0)

    def test_repeaters_are_directional_including_existing_chains(self):
        signals = {(0,0,0):None,(1,0,0):(1,0),(2,0,0):(1,0),(3,0,0):None}
        self.assertEqual(signal_powers(signals,set(),(0,0,0))[(3,0,0)],15)
        self.assertNotIn((0,0,0),signal_powers(signals,set(),(3,0,0)))


if __name__ == '__main__':
    unittest.main()
