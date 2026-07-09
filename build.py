#!/usr/bin/env python3
"""
build.py — Compile DailyHackerNews into a single clickable file (Win / macOS / Linux)

Usage:
    python3 build.py

Produces in the project directory:
    macOS   → DailyHackerNews.app
    Windows → DailyHackerNews.exe
    Linux   → DailyHackerNews
"""
from __future__ import annotations
import os
import sys
import shutil
import platform
import subprocess
import textwrap
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent          # project root
SCRIPT     = ROOT / "scripts" / "secjournal.py"
ICON_PNG   = ROOT / "icon.png"
TMP        = ROOT / "_build_tmp"
DIST_TMP   = TMP / "dist"
WORK_TMP   = TMP / "work"
SPEC_TMP   = TMP

OS = platform.system()   # 'Darwin' | 'Windows' | 'Linux'

BANNER = r"""
  ╔══════════════════════════════════════════════╗
  ║  DailyHackerNews Builder — detect OS + compile   ║
  ╚══════════════════════════════════════════════╝
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list, **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def pip(pkg: str):
    run([sys.executable, "-m", "pip", "install", "--quiet", pkg])


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        print("[✓] PyInstaller present")
    except ImportError:
        print("[*] Installing PyInstaller...")
        pip("pyinstaller")


# ── Icon conversion ────────────────────────────────────────────────────────

def icon_to_icns(png: Path) -> Path | None:
    """macOS: PNG -> .icns via sips + iconutil"""
    if not png.exists():
        return None
    iconset = TMP / "AppIcon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for s in [16, 32, 64, 128, 256, 512]:
        run(["sips", "-z", str(s), str(s), str(png),
             "--out", str(iconset / f"icon_{s}x{s}.png")], stdout=subprocess.DEVNULL)
        run(["sips", "-z", str(s * 2), str(s * 2), str(png),
             "--out", str(iconset / f"icon_{s}x{s}@2x.png")], stdout=subprocess.DEVNULL)
    icns = TMP / "AppIcon.icns"
    run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)])
    return icns


def icon_to_ico(png: Path) -> Path | None:
    """Windows: PNG -> .ico via Pillow"""
    if not png.exists():
        return None
    try:
        from PIL import Image
    except ImportError:
        pip("pillow")
        from PIL import Image
    ico = TMP / "AppIcon.ico"
    img = Image.open(png).convert("RGBA")
    img.save(str(ico), format="ICO",
             sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    return ico


# ── Shared PyInstaller command ──────────────────────────────────────────────

def pyinstaller_cmd(icon_path: Path | None = None) -> list:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "DailyHackerNews",
        "--distpath", str(DIST_TMP),
        "--workpath", str(WORK_TMP),
        "--specpath", str(SPEC_TMP),
        # bundled data: knowledge/rss + configs
        "--add-data", f"{ROOT / 'knowledge'}:knowledge",
        "--add-data", f"{ROOT / 'configs'}:configs",
    ]
    if icon_path and icon_path.exists():
        cmd += ["--icon", str(icon_path)]
    cmd.append(str(SCRIPT))
    return cmd


# ── macOS ─────────────────────────────────────────────────────────────────────

def build_macos():
    print("[*] Target: macOS -> DailyHackerNews.app")

    icns = icon_to_icns(ICON_PNG)
    run(pyinstaller_cmd(icns))

    binary = DIST_TMP / "DailyHackerNews"
    if not binary.exists():
        sys.exit("[!] PyInstaller did not produce a binary")

    app = ROOT / "DailyHackerNews.app"
    if app.exists():
        shutil.rmtree(app)

    macos_dir = app / "Contents" / "MacOS"
    res_dir   = app / "Contents" / "Resources"
    macos_dir.mkdir(parents=True)
    res_dir.mkdir(parents=True)

    # Compiled binary
    dest_bin = macos_dir / "DailyHackerNews_bin"
    shutil.copy(binary, dest_bin)
    dest_bin.chmod(0o755)

    # Launcher: opens Terminal.app and runs the binary
    launcher = macos_dir / "DailyHackerNews"
    # First run (no journal yet) uses --days 7 for a richer initial view;
    # subsequent runs use --days 3 which stays lively without duplicating too
    # much between daily launches. The .app already defaults to auto-open so
    # the HTML shows up in the browser as soon as it's ready.
    launcher.write_text(textwrap.dedent("""\
        #!/bin/bash
        DIR="$(cd "$(dirname "$0")" && pwd)"
        BIN="$DIR/DailyHackerNews_bin"
        # Look for an existing journal — if none, seed with a wider window
        PROJECT_ROOT="$(cd "$DIR/../../.." && pwd)"
        JOURNAL_DIR="$PROJECT_ROOT/out/journals"
        DAYS=3
        if ! ls "$JOURNAL_DIR"/secjournal_*.html >/dev/null 2>&1; then
          DAYS=7
        fi
        osascript \\
          -e 'tell application "Terminal"' \\
          -e 'activate' \\
          -e "do script \\"'$BIN' --days $DAYS\\"" \\
          -e 'end tell'
    """))
    launcher.chmod(0o755)

    # Icon
    if icns and icns.exists():
        shutil.copy(icns, res_dir / "AppIcon.icns")
        icon_plist = "<key>CFBundleIconFile</key><string>AppIcon</string>"
    else:
        icon_plist = ""

    # Info.plist
    (app / "Contents" / "Info.plist").write_text(textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>CFBundleName</key><string>DailyHackerNews</string>
          <key>CFBundleDisplayName</key><string>DailyHackerNews</string>
          <key>CFBundleIdentifier</key><string>com.secjournal.veille</string>
          <key>CFBundleVersion</key><string>1.0</string>
          <key>CFBundleExecutable</key><string>DailyHackerNews</string>
          <key>CFBundlePackageType</key><string>APPL</string>
          {icon_plist}
        </dict>
        </plist>
    """))

    print(f"\n[✓] {app}")
    print("    → Double-click DailyHackerNews.app to generate and open the journal")
    print("    (First launch: right-click -> Open if Gatekeeper blocks it)")


