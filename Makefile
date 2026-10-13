# Variables
LIB_FILE = my_gates.lib
OUT_DIR = output

# Default top module
TOP = multiplexer4_1
MAPPING ?= gates
LUT_COSTS ?= 24,60,144,340
ifeq ($(MAPPING),lut)
MAP_COMMAND = abc -luts $(LUT_COSTS)
SYNTH_OPTIONS = -noabc
SUFFIX = _lut
else ifeq ($(MAPPING),gates)
MAP_COMMAND = abc -liberty $(LIB_FILE)
else
$(error MAPPING must be gates or lut)
endif

# Files
# Search in current dir or tests/
VERILOG_FILE = $(shell find . -name "$(TOP).v")
OUTPUT_JSON = $(OUT_DIR)/$(TOP)$(SUFFIX).json
OUTPUT_PREFIX = $(OUT_DIR)/$(TOP)$(SUFFIX)

# Default target
all: prep synth

# Ensure output directory exists
prep:
	mkdir -p $(OUT_DIR)

# Unified Synthesis Pipeline
# - flatten: Inlines any submodules into the top module so we have one graph.
# - abc -liberty: Maps combinational logic securely to our specific Minecraft gates.
synth: prep $(VERILOG_FILE)
	yosys -p "read_verilog -lib storage_cells.v; read_verilog $(VERILOG_FILE); \
	          hierarchy -check -top $(TOP); \
	          flatten; \
	          proc; opt; \
	          synth -top $(TOP) $(SYNTH_OPTIONS); \
	          $(MAP_COMMAND); \
	          opt; clean; \
	          json -o $(OUTPUT_JSON)"

# Visualization
viz: synth
	yosys -p "read_liberty -lib $(LIB_FILE); \
	          read_json $(OUTPUT_JSON); \
	          splitnets -ports; \
	          show -format dot -prefix $(OUTPUT_PREFIX)"
	# Add labels to wires in the DOT file using the node names
	sed -i 's/\(n[0-9]\+\):e -> \(.*\)label=""/\1:e -> \2label="\1"/g' $(OUTPUT_PREFIX).dot
	dot -Tsvg $(OUTPUT_PREFIX).dot -o $(OUTPUT_PREFIX).svg
	@echo "Generated $(OUTPUT_PREFIX).svg with labels"

# Clean target
clean:
	rm -rf $(OUT_DIR)
	rm -f abc.history
