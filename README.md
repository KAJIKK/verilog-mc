# Verilog to Minecraft (verilog-mc)

A compiler toolchain that translates Verilog hardware descriptions into functional Minecraft redstone circuits.

## Overview

`verilog-mc` leverages the industry-standard synthesis tool **Yosys** to compile Verilog code into a gate-level netlist. This netlist is then mapped to a custom library of Minecraft logic gates and automatically laid out and routed into a `.schem` file, ready to be imported into Minecraft via WorldEdit.

### Key Features

- **Verilog Synthesis:** Uses Yosys to process Verilog, supporting standard logic constructs.
- **Custom Gate Library:** Maps logic to compact, Redstone-efficient gate designs (AND, OR, XOR, MUX, etc.).
- **Automatic Routing:** Handles complex wire routing between gates.
- **Signal Post-Processing:** Automatically places repeaters on long redstone lines to prevent signal loss.
- **Carry Cancel Adder Support:** Includes high-performance adder architectures (like CCA) optimized for Minecraft's redstone tick system.
- **Visualization:** Generate SVG diagrams of the synthesized logic netlists.

## Project Structure

- `*.v`: Verilog source files (e.g., `adder32_cca.v`, `multiplexer4_1.v`).
- `my_gates.lib`: Liberty library file defining the gate primitives for Yosys.
- `gates.json`: Physical layout and block definitions for each gate in Minecraft.
- `generate_schem.py`: The main script to generate a Minecraft schematic from a synthesized netlist.
- `repeater_postprocessor.py`: A graph-based tool to optimize repeater placement for all signal sources.
- `router.py`: Logic for routing redstone signals between gates.
- `Makefile`: Orchestrates the synthesis and visualization pipeline.

## Prerequisites

- **Yosys:** Open Source Synthesis Suite.
- **Python 3.10+**
- **mcschematic:** Python library for generating Minecraft schematics.
- **nbtlib:** NBT parsing library.
- **Graphviz (Optional):** For netlist visualization.

## Usage

### 1. Synthesis

To synthesize your Verilog code into a JSON netlist:

```bash
make TOP=your_module_name
```

Replace `your_module_name` with the name of your Verilog module. The output will be stored in `output/your_module_name.json`.

### 2. Schematic Generation

Convert the synthesized netlist into a Minecraft schematic:

```bash
python3 generate_schem.py output/your_module_name.json
```

This will generate `your_module_name.schem` in the current directory and automatically attempt to copy it to your Minecraft WorldEdit schematics folder.

### 3. Visualization

To view the synthesized gate-level logic:

```bash
make viz TOP=your_module_name
```

This generates an SVG file in the `output/` directory.

### 4. Four-bit adder and live Minecraft test

`adder4.v` adds two unsigned 4-bit inputs (`a`, `b`) into a 5-bit
`sum`, retaining carry-out in `sum[4]`. Build and copy to your active
Minecraft instance:

```bash
make TOP=adder4
WORLDEDIT_SCHEMATICS_DIR="/path/to/minecraft/config/worldedit/schematics" \
  python3 generate_schem.py output/adder4.json
```

In Minecraft, stand at the intended circuit origin and run:

```text
//schem load adder4.schem
//paste
```

The input signs label bits from least significant to most significant.
Attach north-facing wall levers to the north faces of the input wool blocks.
The output lamps represent `sum[0]` through `sum[4]`.

`generate_adder_test.py` generates a datapack which installs those levers,
drives all 256 input pairs, waits 100 game ticks per pair, and compares the
live lamps against the expected sum. It reads IO positions from the schematic
labels; use the actual WorldEdit paste origin (shown in chat):

```bash
python3 generate_adder_test.py adder4.schem "/path/to/world/datapacks" \
  --origin 24 -60 24
```

Then run via Minecraft chat or Minecraft MCP:

```text
/reload
/function adder4_test:start
/tick sprint 26000t
/data get storage adder4_test:results
```

The generated test datapack targets Minecraft 26.3 (data pack version 121.0).
Keep the circuit loaded while testing and wait for `status: "complete"`.
The driver refreshes the first dust after setting each lever because command
placement doesn't notify the attached block's neighbors like a right-click does.

Verified in the `flat` world using Minecraft MCP and WorldEdit 7.4.6-beta-02:

- Origin: **(24, -60, 24)**; circuit bounds including base: `(23, -61, 23)`
  through `(73, -58, 89)`.
- Logic: **7 XOR2, 9 NAND2, 1 AND2**, plus 15 routing relays.
- Exhaustive live result: **256 passed, 0 failed**.
- Inputs: `a[0..3]` at x = 24, 26, 28, 30; `b[0..3]` at x = 32, 34,
  36, 38. All levers are at y = -60, z = 23.
- Output lamps `sum[0..4]`: x = 28, 40, 52, 60, 70; y = -60, z = 88.
- A real MCP right-click on `a[0]` also verified the transition
  `15 + 15 = 30` → `14 + 15 = 29` → `15 + 15 = 30`.

## Sequential example: one-bit D latch

`dlatch.v` infers a positive-enable, level-sensitive D latch:

| Enable | Data | Output |
| --- | --- | --- |
| 1 | 0 | 0 after propagation |
| 1 | 1 | 1 after propagation |
| 0 | either | Previously stored value |

The physical `D_LATCH` primitive uses a side repeater to lock the storage
repeater when enable is low. This stores state in redstone itself. Initialize
by enabling the latch with a known data value; the Verilog initial value is
unspecified. Change inputs separately and allow propagation to settle.

The backend maps Yosys `$_DLATCH_P_` cells and routes named `D`/`E` pins by
signal identity, including through routing relays. Other latch polarities
and flip-flop cells are not mapped by this example.

```bash
make TOP=dlatch
WORLDEDIT_SCHEMATICS_DIR="/path/to/minecraft/config/worldedit/schematics" \
  python3 generate_schem.py output/dlatch.json
```

Load `dlatch.schem` with WorldEdit and paste at the chosen origin. Generate
the Minecraft 26.3 test datapack using that origin:

```bash
python3 generate_dlatch_test.py dlatch.schem "/path/to/world/datapacks" \
  --origin -352 -60 164
```

Then run in-game:

