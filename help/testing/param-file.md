# Parameter files — values by key

Driver `testPlatform/instruments/param_file.py`: create a file, write a parameter, read it back by key —
calibration values of a station, counters, settings, the last serial number. Format by extension: `.json`, or
`key = value` lines for anything else (comments `#` / `;` are kept). Values come back typed: int, float, bool,
None, str. Every write is atomic (temporary file + rename), so a power loss never leaves a broken file.

Relative paths are relative to `testPlatform/`; `data_path()` puts files into `testPlatform/data/` (station
data, not in git). See [Instruments](instruments.md).

## Parameters

```python
from instruments.param_file import ParamFile, data_path

cal = ParamFile(data_path("calibration.ini"))   # testPlatform/data/calibration.ini
cal.create({"offset": 0.0, "gain": 1.0})        # only if the file does not exist (True if written)
cal.create({"offset": 0.0}, overwrite=True)     # start again
cal.exists()                                    # True / False
cal.get("gain", 1.0)                            # value, or the default when missing
cal.has("offset")                               # True / False
cal.set("offset", 0.012)                        # one key, written at once
cal.setMany({"gain": 1.003, "date": "2026-11-11"})   # several keys, one write
cal.delete("date")                              # True if it was there
cal.increment("boards_tested")                  # counter + 1, returns the new value
cal.increment("energy_wh", 2.5)                 # any step
cal.keys()                                      # ["offset", "gain", …]
cal.all()                                       # {"offset": 0.012, "gain": 1.003, …}
```

```python
cal = ParamFile(data_path("calibration.ini"))
v = dmm.getVoltDC() * cal.get("gain", 1.0) + cal.get("offset", 0.0)
ts.numericLimitTest("Rail 5V (calibrated)", v, 4.95, 5.05, "V")
```

## Text files

```python
log = ParamFile(data_path("results.csv"))
log.appendLine("serial,vout,result")            # add a line
log.appendLine(f"{ts.serial},{v:.3f},PASS")
log.readText()                                  # whole file as text ('' if missing)
log.writeText("replaced content\n")             # replace the file
```
