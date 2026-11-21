"""Siglent SDS802X HD oscilloscope: 2 channels, 70 MHz, 2 GSa/s, 12 bit (the scope at 192.168.1.75).

    from instruments.siglent_sds802xhd import SIGLENT_SDS802XHD

    scope = SIGLENT_SDS802XHD("192.168.1.75")   # host, port=5025, timeout=5.0
    scope.checkModel()                          # InstrumentError if another model answers at this address

All functions are in instruments/siglent_sds.py (the common SDS800X HD driver), see help/testing/siglent-sds.md.
"""
if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.siglent_sds import SiglentSDS  # noqa: E402


class SIGLENT_SDS802XHD(SiglentSDS):
    MODEL = "SDS802X HD"
    CHANNELS = 2


if __name__ == "__main__":                             # read-only check: python3 instruments/siglent_sds802xhd.py [ip]
    import sys
    s = SIGLENT_SDS802XHD(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.75")
    print(s.checkModel(), s.idn().split(",")[-1])
    print("CH1:", s.getCoupling(1), s.getScale(1), "V/div, probe", s.getProbe(1), " timebase:", s.getTimebase())
    print("errors:", s.errors() or "none")
