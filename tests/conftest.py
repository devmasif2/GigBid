import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


@pytest.fixture
def make_text_pdf():
    def make_pdf(*pages: str, encrypted: bool = False) -> bytes:
        writer = PdfWriter()
        for text in pages:
            page = writer.add_blank_page(width=612, height=792)
            font = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content = DecodedStreamObject()
            content.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
            page.replace_contents(content)
        if encrypted:
            writer.encrypt("test-password")
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    return make_pdf
