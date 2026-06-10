from taobao_image_saver.storage.file_names import sanitize_file_name, unique_dir


def test_sanitize_file_name_handles_empty_and_invalid_chars() -> None:
    assert sanitize_file_name("") == "untitled"
    assert sanitize_file_name('  a<b>c:"d"/e\\f|g?*  ') == "a_b_c__d__e_f_g__"


def test_sanitize_file_name_handles_reserved_names_and_length() -> None:
    assert sanitize_file_name("CON") == "CON_"
    assert sanitize_file_name("x" * 120, max_length=10) == "x" * 10


def test_unique_dir_adds_suffix_for_existing_dir(tmp_path) -> None:
    (tmp_path / "商品").mkdir()
    assert unique_dir(tmp_path, "商品").name == "商品-2"