```text
/reload
/function dlatch_test:start
/tick sprint 15200t
/data get storage dlatch_test:results
```

The sequence covers all eight previous-value/data/enable combinations,
128 seeded input transitions, and 1,200-tick holds against opposite data
for both stored values. Checks inspect the actual lamp, the storage
repeater's locked/powered states, and both input dust levels. Keep the circuit
loaded until the test reports completion. The generated datapack drives
levers and observes state; it does not calculate or force the circuit output.

The original implementation was verified using Minecraft MCP and WorldEdit
in the `flat(1)` world:

- Origin: **(-340, -60, 164)**; schematic footprint **7 × 16 blocks**.
- **192 checks passed, zero failed**.
- Data lever: **(-340, -60, 163)**.
- Enable lever: **(-338, -60, 163)**.
- Output lamp: **(-338, -60, 177)**.
- Storage repeater: **(-336, -60, 172)**.
- Real MCP right-clicks also verified enabling with data 0 clears the output,
  changing data to 1 while enabled sets it, and disabling then changing data
  to 0 retains 1. The circuit is left in this last state.

Run the named-pin routing regression tests with:

```bash
python3 -m unittest test_latch_mapping -v
```

### Compact latch primitive

The optimized `D_LATCH` uses five blocks in a **3 × 1 × 2** bounding box,
down from ten blocks in **5 × 1 × 4**. Its named data and output pins are
now at x = 2; enable remains at x = 0. The declared size matches the
occupied blocks so the output channel connects directly to the storage repeater.

Rebuilt `dlatch.schem` and verified the same **192 live checks, zero failures**.
The complete schematic footprint including its base is now **5 × 16**
instead of **7 × 16** (approximately 29% less area).

- Compact circuit origin: **(-352, -60, 164)** in `flat(1)`.
- Data lever: **(-352, -60, 163)**.
- Enable lever: **(-350, -60, 163)**.
- Output lamp: **(-350, -60, 177)**.
- Storage repeater: **(-350, -60, 173)**.
- Final state: **data = 0, enable = 0, stored output = 1**.

## Imported SR and toggle/reset primitives

`SR_latch_primitive.schem` and `T_latch_primitive.schem` are imported into
`gates.json` with `import_storage_primitives.py`. The importer handles Sponge
v2/v3 palette varints, ignores clipboard offsets, and removes captured power
states. The observer of the T primitive is at local **(0, 0, 0)**.

| Library cell | Size (X × Y × Z) | Blocks | Front input X offsets | Rear output X offsets |
| --- | --- | --- | --- | --- |
| `SR_LATCH` | 3 × 2 × 2 | 8 | S = 2, R = 0 | Q = 2 (dust), QN = 0 (wool) |
| `T_LATCH` | 3 × 1 × 4 | 10 | T = 2 (comparator), R = 0 (observer) | Q = 2 (wool), QN = 0 (dust) |

The SR primitive has active-high set/reset inputs. Both low retain state;
**both high are forbidden**, so it is not a priority-defined SR cell.

The T primitive toggles on rising power at T. Its observer reset responds to
**both rising and falling edges** of R. Holding R high does not inhibit T.
Apply reset with T low: **reset is ignored while T stays high**, and merely
lowering T afterward does not replay the missed reset. Change R again with
T low to reset it. Initialize storage explicitly after placement.

Live tests of library-generated fixtures in Minecraft 26.3, world `flat(1)`:

- SR origin **(-400, -60, 164)**: **102 passed, zero failed**, including legal
  previous-state/input combinations, 64 seeded transitions, recovery from
  forbidden inputs, and 1,200-tick holds. Both Q and QN are checked.
  Two forbidden-input observations
  are logged without assigning a deterministic expected result.
- T origin **(-390, -60, 164)**: **99 passed, 4 failed** of 103 assertions.
  Two failures are an ignored **2-game-tick** toggle pulse and its subsequent
  hold; two are the overlapping-reset condition and its retained result.
  **4, 8, 20, 100, and 1,200-game-tick high pulses passed**, with 60-tick low
  gaps. Both Q and QN are checked. These are tested timings, not a promise
  for every shorter pulse spacing or simultaneous transition.

The fixtures are left with floor levers for manual use (all at y = -60,
z = 162): SR set x = -398, SR reset x = -400, T toggle x = -388,
T reset x = -390. SR Q is left at 0 (QN = 1); T Q is left at 1 (QN = 0).

The test drives only input power blocks; Q and QN are produced by the actual
redstone components. Output wires are connected before measurements so lamp
placement does not introduce a command-only initialization artifact.

### Use all three storage primitives in one design

`storage_cells.v` supplies black-box declarations loaded by the Makefile.
Explicit instances preserve the physical primitives through Yosys:

```verilog
MC_SR_LATCH flag_cell(.S(set_flag), .R(reset_flag), .Q(flag), .QN(flag_n));
MC_T_LATCH toggle_cell(.T(toggle), .R(reset_toggle), .Q(q), .QN(q_n));
```

`storage_demo.v` combines these with an inferred D latch. It synthesizes into
one cell of each kind, and schematic generation has been verified. Routing
tracks Q and QN separately, including through intermediate relay layers.
These explicit cells do not automatically replace arbitrary inferred
flip-flops or priority-defined set/reset logic. The black-box declarations
are synthesis interfaces, not behavioral simulation models.

```bash
python3 import_storage_primitives.py "/path/to/minecraft/config/worldedit/schematics"
make TOP=storage_demo
WORLDEDIT_SCHEMATICS_DIR="/path/to/minecraft/config/worldedit/schematics" \
  python3 generate_schem.py output/storage_demo.json
```

### Repeat the live primitive tests

The test creates fixtures at the two fixed origins above; those footprints
must be reserved for testing. It replaces only those test fixture regions.

```bash
python3 generate_storage_test.py "/path/to/world/datapacks"
```

Keep both fixtures loaded and run:

```text
/reload
/function storage_test:start
/tick sprint 24668t
/data get storage storage_test:results status
/data get storage storage_test:results SR_LATCH
/data get storage storage_test:results T_LATCH
/data get storage storage_test:results failures
```

