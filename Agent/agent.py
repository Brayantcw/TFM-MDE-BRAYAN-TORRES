"""
Medical RAG with LM Studio Integration
- Papers: Weaviate retrieval (MedicalResearch) + LM Studio for answers
- Similar Patients: Weaviate retrieval (DiabetesPatients) + LM Studio cohort summary + Treatment Audit
"""

import os
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse
from dataclasses import dataclass

import requests
import streamlit as st
import weaviate
import weaviate.classes as wvc
from weaviate.classes.init import AdditionalConfig, Timeout
from sentence_transformers import SentenceTransformer


# ---------------------------
# Utils
# ---------------------------
def strip_reasoning(text: str) -> str:
    """Remove hidden chain-of-thought and thinking patterns."""
    if not text:
        return ""
    # Remove <think> tags
    text = re.sub(r"(?is)<\s*think\s*>.*?<\s*/\s*think\s*>", "", text)
    text = re.sub(r"(?is)<\s*/?\s*think\s*>", "", text)
    # Remove common thinking patterns at the start
    thinking_patterns = [
        r"(?is)^(okay|alright|so|let me|let's|first|i need to|i'll).*?(?=\[BEGIN|Based on|According to|\n\n)",
        r"(?is)^.*?(checking|looking at|analyzing|reviewing).*?(?=\[BEGIN|Based on|According to|\n\n)",
    ]
    for pattern in thinking_patterns:
        text = re.sub(pattern, "", text)
    return text.strip()


def extract_final_answer(text: str) -> str:
    """Extract content strictly between [BEGIN ANSWER] and [END ANSWER]."""
    if not text:
        return ""
    patterns = [
        r"(?is)\[BEGIN\s+ANSWER\](.*?)(?:\[END\s+ANSWER\]|$)",
        r"(?is)\[BEGIN ANSWER\](.*?)(?:\[END ANSWER\]|$)",
        r"(?is)BEGIN ANSWER:?\s*(.*?)(?:END ANSWER|$)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            answer = m.group(1).strip()
            if answer and len(answer) > 20:
                return answer
    return ""


def render_scrollable_markdown(title: str, content: str, key_prefix: str):
    st.subheader(title)
    if content and content.strip():
        st.code(content, language="markdown")
        st.download_button(f"Download (.md)", content, file_name=f"{key_prefix}.md", key=f"dl_{key_prefix}")
    else:
        st.caption("No content.")


# ---------------------------
# Lightweight reranker (optional)
# ---------------------------
class SimpleReranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, docs: List[Dict], top_k: int) -> List[Dict]:
        pairs = [(query, f"{d.get('title','')} {d.get('abstract','')}") for d in docs]
        scores = self.model.predict(pairs).tolist()
        for d, s in zip(docs, scores):
            d["_rr"] = float(s)
        docs.sort(key=lambda x: x.get("_rr", 0.0), reverse=True)
        return docs[:top_k]


# ---------------------------
# Treatment audit (rule-based heuristics, not medical advice)
# ---------------------------
@dataclass
class AuditResult:
    status: str              # "ok" | "missing_indication" | "caution" | "contra"
    reasons: List[str]
    positives: List[str]
    negatives: List[str]

