"""
RAG 检索增强：医疗知识库 + 向量检索（零第三方依赖，只用标准库 + httpx）

设计取舍
--------
本机沙箱禁止 pip 安装，langchain / chromadb / numpy 均不可用，
因此按 LangChain 的五个核心抽象自行实现等价能力，接口命名保持一致，
后续接入官方库时可直接替换同名对象，业务代码零改动：

    LangChain             本模块
    ---------             ------------
    Document              Document           文档与元数据
    RecursiveTextSplitter split_text()       语义化切块
    Embeddings            Embeddings         向量化（远端 / 本地降级双通道）
    VectorStore           VectorStore        向量持久化 + 相似度检索
    Retriever             get_retriever()    检索器

向量化双通道
    primary  阿里云 text-embedding-v3（OpenAI 兼容 /embeddings，1024 维）
    fallback 本地字符 bi-gram 哈希向量（256 维），无网无 key 也能跑

两者维度不同，各自独立建库（靠 dim 字段隔离），检索时按通道匹配，
不会出现跨空间比较导致的乱序。
"""
import os
import re
import json
import math
import struct
import array
import hashlib
import urllib.request
from dataclasses import dataclass, field

import db

ROOT = os.path.dirname(os.path.abspath(__file__))
KB_DIR = os.path.join(ROOT, "kb")

CHUNK_SIZE = 320      # 单块目标字数
CHUNK_OVERLAP = 60    # 相邻块重叠字数，避免切断语义
TOP_K = 3             # 默认召回条数
MIN_SCORE = 0.32      # 低于此相关度视为未命中，不注入上下文

EMB_MODEL = os.environ.get("EMB_MODEL", "text-embedding-v3")
EMB_DIM = 1024
EMB_BATCH = 10        # 阿里云单次最多 25 条，取 10 稳妥
EMB_TIMEOUT = 20

_LOCAL_DIM = 256      # 本地降级向量维度

EMB_LAST = {"ok": None, "mode": "", "err": ""}


# ==================== 1. Document ====================
@dataclass
class Document:
    """一条待入库的文本片段"""
    text: str
    meta: dict = field(default_factory=dict)