There are 220 observations, including pulse-phase and forbidden-SR
characterization steps without assertions. `entries` retains each observation;
`failures` records assertion failures with inputs, expected Q, actual Q and QN.
The four T failures above are intentional boundary probes and remain visible.

## Height-aware routing

`router.py` now routes actual 3D pin coordinates instead of flattening every
pin to Y=0. Its existing tuple API remains:

```python
from router import route

channel = route([
    # First pin is the source; remaining pins are sinks at either boundary.
    [(0, 0, True), (4, 3, True), (0, 6, False), (8, 0, False)],
])
print(channel.size_x, channel.size_y, channel.size_z)
print(channel.route_stats)
```

- `True` means the top row, Z=0; `False` means the bottom row,
  Z=`channel.size_z - 1`. Either row can contain sources or sinks.
- X/Y are nonnegative local coordinates. Translate the resulting circuit to
  the desired world origin; supports below Y=0 are included at Y=-1.
- Heights have no fixed three-block ceiling. Channels can climb, descend,
  connect pins on the same row, and fan out across different heights.
- Routing uses weighted 3D search, multi-source attachment to existing net
  trees, deterministic ordering retries, and obstacle-aware reverse search
  for congestion. Compact footprint/height budgets are tried first.
- Every dust block gets a solid support. Pin escape corridors, dust headroom,
  and inter-net spacing prevent overwritten supports and unintended joins.
  Flat lines can cross or stack **two Y levels apart**: lower dust at Y=0,
  upper support at Y=1, upper dust at Y=2. No extra air block is required.
  Climbs/descents reserve their actual throat above the lower wire; neither
  a later support nor a wire may occupy it. Optional escape reservations are
  released when a net is complete; its actual wires and slope clearance stay.
- Long climbs and winding paths include flat landing sections. Branches
  preserve usable upstream landings and avoid accidental same-net loops.
  **The router places only dust and supports. All repeater placement remains
  in `repeater_postprocessor.py`.**

`width`, `height`, and `length` can fix individual channel bounds.
`max_height`, `max_length`, `attempts`, and `max_states` control bounded
automatic growth/search. `obstacles={(x, y, z): block_state}` supplies existing
static geometry; full solid supports such as stone are reused without overwriting
them. This is a bounded heuristic router, not a global minimum-size solver.
Electrically incompatible pins or insufficient bounds raise `RoutingError`.
`min_width` provides a row-width lower bound without fixing channel width.
`pin_headroom=[(x,y,is_top), ...]` reserves air above ports whose external
connection climbs/descends. The compiler detects gate-edge dust above such
ports and also checks gate-row extensions against their required clearance.

### Height-aware gate interfaces

Library `input_offsets` and `output_offsets` accept either legacy X integers
or `[x, y]` offsets, in lists or named-port dictionaries. For example:

```json
"input_offsets": {"D": [2, 4], "E": [0, 1]},
"output_offsets": {"Q": [2, 8]}
```

The physical gate blueprint must expose those pins at the declared heights.
`IntermediateCircuit` carries the heights through named signal mapping,
channel routing, output extensions, supports, and final circuit dimensions.
Existing integer-offset gates remain compatible.

The repeater postprocessor now models direction and attenuation explicitly,
restores power only on flat straight dust, and terminates on staircase/loop
graphs. Generation reports an error if power cannot be restored, rather than
exporting an underpowered bare-wire fallback.

### Compact gate placement

Gate placement in `IntermediateCircuit` prioritizes circuit footprint. The
default `ic.route_channels(placement='compact')` places all rows, including I/O,
within a width budget derived from packing the widest row. It retains even X
origins and at least one block between gate bounding boxes. Narrower rows can
use spare space to align their connections without making the circuit wider.

Placement uses actual physical pin coordinates and the same signal mapping as
the router, including named D/E, MUX inputs, separate Q/QN outputs, backward
connections and relay branches. It does not change the graph or gate blueprints.
Alternating forward/backward ordering sweeps and adjacent exchanges minimize:

```text
sum(horizontal pin-to-pin distances)
  + 2 * sum(maximum horizontal span in each channel)
  + 4 * number of crossing pin pairs
```

For each row order, dynamic programming chooses the best legal even offsets
within the width budget. The best whole-layout snapshot is retained. This is a
placement proxy, not a guarantee of the smallest routed circuit; channel length
and height are still determined by the router. Port order may change physically;
IO sign labels continue to identify the signals, and live tests locate pins by
those labels.

Measured generated dimensions (W×H×L), comparing the previous placement with
compact placement on the same netlists and router:

| Circuit | Previous placement | Compact placement | W×L reduction |
| --- | ---: | ---: | ---: |
| Four-bit adder | 51×7×61 | **41×5×59** | **22.2%** |
| Storage demo | 13×3×22 | **13×3×12** | **45.5%** |
| D latch | 5×3×16 | **5×3×10** | **37.5%** |

Storage and D-latch channels now align straight through at the minimum three
blocks of channel length, with no routing repeaters. The adder needs 30 routing
repeaters rather than 33. All repeater placement remains in the postprocessor.
The newly placed adder passes all **256** live input combinations; the newly
placed D latch passes **192** live transparency/retention checks, both with zero
failures. Five placement regressions cover footprint, named pin alignment,
variable-width packing and feedback edges, alongside the existing 25 tests.

Use `ic.route_channels(placement='legacy')` to reproduce the previous placement.
The benchmark reports assembled dimensions and footprint as well as time:

```bash
python3 -m tests.benchmark_router --design output/adder4.json --placement legacy --repeat 3
python3 -m tests.benchmark_router --design output/adder4.json --placement compact --repeat 3
python3 -m unittest discover -s tests -p 'test_gate_placement.py' -v
```

### Experimental gate reversal and row folding

`tests/benchmark_orientation.py` probes 180-degree rotations about Y, rotating
block coordinates, component facing, wire connection properties and pin offsets
together. I/O remains at the two boundary rows. Opposite-facing ports require
real, signal-specific feedthroughs across gate rows; their width, wire length,
attenuation and repeaters are included. This is an isolated experiment, not the
production placement algorithm.