# ── Windows ───────────────────────────────────────────────────────────────────

def build_windows():
    print("[*] Target: Windows -> DailyHackerNews.exe")

    ico = icon_to_ico(ICON_PNG)
    cmd = pyinstaller_cmd(ico) + ["--console"]
    # Point --distpath straight at the project root
    idx = cmd.index("--distpath") + 1
    cmd[idx] = str(ROOT)
    run(cmd)

    exe = ROOT / "DailyHackerNews.exe"
    if not exe.exists():
        sys.exit("[!] PyInstaller did not produce a .exe")

    print(f"\n[✓] {exe}")
    print("    → Double-click DailyHackerNews.exe to generate and open the journal")


# ── Linux ─────────────────────────────────────────────────────────────────────

def is_termux() -> bool:
    """Detect Android/Termux runtime."""
    return (
        "com.termux" in os.environ.get("PREFIX", "")
        or Path("/data/data/com.termux").exists()
        or os.environ.get("TERMUX_VERSION") is not None
    )


def build_termux():
    """Install-and-run flow for Android via Termux.

    Termux ships a real Python but not necessarily PyInstaller-compatible
    libc, so we skip freezing and instead:
      1. Install runtime deps (python, git, feedparser, pyyaml).
      2. Wire a `dhn` launcher shell script into ~/bin (or $PREFIX/bin).
      3. Report how to run and how to serve the journal.
    """
    print("[*] Target: Android / Termux -> runtime install (no freeze)")

    PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    HOME   = Path(os.environ.get("HOME", str(Path.home())))

    print("[*] Updating pkg…")
    subprocess.run(["pkg", "update", "-y"],  check=False)
    subprocess.run(["pkg", "upgrade", "-y"], check=False)

    pkgs = ["python", "git", "openssl", "libxml2", "libxslt",
            "curl", "termux-api"]
    print(f"[*] Installing packages: {' '.join(pkgs)}")
    subprocess.run(["pkg", "install", "-y", *pkgs], check=False)

    print("[*] pip : feedparser + pyyaml + deep-translator")
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
                   check=False)
    for pkg in ("feedparser", "pyyaml", "deep-translator"):
        subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=False)

    # ~/bin/dhn launcher
    bin_dir = HOME / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / "dhn"
    launcher.write_text(textwrap.dedent(f"""\
        #!/data/data/com.termux/files/usr/bin/bash
        # Daily Hacker News — Termux launcher
        cd "{ROOT}"
        exec {sys.executable} scripts/secjournal.py "$@"
    """))
    launcher.chmod(0o755)

    # cheap desktop-widget shortcut for Termux:Widget if installed
    widget = HOME / ".shortcuts" / "DailyHackerNews"
    widget.parent.mkdir(parents=True, exist_ok=True)
    widget.write_text(textwrap.dedent(f"""\
        #!/data/data/com.termux/files/usr/bin/bash
        cd "{ROOT}"
        {sys.executable} scripts/secjournal.py --open || true
    """))
    widget.chmod(0o755)

    print()
    print(f"[✓] launcher installed: {launcher}")
    print(f"[✓] Termux:Widget shortcut: {widget}")
    print()
    print("  Usage:")
    print("    dhn                              # 24h journal")
    print("    dhn --days 7 --output both       # week, HTML+MD")
    print("    dhn --search 'log4j' --sources github,gitee --lang en")
    print()
    print("  To publish via Cloudflare Tunnel from Termux:")
    print("    pkg install cloudflared")
    print("    bash publish.sh --daemon")
    print()
    print("  If 'dhn' is not found, add to your ~/.bashrc:")
    print("    export PATH=\"$HOME/.local/bin:$PATH\"")


