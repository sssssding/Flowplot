"""Small in-process capability registry; adding a module adds one registration."""
from . import flow, heat, thermal_coupling

MODULES = {"LaminarFlow": flow, "HeatTransferInFluids": heat,
           "HeatTransfer": heat}
COUPLING_MODULES = {"NonIsothermalFlow": thermal_coupling}
