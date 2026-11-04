"""Build the single-file adfu-tool.exe with PyInstaller (run from this directory)."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    dist = HERE / "dist"
    build = HERE / "build-exe"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--onefile", "--clean",
        "--name", "adfu-tool",
        "--distpath", str(dist), "--workpath", str(build), "--specpath", str(build),
        "--collect-all", "libusb_package",
        "--collect-data", "adfu_tool",
        "--hidden-import", "usb", "--hidden-import", "usb.core", "--hidden-import", "usb.util",
        "--hidden-import", "usb.backend.libusb1",
        "--paths", str(HERE),
        str(HERE / "launcher.py"),
    ]
    print(" ".join(command))
    subprocess.run(command, cwd=HERE, check=True)
    exe = dist / "adfu-tool.exe"
    if not exe.exists():
        raise SystemExit("exe missing after build")
    print(f"\nbuilt {exe} ({exe.stat().st_size} bytes)")
    for args in (["--version"], ["devices"]):
        result = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=60)
        print(f"$ adfu-tool {' '.join(args)}\n{result.stdout}{result.stderr}")
        if result.returncode != 0:
            raise SystemExit(f"smoke command failed: {args}")


if __name__ == "__main__":
    main()
