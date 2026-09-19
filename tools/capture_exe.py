"""Captura a janela do executavel empacotado. Ferramenta de verificacao."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
EXE = RAIZ / "dist" / "edgemd" / "edgemd.exe"
DEMO = RAIZ / "docs-exemplo" / "demo.md"
SAIDA = RAIZ / "scratch" / "exe-preview.png"

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

user32.SetProcessDPIAware()


def encontrar_janela(pid: int) -> int:
    achados: list[int] = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

    def cb(hwnd, _lparam):
        dono = w.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(dono))
        if dono.value == pid and user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                achados.append(hwnd)
        return True

    user32.EnumWindows(CB(cb), 0)
    return achados[0] if achados else 0


def capturar(hwnd: int) -> Image.Image:
    """Fotografa a janela com PrintWindow (funciona mesmo sobreposta)."""
    rect = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    largura = rect.right - rect.left
    altura = rect.bottom - rect.top

    hdc_janela = user32.GetWindowDC(hwnd)
    hdc_memoria = gdi32.CreateCompatibleDC(hdc_janela)
    bitmap = gdi32.CreateCompatibleBitmap(hdc_janela, largura, altura)
    gdi32.SelectObject(hdc_memoria, bitmap)

    # 2 = PW_RENDERFULLCONTENT: sem isso, o Chromium sai em branco, porque ele
    # desenha por composicao e nao na superficie normal da janela.
    user32.PrintWindow(hwnd, hdc_memoria, 2)

    buffer = ctypes.create_string_buffer(largura * altura * 4)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG),
            ("biPlanes", w.WORD), ("biBitCount", w.WORD),
            ("biCompression", w.DWORD), ("biSizeImage", w.DWORD),
            ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG),
            ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD),
        ]

    cabecalho = BITMAPINFOHEADER()
    cabecalho.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    cabecalho.biWidth = largura
    cabecalho.biHeight = -altura          # negativo = origem no topo
    cabecalho.biPlanes = 1
    cabecalho.biBitCount = 32
    cabecalho.biCompression = 0

    gdi32.GetDIBits(hdc_memoria, bitmap, 0, altura, buffer, ctypes.byref(cabecalho), 0)

    imagem = Image.frombuffer("RGBA", (largura, altura), buffer, "raw", "BGRA", 0, 1)
    imagem = imagem.convert("RGB")

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(hdc_memoria)
    user32.ReleaseDC(hwnd, hdc_janela)
    return imagem


def main() -> int:
    SAIDA.parent.mkdir(exist_ok=True)

    if not EXE.is_file():
        print(f"ERRO: {EXE} nao existe")
        return 1

    print(f"==> Executando {EXE.name} com {DEMO.name}")
    processo = subprocess.Popen([str(EXE), str(DEMO)])

    hwnd = 0
    for _ in range(40):
        time.sleep(1)
        hwnd = encontrar_janela(processo.pid)
        if hwnd:
            break

    if not hwnd:
        print("ERRO: janela nao apareceu")
        processo.kill()
        return 1

    # Espera o Chromium renderizar: o Mermaid tem 3,5 MB e desenha depois.
    time.sleep(12)
    hwnd = encontrar_janela(processo.pid) or hwnd

    titulo = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, titulo, 512)
    print(f"  janela: {titulo.value!r}")

    imagem = capturar(hwnd)
    imagem.save(SAIDA, "PNG")
    print(f"  captura: {SAIDA} ({imagem.width}x{imagem.height})")

    # A foto sozinha nao prova nada; conta os pixels nao uniformes para
    # distinguir "renderizou" de "janela em branco".
    cores = imagem.getcolors(maxcolors=1_000_000) or []
    print(f"  cores distintas: {len(cores)}")
    if len(cores) < 200:
        print("  AVISO: poucas cores — a janela pode estar vazia")
        processo.kill()
        return 1

    processo.terminate()
    try:
        processo.wait(timeout=10)
    except subprocess.TimeoutExpired:
        processo.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
