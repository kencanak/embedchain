import os
from typing import Dict, List, Optional, Set

try:
    import pinecone
except ImportError:
    raise ImportError(
        "Pinecone requires extra dependencies. Install with `pip install --upgrade embedchain[pinecone]`"
    ) from None

from embedchain.config.vectordb.pinecone import PineconeDbConfig
from embedchain.helper.json_serializable import register_deserializable
from embedchain.vectordb.base import BaseVectorDB


@register_deserializable
class PineconeDb(BaseVectorDB):
    """
    Pinecone as vector database
    """

    def __init__(
            self,
            config: Optional[PineconeDbConfig] = None,
    ):
        """Pinecone as vector database.

        :param config: Pinecone database config, defaults to None
        :type config: PineconeDbConfig, optional
        :raises ValueError: No config provided
        """
        if config is None:
            self.config = PineconeDbConfig()
        else:
            if not isinstance(config, PineconeDbConfig):
                raise TypeError(
                    "config is not a `PineconeDbConfig` instance. "
                    "Please make sure the type is right and that you are passing an instance."
                )
            self.config = config
        self.client = self._setup_pinecone_index()
        # Call parent init here because embedder is needed
        super().__init__(config=self.config)

    def _initialize(self):
        """
        This method is needed because `embedder` attribute needs to be set externally before it can be initialized.
        """
        if not self.embedder:
            raise ValueError("Embedder not set. Please set an embedder with `set_embedder` before initialization.")

    # Loads the Pinecone index or creates it if not present.
    def _setup_pinecone_index(self):
        pinecone.init(
            api_key=os.environ.get("PINECONE_API_KEY"),
            environment=os.environ.get("PINECONE_ENV"),
        )
        self.index_name = self._get_index_name()
        indexes = pinecone.list_indexes()
        if indexes is None or self.index_name not in indexes:
            pinecone.create_index(
                name=self.index_name,
                metric=self.config.metric,
                dimension=self.config.dimension
            )
        return pinecone.Index(self.index_name)

    def get(
            self, ids: Optional[List[str]] = None, where: Optional[Dict[str, any]] = None, limit: Optional[int] = None
    ):
        """
        Get existing doc ids present in vector database

        :param ids: _list of doc ids to check for existance
        :type ids: List[str]
        :param where: to filter data
        :type where: Dict[str, any]
        :return: ids
        :rtype: Set[str]
        """
        zero_vector = []
        for i in range(self.config.dimension):
            zero_vector.append(0)

        results = self.client.query(vector=zero_vector, top_k=max(1, self.count()), filter=where)
        ids = set()

        for result in results["matches"]:
            ids.add(result["id"])
        return {"ids": ids}

    def add(self, documents: List[str], metadatas: List[object], ids: List[str]):
        """add data in vector database

        :param documents: list of texts to add
        :type documents: List[str]
        :param metadatas: list of metadata associated with docs
        :type metadatas: List[object]
        :param ids: ids of docs
        :type ids: List[str]
        """

        docs = []
        embeddings = self.embedder.embedding_fn(documents)
        for id, text, metadata, embedding in zip(ids, documents, metadatas, embeddings):
            metadata["text"] = text
            docs.append(
                {
                    "id": id,
                    "values": embedding,
                    "metadata": metadata,
                }
            )
        self.client.upsert(docs)

    def query(self, input_query: List[str], n_results: int, where: Dict[str, any]) -> List[str]:
        """
        query contents from vector database based on vector similarity

        :param input_query: list of query string
        :type input_query: List[str]
        :param n_results: no of similar documents to fetch from database
        :type n_results: int
        :param where: Optional. to filter data
        :type where: Dict[str, any]
        :return: Database contents that are the result of the query
        :rtype: List[str]
        """
        input_query_vector = self.embedder.embedding_fn(input_query)
        query_vector = input_query_vector[0]
        contents = self.client.query(vector=query_vector, filter=where, top_k=n_results, include_metadata=True,)
        embeddings = list(map(lambda content: content["metadata"]["text"], contents["matches"]))
        return embeddings

    def set_collection_name(self, name: str):
        """
        Set the name of the collection. A collection is an isolated space for vectors.

        :param name: Name of the collection.
        :type name: str
        """
        if not isinstance(name, str):
            raise TypeError("Collection name must be a string")
        self.config.collection_name = name

    def count(self) -> int:
        """
        Count number of documents/chunks embedded in the database.

        :return: number of documents
        :rtype: int
        """
        return self.client.describe_index_stats()["total_vector_count"]

    def _get_or_create_db(self):
        """Called during initialization"""
        return self.client

    def reset(self):
        """
        Resets the database. Deletes all embeddings irreversibly.
        """
        # Delete all data from the database
        pinecone.delete_index(self.index_name)
        self._setup_pinecone_index()

    # Pinecone only allows alphanumeric characters and "-" in the index name
    def _get_index_name(self) -> str:
        """Get the Pinecone index for a collection

        :return: Pinecone index
        :rtype: str
        """
        return f"{self.config.collection_name}-{self.config.dimension}".lower().replace("_", "-")