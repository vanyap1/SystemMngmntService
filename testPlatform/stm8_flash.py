import subprocess
import sys
import os
import tempfile


class STM8Flasher:
    FLASH_SIZE = 8192

    def __init__(self, fw_dir: str = "fw", chip: str = "STM8S003F3"):
        self.fw_dir = fw_dir
        self.chip = chip

    # ------------------------------------------------------------------ #
    #  stm8flash write + verify
    # ------------------------------------------------------------------ #

    def flash(self, prog_file: str, data_file: str = None, verify: bool = True) -> bool:
        """Write (and optionally verify) firmware via stm8flash.

        Args:
            prog_file: program .hex file name (relative to fw_dir).
            data_file: optional EEPROM data .hex file name (relative to fw_dir).
            verify:    run verify after writing (default True).
        """
        prog_path = os.path.join(self.fw_dir, prog_file)
        if not os.path.exists(prog_path):
            print(f"❌ File not found: {prog_path}")
            return False

        if not self._run_stm8flash(["-w", prog_path]):
            return False

        if data_file:
            data_path = os.path.join(self.fw_dir, data_file)
            if not os.path.exists(data_path):
                print(f"❌ File not found: {data_path}")
                return False
            if not self._run_stm8flash(["-s", "eeprom", "-w", data_path]):
                return False

        if verify:
            if not self._run_stm8flash(["-v", prog_path]):
                return False
            if data_file:
                if not self._run_stm8flash(["-s", "eeprom", "-v", data_path]):
                    return False

        return True

    def verify(self, prog_file: str, data_file: str = None) -> bool:
        """Verify chip contents against file(s) without writing."""
        prog_path = os.path.join(self.fw_dir, prog_file)
        if not os.path.exists(prog_path):
            print(f"❌ File not found: {prog_path}")
            return False

        if not self._run_stm8flash(["-v", prog_path]):
            return False

        if data_file:
            data_path = os.path.join(self.fw_dir, data_file)
            if not os.path.exists(data_path):
                print(f"❌ File not found: {data_path}")
                return False
            if not self._run_stm8flash(["-s", "eeprom", "-v", data_path]):
                return False

        return True

    def reset_chip(self) -> bool:
        """Reset chip via st-flash."""
        try:
            result = subprocess.run(
                ["st-flash", "reset"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True
            )
            print(result.stdout)
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Reset error (code {e.returncode}):\n{e.stdout}")
            return False
        except FileNotFoundError:
            print("❌ st-flash not found, skipping reset.")
            return False

    # ------------------------------------------------------------------ #
    #  stm8flash  (read / erase)
    # ------------------------------------------------------------------ #

    def _run_stm8flash(self, args: list) -> bool:
        command = ["stm8flash", "-c", "stlinkv2", "-p", self.chip.lower()] + args
        try:
            subprocess.run(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
            return True
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            print("❌ stm8flash not found!")
            return False

    def read_dump(self, filename: str) -> bool:
        """Read memory dump from chip to file (relative to fw_dir)."""
        filepath = os.path.join(self.fw_dir, filename)
        os.makedirs(self.fw_dir, exist_ok=True)
        return self._run_stm8flash(["-r", filepath])

    def erase_chip(self) -> bool:
        """Erase chip flash (write zeros)."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b'\x00' * self.FLASH_SIZE)
            tmp_name = tmp.name
        try:
            return self._run_stm8flash(["-s", "flash", "-w", tmp_name])
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)


# ------------------------------------------------------------------ #
#  Standalone CLI
# ------------------------------------------------------------------ #

def main():
    fw_dir = input("Firmware directory (Enter = 'fw'): ").strip() or "fw"
    chip   = input("Chip name (Enter = 'STM8S003F3'): ").strip() or "STM8S003F3"
    flasher = STM8Flasher(fw_dir=fw_dir, chip=chip)

    while True:
        print(f"\n[{chip}  dir={fw_dir}]")
        print(" [f]  Flash (STVP)")
        print(" [r]  Read dump (stm8flash)")
        print(" [e]  Erase chip (stm8flash)")
        print(" [q]  Quit")

        choice = input("> ").strip().lower()

        if choice == 'f':
            prog = input("Program .hex file: ").strip()
            if not prog:
                continue
            data = input("Data .hex file (Enter to skip): ").strip() or None
            flasher.flash(prog, data_file=data)
        elif choice == 'r':
            name = input("Output file name: ").strip()
            if name:
                flasher.read_dump(name)
        elif choice == 'e':
            if input("Erase entire flash? (y/n): ").strip().lower() == 'y':
                flasher.erase_chip()
        elif choice == 'q':
            break
        else:
            print("Unknown command.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)