The experiment evaluated **35 candidates** across the adder, storage demo and
D latch: forward controls, every individual real-gate flip, whole-row flips,
and individual adjacent-row folds with and without reversal. Reversing gates
without changing row membership did not beat the current production adder
footprint. Accepted reversed storage layouts were larger; two storage variants
were rejected by the repeater postprocessor. Reversing the standalone D latch
increased its footprint from 50 to 154 blocks because it needed three
feedthroughs around its row.

The strongest folded adder candidates were then checked exhaustively in-world:

| Layout | W×H×L | W×L | Versus current production footprint | Routing repeaters | Live checks |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current compact production placement | 41×5×59 | 2419 | — | 30 | 256/256 |
| Fold internal rows 2/3; reverse three gates | 47×7×49 | 2303 | −4.8% | 39 | 256/256 |
| Fold the same rows; all gates forward | 41×3×47 | 1927 | **−20.3%** | 17 | 256/256 |

Both new live runs had zero failures. The reversed fixture is at
**(-479, -60, 390)**, namespace `adder_reverse`; the forward-folded fixture is
at **(-415, -60, 390)**, namespace `adder_fold`. The production fixture remains
at its previous origin. These results suggest making layer merging/relay
reduction the next size optimization, with reversal considered as an optional
candidate when its routing benefit outweighs extra feedthroughs.

This is a bounded sample, not an exhaustive orientation optimizer. All
experimental variants use the same routing budgets (3 ordering attempts, 4000
states, maximum channel length 17 and height 9) and fixed pre-placement physical
input assignments. Production can reassign interchangeable logic inputs during
placement. The experimental all-forward adder control is therefore 41×3×63,
not the production 41×5×59. Compare experimental variants to one another to
isolate reversal, and the live-verified best candidates to production to measure
the available end-to-end size improvement.

```bash
python3 -m tests.benchmark_orientation --design output/adder4.json --output /tmp/adder_orientation.json
python3 -m tests.benchmark_orientation --design output/storage_demo.json
python3 -m tests.benchmark_orientation --design output/dlatch.json
python3 -m tests.benchmark_orientation --design output/adder4.json \
  --candidate fold_rows:2,3 --export /tmp/adder_reverse.schem
python3 -m tests.benchmark_orientation --design output/adder4.json \
  --candidate fold_rows_forward:2,3 --export /tmp/adder_fold.schem
python3 -m unittest tests.test_gate_orientation -v
```

The adder test generator supports `--namespace` for independent experimental
packs and result storage. Source power must start at the gate's actual physical
output **before** row-padding extensions; the live experiment caught and fixed
an initial prototype error that incorrectly gave those extensions fresh power.

### Routing performance and parallelism

All channel jobs are submitted together to a process pool, up to the available
CPU count. Results are collected as they finish, with per-channel dimensions,
elapsed time, and attempt counts printed immediately. Workers receive pin
coordinates, row width, and port clearance rather than complete gate blueprints.
`ic.route_channels(workers=N)` overrides the worker count; `workers=1` runs
serially. Routing output is tested for serial/parallel equivalence.

Within a channel, routing now uses:

- Cached static legality/neighborhood queries and precomputed net-spacing masks.
- Parent-linked paths with integer bitsets for local wires/supports/clearance,
  avoiding repeated full-path copies and set reconstruction.
- Best-cost checks when enqueuing states, suppressing duplicate queue entries.
- A short geometric-search probe before switching to obstacle-aware search.
- Completed-net escape release, and diagnostics stored without retaining
  failed search tracebacks and their large geometry caches.

Measured routing-only times on this machine (before: single-run baseline;
after: median of three runs):

| Workload | Before | After |
| --- | ---: | ---: |
| 15-net stress layout | 37.95 s | 1.10 s |
| Five adder channels, parallel | 18.33 s | 3.22 s |

The stress layout also shrinks from **43×7×13 to 43×7×9**. Reproduce timings
without writing schematics or modifying Minecraft:

```bash
python3 -m tests.benchmark_router --case fifteen_net_stress --repeat 3
python3 -m tests.benchmark_router --design output/adder4.json --placement legacy --repeat 3
python3 -m tests.benchmark_router --design output/adder4.json --placement legacy --workers 1 --repeat 3
```

### Routing verification

The tests cover flat connections, rising/falling stairs, both source rows,
same-row connections, mixed-height and tall fan-out, crossings, stacked pins,
long lines, obstacles, permutations, and a 15-net interlocking stress layout.
Dedicated fixtures exercise two-level stacked/perpendicular lines, a crossing
with postprocessor repeaters, and rising/falling/sloped crossings. Negative
tests reject supports that overwrite lower dust or cut a slope's throat,
including slopes in the current uncommitted path and external gate interfaces.
Invalid coordinates, conflicting pins, impossible bounds, deterministic
results, and height-aware assembly are also checked. An offline 128-block
height change verifies that the old fixed ceiling is gone.

```bash
python3 -m unittest discover -s tests -p 'test_height_router.py' -v
python3 -m unittest discover -s tests -p 'test_latch_mapping.py' -v
# Export the existing 15-net stress schematic, now with real pin heights
# and repeaters inserted by the production postprocessor:
python3 tests/test_router.py
```

For live tests, reserve the fixture area at **(-480, -60, 240)**. The generator
accepts `--origin X Y Z` to choose another location. It clears/rebuilds that
test area between fixtures and force-loads its chunks.

```bash
python3 generate_router_test.py "/path/to/world/datapacks"
```

```text
/reload
/function router_test:start
/tick sprint 25900t
/data get storage router_test:results status
/data get storage router_test:results passed
/data get storage router_test:results failed
/data get storage router_test:results failures
```

Verified in Minecraft 26.3, world `flat(1)`:

- **25 routing fixtures, 257 passed checks, 0 failures.** Each check verifies
  every routed dust/repeater and every output lamp. Multi-net fixtures include
  all input combinations up to five nets; the 15-net case includes one-hot,
  all-on, randomized inputs, and all-off transitions to detect crosstalk.
- **24-block climbs and descents**, including a tall multi-height fan-out,
  propagate correctly with postprocessor-generated repeaters.