# ==================== 2. 文本切块 ====================
def _clean(t):
    t = t.replace("\r\n", "\n").replace("\u3000", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def split_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """按 markdown 小节优先切块：先按 ## 切，超长再按句号切，仍超长才硬切。
    保留标题前缀，保证每个 chunk 自带主题，脱离原文也可独立理解。"""
    text = _clean(text)
    parts, buf = [], ""
    for seg in re.split(r"\n(?=#{1,3} )", text):
        seg = seg.strip()
        if not seg:
            continue
        title = seg.split("\n", 1)[0].lstrip("# ").strip()
        body = seg
        if len(body) <= size:
            parts.append(body)
            continue
        # 超长小节：按句子累积
        cur = ""
        for sent in re.split(r"(?<=[。！？；\n])", body):
            if not sent.strip():
                continue
            if len(cur) + len(sent) > size and cur:
                parts.append(cur.strip())
                cur = (cur[-overlap:] if overlap else "") + sent   # 尾部重叠
            else:
                cur += sent
        if cur.strip():
            parts.append(cur.strip())
        _ = title
    # 兜底：仍超长的硬切
    out = []
    for p in parts:
        while len(p) > size * 2:
            out.append(p[:size])
            p = p[size - overlap:]
        if p.strip():
            out.append(p.strip())
    return out


def load_kb(kb_dir=KB_DIR):
    """加载知识库目录下所有 .md / .txt 文件"""
    docs = []
    if not os.path.isdir(kb_dir):
        return docs
    for fn in sorted(os.listdir(kb_dir)):
        if not fn.lower().endswith((".md", ".txt")):
            continue
        path = os.path.join(kb_dir, fn)
        raw = open(path, encoding="utf-8").read()
        for i, chunk in enumerate(split_text(raw)):
            docs.append(Document(chunk, {"src": fn, "seq": i}))
    return docs


# ==================== 3. Embeddings ====================
def _cfg(names, default=""):
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    env_file = os.path.join(ROOT, ".env")
    if os.path.exists(env_file):
        for line in open(env_file, encoding="utf-8"):
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() in names:
                return v.strip().strip('"').strip("'")
    return default


def _emb_endpoint():
    key = _cfg(("QINAWEN_API_KEY", "QIANWEN_API_KEY", "DASHSCOPE_API_KEY"))
    base = _cfg(("QINAWEN_BASE_URL", "QIANWEN_BASE_URL", "DASHSCOPE_BASE_URL"),
                "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return key, base + "/embeddings"


def _remote_embed(texts):
    """阿里云 text-embedding-v3，返回 (向量列表, 错误信息)"""
    key, url = _emb_endpoint()
    if not key:
        return None, "未配置 API_KEY"
    out = []
    for i in range(0, len(texts), EMB_BATCH):
        batch = texts[i: i + EMB_BATCH]
        body = json.dumps({"model": EMB_MODEL, "input": batch,
                           "encoding_format": "float"}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(req, timeout=EMB_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            out.extend([d["embedding"] for d in data["data"]])
        except Exception as e:
            return None, str(e)[:160]
    return out, ""


def _local_embed(texts):
    """本地降级向量：字符 bi-gram 哈希 + TF 权重，再 L2 归一化。
    不追求语义精度，只保证无网无 key 时检索链路仍然可用。"""
    vecs = []
    for t in texts:
        v = [0.0] * _LOCAL_DIM
        t = re.sub(r"\s+", "", t)
        grams = [t[i: i + 2] for i in range(max(0, len(t) - 1))] or [t]
        for g in grams:
            h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
            v[h % _LOCAL_DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        vecs.append([x / n for x in v])
    return vecs


def embed(texts):
    """统一向量化入口：远端优先，失败自动降级本地。返回 (向量列表, 通道名)"""
    texts = [t if t.strip() else " " for t in texts]
    vecs, err = _remote_embed(texts)
    if vecs and len(vecs) == len(texts):
        EMB_LAST.update(ok=True, mode="remote", err="")
        return vecs, "remote"
    EMB_LAST.update(ok=False, mode="local", err=err)
    if err:
        try:
            import core
            core.log.warning("embed_fallback err=%s", err)
        except Exception:
            pass
    return _local_embed(texts), "local"


def _pack(vec):
    return struct.pack("<%df" % len(vec), *vec)


def _unpack(blob):
    a = array.array("f")
    a.frombytes(blob)
    return a


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


# ==================== 4. VectorStore ====================
DDL = """CREATE TABLE IF NOT EXISTS kb_chunks(id INTEGER PRIMARY KEY AUTOINCREMENT,
  src TEXT, seq INT, text TEXT, dim INT, mode TEXT, vec BLOB, hash TEXT, updated TEXT);"""


def init_schema():
    db.init_schema(DDL)
    db.exec_script("CREATE INDEX IF NOT EXISTS idx_kb_dim ON kb_chunks(dim, mode)")


def _h(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def build(force=False, kb_dir=KB_DIR):
    """全量重建索引。force=False 时按内容哈希跳过未变更的块（增量更新）"""
    init_schema()
    docs = load_kb(kb_dir)
    if not docs:
        return {"ok": False, "msg": "知识库目录为空：%s" % kb_dir}

    old = {r["hash"]: r for r in db.rows("SELECT hash, dim, mode FROM kb_chunks")}
    todo = [d for d in docs if force or _h(d.text) not in old]
    if not todo:
        stat = db.one("SELECT COUNT(*) AS n FROM kb_chunks")
        return {"ok": True, "msg": "索引已是最新", "chunks": int((stat or {}).get("n") or 0),
                "skipped": len(docs), "build": 0}

    vecs, mode = embed([d.text for d in todo])
    dim = len(vecs[0])
    ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if force or len(todo) == len(docs):
        db.exec_script("DELETE FROM kb_chunks")
    for d, v in zip(todo, vecs):
        db.exec_script(
            "INSERT INTO kb_chunks(src,seq,text,dim,mode,vec,hash,updated) VALUES(?,?,?,?,?,?,?,?)",
            (d.meta.get("src"), d.meta.get("seq"), d.text, dim, mode, _pack(v), _h(d.text), ts))
    stat = db.one("SELECT COUNT(*) AS n FROM kb_chunks")
    return {"ok": True, "msg": "索引构建完成", "chunks": int((stat or {}).get("n") or 0),
            "build": len(todo), "dim": dim, "mode": mode, "docs": len({d.meta.get("src") for d in docs})}


def search(query, k=TOP_K, min_score=MIN_SCORE):
    """相似度检索：向量已 L2 归一化，点积即余弦相似度"""
    init_schema()
    qv, mode = embed([query])
    qv = qv[0]
    dim = len(qv)
    cands = db.rows("SELECT id, src, seq, text, vec FROM kb_chunks WHERE dim=? AND mode=?",
                    (dim, mode))
    if not cands:
        return []
    scores = []
    for r in cands:
        s = _dot(qv, _unpack(r["vec"]))
        if s >= min_score:
            scores.append((s, r))
    scores.sort(key=lambda x: -x[0])
    return [{"score": round(s, 4), "src": r["src"], "seq": r["seq"], "text": r["text"]}
            for s, r in scores[:k]]


# ==================== 5. Retriever / Chain ====================
def build_context(query, k=TOP_K, min_score=MIN_SCORE):
    """检索并拼装上下文，供 prompt 注入。未命中返回 ('', [])"""
    hits = search(query, k, min_score)
    if not hits:
        return "", []
    ctx = "\n\n".join("【资料%d｜%s】\n%s" % (i + 1, h["src"], h["text"])
                      for i, h in enumerate(hits))
    return ctx, hits


def status():
    """检索链路自检，用于 /api/rag/status"""
    try:
        init_schema()
        n = int((db.one("SELECT COUNT(*) AS n FROM kb_chunks") or {}).get("n") or 0)
        modes = [r["mode"] for r in db.rows("SELECT DISTINCT mode FROM kb_chunks")]
    except Exception as e:
        return {"ok": False, "msg": str(e)[:200]}
    return {"ok": True, "chunks": n, "index_modes": modes, "embed_model": EMB_MODEL,
            "last_embed": EMB_LAST, "kb_dir": KB_DIR,
            "kb_files": len([f for f in os.listdir(KB_DIR)
                             if f.lower().endswith((".md", ".txt"))]) if os.path.isdir(KB_DIR) else 0}


if __name__ == "__main__":
    print(json.dumps(build(force=True), ensure_ascii=False, indent=2))
    for q in ["发烧到39度怎么办", "吃完头孢能喝酒吗", "孩子拉肚子脱水"]:
        print("\nQ:", q)
        for h in search(q):
            print("  %.3f  %s  %s" % (h["score"], h["src"], h["text"][:60].replace("\n", " ")))
