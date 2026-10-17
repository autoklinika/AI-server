"""Fail-closed, interruption-safe journal for long Vision PCB inference runs.

No dependencies on ML runtimes. The finished JSONL is emitted only with exact
coverage of the requested split and is never overwritten with differing bytes.
"""
from __future__ import annotations
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path

def sha256_bytes(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(2**20), b""):
            h.update(chunk)
    return h.hexdigest()

def encode(obj)->bytes:
    return (json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")

def immutable(path:Path,data:bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=data:raise FileExistsError(f"immutable artifact changed: {path}")
        return
    with path.open("xb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())

def atomic_record(path:Path,data:bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise FileExistsError(f"sample already exists: {path}")
    tmp=path.with_name(path.name+".pending")
    if tmp.exists():tmp.unlink()
    with tmp.open("xb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    # exclusive per-process file lock is held by caller
    if path.exists():raise FileExistsError(f"concurrent commit: {path}")
    os.replace(tmp,path)

class Journal:
    def __init__(self,dir:Path,config:dict,split_ids:set[str],model_id:str="winclip"):
        self.dir=dir
        self.config=config
        self.split_ids=set(split_ids)
        self.model_id=model_id
        if not split_ids:raise ValueError("no expected samples")
        self.dir.mkdir(parents=True,exist_ok=True)
        self.lock=(self.dir/".lock").open("a+b")
        try:
            fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("another inference process owns this journal")
        try:
            immutable(self.dir/"config.json",encode(config))
            (self.dir/"records").mkdir(exist_ok=True)
        except Exception:
            self.close()
            raise

    def path(self,sid:str)->Path:
        if not sid or not isinstance(sid,str):raise ValueError("sample id required")
        return self.dir/"records"/(hashlib.sha256(sid.encode()).hexdigest()+".json")

    def read(self,sid:str):
        file=self.path(sid)
        if not file.exists():return None
        row=json.loads(file.read_text(encoding="utf-8"))
        self.validate_record(row,sid)
        if self.config.get("anomaly_map_resolution"):
            mapfile=self.dir/"maps"/(hashlib.sha256(sid.encode()).hexdigest()+".npz")
            if not mapfile.is_file() or row.get("map_sha256")!=sha256_file(mapfile):
                raise ValueError("missing or corrupted anomaly map for: "+sid)
        return row

    def validate_record(self,row:dict,sid:str):
        if row.get("sample_id")!=sid or sid not in self.split_ids:
            raise ValueError("record identity mismatch")
        if row.get("model_id")!=self.model_id or row.get("localization_mode")!="none" or row.get("regions")!=[]:
            raise ValueError("record contract mismatch")
        score=row.get("image_score")
        if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:
            raise ValueError("invalid anomaly score")
        if not isinstance(row.get("image_sha256"),str) or len(row["image_sha256"])!=64:
            raise ValueError("missing source image digest")
        if row.get("preprocessing_mode")!=self.config["preprocessing_mode"]:
            raise ValueError("record preprocessing mismatch")

    def write(self,row:dict):
        sid=row["sample_id"]
        self.validate_record(row,sid)
        atomic_record(self.path(sid),encode(row))

    def finished(self):
        for item in (self.dir/"records").glob("*.json"):
            row=json.loads(item.read_text())
            sid=row.get("sample_id")
            if sid not in self.split_ids or item!=self.path(sid):
                raise ValueError(f"unexpected cached result {item}")
            self.validate_record(row,sid)
        rows=[]
        for sid in sorted(self.split_ids):
            cached=self.read(sid)
            if cached is None:return None
            rows.append({key:cached[key] for key in ("sample_id","model_id","image_score","localization_mode","regions")})
        return rows

    def finalize(self):
        rows=self.finished()
        if rows is None:return False
        out=b"".join(encode(row) for row in rows)
        immutable(self.dir/"predictions.jsonl",out)
        immutable(self.dir/"predictions.sha256", (sha256_bytes(out)+"\n").encode())
        return True

    def progress(self):
        observed=sum(1 for sid in self.split_ids if self.path(sid).exists())
        return observed,len(self.split_ids)

    def close(self):
        fcntl.flock(self.lock,fcntl.LOCK_UN)
        self.lock.close()
