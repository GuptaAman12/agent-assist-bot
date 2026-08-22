from sentence_transformers import SentenceTransformer, util

from .. import config


class KnowledgeBase:
    def __init__(self) -> None:
        self.entries = config.load_knowledge_base()
        self.model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
        corpus = [entry["response"] for entry in self.entries]
        self.corpus_embeddings = self.model.encode(corpus, convert_to_tensor=True)

    def best_response(self, query: str) -> str:
        query_embedding = self.model.encode(query, convert_to_tensor=True)
        scores = util.pytorch_cos_sim(query_embedding, self.corpus_embeddings)[0]
        top_idx = scores.argmax().item()
        return self.entries[top_idx]["response"]
