"""Prepara o ícone do aplicativo a partir da arte de origem.

A arte de origem (``EdgeMD.png``, 2048×2048) não serve como ícone direto, por
três motivos:

1. **Margem desperdiçada.** O tile ocupa só o miolo da imagem; usar o arquivo
   inteiro faria o ícone aparecer pequeno, com uma moldura escura em volta.
2. **Sem transparência.** É RGB puro. Sem recortar os cantos, o ícone vira um
   quadrado escuro opaco na barra de tarefas, que fica evidente sobre um tema
   claro.
3. **Marca d'água.** O rodapé da arte traz um crédito de geração de imagem, que
   não deve ir para um ícone de produto. Ele fica fora do tile, então o recorte
   já o remove.

O tile é localizado automaticamente pela linha clara da borda, em vez de
coordenadas fixas: a arte pode ser regerada com outro enquadramento.

Uso:
    python tools/make_icons.py
    python tools/make_icons.py --source outra-arte.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

RESOURCES = ROOT / "src" / "edgemd" / "resources" / "icons"

#: Tamanho do PNG canônico. 512 px cobre com folga o maior uso (256 px de
#: ícone em tela com escala 2) sem carregar o repositório.
CANONICAL_SIZE = 512

#: Resoluções guardadas no .ico. O Windows escolhe a adequada por contexto:
#: 16 na bandeja, 32 na barra de tarefas, 256 no Explorador em ícones grandes.
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

#: Abaixo deste tamanho o ícone usa a variante sem a assinatura "EdgeMD".
#: Em 32 px ou menos o texto vira mancha cinza e só suja o desenho; sem ele, o
#: "#" e a fita ficam maiores e continuam reconhecíveis. É prática comum em
#: conjuntos de ícones: o desenho simplifica conforme o tamanho cai.
SMALL_ICON_THRESHOLD = 40

#: Região da assinatura "EdgeMD", em fração do tile: (esquerda, topo, direita,
#: base). Medida na arte de origem — é o que a variante pequena deixa de fora.
WORDMARK_ZONE = (0.55, 0.33, 1.0, 0.61)

#: Folga em volta da arte na variante pequena, em fração do lado do recorte.
SMALL_PADDING_RATIO = 0.10

#: Raio dos cantos como fração do lado, medido na arte de origem.
CORNER_RADIUS_RATIO = 0.161

#: Supersampling ao desenhar a máscara, para o canto sair liso.
MASK_SUPERSAMPLE = 4

#: Brilho mínimo para considerar que um pixel é a linha da borda.
BORDER_THRESHOLD = 60


def brightness(pixel: tuple[int, ...]) -> float:
    return sum(pixel[:3]) / 3


def find_border(image: Image.Image, along_x: bool, fixed: int, rng: range) -> int | None:
    """Acha a linha da borda do tile numa varredura.

    A borda é um pico local de brilho: mais clara que o fundo externo **e** que
    o interior do tile, que é escuro. Procurar por pico, e não por limiar
    absoluto, é o que torna a detecção robusta se a arte mudar de tom.
    """
    pixels = image.load()

    def value(pos: int) -> float:
        return brightness(pixels[pos, fixed] if along_x else pixels[fixed, pos])

    for pos in rng:
        if value(pos) < BORDER_THRESHOLD:
            continue
        if value(pos) > value(pos - 5) + 5 and value(pos) > value(pos + 5) + 5:
            return pos
    return None


def detect_tile(image: Image.Image) -> tuple[int, int, int, int]:
    """Devolve a caixa ``(esquerda, topo, direita, base)`` do tile."""
    width, height = image.size
    middle_x, middle_y = width // 2, height // 2
    span = min(width, height) // 2 - 10

    left = find_border(image, True, middle_y, range(5, span))
    top = find_border(image, False, middle_x, range(5, span))
    right = find_border(image, True, middle_y, range(width - 6, width - span, -1))
    bottom = find_border(image, False, middle_x, range(height - 6, height - span, -1))

    faltando = [
        nome
        for nome, valor in (("esquerda", left), ("topo", top), ("direita", right), ("base", bottom))
        if valor is None
    ]
    if faltando:
        raise SystemExit(
            "Não consegui localizar a borda do tile ("
            + ", ".join(faltando)
            + "). Passe --box esquerda,topo,direita,base explicitamente."
        )

    return left, top, right, bottom  # type: ignore[return-value]


def rounded_mask(size: int, radius: int) -> Image.Image:
    """Máscara com cantos arredondados, desenhada com supersampling.

    Desenhar em 4× e reduzir é o que evita a escada no arco: o
    ``rounded_rectangle`` do Pillow não tem antialias próprio.
    """
    big = size * MASK_SUPERSAMPLE
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, big - 1, big - 1), radius=radius * MASK_SUPERSAMPLE, fill=255
    )
    return mask.resize((size, size), Image.LANCZOS)


def build_icon(source: Path, box: tuple[int, int, int, int] | None, *, size: int = CANONICAL_SIZE) -> Image.Image:
    """Recorta o tile e devolve um quadrado com cantos transparentes."""
    art = Image.open(source).convert("RGBA")

    left, top, right, bottom = box or detect_tile(art)
    tile = art.crop((left, top, right + 1, bottom + 1))

    # O tile da arte não é perfeitamente quadrado (diferença de ~1%), e o
    # ícone precisa ser. Redimensionar para quadrado estica menos de 1%, o que
    # é imperceptível.
    square = tile.resize((size, size), Image.LANCZOS)

    radius = round(size * CORNER_RADIUS_RATIO)
    square.putalpha(rounded_mask(size, radius))
    return square


def _erase_region(icon: Image.Image, box: tuple[int, int, int, int]) -> None:
    """Preenche uma região com o fundo reconstruído pela vizinhança.

    Usa filtro de mediana em vez de interpolar entre pontos de amostra. A
    tentativa anterior escolhia a cor logo acima e logo abaixo do texto, e
    perto do gume luminoso da fita essas amostras vinham contaminadas — o
    resultado foi uma emenda vertical visível.

    A mediana é imune a isso: numa janela grande o suficiente, a maioria dos
    vizinhos é fundo (a fita é um traço fino), então o valor mediano é a cor do
    fundo, independentemente de onde a amostra cai.
    """
    left, top, right, bottom = box
    side = icon.width
    margem = 24

    expandido = (
        max(0, left - margem),
        max(0, top - margem),
        min(side, right + margem),
        min(side, bottom + margem),
    )
    regiao = icon.crop(expandido)
    # A mediana precisa de janela ímpar; 41 px cobre com folga a espessura dos
    # traços da assinatura e ainda é rápido o bastante numa região pequena.
    suavizada = regiao.filter(ImageFilter.MedianFilter(size=41))

    # Cola de volta só a área da assinatura: a margem existe apenas para dar
    # vizinhança ao filtro e não deve ser alterada.
    recorte = (
        left - expandido[0],
        top - expandido[1],
        left - expandido[0] + (right - left),
        top - expandido[1] + (bottom - top),
    )
    icon.paste(suavizada.crop(recorte), (left, top))


def erase_wordmark(icon: Image.Image, margin: int = 8) -> tuple[Image.Image, int]:
    """Apaga a assinatura "EdgeMD" do tile, devolvendo ``(imagem, lado_arte)``.

    Recortar não serve: a fita e a assinatura se sobrepõem em x, então qualquer
    recorte retangular ou inclui o texto ou decepa a ponta da fita — o primeiro
    resultado foi um "EdgeMI" cortado no meio.

    Como a assinatura está sobre fundo chapado, apagá-la é invisível.
    """
    cleaned = icon.copy()
    pixels = cleaned.load()
    side = cleaned.width

    zone_left = int(side * WORDMARK_ZONE[0])
    zone_top = int(side * WORDMARK_ZONE[1])
    zone_right = int(side * WORDMARK_ZONE[2])
    zone_bottom = int(side * WORDMARK_ZONE[3])

    # A assinatura é branca; a fita é ciano/azul. Exigir os três canais claros
    # separa uma da outra e evita apagar o gume luminoso da fita.
    xs: list[int] = []
    ys: list[int] = []
    for y in range(zone_top, min(zone_bottom, side)):
        for x in range(zone_left, min(zone_right, side)):
            red, green, blue, alpha = pixels[x, y]
            if alpha > 200 and red > 185 and green > 185 and blue > 185:
                xs.append(x)
                ys.append(y)

    if not xs:
        return cleaned, side

    _erase_region(
        cleaned,
        (
            max(0, min(xs) - margin),
            max(0, min(ys) - margin),
            min(side - 1, max(xs) + margin),
            min(side - 1, max(ys) + margin),
        ),
    )

    # Maior quadrado que contém só a arte, para a variante pequena enquadrá-la.
    pixels = cleaned.load()
    art_xs: list[int] = []
    art_ys: list[int] = []
    for y in range(0, side, 2):
        for x in range(0, side, 2):
            red, green, blue, alpha = pixels[x, y]
            if alpha > 200 and (red + green + blue) / 3 > 110:
                art_xs.append(x)
                art_ys.append(y)

    if not art_xs:
        return cleaned, side

    center_x = (min(art_xs) + max(art_xs)) // 2
    center_y = (min(art_ys) + max(art_ys)) // 2
    needed = max(max(art_xs) - min(art_xs), max(art_ys) - min(art_ys))
    needed = int(needed * (1 + 2 * SMALL_PADDING_RATIO))
    max_side = 2 * min(center_x, center_y, side - center_x, side - center_y)
    return cleaned, max(64, min(needed, max_side))


def build_small_icon(full: Image.Image, size: int = CANONICAL_SIZE) -> Image.Image:
    """Variante para tamanhos pequenos: sem assinatura e com a arte maior.

    Em 16 a 32 px a assinatura vira mancha cinza; sem ela, o "#" e a fita
    ocupam mais espaço e continuam reconhecíveis na bandeja e na barra de
    tarefas.
    """
    cleaned, art_side = erase_wordmark(full)
    if art_side >= cleaned.width:
        return cleaned

    pixels = cleaned.load()
    side = cleaned.width

    xs: list[int] = []
    ys: list[int] = []
    for y in range(0, side, 2):
        for x in range(0, side, 2):
            red, green, blue, alpha = pixels[x, y]
            if alpha > 200 and (red + green + blue) / 3 > 110:
                xs.append(x)
                ys.append(y)

    center_x = (min(xs) + max(xs)) // 2
    center_y = (min(ys) + max(ys)) // 2
    half = art_side // 2

    left = max(0, min(side - art_side, center_x - half))
    top = max(0, min(side - art_side, center_y - half))

    cropped = cleaned.crop((left, top, left + art_side, top + art_side))
    cropped = cropped.resize((size, size), Image.LANCZOS)

    radius = round(size * CORNER_RADIUS_RATIO)
    cropped.putalpha(rounded_mask(size, radius))
    return cropped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "EdgeMD.png",
        help="arte de origem (padrão: EdgeMD.png na raiz do projeto)",
    )
    parser.add_argument(
        "--box",
        help="caixa do tile como esquerda,topo,direita,base (padrão: detectar)",
    )
    parser.add_argument(
        "--no-ico", action="store_true", help="gerar só o PNG canônico"
    )
    parser.add_argument(
        "--no-simplify-small",
        action="store_true",
        help=f"usar o mesmo desenho em todos os tamanhos (sem a variante "
             f"abaixo de {SMALL_ICON_THRESHOLD} px)",
    )
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_file():
        raise SystemExit(f"Arte de origem não encontrada: {source}")

    box = None
    if args.box:
        try:
            partes = [int(v) for v in args.box.split(",")]
        except ValueError:
            raise SystemExit("--box espera quatro inteiros: esquerda,topo,direita,base")
        if len(partes) != 4:
            raise SystemExit("--box espera quatro inteiros: esquerda,topo,direita,base")
        box = (partes[0], partes[1], partes[2], partes[3])

    art = Image.open(source)
    print(f"origem   : {source.name} ({art.width}x{art.height}, {art.mode})")

    tile = box or detect_tile(art.convert("RGBA"))
    print(f"tile     : esquerda={tile[0]} topo={tile[1]} direita={tile[2]} base={tile[3]}")
    print(f"           {tile[2] - tile[0] + 1}x{tile[3] - tile[1] + 1} px")

    icon = build_icon(source, box)
    RESOURCES.mkdir(parents=True, exist_ok=True)

    png_path = RESOURCES / "edgemd.png"
    icon.save(png_path, "PNG", optimize=True)
    print(f"gerado   : {png_path.relative_to(ROOT)} ({CANONICAL_SIZE}x{CANONICAL_SIZE}, "
          f"cantos transparentes, {png_path.stat().st_size / 1024:.0f} KB)")

    if args.no_ico:
        return 0

    small = None if args.no_simplify_small else build_small_icon(icon)
    if small is not None:
        small_path = RESOURCES / "edgemd-small.png"
        small.save(small_path, "PNG", optimize=True)
        print(f"gerado   : {small_path.relative_to(ROOT)} (variante sem a assinatura, "
              f"para os tamanhos abaixo de {SMALL_ICON_THRESHOLD} px)")

    ico_path = RESOURCES / "edgemd.ico"
    # O Pillow monta o .ico a partir de várias imagens; a lista `append_images`
    # é que define o conteúdo de cada resolução. Passar a variante simplificada
    # nos tamanhos pequenos é o que faz o ícone ser legível na bandeja.
    base = small if small is not None else icon
    frames = [
        (small if small is not None and size < SMALL_ICON_THRESHOLD else icon).resize(
            (size, size), Image.LANCZOS
        )
        for size in ICO_SIZES
    ]
    frames[-1].save(
        ico_path,
        format="ICO",
        sizes=[(size, size) for size in ICO_SIZES],
        append_images=frames[:-1],
    )
    print(f"gerado   : {ico_path.relative_to(ROOT)} ({len(ICO_SIZES)} resoluções, "
          f"{ico_path.stat().st_size / 1024:.0f} KB, "
          f"{'com' if small is not None else 'sem'} variante simplificada)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
