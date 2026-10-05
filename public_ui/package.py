"""Only the public projection is readable. No local-source fallback."""
from __future__ import annotations
import gzip
import io
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from .schema import PublicDataError,VERSION,RELEASE,relative_name,validate

ROOT=Path(__file__).resolve().parents[1]

def digest(raw):return hashlib.sha256(raw).hexdigest()

def safe_file(root,name):
    relative_name(name)
    base=Path(root).resolve();path=(base/name).resolve()
    if not path.is_relative_to(base) or not path.is_file():raise PublicDataError("公开工件不可读取")
    return path

def read_bytes(path):
    try:return path.read_bytes()
    except OSError:raise PublicDataError("公开工件不可读取") from None

class PublicPackage:
    def __init__(self,root=ROOT):
        self.root=Path(root).resolve()
        try:
            self.anchor=json.loads(read_bytes(safe_file(self.root,"config/PUBLIC_PACKAGE_ANCHOR.json")))
            if set(self.anchor)!={"schema_version","release_id","package_path","manifest_sha256","profile_sha256"}:
                raise PublicDataError("公开锚点字段不匹配")
            if self.anchor["schema_version"]!=VERSION or self.anchor["release_id"]!=RELEASE:
                raise PublicDataError("公开锚点版本不匹配")
            self.base=safe_file(self.root,self.anchor["package_path"]+"/manifest.json").parent
            raw=read_bytes(self.base/"manifest.json")
            if digest(raw)!=self.anchor["manifest_sha256"]:raise PublicDataError("公开包指纹不匹配")
            profile=read_bytes(safe_file(self.root,"config/public_profile.json"))
            if digest(profile)!=self.anchor["profile_sha256"]:raise PublicDataError("发布规格指纹不匹配")
            self.manifest=json.loads(raw)
            if set(self.manifest)!={"schema_version","release_id","scope","files","source_anchors","business_recalculated"}:
                raise PublicDataError("公开manifest字段不匹配")
            if self.manifest["release_id"]!=RELEASE or self.manifest["business_recalculated"] is not False:
                raise PublicDataError("公开包身份不匹配")
            self.files=self.manifest["files"]
            for name,item in self.files.items():
                relative_name(name)
                if set(item)!={"sha256","kind","uncompressed_sha256"}:raise PublicDataError("公开文件登记无效")
        except (ValueError,KeyError,TypeError) as exc:
            if isinstance(exc,PublicDataError):raise
            raise PublicDataError("公开包结构无效") from None

    def read(self,name):return _read(self,str(name))

    def all_valid(self):
        for name in self.files:self.read(name)
        return len(self.files)

@lru_cache(maxsize=10)
def _read(package,name):
    if name not in package.files:raise PublicDataError("未登记公开工件")
    item=package.files[name];raw=read_bytes(safe_file(package.base,name))
    if digest(raw)!=item["sha256"]:raise PublicDataError("公开工件指纹不匹配")
    try:
        if name.endswith(".gz"):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                decoded=stream.read(24000001)
        else:decoded=raw
        if len(decoded)>24000000:raise PublicDataError("公开工件解码体积越界")
        if digest(decoded)!=item["uncompressed_sha256"]:raise PublicDataError("公开内容指纹不匹配")
        value=json.loads(decoded);validate(value,item["kind"])
        return value
    except (OSError,EOFError,ValueError,TypeError) as exc:
        if isinstance(exc,PublicDataError):raise
        raise PublicDataError("公开内容校验失败") from None

@lru_cache(maxsize=1)
def get_package():return PublicPackage()
