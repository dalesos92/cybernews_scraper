"""Inyecta logos BBVA como base64 en los templates y actualiza colores."""
import pathlib, re

logo_negro  = pathlib.Path("img/.logo_negro_b64.txt").read_text()
logo_blanco = pathlib.Path("img/.logo_blanco_b64.txt").read_text()

IMG_NEGRO  = f'<img src="{logo_negro}" alt="BBVA" height="36" style="display:block;margin-bottom:12px;" />'
IMG_BLANCO = f'<img src="{logo_blanco}" alt="BBVA" height="36" style="display:block;margin-bottom:12px;filter:brightness(10);" />'

# Patrón que detecta el bloque de texto "BBVA" (texto de placeholder italic)
PATTERN_BBVA_TEXT = re.compile(
    r'<p\s+style="[^"]*font-style:italic[^"]*">\s*BBVA\s*</p>',
    re.DOTALL
)

# También el bloque con letter-spacing en span
PATTERN_BBVA_SPAN = re.compile(
    r'<span\s+style="[^"]*letter-spacing:[^"]*font-style:italic[^"]*">\s*BBVA\s*</span>',
    re.DOTALL
)

# Footer pseudo-logo (texto BBVA en footer)
PATTERN_FOOTER_BBVA = re.compile(
    r'<strong\s+style="[^"]*font-style:italic[^"]*letter-spacing:[^"]*">\s*BBVA\s*</strong>',
    re.DOTALL
)
FOOTER_LOGO_SMALL = '<img src="{src}" alt="BBVA" height="18" style="vertical-align:middle;" />'

for tpl, logo_img, logo_src in [
    ("templates/email_bbva_a.html.j2", IMG_NEGRO,  logo_negro),
    ("templates/email_bbva_b.html.j2", IMG_BLANCO, logo_blanco),
    ("templates/email_bbva_c.html.j2", IMG_NEGRO,  logo_negro),
]:
    content = pathlib.Path(tpl).read_text(encoding="utf-8")

    # Sustituir placeholder de header
    content, n1 = PATTERN_BBVA_TEXT.subn(logo_img, content)
    content, n2 = PATTERN_BBVA_SPAN.subn(logo_img, content)

    # Sustituir pseudo-logo en footer
    footer_img = FOOTER_LOGO_SMALL.format(src=logo_src)
    content, n3 = PATTERN_FOOTER_BBVA.subn(footer_img, content)

    # Template C tiene el logo en un <td> con padding
    # Reemplazar bloque de texto en el logo-box del header
    content = re.sub(
        r'<span\s+style="color:#ffffff;font-size:\d+px;font-weight:900;'
        r'letter-spacing:\d+px;font-style:italic;">BBVA</span>',
        f'<img src="{logo_src}" alt="BBVA" height="28" '
        r'style="display:block;" />',
        content,
    )

    pathlib.Path(tpl).write_text(content, encoding="utf-8")
    print(f"{tpl}: header={n1+n2}, footer={n3}")

print("Logos inyectados correctamente.")
