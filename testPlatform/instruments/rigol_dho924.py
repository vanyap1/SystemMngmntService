"""Rigol DHO924 oscilloscope: 4 channels, 250 MHz, 1.25 GSa/s (the scope at 192.168.1.146).

    from instruments.rigol_dho924 import RIGOL_DHO924

    scope = RIGOL_DHO924("192.168.1.146")       # host, port=5555, timeout=5.0
    scope.checkModel()                          # InstrumentError if another model answers at this address

All functions are in instruments/rigol_dho.py (the common DHO800 / DHO900 driver), see help/testing/rigol-dho.md.
"""
if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.rigol_dho import RigolScope  # noqa: E402


class RIGOL_DHO924(RigolScope):
    MODEL = "DHO924"


if __name__ == "__main__":                             # read-only check: python3 instruments/rigol_dho924.py [ip]
    import sys
    s = RIGOL_DHO924(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.146")
    print(s.checkModel(), "CH1 Vpp:", s.getVoltPkPk(1), "f:", s.getFrequency(1))
