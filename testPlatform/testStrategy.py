

import json
import os
import sys

# Set by the web test runner (SystemMngmntService): results are also emitted
# as machine-readable "@@RESULT {json}" lines.
_RUNNER_MODE = os.environ.get("TEST_RUNNER") == "1"
# Stop on fail: web runner checkbox (TEST_STOP_ON_FAIL=1) or "--stop-on-fail" in a terminal.
# Only applies inside TestStrategy.run(); scripts that don't use run() are unaffected.
_STOP_ON_FAIL = os.environ.get("TEST_STOP_ON_FAIL", "1" if "--stop-on-fail" in sys.argv else "0") == "1"
# Operator answers arrive on this file descriptor as "{"id": n, "value": ...}" lines.
_ANSWER_FD = os.environ.get("TEST_RUNNER_ANSWER_FD")

# ANSI color codes (text only, SSH-safe)
_GREEN  = "\033[32m"
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_CYAN   = "\033[36m"
_RESET  = "\033[0m"

_NAME_W  = 40   # test name column width
_COND_W  = 24   # condition / value column width
_UNIT_W  = 8    # units column width


def _status_tag(status: str) -> str:
    if status == "PASS":
        return f"{_GREEN}[PASS]{_RESET}"
    if status == "FAIL":
        return f"{_RED}[FAIL]{_RESET}"
    if status == "ERROR":
        return f"{_YELLOW}[ERROR]{_RESET}"
    if status == "INFO":
        return f"{_CYAN}[INFO]{_RESET}"
    return f"[{status}]"


class StopOnFail(Exception):
    """Raised by a failing step inside TestStrategy.run() when stop-on-fail is enabled."""
    def __init__(self, step: str):
        super().__init__(step)
        self.step = step


_sequence_active = False   # True while the steps of TestStrategy.run() execute


def _print_result(name: str, condition: str, units: str, status: str) -> None:
    if _RUNNER_MODE:
        record = {"name": name, "condition": condition, "units": units, "status": status}
        print("@@RESULT " + json.dumps(record, ensure_ascii=False), flush=True)
    else:
        name_col = name[:_NAME_W].ljust(_NAME_W)
        cond_col = condition[:_COND_W].ljust(_COND_W)
        unit_col = units[:_UNIT_W].ljust(_UNIT_W)
        print(f"{name_col}  {cond_col}  {unit_col}  {_status_tag(status)}")
    if status in ("FAIL", "ERROR") and _sequence_active and _STOP_ON_FAIL:
        raise StopOnFail(name)


def _print_section(title: str) -> None:
    """Separator row in the results (e.g. "Finalization")."""
    if _RUNNER_MODE:
        record = {"name": title, "condition": "", "units": "", "status": "SECTION"}
        print("@@RESULT " + json.dumps(record, ensure_ascii=False), flush=True)
    else:
        print(f"{_CYAN}{'-' * 20} {title} {'-' * 20}{_RESET}")


# ---------------------------------------------------------------------- #
#  Operator prompts
# ---------------------------------------------------------------------- #
_answers = None
_prompt_seq = 0


def _ask_runner(kind: str, name: str, message: str, **extra):
    """Send "@@PROMPT {json}" to the web runner and block until the operator answers."""
    global _answers, _prompt_seq
    _prompt_seq += 1
    record = {"id": _prompt_seq, "type": kind, "name": name, "message": message}
    record.update({k: v for k, v in extra.items() if v is not None})
    print("@@PROMPT " + json.dumps(record, ensure_ascii=False), flush=True)
    if _answers is None:
        _answers = os.fdopen(int(_ANSWER_FD), "r", encoding="utf-8")
    while True:
        line = _answers.readline()
        if not line:
            raise EOFError("test runner closed the operator answer channel")
        answer = json.loads(line)
        if answer.get("id") == _prompt_seq:
            return answer.get("value")


def _ask_console(kind: str, message: str, options=None, lo=None, hi=None, default=None):
    """Console fallback (SSH use): ask with input() until the answer is valid."""
    while True:
        if kind in ("choice", "buttons"):
            for i, opt in enumerate(options, 1):
                print(f"  {i}) {opt}")
            raw = input(f"{message} [1-{len(options)}]: ").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1]
            if raw in options:
                return raw
        elif kind == "number":
            raw = input(f"{message}{f' [{default}]' if default is not None else ''}: ").strip()
            if not raw and default is not None:
                return float(default)
            try:
                value = float(raw)
            except ValueError:
                print("  Enter a number")
                continue
            if (lo is None or value >= lo) and (hi is None or value <= hi):
                return value
            print(f"  Allowed range: {lo} .. {hi}")
        else:
            raw = input(f"{message}{f' [{default}]' if default else ''}: ").strip()
            if raw or default:
                return raw or default


def _arg_value(flag: str) -> str:
    """Value of a command line option: "--sn VALUE" or "--sn=VALUE"; '' if absent."""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == flag:
            return args[i + 1] if i + 1 < len(args) else ""
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return ""


