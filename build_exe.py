"""Build the single-file adfu-tool exes with PyInstaller (run from this directory)."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
WORK = HERE / "build-exe"


def build(name, entry, extra):
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--onefile", "--clean",
        "--name", name,
        "--distpath", str(DIST), "--workpath", str(WORK), "--specpath", str(WORK),
        "--collect-all", "libusb_package",
        "--collect-data", "adfu_tool",
        "--hidden-import", "usb", "--hidden-import", "usb.core", "--hidden-import", "usb.util",
        "--hidden-import", "usb.backend.libusb1",
        "--paths", str(HERE),
    ] + extra + [str(HERE / entry)]
    print(" ".join(command))
    subprocess.run(command, cwd=HERE, check=True)
    exe = DIST / (name + ".exe")
    if not exe.exists():
        raise SystemExit(name + ".exe missing after build")
    print("\nbuilt", exe, "(" + str(exe.stat().st_size) + " bytes)")
    return exe


def main():
    build("adfu-tool", "launcher.py", [])
    gui_exe = build("adfu-tool-gui", "launcher_gui.py", ["--noconsole"])
    for args in (["--version"], ["devices"]):
        result = subprocess.run([str(DIST / "adfu-tool.exe"), *args],
                                capture_output=True, text=True, timeout=60)
        print("$ adfu-tool", " ".join(args))
        print(result.stdout, result.stderr)
        if result.returncode != 0:
            raise SystemExit("smoke command failed: " + " ".join(args))
    result = subprocess.run([str(gui_exe), "--smoke"], timeout=120)
    if result.returncode != 0:
        raise SystemExit("gui smoke failed")


if __name__ == "__main__":
    main()
