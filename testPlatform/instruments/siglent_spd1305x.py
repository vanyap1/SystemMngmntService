"""Siglent SPD1305X programmable power supply: 1 channel, 30 V / 5 A, LAN (raw SCPI :5025).

    from instruments.siglent_spd1305x import SIGLENT_SPD1305X

    psu = SIGLENT_SPD1305X("192.168.1.74")         # host, port=5025, timeout=3.0
    psu.checkModel()                               # InstrumentError if another model answers at this address
    psu.setup(12.0, 0.5)

All functions are in instruments/siglent_spd.py (the common SPD1000X driver), see help/testing/siglent-spd.md.
"""
if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.siglent_spd import SiglentSPD  # noqa: E402


class SIGLENT_SPD1305X(SiglentSPD):
    MODEL = "SPD1305X"
    V_MAX = 30.0
    I_MAX = 5.0


if __name__ == "__main__":                             # read-only check: python3 instruments/siglent_spd1305x.py [ip]
    import sys
    p = SIGLENT_SPD1305X(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.74")
    print(p.checkModel(), p.version(), "  setpoints:", p.getSetVoltage(), "V", p.getSetCurrent(), "A")
    print("status:", p.status(), "  V, A, W:", p.measureAll())
    print("network:", p.network(), "  errors:", p.errors() or "none")
