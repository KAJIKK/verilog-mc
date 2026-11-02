"""Footprint and physical signal identity regressions for gate placement."""
import contextlib
import io
from pathlib import Path
import unittest

from intermediate_circuit import IntermediateCircuit
from logic_gates import Gate
from netlist_parser import Graph, Vertex, VertexType, parse_yosys_json
from tests import test_latch_mapping


class GatePlacementTests(unittest.TestCase):
    def build(self, graph, placement='compact'):
        ic = IntermediateCircuit()
        with contextlib.redirect_stdout(io.StringIO()):
            ic.load_graph(graph)
            ic.build_gates()
            ic.route_channels(workers=1,placement=placement,cache=False)
        return ic

    def test_data_enable_align_without_swapping_named_roles(self):
        graph = test_latch_mapping.LatchMappingTests().parse_latch()
        ic = self.build(graph)
        inputs = {v.name:g.x_offset for v,g in zip(ic.vertex_layers[0],ic.gate_layers[0])}
        cell = next(g for vs,gs in zip(ic.vertex_layers,ic.gate_layers)
                    for v,g in zip(vs,gs) if v.name == 'storage')
        self.assertEqual(inputs['gate'],cell.x_offset)
        self.assertEqual(inputs['data'],cell.x_offset+2)
        pins = ic.channels[0].circuit.net_pins
        self.assertTrue(all(source[0] == sink[0] for source,sink in pins))
        self.assertEqual(ic.channels[0].size_z(),3)
        legacy = self.build(test_latch_mapping.LatchMappingTests().parse_latch(),'legacy')
        compact_circuit,_,_ = ic.gen_circuit()
        legacy_circuit,_,_ = legacy.gen_circuit()
        self.assertLess(compact_circuit.size_x*compact_circuit.size_z,
                        legacy_circuit.size_x*legacy_circuit.size_z)

    def test_q_and_qn_align_to_their_own_output_pins(self):
        graph = Graph()
        nodes = [Vertex('s',VertexType.INPUT,bits=[2]),
                 Vertex('r',VertexType.INPUT,bits=[3]),
                 Vertex('cell',VertexType.FUNCTION,func_type='MC_SR_LATCH',bits=[4,5],
                        input_bits={'S':[2],'R':[3]},output_bits={'Q':[4],'QN':[5]}),
                 Vertex('q',VertexType.OUTPUT,bits=[4]),
                 Vertex('qn',VertexType.OUTPUT,bits=[5])]
        for node in nodes:
            graph.add_vertex(node)
        for a,b in ((0,2),(1,2),(2,3),(2,4)):
            graph.add_edge(nodes[a],nodes[b])
        ic = self.build(graph)
        outputs = {v.name:g.x_offset for v,g in zip(ic.vertex_layers[-1],ic.gate_layers[-1])}
        self.assertEqual(outputs,{'qn':0,'q':2})
        self.assertEqual({tuple(p[0] for p in net) for net in ic.channels[-1].circuit.net_pins},
                         {(0,0),(2,2)})

    def test_variable_widths_fit_after_reordering_with_safe_gaps(self):
        ic = IntermediateCircuit()
        rows = [[Vertex(str(i),VertexType.INPUT,bits=[i]) for i in range(4)],
                [Vertex('sink'+str(i),VertexType.OUTPUT,bits=[3-i]) for i in range(4)]]
        ic.vertex_layers = rows
        ic.v_to_layer = {v:i for i,vs in enumerate(rows) for v in vs}
        ic.gate_layers = [[Gate(w,1,1,1,1) for w in widths]
                          for widths in ((1,4,2,3),(2,1,3,4))]
        for gs in ic.gate_layers:
            for g in gs:
                g.x_offset = 0
        for source,sink in zip(rows[0],reversed(rows[1])):
            source.add_next(sink)
            sink.add_before(source)
        ic.place_gates()
        budget = ic.placement_stats['row_width_budget']
        for gs in ic.gate_layers:
            self.assertTrue(all(g.x_offset % 2 == 0 for g in gs))
            self.assertTrue(all(b.x_offset >= a.x_offset+a.size_x+1 for a,b in zip(gs,gs[1:])))
            self.assertTrue(all(g.x_offset+g.size_x <= budget for g in gs))

    def test_feedback_edges_are_included_without_mutating_graph(self):
        source = Vertex('input',VertexType.INPUT,bits=[1])
        sink = Vertex('output',VertexType.OUTPUT,bits=[3])
        a = Vertex('a',VertexType.FUNCTION,func_type='AND',bits=[2],input_bits={'A':[1],'B':[3]})
        b = Vertex('b',VertexType.FUNCTION,func_type='INV',bits=[3],input_bits={'A':[2]})
        up = Vertex('up',VertexType.FUNCTION,func_type='RELAY',bits=[3])
        down = Vertex('down',VertexType.FUNCTION,func_type='RELAY',bits=[3])
        for u,v in ((source,a),(a,b),(b,down),(down,up),(up,a),(b,sink)):
            u.add_next(v)
            v.add_before(u)
        ic = IntermediateCircuit()
        ic.vertex_layers = [[source],[a,up],[b,down],[sink]]
        ic.v_to_layer = {v:i for i,vs in enumerate(ic.vertex_layers) for v in vs}
        ic.build_gates()
        edges_before = {v:tuple(v.next) for vs in ic.vertex_layers for v in vs}
        ic.place_gates()
        edges = ic._placement_edges()
        self.assertTrue(any(same for *_,same in edges))
        self.assertTrue(any(ic.v_to_layer[u] > ic.v_to_layer[v]
                            for _,u,ox,oy,v,ix,iy,same in edges))
        self.assertEqual(edges_before,{v:tuple(v.next) for v in edges_before})

    def test_storage_design_has_smaller_routed_footprint(self):
        path = Path(__file__).resolve().parents[1]/'output'/'storage_demo.json'
        if not path.exists():
            self.skipTest('Run make TOP=storage_demo to generate the netlist')
        compact = self.build(parse_yosys_json(path))
        legacy = self.build(parse_yosys_json(path),'legacy')
        a,_,_ = compact.gen_circuit()
        b,_,_ = legacy.gen_circuit()
        self.assertLess(a.size_x*a.size_z,b.size_x*b.size_z)
        self.assertEqual(compact.get_statistics()['gate_counts'],legacy.get_statistics()['gate_counts'])


if __name__ == '__main__':
    unittest.main()
