"""Siglent SDL1020X DC electronic load: 150 V / 30 A / 200 W, LAN (raw SCPI :5025).

    from instruments.siglent_sdl1020x import SIGLENT_SDL1020X

    load = SIGLENT_SDL1020X("192.168.1.72")        # host, port=5025, timeout=3.0
    load.checkModel()                              # InstrumentError if another model answers at this address
    load.setup("CC", 0.5)

All functions are in instruments/siglent_sdl.py (the common SDL1000X driver), see help/testing/siglent-sdl.md.
"""
if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.siglent_sdl import SiglentSDL  # noqa: E402


class SIGLENT_SDL1020X(SiglentSDL):
    MODEL = "SDL1020X"
    V_MAX = 150.0
    I_MAX = 30.0
    P_MAX = 200.0


if __name__ == "__main__":                             # read-only check: python3 instruments/siglent_sdl1020x.py [ip]
    import sys
    ld = SIGLENT_SDL1020X(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.72")
    print(ld.checkModel(), ld.idn().split(",")[-1])
    print("input:", ld.isOn(), " mode:", ld.getMode(), ld.getLevel(), " protection:", ld.protection())
    print("V, A, W:", ld.measureAll(), " errors:", ld.errors() or "none")
