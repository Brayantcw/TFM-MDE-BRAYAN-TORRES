"""
Medical RAG (BYOV) with Separate AI Layer
- Papers: Weaviate retrieval (MedicalResearch) + pluggable LLM for answers
- Similar Patients: Weaviate retrieval (DiabetesPatients) + instant LLM cohort summary
"""

import os
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

import streamlit as st
import weaviate
import weaviate.classes as wvc
from weaviate.classes.init import AdditionalConfig, Timeout
from sentence_transformers import SentenceTransformer


# ---------------------------
# Utils
# ---------------------------
def strip_reasoning(text: str) -> str:
    """Remove hidden chain-of-thought (<think>...</think>) and clean whitespace."""
    if not text:
        return ""
    # Remove <think> ... </think>
    text = re.sub(r"(?is)<\s*think\s*>.*?<\s*/\s*think\s*>", "", text)
    # Remove any stray tags
    text = re.sub(r"(?is)<\s*/?\s*think\s*>", "", text)
    return text.strip()


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
# LLM Answerer (separate AI layer) — robust Ollama
# ---------------------------
class LLLMError(Exception):
    pass


class LLMAnswerer:
    """
    Pluggable generation backends: none | openai | azure | ollama
    """

    def __init__(
        self,
        provider: str = "none",
        model: str = "gpt-4o-mini",
        temperature: float = 0.1,
        max_tokens: int = 800,
        azure_api_version: str = "2024-02-15-preview",
        azure_deployment: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
        show_raw: bool = False,  # debug toggle
    ):
        self.provider = provider.lower()
        self.model = model
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.azure_api_version = azure_api_version
        self.azure_deployment = azure_deployment
        self.ollama_url = ollama_url
        self._openai_client = None
        self._azure_client = None
        self.show_raw = show_raw
        self._last_raw = ""  # for debug display

    @property
    def last_raw(self) -> str:
        return self._last_raw

    def _build_messages(self, question: str, patient_ctx: Optional[Dict], contexts: List[Dict]) -> List[Dict]:
        # Works for papers (expects title/pmid/journal/abstract) OR patients (expects clinical_summary/patient_id)
        ctx_lines = []
        for i, d in enumerate(contexts, 1):
            if "pmid" in d:  # papers
                pmid = d.get("pmid", "")
                title = d.get("title", "")
                journal = d.get("journal", "")
                abstract = (d.get("abstract") or "")[:1400]
                ctx_lines.append(f"[{i}] PMID:{pmid} | {title} — {journal}\n{abstract}\n")
            else:  # patients
                pid = d.get("patient_id", "")
                summary = (d.get("clinical_summary") or "")[:1400]
                ctx_lines.append(f"[{i}] PatientID:{pid}\n{summary}\n")

        patient = ""
        if patient_ctx:
            patient = (
                "Patient Context:\n"
                f"- Age: {patient_ctx.get('age','Unknown')}\n"
                f"- Conditions: {', '.join(patient_ctx.get('conditions', []))}\n"
                f"- Medications: {', '.join(patient_ctx.get('medications', []))}\n\n"
            )

        system = (
            "You are a clinical assistant. Use ONLY the provided context. "
            "Cite papers with [PMID:XXXXXX] or patients with [PatientID:XXXXX]. "
            "If evidence is weak or conflicting, say so explicitly."
        )
        user = (
            f"{patient}"
            f"Question: {question}\n\n"
            "Sources:\n" + "\n".join(ctx_lines) +
            "\nInstructions:\n"
            "- Synthesize key findings.\n"
            "- Call out contraindications/warnings.\n"
            "- Provide 2–4 citations.\n"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # ---------- OpenAI ----------
    def _generate_openai_raw(self, messages: List[Dict]) -> str:
        from openai import OpenAI
        if self._openai_client is None:
            self._openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = self._openai_client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            messages=messages,
        )
        text = (resp.choices[0].message.content or "").strip()
        self._last_raw = text
        return text

    # ---------- Azure OpenAI ----------
    def _generate_azure_raw(self, messages: List[Dict]) -> str:
        from openai import AzureOpenAI
        if self._azure_client is None:
            self._azure_client = AzureOpenAI(
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_version=self.azure_api_version,
            )
        model = self.azure_deployment or self.model
        resp = self._azure_client.chat.completions.create(
            model=model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            messages=messages,
        )
        text = (resp.choices[0].message.content or "").strip()
        self._last_raw = text
        return text

    # ---------- Ollama: prefer /api/chat, fallback to /api/generate ----------
    def _generate_ollama_chat_raw(self, messages: List[Dict]) -> str:
        import requests
        payload = {
            "model": self.model,
            "messages": messages,  # {role, content}
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
                "num_ctx": 8192,
                # IMPORTANT: stop only on closing tag; do NOT stop on "<think>"
                "stop": ["</think>"],
            },
        }
        r = requests.post(f"{self.ollama_url}/api/chat", json=payload, timeout=180)
        self._last_raw = r.text
        r.raise_for_status()
        data = r.json()
        msg = ((data.get("message") or {}).get("content") or "").strip()

        # Safety retry without stop tokens if empty
        if not msg:
            payload["options"].pop("stop", None)
            r2 = requests.post(f"{self.ollama_url}/api/chat", json=payload, timeout=180)
            self._last_raw = r2.text
            r2.raise_for_status()
            data2 = r2.json()
            msg = ((data2.get("message") or {}).get("content") or "").strip()

        if not msg:
            raise LLLMError(f"Ollama /api/chat returned empty content. Body (first 400 chars): {self._last_raw[:400]}")
        return msg

    def _generate_ollama_generate_raw(self, messages: List[Dict]) -> str:
        import requests
        # Flatten roles for /api/generate
        prompt = ""
        for m in messages:
            role = m.get("role", "user").upper()
            content = m.get("content", "")
            prompt += f"{role}:\n{content}\n\n"
        if len(prompt) > 8000:
            prompt = prompt[-8000:]

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
                "num_ctx": 8192,
                # IMPORTANT: stop only on closing tag
                "stop": ["</think>"],
            },
        }
        r = requests.post(f"{self.ollama_url}/api/generate", json=payload, timeout=180)
        self._last_raw = r.text
        r.raise_for_status()
        data = r.json()
        msg = (data.get("response") or "").strip()

        # Safety retry without stop tokens if empty
        if not msg:
            payload["options"].pop("stop", None)
            r2 = requests.post(f"{self.ollama_url}/api/generate", json=payload, timeout=180)
            self._last_raw = r2.text
            r2.raise_for_status()
            data2 = r2.json()
            msg = (data2.get("response") or "").strip()

        if not msg:
            raise LLLMError(f"Ollama /api/generate returned empty response. Body (first 400 chars): {self._last_raw[:400]}")
        return msg

    def _generate_ollama_raw(self, messages: List[Dict]) -> str:
        # Try chat endpoint first, then fallback to generate
        try:
            raw = self._generate_ollama_chat_raw(messages)
        except Exception:
            raw = self._generate_ollama_generate_raw(messages)
        return raw

    # ---------- public ----------
    def generate_raw(self, question: str, patient_ctx: Optional[Dict], contexts: List[Dict]) -> str:
        """Return the raw model output (may include <think>…</think>)."""
        if self.provider == "none":
            return ""
        messages = self._build_messages(question, patient_ctx, contexts)
        if self.provider == "openai":
            return self._generate_openai_raw(messages)
        if self.provider == "azure":
            return self._generate_azure_raw(messages)
        if self.provider == "ollama":
            return self._generate_ollama_raw(messages)
        return ""

    def generate(self, question: str, patient_ctx: Optional[Dict], contexts: List[Dict]) -> str:
        """Return cleaned model output (reasoning stripped)."""
        raw = self.generate_raw(question, patient_ctx, contexts)
        cleaned = strip_reasoning(raw)
        return cleaned or raw


