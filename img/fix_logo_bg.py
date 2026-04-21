"""Añade fondo blanco al logo en los 3 templates BBVA."""
import pathlib, re

# Patrón: img del logo en el header (height="36", margin-bottom)
# Reemplaza el estilo de la img para que tenga background blanco + padding
PATTERN_LOGO_HEADER = re.compile(
    r'(<img src="data:image/jpeg[^"]*" alt="BBVA" height="36" style=")([^"]*)("/>|" />)'
)

def wrap_logo(style: str) -> str:
    """Añade background blanco, padding y border-radius al logo."""
    # Eliminar cualquier background previo
    style = re.sub(r'background:[^;]+;?\s*', '', style)
    style = re.sub(r'filter:[^;]+;?\s*', '', style)  # quitar filter:brightness
    style = style.strip().rstrip(';')
    return style + ";background:#ffffff;padding:5px 12px;border-radius:4px;"

for tpl in [
    "templates/email_bbva_a.html.j2",
    "templates/email_bbva_b.html.j2",
    "templates/email_bbva_c.html.j2",
]:
    content = pathlib.Path(tpl).read_text(encoding="utf-8")

    def replace_logo(m):
        new_style = wrap_logo(m.group(2))
        return f'{m.group(1)}{new_style}" />'

    new_content, n = PATTERN_LOGO_HEADER.subn(replace_logo, content)
    pathlib.Path(tpl).write_text(new_content, encoding="utf-8")
    print(f"{tpl}: {n} logos actualizados")

print("Listo.")
