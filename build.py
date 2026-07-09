#!/usr/bin/env python3
"""
build.py — Compile DailyHackerNews en un seul fichier cliquable (Win / macOS / Linux)

Usage :
    python3 build.py

Produit dans le dossier du projet :
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

# ── Chemins ───────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent          # racine du projet
SCRIPT     = ROOT / "scripts" / "secjournal.py"
ICON_PNG   = ROOT / "icon.png"
TMP        = ROOT / "_build_tmp"
DIST_TMP   = TMP / "dist"
WORK_TMP   = TMP / "work"
SPEC_TMP   = TMP

OS = platform.system()   # 'Darwin' | 'Windows' | 'Linux'

BANNER = r"""
  ╔══════════════════════════════════════════════╗
  ║  DailyHackerNews Builder — détection OS + compile ║
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
        print("[✓] PyInstaller présent")
    except ImportError:
        print("[*] Installation de PyInstaller...")
        pip("pyinstaller")


# ── Conversion d'icône ────────────────────────────────────────────────────────

def icon_to_icns(png: Path) -> Path | None:
    """macOS : PNG → .icns via sips + iconutil"""
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
    """Windows : PNG → .ico via Pillow"""
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


# ── Commande PyInstaller commune ──────────────────────────────────────────────

def pyinstaller_cmd(icon_path: Path | None = None) -> list:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "DailyHackerNews",
        "--distpath", str(DIST_TMP),
        "--workpath", str(WORK_TMP),
        "--specpath", str(SPEC_TMP),
        # données embarquées : knowledge/rss + configs
        "--add-data", f"{ROOT / 'knowledge'}:knowledge",
        "--add-data", f"{ROOT / 'configs'}:configs",
    ]
    if icon_path and icon_path.exists():
        cmd += ["--icon", str(icon_path)]
    cmd.append(str(SCRIPT))
    return cmd


# ── macOS ─────────────────────────────────────────────────────────────────────

def build_macos():
    print("[*] Cible : macOS → DailyHackerNews.app")

    icns = icon_to_icns(ICON_PNG)
    run(pyinstaller_cmd(icns))

    binary = DIST_TMP / "DailyHackerNews"
    if not binary.exists():
        sys.exit("[!] PyInstaller n'a pas produit de binaire")

    app = ROOT / "DailyHackerNews.app"
    if app.exists():
        shutil.rmtree(app)

    macos_dir = app / "Contents" / "MacOS"
    res_dir   = app / "Contents" / "Resources"
    macos_dir.mkdir(parents=True)
    res_dir.mkdir(parents=True)

    # Binaire compilé
    dest_bin = macos_dir / "DailyHackerNews_bin"
    shutil.copy(binary, dest_bin)
    dest_bin.chmod(0o755)

    # Launcher : ouvre Terminal.app et exécute le binaire
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

    # Icône
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
    print("    → Double-cliquez sur DailyHackerNews.app pour générer et ouvrir le journal")
    print("    (Premier lancement : clic-droit → Ouvrir si Gatekeeper bloque)")


# ── Windows ───────────────────────────────────────────────────────────────────

def build_windows():
    print("[*] Cible : Windows → DailyHackerNews.exe")

    ico = icon_to_ico(ICON_PNG)
    cmd = pyinstaller_cmd(ico) + ["--console"]
    # Remplacer --distpath par le dossier racine directement
    idx = cmd.index("--distpath") + 1
    cmd[idx] = str(ROOT)
    run(cmd)

    exe = ROOT / "DailyHackerNews.exe"
    if not exe.exists():
        sys.exit("[!] PyInstaller n'a pas produit de .exe")

    print(f"\n[✓] {exe}")
    print("    → Double-cliquez sur DailyHackerNews.exe pour générer et ouvrir le journal")


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
    print("[*] Cible : Android / Termux → runtime install (pas de freeze)")

    PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    HOME   = Path(os.environ.get("HOME", str(Path.home())))

    print("[*] Mise a jour de pkg…")
    subprocess.run(["pkg", "update", "-y"],  check=False)
    subprocess.run(["pkg", "upgrade", "-y"], check=False)

    pkgs = ["python", "git", "openssl", "libxml2", "libxslt",
            "curl", "termux-api"]
    print(f"[*] Installation des paquets : {' '.join(pkgs)}")
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
    print(f"[✓] launcher installe : {launcher}")
    print(f"[✓] shortcut Termux:Widget : {widget}")
    print()
    print("  Utilisation :")
    print("    dhn                              # journal 24h")
    print("    dhn --days 7 --output both       # semaine, HTML+MD")
    print("    dhn --search 'log4j' --sources github,gitee --lang en")
    print()
    print("  Pour publier via Cloudflare Tunnel depuis Termux :")
    print("    pkg install cloudflared")
    print("    bash build2.sh --daemon")
    print()
    print("  Si 'dhn' n'est pas trouve, ajoute a ton ~/.bashrc :")
    print("    export PATH=\"$HOME/.local/bin:$PATH\"")


def build_linux():
    print("[*] Cible : Linux → DailyHackerNews")

    icon = ICON_PNG if ICON_PNG.exists() else None
    cmd = pyinstaller_cmd(icon)
    idx = cmd.index("--distpath") + 1
    cmd[idx] = str(ROOT)
    run(cmd)

    binary = ROOT / "DailyHackerNews"
    if not binary.exists():
        sys.exit("[!] PyInstaller n'a pas produit de binaire")
    binary.chmod(0o755)

    # Fichier .desktop pour double-clic dans les gestionnaires de fichiers
    desktop = ROOT / "DailyHackerNews.desktop"
    icon_path = str(ICON_PNG) if ICON_PNG.exists() else "terminal"
    desktop.write_text(textwrap.dedent(f"""\
        [Desktop Entry]
        Name=DailyHackerNews
        Comment=Veille sécurité quotidienne
        Exec={binary}
        Icon={icon_path}
        Terminal=true
        Type=Application
        Categories=Security;
    """))
    desktop.chmod(0o755)

    print(f"\n[✓] {binary}")
    print("    → Double-cliquez sur DailyHackerNews (ou DailyHackerNews.desktop) pour lancer")


# ── Nettoyage ─────────────────────────────────────────────────────────────────

def cleanup():
    print("\n[*] Nettoyage des fichiers de build...")
    if TMP.exists():
        shutil.rmtree(TMP)
    for f in ROOT.glob("*.spec"):
        f.unlink(missing_ok=True)
    print("[✓] Dossiers build/ et fichiers .spec supprimés")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(BANNER)
    print(f"[*] OS détecté    : {OS} ({platform.machine()})")
    print(f"[*] Python        : {sys.version.split()[0]}")
    print(f"[*] Racine projet : {ROOT}")
    print(f"[*] Script source : {SCRIPT}")
    print()

    if not SCRIPT.exists():
        sys.exit(f"[!] Script introuvable : {SCRIPT}")

    # Android/Termux : traite en tout premier, il tourne sur un OS Linux
    # mais son toolchain interdit PyInstaller / .desktop / iconutil.
    if is_termux():
        print("[*] Environnement Termux détecté (Android)")
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
        sys.exit(f"[!] OS non supporté : {OS}")

    cleanup()

    print("\n" + "─" * 50)
    print("  ✅  Build terminé — cliquez sur l'icône pour lancer DailyHackerNews")
    print("─" * 50 + "\n")


if __name__ == "__main__":
    main()
