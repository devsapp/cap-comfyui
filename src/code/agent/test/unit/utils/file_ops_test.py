import pytest
import shutil
from utils.file_ops import copy, move, remove, compress, extract


# 创建测试用的临时目录和文件
@pytest.fixture
def setup_test_files(tmp_path):
    # 创建源文件和目录
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    # 创建测试文件
    test_file = source_dir / "test.txt"
    test_file.write_text("test content")

    # 创建测试子目录
    test_subdir = source_dir / "subdir"
    test_subdir.mkdir()
    (test_subdir / "subfile.txt").write_text("subfile content")

    return tmp_path


def test_copy_file(setup_test_files):
    source_file = setup_test_files / "source" / "test.txt"
    target_file = setup_test_files / "target" / "test.txt"

    copy(str(source_file), str(target_file))

    assert target_file.exists()
    assert target_file.read_text() == "test content"


def test_copy_directory(setup_test_files):
    source_dir = setup_test_files / "source"
    target_dir = setup_test_files / "target"

    copy(str(source_dir), str(target_dir))

    assert target_dir.exists()
    assert (target_dir / "test.txt").exists()
    assert (target_dir / "subdir" / "subfile.txt").exists()


def test_move_file(setup_test_files):
    source_file = setup_test_files / "source" / "test.txt"
    target_file = setup_test_files / "target" / "test.txt"

    move(str(source_file), str(target_file))

    assert target_file.exists()
    assert not source_file.exists()
    assert target_file.read_text() == "test content"


def test_move_directory(setup_test_files):
    source_dir = setup_test_files / "source"
    target_dir = setup_test_files / "target"

    move(str(source_dir), str(target_dir))

    assert target_dir.exists()
    assert not source_dir.exists()
    assert (target_dir / "test.txt").exists()
    assert (target_dir / "subdir" / "subfile.txt").exists()


def test_remove_file(setup_test_files):
    test_file = setup_test_files / "source" / "test.txt"

    assert test_file.exists()
    remove(str(test_file))
    assert not test_file.exists()


def test_remove_directory(setup_test_files):
    source_dir = setup_test_files / "source"

    assert source_dir.exists()
    remove(str(source_dir))
    assert not source_dir.exists()


def test_remove_nonexistent_path(setup_test_files):
    nonexistent_path = setup_test_files / "nonexistent"

    # Should print message but not raise exception
    remove(str(nonexistent_path))


def test_compress_all_files(setup_test_files):
    source_dir = setup_test_files / "source"
    tar_file = setup_test_files / "test.tar"

    compress(str(tar_file), str(source_dir))

    assert tar_file.exists()


def test_compress_selected_files(setup_test_files):
    source_dir = setup_test_files / "source"
    tar_file = setup_test_files / "test.tar"

    compress(str(tar_file), str(source_dir), ["test.txt"])

    assert tar_file.exists()


def test_extract(setup_test_files):
    # 首先创建一个tar文件
    source_dir = setup_test_files / "source"
    tar_file = setup_test_files / "test.tar"
    output_dir = setup_test_files / "extracted"

    compress(str(tar_file), str(source_dir))
    extract(str(tar_file), str(output_dir))

    assert output_dir.exists()
    assert (output_dir / "test.txt").exists()
    assert (output_dir / "subdir" / "subfile.txt").exists()


def test_extract_to_default_location(setup_test_files):
    source_dir = setup_test_files / "source"
    tar_file = setup_test_files / "test.tar"

    compress(str(tar_file), str(source_dir))
    extract(str(tar_file))

    assert tar_file.parent.exists()
    assert (tar_file.parent / "test.txt").exists()
    assert (tar_file.parent / "subdir" / "subfile.txt").exists()


# 错误处理测试
def test_copy_nonexistent_source():
    with pytest.raises(Exception):
        copy("nonexistent_file", "target")


def test_move_nonexistent_source():
    with pytest.raises(Exception):
        move("nonexistent_file", "target")


def test_extract_nonexistent_tar():
    with pytest.raises(Exception):
        extract("nonexistent.tar")


# 清理函数
@pytest.fixture(autouse=True)
def cleanup(setup_test_files):
    yield
    # 测试后清理临时文件
    shutil.rmtree(setup_test_files)
