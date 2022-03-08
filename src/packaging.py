import hashlib
import os
import shutil
import subprocess
from utils import write_cfg_file

CHUNK_SIZE = 4096


def create_deb_package(package_name, root_dir, base_dir):
    package_file = f"{package_name}.deb"
    debian_dir = os.path.join(base_dir, "DEBIAN")
    os.mkdir(debian_dir)
    os.chdir(debian_dir)

    os.chdir(root_dir)
    subprocess.check_output(f"dpkg-deb --build {root_dir}".split(), stderr=subprocess.STDOUT, shell=True)
    return package_file


def compute_check_sums(_file):
    with open(_file, mode="rb", buffering=0) as fp:
        md5_hash_func = hashlib.md5()
        sha256_hash_func = hashlib.sha256()
        buffer = fp.read(CHUNK_SIZE)
        while len(buffer) > 0:
            md5_hash_func.update(buffer)
            sha256_hash_func.update(buffer)
            buffer = fp.read(CHUNK_SIZE)
    return sha256_hash_func.digest().hex(), md5_hash_func.digest().hex()


def create_package(info: dict, _package_type: str, _src_dir: str, keep_storage_dir: bool) -> None:
    package_name = os.path.basename(_src_dir)
    root_dir = os.path.dirname(_src_dir)
    base_dir = os.path.relpath(_src_dir, root_dir)
    os.chdir(root_dir)
    if _package_type == "tgz":
        package_file = shutil.make_archive(package_name, 'gztar', root_dir=root_dir, base_dir=base_dir)
    elif _package_type == "zip":
        package_file = shutil.make_archive(package_name, 'zip', root_dir=root_dir, base_dir=base_dir)
    elif _package_type == "deb":
        package_file = create_deb_package(package_name, root_dir, base_dir)
    else:
        raise NotImplemented()
    sha256_check_sum, md5_check_sum = compute_check_sums(package_file)
    info.update({"sha256sum": sha256_check_sum,
                 "md5sum": md5_check_sum,
                 "file_name": os.path.basename(package_file),
                 "package_type": _package_type
                 })
    write_cfg_file(os.path.join(root_dir, f"{package_file}.info.json"), info, human_readable=True)
    if not keep_storage_dir:
        shutil.rmtree(_src_dir)
