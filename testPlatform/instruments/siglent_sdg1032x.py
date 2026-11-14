"""Siglent SDG1032X function / arbitrary waveform generator: 2 channels, 30 MHz, LAN (raw SCPI :5025).

    from instruments.siglent_sdg1032x import SIGLENT_SDG1032X

    gen = SIGLENT_SDG1032X("192.168.1.73")         # host, port=5025, timeout=3.0
    gen.checkModel()                               # InstrumentError if another model answers at this address
    gen.sine(1, 1000, 2.0)

All functions are in instruments/siglent_sdg.py (the common SDG driver), see help/testing/siglent-sdg.md.
"""
if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.siglent_sdg import SiglentSDG  # noqa: E402


class SIGLENT_SDG1032X(SiglentSDG):
    MODEL = "SDG1032X"
    CHANNELS = 2
    F_MAX = 30e6


if __name__ == "__main__":                             # read-only check: python3 instruments/siglent_sdg1032x.py [ip]
    import sys
    g = SIGLENT_SDG1032X(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.73")
    print(g.checkModel(), g.idn().split(",")[-1])
    for c in (1, 2):
        b = g.getBasic(c)
        print(f"CH{c}: {g.outputState(c)}  {b.get('WVTP')} {b.get('FRQ')} Hz {b.get('AMP')} Vpp offset {b.get('OFST')} V"
              f"  mode: {g.getMode(c) or 'basic'}")
    print("arb waves:", len(g.arbList()), " errors:", g.errors() or "none")