class TestStrategy:

    @property
    def stopOnFail(self) -> bool:
        return _STOP_ON_FAIL

    # ------------------------------------------------------------------ #
    #  Sequence with finalization:
    #      ts.run(steps, finalize)
    #  `steps` runs the test steps; with stop-on-fail the first FAIL/ERROR
    #  skips the remaining steps. `finalize` (cleanup: power off, relays...)
    #  always runs afterwards - also after an exception or Stop (Ctrl+C) -
    #  and is never interrupted by stop-on-fail. Returns True if all steps ran.
    # ------------------------------------------------------------------ #
    def run(self, steps, finalize=None) -> bool:
        global _sequence_active
        completed = False
        _sequence_active = True
        try:
            steps()
            completed = True
        except StopOnFail as e:
            _sequence_active = False
            _print_section(f"Stop on fail: '{e.step}' failed, remaining steps skipped")
        finally:
            _sequence_active = False
            if finalize:
                _print_section("Finalization")
                finalize()
        return completed

    def section(self, title: str) -> None:
        """Visual separator between groups of steps."""
        _print_section(title)

    @property
    def serial(self) -> str:
        """Serial number of the unit under test (web runner field or "--sn" option), '' if not given."""
        return _arg_value("--sn")


    # ------------------------------------------------------------------ #
    #  Numeric limit:  lo < val < hi
    # ------------------------------------------------------------------ #
    def numericLimitTest(self, name: str, value, lo, hi, units: str = "") -> bool:
        try:
            v = float(value)
        except (TypeError, ValueError):
            _print_result(name, f"ERR: cannot convert '{value}'", units, "ERROR")
            return False

        condition = f"{lo} < {v} < {hi}"
        if lo < v < hi:
            _print_result(name, condition, units, "PASS")
            return True
        else:
            _print_result(name, condition, units, "FAIL")
            return False

    # ------------------------------------------------------------------ #
    #  Numeric limit (inclusive):  lo <= val <= hi
    # ------------------------------------------------------------------ #
    def numericLimitTestInclusive(self, name: str, value, lo, hi, units: str = "") -> bool:
        try:
            v = float(value)
        except (TypeError, ValueError):
            _print_result(name, f"ERR: cannot convert '{value}'", units, "ERROR")
            return False

        condition = f"{lo} <= {v} <= {hi}"
        if lo <= v <= hi:
            _print_result(name, condition, units, "PASS")
            return True
        else:
            _print_result(name, condition, units, "FAIL")
            return False

    # ------------------------------------------------------------------ #
    #  String match
    # ------------------------------------------------------------------ #
    def stringMatchTest(self, name: str, value: str, expected: str) -> bool:
        condition = f"'{value}' == '{expected}'"
        if value == expected:
            _print_result(name, condition, "", "PASS")
            return True
        else:
            _print_result(name, condition, "", "FAIL")
            return False

    # ------------------------------------------------------------------ #
    #  Boolean / presence check
    # ------------------------------------------------------------------ #
    def booleanTest(self, name: str, value: bool, expected: bool = True) -> bool:
        condition = f"{value} == {expected}"
        if value == expected:
            _print_result(name, condition, "", "PASS")
            return True
        else:
            _print_result(name, condition, "", "FAIL")
            return False

    # ------------------------------------------------------------------ #
    #  Pass-through: just log a named step as PASS / FAIL
    # ------------------------------------------------------------------ #
    def logResult(self, name: str, passed: bool, info: str = "") -> bool:
        status = "PASS" if passed else "FAIL"
        _print_result(name, info, "", status)
        return passed

    # ------------------------------------------------------------------ #
    #  Operator input: ask the operator, log the answer as an INFO step.
    #  The returned value can then be checked with the methods above.
    # ------------------------------------------------------------------ #
    def _ask(self, kind: str, name: str, message: str, units: str = "", **extra):
        if _RUNNER_MODE and _ANSWER_FD:
            value = _ask_runner(kind, name, message, units=units or None, **extra)
        else:
            value = _ask_console(kind, message, options=extra.get("options"),
                                 lo=extra.get("min"), hi=extra.get("max"),
                                 default=extra.get("default"))
        _print_result(name, f"operator: {value}", units, "INFO")
        return value

    def askNumber(self, name: str, message: str, lo=None, hi=None, units: str = "", default=None) -> float:
        """Number input; lo/hi limit what the operator may enter."""
        return float(self._ask("number", name, message, units, min=lo, max=hi, default=default))

    def askText(self, name: str, message: str, default: str = "") -> str:
        """Free text input (e.g. serial number); empty answers are not accepted."""
        return str(self._ask("text", name, message, default=default or None))

    def askChoice(self, name: str, message: str, options, default=None) -> str:
        """Drop-down list; returns the selected option."""
        return self._ask("choice", name, message, options=list(options), default=default)

    def askButtons(self, name: str, message: str, buttons=("OK",)) -> str:
        """One button per option; returns the label of the pressed button."""
        return self._ask("buttons", name, message, options=list(buttons))

    def askYesNo(self, name: str, message: str) -> bool:
        return self.askButtons(name, message, ("Yes", "No")) == "Yes"


    # ------------------------------------------------------------------ #
    #  Error / exception marker
    # ------------------------------------------------------------------ #
    def logError(self, name: str, message: str = "") -> None:
        _print_result(name, message, "", "ERROR")


if __name__ == "__main__":
    ts = TestStrategy()
    print(f"{'Test name':<{_NAME_W}}  {'Condition':<{_COND_W}}  {'Unit':<{_UNIT_W}}  Status")
    print("-" * (_NAME_W + _COND_W + _UNIT_W + 14))

    ts.numericLimitTest("Voltage -8V",          7.8,   7.3, 8.3,  "V")
    ts.numericLimitTest("Voltage -3V3",         3.5,   3.2, 3.7,  "V")
    ts.numericLimitTest("AC current",           0.05,  0.0, 0.04, "A")
    ts.numericLimitTestInclusive("NTC value",   215,   209, 223,  "")
    ts.stringMatchTest("FW version response",   "4",   "4")
    ts.booleanTest("Key1 state off",            False, False)
    ts.booleanTest("Key2 state on",             False, True)
    ts.logResult("Pump activated",              True,  "relay closed")
    ts.logError("FM counter",                   "timeout reading counter")
