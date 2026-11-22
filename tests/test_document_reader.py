import pymupdf
import pytest

from core.tools.document_reader import (
    DocumentReadError,
    DocumentReadResult,
    LocalDocumentReader,
)


def make_pdf(pages):
    """Build a PDF in memory; each item is the text of one page ('' = blank)."""
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture
def reader(tmp_path):
    return LocalDocumentReader(tmp_path)


def store(tmp_path, name, data):
    (tmp_path / name).write_bytes(data)
    return name


def test_reads_valid_pdf(tmp_path, reader):
    ref = store(tmp_path, "a.pdf", make_pdf(["First page", "Second page"]))

    result = reader.read(ref)

    assert isinstance(result, DocumentReadResult)
    assert result.format == "pdf"
    assert result.page_count == 2
    assert "First page" in result.text
    assert "Second page" in result.text


def test_reads_utf8_txt(tmp_path, reader):
    ref = store(tmp_path, "a.txt", "Привет, мир!\nSecond line".encode("utf-8"))

    result = reader.read(ref)

    assert result == DocumentReadResult(
        text="Привет, мир!\nSecond line", page_count=None, format="txt"
    )


def test_txt_bom_is_dropped(tmp_path, reader):
    ref = store(tmp_path, "bom.txt", b"\xef\xbb\xbfhello")

    assert reader.read(ref).text == "hello"


def test_corrupted_pdf(tmp_path, reader):
    ref = store(tmp_path, "bad.pdf", b"%PDF-1.4\nthis is not a real pdf body")

    with pytest.raises(DocumentReadError) as error:
        reader.read(ref)

    assert error.value.code == "DOCUMENT_CORRUPTED"


def test_truncated_pdf(tmp_path, reader):
    ref = store(tmp_path, "cut.pdf", make_pdf(["Some text"])[:60])

    with pytest.raises(DocumentReadError) as error:
        reader.read(ref)

    assert error.value.code == "DOCUMENT_CORRUPTED"


def test_pdf_without_text_layer_is_read_with_empty_text(tmp_path, reader):
    ref = store(tmp_path, "scan.pdf", make_pdf([""]))

    result = reader.read(ref)

    assert result.page_count == 1
    assert result.text.strip() == ""


def test_binary_file_is_unsupported_format(tmp_path, reader):
    ref = store(tmp_path, "tool.exe", b"MZ\x90\x00\xff\xfe\x00\x80binary")

    with pytest.raises(DocumentReadError) as error:
        reader.read(ref)

    assert error.value.code == "UNSUPPORTED_FORMAT"


def test_non_utf8_txt_is_unsupported_format(tmp_path, reader):
    ref = store(tmp_path, "cp1251.txt", "Привет".encode("cp1251"))

    with pytest.raises(DocumentReadError) as error:
        reader.read(ref)

    assert error.value.code == "UNSUPPORTED_FORMAT"


def test_missing_document(reader):
    with pytest.raises(DocumentReadError) as error:
        reader.read("documents/missing")

    assert error.value.code == "DOCUMENT_READ_FAILED"


def test_reference_outside_storage_is_rejected(tmp_path):
    (tmp_path / "secret.txt").write_text("secret")
    storage = tmp_path / "storage"
    storage.mkdir()

    with pytest.raises(DocumentReadError) as error:
        LocalDocumentReader(storage).read("../secret.txt")

    assert error.value.code == "DOCUMENT_READ_FAILED"
    assert "secret" not in error.value.message


def test_directory_is_a_read_failure(tmp_path, reader):
    (tmp_path / "folder").mkdir()

    with pytest.raises(DocumentReadError) as error:
        reader.read("folder")

    assert error.value.code == "DOCUMENT_READ_FAILED"


def test_password_protected_pdf(tmp_path, reader):
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "secret")
    data = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw"
    )
    document.close()
    ref = store(tmp_path, "locked.pdf", data)

    with pytest.raises(DocumentReadError) as error:
        reader.read(ref)

    assert error.value.code == "DOCUMENT_READ_FAILED"