- The rebuilt four-bit adder passes **all 256 input combinations**. Its latest
  live origin is **(-479, -60, 303)**, with output lamps at Z=361. Current
  dimensions are **41×5×59**, with 30 postprocessor-generated repeaters.
  The generated `/function adder4_test:place` optionally rebuilds the schematic
  at the exact test origin before `/function adder4_test:start`, without moving
  the player or requiring WorldEdit placement.
- The storage demo shrinks from **19×3×28 to 13×3×12** (W×H×L): footprint
  **532 → 156 blocks**, about **71% smaller**, at the original height. Compared
  to the previous placement's 13×3×22, compact placement reduces footprint 45.5%.
  This is a generated-size comparison; routing improvement depends on layout.

`manifest.json` in the generated datapack records fixture dimensions, pins,
repeater counts, origin, and test duration. `entries`/`failures` in Minecraft
storage retain the result for each input pattern. The final stress fixture
remains in the world with inputs off.

## Complex routing regression: 8-bit ALU

`alu8.v` is a combinational circuit with 18 input bits and 10 output bits:

| `op` | Operation | `result[8]` |
| --- | --- | --- |
| 0 | `a + b` | Carry-out |
| 1 | `a - b` modulo 256 | No-borrow (1 when `a >= b`) |
| 2 | `a ^ b` | 0 |
| 3 | `a & b` | 0 |

`zero` is 1 when `result[7:0]` is zero, independently of carry/no-borrow.
Addition and subtraction share an arithmetic datapath. The two control bits
fan out widely; arithmetic, bitwise selection and zero detection create many
reconverging connections. This stresses fan-out trees, crossings, multi-height
routes, long relay chains, same-row connections and repeater power restoration.

Current synthesis/placement results:

- **101 logic cells**, **258 relay feedthroughs**, 18 input and 10 output gates.
- **20 gate rows**, **19 routed channels**, **131×8×307** (W×H×L).
- **549 postprocessor-generated routing repeaters**.
- The densest channel took about **327 seconds**, while simpler channels took
  milliseconds to seconds. This is a larger stress case, not a fast benchmark.
- Synthesis exposed an XNOR mapping bug: XNOR had previously been implemented
  as XOR. It now uses the XOR primitive followed by a physical output inverter.

```bash
make TOP=alu8
WORLDEDIT_SCHEMATICS_DIR="/path/to/minecraft/config/worldedit/schematics" \
  python3 generate_schem.py output/alu8.json
python3 -m tests.generate_alu_test alu8.schem "/path/to/world/datapacks" \
  --origin -479 -60 480
python3 -m unittest tests.test_alu -v
```

The test generator first checks the mapped Boolean netlist against an
independent arithmetic/bitwise model. Its **1,328** deterministic vectors cover:

- Corner values, alternating bits, sign-bit boundaries and mode changes with
  operands held fixed.
- Walking bits and all 64 one-hot operand pairs for all four operations.
- Carry/borrow propagation of every chain length from one to eight bits.
- 512 seeded randomized vectors, evenly divided among operations.
- All-on to all-off recovery, checking stale power and cross-net leakage.

Each live check reads all nine result lamps and the zero lamp after 400 ticks.
Verified in Minecraft 26.3: **1,328 passed, 0 failed**, with all four operations
represented by 332 cases each. The mapped-netlist reference checks also pass
all 1,328 vectors, and the complete automated regression suite has 39 passing
tests.
`manifest.json` records every input, expected result, label, IO position and
test duration. Minecraft storage records the total failures and the first 32
failure details. These are selected edge/random tests, not exhaustive testing
of all 262,144 possible inputs.

The current live origin is **(-479, -60, 480)**; output lamps are at Z=786.
Large placement is split across scheduled batches to stay within the command
chain limit. Clearing is split across all three axes to respect `/fill`'s
32,768-block cap even when the floor alone is larger than that limit.

```text
/reload
/function alu8_test:place
/tick sprint 100t
/data get storage alu8_test:placement status
# Wait for placement status "complete", then:
/function alu8_test:start
/tick sprint 531400t
/data get storage alu8_test:results
```

All schematic exports, including the experimental orientation layouts, include
a continuous stone-brick base with a one-block border. Their actual support
blocks and gate-row floors are then placed on top of that base layer.

## LUT synthesis and multi-output packing

`generate_lut.py` is integrated with the compiler. Use the LUT mapping mode:

```bash
make TOP=adder4 MAPPING=lut
python3 generate_schem.py output/adder4_lut.json
make TOP=alu8 MAPPING=lut
python3 generate_schem.py output/alu8_lut.json
```

Gate-library synthesis remains available with `MAPPING=gates`. The `_lut`
suffix keeps LUT netlists and schematics separate from those gate-library
artifacts. Both exporters respect `WORLDEDIT_SCHEMATICS_DIR` and include the
stone-brick base and border.

### Physical LUT interfaces

`build_lut(inputs, outputs, data)` returns a `Gate` directly, without saving a
file or copying into Minecraft. The existing `generate_lut(...)` wrapper still
exports a standalone schematic and now also returns the gate.

- Zero through **four inputs**, one through **eight outputs**.
- Exactly `2**inputs` integer table entries, each containing the output bits.
- Input bit `j` contributes `2**j` to the address; output bit `m` is bit `m` of
  `data[address]`. Yosys truth tables use the same little-endian convention.
- Named input pins `I0…` at **(2*j+1, Y=5)** on the front face.
- Named output pins `O0…` at **(2*m, Y=1)** on the back face.
- The existing decoder/encoder geometry and reversed physical row indexing are
  preserved. Boundary repeaters restore address and output power for composition
  with routed channels. These are internal gate components; the router still
  generates only dust/supports and routing repeaters remain in the postprocessor.

### Space-aware mapping

Synthesis uses `synth -noabc` followed by `abc -luts 24,60,144,340`. Unlike the
uniform cost of an FPGA LUT, these costs model the one-output physical LUT's
allocated footprint, including the gate-row gap. Decoder depth grows
exponentially with input count, so using four-input LUTs everywhere can waste
space. `LUT_COSTS` can override the four costs.

`lut_mapping.py` then greedily packs compatible LUTs into a shared decoder with
multiple output columns. It can combine shared-address functions and adjacent
cones, subject to four external inputs/eight live outputs and a reduction in
allocated macro footprint. Internal-only signals disappear; externally read
signals and primary outputs remain. A cut with a dependency through an
unabsorbed cell is rejected to avoid introducing a combinational cycle.
Constants and repeated address signals are folded exactly. Unknown truth-table
bits are rejected. Literal 0/1 rails have explicit zero-input LUT drivers.

