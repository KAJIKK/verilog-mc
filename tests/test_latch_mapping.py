"""Regression tests for non-interchangeable data/enable routing."""
import json
from pathlib import Path
import tempfile
import unittest

from intermediate_circuit import IntermediateCircuit
from logic_gates import LogicGates
from netlist_parser import Graph, Vertex, VertexType, parse_yosys_json


class LatchMappingTests(unittest.TestCase):
    def parse_latch(self, enable_bit=3):
        # Inputs are encountered D first, while physical pins are E first.
        data = {"modules": {"example": {
            "ports": {
                "data": {"direction": "input", "bits": [2]},
                "gate": {"direction": "input", "bits": [3]},
                "result": {"direction": "output", "bits": [4]},
            },
            "cells": {"storage": {
                "type": "$_DLATCH_P_",
                "port_directions": {"D": "input", "E": "input", "Q": "output"},
                "connections": {"D": [2], "E": [enable_bit], "Q": [4]},
            }},
        }}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latch.json"
            path.write_text(json.dumps(data))
            return parse_yosys_json(path)

    def test_named_pins_do_not_follow_source_order(self):
        graph = self.parse_latch()
        cell = graph.vertices["storage"]
        ic = IntermediateCircuit()
        gate = ic.gen_gate(cell)
        gate.x_offset = 10
        pointers = {cell: 0}
        self.assertEqual(ic._input_pins_for_source(cell, gate, graph.vertices["data"], pointers), [12])
        self.assertEqual(ic._input_pins_for_source(cell, gate, graph.vertices["gate"], pointers), [10])

    def test_shared_signal_connects_both_named_pins(self):
        graph = self.parse_latch(enable_bit=2)
        cell = graph.vertices["storage"]
        gate = LogicGates.d_latch()
        gate.x_offset = 0
        self.assertEqual(IntermediateCircuit()._input_pins_for_source(
            cell, gate, graph.vertices["data"], {cell: 0}), [0, 2])

    def test_routing_relay_preserves_signal_identity(self):
        graph = self.parse_latch()
        cell = graph.vertices["storage"]
        # Add an upstream combinational stage to make enable skip a layer.
        source = graph.vertices["data"]
        inverter = Vertex("inverter", VertexType.FUNCTION, func_type="INV", bits=[5])
        graph.add_vertex(inverter)
        source.next.remove(cell)
        cell.before.remove(source)
        graph.add_edge(source, inverter)
        graph.add_edge(inverter, cell)
        cell.input_bits["D"] = [5]
        # Keep both intermediate layers populated so the single-gate
        # compaction optimization doesn't merge them for this fixture.
        helper1 = Vertex("helper1", VertexType.FUNCTION, func_type="INV", bits=[6])
        helper2 = Vertex("helper2", VertexType.FUNCTION, func_type="INV", bits=[7])
        graph.add_vertex(helper1)
        graph.add_vertex(helper2)
        graph.add_edge(source, helper1)
        graph.add_edge(helper1, helper2)
        ic = IntermediateCircuit()
        ic.load_graph(graph)
        enable_source = next(v for v in cell.before if getattr(v, "func_type", "") == "RELAY")
        gate = ic.gen_gate(cell)
        gate.x_offset = 0
        self.assertEqual(enable_source.bits, [3])
        self.assertEqual(ic._input_pins_for_source(cell, gate, enable_source, {cell: 0}), [0])

    def test_unsupported_storage_is_not_silently_a_wire(self):
        for cell_type in ("$_DLATCH_N_", "$_DFF_P_", "$_SDFF_PP0_"):
            with self.subTest(cell_type=cell_type), self.assertRaises(ValueError):
                IntermediateCircuit().gen_gate(Vertex("unsupported", VertexType.FUNCTION,
                                                      func_type=cell_type))

    def test_complementary_outputs_route_to_separate_signals(self):
        cell = Vertex('toggle', VertexType.FUNCTION, func_type='MC_T_LATCH',
                      bits=[4, 5], output_bits={'Q': [4], 'QN': [5]})
        ic = IntermediateCircuit()
        gate = ic.gen_gate(cell)
        gate.x_offset = 10
        consumer = Vertex('consumer', VertexType.FUNCTION,
                          input_bits={'D': [4], 'E': [5]})
        consumer_gate = LogicGates.d_latch()
        consumer_gate.x_offset = 20
        routes = [(pin, ic._input_pins_for_source(consumer, consumer_gate, source,
                                                 {consumer: 0}))
                  for pin, source in ic._output_sources(cell, gate)]
        self.assertEqual(routes, [(10, [20]), (12, [22])])
        output = Vertex('q', VertexType.OUTPUT, bits=[4])
        output_gate = LogicGates.output_gate('q')
        output_gate.x_offset = 0
        inverse_source = ic._output_sources(cell, gate)[0][1]
        self.assertEqual(ic._input_pins_for_source(output, output_gate,
                                                  inverse_source, {output: 0}), [])

    def test_top_design_is_selected_instead_of_library_blackbox(self):
        data = {'modules': {
            'MC_SR_LATCH': {'attributes': {'blackbox': '1'}, 'ports': {}},
            'design': {'attributes': {'top': '1'},
                       'ports': {'s': {'direction': 'input', 'bits': [2]}},
                       'cells': {}},
        }}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'design.json'
            path.write_text(json.dumps(data))
            self.assertEqual(set(parse_yosys_json(path).vertices), {'s'})

    def test_multi_output_relays_keep_each_bit_separate(self):
        graph = Graph()
        nodes = [
            Vertex('input', VertexType.INPUT, bits=[2]),
            Vertex('toggle', VertexType.FUNCTION, func_type='MC_T_LATCH', bits=[4, 5],
                   input_bits={'T': [2], 'R': [2]}, output_bits={'Q': [4], 'QN': [5]}),
            Vertex('a', VertexType.FUNCTION, func_type='INV', bits=[6]),
            Vertex('b', VertexType.FUNCTION, func_type='INV', bits=[7]),
            Vertex('c', VertexType.FUNCTION, func_type='INV', bits=[8]),
            Vertex('consumer', VertexType.FUNCTION, func_type='$_DLATCH_P_', bits=[10],
                   input_bits={'D': [4], 'E': [5], 'dependency': [7]}),
            Vertex('d', VertexType.FUNCTION, func_type='INV', bits=[9]),
            Vertex('out', VertexType.OUTPUT, bits=[10]),
        ]
        for node in nodes:
            graph.add_vertex(node)
        for source, target in [('input','toggle'), ('input','a'), ('a','b'), ('a','c'),
                               ('toggle','consumer'), ('b','consumer'), ('c','d'),
                               ('consumer','out')]:
            graph.add_edge(graph.vertices[source], graph.vertices[target])
        ic = IntermediateCircuit()
        ic.load_graph(graph)
        relays = graph.vertices['toggle'].next
        self.assertEqual(sorted(v.bits for v in relays), [[4], [5]])
        self.assertTrue(all(v.next == [graph.vertices['consumer']] for v in relays))


if __name__ == "__main__":
    unittest.main()