# ---------------------------
# Weaviate Agents
# ---------------------------
class WeaviateRAGAgent:
    """MedicalResearch (papers) + DiabetesPatients (similar patients)"""

    def __init__(
        self,
        weaviate_url: str = "http://localhost:8080",
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

    # ----- shared helpers -----
    def _score_from_meta(self, meta) -> float:
        if meta is None:
            return 0.0
        if getattr(meta, "score", None) is not None:
            return float(meta.score)
        if getattr(meta, "distance", None) is not None:
            try:
                return 1.0 - float(meta.distance)
            except Exception:
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

    # ----- papers -----
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
            docs.append(
                {
                    "title": props.get("title", ""),
                    "pmid": props.get("pmid", ""),
                    "journal": props.get("journal", ""),
                    "abstract": props.get("abstract", "") or "",
                    "score": self._score_from_meta(meta),
                }
            )
        return self._maybe_rerank(question, docs, num_results)

    # ----- patients -----
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
            age_min,
            age_max,
            egfr_min,
            egfr_max,
            hba1c_min,
            hba1c_max,
            diabetes_type,
            meds_any,
            comps_any,
            symp_any,
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
            docs.append(
                {
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
                }
            )
        return docs

    def close(self):
        self.client.close()


# ---------------------------
# Streamlit UI
# ---------------------------
def create_streamlit_app():
    st.set_page_config(page_title="Medical RAG (Weaviate + Separate AI Layer)", page_icon="🏥", layout="wide")
    st.title("🏥 Medical Research RAG — Papers & Similar Patients")

    with st.sidebar:
        st.header("⚙️ Weaviate Connection")
        weaviate_url = st.text_input("Weaviate URL (REST)", os.getenv("WEAVIATE_URL", "http://localhost:8080"))
        grpc_port = st.number_input("gRPC port", 1, 65535, int(os.getenv("WEAVIATE_GRPC_PORT", "50051")))
        skip_checks = st.checkbox("Skip init checks", value=False)
        init_timeout = st.slider("Init timeout (s)", 5, 120, int(os.getenv("WEAVIATE_INIT_TIMEOUT", "30")))

        st.header("🔎 Retrieval (both tabs)")
        mode = st.selectbox("Mode", ["hybrid", "vector", "bm25"], index=0)
        alpha = st.slider("Hybrid alpha (vector weight)", 0.0, 1.0, 0.7) if mode == "hybrid" else None
        bm25_papers_props = st.text_input("Papers properties", "title,abstract,journal")
        bm25_patients_props = st.text_input("Patients properties", "clinical_summary,medications,symptoms,complications")
        bm25_papers = [p.strip() for p in bm25_papers_props.split(",") if p.strip()]
        bm25_patients = [p.strip() for p in bm25_patients_props.split(",") if p.strip()]
        enable_reranker = st.checkbox("Enable local reranker (papers)", value=False)

        st.header("🧠 LLM Provider")
        provider = st.selectbox("Provider", ["none", "openai", "azure", "ollama"], index=0)
        llm_model = st.text_input("Model / Deployment", os.getenv("LLM_MODEL", "gpt-4o-mini"))
        temperature = st.slider("Temperature", 0.0, 1.0, 0.1)
        max_tokens = st.slider("Max tokens", 256, 2000, 800, step=64)
        azure_deployment = st.text_input("Azure Deployment (if Azure)", os.getenv("AZURE_OPENAI_DEPLOYMENT", "")) if provider == "azure" else None
        azure_api_version = st.text_input("Azure API version", os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")) if provider == "azure" else "2024-02-15-preview"
        ollama_url = st.text_input("Ollama URL", os.getenv("OLLAMA_URL", "http://localhost:11434")) if provider == "ollama" else "http://localhost:11434"
        show_raw = st.checkbox("Show raw LLM output (debug)", value=False)

        if st.button("🩺 Test LLM"):
            try:
                tester = LLMAnswerer(provider=provider, model=llm_model, temperature=temperature,
                                     max_tokens=256, azure_api_version=azure_api_version,
                                     azure_deployment=azure_deployment, ollama_url=ollama_url, show_raw=show_raw)
                raw = tester.generate_raw("Say LLM OK and nothing else.", None, [])
                cleaned = strip_reasoning(raw)
                st.success("LLM call succeeded.")
                st.write("**Cleaned:**")
                st.code(cleaned or "<empty>")
                if show_raw:
                    st.write("**Raw:**")
                    st.code(tester.last_raw or "<empty>")
            except Exception as e:
                st.error(f"LLM test failed: {e}")

        st.divider()
        embedding_model = st.text_input("Query embedding model", os.getenv("EMBEDDING_MODEL", "pritamdeka/S-PubMedBert-MS-MARCO"))
        num_results = st.slider("Top-K", 1, 15, 5)
        connect = st.button("🔌 Connect / Reconnect", use_container_width=True)

    # Connect
    if "agent" not in st.session_state or connect:
        try:
            st.session_state.agent = WeaviateRAGAgent(
                weaviate_url=weaviate_url,
                grpc_port=int(grpc_port),
                skip_init_checks=skip_checks,
                init_timeout_secs=int(init_timeout),
                bm25_properties_papers=bm25_papers,
                bm25_properties_patients=bm25_patients,
                enable_reranker=enable_reranker,
            )
            if embedding_model:
                st.session_state.agent.embedder = SentenceTransformer(embedding_model)
            st.success("✅ Connected to Weaviate")
        except Exception as e:
            st.error(f"Failed to connect: {e}")
            st.stop()

    # LLM layer
    answerer = LLMAnswerer(
        provider=provider,
        model=llm_model,
        temperature=temperature,
        max_tokens=max_tokens,
        azure_api_version=azure_api_version,
        azure_deployment=azure_deployment,
        ollama_url=ollama_url,
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

            with st.spinner("Analyzing with LLM..."):
                try:
                    ans = answerer.generate(question=q, patient_ctx=None, contexts=docs)
                except Exception as e:
                    st.error(f"LLM error: {e}")
                    ans = ""

            st.subheader("💡 Evidence-based answer")
            if ans.strip():
                st.markdown(ans)
            else:
                st.info("No LLM output. Showing fallback summary.")
                st.markdown(_fallback_answer(docs))
                if show_raw:
                    st.write("**Raw LLM output:**")
                    st.code(answerer.last_raw or "<empty>")

    # ----- PATIENTS TAB -----
    with tab_patients:
        st.header("🧍 Find similar patients")
        # Quick builder
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
        desc = st.text_area(
            "Patient description (used for embedding/search)",
            value=default_desc,
            height=100,
            key="p_desc",
        )

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

        # LLM prompt for cohort analysis
        cohort_q = st.text_input(
            "LLM prompt for cohort analysis",
            "Summarize common patterns and suggest next steps for this cohort.",
            key="cohort_q",
        )

        med_list = [m.strip() for m in meds.split(",") if m.strip()]
        comp_list = [m.strip() for m in comps.split(",") if m.strip()]
        symp_list = [m.strip() for m in symps.split(",") if m.strip()]

        # Single button: retrieve + analyze (like Papers tab)
        run_btn = st.button("🔍 Retrieve & Analyze (Patients)", type="primary", key="btn_patients")

        if run_btn:
            # 1) Retrieve
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

            # 2) Analyze immediately with LLM
            with st.spinner("Analyzing cohort with LLM..."):
                try:
                    ans_pat = answerer.generate(question=cohort_q, patient_ctx=None, contexts=results)
                except Exception as e:
                    st.error(f"LLM error: {e}")
                    ans_pat = ""
            st.session_state["patients_llm_answer"] = ans_pat
            st.session_state["patients_llm_raw"] = answerer.last_raw

        # Always render from session (survives reruns)
        patients = st.session_state.get("patients_results", [])
        ans_pat = st.session_state.get("patients_llm_answer", "")
        raw_pat = st.session_state.get("patients_llm_raw", "")

        st.subheader("👥 Matches")
        if patients:
            for i, p in enumerate(patients, 1):
                with st.expander(f"🧍 Patient {i}: {p.get('patient_id','')}  —  Score {p['score']:.3f}"):
                    st.write(f"**Age/Gender/Type:** {p['age']} / {p['gender']} / {p['diabetes_type']}")
                    st.write(f"**HbA1c / eGFR:** {p['hba1c_current']}% / {p['egfr']}")
                    st.write(f"**Medications:** {', '.join(p['medications']) if p['medications'] else '—'}")
                    st.write(f"**Complications:** {', '.join(p['complications']) if p['complications'] else '—'}")
                    st.write(f"**Symptoms:** {', '.join(p['symptoms']) if p['symptoms'] else '—'}")
                    st.write(f"**Summary:** {(p.get('clinical_summary') or '')[:1200]}...")
        else:
            st.info("Run a search to see similar patients.")

        st.subheader("💡 Cohort analysis")
        if ans_pat and ans_pat.strip():
            st.markdown(ans_pat)
        elif patients:
            st.info("No LLM output. Showing fallback summary of first matches.")
            st.markdown(_fallback_patients(patients))
        else:
            st.caption("No cohort loaded yet.")
        if show_raw and raw_pat:
            st.write("**Raw LLM output (patients):**")
            st.code(raw_pat or "<empty>")

    st.caption("Note: Demo system. Not medical advice.")


def _fallback_answer(sources: List[Dict]) -> str:
    if not sources:
        return "No relevant research papers found for your question."
    lines = [f"Based on {len(sources)} research papers:\n"]
    for i, s in enumerate(sources, 1):
        lines.append(f"**Paper {i}**: {s['title']}")
        lines.append(f"- Journal: {s['journal']}")
        lines.append(f"- Key Finding: {(s.get('abstract') or '')[:200]}...")
        lines.append(f"- Score: {s.get('score', 0):.3f}\n")
    return "\n".join(lines)


def _fallback_patients(pats: List[Dict]) -> str:
    if not pats:
        return "No similar patients found."
    lines = [f"Top {len(pats)} similar patients:\n"]
    for i, p in enumerate(pats, 1):
        lines.append(f"**Patient {i} ({p.get('patient_id','')})** — Score {p['score']:.3f}")
        lines.append(
            f"- Age {p['age']}, {p['gender']}, {p['diabetes_type']}; "
            f"HbA1c {p['hba1c_current']}%, eGFR {p['egfr']}"
        )
        lines.append(
            f"- Meds: {', '.join(p['medications']) if p['medications'] else '—'}; "
            f"Complications: {', '.join(p['complications']) if p['complications'] else '—'}"
        )
        lines.append(f"- Summary: {(p.get('clinical_summary') or '')[:180]}...\n")
    return "\n".join(lines)


# ---------------------------
# Entry
# ---------------------------
if __name__ == "__main__":
    create_streamlit_app()