Packing happens automatically when `parse_yosys_json()` reads a LUT netlist;
the saved Yosys JSON retains its normal single-output `$lut` cells. For debugging,
`parse_yosys_json(path, pack_luts=False)` disables multi-output packing. Physical
pin roles follow signals rather than placement order. Relay chains are shared
per output signal, keeping different output columns electrically separate.
Storage is not absorbed into truth tables; positive D latches and explicit SR/T
primitives remain supported in LUT synthesis mode.

### Measured size improvements

| Design | Gate-library layout | LUT layout | W×L reduction | Routing repeaters |
| --- | ---: | ---: | ---: | ---: |
| Four-bit adder | 41×5×59 | **30×6×46** | **43.0%** | 30 → 10 |
| Eight-bit ALU | 131×8×307 | **81×8×290** | **41.6%** | 549 → 349 |

The default area-costed adder maps 11 single-output LUTs into **3 macros**,
with 2 relays instead of 15. The ALU maps 56 LUTs into **35 macros**, with 79
relays instead of 258, and 8 routing channels instead of 19. Its slowest channel
in the measured generation took about **29 seconds**, versus 327 seconds in the
gate-library layout (single runs, not benchmark medians).

An initial uniform four-input mapping produced a **95×8×312** ALU, also passing
all 1,328 live tests. The physical-area costs improve on that result. A separate
three-input-only experiment produced **100×8×248**, larger in footprint than
the default area-costed mapping. These are bounded heuristic choices rather
than guarantees of globally minimum size.

### Verification and live fixtures

```bash
python3 -m unittest tests.test_lut_integration -v
python3 -m tests.generate_lut_test "/path/to/world/datapacks" --origin -620 -60 390
python3 -m tests.generate_adder_test adder4_lut.schem "/path/to/world/datapacks" \
  --origin -620 -60 303 --namespace adder_lut
python3 -m tests.generate_alu_test alu8_lut.schem "/path/to/world/datapacks" \
  --origin -870 -60 480 --netlist output/alu8_lut.json --namespace alu_lut_area
```

The primitive test checks all addresses forwards and backwards for each input
width 0–4, always with eight output columns: **62 passed, 0 failed**. It includes
the original two-input/eight-output `[0,255,128,64]` table. The current LUT adder
also passes **all 256 combinations**. Packed adder and ALU truth tables are
independently checked against the arithmetic models before layer/relay mutation.
The final area-costed ALU passes **1,328 live checks, 0 failures**, reading all
nine result bits and the zero flag. The combined automated regression suite
passes **51 tests**.
Regression tests cover bit order, aliases/constants, live-output preservation,
cycle-safe cuts, invalid interfaces and storage boundaries.

World locations:

- Primitive fixture: **(-620, -60, 390)**, storage `lut_test:results`.
- LUT adder: **(-620, -60, 303)**, output Z=348, storage `adder_lut:results`.
- Current area-costed LUT ALU: **(-870, -60, 480)**, output Z=769,
  storage `alu_lut_area:results`.
- Earlier uniform-cost LUT ALU: **(-750, -60, 480)**, output Z=791,
  storage `alu_lut:results`. Its earlier schematic has been superseded by the
  area-costed `alu8_lut.schem`; its independent datapack retains that fixture.

After generating packs, `/reload`, run the appropriate `:place` function before
`:start`. The ALU's batched placement must report `"complete"` first. Sprint
5,160 ticks for `lut_test`, 26,000 for `adder_lut`, or 531,400 for `alu_lut_area`,
then read that namespace's `:results` storage.

## Repeater placement: baseline, optimization, and stress tests

`repeater_postprocessor.py` retains the starting implementation as
`build_graph_baseline()`. Production generation calls the optimized
`build_graph()`. Both operate on identical routed geometry and preserve
repeaters that already belong to gate blueprints.

### How placement works

The baseline constructs electrical reachability from each source, propagates
power, finds the first unpowered node, and follows its BFS parents back toward
the source. It replaces the latest powered, eligible straight wire with a
directional repeater, then recomputes power and repeats. It finally checks that
every node originally reachable from each source is still powered from that
source individually. `get_score()` is an older helper; this placement path does
not use its sum-of-powers score.

The baseline at the start of this comparison required positive **dust power at
the placement site**, rather than a hardcoded strength-2 threshold. This misses
a useful boundary: a repeater can read adjacent dust at strength **1**, even if
dust replacing the repeater itself would have strength **0**. It also processes
forks incrementally, so it can place separate repeaters on both arms instead of
sharing one before the fork.

The new implementation uses dynamic programming on independent tree-shaped
nets. Each node has 16 states: the power that dust would have there, 0–15.
For each state it compares keeping dust against placing a legal repeater:

- Dust must have positive power and passes `power - 1` to each child.
- A new repeater costs one placement and passes power 15 to its children.
  State zero is allowed because the preceding dust can still have power one.
- Existing gate repeaters restore power without adding to the placement cost.
- The costs of all child branches are considered together. Reconstruction
  chooses the minimum-count placement, including shared restoration at forks.

This is minimum-count placement **for an independent electrical tree with the
existing legal sites and fixed gate repeaters**. Tree optimization uses 16
states per node; power and safety validation are additional work. Sources,
corners, branches, slopes, and sites next to fixed repeaters remain protected
by the placement rules. Minecraft repeater `facing` points toward its input,
opposite the direction of signal travel.

Cycles and shared-source networks need additional handling. Cyclic nets compare
a spanning-tree DP against the original greedy solution and keep the smaller
safe result. Shared-source nets start with the baseline. A removal pass accepts
an insertion's deletion only if every affected original source still powers
its full original network and no remaining inserted repeater sustains feedback.
These cases are heuristic, rather than a global optimality guarantee.

Feedback detection energizes one inserted repeater with external sources absent
and checks whether its output can power its own input. This respects attenuation:
a long dust return path that decays to zero is safe. A short boosted feedback
loop can latch on and must be avoided even when its source-on test passes.

