"""
Renderização do Markdown do postmortem em PDF, usando fpdf2.

Implementamos um subconjunto simples de Markdown (o suficiente para o que o
prompt pede ao Claude para gerar):
  - `#`, `##`, `###`  -> cabeçalhos com fontes maiores/negrito
  - `- ` ou `* `      -> bullets com indentação
  - linha em branco    -> quebra de parágrafo
  - qualquer outra linha -> texto corrido, com word-wrap (via multi_cell)

Não usamos wkhtmltopdf/weasyprint para manter a imagem Docker simples (sem
dependências de sistema).
"""
import re
import tempfile
from datetime import datetime

from fpdf import FPDF

# fpdf2's core fonts (Helvetica/Times/Courier) only support Latin-1/WinAnsi.
# O Claude pode gerar aspas tipográficas, travessões "em-dash", elipses, etc.
# Normalizamos esses caracteres para equivalentes ASCII/Latin-1 antes de
# desenhar o PDF, para nunca quebrar a geração por um caractere fora do range.
_TYPOGRAPHIC_REPLACEMENTS = {
    "—": "-",   # em dash —
    "–": "-",   # en dash –
    "‘": "'",   # ‘
    "’": "'",   # ’
    "“": '"',   # “
    "”": '"',   # ”
    "…": "...",  # …
    "•": "-",   # • (já tratamos bullets manualmente, mas por segurança)
}

_BOLD_MARKER_RE = re.compile(r"\*\*(.*?)\*\*")


def _sanitize(text: str) -> str:
    for src, dst in _TYPOGRAPHIC_REPLACEMENTS.items():
        text = text.replace(src, dst)
    # Remove marcadores de negrito markdown (**texto**) mantendo o conteúdo,
    # já que o renderer não implementa negrito inline.
    text = _BOLD_MARKER_RE.sub(r"\1", text)
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text


class PostmortemPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Página {self.page_no()}", align="C")


def _render_markdown_body(pdf: PostmortemPDF, markdown_text: str) -> None:
    pdf.set_text_color(0, 0, 0)
    lines = markdown_text.splitlines()

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            pdf.ln(3)
            continue

        if stripped.startswith("### "):
            pdf.set_font("Helvetica", "B", 12)
            pdf.ln(2)
            pdf.multi_cell(0, 7, _sanitize(stripped[4:].strip()))
            pdf.ln(1)
            continue

        if stripped.startswith("## "):
            pdf.set_font("Helvetica", "B", 14)
            pdf.ln(3)
            pdf.multi_cell(0, 8, _sanitize(stripped[3:].strip()))
            pdf.ln(1)
            continue

        if stripped.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.ln(3)
            pdf.multi_cell(0, 9, _sanitize(stripped[2:].strip()))
            pdf.ln(1)
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            pdf.set_font("Helvetica", "", 11)
            bullet_text = _sanitize(stripped[2:].strip())
            indent = 6
            pdf.set_x(pdf.l_margin + indent)
            usable_width = pdf.w - pdf.r_margin - (pdf.l_margin + indent)
            pdf.multi_cell(usable_width, 6, f"- {bullet_text}")
            continue

        # Texto corrido (parágrafo normal), com word-wrap.
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6, _sanitize(stripped))


def render_postmortem_pdf(
    markdown_text: str,
    alertname: str,
    app: str,
    summary: str,
) -> str:
    """
    Gera o PDF do postmortem e retorna o caminho do arquivo temporário criado.
    O chamador é responsável por remover o arquivo após o uso (ex.: após o
    upload para o Discord).
    """
    pdf = PostmortemPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)

    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # --- Capa / cabeçalho ---
    pdf.set_font("Helvetica", "B", 18)
    title = _sanitize(f"Postmortem — {alertname} — {app}")
    pdf.multi_cell(0, 10, title)
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 6, f"Gerado em: {generated_at}", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "Resumo do alerta original:", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, _sanitize(summary or "(sem resumo fornecido pelo alerta)"))
    pdf.ln(4)

    # Linha separadora simples entre a capa e o corpo do RCA.
    pdf.set_draw_color(180, 180, 180)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(6)

    # --- Corpo do postmortem (Markdown gerado pelo Claude) ---
    _render_markdown_body(pdf, markdown_text)

    tmp = tempfile.NamedTemporaryFile(prefix="postmortem_", suffix=".pdf", delete=False)
    tmp_path = tmp.name
    tmp.close()
    pdf.output(tmp_path)
    return tmp_path
