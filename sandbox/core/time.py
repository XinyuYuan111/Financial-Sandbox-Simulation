"""Simulation time constants shared by the runtime and planning contracts."""

# The UI intentionally relabels each simulation-second tick as one simulation
# minute. Keep the stored clock in microseconds and preserve its numeric value.
SIMULATION_PLAN_HORIZON_US = 30 * 1_000_000

# One stored 1,000,000us tick is displayed as one simulation minute. Autonomous
# runs pace that tick at one wall-clock second.
SIMULATION_WALL_SECONDS_PER_MINUTE = 1.0