### Measured repeater counts

Counts below are **added postprocessor repeaters**, excluding immutable gate
repeaters. Geometry and synthesis inputs are identical between both algorithms.
Full per-fixture placements, input hashes, and three-run median timings are in
`tests/repeater_results.json`.

| Circuit | Baseline | Optimized | Reduction |
| --- | ---: | ---: | ---: |
| Synthetic suite, 35 common buildable fixtures | 98 | **80** | **18.4%** |
| Shared-trunk comb (included above) | 12 | **4** | **66.7%** |
| Four-bit gate-library adder | 30 | **29** | **3.3%** |
| Four-bit LUT adder | 10 | 10 | 0% |
| Eight-bit LUT ALU | 349 | **327** | **6.3%** |
| Existing 25 router fixtures, combined | 24 | 24 | 0% |
| D latch / storage demo | 0 / 0 | 0 / 0 | 0% |

The ALU also contains 631 fixed gate repeaters, so its **physical total changes
from 980 to 958**. The gate-library adder's total changes from 60 to 59. The
synthetic comparison excludes the new zero-power staircase landing: the
baseline cannot restore it, while the optimized implementation uses one repeater.
The two deliberately impossible fixtures are rejected by both algorithms.

### Edge cases and live validation

`tests/repeater_stress.py` constructs exact decay boundaries, multi-fork trees,
sparse corner landings, uphill/downhill paths, a uniquely usable zero-power
landing, Y+2 crossings, fixed repeater chains, dust loops, overlapping sources,
and impossible unlanded staircases. The baseline and optimized variants of these
and the existing routing fixtures are shelf-packed into **121 independent live
circuits** and driven concurrently. Every routed wire/repeater is checked, with
ON/OFF recovery and independent-net isolation patterns.

The automated tests include exhaustive smaller-placement searches, straight-line
lower bounds across source powers 1–15, source isolation, immutable gate
repeaters, and both short unsafe and long decaying feedback paths.

Verified in Minecraft 26.3:

- Optimized stress/router variants: **445 passed, 0 failed**.
- Baseline variants: **434 passed, 6 failed**, all six failures being switch-off
  checks in three small feedback-loop fixtures. The optimized versions recover.
- Optimized gate-library adder and LUT adder: **256/256 each**.
- Optimized LUT ALU, four copies with 332 cases each: **1,328/1,328**.
- Python regression suite: **65 tests passed**.

That is **2,285 successful optimized live checks**. The final stress sprint took
about 31 seconds (4,400 ticks at 142 ticks/s); an earlier run while viewed from
elsewhere reached 2,196 ticks/s. The full parallel ALU/adder sprint took about
317 seconds (133,000 ticks at 419 ticks/s). These are observed world/client
measurements, not fixed runtime guarantees. `tests/repeater_live_results.json`
records the final results, world positions, and test settings.

Reproduce the comparison without repeating synthesis:

```bash
python3 -m unittest discover -s tests
python3 -m tests.benchmark_repeaters --rebuild --router \
  --design output/adder4.json --design output/adder4_lut.json \
  --design output/alu8_lut.json --design output/dlatch.json \
  --design output/storage_demo.json --repeat 3
python3 -m tests.generate_repeater_test "/path/to/world/datapacks"
```

The benchmark saves raw geometry in `output/repeater_corpus.json.gz` and reuses
cached routing. Later `python3 -m tests.benchmark_repeaters` runs only the two
postprocessors on that frozen corpus. The live generator defaults to the test
region around **(-1250, -60, 200)**; use `--origin` for a different empty region.

```text
/reload
/function rpt_stress:place
/data get storage rpt_stress:results placement
# Wait for "complete", then:
/function rpt_stress:start
/tick sprint 4400t
/data get storage rpt_stress:results
```

The suite uses 4,284 scheduled ticks, including an 84-tick conservative settling
interval derived from its repeater counts. `/function rpt_stress:stop` cancels
checks and releases owned force-load flags. Finishing also releases them while
preserving flags that existed before the test. Results must have
`status: "complete"` before interpreting their final counters.

After tests finish, `/function rpt_stress:audit` checks placement without
rebuilding or changing circuit blocks. Read `/data get storage rpt_stress:audit`
after it completes. The verified field had **11,372 expected blocks, zero missing
or wrong blocks, and zero unloaded checks**. This checks supports, component
types, and repeater facing while ignoring transient power/connection states.
Rebuilding an older field can leave dropped dust/repeater items because clearing
its supports makes the old components pop off before replacement.

For larger circuits, `tests.generate_alu_test --shard INDEX COUNT` partitions
the reference vectors into contiguous ranges for independent physical copies.
For example, `--shard 0 4` tests the first 332 cases. Give all four copies
different origins and namespaces. Their combined 1,328 cases retain the
400-tick settling interval while taking 132,800 scheduled ticks concurrently.
Contiguous ranges preserve mode switching that a stride of four would lose.
Minecraft's server still performs all copies' redstone updates, so reducing
scheduled ticks does not imply a proportional wall-time speedup.

## Hybrid LUT / native-gate mapping

Hybrid mapping compares native Minecraft gates with shared LUT implementations:

```bash
make TOP=alu8 MAPPING=hybrid
python3 generate_schem.py output/alu8_hybrid.json
```

This writes `output/alu8_hybrid.json` and `alu8_hybrid.schem`. Existing
`MAPPING=gates` and `MAPPING=lut` remain available. Hybrid selection is frozen
in the generated JSON, including its cost/placement scores; parsing that file
does not silently repack it using the pure-LUT rules.

### Choosing gates without losing shared decoders

`pack_lut_cells(module, hybrid=True)` extends the original packer:

- Match truth tables to physical NOT, AND/NAND, OR/NOR, XOR/XNOR and mux gates.
  Remove irrelevant inputs before matching, retaining exact signal identities.
- Consider AND/NAND minterms with selected input polarities. Their negative
  literal pins use input repeaters at Y=1, bypassing the ordinary input torch.
  Those repeaters isolate each input from the shared internal bus; using dust
  there would backfeed other nets. Named, height-aware pins retain each role.
