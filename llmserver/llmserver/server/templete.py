# ruff: noqa: E501
qwen3_reranker_template = """<|im_start|>system
Judge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>
<|im_start|>user
<Instruct>: {{ messages | selectattr("role", "eq", "system") | map(attribute="content") | first | default("Given a web search query, retrieve relevant passages that answer the query") }}
<Query>: {{ messages | selectattr("role", "eq", "query") | map(attribute="content") | first }}
<Document>: {{ messages | selectattr("role", "eq", "document") | map(attribute="content") | first }}<|im_end|>
<|im_start|>assistant
<think>

</think>
"""

qwen3_vl_reranker_template = """<|im_start|>system
Judge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>
<|im_start|>user
<Instruct>: {{
    messages
    | selectattr("role", "eq", "system")
    | map(attribute="content")
    | first
    | default("Given a search query, retrieve relevant candidates that answer the query.")
}}<Query>:{{
    messages
    | selectattr("role", "eq", "query")
    | map(attribute="content")
    | first
}}
<Document>:{{
    messages
    | selectattr("role", "eq", "document")
    | map(attribute="content")
    | first
}}<|im_end|>
<|im_start|>assistant
"""

bge_reranker_v2_gemma_template = """A: {{ (messages | selectattr("role", "eq", "query") | first).content }}
B: {{ (messages | selectattr("role", "eq", "document") | first).content }}
Given a query A and a passage B, determine whether the passage contains an answer to the query by providing a prediction of either 'Yes' or 'No'."""

mxbai_rerank_v2_template = """<|im_start|>system
You are Qwen, created by Alibaba Cloud. You are a helpful assistant.<|im_end|>
<|im_start|>user
query: {{ (messages | selectattr("role", "eq", "query") | first).content }}
document: {{ (messages | selectattr("role", "eq", "document") | first).content }}
You are a search relevance expert who evaluates how well documents match search queries. For each query-document pair, carefully analyze the semantic relationship between them, then provide your binary relevance judgment (0 for not relevant, 1 for relevant).
Relevance:<|im_end|>
<|im_start|>assistant

"""

nemotron_rerank_template = """question:{{ (messages | selectattr("role", "eq", "query") | first).content }}

 passage:{{ (messages | selectattr("role", "eq", "document") | first).content }}"""


def get_template(model):
    if "qwen3-reranker" in model.lower():
        return qwen3_reranker_template
    if "qwen3-vl-reranker" in model.lower():
        return qwen3_vl_reranker_template
    if "bge-reranker-v2-gemma" in model.lower():
        return bge_reranker_v2_gemma_template
    if "mxbai-rerank-v2" in model.lower():
        return mxbai_rerank_v2_template
    if "nemotron-rerank" in model.lower():
        return nemotron_rerank_template
    return None