class TreatmentAuditor:
    # Add common brand names (lowercased)
    SGLT2 = {
        "empagliflozin","dapagliflozin","canagliflozin","ertugliflozin",
        "jardiance","farxiga","invokana","steglatro"
    }
    GLP1  = {
        "semaglutide","liraglutide","dulaglutide","exenatide","lixisenatide","tirzepatide",
        "ozempic","rybelsus","wegovy","trulicity","victoza","byetta","bydureon","lyxumia","mounjaro","zepbound"
    }
    MET   = {"metformin","glucophage"}
    TZD   = {"pioglitazone","rosiglitazone","actos","avandia"}
    SU    = {"glimepiride","glipizide","glyburide","glibenclamide","gliclazide"}
    DPP4  = {"sitagliptin","saxagliptin","linagliptin","alogliptin","januvia","onglyza","tradjenta","nesina"}

    ASCVD_KEYS = {"ascvd","cad","coronary","mi","myocardial infarction","stroke","cva","tia","pad","peripheral artery"}
    HF_KEYS    = {"hf","hfrEF".lower(),"hfpef","heart failure"}
    CKD_KEYS   = {"ckd","nephropathy","albuminuria","proteinuria","esrd","dialysis","kidney disease"}
    RET_KEYS   = {"retinopathy","pdr","proliferative retinopathy"}

    def __init__(self, elderly_age: int = 75):
        self.elderly_age = elderly_age
        self._rank = {"ok":0, "missing_indication":1, "caution":2, "contra":3}

    @staticmethod
    def _norm_list(xs):
        return [str(x).strip().lower() for x in (xs or []) if x is not None]

    @staticmethod
    def _has_any(text: str, keys: set) -> bool:
        t = (text or "").lower()
        return any(k in t for k in keys)

    def _has_comorb(self, patient: dict, keys: set) -> bool:
        comps = self._norm_list(patient.get("complications", []))
        if any(self._has_any(c, keys) for c in comps):
            return True
        return self._has_any(patient.get("clinical_summary",""), keys)

    def _has_med_from(self, meds_norm: List[str], bag: set) -> bool:
        return any(m in bag or any(m.startswith(x) or x in m for x in bag) for m in meds_norm)

    def audit_patient(self, p: dict) -> AuditResult:
        reasons, positives, negatives = [], [], []
        worst = "ok"

        try: age = int(float(p.get("age") or 0))
        except: age = 0
        try: a1c = float(p.get("hba1c_current") or 0.0)
        except: a1c = 0.0
        try: egfr = float(p.get("egfr") or 0.0)
        except: egfr = 0.0
        meds  = self._norm_list(p.get("medications", []))

        has_sglt2 = self._has_med_from(meds, self.SGLT2)
        has_glp1  = self._has_med_from(meds, self.GLP1)
        has_met   = self._has_med_from(meds, self.MET)
        has_tzd   = self._has_med_from(meds, self.TZD)
        has_su    = self._has_med_from(meds, self.SU)

        has_ckd = (egfr and egfr <= 60) or self._has_comorb(p, self.CKD_KEYS)
        has_hf  = self._has_comorb(p, self.HF_KEYS)
        has_ascvd = self._has_comorb(p, self.ASCVD_KEYS)
        has_ret = self._has_comorb(p, self.RET_KEYS)

        # Contraindications / strong cautions
        if egfr and egfr < 30 and has_met:
            negatives.append("Metformin with eGFR <30 (contraindication).")
            worst = "contra"
        elif 30 <= egfr < 45 and has_met:
            negatives.append("Metformin with eGFR 30–44 (use lower dose/monitor).")
            worst = "caution" if self._rank["caution"] > self._rank[worst] else worst

        if has_hf and has_tzd:
            negatives.append("TZD in heart failure (fluid retention risk).")
            worst = "contra" if self._rank["contra"] > self._rank[worst] else worst

        if age >= self.elderly_age and has_su:
            negatives.append("Sulfonylurea in elderly (hypoglycemia risk).")
            worst = "caution" if self._rank["caution"] > self._rank[worst] else worst

        if has_ret and has_glp1 and ("semaglutide" in meds or "ozempic" in meds or "rybelsus" in meds or "wegovy" in meds):
            negatives.append("Semaglutide + retinopathy: monitor for early worsening with rapid A1c drop.")
            worst = "caution" if self._rank["caution"] > self._rank[worst] else worst

        # Positive signals
        if has_ckd and has_sglt2:
            positives.append("CKD present and on SGLT2 inhibitor (renal/CV benefit signal).")
        if has_hf and has_sglt2:
            positives.append("HF present and on SGLT2 inhibitor (HF hospitalization reduction).")
        if has_ascvd and (has_sglt2 or has_glp1):
            positives.append("ASCVD present and on GLP-1 RA/SGLT2 (MACE benefit signal).")

        # Missing indications
        if has_ckd and not has_sglt2:
            reasons.append("CKD without SGLT2 inhibitor (consider if not contraindicated).")
            worst = "missing_indication" if self._rank["missing_indication"] > self._rank[worst] else worst

        if has_hf and not has_sglt2:
            reasons.append("HF without SGLT2 inhibitor (consider if not contraindicated).")
            worst = "missing_indication" if self._rank["missing_indication"] > self._rank[worst] else worst

        if has_ascvd and not (has_glp1 or has_sglt2):
            reasons.append("ASCVD without GLP-1 RA/SGLT2 (consider if not contraindicated).")
            worst = "missing_indication" if self._rank["missing_indication"] > self._rank[worst] else worst

        if a1c >= 9 and not has_glp1 and not has_sglt2:
            reasons.append("A1c ≥9% without potent add-on therapy flagged.")
            worst = "missing_indication" if self._rank["missing_indication"] > self._rank[worst] else worst

        details = []
        if positives: details += [f"✔️ {s}" for s in positives]
        if negatives: details += [f"⚠️ {s}" for s in negatives]
        if reasons:   details += [f"🔎 {s}" for s in reasons]
        return AuditResult(status=worst, reasons=details, positives=positives, negatives=negatives)

    def cohort_summary(self, cohort: List[dict]) -> dict:
        counts = {"ok":0, "missing_indication":0, "caution":0, "contra":0}
        pos = {"ckd+sglt2":0, "hf+sglt2":0, "ascvd+cv_agent":0}
        neg = {"met_eGFR<30":0, "tzd_hf":0, "su_elderly":0}
        per_patient = []
        for p in cohort:
            ar = self.audit_patient(p)
            counts[ar.status] += 1
            if any("CKD present and on SGLT2" in s for s in ar.positives): pos["ckd+sglt2"] += 1
            if any("HF present and on SGLT2" in s for s in ar.positives):  pos["hf+sglt2"] += 1
            if any("ASCVD present and on GLP-1 RA/SGLT2" in s for s in ar.positives): pos["ascvd+cv_agent"] += 1
            if any("Metformin with eGFR <30" in s for s in ar.negatives): neg["met_eGFR<30"] += 1
            if any("TZD in heart failure" in s for s in ar.negatives):     neg["tzd_hf"] += 1
            if any("Sulfonylurea in elderly" in s for s in ar.negatives):  neg["su_elderly"] += 1
            per_patient.append(ar)
        return {"counts":counts, "positives":pos, "negatives":neg, "per_patient":per_patient}