def build_linux():
    print("[*] Target: Linux -> DailyHackerNews")

    icon = ICON_PNG if ICON_PNG.exists() else None
    cmd = pyinstaller_cmd(icon)
    idx = cmd.index("--distpath") + 1
    cmd[idx] = str(ROOT)
    run(cmd)

    binary = ROOT / "DailyHackerNews"
    if not binary.exists():
        sys.exit("[!] PyInstaller did not produce a binary")
    binary.chmod(0o755)

    # .desktop file for double-click in file managers
    desktop = ROOT / "DailyHackerNews.desktop"
    icon_path = str(ICON_PNG) if ICON_PNG.exists() else "terminal"
    desktop.write_text(textwrap.dedent(f"""\
        [Desktop Entry]
        Name=DailyHackerNews
        Comment=Daily security intelligence journal
        Exec={binary}
        Icon={icon_path}
        Terminal=true
        Type=Application
        Categories=Security;
    """))
    desktop.chmod(0o755)

    print(f"\n[✓] {binary}")
    print("    -> Double-click DailyHackerNews (or DailyHackerNews.desktop) to launch")


# ── Cleanup ─────────────────────────────────────────────────────────────────

def cleanup():
    print("\n[*] Cleaning up build files...")
    if TMP.exists():
        shutil.rmtree(TMP)
    for f in ROOT.glob("*.spec"):
        f.unlink(missing_ok=True)
    print("[✓] build/ dirs and .spec files removed")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(BANNER)
    print(f"[*] Detected OS   : {OS} ({platform.machine()})")
    print(f"[*] Python        : {sys.version.split()[0]}")
    print(f"[*] Project root : {ROOT}")
    print(f"[*] Script source : {SCRIPT}")
    print()

    if not SCRIPT.exists():
        sys.exit(f"[!] Script introuvable : {SCRIPT}")

    # Android/Termux: handle first, since it reports as a Linux OS
    # mais son toolchain interdit PyInstaller / .desktop / iconutil.
    if is_termux():
        print("[*] Termux environment detected (Android)")
        build_termux()
        return

    TMP.mkdir(parents=True, exist_ok=True)
    ensure_pyinstaller()
    print()

    if OS == "Darwin":
        build_macos()
    elif OS == "Windows":
        build_windows()
    elif OS == "Linux":
        build_linux()
    else:
        sys.exit(f"[!] Unsupported OS: {OS}")

    cleanup()

    print("\n" + "─" * 50)
    print("  ✅  Build complete — click the icon to launch DailyHackerNews")
    print("─" * 50 + "\n")


if __name__ == "__main__":
    main()