- For each prospective cone, use output-subset dynamic programming to choose
  between dedicated gates, a shared LUT, and extracting some cheap outputs while
  keeping the others together. Up to eight outputs make this bounded search
  practical.
- Compare those costs **before each merge**, not only after pure-LUT packing.
  A merge is accepted only for positive estimated savings and a cycle-safe cut.
  Storage and external live outputs remain intact.

Native costs come from the gate blueprints' allocated width and depth. LUT
costs include decoder/encoder dimensions. These are heuristic physical costs,
not a global optimum: row padding, relay chains and routing can outweigh a
local cell-area saving.

### Comparing ABC cuts cheaply

The default hybrid build saves the pre-ABC design once, then maps it with both
four-input costs (`24,60,144,340`) and three-input costs (`24,60,144`). The packer
scores both hybrid results using actual gate placement, row depths and relay
insertion, plus minimum-length routing channels. It selects the smaller proxy
footprint before performing any routing searches.

For this ALU the three-input cut map wins; for the adder the four-input map
wins. This avoids making the adder larger just to use the ALU's preferred cut
size. Only the selected design needs full routing. The layout proxy is an
estimate; measured routed footprint is still the final metric.

Overrides:

```bash
# Use a single four-input cut map, with no comparison candidate:
make TOP=alu8 MAPPING=hybrid HYBRID_COMPARE_COSTS=
# Force a single three-input cut map:
make TOP=alu8 MAPPING=hybrid LUT_COSTS=24,60,144 HYBRID_COMPARE_COSTS=
# Increase the native-gate penalty in the local cost model:
make TOP=alu8 MAPPING=hybrid HYBRID_GATE_SCALE=2
```

An existing LUT JSON can also be mapped without rerunning synthesis:

```bash
python3 -m lut_mapping output/alu8_lut.json --hybrid \
  --output output/alu8_hybrid_manual.json
```

`--candidate another_lut_netlist.json` adds another cut map to the cheap layout
comparison. The two inputs must describe the same design. The Python parser
also supports `parse_yosys_json(path, hybrid_luts=True)` for experiments on a
raw LUT netlist.

### Measured results

| Circuit | Pure LUT layout | Selected hybrid layout | Footprint change |
| --- | ---: | ---: | ---: |
| Eight-bit ALU | 81×8×290 | **81×8×266** | **−8.3%** |
| Four-bit adder | 30×6×46 | **30×6×46** | unchanged |

The hybrid ALU contains **27 LUT macros + 20 native gates**: 11 mixed-polarity
minterms, 4 NORs, 4 ORs and one AND. Its footprint is 21,546 blocks versus
23,490 for the pure-LUT baseline. It has more layers/relays, but substantially
shorter gate rows.

| ALU repeater category | Pure LUT | Hybrid |
| --- | ---: | ---: |
| Fixed gate repeaters | 631 | **443** |
| Added routing repeaters | **327** | 346 |
| Physical total | 958 | **789** |

Thus the footprint improvement also saves **169 physical repeaters (17.6%)**,
despite requiring 19 additional routing repeaters. The adder deliberately keeps
three shared LUT macros rather than forcing native substitutions.

### Verification and performance

`tests/test_hybrid_mapping.py` checks truth tables, input-polarity patterns,
all mux role permutations, partially extracted output groups, shared decoders,
storage boundaries, source immutability and frozen mappings. It also checks
that multi-output sources driving several primitive inputs produce the correct
physical input count, and that negative-literal inputs cannot backfeed each other.

`tests/benchmark_hybrid.py` emits an independent combinational Verilog model
and uses Yosys `equiv_simple` / `equiv_status -assert` against the original RTL.
Both the selected ALU and adder are formally equivalent for **all inputs**.
Proof logs are `output/alu8_hybrid.equiv.log` and
`output/adder4_hybrid.equiv.log`. This model check complements Minecraft testing
of the physical blueprints and routing.

```bash
python3 -m unittest discover -s tests
python3 -m tests.benchmark_hybrid --formal-source alu8.v --route-best 2
python3 -m tests.generate_hybrid_primitives "/path/to/world/datapacks"
```

The primitive pack runs **76 independent circuits** concurrently, checking
addresses forwards and backwards: **2,432 passed, zero failed**. It tests all
two- through four-input minterm patterns and both polarities, plus the standard
native gates. It exposed reversed A/B pin labels in the existing mux blueprint;
the labels were corrected and the exhaustive test rerun successfully.

The selected full ALU passes **1,328/1,328 live vectors**, partitioned across
four independent copies with the original 400-tick settling allowance. The
selected adder passes **256/256**. Combined with the primitive matrix, this is
**4,016 successful live checks**. The Python regression suite passes **75 tests**.
Measurements and exact test locations/settings are in `tests/hybrid_results.json`.

One measured ALU synthesis, both ABC cut maps, packing and cheap layout selection
took about **5 seconds**. First-time routing took **43 seconds**; subsequent
generation reuses cached channels. The full ALU/adder sprint took about **387
seconds** in the observed world/client state. Parallel copies reduce scheduled
ticks, but all redstone updates still share the server thread.

Run `/function hybrid_prims:place`, then `hybrid_prims:start`, sprint 1,000 ticks,
and read `hybrid_prims:results`. Its cleanup removes fragile components before
their supports on rebuild, avoiding the dropped-item debris of support-first
clearing. Owned force-load flags are released on completion.

World locations for the selected hybrid builds:

- Primitive matrix: **(-1390, -60, 200)**, storage `hybrid_prims:results`.
- ALU copies: **(-1530, -60, 600)**, **(-1420, -60, 600)**,
  **(-1530, -60, 920)** and **(-1420, -60, 920)**,
  storage `hyb_alu0:results` through `hyb_alu3:results`.
- Adder: **(-1300, -60, 600)**, storage `hyb_adder:results`.

## Performance Optimization: Carry Cancel Adder (CCA)

For high-speed arithmetic, use the provided `adder32_cca.v`. This implementation uses a Carry Cancel architecture that maps directly to the multiplexer primitives in the custom library, allowing for "instant-carry" redstone behavior across large bit-widths.

## Acknowledgments

- **Yosys** for the synthesis engine.
- **mcschematic** for the Minecraft integration.
- The Redstone engineering community for high-speed gate designs.