# ---------------------------
# LM Studio Integration (OpenAI-compatible API) — ROBUST VERSION
# ---------------------------
class LMStudioClient:
    """
    LM Studio client using OpenAI-compatible API.
    More robust against template/stop issues:
      - no custom stop strings by default
      - fallback to system→user merge on template errors
      - final fallback: simplified prompt without markers
    """

    def __init__(
        self,
        base_url: str = "http://localhost:1234",
        model: str = "biomistral-7b",  # prefer exact id from GET /v1/models
        temperature: float = 0.2,
        max_tokens: int = 2000,
        show_raw: bool = False,
    ):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.show_raw = show_raw
        self._last_raw = ""

    @property
    def last_raw(self) -> str:
        return self._last_raw

    def _merge_system_into_user(self, messages: List[Dict]) -> List[Dict]:
        sys_parts = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
        sys_text = ("\n".join(sys_parts)).strip()
        kept = [m for m in messages if m.get("role") != "system"]
        if sys_text:
            if kept and kept[0].get("role") == "user":
                kept[0]["content"] = f"{sys_text}\n\n{kept[0]['content']}"
            else:
                kept.insert(0, {"role": "user", "content": sys_text})
        return kept

    def _build_messages(self, question: str, patient_ctx: Optional[Dict], contexts: List[Dict]) -> List[Dict]:
        ctx_lines = []
        for i, d in enumerate(contexts, 1):
            if "pmid" in d:  # papers
                pmid = d.get("pmid", "")
                title = d.get("title", "")
                journal = d.get("journal", "")
                abstract = (d.get("abstract") or "")[:600]
                ctx_lines.append(f"[{i}] PMID:{pmid} | {title}\nJournal: {journal}\nAbstract: {abstract}\n")
            else:  # patients
                pid = d.get("patient_id", "")
                summary = (d.get("clinical_summary") or "")[:600]
                ctx_lines.append(f"[{i}] PatientID:{pid}\n{summary}\n")

        patient = ""
        if patient_ctx:
            patient = (
                "Patient Context:\n"
                f"- Age: {patient_ctx.get('age','Unknown')}\n"
                f"- Conditions: {', '.join(patient_ctx.get('conditions', []))}\n"
                f"- Medications: {', '.join(patient_ctx.get('medications', []))}\n\n"
            )

        system = """You are a medical assistant. Provide evidence-based answers using ONLY the given sources.
Include citations like [PMID:12345] or [PatientID:ABC123]. Include any warnings or contraindications.
"""

        user = f"""{patient}Question: {question}

Sources:
{chr(10).join(ctx_lines)}

Remember: Write your complete answer between [BEGIN ANSWER] and [END ANSWER] markers."""

        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _post(self, payload: Dict) -> requests.Response:
        return requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=180
        )

    def _too_short(self, txt: str) -> bool:
        if not txt:
            return True
        t = txt.strip()
        if t in {"[BEGIN ANSWER]", " [BEGIN ANSWER]", "[BEGIN ANSWER]\n"}:
            return True
        return len(t) < 50

    def generate_raw(self, question: str, patient_ctx: Optional[Dict], contexts: List[Dict]) -> str:
        if not contexts:
            return "No sources available to answer the question."

        messages = self._build_messages(question, patient_ctx, contexts)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False
        }

        try:
            resp = self._post(payload)
            self._last_raw = resp.text

            if resp.status_code == 400 and (
                "Only user and assistant roles are supported" in resp.text
                or "Error rendering prompt with jinja template" in resp.text
            ):
                messages2 = self._merge_system_into_user(messages)
                payload["messages"] = messages2
                resp = self._post(payload)
                self._last_raw = resp.text

            if resp.status_code == 200:
                data = resp.json()
                content = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""
                content = content.strip()

                if self._too_short(content):
                    sources_blob = ""
                    for m in messages:
                        if m.get("role") == "user":
                            sources_blob = m.get("content", "")
                            break
                    simple_messages = [{
                        "role": "user",
                        "content": (
                            "You are a medical assistant. Using ONLY the sources below, answer the question in 4–8 sentences "
                            "with inline citations like [PMID:12345] or [PatientID:ABC123]. Include major contraindications.\n\n"
                            f"{sources_blob}"
                        )
                    }]
                    payload_simple = dict(payload, messages=simple_messages)
                    resp2 = self._post(payload_simple)
                    self._last_raw = resp2.text
                    if resp2.status_code == 200:
                        data2 = resp2.json()
                        content2 = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""
                        return content2.strip()
                    else:
                        raise Exception(f"LM Studio returned status {resp2.status_code}: {resp2.text[:500]}")

                return content

            raise Exception(f"LM Studio returned status {resp.status_code}: {resp.text[:500]}")

        except requests.exceptions.ConnectionError:
            raise Exception(
                f"Cannot connect to LM Studio at {self.base_url}. "
                f"Ensure the Local Server is running, port matches, and a model is loaded."
            )
        except Exception as e:
            if "LM Studio" not in str(e):
                raise Exception(f"LM Studio error: {str(e)}")
            raise

    def generate(self, question: str, patient_ctx: Optional[Dict], contexts: List[Dict]) -> str:
        raw = self.generate_raw(question, patient_ctx, contexts)
        final = extract_final_answer(raw)
        if not final or len(final) < 20:
            cleaned = strip_reasoning(raw)
            final = extract_final_answer(cleaned)
            if not final or len(final) < 20:
                citation_pattern = r"[^.]*\[(?:PMID|PatientID):[^\]]+\][^.]*\."
                citations = re.findall(citation_pattern, raw, re.IGNORECASE)
                final = " ".join(citations[:4]) if citations else (cleaned[:600] or raw[:600])
        return final

    def test_connection(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/v1/models", timeout=5)
            if r.status_code == 200:
                return True
            r = requests.get(f"{self.base_url}/", timeout=5)
            return r.status_code == 200
        except:
            return False


# ---------------------------
# Weaviate RAG Agent
# ---------------------------
class WeaviateRAGAgent:
    """MedicalResearch (papers) + DiabetesPatients (similar patients)."""

    def __init__(
        self,
        weaviate_url: str = "http://localhost:9090",
        grpc_port: int = 50051,
        embedding_model: str = "pritamdeka/S-PubMedBert-MS-MARCO",
        skip_init_checks: bool = False,
        init_timeout_secs: int = 30,
        bm25_properties_papers: Optional[List[str]] = None,
        bm25_properties_patients: Optional[List[str]] = None,
        enable_reranker: bool = False,
        reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ):
        self.bm25_papers = bm25_properties_papers or ["title", "abstract", "journal"]
        self.bm25_patients = bm25_properties_patients or [
            "clinical_summary",
            "medications",
            "symptoms",
            "complications",
        ]
        self.enable_reranker = enable_reranker
        self._reranker = None
        self._reranker_name = reranker_model

        u = urlparse(weaviate_url)
        host = u.hostname or "127.0.0.1"
        rest_port = u.port or (443 if u.scheme == "https" else 8080)

        self.client = weaviate.connect_to_local(
            host=host,
            port=rest_port,
            grpc_port=grpc_port,
            additional_config=AdditionalConfig(timeout=Timeout(init=init_timeout_secs)),
            skip_init_checks=skip_init_checks,
        )

        self.papers_col = self.client.collections.get("MedicalResearch")
        self.patients_col = self.client.collections.get("DiabetesPatients")
        self.embedder = SentenceTransformer(embedding_model)

    def _score_from_meta(self, meta) -> float:
        if meta is None:
            return 0.0
        if getattr(meta, "score", None) is not None:
            return float(meta.score)
        if getattr(meta, "distance", None) is not None:
            try:
                return 1.0 - float(meta.distance)
            except:
                return 0.0
        if getattr(meta, "certainty", None) is not None:
            return float(meta.certainty)
        return 0.0

    def _maybe_rerank(self, query: str, docs: List[Dict], k: int) -> List[Dict]:
        if not self.enable_reranker or not docs:
            return docs[:k]
        if self._reranker is None:
            self._reranker = SimpleReranker(self._reranker_name)
        return self._reranker.rerank(query, docs, k)

    def retrieve_papers(self, question: str, num_results: int = 5, mode: str = "hybrid", alpha: Optional[float] = 0.7) -> List[Dict]:
        qvec = self.embedder.encode(question).tolist()

        if mode == "vector":
            response = self.papers_col.query.near_vector(
                near_vector=qvec,
                limit=num_results,
                return_metadata=wvc.query.MetadataQuery(distance=True, score=True),
            )
        elif mode == "bm25":
            response = self.papers_col.query.bm25(
                query=question,
                query_properties=self.bm25_papers,
                limit=num_results,
                return_metadata=wvc.query.MetadataQuery(score=True, distance=True),
            )
        else:
            kwargs = dict(
                query=question,
                vector=qvec,
                query_properties=self.bm25_papers,
                limit=num_results,
                return_metadata=wvc.query.MetadataQuery(score=True, distance=True),
            )
            if alpha is not None:
                kwargs["alpha"] = float(alpha)
            response = self.papers_col.query.hybrid(**kwargs)

        docs: List[Dict] = []
        for obj in getattr(response, "objects", []) or []:
            props = getattr(obj, "properties", {}) or {}
            meta = getattr(obj, "metadata", None)
            docs.append({
                "title": props.get("title", ""),
                "pmid": props.get("pmid", ""),
                "journal": props.get("journal", ""),
                "abstract": props.get("abstract", "") or "",
                "score": self._score_from_meta(meta),
            })
        return self._maybe_rerank(question, docs, num_results)

    def _build_patient_filter(
        self,
        age_min: Optional[int],
        age_max: Optional[int],
        egfr_min: Optional[float],
        egfr_max: Optional[float],
        hba1c_min: Optional[float],
        hba1c_max: Optional[float],
        diabetes_type: Optional[str],
        meds_any: List[str],
        comps_any: List[str],
        symp_any: List[str],
    ):
        f = None

        def AND(a, b):
            return a & b if (a is not None and b is not None) else (a or b)

        if age_min is not None:
            f = AND(f, wvc.query.Filter.by_property("age").greater_or_equal(int(age_min)))
        if age_max is not None:
            f = AND(f, wvc.query.Filter.by_property("age").less_or_equal(int(age_max)))
        if egfr_min is not None:
            f = AND(f, wvc.query.Filter.by_property("egfr").greater_or_equal(float(egfr_min)))
        if egfr_max is not None:
            f = AND(f, wvc.query.Filter.by_property("egfr").less_or_equal(float(egfr_max)))
        if hba1c_min is not None:
            f = AND(f, wvc.query.Filter.by_property("hba1c_current").greater_or_equal(float(hba1c_min)))
        if hba1c_max is not None:
            f = AND(f, wvc.query.Filter.by_property("hba1c_current").less_or_equal(float(hba1c_max)))
        if diabetes_type:
            f = AND(f, wvc.query.Filter.by_property("diabetes_type").equal(diabetes_type))
        if meds_any:
            f = AND(f, wvc.query.Filter.by_property("medications").contains_any(meds_any))
        if comps_any:
            f = AND(f, wvc.query.Filter.by_property("complications").contains_any(comps_any))
        if symp_any:
            f = AND(f, wvc.query.Filter.by_property("symptoms").contains_any(symp_any))
        return f

    def retrieve_patients(
        self,
        description: str,
        num_results: int = 5,
        mode: str = "hybrid",
        alpha: Optional[float] = 0.7,
        age_min: Optional[int] = None,
        age_max: Optional[int] = None,
        egfr_min: Optional[float] = None,
        egfr_max: Optional[float] = None,
        hba1c_min: Optional[float] = None,
        hba1c_max: Optional[float] = None,
        diabetes_type: Optional[str] = None,
        meds_any: Optional[List[str]] = None,
        comps_any: Optional[List[str]] = None,
        symp_any: Optional[List[str]] = None,
    ) -> List[Dict]:
        meds_any = meds_any or []
        comps_any = comps_any or []
        symp_any = symp_any or []

        qvec = self.embedder.encode(description).tolist()
        filt = self._build_patient_filter(
            age_min, age_max, egfr_min, egfr_max, hba1c_min, hba1c_max,
            diabetes_type, meds_any, comps_any, symp_any,
        )

        if mode == "vector":
            response = self.patients_col.query.near_vector(
                near_vector=qvec,
                limit=num_results,
                filters=filt,
                return_metadata=wvc.query.MetadataQuery(distance=True, score=True),
            )
        elif mode == "bm25":
            response = self.patients_col.query.bm25(
                query=description,
                query_properties=self.bm25_patients,
                limit=num_results,
                filters=filt,
                return_metadata=wvc.query.MetadataQuery(score=True, distance=True),
            )
        else:
            kwargs = dict(
                query=description,
                vector=qvec,
                query_properties=self.bm25_patients,
                limit=num_results,
                filters=filt,
                return_metadata=wvc.query.MetadataQuery(score=True, distance=True),
            )
            if alpha is not None:
                kwargs["alpha"] = float(alpha)
            response = self.patients_col.query.hybrid(**kwargs)

        docs: List[Dict] = []
        for obj in getattr(response, "objects", []) or []:
            p = getattr(obj, "properties", {}) or {}
            meta = getattr(obj, "metadata", None)
            docs.append({
                "patient_id": p.get("patient_id", ""),
                "age": p.get("age", ""),
                "gender": p.get("gender", ""),
                "diabetes_type": p.get("diabetes_type", ""),
                "hba1c_current": p.get("hba1c_current", ""),
                "egfr": p.get("egfr", ""),
                "medications": p.get("medications", []),
                "complications": p.get("complications", []),
                "symptoms": p.get("symptoms", []),
                "clinical_summary": p.get("clinical_summary", ""),
                "score": self._score_from_meta(meta),
            })
        return docs

    def close(self):
        self.client.close()


# ---------------------------
# Streamlit UI
# ---------------------------
def create_streamlit_app():
    st.set_page_config(page_title="Medical RAG with LM Studio", page_icon="🏥", layout="wide")
    st.title("🏥 Medical Research RAG — Papers & Similar Patients (LM Studio)")

    with st.sidebar:
        st.header("⚙️ Weaviate Connection")
        weaviate_url = st.text_input("Weaviate URL (REST)", os.getenv("WEAVIATE_URL", "http://localhost:9090"))
        grpc_port = st.number_input("gRPC port", 1, 65535, int(os.getenv("WEAVIATE_GRPC_PORT", "50051")))
        skip_checks = st.checkbox("Skip init checks", value=False)
        init_timeout = st.slider("Init timeout (s)", 5, 120, int(os.getenv("WEAVIATE_INIT_TIMEOUT", "30")))

        st.header("🔎 Retrieval Settings")
        mode = st.selectbox("Mode", ["hybrid", "vector", "bm25"], index=0)
        alpha = st.slider("Hybrid alpha (vector weight)", 0.0, 1.0, 0.7) if mode == "hybrid" else None
        enable_reranker = st.checkbox("Enable local reranker (papers)", value=False)
        num_results = st.slider("Top-K results", 1, 15, 5)

        st.header("LM Studio Settings")
        lm_studio_url = st.text_input(
            "LM Studio URL",
            os.getenv("LM_STUDIO_URL", "http://localhost:1234"),
            help="Default LM Studio port is 1234"
        )
        model_name = st.text_input(
            "Model name",
            os.getenv("LM_MODEL_NAME", "biomistral-7b"),
            help="Prefer the exact id from GET /v1/models in LM Studio"
        )
        temperature = st.slider("Temperature", 0.0, 1.0, 0.2)
        max_tokens = st.slider("Max tokens", 256, 4000, 1500, step=64)
        show_raw = st.checkbox("Show raw LLM output (debug)", value=False)

        # Test LM Studio connection
        if st.button("🧪 Test LM Studio Connection"):
            try:
                client = LMStudioClient(
                    base_url=lm_studio_url,
                    model=model_name,
                    temperature=temperature,
                    max_tokens=256,
                    show_raw=show_raw
                )
                if client.test_connection():
                    st.success("✅ Connected to LM Studio!")
                    test_q = "Test"
                    test_ctx = [{"pmid": "12345", "title": "Test", "journal": "Test", "abstract": "Test"}]
                    raw = client.generate_raw(test_q, None, test_ctx)
                    if raw:
                        st.info(f"Model responding. Output length: {len(raw)} chars")
                else:
                    st.error("❌ Cannot connect to LM Studio. Make sure the server is running.")
            except Exception as e:
                st.error(f"LM Studio test failed: {e}")

        st.divider()
        embedding_model = st.text_input(
            "Query embedding model",
            os.getenv("EMBEDDING_MODEL", "pritamdeka/S-PubMedBert-MS-MARCO")
        )
        connect = st.button("🔌 Connect to Weaviate", use_container_width=True)

    # Connect to Weaviate
    if "agent" not in st.session_state or connect:
        try:
            st.session_state.agent = WeaviateRAGAgent(
                weaviate_url=weaviate_url,
                grpc_port=int(grpc_port),
                skip_init_checks=skip_checks,
                init_timeout_secs=int(init_timeout),
                bm25_properties_papers=["title", "abstract", "journal"],
                bm25_properties_patients=["clinical_summary", "medications", "symptoms", "complications"],
                enable_reranker=enable_reranker,
            )
            if embedding_model:
                st.session_state.agent.embedder = SentenceTransformer(embedding_model)
            st.success("✅ Connected to Weaviate")
        except Exception as e:
            st.error(f"Failed to connect to Weaviate: {e}")
            st.stop()

    # LM Studio client
    lm_client = LMStudioClient(
        base_url=lm_studio_url,
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        show_raw=show_raw,
    )

    tab_papers, tab_patients = st.tabs(["📄 Papers", "🧍 Similar Patients"])

    # ----- PAPERS TAB -----
    with tab_papers:
        st.header("💬 Ask a medical question")
        q = st.text_area(
            "Question",
            value=st.session_state.get("current_question", ""),
            placeholder="e.g., Contraindications for metformin in CKD?",
            height=100,
        )
        ask = st.button("🔍 Retrieve & Analyze (Papers)", type="primary", key="btn_papers")

        if ask and q:
            with st.spinner("Retrieving papers..."):
                docs = st.session_state.agent.retrieve_papers(
                    question=q, num_results=num_results, mode=mode, alpha=alpha
                )

            st.subheader("📚 Sources")
            for i, s in enumerate(docs, 1):
                with st.expander(f"📄 Source {i}: {s['title'][:80]}"):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.write(f"**Journal:** {s['journal']}")
                        st.write(f"**PMID:** {s['pmid']}")
                        st.write(f"**Abstract:** {(s['abstract'] or '')[:1200]}...")
                    with c2:
                        st.metric("Score", f"{s['score']:.3f}")

            with st.spinner("Analyzing with LM Studio..."):
                try:
                    ans = lm_client.generate(question=q, patient_ctx=None, contexts=docs)
                except Exception as e:
                    st.error(f"LM Studio error: {e}")
                    ans = ""

            if ans.strip():
                render_scrollable_markdown("💡 Evidence-based answer", ans, "evidence_answer")
            else:
                st.info("No LM Studio output. Check connection and model.")

            if show_raw and lm_client.last_raw:
                render_scrollable_markdown("Raw LM Studio output", lm_client.last_raw, "raw_papers")

    # ----- PATIENTS TAB -----
    with tab_patients:
        st.header("🧍 Find similar patients")
        colA, colB, colC = st.columns(3)
        with colA:
            age = st.number_input("Age", 18, 95, 62, key="p_age")
            gender = st.selectbox("Gender", ["Male", "Female"], key="p_gender")
            dia_type = st.selectbox("Diabetes type", ["Type 2", "Type 1"], index=0, key="p_dtype")
        with colB:
            a1c = st.number_input("HbA1c (%)", 5.0, 14.0, 8.6, step=0.1, key="p_a1c")
            egfr = st.number_input("eGFR", 15.0, 180.0, 45.0, step=1.0, key="p_egfr")
            bp = st.text_input("BP (optional)", "140/85", key="p_bp")
        with colC:
            meds = st.text_input("Key diabetes meds (comma)", "metformin, empagliflozin", key="p_meds")
            comps = st.text_input("Complications (comma)", "diabetic nephropathy", key="p_comps")
            symps = st.text_input("Symptoms (comma)", "fatigue, polyuria", key="p_symps")

        default_desc = (
            f"{age}-year-old {gender.lower()} with {dia_type} diabetes. "
            f"HbA1c {a1c:.1f}%, eGFR {egfr:.0f}. Meds: {meds}. "
            f"Complications: {comps}. Symptoms: {symps}."
        )
        desc = st.text_area("Patient description", value=default_desc, height=100, key="p_desc")

        st.subheader("Filters (optional)")
        c1, c2, c3 = st.columns(3)
        with c1:
            f_age_min = st.number_input("Min age", 18, 95, value=18, key="f_age_min")
            f_age_max = st.number_input("Max age", 18, 95, value=95, key="f_age_max")
        with c2:
            f_egfr_min = st.number_input("Min eGFR", 15.0, 200.0, value=15.0, step=1.0, key="f_egfr_min")
            f_egfr_max = st.number_input("Max eGFR", 15.0, 200.0, value=200.0, step=1.0, key="f_egfr_max")
        with c3:
            f_a1c_min = st.number_input("Min HbA1c", 5.0, 14.0, value=5.0, step=0.1, key="f_a1c_min")
            f_a1c_max = st.number_input("Max HbA1c", 5.0, 14.0, value=14.0, step=0.1, key="f_a1c_max")

        cohort_q = st.text_input(
            "LLM prompt for cohort analysis",
            "Summarize common patterns and suggest next steps for this cohort.",
            key="cohort_q",
        )

        med_list = [m.strip() for m in meds.split(",") if m.strip()]
        comp_list = [m.strip() for m in comps.split(",") if m.strip()]
        symp_list = [m.strip() for m in symps.split(",") if m.strip()]

        run_btn = st.button("🔍 Retrieve & Analyze (Patients)", type="primary", key="btn_patients")

        if run_btn:
            # Retrieve similar patients
            with st.spinner("Retrieving similar patients..."):
                results = st.session_state.agent.retrieve_patients(
                    description=desc,
                    num_results=num_results,
                    mode=mode,
                    alpha=alpha,
                    age_min=f_age_min,
                    age_max=f_age_max,
                    egfr_min=f_egfr_min,
                    egfr_max=f_egfr_max,
                    hba1c_min=f_a1c_min,
                    hba1c_max=f_a1c_max,
                    diabetes_type=dia_type,
                    meds_any=med_list,
                    comps_any=comp_list,
                    symp_any=symp_list,
                )
            st.session_state["patients_results"] = results

            # ---------- Treatment audit ----------
            auditor = TreatmentAuditor()
            summary = auditor.cohort_summary(results)
            st.session_state["audit_summary"] = summary

            # Input patient quick audit
            input_patient = {
                "age": age,
                "gender": gender,
                "diabetes_type": dia_type,
                "hba1c_current": a1c,
                "egfr": egfr,
                "medications": med_list,
                "complications": comp_list,
                "symptoms": symp_list,
                "clinical_summary": desc,
            }
            st.session_state["input_patient_audit"] = auditor.audit_patient(input_patient)

            # Optional LLM narrative for cohort
            with st.spinner("Analyzing cohort with LM Studio..."):
                try:
                    ans_pat = lm_client.generate(question=cohort_q, patient_ctx=None, contexts=results)
                except Exception as e:
                    st.error(f"LM Studio error: {e}")
                    ans_pat = ""
            st.session_state["patients_llm_answer"] = ans_pat
            st.session_state["patients_llm_raw"] = lm_client.last_raw

        # ---------- Display ----------
        patients = st.session_state.get("patients_results", [])
        audit_summary = st.session_state.get("audit_summary")
        input_audit = st.session_state.get("input_patient_audit")
        ans_pat = st.session_state.get("patients_llm_answer", "")
        raw_pat = st.session_state.get("patients_llm_raw", "")

        st.subheader("👥 Matches")
        if patients:
            auditor = TreatmentAuditor()
            per_patient = audit_summary["per_patient"] if audit_summary else [auditor.audit_patient(p) for p in patients]
            for i, (p, ar) in enumerate(zip(patients, per_patient), 1):
                color = {"ok":"✅", "missing_indication":"🔎", "caution":"⚠️", "contra":"⛔️"}[ar.status]
                with st.expander(f"{color} Patient {i}: {p.get('patient_id','')}  —  Score {p['score']:.3f}"):
                    st.write(f"**Age/Gender/Type:** {p['age']} / {p['gender']} / {p['diabetes_type']}")
                    st.write(f"**HbA1c / eGFR:** {p['hba1c_current']}% / {p['egfr']}")
                    st.write(f"**Medications:** {', '.join(p['medications']) if p['medications'] else '—'}")
                    st.write(f"**Complications:** {', '.join(p['complications']) if p['complications'] else '—'}")
                    st.write(f"**Symptoms:** {', '.join(p['symptoms']) if p['symptoms'] else '—'}")
                    st.write(f"**Summary:** {(p.get('clinical_summary') or '')[:800]}...")
                    if ar.reasons:
                        st.markdown("**Treatment audit:**")
                        for r in ar.reasons:
                            st.write("- " + r)
        else:
            st.info("Run a search to see similar patients.")

        # ---------- Cohort treatment audit ----------
        if audit_summary:
            st.subheader("Cohort treatment audit (signals)")
            c = audit_summary["counts"]; pos = audit_summary["positives"]; neg = audit_summary["negatives"]
            st.write(
                f"- Status — OK: {c['ok']} · Missing indication: {c['missing_indication']} · "
                f"Caution: {c['caution']} · Contra: {c['contra']}"
            )
            st.write(
                f"- Positives — CKD+SGLT2: {pos['ckd+sglt2']} · HF+SGLT2: {pos['hf+sglt2']} · "
                f"ASCVD+CV agent: {pos['ascvd+cv_agent']}"
            )
            st.write(
                f"- Negatives — Metformin eGFR<30: {neg['met_eGFR<30']} · TZD in HF: {neg['tzd_hf']} · "
                f"SU in elderly: {neg['su_elderly']}"
            )

        # ---------- Input patient decision checklist ----------
        if input_audit:
            st.subheader("Input patient — decision checklist")
            icon = {"ok":"✅","missing_indication":"🔎","caution":"⚠️","contra":"⛔️"}[input_audit.status]
            st.write(f"{icon} **Overall status:** {input_audit.status.upper()}")
            if input_audit.reasons:
                st.markdown("**Signals:**")
                for r in input_audit.reasons:
                    st.write("- " + r)
            st.caption("Heuristic audit. For education only — not medical advice.")

        # Cohort LLM analysis
        st.subheader("Cohort analysis (LLM)")
        if ans_pat and ans_pat.strip():
            render_scrollable_markdown("💡 Cohort analysis", ans_pat, "cohort_analysis")
        elif patients:
            st.info("No LM Studio output for cohort analysis.")
        if show_raw and raw_pat:
            render_scrollable_markdown("Raw LM Studio output (patients)", raw_pat, "raw_patients")

    st.caption("Note: Demo system. Not medical advice.")


# ---------------------------
# Entry Point
# ---------------------------
if __name__ == "__main__":
    create_streamlit_app()
