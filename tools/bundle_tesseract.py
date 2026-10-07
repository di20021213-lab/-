"""Собирает папку с Tesseract для программы: только tesseract.exe и те DLL,
которые ему действительно нужны (по таблицам импорта), без отладочной
информации. Так программа получается в разы меньше.

    python tools/bundle_tesseract.py C:\\Tesseract-OCR bundle\\tesseract
"""

import os
import shutil
import subprocess
import sys

import pefile


def imports(path):
    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories(directories=[
        pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
        pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    names = set()
    for attr in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
        for entry in getattr(pe, attr, []):
            names.add(entry.dll.decode("ascii", "replace").lower())
    pe.close()
    return names


def strip_tools():
    """GNU strip (MinGW binutils) справляется с DLL Tesseract лучше llvm-strip."""
    cands = [shutil.which("strip"),
             r"C:\mingw64\bin\strip.exe", r"C:\Strawberry\c\bin\strip.exe",
             r"C:\msys64\mingw64\bin\strip.exe", r"C:\msys64\usr\bin\strip.exe",
             shutil.which("llvm-strip"), r"C:\Program Files\LLVM\bin\llvm-strip.exe"]
    out = []
    for c in cands:
        if c and os.path.isfile(c) and c not in out:
            out.append(c)
    return out


def strip_file(path, tools):
    before = os.path.getsize(path)
    for tool in tools:
        tmp = path + ".tmp"
        shutil.copy2(path, tmp)
        r = subprocess.run([tool, "--strip-debug", tmp], capture_output=True)
        if r.returncode == 0 and 0 < os.path.getsize(tmp) <= before:
            os.replace(tmp, path)
            return os.path.basename(tool)
        os.remove(tmp)
    return None


def main(src, dst):
    available = {f.lower(): f for f in os.listdir(src) if f.lower().endswith(".dll")}
    need, queue = set(), ["tesseract.exe"]
    while queue:
        name = queue.pop()
        for dep in imports(os.path.join(src, available.get(name, name))):
            if dep in available and dep not in need:
                need.add(dep)
                queue.append(dep)
    os.makedirs(dst, exist_ok=True)
    files = ["tesseract.exe"] + sorted(available[n] for n in need)
    for f in files:
        shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    print("взяты:", ", ".join(files))

    tools = strip_tools()
    print("strip:", tools or "не найден")
    for f in files:
        path = os.path.join(dst, f)
        before = os.path.getsize(path)
        used = strip_file(path, tools) if tools else None
        print(f"{f}: {before // 1024} -> {os.path.getsize(path) // 1024} КБ ({used or 'как есть'})")
    if os.name == "nt":
        # проверка, что после обрезки всё работает; иначе — исходные файлы
        ok = subprocess.run([os.path.join(dst, "tesseract.exe"), "--version"],
                            capture_output=True).returncode == 0
        if not ok:
            print("после обрезки tesseract не запускается — беру исходные файлы")
            for f in files:
                shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    total = sum(os.path.getsize(os.path.join(dst, f)) for f in files)
    print(f"итого: {total / 1024 / 1024:.1f} МБ")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
